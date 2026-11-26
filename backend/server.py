"""JMK Traders app (Sai Markets core). Stock, sales, khata and a public stock page.

Rules:
- Items are POOLED: one item = film + type + micron + grade. Adding stock of the same item adds to it.
- Stock is counted in rolls. Kilos are weighed only at sale (kanta weight), so kg in stock is an estimate.
- Every money/stock action is one ENTRY (sale, stock_in, payment_in, payment_out). Nothing is ever deleted:
  "undo" writes a reversing entry and marks the original reversed.
- Khata (party balance) is worked out from entries, so it can never drift from the history.
  Buyer balance  = credit sales - payments in       (lena hai)
  Supplier balance = credit purchases - payments out (dena hai)
- Money is stored in paise (whole numbers) so totals never get rounding errors.
- The public page shows stock only: no rates, no costs, no khata.
"""
import os
import io
import re
import json
import uuid
import base64
import logging
import secrets
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import security  # noqa: E402
from security import current_user, need, charge_ai, accounts_user, ACCOUNTS, SUPER, OWNER  # noqa: E402

client = AsyncIOMotorClient(os.environ['MONGO_URL'])
db = client[os.environ.get('DB_NAME') or 'jmk']
GEMINI_KEY = os.environ.get('GEMINI_API_KEY', '')
VISION_MODEL = os.environ.get('GEMINI_VISION_MODEL', 'gemini-3.1-flash-lite')
MAX_PHOTO_BYTES = 12 * 1024 * 1024
IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="JMK Traders", docs_url=None, redoc_url=None, openapi_url=None)
api = APIRouter(prefix="/api")
log = logging.getLogger("jmk")
logging.basicConfig(level=logging.INFO)

FILMS = ["BOPP", "Polyester", "LDPE", "CPP", "Nylon", "Metallised", "PVC", "HDPE", "Other"]
GRADES = {"A": "Usable", "B": "Needs processing", "C": "Scrap"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def nid(p: str) -> str:
    return p + secrets.token_hex(6)


def paise(rupees: float) -> int:
    return int(round(float(rupees) * 100))


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def item_key(film: str, kind: str, micron: float, grade: str) -> str:
    m = ("%g" % float(micron)) if micron else "0"
    return "|".join([norm(film).lower(), norm(kind).lower(), m, grade.upper()])


def item_name(it: Dict[str, Any]) -> str:
    parts = [it["film"]]
    if it.get("kind"):
        parts.append(it["kind"])
    return " ".join(parts)


def item_out(it: Dict[str, Any], public: bool = False) -> Dict[str, Any]:
    rolls_sold = it.get("rolls_sold_kg_basis", 0)
    avg = (it.get("kg_sold", 0) / rolls_sold) if rolls_sold else (it.get("avg_kg") or 0)
    out = {"id": it["id"], "film": it["film"], "kind": it.get("kind", ""), "micron": it.get("micron", 0),
           "grade": it["grade"], "grade_label": GRADES.get(it["grade"], ""), "name": item_name(it),
           "rolls": it.get("rolls", 0), "est_kg": round(max(it.get("rolls", 0), 0) * avg) if avg else None,
           "photo": it.get("photo"), "note": it.get("note", "") if not public else it.get("public_note", "")}
    if not public:
        out.update({"visible": it.get("visible", True), "avg_kg": round(avg, 1) if avg else None,
                    "updated_at": it.get("updated_at")})
    return out


# ---------------- photos (kept in the database so they survive restarts) ----------------
def _shrink(raw: bytes) -> bytes:
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(raw))
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True)
    return buf.getvalue()


def _decode(data_url: str) -> bytes:
    m = re.match(r"^data:image/(jpeg|jpg|png|webp|heic|heif);base64,(.+)$", data_url or "", re.S)
    if not m:
        raise HTTPException(400, "Please send a photo (JPG, PNG or WEBP)")
    raw = base64.b64decode(m.group(2))
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo is too large")
    return raw


