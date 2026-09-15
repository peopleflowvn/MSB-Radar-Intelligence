# -*- coding: utf-8 -*-
"""
Cơ sở dữ liệu SQLite - nơi lưu chính thức toàn bộ thông tin ứng viên.

Vì sao dùng SQLite thay cho Excel/CSV:
  • Ghi từng dòng tức thì, không phải ghi lại cả file (Excel càng nhiều dòng càng chậm).
  • Tìm kiếm / lọc trên hàng chục nghìn dòng gần như tức thì nhờ chỉ mục.
  • An toàn khi máy tắt đột ngột (mỗi thao tác là một giao dịch).
  • Không kẹt khi người dùng đang mở file Excel.
  • Có sẵn trong Python, không cần cài thêm gì.
Excel / CSV trở thành chức năng XUẤT dữ liệu khi cần gửi cho người khác.

Khoá chính là (nguồn, mã CV) nên nhiều nguồn tuyển dụng khác nhau
(TopCV, VietnamWorks, ITviec...) có thể dùng chung một cơ sở dữ liệu.
"""
import os
import json
import random
import re
import sqlite3
import unicodedata
import threading
import time
from datetime import datetime, timedelta

DONE = "Đã tải"

# Cột hiển thị trên giao diện: (tên cột trong DB, nhãn tiếng Việt, độ rộng)
DISPLAY_COLUMNS = [
    ("fullname",   "Họ tên",           190),
    ("email",      "Email",            210),
    ("phone",      "Số điện thoại",    115),
    ("position",   "Vị trí ứng tuyển", 300),
    ("applied_at", "Ngày ứng tuyển",   125),
    ("status",     "Trạng thái",       105),
    ("source",     "Nguồn",            80),
    ("account",    "Tài khoản",        200),
    ("dl_status",  "Tình trạng tải",   150),
    ("filename",   "File CV",          230),
]

# Thứ tự cột khi xuất ra Excel/CSV
EXPORT_COLUMNS = [
    ("source", "Nguồn"), ("account", "Tài khoản tải"), ("cv_id", "Mã CV"), ("fullname", "Họ tên"),
    ("email", "Email"), ("phone", "Số điện thoại"),
    ("cv_emails", "Email khác trong CV"), ("cv_phones", "SĐT khác trong CV"),
    ("position", "Vị trí ứng tuyển"),
    ("campaign_id", "Mã tin"), ("applied_at", "Ngày ứng tuyển"),
    ("apply_source", "Loại hồ sơ / Nguồn chi tiết"), ("status", "Trạng thái"),
    ("gender", "Giới tính"), ("birth_year", "Năm sinh"), ("marital_status", "Tình trạng hôn nhân"),
    ("experience", "Kinh nghiệm"), ("years_experience", "Số năm kinh nghiệm"),
    ("address", "Địa chỉ"), ("city", "Tỉnh/Thành phố"), ("district", "Quận/Huyện"),
    ("desired_location", "Nơi làm việc mong muốn"),
    ("current_title", "Chức danh gần nhất"), ("job_level", "Cấp bậc"),
    ("desired_level", "Cấp bậc mong muốn"), ("desired_position", "Ngành nghề/Vị trí mong muốn"),
    ("job_type", "Hình thức làm việc mong muốn"),
    ("education", "Học vấn"), ("foreign_language", "Ngoại ngữ"),
    ("expected_salary", "Lương mong muốn"), ("current_salary", "Lương hiện tại"), ("skills", "Kỹ năng"),
    ("last_company", "Công ty gần nhất"), ("labels", "Nhãn CV"), ("note", "Ghi chú"),
    ("candidate_id", "Mã ứng viên"), ("resume_id", "Mã hồ sơ"),
    ("profile_type", "Loại hồ sơ"), ("attachment_name", "Tên file gốc"),
    ("attachment_mime", "Định dạng file"),
    ("is_viewed", "Đã xem"), ("filename", "Tên file CV"),
    ("dl_status", "Tình trạng tải"), ("alerts", "Cảnh báo ứng viên"),
    ("cv_url", "Link xem CV"),
    ("first_seen", "Lần đầu ghi nhận"), ("updated_at", "Cập nhật lúc"),
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    source       TEXT NOT NULL,
    cv_id        TEXT NOT NULL,
    account      TEXT NOT NULL DEFAULT '',
    fullname     TEXT,
    email        TEXT,
    phone        TEXT,
    cv_emails    TEXT,
    cv_phones    TEXT,
    position     TEXT,
    campaign_id  TEXT,
    applied_at   TEXT,
    applied_ts   TEXT,
    apply_source TEXT,
    status       TEXT,
    gender       TEXT,
    birth_year   TEXT,
    marital_status TEXT,
    experience   TEXT,
    years_experience TEXT,
    address      TEXT,
    city         TEXT,
    district     TEXT,
    desired_location TEXT,
    current_title TEXT,
    job_level    TEXT,
    desired_level TEXT,
    desired_position TEXT,
    job_type     TEXT,
    education    TEXT,
    foreign_language TEXT,
    expected_salary TEXT,
    current_salary TEXT,
    skills       TEXT,
    last_company TEXT,
    labels       TEXT,
    note         TEXT,
    candidate_id TEXT,
    resume_id    TEXT,
    profile_type TEXT,
    attachment_name TEXT,
    attachment_mime TEXT,
    source_payload TEXT,
    detail_loaded INTEGER DEFAULT 0,
    is_viewed    INTEGER DEFAULT 0,
    filename     TEXT,
    dl_status    TEXT,
    cv_url       TEXT,
    first_seen   TEXT,
    updated_at   TEXT,
    PRIMARY KEY (source, account, cv_id)
);
CREATE INDEX IF NOT EXISTS ix_name    ON candidates(fullname);
CREATE INDEX IF NOT EXISTS ix_email   ON candidates(email);
CREATE INDEX IF NOT EXISTS ix_phone   ON candidates(phone);
CREATE INDEX IF NOT EXISTS ix_pos     ON candidates(position);
CREATE INDEX IF NOT EXISTS ix_applied ON candidates(applied_ts);
CREATE INDEX IF NOT EXISTS ix_dl      ON candidates(dl_status);
CREATE INDEX IF NOT EXISTS ix_source  ON candidates(source);
CREATE INDEX IF NOT EXISTS ix_src_account ON candidates(source, account);
CREATE INDEX IF NOT EXISTS ix_src_dl  ON candidates(source, dl_status);
CREATE INDEX IF NOT EXISTS ix_src_applied ON candidates(source, applied_ts DESC);
CREATE INDEX IF NOT EXISTS ix_pos_applied ON candidates(position, applied_ts DESC);
CREATE INDEX IF NOT EXISTS ix_src_pos_applied ON candidates(source, position, applied_ts DESC);
CREATE INDEX IF NOT EXISTS ix_src_account_dl_applied
ON candidates(source, account, dl_status, applied_ts DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS candidate_search USING fts5(
    text, tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS candidate_search_ai AFTER INSERT ON candidates BEGIN
  INSERT INTO candidate_search(rowid,text) VALUES (new.rowid,
    COALESCE(new.fullname,'')||' '||COALESCE(new.email,'')||' '||COALESCE(new.phone,'')||' '||
    COALESCE(new.position,'')||' '||COALESCE(new.skills,'')||' '||COALESCE(new.note,'')||' '||
    COALESCE(new.labels,'')||' '||COALESCE(new.address,'')||' '||COALESCE(new.city,'')||' '||
    COALESCE(new.current_title,'')||' '||COALESCE(new.last_company,'')||' '||
    COALESCE(new.cv_id,'')||' '||COALESCE(new.campaign_id,'')||' '||
    COALESCE(new.candidate_id,'')||' '||COALESCE(new.resume_id,'')||' '||
    COALESCE(new.source,'')||' '||COALESCE(new.account,'')||' '||COALESCE(new.status,'')||' '||
    COALESCE(new.apply_source,''));
END;
CREATE TRIGGER IF NOT EXISTS candidate_search_ad AFTER DELETE ON candidates BEGIN
  DELETE FROM candidate_search WHERE rowid=old.rowid;
END;
CREATE TRIGGER IF NOT EXISTS candidate_search_au AFTER UPDATE ON candidates BEGIN
  DELETE FROM candidate_search WHERE rowid=old.rowid;
  INSERT INTO candidate_search(rowid,text) VALUES (new.rowid,
    COALESCE(new.fullname,'')||' '||COALESCE(new.email,'')||' '||COALESCE(new.phone,'')||' '||
    COALESCE(new.position,'')||' '||COALESCE(new.skills,'')||' '||COALESCE(new.note,'')||' '||
    COALESCE(new.labels,'')||' '||COALESCE(new.address,'')||' '||COALESCE(new.city,'')||' '||
    COALESCE(new.current_title,'')||' '||COALESCE(new.last_company,'')||' '||
    COALESCE(new.cv_id,'')||' '||COALESCE(new.campaign_id,'')||' '||
    COALESCE(new.candidate_id,'')||' '||COALESCE(new.resume_id,'')||' '||
    COALESCE(new.source,'')||' '||COALESCE(new.account,'')||' '||COALESCE(new.status,'')||' '||
    COALESCE(new.apply_source,''));
END;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS app_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT DEFAULT 'system',
    level       TEXT DEFAULT 'INFO',
    message     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_log_ts  ON app_logs(created_at);
CREATE INDEX IF NOT EXISTS ix_log_lvl ON app_logs(level);
CREATE TABLE IF NOT EXISTS candidate_extensions (
    source TEXT NOT NULL, account TEXT NOT NULL DEFAULT '', cv_id TEXT NOT NULL,
    namespace TEXT NOT NULL, schema_version INTEGER NOT NULL DEFAULT 1,
    payload TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (source, account, cv_id, namespace),
    FOREIGN KEY (source, account, cv_id) REFERENCES candidates(source, account, cv_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_ext_namespace_updated
ON candidate_extensions(namespace, updated_at DESC);
CREATE TABLE IF NOT EXISTS candidate_documents (
    source TEXT NOT NULL, account TEXT NOT NULL DEFAULT '', cv_id TEXT NOT NULL,
    filename TEXT NOT NULL DEFAULT '', file_hash TEXT NOT NULL DEFAULT '',
    file_size INTEGER NOT NULL DEFAULT 0, file_mtime_ns INTEGER NOT NULL DEFAULT 0,
    file_format TEXT NOT NULL DEFAULT '', parser_version TEXT NOT NULL DEFAULT '',
    parse_status TEXT NOT NULL DEFAULT 'pending', extraction_method TEXT NOT NULL DEFAULT '',
    full_text TEXT NOT NULL DEFAULT '', text_length INTEGER NOT NULL DEFAULT 0,
    quality_score REAL NOT NULL DEFAULT 0, needs_ocr INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0, parse_error TEXT NOT NULL DEFAULT '',
    queued_at TEXT NOT NULL, started_at TEXT, parsed_at TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY (source, account, cv_id),
    FOREIGN KEY (source, account, cv_id) REFERENCES candidates(source, account, cv_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_documents_queue
ON candidate_documents(parse_status, queued_at);
CREATE INDEX IF NOT EXISTS ix_documents_parsed_at
ON candidate_documents(parsed_at DESC, parse_status);
CREATE INDEX IF NOT EXISTS ix_documents_status_parsed
ON candidate_documents(parse_status, parsed_at DESC);
CREATE INDEX IF NOT EXISTS ix_applied_dl
ON candidates(applied_ts, dl_status);
CREATE TABLE IF NOT EXISTS candidate_contacts (
    source TEXT NOT NULL, account TEXT NOT NULL DEFAULT '', cv_id TEXT NOT NULL,
    email_key TEXT NOT NULL DEFAULT '', phone_key TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source, account, cv_id)
);
CREATE INDEX IF NOT EXISTS ix_contact_email ON candidate_contacts(email_key);
CREATE INDEX IF NOT EXISTS ix_contact_phone ON candidate_contacts(phone_key);
CREATE TRIGGER IF NOT EXISTS candidate_contacts_ai AFTER INSERT ON candidates BEGIN
  INSERT OR REPLACE INTO candidate_contacts(source,account,cv_id,email_key,phone_key) VALUES(
    new.source,new.account,new.cv_id,LOWER(TRIM(COALESCE(new.email,''))),
    REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(new.phone,''),' ',''),'-',''),'.',''),'(',''),')',''),'+',''));
END;
DROP TRIGGER IF EXISTS candidate_contacts_au;
CREATE TRIGGER candidate_contacts_au AFTER UPDATE OF email,phone ON candidates BEGIN
  UPDATE candidate_contacts SET email_key=LOWER(TRIM(COALESCE(new.email,''))),
    phone_key=REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(new.phone,''),' ',''),'-',''),'.',''),'(',''),')',''),'+','')
    WHERE source=new.source AND account=new.account AND cv_id=new.cv_id;
END;
CREATE TRIGGER IF NOT EXISTS candidate_contacts_ad AFTER DELETE ON candidates BEGIN
  DELETE FROM candidate_contacts WHERE source=old.source AND account=old.account AND cv_id=old.cv_id;
