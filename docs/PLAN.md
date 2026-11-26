# ESAF CSP Onboarding Automation: Plan

*Drafted 25 Nov 2026. Covers lead intake through to a filled KYC packet, run by one developer acting as RM.*
*Database design: [ARCHITECTURE.md](ARCHITECTURE.md) · Security design: [SECURITY.md](SECURITY.md)*

---

## 1. Goal

Make onboarding fast for **leads** (rural shopkeepers becoming ESAF CSP agents) and nearly hands-off for **the RM**:

> A lead comes in → the RM gets an alert and calls them → after one tap ("Interested"), the lead receives a bilingual WhatsApp + email with the form link → the lead fills the form on their phone → the system fills every official document, files it neatly, and tells the RM it's ready → the RM reviews and sends the packet to Aceware.

Humans make two decisions in this flow: **whether a lead is interested** and **whether a packet is ready to send**. The system does everything else, and records each step.

---

## 2. Review of the original plan

| Your idea | Verdict | Change |
|---|---|---|
| Pull website leads into the dashboard via API key | ✅ Right idea | Ask the website team for a **signed webhook** (push) instead of polling with an API key. Keep a nightly API check as a safety net. |
| "Zero-UI" dashboard | ✅ Right idea, needs a clear definition | Zero-UI = **the system acts, then notifies; you approve with one tap** (on Telegram or the dashboard). The dashboard is for oversight, not data entry. See §4. |
| Alert the admin on new leads | ✅ Yes, do it | **Telegram bot.** Free, instant, supports Approve/Reject buttons. Add a daily email digest as a record. |
| Gmail automation after the call | ⚠️ Change the channel | Rural leads read **WhatsApp**, not email. Make WhatsApp the main channel and email the detailed record. Send email through a transactional service (Amazon SES Mumbai or Zoho ZeptoMail) on a company subdomain, **not** a personal Gmail. |
| Speech-to-text decides "interested" and auto-sends | ⚠️ Don't wait for it, and don't auto-send at first | Build the **"Interested" button now**. When STT arrives, it *suggests* that tap and you confirm. A misheard "dekhte hain" must not trigger a message. Allow full auto-send only for high-confidence cases once you have data. |
| Professional bilingual email UI | ✅ | MJML template, Hindi as live text (never inside images), a bulletproof button, and a documents checklist. Draft copy in §7. |
| Auto-fill official documents into proper folders | ✅ | PyMuPDF writes text onto the original PDFs (Hindi renders correctly). docxtpl fills the agreement. Use a fixed folder layout with no personal data in file names (§8). |
| **Missing from the plan** | ❗ | Compliance sign-off for Aadhaar data, consent capture, retention and backups, and **which brand the messages come from** (Eko? Aceware? ESAF?) (§10). |

---

## 3. What already exists (in `csp-onboarding-agent/`)

- **Postgres schema** (`db/schema.sql`): leads, forms (one row per form session), documents, mismatches, declarations, calls, transcripts, extractions, email logs, agent actions, and an automatic status history.
- **One permanent form link** `/apply`: 5 steps, Hindi + English. It saves progress on every step, uploads each photo the moment it's picked, resumes where the lead left off, and refuses submission until everything is filled.
- **RM dashboard** `/dashboard`, password-protected:
  - the shareable link, plus WhatsApp share buttons
  - add a lead to track
  - per lead: Not opened → Opened → Filling in (step X/5) → Submitted
  - answers and photos filled so far, what's still missing, photo thumbnails, mismatch flags, and a history timeline
- **Runs on:** the developer's laptop. **Not yet:** the company server, HTTPS, alerts, outbound messages, document filling, call pipeline.

---

## 4. Target architecture

```
                         ┌──────────────── Company Linux server (India) ─────────────────┐
 Website apply page ──webhook──▶ /webhooks/leads ─┐                                        │
 Lead's phone ──https──▶ /apply (form) ───────────┤                                        │
 Exotel (call recording) ─webhook─▶ /webhooks/calls┤──▶ PostgreSQL ◀── Job worker (Procrastinate)
 RM ──https──▶ /dashboard ────────────────────────┘     events table        │  STT (Sarvam)
                                                         pending approvals   │  LLM extraction
                                                         leads, forms, docs  │  PDF/DOCX filling
                                                                             │  WhatsApp / Email send
 RM's phone ◀── Telegram bot (alerts + Approve/Reject buttons) ◀─────────────┘
                         └─────────────────────────────────────────────────────────────────┘
```

