"""Human review batches for answer correctness and evidence entailment.

This module never asks an LLM to grade another LLM. Two independent reviewers
label each item; disagreements remain unmeasured until an adjudicator resolves
them. Production text stays in caller-selected ignored artifacts, not the repo.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

SCHEMA_VERSION = 2
LABELS = {
    "claim": {"SUPPORTED", "CONTRADICTED", "INSUFFICIENT"},
    "candidate": {"RELEVANT", "NOT_RELEVANT", "UNCERTAIN"},
    "answer": {"ACCEPT", "REJECT"},
}
_CITE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_CLAUSE = re.compile(r"[^\n.!?]+(?:[.!?]+|$)")


def stable_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cited_numbers(text):
    return [int(part.strip()) for match in _CITE.finditer(str(text or ""))
            for part in match.group(1).split(",")]


def citation_claims(text):
    """Map each cited number to the nearby sentence shown to reviewers."""
    claims = {}
    for match in _CLAUSE.finditer(str(text or "")):
        clause = " ".join(match.group(0).split())
        for number in _cited_numbers(clause):
            claims.setdefault(number, clause)
    return claims


def citation_occurrences(text):
    """Keep every sentence/source pair, including repeated and missing sources.

    Segmentation is mechanical, not a claim truth classifier. Offsets let a human
    inspect the original answer when punctuation splits a sentence imperfectly.
    """
    occurrences = []
    for match in _CLAUSE.finditer(str(text or "")):
        clause = " ".join(match.group(0).split())
        for number in dict.fromkeys(_cited_numbers(clause)):
            occurrences.append({"source_number": number, "claim": clause,
                                "answer_start": match.start(), "answer_end": match.end()})
    return occurrences


def _blank_reviews():
    return [{"reviewer_id": "", "label": None, "notes": ""} for _ in range(2)]


def build_batch(report):
    """Create answer, candidate and cited-claim records from an eval report."""
    records = []
    for run_number, row in enumerate(report.get("rows") or [], 1):
        if row.get("error"):
            continue
        case = str(row.get("case") or row.get("n") or run_number)
        answer = str(row.get("answer") or "")
        question = str(row.get("q") or row.get("question") or "")
        sources = row.get("all_sources") or row.get("sources") or []
        if not isinstance(sources, list):
            sources = []
        by_number = {source.get("n"): source for source in sources
                     if isinstance(source, dict) and type(source.get("n")) is int}
        claims = citation_occurrences(answer)
        common = {"case": case, "run": run_number, "question": question,
                  "model": row.get("model") or report.get("model") or ""}

        answer_key = {**common, "type": "answer", "answer": answer}
        records.append({"review_id": stable_hash(answer_key)[:24], **common,
                        "record_type": "answer", "answer": answer,
                        "allowed_labels": sorted(LABELS["answer"]),
                        "reviews": _blank_reviews(), "adjudication": None})

        people = row.get("people_detail") or row.get("people") or row.get("ids") or []
        for position, person in enumerate(people, 1):
            if isinstance(person, dict):
                person_id = person.get("person_id") or person.get("id")
                name = person.get("name") or ""
            else:
                person_id, name = person, ""
            owned = [source for source in sources
                     if isinstance(source, dict) and source.get("person_id") == person_id]
            if not name and owned:
                name = owned[0].get("name") or ""
            key = {**common, "type": "candidate", "person_id": person_id,
                   "position": position}
            records.append({"review_id": stable_hash(key)[:24], **common,
                            "record_type": "candidate", "position": position,
                            "person_id": person_id, "name": name,
                            "evidence": owned, "allowed_labels": sorted(LABELS["candidate"]),
                            "reviews": _blank_reviews(), "adjudication": None})

        for occurrence, claim in enumerate(claims, 1):
            number = claim["source_number"]
            source = by_number.get(number)
            key = {**common, "type": "claim", "source_number": number,
                   "occurrence": occurrence, **claim}
            records.append({"review_id": stable_hash(key)[:24], **common,
                            "record_type": "claim", "occurrence": occurrence, **claim,
                            "source_missing": source is None,
                            "source": source, "allowed_labels": sorted(LABELS["claim"]),
                            "reviews": _blank_reviews(), "adjudication": None})

    identity = [_review_content(row) for row in records]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_sha256": stable_hash(report),
        "input_scope": report.get("scope") or report.get("measurement_scope") or "",
        "input_model": report.get("model") or "",
        "input_gold_version": report.get("gold_version"),
        "input_runtime_sha256": report.get("runtime_sha256") or {},
        "record_count": len(records),
        "record_identity_sha256": stable_hash(identity),
        "required_independent_reviewers": 2,
    }
    return manifest, records


def _review_content(record):
    return {key: value for key, value in record.items()
            if key not in ("reviews", "adjudication")}


def _final_label(record):
    kind = record.get("record_type")
    allowed = LABELS.get(kind, set())
    reviews = record.get("reviews") or []
    valid = [review for review in reviews
             if isinstance(review, dict) and review.get("reviewer_id")
             and review.get("label") in allowed]
    reviewer_ids = {review["reviewer_id"] for review in valid}
    if len(reviews) != 2 or len(valid) != 2 or len(reviewer_ids) != 2:
        return None, "incomplete"
    labels = {review["label"] for review in valid}
    if len(labels) == 1:
        return valid[0]["label"], "agreed"
    adjudication = record.get("adjudication") or {}
    if (adjudication.get("reviewer_id") not in reviewer_ids
            and adjudication.get("reviewer_id")
            and adjudication.get("label") in allowed):
        return adjudication["label"], "adjudicated"
    return None, "disputed"


def score_batch(manifest, records):
    """Score only agreed/adjudicated rows; missing truth stays null."""
    counts = {kind: {label: 0 for label in labels} for kind, labels in LABELS.items()}
    states = {"agreed": 0, "adjudicated": 0, "disputed": 0, "incomplete": 0}
    identity = [_review_content(row) for row in records]
    review_ids = [row.get("review_id") for row in records]
    integrity_ok = (manifest.get("schema_version") in (1, SCHEMA_VERSION)
                    and manifest.get("record_count") == len(records)
                    and manifest.get("record_identity_sha256") == stable_hash(identity)
                    and len(review_ids) == len(set(review_ids))
                    and all(row.get("record_type") in LABELS for row in records))
    finalized = 0
    for record in records:
        label, state = _final_label(record) if integrity_ok else (None, "incomplete")
        states[state] += 1
        if label is not None:
            counts[record["record_type"]][label] += 1
            finalized += 1

    claim_total = sum(counts["claim"].values())
    candidate_total = sum(counts["candidate"].values())
    answer_total = sum(counts["answer"].values())
    return {
        "schema_version": SCHEMA_VERSION,
        "input_schema_version": manifest.get("schema_version"),
        "claim_coverage": ("sentence_source_pairs" if manifest.get("schema_version") == 2
                           else "legacy_first_sentence_per_source"),
        "missing_source_records": sum(1 for row in records if row.get("record_type") == "claim"
                                      and row.get("source_missing")),
        "source_manifest_sha256": stable_hash(manifest),
        "record_count": len(records), "finalized": finalized, **states,
        "integrity_ok": integrity_ok,
        "complete": bool(records) and integrity_ok and finalized == len(records) and not states["disputed"],
        "independent_agreement_rate": (
            states["agreed"] / (states["agreed"] + states["adjudicated"]
                                + states["disputed"])
            if states["agreed"] + states["adjudicated"] + states["disputed"] else None),
        "counts": counts,
        "claim_hallucination_rate": (
            counts["claim"]["CONTRADICTED"] / claim_total if claim_total else None),
        "claim_unsupported_rate": (
            (counts["claim"]["CONTRADICTED"] + counts["claim"]["INSUFFICIENT"])
            / claim_total if claim_total else None),
        "acceptance_at_returned_k": (
            counts["candidate"]["RELEVANT"] / candidate_total if candidate_total else None),
        "answer_acceptance_rate": (
            counts["answer"]["ACCEPT"] / answer_total if answer_total else None),
        "measurement_scope": (
            "two independent human labels; disagreements require a third adjudicator; "
            "null means no finalized labels"),
    }
