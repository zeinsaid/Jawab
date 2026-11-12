# Putting the Jawab bubble on a website

Two ways, the same bubble.

## 1. Self-hosted loader (recommended)

Download `jawab.js` from your Jawab server (`https://<jawab-server>/jawab.js`, the same file as
`app/static/jawab.js`) and serve it from your own website, for example as `/jawab.js`. Then, on every
page, just before `</body>`:

```html
<script src="/jawab.js" defer
        data-base="https://<jawab-server>"
        data-business="<slug>"
        data-accent="#F920EB"
        data-name="The Plug"
        data-languages="en,el"
        data-offline-en="Chat is offline right now. Call us on 22 542659 (24/7), message us on WhatsApp 94 055151, or email theplug.cyprus@gmail.com."
        data-offline-el="Η συνομιλία δεν είναι διαθέσιμη αυτή τη στιγμή. Πάρε μας τηλέφωνο στο 22 542659 (24/7), στείλε μας μήνυμα στο WhatsApp 94 055151 ή email στο theplug.cyprus@gmail.com."></script>
```

| Attribute | Required | What it does |
|---|---|---|
| `data-base` | yes | The Jawab server's address, no trailing slash. |
| `data-business` | yes | The business's slug (`the-plug`). |
| `data-accent` | no | The bubble's colour, `#RRGGBB`. Text on it is darkened just enough to stay readable. |
| `data-name` | no | The name in the greeting and header. Use the business's display name, so the greeting doesn't change when the real chat takes over. |
| `data-languages` | no | The chat's page languages (default `en,el,ar`). |
| `data-offline-en` / `-el` / `-ar` | no | Shown if the server can't be reached. Use the same text as the business's offline setting. |
| `data-theme` | no | `light` keeps the bubble and the chat light even in dark mode, for a light-only website. Left out, the chat follows the visitor's device. |

**Why self-hosted:** the bubble appears at once, even while a free Jawab server is asleep (it takes
about a minute to wake). Because the file is yours, update it when Jawab's `jawab.js` changes.

**What it does on the page:**
- Renders the bubble immediately, and pings `GET {data-base}/health` once on page load to wake the
  server. The server's `JAWAB_CORS_ORIGINS` / `JAWAB_CORS_ORIGIN_REGEX` must allow the website's
  address for the ping to read the answer. Even without it the bubble still works, just less quickly.
- On open, it shows a local greeting with the input ready, in the page's language (`<html lang="el">`
  gives Greek). The real chat loads hidden and takes over as soon as it's ready.
- A message typed before then shows a typing indicator, waits up to about 60 s for the server, then
  goes to the real chat as if typed there. If the server is still asleep, the offline message shows.
- The conversation ID is kept in the website's own `localStorage` (`jawab:<slug>:conversation`), so
  a visitor who comes back finds their conversation, and the owner's answer, waiting.
- Everything is inside a shadow root: no globals, no dependencies, and the page's CSS can't reach in.

## 2. One-line snippet

```html
<script src="https://<jawab-server>/embed.js?b=<slug>" async></script>
```

The same loader, served by the Jawab server with that business's settings filled in (accent, name,
languages, offline message). Simpler, but the bubble only appears once the server is awake.

## Privacy and cookies

The chat stores two things in the visitor's browser, both essential to the chat working: the
conversation ID (on the website, and inside the chat frame) and the chosen chat language. No
tracking, and nothing is shared with third parties. Messages are stored on the Jawab server and
processed by the model provider (OpenAI) outside the EU. If a customer leaves an email for an
answer, it's stored with their conversation and used only to send that answer.