async def save_photo(data_url: str) -> str:
    try:
        blob = _shrink(_decode(data_url))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "Could not read this photo")
    pid = secrets.token_hex(10)
    await db.photos.insert_one({"id": pid, "mime": "image/jpeg", "data": blob, "at": now()})
    return pid


@api.get("/photo/{pid}")
async def get_photo(pid: str):
    if not re.fullmatch(r"[a-f0-9]{20}", pid):
        raise HTTPException(404, "No such photo")
    d = await db.photos.find_one({"id": pid}, {"_id": 0, "mime": 1, "data": 1})
    if not d:
        raise HTTPException(404, "No such photo")
    return Response(bytes(d["data"]), media_type=d["mime"], headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ---------------- shop details (only Sai Markets super admin changes them) ----------------
SHOP_DEFAULT = {"name": "JMK Traders", "tagline": "Plastic film stocklots", "area": "Alipur, Delhi", "phone": "", "whatsapp": ""}


async def shop() -> Dict[str, Any]:
    d = await db.settings.find_one({"id": "shop"}, {"_id": 0, "id": 0}) or {}
    return {**SHOP_DEFAULT, **d}


class ShopIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    tagline: str = Field(default="", max_length=80)
    area: str = Field(default="", max_length=80)
    phone: str = Field(default="", pattern=r"^\d{0,13}$")
    whatsapp: str = Field(default="", pattern=r"^\d{0,13}$")


@api.get("/")
async def root():
    return {"ok": True, "app": "jmk"}


@api.get("/shop")
async def shop_get():
    return await shop()


@api.put("/admin/shop")
async def shop_set(body: ShopIn, user=Depends(need(SUPER))):
    await db.settings.update_one({"id": "shop"}, {"$set": {"id": "shop", **body.model_dump()}}, upsert=True)
    return await shop()


# ---------------- public stock page ----------------
@api.get("/stock")
async def public_stock():
    rows = await db.items.find({"visible": {"$ne": False}, "rolls": {"$gt": 0}}, {"_id": 0}).sort("film", 1).to_list(2000)
    return {"items": [item_out(r, public=True) for r in rows], "films": FILMS, "updated": today_ist()}


# ---------------- items ----------------
class ItemIn(BaseModel):
    film: str = Field(min_length=1, max_length=40)
    kind: str = Field(default="", max_length=40)
    micron: float = Field(default=0, ge=0, le=2000)
    grade: str = Field(pattern="^[ABC]$")


class ItemPatch(BaseModel):
    film: Optional[str] = Field(default=None, max_length=40)
    kind: Optional[str] = Field(default=None, max_length=40)
    micron: Optional[float] = Field(default=None, ge=0, le=2000)
    grade: Optional[str] = Field(default=None, pattern="^[ABC]$")
    visible: Optional[bool] = None
    note: Optional[str] = Field(default=None, max_length=200)
    public_note: Optional[str] = Field(default=None, max_length=120)
    avg_kg: Optional[float] = Field(default=None, ge=0, le=5000)
    photo: Optional[str] = None  # data URL


async def find_or_make_item(body: ItemIn, user) -> Dict[str, Any]:
    key = item_key(body.film, body.kind, body.micron, body.grade)
    it = await db.items.find_one({"key": key}, {"_id": 0})
    if it:
        return it
    it = {"id": nid("i"), "key": key, "film": norm(body.film), "kind": norm(body.kind), "micron": body.micron,
          "grade": body.grade, "rolls": 0, "kg_sold": 0, "rolls_sold_kg_basis": 0, "visible": True,
          "created_at": now(), "updated_at": now(), "by": user["id"]}
    try:
        await db.items.insert_one(dict(it))
    except Exception:  # two phones made the same item at once: use the one that won
        it = await db.items.find_one({"key": key}, {"_id": 0})
    return it


@api.get("/items")
async def items_list(user=Depends(current_user)):
    rows = await db.items.find({}, {"_id": 0}).sort([("film", 1), ("micron", 1)]).to_list(5000)
    return {"items": [item_out(r) for r in rows], "films": FILMS}


@api.post("/items")
async def items_add(body: ItemIn, user=Depends(current_user)):
    return {"item": item_out(await find_or_make_item(body, user))}


@api.patch("/items/{iid}")
async def items_edit(iid: str, body: ItemPatch, user=Depends(need(OWNER))):
    it = await db.items.find_one({"id": iid}, {"_id": 0})
    if not it:
        raise HTTPException(404, "Item not found")
    upd: Dict[str, Any] = {k: v for k, v in body.model_dump(exclude_none=True).items() if k != "photo"}
    if body.photo:
        upd["photo"] = await save_photo(body.photo)
    if {"film", "kind", "micron", "grade"} & set(upd):
        merged = {**it, **upd}
        key = item_key(merged["film"], merged.get("kind", ""), merged.get("micron", 0), merged["grade"])
        other = await db.items.find_one({"key": key, "id": {"$ne": iid}})
        if other:
            raise HTTPException(409, "This item already exists. Add stock to that one instead.")
        upd["key"] = key
        for k in ("film", "kind"):
            if k in upd:
                upd[k] = norm(upd[k])
    upd["updated_at"] = now()
    await db.items.update_one({"id": iid}, {"$set": upd})
    return {"item": item_out(await db.items.find_one({"id": iid}, {"_id": 0}))}


# ---------------- parties (khata) ----------------
async def party_for(name: str, kind: str, phone: str = "") -> Optional[Dict[str, Any]]:
    name = norm(name)
    if not name:
        return None
    key = kind + "|" + name.lower()
    p = await db.parties.find_one({"key": key}, {"_id": 0})
    if p:
        if phone and not p.get("phone"):
            await db.parties.update_one({"id": p["id"]}, {"$set": {"phone": phone}})
            p["phone"] = phone
        return p
    p = {"id": nid("p"), "key": key, "name": name, "kind": kind, "phone": phone, "created_at": now()}
    try:
        await db.parties.insert_one(dict(p))
    except Exception:
        p = await db.parties.find_one({"key": key}, {"_id": 0})
    return p


EFFECT = {  # how each entry moves a party's balance (+ = more owed)
    "sale": lambda e: e["amount"] if e.get("pay") == "credit" else 0,
    "payment_in": lambda e: -e["amount"],
    "stock_in": lambda e: e.get("amount", 0) if e.get("pay") == "credit" else 0,
    "payment_out": lambda e: -e["amount"],
}


def effect(e: Dict[str, Any]) -> int:
    return 0 if e.get("reversed") or e.get("kind") == "undo" else EFFECT.get(e["kind"], lambda _: 0)(e)


async def balances(kind: Optional[str] = None) -> Dict[str, int]:
    q: Dict[str, Any] = {"party_id": {"$ne": None}, "reversed": {"$ne": True}, "kind": {"$ne": "undo"}}
    out: Dict[str, int] = {}
    async for e in db.entries.find(q, {"_id": 0, "party_id": 1, "kind": 1, "amount": 1, "pay": 1}):
        out[e["party_id"]] = out.get(e["party_id"], 0) + effect(e)
    return out


@api.get("/parties")
async def parties_list(kind: str = "buyer", user=Depends(current_user)):
    if kind not in ("buyer", "supplier"):
        raise HTTPException(400, "kind must be buyer or supplier")
    rows = await db.parties.find({"kind": kind}, {"_id": 0, "key": 0}).to_list(5000)
    bal = await balances()
    last = {}
    async for e in db.entries.find({"party_id": {"$in": [r["id"] for r in rows]}}, {"_id": 0, "party_id": 1, "at": 1}).sort("at", -1):
        last.setdefault(e["party_id"], e["at"])
    for r in rows:
        r["balance"] = bal.get(r["id"], 0)
        r["last_at"] = last.get(r["id"])
    rows.sort(key=lambda r: (-r["balance"], r["name"].lower()))
    if user["role"] not in ACCOUNTS:  # salesman: names only, for picking a buyer; no balances
        return {"parties": [{"id": r["id"], "name": r["name"], "kind": r["kind"], "phone": r.get("phone", "")} for r in rows], "total": None}
    return {"parties": rows, "total": sum(max(r["balance"], 0) for r in rows)}


@api.get("/parties/{pid}")
async def party_detail(pid: str, user=Depends(accounts_user)):
    p = await db.parties.find_one({"id": pid}, {"_id": 0, "key": 0})
    if not p:
        raise HTTPException(404, "Not found")
    rows = await db.entries.find({"party_id": pid}, {"_id": 0}).sort("at", -1).to_list(500)
    p["balance"] = sum(effect(e) for e in rows)
    return {"party": p, "entries": [entry_out(e) for e in rows]}


class PartyPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=60)
    phone: Optional[str] = Field(default=None, pattern=r"^\d{0,13}$")


