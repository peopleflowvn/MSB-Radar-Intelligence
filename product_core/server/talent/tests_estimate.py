# -*- coding: utf-8 -*-
"""`talent.estimate` + kỹ năng `estimate_profile_gaps`.

Ghim: field CV đã ghi trực tiếp không bao giờ bị ghi đè bằng số đoán; ba suy
luận (kinh nghiệm ← năm tốt nghiệp, năm tốt nghiệp ↔ năm sinh) đều tất định,
và mọi kết quả trả về có nhãn "ước tính" — không lẫn với fact có bằng chứng.
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from accounts import roles
from ai import toolset
from intel.models import ExtractedFact
from people.models import Person
from talent import estimate
from talent.models import TalentProfile


def _fact(person, field, value, fp):
    return ExtractedFact.objects.create(
        person=person, field=field, raw_value=value, normalized_value=value,
        source_kind=ExtractedFact.SOURCE_AI, fingerprint=fp,
        status=ExtractedFact.STATUS_ACCEPTED, is_current=True)


class ExtractYearTest(TestCase):
    def test_doc_nam_tu_nhieu_dinh_dang(self):
        self.assertEqual(estimate.extract_year("2015"), 2015)
        self.assertEqual(estimate.extract_year(2015), 2015)
        self.assertEqual(estimate.extract_year("12/05/1995"), 1995)
        self.assertEqual(estimate.extract_year("sinh năm 1995"), 1995)

    def test_khong_doc_duoc_thi_none(self):
        self.assertIsNone(estimate.extract_year(""))
        self.assertIsNone(estimate.extract_year(None))
        self.assertIsNone(estimate.extract_year("không rõ"))

    def test_nam_phi_ly_bi_loai(self):
        future_year = timezone.now().year + 1
        self.assertIsNone(estimate.extract_year(str(future_year)))
        self.assertIsNone(estimate.extract_year("1900"))


class EstimateFormulasTest(TestCase):
    def test_kinh_nghiem_tu_nam_tot_nghiep(self):
        current_year = timezone.now().year
        grad_year = current_year - 6
        self.assertEqual(estimate.estimate_years_experience(str(grad_year)), 6)

    def test_kinh_nghiem_none_khi_khong_doc_duoc_nam(self):
        self.assertIsNone(estimate.estimate_years_experience("chưa rõ"))

    def test_nam_tot_nghiep_tu_nam_sinh(self):
        self.assertEqual(estimate.estimate_graduation_year("1995"),
                         1995 + estimate.TYPICAL_GRADUATION_AGE)

    def test_nam_sinh_tu_nam_tot_nghiep(self):
        self.assertEqual(estimate.estimate_birth_year("2017"),
                         2017 - estimate.TYPICAL_GRADUATION_AGE)


class EstimateProfileGapsToolTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles.ensure_groups()

    def setUp(self):
        self.recruiter = User.objects.create_user("rec-est", password="x")
        self.recruiter.groups.add(Group.objects.get(name=roles.RECRUITER))

    def test_uoc_tinh_kinh_nghiem_tu_nam_tot_nghiep(self):
        person = Person.objects.create(display_name="Ứng viên thiếu kinh nghiệm")
        _fact(person, "graduation_year", "2018", "fp-grad")

        names = {t["function"]["name"] for t in toolset.agent_toolset_for("talent", self.recruiter)}
        self.assertIn("estimate_profile_gaps", names)

        out = toolset.dispatch("estimate_profile_gaps", {"person_id": person.pk},
                               user=self.recruiter, surface="talent")
        self.assertTrue(out.ok, out.error)
        self.assertIsNone(out.result["known"]["years_experience"])
        self.assertEqual(out.result["known"]["graduation_year"], 2018)
        estimated = out.result["estimated"]["years_experience"]
        self.assertEqual(estimated["value"], timezone.now().year - 2018)
        self.assertIn("năm tốt nghiệp", estimated["basis"])
        self.assertEqual(estimated["method"], "formula")
        self.assertIn("KHÔNG PHẢI dữ liệu có bằng chứng", out.result["disclaimer"])

    def test_khong_ghi_de_field_cv_da_co(self):
        """CV đã ghi rõ số năm kinh nghiệm — tool KHÔNG được đè bằng số đoán."""
        person = Person.objects.create(display_name="Ứng viên đã có kinh nghiệm")
        TalentProfile.objects.create(person=person, years_experience=9)
        _fact(person, "graduation_year", "2018", "fp-grad2")

        out = toolset.dispatch("estimate_profile_gaps", {"person_id": person.pk},
                               user=self.recruiter, surface="talent")
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.result["known"]["years_experience"], 9)
        self.assertNotIn("years_experience", out.result["estimated"])

    def test_uoc_tinh_hai_chieu_nam_sinh_nam_tot_nghiep(self):
        person = Person.objects.create(display_name="Ứng viên chỉ có năm sinh")
        _fact(person, "date_of_birth", "1995", "fp-dob")

        out = toolset.dispatch("estimate_profile_gaps", {"person_id": person.pk},
                               user=self.recruiter, surface="talent")
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.result["known"]["birth_year"], 1995)
        self.assertEqual(out.result["estimated"]["graduation_year"]["value"],
                         1995 + estimate.TYPICAL_GRADUATION_AGE)

    def test_khong_du_moc_thoi_gian_thi_bao_ro(self):
        person = Person.objects.create(display_name="Ứng viên không có mốc nào")
        out = toolset.dispatch("estimate_profile_gaps", {"person_id": person.pk},
                               user=self.recruiter, surface="talent")
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.result["estimated"], {})
        self.assertTrue(out.result["note"])

    def test_selection_guard_applies(self):
        person = Person.objects.create(display_name="Ứng viên guard")
        out = toolset.dispatch("estimate_profile_gaps", {"person_id": person.pk},
                               user=self.recruiter, surface="talent",
                               context={"selected_person_ids": [person.pk + 1]})
        self.assertFalse(out.ok)
        self.assertIn("vừa chọn", out.error)

    def test_denied_without_talent_module(self):
        person = Person.objects.create(display_name="Ứng viên RBAC")
        plain = User.objects.create_user("plain-est", password="x")
        out = toolset.dispatch("estimate_profile_gaps", {"person_id": person.pk},
                               user=plain, surface="talent")
        self.assertFalse(out.ok)


class ModelReasoningTierTest(TestCase):
    """Tầng 2 — model TỰ LUẬN khi công thức tất định không đủ mốc thời gian.

    Thí điểm theo yêu cầu người dùng: chỉ tool này được phép "tự luận" thay vì
    gọi hàm cố định — ghim rằng nó (a) chỉ chạy khi công thức bó tay, (b) không
    bao giờ tự ý gọi model khi không có dữ kiện gián tiếp nào để suy, (c) luôn
    gắn method='model_reasoning' + confidence khác hẳn method='formula', và
    (d) lỗi model không làm hỏng cả tool — chỉ mất phần làm giàu.
    """
    @classmethod
    def setUpTestData(cls):
        roles.ensure_groups()

    def setUp(self):
        self.recruiter = User.objects.create_user("rec-reason", password="x")
        self.recruiter.groups.add(Group.objects.get(name=roles.RECRUITER))

    def test_tu_luan_tu_chuc_danh_va_ky_nang(self):
        from unittest.mock import patch

        from ai.adapter import ModelResponse

        person = Person.objects.create(display_name="Ứng viên chỉ có chức danh")
        TalentProfile.objects.create(
            person=person, current_title="Senior Backend Developer",
            skills=["Java", "Spring"])

        with patch("ai.adapter.get_adapter") as g:
            g.return_value.complete.return_value = ModelResponse(
                text='{"years_experience": {"value": 5, "reasoning": '
                     '"Chức danh Senior thường ứng 5+ năm", "confidence": "trung bình"}, '
                     '"graduation_year": {"value": null}, "birth_year": {"value": null}}',
                provider="p", model="m")
            out = toolset.dispatch("estimate_profile_gaps", {"person_id": person.pk},
                                   user=self.recruiter, surface="talent")

        self.assertTrue(out.ok, out.error)
        entry = out.result["estimated"]["years_experience"]
        self.assertEqual(entry["value"], 5)
        self.assertEqual(entry["method"], "model_reasoning")
        self.assertEqual(entry["confidence"], "trung bình")
        self.assertNotIn("graduation_year", out.result["estimated"])
        self.assertNotIn("birth_year", out.result["estimated"])

    def test_khong_goi_model_khi_khong_co_du_kien_gian_tiep(self):
        """Person không có TalentProfile lẫn fact nào — không đủ căn cứ để tự
        luận, nên KHÔNG được gọi model (không có gì để đưa vào prompt)."""
        from unittest.mock import patch

        person = Person.objects.create(display_name="Ứng viên trắng hồ sơ")
        with patch("ai.adapter.get_adapter") as g:
            out = toolset.dispatch("estimate_profile_gaps", {"person_id": person.pk},
                                   user=self.recruiter, surface="talent")
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.result["estimated"], {})
        g.assert_not_called()

    def test_loi_model_khong_lam_hong_ca_tool(self):
        from unittest.mock import patch

        person = Person.objects.create(display_name="Ứng viên model lỗi")
        TalentProfile.objects.create(person=person, current_title="Kế toán")

        with patch("ai.adapter.get_adapter") as g:
            g.return_value.complete.side_effect = RuntimeError("model timeout")
            out = toolset.dispatch("estimate_profile_gaps", {"person_id": person.pk},
                                   user=self.recruiter, surface="talent")
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.result["estimated"], {})

    def test_cong_thuc_uu_tien_hon_khong_goi_model_tu_luan_cho_field_da_co(self):
        """Còn năm tốt nghiệp thì kinh nghiệm tính bằng CÔNG THỨC — model tự
        luận chỉ chạm field mà công thức thật sự bó tay."""
        from unittest.mock import patch

        from ai.adapter import ModelResponse

        person = Person.objects.create(display_name="Ứng viên có năm tốt nghiệp")
        TalentProfile.objects.create(person=person, current_title="Dev")
        _fact(person, "graduation_year", "2018", "fp-grad3")

        with patch("ai.adapter.get_adapter") as g:
            g.return_value.complete.return_value = ModelResponse(
                text='{"birth_year": {"value": 1990, "confidence": "thấp"}}',
                provider="p", model="m")
            out = toolset.dispatch("estimate_profile_gaps", {"person_id": person.pk},
                                   user=self.recruiter, surface="talent")

        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.result["estimated"]["years_experience"]["method"], "formula")
        # birth_year: công thức CÓ THỂ tính từ graduation_year rồi (known["birth_year"]
        # is None nhưng known["graduation_year"] có) — nên đây cũng là formula, model
        # tự luận không được gọi cho field này.
        self.assertEqual(out.result["estimated"]["birth_year"]["method"], "formula")
        g.assert_not_called()
