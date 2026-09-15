# -*- coding: utf-8 -*-
"""Rút hàng đợi outbox và đẩy lên Hub.

Đây là toàn bộ phần "gửi" của Phase 2. Cố ý không có nghiệp vụ nào ở đây: không
gộp Person, không phân giải định danh, không chấm điểm. Edge chỉ báo cáo những
gì nó thu thập được; mọi diễn giải thuộc về Hub.

Ba tính chất mà Master Plan mục 9 yêu cầu ở mọi lượt đồng bộ:

  idempotent   cùng entity_key + payload_hash gửi lại là no-op ở phía Hub
  retryable    lỗi tạm thời được hẹn lại với backoff luỹ thừa có jitter
  resume-able  trạng thái nằm trong SQLite; tắt máy giữa chừng rồi mở lại là
               chạy tiếp, recover_sync_queue() nhặt lại các hàng inflight
"""
import hashlib
import os

from .client import HubAuthError, HubError
from .payload import (ENTITY_DOCUMENT, ENTITY_SOURCE_RECORD, candidate_key,
                      candidate_payload, document_payload, idempotency_key,
                      payload_hash)

#: Giới hạn kích thước file Hub chấp nhận (`server/core/documents.py::MAX_FILE_BYTES`).
#:
#: Chép sang đây thay vì hỏi Hub: kiểm tra trước khi gửi thì tiết kiệm cả lượt
#: tải lên lẫn 8 lần thử lại vô ích. Lệch nhau thì Hub vẫn là người quyết định —
#: nó từ chối, và Edge ghi nhận thất bại kèm lý do.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024



def scan_candidates(db, limit=1000, after_rowid=0):
    """Quét bảng candidates và xếp hàng những bản ghi thật sự thay đổi.

    Trả về (số hàng đã xếp, rowid cuối cùng đã xét). rowid cuối cho phép quét
    từng lô mà không giữ một truy vấn lớn mở trên CSDL nằm ở Google Drive.

    Rẻ khi chạy lại: enqueue_sync() so payload_hash nên bản ghi không đổi sẽ
    không sinh việc mới.
    """
    # Chỉ đồng bộ ứng viên khi CV của họ đã bóc tách xong (kể cả bóc lỗi) - nhờ vậy
    # Hub luôn nhận kèm dữ liệu liên hệ đã trích từ CV, không phải bản chưa parse.
    # Ứng viên không có bản ghi tài liệu nào (tải lỗi, hoặc máy chưa bật parsing)
    # vẫn được đồng bộ như cũ.
    rows = db._read(
        """SELECT c.rowid AS rowid, c.*
             FROM candidates c
             LEFT JOIN candidate_documents d
               ON d.source=c.source AND d.account=c.account AND d.cv_id=c.cv_id
            WHERE c.rowid > ?
              AND (d.cv_id IS NULL OR d.parse_status IN
                   ('done','empty','needs_ocr','unsupported','error'))
            ORDER BY c.rowid LIMIT ?""",
        (int(after_rowid), int(limit)), "quét ứng viên để đồng bộ").fetchall()

    queued, last_rowid = 0, int(after_rowid)
    for row in rows:
        record = dict(row)
        last_rowid = int(record.get("rowid") or last_rowid)
        payload = candidate_payload(record, extensions=db.get_extensions(
            record.get("source"), record.get("account"), record.get("cv_id")))
        if db.enqueue_sync(ENTITY_SOURCE_RECORD, candidate_key(record), payload_hash(payload)):
            queued += 1
    return queued, last_rowid


def scan_all_candidates(db, batch_size=1000):
    """Quét toàn bộ bảng candidates theo từng lô. Trả tổng số hàng đã xếp."""
    total, cursor = 0, 0
    while True:
        queued, last_rowid = scan_candidates(db, batch_size, cursor)
        total += queued
        if last_rowid <= cursor:
            return total
        cursor = last_rowid