@api.patch("/parties/{pid}")
async def party_edit(pid: str, body: PartyPatch, user=Depends(need(OWNER))):
    p = await db.parties.find_one({"id": pid})
    if not p:
        raise HTTPException(404, "Not found")
    upd = body.model_dump(exclude_none=True)
    if "name" in upd:
        upd["name"] = norm(upd["name"])
        if not upd["name"]:
            raise HTTPException(400, "Name can't be empty")
        upd["key"] = p["kind"] + "|" + upd["name"].lower()
        if await db.parties.find_one({"key": upd["key"], "id": {"$ne": pid}}):
            raise HTTPException(409, "Another party already has this name")
    if upd:
        await db.parties.update_one({"id": pid}, {"$set": upd})
    return {"ok": True}


# ---------------- entries ----------------
def entry_out(e: Dict[str, Any]) -> Dict[str, Any]:
    return {k: e.get(k) for k in ("id", "at", "kind", "item_id", "item_name", "rolls", "kg", "unit", "rate", "amount",
                                    "party_id", "party_name", "pay", "mode", "note", "reversed", "reverses", "by_name")}


async def _dupe(op: str) -> Optional[Dict[str, Any]]:
    """Same button pressed twice on a slow network: return the first result instead of saving twice."""
    if not op:
        return None
    return await db.entries.find_one({"op": op}, {"_id": 0})


