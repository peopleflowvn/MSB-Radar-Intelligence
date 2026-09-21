# -*- coding: utf-8 -*-
"""Client HTTP gọi MSB Radar Hub.

Chưa có Hub nào tồn tại ở Phase 2. Vì vậy client được thiết kế để kiểm thử được
hoàn toàn không cần mạng: mọi lời gọi đi qua `transport`, mặc định là requests,
còn test thì tiêm một hàm giả.

Phân loại lỗi là phần quan trọng nhất ở đây. Gửi lại một yêu cầu sai định dạng
tám lần chỉ tổ phí thời gian và làm rác nhật ký; ngược lại bỏ cuộc khi Hub tạm
thời sập sẽ làm mất dữ liệu chưa đồng bộ. Do đó:

    HubUnavailable   lỗi tạm thời  -> đáng thử lại (mạng, 5xx, 429, timeout)
    HubAuthError     sai thông tin -> KHÔNG thử lại cho tới khi người dùng sửa
    HubError         lỗi vĩnh viễn -> KHÔNG thử lại (4xx do dữ liệu sai)
"""
import json

# Lô metadata có thể phải đi qua proxy/VPN doanh nghiệp và Hub còn phải ghi bền
# vững từng bản ghi. 30 giây quá sát: production đã ghi nhận Hub lưu được việc
# nhưng Edge hết thời gian chờ trước khi nhận phản hồi, rồi gửi lại cả lô. Upload
# file vẫn có ngưỡng riêng ở dưới.
DEFAULT_TIMEOUT = 90
#: Upload file CV nặng hơn hẳn và hay nghẽn qua proxy công ty bị bóp băng thông;
#: cho nó cửa sổ rộng hơn để không bị hủy oan rồi thử lại vô ích.
DEFAULT_UPLOAD_TIMEOUT = 120
SYNC_ENDPOINT = "/api/v1/edge/sync/"
HEALTH_ENDPOINT = "/api/v1/edge/health/"
REGISTER_ENDPOINT = "/api/v1/edge/register/"
DATA_REPORT_ENDPOINT = "/api/v1/edge/data-report/"
DOCUMENT_ENDPOINT = "/api/v1/edge/documents/"


class HubError(Exception):
    """Hub từ chối yêu cầu vì lý do sẽ không tự hết. Không thử lại."""
    retryable = False


class HubAuthError(HubError):
    """Thiếu hoặc sai API key. Chỉ người dùng sửa được."""
    retryable = False


class HubUnavailable(HubError):
    """Sự cố tạm thời. Đáng thử lại sau."""
    retryable = True


