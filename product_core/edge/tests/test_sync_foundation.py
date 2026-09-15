# -*- coding: utf-8 -*-
"""Kiểm thử nền tảng đồng bộ Edge -> Hub (Phase 2).

Ba tính chất Master Plan mục 9 yêu cầu — idempotent, retryable, resume-able —
đều có test tương ứng ở đây. Không test nào chạm mạng: HubClient nhận transport
tiêm vào.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import Database
from app.sync.client import HubAuthError, HubClient, HubError, HubUnavailable
from app.sync.payload import (ENTITY_SOURCE_RECORD, candidate_key,
                              candidate_payload, idempotency_key, payload_hash)
from app.sync import runner


def _candidate(cv_id="1", **overrides):
    row = {
        "source": "topcv", "account": "ta@msb.com.vn", "cv_id": cv_id,
        "fullname": "Nguyễn Văn A", "email": "a@example.com", "phone": "0901234567",
        "position": "Data Analyst", "applied_ts": "2026-08-01 09:00:00",
        "dl_status": "done", "first_seen": "2026-08-01 09:00:00",
    }
    row.update(overrides)
    return row


class PayloadTest(unittest.TestCase):
    def test_entity_key_la_khoa_chinh_cua_candidates(self):
        self.assertEqual(candidate_key(_candidate("42")), "topcv|ta@msb.com.vn|42")

    def test_hash_on_dinh_giua_cac_lan_goi(self):
        row = _candidate()
        self.assertEqual(payload_hash(candidate_payload(row)),
                         payload_hash(candidate_payload(row)))

    def test_none_va_chuoi_rong_cho_cung_hash(self):
        """SQLite trả None, JSON trả '' — hai thứ đó không được sinh hash khác nhau."""
        a = candidate_payload(_candidate(note=None, city=None))
        b = candidate_payload(_candidate(note="", city=""))
        self.assertEqual(payload_hash(a), payload_hash(b))

    def test_doi_noi_dung_thi_doi_hash(self):
        base = payload_hash(candidate_payload(_candidate()))
        changed = payload_hash(candidate_payload(_candidate(phone="0909999999")))
        self.assertNotEqual(base, changed)

    def test_raw_and_versioned_extensions_participate_in_payload_hash(self):
        base = candidate_payload(_candidate(source_payload='{"id":1}'))
        changed_raw = candidate_payload(_candidate(source_payload='{"id":2}'))
        changed_ext = candidate_payload(
            _candidate(source_payload='{"id":1}'),
            extensions={"cv_parser": {"schema_version": 2,
                                       "payload": {"skills": ["SQL"]}}})
        self.assertNotEqual(payload_hash(base), payload_hash(changed_raw))
        self.assertNotEqual(payload_hash(base), payload_hash(changed_ext))

    def test_cot_ngoai_danh_sach_khong_lam_doi_hash(self):
        """updated_at đổi mỗi lần ghi; nó không được kích hoạt đồng bộ lại."""
        base = payload_hash(candidate_payload(_candidate()))
        noisy = payload_hash(candidate_payload(
            _candidate(updated_at="2026-08-19 23:59:59", detail_loaded=1, is_viewed=1)))
        self.assertEqual(base, noisy)

    def test_edge_id_khong_tham_gia_vao_hash(self):
        row = _candidate()
        self.assertEqual(payload_hash(candidate_payload(row, "edge-mot")),
                         payload_hash(candidate_payload(row, "edge-hai")))

    def test_idempotency_key_doi_khi_noi_dung_doi(self):
        a = idempotency_key("e1", ENTITY_SOURCE_RECORD, "k", "hash-a")
        b = idempotency_key("e1", ENTITY_SOURCE_RECORD, "k", "hash-b")
        self.assertNotEqual(a, b)
        self.assertEqual(a, idempotency_key("e1", ENTITY_SOURCE_RECORD, "k", "hash-a"))


class OutboxTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.db = Database(os.path.join(self.folder, "test.db"), log=lambda *a: None).open()
        self.addCleanup(self.db.close)

    def _enqueue(self, key="topcv|a|1", digest="h1"):
        return self.db.enqueue_sync(ENTITY_SOURCE_RECORD, key, digest)

    # ---------- idempotent ----------

    def test_xep_hang_lai_cung_noi_dung_la_no_op(self):
        self.assertTrue(self._enqueue())
        self.assertFalse(self._enqueue(), "cùng hash không được sinh việc mới")
        self.assertEqual(self.db.sync_stats()["total"], 1)

    def test_doi_hash_thi_xep_lai_hang(self):
        self._enqueue(digest="h1")
        self.assertTrue(self._enqueue(digest="h2"))
        self.assertEqual(self.db.sync_stats()["pending"], 1)

    def test_moi_thuc_the_chi_co_mot_hang(self):
        for digest in ("h1", "h2", "h3"):
            self._enqueue(digest=digest)
        self.assertEqual(self.db.sync_stats()["total"], 1)

    def test_khong_xep_hang_khi_thieu_khoa(self):
        self.assertFalse(self.db.enqueue_sync(ENTITY_SOURCE_RECORD, "", "h"))
        self.assertFalse(self.db.enqueue_sync("", "k", "h"))

    # ---------- claim / finish ----------

    def test_claim_danh_dau_inflight_va_tang_so_lan_thu(self):
        self._enqueue()
        batch = self.db.claim_sync_batch(10)
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]["attempts"], 0, "hàng trả về là ảnh trước khi tăng")
        stats = self.db.sync_stats()
        self.assertEqual(stats["inflight"], 1)
        self.assertEqual(stats["pending"], 0)

    def test_khong_claim_trung_mot_hang(self):
        self._enqueue()
        self.assertEqual(len(self.db.claim_sync_batch(10)), 1)
        self.assertEqual(self.db.claim_sync_batch(10), [],
                         "hàng đang inflight không được nhận lần nữa")

    def test_finish_ghi_hub_id(self):
        self._enqueue()
        row = self.db.claim_sync_batch(1)[0]
        self.db.finish_sync(row["id"], "hub-123")
        self.assertEqual(self.db.sync_stats()["synced"], 1)

    def test_da_dong_bo_thi_khong_xep_lai_neu_noi_dung_giu_nguyen(self):
        self._enqueue(digest="h1")
        row = self.db.claim_sync_batch(1)[0]
        self.db.finish_sync(row["id"], "hub-1")
        self.assertFalse(self._enqueue(digest="h1"))
        self.assertEqual(self.db.sync_stats()["synced"], 1)

    # ---------- retryable ----------

    def test_that_bai_tam_thoi_thi_hen_lai(self):
        self._enqueue()
        row = self.db.claim_sync_batch(1)[0]
        self.assertTrue(self.db.fail_sync(row["id"], "mạng lỗi", True))
        stats = self.db.sync_stats()
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["failed"], 0)

    def test_hen_lai_thi_chua_toi_han_khong_duoc_claim(self):
        self._enqueue()
        row = self.db.claim_sync_batch(1)[0]
        self.db.fail_sync(row["id"], "mạng lỗi", True)
        self.assertEqual(self.db.claim_sync_batch(10), [],
                         "phải tôn trọng next_attempt_at")

    def test_loi_vinh_vien_khong_thu_lai(self):
        self._enqueue()
        row = self.db.claim_sync_batch(1)[0]
        self.assertFalse(self.db.fail_sync(row["id"], "dữ liệu sai", False))
        self.assertEqual(self.db.sync_stats()["failed"], 1)

    def test_het_luot_thu_thi_chuyen_sang_failed(self):
        self._enqueue()
        for _ in range(Database.OUTBOX_MAX_ATTEMPTS):
            self.db._write("UPDATE sync_outbox SET status='pending',next_attempt_at=''")
            row = self.db.claim_sync_batch(1)[0]
            self.db.fail_sync(row["id"], "mạng lỗi", True)
        self.assertEqual(self.db.sync_stats()["failed"], 1)

    def test_backoff_tang_theo_cap_so_nhan_va_bi_chan_tren(self):
        first = Database.outbox_retry_delay(1)
        later = Database.outbox_retry_delay(4)
        self.assertLess(first, later)
        self.assertLessEqual(Database.outbox_retry_delay(50),
                             Database._OUTBOX_BACKOFF_CAP * 1.25 + 1)

    def test_requeue_failed_dua_ve_hang_doi(self):
        self._enqueue()
        row = self.db.claim_sync_batch(1)[0]
        self.db.fail_sync(row["id"], "dữ liệu sai", False)
        self.assertEqual(self.db.requeue_failed_sync(), 1)
        self.assertEqual(self.db.sync_stats()["pending"], 1)

    # ---------- resume-able ----------

    def test_khoi_phuc_hang_inflight_sau_khi_tat_dot_ngot(self):
        self._enqueue()
        self.db.claim_sync_batch(1)
        self.assertEqual(self.db.sync_stats()["inflight"], 1)
        self.assertEqual(self.db.recover_sync_queue(), 1)
        self.assertEqual(self.db.sync_stats()["pending"], 1)

    def test_trang_thai_song_sot_qua_lan_mo_lai(self):
        self._enqueue()
        path = self.db.path
        self.db.close()
        reopened = Database(path, log=lambda *a: None).open()
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.sync_stats()["pending"], 1)


class HubClientTest(unittest.TestCase):
    def _client(self, status, body, **kwargs):
        calls = []

        def transport(method, url, headers, payload, timeout):
            calls.append({"method": method, "url": url, "headers": headers,
                          "body": payload, "timeout": timeout})
            return status, body

        client = HubClient("https://hub.test/", "key-abc", "edge-1",
                           transport=transport, **kwargs)
        return client, calls

    def test_gui_kem_api_key_va_edge_id(self):
        client, calls = self._client(200, {"results": []})
        client.push_batch([{"entity_key": "k"}])
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer key-abc")
        self.assertEqual(calls[0]["headers"]["X-Edge-Id"], "edge-1")

    def test_bo_dau_gach_cheo_thua_o_base_url(self):
        client, calls = self._client(200, {"results": []})
        client.health()
        self.assertEqual(calls[0]["url"], "https://hub.test/api/v1/edge/health/")

    def test_ket_qua_tra_ve_theo_tung_entity_key(self):
        client, _ = self._client(200, {"results": [
            {"entity_key": "a", "entity_type": "source_record",
             "status": "accepted", "id": "1"},
            {"entity_key": "b", "entity_type": "source_record", "status": "duplicate"},
        ]})
        answers = client.push_batch([{"entity_key": "a"}, {"entity_key": "b"}])
        self.assertEqual(answers[("source_record", "a")]["status"], "accepted")
        self.assertEqual(answers[("source_record", "b")]["status"], "duplicate")

    def test_tai_lieu_va_ung_tuyen_cung_khoa_khong_de_len_nhau(self):
        """File CV dùng chung entity_key với lượt ứng tuyển mang nó."""
        client, _ = self._client(200, {"results": [
            {"entity_key": "k", "entity_type": "source_record", "status": "accepted"},
            {"entity_key": "k", "entity_type": "document", "status": "accepted",
             "needs_file": True},
        ]})
        answers = client.push_batch([{"entity_key": "k"}])
        self.assertEqual(len(answers), 2)
        self.assertTrue(answers[("document", "k")]["needs_file"])
        self.assertNotIn("needs_file", answers[("source_record", "k")])

    def test_hub_cu_khong_gui_entity_type_van_hieu_duoc(self):
        client, _ = self._client(200, {"results": [
            {"entity_key": "a", "status": "accepted"}]})
        answers = client.push_batch([{"entity_key": "a"}])
        self.assertIn(("source_record", "a"), answers)

    def test_lo_rong_khong_goi_mang(self):
        client, calls = self._client(200, {})
        self.assertEqual(client.push_batch([]), {})
        self.assertEqual(calls, [])

    def test_401_la_loi_xac_thuc_khong_thu_lai(self):
        client, _ = self._client(401, {"detail": "sai key"})
        with self.assertRaises(HubAuthError) as ctx:
            client.health()
        self.assertFalse(ctx.exception.retryable)

    def test_500_dang_thu_lai(self):
        client, _ = self._client(500, {})
        with self.assertRaises(HubUnavailable) as ctx:
            client.health()
        self.assertTrue(ctx.exception.retryable)

    def test_429_dang_thu_lai(self):
        client, _ = self._client(429, {})
        with self.assertRaises(HubUnavailable):
            client.health()

    def test_400_la_loi_vinh_vien(self):
        client, _ = self._client(400, {"detail": "thiếu trường"})
        with self.assertRaises(HubError) as ctx:
            client.health()
        self.assertFalse(ctx.exception.retryable)
        self.assertNotIsInstance(ctx.exception, HubUnavailable)

    def test_su_co_tang_van_chuyen_la_tam_thoi(self):
        def broken(*args):
            raise ConnectionError("DNS hỏng")

        client = HubClient("https://hub.test", "key", "edge-1", transport=broken)
        with self.assertRaises(HubUnavailable):
            client.health()

    def test_chua_cau_hinh_thi_bao_loi_ro_rang(self):
        with self.assertRaises(HubError):
            HubClient("", "key").health()
        with self.assertRaises(HubAuthError):
            HubClient("https://hub.test", "").health()

    def test_configured(self):
        self.assertFalse(HubClient("", "").configured())
        self.assertFalse(HubClient("https://hub.test", "").configured())
        self.assertTrue(HubClient("https://hub.test", "k").configured())


class _FakeHub:
    """Hub giả: trả trạng thái đặt trước cho từng entity_key."""

    def __init__(self, answers=None, raises=None):
        self.answers = answers or {}
        self.raises = raises
        self.batches = []

    def push_batch(self, records):
        if self.raises:
            raise self.raises
        self.batches.append(list(records))
        # Khoá theo cặp (entity_type, entity_key) giống HubClient thật: tài liệu
        # và lượt ứng tuyển dùng chung entity_key nên khoá đơn sẽ chồng nhau.
        results = {}
        for record in records:
            key = record["entity_key"]
            kind = record.get("entity_type") or "source_record"
            answer = dict(self.answers.get(key) or {"status": "accepted", "id": "h1"})
            answer.setdefault("entity_key", key)
            answer.setdefault("entity_type", kind)
            results[(kind, key)] = answer
        return results


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.db = Database(os.path.join(self.folder, "test.db"), log=lambda *a: None).open()
        self.addCleanup(self.db.close)

    def _add(self, cv_id="1", **kw):
        self.db.upsert(_candidate(cv_id, **kw))
        self.db.commit()

    def test_quet_xep_hang_ung_vien_moi(self):
        self._add("1")
        self._add("2")
        queued, _ = runner.scan_candidates(self.db)
        self.assertEqual(queued, 2)
        self.assertEqual(self.db.sync_stats()["pending"], 2)

    def test_quet_lai_khong_sinh_viec_moi(self):
        self._add("1")
        runner.scan_all_candidates(self.db)
        self.assertEqual(runner.scan_all_candidates(self.db), 0,
                         "quét lại dữ liệu không đổi phải là no-op")

    def test_sua_ung_vien_thi_xep_hang_lai(self):
        self._add("1")
        runner.scan_all_candidates(self.db)
        row = self.db.claim_sync_batch(1)[0]
        self.db.finish_sync(row["id"], "hub-1")

        self._add("1", phone="0912345678")
        self.assertEqual(runner.scan_all_candidates(self.db), 1)
        self.assertEqual(self.db.sync_stats()["pending"], 1)

    def test_gui_thanh_cong_thi_danh_dau_synced(self):
        self._add("1")
        runner.scan_all_candidates(self.db)
        outcome = runner.push_once(self.db, _FakeHub(), "edge-1", log=lambda *a: None)
        self.assertEqual(outcome["synced"], 1)
        self.assertEqual(self.db.sync_stats()["synced"], 1)

    def test_payload_gui_di_kem_edge_id_va_idempotency_key(self):
        self._add("1")
        runner.scan_all_candidates(self.db)
        hub = _FakeHub()
        runner.push_once(self.db, hub, "edge-1", log=lambda *a: None)
        sent = hub.batches[0][0]
        self.assertEqual(sent["edge_id"], "edge-1")
        self.assertTrue(sent["idempotency_key"])
        self.assertEqual(sent["entity_type"], ENTITY_SOURCE_RECORD)

    def test_hub_bao_duplicate_van_tinh_la_xong(self):
        self._add("1")
        runner.scan_all_candidates(self.db)
        hub = _FakeHub({"topcv|ta@msb.com.vn|1": {"status": "duplicate"}})
        outcome = runner.push_once(self.db, hub, "edge-1", log=lambda *a: None)
        self.assertEqual(outcome["synced"], 1)

    def test_hub_bao_retry_thi_hen_lai(self):
        self._add("1")
        runner.scan_all_candidates(self.db)
        hub = _FakeHub({"topcv|ta@msb.com.vn|1": {"status": "retry", "detail": "bận"}})
        outcome = runner.push_once(self.db, hub, "edge-1", log=lambda *a: None)
        self.assertEqual(outcome["retry"], 1)
        self.assertEqual(self.db.sync_stats()["pending"], 1)

    def test_hub_bao_rejected_la_loi_vinh_vien(self):
        self._add("1")
        runner.scan_all_candidates(self.db)
        hub = _FakeHub({"topcv|ta@msb.com.vn|1": {"status": "rejected", "detail": "thiếu email"}})
        outcome = runner.push_once(self.db, hub, "edge-1", log=lambda *a: None)
        self.assertEqual(outcome["failed"], 1)
        self.assertEqual(self.db.sync_stats()["failed"], 1)

    def test_hub_bo_sot_ban_ghi_thi_gui_lai(self):
        """Thà gửi thừa (Hub chống trùng được) còn hơn âm thầm mất dữ liệu."""
        self._add("1")
        runner.scan_all_candidates(self.db)

        class Silent:
            def push_batch(self, records):
                return {}

        outcome = runner.push_once(self.db, Silent(), "edge-1", log=lambda *a: None)
        self.assertEqual(outcome["retry"], 1)

    def test_hub_sap_thi_ca_lo_duoc_hen_lai(self):
        self._add("1")
        self._add("2")
        runner.scan_all_candidates(self.db)
        hub = _FakeHub(raises=HubUnavailable("Hub sập"))
        outcome = runner.push_once(self.db, hub, "edge-1", log=lambda *a: None)
        self.assertEqual(outcome["retry"], 2)
        self.assertEqual(outcome["failed"], 0)
        self.assertTrue(outcome["error"])

    def test_loi_xac_thuc_TRA_HANG_VE_chu_khong_chon_ban_ghi(self):
        """Khoá sai không phải lỗi của bản ghi — đừng bắt bản ghi chịu.

        Bản cũ đánh dấu cả lô `failed` ngay lập tức (không qua backoff, không
        đếm lần thử), nên một lần xoay khoá giữa lúc đang đồng bộ chôn 50 bản
        ghi mỗi lô — dữ liệu mà Hub hoàn toàn nhận được ngay khi khoá mới được
        nhập. Nay lô được trả về `pending` và lượt sau tiếp đúng chỗ đang dở.
        """
        self._add("1")
        runner.scan_all_candidates(self.db)
        hub = _FakeHub(raises=HubAuthError("sai key"))
        outcome = runner.push_once(self.db, hub, "edge-1", log=lambda *a: None)

        self.assertEqual(outcome["failed"], 0)
        self.assertEqual(outcome["retry"], 0)
        self.assertTrue(outcome["error"])
        stats = self.db.sync_stats()
        self.assertEqual(stats["pending"], 1, "bản ghi phải quay lại hàng đợi")
        self.assertEqual(stats["failed"], 0)

    def test_khoa_thuc_the_sai_khuon_KHONG_bi_danh_dau_da_gui(self):
        """Bản cũ coi khoá sai khuôn như thực thể đã bị xoá và đánh dấu `synced`.

        Hàng biến mất khỏi hàng đợi trong khi Hub chưa hề nhận gì — mất dữ liệu
        im lặng, không cách nào phát hiện.
        """
        self.db.enqueue_sync("source_record", "co|dau|gach|thua", "hash-la")
        self.db.commit()
        outcome = runner.push_once(self.db, _FakeHub(), "edge-1", log=lambda *a: None)
        self.assertEqual(outcome["failed"], 1)
        self.assertEqual(outcome["skipped"], 0)
        self.assertEqual(self.db.sync_stats()["synced"], 0)

    def test_ung_vien_bi_xoa_sau_khi_xep_hang_thi_bo_qua(self):
        self._add("1")
        runner.scan_all_candidates(self.db)
        self.db.delete_candidates(source="topcv")
        self.db.commit()
        outcome = runner.push_once(self.db, _FakeHub(), "edge-1", log=lambda *a: None)
        self.assertEqual(outcome["skipped"], 1)
        self.assertEqual(self.db.sync_stats()["pending"], 0,
                         "hàng mồ côi không được chặn hàng đợi")

    def test_drain_gui_het_hang_doi(self):
        for i in range(7):
            self._add(str(i))
        runner.scan_all_candidates(self.db)
        totals = runner.drain(self.db, _FakeHub(), "edge-1", batch_size=2, log=lambda *a: None)
        self.assertEqual(totals["synced"], 7)
        self.assertEqual(self.db.sync_stats()["pending"], 0)

    def test_drain_dung_ngay_khi_ca_lo_that_bai(self):
        for i in range(5):
            self._add(str(i))
        runner.scan_all_candidates(self.db)
        hub = _FakeHub(raises=HubUnavailable("Hub sập"))
        totals = runner.drain(self.db, hub, "edge-1", batch_size=2, log=lambda *a: None)
        self.assertEqual(totals["batches"], 1, "không nên đấm vào một Hub đang sập")

    def test_drain_gui_lai_duoc_sau_khi_khoi_phuc(self):
        self._add("1")
        runner.scan_all_candidates(self.db)
        runner.drain(self.db, _FakeHub(raises=HubUnavailable("sập")), "edge-1",
                     log=lambda *a: None)
        # Backoff đã hẹn ở tương lai; mô phỏng việc tới hạn.
        self.db._write("UPDATE sync_outbox SET next_attempt_at=''")
        totals = runner.drain(self.db, _FakeHub(), "edge-1", log=lambda *a: None)
        self.assertEqual(totals["synced"], 1)


class EdgeIdentityTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        from app.sync import identity
        self.identity = identity
        identity.reset_cache()
        self.addCleanup(identity.reset_cache)
        self._patch = mock.patch.object(
            identity, "local_state_dir", return_value=self.folder)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_tao_edge_id_lan_dau_va_luu_lai(self):
        first = self.identity.edge_id()
        self.assertTrue(first)
        self.assertTrue(os.path.isfile(
            os.path.join(self.folder, self.identity.IDENTITY_FILE)))

        self.identity.reset_cache()
        self.assertEqual(self.identity.edge_id(), first,
                         "edge_id phải ổn định giữa các lần khởi động")

    def test_file_hong_thi_tao_lai_thay_vi_sap(self):
        with open(os.path.join(self.folder, self.identity.IDENTITY_FILE), "w") as f:
            f.write("{khong-phai-json")
        self.assertTrue(self.identity.edge_id())

    def test_khong_ghi_duoc_dia_van_tra_ve_danh_tinh(self):
        with mock.patch.object(self.identity, "_write_identity"):
            self.identity.reset_cache()
            self.assertTrue(self.identity.edge_id())


if __name__ == "__main__":
    unittest.main()
