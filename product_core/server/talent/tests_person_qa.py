# -*- coding: utf-8 -*-
"""Kiểm thử Hỏi & đáp AI có phạm vi cho một người cụ thể (Person 360).

Ba điều được canh kỹ nhất, giống hệt tinh thần `tests_ai.py`:

1. **LLM không được đọc hồ sơ thô** — chỉ nhận đúng những FACT được gom sẵn.
2. **RM thuần không được lộ dữ liệu CV/pipeline tuyển dụng** qua Q&A — đúng
   như đã bị lọc khỏi chính trang Person 360.
3. **Mất AI thì báo lỗi rõ ràng**, không im lặng trả "".
"""
import json
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from people.models import Person
from rb.models import PRODUCT_CREDIT_CARD, ProductInterest, RBProfile
from django.utils import timezone

from . import person_qa
from .models import TalentProfile
from .tests_fakes import FakeLLM


class FactsTest(TestCase):
    """`_facts()` là ranh giới duy nhất giữa hồ sơ thật và những gì LLM thấy."""

    def setUp(self):
        self.person = Person.objects.create(display_name="Nguyễn Văn An",
                                            primary_email="an@x.vn",
                                            primary_phone="+84901234567")
        self.talent = TalentProfile.objects.create(
            person=self.person, current_title="Senior Data Analyst",
            current_company="Ngân hàng ABC", years_experience=4.0,
            location="Hà Nội", skills=["SQL", "Python"],
            expected_salary="30-40 triệu", summary="Có kinh nghiệm BI.")
        self.rb = RBProfile.objects.create(
            person=self.person, occupation="Trưởng phòng kinh doanh",
            employer="Công ty XYZ", segment=RBProfile.SEGMENT_AFFLUENT)
        ProductInterest.objects.create(
            profile=self.rb, product=PRODUCT_CREDIT_CARD, confidence=0.8,
            observed_at=timezone.now())

    def test_bao_gom_nghiep_vu_tuyen_dung_khi_duoc_phep(self):
        facts = person_qa._facts(self.person, include_recruiting=True)
        self.assertEqual(facts["nghiep_vu_tuyen_dung"]["chuc_danh_hien_tai"],
                         "Senior Data Analyst")
        self.assertIn("SQL", facts["nghiep_vu_tuyen_dung"]["ky_nang"])

    def test_AN_nghiep_vu_tuyen_dung_khoi_rm_thuan(self):
        """Đúng dữ liệu mà `person_detail` đã ẩn khỏi RM thuần."""
        facts = person_qa._facts(self.person, include_recruiting=False)
        self.assertNotIn("nghiep_vu_tuyen_dung", facts)

    def test_van_co_nghiep_vu_khach_hang_du_co_hay_khong_include_recruiting(self):
        for include in (True, False):
            facts = person_qa._facts(self.person, include_recruiting=include)
            self.assertEqual(facts["nghiep_vu_khach_hang"]["nghe_nghiep"],
                             "Trưởng phòng kinh doanh")
            self.assertEqual(
                facts["nghiep_vu_khach_hang"]["quan_tam_san_pham"][0]["product"],
                PRODUCT_CREDIT_CARD)

    def test_khong_co_rb_profile_thi_khong_co_khoa_nghiep_vu_khach_hang(self):
        rieng = Person.objects.create(display_name="Chỉ ứng viên")
        TalentProfile.objects.create(person=rieng, current_title="BA")
        facts = person_qa._facts(rieng, include_recruiting=True)
        self.assertNotIn("nghiep_vu_khach_hang", facts)


