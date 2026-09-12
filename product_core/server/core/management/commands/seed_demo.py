# -*- coding: utf-8 -*-
"""Dựng dữ liệu demo cho Hero Flow (Master Plan mục 49).

    python manage.py seed_demo            # thêm vào dữ liệu đang có
    python manage.py seed_demo --reset    # xoá dữ liệu demo cũ rồi dựng lại

Vì sao đây là một management command chứ không phải một script để đâu đó:

  • **Ngày demo mà máy chủ trắng dữ liệu thì phải dựng lại trong một câu lệnh.**
    Một script nằm trong thư mục tạm của người viết là thứ không ai chạy được
    lúc 8 giờ sáng ngày Hackday.
  • Nó chạy trong test được, nên bài kiểm thử Hero Flow dùng đúng dữ liệu mà
    demo dùng — không có hai bộ dữ liệu lệch nhau.

Dữ liệu đi qua **đúng đường thật**: SourceRecord → `people.ingest` → Person +
TalentProfile. Không tạo thẳng Person, vì như thế là bỏ qua chính phần phân giải
định danh mà dự án tồn tại để làm.
"""
import hashlib

from accounts import roles
from core import documents
from core.models import Edge, SourceRecord
from core.serializers import PROMOTED_COLUMNS
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction
from hiring.models import HiringNeed
from people import ingest, resolution
from people.models import Person

EDGE_ID = "demo-edge"
ACCOUNT = "ta@msb.com.vn"
MAT_KHAU = "mat-khau-demo-1234"

NGUOI_DUNG = [
    ("admin", roles.ADMIN, True),
    ("tuyendung", roles.RECRUITER, False),
    ("truongbophan", roles.HIRING_MANAGER, False),
    ("sales", roles.RB_SALES, False),
    ("vanhanh", roles.EDGE_OPERATOR, False),
    ("quanly", roles.MANAGER, False),
]

# (nguồn, mã CV, họ tên, email, sđt, chức danh, kỹ năng, nơi ở, số năm, ngày nộp)
#
# Nguyễn Văn An cố ý xuất hiện 3 lần qua 3 nguồn và 3 năm, mỗi lần thiếu một
# mảnh liên hệ khác nhau — đó là ca phân giải định danh đáng xem nhất: gộp được
# nhờ email ở lần 1–2 và nhờ số điện thoại ở lần 1–3.
UNG_VIEN = [
    ("topcv", "101", "Nguyễn Văn An", "an.nguyen@example.com", "0901234567",
     "Data Analyst", "SQL, Excel", "Hà Nội", "2 năm", "2023-03-15 09:00:00"),
    ("vietnamworks", "102", "Nguyễn Văn An", "an.nguyen@example.com", "",
     "Senior Data Analyst", "SQL, Python, Airflow", "Hà Nội", "4 năm",
     "2025-06-20 09:00:00"),
    ("careerviet", "103", "Nguyễn Văn An", "", "+84 90 123 4567",
     "Senior Data Analyst", "SQL, Python, Power BI", "Hà Nội", "4 năm",
     "2026-08-01 09:00:00"),

    ("topcv", "201", "Trần Thị Bình", "binh.tran@example.com", "0987654321",
     "Business Analyst", "SQL, Tableau, Agile", "Hồ Chí Minh", "8 năm",
     "2026-07-10 09:00:00"),
    ("itviec", "301", "Lê Văn Cường", "cuong.le@example.com", "0911111111",
     "Backend Engineer", "Java, Spring Boot, Kafka", "Hà Nội", "10 năm",
     "2026-06-05 09:00:00"),
    ("vietnamworks", "401", "Phạm Thu Dung", "dung.pham@example.com", "0922222222",
     "Data Engineer", "Python, Spark, Airflow", "Hà Nội", "5 năm",
     "2026-08-12 09:00:00"),
    ("careerviet", "501", "Hoàng Minh Đức", "duc.hoang@example.com", "0933333333",
     "Chuyên viên Phân tích Tín dụng", "SQL, Credit Risk, Excel", "Hà Nội", "6 năm",
     "2026-05-18 09:00:00"),
    ("topcv", "601", "Vũ Thị Én", "en.vu@example.com", "0944444444",
     "Data Analyst", "Python, SQL, Power BI", "Đà Nẵng", "3 năm",
     "2026-08-14 09:00:00"),
    ("itviec", "701", "Đỗ Quang Phúc", "phuc.do@example.com", "0955555555",
     "Data Scientist", "Python, SQL, Machine Learning", "Hà Nội", "7 năm",
     "2026-07-28 09:00:00"),
    ("vietnamworks", "801", "Bùi Thanh Giang", "giang.bui@example.com", "0966666666",
     "BI Developer", "Power BI, SQL, DAX", "Hà Nội", "4 năm",
     "2026-08-05 09:00:00"),
]


