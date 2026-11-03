# Jawab · جواب

An AI receptionist for small businesses that **never guesses**. It answers customers in their own language (tested in English, Greek and Arabic, including Greek and Arabic typed in Latin letters) from the owner's own information. When it doesn't know, it **asks the owner**, passes the answer on to the customer in their language, and **learns it with one tap**. A new business sets itself up in a few minutes by pasting its price list.

**[Try it: be the customer and the owner →](https://jawab-fb4z.onrender.com/try)** You get your own private copy of a real print shop. Ask it "Are you open on Christmas Day?", answer as the owner in the inbox next to the chat, tap Save, start a new chat and ask again.

<sub>The demo runs on free hosting that sleeps when nobody's using it, so the first visit can take about a minute to wake up. Your demo shop is private to you and resets after a day.</sub>

![The demo: a customer asks in Arabic, the owner answers in the inbox, and the bot learns the answer](docs/demo.png)

Built in one day (31 Oct 2026) at the **Founding MENA x Replit Hackathon** in Dubai, on top of the engine of my earlier project, [Shop Assistant](https://github.com/zeinsaid/Shop-Assistant).

---

## What it does

| For | What they get |
|---|---|
| **Customers** | A chat on the shop's website (a one-line script tag adds a chat bubble) that answers prices, hours and services in their language, and cites the shop's own information. The page itself comes in English, Greek or Arabic (right to left), as the business chooses. |
| **The owner** | An inbox of the questions the bot couldn't answer and the chats it handed to a person. Each answer goes to the customer, rewritten in their language, and comes with a draft knowledge entry: **Save**, **Edit** or **Just this once**. |
| **A new business** | `/start`: paste a price list, menu or website text, answer a few short questions, review the drafted knowledge base and publish. The bot is live straight away. |

The loop that makes it different:

```
customer: "هل أنتم مفتوحون يوم عيد الميلاد؟"        (are you open on Christmas Day?)
  bot: the knowledge base doesn't say  →  ask_owner: "I'll check with the team"
owner: "Closed on the 25th, back to 24/7 on the 26th."
  bot → customer, in Arabic: the owner's answer
  bot → owner: "Save this?  holiday-christmas (public): Closed on 25 December..."   [Save]
next customer, in English: "are you open on christmas day?"
  bot: answer, citing holiday-christmas ✦ Learned
```

## Built on the Shop Assistant engine

Jawab is a product built on an engine. The engine decides what to say; Jawab is the business around it.

| Layer | Repo | What it is |
|---|---|---|
| **Engine** | [Shop-Assistant](https://github.com/zeinsaid/Shop-Assistant) | The brain: one decision per message (`answer`, `ask_owner` or `handoff`), answers that must cite a public knowledge-base entry or code turns them into a question for the owner, internal rules that never reach customers, one corrective retry and a safe fallback. Also the learning call and the onboarding interview, and their prompts. Proven on a **130-case evaluation** across Anthropic, OpenAI and Google models. |
| **Product** | Jawab (this repo) | Multi-business web app: database, customer chat, owner inbox and learning, `/start` onboarding, the embeddable bubble, the landing page, rate limits, the public demo's sandboxes. |
| **Businesses** | data in Jawab's database | Each business is one markdown knowledge base plus settings. The Plug, a real print shop in Nicosia with its real prices, is the demo. Nothing business-specific is in the code. |

Jawab installs the engine as a Python package, pinned to a release tag:

```toml
dependencies = ["shop-assistant[openai]"]

[tool.uv.sources]
shop-assistant = { git = "https://github.com/zeinsaid/Shop-Assistant", tag = "v1.0.0" }
```

and uses it like any library:

```python
from brain.brain import Brain        # decide(message) -> one checked decision
from brain.learn import Learner      # owner's answer -> reply for the customer + draft KB entry
from onboarding.interview import Interview
```

Building Jawab improved the engine, and those changes went back into it: Arabic support, "learned entries win over ask-the-owner rules", the learning call, a quick five-minute interview, and language notes that switch on per business (a Greek shop gets the Greeklish notes, an Arabic one the Arabizi notes).

## How it was built

- **Before the day:** I wrote the product spec, the phase plan and the test script ([`docs/`](docs/)), adapted the engine's prompts for Arabic, and tested them live against the model the night before.
- **On the day (8:30 to 17:00):** Replit Agent built the app phase by phase from that spec: customer chat, owner inbox, learning, onboarding, landing page. After every phase I tested it on the published app (scripted HTTP checks plus manual checks on a phone) before starting the next. The engine was reused, not rewritten.
- **After the day:** with [Claude Code](https://claude.com/claude-code), I moved it off Replit: the engine became an installable package that Jawab depends on, the hosting moved to Render, and the public demo got private sandboxes and tighter spending limits.

## Running it locally

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```
uv sync          # install dependencies, including the engine from GitHub
uv run pytest    # run the tests (no API key needed)

# The app at http://localhost:8000. Without OPENAI_API_KEY it calls no model and costs nothing
# (every message goes to the owner). Data goes into a local SQLite file, jawab.db.
uv run uvicorn app.main:from_env --factory --reload
uv run --env-file .env uvicorn app.main:from_env --factory
```

Copy `.env.example` to `.env` for the settings: `OPENAI_API_KEY`, and optionally `DATABASE_URL` (any Postgres database, for data that must last) and `PLUG_OWNER_KEY`.

| Page | What it is |
|---|---|
| `/` | Landing page (English / Greek / Arabic) |
| `/try` | The public demo: your own sandbox, customer chat and owner inbox side by side |
| `/b/{slug}` | A business's customer chat (`?panel=1` adds the "Behind the reply" panel) |
| `/owner/{slug}?key=...` | The owner's inbox, knowledge and share links |
| `/start` | Onboarding a new business |
| `/embed.js?b={slug}` | The website chat bubble, e.g. on [a demo shop site](https://jawab-fb4z.onrender.com/demo/the-plug) |

## Repository layout

```
├── app/
│   ├── main.py         # FastAPI: pages, customer API, owner API, onboarding, sandboxes
│   ├── db.py           # SQLAlchemy models (every table has a business_id) and seeding
│   ├── limits.py       # Rate limits that protect the API credit
│   ├── embed.js        # The website chat bubble
│   ├── services/       # Conversations, owner inbox and learning, KB edits, onboarding, sandboxes
│   └── static/         # Plain HTML, CSS and JavaScript; no build step
├── kb/the-plug.md      # The demo business's knowledge base
├── docs/               # The spec, test script and demo business written for the hackathon
├── tests/              # pytest, on an in-memory database with scripted model responses
└── render.yaml         # Hosting for the public demo (Render, free plan)
```

## The public demo's limits

The demo calls a real model, so it's protected: per-visitor and daily caps on model calls (`app/limits.py`), at most three onboardings per visitor a day, and a spending cap at the provider. Sandboxes are deleted after a day, and the free server's database is wiped whenever it restarts.

Known simplifications, fine for a demo, to change for real customers: the owner key is in the owner page's URL instead of a login, `/start` needs no sign-up, and the rate limits live in memory on one server.

## Data and privacy

The Plug's knowledge base has the shop's real public prices. The demo keeps conversations only in its temporary database, and the model provider is called with storage turned off.
