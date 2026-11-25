"""The AI assistant: one engine for the in-app chat and the WhatsApp bot.

How a message is handled (text or voice):
1. Voice -> Gemini writes down exactly what was said.
2. "1" / "2" / "3" / "undo" are handled in code (save / change / cancel / undo last). No AI.
3. Gemini Flash sorts the message: money/stock work, a question, or chit-chat.
4. Money/stock work is read by Claude (best at messy Hinglish); without a Claude key, Gemini reads it.
   Questions are read by Gemini. The AI ONLY pulls out fields (item, rolls, kg, rate, party...).
5. Code finds the item and party, does all the maths, and shows a summary. Nothing is saved until "1".
6. Saving calls the same functions the app's buttons use, so the app, khata and stock update together.
7. When the owner corrects a draft ("2" then the fix), the fix is remembered and shown to the AI next time.
"""
import os
import re
import json
import base64
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, ValidationError

from security import current_user, need, charge_ai, OWNER

router = APIRouter(prefix="/api")
log = logging.getLogger("jmk.ai")
_db = None
S = None  # the server module (handlers + helpers), set by bind()

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FAST_MODEL = os.environ.get("GEMINI_FAST_MODEL", "gemini-2.5-flash")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
DRAFT_MINUTES = 30
MAX_AUDIO = 8 * 1024 * 1024
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_DICTIONARY = """lobhan = yellow LDPE film
udhaar / baaki / credit = credit sale or purchase
nakad / cash / paid = cash
kanta / kaanta / weight = kilos weighed at sale
maal = goods, rolls = reels = bobbin
poly / polyester / PET = Polyester
"""


# Every fixed reply the bot can send, in one place (respectful Hinglish: aap, ji, kijiye).
# The reply book in the project lists these with when each one is sent. Change wording here only.
R = {
    "empty": "Ji, boliye ya likhiye. Jaise: 'Sharma ji ko BOPP 20 micron 250 kg, 95 rate, udhaar'.",
    "help": "Ji, chhota sa likhiye ya boliye: 'Sharma 250kg 95 udhaar' · 'Euro 40 roll BOPP 20 aaya' · 'Gupta 15000 aaye' · 'Sharma baaki?' · 📷 roll photo.\nPoori list ke liye 'help detail' likhiye.",
    "help_detail": ("Namaste ji 🙏 Main JMK ka AI sahayak hoon. Aap mujhe likh kar, bol kar ya photo bhej kar yeh kaam de sakte hain:\n"
             "• Sale: 'Sharma ji ko BOPP 20 micron 250 kg, 95 rate, udhaar'\n"
             "• Maal aaya: 'Euro Films se 40 roll polyester 36 micron aaya, 1.5 lakh udhaar'\n"
             "• Payment: 'Gupta ji ne 15000 diye UPI se'\n"
             "• Sawal: 'Sharma ji ka kitna baaki?', 'BOPP 20 kitna bacha?', 'Aaj ki sale'\n"
             "• Galti: 'undo' (pichhli entry hat jaayegi)\n"
             "• 📷 Roll ki photo: kaunsa maal hai\n"
             "Har entry pehle main dikhata hoon. 1 bhejne par hi save hoti hai."),
    "thanks": "Aapka swagat hai ji 🙏 Aur kuch kaam ho to bataiye.",
    "greet": "Namaste ji 🙏 Bataiye, kya kaam hai? Sale, maal aaya, payment, ya kisi ka baaki poochiye.",
    "labour_need_photo": "Namaste ji 🙏 Roll ki saaf photo bhejiye (label dikhe to aur achha). Main bata dunga kaunsa maal hai.",
    "labour_only": "Maaf kijiye ji, is number se sirf maal pehchaan hoti hai. Sale ya hisaab ke liye " + os.environ.get("OWNER_NAME", "Geetansh").split()[0] + " ji se baat kijiye.",
    "saved_tail": "app mein update ho gaya",
    "cancelled": "Theek hai ji, cancel kar diya. Kuch bhi save nahi hua.",
    "change_what": "Ji, kya badalna hai? Sirf woh bata dijiye, jaise 'rate 92 tha' ya 'party Gupta ji hain'.",
    "no_draft": "Ji, abhi koi entry save hone ke liye pending nahi hai. Nayi entry likhiye ya boliye.",
    "draft_expired": "Ji, pichhli entry 30 minute se zyada purani ho gayi, isliye save nahi ki. Kripya dobara bhejiye.",
    "ai_off": "Maaf kijiye ji, AI abhi chalu nahi hai. Abhi app ke buttons se entry kar lijiye.",
    "ai_busy": "Maaf kijiye ji, AI abhi jawab nahi de pa raha. Thodi der mein dobara bhejiye, ya app ke buttons se entry kar lijiye.",
    "limit": "Maaf kijiye ji, aaj ki AI limit poori ho gayi. App ke buttons se entry chalti rahegi. Sai Markets se limit badhwa sakte hain.",
    "not_understood": "Maaf kijiye ji, yeh samajh nahi aaya. Party ka baaki, maal ka stock, ya aaj ki sale pooch sakte hain. 'help' likhne par poori list milegi.",
    "ask_item_new": "Ji, kaunsa maal? Film, micron aur grade (A/B/C) bata dijiye. Jaise: BOPP 20 micron A grade.",
    "ask_item_pick": "Ji, kaunsa item? {options}",
    "item_missing": "Ji, yeh maal stock mein nahi mila. Pehle 'maal aaya' wali entry kijiye, ya poora naam bataiye (film, micron, grade).",
    "ask_rate": "Ji, {item} ka rate kya tha? (₹ per {unit})",
    "ask_kg": "Ji, kanta weight kitna aaya? (kg mein)",
    "ask_rolls_out": "Ji, kitne roll gaye?",
    "ask_pay": "Ji, cash mila ya udhaar?",
    "ask_credit_party": "Ji, udhaar kis party ko diya? Naam bata dijiye.",
    "ask_rolls_in": "Ji, kitne roll aaye?",
    "ask_supplier": "Ji, udhaar maal hai to supplier ka naam aur total amount bata dijiye.",
    "ask_pay_party": "Ji, payment kis party ki hai?",
    "ask_amount": "Ji, kitne rupaye?",
    "undo_none": "Ji, undo karne ke liye aapki koi entry nahi mili.",
    "undo_done": "↩️ Undo ho gaya ji, stock aur khata pehle jaise",
    "not_saved": "❌ Save nahi hua: {why}",
    "bad_number": "❌ Save nahi hua: koi number sahi nahi lag raha. Kripya dobara bhejiye.",
    "party_due": "{name}: {side} {amount}",
    "party_settled": "{name}: hisaab barabar hai ji ✅",
    "party_missing": "Ji, '{name}' naam ki koi party nahi mili. Spelling check kar lijiye.",
    "today": "Aaj ki sale: {amount} ({n} sale)",
    "dues_none": "Kisi ka kuch baaki nahi hai ji ✅",
    "stock_empty": "Ji, abhi stock khaali dikh raha hai.",
    "voice_off": "Maaf kijiye ji, voice abhi chalu nahi hai. Kripya type karke bhejiye.",
    "voice_empty": "Ji, kuch sunai nahi diya. Kripya dobara boliye, thoda paas se.",
    "voice_long": "Ji, voice note bahut lamba hai. 1 minute se chhota bhejiye.",
    "heard": "🎙️ Maine suna: {text}",
    "photo_off": "Maaf kijiye ji, photo se pehchaan abhi chalu nahi hai.",
    "photo_bad": "Ji, photo saaf samajh nahi aayi. Roll ke label ki paas se, roshni mein photo bhejiye.",
    "unknown_number": "Namaste ji 🙏 Yeh JMK Traders ka private number hai. Hamara stock yahan dekhiye: https://jmk.sai.markets",
    "unsupported": "Ji, abhi main sirf text, voice note aur photo samajh sakta hoon. Kripya inmein se bhejiye.",
    "error": "Maaf kijiye ji, kuch gadbad ho gayi. Kripya dobara bhejiye, ya app se entry kar lijiye.",
    "abuse": "Ji, main samajh sakta hoon aap pareshan hain 🙏 Bataiye kya galat hua, main theek karne ki koshish karta hoon. Galat entry ho to 'undo' likhiye.",
}

