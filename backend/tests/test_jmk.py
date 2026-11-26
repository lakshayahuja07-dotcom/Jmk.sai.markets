"""JMK tests: python -m pytest backend/tests  (in-memory database, no network, no AI)."""
import os
import sys
import uuid
import importlib

import pytest

os.environ.update({"MONGO_URL": "mongodb://localhost:27017", "DB_NAME": "jmk_test", "AUTH_SECRET": "t" * 40, "GRACE_DAYS": "0",
                   "PIN_PEPPER": "p" * 20, "SUPER_ADMIN_PIN": "1111", "OWNER_PIN": "2222", "GEMINI_API_KEY": "",
                   "CORS_ORIGINS": "https://jmk.sai.markets"})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import motor.motor_asyncio  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402
motor.motor_asyncio.AsyncIOMotorClient = AsyncMongoMockClient

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def c():
    os.environ["DB_NAME"] = "jmk_" + uuid.uuid4().hex[:8]
    for m in ("server", "security", "leads"):
        sys.modules.pop(m, None)
    server = importlib.import_module("server")
    with TestClient(server.app) as client:
        yield client


def H(c, sid="geetansh", pin="2222"):
    r = c.post("/api/auth/login", json={"staff_id": sid, "pin": pin})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


BOPP = {"film": "BOPP", "kind": "Plain", "micron": 20, "grade": "A"}


def add_stock(c, h, rolls=40, **kw):
    r = c.post("/api/stock-in", headers=h, json={"item": BOPP, "rolls": rolls, **kw})
    assert r.status_code == 200, r.text
    return r.json()["item"]


def test_login_cards_hide_super_admin_and_pins(c):
    rows = c.get("/api/staff/public").json()["staff"]
    assert {r["id"] for r in rows} == {"geetansh"}
    assert all("pin_hash" not in r for r in rows)
    assert c.post("/api/auth/login", json={"staff_id": "geetansh", "pin": "0000"}).status_code == 401
    assert c.post("/api/auth/login", json={"staff_id": "ghost", "pin": "1111"}).status_code == 200


def test_writes_need_login(c):
    assert c.post("/api/stock-in", json={"item": BOPP, "rolls": 5}).status_code == 401
    assert c.get("/api/summary").status_code == 401
    assert c.get("/api/parties").status_code == 401


def test_same_item_pools(c):
    h = H(c)
    a = add_stock(c, h, 40)
    b = add_stock(c, h, 10, item={"film": " bopp ", "kind": "plain", "micron": 20.0, "grade": "A"})
    assert a["id"] == b["id"] and b["rolls"] == 50
    other = add_stock(c, h, 5, item={**BOPP, "grade": "B"})
    assert other["id"] != a["id"]


def test_credit_sale_moves_stock_and_khata_together(c):
    h = H(c)
    it = add_stock(c, h, 40)
    r = c.post("/api/sales", headers=h, json={"item_id": it["id"], "rolls": 8, "kg": 250, "unit": "kg", "rate": 95,
                                             "party": "Sharma Packers", "pay": "credit"})
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["amount"] == 2375000  # Rs 23,750 in paise
    items = {i["id"]: i for i in c.get("/api/items", headers=h).json()["items"]}
    assert items[it["id"]]["rolls"] == 32
    assert items[it["id"]]["avg_kg"] == 31.2 and items[it["id"]]["est_kg"] == 1000
    buyers = c.get("/api/parties?kind=buyer", headers=h).json()
    assert buyers["parties"][0]["name"] == "Sharma Packers" and buyers["parties"][0]["balance"] == 2375000
    s = c.get("/api/summary", headers=h).json()
    assert s["sold_today"] == 2375000 and s["lena"] == 2375000 and s["sales_today"] == 1


def test_cash_sale_leaves_khata_alone_and_roll_rate_works(c):
    h = H(c)
    it = add_stock(c, h, 10)
    r = c.post("/api/sales", headers=h, json={"item_id": it["id"], "rolls": 3, "unit": "roll", "rate": 2500, "party": "Walk-in", "pay": "cash"})
    assert r.json()["entry"]["amount"] == 750000
    assert c.get("/api/summary", headers=h).json()["lena"] == 0


