"""Assistant + WhatsApp bot tests. The AI is replaced by fixed answers, so no network and no cost."""
import os
import sys
import json
import hmac
import uuid
import hashlib
import importlib

import pytest

os.environ.update({"MONGO_URL": "mongodb://localhost:27017", "AUTH_SECRET": "t" * 40, "GRACE_DAYS": "0", "PIN_PEPPER": "p" * 20,
                   "SUPER_ADMIN_PIN": "1111", "OWNER_PIN": "2222", "GEMINI_API_KEY": "", "CORS_ORIGINS": "https://jmk.sai.markets",
                   "OWNER_LANG": "hi", "WA_TOKEN": "tok", "WA_PHONE_ID": "123", "WA_VERIFY_TOKEN": "verify-me", "WA_APP_SECRET": "app-secret"})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import motor.motor_asyncio  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402
motor.motor_asyncio.AsyncIOMotorClient = AsyncMongoMockClient
from fastapi.testclient import TestClient  # noqa: E402

SENT = []
NEXT = []  # queue of parsed JSON the fake AI returns


@pytest.fixture()
def env():
    os.environ["DB_NAME"] = "jmk_" + uuid.uuid4().hex[:8]
    for m in ("server", "security", "assistant", "whatsapp"):
        sys.modules.pop(m, None)
    server = importlib.import_module("server")
    a = sys.modules["assistant"]
    w = sys.modules["whatsapp"]
    a.GEMINI_KEY = "fake"

    async def fake_understand(text, previous=None):
        return NEXT.pop(0), "test"

    async def fake_send(to, text):
        SENT.append((to, text))

    async def fake_gemini(parts, max_out=600, as_json=True):
        return json.dumps(NEXT.pop(0))

    a.understand = fake_understand
    a.gemini = fake_gemini
    w.send_text = fake_send
    SENT.clear()
    NEXT.clear()
    with TestClient(server.app) as c:
        yield c, server, a, w


def H(c, sid="geetansh", pin="2222"):
    r = c.post("/api/auth/login", json={"staff_id": sid, "pin": pin})
    return {"Authorization": "Bearer " + r.json()["token"]}


def stock(c, h, rolls=40):
    return c.post("/api/stock-in", headers=h, json={"item": {"film": "BOPP", "kind": "Plain", "micron": 20, "grade": "A"}, "rolls": rolls}).json()["item"]


