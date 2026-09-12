# -*- coding: utf-8 -*-
"""Nhận webhook Resend/Svix và lưu inbound mail sau khi xác minh chữ ký."""
import base64
import binascii
import hashlib
import hmac
import json
import logging
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.utils import timezone

from .email_otp import RESEND_USER_AGENT
from .models import ResendInboxEmail

log = logging.getLogger(__name__)
MAX_BODY_CHARS = 500_000


def verify_svix(raw_body, headers, secret):
    """Svix signed-content: {svix-id}.{svix-timestamp}.{raw payload}."""
    msg_id = headers.get("svix-id", "")
    timestamp = headers.get("svix-timestamp", "")
    signatures = headers.get("svix-signature", "")
    if not (msg_id and timestamp and signatures and secret.startswith("whsec_")):
        return False
    try:
        ts = int(timestamp)
        if abs(int(timezone.now().timestamp()) - ts) > 300:
            return False
        key = base64.urlsafe_b64decode(secret[6:] + "===")
        expected = base64.b64encode(hmac.new(
            key, f"{msg_id}.{timestamp}.".encode("utf-8") + raw_body,
            hashlib.sha256).digest()).decode("ascii")
    except (ValueError, TypeError, binascii.Error):
        return False
    return any(version == "v1" and hmac.compare_digest(signature, expected)
               for item in signatures.split() if "," in item
               for version, signature in [item.split(",", 1)])


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_and_store_inbound(email_id, api_key, fallback):
    """Webhook inbound không mang body nên lấy một lần từ Receiving API."""
    request = Request(f"https://api.resend.com/emails/receiving/{email_id}",
                      headers={"Authorization": f"Bearer {api_key}",
                               "User-Agent": RESEND_USER_AGENT})
    try:
        with urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        log.warning("Không lấy được nội dung inbound %s: %s", email_id, exc)
        return None
    email = data.get("data", data)
    return ResendInboxEmail.objects.update_or_create(email_id=email_id, defaults={
        "sender": str(email.get("from") or fallback.get("from") or "")[:254],
        "recipients": email.get("to") or fallback.get("to") or [],
        "subject": str(email.get("subject") or fallback.get("subject") or "")[:500],
        "text_body": str(email.get("text") or "")[:MAX_BODY_CHARS],
        "html_body": str(email.get("html") or "")[:MAX_BODY_CHARS],
        "headers": email.get("headers") or {},
        "attachments": email.get("attachments") or fallback.get("attachments") or [],
        "received_at": _parse_time(email.get("created_at") or fallback.get("created_at")),
    })[0]