def scan_documents(db, cv_folder, limit=1000, after_rowid=0):
    """Xếp hàng các file CV đã tải về và đã bóc tách xong.

    Trả `(số hàng đã xếp, rowid cuối cùng đã xét)` — cùng khuôn với
    `scan_candidates()`, để `scan_all_documents()` phân trang được.

    Chỉ xếp hàng những hàng có `file_hash` — không có mã băm thì Hub không khử
    trùng lặp được, mà khử trùng lặp theo nội dung chính là thứ khiến "cùng một
    người, nhiều lượt ứng tuyển" trở thành nhiều phiên bản CV thay vì nhiều bản
    sao của cùng một file.

    Cũng kiểm tra file thật sự còn trên đĩa: CSDL có thể còn hàng trong khi file
    đã bị dọn đi, và xếp hàng một file không tồn tại chỉ tạo việc thất bại.
    """
    # Xếp theo `rowid` chứ không theo `updated_at DESC`: thứ tự theo ngày sửa
    # không phân trang được, nên bản cũ chỉ lấy 1000 hàng mới nhất rồi dừng —
    # với kho ~20.000 CV thì 19.000 file còn lại KHÔNG BAO GIỜ được xếp hàng.
    # Lần quét sau cũng không cứu được: `enqueue_sync` trả False cho hàng không
    # đổi, nên hàng đợi trống và người dùng tưởng đã đồng bộ xong.
    rows = db._read(
        """SELECT d.rowid AS rowid, d.source, d.account, d.cv_id, d.filename,
                  d.file_hash, d.file_size, d.file_format, d.parse_status,
                  d.quality_score, d.text_length, c.applied_ts
             FROM candidate_documents d
             LEFT JOIN candidates c
               ON c.source=d.source AND c.account=d.account AND c.cv_id=d.cv_id
            WHERE d.file_hash <> '' AND d.filename <> '' AND d.rowid > ?
              AND d.parse_status IN ('done','empty','needs_ocr','unsupported','error')
            ORDER BY d.rowid LIMIT ?""",
        (int(after_rowid), int(limit)), "quét tài liệu để đồng bộ").fetchall()

    queued, last_rowid = 0, int(after_rowid)
    for row in rows:
        record = dict(row)
        last_rowid = int(record.pop("rowid", None) or last_rowid)
        if not _document_path(cv_folder, record.get("filename")):
            continue
        record["sha256"] = record.pop("file_hash", "")
        record["observed_at"] = record.pop("applied_ts", "") or ""
        payload = document_payload(record)
        if db.enqueue_sync(ENTITY_DOCUMENT, candidate_key(record), payload_hash(payload)):
            queued += 1
    return queued, last_rowid


def scan_all_documents(db, cv_folder, batch_size=1000):
    """Quét toàn bộ tài liệu theo từng lô. Trả tổng số hàng đã xếp.

    Đối xứng với `scan_all_candidates()`. Thiếu hàm này chính là lý do bản cũ
    chỉ đồng bộ được 1000 CV mới nhất.
    """
    total, cursor = 0, 0
    while True:
        queued, last_rowid = scan_documents(db, cv_folder, batch_size, cursor)
        total += queued
        if last_rowid <= cursor:
            return total
        cursor = last_rowid


def _document_path(cv_folder, filename):
    """Đường dẫn file CV nếu nó thật sự tồn tại, ngược lại chuỗi rỗng.

    Chốt chặn thoát thư mục: `filename` đến từ CSDL, vốn được điền từ dữ liệu của
    nhà cung cấp — không được để nó trỏ ra ngoài thư mục CV.
    """
    name = str(filename or "").strip()
    if not name or not cv_folder:
        return ""
    root = os.path.abspath(str(cv_folder))
    path = os.path.abspath(os.path.join(root, name))
    if not path.startswith(root + os.sep):
        return ""
    return path if os.path.isfile(path) else ""