def test_sale_rules(c):
    h = H(c)
    it = add_stock(c, h, 10)
    base = {"item_id": it["id"], "rolls": 1, "unit": "kg", "rate": 90, "pay": "cash"}
    assert c.post("/api/sales", headers=h, json={**base, "kg": 0}).status_code == 400
    assert c.post("/api/sales", headers=h, json={**base, "kg": 30, "pay": "credit", "party": " "}).status_code == 400
    assert c.post("/api/sales", headers=h, json={**base, "kg": 30, "rate": 0}).status_code == 422


def test_payment_reduces_balance(c):
    h = H(c)
    it = add_stock(c, h, 10)
    c.post("/api/sales", headers=h, json={"item_id": it["id"], "rolls": 2, "kg": 100, "unit": "kg", "rate": 100, "party": "RK", "pay": "credit"})
    c.post("/api/payments", headers=h, json={"party": "rk", "kind": "buyer", "amount": 4000, "mode": "upi"})
    p = c.get("/api/parties?kind=buyer", headers=h).json()["parties"][0]
    assert p["balance"] == 600000
    d = c.get(f"/api/parties/{p['id']}", headers=h).json()
    assert d["party"]["balance"] == 600000 and len(d["entries"]) == 2


def test_supplier_credit_purchase_is_dena(c):
    h = H(c)
    add_stock(c, h, 20, supplier="Euro Films", amount=150000, pay="credit")
    s = c.get("/api/summary", headers=h).json()
    assert s["dena"] == 15000000 and s["suppliers_owed"] == 1
    assert c.post("/api/stock-in", headers=h, json={"item": BOPP, "rolls": 1, "pay": "credit"}).status_code == 400


def test_undo_restores_everything_once(c):
    h = H(c)
    it = add_stock(c, h, 40)
    e = c.post("/api/sales", headers=h, json={"item_id": it["id"], "rolls": 8, "kg": 250, "unit": "kg", "rate": 95, "party": "Sharma", "pay": "credit"}).json()["entry"]
    assert c.post(f"/api/entries/{e['id']}/undo", headers=h).status_code == 200
    assert c.post(f"/api/entries/{e['id']}/undo", headers=h).status_code == 409
    item = [i for i in c.get("/api/items", headers=h).json()["items"] if i["id"] == it["id"]][0]
    assert item["rolls"] == 40 and item["avg_kg"] is None
    s = c.get("/api/summary", headers=h).json()
    assert s["lena"] == 0 and s["sold_today"] == 0


def test_double_tap_saves_once(c):
    h = H(c)
    it = add_stock(c, h, 40)
    body = {"item_id": it["id"], "rolls": 2, "kg": 60, "unit": "kg", "rate": 90, "party": "X", "pay": "credit", "op": "op-abc-123"}
    a = c.post("/api/sales", headers=h, json=body).json()["entry"]
    b = c.post("/api/sales", headers=h, json=body).json()["entry"]
    assert a["id"] == b["id"]
    item = [i for i in c.get("/api/items", headers=h).json()["items"] if i["id"] == it["id"]][0]
    assert item["rolls"] == 38


def test_public_stock_has_no_money(c):
    h = H(c)
    it = add_stock(c, h, 40, supplier="Euro Films", amount=99999, pay="credit")
    c.post("/api/sales", headers=h, json={"item_id": it["id"], "rolls": 2, "kg": 60, "unit": "kg", "rate": 90, "party": "X", "pay": "credit"})
    c.patch(f"/api/items/{it['id']}", headers=h, json={"note": "secret cost 70"})
    pub = c.get("/api/stock").json()
    txt = str(pub)
    assert pub["items"][0]["rolls"] == 38
    for bad in ("rate", "amount", "balance", "secret cost", "Euro", "avg_kg", "9999"):
        assert bad not in txt
    c.patch(f"/api/items/{it['id']}", headers=h, json={"visible": False})
    assert c.get("/api/stock").json()["items"] == []


