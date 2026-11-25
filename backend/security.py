"""Server-side login, roles, AI limits and payment lock for JMK Traders (Sai Markets core, from Festive Buddy).

Rules this file enforces (never trust the phone):
- PINs live only here, scrambled with scrypt + a secret pepper. The website never sees a PIN.
- Login returns a signed pass (token) that says who you are and your role. Every write needs it.
- Roles: SUPER (Sai Markets, Lakshay) > OWNER (shop owner) > SALESMAN.
- Shop identity (name, address, phone) can only be changed by SUPER.
- Every AI call is counted per person (staff) or per phone (customers) per day.
"""
import os
import hmac
import json
import time
import base64
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Request, Depends, Body
from pydantic import BaseModel, Field

SUPER, OWNER, SALESMAN = "Sai Markets Super Admin", "Owner", "Salesman"
LABOUR = "Labour"  # WhatsApp-only helper: can ask the bot to identify material, nothing else. Has no PIN, so can never sign in to the app.
RANK = {SALESMAN: 1, OWNER: 2, SUPER: 3}
TOKEN_HOURS = 24 * 7  # stay signed in for a week; the owner can end a pass at once by switching someone off or changing their PIN
MAX_FAILS, LOCK_MINUTES = 5, 15

router = APIRouter(prefix="/api")
_db = None


def _secret(name: str, min_len: int = 32) -> bytes:
    v = os.environ.get(name, "")
    if len(v) < min_len:
        raise RuntimeError(f"{name} must be set (at least {min_len} characters)")
    return v.encode()


def bind(db):
    global _db
    _db = db
    _secret("AUTH_SECRET")
    _secret("PIN_PEPPER", 16)


