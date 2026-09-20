# -*- coding: utf-8 -*-
"""Kiểm thử lớp nhà cung cấp LLM.

Không test nào chạm mạng: transport được tiêm vào. Điều đó cũng có nghĩa bộ test
này chạy được ngay cả khi chưa có khoá của bất kỳ nhà cung cấp nào — đúng tình
trạng hiện tại với GreenNode.
"""
from django.test import TestCase
from django.urls import reverse

from . import tasks as tasks_registry
from .models import LLMCall, ProviderConfig, TaskModelRoute
from .providers import (Completion, LLMAuthError, LLMError, LLMUnavailable,
                        OpenAICompatibleProvider, PROVIDER_DEFAULTS, build_provider)
from .router import DEFAULT_ORDER, NoProviderConfigured, Router


def fake_transport(status=200, payload=None, record=None):
    """Transport giả. `record` nhận lại từng lời gọi để kiểm tra."""
    body = payload if payload is not None else {
        "choices": [{"message": {"content": "xin chào"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    def transport(url, headers, request_body, timeout):
        if record is not None:
            record.append({"url": url, "headers": headers, "body": request_body,
                           "timeout": timeout})
        if isinstance(status, Exception):
            raise status
        return status, body

    return transport


MESSAGES = [{"role": "user", "content": "xin chào"}]


class ProviderTest(TestCase):
    def _provider(self, **kwargs):
        kwargs.setdefault("transport", fake_transport())
        return OpenAICompatibleProvider(
            name="test", base_url="https://api.test/v1", api_key="k", model="m", **kwargs)

    def test_goi_thanh_cong_tra_ve_text_va_token(self):
        result = self._provider().complete(MESSAGES)
        self.assertEqual(result.text, "xin chào")
        self.assertEqual(result.prompt_tokens, 10)
        self.assertEqual(result.completion_tokens, 5)
        self.assertEqual(result.total_tokens, 15)
        self.assertEqual(result.provider, "test")

    def test_reasoning_effort_bi_bo_qua_cho_deepseek(self):
        """deepseek-v4-* trả HTTP 400 khi thấy `reasoning_effort` — bỏ qua nó."""
        calls = []
        self._provider(transport=fake_transport(record=calls)).complete(
            MESSAGES, model="deepseek/deepseek-v4-pro", reasoning_effort="none")
        self.assertNotIn("reasoning_effort", calls[0]["body"])
        self.assertEqual(calls[0]["body"]["model"], "deepseek/deepseek-v4-pro")

    def test_reasoning_effort_van_gui_cho_model_khac(self):
        calls = []
        self._provider(transport=fake_transport(record=calls)).complete(
            MESSAGES, model="qwen/qwen3.6-flash", reasoning_effort="none")
        self.assertEqual(calls[0]["body"]["reasoning_effort"], "none")

    def test_gui_dung_duong_dan_va_khoa(self):
        calls = []
        self._provider(transport=fake_transport(record=calls)).complete(MESSAGES)
        self.assertEqual(calls[0]["url"], "https://api.test/v1/chat/completions")
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer k")
        self.assertEqual(calls[0]["body"]["model"], "m")

    def test_bo_dau_gach_cheo_thua_o_base_url(self):
        calls = []
        OpenAICompatibleProvider("t", "https://api.test/v1/", "k", "m",
                                 transport=fake_transport(record=calls)).complete(MESSAGES)
        self.assertEqual(calls[0]["url"], "https://api.test/v1/chat/completions")

    def test_ghi_de_model_theo_tung_loi_goi(self):
        calls = []
        self._provider(transport=fake_transport(record=calls)).complete(
            MESSAGES, model="model-khac")
        self.assertEqual(calls[0]["body"]["model"], "model-khac")

    def test_tham_so_tuy_chon_chi_gui_khi_co(self):
        calls = []
        self._provider(transport=fake_transport(record=calls)).complete(MESSAGES)
        self.assertNotIn("max_tokens", calls[0]["body"])
        self.assertNotIn("tools", calls[0]["body"])

        calls.clear()
        self._provider(transport=fake_transport(record=calls)).complete(
            MESSAGES, max_tokens=100, response_format={"type": "json_object"})
        self.assertEqual(calls[0]["body"]["max_tokens"], 100)
        self.assertEqual(calls[0]["body"]["response_format"], {"type": "json_object"})

    def test_chua_cau_hinh_thi_bao_loi_ro_rang(self):
        with self.assertRaises(LLMError):
            OpenAICompatibleProvider("t", "", "k", "m").complete(MESSAGES)
        with self.assertRaises(LLMError):
            OpenAICompatibleProvider("t", "https://x/v1", "", "m").complete(MESSAGES)
        with self.assertRaises(LLMError):
            OpenAICompatibleProvider("t", "https://x/v1", "k", "").complete(MESSAGES)

    # ---------- phân loại lỗi ----------

    def test_401_la_loi_xac_thuc_khong_thu_lai(self):
        provider = self._provider(transport=fake_transport(
            401, {"error": {"message": "khoá sai"}}))
        with self.assertRaises(LLMAuthError) as ctx:
            provider.complete(MESSAGES)
        self.assertFalse(ctx.exception.retryable)

    def test_429_va_5xx_dang_thu_lai(self):
        for status in (429, 500, 503):
            provider = self._provider(transport=fake_transport(status, {}))
            with self.assertRaises(LLMUnavailable) as ctx:
                provider.complete(MESSAGES)
            self.assertTrue(ctx.exception.retryable, f"HTTP {status}")

    def test_400_la_loi_cau_hinh_khong_thu_lai(self):
        """Sai tên model trả 400; thử lại chỉ tốn thời gian."""
        provider = self._provider(transport=fake_transport(
            400, {"error": {"message": "model không tồn tại"}}))
        with self.assertRaises(LLMError) as ctx:
            provider.complete(MESSAGES)
        self.assertNotIsInstance(ctx.exception, LLMUnavailable)

    def test_su_co_mang_la_tam_thoi(self):
        provider = self._provider(transport=fake_transport(ConnectionError("mất mạng")))
        with self.assertRaises(LLMUnavailable):
            provider.complete(MESSAGES)

    def test_phan_hoi_khong_co_lua_chon_nao(self):
        provider = self._provider(transport=fake_transport(200, {"choices": []}))
        with self.assertRaises(LLMUnavailable):
            provider.complete(MESSAGES)

    def test_thong_bao_loi_cua_nha_cung_cap_duoc_giu_lai(self):
        provider = self._provider(transport=fake_transport(
            400, {"error": {"message": "chi tiết hữu ích"}}))
        with self.assertRaises(LLMError) as ctx:
            provider.complete(MESSAGES)
        self.assertIn("chi tiết hữu ích", str(ctx.exception))


class BuildProviderTest(TestCase):
    def test_bon_nha_cung_cap_deu_co_mac_dinh(self):
        self.assertEqual(set(PROVIDER_DEFAULTS), {"greennode", "openai", "gemini", "deepseek"})

    def test_greennode_dung_endpoint_maas(self):
        self.assertIn("maas-llm-aiplatform-hcm.api.vngcloud.vn",
                      PROVIDER_DEFAULTS["greennode"]["base_url"])

    def test_chua_co_khoa_thi_tra_none(self):
        self.assertIsNone(build_provider("openai", env={}))

    def test_co_khoa_thi_dung_mac_dinh(self):
        provider = build_provider("deepseek", env={"MSB_AI_DEEPSEEK_API_KEY": "k"})
        self.assertEqual(provider.base_url, "https://api.deepseek.com/v1")
        self.assertEqual(provider.model, "deepseek-v4-flash")

    def test_bien_moi_truong_ghi_de_duoc_base_url_va_model(self):
        """Mã model đổi vài tháng một lần — phải đổi được mà không sửa code."""
        provider = build_provider("greennode", env={
            "MSB_AI_GREENNODE_API_KEY": "k",
            "MSB_AI_GREENNODE_MODEL": "model-tu-workshop",
            "MSB_AI_GREENNODE_BASE_URL": "https://noi-khac/v1",
        })
        self.assertEqual(provider.model, "model-tu-workshop")
        self.assertEqual(provider.base_url, "https://noi-khac/v1")

    def test_greennode_chua_co_model_thi_chua_dung_duoc(self):
        """Chưa biết mã model của GreenNode; lấy ở workshop ngày 28/08."""
        provider = build_provider("greennode", env={"MSB_AI_GREENNODE_API_KEY": "k"})
        self.assertFalse(provider.configured())

    def test_ten_nha_cung_cap_la_thi_bao_loi(self):
        with self.assertRaises(LLMError):
            build_provider("khong-ton-tai", env={})


class AgentBaseProviderTest(TestCase):
    ENV = {"MSB_AGENT_ENDPOINT": "https://agent.example", "MSB_AGENT_TIMEOUT": "70"}

    def _agent(self, transport):
        return build_provider("agentbase", env=self.ENV, transport=transport)

    def test_khong_co_endpoint_thi_tra_none(self):
        self.assertIsNone(build_provider("agentbase", env={}))

    def test_goi_action_chat_va_tra_completion(self):
        calls = []

        def transport(url, headers, body, timeout):
            calls.append({"url": url, "body": body})
            return 200, {"text": "Xin chào anh/chị.", "model": "glm-x",
                         "usage": {"prompt_tokens": 8, "completion_tokens": 3}}

        c = self._agent(transport).complete(
            MESSAGES, max_tokens=200, reasoning_effort="none")
        self.assertEqual(c.text, "Xin chào anh/chị.")
        self.assertEqual(c.provider, "agentbase")
        self.assertEqual(c.model, "glm-x")
        self.assertEqual(c.prompt_tokens, 8)
        self.assertTrue(calls[0]["url"].endswith("/invocations"))
        self.assertEqual(calls[0]["body"]["action"], "chat")
        self.assertEqual(calls[0]["body"]["messages"], MESSAGES)
        self.assertEqual(calls[0]["body"]["reasoning_effort"], "none")

    def test_payload_co_error_thi_LLMUnavailable(self):
        with self.assertRaises(LLMUnavailable):
            self._agent(fake_transport(200, {"error": "greennode sập"})).complete(MESSAGES)

    def test_5xx_thi_LLMUnavailable(self):
        with self.assertRaises(LLMUnavailable):
            self._agent(fake_transport(503, {})).complete(MESSAGES)

    def test_noi_dung_rong_thi_LLMUnavailable(self):
        with self.assertRaises(LLMUnavailable):
            self._agent(fake_transport(200, {"text": ""})).complete(MESSAGES)

    def test_mat_mang_thi_LLMUnavailable(self):
        with self.assertRaises(LLMUnavailable):
            self._agent(fake_transport(ConnectionError("mất mạng"))).complete(MESSAGES)

    def test_khong_stream(self):
        self.assertFalse(hasattr(self._agent(fake_transport()), "stream"))

    def test_router_bo_qua_khi_khong_co_endpoint(self):
        r = Router(env={"MSB_AI_GEMINI_API_KEY": "k"})
        self.assertIsNone(r.get_provider("agentbase"))

    def test_router_dung_agentbase_khi_co_endpoint(self):
        r = Router(env={**self.ENV}, transport=fake_transport(
            200, {"text": "ok", "model": "m"}))
        self.assertIn("agentbase", r.available())


class RouterTest(TestCase):
    def _router(self, env, **kwargs):
        return Router(env=env, **kwargs)

    def _khong_route_db(self, *tasks):
        """Dọn route CSDL để test được nhánh env bootstrap.

        Từ migration 0014, MỌI tác vụ đều có route trong CSDL — cố ý, để không
        còn cái nào im lặng rơi xuống model mặc định của nhà cung cấp. Mà env
        bootstrap theo thiết kế CHỈ chạy khi không có route CSDL, nên muốn kiểm
        nhánh đó thì phải dựng lại đúng điều kiện của nó. Không dọn thì test
        không sai — nó chỉ đo nhầm nhánh.
        """
        TaskModelRoute.objects.filter(task__in=tasks).delete()

    def test_greennode_dung_dau_mac_dinh(self):
        """Vừa là hạ tầng ban tổ chức, vừa là điều kiện tranh giải."""
        self.assertEqual(self._router({}).provider_order()[0], "greennode")

    def test_thu_tu_uu_tien_theo_tac_vu(self):
        """Pin ENV vẫn đứng đầu; mặc định sổ đăng ký chen vào làm lớp đỡ.

        `greennode` xuất hiện ở vị trí hai vì `talent_search` có mặc định trong
        `tasks.py`. Nó KHÔNG cướp chỗ của pin — chỉ đứng trước thứ tự chung, vì
        sổ đăng ký biết tác vụ này hợp nhà cung cấp nào, còn PROVIDER_DEFAULT
        thì không.
        """
        self._khong_route_db("talent_search")
        order = self._router({
            "MSB_AI_PROVIDER_TALENT_SEARCH": "deepseek",
            "MSB_AI_PROVIDER_DEFAULT": "openai",
            "MSB_AI_PROVIDER_FALLBACK": "gemini",
        }).provider_order("talent_search")
        self.assertEqual(order, ["deepseek", "greennode", "openai", "gemini"])

    def test_model_theo_tac_vu_uu_tien_nha_cung_cap_roi_chung(self):
        self._khong_route_db("talent_search", "assistant_conversation")
        r = self._router({
            "MSB_AI_GREENNODE_MODEL_TALENT_SEARCH": "qwen/qwen3.6-flash",
            "MSB_AI_MODEL_TALENT_EXPLAIN": "deepseek/deepseek-v4-pro",
        })
        self.assertEqual(r._model_for("greennode", "talent_search"), "qwen/qwen3.6-flash")
        self.assertEqual(r._model_for("greennode", "talent_explain"),
                         "deepseek/deepseek-v4-pro")
        self.assertEqual(r._model_for("agentbase", "talent_explain"),
                         "deepseek/deepseek-v4-pro")     # dùng chung
        # Không cấu hình gì cho `assistant_conversation` thì KHÔNG còn trả None
        # nữa. None nghĩa là "để nhà cung cấp tự chọn model mặc định" — chính
        # cái tầng đã lặng lẽ gán glm-5.2 cho 13 tác vụ, trong đó có một tác vụ
        # cần thị giác mà model ấy không có. Nay rơi vào mặc định của sổ đăng ký.
        #
        # Nhà cung cấp lấy TỪ sổ đăng ký, không viết cứng: `assistant_conversation`
        # đã đổi greennode → gemini một lần (cb59be3, benchmark 09/2026) và bản
        # viết cứng cũ đỏ từ đó mà không ai thấy. Đọc từ chính nguồn sự thật thì
        # lần đổi tuyến sau không làm test sai lần nữa.
        mac_dinh_provider, mac_dinh_model = tasks_registry.DEFAULT_ROUTE["assistant_conversation"]
        self.assertEqual(r._model_for(mac_dinh_provider, "assistant_conversation"),
                         mac_dinh_model)
        # Nhà cung cấp KHÁC với nhà cung cấp mặc định thì vẫn None — mặc định là
        # một cặp (nhà cung cấp, model), tách ra dùng chéo là gửi mã model của
        # hub này sang hub kia.
        khac = "openai" if mac_dinh_provider != "openai" else "greennode"
        self.assertIsNone(r._model_for(khac, "assistant_conversation"))
        self.assertIsNone(r._model_for("greennode", ""))

    def test_model_theo_tac_vu_duoc_gui_toi_provider(self):
        self._khong_route_db("talent_search")
        calls = []
        r = Router(env={"MSB_AI_GEMINI_API_KEY": "k",
                        "MSB_AI_PROVIDER_DEFAULT": "gemini",
                        "MSB_AI_GEMINI_MODEL_TALENT_SEARCH": "qwen/qwen3.6-flash"},
                   transport=fake_transport(record=calls))
        r.complete(MESSAGES, task="talent_search")
        self.assertEqual(calls[0]["body"]["model"], "qwen/qwen3.6-flash")

    def test_nguoi_goi_chi_dinh_model_thi_thang_pin_tac_vu(self):
        calls = []
        r = Router(env={"MSB_AI_GEMINI_API_KEY": "k",
                        "MSB_AI_PROVIDER_DEFAULT": "gemini",
                        "MSB_AI_GEMINI_MODEL_TALENT_SEARCH": "qwen/qwen3.6-flash"},
                   transport=fake_transport(record=calls))
        r.complete(MESSAGES, task="talent_search", model="deepseek/deepseek-v4-pro")
        self.assertEqual(calls[0]["body"]["model"], "deepseek/deepseek-v4-pro")

    def test_du_phong_khong_mang_model_cua_hub_khac(self):
        """Production 20/09: 254 lượt gọi 404 trong 48 giờ vì gửi
        `deepseek/deepseek-v4-pro` sang Gemini trong chuỗi dự phòng."""
        self._khong_route_db("talent_answer_judge")
        ProviderConfig.objects.all().delete()   # để thứ tự env có hiệu lực
        calls = []
        r = Router(env={"MSB_AI_GREENNODE_API_KEY": "k",
                        "MSB_AI_GREENNODE_MODEL": "qwen/qwen3.6-flash",
                        "MSB_AI_GEMINI_API_KEY": "k",
                        "MSB_AI_PROVIDER_DEFAULT": "greennode",
                        "MSB_AI_PROVIDER_FALLBACK": "gemini"},
                   transport=fake_transport(status=LLMUnavailable("greennode bận"),
                                            record=calls))
        with self.assertRaises(LLMUnavailable) as ctx:
            r.complete(MESSAGES, task="talent_answer_judge", budget_seconds=3,
                       model="deepseek/deepseek-v4-pro")
        # GreenNode (đầu chuỗi) được thử; Gemini bị bỏ qua chứ không tiêu một
        # lượt gọi để nhận 404.
        self.assertEqual([call["url"].split("//")[1].split("/")[0] for call in calls],
                         ["maas-llm-aiplatform-hcm.api.vngcloud.vn"])
        self.assertIn("gemini:deepseek/deepseek-v4-pro", str(ctx.exception))

    def test_model_gemini_khong_bi_gui_sang_hub_khac(self):
        self._khong_route_db("talent_answer_judge")
        ProviderConfig.objects.all().delete()
        calls = []
        r = Router(env={"MSB_AI_GEMINI_API_KEY": "k",
                        "MSB_AI_GREENNODE_API_KEY": "k",
                        "MSB_AI_GREENNODE_MODEL": "qwen/qwen3.6-flash",
                        "MSB_AI_PROVIDER_DEFAULT": "gemini",
                        "MSB_AI_PROVIDER_FALLBACK": "greennode"},
                   transport=fake_transport(status=LLMUnavailable("gemini bận"),
                                            record=calls))
        with self.assertRaises(LLMUnavailable):
            r.complete(MESSAGES, task="talent_answer_judge", budget_seconds=3,
                       model="gemini-3.5-flash")
        # Model của Gemini không được đem sang MaaS của GreenNode.
        self.assertTrue(all("googleapis.com" in call["url"] for call in calls), calls)

    def test_provider_tu_choi_model_thi_khong_thu_lai_mai(self):
        """HTTP 404/402 không tự khỏi như 429, nên nhớ theo cặp provider+model."""
        r = Router(env={"MSB_AI_GEMINI_API_KEY": "k",
                        "MSB_AI_PROVIDER_DEFAULT": "gemini"},
                   transport=fake_transport(
                       status=LLMUnavailable("gemini: yêu cầu bị từ chối (HTTP 404)."),
                       record=[]))
        for _ in range(2):
            with self.assertRaises(LLMUnavailable):
                r.complete(MESSAGES, task="talent_answer_judge",
                           model="gemini-3.5-flash", budget_seconds=2)
        self.assertTrue(r._model_blocked("gemini", "gemini-3.5-flash"))
        self.assertFalse(r._model_blocked("gemini", "gemini-3.5-pro"))

    def test_doi_provider_mac_dinh_KHONG_lam_mat_greennode(self):
        """Đặt default=gemini không được âm thầm loại GreenNode khỏi chuỗi.

        Nó đã có khoá thì vẫn phải được thử, và nó là điều kiện tranh giải
        Best Use of GreenNode.
        """
        order = self._router({"MSB_AI_PROVIDER_DEFAULT": "gemini"}).provider_order()
        self.assertEqual(order[0], "gemini")
        self.assertIn("greennode", order)
        self.assertEqual(set(order), set(DEFAULT_ORDER))

    def test_fallback_khai_tuong_minh_thi_ton_trong_dung_danh_sach(self):
        """Khai rõ thì làm đúng như khai — kể cả khi bỏ GreenNode."""
        order = self._router({
            "MSB_AI_PROVIDER_DEFAULT": "gemini",
            "MSB_AI_PROVIDER_FALLBACK": "deepseek",
        }).provider_order()
        self.assertEqual(order, ["gemini", "deepseek"])

    def test_khong_lap_lai_nha_cung_cap(self):
        order = self._router({
            "MSB_AI_PROVIDER_DEFAULT": "openai",
            "MSB_AI_PROVIDER_FALLBACK": "openai,gemini,openai",
        }).provider_order()
        self.assertEqual(order, ["openai", "gemini"])

    def test_bo_provider_khong_co_billing_khoi_fallback(self):
        order = self._router({
            "MSB_AI_PROVIDER_DEFAULT": "deepseek",
            "MSB_AI_PROVIDER_FALLBACK": "gemini,openai",
            "MSB_AI_DISABLED_PROVIDERS": "gemini",
        }).provider_order("talent_answer_compose")
        self.assertNotIn("gemini", order)
        self.assertLess(order.index("deepseek"), order.index("openai"))

    def test_disabled_provider_theo_task_khong_anh_huong_embedding(self):
        env = {
            "MSB_AI_PROVIDER_DEFAULT": "deepseek",
            "MSB_AI_PROVIDER_FALLBACK": "gemini",
            "MSB_AI_DISABLED_PROVIDERS_TALENT_ANSWER_COMPOSE": "gemini",
        }
        router = self._router(env)
        self.assertNotIn("gemini", router.provider_order("talent_answer_compose"))
        self.assertIn("gemini", router.provider_order("talent_embedding"))

    def test_bo_qua_nha_cung_cap_chua_co_khoa(self):
        """Chưa có khoá GreenNode vẫn phát triển được với GPT/Gemini/DeepSeek."""
        router = self._router({"MSB_AI_DEEPSEEK_API_KEY": "k"},
                              transport=fake_transport())
        result = router.complete(MESSAGES)
        self.assertEqual(result.provider, "deepseek")

    def test_khong_co_nha_cung_cap_nao_thi_bao_loi_huong_dan(self):
        with self.assertRaises(NoProviderConfigured) as ctx:
            self._router({}).complete(MESSAGES)
        self.assertIn("MSB_AI_GREENNODE_API_KEY", str(ctx.exception))

    def test_chuyen_sang_du_phong_khi_loi_tam_thoi(self):
        calls = {"n": 0}

        def transport(url, headers, body, timeout):
            calls["n"] += 1
            if "deepseek" in url:
                return 503, {}
            return 200, {"choices": [{"message": {"content": "ok"}}],
                         "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

        router = self._router({
            "MSB_AI_PROVIDER_DEFAULT": "deepseek",
            "MSB_AI_PROVIDER_FALLBACK": "openai",
            "MSB_AI_DEEPSEEK_API_KEY": "k", "MSB_AI_OPENAI_API_KEY": "k",
        }, transport=transport)

        result = router.complete(MESSAGES)
        self.assertEqual(result.provider, "openai")
        self.assertEqual(calls["n"], 2)

    def test_khoa_sai_KHONG_chuyen_sang_nha_cung_cap_khac(self):
        """Nếu chuyển, lỗi cấu hình bị giấu và hoá đơn nhảy sang chỗ khác."""
        router = self._router({
            "MSB_AI_PROVIDER_DEFAULT": "deepseek",
            "MSB_AI_PROVIDER_FALLBACK": "openai",
            "MSB_AI_DEEPSEEK_API_KEY": "k", "MSB_AI_OPENAI_API_KEY": "k",
        }, transport=fake_transport(401, {"error": {"message": "sai khoá"}}))

        with self.assertRaises(LLMAuthError):
            router.complete(MESSAGES)

    def test_bi_gioi_han_toc_do_thi_doi_roi_thu_lai(self):
        """Ca thường gặp: một nhà cung cấp, bị 429. Chuyển provider không cứu được."""
        lan = {"n": 0}

        def transport(url, headers, body, timeout):
            lan["n"] += 1
            if lan["n"] == 1:
                return 429, {"error": {"message": "quá nhanh"}}
            return 200, {"choices": [{"message": {"content": "ok"}}],
                         "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

        router = self._router({"MSB_AI_GEMINI_API_KEY": "k",
                               "MSB_AI_PROVIDER_DEFAULT": "gemini",
                               "MSB_AI_PROVIDER_FALLBACK": "gemini"},
                              transport=transport)
        router.RETRY_DELAY_SECONDS = 0        # test không cần đợi thật
        self.assertEqual(router.complete(MESSAGES).text, "ok")
        self.assertEqual(lan["n"], 2)

    def test_moi_nha_cung_cap_deu_hong_thi_bao_da_thu_nhung_ai(self):
        router = self._router({
            "MSB_AI_PROVIDER_DEFAULT": "deepseek",
            "MSB_AI_PROVIDER_FALLBACK": "openai",
            "MSB_AI_DEEPSEEK_API_KEY": "k", "MSB_AI_OPENAI_API_KEY": "k",
        }, transport=fake_transport(503, {}))

        with self.assertRaises(LLMUnavailable) as ctx:
            router.complete(MESSAGES)
        self.assertIn("deepseek", str(ctx.exception))
        self.assertIn("openai", str(ctx.exception))

    def test_available_liet_ke_nha_cung_cap_da_co_khoa(self):
        router = self._router({"MSB_AI_OPENAI_API_KEY": "k", "MSB_AI_GEMINI_API_KEY": "k"})
        self.assertEqual(set(router.available()), {"openai", "gemini"})

    # ---------- nhật ký ----------

    def test_ghi_nhat_ky_luot_goi_thanh_cong(self):
        entries = []
        router = self._router({"MSB_AI_OPENAI_API_KEY": "k"},
                              transport=fake_transport(), sink=entries.append)
        router.complete(MESSAGES, task="talent_search")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["provider"], "openai")
        self.assertEqual(entries[0]["task"], "talent_search")
        self.assertEqual(entries[0]["prompt_tokens"], 10)
        self.assertTrue(entries[0]["ok"])

    def test_ghi_nhat_ky_ca_luot_that_bai(self):
        entries = []
        router = self._router({"MSB_AI_OPENAI_API_KEY": "k"},
                              transport=fake_transport(503, {}), sink=entries.append)
        with self.assertRaises(LLMUnavailable):
            router.complete(MESSAGES)
        self.assertFalse(entries[0]["ok"])
        self.assertTrue(entries[0]["error"])

    def test_nhat_ky_hong_khong_lam_hong_loi_goi(self):
        def sink_hong(entry):
            raise RuntimeError("CSDL sập")

        router = self._router({"MSB_AI_OPENAI_API_KEY": "k"},
                              transport=fake_transport(), sink=sink_hong)
        self.assertEqual(router.complete(MESSAGES).text, "xin chào")


class LLMCallModelTest(TestCase):
    def test_tong_token(self):
        row = LLMCall.objects.create(provider="openai", model="m",
                                     prompt_tokens=10, completion_tokens=5)
        self.assertEqual(row.total_tokens, 15)

    def test_sink_django_ghi_duoc_vao_csdl(self):
        from .router import _django_sink
        _django_sink({"provider": "greennode", "model": "m", "task": "t",
                      "prompt_tokens": 3, "completion_tokens": 4, "latency_ms": 120,
                      "ok": True, "error": "", "at": 0})
        row = LLMCall.objects.get()
        self.assertEqual(row.provider, "greennode")
        self.assertEqual(row.total_tokens, 7)


class CompletionTest(TestCase):
    def test_repr_co_du_thong_tin_de_doc_log(self):
        text = repr(Completion("x", "greennode", "m", 10, 5, 250))
        for part in ("greennode", "m", "15tok", "250ms"):
            self.assertIn(part, text)


class DefaultOrderTest(TestCase):
    def test_greennode_dung_dau_agentbase_ngay_sau(self):
        # GreenNode-trực-tiếp vẫn đứng đầu (điều kiện tranh giải); agentbase là
        # đường tới GreenNode qua AgentBase, đứng ngay sau — dự phòng nhanh.
        self.assertEqual(DEFAULT_ORDER[:2], ["greennode", "agentbase"])
        self.assertEqual([p for p in DEFAULT_ORDER if p != "agentbase"],
                         ["greennode", "openai", "gemini", "deepseek"])


class ProviderObservabilityTest(TestCase):
    """Bằng chứng dùng GreenNode phải tách theo TỪNG nhà cung cấp.

    Con số gộp trả lời được "hệ thống có chậm không", nhưng không trả lời được
    câu giám khảo GreenNode sẽ hỏi: *"GreenNode chạy thế nào so với các nhà
    cung cấp khác trong chính hệ thống này"*.
    """

    def setUp(self):
        from accounts import roles
        from django.contrib.auth.models import Group, User

        roles.ensure_groups()
        self.admin = User.objects.create_user("quan-tri-quan-sat",
                                              password="mat-khau-dai-1")
        self.admin.groups.add(Group.objects.get(name=roles.ADMIN))
        self.client.force_login(self.admin)

    def _call(self, provider, ok=True, latency=100, prompt=10, completion=20):
        return LLMCall.objects.create(
            provider=provider, model="m", task="talent_search", ok=ok,
            latency_ms=latency, prompt_tokens=prompt, completion_tokens=completion)

    def test_do_tre_va_ty_le_thanh_cong_theo_tung_nha_cung_cap(self):
        self._call("greennode", ok=True, latency=200)
        self._call("greennode", ok=True, latency=400)
        self._call("openai", ok=False, latency=25000)
        body = self.client.get(reverse("ai-usage")).json()
        rows = {row["provider"]: row for row in body["by_provider"]}

        self.assertEqual(rows["greennode"]["avg_latency_ms"], 300)
        self.assertEqual(rows["greennode"]["success_rate"], 1.0)
        self.assertEqual(rows["openai"]["success_rate"], 0.0)

    def test_chi_phi_tach_theo_chang_khong_chi_theo_nha_cung_cap(self):
        """§2.F dòng 2 / §2.J dòng 1 — "chặng nào đáng tối ưu?".

        `by_provider`/`by_model` chỉ trả lời "nhà cung cấp nào tốn". Câu dẫn tới
        hành động là "chặng nào tốn": biết ③ nuốt phần lớn token thì mới biết
        nên đi tối ưu ③ chứ không phải ⑤.
        """
        LLMCall.objects.create(provider="greennode", model="m",
                               task="talent_answer_judge", ok=True,
                               latency_ms=100, prompt_tokens=800, completion_tokens=200)
        LLMCall.objects.create(provider="greennode", model="m",
                               task="talent_answer_plan", ok=True,
                               latency_ms=50, prompt_tokens=80, completion_tokens=20)
        # Lượt không gắn tác vụ không được làm lệch tổng.
        LLMCall.objects.create(provider="greennode", model="m", task="",
                               ok=True, latency_ms=10, prompt_tokens=5,
                               completion_tokens=5)

        body = self.client.get(reverse("ai-usage")).json()
        rows = {r["task"]: r for r in body["by_task"]}

        self.assertEqual(rows["talent_answer_judge"]["tokens"], 1000)
        self.assertEqual(rows["talent_answer_plan"]["tokens"], 100)
        # Phần token là con số dẫn tới hành động — ③ chiếm ~91%, ① ~9%.
        self.assertAlmostEqual(rows["talent_answer_judge"]["token_share"],
                               1000 / 1100, places=3)
        self.assertNotIn("", rows, "lượt không gắn tác vụ lọt vào bảng chặng")
        # Nhãn tiếng Việt, để không phải đoán `talent_answer_judge` là chặng nào.
        self.assertEqual(rows["talent_answer_judge"]["label"],
                         tasks_registry.TASKS["talent_answer_judge"].label)

    def test_do_tre_CHI_tinh_luot_thanh_cong(self):
        """Lượt timeout luôn bằng đúng ngưỡng chờ; gộp vào thì nhà cung cấp hay
        hỏng trông như chậm đều đặn thay vì hỏng."""
        self._call("greennode", ok=True, latency=100)
        self._call("greennode", ok=False, latency=25000)
        rows = {row["provider"]: row
                for row in self.client.get(reverse("ai-usage")).json()["by_provider"]}
        self.assertEqual(rows["greennode"]["avg_latency_ms"], 100)

    def test_dem_luot_phai_dung_du_phong(self):
        """Thiếu số này thì "GreenNode là mặc định" chỉ là một dòng cấu hình."""
        self._call("greennode")
        self._call("greennode")
        self._call("gemini")
        body = self.client.get(reverse("ai-usage")).json()
        self.assertEqual(body["primary_provider"], "greennode")
        self.assertEqual(body["fallback_calls"], 1)

    def test_chua_goi_lan_nao_thi_khong_chia_cho_khong(self):
        body = self.client.get(reverse("ai-usage")).json()
        self.assertEqual(body["total_calls"], 0)
        self.assertEqual(body["by_provider"], [])

    def test_cua_so_24h_percentile_va_nguyen_nhan_loi(self):
        from datetime import timedelta
        from django.utils import timezone
        old = self._call("greennode", latency=9999)
        LLMCall.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(hours=25))
        self._call("greennode", latency=100)
        self._call("greennode", latency=300)
        failed = self._call("greennode", ok=False, latency=25000)
        failed.error = "provider timeout"
        failed.save(update_fields=["error"])

        body = self.client.get(reverse("ai-usage") + "?hours=24").json()
        self.assertEqual(body["total_calls"], 3)
        self.assertEqual(body["window_hours"], 24)
        self.assertEqual(body["p50_latency_ms"], 200)
        self.assertEqual(body["p95_latency_ms"], 290)
        self.assertEqual(body["failure_causes"]["timeout"], 1)
        self.assertEqual(body["success_rate"], 0.667)