def push_once(db, client, edge_id="", batch_size=50, log=print, cv_folder=""):
    """Nhận một lô, gửi lên Hub, ghi nhận kết quả từng bản ghi.

    Trả dict thống kê. Không bao giờ ném lỗi ra ngoài: đồng bộ hỏng không được
    phép làm dừng việc thu thập CV.

    `cv_folder` cần cho pha hai của đồng bộ tài liệu — nơi lấy nội dung file CV.
    """
    result = {"claimed": 0, "synced": 0, "retry": 0, "failed": 0, "skipped": 0,
              "uploaded": 0, "error": ""}

    batch = db.claim_sync_batch(batch_size)
    result["claimed"] = len(batch)
    if not batch:
        return result

    records, by_key = [], {}
    for row in batch:
        if len(str(row["entity_key"]).split("|")) != 3:
            # Khoá sai khuôn — `account` hoặc `cv_id` chứa dấu «|». Đây KHÔNG
            # phải thực thể đã bị xoá, nên không được đánh dấu là đã gửi: bản cũ
            # làm vậy và hàng đó biến mất khỏi hàng đợi trong khi Hub chưa hề
            # nhận gì. Mất dữ liệu im lặng, không cách nào phát hiện.
            db.fail_sync(row["id"], "Khoá thực thể sai khuôn (chứa dấu |).", False)
            result["failed"] += 1
            continue

        payload = _rebuild_payload(db, row, edge_id)
        if payload is None:
            # Thực thể đã bị xoá cục bộ sau khi được xếp hàng. Không còn gì để
            # gửi, và giữ nó lại sẽ chặn hàng đợi mãi.
            db.finish_sync(row["id"], "")
            result["skipped"] += 1
            continue
        payload["idempotency_key"] = idempotency_key(
            edge_id, row["entity_type"], row["entity_key"], row["payload_hash"])
        records.append(payload)
        # Khoá theo CẶP: tài liệu và lượt ứng tuyển dùng chung entity_key.
        by_key[(row["entity_type"], row["entity_key"])] = row

    if not records:
        return result

    try:
        responses = client.push_batch(records)
    except HubAuthError as exc:
        # Khoá bị thu hồi, khoá vừa xoay, hoặc Edge bị vô hiệu hoá.
        #
        # KHÔNG đánh dấu thất bại: `fail_sync(retryable=False)` ghi thẳng
        # `failed` không qua backoff, nên một lần xoay khoá giữa lúc đang đồng
        # bộ sẽ chôn 50 bản ghi mỗi lô — dữ liệu Hub hoàn toàn nhận được ngay
        # khi khoá mới được nhập. Trả hàng về `pending` và dừng lượt này: người
        # dùng sửa khoá xong thì lượt sau tiếp đúng chỗ đang dở.
        db.release_sync_batch([row["id"] for row in by_key.values()])
        result["error"] = f"Xác thực với Hub thất bại: {exc}"
        log(result["error"])
        return result
    except HubError as exc:
        # Cả lô thất bại cùng một lý do. Retryable hay không do client quyết định.
        for row in by_key.values():
            if db.fail_sync(row["id"], str(exc), getattr(exc, "retryable", True)):
                result["retry"] += 1
            else:
                result["failed"] += 1
        result["error"] = str(exc)
        log(f"Đồng bộ Hub thất bại: {exc}")
        return result

    # Nội dung đã tải lên trong chính lô này, để không gửi hai lần cùng một file.
    uploaded_hashes = set()

    for key, row in by_key.items():
        answer = responses.get(key)
        if answer is None and key[0] == ENTITY_SOURCE_RECORD:
            # Hub cũ trả kết quả không kèm entity_type; client đã quy về
            # source_record nên chỉ nhánh này cần dò lại.
            answer = responses.get((ENTITY_SOURCE_RECORD, key[1]))
        if answer is None:
            # Hub không nhắc tới bản ghi này. Coi là tạm thời và gửi lại — thà
            # gửi thừa (Hub chống trùng được) còn hơn âm thầm mất dữ liệu.
            if db.fail_sync(row["id"], "Hub không trả kết quả cho bản ghi này", True):
                result["retry"] += 1
            else:
                result["failed"] += 1
            continue

        status = str(answer.get("status") or "").lower()
        if status in ("accepted", "duplicate", "updated"):
            # Pha 2: Hub báo chưa có nội dung file thì mới tải lên. Nhờ vậy một CV
            # không đổi vĩnh viễn không bị gửi lại.
            digest = str(answer.get("sha256") or "")
            if answer.get("needs_file") and digest in uploaded_hashes:
                # Cùng một nội dung đã tải lên ở bản ghi trước trong CHÍNH lô này.
                # Hub tính needs_file cho cả lô trước khi có lượt tải nào, nên
                # nó chưa thể biết. Một người nộp cùng CV cho hai cổng là chuyện
                # thường, và ở lần đồng bộ đầu 20 nghìn hồ sơ thì rất hay gặp.
                pass
            elif answer.get("needs_file"):
                uploaded = _upload_file(db, client, row, answer, cv_folder, log)
                if uploaded and digest:
                    uploaded_hashes.add(digest)
                if not uploaded:
                    # Metadata đã lưu ở Hub, nhưng file thì chưa. Xếp lại để lần
                    # sau tải nốt, thay vì đánh dấu xong khi mới xong một nửa.
                    if db.fail_sync(row["id"], "Chưa tải được nội dung file", True):
                        result["retry"] += 1
                    else:
                        result["failed"] += 1
                    continue
                result["uploaded"] += 1
            db.finish_sync(row["id"], answer.get("id") or answer.get("hub_id") or "")
            result["synced"] += 1
        elif status in ("retry", "conflict"):
            if db.fail_sync(row["id"], str(answer.get("detail") or status), True):
                result["retry"] += 1
            else:
                result["failed"] += 1
        else:
            db.fail_sync(row["id"], str(answer.get("detail") or f"Hub trả về '{status}'"), False)
            result["failed"] += 1

    return result


