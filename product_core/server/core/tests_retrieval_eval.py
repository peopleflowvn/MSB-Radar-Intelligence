# -*- coding: utf-8 -*-
"""Phép đo truy hồi bằng nhãn người duyệt (`core/answer/evaluation.py`).

Thứ phải ghim ở đây không phải công thức — công thức ai cũng viết đúng. Mà là
những cách một con số đo được có thể TRÔNG đúng trong khi sai: câu chưa nhãn bị
tính như 0, pool thiếu mà vẫn được chấm, người duyệt nhìn thấy thứ hạng của
chính hệ thống đang bị đo, kho đổi mà vẫn so hai lần chạy.
"""
import csv
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from core.answer import evaluation


def _adapter(results_by_mode, corpus="v1"):
    def run(query, mode, user, pool):
        rows = results_by_mode[mode]
        if isinstance(rows, Exception):
            raise rows
        return [(pid, f"Người {pid}", [f"bằng chứng {pid}"]) for pid in rows][:pool]
    return evaluation.Adapter("rb", run, lambda: corpus)


class ScoreTest(SimpleTestCase):
    def test_cong_thuc_tren_vi_du_tay(self):
        # Kỳ vọng {1, 2}; top-3 = [9, 1, 3] → recall 0.5, precision 1/3, RR 1/2.
        out = evaluation.score([({"1", "2"}, ["9", "1", "3"])], k=3)
        self.assertEqual(out["recall@3"], 0.5)
        self.assertEqual(out["precision@3"], round(1 / 3, 6))
        self.assertEqual(out["mrr"], 0.5)
        self.assertEqual(out["retrieval_cases"], 1)

    def test_cau_khong_co_dap_an_dung_cham_rieng(self):
        out = evaluation.score([(set(), []), (set(), ["5"])], k=3)
        self.assertEqual(out["no_result_cases"], 2)
        self.assertEqual(out["no_result_accuracy"], 0.5)
        self.assertIsNone(out["recall@3"])


class PoolTest(SimpleTestCase):
    CASES = [{"id": "c1", "query": "vay mua nhà"}]

    def test_hop_nhieu_che_do(self):
        """Chỉ lấy top của đúng phiên bản đang đo thì người nó bỏ sót không ai thấy."""
        adapter = _adapter({"literal": [1, 2], "planned": [2, 3]})
        rows = evaluation.build_pool(adapter, self.CASES, modes=("literal", "planned"))
        self.assertEqual({r["person_id"] for r in rows}, {"1", "2", "3"})

    def test_thu_tu_bi_xao_khong_lo_thu_hang_cua_he_thong(self):
        ranked = list(range(1, 21))
        rows = evaluation.build_pool(_adapter({"literal": ranked}), self.CASES,
                                     modes=("literal",), depth=20, seed=7)
        order = [int(r["person_id"]) for r in rows]
        self.assertEqual(sorted(order), ranked)
        self.assertNotEqual(order, ranked)
        again = evaluation.build_pool(_adapter({"literal": ranked}), self.CASES,
                                      modes=("literal",), depth=20, seed=7)
        self.assertEqual(order, [int(r["person_id"]) for r in again])   # tất định theo seed

    def test_nhan_khong_nhin_thay_diem(self):
        rows = evaluation.build_pool(_adapter({"literal": [1]}), self.CASES, modes=("literal",))
        self.assertEqual(set(rows[0]), set(evaluation.WORKSHEET_FIELDS))


class LabelsTest(SimpleTestCase):
    def _worksheet(self, rows):
        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                             encoding="utf-8-sig", newline="")
        writer = csv.DictWriter(handle, fieldnames=evaluation.WORKSHEET_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in evaluation.WORKSHEET_FIELDS})
        handle.close()
        return handle.name

    def test_cau_con_dong_chua_dien_KHONG_duoc_dung(self):
        path = self._worksheet([
            {"case_id": "a", "person_id": "1", "relevant": "1"},
            {"case_id": "a", "person_id": "2", "relevant": "0"},
            {"case_id": "b", "person_id": "3", "relevant": "1"},
            {"case_id": "b", "person_id": "4", "relevant": ""},
        ])
        labelled, incomplete = evaluation.labels_from_worksheet(path)
        self.assertEqual(labelled, {"a": {"1"}})
        self.assertEqual(incomplete, ["b"])

    def test_tat_ca_0_la_cau_khong_co_dap_an_dung_chu_khong_phai_chua_nhan(self):
        path = self._worksheet([{"case_id": "c", "person_id": "5", "relevant": "0"}])
        labelled, _ = evaluation.labels_from_worksheet(path)
        self.assertEqual(labelled, {"c": set()})

    def test_pool_loi_luc_xuat_thi_khong_cham_du_da_dien_du(self):
        """Người đúng mà cấu hình bị lỗi tìm ra chưa từng được duyệt."""
        adapter = _adapter({"literal": [1], "planned": RuntimeError("model chết")})
        rows = evaluation.build_pool(adapter, [{"id": "d", "query": "x"}],
                                     modes=("literal", "planned"))
        for row in rows:
            if row["person_id"]:
                row["relevant"] = "1"
        labelled, incomplete = evaluation.labels_from_worksheet(self._worksheet(rows))
        self.assertNotIn("d", labelled)
        self.assertEqual(incomplete, ["d"])


