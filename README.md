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

Hosting: Render (Docker, free plan), data in MongoDB Atlas database `jmk`. Settings: `backend/env.example`.

Tests: `cd backend && python -m pytest tests` (needs `pip install mongomock-motor httpx pytest`).
