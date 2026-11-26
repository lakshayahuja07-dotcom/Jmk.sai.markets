"""Free bill maker leads, shared by sai.markets and jmk.sai.markets.

Every shop that makes a free bill must give its phone number. One record per (source, phone),
so the two sites' customers stay apart: source "sai" = sai.markets, "jmk" = jmk.sai.markets.
Only the Sai Markets super admin sees "sai" leads; the shop owner sees "jmk" leads.
"""
import re
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import security
from security import need, OWNER, SUPER

router = APIRouter(prefix="/api/leads")
_db = None
SOURCES = {"sai": "sai.markets", "jmk": "jmk.sai.markets"}


def bind(db):
    global _db
    _db = db


def clean_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if not re.fullmatch(r"[6-9]\d{9}", d):
        raise HTTPException(422, "Please enter a valid 10-digit mobile number.")
    return d


class BillIn(BaseModel):
    source: Literal["sai", "jmk"]
    shop: str = Field("", max_length=120)
    phone: str = Field(..., max_length=20)
    address: str = Field("", max_length=200)
    gstin: str = Field("", max_length=20)
    doc_type: str = Field("Invoice", max_length=20)
    number: str = Field("", max_length=20)
    total: float = Field(0, ge=0, le=1e10)
    items: int = Field(0, ge=0, le=1000)


@router.post("/bill")
async def bill_made(body: BillIn, request: Request):
    await security.bump("lead:" + security.client_ip(request), 30, "hour")
    phone = clean_phone(body.phone)
    at = datetime.now(timezone.utc).isoformat()
    s = lambda v: re.sub(r"\s+", " ", v or "").strip()  # noqa: E731
    await _db.leads.update_one(
        {"source": body.source, "phone": phone},
        {"$set": {"shop": s(body.shop), "address": s(body.address), "gstin": s(body.gstin).upper(),
                  "last_type": s(body.doc_type), "last_number": s(body.number), "last_total": round(body.total, 2),
                  "last_items": body.items, "last_at": at},
         "$inc": {"bills": 1},
         "$setOnInsert": {"id": "ld" + secrets.token_hex(6), "first_at": at}},
        upsert=True)
    return {"ok": True}


@router.get("")
async def leads_list(source: str = "jmk", user=Depends(need(OWNER))):
    if source not in SOURCES:
        raise HTTPException(422, "Unknown source")
    if source == "sai" and user["role"] != SUPER:
        raise HTTPException(403, "Not allowed")
    rows = await _db.leads.find({"source": source}, {"_id": 0}).sort("last_at", -1).to_list(5000)
    return {"source": source, "site": SOURCES[source], "leads": rows}
