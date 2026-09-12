# -*- coding: utf-8 -*-
"""Kiểm thử luồng Hiring Manager (Phase 8).

Ba điều được canh:

1. **Hiệu chỉnh học đúng hướng** và không học từ nhiễu.
2. **Nhờ recruiter săn** — CTA cốt lõi — bàn giao đúng người, đúng trạng thái.
3. Đánh giá của HM để lại dấu vết trên timeline của Person.
"""
import json
from datetime import timedelta

from accounts import roles
from core.models import Edge, SourceRecord
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from people import ingest
from people.models import Interaction, Person, Relationship, Signal
from talent.models import TalentProfile
from talent import scoring

from . import calibration as calibration_module
from . import jd as jd_module
from . import outreach as outreach_module
from .models import (Candidacy, HiringNeed, HuntCandidate,
                     HuntCandidateStatusEvent, HuntRequest)


def make_user(username, *role_names):
    roles.ensure_groups()
    user = User.objects.create_user(username, password="mat-khau-dai-1")
    for name in role_names:
        user.groups.add(Group.objects.get(name=name))
    return user


def dims(**scores):
    """Ảnh chụp các chiều, đủ dùng cho hiệu chỉnh."""
    return [{"key": k, "score": v, "weight": 0.2, "fact": "", "unknown": ""}
            for k, v in scores.items()]


class CalibrationTest(TestCase):
    def setUp(self):
        self.need = HiringNeed.objects.create(title="Data Analyst")

    def _candidacy(self, name, state, **scores):
        person = Person.objects.create(display_name=name)
        return Candidacy.objects.create(
            hiring_need=self.need, person=person, state=state,
            dimensions_snapshot=dims(**scores))

    def test_khong_du_phan_hoi_thi_KHONG_hieu_chinh(self):
        """Chỉnh trọng số theo nhiễu còn tệ hơn không chỉnh."""
        self._candidacy("A", Candidacy.STATE_GOOD_FIT, skills=1.0)
        result = calibration_module.calibrate(self.need)
        self.assertFalse(result.applied)
        self.assertEqual(result.weights, {})
        self.assertIn("ít nhất", result.insights[0])

    def test_hoc_dung_chieu_phan_tach_hai_nhom(self):
        """Người phù hợp toàn khớp kỹ năng, không phù hợp thì không → tăng kỹ năng."""
        for name in ("A", "B"):
            self._candidacy(name, Candidacy.STATE_GOOD_FIT, skills=1.0, location=0.5)
        for name in ("C", "D"):
            self._candidacy(name, Candidacy.STATE_NOT_FIT, skills=0.0, location=0.5)

        result = calibration_module.calibrate(self.need)
        self.assertTrue(result.applied)
        from talent import scoring
        base = scoring.weights()
        self.assertGreater(result.weights["skills"], base["skills"])
        self.assertTrue(any("kỹ năng" in s for s in result.insights))

    def test_chieu_khong_phan_tach_thi_bi_GIAM(self):
        """HM chọn ngược với chiều nào thì chiều đó bớt quan trọng."""
        for name in ("A", "B"):
            self._candidacy(name, Candidacy.STATE_GOOD_FIT, skills=1.0, location=0.0)
        for name in ("C", "D"):
            self._candidacy(name, Candidacy.STATE_NOT_FIT, skills=0.0, location=1.0)

        result = calibration_module.calibrate(self.need)
        self.assertGreater(result.weights["skills"], result.weights["location"])

    def test_trong_so_bi_chan_hai_dau(self):
        """Một loạt phản hồi lệch không được xoá sổ hoàn toàn một chiều."""
        for name in ("A", "B", "C"):
            self._candidacy(name, Candidacy.STATE_GOOD_FIT, skills=1.0)
        for name in ("D", "E", "F"):
            self._candidacy(name, Candidacy.STATE_NOT_FIT, skills=0.0)

        result = calibration_module.calibrate(self.need)
        for value in result.weights.values():
            self.assertGreater(value, 0)

    def test_giu_nguyen_tong_trong_so(self):
        """Để điểm vẫn ở thang 0..1 và so sánh được giữa các lần hiệu chỉnh."""
        for name in ("A", "B"):
            self._candidacy(name, Candidacy.STATE_GOOD_FIT, skills=1.0)
        for name in ("C", "D"):
            self._candidacy(name, Candidacy.STATE_NOT_FIT, skills=0.0)

        result = calibration_module.calibrate(self.need)
        self.assertAlmostEqual(sum(result.weights.values()),
                               sum(scoring.weights().values()), places=2)

    def test_chieu_khong_co_du_lieu_thi_giu_nguyen(self):
        for name in ("A", "B"):
            self._candidacy(name, Candidacy.STATE_GOOD_FIT, skills=1.0)
        for name in ("C", "D"):
            self._candidacy(name, Candidacy.STATE_NOT_FIT, skills=0.0)

        result = calibration_module.calibrate(self.need)
        # `industry` không có trong ảnh chụp nào.
        self.assertIn("industry", result.weights)

    def test_shortlist_cung_la_tin_hieu_duong(self):
        """Chấm phù hợp rồi shortlist là thao tác tự nhiên nhất — không được để
        nó xoá mất chính tín hiệu dương mà hiệu chỉnh cần."""
        for name in ("A", "B"):
            self._candidacy(name, Candidacy.STATE_SHORTLISTED, skills=1.0)
        for name in ("C", "D"):
            self._candidacy(name, Candidacy.STATE_NOT_FIT, skills=0.0)

        result = calibration_module.calibrate(self.need)
        self.assertTrue(result.applied)
        self.assertEqual(result.good_count, 2)
        from talent import scoring
        self.assertGreater(result.weights["skills"], scoring.weights()["skills"])

    def test_xep_lai_theo_trong_so_moi(self):
        nguoi_a = Person.objects.create(display_name="A")
        nguoi_b = Person.objects.create(display_name="B")
        scored = [
            (nguoi_a, {"score": 0.5, "dimensions": dims(skills=1.0, location=0.0)}),
            (nguoi_b, {"score": 0.5, "dimensions": dims(skills=0.0, location=1.0)}),
        ]
        ranked = calibration_module.rank(scored, {"skills": 0.9, "location": 0.1})
        self.assertEqual(ranked[0][0], nguoi_a)


