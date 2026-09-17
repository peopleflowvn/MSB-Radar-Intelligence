# -*- coding: utf-8 -*-
"""Đo chất lượng TRUY HỒI (②) của Talent và Growth trên kho thật, bằng nhãn người duyệt.

## Vì sao cần file này

`docs/EVALUATION.md` ghi Recall@K / Precision@K / MRR của cả hai Radar là
`NOT MEASURED`: bộ câu hỏi có sẵn nhưng không câu nào có đáp án đã duyệt. Máy
không tự lấp được chỗ đó — dùng model chấm kết quả của chính hệ thống là đo vòng
tròn, và một con số như vậy tệ hơn không có số vì nó trông như đã đo.

Nên file này làm phần MÁY làm được, và chỉ phần đó:

    pool     gom ứng viên từ NHIỀU cấu hình truy hồi (pooling kiểu TREC) và XÁO
             thứ tự trước khi đưa người duyệt — người duyệt không được thấy hệ
             thống đã xếp ai lên đầu, nếu không nhãn sẽ nghiêng theo chính thứ
             đang được đo
    labels   đọc phiếu đã điền → bộ dữ liệu vàng, ghi kèm vân tay kho lúc gán nhãn
    score    chỉ chấm câu CÓ nhãn; câu chưa nhãn đếm riêng, không bao giờ tính là
             0 hay 1; kho đã đổi so với lúc gán nhãn thì cảnh báo

## Hai chế độ lập kế hoạch

`literal`  truy vấn = nguyên văn câu hỏi, không gọi LLM. Đo riêng ②, lặp lại
           được giữa hai lần chạy — dùng để so hai phiên bản truy hồi.
`planned`  chạy ① thật rồi ②. Đo đúng thứ người dùng nhận, nhưng dao động theo
           model — dùng để kiểm trước khi phát hành.

## Định dạng

Dòng bộ dữ liệu giữ đúng hợp đồng `radar_intelligence/evaluation/dataset.py`
(`id, category, query, expected_path, source`, tuỳ chọn `relevant_person_ids`
dạng chuỗi), nên cùng một file đọc được ở cả hai phía. Thông tin riêng của một
lần gán nhãn (domain, vân tay kho, ai gán, khi nào) nằm trong `manifest.json`
đi kèm, không nằm trong dòng.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

PLAN_MODES = ("literal", "planned")


# ---------------------------------------------------------------- bộ dữ liệu

def load_cases(path):
    """Đọc JSONL theo hợp đồng dataset. Trả `(cases, sha256)`."""
    raw = Path(path).read_bytes()
    cases, seen = [], set()
    for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        for key in ("id", "query"):
            if not str(row.get(key) or "").strip():
                raise ValueError(f"dòng {number}: thiếu '{key}'")
        if row["id"] in seen:
            raise ValueError(f"dòng {number}: trùng id {row['id']}")
        seen.add(row["id"])
        relevant = row.get("relevant_person_ids")
        if relevant is not None and (not isinstance(relevant, list)
                                     or any(not isinstance(x, str) for x in relevant)):
            raise ValueError(f"dòng {number}: relevant_person_ids phải là mảng chuỗi")
        cases.append(row)
    return cases, hashlib.sha256(raw).hexdigest()


# -------------------------------------------------------------------- truy hồi

@dataclass
class Adapter:
    """Nối một domain vào phép đo mà không để file này biết nghiệp vụ.

    Các adapter cụ thể nằm ở `core/management/commands/retrieval_eval.py` —
    `core/answer/` không import `talent` hay `rb` (xem `core/answer/__init__.py`).
    """

    domain: str
    retrieve: object          # (query, mode, user, pool) -> [(person_id, name, [snippet])]
    corpus_fingerprint: object


# ---------------------------------------------------------------- pool → phiếu

def build_pool(adapter, cases, *, depth=20, modes=PLAN_MODES, user=None, seed=42):
    """Mỗi câu: HỢP các ứng viên top-`depth` của mọi chế độ, đã XÁO thứ tự.

    Hợp từ nhiều cấu hình là cách pooling giảm thiên vị: nếu chỉ lấy top của
    đúng phiên bản đang đo, người đúng mà phiên bản ấy bỏ sót không bao giờ được
    ai nhìn thấy, và recall đo được cao hơn thực tế.
    """
    rng = random.Random(seed)
    rows = []
    for case in cases:
        seen = {}
        for mode in modes:
            try:
                results = adapter.retrieve(case["query"], mode, user, depth)
            except Exception as exc:               # noqa: BLE001
                results = []
                seen.setdefault("__errors__", []).append(f"{mode}: {exc}")
            for person_id, name, snippets in results[:depth]:
                seen.setdefault(person_id, (name, snippets))
        errors = seen.pop("__errors__", [])
        items = list(seen.items())
        rng.shuffle(items)
        for person_id, (name, snippets) in items:
            rows.append({"case_id": case["id"], "query": case["query"],
                         "person_id": str(person_id), "name": name,
                         "evidence": " | ".join(s[:240] for s in snippets),
                         "relevant": ""})
        if errors:
            rows.append({"case_id": case["id"], "query": case["query"], "person_id": "",
                         "name": "", "evidence": "LỖI TRUY HỒI: " + "; ".join(errors),
                         "relevant": ""})
    return rows


WORKSHEET_FIELDS = ("case_id", "query", "person_id", "name", "evidence", "relevant")


def write_worksheet(rows, out_dir, *, domain, dataset_sha, corpus, depth, modes, seed):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "worksheet.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WORKSHEET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "domain": domain, "dataset_sha256": dataset_sha, "corpus_fingerprint": corpus,
        "pool_depth": depth, "plan_modes": list(modes), "seed": seed,
        "exported_at": datetime.now(dt_timezone.utc).isoformat(),
        "instructions": (
            "Điền cột 'relevant' cho MỌI dòng: 1 = người này đúng là câu trả lời "
            "cho câu hỏi, 0 = không. Để trống = chưa duyệt (câu có dòng trống sẽ "
            "KHÔNG được chấm). Thứ tự dòng đã bị xáo có chủ đích — đừng suy ra "
            "độ liên quan từ vị trí. Câu mà không ai trong pool đúng: điền 0 hết, "
            "câu đó được chấm như câu 'không có kết quả đúng'."),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    return out


# --------------------------------------------------------- phiếu → dữ liệu vàng

def labels_from_worksheet(path):
    """`{case_id: set(person_id)}` cho câu đã duyệt HẾT; và danh sách câu còn dở.

    Một câu có dù chỉ một dòng chưa điền thì KHÔNG được dùng: nhãn thiếu làm
    recall sai theo hướng không đoán trước được, nên thà không chấm câu đó.
    """
    labelled, incomplete = {}, set()
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            case_id = (row.get("case_id") or "").strip()
            person_id = (row.get("person_id") or "").strip()
            if case_id and not person_id and str(row.get("evidence") or "").startswith("LỖI TRUY HỒI"):
                # Pool của câu này thiếu một cấu hình truy hồi lúc xuất phiếu: người
                # đúng mà cấu hình đó tìm ra chưa từng được duyệt, nên nhãn "đủ" của
                # câu này vẫn là nhãn thiếu. Không chấm.
                incomplete.add(case_id)
                continue
            if not case_id or not person_id:
                continue
            value = (row.get("relevant") or "").strip().lower()
            if value in ("1", "yes", "y", "co", "có", "x", "true"):
                labelled.setdefault(case_id, set()).add(person_id)
            elif value in ("0", "no", "n", "khong", "không", "false"):
                labelled.setdefault(case_id, set())
            else:
                incomplete.add(case_id)
    for case_id in incomplete:
        labelled.pop(case_id, None)
    return labelled, sorted(incomplete)


def apply_labels(cases, labelled):
    """Gắn `relevant_person_ids` vào các câu đã duyệt đủ. Không đụng câu còn lại."""
    out = []
    for case in cases:
        row = dict(case)
        if case["id"] in labelled:
            row["relevant_person_ids"] = sorted(labelled[case["id"]], key=_id_sort)
        out.append(row)
    return out


def _id_sort(value):
    return (0, int(value)) if str(value).isdigit() else (1, str(value))


# --------------------------------------------------------------------- chấm điểm

def score(expected_and_actual, k):
    """Recall@K, Precision@K, MRR, nDCG@K — cùng định nghĩa với
    `radar_intelligence/evaluation/metrics.py`, cộng nDCG vì thứ tự đầu danh sách
    là thứ RM/nhà tuyển dụng thật sự đọc."""
    if k <= 0:
        raise ValueError("k phải dương")
    recalls, precisions, rr, ndcgs, no_result = [], [], [], [], []
    for expected, actual in expected_and_actual:
        top = [str(x) for x in list(actual)[:k]]
        if not expected:
            no_result.append(not top)
            continue
        hits = [pid in expected for pid in top]
        recalls.append(sum(hits) / len(expected))
        precisions.append(sum(hits) / len(top) if top else 0.0)
        first = next((i for i, hit in enumerate(hits, start=1) if hit), None)
        rr.append(0.0 if first is None else 1.0 / first)
        dcg = sum(1.0 / math.log2(i + 1) for i, hit in enumerate(hits, start=1) if hit)
        ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(expected), k) + 1))
        ndcgs.append(dcg / ideal if ideal else 0.0)

    def mean(values):
        return round(sum(values) / len(values), 6) if values else None

    return {"k": k, "retrieval_cases": len(recalls), "no_result_cases": len(no_result),
            f"recall@{k}": mean(recalls), f"precision@{k}": mean(precisions),
            "mrr": mean(rr), f"ndcg@{k}": mean(ndcgs),
            "no_result_accuracy": mean([1.0 if x else 0.0 for x in no_result])}


def run_scoring(adapter, cases, *, k=10, mode="literal", user=None, label_manifest=None):
    scored = [c for c in cases if c.get("relevant_person_ids") is not None]
    pairs, per_case = [], []
    for case in scored:
        results = adapter.retrieve(case["query"], mode, user, max(k, 16))
        ranked = [str(pid) for pid, _name, _snips in results]
        expected = set(case["relevant_person_ids"])
        pairs.append((expected, ranked))
        per_case.append({"id": case["id"], "expected": sorted(expected, key=_id_sort),
                         "top": ranked[:k],
                         "missed": sorted(expected - set(ranked[:k]), key=_id_sort)})
    corpus = adapter.corpus_fingerprint()
    warnings = []
    if label_manifest and label_manifest.get("corpus_fingerprint") not in ("", None, corpus):
        warnings.append(
            "Kho đã đổi so với lúc gán nhãn: người mới vào kho chưa từng được duyệt, "
            "nên recall có thể THẤP hơn thực tế và precision có thể sai. Xuất phiếu "
            "và gán nhãn lại trước khi so sánh hai lần chạy.")
    if label_manifest and label_manifest.get("domain") not in (None, adapter.domain):
        warnings.append(f"Nhãn được gán cho domain '{label_manifest.get('domain')}', "
                        f"đang chấm '{adapter.domain}'.")
    return {
        "domain": adapter.domain, "plan_mode": mode, "corpus_fingerprint": corpus,
        "cases_total": len(cases), "cases_scored": len(scored),
        "cases_not_measured": len(cases) - len(scored),
        "metrics": score(pairs, k) if pairs else "NOT MEASURED — không có câu nào có nhãn",
        "warnings": warnings, "per_case": per_case,
        "run_at": datetime.now(dt_timezone.utc).isoformat(),
    }
