# -*- coding: utf-8 -*-
"""Hero Flow — đường demo, chạy đầu tới cuối (Master Plan mục 49).

```text
Hiring Manager → "Tôi cần..." → AI Talent Search → People Database
→ Top Recommendations → Why → Shortlist → Nhờ Recruiter săn → Recruiter
```

Từng mảnh đã có bài kiểm thử riêng. Bài này kiểm thứ khác: **cả chuỗi có nối
được với nhau không**. Đó là loại lỗi mà kiểm thử theo app không bắt được — mỗi
app đúng phần của mình, nhưng dữ liệu app trước trả ra không vừa với thứ app sau
cần, và chỉ vỡ ra lúc bấm thật.

Và đó chính là thứ sẽ chạy trước ban giám khảo. Nếu chỉ giữ được một bài kiểm
thử trong cả kho, giữ bài này.

Dùng đúng `manage.py seed_demo` mà ngày demo dùng — không dựng bộ dữ liệu thứ
hai để rồi hai bộ lệch nhau lúc nào không biết.
"""
import json
from unittest import mock

from ai.providers import Completion
from core.asgi_stream import drain_to_bytes
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from hiring.models import Candidacy, HuntCandidate, HuntRequest
from people.models import Interaction, Person, Relationship

CAU_HOI = "Tôi cần Data Analyst ở Hà Nội, biết SQL và Python, ít nhất 3 năm"

# LLM giả: trả đúng khuôn `talent.hiring_need` mong đợi. Dùng giả chứ không gọi
# thật vì bài này kiểm ĐƯỜNG NỐI giữa các bước, không kiểm chất lượng mô hình —
# và vì khoá miễn phí bị giới hạn tốc độ, gọi thật sẽ làm bài kiểm thử chập chờn.
TIEU_CHI = json.dumps({
    "title": "Data Analyst",
    "skills": ["SQL", "Python"],
    "location": "Hà Nội",
    "min_years": 3,
})

GIAI_THICH = json.dumps({
    "summary": "Khớp cả hai kỹ năng bắt buộc và đúng nơi ở.",
    "inference": "Hồ sơ mới cập nhật nên khả năng còn quan tâm cơ hội mới.",
    "next_action": "Gọi điện trong tuần này.",
})


def _completion(text):
    """Dùng `Completion` thật chứ không `Mock`.

    Mock tự sinh thuộc tính con cho mọi thứ được truy cập, nên chỗ nào đọc nhầm
    thuộc tính vẫn "chạy" — và ở đây nó còn đệ quy vô tận khi lớp ghi nhật ký
    dò các trường token. Đối tượng thật thì đọc sai là nổ ngay.
    """
    return Completion(text=text, provider="fake", model="fake-1",
                      prompt_tokens=10, completion_tokens=20)


def fake_complete(messages, **kwargs):
    """Trả JSON hợp với từng bước, nhận biết qua `task`."""
    task = kwargs.get("task", "")
    if task == "outreach_draft":
        return _completion("Chào anh An, bên em đang tìm Data Analyst tại MSB…")
    if task == "explain":
        return _completion(GIAI_THICH)
    return _completion(TIEU_CHI)


