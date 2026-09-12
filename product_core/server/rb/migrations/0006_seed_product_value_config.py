# -*- coding: utf-8 -*-
"""Giá trị mặc định cho 9 nhóm sản phẩm bán lẻ.

Đây là **thang định tính**, không phải số tài chính đã kiểm chứng của MSB — xem
docstring `ProductValueConfig`. Xếp bậc theo quy mô giao dịch và độ dài quan hệ
khách hàng mà nhóm sản phẩm đó thường mang lại, là thứ đúng về mặt thứ tự kể cả
khi con số tuyệt đối chưa có:

    Rất cao   vay mua nhà        — giao dịch lớn nhất, quan hệ dài nhất
    Cao       đầu tư, tài khoản lương, vay mua xe
              (tài khoản lương kéo theo cả doanh nghiệp, không chỉ một người)
    Trung bình bảo hiểm, thẻ tín dụng, vay tiêu dùng, tiết kiệm
    Thấp      ngoại tệ           — giá trị mỗi lượt nhỏ, thường một lần

`value_weight` để 0 ở tất cả: khi khối bán lẻ cung cấp số biên lợi nhuận thật,
nhập vào trường đó qua trang quản trị và nó sẽ tự động thắng thang định tính,
không cần sửa code hay chạy lại migration.
"""
from django.db import migrations

DEFAULTS = [
    # (product, band, strategic_weight, business_priority)
    ("mortgage", "very_high", 1.0, 90),
    ("investment", "high", 1.0, 80),
    ("payroll", "high", 1.0, 75),
    ("auto_loan", "high", 1.0, 70),
    ("insurance", "medium", 1.0, 60),
    ("credit_card", "medium", 1.0, 55),
    ("consumer_loan", "medium", 1.0, 50),
    ("savings", "medium", 1.0, 45),
    ("fx", "low", 1.0, 30),
]


def seed(apps, _schema_editor):
    Config = apps.get_model("rb", "ProductValueConfig")
    for product, band, strategic, priority in DEFAULTS:
        # `get_or_create` chứ không `create`: migration phải chạy được trên cả
        # cơ sở dữ liệu mà quản trị viên đã tự nhập cấu hình trước đó.
        Config.objects.get_or_create(
            product=product,
            defaults={"value_band": band, "strategic_weight": strategic,
                      "business_priority": priority, "value_weight": 0.0,
                      "active": True})


def unseed(apps, _schema_editor):
    Config = apps.get_model("rb", "ProductValueConfig")
    Config.objects.filter(product__in=[row[0] for row in DEFAULTS]).delete()


class Migration(migrations.Migration):

    dependencies = [("rb", "0005_productvalueconfig_opportunityoutcome_and_more")]

    operations = [migrations.RunPython(seed, unseed)]