class HubClient:
    """Gọi Hub. Một instance dùng lại được cho nhiều lượt gửi."""

    def __init__(self, base_url, api_key="", edge_id="", timeout=DEFAULT_TIMEOUT,
                 transport=None, binary_transport=None, proxies=None, verify=True,
                 upload_timeout=DEFAULT_UPLOAD_TIMEOUT):
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.edge_id = str(edge_id or "")
        self.timeout = timeout
        self.upload_timeout = upload_timeout or timeout
        # Proxy + xác thực TLS cho mạng doanh nghiệp; xem app/net.py.
        self._proxies = proxies or None
        self._verify = verify

        def _bound_transport(method, url, headers, body, timeout):
            return _requests_transport(method, url, headers, body, timeout,
                                       proxies=self._proxies, verify=self._verify)

        def _bound_binary(url, headers, data, timeout):
            return _requests_binary_transport(url, headers, data, timeout,
                                              proxies=self._proxies, verify=self._verify)

        self._transport = transport or _bound_transport
        self._binary_transport = binary_transport or _bound_binary

    # ---------------- công khai ----------------

    def configured(self):
        return bool(self.base_url and self.api_key)

    def health(self):
        """Kiểm tra Hub có sống và API key có hợp lệ không. Dùng cho nút Kiểm tra kết nối."""
        return self._call("GET", HEALTH_ENDPOINT)

    def register_edge(self, hostname="", app_version=""):
        """Khai báo Edge này với Hub. Idempotent theo edge_id."""
        return self._call("POST", REGISTER_ENDPOINT, {
            "edge_id": self.edge_id,
            "hostname": hostname,
            "app_version": app_version,
        })

    def push_batch(self, records):
        """Gửi một lô bản ghi. Trả dict {(entity_type, entity_key): kết quả}.

        Hub trả kết quả cho TỪNG bản ghi thay vì một trạng thái chung cho cả lô:
        một bản ghi hỏng không được kéo theo cả lô phải gửi lại, còn không thì
        một hàng lỗi vĩnh viễn sẽ chặn hàng đợi mãi mãi.

        Khoá là CẶP (entity_type, entity_key), không phải riêng entity_key: một
        file CV dùng chung entity_key với lượt ứng tuyển mang nó, nên khoá bằng
        entity_key thôi thì hai loại sẽ ghi đè kết quả của nhau.
        """
        if not records:
            return {}
        response = self._call("POST", SYNC_ENDPOINT, {
            "edge_id": self.edge_id,
            "records": list(records),
        })
        results = {}
        for row in (response.get("results") or []):
            key = str(row.get("entity_key") or "")
            if not key:
                continue
            # Hub cũ chưa gửi entity_type — coi như bản ghi nguồn để không vỡ.
            kind = str(row.get("entity_type") or "source_record")
            results[(kind, key)] = row
        return results

    def report_data(self, report):
        """Gửi số đếm đối soát; tuyệt đối không chứa dữ liệu ứng viên."""
        return self._call("POST", DATA_REPORT_ENDPOINT, dict(report or {}))

    def upload_document(self, sha256, entity_key, data, filename=""):
        """Tải nội dung file lên (pha 2). Chỉ gọi khi Hub báo `needs_file`.

        Gửi nhị phân thô chứ không base64 trong JSON: base64 phình thêm 33% cho
        đúng phần nặng nhất của việc đồng bộ.
        """
        if not self.base_url:
            raise HubError("Chưa cấu hình địa chỉ Hub.")
        if not self.api_key:
            raise HubAuthError("Chưa cấu hình API key của Hub.")

        from urllib.parse import quote, urlencode
        query = urlencode({"entity_key": entity_key, "filename": filename})
        url = f"{self.base_url}{DOCUMENT_ENDPOINT}{quote(str(sha256))}/?{query}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/octet-stream",
            "Content-Disposition": 'attachment; filename="cv"',
            "X-Edge-Id": self.edge_id,
        }
        try:
            status, payload = self._binary_transport(url, headers, data, self.upload_timeout)
        except HubError:
            raise
        except Exception as exc:
            raise HubUnavailable(f"Không tải được tài liệu lên Hub: {exc}") from exc
        return self._interpret(status, payload)

    # ---------------- nội bộ ----------------

    def _call(self, method, path, body=None):
        if not self.base_url:
            raise HubError("Chưa cấu hình địa chỉ Hub.")
        if not self.api_key:
            raise HubAuthError("Chưa cấu hình API key của Hub.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Edge-Id": self.edge_id,
        }
        try:
            status, payload = self._transport(
                method, self.base_url + path, headers, body, self.timeout)
        except HubError:
            raise
        except Exception as exc:
            # Mọi sự cố tầng vận chuyển (DNS, timeout, kết nối bị reset) đều là
            # tạm thời. Đây là trường hợp hay gặp nhất trên máy văn phòng.
            raise HubUnavailable(f"Không kết nối được Hub: {exc}") from exc

        return self._interpret(status, payload)

    @staticmethod
    def _interpret(status, payload):
        payload = payload if isinstance(payload, dict) else {}
        if 200 <= status < 300:
            return payload

        detail = str(payload.get("detail") or payload.get("error") or "").strip()
        if status in (401, 403):
            raise HubAuthError(detail or f"Hub từ chối xác thực (HTTP {status}).")
        if status == 429:
            raise HubUnavailable(detail or "Hub đang giới hạn tốc độ (HTTP 429).")
        if status >= 500:
            raise HubUnavailable(detail or f"Hub gặp sự cố (HTTP {status}).")
        # 404 nằm ở nhánh này một cách có chủ đích: sai đường dẫn/cấu hình sẽ
        # không tự hết, thử lại chỉ phí công.
        raise HubError(detail or f"Hub từ chối yêu cầu (HTTP {status}).")


def _requests_binary_transport(url, headers, data, timeout, proxies=None, verify=True):
    """Tải nhị phân thô. Import requests ở đây để test không cần tới nó."""
    import requests

    response = requests.post(url, headers=headers, data=data, timeout=timeout,
                             proxies=proxies or None, verify=verify)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return response.status_code, payload


def _requests_transport(method, url, headers, body, timeout, proxies=None, verify=True):
    """Vận chuyển mặc định. Import requests ở đây để test không cần tới nó."""
    import requests

    response = requests.request(
        method, url, headers=headers, timeout=timeout,
        proxies=proxies or None, verify=verify,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return response.status_code, payload