**Event-driven setup:**
- Everything that happens writes a row to an append-only **`events`** table, e.g. `lead.received`, `lead.marked_interested`, `form.opened`, `form.submitted`, `docs.generated`, `message.sent`.
- Each event can queue background jobs.
- The dashboard is a view over these tables.

**Risk tiers:**

| Tier | Examples | Behaviour |
|---|---|---|
| Safe, internal | Alert the RM, generate PDFs, decode Aadhaar QR, look up IFSC | **Automatic** |
| Reaches an outsider | WhatsApp/email to a lead, packet to Aceware | Creates a **pending approval**. The RM taps Approve/Edit/Reject on Telegram or the dashboard. It expires if ignored. Who approved, and when, is recorded. |

Once a message template has a clean track record (e.g. 4 weeks with no RM edits), that template can be switched to auto-approve.

**Stack choices:**
- Flask + Postgres, which we already have.
- **gunicorn + nginx + HTTPS** in production.
- **Procrastinate** as the job queue: Postgres-backed, so no Redis to run. A job is queued in the same database transaction that creates the lead, retries are built in, and periodic tasks work. PgQueuer is the alternative.
- No n8n for now. Logic stays in Python, in git.

---

## 5. Phases

Each phase can be used on its own. Estimates assume one developer who is also doing RM calls.

### Phase 0: Approvals and decisions (this week, before more building)
- [ ] Manager/compliance okay to collect Aadhaar, PAN and bank data, and confirmation of where it may be stored. Our company is probably a **data processor** for ESAF/Aceware, so we may need a data processing agreement (DPA).
- [ ] **Brand to use in messages.** The agreement is between **Aceware Fintech (Radiant Acemoney)** and the agent, not Eko. Confirm what the email/WhatsApp should say and which logo to use.
- [ ] Does ESAF/Aceware need the **full Aadhaar number** on their forms, or is a masked one (last 4 digits) acceptable?
- [ ] Get a company server, a subdomain (e.g. `csp.<company>.in`), and an email sending subdomain (e.g. `onboarding.<company>.in`).
- [ ] Call script: add a recording/contact **consent line** in Hindi at the start of every call, and log the "haan".

