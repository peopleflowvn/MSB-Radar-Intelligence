# -*- coding: utf-8 -*-
"""Kỹ năng `person_activity` (surfaces: talent, general — xem lý do ở toolset.py).

Ghim ranh giới nghiệp vụ: Recruiter không thấy hoạt động bán lẻ, RM thuần không
thấy hoạt động tuyển dụng (đúng Person 360), liên hệ trong chữ tự do bị che, và
kỹ năng không bao giờ chạm tới người ngoài danh sách người dùng vừa chọn.

RM gọi qua surface "talent" (RB_SALES có MODULE_TALENT — quyết định 19/08/2026),
KHÔNG qua "prospect": Growth Radar (`/rb/ask/`) dùng `rb/answer/act.py` code-
driven riêng, không đi qua sổ đăng ký tool này.
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from accounts import roles
from people.models import Interaction, Person, Relationship, Signal

from . import toolset


def _user(name, *role_names):
    u = User.objects.create_user(name, password="x")
    for role in role_names:
        u.groups.add(Group.objects.get(name=role))
    return u


class PersonActivityToolTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles.ensure_groups()

    def setUp(self):
        now = timezone.now()
        self.person = Person.objects.create(display_name="Nguyễn Văn Hoạt Động")
        Relationship.objects.create(person=self.person, domain="talent", state="contacted",
                                    owner="rec", next_action="Gọi lại 0912345678 thứ Hai")
        Relationship.objects.create(person=self.person, domain="rb", state="lead",
                                    owner="rm", do_not_contact=True)
        Interaction.objects.create(person=self.person, domain="talent", action="note_added",
                                   actor_name="rec", occurred_at=now)
        Interaction.objects.create(person=self.person, domain="talent", action="viewed",
                                   actor_name="rec", occurred_at=now)
        Interaction.objects.create(person=self.person, domain="rb", action="rb_called",
                                   actor_name="rm", occurred_at=now)
        Signal.objects.create(person=self.person, domain="rb", signal_type="home_purchase",
                              confidence=0.7, observed_at=now, evidence={"quote": "mua nhà"})
        self.recruiter = _user("rec-act", roles.RECRUITER)
        self.rm = _user("rm-act", roles.RB_SALES)
        self.manager = _user("mgr-act", roles.MANAGER)

    def _run(self, user, surface="talent", **args):
        return toolset.dispatch("person_activity", {"person_id": self.person.pk, **args},
                                user=user, surface=surface)

    def test_recruiter_sees_only_talent_and_contacts_are_masked(self):
        out = self._run(self.recruiter)
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.result["domains"], ["talent"])
        self.assertEqual([r["domain"] for r in out.result["relationships"]], ["talent"])
        self.assertNotIn("0912345678", out.result["relationships"][0]["next_action"])
        actions = [e["action"] for e in out.result["timeline"]]
        self.assertEqual(actions, ["note_added"])            # không 'viewed', không rb

    def test_recruiter_cannot_ask_for_rb_domain(self):
        out = self._run(self.recruiter, domain="rb")
        self.assertFalse(out.ok)
        self.assertIn("nghiệp vụ", out.error)

    def test_rm_only_sees_rb_like_person_360(self):
        out = self._run(self.rm)
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.result["domains"], ["rb"])
        self.assertTrue(out.result["relationships"][0]["do_not_contact"])
        self.assertEqual({e["action"] for e in out.result["timeline"]},
                         {"rb_called", "home_purchase"})

    def test_manager_sees_both(self):
        out = self._run(self.manager)
        self.assertEqual(out.result["domains"], ["rb", "talent"])

    def test_selection_guard_applies(self):
        out = toolset.dispatch("person_activity", {"person_id": self.person.pk},
                               user=self.recruiter, surface="talent",
                               context={"selected_person_ids": [self.person.pk + 1]})
        self.assertFalse(out.ok)
        self.assertIn("vừa chọn", out.error)

    def test_not_registered_for_prospect_surface(self):
        """Growth có act.py code-driven riêng; đăng ký ở đây không tự nhiên có
        đường gọi tới — xem comment ở `toolset.py`."""
        self.assertNotIn("person_activity",
                         {t["function"]["name"]
                          for t in toolset.agent_toolset_for("prospect", self.manager)})
