# -*- coding: utf-8 -*-
"""Gieo từ điển tìm kiếm từ hằng số trong code vào bảng quản trị được.

Hành vi không đổi: nội dung gieo đúng bằng `SEED_VOCABULARY` mà compiler vẫn
dùng khi bảng trống. Cái đổi là từ đây nghiệp vụ thêm được alias mà không cần
một lần deploy, và mỗi truy vấn ghi lại `vocabulary_version` đã dùng.
"""
from django.db import migrations

SEED = {
    "location": {
        "ha noi": ["ha noi", "hanoi", "hn"],
        "ho chi minh": ["ho chi minh", "hochiminh", "hcm", "saigon", "sg",
                        "tp hcm", "sai gon"],
    },
    "title": {
        "data analyst": ["data analyst", "chuyen vien phan tich du lieu",
                         "phan tich du lieu"],
        "relationship manager": ["relationship manager", "quan he khach hang", "rm"],
        "accountant": ["accountant", "ke toan"],
    },
    "education": {"college": ["college", "cao dang"]},
}


def seed(apps, schema_editor):
    SearchVocabulary = apps.get_model("talent", "SearchVocabulary")
    for kind, rows in SEED.items():
        for canonical, aliases in rows.items():
            SearchVocabulary.objects.update_or_create(
                kind=kind, canonical=canonical,
                defaults={"aliases": aliases, "enabled": True, "version": 1,
                          "updated_by": "migration.0018", "note": "gieo từ code"})


def unseed(apps, schema_editor):
    SearchVocabulary = apps.get_model("talent", "SearchVocabulary")
    # Chỉ xoá đúng phần do migration gieo; alias do người vận hành thêm phải còn.
    SearchVocabulary.objects.filter(updated_by="migration.0018").delete()


class Migration(migrations.Migration):
    dependencies = [("talent", "0017_search_vocabulary")]
    operations = [migrations.RunPython(seed, unseed)]