### Phase 1: Go live on the company server (~3–4 days)
- gunicorn + nginx + HTTPS (Let's Encrypt or the company certificate). The form link becomes `https://csp.<company>.in/apply`, and shop-photo location starts working, since phones only share location over HTTPS.
- Run the app and worker as systemd services. Daily Postgres backup plus backup of the uploads folder, encrypted at rest.
- Mask the first 8 Aadhaar digits on stored images, or ask leads to upload masked Aadhaar. Never store the full Aadhaar number anywhere.
- Access log of who viewed which lead's documents, kept at least 1 year.
- Store secrets in the server's environment, never in git.

### Phase 2: Events, job queue, Telegram alerts (~3 days)
- Tables: `events`, `pending_actions`.
- Procrastinate worker.
- Telegram bot alerts:
  - new lead
  - a lead opened the form
  - form submitted
  - a lead stuck for over 48h at the same step
  - daily 9 am summary
- Dashboard: an **"Needs your approval"** box at the top, plus an event timeline.

### Phase 3: Leads from the website (~2 days + website team's time)
- `POST /webhooks/leads`:
  - HMAC-SHA256 signature check (Standard Webhooks headers)
  - reject requests older than 5 minutes
  - a stored `webhook-id` for idempotency
  - fast 200 response, with processing done in a background job
- **Ask the website team for:**
  - payload fields: name, mobile, pincode/village, shop type, consent flag, source/UTM
  - a stable lead ID
  - a shared secret, plus a way to rotate it
  - their retry policy
  - a sandbox
  - a "leads since X" API, for a nightly reconciliation check
- New lead → `lead.received` → Telegram alert with a **Call** button (a `tel:` link).

### Phase 4: "Interested" → WhatsApp + email (~1 week, plus Meta approval wait)
- The dashboard and Telegram get a **Mark interested** button. It creates a pending approval with the drafted messages; you approve and they send.
- **WhatsApp Business Cloud API:** a *utility* template carrying the form link, about ₹0.12/message plus GST (check Meta's current India rate card). Needs Meta business verification and template approval, so **start this in Phase 0**, since approval takes time.
- **Email:** Amazon SES (Mumbai) or Zoho ZeptoMail, sent from `onboarding.<company>.in` with SPF/DKIM/DMARC set up. MJML template, a plain-text part, and a List-Unsubscribe header. *Until then, Gmail API from a company account (2,000 mails/day limit) works as a stopgap.*
- Follow-ups, also through approvals: a reminder 24h after sending if the form wasn't opened, and a nudge 48h after a lead stalls.

### Phase 5: Documents auto-filled and filed (~1–1.5 weeks)
- **Aggregator Application Form, Field Verification Report, Declaration:**
  - Use **PyMuPDF** to write onto the *original* PDFs, so the output is still the official form.
  - Map each form's field coordinates once, in YAML.
  - Box-per-character fields (DOB, PAN, IFSC, PIN) get one character per box.
  - Hindi goes through `insert_htmlbox` with Noto Sans Devanagari, which shapes conjuncts correctly. Test with श्री, क्षेत्र, जन्म.
- **Agent Banking Agreement:** docxtpl placeholders in the original .docx, then LibreOffice headless → PDF, laid out for ₹100 stamp paper.
- **Declaration** is generated only when there's a mismatch (address, name, DOB, father's name).
- **FVR** needs the RM's field-visit answers. Add a mobile-friendly **Field visit** page per lead: footfall, distance to nearest ESAF branch, competition, recommendation, etc.
- **Name-match warning** before the packet is built: fuzzy-compare names (and DOB) across Aadhaar, PAN and bank account. Mismatched names are the most common reason BCs reject applications.
- **Pre-flight check** before "Approve & send": every required file exists, isn't empty, opens as a valid image/PDF and is readable. This avoids days of back-and-forth with Aceware.
- **Stamp-paper layout:** page 1 of the agreement leaves the top ~4 inches blank for the ₹100 e-stamp header. The margin is configurable, and you can preview it before printing.
- **Coordinates live in versioned YAML files per form version, never in code.** Keep a script that fills a dummy record so you can check it by eye whenever the bank changes a form.
- Output goes to the folder layout in §8 with a `manifest.json`, then a Telegram alert "Packet ready for <lead>". You review and approve, and it goes to Aceware as an **encrypted zip or expiring download link**, not a plain attachment.

### Phase 5b: After approval, agent requirements (~3 days)
Track these as milestones per agent (`agent_requirements`):
- IIBF BC certificate
- police verification certificate
- shop proof
- biometric device registered
- stamped agreement received
- training

Each has a due date and a reminder. **Confirm with ESAF/Aceware which of these apply and the grace periods.**

### Phase 6: Less typing for the lead (~1 week)
- **Aadhaar Secure QR** (back of the card): decode name, DOB, gender, address (including Hindi), photo and last 4 digits, all signed by UIDAI. Prefill the form from it, and verify the signature with UIDAI's certificate.
- **IFSC:** self-hosted Razorpay IFSC dataset. Shows bank and branch as the lead types. **Pincode → district/state** lookup the same way.
- **Form UX for low-literacy users:**
  - Hindi by default, with an English toggle.
  - A 🔊 "सुनें" button on each step playing a short pre-recorded Hindi instruction.
  - A "good photo vs blurry/cut-off photo" example above each document upload.
  - Photos compressed on the phone before upload.
  - Ask nominee details and highest education.
  - Unbundled consent checkbox on step 1.
- **WhatsApp progress nudges:** "आपका फॉर्म 60% पूरा, बस बैंक पासबुक की फोटो बाकी है". These recover the most half-filled forms.
- **Passbook OCR fallback:** PaddleOCR (Devanagari) for name and account number. The lead confirms the values.
- Later, through a KYC aggregator (Setu/Cashfree/Digio): PAN verification and bank penny-drop (Setu publishes ~₹3 per verification). DigiLocker needs partner onboarding, so go through an aggregator or ESAF.

### Phase 7: Calls → transcripts → suggestions (~1.5 weeks, once STT is available)
- **Recording:** Exotel click-to-call. Android apps can't reliably record calls any more.
  - Use `Record=true` and `RecordingChannels=dual`, so the RM and the lead are on separate audio channels. That gives much better speech-to-text.
  - The status webhook brings a **time-limited** `RecordingUrl`. A background job downloads and encrypts the recording straight away.
  - Exotel's entry plan is about ₹9,999 + GST (verify).
- **STT:**
  - Primary: **Sarvam Saaras**. Best tested accuracy on Indian telephone Hindi (~5% WER), processing stays in India, about ₹35/hour with speaker separation.
  - Fallback: self-hosted IndicConformer.
  - Test on 20–30 real calls before committing.
- **LLM extraction** to JSON: `interest` (yes/no/maybe), `confidence`, `evidence_quote`, `consent_to_contact`, name, shop details, `follow_up_date`.
- **Suggest mode for the first 2–4 weeks:** the system pre-fills "Mark interested" and you confirm. Log every time you override it. Later, auto-send only when the lead clearly asked for details, confidence is ≥ 0.85 and consent is logged.
- Retention: delete audio after 30–90 days and keep the transcript/fields. Confirm with ESAF.

---

## 6. Database additions

| Table | Purpose |
|---|---|
| `events` (id, lead_id, type, payload jsonb, created_at) | Append-only log that drives jobs and the timeline |
| `pending_actions` (id, lead_id, kind, draft jsonb, status, decided_by, decided_at, expires_at) | Messages and packets waiting for approval |
| `messages` (id, lead_id, channel whatsapp/email, template, status, provider_id, sent_at) | Replaces `email_logs`; one log for both channels |
| `webhook_deliveries` (webhook_id unique, source, received_at) | Webhook idempotency |
| `consents` (lead_id, kind recording/contact/data, given_at, method, evidence) | DPDP consent record |
| `field_visits` (lead_id, answers jsonb, visited_at, recommendation) | FVR inputs |
| `generated_documents` (exists) + version + sha256 | Points at the current version of each document |

---

## 7. Draft messages

**WhatsApp (utility template, after "Interested"):**
> नमस्ते {{name}} जी 🙏
> ESAF Small Finance Bank के CSP एजेंट बनने में आपकी रुचि के लिए धन्यवाद।
> अपने दस्तावेज़ अपलोड करने के लिए यह फॉर्म भरें (10 मिनट): {{link}}
> मदद के लिए कॉल करें: {{rm_phone}} – {{rm_name}}

**Email**
- **Subject:** `{{name}} जी, ESAF CSP एजेंट ऑनबोर्डिंग – अगला कदम | Your next step to become an ESAF CSP agent`
- **Layout** (600px, single column, Hindi then English in each block):
  1. Header: {{brand}} logo + "ESAF Small Finance Bank – CSP Onboarding"
  2. **नमस्ते {{name}} जी / Namaste {{name}} ji**: thanks for your interest in becoming a Customer Service Point (CSP) agent.
  3. **3 steps:** ① Fill the form (10 min) ② We verify & visit your shop ③ Sign the agreement & start earning
  4. Big red button **फॉर्म भरें / Fill the form** + the link as text
  5. **Keep ready:** Aadhaar (front & back), PAN, bank passbook/cheque, 12th marksheet, passport photo, ₹1,999 payment receipt, a photo at your shop
  6. Earnings teaser: commission on every AEPS, Micro ATM, money transfer, recharge and bill payment (link to the commission sheet)
  7. RM name, phone, WhatsApp
  8. Footer: legal entity and address, why they got this email, opt-out line

*Never call them a "lead" in messages. Use "CSP agent", "partner" or their name.* The **brand line** depends on the Phase 0 decision.

---

## 8. Folder and file layout on the server

```
/data/kyc/2026/11/<LEAD_ID>/
  inputs/            aadhaar_front.jpg  aadhaar_back.jpg  pan.jpg  bank_proof.jpg
                     education_cert.jpg  photo.jpg  payment_receipt.jpg  shop_photo.jpg
  generated/v1/      <LEAD_ID>_aggregator_form_v1.pdf   <LEAD_ID>_fvr_v1.pdf
                     <LEAD_ID>_declaration_v1.pdf       <LEAD_ID>_agreement_v1.pdf (+ .docx)
  packet/            <LEAD_ID>_ESAF_KYC_packet_v1_20261125.zip   (AES-256 encrypted)
  manifest.json      sha256 of every file, template versions, generated_by, timestamps
```
- No names, Aadhaar, PAN or account numbers in any path.
- Never overwrite: a correction creates `v2`, and the database points at the current version.

---

## 9. Costs (approximate, monthly, at a few hundred leads)

| Item | Cost |
|---|---|
| Company server | existing |
| Telegram alerts | free |
| Email (SES / ZeptoMail) | < ₹500 |
| WhatsApp utility messages | ~₹0.12–0.15 each + GST + provider fee |
| STT (Sarvam, with diarization) | ~₹35 per hour of calls |
| Exotel | plan + per-minute; get a quote |
| Penny-drop / PAN verification | ~₹3 per check (aggregator quote) |

---

## 10. Risks and open questions

1. **Compliance:** the DPDP Rules 2025 phase in by about May 2027. Build consent, encryption, access logs and deletion now. Get ESAF/Aceware's retention policy in writing.
2. **Brand / legal entity on messages:** Eko vs Aceware vs ESAF. Don't send anything to leads until this is settled.
3. **Full Aadhaar on official forms:** if required, it must be handled per UIDAI rules and never stored in plain form.
4. **Call recording consent:** get a legal opinion on whether one-party consent is enough. Use cloud telephony with a DLT-registered number (TRAI).
5. **WhatsApp template approval delays:** apply early.
6. **One person is RM and developer at once:** phases are ordered so that each one saves RM time before the next starts.

---

## 11. External research cross-check (26 Nov 2026)

Two outside deep-research reports were checked against our own research. **Adopted:**
- Agent-requirement milestones (IIBF certificate, police verification).
- Nominee and education fields.
- Name fuzzy-match.
- Packet pre-flight check.
- Stamp-paper margin.
- Form coordinates kept in versioned YAML.
- Browser-side photo compression.
- Low-literacy UX: audio, photo guides, Hindi first.
- WhatsApp progress nudges.
- Exotel dual-channel recording.
- **Meta Cloud API directly** (no BSP subscription or markup).
- The 72-hour DPDP breach report.
- Telegram double-tap protection: check the approval status in one database transaction and remove the buttons after the tap.
- An alert when background jobs are stuck for more than 15 minutes.

**Corrected or not adopted:**

| Claim in a report | Our position |
|---|---|
| WhatsApp templates must be DLT-registered | **No.** DLT (TRAI) applies to SMS and telecom voice, not WhatsApp. Meta's own opt-in and template rules govern WhatsApp. |
| ElevenLabs Scribe can't transcribe Hindi | **Wrong.** An independent 2026 telephone benchmark measured Scribe v2 at 7.7% Hindi WER. It's our fallback option. |
| Use the Aadhaar QR "reference ID" hash to detect duplicates | **Doesn't work.** The reference ID includes a timestamp and changes between prints. We use a hash of name + DOB + last 4 instead. |
| `pyaadhaar` verifies signatures | It's unmaintained (last release 2023). Write our own ~60-line parser plus signature check against UIDAI's certificate. |
| "RBI mandates data localisation" for this data | RBI's localisation directive is about **payment system** data. We keep everything in India anyway, but get ESAF's storage requirement in writing rather than relying on that claim. |
| DMARC `p=quarantine` from day one | Start at `p=none` with reports. Move to `quarantine` once the reports show only legitimate mail. |
| Specific prices (Sarvam ₹0.45/min, Exotel ₹9,999, ZeptoMail INR) | Reports disagree slightly. **Get live quotes before budgeting.** |

---

## 12. Recommended order

**Phase 0 → 1 → 2 → 4 → 5 → 5b → 3 → 6 → 7**

Go live first, then alerts, then outreach and documents, since these save the most RM time. Website intake depends on another team, so ask for it in Phase 0 and build it whenever their webhook is ready. The call pipeline comes last, when the STT API arrives.