async def _add_entry(e: Dict[str, Any], user) -> Dict[str, Any]:
    e.update({"id": nid("e"), "at": now(), "day": today_ist(), "by": user["id"], "by_name": user["name"], "reversed": False})
    try:
        await db.entries.insert_one(dict(e))
    except Exception:
        d = await _dupe(e.get("op", ""))
        if d:
            return d
        raise
    return e


class SaleIn(BaseModel):
    item_id: str
    rolls: int = Field(default=0, ge=0, le=100000)
    kg: float = Field(default=0, ge=0, le=10000000)
    unit: str = Field(pattern="^(kg|roll)$")
    rate: float = Field(gt=0, le=10000000)
    party: str = Field(default="", max_length=60)
    phone: str = Field(default="", pattern=r"^\d{0,13}$")
    pay: str = Field(pattern="^(cash|credit)$")
    note: str = Field(default="", max_length=200)
    op: str = Field(default="", max_length=40)


@api.post("/sales")
async def sale_add(body: SaleIn, user=Depends(current_user)):
    d = await _dupe(body.op)
    if d:
        return {"entry": entry_out(d)}
    it = await db.items.find_one({"id": body.item_id}, {"_id": 0})
    if not it:
        raise HTTPException(404, "Item not found")
    if body.unit == "kg" and body.kg <= 0:
        raise HTTPException(400, "Enter the kanta weight (kg)")
    if body.unit == "roll" and body.rolls <= 0:
        raise HTTPException(400, "Enter how many rolls")
    if body.pay == "credit" and not norm(body.party):
        raise HTTPException(400, "Udhaar needs the buyer's name")
    qty = body.kg if body.unit == "kg" else body.rolls
    amount = paise(qty * body.rate)
    p = await party_for(body.party, "buyer", body.phone)
    e = await _add_entry({"kind": "sale", "item_id": it["id"], "item_name": f'{item_name(it)} {("%g" % it["micron"]) + " mic " if it.get("micron") else ""}{it["grade"]}'.strip(),
                          "rolls": body.rolls, "kg": body.kg, "unit": body.unit, "rate": paise(body.rate), "amount": amount,
                          "party_id": p["id"] if p else None, "party_name": p["name"] if p else "", "pay": body.pay,
                          "note": norm(body.note), "op": body.op or None}, user)
    inc: Dict[str, Any] = {"rolls": -body.rolls}
    if body.kg > 0 and body.rolls > 0:  # both known: teaches the average roll weight
        inc.update({"kg_sold": body.kg, "rolls_sold_kg_basis": body.rolls})
    await db.items.update_one({"id": it["id"]}, {"$inc": inc, "$set": {"updated_at": now()}})
    return {"entry": entry_out(e)}


