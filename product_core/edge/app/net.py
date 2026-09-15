# -*- coding: utf-8 -*-
"""Chính sách mạng dùng chung: proxy công ty và chứng chỉ TLS.

## Vì sao module này tồn tại

Mỗi provider và cả `sync/client.py` đều tự tạo `requests.Session()` riêng mà
không đụng gì tới proxy hay chứng chỉ. Hệ quả trên mạng doanh nghiệp:

* `requests` chỉ đọc proxy từ **biến môi trường** (`HTTP_PROXY`/`HTTPS_PROXY`),
  KHÔNG đọc cấu hình proxy của Windows. Máy văn phòng thường đặt proxy qua
  Internet Settings / GPO nên đường tải nhanh và đồng bộ Hub bị timeout.
* Proxy soi SSL ký lại chứng chỉ bằng CA nội bộ. `requests` xác thực theo bộ
  `certifi` nên gần như mọi lời gọi `https` thất bại với `SSLError`, trừ chỗ
  từng vá riêng bằng `verify=False`.

Module này gom một chỗ:

* `install_windows_ca()` — gộp CA gốc của Windows (nơi CA nội bộ do IT đẩy vào
  máy nằm sẵn) với bộ `certifi` thành một file .pem và trỏ `REQUESTS_CA_BUNDLE`
  vào đó. Gọi MỘT lần lúc khởi động. Không cần thư viện ngoài, chạy trên Python 3.9.
* `resolve_proxies(cfg)` — proxy hiệu lực: cấu hình trong app > proxy Windows >
  biến môi trường. `""` = tự dò, `"off"` = ép đi thẳng.
* `verify_for(cfg)` — giá trị `verify` dùng chung: `True` / đường dẫn CA / `False`.
* `apply(session, cfg)` — gắn cả hai vào một `requests.Session`.
* `request_kwargs(cfg)` — dict `proxies`/`verify` cho lời gọi `requests` lẻ.
"""
import os
import urllib.request
from pathlib import Path

_DIRECT = object()          # đánh dấu "ép không dùng proxy"
_ca_bundle_state = None       # None = chưa dựng, "" = không dựng được, str = đường dẫn

#: OID "TLS Web Server Authentication" - chỉ lấy CA còn hiệu lực cho mục đích này.
_SERVER_AUTH_OID = "1.3.6.1.5.5.7.3.1"


def _windows_ca_pems():
    import ssl
    pems = []
    for store in ("ROOT", "CA"):
        try:
            entries = ssl.enum_certificates(store)
        except Exception:       # noqa: BLE001 - không phải Windows / API thiếu
            continue
        for der, encoding, trust in entries:
            if encoding != "x509_asn":
                continue
            if trust is False:                      # bị đánh dấu KHÔNG tin
                continue
            if isinstance(trust, (set, frozenset, tuple, list)) and _SERVER_AUTH_OID not in trust:
                continue
            try:
                pems.append(ssl.DER_cert_to_PEM_cert(der))
            except Exception:   # noqa: BLE001
                pass
    return pems


def _ca_bundle_dir():
    try:
        from .state_paths import local_state_dir
        folder = local_state_dir()
    except Exception:           # noqa: BLE001
        folder = os.path.join(os.path.expanduser("~"), ".msbradar")
    os.makedirs(folder, exist_ok=True)
    return folder


def windows_ca_bundle():
    """Đường dẫn file .pem gộp `certifi` + CA gốc Windows. `None` nếu không dựng
    được (không phải Windows, hoặc lỗi)."""
    global _ca_bundle_state
    if _ca_bundle_state is not None:
        return _ca_bundle_state or None
    if os.name != "nt":
        _ca_bundle_state = ""
        return None
    try:
        pems = _windows_ca_pems()
        if not pems:
            _ca_bundle_state = ""
            return None
        try:
            import certifi
            base = Path(certifi.where()).read_text(encoding="utf-8")
        except Exception:       # noqa: BLE001
            base = ""
        seen = set()
        merged = [base] if base else []
        for pem in pems:
            key = pem.strip()
            if key and key not in seen:
                seen.add(key)
                merged.append(pem.strip())
        out = os.path.join(_ca_bundle_dir(), "ca_bundle_windows.pem")
        Path(out).write_text("\n".join(merged) + "\n", encoding="utf-8")
        _ca_bundle_state = out
        return out
    except Exception:           # noqa: BLE001
        _ca_bundle_state = ""
        return None


