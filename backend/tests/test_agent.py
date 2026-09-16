import sys
from types import SimpleNamespace

from conftest import login
from app import agent
from test_workflows import call, start, finish, seed_energy, A, B


def ask(c, h, message, admin=False, **params):
    return call(c, "POST", (B if admin else A) + "/agent/chat", h, {"message": message, **params})


def test_agent_nearby_and_boundaries(client, user_headers):
    assert ask(client, user_headers, "附近空闲快充")["status"] == "needs_clarification"
    data = ask(client, user_headers, "附近空闲快充", longitude=116.51, latitude=39.92)
    assert data["engine"] == "RULE_BASED_FALLBACK"
    stations = data["toolCalls"][0]["data"]["list"]
    assert stations and all(s["idleFastCount"] > 0 and s["distanceKm"] <= 10 for s in stations)
    assert ask(client, user_headers, "推荐餐厅")["status"] == "unsupported"
    call(
        client,
        "POST",
        A + "/agent/chat",
        user_headers,
        {"message": "最近订单", "userId": 2},
        code=40000,
    )
    call(client, "POST", A + "/agent/chat", user_headers, {"message": " "}, code=40000)
    call(client, "POST", A + "/agent/chat", {}, {"message": "最近订单"}, code=40001)


def test_agent_real_cost_order_and_isolation(client, user_headers):
    s = start(client, user_headers)
    seed_energy(s["id"])
    d = ask(client, user_headers, "当前充电费用")
    assert d["toolCalls"][0]["data"]["currentAmount"] > 0
    assert "元" in d["answer"]
    assert ask(client, user_headers, "当前电价")["toolCalls"][1]["data"]
    assert len(ask(client, user_headers, "充电异常")["toolCalls"]) == 2
    second = login(client, second=True)
    assert ask(client, second, "当前充电")["toolCalls"][0]["data"] is None
    finish(client, user_headers, s)
    assert ask(client, user_headers, "最近订单")["toolCalls"][0]["data"]["payableAmount"] > 0
    assert ask(client, second, "最近订单")["toolCalls"][0]["data"] is None


def test_agent_report_and_rbac(client, admin_headers, user_headers):
    finish(client, user_headers, start(client, user_headers))
    d = ask(client, admin_headers, "近一周运营报告", admin=True)
    assert len(d["toolCalls"]) == 3
    assert d["toolCalls"][0]["data"]["orderCount"] == 1
    assert d["toolCalls"][1]["data"][0]["orderCount"] == 1
    assert d["toolCalls"][0]["data"]["platformRevenue"] == 0
    token = client.post(
        B + "/auth/login", json={"username": "maintainer", "password": "Maintainer123!"}
    ).json()["data"]["accessToken"]
    h = {"Authorization": "Bearer " + token}
    assert ask(client, h, "故障排名", admin=True)["status"] == "answered"
    call(client, "POST", B + "/agent/chat", h, {"message": "运营报告"}, code=40300)
    call(client, "POST", B + "/agent/chat", user_headers, {"message": "运营报告"}, code=40300)


def test_agent_rate_limit(client, user_headers):
    for _ in range(30):
        ask(client, user_headers, "帮助")
    call(client, "POST", A + "/agent/chat", user_headers, {"message": "帮助"}, code=42900)


def test_agent_uses_zhipu_when_configured(monkeypatch):
    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["model"] == "glm-5.3"
            assert kwargs["messages"][1]["role"] == "user"
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="基于证据的模型回答"))]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "unit-test-key"
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("AGENT_LLM_ENABLED", "true")
    monkeypatch.setenv("ZHIPUAI_API_KEY", "unit-test-key")
    monkeypatch.setenv("ZHIPUAI_MODEL", "glm-5.3")
    monkeypatch.setitem(sys.modules, "zai", SimpleNamespace(ZhipuAiClient=FakeClient))
    assert (
        agent._llm_answer("问题", "草稿", [{"tool": "demo", "data": {"n": 1}}], "answered")
        == "基于证据的模型回答"
    )