def test_only_super_admin_sets_shop_details(c):
    h = H(c)
    body = {"name": "JMK Traders", "tagline": "Film", "area": "Alipur", "phone": "919999999999", "whatsapp": "919999999999"}
    assert c.put("/api/admin/shop", headers=h, json=body).status_code == 403
    sh = H(c, "ghost", "1111")
    assert c.put("/api/admin/shop", headers=sh, json=body).status_code == 200
    assert c.get("/api/shop").json()["whatsapp"] == "919999999999"


def test_rename_item_cannot_collide(c):
    h = H(c)
    a = add_stock(c, h, 5)
    b = add_stock(c, h, 5, item={**BOPP, "micron": 25})
    assert c.patch(f"/api/items/{b['id']}", headers=h, json={"micron": 20}).status_code == 409
    assert c.patch(f"/api/items/{a['id']}", headers=h, json={"kind": "Metallised"}).status_code == 200


def test_ai_off_without_key(c):
    h = H(c)
    assert c.post("/api/ai/read-roll", headers=h, json={"photo": "data:image/jpeg;base64,AAAA"}).status_code == 503


def test_photo_roundtrip(c):
    import io
    import base64
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 60)).save(buf, "PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    h = H(c)
    it = add_stock(c, h, 5, photo=url)
    assert it["photo"]
    r = c.get(f"/api/photo/{it['photo']}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"


def test_free_bill_leads_kept_apart_by_site(c):
    bill = {"shop": "Sharma Traders", "phone": "+91 98100 12345", "doc_type": "Invoice", "total": 1180, "items": 2}
    assert c.post("/api/leads/bill", json={**bill, "source": "sai"}).status_code == 200
    assert c.post("/api/leads/bill", json={**bill, "source": "sai", "total": 500}).status_code == 200
    assert c.post("/api/leads/bill", json={**bill, "source": "jmk"}).status_code == 200
    assert c.post("/api/leads/bill", json={**bill, "source": "sai", "phone": "12345"}).status_code == 422
    assert c.post("/api/leads/bill", json={**bill, "source": "other"}).status_code == 422
    sup, own = H(c, "ghost", "1111"), H(c)
    sai = c.get("/api/leads?source=sai", headers=sup).json()["leads"]
    assert len(sai) == 1 and sai[0]["phone"] == "9810012345" and sai[0]["bills"] == 2 and sai[0]["last_total"] == 500
    assert len(c.get("/api/leads?source=jmk", headers=own).json()["leads"]) == 1
    assert c.get("/api/leads?source=sai", headers=own).status_code == 403
    assert c.get("/api/leads?source=jmk").status_code == 401


def test_accounts_only_for_owner_super_and_accountant(c):
    own = H(c)
    r = c.post("/api/staff", headers=own, json={"name": "Mehta CA", "pin": "4321", "role": "Accountant"})
    assert r.status_code == 200, r.text
    acc_id = r.json()["staff"]["id"]
    r = c.post("/api/staff", headers=own, json={"name": "Ravi", "pin": "5678"})
    assert r.status_code == 200 and r.json()["staff"]["role"] == "Salesman"
    sal = H(c, r.json()["staff"]["id"], "5678")
    acc = H(c, acc_id, "4321")
    assert c.get("/api/parties?kind=buyer", headers=acc).status_code == 200
    assert c.get("/api/summary", headers=acc).json()["lena"] is not None
    assert c.get("/api/summary", headers=sal).json()["lena"] is None
    assert c.get("/api/parties?kind=buyer", headers=sal).json()["total"] is None
    assert c.post("/api/stock-in", headers=acc, json={"item": BOPP, "rolls": 5}).status_code == 403
    assert c.post("/api/staff", headers=own, json={"name": "X", "pin": "1234", "role": "Owner"}).status_code == 422