class StockInIn(BaseModel):
    item: Optional[ItemIn] = None
    item_id: Optional[str] = None
    rolls: int = Field(gt=0, le=100000)
    supplier: str = Field(default="", max_length=60)
    amount: float = Field(default=0, ge=0, le=1000000000)
    pay: str = Field(default="cash", pattern="^(cash|credit)$")
    note: str = Field(default="", max_length=200)
    photo: Optional[str] = None
    op: str = Field(default="", max_length=40)


@api.post("/stock-in")
async def stock_in(body: StockInIn, user=Depends(current_user)):
    d = await _dupe(body.op)
    if d:
        return {"entry": entry_out(d)}
    if body.item_id:
        it = await db.items.find_one({"id": body.item_id}, {"_id": 0})
        if not it:
            raise HTTPException(404, "Item not found")
    elif body.item:
        it = await find_or_make_item(body.item, user)
    else:
        raise HTTPException(400, "Pick an item")
    if body.pay == "credit" and (not norm(body.supplier) or body.amount <= 0):
        raise HTTPException(400, "Udhaar purchase needs the supplier's name and amount")
    p = await party_for(body.supplier, "supplier")
    e = await _add_entry({"kind": "stock_in", "item_id": it["id"], "item_name": f'{item_name(it)} {("%g" % it["micron"]) + " mic " if it.get("micron") else ""}{it["grade"]}'.strip(),
                          "rolls": body.rolls, "kg": 0, "amount": paise(body.amount), "pay": body.pay,
                          "party_id": p["id"] if p else None, "party_name": p["name"] if p else "",
                          "note": norm(body.note), "op": body.op or None}, user)
    st: Dict[str, Any] = {"updated_at": now()}
    if body.photo and not it.get("photo"):
        st["photo"] = await save_photo(body.photo)
    await db.items.update_one({"id": it["id"]}, {"$inc": {"rolls": body.rolls}, "$set": st})
    return {"entry": entry_out(e), "item": item_out(await db.items.find_one({"id": it["id"]}, {"_id": 0}))}


class PaymentIn(BaseModel):
    party: str = Field(min_length=1, max_length=60)
    kind: str = Field(pattern="^(buyer|supplier)$")
    amount: float = Field(gt=0, le=1000000000)
    mode: str = Field(default="cash", pattern="^(cash|bank|upi|cheque)$")
    note: str = Field(default="", max_length=200)
    op: str = Field(default="", max_length=40)


@api.post("/payments")
async def payment_add(body: PaymentIn, user=Depends(current_user)):
    d = await _dupe(body.op)
    if d:
        return {"entry": entry_out(d)}
    p = await party_for(body.party, body.kind)
    e = await _add_entry({"kind": "payment_in" if body.kind == "buyer" else "payment_out", "amount": paise(body.amount),
                          "mode": body.mode, "party_id": p["id"], "party_name": p["name"], "note": norm(body.note),
                          "op": body.op or None}, user)
    return {"entry": entry_out(e)}