class AskTest(TestCase):
    def setUp(self):
        self.person = Person.objects.create(display_name="Nguyễn Văn An")
        TalentProfile.objects.create(person=self.person, current_title="Data Analyst",
                                     skills=["SQL"])

    def test_tra_loi_dung_tu_LLM(self):
        llm = FakeLLM("Người này có kỹ năng SQL, phù hợp vị trí Data Analyst.")
        result = person_qa.ask(self.person, "Người này mạnh gì?", complete_fn=llm)
        self.assertIn("SQL", result["answer"])
        self.assertEqual(result["provider"], "fake")
        self.assertFalse(result["error"])

    def test_LLM_CHI_nhan_FACT_khong_nhan_ho_so_tho(self):
        """`person` (Model instance) không được lọt vào nội dung gửi LLM."""
        llm = FakeLLM("...")
        person_qa.ask(self.person, "Người này mạnh gì?", complete_fn=llm)
        sent = json.dumps(llm.calls[0]["messages"], ensure_ascii=False)
        payload = json.loads(llm.calls[0]["messages"][-1]["content"])
        self.assertIn("ho_so", payload)
        self.assertEqual(payload["ho_so"]["nghiep_vu_tuyen_dung"]["ky_nang"], ["SQL"])
        self.assertNotIn("<Person:", sent)

    def test_cau_hoi_rong_bi_tu_choi_khong_goi_LLM(self):
        llm = FakeLLM("không nên được gọi")
        result = person_qa.ask(self.person, "   ", complete_fn=llm)
        self.assertTrue(result["error"])
        self.assertEqual(llm.calls, [])

    def test_mat_AI_thi_bao_loi_ro_rang(self):
        llm = FakeLLM(raises=RuntimeError("nhà cung cấp sập"))
        result = person_qa.ask(self.person, "Người này thế nào?", complete_fn=llm)
        self.assertEqual(result["answer"], "")
        self.assertIn("sập", result["error"])

    def test_lich_su_hoi_dap_truoc_duoc_dua_vao_prompt(self):
        llm = FakeLLM("...")
        history = [{"question": "Người này ở đâu?", "answer": "Ở Hà Nội."}]
        person_qa.ask(self.person, "Vậy có phù hợp vị trí ở HCM không?",
                      history=history, complete_fn=llm)
        system_messages = " ".join(
            m["content"] for m in llm.calls[0]["messages"] if m["role"] == "system")
        self.assertIn("LỊCH SỬ HỎI ĐÁP TRƯỚC ĐÓ", system_messages)
        self.assertIn("Ở Hà Nội", system_messages)


class PersonAskApiTest(TestCase):
    def setUp(self):
        from accounts import roles
        roles.ensure_groups()
        self.user = User.objects.create_user("recruiter", password="mat-khau-dai-1")
        self.user.groups.add(Group.objects.get(name=roles.RECRUITER))
        self.client.force_login(self.user)
        self.person = Person.objects.create(display_name="Nguyễn Văn An")
        TalentProfile.objects.create(person=self.person, current_title="Data Analyst")

    def _post(self, body):
        return self.client.post(
            reverse("talent-person-ask", args=[self.person.pk]),
            data=json.dumps(body), content_type="application/json")

    def test_thieu_cau_hoi_thi_400(self):
        self.assertEqual(self._post({"question": "  "}).status_code, 400)

    def test_chua_dang_nhap_bi_chan(self):
        self.client.logout()
        self.assertIn(self._post({"question": "x"}).status_code, (401, 403))

    def test_vai_tro_khong_hop_le_bi_chan(self):
        from accounts import roles
        self.user.groups.clear()
        self.user.groups.add(Group.objects.get(name=roles.EDGE_OPERATOR))
        self.assertEqual(self._post({"question": "x"}).status_code, 403)

    def test_tra_loi_thanh_cong(self):
        with self._mock_llm("Ứng viên phù hợp vị trí Data Analyst."):
            response = self._post({"question": "Người này phù hợp vị trí gì?"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Data Analyst", response.json()["answer"])

    def test_rm_thuan_khong_lo_du_lieu_tuyen_dung(self):
        """RM đặt câu hỏi thì `person_qa.ask()` phải được gọi với
        `include_recruiting=False` — đúng như `person_detail` đã ẩn CV/pipeline."""
        from accounts import roles
        self.user.groups.clear()
        self.user.groups.add(Group.objects.get(name=roles.RB_SALES))
        from unittest import mock as _mock
        with _mock.patch("talent.views.person_qa.ask",
                        return_value={"answer": "ok", "error": "", "provider": "", "model": ""}) as call:
            self._post({"question": "x"})
        self.assertFalse(call.call_args.kwargs["include_recruiting"])

    def test_lich_su_qua_dai_bi_cat_bot(self):
        from unittest import mock as _mock
        history = [{"question": f"h{i}", "answer": f"a{i}"} for i in range(20)]
        with _mock.patch("talent.views.person_qa.ask",
                        return_value={"answer": "ok", "error": "", "provider": "", "model": ""}) as call:
            self._post({"question": "x", "history": history})
        self.assertLessEqual(len(call.call_args.kwargs["history"]), person_qa.MAX_HISTORY_TURNS)

    def _mock_llm(self, text):
        from unittest import mock as _mock
        return _mock.patch("talent.person_qa.complete", FakeLLM(text))