class HiringNeedApiTest(TestCase):
    def setUp(self):
        self.hm = make_user("truongbophan", roles.RECRUITER)
        self.client.force_login(self.hm)

        edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        mau = [
            ("An", "an@x.vn", "0901111111", "Senior Data Analyst", "SQL, Python", "Hà Nội", "4 năm"),
            ("Bình", "binh@x.vn", "0902222222", "Data Analyst", "SQL, Excel", "Hà Nội", "2 năm"),
            ("Cường", "cuong@x.vn", "0903333333", "Backend Engineer", "Java", "Hà Nội", "9 năm"),
        ]
        for ten, email, phone, vitri, kynang, tp, nam in mau:
            SourceRecord.objects.create(
                edge=edge, entity_type="source_record",
                entity_key=f"topcv|ta@msb.com.vn|{email}", content_hash=f"h{email}",
                payload={"source": "topcv", "account": "ta@msb.com.vn", "cv_id": email,
                         "fullname": f"Nguyễn Văn {ten}", "email": email, "phone": phone,
                         "current_title": vitri, "position": vitri, "skills": kynang,
                         "city": tp, "years_experience": nam,
                         "applied_ts": "2026-08-01 09:00:00"})
        ingest.resolve_pending()

    def _post(self, name, args=None, body=None):
        return self.client.post(reverse(name, args=args or []),
                                data=json.dumps(body or {}),
                                content_type="application/json")

    def test_tao_nhu_cau_tuyen_dung(self):
        response = self._post("hiring-needs", body={"title": "Data Analyst",
                                                    "department": "Khối Dữ liệu"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(HiringNeed.objects.get().owner, self.hm)

    def test_thieu_ca_ten_lan_JD_thi_400(self):
        self.assertEqual(self._post("hiring-needs", body={}).status_code, 400)

    def test_de_xuat_ung_vien_va_GHI_LAI_candidacy(self):
        """Không lưu ảnh chụp điểm thì hiệu chỉnh không có gì để học."""
        need = HiringNeed.objects.create(title="Data Analyst",
                                         criteria={"skills": ["SQL"]})
        body = self.client.get(reverse("hiring-suggestions", args=[need.pk])).json()
        self.assertEqual(body["count"], 3)
        self.assertEqual(need.candidacies.count(), 3)
        self.assertTrue(need.candidacies.first().dimensions_snapshot)

    def test_tieu_chi_chat_van_de_xuat_nguoi_lech_MOT_chut(self):
        """Lọc AND cứng còn 1 người thì HM không có ai để chấm "không phù hợp"
        — mà thiếu vế đó thì hiệu chỉnh không có gì để học."""
        need = HiringNeed.objects.create(
            title="Data Analyst",
            criteria={"title": "Data Analyst", "skills": ["SQL", "Python"],
                      "location": "Hà Nội", "min_years": 5})
        body = self.client.get(reverse("hiring-suggestions", args=[need.pk])).json()
        # Không ai đủ 5 năm VÀ đủ cả hai kỹ năng, nhưng vẫn phải có người để xét.
        self.assertEqual(body["count"], 3)
        # Và phải nói rõ không ai khớp đủ, kẻo con số lệch với ô tìm kiếm mà
        # người dùng tưởng hệ thống đếm sai.
        self.assertEqual(body["strict_count"], 0)

    def test_noi_tieu_chi_KHONG_lam_loan_thu_tu(self):
        need = HiringNeed.objects.create(
            title="Data Analyst",
            criteria={"title": "Data Analyst", "skills": ["SQL", "Python"],
                      "location": "Hà Nội", "min_years": 3})
        body = self.client.get(reverse("hiring-suggestions", args=[need.pk])).json()
        self.assertEqual(body["results"][0]["display_name"], "Nguyễn Văn An")

    def test_de_xuat_lai_khong_tao_ban_ghi_trung(self):
        need = HiringNeed.objects.create(title="X", criteria={"skills": ["SQL"]})
        for _ in range(3):
            self.client.get(reverse("hiring-suggestions", args=[need.pk]))
        self.assertEqual(need.candidacies.count(), 3)

    def test_danh_dau_phu_hop(self):
        need = HiringNeed.objects.create(title="X", criteria={"skills": ["SQL"]})
        person = Person.objects.first()
        response = self._post("hiring-mark", [need.pk],
                              {"person_id": person.pk, "state": "good_fit"})
        self.assertEqual(response.status_code, 200)
        candidacy = Candidacy.objects.get(hiring_need=need, person=person)
        self.assertEqual(candidacy.state, "good_fit")
        self.assertEqual(candidacy.marked_by, self.hm)

    def test_danh_dau_de_lai_dau_vet_tren_timeline_cua_Person(self):
        """Đánh giá của HM là dữ kiện về con người, không chỉ về vị trí này."""
        need = HiringNeed.objects.create(title="X")
        person = Person.objects.first()
        self._post("hiring-mark", [need.pk],
                   {"person_id": person.pk, "state": "good_fit"})
        self.assertTrue(Interaction.objects.filter(
            person=person, action="hm_good_fit", actor=self.hm).exists())

    def test_trang_thai_danh_dau_la_thi_400(self):
        need = HiringNeed.objects.create(title="X")
        person = Person.objects.first()
        response = self._post("hiring-mark", [need.pk],
                              {"person_id": person.pk, "state": "linh_tinh"})
        self.assertEqual(response.status_code, 400)

    def test_hieu_chinh_qua_API(self):
        need = HiringNeed.objects.create(title="X")
        people = list(Person.objects.all())
        for person, state, score in (
            (people[0], "good_fit", 1.0), (people[1], "good_fit", 1.0),
            (people[2], "not_fit", 0.0),
        ):
            Candidacy.objects.create(hiring_need=need, person=person, state=state,
                                     dimensions_snapshot=dims(skills=score))
        # Mới 1 not_fit -> chưa đủ
        self.assertEqual(self._post("hiring-calibrate", [need.pk]).status_code, 400)

        Candidacy.objects.create(
            hiring_need=need, person=Person.objects.create(display_name="D"),
            state="not_fit", dimensions_snapshot=dims(skills=0.0))
        response = self._post("hiring-calibrate", [need.pk])
        self.assertEqual(response.status_code, 200)
        need.refresh_from_db()
        self.assertTrue(need.is_calibrated)

    def test_bo_hieu_chinh(self):
        need = HiringNeed.objects.create(title="X", learned_weights={"skills": 0.9})
        self._post("hiring-calibrate-reset", [need.pk])
        need.refresh_from_db()
        self.assertFalse(need.is_calibrated)


class JdFallbackTest(TestCase):
    """LLM bận là chuyện thường ngày với khoá miễn phí — kể cả hôm demo."""

    def setUp(self):
        edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        SourceRecord.objects.create(
            edge=edge, entity_type="source_record", entity_key="topcv|a|1",
            content_hash="h1",
            payload={"source": "topcv", "account": "a", "cv_id": "1",
                     "fullname": "Nguyễn Văn An", "email": "an@x.vn",
                     "current_title": "Data Analyst", "skills": "SQL, Python, Power BI",
                     "city": "Hà Nội", "years_experience": "4 năm",
                     "applied_ts": "2026-08-01 09:00:00"})
        ingest.resolve_pending()

    def _parse(self, text, title=""):
        from unittest import mock
        with mock.patch("hiring.jd.complete", side_effect=RuntimeError("hết hạn mức")):
            return jd_module.parse_jd(text, title=title)

    def test_do_duoc_ky_nang_CO_THAT_trong_kho(self):
        parsed = self._parse("Cần người thành thạo SQL và Python, làm tại Hà Nội.")
        self.assertTrue(parsed.fallback)
        self.assertEqual(sorted(parsed.criteria["skills"]), ["Python", "SQL"])
        self.assertEqual(parsed.criteria["location"], "Hà Nội")

    def test_khong_bia_ky_nang_khong_co_trong_kho(self):
        """Từ vựng lấy từ CSDL nên tiêu chí rút ra luôn tìm được người."""
        parsed = self._parse("Yêu cầu: COBOL, Fortran.")
        self.assertNotIn("skills", parsed.criteria)

    def test_lay_moc_nam_NHO_NHAT(self):
        """JD hay nhắc nhiều mốc; đòi mốc cao nhất là loại oan ứng viên."""
        parsed = self._parse("Tối thiểu 3 năm kinh nghiệm. Ưu tiên 7 năm trong ngành.")
        self.assertEqual(parsed.criteria["min_years"], 3)

    def test_tieu_chi_do_chu_van_TIM_RA_nguoi(self):
        make_user("hm", roles.RECRUITER)
        parsed = self._parse("Cần Data Analyst thạo SQL tại Hà Nội", title="Data Analyst")
        need = HiringNeed.objects.create(title="X", criteria=parsed.criteria,
                                         criteria_fallback=True)
        self.client.force_login(User.objects.get(username="hm"))
        body = self.client.get(reverse("hiring-suggestions", args=[need.pk])).json()
        self.assertGreaterEqual(body["count"], 1)

    def test_lay_dong_dau_JD_lam_ten_vi_tri(self):
        """Không có tên thì danh sách toàn "(chưa đặt tên)", không phân biệt nổi."""
        parsed = self._parse("Chuyên viên Phân tích Dữ liệu\n\nYêu cầu: SQL")
        self.assertEqual(parsed.title, "Chuyên viên Phân tích Dữ liệu")

    def test_chuc_danh_phai_vao_ca_TIEU_CHI_khong_chi_lam_ten(self):
        """Chỉ lấy làm tên thì vị trí có tên đàng hoàng mà chiều "chức danh"
        không được chấm chút nào — Data Engineer xếp ngang Data Analyst."""
        parsed = self._parse("Chuyên viên Phân tích Dữ liệu\n\nYêu cầu: SQL")
        self.assertEqual(parsed.criteria["title"], "Chuyên viên Phân tích Dữ liệu")

    def test_danh_dau_la_do_chu_de_HM_biet_ma_xem_lai(self):
        make_user("hm", roles.RECRUITER)
        self.client.force_login(User.objects.get(username="hm"))
        from unittest import mock
        with mock.patch("hiring.jd.complete", side_effect=RuntimeError("bận")):
            response = self.client.post(
                reverse("hiring-needs"),
                data=json.dumps({"title": "Data Analyst",
                                 "jd_text": "Cần người thạo SQL tại Hà Nội"}),
                content_type="application/json")
        self.assertTrue(response.json()["criteria_fallback"])


class HuntRequestTest(TestCase):
    def setUp(self):
        self.hm = make_user("truongbophan", roles.RECRUITER)
        self.recruiter = make_user("tuyendung", roles.RECRUITER)
        self.need = HiringNeed.objects.create(title="Data Analyst", owner=self.hm)
        self.people = [Person.objects.create(display_name=f"Người {i}")
                       for i in range(3)]
        self.client.force_login(self.hm)

    def _post(self, name, args=None, body=None):
        return self.client.post(reverse(name, args=args or []),
                                data=json.dumps(body or {}),
                                content_type="application/json")

    def test_nho_san_voi_shortlist(self):
        for person in self.people[:2]:
            Candidacy.objects.create(hiring_need=self.need, person=person,
                                     state=Candidacy.STATE_SHORTLISTED)
        response = self._post("hiring-request-hunt", [self.need.pk],
                              {"message": "Ưu tiên hai người này"})
        self.assertEqual(response.status_code, 201)

        hunt = HuntRequest.objects.get()
        self.assertEqual(hunt.people.count(), 2)
        self.assertEqual(hunt.requested_by, self.hm)
        self.assertEqual(hunt.status, HuntRequest.STATUS_NEW)

    def test_nho_san_doi_trang_thai_nhu_cau(self):
        Candidacy.objects.create(hiring_need=self.need, person=self.people[0],
                                 state=Candidacy.STATE_SHORTLISTED)
        self._post("hiring-request-hunt", [self.need.pk])
        self.need.refresh_from_db()
        self.assertEqual(self.need.status, HiringNeed.STATUS_HUNTING)

    def test_shortlist_rong_thi_400(self):
        response = self._post("hiring-request-hunt", [self.need.pk])
        self.assertEqual(response.status_code, 400)

    def test_chi_dinh_ro_danh_sach_nguoi(self):
        response = self._post("hiring-request-hunt", [self.need.pk],
                              {"person_ids": [p.pk for p in self.people]})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(HuntRequest.objects.get().people.count(), 3)

    def test_ghi_dau_vet_tren_timeline_tung_nguoi(self):
        self._post("hiring-request-hunt", [self.need.pk],
                   {"person_ids": [self.people[0].pk]})
        self.assertTrue(Interaction.objects.filter(
            person=self.people[0], action="hunt_requested").exists())

    def test_recruiter_thay_yeu_cau_trong_hop_thu(self):
        self._post("hiring-request-hunt", [self.need.pk],
                   {"person_ids": [self.people[0].pk]})
        self.client.force_login(self.recruiter)
        body = self.client.get(reverse("hiring-hunts"), {"open": "1"}).json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["hiring_need_title"], "Data Analyst")

    def test_recruiter_nhan_viec_thi_tu_dung_ten(self):
        self._post("hiring-request-hunt", [self.need.pk],
                   {"person_ids": [self.people[0].pk]})
        hunt = HuntRequest.objects.get()

        self.client.force_login(self.recruiter)
        self.client.patch(reverse("hiring-hunt", args=[hunt.pk]),
                          data=json.dumps({"status": "accepted"}),
                          content_type="application/json")
        hunt.refresh_from_db()
        self.assertEqual(hunt.assigned_to, self.recruiter)
        self.assertEqual(hunt.status, HuntRequest.STATUS_ACCEPTED)

    def test_loc_theo_viec_cua_toi(self):
        self._post("hiring-request-hunt", [self.need.pk],
                   {"person_ids": [self.people[0].pk]})
        hunt = HuntRequest.objects.get()
        hunt.assigned_to = self.recruiter
        hunt.save()

        self.client.force_login(self.recruiter)
        body = self.client.get(reverse("hiring-hunts"), {"mine": "1"}).json()
        self.assertEqual(len(body["results"]), 1)

    def test_mot_vi_tri_nho_san_nhieu_lan(self):
        """Mỗi lần một nhóm khác, có thể giao cho recruiter khác."""
        for person in self.people[:2]:
            self._post("hiring-request-hunt", [self.need.pk],
                       {"person_ids": [person.pk]})
        self.assertEqual(HuntRequest.objects.count(), 2)

    def test_recruiter_tu_tao_shortlist_khong_can_hiring_need(self):
        self.client.force_login(self.recruiter)
        response = self._post("hiring-hunts", body={
            "title": "Data team - ưu tiên tuần này",
            "person_ids": [self.people[0].pk, self.people[1].pk],
            "priority": "high",
            "message": "Liên hệ trước thứ Sáu",
        })
        self.assertEqual(response.status_code, 201)
        hunt = HuntRequest.objects.get()
        self.assertIsNone(hunt.hiring_need)
        self.assertEqual(hunt.assigned_to, self.recruiter)
        self.assertEqual(hunt.requested_by, self.recruiter)
        self.assertEqual(hunt.people.count(), 2)
        self.assertEqual(hunt.priority, "high")
        self.assertEqual(response.json()["hiring_need_title"], hunt.title)
        self.assertTrue(Interaction.objects.filter(
            person=self.people[0], action="shortlist_added").exists())

    def test_tao_shortlist_can_ten_ung_vien_va_priority_hop_le(self):
        self.client.force_login(self.recruiter)
        self.assertEqual(self._post("hiring-hunts", body={
            "person_ids": [self.people[0].pk]}).status_code, 400)
        response = self._post("hiring-hunts", body={
            "title": "Danh sách", "person_ids": []})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["progress"]["total"], 0)
        self.assertEqual(self._post("hiring-hunts", body={
            "title": "Danh sách", "person_ids": [self.people[0].pk],
            "priority": "impossible"}).status_code, 400)