DETAIL_RE = re.compile(r"\b(detail|details|poora|pura|puri|poori|report|vistar|sab|sabka|list|full)\b", re.I)


def wants_detail(text: str) -> bool:
    return bool(DETAIL_RE.search(text or ""))


SAVE_WORDS = {"1", "save", "haan", "ha", "han", "yes", "ok", "okay", "theek hai", "thik hai", "sahi hai", "kar do", "kardo", "done"}
CANCEL_WORDS = {"3", "cancel", "nahi", "nahin", "no", "rehne do", "chhodo", "mat karo"}
CHANGE_WORDS = {"2", "change", "badlo", "galat", "galat hai", "edit"}
THANKS_WORDS = {"thanks", "thank you", "thank u", "shukriya", "dhanyavad", "dhanyawad", "thx", "ty"}
HELP_WORDS = {"help", "madad", "kya kar sakte ho", "menu", "?", "options"}
GREET_WORDS = {"hi", "hello", "namaste", "namaskar", "hey", "hii", "ram ram", "jai shri krishna", "good morning", "gm"}


def bind(db, server_module):
    global _db, S
    _db, S = db, server_module


def ai_on() -> bool:
    return bool(GEMINI_KEY or ANTHROPIC_KEY)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rs(paise: int) -> str:
    """Rupees with Indian grouping: 150000 -> Rs 1,50,000."""
    v = round((paise or 0) / 100)
    n = str(abs(v))
    if len(n) > 3:
        n = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", n[:-3]) + "," + n[-3:]
    return ("-₹" if v < 0 else "₹") + n


def _json(text: str) -> Dict[str, Any]:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    m = re.search(r"\{.*\}", t, re.S)
    return json.loads(m.group(0) if m else t)


# ---------------- model calls ----------------
async def gemini(parts: List[Any], max_out: int = 600, as_json: bool = True) -> str:
    if not GEMINI_KEY:
        raise RuntimeError("no gemini key")
    from google import genai
    from google.genai import types
    g = genai.Client(api_key=GEMINI_KEY)
    cfg = types.GenerateContentConfig(temperature=0.1, max_output_tokens=max_out,
                                      response_mime_type="application/json" if as_json else "text/plain")
    r = await g.aio.models.generate_content(model=FAST_MODEL, contents=parts, config=cfg)
    return r.text or ""


async def claude(system: str, user_text: str, max_out: int = 900) -> str:
    if not ANTHROPIC_KEY:
        raise RuntimeError("no claude key")
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.post("https://api.anthropic.com/v1/messages",
                         headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                         json={"model": CLAUDE_MODEL, "max_tokens": max_out, "system": system,
                               "messages": [{"role": "user", "content": user_text}]})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


async def transcribe(audio: bytes, mime: str) -> str:
    from google.genai import types
    txt = await gemini([types.Part.from_bytes(data=audio, mime_type=mime),
                        "Write down exactly what is said in this voice note from an Indian shop owner. Hindi words in Roman letters "
                        "(Hinglish), numbers as digits. Output only the words, nothing else."], max_out=400, as_json=False)
    return re.sub(r"\s+", " ", txt).strip()


