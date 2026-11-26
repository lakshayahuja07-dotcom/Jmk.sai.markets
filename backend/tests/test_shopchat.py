"""Public AI chat box tests. The model is replaced by fixed answers: no network, no cost."""
import os
import sys
import json
import uuid
import importlib

import pytest

os.environ.update({"MONGO_URL": "mongodb://localhost:27017", "AUTH_SECRET": "t" * 40, "GRACE_DAYS": "0", "PIN_PEPPER": "p" * 20,
                   "SUPER_ADMIN_PIN": "1111", "OWNER_PIN": "2222", "GEMINI_API_KEY": "", "CORS_ORIGINS": "https://jmk.sai.markets"})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import motor.motor_asyncio  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402
motor.motor_asyncio.AsyncIOMotorClient = AsyncMongoMockClient
from fastapi.testclient import TestClient  # noqa: E402

NEXT = []   # fake model answers (dicts), with token counts
SEEN = []   # system prompts and messages the fake model got


@pytest.fixture()
def c(monkeypatch):
    os.environ["DB_NAME"] = "jmk_" + uuid.uuid4().hex[:8]
    for k in ("PUBLIC_CHAT", "PUBLIC_CHAT_DAILY_USD", "PUBLIC_CHAT_PER_HOUR", "PUBLIC_CHAT_PER_DAY"):
        os.environ.pop(k, None)
    os.environ["ANTHROPIC_API_KEY"] = "fake"
    for m in ("server", "security", "leads", "assistant", "whatsapp", "shopchat"):
        sys.modules.pop(m, None)
    server = importlib.import_module("server")
    sc = sys.modules["shopchat"]

    async def fake(system, messages):
        SEEN.append((system, messages))
        a = NEXT.pop(0)
        return {"text": json.dumps(a), "in": 3000, "out": 300}

    sc.ask_model = fake
    NEXT.clear()
    SEEN.clear()
    with TestClient(server.app) as client:
        yield client
    os.environ.pop("ANTHROPIC_API_KEY", None)


def H(c, sid="geetansh", pin="2222"):
    r = c.post("/api/auth/login", json={"staff_id": sid, "pin": pin})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def say(c, text, site="jmk", cart=None, h=None):
    return c.post("/api/public/chat", headers=h or {}, json={"site": site, "messages": [{"role": "user", "text": text}], "cart": cart or []})


def test_bill_is_cleaned(c):
    NEXT.append({"reply": "Ji, bill ready.", "order": None,
                 "bill": {"doc_type": "Invoice", "customer": "Sharma", "items": [
                     {"name": "Box", "qty": 10, "rate": 250, "gst": 18}, {"name": "", "qty": 2, "rate": 5},
                     {"name": "Tape", "qty": "5", "rate": "-3", "gst": 7}]}})
    r = say(c, "bill bana do 10 box 250 ke, 5 tape", site="sai")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["bill"]["items"] == [{"name": "Box", "qty": 10, "rate": 250, "gst": 18}, {"name": "Tape", "qty": 5, "rate": 0, "gst": 0}]
    assert d["wa"] == "917678587824"


def test_jmk_order_only_keeps_real_stock(c):
    h = H(c)
    assert c.post("/api/stock-in", headers=h, json={"item": {"film": "BOPP", "kind": "Plain", "micron": 20, "grade": "A"}, "rolls": 40}).status_code == 200
    NEXT.append({"reply": "Ji.", "bill": None, "order": {"items": [{"name": "bopp plain 20 micron grade a", "qty": 10, "unit": "rolls"},
                                                                   {"name": "Gold bars", "qty": 1}], "note": "jaldi"}})
    d = say(c, "BOPP 20 ke 10 roll chahiye, aur gold bars").json()
    assert d["order"]["items"] == [{"name": "BOPP Plain 20 micron grade A", "qty": 10, "unit": "rolls"}]
    system = SEEN[-1][0]
    assert "BOPP Plain 20 micron grade A: 40 rolls" in system and "price" in system.lower()


def test_cart_goes_to_the_model(c):
    NEXT.append({"reply": "Ji.", "bill": None, "order": None})
    say(c, "aur 5 add karo", site="sai", cart=[{"name": "App setup", "qty": 1, "unit": ""}])
    assert SEEN[-1][1][-1]["content"].startswith("[Current cart: App setup x 1]")


def test_public_daily_cap_but_not_for_owner(c):
    os.environ["PUBLIC_CHAT_DAILY_USD"] = "0.0005"  # one fake answer costs 0.00045
    try:
        NEXT.extend([{"reply": "1"}, {"reply": "2"}, {"reply": "3"}])
        assert say(c, "hi", site="sai").status_code == 200
        assert say(c, "hi again", site="sai").status_code == 200   # 450 < 500 micro-dollars spent before this one
        assert say(c, "third", site="sai").status_code == 429      # 900 spent: public cap reached
        assert say(c, "owner can still chat", h=H(c)).status_code == 200
    finally:
        os.environ.pop("PUBLIC_CHAT_DAILY_USD", None)


def test_per_visitor_limit(c):
    os.environ["PUBLIC_CHAT_PER_HOUR"] = "2"
    try:
        NEXT.extend([{"reply": "a"}, {"reply": "b"}])
        assert say(c, "1").status_code == 200
        assert say(c, "2").status_code == 200
        assert say(c, "3").status_code == 429
    finally:
        os.environ.pop("PUBLIC_CHAT_PER_HOUR", None)


def test_off_without_key(c):
    os.environ.pop("ANTHROPIC_API_KEY", None)
    assert c.get("/api/public/chat").json() == {"on": False}
    assert say(c, "hi").status_code == 503


def test_bad_model_text_does_not_break(c):
    sc = sys.modules["shopchat"]

    async def junk(system, messages):
        return {"text": "Sorry, plain words", "in": 10, "out": 5}
    sc.ask_model = junk
    d = say(c, "hello").json()
    assert d["reply"] == "Sorry, plain words" and d["bill"] is None and d["order"] is None


def test_usage_stats_kept_apart_by_site(c):
    NEXT.extend([{"reply": "x", "bill": {"items": [{"name": "Box", "qty": 1, "rate": 10}]}},
                 {"reply": "y", "order": {"items": [{"name": "App setup", "qty": 1}]}}])
    say(c, "bill", site="sai")
    say(c, "order", site="sai")
    assert c.post("/api/public/event", json={"site": "sai", "feature": "wa_order", "products": ["App setup"]}).status_code == 200
    assert c.post("/api/public/event", json={"site": "jmk", "feature": "bill_pdf", "products": ["Roll"]}).status_code == 200
    assert c.post("/api/public/event", json={"site": "jmk", "feature": "hack"}).status_code == 422
    sup, own = H(c, "ghost", "1111"), H(c)
    s = c.get("/api/public/stats?site=sai", headers=sup).json()
    assert s["features"]["chat"] == 2 and s["features"]["ai_bill"] == 1 and s["features"]["cart"] == 1 and s["features"]["wa_order"] == 1
    app = next(p for p in s["products"] if p["name"] == "App setup")
    assert app["wa_order"] == 1 and app["cart"] == 1
    assert s["ai_usd"] == 0.0009
    j = c.get("/api/public/stats?site=jmk", headers=own).json()
    assert j["features"]["bill_pdf"] == 1 and j["features"]["chat"] == 0
    assert c.get("/api/public/stats?site=sai", headers=own).status_code == 403
    assert c.get("/api/public/stats?site=jmk").status_code == 401
