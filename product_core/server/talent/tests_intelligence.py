import hashlib
import io
import json

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import roles
from people.models import Document, Person

from .intelligence_views import issue_scope_token


@override_settings(
    INTELLIGENCE_SERVICE_TOKEN="service-secret",
    INTELLIGENCE_INDEX_SCOPE_TOKEN="index-secret",
    INTELLIGENCE_SCOPE_MAX_AGE_SECONDS=300,
)
class IntelligenceBridgeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("recruiter", password="secret")
        Group.objects.get_or_create(name=roles.RECRUITER)[0].user_set.add(self.user)
        self.person = Person.objects.create(display_name="Nguyen Van A", is_applicant=True)
        self.document = Document.objects.create(
            person=self.person, document_type="cv", source="topcv", sha256="a" * 64,
            parsed_text="Python SQL banking", text_length=18,
            parse_status=Document.PARSE_DONE)

    @property
    def service_headers(self):
        return {"HTTP_AUTHORIZATION": "Bearer service-secret"}

    def test_feed_requires_both_private_tokens(self):
        url = reverse("intelligence-document-feed")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(url, **self.service_headers).status_code, 404)

    def test_feed_matches_v2_contract_and_cursor_is_replayable(self):
        second = Document.objects.create(
            person=self.person, document_type="cv", source="manual", sha256="b" * 64,
            parsed_text="Second CV", text_length=9, parse_status=Document.PARSE_DONE)
        response = self.client.get(
            reverse("intelligence-document-feed"), {"limit": 1},
            **self.service_headers, HTTP_X_RADAR_SCOPE_TOKEN="index-secret")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["has_more"])
        self.assertEqual(len(body["events"]), 1)
        event = body["events"][0]
        self.assertEqual(event["operation"], "upsert")
        self.assertEqual(event["content_hash"], hashlib.sha256(
            event["text"].encode("utf-8")).hexdigest())

        response = self.client.get(
            reverse("intelligence-document-feed"),
            {"limit": 1, "cursor": body["next_cursor"]},
            **self.service_headers, HTTP_X_RADAR_SCOPE_TOKEN="index-secret")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][0]["document_id"], str(second.pk))

    def test_feed_rejects_bad_cursor(self):
        response = self.client.get(
            reverse("intelligence-document-feed"), {"cursor": "not-a-cursor"},
            **self.service_headers, HTTP_X_RADAR_SCOPE_TOKEN="index-secret")
        self.assertEqual(response.status_code, 400)

    def test_feed_never_emits_empty_text_or_source(self):
        self.document.source = ""
        self.document.save(update_fields=["source"])
        response = self.client.get(
            reverse("intelligence-document-feed"), **self.service_headers,
            HTTP_X_RADAR_SCOPE_TOKEN="index-secret")
        event = response.json()["events"][0]
        self.assertEqual(event["source"], "radar")
        self.assertTrue(event["text"])

    def test_event_id_changes_when_document_owner_changes_without_text_change(self):
        url = reverse("intelligence-document-feed")
        response = self.client.get(
            url, **self.service_headers, HTTP_X_RADAR_SCOPE_TOKEN="index-secret")
        first_event = response.json()["events"][0]

        replacement = Person.objects.create(display_name="Tran Thi B", is_applicant=True)
        self.document.person = replacement
        self.document.save(update_fields=["person", "updated_at"])
        response = self.client.get(
            url, **self.service_headers, HTTP_X_RADAR_SCOPE_TOKEN="index-secret")
        changed_event = response.json()["events"][0]

        self.assertEqual(first_event["content_hash"], changed_event["content_hash"])
        self.assertNotEqual(first_event["event_id"], changed_event["event_id"])
        self.assertEqual(changed_event["person_id"], str(replacement.pk))

    def test_feed_emits_tombstone_after_document_is_deleted(self):
        url = reverse("intelligence-document-feed")
        first = self.client.get(
            url, **self.service_headers,
            HTTP_X_RADAR_SCOPE_TOKEN="index-secret").json()
        document_id = first["events"][0]["document_id"]
        self.document.delete()

        response = self.client.get(
            url, {"cursor": first["next_cursor"]}, **self.service_headers,
            HTTP_X_RADAR_SCOPE_TOKEN="index-secret")
        self.assertEqual(response.status_code, 200)
        event = response.json()["events"][0]
        self.assertEqual(event["operation"], "delete")
        self.assertEqual(event["document_id"], document_id)
        self.assertIsNone(event["text"])

    def test_hiding_person_emits_tombstone_and_reactivation_emits_upsert(self):
        url = reverse("intelligence-document-feed")
        initial = self.client.get(
            url, **self.service_headers,
            HTTP_X_RADAR_SCOPE_TOKEN="index-secret").json()
        self.person.is_applicant = False
        self.person.save(update_fields=["is_applicant", "updated_at"])
        hidden = self.client.get(
            url, {"cursor": initial["next_cursor"]}, **self.service_headers,
            HTTP_X_RADAR_SCOPE_TOKEN="index-secret").json()
        self.assertEqual(hidden["events"][0]["operation"], "delete")

        self.person.is_applicant = True
        self.person.save(update_fields=["is_applicant", "updated_at"])
        visible = self.client.get(
            url, {"cursor": hidden["next_cursor"]}, **self.service_headers,
            HTTP_X_RADAR_SCOPE_TOKEN="index-secret").json()
        self.document.refresh_from_db()
        self.assertTrue(visible["events"], {
            "hidden_cursor": hidden["next_cursor"],
            "document_updated_at": self.document.updated_at.isoformat(),
        })
        self.assertEqual(visible["events"][0]["operation"], "upsert")

    def test_evidence_uses_existing_user_cv_permission(self):
        token = issue_scope_token(self.user)
        response = self.client.get(
            reverse("intelligence-evidence-document", args=[self.document.pk]),
            **self.service_headers, HTTP_X_RADAR_SCOPE_TOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["person_id"], str(self.person.pk))

        rb = User.objects.create_user("rm", password="secret")
        Group.objects.get_or_create(name=roles.RB_SALES)[0].user_set.add(rb)
        response = self.client.get(
            reverse("intelligence-evidence-document", args=[self.document.pk]),
            **self.service_headers, HTTP_X_RADAR_SCOPE_TOKEN=issue_scope_token(rb))
        self.assertEqual(response.status_code, 404)

    def test_logged_in_user_can_request_short_lived_scope(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("intelligence-scope"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["scope_token"])

    def test_user_without_talent_module_cannot_request_scope(self):
        outsider = User.objects.create_user("outsider", password="secret")
        self.client.force_login(outsider)
        self.assertEqual(self.client.post(reverse("intelligence-scope")).status_code, 404)

    def test_v2_can_validate_scope_without_receiving_user_data(self):
        response = self.client.post(
            reverse("intelligence-scope-validate"), **self.service_headers,
            HTTP_X_RADAR_SCOPE_TOKEN=issue_scope_token(self.user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"allowed": True, "scope": "all_applicants"})

    def test_v2_scope_validation_does_not_require_browser_csrf_cookie(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        response = csrf_client.post(
            reverse("intelligence-scope-validate"), **self.service_headers,
            HTTP_X_RADAR_SCOPE_TOKEN=issue_scope_token(self.user))
        self.assertEqual(response.status_code, 200)

    def test_non_pii_reconciliation_audit_has_expected_counts(self):
        output = io.StringIO()
        call_command("audit_intelligence_data", "--json", stdout=output)
        audit = json.loads(output.getvalue())
        self.assertEqual(audit["documents"]["eligible_for_intelligence"], 1)
        self.assertEqual(audit["people"]["active_applicants"], 1)
        self.assertEqual(audit["users"]["active"], 1)
        self.assertNotIn("display_name", output.getvalue())

    def test_merged_or_non_applicant_document_is_hidden(self):
        self.person.is_applicant = False
        self.person.save(update_fields=["is_applicant"])
        token = issue_scope_token(self.user)
        response = self.client.get(
            reverse("intelligence-evidence-document", args=[self.document.pk]),
            **self.service_headers, HTTP_X_RADAR_SCOPE_TOKEN=token)
        self.assertEqual(response.status_code, 404)