# ---------------- context for the AI ----------------
async def dictionary() -> str:
    d = await _db.settings.find_one({"id": "dictionary"}, {"_id": 0, "text": 1})
    return (d or {}).get("text") or DEFAULT_DICTIONARY


async def context_text() -> str:
    items = await _db.items.find({}, {"_id": 0}).sort([("film", 1), ("micron", 1)]).to_list(400)
    parties = await _db.parties.find({}, {"_id": 0, "name": 1, "kind": 1}).to_list(800)
    fixes = await _db.corrections.find({}, {"_id": 0, "said": 1, "right": 1}).sort("at", -1).to_list(15)
    lines = ["ITEMS (id: name · stock):"] + [f'{i["id"]}: {S.item_name(i)} {("%g" % i["micron"]) + " mic" if i.get("micron") else ""} grade {i["grade"]} · {i.get("rolls", 0)} rolls' for i in items]
    lines += ["", "BUYERS: " + ", ".join(p["name"] for p in parties if p["kind"] == "buyer"),
              "SUPPLIERS: " + ", ".join(p["name"] for p in parties if p["kind"] == "supplier"),
              "", "SHOP WORDS:", await dictionary()]
    if fixes:
        lines += ["", "PAST CORRECTIONS (the owner's message -> what was right):"] + [f'"{f["said"]}" -> {json.dumps(f["right"], ensure_ascii=False)}' for f in fixes]
    return "\n".join(lines)


PARSE_RULES = """You read messages from the owner of JMK Traders, a plastic packaging film stocklot godown in Delhi.
Messages are Hindi, Hinglish or English, typed or spoken. Turn the message into JSON. NEVER do maths and never invent numbers:
copy only numbers the owner said. If something needed is missing, ask ONE short question in simple Hinglish.

Reply with JSON only:
{"actions": [ ... ], "question": "" }

Action shapes:
- sale:      {"type":"sale","item_id":"id from ITEMS or null","item_text":"item as said","film":"","kind":"","micron":0,"grade":"A|B|C or empty",
              "rolls":0,"kg":0,"unit":"kg|roll","rate":0,"party":"buyer name","pay":"cash|credit"}
- stock_in:  {"type":"stock_in","item_id":"id or null","item_text":"","film":"BOPP|Polyester|LDPE|CPP|Nylon|Metallised|PVC|HDPE|Other","kind":"","micron":0,"grade":"A|B|C",
              "rolls":0,"supplier":"","amount":0,"pay":"cash|credit"}
- payment:   {"type":"payment","direction":"in|out","party":"","amount":0,"mode":"cash|upi|bank|cheque"}
- undo:      {"type":"undo"}   (undo the last saved entry)
- query:     {"type":"query","what":"party_balance|item_stock|today|stock_list|dues_list","party":"","item_id":"","item_text":""}

Rules:
- unit is "kg" when the rate is per kilo (most sales), "roll" when the rate is per roll/bale/piece.
- "udhaar", "baaki", "credit", "baad mein" = pay "credit". "cash", "nakad", "paid", "de diya" = "cash". If not said for a sale, use "credit" only when a buyer is named and no payment is mentioned; otherwise ask.
- Payment from a buyer = direction "in"; payment to a supplier = "out".
- Pick item_id only when you are sure it is that item (same film, micron and grade). If two items could match, ask which.
- Party names: reuse the exact spelling from BUYERS/SUPPLIERS when it is clearly the same party.
- A message can hold several actions (e.g. two sales). Keep their order.
- Greetings or anything not about the business: {"actions": [], "question": "", "chat": "short reply"}.

How to talk (for "question" and "chat"): always respectful Hinglish, like a polite munim talking to the seth: use "aap", "ji",
"kijiye", "bataiye"; never "tu"/"tum", never slang, never jokes about money.
LENGTH: 1 line normally, at most 3 short lines. Write long only when the owner asks for "detail", "report" or "poora".
- If the owner is angry, rude or swears: stay calm and polite, say sorry once, ask what went wrong, remind that "undo" fixes a wrong entry.
- If asked about taxes, GST filing, law, loans or investments: say politely that you only keep JMK's stock and khata, and to ask their CA.
- If asked for another business's data or anything about Sai Markets' other clients: politely refuse.
- If asked to delete history or change an old entry silently: explain that entries are never deleted; "undo" reverses the last one, and Sai Markets can fix older ones.
- If asked to message or call a buyer/supplier: say you cannot send messages yourself; the app's khata has a "Send reminder" button.
- Personal, political or religious chat: reply in one warm, neutral line and bring it back to work.
- If unsure what they mean: ask ONE short question, never guess money, quantity, party or item.
"""

SORT_PROMPT = """Sort this shop owner's message. Reply JSON only: {"kind": "work"|"question"|"chat"}.
work = recording a sale, purchase/stock coming in, payment received or paid, or undo.
question = asking about dues, stock, today's sales.
chat = anything else. Message: """


async def understand(text: str, previous: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], str]:
    """Returns (parsed JSON, brain used)."""
    kind = "work"
    if GEMINI_KEY and not previous:
        try:
            kind = _json(await gemini([SORT_PROMPT + json.dumps(text, ensure_ascii=False)], max_out=40)).get("kind", "work")
        except Exception:
            kind = "work"
    ctx = await context_text()
    msg = f"{ctx}\n\nTODAY: {datetime.now(IST).strftime('%d %b %Y')}\n\n"
    if previous:
        msg += f"YOUR EARLIER READING: {json.dumps(previous, ensure_ascii=False)}\nTHE OWNER CORRECTS IT: {text}\nReturn the full corrected JSON."
    else:
        msg += f"MESSAGE: {text}"
    if kind == "work" and ANTHROPIC_KEY:
        try:
            return _json(await claude(PARSE_RULES, msg)), "claude"
        except Exception:
            log.exception("claude parse failed, falling back to gemini")
    out = await gemini([PARSE_RULES + "\n\n" + msg], max_out=900)
    return _json(out), "gemini"