@api.post("/entries/{eid}/undo")
async def entry_undo(eid: str, user=Depends(current_user)):
    e = await db.entries.find_one({"id": eid}, {"_id": 0})
    if not e or e["kind"] == "undo":
        raise HTTPException(404, "Entry not found")
    if user["role"] not in (OWNER, SUPER) and e["by"] != user["id"]:
        raise HTTPException(403, "Only the owner can undo someone else's entry")
    res = await db.entries.update_one({"id": eid, "reversed": False}, {"$set": {"reversed": True, "reversed_at": now(), "reversed_by": user["id"]}})
    if not res.modified_count:
        raise HTTPException(409, "Already undone")
    if e["kind"] == "sale" and e.get("item_id"):
        inc: Dict[str, Any] = {"rolls": e.get("rolls", 0)}
        if e.get("kg", 0) > 0 and e.get("rolls", 0) > 0:
            inc.update({"kg_sold": -e["kg"], "rolls_sold_kg_basis": -e["rolls"]})
        await db.items.update_one({"id": e["item_id"]}, {"$inc": inc, "$set": {"updated_at": now()}})
    elif e["kind"] == "stock_in" and e.get("item_id"):
        await db.items.update_one({"id": e["item_id"]}, {"$inc": {"rolls": -e.get("rolls", 0)}, "$set": {"updated_at": now()}})
    await _add_entry({"kind": "undo", "reverses": eid, "party_id": e.get("party_id"), "party_name": e.get("party_name", ""),
                      "item_id": e.get("item_id"), "item_name": e.get("item_name", ""), "amount": e.get("amount", 0),
                      "note": "Undo of " + e["kind"].replace("_", " ")}, user)
    return {"ok": True}


@api.get("/entries")
async def entries_list(day: str = "", limit: int = 50, user=Depends(current_user)):
    q: Dict[str, Any] = {}
    if day:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise HTTPException(400, "Bad date")
        q["day"] = day
    rows = await db.entries.find(q, {"_id": 0}).sort("at", -1).to_list(max(1, min(limit, 500)))
    return {"entries": [entry_out(e) for e in rows]}


@api.get("/summary")
async def summary(user=Depends(current_user)):
    day = today_ist()
    sold = kg = n = 0
    async for e in db.entries.find({"day": day, "kind": "sale", "reversed": False}, {"_id": 0, "amount": 1, "kg": 1}):
        sold += e["amount"]
        kg += e.get("kg", 0) or 0
        n += 1
    bal = await balances()
    kinds = {p["id"]: p["kind"] async for p in db.parties.find({}, {"_id": 0, "id": 1, "kind": 1})}
    lena = sum(v for k, v in bal.items() if v > 0 and kinds.get(k) == "buyer")
    dena = sum(v for k, v in bal.items() if v > 0 and kinds.get(k) == "supplier")
    buyers = sum(1 for k, v in bal.items() if v > 0 and kinds.get(k) == "buyer")
    sups = sum(1 for k, v in bal.items() if v > 0 and kinds.get(k) == "supplier")
    rolls = 0
    async for it in db.items.find({"rolls": {"$gt": 0}}, {"_id": 0, "rolls": 1}):
        rolls += it["rolls"]
    recent = await db.entries.find({"day": day}, {"_id": 0}).sort("at", -1).to_list(20)
    if user["role"] not in ACCOUNTS:
        lena = dena = buyers = sups = None
    return {"day": day, "sold_today": sold, "kg_today": round(kg, 1), "sales_today": n, "lena": lena, "dena": dena,
            "buyers_owing": buyers, "suppliers_owed": sups, "rolls_in_stock": rolls, "recent": [entry_out(e) for e in recent]}


# ---------------- AI: read a roll photo (Gemini, counted against the shop's AI limit) ----------------
class ReadIn(BaseModel):
    photo: str