def _upload_file(db, client, row, answer, cv_folder, log):
    """Pha hai: tải nội dung file CV lên. Trả True nếu xong.

    Đọc file từ đĩa tại thời điểm gửi chứ không giữ nội dung trong hàng đợi —
    cùng lý do với việc dựng lại payload: outbox chỉ giữ con trỏ, không giữ dữ liệu.
    """
    parts = str(row["entity_key"]).split("|")
    if len(parts) != 3:
        return False
    source, account, cv_id = parts

    found = db._read(
        "SELECT filename FROM candidate_documents WHERE source=? AND account=? AND cv_id=?",
        (source, account, cv_id), "đọc tên file tài liệu").fetchone()
    path = _document_path(cv_folder, found["filename"] if found else "")
    if not path:
        log(f"Không thấy file CV để tải lên: {row['entity_key']}")
        return False

    expected = str(answer.get("sha256") or "")
    try:
        with open(path, "rb") as handle:
            data = handle.read()

        if len(data) > MAX_UPLOAD_BYTES:
            # Hub từ chối file lớn hơn giới hạn của nó bằng 400, và 400 quay
            # vòng đủ 8 lần rồi mới thành `failed` — hai tiếng thử lại một việc
            # chắc chắn hỏng. Dừng ngay ở đây, kèm lý do đọc được.
            log(f"File CV quá lớn để tải lên ({len(data)} byte): {row['entity_key']}")
            db.fail_sync(row["id"],
                         f"File {len(data)} byte, vượt giới hạn {MAX_UPLOAD_BYTES}.",
                         False)
            return False

        # Băm lại NGAY TRƯỚC khi gửi. `file_hash` được ghi lúc bóc tách; nếu file
        # bị thay dưới cùng tên mà chưa bóc tách lại thì mã băm đã cũ, Hub tự
        # băm lại và từ chối — lại đúng 8 lần thử vô ích rồi thất bại vĩnh viễn.
        actual = hashlib.sha256(data).hexdigest()
        if expected and actual != expected:
            log(f"Nội dung file đã đổi so với lúc bóc tách: {row['entity_key']}")
            db.fail_sync(row["id"],
                         "Mã băm không khớp — hãy bóc tách lại file này.", False)
            return False

        client.upload_document(expected or actual, row["entity_key"], data,
                               filename=os.path.basename(path))
        return True
    except HubError as exc:
        log(f"Tải file CV thất bại ({row['entity_key']}): {exc}")
        return False
    except OSError as exc:
        log(f"Không đọc được file CV ({path}): {exc}")
        return False