# ---------------- turning AI fields into checked actions ----------------
class Need(Exception):
    """Something is missing: ask the owner this question."""


async def _item_for(a: Dict[str, Any], create: bool, user) -> Dict[str, Any]:
    iid = a.get("item_id")
    if iid:
        it = await _db.items.find_one({"id": iid}, {"_id": 0})
        if it:
            return it
    film = (a.get("film") or "").strip()
    if film and (a.get("micron") or 0) and a.get("grade") in ("A", "B", "C"):
        key = S.item_key(film, a.get("kind") or "", float(a["micron"]), a["grade"])
        it = await _db.items.find_one({"key": key}, {"_id": 0})
        if it:
            return it
        if create:
            if film not in S.FILMS:
                film = "Other"
            return await S.find_or_make_item(S.ItemIn(film=film, kind=a.get("kind") or "", micron=float(a["micron"]), grade=a["grade"]), user)
    # close matches to offer
    said = (a.get("item_text") or film or "").lower()
    cands = []
    async for it in _db.items.find({}, {"_id": 0}):
        name = f'{S.item_name(it)} {("%g" % it["micron"]) if it.get("micron") else ""} {it["grade"]}'.lower()
        score = sum(1 for w in re.findall(r"[a-z0-9.]+", said) if w in name)
        if score:
            cands.append((score, it))
    cands.sort(key=lambda x: -x[0])
    if create:
        raise Need(R["ask_item_new"])
    if cands:
        opts = "; ".join(f"{S.item_name(c[1])} {('%g' % c[1]['micron']) + ' mic' if c[1].get('micron') else ''} {c[1]['grade']}" for c in cands[:3])
        raise Need(R["ask_item_pick"].format(options=opts))
    raise Need(R["item_missing"])


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


async def resolve(actions: List[Dict[str, Any]], user) -> List[Dict[str, Any]]:
    """Check every action and work out the numbers in code. Raises Need with a question."""
    out = []
    for a in actions:
        t = a.get("type")
        if t == "sale":
            it = await _item_for(a, create=False, user=user)
            unit = "roll" if a.get("unit") == "roll" else "kg"
            rolls, kg, rate = int(_num(a.get("rolls"))), _num(a.get("kg")), _num(a.get("rate"))
            party = (a.get("party") or "").strip()
            pay = a.get("pay") if a.get("pay") in ("cash", "credit") else ""
            if rate <= 0:
                raise Need(R["ask_rate"].format(item=S.item_name(it), unit="kg" if unit == "kg" else "roll"))
            if unit == "kg" and kg <= 0:
                raise Need(R["ask_kg"])
            if unit == "roll" and rolls <= 0:
                raise Need(R["ask_rolls_out"])
            if not pay:
                raise Need(R["ask_pay"])
            if pay == "credit" and not party:
                raise Need(R["ask_credit_party"])
            qty = kg if unit == "kg" else rolls
            out.append({"type": "sale", "item_id": it["id"], "item_label": S.item_name(it) + (f' {"%g" % it["micron"]} mic' if it.get("micron") else "") + f' {it["grade"]}',
                        "stock_before": it.get("rolls", 0), "rolls": rolls, "kg": kg, "unit": unit, "rate": rate, "party": party, "pay": pay,
                        "amount": S.paise(qty * rate)})
        elif t == "stock_in":
            it = await _item_for(a, create=True, user=user)
            rolls = int(_num(a.get("rolls")))
            if rolls <= 0:
                raise Need(R["ask_rolls_in"])
            pay = a.get("pay") if a.get("pay") in ("cash", "credit") else "cash"
            amount = _num(a.get("amount"))
            sup = (a.get("supplier") or "").strip()
            if pay == "credit" and (not sup or amount <= 0):
                raise Need(R["ask_supplier"])
            out.append({"type": "stock_in", "item_id": it["id"], "item_label": S.item_name(it) + (f' {"%g" % it["micron"]} mic' if it.get("micron") else "") + f' {it["grade"]}',
                        "stock_before": it.get("rolls", 0), "rolls": rolls, "supplier": sup, "amount": S.paise(amount), "pay": pay})
        elif t == "payment":
            party = (a.get("party") or "").strip()
            amount = _num(a.get("amount"))
            if not party:
                raise Need(R["ask_pay_party"])
            if amount <= 0:
                raise Need(R["ask_amount"])
            direction = "out" if a.get("direction") == "out" else "in"
            out.append({"type": "payment", "direction": direction, "party": party, "amount": S.paise(amount),
                        "mode": a.get("mode") if a.get("mode") in ("cash", "upi", "bank", "cheque") else "cash"})
        elif t == "undo":
            last = await _db.entries.find_one({"by": user["id"], "reversed": False, "kind": {"$ne": "undo"}}, {"_id": 0}, sort=[("at", -1)])
            if not last:
                raise Need(R["undo_none"])
            out.append({"type": "undo", "entry_id": last["id"], "label": f'{last["kind"].replace("_", " ")} {last.get("party_name") or ""} {rs(last.get("amount", 0))}'.strip()})
    return out


async def _balance(party: str, kind: str) -> Optional[int]:
    p = await _db.parties.find_one({"key": kind + "|" + S.norm(party).lower()}, {"_id": 0, "id": 1})
    if not p:
        return None
    bal = await S.balances()
    return bal.get(p["id"], 0)


