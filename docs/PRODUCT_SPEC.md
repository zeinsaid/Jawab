# Jawab: product spec

> **Historical note.** Written on 30 Oct 2026 as the brief for the hackathon build (with Replit Agent, on Replit). Kept as the design record. Since then: the app runs on Render with SQLite or any Postgres instead of Replit PostgreSQL, the engine (`brain/`, `onboarding/`, prompts) is installed from [Shop-Assistant](https://github.com/zeinsaid/Shop-Assistant) instead of copied, and visitors get a private sandbox at `/try`. See the README for the current state.

The source of truth for what we build today. `replit.md` has the short version and the rules.

---

## 1. What it is

An AI receptionist that any small business can put on its website (and later WhatsApp). It answers customers in English and Arabic **only from the business's knowledge base (KB)**, and every answer must cite the KB. When it doesn't know, it asks the owner, relays the owner's answer to the customer, and offers to save that answer to the KB, so the same question never reaches the owner twice.

Three kinds of user:

| User | What they do | Where |
|---|---|---|
| Customer | Chats with the business | `/b/{slug}` (full page) |
| Owner | Answers questions the bot couldn't, takes over handoffs, approves what the bot learns, edits the KB | `/owner/{slug}?key=...` |
| New business | Signs up, pastes their info or does a short interview, gets their own bot | `/start` |

The first business is **The Plug** (slug `the-plug`), seeded from `kb/the-plug.md`.

---

## 2. What we reuse (don't rewrite)

From `reference/shop-assistant/` (my earlier, proven project). Copy these into the new app, unchanged unless this spec says otherwise:

| Reference file | Becomes | Notes |
|---|---|---|
| `brain/schema.py` | `brain/schema.py` | Unchanged. `IncomingMessage`, `Turn`, `BrainDecision`, `Action`. |
| `brain/kb.py` | `brain/kb.py` | Unchanged. `parse_kb()` validates every KB before it's saved. |
| `brain/llm.py` | `brain/llm.py` | One change: `OpenAIClient` takes `api_key` and `base_url` and passes them to `openai.OpenAI(...)`. `make_client()` reads them from the Replit AI Integrations env vars when present. Drop the Anthropic and Gemini clients if their SDKs cause trouble; keep `DryRunClient` and `ScriptedClient`. |
| `brain/brain.py` | `brain/brain.py` | Unchanged. `Brain(kb, client, allow_no_reply=False)`. |
| `onboarding/schema.py`, `interview.py`, `draft.py` | `onboarding/` | Reused for `/start`. `Interview` keeps its transcript in memory; we store it in the DB between requests. Adds the `quick` prompt block (section 8). |
| `app/limits.py` | `app/limits.py` | Unchanged: per-visitor and per-day message caps. |
| `app/static/*` | `app/static/chat.*` | Starting point for the customer chat page and the "Behind the reply" panel. |
| `tests/` | `tests/` | Keep the ones that still apply (schema, kb, brain, prompt, limits). |

Live prompts are in `prompts/`: `brain.md` (the receptionist), `learn.md` (relay + learning, **new**), `interview.md` (onboarding interview, with a new quick mode), `draft.md` (interview to KB), `translate_kb.md`.

---

## 3. Code layout

```
replit.md
pyproject.toml
kb/the-plug.md                seed KB for business 'the-plug'
prompts/                      brain.md, learn.md, interview.md, draft.md, translate_kb.md
brain/                        reused (section 2)
onboarding/                   reused (section 2)
app/
  main.py                     FastAPI app: routes, startup seeding
  db.py                       SQLAlchemy engine, session, models
  services/
    businesses.py             create/load businesses, KB versions, brain cache
    conversations.py          conversation + message logic, states
    owner.py                  inbox, relay + learning, applying KB changes
    onboarding.py             interview sessions, drafting, publishing
  prompts.py                  render_blocks(text, flags): the <!-- if X --> blocks
  static/
    index.html, landing.css               landing page
    chat.html, chat.js, chat.css          customer chat
    owner.html, owner.js, owner.css       owner dashboard
    start.html, start.js, start.css       onboarding
    shared.css                            colours, fonts, RTL helpers
tests/
reference/shop-assistant/     read-only
```

---

## 4. Data model (Replit PostgreSQL)

Every table has `business_id` (except `businesses` itself and `onboarding_sessions` before publishing). All timestamps are UTC.

**businesses**
| column | type | notes |
|---|---|---|
| id | serial PK | |
| slug | text unique | url-safe, e.g. `the-plug`, `noor-tailoring` |
| name | text | from KB front matter `business:` |
| owner_key | text | random 24-char secret; the owner link carries it |
| kb_markdown | text | **current** KB, always valid per `parse_kb()` |
| kb_version | int | +1 on every saved change |
| suggestions | json | list of starter questions shown as chips (may be empty) |
| created_at | timestamptz | |

**kb_changes** (history; nothing is ever lost)
| column | type | notes |
|---|---|---|
| id, business_id | | |
| entry_id | text | e.g. `holiday-christmas` |
| change | text | `add`, `update`, `manual_edit`, `initial` |
| old_text, new_text | text | entry text before/after (`manual_edit`/`initial`: whole KB) |
| source_escalation_id | int null | which owner answer it came from |
| created_at | | |

**conversations**
| column | type | notes |
|---|---|---|
| id | uuid PK | the customer page keeps it in `localStorage` |
| business_id | | |
| state | text | `bot_active`, `waiting_on_owner`, `human_handoff`, `closed` |
| language | text null | last detected customer language, informational |
| created_at, updated_at | | |

**messages**
| column | type | notes |
|---|---|---|
| id serial, business_id, conversation_id | | |
| role | text | `customer`, `bot`, `staff` |
| text | text | |
| action | text null | bot messages only: `answer`, `ask_owner`, `handoff` |
| cited_entries | json | bot messages: all cited IDs (public + internal); **never sent to the customer page in full** |
| reasoning | text null | bot messages; owner page only |
| created_at | | |

**escalations** (the owner's inbox)
| column | type | notes |
|---|---|---|
| id serial, business_id, conversation_id | | |
| message_id | int | the bot message that raised it |
| kind | text | `ask_owner` or `handoff` |
| question | text | `question_for_owner` (ask_owner) or a short summary (handoff) |
| status | text | `pending`, `answered`, `closed` |
| owner_answer | text null | |
| learn_proposal | json null | the `LearnResult` (section 7) |
| learn_decision | text null | `saved`, `edited`, `once` |
| created_at, answered_at | | |

**onboarding_sessions**
| column | type | notes |
|---|---|---|
| id uuid PK | | |
| business_name | text | |
| mode | text | `quick` or `full` |
| transcript | json | `[{role: "owner"|"interviewer", text}]` |
| covered | json | topic IDs |
| done | bool | |
| draft_kb | text null | |
| open_questions | json | |
| business_id | int null | set when published |
| created_at | | |

On startup: create tables if missing; if no business `the-plug` exists, create it from `kb/the-plug.md` with the suggestions in section 6. Its owner key is the `PLUG_OWNER_KEY` secret when set (always set it), otherwise a random key logged once.

**Two databases.** Replit gives the published app its own **production database**, separate from the development database the workspace and Agent use. Agent can't modify production data. So:
- Seeding must happen **in app code at startup** (above), so the production database gets The Plug too.
- Anything created while testing in the workspace preview (learned entries, conversations, Noor Tailoring) does **not** exist on the published URL. Stage demos use the published app, so create demo data there.
- Use `DATABASE_URL` exactly as provided in each environment. If a connection fails on SSL, follow Replit's database docs (SSL off for development, on for production).

---

## 5. The brain per business

- `get_brain(business)` returns a cached `Brain(parse_kb(business.kb_markdown), client, allow_no_reply=False)`, cached by `(business.id, business.kb_version)`. A KB change bumps the version, so the next message builds a new brain.
- One shared LLM client: `make_client("gpt-6-luna", effort="medium")`.
- Without AI credentials (or `JAWAB_MODEL=dry-run`), use `DryRunClient`: the app still runs, and every message escalates. Useful for UI work without spending credits.

---

## 6. Customer chat: `/b/{slug}`

**Page:** the chat from the reference demo, restyled with the business's name in the header. "Behind the reply" panel kept (it's our demo hook), but **hidden unless `?panel=1`**; the landing page's demo link uses `?panel=1`.

- Every bubble and the input use `dir="auto"` so Arabic renders right-to-left.
- A language toggle (EN / عربي) switches only the page's own labels (placeholder, buttons, notes), not the bot. Keep the UI strings in one small JS dictionary.
- Suggestion chips from `business.suggestions`. For The Plug, seed:
  1. "How much for 100 black & white pages?"
  2. "كم سعر طباعة ٥٠ صفحة ملونة؟"
  3. "هل أنتم مفتوحون يوم عيد الميلاد؟"
  4. "My prints came out in the wrong order!"
  5. "ana talib, fi discount?"
- The conversation ID lives in `localStorage` (`jawab:{slug}:conversation`), wrapped in try/catch; if storage fails, keep it in memory. A "New chat" button clears it.
- While the conversation is `waiting_on_owner` or `human_handoff`, the page **polls** `GET /api/b/{slug}/conversations/{id}/messages?after={last_id}` every 3 seconds and appends new bot or staff messages. Staff messages look different (a "Team" label).

**API**

`POST /api/b/{slug}/chat`
```json
// request
{ "conversation_id": "uuid or null", "message": "text (1-500 chars)" }
// response
{
  "conversation_id": "uuid",
  "state": "bot_active | waiting_on_owner | human_handoff",
  "message": { "id": 123, "role": "bot", "text": "...", "action": "answer" },
  "panel": {                        // what the "Behind the reply" panel may show
    "action": "answer",
    "question_for_owner": null,     // shown, it's in English and harmless
    "sources": [{ "id": "print-a4-bw", "text": "...", "learned": false }],   // PUBLIC entries only
    "internal_rules_used": 1        // a count; IDs and text of internal entries never leave the server
  }
}
```

Flow for each customer message:
1. Find or create the conversation (`business_id` checked). Rate limits from `app/limits.py`: **60 per visitor per hour, 3,000 per day overall**. Behind Replit's proxy every request comes from the proxy's address, so identify the visitor by the **first IP in `X-Forwarded-For`** (falling back to `request.client.host`). Otherwise all the judges' phones share one limit.
2. Save the customer message.
3. **If state is `human_handoff`:** don't call the brain. Return `message: null`. The message shows up in the owner's handoff thread. (Optional: one short automatic note the first time: "A team member will reply here.")
4. Otherwise build `IncomingMessage(text=<this message>, history=<the up to 40 messages before it, oldest first>)` (the current message is the `text`, not part of `history`). History comes from the database, so customers can't fake staff turns. Map rows to `Turn`: customer → `role=customer`; bot → `role=bot` with its `action`; staff → `role=staff`. Then call `brain.decide()`.
5. Save the bot message (text, action, cited_entries, reasoning).
6. By action:
   - `answer`: state stays or returns to `bot_active`. (A new answerable question while `waiting_on_owner` keeps the state `waiting_on_owner`, as the prompt already handles.)
   - `ask_owner`: state `waiting_on_owner`; create an escalation (`kind=ask_owner`, `question=question_for_owner`). If there is already a pending ask_owner escalation for this conversation, **update its question** instead of creating a second one (the prompt restates the whole request).
   - `handoff`: state `human_handoff`; create an escalation (`kind=handoff`, `question`: a one-line summary built from the customer's last message).
7. Return the response.

`GET /api/b/{slug}/conversations/{id}/messages?after={id}` returns `{state, messages: [{id, role, text}]}` (customer-safe fields only).

`GET /api/b/{slug}/public` returns `{name, suggestions}` for the page header.

---

## 7. Owner dashboard: `/owner/{slug}?key=...`

Every `/api/owner/{slug}/...` call needs the key (query `key` or header `X-Owner-Key`), compared with `secrets.compare_digest`. Wrong key: 403.

**Tabs:**

1. **Inbox** (default): pending escalations, newest first, with a red count badge. Polls every 5 s.
   - **Ask owner** card: the customer's last messages (small transcript), the bot's `question_for_owner`, a text box "Your answer" and **Send**.
     - Send runs the **relay + learn** call (below). The customer gets `reply_to_customer` as a bot message (if it isn't null); state goes back to `bot_active`; escalation `answered`.
     - Then the card turns into the **learning card**: `owner_summary`, the proposed entry (ID, visibility, text, and for `update` the old text struck through), and three buttons:
       - **Save**: apply the proposal to the KB.
       - **Edit**: open the entry text in a textarea (ID and visibility editable), then save.
       - **Just this once**: save nothing (`learn_decision=once`).
       - If `learn_action` is `none`: show the reasoning ("Looks like a one-off answer, so nothing to save") plus a small "Save anyway" link that opens Edit with a blank draft.
   - **Handoff** card: the transcript, a reply box (sends a `staff` message to the customer as-is; no model call), and **Give back to the bot** (state `bot_active`, escalation `closed`).
2. **Conversations**: list of recent conversations with state and last message; click to see the full thread including bot actions, cited entries and reasoning (owner-only). Lower priority: build last.
3. **Knowledge**: the KB rendered as cards grouped by section. Learned entries get a "Learned ✦ {date}" badge and a link to the customer question they came from. *(Optional extra, only in P5 if there's time:)* an "Edit raw KB" button opens the full markdown; saving runs `parse_kb()` and shows errors instead of saving if it fails (`kb_changes.change=manual_edit`).
4. **Share**: the customer link, the owner link, and an embed snippet:
   ```html
   <iframe src="https://{host}/b/{slug}" style="width:380px;height:600px;border:0;border-radius:16px"></iframe>
   ```
5. **Stats strip** (top of the page): messages this week; % answered by the bot without the owner (`answer` actions ÷ all bot messages); questions learned (count of `kb_changes` from escalations); pending now.

**Relay + learn call** (`prompts/learn.md`)

One model call through the same client and seam as the brain, structured output:

```python
class LearnAction(StrEnum):
    ADD = "add"
    UPDATE = "update"
    NONE = "none"

class ProposedEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(description="Lowercase, hyphenated, unique. For 'update', the existing entry's ID.")
    visibility: Literal["public", "internal"]
    text: str = Field(min_length=1, description="The complete entry text, in English.")

class LearnResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reasoning: str = Field(min_length=1, description="1-3 plain sentences for the owner: general or one-off, and why.")
    reply_to_customer: str | None = Field(description="The message to the customer in their language, or null if the owner's answer isn't for the customer.")
    learn_action: LearnAction
    target_entry_id: str | None = Field(description="Required for 'update', null otherwise.")
    proposed_entry: ProposedEntry | None = Field(description="Required for 'add' and 'update', null for 'none'.")
    owner_summary: str = Field(description="One short line for the owner saying what would be saved, or why nothing is.")
```

Input (user message), each part in its tags: `<knowledge_base>` (current KB), `<conversation>` (last 10 messages as `[customer] ...`, `[bot, ask_owner] ...`, `[staff] ...`), `<question_for_owner>`, `<owner_answer>`. Validate like the brain: one corrective retry on invalid output; on a second failure, send the owner's answer to the customer as a `staff` message as-is and show "Couldn't draft a knowledge entry" with Edit open.

Code checks after parsing: `add` must use a new ID (if taken, append `-2`); `update` must target an existing ID; `proposed_entry.text` must not contain a line starting with `#` or a line that is only `---`.

**Applying a saved entry**

- `add`: append under a `## Learned from the owner` section at the end of the KB (create it with a `---` line before it if missing):
  ```
  ### {id}
  **Visibility:** {visibility} · **Status:** learned

  {text}
  ```
- `update`: replace that entry's body text (everything between its meta line and the next heading or `---`) and set its status to `learned`.
- Run `parse_kb()` on the result. If it fails, don't save: show the error and open Edit.
- On success: save `kb_markdown`, bump `kb_version`, insert into `kb_changes`, set `learn_decision`.

`prompts/brain.md` already treats `learned` entries as the owner's confirmed answers and lets them win over an internal "ask the owner about X" rule (never over a "handoff" rule).

---

## 8. Onboarding: `/start`

Goal: a new business has a working bot in about five minutes. **Two paths on one screen:**

**A. Paste (fast, the stage demo):** a big textarea, "Paste your price list, menu, website text or notes", plus business name. **Create my assistant** sends it as the owner's first message of a **quick** interview. The interviewer then asks a handful of short questions (usually 3 to 8) to fill gaps. A **Skip to draft** button is always available.

**B. Interview:** the same chat without the paste box, `mode=full` (the full topic list).

Then:
1. **Draft:** run `onboarding/draft.py` with `prompts/draft.md` on the transcript. Show the drafted KB as readable cards (public/internal badges), the **open questions** list, and an "Edit raw" textarea. `parse_kb()` must pass before publishing.
2. **Publish:** create the business (slug from the name, made unique; `owner_key` random; suggestions: ask the drafting step for 4 starter questions customers would ask, or leave empty if that adds risk), store the KB with a `kb_changes` row `initial`, and show:
   - "Your assistant is live": customer link `/b/{slug}`, owner link `/owner/{slug}?key=...` (with a warning to keep it private), and the embed snippet.
   - A **Try it now** button that opens the chat.

**Quick mode prompt block.** `prompts/interview.md` ends with a block between `<!-- if quick -->` and `<!-- end -->`. `app/prompts.py` provides `render_blocks(text, {"quick": True/False})`: keep the block content when the flag is true, drop it when false. **`onboarding.Interview` reads the raw file by default, so always pass the rendered text in: `Interview(client, prompt=render_blocks(raw, {"quick": ...}))`.** Otherwise full-mode interviews would also get the quick-mode instructions. (Same pattern as the `no_reply` blocks in `brain.md`, which `brain.render_prompt()` already handles. Don't break those.) In quick mode, treat the interview as done when the model says `done`, even if some topics are uncovered.

**API**
- `POST /api/onboarding` `{business_name, mode, pasted_text?}` → `{session_id, interviewer_message}`
- `POST /api/onboarding/{id}/reply` `{text}` → `{interviewer_message, covered, done}`
- `POST /api/onboarding/{id}/draft` → `{kb_markdown, open_questions, errors}`
- `POST /api/onboarding/{id}/publish` `{kb_markdown}` → `{slug, chat_url, owner_url, embed_html}`

Model for onboarding: `gpt-6-luna` at `effort="medium"` for both the interview and the draft. (At `high`, the draft took about 75 seconds in testing, too slow on stage; medium is the setting the rest of the app uses.) Give the draft call `max_tokens=32000`.

---

## 9. Landing page: `/`

One page, EN/AR toggle (Arabic flips the layout with `dir="rtl"` on `<html>`).

- **Hero:** "Your shop's receptionist that never guesses." / "موظف استقبال لمتجرك لا يخمّن أبداً." Sub-line: "Answers your customers in Arabic and English from your own price list. When it doesn't know, it asks you, and learns your answer." Two buttons: **Try the live demo** (`/b/the-plug?panel=1`) and **Set up your business, free** (`/start`).
- **How it works**, 3 steps: Paste your info → It answers, citing your info → It asks you when unsure, and learns.
- **Why it's different**, 3 cards: Never guesses (every answer cites your info, or it asks you) · Learns from you (one tap turns your answer into knowledge) · Arabic and English (and Arabizi), from one knowledge base.
- **Live proof:** the stats of the demo business (messages handled, % answered without the owner, questions learned), from a public stats endpoint that returns only those three numbers.
- Footer: "Built at the Founding MENA x Replit Hackathon, Dubai, 31 Oct 2026."

Pricing is **not** built. (The pitch covers it.)

---

## 10. Look and feel

- Clean, modern, light by default with dark mode (`prefers-color-scheme`). One accent colour (deep teal `#0F766E`), warm neutral background, rounded cards, generous whitespace.
- Fonts: system UI stack for Latin; for Arabic, `"IBM Plex Sans Arabic", "Noto Sans Arabic", system-ui` from Google Fonts.
- Action badges keep the reference colours: Answer (green), Ask owner (amber), Hand off (red/rose). Learned entries: violet "✦ Learned" badge.
- Mobile first: the chat must work well on a phone (judges will open the link on their phones).

---

## 11. Not today

WhatsApp/Telegram/email channels, user accounts and passwords (the owner key link is enough for today), payments, voice, file uploads in the chat, vector search, analytics beyond the stats strip. If asked "what's next", these are the roadmap.