class HuntCandidateTest(TestCase):
    """Phase 9 — recruiter làm việc với từng người trong yêu cầu săn."""

    def setUp(self):
        self.hm = make_user("truongbophan", roles.RECRUITER)
        self.recruiter = make_user("tuyendung", roles.RECRUITER)
        self.need = HiringNeed.objects.create(title="Data Analyst", owner=self.hm)
        self.people = [Person.objects.create(display_name=f"Người {i}")
                       for i in range(3)]
        self.hunt = HuntRequest.objects.create(hiring_need=self.need,
                                               requested_by=self.hm)
        self.hunt.people.set(self.people)
        self.client.force_login(self.recruiter)

    def _patch(self, person, body):
        return self.client.patch(
            reverse("hiring-hunt-candidate", args=[self.hunt.pk, person.pk]),
            data=json.dumps(body), content_type="application/json")

    def test_moi_nguoi_bat_dau_o_chua_lien_he(self):
        self.assertEqual(self.hunt.candidates.count(), 3)
        self.assertTrue(all(c.state == HuntCandidate.STATE_PENDING
                            for c in self.hunt.candidates.all()))

    def test_doi_trang_thai_lien_he(self):
        response = self._patch(self.people[0], {"state": "interested",
                                                "note": "Hẹn gọi lại thứ 5"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state_label"], "Có quan tâm")

    def test_dong_bo_sang_Relationship_de_NGUOI_KHAC_nhin_thay(self):
        """Không đồng bộ thì hồ sơ vẫn hiện chưa liên hệ dù đã bị gọi ba lần."""
        self._patch(self.people[0], {"state": "interested"})
        relationship = Relationship.objects.get(person=self.people[0],
                                                domain=Signal.DOMAIN_TALENT)
        self.assertEqual(relationship.state, "interested")
        self.assertEqual(relationship.owner_user, self.recruiter)

    def test_khong_lien_he_duoc_duoc_phan_anh_len_quan_he_tong(self):
        self._patch(self.people[0], {"state": "unreachable"})
        relationship = Relationship.objects.get(
            person=self.people[0], domain=Signal.DOMAIN_TALENT)
        self.assertEqual(relationship.state, "attempted")

    def test_luong_yeu_khong_ghi_de_luong_manh_cua_cung_ung_vien(self):
        other_hunt = HuntRequest.objects.create(
            title="Luồng khác", requested_by=self.recruiter,
            assigned_to=self.recruiter, status=HuntRequest.STATUS_IN_PROGRESS)
        HuntCandidate.objects.create(
            hunt_request=other_hunt, person=self.people[0],
            assigned_to=self.recruiter, state=HuntCandidate.STATE_INTERESTED)
        self._patch(self.people[0], {"state": "contacting"})
        relationship = Relationship.objects.get(
            person=self.people[0], domain=Signal.DOMAIN_TALENT)
        self.assertEqual(relationship.state, "interested")

    def test_tra_ve_kho_BAT_BUOC_co_ly_do(self):
        response = self._patch(self.people[0], {"state": "returned"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("lý do", response.json()["detail"])

    def test_tra_ve_kho_kem_ly_do_thi_duoc(self):
        response = self._patch(self.people[0],
                               {"state": "returned",
                                "return_reason": "Đang trong hợp đồng 2 năm"})
        self.assertEqual(response.status_code, 200)
        relationship = Relationship.objects.get(person=self.people[0])
        self.assertEqual(relationship.state, "nurturing")
        self.assertEqual(relationship.reason, "Đang trong hợp đồng 2 năm")
        self.assertIsNotNone(relationship.next_action_at)

    def test_ly_do_tra_ve_nam_tren_timeline(self):
        self._patch(self.people[0], {"state": "returned",
                                     "return_reason": "Vừa nhận việc mới"})
        interaction = Interaction.objects.get(person=self.people[0],
                                              action="hunt_returned")
        self.assertEqual(interaction.detail["reason"], "Vừa nhận việc mới")

    def test_trang_thai_la_thi_400(self):
        self.assertEqual(self._patch(self.people[0], {"state": "abc"}).status_code, 400)

    def test_luu_uu_tien_ghi_chu_va_lich_follow_up(self):
        response = self._patch(self.people[0], {
            "priority": "urgent", "note": "Gọi lại sau giờ làm",
            "next_action_at": "2026-08-25T09:30:00+07:00",
        })
        self.assertEqual(response.status_code, 200)
        candidate = self.hunt.candidates.get(person=self.people[0])
        self.assertEqual(candidate.priority, "urgent")
        self.assertEqual(candidate.note, "Gọi lại sau giờ làm")
        self.assertIsNotNone(candidate.next_action_at)

    def test_phan_cong_cap_ung_vien_va_luu_lich_su_trang_thai(self):
        response = self._patch(self.people[0], {
            "assigned_to_id": self.recruiter.pk, "state": "contacting",
            "note": "Gọi lần đầu",
        })
        self.assertEqual(response.status_code, 200)
        candidate = self.hunt.candidates.get(person=self.people[0])
        self.assertEqual(candidate.assigned_to, self.recruiter)
        event = HuntCandidateStatusEvent.objects.get(candidate=candidate)
        self.assertEqual(event.from_state, "pending")
        self.assertEqual(event.to_state, "contacting")
        self.assertEqual(event.actor, self.recruiter)
        self.assertEqual(response.json()["status_events"][0]["to_state"], "contacting")

    def test_recruiter_tu_nhan_cong_viec_chua_phan_cong(self):
        response = self._patch(self.people[0], {"claim": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.hunt.candidates.get(person=self.people[0]).assigned_to,
                         self.recruiter)

    def test_scope_viec_cua_toi_chi_tra_ung_vien_duoc_giao(self):
        first = self.hunt.candidates.get(person=self.people[0])
        first.assigned_to = self.recruiter
        first.save()
        body = self.client.get(reverse("hiring-hunts"), {"scope": "mine"}).json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual([row["person_id"] for row in body["results"][0]["people"]],
                         [self.people[0].pk])

    def test_scope_followup_va_chua_phan_cong(self):
        first = self.hunt.candidates.get(person=self.people[0])
        first.assigned_to = self.recruiter
        first.next_action_at = timezone.now() - timedelta(minutes=1)
        first.save()
        followup = self.client.get(reverse("hiring-hunts"), {"scope": "followup"}).json()
        self.assertEqual(followup["results"][0]["people"][0]["person_id"],
                         self.people[0].pk)
        unassigned = self.client.get(reverse("hiring-hunts"), {"scope": "unassigned"}).json()
        self.assertEqual(len(unassigned["results"][0]["people"]), 2)

    def test_inbox_phang_gop_cong_viec_va_quan_he_den_han(self):
        candidate = self.hunt.candidates.get(person=self.people[0])
        candidate.assigned_to = self.recruiter
        candidate.next_action_at = timezone.now() - timedelta(minutes=5)
        candidate.save()
        Relationship.objects.create(
            person=self.people[1], domain=Signal.DOMAIN_TALENT,
            state="nurturing", owner_user=self.recruiter,
            next_action="Hỏi lại sau thử việc",
            next_action_at=timezone.now() - timedelta(minutes=2))

        body = self.client.get(reverse("hiring-hunt-tasks"),
                               {"scope": "overdue"}).json()
        self.assertEqual(body["count"], 2)
        self.assertEqual({row["kind"] for row in body["results"]},
                         {"work", "relationship"})
        self.assertEqual(body["summary"]["active"], 1)

    def test_inbox_tu_choi_scope_va_phan_trang_sai_thay_vi_HTTP_500(self):
        url = reverse("hiring-hunt-tasks")
        self.assertEqual(self.client.get(url, {"scope": "team"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"limit": "abc"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"pool": "abc"}).status_code, 400)

    def test_inbox_gop_followup_quan_he_vao_task_pipeline_cung_nguoi(self):
        candidate = self.hunt.candidates.get(person=self.people[0])
        candidate.assigned_to = self.recruiter
        candidate.next_action_at = timezone.now() - timedelta(minutes=5)
        candidate.save()
        Relationship.objects.create(
            person=self.people[0], domain=Signal.DOMAIN_TALENT,
            owner_user=self.recruiter, state="nurturing",
            next_action_at=timezone.now() - timedelta(minutes=2))
        body = self.client.get(reverse("hiring-hunt-tasks"),
                               {"scope": "overdue"}).json()
        self.assertEqual(body["count"], 1)
        self.assertTrue(body["results"][0]["relationship_due"])
        self.assertEqual(body["summary"]["overdue"], 1)

    def test_sua_ghi_chu_khong_reset_moc_SLA(self):
        from core.models import WorkflowStage
        stage, _ = WorkflowStage.objects.get_or_create(
            domain="talent", code="contacting",
            defaults={"label": "Đang tiếp cận", "sla_hours": 1})
        stage.sla_hours = 1
        stage.save()
        candidate = self.hunt.candidates.get(person=self.people[0])
        candidate.assigned_to = self.recruiter
        candidate.state = HuntCandidate.STATE_CONTACTING
        candidate.stage_entered_at = timezone.now() - timedelta(hours=2)
        candidate.save()
        original = candidate.stage_entered_at
        self._patch(self.people[0], {"note": "Bổ sung ghi chú"})
        candidate.refresh_from_db()
        self.assertEqual(candidate.stage_entered_at, original)
        body = self.client.get(reverse("hiring-hunt-tasks"),
                               {"scope": "overdue"}).json()
        self.assertEqual(body["count"], 1)

    def test_khong_the_claim_de_len_cong_viec_nguoi_khac(self):
        candidate = self.hunt.candidates.get(person=self.people[0])
        candidate.assigned_to = self.hm
        candidate.save()
        response = self._patch(self.people[0], {"claim": True})
        self.assertEqual(response.status_code, 409)
        candidate.refresh_from_db()
        self.assertEqual(candidate.assigned_to, self.hm)

    def test_bulk_la_all_or_nothing_khi_mot_viec_thuoc_nguoi_khac(self):
        mine = self.hunt.candidates.get(person=self.people[0])
        mine.assigned_to = self.recruiter
        mine.save()
        other = self.hunt.candidates.get(person=self.people[1])
        other.assigned_to = self.hm
        other.save()
        response = self.client.post(
            reverse("hiring-hunt-candidates-bulk"),
            data=json.dumps({
                "items": [
                    {"hunt_id": self.hunt.pk, "person_id": self.people[0].pk},
                    {"hunt_id": self.hunt.pk, "person_id": self.people[1].pk},
                ],
                "patch": {"state": "contacting"},
            }), content_type="application/json")
        self.assertEqual(response.status_code, 409)
        mine.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(mine.state, HuntCandidate.STATE_PENDING)
        self.assertEqual(other.state, HuntCandidate.STATE_PENDING)

    def test_inbox_hien_DNC_va_cac_luong_khac_dang_xu_ly(self):
        candidate = self.hunt.candidates.get(person=self.people[0])
        candidate.assigned_to = self.recruiter
        candidate.save()
        Relationship.objects.create(
            person=self.people[0], domain=Signal.DOMAIN_TALENT,
            state="do_not_contact", do_not_contact=True)
        other = HuntRequest.objects.create(title="Data Q4", requested_by=self.recruiter,
                                           status=HuntRequest.STATUS_IN_PROGRESS)
        HuntCandidate.objects.create(hunt_request=other, person=self.people[0],
                                     assigned_to=self.hm)
        row = self.client.get(reverse("hiring-hunt-tasks")).json()["results"][0]
        self.assertTrue(row["relationship"]["do_not_contact"])
        self.assertEqual(row["other_active_worklists"][0]["title"], "Data Q4")

    def test_scope_da_hoan_tat_chi_hien_cong_viec_cua_toi(self):
        mine = self.hunt.candidates.get(person=self.people[0])
        mine.assigned_to = self.recruiter
        mine.state = HuntCandidate.STATE_SUBMITTED
        mine.save()
        other = self.hunt.candidates.get(person=self.people[1])
        other.assigned_to = self.hm
        other.state = HuntCandidate.STATE_SUBMITTED
        other.save()
        body = self.client.get(reverse("hiring-hunts"), {"scope": "completed"}).json()
        self.assertEqual([row["person_id"] for row in body["results"][0]["people"]],
                         [self.people[0].pk])

    def test_khong_dong_danh_sach_khi_con_ung_vien_dang_xu_ly(self):
        response = self.client.patch(
            reverse("hiring-hunt", args=[self.hunt.pk]),
            data=json.dumps({"status": "done"}), content_type="application/json")
        self.assertEqual(response.status_code, 409)

    def test_tien_do_khong_bi_thay_doi_theo_bo_loc_followup(self):
        candidate = self.hunt.candidates.get(person=self.people[0])
        candidate.assigned_to = self.recruiter
        candidate.next_action_at = timezone.now() - timedelta(minutes=1)
        candidate.save()
        body = self.client.get(reverse("hiring-hunts"), {"scope": "followup"}).json()
        self.assertEqual(body["results"][0]["progress"]["total"], 3)
        self.assertEqual(body["results"][0]["visible_count"], 1)

    def test_xong_het_nguoi_thi_TU_DONG_dong_yeu_cau(self):
        for person in self.people[:2]:
            self._patch(person, {"state": "submitted"})
        self.hunt.refresh_from_db()
        self.assertEqual(self.hunt.status, HuntRequest.STATUS_NEW)

        self._patch(self.people[2], {"state": "returned", "return_reason": "Xa quá"})
        self.hunt.refresh_from_db()
        self.assertEqual(self.hunt.status, HuntRequest.STATUS_DONE)

    def test_khong_tu_MO_LAI_yeu_cau_da_dong(self):
        """Mở lại là quyết định có chủ ý của recruiter, không phải tác dụng phụ."""
        self.hunt.status = HuntRequest.STATUS_DONE
        self.hunt.save()
        self._patch(self.people[0], {"state": "contacting"})
        self.hunt.refresh_from_db()
        self.assertEqual(self.hunt.status, HuntRequest.STATUS_DONE)

    def test_tien_do_hien_trong_hop_thu(self):
        self._patch(self.people[0], {"state": "submitted"})
        body = self.client.get(reverse("hiring-hunts")).json()
        self.assertEqual(body["results"][0]["progress"],
                         {"total": 3, "closed": 1, "submitted": 1})

    def test_lien_he_hien_ngay_trong_danh_sach_nhung_DA_CHE(self):
        """Recruiter vẫn nhận ra hồ sơ ngay trong danh sách — nhưng số bị che.

        Đổi hợp đồng (Master Plan mục 27): danh sách trả về số đã che thay vì số
        đầy đủ. Ý định cũ vẫn giữ — recruiter không phải mở Person 360 mới biết
        hồ sơ nào có liên hệ — nhưng cuộn 500 dòng không còn thu được kho số.
        """
        self.people[0].primary_phone = "+84901234567"
        self.people[0].save()
        body = self.client.get(reverse("hiring-hunts")).json()
        rows = body["results"][0]["people"]
        phones = [p["primary_phone"] for p in rows]
        self.assertNotIn("+84901234567", phones)
        self.assertIn("+84******567", phones)
        self.assertTrue(any(p["contact_masked"] for p in rows))


class OutreachTest(TestCase):
    def setUp(self):
        self.recruiter = make_user("tuyendung", roles.RECRUITER)
        self.need = HiringNeed.objects.create(
            title="Data Analyst", criteria={"skills": ["SQL", "Python"]})
        self.person = Person.objects.create(display_name="Nguyễn Văn An")
        TalentProfile.objects.create(
            person=self.person, current_title="Data Analyst",
            current_company="Ngân hàng ABC", location="Hà Nội",
            years_experience=4, skills=["SQL", "Python", "Excel"])
        self.hunt = HuntRequest.objects.create(hiring_need=self.need)
        self.hunt.people.set([self.person])
        self.client.force_login(self.recruiter)

    def _draft(self, **kwargs):
        return self.client.post(
            reverse("hiring-outreach-draft", args=[self.hunt.pk, self.person.pk]),
            data=json.dumps(kwargs), content_type="application/json")

    def test_chi_neu_ky_nang_TRUNG_voi_yeu_cau(self):
        """Đó là lý do ta gọi họ, và là thứ khiến thư đọc như viết riêng."""
        facts = outreach_module._facts(self.person, self.need)
        khop = [f for f in facts if f.startswith("Kỹ năng khớp")][0]
        self.assertIn("SQL", khop)
        self.assertIn("Python", khop)
        self.assertNotIn("Excel", khop)

    def test_khong_co_du_kien_thi_KHONG_bia(self):
        tron = Person.objects.create(display_name="Người lạ")
        self.assertEqual(outreach_module._facts(tron, self.need), [])

    def test_soan_thu_bang_LLM(self):
        from unittest import mock
        gia = mock.Mock(text="Chào anh An, bên em đang tìm Data Analyst…")
        with mock.patch("hiring.outreach.complete", return_value=gia):
            response = self._draft(channel="message")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Data Analyst", response.json()["draft"])

    def test_LLM_ban_thi_tra_KHUNG_THU_chu_khong_chan(self):
        """Chặn recruiter giữa lúc đang làm việc là cái giá quá đắt cho một lỗi tạm."""
        from unittest import mock
        with mock.patch("hiring.outreach.complete", side_effect=RuntimeError("bận")):
            response = self._draft()
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Nguyễn Văn An", body["draft"])
        self.assertIn("[Viết thêm", body["draft"])
        self.assertTrue(body["error"])

    def test_kenh_la_thi_400(self):
        self.assertEqual(self._draft(channel="fax").status_code, 400)

    def test_thu_duoc_LUU_de_lan_sau_mo_lai_van_thay(self):
        from unittest import mock

        # Đủ dài để không bị bộ lọc "thư cụt" loại — xem `outreach.MIN_CHARS`.
        thu = ("Chào anh An, bên em đang tìm Data Analyst tại MSB và thấy hồ sơ "
               "của anh rất phù hợp. Anh có tiện trao đổi thêm không ạ?")
        gia = mock.Mock(text=thu, truncated=False)
        with mock.patch("hiring.outreach.complete", return_value=gia):
            self._draft()
        candidate = HuntCandidate.objects.get(hunt_request=self.hunt, person=self.person)
        self.assertEqual(candidate.outreach_draft, thu)

    def test_he_thong_KHONG_tu_gui_thu(self):
        """Chỉ ghi nhận recruiter đã gửi — nhắn tin nhân danh MSB cần người quyết."""
        final_draft = "Nội dung recruiter đã kiểm tra và chỉnh sửa trước khi gửi"
        response = self.client.post(
            reverse("hiring-outreach-sent", args=[self.hunt.pk, self.person.pk]),
            data=json.dumps({"channel": "message", "draft": final_draft}),
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        candidate = HuntCandidate.objects.get(hunt_request=self.hunt, person=self.person)
        self.assertIsNotNone(candidate.outreach_sent_at)
        self.assertEqual(candidate.state, HuntCandidate.STATE_CONTACTING)
        self.assertEqual(candidate.outreach_draft, final_draft)
        self.assertTrue(HuntCandidateStatusEvent.objects.filter(
            candidate=candidate, from_state="pending", to_state="contacting").exists())
        self.assertTrue(Interaction.objects.filter(
            person=self.person, action="outreach_sent").exists())
        self.assertEqual(Interaction.objects.get(
            person=self.person, action="outreach_sent").detail["text"], final_draft)

    def test_khong_soan_hoac_ghi_nhan_gui_khi_ung_vien_DNC(self):
        Relationship.objects.create(
            person=self.person, domain="talent", state="do_not_contact",
            do_not_contact=True)
        self.assertEqual(self._draft().status_code, 409)
        response = self.client.post(
            reverse("hiring-outreach-sent", args=[self.hunt.pk, self.person.pk]),
            data=json.dumps({"channel": "message"}), content_type="application/json")
        self.assertEqual(response.status_code, 409)


class MetricsTest(TestCase):
    """Chỉ số mục 50 — thứ sẽ đứng trên slide, nên sai một con số là đắt."""

    def setUp(self):
        self.hm = make_user("truongbophan", roles.RECRUITER)
        self.client.force_login(self.hm)
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")

    def _nguoi(self, ten, ngay_nop):
        SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record",
            entity_key=f"topcv|a|{ten}", content_hash=f"h{ten}",
            payload={"source": "topcv", "account": "a", "cv_id": ten,
                     "fullname": ten, "email": f"{ten}@x.vn",
                     "current_title": "Data Analyst", "skills": "SQL",
                     "city": "Hà Nội", "years_experience": "3 năm",
                     "applied_ts": ngay_nop})
        ingest.resolve_pending()
        return Person.objects.get(display_name=ten)

    def test_chua_co_du_lieu_thi_tra_None_KHONG_tra_0(self):
        """0 đọc như “làm rồi mà kém”; None đọc đúng là “chưa đủ dữ liệu”."""
        body = self.client.get(reverse("hiring-metrics")).json()["metrics"]
        self.assertIsNone(body["historical_reuse"]["value"])
        self.assertIsNone(body["hunt_conversion"]["value"])
        self.assertIn("Chưa", body["historical_reuse"]["detail"])

    def test_tai_su_dung_ho_so_cu_tinh_theo_NGAY_UNG_TUYEN(self):
        """Không phải lúc Hub nhận — đồng bộ cả kho lịch sử trong một buổi sẽ
        khiến mọi hồ sơ trông như vừa nộp hôm nay."""
        cu = self._nguoi("Cũ", "2022-01-15 09:00:00")
        moi = self._nguoi("Mới", timezone.now().strftime("%Y-%m-%d %H:%M:%S"))
        need = HiringNeed.objects.create(title="X")
        for person in (cu, moi):
            Candidacy.objects.create(hiring_need=need, person=person,
                                     state=Candidacy.STATE_SHORTLISTED)

        value = self.client.get(reverse("hiring-metrics")).json()
        chiso = value["metrics"]["historical_reuse"]
        self.assertEqual(chiso["value"], 0.5)
        self.assertIn("1/2", chiso["detail"])

    def test_gop_trung_lap(self):
        self._nguoi("A", "2026-01-01 09:00:00")
        self._nguoi("B", "2026-01-01 09:00:00")
        chiso = self.client.get(reverse("hiring-metrics")).json()["metrics"]
        self.assertEqual(chiso["duplicate_consolidation"]["value"], 1.0)

    def test_muc_chap_nhan_chi_tinh_ho_so_DA_CHAM(self):
        """Hồ sơ chưa ai xem không phải là hồ sơ bị từ chối."""
        need = HiringNeed.objects.create(title="X")
        for i, state in enumerate(["good_fit", "not_fit", "suggested", "suggested"]):
            Candidacy.objects.create(
                hiring_need=need,
                person=Person.objects.create(display_name=f"N{i}"), state=state)
        chiso = self.client.get(reverse("hiring-metrics")).json()["metrics"]
        self.assertEqual(chiso["hm_acceptance"]["value"], 0.5)
        self.assertIn("1/2", chiso["hm_acceptance"]["detail"])

    def test_chot_yeu_cau_san(self):
        need = HiringNeed.objects.create(title="X")
        for i in range(2):
            hunt = HuntRequest.objects.create(hiring_need=need)
            hunt.people.set([Person.objects.create(display_name=f"P{i}")])
        first = HuntCandidate.objects.first()
        first.state = HuntCandidate.STATE_SUBMITTED
        first.save()

        chiso = self.client.get(reverse("hiring-metrics")).json()["metrics"]
        self.assertEqual(chiso["hunt_conversion"]["value"], 0.5)

    def test_thoi_gian_toi_shortlist_dung_TRUNG_VI(self):
        """Một vị trí bị bỏ quên nửa tháng đủ kéo lệch trung bình tới vô nghĩa."""
        for phut in (10, 20, 60 * 24 * 15):
            need = HiringNeed.objects.create(title=f"Vị trí {phut}")
            Candidacy.objects.create(
                hiring_need=need,
                person=Person.objects.create(display_name=f"N{phut}"),
                state=Candidacy.STATE_SHORTLISTED,
                marked_at=need.created_at + timezone.timedelta(minutes=phut))

        chiso = self.client.get(reverse("hiring-metrics")).json()["metrics"]
        self.assertEqual(chiso["time_to_first_shortlist"]["value"], 20)
        self.assertEqual(chiso["time_to_first_shortlist"]["unit"], "phút")

    def test_don_vi_thoi_gian_doc_duoc(self):
        """"0.2 phút" là con số máy nói; chỉ số này sẽ nằm trên slide."""
        from .metrics import _duration
        self.assertEqual(_duration(45), (45, "giây"))
        self.assertEqual(_duration(600), (10, "phút"))
        self.assertEqual(_duration(10800), (3.0, "giờ"))
        self.assertEqual(_duration(86400 * 3), (3.0, "ngày"))


class PermissionTest(TestCase):
    def test_edge_operator_bi_chan(self):
        self.client.force_login(make_user("vanhanh", roles.EDGE_OPERATOR))
        self.assertEqual(self.client.get(reverse("hiring-needs")).status_code, 403)

    def test_chua_dang_nhap_bi_chan(self):
        self.assertIn(self.client.get(reverse("hiring-needs")).status_code, (401, 403))

    def test_rm_duoc_vao_worklist_ung_vien_theo_dinh_huong_dung_chung(self):
        self.client.force_login(make_user("rm", roles.RB_SALES))
        self.assertEqual(self.client.get(reverse("hiring-hunts")).status_code, 200)


class OutreachTruncationTest(TestCase):
    """Thư cụt phải bị loại, không được đưa cho recruiter bấm gửi."""

    def setUp(self):
        self.need = HiringNeed.objects.create(title="Data Analyst")
        self.person = Person.objects.create(display_name="Nguyễn Văn An")

    def _draft(self, text, truncated):
        from unittest import mock
        from ai.providers import Completion
        from hiring import outreach

        gia = Completion(text=text, provider="f", model="f", truncated=truncated)
        with mock.patch("hiring.outreach.complete", return_value=gia):
            return outreach.draft(self.person, self.need)

    def test_thu_bi_cat_thi_dung_khung_thu(self):
        text, error = self._draft("Chào anh An, tôi liên hệ vì được biết anh đang", True)
        self.assertIn("[Viết thêm", text)
        self.assertIn("cắt", error)

    def test_thu_qua_ngan_cung_bi_loai(self):
        """Model trả vài chữ rồi dừng cũng là hỏng, dù không báo finish_reason."""
        text, _ = self._draft("Chào anh,", False)
        self.assertIn("[Viết thêm", text)

    def test_thu_hoan_chinh_thi_giu_nguyen(self):
        thu = ("Chào anh An, bên em đang tìm Data Analyst tại MSB và thấy hồ sơ "
               "của anh rất phù hợp. Anh có tiện trao đổi thêm không ạ?")
        text, error = self._draft(thu, False)
        self.assertEqual(text, thu)
        self.assertEqual(error, "")

    def test_tat_buoc_suy_nghi_khi_soan_thu(self):
        """Bước suy nghĩ ăn vào chính hạn mức token của câu trả lời."""
        from unittest import mock
        from ai.providers import Completion
        from hiring import outreach

        goi = {}

        def fake(messages, **kwargs):
            goi.update(kwargs)
            return Completion(text="x" * 100, provider="f", model="f")

        with mock.patch("hiring.outreach.complete", side_effect=fake):
            outreach.draft(self.person, self.need)
        self.assertEqual(goi.get("reasoning_effort"), "none")