async def preview(acts: List[Dict[str, Any]]) -> str:
    """Short: one line per entry, one line of what changes, then 1/2/3."""
    lines, effects = [], []
    stock: Dict[str, int] = {}
    for a in acts:
        if a["type"] == "sale":
            before = stock.get(a["item_id"], a["stock_before"])
            stock[a["item_id"]] = before - a["rolls"]
            qty = f'{a["kg"]:g} kg' if a["unit"] == "kg" else f'{a["rolls"]} roll'
            lines.append(f'🧾 {a["party"] or "Cash sale"} · {a["item_label"]} · {qty} × ₹{a["rate"]:g} = {rs(a["amount"])} {"udhaar" if a["pay"] == "credit" else "cash"}')
            eff = f'Stock {before}→{stock[a["item_id"]]}' + (" ⚠️" if stock[a["item_id"]] < 0 else "")
            if a["pay"] == "credit":
                b = await _balance(a["party"], "buyer")
                eff += f' · Khata {rs((b or 0) + a["amount"])}' + ("" if b is not None else " (nayi party)")
            effects.append(eff)
        elif a["type"] == "stock_in":
            before = stock.get(a["item_id"], a["stock_before"])
            stock[a["item_id"]] = before + a["rolls"]
            lines.append(f'📦 Maal aaya · {a["item_label"]} · +{a["rolls"]} roll' + (f' · {a["supplier"]}' if a["supplier"] else "")
                         + (f' · {rs(a["amount"])} {"udhaar" if a["pay"] == "credit" else "paid"}' if a["amount"] else ""))
            effects.append(f'Stock {before}→{stock[a["item_id"]]}')
        elif a["type"] == "payment":
            kind = "buyer" if a["direction"] == "in" else "supplier"
            b = await _balance(a["party"], kind)
            lines.append(f'💰 {a["party"]} {"ne diye" if a["direction"] == "in" else "ko diye"} {rs(a["amount"])} · {a["mode"].upper() if a["mode"] == "upi" else a["mode"]}')
            if b is not None:
                effects.append(f'{"Baaki" if kind == "buyer" else "Dena"} {rs(b)}→{rs(b - a["amount"])}')
        elif a["type"] == "undo":
            lines.append(f'↩️ Undo: {a["label"]}')
    if effects:
        lines.append(" · ".join(effects))
    lines.append("1 save · 2 change · 3 cancel")
    return "\n".join(lines)


async def run_actions(acts: List[Dict[str, Any]], user, channel: str, said: str) -> List[str]:
    done = []
    for a in acts:
        op = "ai-" + secrets.token_hex(8)
        try:
            if a["type"] == "sale":
                r = await S.sale_add(S.SaleIn(item_id=a["item_id"], rolls=a["rolls"], kg=a["kg"], unit=a["unit"], rate=a["rate"],
                                              party=a["party"], pay=a["pay"], op=op), user)
            elif a["type"] == "stock_in":
                r = await S.stock_in(S.StockInIn(item_id=a["item_id"], rolls=a["rolls"], supplier=a["supplier"], amount=a["amount"] / 100,
                                                 pay=a["pay"], op=op), user)
            elif a["type"] == "payment":
                r = await S.payment_add(S.PaymentIn(party=a["party"], kind="buyer" if a["direction"] == "in" else "supplier",
                                                    amount=a["amount"] / 100, mode=a["mode"], op=op), user)
            elif a["type"] == "undo":
                await S.entry_undo(a["entry_id"], user)
                done.append(R["undo_done"])
                continue
            eid = r["entry"]["id"]
            await _db.entries.update_one({"id": eid}, {"$set": {"via": channel, "said": said[:500]}})
            done.append("✅ " + {"sale": "Sale", "stock_in": "Maal", "payment": "Payment"}[a["type"]] + (f' {rs(r["entry"]["amount"])}' if r["entry"].get("amount") else "") + " save")
        except HTTPException as e:
            done.append(R["not_saved"].format(why=e.detail))
        except ValidationError:
            done.append(R["bad_number"])
    return done


# ---------------- answers to questions (from the books, never from the AI) ----------------
async def answer(q: Dict[str, Any], detail: bool = False) -> str:
    what = q.get("what")
    if what == "party_balance" and q.get("party"):
        name = S.norm(q["party"])
        for kind in ("buyer", "supplier"):
            b = await _balance(name, kind)
            if b is not None:
                return R["party_due"].format(name=name, side="lena baaki" if kind == "buyer" else "dena baaki", amount=rs(b)) if b else R["party_settled"].format(name=name)
        return R["party_missing"].format(name=name)
    if what == "item_stock":
        try:
            it = await _item_for({"item_id": q.get("item_id"), "item_text": q.get("item_text", "")}, create=False, user=None)
        except Need as n:
            return str(n)
        o = S.item_out(it)
        return f'{o["name"]} {o["micron"]:g} mic {o["grade"]}: {o["rolls"]} roll' + (f' (~{rs(o["est_kg"] * 100)[1:]} kg)' if o.get("est_kg") else "")
    if what == "today":
        day = S.today_ist()
        sold = n = 0
        async for e in _db.entries.find({"day": day, "kind": "sale", "reversed": False}, {"_id": 0, "amount": 1}):
            sold += e["amount"]
            n += 1
        return R["today"].format(amount=rs(sold), n=n)
    if what == "dues_list":
        bal = await S.balances()
        names = {p["id"]: p["name"] async for p in _db.parties.find({"kind": "buyer"}, {"_id": 0, "id": 1, "name": 1})}
        rows = sorted(((v, names[k]) for k, v in bal.items() if k in names and v > 0), reverse=True)
        if not rows:
            return R["dues_none"]
        top = rows if detail else rows[:3]
        more = "" if detail or len(rows) <= 3 else f"\n+{len(rows) - 3} aur · poori list ke liye 'baaki detail'"
        return f"Kul baaki {rs(sum(v for v, _ in rows))}: " + ", ".join(f"{n} {rs(v)}" for v, n in top) + more if not detail else "Sabka baaki:\n" + "\n".join(f"• {n}: {rs(v)}" for v, n in rows)
    if what == "stock_list":
        rows = await _db.items.find({"rolls": {"$gt": 0}}, {"_id": 0}).sort("rolls", -1).to_list(500)
        if not rows:
            return R["stock_empty"]
        lab = lambda i: f'{S.item_name(i)} {("%g" % i["micron"]) if i.get("micron") else ""} {i["grade"]}'.replace("  ", " ")
        if detail:
            return "Poora stock:\n" + "\n".join(f'• {lab(i)}: {i["rolls"]} roll' for i in rows)
        return f'{len(rows)} items, {sum(i["rolls"] for i in rows)} roll. Sabse zyada: ' + ", ".join(f'{lab(i)} ({i["rolls"]})' for i in rows[:3]) + ("\nPoori list: 'stock detail'" if len(rows) > 3 else "")
    return R["not_understood"]


