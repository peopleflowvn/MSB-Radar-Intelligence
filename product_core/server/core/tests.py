# -*- coding: utf-8 -*-
"""Kiểm thử Hub Phase 3.

Trọng tâm: hợp đồng API phải khớp CHÍNH XÁC với client Edge đã viết ở Phase 2.
Hai bên được viết cách nhau, nên đây là chỗ duy nhất phát hiện lệch giao thức
trước khi nó thành lỗi lúc demo.
"""
import hashlib
import json

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from people.models import Person

from . import documents
from .models import Edge, EdgeApiKey, SourceRecord, hash_api_key
from .serializers import content_hash, promote_columns


def _record(cv_id="1", **overrides):
    payload = {
        "entity_type": "source_record",
        "entity_key": f"topcv|ta@msb.com.vn|{cv_id}",
        "edge_id": "edge-abc",
        "source": "topcv", "account": "ta@msb.com.vn", "cv_id": cv_id,
        "fullname": "Nguyễn Văn A", "email": "a@example.com", "phone": "0901234567",
        "position": "Data Analyst",
        "idempotency_key": "idem-" + cv_id,
    }
    payload.update(overrides)
    return payload


class EdgeApiKeyModelTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy phòng TA")

    def test_khoa_tho_khong_duoc_luu(self):
        record, raw = EdgeApiKey.issue(self.edge)
        self.assertNotIn(raw, json.dumps(
            {"hash": record.key_hash, "prefix": record.prefix}))
        self.assertEqual(record.key_hash, hash_api_key(raw))

    def test_moi_lan_cap_ra_khoa_khac_nhau(self):
        _, a = EdgeApiKey.issue(self.edge)
        _, b = EdgeApiKey.issue(self.edge)
        self.assertNotEqual(a, b)

    def test_thu_hoi_la_thao_tac_mot_chieu(self):
        record, _ = EdgeApiKey.issue(self.edge)
        record.revoke()
        first = record.revoked_at
        record.revoke()
        self.assertEqual(record.revoked_at, first)


class AuthTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy phòng TA")
        self.key_record, self.raw_key = EdgeApiKey.issue(self.edge)
        self.url = reverse("edge-health")

    def _get(self, key=None, **extra):
        headers = {}
        if key is not None:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {key}"
        headers.update(extra)
        return self.client.get(self.url, **headers)

    def test_khoa_hop_le_thi_qua(self):
        response = self._get(self.raw_key)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_khong_co_khoa_thi_401(self):
        self.assertEqual(self._get().status_code, 401)

    def test_khoa_sai_thi_401(self):
        self.assertEqual(self._get("khoa-bia-dat").status_code, 401)

    def test_khoa_da_thu_hoi_thi_401(self):
        self.key_record.revoke()
        self.assertEqual(self._get(self.raw_key).status_code, 401)

    def test_edge_bi_vo_hieu_hoa_thi_401(self):
        self.edge.is_active = False
        self.edge.save()
        self.assertEqual(self._get(self.raw_key).status_code, 401)

    def test_khoa_sai_va_khoa_thu_hoi_bao_cung_mot_thong_diep(self):
        """Đừng cho bên gọi biết khoá của họ từng tồn tại."""
        sai = self._get("khoa-bia-dat").json()["detail"]
        self.key_record.revoke()
        thu_hoi = self._get(self.raw_key).json()["detail"]
        self.assertEqual(sai, thu_hoi)

    def test_last_used_duoc_ghi_nhan(self):
        self.assertIsNone(self.key_record.last_used_at)
        self._get(self.raw_key)
        self.key_record.refresh_from_db()
        self.assertIsNotNone(self.key_record.last_used_at)

    def test_liveness_khong_can_xac_thuc(self):
        response = self.client.get(reverse("liveness"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])


class RegisterTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy phòng TA")
        _, self.raw_key = EdgeApiKey.issue(self.edge)
        self.url = reverse("edge-register")

    def _post(self, body, key=None):
        return self.client.post(
            self.url, data=json.dumps(body), content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {key or self.raw_key}")

    def test_dang_ky_lan_dau_gan_edge_id(self):
        response = self._post({"edge_id": "abc123", "hostname": "PC-TA-01",
                               "app_version": "3.0.0"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "accepted")
        self.edge.refresh_from_db()
        self.assertEqual(self.edge.edge_id, "abc123")
        self.assertEqual(self.edge.hostname, "PC-TA-01")
        self.assertIsNotNone(self.edge.registered_at)

    def test_dang_ky_lai_la_idempotent(self):
        self._post({"edge_id": "abc123"})
        response = self._post({"edge_id": "abc123", "hostname": "PC-DOI-TEN"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "duplicate")
        self.edge.refresh_from_db()
        self.assertEqual(self.edge.hostname, "PC-DOI-TEN")

    def test_dung_lai_khoa_tren_may_khac_bi_tu_choi(self):
        """Khoá bị chép sang máy thứ hai không được âm thầm cướp danh tính."""
        self._post({"edge_id": "abc123"})
        response = self._post({"edge_id": "may-khac-456"})
        self.assertEqual(response.status_code, 409)
        self.edge.refresh_from_db()
        self.assertEqual(self.edge.edge_id, "abc123")

    def test_edge_id_da_thuoc_ve_edge_khac_thi_409(self):
        khac = Edge.objects.create(label="Máy khác", edge_id="abc123")
        self.assertTrue(khac.pk)
        response = self._post({"edge_id": "abc123"})
        self.assertEqual(response.status_code, 409)

    def test_thieu_edge_id_thi_400(self):
        self.assertEqual(self._post({}).status_code, 400)
        self.assertEqual(self._post({"edge_id": "   "}).status_code, 400)


class EdgeDataReportTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy phòng TA")
        _, self.raw_key = EdgeApiKey.issue(self.edge)

    def test_only_persists_bounded_numeric_counts(self):
        response = self.client.post(
            reverse("edge-data-report"),
            data=json.dumps({"candidates": {"total": 1200, "name": "PII"},
                             "documents": {"done": 900},
                             "outbox": {"failed": -1, "pending": 3},
                             "db_schema_version": "8"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_key}")
        self.assertEqual(response.status_code, 200)
        self.edge.refresh_from_db()
        self.assertEqual(self.edge.data_report["candidates"], {"total": 1200})
        self.assertEqual(self.edge.data_report["outbox"], {"pending": 3})
        self.assertIsNotNone(self.edge.data_reported_at)

class SyncTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy phòng TA", edge_id="edge-abc")
        _, self.raw_key = EdgeApiKey.issue(self.edge)
        self.url = reverse("edge-sync")

    def _push(self, records, key=None):
        return self.client.post(
            self.url,
            data=json.dumps({"edge_id": "edge-abc", "records": records}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {key or self.raw_key}",
            HTTP_X_EDGE_ID="edge-abc")

    # ---------- hợp đồng với client Edge ----------

    def test_tra_ket_qua_theo_tung_entity_key(self):
        """Đây là điều runner.push_once() của Edge dựa vào."""
        response = self._push([_record("1"), _record("2")])
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual({r["entity_key"] for r in results},
                         {"topcv|ta@msb.com.vn|1", "topcv|ta@msb.com.vn|2"})
        for row in results:
            self.assertEqual(row["status"], "accepted")
            self.assertTrue(row["id"])

    def test_trang_thai_nam_trong_tap_edge_hieu_duoc(self):
        hieu_duoc = {"accepted", "duplicate", "updated", "retry", "conflict", "rejected"}
        results = self._push([_record("1")]).json()["results"]
        self.assertIn(results[0]["status"], hieu_duoc)

    def test_lo_rong_van_tra_200(self):
        response = self._push([])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    # ---------- khử trùng lặp ----------

    def test_gui_lai_cung_noi_dung_la_duplicate(self):
        self._push([_record("1")])
        results = self._push([_record("1")]).json()["results"]
        self.assertEqual(results[0]["status"], "duplicate")
        self.assertEqual(SourceRecord.objects.count(), 1)

    def test_gui_noi_dung_moi_la_updated(self):
        self._push([_record("1")])
        results = self._push([_record("1", phone="0999888777")]).json()["results"]
        self.assertEqual(results[0]["status"], "updated")
        self.assertEqual(SourceRecord.objects.count(), 1)
        row = SourceRecord.objects.get()
        self.assertEqual(row.phone, "0999888777")
        self.assertEqual(row.revision, 2)

    def test_doi_idempotency_key_khong_lam_ban_ghi_thanh_moi(self):
        """Hub tự tính hash nội dung, không tin hash/khoá do Edge cung cấp."""
        self._push([_record("1", idempotency_key="lan-1")])
        results = self._push([_record("1", idempotency_key="lan-2")]).json()["results"]
        self.assertEqual(results[0]["status"], "duplicate")

    def test_hai_edge_khac_nhau_giu_ban_ghi_rieng(self):
        edge2 = Edge.objects.create(label="Máy khác", edge_id="edge-xyz")
        _, key2 = EdgeApiKey.issue(edge2)
        self._push([_record("1")])
        self._push([_record("1")], key=key2)
        self.assertEqual(SourceRecord.objects.count(), 2)

    def test_cap_nhat_dat_lai_trang_thai_phan_giai(self):
        """Nội dung đổi thì kết quả phân giải cũ không còn đáng tin.

        Dùng bản ghi KHÔNG có định danh mạnh để quan sát được việc đặt lại
        trạng thái: bản ghi có email/điện thoại sẽ được phân giải lại ngay trong
        cùng yêu cầu, nên không thấy được trạng thái trung gian.
        """
        self._push([_record("1", email="", phone="")])
        row = SourceRecord.objects.get()
        row.status = SourceRecord.STATUS_RESOLVED
        row.save()

        self._push([_record("1", email="", phone="", fullname="Tên Đã Sửa")])
        row.refresh_from_db()
        self.assertEqual(row.status, SourceRecord.STATUS_PENDING)

    def test_ban_ghi_duoc_worker_phan_giai_sau_khi_hub_xac_nhan(self):
        from people.models import Person
        from people.ingest import resolve_pending

        self._push([_record("1")])
        row = SourceRecord.objects.get()
        self.assertEqual(row.status, SourceRecord.STATUS_PENDING)
        resolve_pending()
        row.refresh_from_db()
        self.assertEqual(row.status, SourceRecord.STATUS_RESOLVED)
        self.assertIsNotNone(row.person)
        self.assertEqual(Person.objects.count(), 1)

    def test_noi_dung_sua_duoc_phan_giai_lai_chu_khong_de_cu(self):
        from people.ingest import resolve_pending

        self._push([_record("1")])
        resolve_pending()
        self._push([_record("1", phone="0912345678")])
        resolve_pending()
        row = SourceRecord.objects.get()
        self.assertEqual(row.revision, 2)
        self.assertEqual(row.status, SourceRecord.STATUS_RESOLVED)
        self.assertIn("+84912345678",
                      row.person.identities.values_list("value", flat=True))

    # ---------- Hub không tin Edge ----------

    def test_loai_thuc_the_la_bi_TU_CHOI_RIENG_khong_keo_ca_lo(self):
        """Đổi hợp đồng: bản ghi hỏng nhận `rejected` riêng, không làm 400 cả lô.

        Bản cũ kiểm cả lô một lượt, nên một `entity_type` lạ — ví dụ từ một Edge
        mới hơn Hub — làm HTTP 400 cho toàn bộ 50 bản ghi. Edge coi 400 là lỗi
        vĩnh viễn và đánh dấu cả lô `failed`, không backoff, không đếm lần thử.
        Điều đó mâu thuẫn với `docs/SYNC.md` mục 5.
        """
        response = self._push([_record("1", entity_type="linh_tinh")])
        self.assertEqual(response.status_code, 200)
        row = response.json()["results"][0]
        self.assertEqual(row["status"], "rejected")
        self.assertTrue(row["detail"])

    def test_thieu_entity_key_bi_tu_choi_rieng(self):
        response = self._push([_record("1", entity_key="")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["status"], "rejected")

    def test_ban_ghi_hong_KHONG_lam_mat_ban_ghi_tot_cung_lo(self):
        """Đây là lý do cả thay đổi này tồn tại."""
        response = self._push([
            _record("1", entity_type="linh_tinh"),
            _record("2"),
        ])
        self.assertEqual(response.status_code, 200)
        by_status = {row["status"] for row in response.json()["results"]}
        self.assertIn("rejected", by_status)
        self.assertIn("accepted", by_status)
        self.assertEqual(SourceRecord.objects.count(), 1)

    def test_danh_sach_ban_ghi_thieu_thi_400(self):
        response = self.client.post(
            self.url, data=json.dumps({"edge_id": "edge-abc"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_key}",
            HTTP_X_EDGE_ID="edge-abc")
        self.assertEqual(response.status_code, 400)

    def test_gia_tri_qua_dai_bi_cat_chu_khong_lam_hong_ban_ghi(self):
        response = self._push([_record("1", fullname="A" * 500)])
        self.assertEqual(response.status_code, 200)
        row = SourceRecord.objects.get()
        self.assertEqual(len(row.fullname), 200)
        self.assertEqual(len(row.payload["fullname"]), 500,
                         "payload đầy đủ phải được giữ nguyên vẹn")

    def test_truong_la_van_duoc_giu_trong_payload(self):
        """Edge bản mới thêm trường không được buộc Hub phát hành lại."""
        self._push([_record("1", truong_tuong_lai="giá trị nào đó")])
        self.assertEqual(SourceRecord.objects.get().payload["truong_tuong_lai"],
                         "giá trị nào đó")

    @override_settings(EDGE_SYNC_MAX_BATCH=3)
    def test_lo_qua_lon_bi_tu_choi(self):
        response = self._push([_record(str(i)) for i in range(5)])
        self.assertEqual(response.status_code, 413)
        self.assertEqual(SourceRecord.objects.count(), 0)

    def test_khong_xac_thuc_thi_khong_luu_gi(self):
        response = self.client.post(
            self.url, data=json.dumps({"records": [_record("1")]}),
            content_type="application/json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(SourceRecord.objects.count(), 0)

    def test_ghi_nhan_lan_lien_lac_cuoi(self):
        self.assertIsNone(self.edge.last_seen_at)
        self._push([_record("1")])
        self.edge.refresh_from_db()
        self.assertIsNotNone(self.edge.last_seen_at)


class ContentHashTest(TestCase):
    def test_edge_id_khong_tham_gia_hash(self):
        """Cùng lượt ứng tuyển gửi từ hai Edge không được thành hai nội dung khác."""
        a = content_hash({"a": 1, "edge_id": "e1"})
        b = content_hash({"a": 1, "edge_id": "e2"})
        self.assertEqual(a, b)

    def test_idempotency_key_khong_tham_gia_hash(self):
        self.assertEqual(content_hash({"a": 1, "idempotency_key": "x"}),
                         content_hash({"a": 1, "idempotency_key": "y"}))

    def test_thu_tu_khoa_khong_anh_huong(self):
        self.assertEqual(content_hash({"a": 1, "b": 2}), content_hash({"b": 2, "a": 1}))

    def test_doi_gia_tri_thi_doi_hash(self):
        self.assertNotEqual(content_hash({"a": 1}), content_hash({"a": 2}))

    def test_promote_columns_luon_tra_du_khoa(self):
        columns = promote_columns({})
        self.assertEqual(set(columns), {"source", "account", "fullname", "email",
                                        "phone", "position"})
        self.assertTrue(all(v == "" for v in columns.values()))

    def test_promote_columns_xu_ly_none(self):
        self.assertEqual(promote_columns({"fullname": None})["fullname"], "")


class HubUiTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy phòng TA", edge_id="edge-abc")
        _, raw = EdgeApiKey.issue(self.edge)
        self.client.post(reverse("edge-sync"),
                         data=json.dumps({"records": [_record("1"), _record("2")]}),
                         content_type="application/json",
                         HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.user = User.objects.create_user("nhanvien", password="mat-khau-rat-dai-123")
        from accounts import roles
        roles.ensure_groups()
        self.user.groups.add(Group.objects.get(name=roles.EDGE_OPERATOR))

    def test_can_dang_nhap(self):
        for name in ("hub-edges", "hub-source-records", "hub-summary"):
            self.assertIn(self.client.get(reverse(name)).status_code, (401, 403),
                          f"{name} phải chặn người chưa đăng nhập")

    def test_khoa_edge_khong_mo_duoc_endpoint_quan_tri(self):
        """Khoá máy không được dùng thay cho quyền của người."""
        _, raw = EdgeApiKey.issue(self.edge)
        response = self.client.get(reverse("hub-edges"), HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.assertIn(response.status_code, (401, 403))

    def test_danh_sach_edge(self):
        self.client.force_login(self.user)
        rows = self.client.get(reverse("hub-edges")).json()["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["record_count"], 2)

    def test_tim_kiem_ban_ghi(self):
        self.client.force_login(self.user)
        body = self.client.get(reverse("hub-source-records"), {"search": "Data"}).json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(self.client.get(reverse("hub-source-records"),
                                         {"search": "khong-co-gi"}).json()["count"], 0)

    def test_tong_hop(self):
        self.client.force_login(self.user)
        body = self.client.get(reverse("hub-summary")).json()
        self.assertEqual(body["edges"], 1)
        self.assertEqual(body["source_records"], 2)
        # Hai bản ghi dùng chung email/điện thoại nên phân giải về một Person
        # ngay khi nhận; không còn gì nằm chờ.
        self.assertEqual(body["pending_resolution"], 0)


class SharedContentTest(TestCase):
    """Hai Person cùng một file CV — kho đánh địa chỉ theo nội dung phải tận dụng.

    Không có bước này thì mất file thật sự: Edge khử trùng lặp trong phạm vi
    một lô theo sha256, nên khi hai lượt ứng tuyển cùng file thuộc hai Person
    chưa được gộp — chuyện thường, một người khớp bằng email ở nguồn này và
    bằng điện thoại ở nguồn kia — Edge chỉ tải một lần rồi đánh dấu cả hai đã
    gửi. Person còn lại giữ `storage_key` rỗng vĩnh viễn.
    """

    def setUp(self):
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e-share")
        # Mã băm THẬT của nội dung dùng bên dưới: Hub tự băm lại và từ chối
        # nếu lệch (`documents.store_file`), nên không dùng digest giả được.
        self.content = b"noi dung cv"
        self.digest = hashlib.sha256(self.content).hexdigest()
        self.a = Person.objects.create(display_name="Nguyễn Văn An")
        self.b = Person.objects.create(display_name="Nguyen Van An")

    def _record(self, person, key):
        return SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record", entity_key=key,
            content_hash=key, person=person,
            status=SourceRecord.STATUS_RESOLVED)

    def _payload(self):
        return {"sha256": self.digest, "filename": "cv.pdf", "file_size": 10}

    def test_noi_dung_da_co_thi_KHONG_can_tai_len_lai(self):
        first = self._record(self.a, "topcv|a|1")
        document, needs_file = documents.ingest_metadata(first, self._payload())
        self.assertTrue(needs_file)

        documents.store_file(self.a, self.digest, self.content, "cv.pdf")

        second = self._record(self.b, "vietnamworks|a|2")
        other, needs_again = documents.ingest_metadata(second, self._payload())
        self.assertFalse(needs_again,
                         "Nội dung đã nằm trong kho — bắt Edge tải lại lần nữa "
                         "là lúc file bị mất nếu Edge đã khử trùng lặp")
        self.assertTrue(other.storage_key)
        document.refresh_from_db()   # store_file cập nhật CSDL, không cập nhật bản trong bộ nhớ
        self.assertEqual(other.storage_key, document.storage_key)

    def test_noi_dung_chua_co_thi_van_yeu_cau_tai_len(self):
        first = self._record(self.a, "topcv|a|1")
        _document, needs_file = documents.ingest_metadata(first, self._payload())
        self.assertTrue(needs_file)

        second = self._record(self.b, "vietnamworks|a|2")
        _other, needs_again = documents.ingest_metadata(second, self._payload())
        self.assertTrue(needs_again,
                        "Chưa ai tải nội dung lên thì không được báo là đã có")