def say(c, h, text):
    r = c.post("/api/ai/chat", headers=h, json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def sale(item_id, **kw):
    a = {"type": "sale", "item_id": item_id, "rolls": 8, "kg": 250, "unit": "kg", "rate": 95, "party": "Sharma Packers", "pay": "credit"}
    a.update(kw)
    return {"actions": [a], "question": ""}


def test_chat_needs_login(env):
    c, *_ = env
    assert c.post("/api/ai/chat", json={"text": "hi"}).status_code == 401


def test_sale_by_chat_preview_then_save(env):
    c, server, a, _ = env
    h = H(c)
    it = stock(c, h)
    NEXT.append(sale(it["id"]))
    r = say(c, h, "Sharma ko BOPP 20 micron 250 kg 95 rate udhaar, 8 roll")
    assert r["state"] == "draft"
    assert "₹23,750" in r["reply"] and "40→32" in r["reply"] and "1 save" in r["reply"] and r["reply"].count("\n") <= 2
    assert c.get("/api/summary", headers=h).json()["sold_today"] == 0  # nothing saved yet
    r = say(c, h, "1")
    assert r["state"] == "saved" and "₹23,750" in r["reply"]
    s = c.get("/api/summary", headers=h).json()
    assert s["sold_today"] == 2375000 and s["lena"] == 2375000
    e = c.get("/api/entries", headers=h).json()["entries"][0]
    assert e["kind"] == "sale"
    hist = c.get("/api/ai/chat", headers=h).json()["messages"]
    assert [m["who"] for m in hist][-4:] == ["owner", "bot", "owner", "bot"]


def test_change_then_save_remembers_the_fix(env):
    c, server, a, _ = env
    h = H(c)
    it = stock(c, h)
    NEXT.append(sale(it["id"], rate=90))
    say(c, h, "sharma 250 kg 90 udhaar")
    assert say(c, h, "2")["state"] == "changing"
    NEXT.append(sale(it["id"], rate=92))
    r = say(c, h, "rate 92 tha")
    assert "₹23,000" in r["reply"]
    say(c, h, "1")
    assert c.get("/api/summary", headers=h).json()["sold_today"] == 2300000


def test_cancel_saves_nothing(env):
    c, *_ = env
    h = H(c)
    it = stock(c, h)
    NEXT.append(sale(it["id"]))
    say(c, h, "sale")
    assert say(c, h, "3")["state"] == "cancelled"
    assert say(c, h, "1")["reply"]  # "1" with no open draft goes to the AI, not a save
    assert c.get("/api/summary", headers=h).json()["sold_today"] == 0


def test_missing_rate_asks_a_question(env):
    c, *_ = env
    h = H(c)
    it = stock(c, h)
    NEXT.append(sale(it["id"], rate=0))
    r = say(c, h, "sharma ko 250 kg diya")
    assert r["state"] == "question" and "rate" in r["reply"].lower()


def test_unknown_item_never_guessed(env):
    c, *_ = env
    h = H(c)
    stock(c, h)
    NEXT.append(sale(None, film="Nylon", micron=15, grade="A", item_text="nylon 15"))
    r = say(c, h, "nylon 15 becha")
    assert r["state"] == "question"
    assert c.get("/api/summary", headers=h).json()["sold_today"] == 0


def test_question_answered_from_books(env):
    c, *_ = env
    h = H(c)
    it = stock(c, h)
    c.post("/api/sales", headers=h, json={"item_id": it["id"], "rolls": 1, "kg": 100, "unit": "kg", "rate": 100, "party": "Gupta", "pay": "credit"})
    NEXT.append({"actions": [{"type": "query", "what": "party_balance", "party": "gupta"}]})
    assert "₹10,000" in say(c, h, "gupta ka kitna baaki")["reply"]
    NEXT.append({"actions": [{"type": "query", "what": "item_stock", "item_id": it["id"]}]})
    assert "39 roll" in say(c, h, "bopp 20 kitna bacha")["reply"]


def test_undo_by_chat(env):
    c, *_ = env
    h = H(c)
    it = stock(c, h)
    NEXT.append(sale(it["id"]))
    say(c, h, "sale")
    say(c, h, "1")
    r = say(c, h, "undo")
    assert "Undo" in r["reply"]
    say(c, h, "1")
    assert c.get("/api/summary", headers=h).json()["sold_today"] == 0


def sig(body: bytes):
    return "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()


def wa_msg(frm, text, mid=None):
    return {"entry": [{"changes": [{"value": {"messages": [{"id": mid or uuid.uuid4().hex, "from": frm, "type": "text", "text": {"body": text}}]}}]}]}


def post_wa(c, payload):
    b = json.dumps(payload).encode()
    return c.post("/api/wa/webhook", content=b, headers={"x-hub-signature-256": sig(b), "content-type": "application/json"})


def test_wa_verify_and_signature(env):
    c, *_ = env
    assert c.get("/api/wa/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"}).text == "42"
    assert c.get("/api/wa/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"}).status_code == 403
    b = json.dumps(wa_msg("919811122233", "hi")).encode()
    assert c.post("/api/wa/webhook", content=b, headers={"x-hub-signature-256": "sha256=bad"}).status_code == 403


def test_wa_unknown_number_gets_nothing(env):
    c, *_ = env
    h = H(c)
    stock(c, h)
    assert post_wa(c, wa_msg("919000000000", "sharma ko 250 kg")).status_code == 200
    assert SENT and "private number" in SENT[-1][1]
    assert c.get("/api/summary", headers=h).json()["sold_today"] == 0


def test_wa_owner_full_flow_and_dedupe(env):
    c, *_ = env
    h = H(c)
    sh = H(c, "ghost", "1111")
    assert c.patch("/api/staff/geetansh", headers=h, json={"wa_phone": "919811122233"}).status_code == 403  # only Sai Markets links numbers
    assert c.patch("/api/staff/geetansh", headers=sh, json={"wa_phone": "919811122233"}).status_code == 200
    it = stock(c, h)
    NEXT.append(sale(it["id"]))
    post_wa(c, wa_msg("919811122233", "sharma ko 250 kg 95 udhaar", mid="m1"))
    post_wa(c, wa_msg("919811122233", "sharma ko 250 kg 95 udhaar", mid="m1"))  # same message delivered twice
    assert len([s for s in SENT if "1 save" in s[1]]) == 1
    post_wa(c, wa_msg("919811122233", "1"))
    assert "app mein update" in SENT[-1][1]
    assert c.get("/api/summary", headers=h).json()["sold_today"] == 2375000