# ---------------- PINs ----------------
def hash_pin(pin: str, salt: Optional[bytes] = None) -> Dict[str, str]:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(pin.encode() + _secret("PIN_PEPPER", 16), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return {"salt": base64.b64encode(salt).decode(), "hash": base64.b64encode(h).decode()}


def check_pin(pin: str, rec: Dict[str, Any]) -> bool:
    try:
        want = hash_pin(pin, base64.b64decode(rec["pin_salt"]))["hash"]
        return hmac.compare_digest(want, rec["pin_hash"])
    except Exception:
        return False


def valid_pin(pin: str) -> bool:
    return isinstance(pin, str) and pin.isdigit() and len(pin) in (4, 6)


# ---------------- signed pass (token) ----------------
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(staff: Dict[str, Any]) -> str:
    body = _b64(json.dumps({"sub": staff["id"], "role": staff["role"], "ver": staff.get("ver", 0),
                            "exp": int(time.time()) + TOKEN_HOURS * 3600}).encode())
    sig = _b64(hmac.new(_secret("AUTH_SECRET"), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(tok: str) -> Optional[Dict[str, Any]]:
    try:
        body, sig = tok.split(".", 1)
        want = _b64(hmac.new(_secret("AUTH_SECRET"), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(want, sig):
            return None
        data = json.loads(_unb64(body))
        return data if data.get("exp", 0) > time.time() else None
    except Exception:
        return None


# ---------------- payment lock (licence per client) ----------------
CLIENT_ID = os.environ.get("CLIENT_ID", "jmk")
_IST = timezone(timedelta(hours=5, minutes=30))
_lic = {"t": 0.0, "row": None}


async def license_row(fresh: bool = False):
    if not fresh and time.time() - _lic["t"] < 20:
        return _lic["row"]
    row = await _db.licenses.find_one({"client_id": CLIENT_ID}, {"_id": 0})
    _lic.update(t=time.time(), row=row)
    return row


def license_state(row) -> Dict[str, Any]:
    """ok | warn | locked. No row, or an unreadable date, never locks by accident."""
    if not row:
        return {"state": "ok", "days_left": None}
    try:
        days_left = (datetime.strptime(row["paid_until"], "%Y-%m-%d").date() - datetime.now(_IST).date()).days
    except Exception:
        return {"state": "ok", "days_left": None}
    if row.get("status") == "suspended":
        return {"state": "locked", "days_left": days_left}
    if days_left >= 0:
        return {"state": "ok", "days_left": days_left}
    return {"state": "warn" if -days_left <= int(row.get("grace_days", 7)) else "locked", "days_left": days_left}


async def is_super(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    data = read_token(auth[7:].strip()) if auth.lower().startswith("bearer ") else None
    if not data:
        return False
    staff = await _db.staff.find_one({"id": data["sub"], "active": True}, {"_id": 0, "role": 1, "ver": 1})
    return bool(staff) and staff.get("role") == SUPER and staff.get("ver", 0) == data.get("ver", 0)


async def locked_now() -> bool:
    return license_state(await license_row())["state"] == "locked"


async def optional_user(request: Request) -> Optional[Dict[str, Any]]:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    data = read_token(auth[7:].strip())
    if not data:
        return None
    staff = await _db.staff.find_one({"id": data["sub"], "active": True}, {"_id": 0, "pin_hash": 0, "pin_salt": 0})
    # a PIN change, role change or switch-off bumps "ver", which ends old passes at once
    if not staff or staff.get("ver", 0) != data.get("ver", 0):
        return None
    # payment lock: when the licence is locked, everyone except Sai Markets is treated as a customer (reads stay open, writes fail)
    if staff.get("role") != SUPER and await locked_now():
        request.state.locked = True
        return None
    return staff


async def current_user(request: Request, user=Depends(optional_user)) -> Dict[str, Any]:
    if not user:
        if getattr(request.state, "locked", False):
            raise HTTPException(403, "LOCKED")
        raise HTTPException(401, "Please sign in again")
    return user


def need(role: str):
    async def dep(user=Depends(current_user)):
        if RANK.get(user["role"], 0) < RANK[role]:
            raise HTTPException(403, "Not allowed")
        return user
    return dep


def client_ip(request: Request) -> str:
    # behind a proxy (Namecheap / nginx) the real address is the first X-Forwarded-For entry
    xff = request.headers.get("x-forwarded-for", "")
    return (xff.split(",")[0].strip() if xff else "") or (request.client.host if request.client else "unknown")


# ---------------- simple counters (rate limits + AI limits) ----------------
async def bump(key: str, limit: Optional[int], window: str = "day", by: int = 1) -> int:
    """Add `by` to `key` in this window (day, hour or month). Raises 429 when `limit` is passed. limit=None means no limit."""
    ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    period = {"day": ist.strftime("%Y-%m-%d"), "hour": ist.strftime("%Y-%m-%dT%H"), "month": ist.strftime("%Y-%m")}[window]
    doc = await _db.usage.find_one_and_update({"key": key, "period": period}, {"$inc": {"n": by}},
                                              upsert=True, return_document=True)
    n = doc["n"] if doc else by
    if limit is not None and n > limit:
        if by:
            await _db.usage.update_one({"key": key, "period": period}, {"$inc": {"n": -by}})  # refused calls don't count
        raise HTTPException(429, "Today's limit is used up. Please try again tomorrow.")
    return n


# ---------------- AI budget, tied to what the shop pays ----------------
# Edit these on the server (.env), no code change needed:
#   PLAN_PRICE_INR     what the shop pays Sai Markets per month (default 25000)
#   AI_BUDGET_PERCENT  share of that price the shop's AI may cost per month (default 6 -> Rs 1,500)
#   AI_LIMITS          per-person daily counts (JSON), see DEFAULT_LIMITS
# reads = one product photo, catalogues = one catalogue/PDF upload (up to 6 files),
# illustrations = AI-drawn picture (only for products with no photo), cutouts = background removal (free, runs on our server)
DEFAULT_LIMITS = {
    SALESMAN: {"reads": 20, "catalogues": 2, "cutouts": 60, "illustrations": 1, "commands": 150},
    OWNER: {"reads": 40, "catalogues": 5, "cutouts": 120, "illustrations": 3, "commands": 300},
    SUPER: {"reads": None, "catalogues": None, "cutouts": None, "illustrations": None, "commands": None},  # first setup: no limit
    "customer_match_per_phone": 2,
    "customer_match_per_ip": 6,
}
# Estimated cost of one use in paise (Gemini 2.5 Flash ~$0.30/$2.50 per 1M tokens, image ~$0.04), with headroom.
# commands = one chat/voice instruction to the AI assistant (Gemini sorts it, Claude reads money/stock ones)
COST_PAISE = {"reads": 50, "catalogues": 300, "illustrations": 350, "match": 30, "cutouts": 350, "commands": 60}


def limits() -> Dict[str, Any]:
    try:
        return {**DEFAULT_LIMITS, **json.loads(os.environ.get("AI_LIMITS", "{}"))}
    except Exception:
        return DEFAULT_LIMITS


def budget_paise() -> Dict[str, int]:
    try:
        plan = float(os.environ.get("PLAN_PRICE_INR", "25000"))
        pct = float(os.environ.get("AI_BUDGET_PERCENT", "6"))
    except ValueError:
        plan, pct = 25000.0, 6.0
    month = int(plan * 100 * pct / 100)
    # a busy day may use up to 3x an average day, so festival rushes still work
    return {"plan": int(plan * 100), "month": month, "day": int(month / 30 * 3)}


async def spend(kind: str, setup: bool = False):
    """Add the estimated cost to the shop's AI spend. Stops at the daily and monthly budget.
    The super admin's first catalogue setup is tracked separately and never blocked."""
    cost = COST_PAISE.get(kind, 0)
    if not cost:
        return
    if setup:
        await bump("spend:setup", None, "month", by=cost)
        return
    if kind in ("cutouts", "illustrations"):  # paid pictures are limited by the monthly photo quota (packs the shop pays for), not by the shared AI budget
        await bump("spend:photos", None, "month", by=cost)
        return
    b = budget_paise()
    try:
        await bump("spend:shop", b["month"], "month", by=cost)
    except HTTPException:
        raise HTTPException(429, "This month's AI allowance is used up. Please contact Sai Markets.")
    try:
        await bump("spend:shop", b["day"], "day", by=cost)
    except HTTPException:
        await _db.usage.update_one({"key": "spend:shop", "period": (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m")},
                                   {"$inc": {"n": -cost}})
        raise HTTPException(429, "Today's AI allowance is used up. Please try again tomorrow.")


async def in_grace() -> bool:
    """First-setup grace: for GRACE_DAYS (default 7) from the first AI use after this was added, nobody is capped,
    so the shop can load its whole product list. Spend is still tracked (as setup spend) so Sai Markets can see it."""
    try:
        days = int(os.environ.get("GRACE_DAYS", "7"))
    except ValueError:
        days = 7
    d = await _db.settings.find_one({"id": "setup-grace"})
    if not d:
        d = {"id": "setup-grace", "until": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()}
        await _db.settings.update_one({"id": "setup-grace"}, {"$setOnInsert": d}, upsert=True)
        d = await _db.settings.find_one({"id": "setup-grace"})
    return datetime.now(timezone.utc).isoformat() < d["until"]


async def charge_ai(user: Dict[str, Any], kind: str):
    """Count one AI use for a staff member (daily count per person + shop budget). SUPER is never limited.
    AI_UNLIMITED=1 on the server: no daily or monthly cap at all for this shop (uses are still logged for Sai Markets)."""
    if os.environ.get("AI_UNLIMITED") == "1":
        await bump(f"ai:{kind}:{user['id']}", None)
        await bump("spend:unlimited", None, "month", by=COST_PAISE.get(kind, 0))
        await _db.ai_log.insert_one({"by": user["id"], "kind": kind, "at": datetime.now(timezone.utc).isoformat()})
        return
    # grace covers reading/text work only; paid picture work (cutouts, upscaling, AI pictures) is never uncapped
    pic = kind in ("cutouts", "illustrations")
    grace = await in_grace()
    lim = limits().get(user["role"], {}).get(kind)
    if grace and not pic:
        lim = None
    elif grace and pic and user["role"] != SUPER:  # during setup: AI pictures are 3 a day for the whole shop, all staff together
        await bump("ai:pics:shop", 3)
    await bump(f"ai:{kind}:{user['id']}", lim)
    await spend(kind, setup=user["role"] == SUPER or (grace and not pic))
    await _db.ai_log.insert_one({"by": user["id"], "kind": kind, "at": datetime.now(timezone.utc).isoformat()})


async def charge_customer_match(request: Request):
    device = (request.headers.get("x-device-id") or "")[:64]
    if len(device) < 16:
        raise HTTPException(400, "Please reload the page and try again")
    L = limits()
    await bump(f"match:dev:{device}", L.get("customer_match_per_phone", 2))
    await bump(f"match:ip:{client_ip(request)}", L.get("customer_match_per_ip", 6))
    await spend("match")


# ---------------- first start ----------------
async def bootstrap():
    """Create the Sai Markets super admin (and the owner) the first time, from one-time server settings."""
    await _db.staff.create_index("id", unique=True)
    await _db.usage.create_index([("key", 1), ("period", 1)], unique=True)
    await _db.licenses.create_index("client_id", unique=True)
    if not await _db.licenses.find_one({"client_id": CLIENT_ID}):  # first start: 30 days paid, 7 days grace
        await _db.licenses.insert_one({"client_id": CLIENT_ID, "status": "active", "grace_days": 7, "override_note": "first start",
                                       "paid_until": (datetime.now(_IST).date() + timedelta(days=30)).isoformat(),
                                       "updated_at": datetime.now(timezone.utc).isoformat()})
    if await _db.staff.count_documents({}) == 0:
        first = [("lakshay", "Lakshay Ahuja", SUPER, "A", True, os.environ.get("SUPER_ADMIN_PIN", "")),
                 (os.environ.get("OWNER_ID", "geetansh"), os.environ.get("OWNER_NAME", "Geetansh Ahuja"), OWNER, "B", False, os.environ.get("OWNER_PIN", ""))]
        for sid, name, role, series, secret, pin in first:
            if not valid_pin(pin):
                if role == SUPER:
                    raise RuntimeError("SUPER_ADMIN_PIN must be set (4 or 6 digits) for the first start")
                continue
            h = hash_pin(pin)
            await _db.staff.insert_one({"id": sid, "name": name, "role": role, "series": series, "secret": secret,
                                        "active": True, "ver": 0, "pin_hash": h["hash"], "pin_salt": h["salt"],
                                        "fails": 0, "locked_until": 0})


# ---------------- login ----------------
GHOST_ID = "ghost"  # sign-in id of the hidden super admin's card (its real id is never sent to the login screen)


class LoginIn(BaseModel):
    staff_id: str = Field(max_length=40)
    pin: str = Field(max_length=6)


@router.get("/staff/public")
async def staff_public():
    """Names and roles for the sign-in cards. Never PINs, and never the hidden super admin (it signs in as "ghost")."""
    rows = await _db.staff.find({"active": True, "secret": {"$ne": True}, "role": {"$ne": LABOUR}}, {"_id": 0, "id": 1, "name": 1, "role": 1, "series": 1}).to_list(100)
    return {"staff": rows}


@router.post("/auth/login")
async def login(body: LoginIn, request: Request):
    await bump(f"login:ip:{client_ip(request)}", 30, window="hour")
    if body.staff_id == GHOST_ID:  # the plain extra card after 5 taps: only the right PIN links it to the hidden super admin
        rec = await _db.staff.find_one({"role": SUPER, "secret": True, "active": True})
    else:
        rec = await _db.staff.find_one({"id": body.staff_id, "active": True})
    now = time.time()
    if not rec:
        raise HTTPException(401, "Wrong PIN")
    if rec.get("locked_until", 0) > now:
        raise HTTPException(429, "Too many wrong PINs. Try again in 15 minutes.")
    if not check_pin(body.pin, rec):
        fails = rec.get("fails", 0) + 1
        upd = {"fails": fails}
        if fails >= MAX_FAILS:
            upd = {"fails": 0, "locked_until": now + LOCK_MINUTES * 60}
        await _db.staff.update_one({"id": rec["id"]}, {"$set": upd})
        raise HTTPException(401, "Wrong PIN")
    await _db.staff.update_one({"id": rec["id"]}, {"$set": {"fails": 0, "locked_until": 0}})
    if rec.get("role") != SUPER and await locked_now():
        raise HTTPException(403, "LOCKED")
    me = {k: rec.get(k) for k in ("id", "name", "role", "series", "secret", "lang")}
    return {"token": make_token(rec), "me": me}


@router.get("/auth/me")
async def who_am_i(user=Depends(current_user)):
    return {"me": {k: user.get(k) for k in ("id", "name", "role", "series", "secret", "lang")}}


# ---------------- team (owner adds / switches off salesmen) ----------------
class StaffIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    pin: str


class StaffPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=40)
    wa_phone: Optional[str] = Field(default=None, pattern=r"^\d{0,13}$")  # WhatsApp number that may talk to the bot as this person
    lang: Optional[str] = Field(default=None, pattern="^(en|hi)$")  # bot reply language: en = simple English, hi = Hinglish
    pin: Optional[str] = None
    active: Optional[bool] = None


@router.get("/staff")
async def staff_list(user=Depends(need(OWNER))):
    q = {} if user["role"] == SUPER else {"role": {"$ne": SUPER}}
    rows = await _db.staff.find(q, {"_id": 0, "pin_hash": 0, "pin_salt": 0, "fails": 0, "locked_until": 0, "ver": 0}).to_list(200)
    return {"staff": rows}


@router.post("/staff")
async def staff_add(body: StaffIn, user=Depends(need(OWNER))):
    if not valid_pin(body.pin):
        raise HTTPException(400, "PIN must be 4 or 6 digits")
    used = {s["series"] for s in await _db.staff.find({}, {"series": 1}).to_list(200)}
    series = next((chr(65 + i) for i in range(26) if chr(65 + i) not in used), None)
    if not series:
        raise HTTPException(400, "Team is full")
    h = hash_pin(body.pin)
    doc = {"id": "s" + secrets.token_hex(5), "name": body.name.strip(), "role": SALESMAN, "series": series, "secret": False,
           "active": True, "ver": 0, "pin_hash": h["hash"], "pin_salt": h["salt"], "fails": 0, "locked_until": 0}
    await _db.staff.insert_one(dict(doc))
    return {"staff": {k: doc[k] for k in ("id", "name", "role", "series", "active")}}


class HelperIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    wa_phone: str = Field(pattern=r"^\d{10,13}$")


@router.post("/staff/helper")
async def helper_add(body: HelperIn, user=Depends(need(OWNER))):
    """Owner adds a godown worker's WhatsApp number. That number can only ask the bot what material a roll is."""
    phone = body.wa_phone[-10:]
    if await _db.staff.find_one({"wa_phone": {"$in": [body.wa_phone, phone]}, "active": True}):
        raise HTTPException(409, "This number is already linked")
    doc = {"id": "h" + secrets.token_hex(5), "name": body.name.strip(), "role": LABOUR, "series": "-", "secret": False,
           "active": True, "ver": 0, "wa_phone": phone, "fails": 0, "locked_until": 0}
    await _db.staff.insert_one(dict(doc))
    return {"staff": {k: doc[k] for k in ("id", "name", "role", "active", "wa_phone")}}


@router.patch("/staff/{sid}")
async def staff_edit(sid: str, body: StaffPatch, user=Depends(need(OWNER))):
    rec = await _db.staff.find_one({"id": sid})
    if not rec:
        raise HTTPException(404, "Not found")
    if rec["role"] == SUPER and user["role"] != SUPER:
        raise HTTPException(403, "Not allowed")
    if rec["role"] == OWNER and user["role"] != SUPER and rec["id"] != user["id"]:
        raise HTTPException(403, "Not allowed")
    upd: Dict[str, Any] = {}
    if body.name is not None and body.name.strip():
        upd["name"] = body.name.strip()
    if body.lang is not None:
        upd["lang"] = body.lang
    if body.wa_phone is not None:
        if user["role"] != SUPER:
            raise HTTPException(403, "Only Sai Markets can link a WhatsApp number")
        upd["wa_phone"] = body.wa_phone
    if body.pin is not None:
        if not valid_pin(body.pin):
            raise HTTPException(400, "PIN must be 4 or 6 digits")
        h = hash_pin(body.pin)
        upd.update({"pin_hash": h["hash"], "pin_salt": h["salt"], "fails": 0, "locked_until": 0})
    if body.active is not None:
        if rec["role"] not in (SALESMAN, LABOUR) and not body.active:
            raise HTTPException(400, "The owner profile cannot be switched off")
        upd["active"] = body.active
    if not upd:
        return {"ok": True}
    inc = {"ver": 1} if ("pin_hash" in upd or "active" in upd) else {}
    await _db.staff.update_one({"id": sid}, {"$set": upd, **({"$inc": inc} if inc else {})})
    return {"ok": True}


# ---------------- AI usage report ----------------
@router.get("/ai/usage")
async def ai_usage(user=Depends(need(OWNER))):
    """This month's estimated AI cost against the budget. Owner sees the shop; super admin also sees setup spend."""
    ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    async def n(key, period):
        d = await _db.usage.find_one({"key": key, "period": period})
        return d["n"] if d else 0
    b = budget_paise()
    out = {"month_spent_paise": await n("spend:shop", ist.strftime("%Y-%m")), "month_budget_paise": b["month"],
           "today_spent_paise": await n("spend:shop", ist.strftime("%Y-%m-%d")), "today_budget_paise": b["day"]}
    if user["role"] == SUPER:
        out.update({"plan_paise": b["plan"], "setup_spent_paise": await n("spend:setup", ist.strftime("%Y-%m"))})
    return out


# ---------------- licence endpoints ----------------
@router.get("/license")
async def license_public():
    """Public: only the state, so the staff screen can show a banner or the pause screen. Never blocks customers."""
    st = license_state(await license_row())
    return {"state": st["state"], "days_left": st["days_left"], "contact_wa": os.environ.get("SAI_WA", "")}


class LicenseIn(BaseModel):
    status: str = Field(pattern="^(active|suspended)$")
    paid_until: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    grace_days: int = Field(ge=0, le=60)
    override_note: str = Field(default="", max_length=200)


@router.get("/admin/licenses")
async def licenses_list(user=Depends(need(SUPER))):
    rows = await _db.licenses.find({}, {"_id": 0}).to_list(200)
    log = await _db.license_log.find({}, {"_id": 0}).sort("at", -1).to_list(30)
    return {"licenses": [{**r, **license_state(r)} for r in rows], "log": log, "this_client": CLIENT_ID}


@router.put("/admin/licenses/{client_id}")
async def licenses_set(client_id: str, body: LicenseIn, user=Depends(need(SUPER))):
    import re
    if not re.fullmatch(r"[a-z0-9-]{2,40}", client_id):
        raise HTTPException(400, "Client id: small letters, numbers and dashes only")
    try:
        datetime.strptime(body.paid_until, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Date must be YYYY-MM-DD")
    now = datetime.now(timezone.utc).isoformat()
    before = await _db.licenses.find_one({"client_id": client_id}, {"_id": 0})
    new = {**body.model_dump(), "client_id": client_id, "updated_at": now}
    await _db.licenses.update_one({"client_id": client_id}, {"$set": new}, upsert=True)
    await _db.license_log.insert_one({"client_id": client_id, "by": user["id"], "at": now, "before": before, "after": new})
    _lic["t"] = 0.0
    return {"ok": True}