END;
CREATE TABLE IF NOT EXISTS sync_outbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT NOT NULL,
    entity_key      TEXT NOT NULL,
    payload_hash    TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL DEFAULT '',
    last_error      TEXT NOT NULL DEFAULT '',
    hub_id          TEXT NOT NULL DEFAULT '',
    synced_at       TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_outbox_entity ON sync_outbox(entity_type, entity_key);
CREATE INDEX IF NOT EXISTS ix_outbox_ready ON sync_outbox(status, next_attempt_at);
"""

# Toàn bộ cột được ghi xuống cơ sở dữ liệu.
# LƯU Ý: phải liệt kê đủ, không suy ra từ EXPORT_COLUMNS — vì có cột dùng nội bộ
# (applied_ts: mốc thời gian chuẩn để sắp xếp & lọc theo ngày) không xuất ra Excel.
_FIELDS = [
    "source", "account", "cv_id", "fullname", "email", "phone",
    "cv_emails", "cv_phones", "position", "campaign_id",
    "applied_at", "applied_ts", "apply_source", "status", "gender", "birth_year", "marital_status",
    "experience", "years_experience", "address", "city", "district", "desired_location",
    "current_title", "job_level", "desired_level", "desired_position", "job_type",
    "education", "foreign_language", "expected_salary", "current_salary", "skills",
    "last_company", "labels", "note",
    "candidate_id", "resume_id", "profile_type", "attachment_name", "attachment_mime", "source_payload",
    "detail_loaded", "is_viewed",
    "filename", "dl_status", "cv_url", "first_seen", "updated_at",
]


def is_cloud_synced_path(path):
    """Nhận diện thư mục đồng bộ phổ biến để tránh WAL bị đồng bộ tách rời file DB."""
    normalized = os.path.normcase(os.path.abspath(str(path or ""))).replace("/", "\\")
    markers = ("\\my drive\\", "\\google drive\\", "\\onedrive\\", "\\dropbox\\")
    return any(marker in normalized for marker in markers)


class Database:
    # 6: thêm sync_outbox cho việc đồng bộ Edge -> Hub.
    SCHEMA_VERSION = 6
    def __init__(self, path: str, log=print):
        self.path = path
        self.log = log
        self.lock = threading.RLock()
        self.conn = None

    # Cơ sở dữ liệu thường nằm trong thư mục Google Drive đồng bộ. Khi Drive đang tải
    # file lên/xuống, nó giữ file trong chốc lát khiến SQLite báo "disk I/O error" -
    # lỗi CHỚP NHOÁNG, thử lại sau một nhịp là xong. Vì mỗi thao tác trên giao diện
    # đều mở cơ sở dữ liệu một lần, không thử lại thì thỉnh thoảng người dùng sẽ thấy
    # một ô số liệu trắng trơn hoặc bảng dữ liệu báo lỗi mà không rõ vì sao.
    _OPEN_RETRIES = 4
    _OPEN_BACKOFF = 0.4      # giây, tăng dần sau mỗi lần thử
    _WRITE_RETRIES = 8

    def open(self):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)

        last = None
        for attempt in range(self._OPEN_RETRIES):
            try:
                cloud_path = is_cloud_synced_path(self.path)
                conn = sqlite3.connect(
                    self.path, check_same_thread=False, timeout=5 if cloud_path else 30)
                conn.row_factory = sqlite3.Row
                # WAL gồm nhiều file và không an toàn trong thư mục đồng bộ: Drive có
                # thể tải DB/WAL/SHM ở các thời điểm khác nhau rồi SQLite báo malformed.
                # DELETE chậm hơn đôi chút nhưng chỉ có một file trạng thái lâu dài.
                journal = "DELETE" if cloud_path else "WAL"
                actual_journal = str(conn.execute(
                    f"PRAGMA journal_mode={journal}").fetchone()[0]).upper()
                if actual_journal != journal:
                    raise sqlite3.OperationalError(
                        f"Không chuyển được SQLite journal sang {journal} (đang là {actual_journal}).")
                conn.execute("PRAGMA synchronous=FULL" if journal == "DELETE"
                             else "PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA temp_store=MEMORY")
                conn.execute(f"PRAGMA busy_timeout={5000 if cloud_path else 30000}")
                conn.execute("PRAGMA cache_size=-32768")
                # Memory-map không phù hợp với filesystem ảo của ứng dụng cloud.
                conn.execute("PRAGMA mmap_size=0" if journal == "DELETE"
                             else "PRAGMA mmap_size=134217728")
                conn.executescript(_SCHEMA)
                self._migrate_candidate_columns(conn)
                self._migrate_document_columns(conn)
                self._migrate_account_key(conn, self.path)
                # SAU mọi migration: lúc này bảng chắc chắn đã có cột và đã giữ
                # đủ dữ liệu, dù đi qua nhánh dựng lại bảng của _migrate_account_key.
                self._split_merged_contacts(conn)
                conn.commit()
                conn.execute("PRAGMA foreign_keys=ON")
                self._normalize_vietnamworks_dates(conn)
                self._ensure_search_index(conn)
                self._ensure_contact_index(conn)
                self._cleanup_orphans(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                    (str(self.SCHEMA_VERSION),))
                conn.commit()
                # Mỗi upsert/checkpoint là một transaction rất ngắn. Điều này đặc biệt quan trọng
                # với journal DELETE trên Google Drive: không giữ transaction mở trong lúc các
                # worker còn tải mạng rồi dồn một commit lớn dễ bị reader/cloud client chặn.
                conn.isolation_level = None
                # Không quét quick_check ở mọi lần open(). Với database vài trăm MB
                # trên Google Drive, phép kiểm tra toàn bộ bảng/index này có thể mất
                # hơn một phút và từng giữ màn hình khởi động mãi. Những câu lệnh
                # schema/migration phía trên đã đủ phát hiện DB không thể sử dụng;
                # kiểm tra toàn vẹn sâu vẫn nằm trong health() khi người dùng yêu cầu.
                conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
                self.conn = conn
                return self
            except sqlite3.Error as e:
                last = e
                try:
                    conn.close()
                except Exception:
                    pass
                if attempt < self._OPEN_RETRIES - 1:
                    time.sleep(self._OPEN_BACKOFF * (attempt + 1))

        raise sqlite3.OperationalError(
            f"Không mở được cơ sở dữ liệu sau {self._OPEN_RETRIES} lần thử:\n{self.path}\n\n"
            f"Hãy đóng các phiên MSB Radar Edge khác, đợi ổ đĩa đám mây đồng bộ xong rồi thử lại.\n"
            f"(Chi tiết kỹ thuật: {last})")

    @staticmethod
    def _ensure_search_index(conn):
        version = conn.execute(
            "SELECT value FROM meta WHERE key='candidate_search_version'").fetchone()
        if version and version[0] == "2":
            return
        conn.executescript("""
            DROP TRIGGER IF EXISTS candidate_search_ai;
            DROP TRIGGER IF EXISTS candidate_search_ad;
            DROP TRIGGER IF EXISTS candidate_search_au;
            DROP TABLE IF EXISTS candidate_document_search;
        """)
        conn.execute("DELETE FROM candidate_search")
        conn.execute("""INSERT INTO candidate_search(rowid,text)
            SELECT rowid, COALESCE(fullname,'')||' '||COALESCE(email,'')||' '||COALESCE(phone,'')||' '||
            COALESCE(position,'')||' '||COALESCE(skills,'')||' '||COALESCE(note,'')||' '||
            COALESCE(labels,'')||' '||COALESCE(address,'')||' '||COALESCE(city,'')||' '||
            COALESCE(current_title,'')||' '||COALESCE(last_company,'')||' '||
            COALESCE(cv_id,'')||' '||COALESCE(campaign_id,'')||' '||COALESCE(candidate_id,'')||' '||
            COALESCE(resume_id,'')||' '||COALESCE(source,'')||' '||COALESCE(account,'')||' '||
            COALESCE(status,'')||' '||COALESCE(apply_source,'')||' '||COALESCE((SELECT full_text
              FROM candidate_documents d WHERE d.source=candidates.source AND d.account=candidates.account
              AND d.cv_id=candidates.cv_id),'') FROM candidates""")
        conn.executescript("""
            CREATE TRIGGER candidate_search_ai AFTER INSERT ON candidates BEGIN
              INSERT INTO candidate_search(rowid,text) VALUES(new.rowid,
                COALESCE(new.fullname,'')||' '||COALESCE(new.email,'')||' '||COALESCE(new.phone,'')||' '||
                COALESCE(new.position,'')||' '||COALESCE(new.skills,'')||' '||COALESCE(new.note,'')||' '||
                COALESCE(new.labels,'')||' '||COALESCE(new.address,'')||' '||COALESCE(new.city,'')||' '||
                COALESCE(new.current_title,'')||' '||COALESCE(new.last_company,'')||' '||
                COALESCE(new.cv_id,'')||' '||COALESCE(new.campaign_id,'')||' '||
                COALESCE(new.candidate_id,'')||' '||COALESCE(new.resume_id,'')||' '||
                COALESCE(new.source,'')||' '||COALESCE(new.account,'')||' '||COALESCE(new.status,'')||' '||
                COALESCE(new.apply_source,'')||' '||COALESCE((SELECT full_text FROM candidate_documents d
                  WHERE d.source=new.source AND d.account=new.account AND d.cv_id=new.cv_id),''));
            END;
            CREATE TRIGGER candidate_search_ad AFTER DELETE ON candidates BEGIN
              DELETE FROM candidate_search WHERE rowid=old.rowid;
            END;
            CREATE TRIGGER candidate_search_au AFTER UPDATE ON candidates BEGIN
              DELETE FROM candidate_search WHERE rowid=old.rowid;
              INSERT INTO candidate_search(rowid,text) VALUES(new.rowid,
                COALESCE(new.fullname,'')||' '||COALESCE(new.email,'')||' '||COALESCE(new.phone,'')||' '||
                COALESCE(new.position,'')||' '||COALESCE(new.skills,'')||' '||COALESCE(new.note,'')||' '||
                COALESCE(new.labels,'')||' '||COALESCE(new.address,'')||' '||COALESCE(new.city,'')||' '||
                COALESCE(new.current_title,'')||' '||COALESCE(new.last_company,'')||' '||
                COALESCE(new.cv_id,'')||' '||COALESCE(new.campaign_id,'')||' '||
                COALESCE(new.candidate_id,'')||' '||COALESCE(new.resume_id,'')||' '||
                COALESCE(new.source,'')||' '||COALESCE(new.account,'')||' '||COALESCE(new.status,'')||' '||
                COALESCE(new.apply_source,'')||' '||COALESCE((SELECT full_text FROM candidate_documents d
                  WHERE d.source=new.source AND d.account=new.account AND d.cv_id=new.cv_id),''));
            END;
        """)
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('candidate_search_version','2')")

    @staticmethod
    def _migrate_document_columns(conn):
        existing = {row[1] for row in conn.execute("PRAGMA table_info(candidate_documents)")}
        additions = {
            "file_size": "INTEGER NOT NULL DEFAULT 0",
            "file_mtime_ns": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, declaration in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE candidate_documents ADD COLUMN {name} {declaration}")

    @staticmethod
    def _ensure_contact_index(conn):
        """Backfill khóa liên hệ đúng một lần; các lần ghi sau do trigger duy trì."""
        version = conn.execute(
            "SELECT value FROM meta WHERE key='candidate_contacts_version'").fetchone()
        if version and version[0] == "1":
            return
        conn.execute("DELETE FROM candidate_contacts")
        conn.execute("""INSERT INTO candidate_contacts(source,account,cv_id,email_key,phone_key)
            SELECT source,account,cv_id,LOWER(TRIM(COALESCE(email,''))),
            REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(phone,''),' ',''),'-',''),'.',''),'(',''),')',''),'+','')
            FROM candidates""")
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('candidate_contacts_version','1')")

    @staticmethod
    def _cleanup_orphans(conn):
        version = conn.execute(
            "SELECT value FROM meta WHERE key='orphan_cleanup_version'").fetchone()
        if version and version[0] == "1":
            return
        for table in ("candidate_documents", "candidate_extensions", "candidate_contacts"):
            conn.execute(f"""DELETE FROM {table} WHERE NOT EXISTS (
                SELECT 1 FROM candidates c WHERE c.source={table}.source
                AND c.account={table}.account AND c.cv_id={table}.cv_id)""")
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('orphan_cleanup_version','1')")

    @staticmethod
    def _migrate_candidate_columns(conn):
        """Bổ sung cột mới mà không làm mất dữ liệu của database phiên bản cũ."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(candidates)")}
        integer_fields = {"is_viewed", "detail_loaded"}
        for field in _FIELDS:
            if field in existing:
                continue
            column_type = "INTEGER DEFAULT 0" if field in integer_fields else "TEXT"
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {field} {column_type}")

    @staticmethod
    def _split_merged_contacts(conn):
        """Tách các ô liên hệ bị gộp của phiên bản cũ.

        Bản cũ nối mọi email/SĐT bóc từ CV vào một ô ("a@x.com, b@y.com"). Hub
        coi ô này là định danh Person nên không đọc nổi chuỗi nhiều giá trị và
        vứt luôn cả định danh (đo thật: 28 hồ sơ mất email, 32 mất điện thoại).
        Ở đây trả `email`/`phone` về một giá trị và đẩy cả danh sách sang
        `cv_emails`/`cv_phones` — không mất gì, Hub sẽ phân xử lại bằng text CV.

        Gọi ở `open()` SAU mọi migration, không gài vào nhánh "vừa thêm cột".
        Bản đầu gài như vậy và có một lỗ: `_migrate_account_key` dựng lại bảng
        rồi mới chép dữ liệu cũ vào, nên nếu nhánh đó chạy thì cột đã tồn tại
        lúc chép — không nhánh nào tách nữa và dữ liệu gộp sống sót vĩnh viễn.

        Tự nó đã idempotent: chạy xong thì không còn hàng nào khớp `LIKE '%,%'`,
        nên gọi mỗi lần mở database chỉ tốn đúng một lượt quét rỗng.
        """
        rows = conn.execute(
            "SELECT rowid, fullname, email, phone FROM candidates "
            "WHERE email LIKE '%,%' OR phone LIKE '%,%'").fetchall()
        for row in rows:
            emails = Database._contact_list(row[2], True)
            phones = Database._contact_list(row[3], False)
            conn.execute(
                "UPDATE candidates SET email=?, phone=?, cv_emails=?, cv_phones=? "
                "WHERE rowid=?",
                (Database._own_contact('', emails, row[1], is_email=True),
                 Database._own_contact('', phones, row[1], is_email=False),
                 json.dumps(emails, ensure_ascii=False) if emails else None,
                 json.dumps(phones, ensure_ascii=False) if phones else None,
                 row[0]))

    @staticmethod
    def _migrate_account_key(conn, db_path=""):
        """Nâng khóa chống trùng từ (source, cv_id) lên (source, account, cv_id)."""
        info = conn.execute("PRAGMA table_info(candidates)").fetchall()
        primary_key = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
        if primary_key == ["source", "account", "cv_id"]:
            # Bản cũ chuẩn hóa lại TOÀN BỘ candidates trong mọi lần mở database.
            # Trên Google Drive việc ghi lại hàng chục nghìn dòng tạo journal lớn và
            # làm startup mất gần một phút dù dữ liệu vốn đã đúng. Chỉ chạy migration
            # một lần và chỉ chạm những dòng thực sự cần sửa.
            normalized = conn.execute(
                "SELECT value FROM meta WHERE key='account_normalization_version'").fetchone()
            if not normalized or normalized[0] != "1":
                conn.execute("""UPDATE candidates
                    SET account=LOWER(TRIM(COALESCE(account,'')))
                    WHERE account IS NULL OR account<>LOWER(TRIM(account))""")
                conn.execute("INSERT OR REPLACE INTO meta(key,value) "
                             "VALUES('account_normalization_version','1')")
            return

        if db_path and os.path.exists(db_path):
            backup_path = db_path + ".pre-schema-v2.bak"
            if not os.path.exists(backup_path):
                target = sqlite3.connect(backup_path)
                try:
                    # Dùng chính connection đang migration để bản sao nhất quán
                    # và tránh hai connection tranh khóa trên Google Drive.
                    conn.backup(target)
                finally:
                    target.close()

        columns = [row[1] for row in info]
        conn.execute("PRAGMA legacy_alter_table=ON")
        conn.execute("ALTER TABLE candidates RENAME TO candidates_legacy_account_key")
        # Index của bảng cũ giữ nguyên tên sau RENAME. Xóa bảng cũ trước để các
        # CREATE INDEX IF NOT EXISTS trong schema có thể tạo lại đúng trên bảng mới.
        conn.execute("""
            CREATE TABLE candidates (
                source TEXT NOT NULL, cv_id TEXT NOT NULL,
                account TEXT NOT NULL DEFAULT '', fullname TEXT, email TEXT, phone TEXT,
                position TEXT, campaign_id TEXT, applied_at TEXT, applied_ts TEXT,
                apply_source TEXT, status TEXT, gender TEXT, birth_year TEXT,
                experience TEXT, years_experience TEXT, address TEXT, city TEXT,
                district TEXT, current_title TEXT, job_level TEXT, education TEXT,
                expected_salary TEXT, skills TEXT, last_company TEXT, labels TEXT, note TEXT,
                candidate_id TEXT, resume_id TEXT, profile_type TEXT,
                attachment_name TEXT, attachment_mime TEXT, source_payload TEXT,
                detail_loaded INTEGER DEFAULT 0, is_viewed INTEGER DEFAULT 0,
                filename TEXT, dl_status TEXT, cv_url TEXT, first_seen TEXT, updated_at TEXT,
                PRIMARY KEY (source, account, cv_id)
            )
        """)
        # CREATE TABLE ở trên cố ý chỉ giữ khung tối thiểu; các cột `_FIELDS` mới
        # hơn (thêm qua `_migrate_candidate_columns` chạy TRƯỚC bước này) được
        # ALTER bù vào ngay để câu INSERT bên dưới - dùng đúng danh sách cột của
        # bảng cũ (đã gồm các cột mới) - không lỗi "no such column".
        Database._migrate_candidate_columns(conn)
        new_table_columns = {row[1] for row in conn.execute("PRAGMA table_info(candidates)")}
        copy_columns = [name for name in columns if name in new_table_columns]
        select_values = [
            "LOWER(TRIM(COALESCE(account,'')))" if name == "account" else name
            for name in copy_columns
        ]
        quoted_columns = ", ".join(f'"{name}"' for name in copy_columns)
        conn.execute(
            f"INSERT OR REPLACE INTO candidates ({quoted_columns}) "
            f"SELECT {', '.join(select_values)} FROM candidates_legacy_account_key")
        conn.execute("DROP TABLE candidates_legacy_account_key")
        conn.executescript(_SCHEMA)
        Database._migrate_candidate_columns(conn)
        conn.execute("PRAGMA legacy_alter_table=OFF")

    def health(self):
        with self.lock:
            quick_check = self.conn.execute("PRAGMA quick_check").fetchone()[0]
            schema_version = self.get_meta("schema_version", "0")
            page_count = int(self.conn.execute("PRAGMA page_count").fetchone()[0] or 0)
            page_size = int(self.conn.execute("PRAGMA page_size").fetchone()[0] or 0)
        return {
            "quick_check": str(quick_check), "schema_version": int(schema_version or 0),
            "rows": self.count(), "database_bytes": page_count * page_size,
        }

    def backup_to(self, target_path):
        folder = os.path.dirname(target_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with self.lock:
            target = sqlite3.connect(target_path)
            try:
                self.conn.backup(target)
                target.commit()
            finally:
                target.close()
        return target_path

    def delete_candidates(self, *, source="", account="", date_from="", date_to=""):
        where, params = self._build_filter(
            source=source, account=account, date_from=date_from, date_to=date_to)
        with self.lock:
            rows = self.conn.execute(
                f"SELECT source, account, cv_id, filename FROM candidates{where}", params).fetchall()
            self.conn.execute(f"DELETE FROM candidates{where}", params)
        return [dict(row) for row in rows]

    @staticmethod
    def _normalize_vietnamworks_dates(conn):
        """Keep display dates consistent with TopCV while preserving sortable timestamps."""
        rows = conn.execute(
            "SELECT account, cv_id, applied_at, applied_ts FROM candidates "
            "WHERE source='vietnamworks' AND applied_at LIKE '%T%Z'").fetchall()
        for row in rows:
            raw = str(row["applied_at"] or "")
            try:
                utc_time = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
                local_time = utc_time + timedelta(hours=7)
            except (TypeError, ValueError):
                continue
            conn.execute(
                "UPDATE candidates SET applied_at=?, applied_ts=? "
                "WHERE source='vietnamworks' AND account=? AND cv_id=?",
                (local_time.strftime("%d/%m/%Y %H:%M"),
                 local_time.strftime("%Y-%m-%d %H:%M:%S"), row["account"], row["cv_id"]))

    def backfill_accounts(self, config_accounts: dict):
        """Gán tài khoản cho dữ liệu legacy đúng một lần, không nhận nhầm khi đổi account."""
        if not self.conn or not config_accounts:
            return
        with self.lock:
            for source, acc_email in config_accounts.items():
                if not acc_email:
                    continue
                known = self.conn.execute(
                    "SELECT COUNT(*) FROM candidates WHERE source=? AND account<>''",
                    (source,)).fetchone()[0]
                if known:
                    continue
                account = str(acc_email).strip().lower()
                # CSDL cũ chưa có ON UPDATE CASCADE. Hoãn kiểm tra khóa ngoại
                # và chuyển tất cả bản ghi phụ thuộc trong cùng một transaction.
                self.conn.execute("BEGIN IMMEDIATE")
                try:
                    self.conn.execute("PRAGMA defer_foreign_keys=ON")
                    self.conn.execute(
                        "UPDATE candidates SET account=? WHERE source=? AND (account IS NULL OR account='')",
                        (account, source))
                    for table in ("candidate_documents", "candidate_extensions", "candidate_contacts"):
                        self.conn.execute(
                            f"UPDATE {table} SET account=? WHERE source=? AND (account IS NULL OR account='')",
                            (account, source))
                    self.conn.commit()
                except Exception:
                    self.conn.rollback()
                    raise

    def close(self):
        with self.lock:
            if self.conn:
                try:
                    self.conn.commit()
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None

    # ---------------- ghi ----------------
    def upsert(self, item: dict):
        """Thêm mới hoặc cập nhật 1 ứng viên. Giữ nguyên 'first_seen' của lần đầu."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = {k: item.get(k) for k in _FIELDS}
        data["account"] = str(data.get("account") or "").strip().lower()
        data["updated_at"] = now
        data["first_seen"] = item.get("first_seen") or now
        cols = ", ".join(_FIELDS)
        ph = ", ".join("?" for _ in _FIELDS)
        integer_fields = {"is_viewed", "detail_loaded"}
        upd = ", ".join(
            f"{c}=COALESCE(excluded.{c}, candidates.{c})" if c in integer_fields
            else f"{c}=COALESCE(NULLIF(excluded.{c}, ''), candidates.{c})"
            for c in _FIELDS if c != "first_seen")
        sql = (f"INSERT INTO candidates ({cols}) VALUES ({ph}) "
               f"ON CONFLICT(source, account, cv_id) DO UPDATE SET {upd}")
        self._write(sql, [data.get(c) for c in _FIELDS], "ghi ứng viên")

    @staticmethod
    def _is_locked_error(exc):
        text = str(exc).lower()
        return "database is locked" in text or "database table is locked" in text

    def _is_transient_write_error(self, exc):
        if self._is_locked_error(exc):
            return True
        text = str(exc).lower()
        return (is_cloud_synced_path(self.path)
                and ("unable to open database file" in text
                     or "disk i/o error" in text
                     or "database is busy" in text))

    def _write(self, sql, params=(), operation="ghi database"):
        """Retry lock tạm thời; autocommit bảo đảm lần lỗi không để transaction treo."""
        last = None
        for attempt in range(self._WRITE_RETRIES):
            try:
                with self.lock:
                    return self.conn.execute(sql, params)
            except sqlite3.OperationalError as exc:
                if not self._is_transient_write_error(exc):
                    raise
                last = exc
                if attempt < self._WRITE_RETRIES - 1:
                    delay = min(8.0, 0.5 * (2 ** attempt))
                    if attempt in (0, 3, 6):
                        self.log(f"SQLite đang bận khi {operation}; tự thử lại ({attempt + 1}/{self._WRITE_RETRIES})...")
                    time.sleep(delay)
        raise sqlite3.OperationalError(
            f"database is locked kéo dài khi {operation} sau {self._WRITE_RETRIES} lần thử") from last

    def _read(self, sql, params=(), operation="đọc database"):
        """Đọc CSDL an toàn với retry tự động khi gặp transient lock / disk I/O error trên Google Drive/cloud sync."""
        last = None
        for attempt in range(self._WRITE_RETRIES):
            try:
                with self.lock:
                    return self.conn.execute(sql, params)
            except sqlite3.OperationalError as exc:
                if not self._is_transient_write_error(exc):
                    raise
                last = exc
                if attempt < self._WRITE_RETRIES - 1:
                    delay = min(4.0, 0.15 * (2 ** attempt))
                    time.sleep(delay)
        raise sqlite3.OperationalError(
            f"Lỗi truy vấn CSDL ({operation}) sau {self._WRITE_RETRIES} lần thử: {last}") from last

    def commit(self):
        with self.lock:
            if self.conn:
                self.conn.commit()

    def _transaction(self, callback, operation="giao dịch database"):
        last = None
        for attempt in range(self._WRITE_RETRIES):
            try:
                with self.lock:
                    self.conn.execute("BEGIN IMMEDIATE")
                    try:
                        value = callback(self.conn)
                        self.conn.execute("COMMIT")
                        return value
                    except Exception:
                        self.conn.execute("ROLLBACK")
                        raise
            except sqlite3.OperationalError as exc:
                if not self._is_transient_write_error(exc):
                    raise
                last = exc
                if attempt < self._WRITE_RETRIES - 1:
                    time.sleep(min(8.0, 0.5 * (2 ** attempt)))
        raise sqlite3.OperationalError(
            f"database is locked kéo dài khi {operation} sau {self._WRITE_RETRIES} lần thử") from last

    # ---------------- CV parsing queue ----------------
    def enqueue_document(self, source, account, cv_id, filename, parser_version="2", force=False,
                         file_size=0, file_mtime_ns=0):
        """Persist a cheap parsing ticket. Existing successful work is preserved."""
        if not filename:
            return False
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = """INSERT INTO candidate_documents
            (source,account,cv_id,filename,parser_version,file_size,file_mtime_ns,parse_status,queued_at,updated_at)
            VALUES (?,?,?,?,?,?,?,'pending',?,?)
            ON CONFLICT(source,account,cv_id) DO UPDATE SET
              filename=excluded.filename, parser_version=excluded.parser_version,
              parse_status=CASE WHEN ? OR candidate_documents.filename<>excluded.filename
                OR candidate_documents.parser_version<>excluded.parser_version
                OR (? > 0 AND candidate_documents.file_size<>excluded.file_size)
                OR (? > 0 AND candidate_documents.file_mtime_ns<>excluded.file_mtime_ns)
                THEN 'pending' ELSE candidate_documents.parse_status END,
              queued_at=CASE WHEN ? THEN excluded.queued_at ELSE candidate_documents.queued_at END,
              updated_at=excluded.updated_at"""
        self._write(sql, (source, str(account or "").strip().lower(), str(cv_id), filename,
                          parser_version, int(file_size or 0), int(file_mtime_ns or 0), now, now,
                          int(bool(force)), int(file_size or 0), int(file_mtime_ns or 0), int(bool(force))),
                    "xếp hàng parsing CV")
        return True

    def _enqueue_unparsed_documents_legacy(self, parser_version="2", force=False):
        """Backfill queue using a single indexed SQL statement; safe to run repeatedly."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_clause = "1=1" if force else "d.cv_id IS NULL OR d.parse_status<>'done' OR d.parser_version<>?"
        params = [] if force else [parser_version]
        sql = f"""INSERT INTO candidate_documents
            (source,account,cv_id,filename,parser_version,parse_status,queued_at,updated_at)
            SELECT c.source,c.account,c.cv_id,c.filename,?,'pending',?,?
            FROM candidates c LEFT JOIN candidate_documents d
              ON d.source=c.source AND d.account=c.account AND d.cv_id=c.cv_id
            WHERE c.dl_status=? AND TRIM(COALESCE(c.filename,''))<>'' AND ({status_clause})
            ON CONFLICT(source,account,cv_id) DO UPDATE SET filename=excluded.filename,
              parser_version=excluded.parser_version,parse_status='pending',parse_error='',
              queued_at=excluded.queued_at,updated_at=excluded.updated_at"""
        cur = self._write(sql, [parser_version, now, now, DONE] + params, "tạo hàng đợi backdate")
        return max(0, int(cur.rowcount or 0))

    def recover_document_queue(self):
        self._write("UPDATE candidate_documents SET parse_status='pending',started_at=NULL "
                    "WHERE parse_status='running'", (), "khôi phục hàng đợi parsing")

    def enqueue_unparsed_batch(self, parser_version="2", force=False, after_rowid=0, limit=500,
                               filters=None, skip_failed=False):
        """Queue one bounded page; suitable for million-row databases.

        `skip_failed=True` chỉ xếp CV chưa từng bóc tách hoặc cần bóc lại do đổi
        phiên bản bộ đọc; KHÔNG đụng file đang ở trạng thái lỗi/rỗng - việc thử
        lại các file đó do `requeue_stale_failed_documents()` lo, có giới hạn số
        lần và thời gian nguội, để một lượt tự động không lặp lại OCR vô ích.
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if force:
            condition = "1=1"
        elif skip_failed:
            condition = ("(d.cv_id IS NULL OR d.parse_status IN ('pending','running') "
                         "OR d.parser_version<>?)")
        else:
            condition = "(d.cv_id IS NULL OR d.parse_status<>'done' OR d.parser_version<>?)"
        filter_sql, filter_params = self._report_filters(**(filters or {}), prefix="c.")
        params = ([DONE, int(after_rowid)] + filter_params
                  + ([] if force else [parser_version]) + [max(1, int(limit))])
        with self.lock:
            rows = self.conn.execute(f"""SELECT c.rowid,c.source,c.account,c.cv_id,c.filename
                FROM candidates c LEFT JOIN candidate_documents d
                  ON d.source=c.source AND d.account=c.account AND d.cv_id=c.cv_id
                WHERE c.dl_status=? AND c.rowid>? AND TRIM(COALESCE(c.filename,''))<>''
                  {filter_sql} AND {condition} ORDER BY c.rowid LIMIT ?""", params).fetchall()
        if not rows:
            return {"count": 0, "last_rowid": int(after_rowid), "has_more": False}
        def insert_batch(conn):
            conn.executemany("""INSERT INTO candidate_documents
                (source,account,cv_id,filename,parser_version,parse_status,queued_at,updated_at)
                VALUES (?,?,?,?,?,'pending',?,?)
                ON CONFLICT(source,account,cv_id) DO UPDATE SET filename=excluded.filename,
                  parser_version=excluded.parser_version,parse_status='pending',parse_error='',
                  queued_at=excluded.queued_at,updated_at=excluded.updated_at""",
                [(r['source'], r['account'], r['cv_id'], r['filename'], parser_version, now, now)
                 for r in rows])
        self._transaction(insert_batch, "xếp lô backdate")
        return {"count": len(rows), "last_rowid": int(rows[-1]['rowid']),
                "has_more": len(rows) >= max(1, int(limit))}

    def enqueue_unparsed_documents(self, parser_version="2", force=False):
        """Compatibility entry point implemented with bounded pages."""
        total, cursor = 0, 0
        while True:
            page = self.enqueue_unparsed_batch(parser_version, force, cursor, 500)
            total += page['count']
            cursor = page['last_rowid']
            if not page['has_more']:
                return total

    def claim_document(self, filters=None):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        filter_sql, filter_params = self._report_filters(**(filters or {}), prefix="c.")
        def claim(conn):
            row = conn.execute("""SELECT d.rowid AS document_rowid,d.*,c.fullname,c.position,c.applied_ts
                FROM candidate_documents d LEFT JOIN candidates c
                  ON c.source=d.source AND c.account=d.account AND c.cv_id=d.cv_id
                WHERE d.parse_status='pending'""" + filter_sql +
                " ORDER BY CASE WHEN c.applied_ts IS NOT NULL AND c.applied_ts <> '' THEN 0 ELSE 1 END, c.applied_ts DESC, d.queued_at, d.rowid LIMIT 1", filter_params).fetchone()
            if not row:
                return None
            changed = conn.execute("UPDATE candidate_documents SET parse_status='running',started_at=?,"
                                   "attempts=attempts+1,updated_at=? WHERE rowid=? AND parse_status='pending'",
                                   (now, now, row['document_rowid'])).rowcount
            if changed != 1:
                return None
            return dict(row)
        return self._transaction(claim, "nhận tác vụ parsing")

    # ---------------- Hàng đợi đồng bộ Edge -> Hub (outbox) ----------------
    # Mẫu outbox: mỗi thực thể chỉ có ĐÚNG MỘT hàng, thay vì một nhật ký nối
    # thêm mãi. Nhờ vậy bảng bị chặn trên bởi số thực thể chứ không bởi số lần
    # thay đổi, và việc gửi lại một bản ghi đã đồng bộ không sinh thêm hàng.
    #
    # Cố ý KHÔNG đặt khoá ngoại tới candidates: outbox sẽ còn mang document,
    # signal, social post... và cần sống sót đủ lâu để báo cáo kết quả kể cả khi
    # ứng viên đã bị xoá cục bộ. Bên gửi tự bỏ qua hàng không còn thực thể.

    OUTBOX_MAX_ATTEMPTS = 8
    _OUTBOX_BACKOFF_BASE = 30.0     # giây
    _OUTBOX_BACKOFF_CAP = 3600.0    # 1 giờ

    @classmethod
    def outbox_retry_delay(cls, attempts):
        """Giãn cách thử lại theo cấp số nhân, có jitter, chặn trên 1 giờ.

        Jitter tránh việc nhiều Edge cùng mất mạng rồi gọi Hub lại đúng cùng lúc.

        Cố ý tự tính thay vì dùng providers.base.jitter_delay: import gói
        providers kéo theo cả selenium/undetected-chromedriver, quá nặng cho một
        phép nhân — và tạo phụ thuộc sai chiều từ tầng lưu trữ sang tầng thu thập.
        """
        exponent = min(16, max(0, int(attempts) - 1))     # chặn trước khi luỹ thừa tràn
        raw = min(cls._OUTBOX_BACKOFF_CAP, cls._OUTBOX_BACKOFF_BASE * (2 ** exponent))
        return raw * random.uniform(0.75, 1.25)

    def enqueue_sync(self, entity_type, entity_key, payload_hash=""):
        """Đưa một thực thể vào hàng đợi đồng bộ. Trả True nếu thật sự có việc mới.

        Gọi lại với cùng payload_hash trên một hàng đã đồng bộ là no-op — đây là
        điều khiến việc quét lại toàn bộ CSDL trở nên rẻ và không sinh rác.
        payload_hash đổi nghĩa là nội dung đã đổi, hàng được xếp lại từ đầu.
        """
        if not entity_type or not entity_key:
            return False
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self._write(
            """INSERT INTO sync_outbox
                 (entity_type,entity_key,payload_hash,status,next_attempt_at,created_at,updated_at)
               VALUES (?,?,?,'pending','',?,?)
               ON CONFLICT(entity_type,entity_key) DO UPDATE SET
                 payload_hash=excluded.payload_hash,
                 status='pending', attempts=0, next_attempt_at='', last_error='',
                 updated_at=excluded.updated_at
               WHERE sync_outbox.payload_hash <> excluded.payload_hash
                  OR sync_outbox.status='failed'""",
            (entity_type, entity_key, payload_hash, now, now), "xếp hàng đồng bộ")
        return cur.rowcount > 0

    def claim_sync_batch(self, limit=50):
        """Lấy các hàng đã tới hạn và đánh dấu inflight trong cùng một transaction.

        Đọc rồi ghi trong một BEGIN IMMEDIATE để hai luồng gửi không thể nhận
        trùng một hàng.
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        def claim(conn):
            rows = conn.execute(
                """SELECT * FROM sync_outbox
                   WHERE status='pending' AND (next_attempt_at='' OR next_attempt_at<=?)
                   ORDER BY next_attempt_at, id LIMIT ?""", (now, int(limit))).fetchall()
            if not rows:
                return []
            ids = [row["id"] for row in rows]
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE sync_outbox SET status='inflight',attempts=attempts+1,updated_at=? "
                f"WHERE id IN ({placeholders})", [now] + ids)
            return [dict(row) for row in rows]

        return self._transaction(claim, "nhận lô đồng bộ")

    def finish_sync(self, outbox_id, hub_id=""):
        """Đánh dấu đã đồng bộ thành công."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._write(
            "UPDATE sync_outbox SET status='synced',hub_id=?,last_error='',synced_at=?,updated_at=? "
            "WHERE id=?", (str(hub_id or ""), now, now, int(outbox_id)), "hoàn tất đồng bộ")

    def fail_sync(self, outbox_id, error="", retryable=True):
        """Ghi nhận thất bại. Hết lượt thử hoặc lỗi vĩnh viễn thì chuyển sang 'failed'.

        'failed' không phải ngõ cụt: enqueue_sync() sẽ xếp lại hàng đó, nên chỉ
        cần nội dung thay đổi hoặc người dùng bấm thử lại là nó quay lại hàng đợi.
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = self._read("SELECT attempts FROM sync_outbox WHERE id=?",
                         (int(outbox_id),), "đọc trạng thái đồng bộ").fetchone()
        attempts = int(row["attempts"]) if row else 1
        if not retryable or attempts >= self.OUTBOX_MAX_ATTEMPTS:
            self._write("UPDATE sync_outbox SET status='failed',last_error=?,updated_at=? WHERE id=?",
                        (str(error)[:500], now, int(outbox_id)), "ghi lỗi đồng bộ")
            return False
        retry_at = (datetime.now() + timedelta(seconds=self.outbox_retry_delay(attempts))
                    ).strftime("%Y-%m-%d %H:%M:%S")
        self._write(
            "UPDATE sync_outbox SET status='pending',next_attempt_at=?,last_error=?,updated_at=? WHERE id=?",
            (retry_at, str(error)[:500], now, int(outbox_id)), "hẹn thử lại đồng bộ")
        return True

    def release_sync_batch(self, outbox_ids):
        """Trả một lô đang gửi về `pending` mà KHÔNG tính là một lần thử.

        Khác `fail_sync`: dùng khi lỗi không thuộc về bản ghi — khoá bị thu hồi,
        khoá vừa xoay, Edge bị vô hiệu hoá. Những bản ghi đó hoàn toàn hợp lệ và
        Hub sẽ nhận ngay khi khoá được sửa; đốt lượt thử của chúng chỉ khiến
        chúng chết sớm hơn vì một chuyện không liên quan.
        """
        ids = [int(value) for value in (outbox_ids or [])]
        if not ids:
            return 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        placeholders = ",".join("?" for _ in ids)
        cur = self._write(
            f"UPDATE sync_outbox SET status='pending',updated_at=? "
            f"WHERE id IN ({placeholders}) AND status='inflight'",
            [now] + ids, "trả lô đồng bộ về hàng đợi")
        return max(0, int(cur.rowcount or 0))

    def recover_sync_queue(self):
        """Trả các hàng đang inflight về pending. Gọi lúc khởi động.

        Ứng dụng bị tắt giữa chừng sẽ để lại hàng ở trạng thái inflight mà không
        còn ai gửi. Không có bước này thì chúng kẹt vĩnh viễn.
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self._write(
            "UPDATE sync_outbox SET status='pending',updated_at=? WHERE status='inflight'",
            (now,), "khôi phục hàng đợi đồng bộ")
        return cur.rowcount

    def requeue_failed_sync(self, entity_type=""):
        """Đưa các hàng 'failed' trở lại hàng đợi (nút thử lại trên giao diện)."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = ("UPDATE sync_outbox SET status='pending',attempts=0,next_attempt_at='',"
               "last_error='',updated_at=? WHERE status='failed'")
        params = [now]
        if entity_type:
            sql += " AND entity_type=?"
            params.append(entity_type)
        return self._write(sql, params, "xếp lại hàng đồng bộ lỗi").rowcount

    def sync_stats(self):
        """Đếm theo trạng thái; luôn trả đủ 4 khoá để giao diện không phải phòng thủ."""
        stats = {"pending": 0, "inflight": 0, "synced": 0, "failed": 0}
        for row in self._read("SELECT status, COUNT(*) AS n FROM sync_outbox GROUP BY status",
                              (), "thống kê đồng bộ").fetchall():
            stats[row["status"]] = int(row["n"])
        stats["total"] = sum(stats[k] for k in ("pending", "inflight", "synced", "failed"))
        return stats

    def requeue_failed_documents(self, filters=None):
        """Chỉ thử lại các tài liệu chưa parsing thành công, không động vào kết quả tốt."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        filter_sql, filter_params = self._report_filters(**(filters or {}), prefix="c.")
        cur = self._write(
            "UPDATE candidate_documents SET parse_status='pending',parse_error='',queued_at=?,"
            "updated_at=? WHERE parse_status IN ('error','empty','needs_ocr','unsupported') "
            "AND EXISTS (SELECT 1 FROM candidates c WHERE c.source=candidate_documents.source "
            "AND c.account=candidate_documents.account AND c.cv_id=candidate_documents.cv_id" +
            filter_sql + ")",
            [now, now] + filter_params, "xếp lại hàng đợi parsing lỗi")
        return max(0, int(cur.rowcount or 0))

    # ---------------- Đếm tồn đọng cho bộ điều phối pipeline ----------------

    _PARSE_TERMINAL = ("done", "empty", "needs_ocr", "unsupported", "error")

    def parsing_backlog(self, parser_version="2"):
        """Số CV đã tải cần bóc tách: chưa có bản ghi tài liệu, đang chờ/đang chạy,
        hoặc phiên bản bộ đọc đã cũ. KHÔNG tính file đang ở trạng thái lỗi/rỗng -
        những file đó do `requeue_stale_failed_documents()` đưa lại hàng đợi khi
        đã đủ nguội. Chỉ dùng COUNT trên index sẵn có nên rẻ để gọi mỗi nhịp."""
        row = self._read(
            """SELECT COUNT(*) AS n
                 FROM candidates c LEFT JOIN candidate_documents d
                   ON d.source=c.source AND d.account=c.account AND d.cv_id=c.cv_id
                WHERE c.dl_status=? AND TRIM(COALESCE(c.filename,''))<>''
                  AND (d.cv_id IS NULL OR d.parse_status IN ('pending','running')
                       OR d.parser_version<>?)""",
            (DONE, str(parser_version)), "đếm tồn đọng parsing").fetchone()
        return int(row["n"]) if row else 0

    def parsing_retry_backlog(self, max_attempts=3, cooldown_hours=6):
        """Số file parse lỗi / cần OCR đã đủ nguội và chưa hết lượt thử lại."""
        row = self._read(
            "SELECT COUNT(*) AS n FROM candidate_documents "
            "WHERE parse_status IN ('error','needs_ocr') AND attempts < ? "
            "AND (updated_at IS NULL OR updated_at <= datetime('now','localtime',?))",
            (int(max_attempts), f"-{int(cooldown_hours)} hours"),
            "đếm parsing lỗi đã nguội").fetchone()
        return int(row["n"]) if row else 0

    def requeue_stale_failed_documents(self, max_attempts=3, cooldown_hours=6):
        """Đưa lại hàng đợi các file parse lỗi / cần OCR đã đủ nguội. Trả số dòng
        được xếp lại. Bỏ qua 'empty'/'unsupported' vì định dạng không tự đổi."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self._write(
            "UPDATE candidate_documents SET parse_status='pending',parse_error='',queued_at=?,"
            "updated_at=? WHERE parse_status IN ('error','needs_ocr') AND attempts < ? "
            "AND (updated_at IS NULL OR updated_at <= datetime('now','localtime',?))",
            (now, now, int(max_attempts), f"-{int(cooldown_hours)} hours"),
            "xếp lại parsing lỗi đã nguội")
        return max(0, int(cur.rowcount or 0))

    def count_parsed_terminal(self):
        """Số tài liệu đã ở trạng thái kết thúc (kể cả lỗi) - mốc để so với số đã đồng bộ."""
        row = self._read(
            "SELECT COUNT(*) AS n FROM candidate_documents WHERE parse_status IN "
            "('done','empty','needs_ocr','unsupported','error')",
            (), "đếm tài liệu đã parse xong").fetchone()
        return int(row["n"]) if row else 0

    @staticmethod
    def _norm_email(value):
        text = str(value or '').strip('.,;:()[]{}<>"\' \t\n\r').lower()
        if '@' not in text or '.' not in text.split('@')[-1]:
            return ''
        if text.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')):
            return ''
        return text

    @staticmethod
    def _norm_phone(value):
        cleaned = re.sub(r"[^\d+]", "", str(value or "")).strip()
        if cleaned.startswith("+84"):
            cleaned = "0" + cleaned[3:]
        elif cleaned.startswith("84") and len(cleaned) >= 11:
            cleaned = "0" + cleaned[2:]
        if (cleaned.startswith("0") and 9 <= len(cleaned) <= 11) or len(cleaned) >= 8:
            return cleaned
        return ''

    @classmethod
    def _contact_list(cls, raw, is_email=True):
        """Danh sách giá trị liên hệ đã chuẩn hoá, giữ thứ tự, không trùng."""
        norm = cls._norm_email if is_email else cls._norm_phone
        if isinstance(raw, (list, tuple, set)):
            values = list(raw)
        else:
            values = re.split(r'[,;\s/]+', str(raw or ''))
        out, seen = [], set()
        for value in values:
            token = norm(value)
            if token and token not in seen:
                seen.add(token)
                out.append(token)
        return out

    @staticmethod
    def _email_matches_name(email, fullname):
        """Phần trước @ có mang tên người này không (bỏ dấu, bỏ ký tự lạ)."""
        local = re.sub(r'[^a-z]', '', str(email or '').lower().split('@')[0])
        folded = unicodedata.normalize('NFD', str(fullname or '').replace('đ', 'd')
                                       .replace('Đ', 'D'))
        folded = ''.join(c for c in folded if unicodedata.category(c) != 'Mn').lower()
        tokens = [t for t in folded.split() if len(t) >= 2]
        if not local or not tokens:
            return False
        if ''.join(tokens) in local:
            return True
        return sum(1 for t in tokens if t in local) >= 2

    @classmethod
    def _own_contact(cls, existing_val, cv_values, fullname, is_email=True):
        """Giá trị liên hệ của CHÍNH ứng viên — đúng một giá trị.

        Trước đây hàm này gộp mọi email/SĐT bóc được từ CV vào một ô
        ("a@x.com, b@y.com, c@z.com"). Nghe thì "không mất gì", nhưng CV thường
        kèm liên hệ của NGƯỜI THAM CHIẾU, nên cái ô ấy trộn lẫn hai ba người
        khác nhau — và Hub thì coi ô liên hệ là ĐỊNH DANH để phân giải Person.
        Hệ quả đo được trên 283 hồ sơ thật: `normalize_email` của Hub không khớp
        nổi chuỗi có dấu phẩy nên vứt luôn cả định danh — 28 hồ sơ mất email,
        32 mất điện thoại, 5 hồ sơ mất cả hai và Hub không tạo được Person nào.

        Nay: ô `email`/`phone` giữ đúng MỘT giá trị đáng tin (ưu tiên giá trị lấy
        từ trang nhà tuyển dụng), còn toàn bộ giá trị bóc từ CV nằm riêng ở
        `cv_emails`/`cv_phones` để Hub đọc lại text CV rồi phân xử của ai.
        """
        from_site = cls._contact_list(existing_val, is_email)
        if from_site:
            return from_site[0]
        from_cv = cls._contact_list(cv_values, is_email)
        if not from_cv:
            return ''
        if is_email:
            for value in from_cv:
                if cls._email_matches_name(value, fullname):
                    return value
        return from_cv[0]

    def finish_document(self, row, result):
        return self.finish_document_v2(row, result)

    def finish_document_v2(self, row, result):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = result.get('text', '')
        fields = result.get('fields') or {}
        def finish(conn):
            conn.execute("""UPDATE candidate_documents SET parser_version=?,file_hash=?,file_size=?,file_mtime_ns=?,file_format=?,
                extraction_method=?,full_text=?,text_length=?,quality_score=?,needs_ocr=?,
                parse_status=?,parse_error=?,parsed_at=?,updated_at=?
                WHERE source=? AND account=? AND cv_id=?""",
                (str(result.get('parser_version') or '2'), result.get('file_hash',''), int(result.get('file_size') or 0),
                 int(result.get('file_mtime_ns') or 0), result.get('file_format',''), result.get('method',''),
                 text, len(text), result.get('quality',0), int(result.get('needs_ocr',False)),
                 result.get('status','done'), result.get('error',''), now, now,
                 row['source'], row['account'], row['cv_id']))
            candidate = conn.execute("SELECT rowid,* FROM candidates WHERE source=? AND account=? AND cv_id=?",
                                     (row['source'], row['account'], row['cv_id'])).fetchone()
            if not candidate:
                return

            # Liên hệ bóc từ CV. `email`/`phone` giữ ĐÚNG MỘT giá trị của chính
            # ứng viên (Hub dùng ô này làm định danh Person); toàn bộ giá trị đọc
            # được từ CV — trong đó thường có liên hệ của NGƯỜI THAM CHIẾU — nằm
            # riêng ở `cv_emails`/`cv_phones` để Hub phân xử bằng ngữ cảnh text CV.
            extracted_emails = self._contact_list(fields.get('emails') or [], True)
            extracted_phones = self._contact_list(fields.get('phones') or [], False)
            own_email = self._own_contact(candidate['email'], extracted_emails,
                                          candidate['fullname'], is_email=True)
            own_phone = self._own_contact(candidate['phone'], extracted_phones,
                                          candidate['fullname'], is_email=False)

            cand_updates = {}
            if own_email and own_email != str(candidate['email'] or '').strip():
                cand_updates['email'] = own_email
            if own_phone and own_phone != str(candidate['phone'] or '').strip():
                cand_updates['phone'] = own_phone
            if extracted_emails:
                cand_updates['cv_emails'] = json.dumps(extracted_emails, ensure_ascii=False)
            if extracted_phones:
                cand_updates['cv_phones'] = json.dumps(extracted_phones, ensure_ascii=False)

            # Phương án dự phòng cho ITViec/Joboko (không có "nơi làm việc mong
            # muốn" trên trang chi tiết): lấy từ text CV, CHỈ điền khi đang trống
            # để không đè giá trị đã bóc từ trang chi tiết của các nguồn khác.
            cv_desired_location = str(fields.get('desired_location') or '').strip()
            if cv_desired_location and not str(candidate['desired_location'] or '').strip():
                cand_updates['desired_location'] = cv_desired_location[:150]

            if cand_updates:
                cand_updates['updated_at'] = now
                set_clause = ", ".join(f"{k}=?" for k in cand_updates)
                conn.execute(f"UPDATE candidates SET {set_clause} WHERE rowid=?",
                             list(cand_updates.values()) + [candidate['rowid']])
                candidate = conn.execute("SELECT rowid,* FROM candidates WHERE rowid=?",
                                         (candidate['rowid'],)).fetchone()

            metadata = " ".join(str(candidate[key] or '') for key in (
                'fullname','email','phone','cv_emails','cv_phones',
                'position','skills','note','labels','address','city',
                'current_title','last_company','cv_id','campaign_id','candidate_id','resume_id',
                'source','account','status','apply_source'))
            conn.execute("DELETE FROM candidate_search WHERE rowid=?", (candidate['rowid'],))
            conn.execute("INSERT INTO candidate_search(rowid,text) VALUES(?,?)",
                         (candidate['rowid'], metadata + ' ' + text))
            conn.execute("""INSERT INTO candidate_extensions
                (source,account,cv_id,namespace,schema_version,payload,updated_at)
                VALUES (?,?,?,'cv_parser',2,?,?)
                ON CONFLICT(source,account,cv_id,namespace) DO UPDATE SET
                  schema_version=excluded.schema_version,payload=excluded.payload,updated_at=excluded.updated_at""",
                (row['source'], row['account'], row['cv_id'],
                 json.dumps({"status": result.get('status'), "method": result.get('method'),
                             "quality": result.get('quality'), "text_length": len(text),
                             "needs_ocr": bool(result.get('needs_ocr')), "fields": fields,
                             "error": result.get('error','')}, ensure_ascii=False), now))
        self._transaction(finish, "hoàn tất parsing CV")

    def document_stats(self):
        try:
            rows = self._read("SELECT parse_status,COUNT(*) n FROM candidate_documents "
                              "GROUP BY parse_status", operation="thống kê tài liệu").fetchall()
            result = {r['parse_status']: int(r['n']) for r in rows}
            result['total'] = sum(result.values())
            return result
        except sqlite3.OperationalError:
            return {"total": 0, "pending": 0, "done": 0, "error": 0}

    def stats_parsing(self, **filters):
        """Báo cáo parsing theo đúng tập ứng viên đang được lọc trên trang Báo cáo."""
        where, params = self._report_filters(**filters, prefix="c.")
        query = (
            "SELECT COALESCE(d.parse_status,'not_queued') status, "
            "COALESCE(NULLIF(d.extraction_method,''),'Chưa xác định') method, "
            "c.source, COUNT(*) n "
            "FROM candidates c "
            "LEFT JOIN candidate_documents d ON d.source=c.source AND d.account=c.account AND d.cv_id=c.cv_id "
            "WHERE 1=1" + where + " GROUP BY c.source, d.parse_status, d.extraction_method"
        )
        try:
            rows = self._read(query, params, operation="thống kê parsing").fetchall()
        except sqlite3.OperationalError:
            rows = []

        counts = {}
        methods_map = {}
        sources_map = {}
        for row in rows:
            st = row["status"]
            m = row["method"]
            src = row["source"]
            cnt = int(row["n"] or 0)

            counts[st] = counts.get(st, 0) + cnt
            if st == "done":
                methods_map[m] = methods_map.get(m, 0) + cnt

            src_entry = sources_map.setdefault(src, {"value": src, "total": 0, "done": 0})
            src_entry["total"] += cnt
            if st == "done":
                src_entry["done"] += cnt

        total = sum(counts.values())
        done = counts.get("done", 0)
        attention = sum(counts.get(key, 0) for key in
                        ("error", "empty", "needs_ocr", "unsupported"))
        return {
            "total": total, "done": done,
            "coverage": round(done * 100 / total, 1) if total else 0.0,
            "pending": counts.get("pending", 0) + counts.get("running", 0),
            "attention": attention, "not_queued": counts.get("not_queued", 0),
            "by_status": [{"value": key, "count": value} for key, value in sorted(counts.items(), key=lambda x: -x[1])],
            "by_method": [{"value": key, "count": value} for key, value in sorted(methods_map.items(), key=lambda x: -x[1])],
            "by_source": sorted(sources_map.values(), key=lambda row: row["total"], reverse=True),
        }

    def get_document(self, source, account, cv_id, text_limit=20000):
        with self.lock:
            row = self.conn.execute("""SELECT filename,file_format,parser_version,parse_status,
                extraction_method,text_length,quality_score,needs_ocr,attempts,parse_error,
                parsed_at,substr(full_text,1,?) AS text FROM candidate_documents
                WHERE source=? AND account=? AND cv_id=?""",
                (max(0, int(text_limit)), source, str(account or '').strip().lower(), str(cv_id))).fetchone()
            extension = self.conn.execute(
                "SELECT payload FROM candidate_extensions WHERE source=? AND account=? AND cv_id=? "
                "AND namespace='cv_parser'",
                (source, str(account or '').strip().lower(), str(cv_id))).fetchone()
        result = dict(row) if row else None
        if result is not None:
            try:
                import json
                result["fields"] = json.loads(extension["payload"]).get("fields", {}) if extension else {}
            except (TypeError, ValueError):
                result["fields"] = {}
        return result

    def get_document_summaries(self, identities):
        """Đọc trạng thái parsing của đúng trang ứng viên hiện tại bằng một truy vấn."""
        keys = [(str(source), str(account or '').strip().lower(), str(cv_id))
                for source, account, cv_id in identities]
        if not keys:
            return {}
        clauses = ["(source=? AND account=? AND cv_id=?)"] * len(keys)
        params = [value for key in keys for value in key]
        with self.lock:
            rows = self.conn.execute(
                "SELECT source,account,cv_id,file_format,parser_version,parse_status,"
                "extraction_method,text_length,quality_score,needs_ocr,attempts,parse_error,"
                "parsed_at FROM candidate_documents WHERE "
                + " OR ".join(clauses), params).fetchall()
            extensions = self.conn.execute(
                "SELECT source,account,cv_id,payload FROM candidate_extensions WHERE namespace='cv_parser' AND ("
                + " OR ".join(clauses) + ")", params).fetchall()
        result = {(row["source"], row["account"], row["cv_id"]): dict(row) for row in rows}
        import json
        for row in extensions:
            key = (row["source"], row["account"], row["cv_id"])
            if key not in result:
                continue
            try:
                result[key]["fields"] = json.loads(row["payload"]).get("fields", {})
            except (TypeError, ValueError):
                result[key]["fields"] = {}
        return result

    def query_parsing_documents(self, limit=50, offset=0, parse_status="", search="", source="",
                                account="", position="", date_from="", date_to=""):
        """Truy vấn danh sách kết quả bóc tách CV chi tiết có phân trang và bộ lọc.
        Chỉ hiển thị các hồ sơ đã từng qua xử lý parsing thực tế để tối ưu hiệu năng."""
        where = " WHERE TRIM(COALESCE(d.filename,''))<>''"
        params = []
        if parse_status:
            values = list(parse_status) if isinstance(parse_status, (list, tuple, set)) else [parse_status]
            where += " AND d.parse_status IN (" + ",".join("?" for _ in values) + ")"
            params.extend(values)
        else:
            # Mặc định chỉ lấy những hồ sơ đã từng qua parsing
            where += " AND d.parse_status IN ('done', 'needs_ocr', 'error', 'empty', 'unsupported') AND d.parsed_at IS NOT NULL"

        if search:
            where += " AND (c.fullname LIKE ? OR c.position LIKE ? OR d.filename LIKE ? OR d.cv_id LIKE ?)"
            pattern = f"%{search}%"
            params.extend([pattern, pattern, pattern, pattern])
        filter_sql, filter_params = self._report_filters(
            source=source, account=account, position=position, date_from=date_from, date_to=date_to, prefix="c.")
        where += filter_sql
        params.extend(filter_params)

        count_sql = f"""SELECT COUNT(*) n FROM candidate_documents d
            LEFT JOIN candidates c ON c.source=d.source AND c.account=d.account AND c.cv_id=d.cv_id {where}"""
        select_sql = f"""SELECT d.source, d.account, d.cv_id, d.filename, d.file_format,
            d.parser_version, d.parse_status, d.extraction_method, d.text_length,
            d.quality_score, d.needs_ocr, d.attempts, d.parse_error, d.parsed_at, d.updated_at,
            substr(d.full_text, 1, 300) AS text_preview,
            c.fullname, c.position, c.applied_at, c.applied_ts, c.email, c.phone
            FROM candidate_documents d
            LEFT JOIN candidates c ON c.source=d.source AND c.account=d.account AND c.cv_id=d.cv_id
            {where}
            ORDER BY d.parsed_at DESC, d.rowid DESC
            LIMIT ? OFFSET ?"""
        try:
            total = self._read(count_sql, params, operation="đếm tài liệu parsing").fetchone()["n"]
            rows = self._read(select_sql, params + [int(limit), int(offset)], operation="truy vấn danh sách parsing").fetchall()
            return [dict(r) for r in rows], total
        except sqlite3.OperationalError:
            return [], 0

    # ---------------- đọc ----------------
    def is_done(self, source, cv_id, account=None) -> bool:
        where, params = self._identity_where(source, cv_id, account)
        with self.lock:
            r = self.conn.execute(
                f"SELECT dl_status FROM candidates WHERE {where}", params).fetchone()
        return bool(r and r["dl_status"] == DONE)

    def get_filename(self, source, cv_id, account=None):
        where, params = self._identity_where(source, cv_id, account)
        with self.lock:
            r = self.conn.execute(
                f"SELECT filename FROM candidates WHERE {where}", params).fetchone()
        return r["filename"] if r else None

    def get_candidate(self, source, cv_id, account=None):
        where, params = self._identity_where(source, cv_id, account)
        with self.lock:
            return self.conn.execute(
                f"SELECT * FROM candidates WHERE {where}", params).fetchone()

    @staticmethod
    def _identity_where(source, cv_id, account=None):
        if account is None:
            return "source=? AND cv_id=?", (source, str(cv_id))
        return "source=? AND account=? AND cv_id=?", (
            source, str(account or "").strip().lower(), str(cv_id))

    def get_meta(self, key: str, default=None):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT value FROM meta WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else default

    def set_meta(self, key: str, value: str):
        self._write("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    (key, str(value)), "lưu checkpoint")

    def set_meta_many(self, values):
        """Lưu toàn bộ checkpoint trong một transaction ngắn."""
        rows = [(str(key), str(value)) for key, value in values.items()]
        if not rows:
            return

        def write(conn):
            conn.executemany(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", rows)

        self._transaction(write, "lưu checkpoint")

    def done_ids(self, source: str, account=None) -> set:
        """Lấy sẵn toàn bộ mã đã tải để kiểm tra trùng trong bộ nhớ (nhanh hơn hỏi từng dòng)."""
        with self.lock:
            if account is None:
                rows = self.conn.execute(
                    "SELECT cv_id FROM candidates WHERE source=? AND dl_status=?",
                    (source, DONE)).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT cv_id FROM candidates WHERE source=? AND account=? AND dl_status=?",
                    (source, str(account or "").strip().lower(), DONE)).fetchall()
        return {r["cv_id"] for r in rows}

    def all_ids(self, source: str, account=None) -> set:
        """Lấy toàn bộ mã đã ghi nhận để cập nhật KPI chính xác ngay trong lúc tải."""
        with self.lock:
            if account is None:
                rows = self.conn.execute(
                    "SELECT cv_id FROM candidates WHERE source=?", (source,)).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT cv_id FROM candidates WHERE source=? AND account=?",
                    (source, str(account or "").strip().lower())).fetchall()
        return {r["cv_id"] for r in rows}

    def count(self, source=None, only_done=False, account=None) -> int:
        q = "SELECT COUNT(*) n FROM candidates WHERE 1=1"
        p = []
        if source:
            q += " AND source=?"
            p.append(source)
        if account is not None:
            q += " AND account=?"
            p.append(str(account or "").strip().lower())
        if only_done:
            q += " AND dl_status=?"
            p.append(DONE)
        with self.lock:
            return self.conn.execute(q, p).fetchone()["n"]

    @staticmethod
    def _report_filters(source="", account="", position="", apply_source="", date_from="", date_to="",
                        prefix=""):
        q, p = "", []
        for column, value in (("source", source), ("account", account), ("position", position),
                              ("apply_source", apply_source)):
            if value:
                values = list(value) if isinstance(value, (list, tuple, set)) else [value]
                q += f" AND {prefix}{column} IN (" + ",".join("?" for _ in values) + ")"
                p.extend(values)
        if date_from:
            q += f" AND {prefix}applied_ts>=?"
            p.append(date_from)
        if date_to:
            q += f" AND {prefix}applied_ts<=?"
            p.append(date_to + " 23:59:59")
        return q, p

    def stats_unique_candidates(self, **filters):
        """Đếm nhóm người liên thông theo email hoặc điện thoại đã chuẩn hóa."""
        where, params = self._report_filters(**filters, prefix="x.")
        parent = {}
        def find(token):
            parent.setdefault(token, token)
            root = token
            while parent[root] != root:
                root = parent[root]
            while parent[token] != token:
                token, parent[token] = parent[token], root
            return root
        def union(left, right):
            left, right = find(left), find(right)
            if left != right:
                parent[right] = left
        anonymous = complete_contact = 0
        with self.lock:
            cursor = self.conn.execute(
                "SELECT c.email_key email, c.phone_key phone FROM candidate_contacts c "
                "JOIN candidates x USING(source,account,cv_id) WHERE 1=1" + where, params)
            for row in cursor:
                email = str(row["email"] or "")
                phone = str(row["phone"] or "")
                complete_contact += int(bool(email and phone))
                email_token = "e:" + email if email else ""
                phone_token = "p:" + phone if phone else ""
                if email_token and phone_token:
                    union(email_token, phone_token)
                elif email_token:
                    find(email_token)
                elif phone_token:
                    find(phone_token)
                else:
                    anonymous += 1
        components = len({find(token) for token in parent})
        return {"unique": components + anonymous, "complete_contact": complete_contact}

    def stats_by_source_account(self, **filters):
        where, params = self._report_filters(**filters)
        params = [DONE] + list(params)
        with self.lock:
            rows = self.conn.execute(
                "SELECT source, COALESCE(NULLIF(TRIM(account),''),'Không xác định') account, "
                "COUNT(*) n, SUM(CASE WHEN dl_status=? THEN 1 ELSE 0 END) done "
                "FROM candidates WHERE 1=1" + where +
                " GROUP BY source, account ORDER BY source, n DESC", params).fetchall()
        return [{"source": row["source"], "account": row["account"],
                 "count": row["n"], "done": row["done"]}
                for row in rows]

    def stats_report_summary(self, **filters):
        """KPI, chất lượng và ngày lỗi trong đúng một lần quét candidates."""
        where, params = self._report_filters(**filters)
        query = ("SELECT COUNT(*) n, "
                 "SUM(CASE WHEN dl_status=? THEN 1 ELSE 0 END) done, "
                 "SUM(CASE WHEN TRIM(COALESCE(email,''))<>'' THEN 1 ELSE 0 END) has_email, "
                 "SUM(CASE WHEN TRIM(COALESCE(phone,''))<>'' THEN 1 ELSE 0 END) has_phone, "
                 "SUM(CASE WHEN TRIM(COALESCE(filename,''))<>'' THEN 1 ELSE 0 END) has_file, "
                 "SUM(CASE WHEN COALESCE(detail_loaded,0)=1 THEN 1 ELSE 0 END) has_detail, "
                 "SUM(CASE WHEN applied_ts IS NOT NULL AND applied_ts<>'' AND NOT "
                 "(length(applied_ts)>=10 AND substr(applied_ts,1,10) "
                 "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]') "
                 "THEN 1 ELSE 0 END) invalid_dates FROM candidates WHERE 1=1")
        with self.lock:
            row = self.conn.execute(query + where, [DONE] + list(params)).fetchone()
        return {key: int(row[key] or 0) for key in
                ("n", "done", "has_email", "has_phone", "has_file", "has_detail",
                 "invalid_dates")}

    def stats_by_day_source(self, source="", account="", position="", apply_source="",
                            date_from="", date_to="", granularity="day"):
        period_len = 7 if granularity == "month" else 10
        where, params = self._report_filters(
            source, account, position, apply_source, date_from, date_to)
        query = (f"SELECT substr(applied_ts,1,{period_len}) d, source, COUNT(*) n FROM candidates "
                 "WHERE applied_ts IS NOT NULL AND length(applied_ts)>=10 AND "
                 "substr(applied_ts,1,10) GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'" +
                 where + " GROUP BY d, source ORDER BY d, source")
        with self.lock:
            rows = self.conn.execute(query, params).fetchall()
        return [{"date": row["d"], "source": row["source"], "count": row["n"]}
                for row in rows]

    def stats(self, source=None, account="", position="", apply_source="", date_from="", date_to=""):
        q = "SELECT COUNT(*) n FROM candidates WHERE 1=1"
        qd = "SELECT COUNT(*) n FROM candidates WHERE dl_status=?"
        where, params = self._report_filters(
            source or "", account, position, apply_source, date_from, date_to)
        q += where
        qd += where
        p, pd = list(params), [DONE] + list(params)
        with self.lock:
            total = self.conn.execute(q, p).fetchone()["n"]
            done = self.conn.execute(qd, pd).fetchone()["n"]
        return {"total": total, "done": done, "failed": total - done}

    def stats_by_position(self, source="", account="", position="", apply_source="",
                          date_from="", date_to="", limit=8):
        """Top N vị trí ứng tuyển nhiều ứng viên nhất - dùng cho biểu đồ báo cáo."""
        q = ("SELECT position, COUNT(*) n, "
             "SUM(CASE WHEN dl_status=? THEN 1 ELSE 0 END) done FROM candidates "
             "WHERE position IS NOT NULL AND position<>''")
        where, p = self._report_filters(
            source, account, position, apply_source, date_from, date_to)
        p.insert(0, DONE)
        q += where
        q += " GROUP BY position ORDER BY n DESC LIMIT ?"
        p.append(int(limit))
        with self.lock:
            rows = self.conn.execute(q, p).fetchall()
        return [{"position": r["position"], "count": r["n"], "done": r["done"]} for r in rows]

    def stats_by_day(self, source="", account="", position="", apply_source="",
                     date_from="", date_to="", days=30, granularity="day"):
        """Số ứng viên ứng tuyển theo từng ngày, N ngày gần nhất - dùng cho biểu đồ xu hướng.
        Ngày không có ứng viên nào sẽ KHÔNG có mặt ở đây (bên gọi tự lấp 0 cho đủ dải ngày)."""
        period_len = 7 if granularity == "month" else 10
        q = (f"SELECT substr(applied_ts,1,{period_len}) d, COUNT(*) n FROM candidates "
             "WHERE applied_ts IS NOT NULL AND applied_ts<>'' "
             "AND length(applied_ts)>=10 "
             "AND substr(applied_ts,1,10) GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'")
        if not date_from and days:
            date_from = (datetime.now() - timedelta(days=max(0, int(days) - 1))).strftime("%Y-%m-%d")
        where, p = self._report_filters(
            source, account, position, apply_source, date_from, date_to)
        q += where
        q += " GROUP BY d ORDER BY d"
        with self.lock:
            rows = self.conn.execute(q, p).fetchall()
        return [{"date": r["d"], "count": r["n"]} for r in rows]

    def count_invalid_applied_dates(self, source="", account="", position="", apply_source="",
                                    date_from="", date_to=""):
        q = ("SELECT COUNT(*) n FROM candidates WHERE applied_ts IS NOT NULL AND applied_ts<>'' "
             "AND NOT (length(applied_ts)>=10 AND "
             "substr(applied_ts,1,10) GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]')")
        where, p = self._report_filters(
            source, account, position, apply_source, date_from, date_to)
        with self.lock:
            return int(self.conn.execute(q + where, p).fetchone()["n"] or 0)

    def stats_by_channel(self, source="", account="", position="", apply_source="",
                         date_from="", date_to="", limit=12):
        q = ("SELECT COALESCE(NULLIF(TRIM(apply_source),''),'Không xác định') channel, COUNT(*) n, "
             "SUM(CASE WHEN dl_status=? THEN 1 ELSE 0 END) done "
             "FROM candidates WHERE 1=1")
        where, p = self._report_filters(
            source, account, position, apply_source, date_from, date_to)
        p.insert(0, DONE)
        q += where + " GROUP BY channel ORDER BY n DESC LIMIT ?"
        p.append(int(limit))
        with self.lock:
            rows = self.conn.execute(q, p).fetchall()
        return [{"channel": r["channel"], "count": r["n"], "done": r["done"]} for r in rows]

    def stats_by_source(self, source="", account="", position="", apply_source="",
                        date_from="", date_to=""):
        q = ("SELECT source, COUNT(*) n, "
             "SUM(CASE WHEN dl_status=? THEN 1 ELSE 0 END) done "
             "FROM candidates WHERE 1=1")
        where, p = self._report_filters(
            source, account, position, apply_source, date_from, date_to)
        p.insert(0, DONE)
        q += where + " GROUP BY source ORDER BY n DESC"
        with self.lock:
            rows = self.conn.execute(q, p).fetchall()
        return [{"source": r["source"], "count": r["n"], "done": r["done"]} for r in rows]

    def stats_by_status(self, source="", account="", position="", apply_source="",
                        date_from="", date_to="", limit=12):
        q = ("SELECT COALESCE(NULLIF(TRIM(status),''),'Chưa xác định') status, COUNT(*) n "
             "FROM candidates WHERE 1=1")
        where, p = self._report_filters(
            source, account, position, apply_source, date_from, date_to)
        q += where + " GROUP BY status ORDER BY n DESC LIMIT ?"
        p.append(int(limit))
        with self.lock:
            rows = self.conn.execute(q, p).fetchall()
        return [{"status": r["status"], "count": r["n"]} for r in rows]

    def stats_quality(self, source="", account="", position="", apply_source="",
                      date_from="", date_to=""):
        q = ("SELECT COUNT(*) n, "
             "SUM(CASE WHEN TRIM(COALESCE(email,''))<>'' THEN 1 ELSE 0 END) has_email, "
             "SUM(CASE WHEN TRIM(COALESCE(phone,''))<>'' THEN 1 ELSE 0 END) has_phone, "
             "SUM(CASE WHEN TRIM(COALESCE(filename,''))<>'' THEN 1 ELSE 0 END) has_file, "
             "SUM(CASE WHEN COALESCE(detail_loaded,0)=1 THEN 1 ELSE 0 END) has_detail "
             "FROM candidates WHERE 1=1")
        where, p = self._report_filters(
            source, account, position, apply_source, date_from, date_to)
        with self.lock:
            row = self.conn.execute(q + where, p).fetchone()
        return {key: int(row[key] or 0) for key in
                ("n", "has_email", "has_phone", "has_file", "has_detail")}

    def _build_filter(self, search="", source="", account="", dl_status="", position="",
                      date_from="", date_to=""):
        q, p = " WHERE 1=1", []
        if search:
            fts_query = self._fts_boolean_query(search)
            if fts_query:
                q += " AND rowid IN (SELECT rowid FROM candidate_search WHERE candidate_search MATCH ?)"
                p.append(fts_query)
        if source:
            values = list(source) if isinstance(source, (list, tuple, set)) else [source]
            q += " AND source IN (" + ",".join("?" for _ in values) + ")"
            p.extend(values)
        if account:
            values = list(account) if isinstance(account, (list, tuple, set)) else [account]
            q += " AND account IN (" + ",".join("?" for _ in values) + ")"
            p.extend(values)
        if dl_status == "done":
            q += " AND dl_status=?"
            p.append(DONE)
        elif dl_status == "failed":
            q += " AND (dl_status IS NULL OR dl_status<>?)"
            p.append(DONE)
        if position:
            q += " AND position=?"
            p.append(position)
        if date_from:
            q += " AND applied_ts>=?"
            p.append(date_from)
        if date_to:
            q += " AND applied_ts<=?"
            p.append(date_to + " 23:59:59")
        return q, p

    @staticmethod
    def _fts_boolean_query(search):
        """Biên dịch Boolean Search an toàn sang FTS5: AND, OR, NOT và cụm từ kép."""
        raw_tokens = re.findall(r'"[^"]+"|\S+', str(search or ""), flags=re.UNICODE)
        output = []
        previous_was_term = False
        pending_operator = None
        for raw in raw_tokens:
            upper = raw.upper()
            if raw == upper and upper in {"AND", "OR", "NOT"}:
                if previous_was_term:
                    pending_operator = upper
                continue
            quoted = len(raw) >= 2 and raw.startswith('"') and raw.endswith('"')
            terms = re.findall(r"\w+", raw[1:-1] if quoted else raw.lower(), flags=re.UNICODE)
            if not terms:
                continue
            if quoted:
                operand = '"' + " ".join(terms) + '"'
            else:
                operand = " AND ".join(f'"{term}"*' for term in terms)
                if len(terms) > 1:
                    operand = f"({operand})"
            if previous_was_term:
                output.append(pending_operator or "AND")
            output.append(operand)
            previous_was_term = True
            pending_operator = None
        return " ".join(output)

    def query(self, limit=200, offset=0, order="applied_ts DESC", columns=None, **filters):
        where, p = self._build_filter(**filters)
        if columns is None:
            select_columns = "*"
        else:
            safe_columns = [name for name in columns if name in _FIELDS]
            if not safe_columns:
                raise ValueError("Danh sách cột truy vấn không hợp lệ")
            select_columns = ", ".join(safe_columns)
        with self.lock:
            total = self.conn.execute(
                "SELECT COUNT(*) n FROM candidates" + where, p).fetchone()["n"]
            rows = self.conn.execute(
                f"SELECT {select_columns} FROM candidates{where} ORDER BY {order} LIMIT ? OFFSET ?",
                p + [limit, offset]).fetchall()
        return rows, total

    def candidate_filter_breakdown(self, **filters):
        """Phân rã toàn bộ kết quả lọc theo nguồn và năm ứng tuyển."""
        where, params = self._build_filter(**filters)
        with self.lock:
            source_rows = self.conn.execute(
                "SELECT COALESCE(NULLIF(TRIM(source),''),'unknown') value, COUNT(*) n "
                "FROM candidates" + where + " GROUP BY value ORDER BY n DESC, value", params
            ).fetchall()
            year_rows = self.conn.execute(
                "SELECT CASE WHEN substr(COALESCE(applied_ts,''),1,4) "
                "GLOB '[0-9][0-9][0-9][0-9]' THEN substr(applied_ts,1,4) "
                "ELSE 'Không rõ năm' END value, COUNT(*) n FROM candidates" + where +
                " GROUP BY value ORDER BY CASE WHEN value='Không rõ năm' THEN 1 ELSE 0 END, "
                "value DESC", params).fetchall()
        return {
            "by_source": [{"value": row["value"], "count": int(row["n"])}
                          for row in source_rows],
            "by_year": [{"value": row["value"], "count": int(row["n"])}
                        for row in year_rows],
        }

    def query_all(self, **filters):
        where, p = self._build_filter(**filters)
        with self.lock:
            return self.conn.execute(
                f"SELECT * FROM candidates{where} ORDER BY applied_ts DESC", p).fetchall()

    def iter_query(self, *, batch_size=2000, columns=None, **filters):
        """Đọc kết quả theo batch; không giữ toàn bộ tập dữ liệu trong RAM."""
        where, params = self._build_filter(**filters)
        safe_columns = [name for name in (columns or _FIELDS) if name in _FIELDS]
        if not safe_columns:
            raise ValueError("Danh sách cột truy vấn không hợp lệ")
        with self.lock:
            cursor = self.conn.execute(
                f"SELECT {', '.join(safe_columns)} FROM candidates{where} "
                "ORDER BY applied_ts DESC", params)
            while True:
                rows = cursor.fetchmany(max(100, min(10000, int(batch_size))))
                if not rows:
                    break
                yield rows

    def set_extension(self, source, account, cv_id, namespace, payload, schema_version=1):
        """Lưu dữ liệu parser/mô hình ngoài bảng lõi để schema có thể tiến hóa độc lập."""
        import json
        body = payload if isinstance(payload, str) else json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"))
        self._write(
            "INSERT INTO candidate_extensions(source,account,cv_id,namespace,schema_version,payload,updated_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(source,account,cv_id,namespace) DO UPDATE SET "
            "schema_version=excluded.schema_version,payload=excluded.payload,updated_at=excluded.updated_at",
            (str(source), str(account or "").strip().lower(), str(cv_id), str(namespace),
             int(schema_version), body, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "lưu dữ liệu mở rộng")
        # Extension là một phần của hồ sơ nguồn. Nếu không chạm outbox thì thay
        # đổi parser chỉ nằm lại Edge cho tới một lần full sync tình cờ.
        try:
            from .sync.payload import (ENTITY_SOURCE_RECORD, candidate_key,
                                       candidate_payload, payload_hash)
            row = self.get_candidate(str(source), str(cv_id), str(account or ""))
            if row:
                record = dict(row)
                body = candidate_payload(record, extensions=self.get_extensions(
                    source, account, cv_id))
                self.enqueue_sync(ENTITY_SOURCE_RECORD, candidate_key(record),
                                  payload_hash(body))
        except Exception:
            # Dữ liệu extension đã commit; lần full scan vẫn vớt được. Không để
            # quan sát đồng bộ phụ làm hỏng chính tác vụ parsing.
            pass

    def get_extensions(self, source, account, cv_id):
        import json
        with self.lock:
            rows = self.conn.execute(
                "SELECT namespace,schema_version,payload,updated_at FROM candidate_extensions "
                "WHERE source=? AND account=? AND cv_id=?",
                (str(source), str(account or "").strip().lower(), str(cv_id))).fetchall()
        result = {}
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                payload = row["payload"]
            result[row["namespace"]] = {"schema_version": row["schema_version"],
                                        "payload": payload, "updated_at": row["updated_at"]}
        return result

    def query_selected(self, identities):
        """Lấy đúng các dòng người dùng đã tích, theo khóa ghép của ứng viên."""
        rows = []
        seen = set()
        for item in identities or []:
            key = (str(item.get("source") or ""),
                   str(item.get("account") or "").strip().lower(),
                   str(item.get("cv_id") or ""))
            if not key[0] or not key[2] or key in seen:
                continue
            seen.add(key)
            row = self.get_candidate(key[0], key[2], key[1])
            if row:
                rows.append(row)
        return rows

    @staticmethod
    def _normalized_phone(value):
        return "".join(char for char in str(value or "") if char.isdigit())

    def candidate_alerts(self, rows):
        """Tổng hợp cảnh báo theo người, ghép bằng email hoặc số điện thoại chuẩn hóa."""
        seed = [dict(row) for row in rows]
        emails = {str(row.get("email") or "").strip().lower() for row in seed
                  if str(row.get("email") or "").strip()}
        phones = {self._normalized_phone(row.get("phone")) for row in seed
                  if self._normalized_phone(row.get("phone"))}
        # Tra theo index liên hệ và chia nhỏ để không vượt giới hạn biến SQLite;
        # tuyệt đối không tải toàn bộ corpus chỉ vì batch export lớn.
        corpus_map = {}
        select_sql = ("SELECT x.source,x.account,x.cv_id,x.fullname,x.email,x.phone,x.position,"
                      "x.applied_at,x.applied_ts,x.dl_status,x.filename FROM candidate_contacts c "
                      "JOIN candidates x USING(source,account,cv_id) WHERE ")
        with self.lock:
            for column, values in (("c.email_key", sorted(emails)),
                                   ("c.phone_key", sorted(phones))):
                for start in range(0, len(values), 400):
                    chunk = values[start:start + 400]
                    if not chunk:
                        continue
                    rows_found = self.conn.execute(
                        select_sql + column + " IN (" + ",".join("?" for _ in chunk) + ")",
                        chunk).fetchall()
                    for found in rows_found:
                        record = dict(found)
                        corpus_map[(record["source"], record["account"], record["cv_id"])] = record
        corpus = list(corpus_map.values()) or seed

        by_email, by_phone = {}, {}
        for record in corpus:
            email = str(record.get("email") or "").strip().lower()
            phone = self._normalized_phone(record.get("phone"))
            if email:
                by_email.setdefault(email, []).append(record)
            if phone:
                by_phone.setdefault(phone, []).append(record)

        result = {}
        for row in seed:
            email = str(row.get("email") or "").strip().lower()
            phone = self._normalized_phone(row.get("phone"))
            matches = {}
            for record in by_email.get(email, []) + by_phone.get(phone, []):
                key = (record.get("source"), record.get("account"), record.get("cv_id"))
                matches[key] = record
            records = list(matches.values()) or [row]
            positions = sorted({str(r.get("position") or "Chưa rõ") for r in records})
            sources = sorted({str(r.get("source") or "").upper() for r in records if r.get("source")})
            details = []
            if len(records) > 1:
                details.append(f"Ứng viên xuất hiện/ứng tuyển {len(records)} lần.")
                details.append("Vị trí: " + "; ".join(positions) + ".")
                if sources:
                    details.append("Nguồn: " + ", ".join(sources) + ".")
                def history_date(record):
                    for value, formats in (
                        (record.get("applied_ts"), ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")),
                        (record.get("applied_at"), ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y")),
                    ):
                        text = str(value or "").strip().replace("T", " ")[:19]
                        for fmt in formats:
                            try:
                                return datetime.strptime(text[:len(datetime.now().strftime(fmt))], fmt)
                            except ValueError:
                                continue
                    return datetime.min
                ordered = sorted(records, key=history_date, reverse=True)
                history = [f"{index}. {r.get('applied_at') or 'Không rõ ngày'} — "
                           f"{r.get('position') or 'Chưa rõ vị trí'} ({str(r.get('source') or '').upper()})"
                           for index, r in enumerate(ordered, start=1)]
                details.append("Lịch sử: " + " | ".join(history) + ".")
            if not email and not phone:
                details.append("Thiếu cả email và số điện thoại để đối chiếu/liên hệ.")
            elif not email:
                details.append("Thiếu email.")
            elif not phone:
                details.append("Thiếu số điện thoại.")
            if str(row.get("dl_status") or "") != DONE or not row.get("filename"):
                details.append("CV chưa tải thành công hoặc chưa có file.")
            short = (f"🔁 {len(records)} lần" if len(records) > 1 else
                     ("⚠ Thiếu LH" if not email or not phone else
                      ("⚠ Lỗi CV" if details else "")))
            identity = (row.get("source"), row.get("account"), row.get("cv_id"))
            applications = [{
                "source": record.get("source") or "",
                "account": record.get("account") or "",
                "cv_id": record.get("cv_id") or "",
                "applied_at": record.get("applied_at") or "Không rõ ngày",
                "position": record.get("position") or "Chưa rõ vị trí",
                "filename": record.get("filename") or "",
                "dl_status": record.get("dl_status") or "",
            } for record in sorted(records, key=history_date, reverse=True)] if len(records) > 1 else []
            result[identity] = {"short": short, "detail": "\n".join(details),
                                "applications": applications}
        return result

    def distinct(self, column, source=""):
        if column not in _FIELDS:
            return []
        q = f"SELECT DISTINCT {column} v FROM candidates WHERE {column} IS NOT NULL AND {column}<>''"
        p = []
        if source:
            values = list(source) if isinstance(source, (list, tuple, set)) else [source]
            q += " AND source IN (" + ",".join("?" for _ in values) + ")"
            p.extend(values)
        with self.lock:
            return [r["v"] for r in self.conn.execute(q + f" ORDER BY {column}", p).fetchall()]

    def candidate_filter_accounts(self):
        with self.lock:
            rows = self.conn.execute(
                "SELECT source, account, COUNT(*) count FROM candidates "
                "WHERE TRIM(COALESCE(account,''))<>'' GROUP BY source, account "
                "ORDER BY source, account").fetchall()
        return [dict(row) for row in rows]

    # ---------------- chuyển dữ liệu từ Excel cũ ----------------
    def import_from_excel(self, xlsx_path, source="topcv") -> int:
        """Nạp dữ liệu từ file Excel của phiên bản cũ (nếu có) để không phải tải lại."""
        if not os.path.exists(xlsx_path):
            return 0
        try:
            from openpyxl import load_workbook
            wb = load_workbook(xlsx_path, data_only=True, read_only=True)
        except Exception:
            return 0
        ws = wb[wb.sheetnames[0]]
        rows = ws.iter_rows(values_only=True)
        try:
            header = [str(h or "").strip() for h in next(rows)]
        except StopIteration:
            return 0
        idx = {h: i for i, h in enumerate(header)}
        if "Mã CV" not in idx:
            return 0

        def g(r, name):
            i = idx.get(name)
            return r[i] if i is not None and i < len(r) else None

        n = 0
        for r in rows:
            cid = g(r, "Mã CV")
            if not cid:
                continue
            self.upsert({
                "source": source, "cv_id": str(cid),
                "fullname": g(r, "Họ tên") or g(r, "Họ Tên"),
                "email": g(r, "Email"), "phone": g(r, "Số điện thoại"),
                "position": g(r, "Vị trí ứng tuyển"), "campaign_id": g(r, "Mã tin"),
                "applied_at": g(r, "Ngày ứng tuyển"), "status": g(r, "Trạng thái"),
                "filename": g(r, "Tên file CV"), "dl_status": g(r, "Tình trạng tải"),
                "cv_url": g(r, "Link xem CV"),
            })
            n += 1
        self.commit()
        wb.close()
        if n:
            self.log(f"Đã chuyển {n:,} dòng từ file Excel cũ sang cơ sở dữ liệu.")
        return n

    # ---------------- Quản lý Nhật ký (App Logs) ----------------
    def insert_log(self, message: str, level: str = "INFO", source: str = "system") -> None:
        """Ghi 1 dòng nhật ký mới vào CSDL.

        KHÔNG tự commit ở đây (giống hệt cách upsert() dồn lại commit theo đợt), và PHẢI
        khoá self.lock như mọi hàm ghi khác. Trước đây hàm này commit sau MỖI dòng - khi
        đang tải nhiều CV cùng lúc (nhiều luồng cùng gọi log()), mỗi dòng phải chờ ghi
        đĩa qua Google Drive xong mới thôi, mà lại không khoá nên nhiều luồng ghi chồng
        lên nhau cùng lúc trên một kết nối. Việc commit định kỳ do luồng gom lô cập nhật
        giao diện đảm nhiệm (xem Api._flush_ui trong web_api.py).
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            self.conn.execute(
                "INSERT INTO app_logs (source, level, message, created_at) VALUES (?, ?, ?, ?)",
                (source, level, message, now_str)
            )

    def insert_logs(self, rows) -> None:
        """Ghi một lô log trong một giao dịch để tránh khóa SQLite cho từng dòng."""
        if not rows:
            return
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        values = [(source, level, message, created_at or now_str)
                  for source, level, message, created_at in rows]
        with self.lock:
            self.conn.executemany(
                "INSERT INTO app_logs (source, level, message, created_at) VALUES (?, ?, ?, ?)",
                values
            )

    def query_logs(self, limit: int = 200, offset: int = 0, level: str = "", search: str = ""):
        """Truy vấn danh sách nhật ký có phân trang và bộ lọc."""
        sql = "SELECT id, source, level, message, created_at FROM app_logs WHERE 1=1"
        params = []

        if level:
            sql += " AND level = ?"
            params.append(level)
        if search:
            sql += " AND message LIKE ?"
            params.append(f"%{search}%")

        count_sql = sql.replace("SELECT id, source, level, message, created_at", "SELECT COUNT(*)")
        cur = self.conn.execute(count_sql, params)
        total = cur.fetchone()[0]

        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cur = self.conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        return rows, total

    def clean_old_logs(self, days: int = 30) -> int:
        """Xóa các log quá cũ (> days ngày) để giữ CSDL luôn gọn nhẹ."""
        try:
            cur = self.conn.execute(
                "DELETE FROM app_logs WHERE created_at < datetime('now', '-' || ? || ' days')",
                (str(days),)
            )
            self.conn.commit()
            return cur.rowcount
        except Exception:
            return 0
