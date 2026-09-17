# -*- coding: utf-8 -*-
"""Prospect Agent — hợp đồng Runtime và hai hành động.

Ba điều bài này canh kỹ nhất:

1. **Hợp đồng Runtime.** Sai cổng hay thiếu `/health` thì container không bao
   giờ lên `ACTIVE`, và lỗi chỉ lộ ra sau khi đã build + push xong.
2. **Không có khoá LLM vẫn chạy.** Một demo sập vì mạng chập là demo hỏng.
3. **LLM không được bịa sản phẩm.** Gợi ý một sản phẩm MSB không bán là lỗi tệ
   hơn nhiều so với gợi ý thiếu.
"""
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as agent_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(agent_app.app)


@pytest.fixture
def no_llm(monkeypatch):
    """Chưa cấu hình khoá — nhánh tất định phải gánh toàn bộ."""
    monkeypatch.setattr(agent_app, "LLM_API_KEY", "")
    return agent_app


# ------------------------------------------------------ hợp đồng Runtime

def test_health_tra_200(client):
    """Thiếu cái này thì container không bao giờ lên ACTIVE."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_health_KHONG_goi_ra_ngoai(client, monkeypatch):
    """Healthcheck gọi LLM sẽ đánh dấu container hỏng mỗi khi nhà cung cấp chập,
    trong khi agent vẫn phục vụ được bằng nhánh dự phòng."""
    def no_network(*_args, **_kwargs):
        raise AssertionError("healthcheck không được gọi mạng")

    monkeypatch.setattr(agent_app.httpx, "post", no_network)
    assert client.get("/health").status_code == 200


def test_dockerfile_bind_dung_cong_8080():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "Dockerfile"), encoding="utf-8") as handle:
        content = handle.read()
    assert "8080" in content
    assert "--port" in content and "8080" in content


def test_hanh_dong_la_bi_tu_choi_ro_rang(client):
    body = client.post("/invocations", json={"action": "xoa-du-lieu"}).json()
    assert "error" in body
    assert "parse_query" in body["supported"]
    assert "chat" in body["supported"]


# ------------------------------------------------------------------- chat

def test_chat_uy_quyen_len_greennode(client, monkeypatch):
    monkeypatch.setattr(agent_app, "LLM_API_KEY", "khoa-gia")
    monkeypatch.setattr(agent_app, "_complete_messages",
                        lambda msgs, **kw: ("Xin chào anh/chị.", {"prompt_tokens": 5}))
    body = client.post("/invocations", json={
        "action": "chat",
        "messages": [{"role": "user", "content": "chào"}],
        "max_tokens": 100}).json()
    assert body["mode"] == "llm"
    assert body["text"] == "Xin chào anh/chị."
    assert body["model"] == agent_app.LLM_MODEL
    assert body["usage"]["prompt_tokens"] == 5


def test_chat_khong_co_khoa_thi_bao_loi(no_llm, client):
    body = client.post("/invocations", json={
        "action": "chat", "messages": [{"role": "user", "content": "x"}]}).json()
    assert "error" in body


def test_chat_messages_rong_thi_bao_loi(client, monkeypatch):
    monkeypatch.setattr(agent_app, "LLM_API_KEY", "khoa-gia")
    body = client.post("/invocations", json={"action": "chat", "messages": []}).json()
    assert "error" in body


def test_chat_LLM_hong_thi_tra_error_khong_nem(client, monkeypatch):
    monkeypatch.setattr(agent_app, "LLM_API_KEY", "khoa-gia")

    def sap(*_a, **_k):
        raise RuntimeError("greennode sập")

    monkeypatch.setattr(agent_app, "_complete_messages", sap)
    body = client.post("/invocations", json={
        "action": "chat", "messages": [{"role": "user", "content": "x"}]}).json()
    assert "error" in body and "sập" in body["error"]


# ------------------------------------------------------------ parse_query

def test_boc_tach_khong_can_LLM(no_llm, client):
    body = client.post("/invocations", json={
        "action": "parse_query",
        "query": "Tìm 20 người quản lý ở Hà Nội có contact, quan tâm thẻ tín dụng",
    }).json()

    assert body["mode"] == "fallback"
    criteria = body["criteria"]
    assert criteria["location"] == "Hà Nội"
    assert criteria["seniority"] == "manager"
    assert "credit_card" in criteria["products"]
    assert criteria["require_contact"] is True
    assert criteria["limit"] == 20


def test_khop_dia_diem_khong_dau(no_llm, client):
    body = client.post("/invocations", json={
        "action": "parse_query", "query": "tim khach o ha noi"}).json()
    assert body["criteria"]["location"] == "Hà Nội"


def test_dia_danh_khac_cach_viet_ra_cung_dang_chuan(no_llm, client):
    """"Sài Gòn" và "Hồ Chí Minh" là cùng một nơi — Hub lọc theo đúng một giá
    trị, không phải hai chuỗi khác nhau."""
    for query in ("khách ở sài gòn", "khách ở tp hcm", "khách ở hồ chí minh"):
        body = client.post("/invocations", json={
            "action": "parse_query", "query": query}).json()
        assert body["criteria"]["location"] == "Hồ Chí Minh", query


def test_nhan_ra_nhu_cau_mua_nha(no_llm, client):
    body = client.post("/invocations", json={
        "action": "parse_query", "query": "Ai đang cần vay mua nhà"}).json()
    assert "mortgage" in body["criteria"]["products"]


def test_doc_duoc_khoang_thoi_gian(no_llm, client):
    body = client.post("/invocations", json={
        "action": "parse_query",
        "query": "có tín hiệu trong 3 tháng gần đây"}).json()
    assert body["criteria"]["signal_recency_days"] == 90


def test_LLM_KHONG_duoc_bia_san_pham(client, monkeypatch):
    """Chốt chặn cuối: gợi ý sản phẩm ngân hàng không bán là lỗi tệ hơn cả."""
    monkeypatch.setattr(agent_app, "LLM_API_KEY", "khoa-gia")
    monkeypatch.setattr(agent_app, "_complete", lambda *_: json.dumps({
        "products": ["crypto_wallet", "mortgage"], "seniority": "hoang-de",
        "location": "Hà Nội", "segment": "sieu-vip", "limit": 5,
    }))
    criteria = client.post("/invocations", json={
        "action": "parse_query", "query": "tìm khách"}).json()["criteria"]

    assert criteria["products"] == ["mortgage"]
    assert criteria["seniority"] == ""      # "hoang-de" bị loại
    assert criteria["segment"] == ""        # "sieu-vip" bị loại
    assert criteria["limit"] == 5


def test_cau_hoi_tiep_giu_lai_tieu_chi_truoc_do(client, monkeypatch):
    """Hỏi tiếp chỉ nói THAY ĐỔI gì — tiêu chí trước không được biến mất."""
    monkeypatch.setattr(agent_app, "LLM_API_KEY", "khoa-gia")
    # Mô hình chỉ trả về location mới, không nhắc lại products/limit của lượt trước.
    monkeypatch.setattr(agent_app, "_complete", lambda *_: json.dumps({"location": "Đà Nẵng"}))

    body = client.post("/invocations", json={
        "action": "parse_query",
        "query": "vậy còn ở Đà Nẵng thì sao",
        "previous_criteria": {"products": ["credit_card"], "limit": 15,
                              "location": "Hà Nội", "seniority": "", "segment": "",
                              "require_contact": True, "signal_recency_days": 0},
    }).json()

    assert body["criteria"]["location"] == "Đà Nẵng"
    assert body["criteria"]["products"] == ["credit_card"]
    assert body["criteria"]["limit"] == 15
    assert body["criteria"]["require_contact"] is True


def test_LLM_hong_thi_lui_ve_do_tu_khoa(client, monkeypatch):
    monkeypatch.setattr(agent_app, "LLM_API_KEY", "khoa-gia")

    def sap(*_args, **_kwargs):
        raise RuntimeError("nhà cung cấp sập")

    monkeypatch.setattr(agent_app, "_complete", sap)
    body = client.post("/invocations", json={
        "action": "parse_query", "query": "quản lý ở Đà Nẵng"}).json()
    assert body["mode"] == "fallback"
    assert body["criteria"]["seniority"] == "manager"


def test_LLM_tra_ve_rac_thi_lui_ve_do_tu_khoa(client, monkeypatch):
    monkeypatch.setattr(agent_app, "LLM_API_KEY", "khoa-gia")
    monkeypatch.setattr(agent_app, "_complete", lambda *_: "xin chào bạn nhé")
    body = client.post("/invocations", json={
        "action": "parse_query", "query": "vay mua xe"}).json()
    assert body["mode"] == "fallback"
    assert "auto_loan" in body["criteria"]["products"]


def test_boc_JSON_trong_khoi_markdown(client, monkeypatch):
    """Mô hình hay bọc JSON trong ```json kể cả khi đã bảo đừng."""
    monkeypatch.setattr(agent_app, "LLM_API_KEY", "khoa-gia")
    monkeypatch.setattr(agent_app, "_complete",
                        lambda *_: '```json\n{"products": ["fx"]}\n```')
    body = client.post("/invocations", json={
        "action": "parse_query", "query": "sắp đi nước ngoài"}).json()
    assert body["mode"] == "llm"
    assert body["criteria"]["products"] == ["fx"]


def test_gioi_han_so_luong_khong_vuot_tran(client, monkeypatch):
    monkeypatch.setattr(agent_app, "LLM_API_KEY", "khoa-gia")
    monkeypatch.setattr(agent_app, "_complete",
                        lambda *_: json.dumps({"limit": 999999}))
    body = client.post("/invocations", json={
        "action": "parse_query", "query": "tìm khách"}).json()
    assert body["criteria"]["limit"] <= 500


# ---------------------------------------------------------------- explain

def _row(row_id=1):
    return {"id": row_id, "person_name": "Nguyễn Văn An",
            "product_label": "Vay mua nhà", "need_summary": "Đang tính mua nhà",
            "why": ["Khách nhắc tới: mua nhà", "Tín hiệu trong 7 ngày qua"]}


def test_giai_thich_khong_can_LLM(no_llm, client):
    body = client.post("/invocations", json={
        "action": "explain", "query": "", "results": [_row()]}).json()
    assert body["mode"] == "fallback"
    assert len(body["explanations"]) == 1
    assert "mua nhà" in body["explanations"][0]["text"]


def test_moi_dong_LUON_co_loi_giai_thich(client, monkeypatch):
    """LLM chỉ trả lời một phần thì phần còn lại dùng bản tất định — mục
    "vì sao bây giờ" trên thẻ không bao giờ được để trống."""
    monkeypatch.setattr(agent_app, "LLM_API_KEY", "khoa-gia")
    monkeypatch.setattr(agent_app, "_complete", lambda *_: json.dumps({
        "explanations": [{"id": 1, "text": "Khách vừa hỏi thủ tục vay mua nhà tuần trước."}]
    }))
    body = client.post("/invocations", json={
        "action": "explain", "results": [_row(1), _row(2)]}).json()
    assert len(body["explanations"]) == 2
    assert all(item["text"] for item in body["explanations"])


def test_cau_qua_ngan_bi_thay_bang_ban_tat_dinh(client, monkeypatch):
    """Câu cụt là câu bị cắt giữa chừng — không hiển thị mẩu chữ dở dang."""
    monkeypatch.setattr(agent_app, "LLM_API_KEY", "khoa-gia")
    monkeypatch.setattr(agent_app, "_complete", lambda *_: json.dumps({
        "explanations": [{"id": 1, "text": "Nên gọi"}]}))
    body = client.post("/invocations", json={
        "action": "explain", "results": [_row(1)]}).json()
    assert body["explanations"][0]["text"] != "Nên gọi"


def test_khong_co_ket_qua_thi_khong_goi_LLM(client, monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("không được gọi LLM khi danh sách rỗng")

    monkeypatch.setattr(agent_app, "_complete", no_network)
    body = client.post("/invocations", json={
        "action": "explain", "results": []}).json()
    assert body["mode"] == "empty"


# ------------------------------------------------------- đồng bộ từ vựng

def test_danh_muc_san_pham_KHOP_voi_Hub():
    """Agent giữ bản sao danh mục sản phẩm; bài này canh nó không lệch khỏi Hub.

    Lệch nhau nghĩa là agent bóc tách ra một mã sản phẩm mà Hub không hiểu, và
    kết quả trả về danh sách rỗng mà không ai biết vì sao.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    models = os.path.join(os.path.dirname(here), "server", "rb", "models.py")
    if not os.path.exists(models):
        pytest.skip("Không tìm thấy server/rb/models.py")

    with open(models, encoding="utf-8") as handle:
        content = handle.read()

    import re
    hub_products = set(re.findall(r'^PRODUCT_[A-Z_]+ = "([a-z_]+)"', content,
                                  re.MULTILINE))
    assert hub_products, "Không đọc được danh mục sản phẩm từ Hub"
    assert set(agent_app.PRODUCTS) == hub_products, (
        "Danh mục sản phẩm của agent lệch khỏi Hub: "
        f"thừa={set(agent_app.PRODUCTS) - hub_products} "
        f"thiếu={hub_products - set(agent_app.PRODUCTS)}")