class ScoringHonestyTest(SimpleTestCase):
    def test_khong_co_nhan_thi_NOT_MEASURED_khong_phai_so_0(self):
        out = evaluation.run_scoring(_adapter({"literal": [1]}),
                                     [{"id": "x", "query": "q"}], k=5)
        self.assertIn("NOT MEASURED", out["metrics"])
        self.assertEqual(out["cases_not_measured"], 1)

    def test_chi_cham_cau_co_nhan(self):
        cases = [{"id": "x", "query": "q", "relevant_person_ids": ["1"]},
                 {"id": "y", "query": "q2"}]
        out = evaluation.run_scoring(_adapter({"literal": [1, 2]}), cases, k=5)
        self.assertEqual(out["cases_scored"], 1)
        self.assertEqual(out["metrics"]["recall@5"], 1.0)

    def test_kho_doi_so_voi_luc_gan_nhan_thi_canh_bao(self):
        cases = [{"id": "x", "query": "q", "relevant_person_ids": ["1"]}]
        out = evaluation.run_scoring(_adapter({"literal": [1]}, corpus="v2"), cases, k=5,
                                     label_manifest={"corpus_fingerprint": "v1", "domain": "rb"})
        self.assertTrue(any("Kho đã đổi" in w for w in out["warnings"]))


class CommandRoundTripTest(TestCase):
    """export → điền tay → import → score, trên kho Growth thật (SQLite test)."""

    def test_ba_buoc(self):
        from people.models import Person
        from rb.models import RBProfile
        from social.models import SocialPost
        from django.utils import timezone

        dung = Person.objects.create(display_name="Cần Vay Nhà", is_applicant=False)
        RBProfile.objects.create(person=dung)
        SocialPost.objects.create(person=dung, content="em cần vay mua nhà",
                                  posted_at=timezone.now(), external_id="rt-1")

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dataset = tmp / "q.jsonl"
            dataset.write_text(json.dumps({
                "id": "g1", "category": "FIND", "query": "vay mua nhà",
                "expected_path": "hybrid", "source": "test"}, ensure_ascii=False) + "\n",
                encoding="utf-8")
            call_command("retrieval_eval", "export", "--domain", "rb",
                         "--dataset", str(dataset), "--out", str(tmp / "lab"), stdout=StringIO())
            sheet = tmp / "lab" / "worksheet.csv"
            with sheet.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertIn(str(dung.pk), [r["person_id"] for r in rows])
            for row in rows:                     # "người duyệt" điền
                row["relevant"] = "1" if row["person_id"] == str(dung.pk) else "0"
            with sheet.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=evaluation.WORKSHEET_FIELDS)
                writer.writeheader()
                writer.writerows(rows)

            gold = tmp / "gold.jsonl"
            call_command("retrieval_eval", "import", "--domain", "rb", "--dataset", str(dataset),
                         "--worksheet", str(sheet), "--out", str(gold), stdout=StringIO())
            out = StringIO()
            call_command("retrieval_eval", "score", "--domain", "rb", "--dataset", str(gold),
                         "--manifest", str(tmp / "lab" / "manifest.json"),
                         "--k", "5", stdout=out)
            summary = json.loads(out.getvalue())
        self.assertEqual(summary["cases_scored"], 1)
        self.assertEqual(summary["metrics"]["recall@5"], 1.0)
        self.assertEqual(summary["warnings"], [])

    def test_adapter_talent_chay_duoc_che_do_literal(self):
        from core.management.commands.retrieval_eval import adapter_for
        from people.models import Document, Person
        from talent import vector_index
        person = Person.objects.create(display_name="Ứng Viên Đo")
        Document.objects.create(person=person, sha256="eval-1", parse_status="done",
                                parsed_text="Chuyên viên phân tích dữ liệu SQL Python. " * 20)
        vector_index.index_person(person.pk, with_embeddings=False)
        rows = adapter_for("talent").retrieve("phân tích dữ liệu", "literal", None, 16)
        self.assertIn(person.pk, [pid for pid, _n, _s in rows])

