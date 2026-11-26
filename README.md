# JMK Traders app

Stock, sales and khata for JMK Traders (plastic film stocklots, Alipur). Built by Sai Markets on the Festive Buddy core
(same PIN logins, payment lock and AI limits). Live at https://jmk.sai.markets.

- `/` public stock page: stock with photos, rolls and estimated kg. No prices. Buyers ask on WhatsApp.
- `/#/login` staff sign in (Geetansh). Five taps on the logo shows the Sai Markets card.
- Owner screens: Home, Record a sale (rate per kg or per roll), Add stock (pooled items: film + type + micron + grade),
  Khata (buyers lena, suppliers dena), Payment in/out, Stock items. Every entry can be undone; nothing is deleted.

AI employee (`#/ai` in the app, and the WhatsApp bot): type, speak or send a roll photo. Sales, stock in, payments,
undo and questions ("Sharma ka kitna baaki?"). Nothing is saved until the owner replies 1. Code does all maths; the AI
only reads fields (Claude for money/stock, Gemini for voice, sorting, questions and material identification).
Godown workers' WhatsApp numbers can only ask what material a roll is (safe checks, never burning).
WhatsApp webhook: `/api/wa/webhook` (off until WA_* settings are filled).

Customer AI chat box (`frontend/chatbox.js`, also used on sai.markets): a bar at the top of the public pages.
Customers ask it to make a bill (fills the free bill maker) or build an order (cart, sent on WhatsApp to the shop).
Server side: `backend/shopchat.py`, `/api/public/chat`, Gemini 2.5 Flash when GEMINI_API_KEY is set, else Claude Haiku. Visitors: 15 messages an hour, 40 a day, and a
shared daily cap (`PUBLIC_CHAT_DAILY_USD`, default 0.14, about Rs 400 a month). Signed-in owner/super admin: no cap.
Usage (chats, AI bills, carts, WhatsApp orders, bill PDFs) is in `events`; see it at More > Free bill leads.
Switch the box off with `PUBLIC_CHAT=off`.

Hosting: Render (Docker, free plan), data in MongoDB Atlas database `jmk`. Settings: `backend/env.example`.

Tests: `cd backend && python -m pytest tests` (needs `pip install mongomock-motor httpx pytest`).