# ---------------- the conversation ----------------
async def log_msg(user, channel: str, who: str, text: str):
    await _db.chat.insert_one({"user": user["id"], "channel": channel, "who": who, "text": text[:4000], "at": now()})


async def open_draft(user) -> Optional[Dict[str, Any]]:
    cut = (datetime.now(timezone.utc) - timedelta(minutes=DRAFT_MINUTES)).isoformat()
    return await _db.drafts.find_one({"user": user["id"], "state": {"$in": ["open", "changing"]}, "at": {"$gt": cut}}, {"_id": 0}, sort=[("at", -1)])


async def handle(user, text: str, channel: str) -> Dict[str, Any]:
    """One message in, one reply out. Used by the app chat and the WhatsApp webhook."""
    text = (text or "").strip()
    if not text:
        return {"reply": R["empty"]}
    await log_msg(user, channel, "owner", text)
    if user.get("role") == "Labour":  # helpers only get material identification, never stock or money
        if await recent_identify(user):
            return await identify(user, channel, note=text)
        reply = R["labour_need_photo"] if not re.search(r"\b(sale|becha|udhaar|payment|diye|baaki|stock)\b", text.lower()) else R["labour_only"]
        await log_msg(user, channel, "bot", reply)
        return {"reply": reply}
    d = await open_draft(user)
    low0 = text.lower()
    if not d and await recent_identify(user) and re.search(r"\b(doob|dub|tair|float|sink|kheench|stretch|phat|tear|awaaz|sound|crackle|naram|soft|dhuan|smell|lau|jal|bujh|mani|boond|detail|burn)", low0):
        return await identify(user, channel, note=text)
    low = text.lower().strip(" .!")
    reply: str
    state = None
    if d and d["state"] == "open" and low in SAVE_WORDS:
        done = await run_actions(d["acts"], user, channel, d["said"])
        await _db.drafts.update_one({"id": d["id"]}, {"$set": {"state": "saved", "saved_at": now()}})
        if d.get("corrected_from"):
            await _db.corrections.insert_one({"said": d["corrected_from"], "right": d["raw"], "at": now(), "by": user["id"]})
        reply, state = ("\n".join(done) + " · " + R["saved_tail"]) if len(done) == 1 else ("\n".join(done) + "\n" + R["saved_tail"]), "saved"
    elif d and low in CANCEL_WORDS:
        await _db.drafts.update_one({"id": d["id"]}, {"$set": {"state": "cancelled"}})
        reply, state = R["cancelled"], "cancelled"
    elif d and d["state"] == "open" and low in CHANGE_WORDS:
        await _db.drafts.update_one({"id": d["id"]}, {"$set": {"state": "changing"}})
        reply, state = R["change_what"], "changing"
    elif low in ("undo", "undo last", "pichla hatao", "pichhli hatao", "galti ho gayi") and not d:
        return await _plan(user, {"actions": [{"type": "undo"}]}, text, channel)
    elif not d and low in SAVE_WORDS | CANCEL_WORDS | CHANGE_WORDS:
        reply = R["draft_expired"] if await _recently_expired(user) else R["no_draft"]
    elif low in THANKS_WORDS or low.startswith(("thank", "shukriya", "dhanyavad", "dhanyawad")):
        reply = R["thanks"]
    elif low in HELP_WORDS:
        reply = R["help"]
    elif low.startswith("help") and wants_detail(low):
        reply = R["help_detail"]
    elif low in GREET_WORDS:
        reply = R["greet"]
    else:
        if not ai_on():
            reply = R["ai_off"]
        else:
            try:
                await charge_ai(user, "commands")
            except HTTPException:
                reply = R["limit"]
                await log_msg(user, channel, "bot", reply)
                return {"reply": reply}
            previous = d["raw"] if d and d["state"] == "changing" else None
            try:
                parsed, brain = await understand(text, previous)
            except Exception:
                log.exception("understand failed")
                reply = R["ai_busy"]
                await log_msg(user, channel, "bot", reply)
                return {"reply": reply}
            if previous:
                await _db.drafts.update_one({"id": d["id"]}, {"$set": {"state": "replaced"}})
            return await _plan(user, parsed, d["said"] if previous else text, channel, corrected_from=d["said"] if previous else None, brain=brain)
    await log_msg(user, channel, "bot", reply)
    return {"reply": reply, "state": state}