class HeroFlowTest(TransactionTestCase):
    """`TransactionTestCase`, không phải `TestCase`: bài này lái qua đúng
    đường SSE thật (`to_async_iter`, core/asgi_stream.py), và đường đó chạy
    generator trên một luồng nền riêng (bắt buộc để stream thật qua ASGI).
    `TestCase` bọc mỗi test trong MỘT transaction trên luồng chính — một luồng
    khác cố ghi CSDL giữa lúc đó sẽ thấy "database table is locked" (SQLite)
    hoặc không thấy dữ liệu (Postgres, tuỳ isolation level). Không có
    `setUpTestData` ở đây vì `TransactionTestCase` không hỗ trợ nó (bù lại,
    seed chạy lại mỗi test — chấp nhận được, đây vốn đã là bài kiểm tích hợp
    chậm nhất trong kho)."""

    def setUp(self):
        call_command("seed_demo", quiet=True)
        self.hm = User.objects.get(username="tuyendung")
        self.recruiter = User.objects.get(username="tuyendung")

    def _post(self, name, args=None, body=None):
        return self.client.post(reverse(name, args=args or []),
                                data=json.dumps(body or {}),
                                content_type="application/json")

    def _fake_answer(self, question, **kwargs):
        """Answer Engine giả — bài này kiểm đường nối, không kiểm mô hình."""
        from talent.answer.engine import AnswerResult
        an = Person.objects.get(display_name__contains="Nguyễn Văn An")
        result = AnswerResult(
            text="Nguyễn Văn An là hồ sơ phù hợp nhất: biết SQL và Python [1].",
            sources=[{"n": 1, "person_id": an.pk, "name": an.display_name,
                      "document_id": 0, "ordinal": 0, "snippet": "SQL, Python"}],
            people=[{"person_id": an.pk, "name": an.display_name,
                     "why": "khớp kỹ năng", "attributes": {}, "citations": [1]}],
            provider="fake", model="fake-1")
        yield {"type": "answer", "text": result.text}
        yield {"type": "done", "result": result}

    def test_seed_gop_dung_nguoi_ung_tuyen_nhieu_lan(self):
        """Ba lượt ứng tuyển của cùng một người phải ra MỘT hồ sơ."""
        an = Person.objects.filter(display_name__contains="Nguyễn Văn An")
        self.assertEqual(an.count(), 1)
        self.assertEqual(an.first().source_records.count(), 3)

    def test_hero_flow_chay_tu_dau_toi_cuoi(self):
        # --- 1. HM hỏi bằng lời ---
        #
        # Đường trả lời nay là Answer Engine (`/talent/ask/`), không còn trả tiêu
        # chí + thẻ ứng viên. Bài này kiểm ĐƯỜNG NỐI giữa các bước nên chỉ cần
        # câu trả lời có nêu đúng người; chất lượng câu trả lời do
        # `talent/tests_answer.py` và lệnh `answer_eval` lo.
        self.client.force_login(self.hm)
        with mock.patch("ai.router.complete", side_effect=fake_complete), \
                mock.patch("talent.answer.engine.stream_answer",
                           side_effect=self._fake_answer):
            response = self.client.post(
                reverse("talent-ask"),
                data=json.dumps({"q": CAU_HOI, "conversation_id": "hero"}),
                content_type="application/json")
            body = drain_to_bytes(response.streaming_content).decode("utf-8")
        self.assertEqual(response.status_code, 200)

        # --- 2. Câu trả lời phải nêu đúng người và dẫn được nguồn ---
        self.assertIn("Nguyễn Văn An", body)
        self.assertIn("event: citations", body)

        # --- 3. HM tạo vị trí từ chính nhu cầu đó ---
        response = self._post("hiring-needs",
                              body={"title": "Data Analyst", "department": "Khối Dữ liệu"})
        self.assertEqual(response.status_code, 201)
        need_id = response.json()["id"]
        self.client.patch(reverse("hiring-need", args=[need_id]),
                          data=json.dumps({"criteria": json.loads(TIEU_CHI)}),
                          content_type="application/json")

        # --- 4. Đề xuất ứng viên ---
        suggestions = self.client.get(
            reverse("hiring-suggestions", args=[need_id])).json()
        self.assertGreaterEqual(suggestions["count"], 4)
        names = [row["display_name"] for row in suggestions["results"]]
        self.assertEqual(names[0], "Nguyễn Văn An")

        # --- 5. HM chấm rồi bắt hệ thống học lại ---
        for row in suggestions["results"][:2]:
            self._post("hiring-mark", [need_id],
                       {"person_id": row["id"], "state": "good_fit"})
        for row in suggestions["results"][-2:]:
            self._post("hiring-mark", [need_id],
                       {"person_id": row["id"], "state": "not_fit"})

        response = self._post("hiring-calibrate", [need_id])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["applied"])
        self.assertTrue(response.json()["insights"])

        # --- 6. Shortlist ---
        for row in suggestions["results"][:2]:
            self._post("hiring-mark", [need_id],
                       {"person_id": row["id"], "state": "shortlisted"})
        self.assertEqual(
            Candidacy.objects.filter(hiring_need_id=need_id,
                                     state=Candidacy.STATE_SHORTLISTED).count(), 2)

        # --- 7. Nhờ recruiter săn ---
        response = self._post("hiring-request-hunt", [need_id],
                              {"message": "Ưu tiên người ở Hà Nội"})
        self.assertEqual(response.status_code, 201)
        hunt_id = response.json()["id"]
        self.assertEqual(len(response.json()["people"]), 2)

        # --- 8. Recruiter thấy việc trong hộp thư ---
        self.client.force_login(self.recruiter)
        inbox = self.client.get(reverse("hiring-hunts"), {"open": "1"}).json()
        self.assertEqual(len(inbox["results"]), 1)
        self.assertEqual(inbox["results"][0]["progress"]["total"], 2)

        # Số điện thoại phải có sẵn — recruiter bấm gọi ngay, không phải mở
        # thêm màn hình nào.
        self.assertTrue(any(p["primary_phone"]
                            for p in inbox["results"][0]["people"]))

        # --- 9. Nhận việc, soạn thư, liên hệ ---
        self.client.patch(reverse("hiring-hunt", args=[hunt_id]),
                          data=json.dumps({"status": "accepted"}),
                          content_type="application/json")

        person_id = inbox["results"][0]["people"][0]["person_id"]
        with mock.patch("hiring.outreach.complete", side_effect=fake_complete):
            response = self._post("hiring-outreach-draft", [hunt_id, person_id],
                                  {"channel": "message"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("MSB", response.json()["draft"])

        self._post("hiring-outreach-sent", [hunt_id, person_id],
                   {"channel": "message"})

        # --- 10. Chốt: một người chuyển cho HM, một người trả về kho ---
        self.client.patch(
            reverse("hiring-hunt-candidate", args=[hunt_id, person_id]),
            data=json.dumps({"state": "submitted"}), content_type="application/json")

        other_id = inbox["results"][0]["people"][1]["person_id"]
        self.client.patch(
            reverse("hiring-hunt-candidate", args=[hunt_id, other_id]),
            data=json.dumps({"state": "returned",
                             "return_reason": "Đang trong hợp đồng 2 năm"}),
            content_type="application/json")

        # Xong hết người thì yêu cầu tự đóng.
        hunt = HuntRequest.objects.get(pk=hunt_id)
        self.assertEqual(hunt.status, HuntRequest.STATUS_DONE)

        # --- 11. Mọi thứ để lại dấu vết trên hồ sơ con người ---
        actions = set(Interaction.objects.filter(person_id=person_id)
                      .values_list("action", flat=True))
        self.assertIn("hunt_requested", actions)
        self.assertIn("outreach_sent", actions)
        self.assertIn("hunt_submitted", actions)

        # Và người khác mở hồ sơ ra là thấy quan hệ đang ở đâu.
        self.assertEqual(Relationship.objects.get(person_id=person_id).state, "ready")
        self.assertEqual(Relationship.objects.get(person_id=other_id).state,
                         "nurturing")

    def test_ly_do_tra_ve_khong_bi_mat(self):
        """Vòng lặp chỉ khép kín nếu lần sau có người đọc được vì sao đã bỏ."""
        self.client.force_login(self.hm)
        need = self._post("hiring-needs", body={"title": "Data Analyst"}).json()
        person = Person.objects.first()
        hunt = HuntRequest.objects.create(hiring_need_id=need["id"],
                                          requested_by=self.hm)
        hunt.people.set([person])

        self.client.force_login(self.recruiter)
        self.client.patch(
            reverse("hiring-hunt-candidate", args=[hunt.pk, person.pk]),
            data=json.dumps({"state": "returned", "return_reason": "Lương lệch 30%"}),
            content_type="application/json")

        candidate = HuntCandidate.objects.get(hunt_request=hunt, person=person)
        self.assertEqual(candidate.return_reason, "Lương lệch 30%")
        interaction = Interaction.objects.get(person=person, action="hunt_returned")
        self.assertEqual(interaction.detail["reason"], "Lương lệch 30%")


class RbHeroFlowTest(TestCase):
    """Hero flow RB — khoảnh khắc mở rộng trong pitch (Master Plan mục 28, 31).

    ```text
    Bài đăng mạng xã hội → ý định → Person → OpportunitySuggestion
    → VÌ SAO BÂY GIỜ → RM nhận → RBOpportunity → ghi nhận kết quả
    ```

    Đây là phần demo diễn ở phút 2:50–3:25, và là phần **mới nhất** nên dễ vỡ
    nhất. Từng mảnh đã có bài kiểm riêng; bài này kiểm cả chuỗi có nối được với
    nhau không — loại lỗi mà kiểm thử theo app không bắt được, vì mỗi app đúng
    phần của mình nhưng dữ liệu app trước trả ra không vừa thứ app sau cần.

    Dùng đúng `seed_demo` mà ngày demo dùng.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", quiet=True)

    def setUp(self):
        self.rm = User.objects.get(username="sales")
        self.client.force_login(self.rm)

    def _post(self, name, args=None, body=None):
        return self.client.post(reverse(name, args=args or []),
                                data=json.dumps(body or {}),
                                content_type="application/json")

    def test_rb_hero_flow_chay_tu_dau_toi_cuoi(self):
        from rb.models import OpportunityOutcome, OpportunitySuggestion, RBOpportunity

        an = Person.objects.get(display_name__contains="Nguyễn Văn An")

        # --- 1. Dán một bài đăng có nhu cầu tài chính ---
        # Số điện thoại phải NẰM TRONG bài: `social/intent.py` cố ý chỉ giữ liên
        # hệ thật sự xuất hiện trong nội dung, vì mô hình đôi khi "hoàn thiện"
        # một số thiếu chữ số — và một số sai gửi tới người vô can là chuyện
        # không sửa lại được.
        phone = an.primary_phone or "0901234567"
        content = f"Em cần vay 500 triệu mua nhà, ai tư vấn giúp em với. LH {phone}"
        intent = json.dumps({
            "talent": 0.0, "rb": 0.9, "labels": ["financial_need"],
            "reason": "Đang hỏi thủ tục vay mua nhà",
            "contacts": {"phone": phone},
        })
        with mock.patch("social.intent.complete",
                        side_effect=lambda *a, **k: _completion(intent)):
            # `save=true`: mặc định endpoint này chỉ «xem thử» và cố ý không
            # ghi gì — một nút xem thử mà âm thầm lưu dữ liệu cá nhân là thứ
            # không nên tồn tại trong hệ thống ngân hàng. Demo thì lưu thật.
            response = self._post("social-analyze", body={
                "content": content,
                "author_name": an.display_name,
                "save": True,
            })
        self.assertIn(response.status_code, (200, 201), response.content[:400])

        # --- 2. Tín hiệu thành ĐỀ XUẤT, chưa phải cơ hội ---
        suggestion = OpportunitySuggestion.objects.filter(person=an).first()
        self.assertIsNotNone(suggestion, "Bài đăng không sinh được đề xuất nào")
        self.assertEqual(
            RBOpportunity.objects.filter(person=an).count(), 0,
            "Chưa ai nhận thì hộp thư cơ hội của RM phải còn trống")

        # --- 3. Đề xuất hiện trên «Cơ hội hôm nay», kèm VÌ SAO BÂY GIỜ ---
        body = self.client.get(reverse("rb-today")).json()
        card = next((row for row in body["results"] if row["id"] == suggestion.pk), None)
        self.assertIsNotNone(card, "Đề xuất không lên được màn hình Cơ hội hôm nay")
        self.assertTrue(card["why"], "Thẻ không có VÌ SAO BÂY GIỜ là thẻ vô dụng")
        self.assertTrue(card["recommended_action"])
        self.assertGreater(card["priority_score"], 0)
        # Che PII áp cho cả màn hình mới nhất, không miễn trừ.
        self.assertNotIn(an.primary_phone or "0901234567",
                         self.client.get(reverse("rb-today")).content.decode())

        # --- 4. RM nhận → sinh cơ hội thật, đúng người bấm nút ---
        accepted = self._post("rb-suggestion-action", args=[suggestion.pk],
                              body={"action": "accept"})
        self.assertEqual(accepted.status_code, 201, accepted.content[:400])
        opportunity = RBOpportunity.objects.get(person=an)
        self.assertEqual(opportunity.assigned_to, self.rm)
        self.assertTrue(opportunity.evidence.get("why"),
                        "Cơ hội phải giữ bằng chứng để sáu tuần sau còn giải thích được")

        # --- 5. Ghi nhận kết quả — khép vòng lặp ---
        outcome = self._post("rb-opportunity-outcomes", args=[opportunity.pk],
                             body={"outcome": "INTERESTED", "channel": "call",
                                   "note": "Hẹn gọi lại thứ Sáu"})
        self.assertEqual(outcome.status_code, 201, outcome.content[:400])
        self.assertEqual(
            OpportunityOutcome.objects.filter(opportunity=opportunity).count(), 1)

    def test_tim_prospect_bang_loi_tra_ve_tieu_chi_va_ket_qua(self):
        """Nhánh RM chủ động hỏi — chạy được cả khi không có AI."""
        def khong_goi_LLM(*_args, **_kwargs):
            raise RuntimeError("không gọi LLM trong bài kiểm hero")

        with mock.patch("rb.prospects.complete", side_effect=khong_goi_LLM), \
             mock.patch("rb.prospects.AGENT_ENDPOINT", ""):
            body = self._post("rb-prospects",
                              body={"q": "Tìm 10 quản lý ở Hà Nội có contact"}).json()

        self.assertEqual(body["criteria"]["seniority"], "manager")
        self.assertEqual(body["criteria_from"], "keyword")
        self.assertEqual(body["count"], len(body["results"]))

    def test_so_lieu_thu_thap_khac_0_de_len_slide(self):
        """Ba con số của phần mở đầu demo phải có thật, không phải 0."""
        from core import capture

        data = capture.consolidation()
        self.assertGreater(data["source_records"], 0)
        self.assertGreater(data["multi_source_people"], 0,
                           "Mất khoảnh khắc «ba lượt hồ sơ, một con người»")
        self.assertGreaterEqual(data["max_sources_for_one_person"], 3)