@api.post("/ai/read-roll")
async def read_roll(body: ReadIn, user=Depends(current_user)):
    if not GEMINI_KEY:
        raise HTTPException(503, "AI is not switched on yet. Fill the details by hand.")
    raw = _shrink(_decode(body.photo))
    await charge_ai(user, "reads")
    from google import genai
    from google.genai import types
    g = genai.Client(api_key=GEMINI_KEY)
    prompt = ("This is a photo of a plastic packaging film roll (or its label) in an Indian stocklot godown. "
              "Reply ONLY with JSON: {\"film\": one of " + json.dumps(FILMS) + ", \"kind\": short variant like Plain, Metallised, "
              "Printed, Silicone coated, Laminate or empty, \"micron\": number or 0 if not readable, \"grade\": \"A\" if it looks clean and usable, "
              "\"B\" if damaged edges/needs processing, \"C\" if scrap, \"confidence\": \"High|Medium|Low\", \"note\": one short line of anything printed on the label}. "
              "Only read micron from text on the label; never guess it.")
    try:
        r = await g.aio.models.generate_content(
            model=VISION_MODEL, contents=[types.Part.from_bytes(data=raw, mime_type="image/jpeg"), prompt],
            config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=300, response_mime_type="application/json"))
        out = json.loads(re.sub(r"^```(json)?|```$", "", (r.text or "").strip()))
    except Exception:
        log.exception("read-roll failed")
        raise HTTPException(502, "AI could not read this photo. Fill the details by hand.")
    film = out.get("film") if out.get("film") in FILMS else "Other"
    grade = out.get("grade") if out.get("grade") in GRADES else "A"
    try:
        micron = max(0.0, min(2000.0, float(out.get("micron") or 0)))
    except (TypeError, ValueError):
        micron = 0.0
    return {"film": film, "kind": norm(str(out.get("kind") or ""))[:40], "micron": micron, "grade": grade,
            "confidence": out.get("confidence", "Low"), "note": norm(str(out.get("note") or ""))[:120]}


# ---------------- app setup ----------------
@app.middleware("http")
async def headers(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH") and int(request.headers.get("content-length") or 0) > 20 * 1024 * 1024:
        return Response('{"detail":"Too large"}', status_code=413, media_type="application/json")
    resp = await call_next(request)
    path = request.url.path
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["X-Frame-Options"] = "DENY"
    if path.startswith("/api") and not path.startswith("/api/photo/"):
        resp.headers["Cache-Control"] = "no-store"
    elif path in ("/", "/index.html", "/app.js", "/app.css"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


security.bind(db)
app.include_router(api)
app.include_router(security.router)

import sys as _sys  # noqa: E402
import assistant  # noqa: E402
import whatsapp  # noqa: E402
import leads  # noqa: E402
import shopchat  # noqa: E402
assistant.bind(db, _sys.modules[__name__])
whatsapp.bind(db)
leads.bind(db)
shopchat.bind(db, _sys.modules[__name__])
app.include_router(assistant.router)
app.include_router(whatsapp.router)
app.include_router(leads.router)
app.include_router(shopchat.router)

from fastapi.staticfiles import StaticFiles  # noqa: E402
_site = Path(os.environ.get('FRONTEND_DIR', ROOT_DIR.parent / 'frontend'))
if (_site / 'index.html').is_file():
    app.mount("/", StaticFiles(directory=str(_site), html=True), name="site")
_origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', 'https://jmk.sai.markets,https://sai.markets,https://www.sai.markets').split(',') if o.strip() and o.strip() != '*']
app.add_middleware(CORSMiddleware, allow_credentials=False, allow_origins=_origins,
                   allow_methods=["GET", "POST", "PUT", "PATCH"], allow_headers=["Authorization", "Content-Type"])


@app.on_event("startup")
async def startup():
    await security.bootstrap()
    await db.items.create_index("key", unique=True)
    await db.items.create_index("id", unique=True)
    await db.parties.create_index("key", unique=True)
    await db.parties.create_index("id", unique=True)
    await db.entries.create_index("id", unique=True)
    await db.entries.create_index("op", unique=True, partialFilterExpression={"op": {"$type": "string"}})
    await db.entries.create_index([("day", 1), ("kind", 1)])
    await db.entries.create_index("party_id")
    await db.photos.create_index("id", unique=True)
    await db.chat.create_index([("user", 1), ("at", -1)])
    await db.drafts.create_index([("user", 1), ("at", -1)])
    await db.wa_seen.create_index("id", unique=True)
    await db.leads.create_index([("source", 1), ("phone", 1)], unique=True)
    await db.leads.create_index([("source", 1), ("last_at", -1)])
    await db.events.create_index([("site", 1), ("day", -1)])


@app.on_event("shutdown")
async def shutdown():
    client.close()