async def _recently_expired(user) -> bool:
    lo = (datetime.now(timezone.utc) - timedelta(minutes=DRAFT_MINUTES * 4)).isoformat()
    hi = (datetime.now(timezone.utc) - timedelta(minutes=DRAFT_MINUTES)).isoformat()
    return bool(await _db.drafts.find_one({"user": user["id"], "state": "open", "at": {"$gt": lo, "$lte": hi}}))


async def _plan(user, parsed: Dict[str, Any], said: str, channel: str, corrected_from: Optional[str] = None, brain: str = "") -> Dict[str, Any]:
    acts_raw = [a for a in (parsed.get("actions") or []) if isinstance(a, dict)]
    work = [a for a in acts_raw if a.get("type") != "query"]
    queries = [a for a in acts_raw if a.get("type") == "query"]
    parts = []
    for q in queries:
        parts.append(await answer(q, detail=wants_detail(said)))
    if parsed.get("question") and not work:
        parts.append(parsed["question"])
    if not work:
        reply = "\n".join(parts) or parsed.get("chat") or R["greet"]
        await log_msg(user, channel, "bot", reply)
        return {"reply": reply}
    if parsed.get("question"):
        reply = parsed["question"]
        await log_msg(user, channel, "bot", reply)
        return {"reply": reply}
    try:
        acts = await resolve(work, user)
    except Need as n:
        reply = str(n)
        await log_msg(user, channel, "bot", reply)
        return {"reply": reply, "state": "question"}
    did = "d" + secrets.token_hex(6)
    await _db.drafts.insert_one({"id": did, "user": user["id"], "channel": channel, "said": said, "raw": parsed, "acts": acts,
                                 "state": "open", "at": now(), "brain": brain, "corrected_from": corrected_from})
    reply = "\n".join(parts + [await preview(acts)])
    await log_msg(user, channel, "bot", reply)
    return {"reply": reply, "state": "draft", "draft": did}


# ---------------- identify material from a photo (labour + owner), never burning ----------------
IDENTIFY_RULES = """You help workers in a Delhi plastic film stocklot godown (JMK Traders) guess what film a roll is.
They are not experts and many can barely read, so use very simple, respectful Hinglish ("aap", "ji"), very short lines (under 12 words each), no jargon.
Start with the safe hand checks. When they cannot settle it, also give the traditional burn test, always with the safety line
"Bahar khuli jagah, chhota tukda, chimte se pakdo, dhuan saans mein mat lo, paani paas rakho, stock se door."
Burn test signs (only for small pieces, done outside):
- PE (LDPE/HDPE, lobhan): jalta hai neeli-peeli lau, mombatti/wax jaisi smell, pighal ke boondein girti hain.
- PP / BOPP / CPP: PE jaisa, par smell thodi tez (jaise garam tel/asphalt), lau ke upar halka safed dhuan.
- Polyester (PET): peeli lau, kaala dhuan, meethi si smell, tukda sikud ke kaala mota mani banata hai.
- Nylon: neeli lau jiske kinare peele, baal/naakhun jalne jaisi smell, sakht bhoora mani.
- PVC: mushkil se jalta hai, lau se hatao to bujh jaata hai, hari jhalak, tez khatti smell (yeh dhuan bilkul mat lo).
- Metallised: andar ka base film ki tarah jalta hai, chamakdar parat raakh mein reh jaati hai.
Safe hand checks:
- Paani test: cut a small piece, drop in a bucket of water. Floats = PP/BOPP/CPP/LDPE/HDPE family. Sinks = Polyester (PET), Nylon, PVC.
- Kheench (stretch): LDPE stretches a lot and gets thin. BOPP/Polyester hardly stretch and stay stiff.
- Phaad (tear): BOPP tears easily in a straight line once nicked. Polyester and Nylon are very hard to tear.
- Awaaz (crinkle): BOPP and Polyester crackle sharply. LDPE is soft and quiet.
- Dekho: shiny metal look = Metallised. Milky/soft = LDPE. Crystal clear and stiff = BOPP or Polyester. Yellow soft = lobhan (LDPE).
- Label/core text: read any printed brand, grade, micron (e.g. "20u", "20 mic") or width.
Reply JSON only:
{"guesses":[{"film":"BOPP|Polyester|LDPE|CPP|Nylon|Metallised|PVC|HDPE|Other","kind":"Plain|Printed|Metallised|Silicone coated|Laminate|...","chance":"High|Medium|Low","why":"one short line"}],
 "micron":0, "micron_from_label": false, "grade":"A|B|C", "checks":["2-3 safe hand checks that best separate the top guesses, one short Hinglish line each"],
 "burn":"one line: what the burn test would show for each top guess (with the safety line), or empty if the guess is already clear", "label":"text read from the label or empty"}
Give at most 3 guesses, best first. Only give micron if printed on the label."""