def drain(db, client, edge_id="", batch_size=50, max_batches=20, log=print,
          cv_folder="", should_continue=None):
    """Gửi liên tiếp cho tới khi hết việc, hết lô cho phép, hoặc gặp lỗi cả lô.

    max_batches chặn trên để một lượt đồng bộ không chiếm máy vô hạn khi hàng
    đợi có hàng chục nghìn bản ghi.

    `should_continue` (nếu có) được hỏi giữa các lô: trả False thì dừng gọn ngay
    sau lô hiện tại - dùng khi tải CV hoặc parsing vừa khởi động và cần nhường máy.
    """
    totals = {"claimed": 0, "synced": 0, "retry": 0, "failed": 0, "skipped": 0,
              "uploaded": 0, "batches": 0, "error": ""}
    for _ in range(max_batches):
        if should_continue is not None and not should_continue():
            break
        outcome = push_once(db, client, edge_id, batch_size, log, cv_folder=cv_folder)
        totals["batches"] += 1
        for key in ("claimed", "synced", "retry", "failed", "skipped", "uploaded"):
            totals[key] += outcome[key]
        if outcome["error"]:
            totals["error"] = outcome["error"]
            break
        if outcome["claimed"] == 0:
            break
    return totals


def _rebuild_payload(db, row, edge_id):
    """Dựng lại payload từ CSDL tại thời điểm gửi.

    Cố ý không lưu payload trong outbox: dữ liệu ứng viên có thể được làm giàu
    sau khi xếp hàng (parsing CV, tự điền liên hệ), và bản mới nhất luôn là bản
    đáng gửi hơn. Outbox chỉ giữ con trỏ và hash, không giữ dữ liệu.
    """
    parts = str(row["entity_key"]).split("|")
    if len(parts) != 3:
        return None
    source, account, cv_id = parts

    if row["entity_type"] == ENTITY_DOCUMENT:
        return _rebuild_document_payload(db, source, account, cv_id, edge_id)
    if row["entity_type"] != ENTITY_SOURCE_RECORD:
        return None

    found = db._read(
        "SELECT * FROM candidates WHERE source=? AND account=? AND cv_id=?",
        (source, account, cv_id), "đọc ứng viên để đồng bộ").fetchone()
    if not found:
        return None
    record = dict(found)
    return candidate_payload(record, edge_id, extensions=db.get_extensions(
        source, account, cv_id))


def _rebuild_document_payload(db, source, account, cv_id, edge_id):
    """Payload tài liệu, dựng lại từ CSDL tại thời điểm gửi.

    Lấy cả `applied_ts` của lượt ứng tuyển làm `observed_at`: đó là thời điểm
    phiên bản CV này thực sự xuất hiện, và là thứ Hub dùng để xếp thứ tự phiên
    bản. Dùng thời điểm đồng bộ thay cho nó sẽ khiến một CV cũ tải về muộn nhảy
    lên đầu danh sách phiên bản.
    """
    found = db._read(
        """SELECT d.filename, d.file_hash, d.file_size, d.file_format,
                  d.parse_status, d.quality_score, d.text_length, d.full_text,
                  c.applied_ts
             FROM candidate_documents d
             LEFT JOIN candidates c
               ON c.source=d.source AND c.account=d.account AND c.cv_id=d.cv_id
            WHERE d.source=? AND d.account=? AND d.cv_id=?""",
        (source, account, cv_id), "đọc tài liệu để đồng bộ").fetchone()
    if not found or not found["file_hash"]:
        return None

    record = dict(found)
    record.update({"source": source, "account": account, "cv_id": cv_id,
                   "sha256": record.pop("file_hash", ""),
                   "observed_at": record.pop("applied_ts", "") or ""})
    return document_payload(record, edge_id)
