# Research prompt

Paste this into a deep-research AI tool (ChatGPT Deep Research, Gemini Deep Research, Perplexity, Claude) to gather ideas and check the plan in `PLAN.md`.

---

I'm a software developer in India, temporarily also working as a Relationship Manager (RM). I onboard rural shopkeepers as **CSP (Customer Service Point) / Business Correspondent agents for ESAF Small Finance Bank**, through a corporate BC (Aceware Fintech / Radiant Acemoney). Leads speak mostly Hindi, use basic Android phones and WhatsApp, and rarely check email.

**What I've built:** a Python Flask + PostgreSQL app with:
- One permanent bilingual (Hindi/English) onboarding form link. It has 5 steps (mobile → document photos → personal details → shop/income/bank → review), saves every step, and uploads each photo immediately.
- An RM dashboard showing each lead's progress (not opened / opened / filling in / submitted), answers, photos and what's missing.

It will be deployed on my company's Linux server.

**What I plan to add:**
1. New leads from our website pushed into the app by a signed webhook.
2. Instant RM/admin alerts via a Telegram bot.
3. A "zero-UI" operating model: an event log plus background jobs, with a human approval step (one tap) before any message goes to a lead.
4. After a call where the lead is interested: a WhatsApp utility template message plus a professional bilingual HTML email with the form link and document checklist.
5. After the form is submitted: auto-fill the official forms and save them in a versioned folder per agent, then send an encrypted packet to the BC. The forms are an Aggregator Application Form, a Field Verification Report and a Customer Declaration (all flattened scanned PDFs), plus an Agent Banking Agreement (.docx, printed on ₹100 stamp paper).
6. Less typing: decode the Aadhaar Secure QR, IFSC lookup, passbook OCR, and later PAN and bank penny-drop verification.
7. Later: record calls (cloud telephony), transcribe Hindi/Hinglish speech, and use an LLM to extract interest and details. It runs in "suggest" mode, where the RM confirms.

**Please research and give me concrete, current (2026) answers with sources:**
1. How do Indian fintechs and BC networks (e.g. Eko, PayNearby, Spice Money, Fino, NSDL CSP, Bank Mitra) onboard BC agents today? What steps, documents and verification do they use, and what makes their onboarding fast? Anything I'm missing?
2. Is my architecture right for one developer: Flask + Postgres + a Postgres-backed job queue (Procrastinate) + Telegram alerts + an approval queue? What would you change, and what are the failure modes?
3. WhatsApp Business Cloud API in India for this use case: utility template examples that get approved, current per-message price, business verification steps and timelines, BSP vs direct Meta.
4. The best way to send ~100–500 transactional emails/day from India (Amazon SES Mumbai, Zoho ZeptoMail, Resend, Postmark), with SPF/DKIM/DMARC setup. Give me a high-quality open-source MJML email template I can adapt, and tell me how to make Hindi (Devanagari) text render well in Gmail and Outlook.
5. Filling flattened PDF forms in Python with correct Hindi rendering (PyMuPDF `insert_htmlbox` vs ReportLab 4.4 shaping vs HTML-to-PDF). Show a working example for box-per-character fields.
6. Aadhaar Secure QR decoding and signature verification in Python: libraries, the UIDAI certificate, the byte format. Also legal limits on storing Aadhaar images/numbers for a non-regulated company (UIDAI circulars 2025, masking).
7. Hindi/Hinglish speech-to-text for 8 kHz phone calls in 2026 (Sarvam, IndicConformer, ElevenLabs Scribe, Deepgram, Google Chirp): accuracy, price, data residency. Also: Exotel/Ozonetel click-to-call with recording webhooks and pricing.
8. Compliance checklist for this flow under India's DPDP Act 2023 and DPDP Rules 2025, RBI BC guidelines, and TRAI TCCCPR (calls and WhatsApp). What must be done now, and what by May 2027?
9. UX for low-literacy rural users on mobile forms: what reduces drop-off (voice instructions, Hindi-first, photo guides, fewer fields, save and resume, WhatsApp reminders)? Any studies or case studies from India?
10. Anything else a small team in this position usually gets wrong.

Format: one section per question. Give a clear recommendation first, then reasoning, then source links with dates. Say plainly when something is uncertain or when sources disagree.