async def identify(user, channel: str, image: bytes = b"", mime: str = "image/jpeg", note: str = "") -> Dict[str, Any]:
    if not GEMINI_KEY:
        return {"reply": R["photo_off"]}
    from google.genai import types
    prev = await _db.identify.find_one({"user": user["id"]}, {"_id": 0}, sort=[("at", -1)])
    parts: List[Any] = []
    reuse = False
    if image:
        parts.append(types.Part.from_bytes(data=image, mime_type=mime))
        ask = IDENTIFY_RULES + "\n\nWorker's note: " + (note or "(none)")
    elif prev and re.fullmatch(r"\s*(detail|details|burn test|burn|poora|pura)\s*", note or "", re.I):
        r = prev["result"]
        reuse = True
    else:
        ask = (IDENTIFY_RULES + "\n\nYOUR EARLIER GUESS: " + json.dumps((prev or {}).get("result", {}), ensure_ascii=False)
               + "\nTHE WORKER DID A CHECK AND SAYS: " + note + "\nUpdate the guesses. If one is now clear, give only that one with chance High.")
    if not reuse:
        parts.append(ask)
        await charge_ai(user, "reads")
        try:
            r = _json(await gemini(parts, max_out=700))
        except Exception:
            log.exception("identify failed")
            return {"reply": R["photo_bad"]}
        await _db.identify.insert_one({"user": user["id"], "at": now(), "result": r, "had_photo": bool(image)})
    g = [x for x in (r.get("guesses") or []) if isinstance(x, dict)][:3]
    sure = {"High": "pakka", "Medium": "shayad", "Low": "pata nahi"}
    lab = r.get("micron") if r.get("micron") and r.get("micron_from_label") else None
    clear = len(g) == 1 and g[0].get("chance") == "High"
    checks = [c for c in (r.get("checks") or []) if isinstance(c, str)]
    detail = wants_detail(note) or "burn" in (note or "").lower() or "jala" in (note or "").lower()
    if not g:
        lines = [R["photo_bad"]]
    elif not detail:
        top = g[0]
        alt = f' ya {g[1].get("film")}' if len(g) > 1 and not clear else ""
        lines = [f'🔍 {top.get("film")} {top.get("kind") or ""}{alt} ({sure.get(top.get("chance"), "shayad")})'.replace("  ", " ") + (f' · {lab:g} mic' if lab else "")]
        if not clear and checks:
            lines.append("Check: " + checks[0])
        if not clear:
            lines.append("Aur check ya 🔥 burn test: 'detail' likhiye")
    else:
        lines = ["🔍 Ji, yeh maal shayad:"]
        for i, x in enumerate(g, 1):
            lines.append(f'{i}. {x.get("film", "?")} {x.get("kind") or ""} ({sure.get(x.get("chance"), "shayad")}) · {x.get("why", "")}'.replace("  ", " "))
        if lab:
            lines.append(f"Label par micron: {lab:g}")
        if r.get("label"):
            lines.append(f'Label: {r["label"]}')
        if checks:
            lines.append("Check kijiye:")
            lines += [f"• {c}" for c in checks[:3]]
        if r.get("burn"):
            lines.append("🔥 Burn test (bahar, chhota tukda, dhuan saans mein nahi): " + str(r["burn"]))
        lines.append("Jo dikha woh bhejiye, jaise 'doob gaya' ya 'kaala dhuan'.")
    if g and detail:
        q: Dict[str, Any] = {"film": g[0].get("film")}
        if lab:
            q["micron"] = float(lab)
        same = await _db.items.find(q, {"_id": 0}).to_list(3)
        if same:
            lines.append("Godown mein aisa maal: " + "; ".join(f'{S.item_name(i)} {("%g" % i["micron"]) + " mic" if i.get("micron") else ""} {i["grade"]} ({i.get("rolls", 0)} roll)' for i in same))
    reply = "\n".join(lines)
    await log_msg(user, channel, "bot", reply)
    return {"reply": reply, "state": "identify"}


async def recent_identify(user) -> bool:
    cut = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    return bool(await _db.identify.find_one({"user": user["id"], "at": {"$gt": cut}}))


# ---------------- app endpoints ----------------
class ChatIn(BaseModel):
    text: str = Field(default="", max_length=2000)
    audio: str = Field(default="", max_length=12_000_000)  # data:audio/wav;base64,...
    image: str = Field(default="", max_length=16_000_000)  # data:image/jpeg;base64,... (identify material)


@router.post("/ai/chat")
async def chat(body: ChatIn, user=Depends(current_user)):
    text = body.text
    if body.image:
        raw = S._shrink(S._decode(body.image))
        await log_msg(user, "app", "owner", "📷 Photo" + (f": {text}" if text else ""))
        return await identify(user, "app", image=raw, note=text)
    if body.audio:
        m = re.match(r"^data:(audio/[a-z0-9.+-]+)(?:;[^,]*)?;base64,(.+)$", body.audio, re.S)
        if not m:
            raise HTTPException(400, "Please send the voice note again")
        raw = base64.b64decode(m.group(2))
        if len(raw) > MAX_AUDIO:
            raise HTTPException(413, R["voice_long"])
        if not GEMINI_KEY:
            raise HTTPException(503, R["voice_off"])
        await charge_ai(user, "commands")
        try:
            text = await transcribe(raw, m.group(1))
        except Exception:
            log.exception("transcribe failed")
            raise HTTPException(502, "Could not hear the voice note. Please try again or type.")
        if not text:
            return {"heard": "", "reply": R["voice_empty"]}
    out = await handle(user, text, "app")
    return {"heard": text if body.audio else "", **out}


@router.get("/ai/chat")
async def chat_history(user=Depends(current_user)):
    rows = await _db.chat.find({"user": user["id"]}, {"_id": 0}).sort("at", -1).to_list(60)
    return {"messages": list(reversed(rows)), "ai_on": ai_on(), "voice_on": bool(GEMINI_KEY)}


class DictIn(BaseModel):
    text: str = Field(max_length=4000)


@router.get("/ai/dictionary")
async def dict_get(user=Depends(need(OWNER))):
    return {"text": await dictionary()}


@router.put("/ai/dictionary")
async def dict_set(body: DictIn, user=Depends(need(OWNER))):
    await _db.settings.update_one({"id": "dictionary"}, {"$set": {"id": "dictionary", "text": body.text}}, upsert=True)
    return {"ok": True}
