# Decisions

Non-obvious choices in Jawab, newest last. The engine's decisions (the brain, the learning call, the
eval) are in [Shop-Assistant's DECISIONS.md](https://github.com/zeinsaid/Shop-Assistant/blob/main/DECISIONS.md);
the hackathon design is in `docs/`. This log starts with The Plug's production deployment (7 Nov 2026).

---

## D-001 — One codebase, two deployments: single-business mode
**Date:** 2026-11-07 · **Status:** Accepted

**Context:** The Plug's website gets its own Jawab, on the shop's own OpenAI key and a database that lasts. The public demo stays as it is. The repo is a public portfolio piece, so nothing may be Plug-only.

**Decision:** An env setting, `JAWAB_MODE=single` with `JAWAB_BUSINESS=<slug>`. In single mode the landing page, `/try`, `/start`, `/demo/*`, `/api/sandbox`, `/api/onboarding*`, `/api/public-stats` and their static files return 404 (a plain page, since the styled one links to the demo). Every business lookup is limited to the one slug, so another row in the database couldn't be reached either. Only that business is seeded, never as a demo (no "Reset demo"). Single mode refuses to start without `DATABASE_URL`, so a real business can't land on a throwaway SQLite file by accident. Production gets its own blueprint file, `render.plug.yaml`.

**Alternatives:** A fork or a branch for The Plug (two codebases drift, and fixes land twice). Hiding the demo routes behind the owner key (still code paths that spend the key). A second blueprint service inside `render.yaml` (Render's blueprint sync would create the production service on the next push, before its secrets are set, and it would start on SQLite).

**Why:** A deployment flag keeps one tested codebase. Blocking by path in one middleware is easy to see and to test, and restricting the lookup closes the gap the path list could miss.

---

## D-002 — Settings are configuration, the knowledge base is data
**Date:** 2026-11-07 · **Status:** Accepted

**Context:** The handoff asks for per-business settings (accent colour, offline message) and the website needs more: a short display name, a contact line, a reply-to address, and switches for alerts and for emailing customers. Saved answers must live in the production database, which is the source of truth for the live KB.

**Decision:** A `settings` JSON column on `businesses` (`app/services/settings.py`, with defaults). A seeded business takes them from its seed in `app/db.py`, and startup **rewrites them every time**: code owns settings. The KB and the conversations are never overwritten at startup: the database owns them. `kb/the-plug.md` is only the first-start seed, and the engine's copy is an eval fixture. Nobody syncs the three (written in the README and CLAUDE.md). `ui_languages` is the one setting that lives in the KB front matter, as the handoff specifies, because it describes the business's languages rather than the product's look.

**Alternatives:** Everything in the KB front matter. Rejected: the front matter goes into every model prompt (tokens and noise), and both deployments share one KB file, so the demo couldn't differ from the shop. Separate DB columns per setting (a migration for each new one).

**Why:** A changed phone number should reach production with a deploy, while an answer the owner saved must survive every deploy. Splitting by "configuration vs data" gives each one the right owner. A JSON column means adding a setting needs no migration (only new tables are created at startup; columns aren't migrated, see D-011).

---

## D-003 — The demo overlay: demo copies never act for real
**Date:** 2026-11-07 · **Status:** Accepted

**Context:** The public demo runs The Plug's real KB, and anyone can open a sandbox where they are the owner.

**Decision:** On the public demo, the seeded Plug and every sandbox get an overlay on top of the real settings: the demo's own offline message ("The demo is offline for a moment…"), no contact line, no reply-to, no alerts, no emails to customers, and all three page languages. The overlay is applied both when seeding and again when settings are read (`demo` or `sandbox_of` set), as a second guard. Where it runs for real, The Plug gets its own suggestion chips per page language (`live_suggestions`). The demo's chips include "My prints came out in the wrong order!", which on the real site would email the shop a pretend complaint.

**Why:** Without it a visitor could type a stranger's address as "their" email, answer the question as the sandbox owner, and make `no-reply@theplug.cy` send that stranger whatever they typed: spam from the shop's domain. Real phone numbers on the demo would send demo visitors to the shop's real phone. The demo keeps its Arabic page toggle because it's the MENA hackathon showcase and the handoff said the demo stays unchanged, while The Plug's site gets only `en, el`.

---

## D-004 — Alert routing on the engine's handoff_reason
**Date:** 2026-11-07 · **Status:** Accepted

**Context:** Engine v1.1.0 labels every handoff `abuse`, `complaint`, `lead` or `other` (Shop-Assistant D-034); the app decides what each triggers.

**Decision:** `ask_owner` emails the owner, `complaint` and `lead` email the shop (subjects `[Jawab – Complaint]` / `[Jawab – Lead]`), and `other` and `abuse` email nobody. Only a **new** escalation sends: an `ask_owner` that only restates a pending question doesn't. The shop's "short summary in English" is the model's own reasoning for the decision, which the engine already writes in English. Abuse gets a new conversation state, `ended`: the bot stays silent from then on, the chat page doesn't claim "a team member will reply", and the escalation is recorded but closed at once. Emails are sent as background tasks after the response, and a failed send is logged, never raised.

**Alternatives:** An extra model call to summarise (costs money on every complaint, for little gain). Abuse as `human_handoff` (the troll would see "a team member will reply here", and the item would sit in the inbox forever). A digest (the handoff says one email per event).

**Why:** The reasoning is already a one-line English explanation of why a person is needed, and it's free. A separate `ended` state is honest to the customer and keeps the owner's inbox clean.

---

## D-005 — The offline fallback, and the 6-hour alert
**Date:** 2026-11-07 · **Status:** Accepted

**Decision:** When `brain.decide` raises (the engine lets provider errors through, D-025 in the engine), the chat returns 503 with `{"offline": true, "detail": <the business's offline message in the customer's language>}`, and the page shows it as a normal bot message. Network errors and other 5xx answers show the same message from the business's settings, which the page already has. The error is classified from the SDK exception, duck-typed with no SDK import: `insufficient_quota` → out of credit, other 429 → rate-limited, 401/403 → key rejected, 5xx/timeout/connection → provider down, else other. The owner is emailed at most once every 6 hours per deployment, and the time of the last alert is kept in a small `app_state` table. The OpenAI client gets a 45 s timeout with one retry (the SDK's default waits up to 10 minutes). The onboarding draft gets 300 s.

**Alternatives:** An in-memory timer (a free server restarts on every wake, so the owner would get an email after every sleep). A scheduled health check (the handoff: the bot only fails when someone uses it, and that first failure sends the alert).

**Why:** Out of credit is the important case: both deployments share one OpenAI balance, so when it runs dry both stop at once, and the subject says so. On the demo the `app_state` row lives in its resetting SQLite, so there the 6 hours restart with the server. That's acceptable: a few extra emails at most, from a demo few people use.

---

## D-006 — The customer's language, without asking the engine
**Date:** 2026-11-07 · **Status:** Accepted

**Context:** The offline message, the contact line and the answer email must be in the customer's language, but the engine's decision has no language field (its replies are simply written in the customer's language).

**Decision:** `detect_language`: Arabic script → `ar`, Greek script → `el`, otherwise the page's language, which the chat sends with each message (`lang`). The result is stored on the conversation on every message.

**Alternatives:** A `language` field in the engine's decision (an engine change, a new tag and an eval rerun, for something a regex settles). Asking the model separately (costs a call).

**Why:** The script is unambiguous for Arabic and Greek. Latin text is English, Greeklish or Arabizi, and the page language the customer chose is the best guess for those.

---

## D-007 — One bubble loader, two ways to deliver it
**Date:** 2026-11-07 · **Status:** Accepted

**Context:** The bubble must appear instantly on theplug.cy even while the free server sleeps, follow the page's language, and hand a message typed during the wake-up to the real chat.

**Decision:** `app/static/jawab.js` replaces `embed.js`. A website hosts its own copy, configured with `data-` attributes. `/embed.js?b=<slug>` serves the same file with that business's settings filled in, so the one-line snippet keeps working. The loader renders the bubble and a local greeting at once and pings `/health` on page load. The real chat is an iframe that loads hidden and takes over when it posts `jawab:ready`. A message typed before that waits up to 60 s, watching **two** signals: the frame saying it's ready, and `/health` answering, which reloads the frame in case it caught Render's "waking up" page. Then the message goes to the chat by `postMessage` (`jawab:send`). The conversation ID is kept in the website's own `localStorage` and passed back as `?c=`. The URL's `?lang=` wins over the chat's stored language.

**Alternatives:** Extend `embed.js` and keep it server-served (it can't render while the server sleeps). The loader calling the chat API itself over CORS (a second chat client to maintain). Relying only on `/health` (if the website's domain were ever missing from the CORS list, a healthy server would look dead forever). Conversation in the iframe's storage only (browsers partition third-party iframe storage, and Safari clears it more readily).

**Why:** One bubble implementation, tested once. The iframe signal makes the loader independent of CORS being right. First-party storage makes "come back later and the answer is waiting" dependable. The greeting is the chat page's own text, and `display_name` is shared, so the hand-over doesn't visibly change anything.

---

## D-008 — "Leave your email": after a question for the owner only
**Date:** 2026-11-07 · **Status:** Accepted

**Decision:** The field appears after an `ask_owner` reply, if the business emails customers. The server accepts an address only for a conversation that has an `ask_owner` escalation, and validates it. When the owner answers, the customer gets a plain-text email in their language: their own question (their words, not the English one sent to the owner), the answer they also see in the chat, the contact line, and Reply-To set to the shop's address. A deliberate "send nothing" from the learning call emails nothing either. The owner sees the address on the inbox card before answering.

**Alternatives:** Also asking for an email after `complaint` and `lead` handoffs. It would help the shop reach those customers, but the shop's alert has already gone by then (a second email per event, or a delayed alert), and the customer is already shown the phone and WhatsApp numbers. Left out to keep this simple. Worth revisiting if leads go unanswered.

**Update (9 Nov 2026):** revisited in D-013: after a complaint or lead the chat can now ask for an email or a WhatsApp number, sent to the shop as a follow-up email.

---

## D-009 — The owner key: asked once per device, never in a link
**Date:** 2026-11-07 · **Status:** Accepted

**Decision:** The inbox page asks for the key and keeps it in that device's `localStorage`. A `?key=` in the URL (the demo's sandbox links) is stored and then removed from the address bar. A wrong key clears it and asks again. Alert emails link to `/owner/<slug>` only.

**Why:** Email is the most likely place for a link to leak (forwarded, synced, previewed). One owner, no time pressure: a key typed once per device is enough, and a real login system isn't worth building for one person.

---

## D-010 — The contact line is shown, not stored
**Date:** 2026-11-07 · **Status:** Accepted

**Decision:** "For anything urgent, call 22 542659 (24/7)…" is added to the chat's view of a reply (`contacts`), in the customer's language, under `ask_owner` and `handoff` replies except `abuse`. It's never written into the stored message text.

**Why:** The stored text is the history the model reads next time. If the contact line were in it, the model would learn to copy phone numbers into its own replies. Kept separate, it changes with the settings, and older chats show the current numbers.

---

## D-011 — Production on Render's free plan, with Neon
**Date:** 2026-11-07 · **Status:** Accepted

**Context:** Render (checked 7 Nov 2026): free web services sleep after 15 idle minutes and take about a minute to wake; 750 free instance hours a month **per workspace, shared by all free services**; when they run out, every free service is suspended until the month ends; SMTP ports are blocked.

**Decision:** Free plan on purpose, in Frankfurt next to the Neon database. Both services sit in one Render project, `Jawab` (environment `Production`): `jawab-demo` (from `render.yaml`) and `jawab-the-plug` (from `render.plug.yaml`, https://jawab-the-plug.onrender.com). One project because they're one product deployed from one repo: every push to `main` redeploys both. A blueprint matches services by name, so a service renamed in the dashboard must be renamed in its blueprint file too, or the next sync creates a duplicate. Email over Resend's HTTPS API. A daily cap of 500 model calls (all visitors together), with OpenAI's hard monthly limit as the backstop. CORS allows `theplug.cy`, `www.theplug.cy` and a Cloudflare Pages pattern for previews. Tables are created at startup, and new **columns** aren't migrated: Neon is new, so today's schema is created whole on the first start. A later column change on Neon needs an `ALTER TABLE` (or Alembic, once there's a second change).

**Risks, accepted:** The website pings `/health` on every page load, so a busy day keeps the shop's service awake longer. Both services draw on the same 750 hours. If the website's traffic ever pushes the total near 750, move The Plug's service to a paid instance (a plan change in `render.plug.yaml`, no code change), which also takes it off the shared pool.

---

## D-012 — Email sender until the domain is verified
**Date:** 2026-11-07 · **Status:** Done (theplug.cy verified; both services send from `no-reply@theplug.cy`, and both blueprints say so since 9 Nov 2026, because a blueprint sync writes the yaml's value over the dashboard's)

**Decision:** Both blueprints send from Resend's test sender (`onboarding@resend.dev`) until theplug.cy is verified in Resend, then switch `JAWAB_EMAIL_FROM` to `The Plug <no-reply@theplug.cy>` (and `Jawab demo <no-reply@theplug.cy>` on the demo). No code change.

**Finding:** Resend's test sender only delivers to the Resend **account's** own address. So `OWNER_ALERT_EMAIL` is set to that address (the owner's Gmail) on both services: owner alerts and the offline alert work now, confirmed with a live test on 7 Nov 2026. Emails to the shop (complaints, leads) and to real customers can only be delivered after the domain is verified and the sender switched.

---

## D-013 — Handoffs a business handles outside Jawab: notify, ask for a contact, copy the owner
**Date:** 2026-11-09 · **Status:** Accepted

**Context:** For The Plug, only the owner uses the inbox (the handoff spec: no staff access), and the manager handles complaints and leads from the shop's email. But a complaint still worked the hackathon way: the chat went into `human_handoff`, so the bot stopped answering that customer, and the item waited in the inbox as pending until someone pressed "Give back to the bot". The shop's email usually said "Customer's email: not given", so the shop couldn't reach the customer either, and the owner wasn't copied. A test complaint on 9 Nov showed all three.

**Decision:** Three per-business settings.
- `handoffs`: `inbox` (default, the old flow: a person replies in the inbox and the bot waits) or `notify`. In `notify`, a non-abuse handoff is recorded with a new escalation status, `notified` (in the inbox's history, nothing to do), the conversation keeps its state so the bot carries on, and a repeat handoff with the same reason in the same chat creates nothing (so a customer venting over five messages emails the shop once). Abuse is unchanged.
- `ask_contact`: after a complaint or lead, the chat offers one field, "email or WhatsApp number". The server decides which it is (an email address, or 7 to 15 digits) and stores it in `customer_email` or the new `customer_phone`. The first one left is emailed to the shop as `Re: <the complaint's subject>`, so it threads under the complaint; a later correction is only stored. It's emailed to the shop, never to the address typed, so it can't be used to spam strangers. Not offered if the customer already left a way to reach them.
- `cc_owner`: the owner is in CC on the shop's complaint and lead emails, and the follow-up.
- Every complaint or lead email has Reply-To set to the customer's email when known, and says so, so staff can press Reply.

The Plug: `notify`, `ask_contact` and `cc_owner` on. The demo keeps `inbox` and both off: a sandbox owner tries the "reply as the team" flow.

**Alternatives:** A staff key for the inbox (a second login to manage, and against the "only me" decision). A "mark as handled" link in the shop's email (a working token in an email link, which D-009 avoids). Delaying the shop's email until the customer leaves a contact (needs a scheduler, and a free server sleeps). Two separate fields for email and phone (one field is simpler for the customer, and the format tells them apart).

**Why:** The email route and the chat behaviour now match how the shop really works: the manager deals with complaints, the owner sees everything as owner and as Jawab's developer, the customer isn't left talking to a silent bot, and the inbox only holds what the owner must act on. As settings, a business whose team does use the inbox keeps the old flow.

---

## D-014 — Startup adds missing nullable columns
**Date:** 2026-11-09 · **Status:** Accepted

**Context:** D-013 adds `conversations.customer_phone`, the first column change since Neon was created. D-011 said a column change needs a manual `ALTER TABLE`; forgetting it would break every chat on deploy.

**Decision:** After `create_all`, `add_missing_columns` compares each existing table with the models and runs `ALTER TABLE … ADD COLUMN` for any model column the table lacks, if it's nullable with no default (old rows get NULL). Anything else (a non-null column, a rename, a type change, a drop) stops startup with an error: that needs a real migration. Idempotent, so it runs on every start.

**Alternatives:** A manual `ALTER TABLE` on Neon before the deploy (easy to forget, and the order matters). Alembic (migration files and a migration step for one added column; worth it once there's a change this can't do).

**Why:** Adding a nullable column is the one schema change that's always safe to do automatically, and it's the common one. It turns "remember to run SQL before you push" into nothing.