def _cv_text(payload):
    """Nội dung CV giả, đủ để bộ suy diễn hồ sơ có cái mà đọc.

    Nội dung phải KHÁC nhau giữa các lượt ứng tuyển của cùng một người — trùng
    nội dung thì kho đánh địa chỉ theo nội dung sẽ gộp lại thành một tài liệu,
    và mất luôn phần thú vị nhất: CV của họ đã đổi qua từng năm.
    """
    return "\n".join([
        f"HỒ SƠ ỨNG VIÊN — {payload.get('fullname', '')}",
        f"Nộp qua {payload.get('source', '')} ngày {payload.get('applied_ts', '')}",
        "",
        f"Vị trí ứng tuyển: {payload.get('position', '')}",
        f"Kinh nghiệm: {payload.get('years_experience', '')}",
        f"Kỹ năng: {payload.get('skills', '')}",
        f"Nơi ở: {payload.get('city', '')}",
        f"Học vấn: {payload.get('education', '')}",
        f"Công ty gần nhất: {payload.get('last_company', '')}",
        "",
        f"Liên hệ: {payload.get('email', '')} · {payload.get('phone', '')}",
    ])


class Command(BaseCommand):
    help = "Dựng dữ liệu demo cho Hero Flow (tài khoản theo vai trò + ứng viên mẫu)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Xoá dữ liệu demo cũ (ứng viên, vị trí tuyển, yêu cầu săn) "
                 "trước khi dựng lại.")
        parser.add_argument("--quiet", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        self.quiet = options["quiet"]

        if options["reset"]:
            self._reset()

        self._users()
        edge = self._edge()
        self._candidates(edge)

        stats = ingest.resolve_pending()
        self._say(f"Đã phân giải {stats['processed']} bản ghi "
                  f"thành {Person.objects.count()} người "
                  f"({stats[resolution.MATCHED]} lượt gộp vào người đã có).")

        self._documents()
        self._say(f"Tài khoản: {', '.join(u for u, _, _ in NGUOI_DUNG)} — mật khẩu «{MAT_KHAU}»")

    # --- các bước ---

    def _reset(self):
        """Xoá dữ liệu demo cũ. KHÔNG dùng `flush`.

        Người chạy lệnh này gần như luôn đang có dữ liệu khác trong cùng CSDL,
        và một lệnh seed xoá sạch CSDL là cái bẫy. Nên chỉ xoá theo `edge_id`
        của Edge demo, cộng những gì trở thành vỏ rỗng sau đó.
        """
        deleted, _ = SourceRecord.objects.filter(edge__edge_id=EDGE_ID).delete()
        Edge.objects.filter(edge_id=EDGE_ID).delete()
        # Người không còn nguồn nào thì không còn lý do tồn tại.
        orphans, _ = Person.objects.filter(source_records__isnull=True).delete()

        # Và vị trí tuyển cũng phải dọn. Xoá người xong thì `Candidacy` bị xoá
        # theo, để lại những vị trí rỗng không ứng viên — trạng thái đó tệ hơn
        # cả việc giữ nguyên. Ngoài ra đây chính là chỗ các vị trí sinh ra lúc
        # diễn tập nằm lại, và chúng sẽ hiện trên màn hình ngày demo.
        needs, _ = HiringNeed.objects.all().delete()

        self._say(f"Đã xoá {deleted} bản ghi nguồn, {orphans} bản ghi liên quan "
                  f"và {needs} bản ghi tuyển dụng.")

    def _users(self):
        roles.ensure_groups()
        for username, role, is_super in NGUOI_DUNG:
            user, _ = User.objects.get_or_create(username=username)
            user.set_password(MAT_KHAU)
            user.is_staff = is_super
            user.is_superuser = is_super
            user.save()
            user.groups.set([Group.objects.get(name=role)])

    def _edge(self):
        edge, _ = Edge.objects.get_or_create(
            edge_id=EDGE_ID, defaults={"label": "Máy demo phòng TA"})
        return edge

    def _candidates(self, edge):
        for (src, cv_id, ten, email, phone, chuc_danh, ky_nang,
             tp, so_nam, ngay) in UNG_VIEN:
            entity_key = f"{src}|{ACCOUNT}|{cv_id}"
            payload = {
                "source": src, "account": ACCOUNT, "cv_id": cv_id,
                "fullname": ten, "email": email, "phone": phone,
                "position": chuc_danh, "current_title": chuc_danh,
                "skills": ky_nang, "city": tp,
                "years_experience": so_nam,
                "last_company": "Ngân hàng ABC",
                "education": "Đại học Kinh tế Quốc dân",
                "applied_ts": ngay,
            }
            SourceRecord.objects.update_or_create(
                edge=edge, entity_type="source_record", entity_key=entity_key,
                defaults={
                    "content_hash": f"demo-{entity_key}",
                    "payload": payload,
                    # Nhấc các trường ra thành cột y như `SyncRecordSerializer`
                    # làm trên đường đồng bộ thật. Bỏ bước này thì dữ liệu demo
                    # KHÁC dữ liệu thật ở đúng chỗ khó nhận ra nhất: mọi màn
                    # hình nhóm theo nguồn sẽ hiện "Không rõ nguồn", kể cả
                    # bảng thu thập dùng để trình diễn.
                    #
                    # Dùng chung `PROMOTED_COLUMNS` chứ không chép lại danh
                    # sách: hai chỗ chép tay sẽ lệch nhau ngay lần thêm cột sau.
                    **{name: str(payload.get(name) or "")[:limit]
                       for name, limit in PROMOTED_COLUMNS.items()},
                })
        self._say(f"Đã nạp {len(UNG_VIEN)} lượt ứng tuyển.")

    def _documents(self):
        """Gắn file CV cho từng lượt ứng tuyển.

        Không có bước này thì hồ sơ hiện “0 phiên bản CV”, và mất luôn thứ đáng
        xem nhất của phần tài liệu: **cùng một người, CV đổi qua từng năm.**
        Nguyễn Văn An nộp 3 lần với 3 nội dung khác nhau → 3 phiên bản, xếp theo
        ngày ứng tuyển chứ không theo ngày Hub nhận.

        Đi qua đúng `core.documents`, giống hệt đường Edge tải file lên: máy chủ
        tự băm lại nội dung và tự khử trùng lặp theo mã băm.
        """
        made = 0
        for record in SourceRecord.objects.filter(edge__edge_id=EDGE_ID,
                                                  person__isnull=False):
            payload = record.payload or {}
            text = _cv_text(payload)
            noi_dung = text.encode("utf-8")
            digest = hashlib.sha256(noi_dung).hexdigest()
            ten_file = f"CV_{payload.get('cv_id')}_{payload.get('source')}.txt"

            try:
                documents.ingest_metadata(record, {
                    "sha256": digest, "document_type": "cv",
                    "source": payload.get("source", ""), "filename": ten_file,
                    "mime_type": "text/plain", "file_size": len(noi_dung),
                    "applied_ts": payload.get("applied_ts"),
                    # Bóc tách text là việc của Edge; ở đây gửi kèm luôn để tìm
                    # kiếm toàn văn có dữ liệu, đúng như Edge thật vẫn gửi.
                    "parsed_text": text,
                })
                documents.store_file(record.person, digest, noi_dung, ten_file)
                made += 1
            except documents.DocumentError as exc:
                self._say(f"Bỏ qua tài liệu của {record.entity_key}: {exc}")

        self._say(f"Đã nạp {made} file CV.")

    def _say(self, message):
        if not self.quiet:
            self.stdout.write(message)