def install_windows_ca():
    """Dựng bundle CA của Windows và trỏ biến môi trường vào đó (nếu chưa có).
    Gọi một lần lúc khởi động, trước mọi lời gọi HTTPS."""
    bundle = windows_ca_bundle()
    if bundle:
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
        os.environ.setdefault("SSL_CERT_FILE", bundle)
    return bool(bundle)


# Tên cũ giữ lại cho gọn nếu chỗ khác đã gọi.
install_truststore = install_windows_ca


def system_proxies():
    """Proxy do hệ điều hành / biến môi trường khai báo.

    `urllib.request.getproxies()` = biến môi trường, và trên Windows còn đọc
    `HKCU\\...\\Internet Settings` (ProxyEnable/ProxyServer). PAC/auto-config
    URL thì không giải được ở đây - trường hợp đó người dùng nhập tay proxy_url.
    """
    proxies = urllib.request.getproxies() or {}
    return {scheme: url for scheme, url in proxies.items() if url}


def resolve_proxies(cfg):
    """Trả về dict proxies cho `requests`, hoặc `None` (không đặt gì), hoặc
    `_DIRECT` (ép đi thẳng, kể cả khi có biến môi trường)."""
    raw = str(getattr(cfg, "proxy_url", "") or "").strip()
    if not raw:
        found = system_proxies()
        return found or None
    if raw.lower() in ("off", "none", "direct", "no"):
        return _DIRECT
    if "://" not in raw:
        raw = "http://" + raw
    return {"http": raw, "https": raw}


def verify_for(cfg):
    """Giá trị `verify` dùng chung cho mọi lời gọi HTTPS."""
    bundle = str(getattr(cfg, "ssl_ca_bundle", "") or "").strip()
    if bundle and os.path.isfile(bundle):
        return bundle
    if getattr(cfg, "ssl_verify", True) is False:
        return False
    env_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or ""
    if env_bundle and os.path.isfile(env_bundle):
        return env_bundle
    win_bundle = windows_ca_bundle()
    if win_bundle:
        return win_bundle
    return True


def apply(session, cfg):
    """Gắn proxy + verify vào một `requests.Session` rồi trả lại chính nó."""
    proxies = resolve_proxies(cfg)
    if proxies is _DIRECT:
        session.trust_env = False
        session.proxies = {}
    elif proxies:
        session.proxies = dict(proxies)
    session.verify = verify_for(cfg)
    return session


def request_kwargs(cfg):
    """kwargs `proxies`/`verify` cho lời gọi `requests.get/post` lẻ (không Session)."""
    kwargs = {"verify": verify_for(cfg)}
    proxies = resolve_proxies(cfg)
    if proxies is _DIRECT:
        kwargs["proxies"] = {"http": None, "https": None}
    elif proxies:
        kwargs["proxies"] = dict(proxies)
    return kwargs


def chrome_proxy_arg(cfg):
    """Nếu người dùng nhập proxy_url tường minh, trả về cờ `--proxy-server=...`
    để truyền cho Chrome (Chrome không đọc biến môi trường như `requests`).
    `""`/`"off"` -> không thêm cờ nào (Chrome tự dùng proxy hệ thống)."""
    raw = str(getattr(cfg, "proxy_url", "") or "").strip()
    if not raw or raw.lower() in ("off", "none", "direct", "no"):
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    return f"--proxy-server={raw}"