def test_labour_can_only_identify(env):
    c, *_ = env
    h = H(c)
    stock(c, h)
    r = c.post("/api/staff/helper", headers=h, json={"name": "Ramesh", "wa_phone": "9876543210"})
    assert r.status_code == 200
    assert all(s["id"] != r.json()["staff"]["id"] for s in c.get("/api/staff/public").json()["staff"])  # no app login card
    assert c.post("/api/auth/login", json={"staff_id": r.json()["staff"]["id"], "pin": "0000"}).status_code == 401
    post_wa(c, wa_msg("919876543210", "sharma ko 250 kg 95 udhaar"))
    assert "sirf maal pehchaan" in SENT[-1][1]
    post_wa(c, wa_msg("919876543210", "namaste"))
    assert "photo" in SENT[-1][1].lower()
    assert c.get("/api/summary", headers=h).json()["sold_today"] == 0


def test_identify_from_app_photo(env):
    c, *_ = env
    import io
    import base64
    from PIL import Image
    h = H(c)
    stock(c, h)
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (220, 220, 230)).save(buf, "JPEG")
    NEXT.append({"guesses": [{"film": "BOPP", "kind": "Plain", "chance": "Medium", "why": "clear and stiff"},
                             {"film": "Polyester", "kind": "Plain", "chance": "Low", "why": "also clear"}],
                 "micron": 20, "micron_from_label": True, "grade": "A", "checks": ["Paani mein daalo: tairta hai to BOPP"],
                 "burn": "BOPP: garam tel jaisi smell, boondein. Polyester: kaala dhuan, meethi smell.", "label": "20u"})
    r = c.post("/api/ai/chat", headers=h, json={"image": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}).json()
    assert "BOPP" in r["reply"] and "Check:" in r["reply"] and r["reply"].count("\n") <= 2  # short by default
    d = say(c, h, "detail")["reply"]  # reuses the last reading, no new AI call
    assert "Burn test" in d and "dhuan saans mein nahi" in d and "Godown mein aisa maal" in d


def test_polite_fixed_replies_need_no_ai(env):
    c, _, a, _ = env
    h = H(c)
    for msg, key in (("thank you", "thanks"), ("help", "help"), ("namaste", "greet"), ("1", "no_draft"), ("3", "no_draft")):
        assert say(c, h, msg)["reply"] == a.R[key], msg
    for v in a.R.values():  # every fixed reply is respectful: never "tu"/"tum"/"karo"/"bhejo"
        low = " " + v.lower() + " "
        assert not any(w in low for w in (" tu ", " tum ", " karo ", " bhejo ", " bolo ", " bata do "))


def test_english_for_owner_who_prefers_english(env):
    c, _, a, _ = env
    h = H(c)
    assert c.patch("/api/staff/geetansh", headers=h, json={"lang": "en"}).status_code == 200
    h = H(c)  # language change keeps the pass
    it = stock(c, h)
    NEXT.append(sale(it["id"]))
    r = say(c, h, "Sharma 250kg 95 credit")
    assert "credit" in r["reply"] and "Reply 1 save" in r["reply"] and "udhaar" not in r["reply"]
    r = say(c, h, "1")
    assert "saved" in r["reply"] and "updated in the app" in r["reply"]
    assert say(c, h, "thank you")["reply"] == a.R_EN["thanks"]
    NEXT.append({"actions": [{"type": "query", "what": "party_balance", "party": "Sharma Packers"}]})
    assert "owes us ₹23,750" in say(c, h, "Sharma due?")["reply"]
    for v in a.R_EN.values():
        assert not any(w in v.lower() for w in ("udhaar", "kijiye", "bhejiye", " ji ")), v


def test_unlimited_ai_never_blocks(env):
    c, *_ = env
    os.environ["AI_UNLIMITED"] = "1"
    os.environ["AI_LIMITS"] = '{"Owner": {"commands": 1}}'
    try:
        h = H(c)
        for _ in range(4):
            NEXT.append({"actions": [{"type": "query", "what": "today"}]})
            assert "limit" not in say(c, h, "aaj sale?")["reply"].lower()
    finally:
        os.environ.pop("AI_UNLIMITED")
        os.environ.pop("AI_LIMITS")
