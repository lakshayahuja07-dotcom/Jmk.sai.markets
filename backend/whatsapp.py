"""WhatsApp bot (official WhatsApp Cloud API). Uses the same assistant as the in-app chat.

Switched OFF until these are set on the server (Render > Environment):
  WA_TOKEN          permanent access token (Meta Business > System user)
  WA_PHONE_ID       the bot number's "Phone number ID"
  WA_VERIFY_TOKEN   any long random text; paste the same text in Meta's webhook settings
  WA_APP_SECRET     the Meta app's secret, used to check every message really comes from WhatsApp

Only numbers linked to a login (Sai Markets super admin sets "WhatsApp number" on Geetansh's login) can use the bot.
Anyone else gets one polite line and nothing is saved.
"""
import os
import hmac
import json
import hashlib
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, BackgroundTasks

import assistant

router = APIRouter(prefix="/api/wa")
log = logging.getLogger("jmk.wa")
_db = None
GRAPH = "https://graph.facebook.com/v21.0"


def bind(db):
    global _db
    _db = db


def cfg(k: str) -> str:
    return os.environ.get(k, "")


def wa_on() -> bool:
    return all(cfg(k) for k in ("WA_TOKEN", "WA_PHONE_ID", "WA_VERIFY_TOKEN", "WA_APP_SECRET"))


async def send_text(to: str, text: str):
    if not wa_on():
        return
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{GRAPH}/{cfg('WA_PHONE_ID')}/messages", headers={"Authorization": "Bearer " + cfg("WA_TOKEN")},
                         json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4000]}})
        if r.status_code >= 300:
            log.warning("wa send failed %s %s", r.status_code, r.text[:300])


async def fetch_media(media_id: str, max_bytes: int = 0):
    async with httpx.AsyncClient(timeout=30) as c:
        h = {"Authorization": "Bearer " + cfg("WA_TOKEN")}
        meta = (await c.get(f"{GRAPH}/{media_id}", headers=h)).json()
        if int(meta.get("file_size") or 0) > (max_bytes or assistant.MAX_AUDIO):
            raise ValueError("too large")
        r = await c.get(meta["url"], headers=h)
        r.raise_for_status()
        return r.content, (meta.get("mime_type") or "audio/ogg").split(";")[0]


@router.get("/webhook")
async def verify(request: Request):
    q = request.query_params
    if wa_on() and q.get("hub.mode") == "subscribe" and hmac.compare_digest(q.get("hub.verify_token", ""), cfg("WA_VERIFY_TOKEN")):
        return Response(q.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403, "Not allowed")


def signed(body: bytes, header: str) -> bool:
    want = "sha256=" + hmac.new(cfg("WA_APP_SECRET").encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header or "")


@router.post("/webhook")
async def receive(request: Request, bg: BackgroundTasks):
    if not wa_on():
        raise HTTPException(404, "Not found")
    body = await request.body()
    if not signed(body, request.headers.get("x-hub-signature-256", "")):
        raise HTTPException(403, "Bad signature")
    try:
        data = json.loads(body)
    except ValueError:
        return {"ok": True}
    for entry in data.get("entry", []):
        for ch in entry.get("changes", []):
            for m in (ch.get("value") or {}).get("messages", []) or []:
                bg.add_task(process, m)
    return {"ok": True}  # answer WhatsApp at once; the work happens right after


async def process(m: dict):
    mid = m.get("id", "")
    if mid:  # WhatsApp may deliver the same message twice
        try:
            await _db.wa_seen.insert_one({"id": mid, "at": datetime.now(timezone.utc).isoformat()})
        except Exception:
            return
    sender = "".join(ch for ch in m.get("from", "") if ch.isdigit())
    user = await _db.staff.find_one({"wa_phone": {"$in": [sender, sender[-10:]]}, "active": True}, {"_id": 0, "pin_hash": 0, "pin_salt": 0})
    if not user:
        await send_text(sender, assistant.R["unknown_number"])
        return
    try:
        kind = m.get("type")
        if kind == "text":
            text = (m.get("text") or {}).get("body", "")
        elif kind in ("audio", "voice"):
            if not assistant.GEMINI_KEY:
                await send_text(sender, assistant.R["voice_off"])
                return
            raw, mime = await fetch_media((m.get(kind) or {}).get("id", ""))
            text = await assistant.transcribe(raw, mime)
            if not text:
                await send_text(sender, assistant.R["voice_empty"])
                return
            if text:
                await send_text(sender, assistant.R["heard"].format(text=text))
        elif kind == "image":
            raw, mime = await fetch_media((m.get("image") or {}).get("id", ""), max_bytes=15 * 1024 * 1024)
            caption = (m.get("image") or {}).get("caption", "")
            await assistant.log_msg(user, "whatsapp", "owner", "📷 Photo" + (f": {caption}" if caption else ""))
            out = await assistant.identify(user, "whatsapp", image=raw, mime=mime, note=caption)
            await send_text(sender, out["reply"])
            return
        elif kind == "interactive":
            it = m.get("interactive") or {}
            text = (it.get("button_reply") or it.get("list_reply") or {}).get("id", "")
        else:
            await send_text(sender, assistant.R["unsupported"])
            return
        out = await assistant.handle(user, text, "whatsapp")
        await send_text(sender, out["reply"])
    except Exception:
        log.exception("wa process failed")
        await send_text(sender, assistant.R["error"])


@router.get("/status")
async def status():
    return {"on": wa_on()}
