# -*- coding: utf-8 -*-
"""Ghi đè giá trị tntalent_domains / msb_domains bị stringify nhiều lớp.

Bản cũ lưu ``str(list)`` nên mỗi lần admin lưu lại bọc thêm một lớp
``['...']`` vào CSDL (xem docstring ``EmailOtpSettings.normalize_domains``).
``normalize_domains`` đã cứu được lúc ĐỌC, nhưng chuỗi trong CSDL vẫn bẩn —
migration này ghi lại đúng dạng phẳng ``"tntalent.vn"`` / ``"msb.com.vn"`` một
lần cho xong, dùng cùng thuật toán bóc tách.
"""
import re

from django.db import migrations

_DOMAIN_RE = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


def _normalize(value):
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if any(marker in text for marker in ("[", "]", "'", '"', "\\")):
        items = sorted(set(_DOMAIN_RE.findall(text)))
    else:
        items = sorted({part.strip().lstrip("@")
                        for part in text.replace(";", ",").replace("\n", ",").split(",")
                        if part.strip().lstrip("@")})
    return ",".join(items)


def normalize_domains(apps, schema_editor):
    Settings = apps.get_model("accounts", "EmailOtpSettings")
    for row in Settings.objects.all():
        dirty = []
        for field in ("tntalent_domains", "msb_domains"):
            clean = _normalize(getattr(row, field))
            if clean != getattr(row, field):
                setattr(row, field, clean)
                dirty.append(field)
        if dirty:
            row.save(update_fields=dirty)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_remove_externalidentity_uq_active_external_identity_subject_and_more"),
    ]

    operations = [
        migrations.RunPython(normalize_domains, migrations.RunPython.noop),
    ]
