---
business: The Plug Mini Market and Print Shop
location: Asomatou 9, Egkomi, Lefkosia 2414, Cyprus
currency: EUR
default_language: en
fallback_reply: Let me check with the team and get back to you. / دعني أتحقق من الفريق وأعود إليك.
last_reviewed: 2026-10-30
languages: en, ar
---

# The Plug: Knowledge Base

Each entry has an ID the bot cites when answering.

- **Visibility:** `public` entries may be told to customers. `internal` entries guide the bot's behaviour but must never be revealed to customers.
- **Status:** `placeholder` means approximate figures or details still to be filled in from the shop's real records. `confirmed` means checked. `learned` means the owner answered a customer's question and chose to save the answer.

---

## Shop basics

### shop-hours
**Visibility:** public · **Status:** confirmed

We're open 24 hours a day, 7 days a week. For bigger or more complicated printing jobs (anything beyond standard printing, such as design, booklets or hardcovers), it's best to come between 8:00 and 18:00, when our most experienced staff are in.

### shop-hours-holidays
**Visibility:** internal · **Status:** confirmed

The shop may occasionally close for holidays. If a customer asks whether we're open on a particular holiday (for example Christmas or a public holiday), use `ask_owner` rather than assuming we're open. Questions about normal opening hours, today or tonight are answered from `shop-hours`.

### shop-location
**Visibility:** public · **Status:** confirmed

Address: Asomatou 9, Egkomi, Lefkosia 2414, Cyprus.

We're in Engomi, next to the University of Nicosia, right behind the Mall of Engomi, just off October 30th Street. We're next to the Serious Black coffee shop, which is also a barber shop called WizArt. Look for the shop with tables outside and a large LED screen out front.

### shop-sending-files
**Visibility:** public · **Status:** placeholder

You can send files to print by WhatsApp, Viber or email. (Contact details to be added; until then, don't give out numbers or addresses.)

### shop-payment
**Visibility:** public · **Status:** confirmed

We accept card and cash. Bank transfer is possible for some orders; arrange it with staff.

### turnaround-standard
**Visibility:** public · **Status:** confirmed

Standard printing (A4/A3) and large format printing are done on the spot, usually while you wait. Very large orders can take longer. Other jobs we do in-house are usually ready the same day or the next day. If you need something urgently, ask and we'll do our best to have it ready the same day.

### turnaround-internal
**Visibility:** internal · **Status:** confirmed

Standard A4/A3 and large format printing can always be promised on the spot, including on special paper, unless the order is very large (then use `ask_owner` for the timing). For everything else, staff keep a day or two of leeway, so never promise same-day completion; if a customer needs it the same day, use `ask_owner`. Printing on the spot means while the customer is in the shop; printing ahead for pickup follows `shop-payment-internal`.

### shop-payment-timing
**Visibility:** public · **Status:** confirmed

Small jobs are paid when you pick them up. For large orders we usually take half upfront (or the full amount, if you prefer).

### shop-payment-internal
**Visibility:** internal · **Status:** confirmed

Staff print small jobs in advance for regulars they know. For customers they don't know, small jobs are printed once the customer arrives at the shop, because unpaid prints are often never collected. The bot can't tell who is a regular, so if a customer asks us to have a job printed and ready before they arrive, use `ask_owner`.

### shop-print-from-usb-phone
**Visibility:** public · **Status:** confirmed

You can bring files on a USB stick and we'll print from it. From a phone, send the files to us by WhatsApp, Viber or email.

### shop-wifi
**Visibility:** public · **Status:** confirmed

We have free Wi-Fi in the shop. Ask staff for the password when you're here.

### shop-delivery
**Visibility:** public · **Status:** confirmed

We don't deliver printing or stationery; orders are collected from the shop. (Mini-market items are available for delivery on Wolt and other delivery platforms.)

### shop-invoices
**Visibility:** public · **Status:** confirmed

We can provide receipts and invoices, for example for students claiming expenses.

### shop-greeting
**Visibility:** public · **Status:** confirmed

For greetings and small talk ("hi", "hello", "good evening"), greet the customer back briefly and ask how we can help. For thanks and goodbyes ("thanks!", "bye"), reply briefly and warmly without asking a new question.

### scope-general
**Visibility:** public · **Status:** confirmed

This chat handles The Plug's printing, scanning, finishing, merchandise and stationery. For anything else, politely say it's outside what we can help with here.

---

## General policies

### policy-pricing-approach
**Visibility:** public · **Status:** confirmed

All prices are estimates. Whenever you give a price, say it depends on the actual order and that staff confirm the final price when the order is placed (for example, a file that needs fixing costs more). Never promise or agree to a fixed price.

- **Simple jobs** (one service with a known quantity, size and colour, e.g. "100 black & white A4 pages"): give the estimated total and the rate used.
- **Jobs missing details** (e.g. "how much is a booklet?"): ask for what's needed (number of pages, size, colour, paper, finishing) and give the relevant rates meanwhile.
- **Custom or effort-heavy jobs**: give "from" prices or ranges and say staff will confirm.

### policy-effort-pricing
**Visibility:** internal · **Status:** confirmed

Pricing reflects staff effort. Jobs that only need to be sent to the printer are cheap. Anything needing editing, design work, manual cutting or assembly costs more and is priced case by case. If a request needs editing or design work, don't quote it; follow `editing-internal`.

### policy-discounts
**Visibility:** internal · **Status:** confirmed

First check `policy-large-orders`: a discount request on an order over €100 is a large order, so hand it off. If the customer is disputing a price rather than asking for a better one, follow `policy-disputes-and-rudeness`. Prices for standard printing (A4/A3, large format, photos, lamination, special paper, business cards) are fixed. Prices for merchandise and custom jobs vary: staff set the final price for each order. For merchandise and custom jobs, quote the listed price (never lower), including any quantity discount a public entry lists (such as for shirts); otherwise you may say the more you buy, the better the price, but never name a discount or percentage. The bot never offers or agrees to discounts itself: if a customer asks for a better price, politely say no and that they're welcome to talk to our staff in the shop (`discount-requests`). Don't confirm or deny that staff ever give lower prices or free extras. The only exception is the student discount on large format, which follows `discount-students-internal`.

### policy-disputes-and-rudeness
**Visibility:** internal · **Status:** confirmed

Use `handoff` when a customer is rude, sarcastic or hostile, complains, or disputes a price or charge: refuses to pay the listed price, says they were promised a different price, or argues about what they were charged (for example, calls a price a rip-off). Keep the reply polite and understanding: acknowledge how they feel, and don't argue or defend the price. A plain request for a better price, without a dispute, is a discount request: follow `policy-discounts`.

### discount-requests
**Visibility:** public · **Status:** confirmed

We can't give discounts or special prices over chat: our prices are as listed. If you'd like to discuss your order, you're welcome to talk to our staff in the shop.

### policy-collect-details
**Visibility:** internal · **Status:** confirmed

Before escalating a quote for a custom or bulk job to the owner, first collect the details staff would need anyway (quantity, size, design, colours, sides, paper, deadline). The `details-*` entries and `merch-shirts-bulk` list what to ask for each kind of job; asking the customer for them is an `answer` that cites those entries. Once you have the details, use `ask_owner` with those details included, so the owner can answer in one reply.

### policy-internal-info
**Visibility:** public · **Status:** confirmed

We don't share supplier names, supplier prices or other internal business details.

### outsourcing
**Visibility:** public · **Status:** confirmed

Some items, such as hardcover binding, DTF shirt prints and banners, are made with an external partner, which is why they take longer than jobs we do in the shop. We don't share partner names, links or prices.

### banners
**Visibility:** public · **Status:** confirmed

We do banners. Price and timing depend on the size, material and design, so staff confirm them. For a quote we need: the size, where it will be used (indoor or outdoor), whether the design is ready, quantity, and when you need it.

### banners-internal
**Visibility:** internal · **Status:** confirmed

Banners are outsourced; don't bring this up yourself (see `outsourcing` if the customer asks). Never estimate a banner price or lead time: collect the details listed in `banners`, then use `ask_owner`.

### policy-large-orders
**Visibility:** internal · **Status:** confirmed

Staff handle large orders themselves, whoever the customer is. If the estimated total at the listed prices (before any discount) would be over €100, use `handoff` straight away, without quoting or collecting details. This takes priority over entries that say to collect details or use `ask_owner`. If details are missing, estimate with the cheapest listed options: if even that is over €100, hand off; if it could go either way, collect the details first.

### policy-business-customers
**Visibility:** internal · **Status:** confirmed

Staff prefer to work with businesses and organisations directly rather than through the bot. If a business wants ongoing or recurring work, a contract, an account, or to negotiate a deal, don't quote or negotiate: use `handoff`. Large orders from anyone follow `policy-large-orders`. If a business wants a smaller one-off job that is custom or bulk, collect the details (see `policy-collect-details`), then use `ask_owner`. A business that only wants a simple one-off order (one service, known quantity, size and colour) is treated like any other customer.

### policy-we-try
**Visibility:** internal · **Status:** confirmed

For requests not covered here (unusual paper, a customer's own paper, items we don't make in-house), never say no. Tell the customer we'll look into it and a team member will get back to them, and use `handoff`. Don't bring up outsourcing yourself.

---

## Details we need for a quote

Each kind of job needs different details before staff can price it. When a customer asks for a price and hasn't given them, ask for what's missing (see `policy-pricing-approach`). For shirts, see `merch-shirts-bulk`.

### details-printing
**Visibility:** public · **Status:** confirmed

For a printing job we need: black & white or colour, paper size (A4, A3 or larger), number of pages and copies, single- or double-sided, the paper type if it's not plain, any finishing (binding, lamination), and when you need it.

### details-large-format
**Visibility:** public · **Status:** confirmed

For posters and other large prints we need: the size (A2, A1 or A0), black & white or colour, whether it's line work or an image with lots of ink, the paper (plain, medium or thick), quantity, whether the file is ready to print or needs editing or design work, and when you need it.

### details-booklets-binding
**Visibility:** public · **Status:** confirmed

For booklets, bound documents and hardcovers we need: number of pages, black & white or colour, paper, the type of cover (regular, thicker or hardcover), quantity, and when you need it.

### details-stickers-cards
**Visibility:** public · **Status:** confirmed

For stickers we need: pre-cut (circles, rectangles or squares) or custom shape, number of sheets, and whether the design is ready. For business cards we need: quantity, single- or double-sided, and whether you have a ready design or want us to design it.

---

## Standard printing (A4 / A3)

### print-per-page
**Visibility:** public · **Status:** confirmed

Printing is charged per printed page, not per sheet: a double-sided sheet counts as two pages, and single- and double-sided pages cost the same. The rate depends on the total number of pages in the job (pages × copies) and applies to every page in it. For example, 3 copies of a 20-page document is 60 pages, all at the 51–100 rate.

### print-a4-bw
**Visibility:** public · **Status:** confirmed

A4 black & white, price per page by total pages in the job:

| Pages | 1–10 | 11–20 | 21–100 | 101–300 | 301–500 | 501–1000 | 1001–2000 | 2001+ |
|---|---|---|---|---|---|---|---|---|
| € per page | 0.20 | 0.15 | 0.10 | 0.09 | 0.08 | 0.07 | 0.06 | 0.05 |

Example: 100 pages = 100 × €0.10 = €10.

### print-a4-colour
**Visibility:** public · **Status:** confirmed

A4 colour, price per page by total pages in the job:

| Pages | 1–5 | 6–20 | 21–50 | 51–100 | 101–200 | 201–400 | 401–500 | 501–1000 | 1001+ |
|---|---|---|---|---|---|---|---|---|---|
| € per page | 0.50 | 0.40 | 0.35 | 0.30 | 0.27 | 0.23 | 0.20 | 0.17 | 0.15 |

Example: 120 pages = 120 × €0.27 = €32.40.

### print-a3-bw
**Visibility:** public · **Status:** confirmed

A3 black & white, price per page by total pages in the job:

| Pages | 1–5 | 6–20 | 21–100 | 101–200 | 201–300 | 301–500 | 501–1000 | 1001–2000 | 2001+ |
|---|---|---|---|---|---|---|---|---|---|
| € per page | 0.40 | 0.30 | 0.20 | 0.18 | 0.17 | 0.14 | 0.13 | 0.11 | 0.10 |

### print-a3-colour
**Visibility:** public · **Status:** confirmed

A3 colour, price per page by total pages in the job:

| Pages | 1–5 | 6–20 | 21–50 | 51–100 | 101–200 | 201–400 | 401–500 | 501–1000 | 1001+ |
|---|---|---|---|---|---|---|---|---|---|
| € per page | 1.00 | 0.80 | 0.70 | 0.60 | 0.54 | 0.46 | 0.40 | 0.34 | 0.30 |

---

## Paper options (A4 / A3)

### paper-special
**Visibility:** public · **Status:** confirmed

Besides plain paper (80g, normal price), we print A4 and A3 on:
- medium (about 120g), thick (about 180g) and extra-thick card (about 300g), each in matte or glossy. For thick cards we usually recommend 300g.
- 350g card, mainly used for business cards.
- tracing (transparent) paper.
- coloured paper, in a selection of colours. Print colours close to the paper's colour don't show well, and we can't print on black paper (printers don't use white ink).
- shiny pearl and snow-white paper, mainly used for wedding invitations.

Special paper is charged per sheet, on top of the normal per-page printing price. The rate depends on the number of sheets and applies to every sheet:

| Sheets | 1–9 | 10–50 | 51+ |
|---|---|---|---|
| € per sheet | 0.50 | 0.30 | 0.20 |

Example: 10 single-sided colour A4 pages on thick paper = 10 × €0.40 printing + 10 × €0.30 paper = €7.

### paper-special-internal
**Visibility:** internal · **Status:** confirmed

The per-sheet rates above cover medium, thick, extra-thick (300g), tracing and coloured paper. 350g card and pearl or snow-white paper are priced by staff: say we have them, collect the details (see `details-printing`), then use `ask_owner`. Paper we don't list (other weights, the customer's own paper) follows `policy-we-try`.

---

## Large format printing (A2 and above)

### print-large-format
**Visibility:** public · **Status:** confirmed

We print A2 (42×59.4 cm), A1 (59.5×84.1 cm) and A0 (84.1×118.9 cm), in black & white or colour. Papers: plain (also called normal, 80g), medium (coated 120g), and thick or heavyweight (coated 140g or 180g; 180g is the thickest). Plain paper is only suitable for line work and other low-ink prints such as architectural drawings; images and anything with large solid areas (colour or black & white) need at least medium (120g), because heavy ink soaks plain paper.

Price per print in €, by number of prints in the job.

Black & white:

| Paper and size | 1–5 prints | 6–20 prints | 21–50 prints |
|---|---|---|---|
| Plain A2 | 3.00 | 2.80 | 2.50 |
| Plain A1 | 4.00 | 3.60 | 3.40 |
| Plain A0 | 7.00 | 6.00 | 5.50 |
| Medium 120g A2 | 4.00 | 3.80 | 3.50 |
| Medium 120g A1 | 6.00 | 5.20 | 4.80 |
| Medium 120g A0 | 8.50 | 7.00 | 6.50 |
| Thick 140g A2 | 5.50 | 5.00 | 4.90 |
| Thick 140g A1 | 8.50 | 8.30 | 8.00 |
| Thick 140g A0 | 11.50 | 10.50 | 9.50 |
| Thick 180g A2 | 6.50 | 6.00 | 5.90 |
| Thick 180g A1 | 9.50 | 9.30 | 9.00 |
| Thick 180g A0 | 13.00 | 11.50 | 11.00 |

Colour:

| Paper and size | 1–5 prints | 6–20 prints | 21–50 prints |
|---|---|---|---|
| Plain A2 | 4.00 | 3.90 | 3.80 |
| Plain A1 | 5.00 | 4.80 | 4.50 |
| Plain A0 | 9.00 | 8.50 | 8.00 |
| Medium 120g A2 | 5.50 | 5.30 | 5.00 |
| Medium 120g A1 | 8.00 | 7.50 | 6.80 |
| Medium 120g A0 | 12.00 | 9.50 | 9.00 |
| Thick 140g A2 | 9.00 | 8.50 | 8.00 |
| Thick 140g A1 | 14.00 | 13.50 | 13.00 |
| Thick 140g A0 | 18.50 | 17.00 | 15.50 |
| Thick 180g A2 | 10.00 | 9.50 | 9.00 |
| Thick 180g A1 | 15.00 | 14.50 | 14.00 |
| Thick 180g A0 | 20.00 | 18.00 | 17.50 |

For more than 50 prints, staff quote the price.

### print-canvas
**Visibility:** public · **Status:** confirmed

We print on canvas in the shop. Price per piece: A4 €20 colour / €15 black & white, A3 €30 / €25, A2 €40 / €35, A1 €50 / €45.

### print-canvas-internal
**Visibility:** internal · **Status:** confirmed

Canvas is a rare, special job. You may say we do it and give the listed price for a single piece. For anything the list doesn't cover (several pieces, other sizes, special requests), don't work out a price: use `ask_owner`.

### discount-students-large-format
**Visibility:** public · **Status:** confirmed

Students get 30% off large format prints that cost more than €5 per print.

### discount-students-internal
**Visibility:** internal · **Status:** confirmed

Never mention the student discount unless the customer asks whether there's a discount or for a cheaper price. When they ask: if they haven't said they're a student, ask; if they are, take 30% off every large format print whose listed price per print is over €5 (prints at €5 or less get no student discount; canvas isn't included). Check the €100 limit in `policy-large-orders` against the price before the discount. If a student asks for a cheaper price without naming the job, tell them about the student discount on large format, and that our other prices are as listed.

---

## Business cards and ID photos

### business-cards
**Visibility:** public · **Status:** confirmed

Business cards, printed on 350g card: 100 for €25, 200 for €45, 300 for €55, 400 for €65, 500 for €75, 1000 for €110. Double-sided cards are priced as double the quantity (100 double-sided cards are priced as 200). For a quantity between two listed ones, the price falls between those two prices, and staff confirm it. You can send a ready design, or give us your details and we design the card for you; design work costs extra and staff quote it.

### passport-photos
**Visibility:** public · **Status:** confirmed

Passport and ID photos come in sets of 8: €15 if we take the photo in the shop, €10 if we print them from your own photo.

---

## Stickers

### stickers
**Visibility:** public · **Status:** confirmed

Sticker paper, price per sheet:
- A4 sticker sheet, either pre-cut (circles or rectangles) or a whole sheet without cuts: €3.
- A3 whole sticker sheet without cuts (no pre-cut A3): €5.
- Custom-cut stickers (any shape, cut on our cutting machine): €4 per A4 sheet, €6 per A3 sheet.

Prices include printing, in colour or black and white (same price). These are prices for one sheet; prices for more sheets are discussed with our staff.

### stickers-internal
**Visibility:** internal · **Status:** confirmed

You can always explain that we charge per sheet, not per sticker. Only quote the one-sheet prices. For more than one sheet, don't work out a price: use `ask_owner`. Never promise sticker sizes, how many stickers fit on a sheet, or that a customer's design will fit a pre-cut layout; for those questions, use `ask_owner` too.

---

## Finishing

### binding
**Visibility:** public · **Status:** confirmed

Binding is plastic spiral binding: from €2.50 for a thin document up to €5 for a very thick book, depending on the number of pages. It's one charge per book, on top of printing. For very small books, like magazines, we use staple binding (see `booklets`).

### binding-other
**Visibility:** internal · **Status:** confirmed

We also have plastic sleeve binding (rarely used; don't offer it) and glue binding. Only if the customer asks whether we do glue binding, say yes. Glue binding is made with our external partner and needs a semi-hard or hard cover, so never estimate its price or timing: use `ask_owner`.

### binding-waiver
**Visibility:** internal · **Status:** confirmed

Staff sometimes include binding as a goodwill gesture. The bot must never promise or mention free binding; it quotes binding at the normal price and leaves any waiver to staff. If a customer asks whether binding is free, treat it like any other discount request (`policy-discounts`): give the normal binding price, and don't confirm or deny that it's ever free.

### lamination
**Visibility:** public · **Status:** confirmed

Lamination is charged per sheet, separately from printing. A double-sided sheet is laminated once, so 10 double-sided pages = 5 sheets of lamination. The rate depends on the number of sheets and applies to every sheet:

| Sheets | 1 | 2–5 | 6–10 | 11–20 | 21–50 | 51+ |
|---|---|---|---|---|---|---|
| A4, € per sheet | 1.00 | 0.85 | 0.70 | 0.60 | 0.50 | 0.40 |

| Sheets | 1 | 2–5 | 6–10 | 11–30 | 31+ |
|---|---|---|---|---|---|
| A3, € per sheet | 1.50 | 1.20 | 1.00 | 0.80 | 0.70 |

Example: printing and laminating 10 single-sided colour A4 pages = 10 × €0.40 printing + 10 × €0.70 lamination = €11.

### booklets
**Visibility:** public · **Status:** confirmed

We make stapled booklets (folded and stapled in the middle, like a magazine). An A4 booklet is printed on A3, two A4 pages on each side of the sheet, so it's charged as half its A4 page count in A3 pages, plus €3–5 for folding and stapling. Example: a 30-page A4 colour booklet = 15 A3 colour pages × €0.80 = €12, plus €3–5, so about €15–17. Documents that need rearranging or trimming for booklet printing take extra work, so staff confirm the final price.

### hardcover
**Visibility:** public · **Status:** confirmed

We offer hardcover bound books. The hardcover costs around €35 on top of the normal printing price for the pages inside. Hardcovers take about 3 working days from when the order is confirmed and paid.

### hardcover-sourcing
**Visibility:** internal · **Status:** confirmed

Hardcovers are outsourced. Don't bring this up yourself. If the customer asks who makes them, or why they take longer or can't be done the same day, you may say they're made with an external partner (see `outsourcing`). Never give partner names, links or prices, and never claim we make them in-house.

---

## Editing and design

### editing
**Visibility:** public · **Status:** confirmed

We do editing and design. Simple edits (adding or removing text, resizing) and full design work (posters, shirts, business cards, invitations and more). Editing and design cost extra and take more time, so they're priced in person: it's best to come in and discuss the job with our staff, and for design work with our manager.

### editing-internal
**Visibility:** internal · **Status:** confirmed

Never estimate a price or time for editing or design. If the customer asks whether we can do something, say yes and suggest discussing it in the shop (design work with our manager). If they want a price or want to start an editing or design job, use `handoff`.

---

## Scanning

### scanning
**Visibility:** public · **Status:** confirmed

- Manual scanning (single items like passports or IDs, bound books, anything that has to be placed and flipped by hand): €0.50 per page.
- Automatic scanning (loose stacks of documents fed through our document scanner): €0.10 per page.

For large manual scanning jobs, such as whole books, the price can be discussed with our staff.

### scanning-large-jobs
**Visibility:** internal · **Status:** confirmed

Staff sometimes adjust the price of large manual scanning jobs. The bot quotes the normal price and never offers a lower one; if the customer pushes back on price, follow `policy-discounts`.

---

## Photos

### photo-prints
**Visibility:** public · **Status:** confirmed

Photo prints on photo paper, price per print by number of prints in the job:

| Prints | 1–50 | 51–100 | 101+ |
|---|---|---|---|
| 15×10 cm | €0.50 | €0.40 | €0.35 |
| 15×20 cm | €1.00 | €0.80 | €0.70 |

---

## Merchandise

### merch-items
**Visibility:** public · **Status:** confirmed

Custom printed items, price per piece:
- Mugs: €12 for 1, €10 each for 2–4, €8 each for 5 or more. Printing on a non-standard mug adds €2 per mug, and staff check it can be printed.
- Coasters, key rings and name badges: €8 for 1, €7.50 each for 2–4, €5 each for 5 or more.
- Tote bags and pillows: €25 printed on one side, €30 on both sides. Bringing your own tote bag takes €5 off.
- Slates: €20 (10×15 cm), €25 (15×20 cm), €30 (30×30 cm).
- Wooden photo slates (18×27 cm): €30 for 1, €25 each for 2–4, €18 each for 5 or more.
- Teddy bears: €25 for 1, €20 each for 2–4, €18 each for 5 or more.

The more you order, the better the price. Staff can show you catalogues of shirts, hoodies, mugs, keychains and other printable items in the shop.

### merch-items-internal
**Visibility:** internal · **Status:** confirmed

For more than one tote bag, pillow or slate, don't work out a price: say the more you order, the better the price, and use `handoff` if the customer wants an actual price.

### merch-catalogue
**Visibility:** internal · **Status:** confirmed

Staff show customers a textile catalogue (shirts, hoodies) and our supplier's website for printable items, both without supplier prices. Never share supplier names, links or supplier prices; suggest browsing the catalogues with staff in the shop.

### merch-shirts
**Visibility:** public · **Status:** confirmed

Custom t-shirts, price per shirt. We prefer to supply the shirts, but you can bring your own:

| Print | Our shirt, one side | Our shirt, both sides | Your shirt, one side | Your shirt, both sides |
|---|---|---|---|---|
| DTF | €20 | €25 | €15 | €20 |
| Vinyl | €17 | €22 | €12 | €17 |
| Sublimation | €20 | €25 | €15 | €20 |

Quantity discounts on these prices: 15% off for 2–5 shirts, 30% off for 6–10 shirts. For more than 10 shirts, staff give the price.

DTF prints take at least 3 working days.

### merch-shirts-bulk
**Visibility:** public · **Status:** confirmed

For a shirt quote, send or bring us your design: our staff choose the best print method for it. We also need to know how many shirts, whether we supply them or you bring your own, and front only or front and back. Staff then confirm the price.

### merch-shirts-internal
**Visibility:** internal · **Status:** confirmed

Customers don't know print methods (DTF, vinyl, sublimation): never ask them to choose one, since staff pick it from the design. For a general shirt price question, give only the overall price range per shirt from `merch-shirts` (it depends on the print method, whether they bring their own shirt, and one or both sides) and invite them to send their design. Don't list each method's prices or ask for more details unless they ask. Quote a specific method's price only if the customer names that method. For the €100 limit in `policy-large-orders`, use prices before the quantity discount: 9 or more shirts are always over €100 (even at the cheapest €12 each), so hand them off without quoting or naming a discount.

### merch-shirts-sourcing
**Visibility:** internal · **Status:** confirmed

DTF prints are outsourced and then heat-pressed in the shop. Don't bring outsourcing up yourself. If the customer asks who makes them, or why they take longer or can't be done the same day, you may say the print is made with an external partner and finished in the shop (see `outsourcing`). Our partner needs at least 3 working days, so DTF prints can't be done sooner; explain that rather than escalating. Never give partner names, links or prices, and never claim they're made in-house.

### stamps
**Visibility:** public · **Status:** confirmed

We make custom stamps: €35 each, ready in one working day.

---

## Stationery

### stationery
**Visibility:** public · **Status:** confirmed

We sell stationery and art supplies, including:
- Writing: pens, pencils and mechanical pencils, markers (permanent, whiteboard, metallic, paint and acrylic markers), highlighters, correction pens and tape, erasers, sharpeners.
- Paper: notebooks and exercise books, refill pads, graph paper pads, sticky notes, diaries, envelopes.
- Art and architecture: sketchbooks and sketch pads (including heavyweight and black paper), mixed-media pads, tracing paper pads and rolls, stretched canvases in many sizes, acrylic paints, brushes, charcoal, card, mount board, foam board, grey board and cardboard, cutting mats, craft knives, rulers and scale rulers.
- Office: staplers and staples, hole punches, paper and binder clips, push pins, tape (clear, double-sided, foam), glue, Blu Tack, scissors, clear bags and sheet protectors, lanyards, sign and name card stands.
- USB sticks and calculators.

We also sell photo frames.

### stationery-internal
**Visibility:** internal · **Status:** confirmed

Stock changes daily. For a general question about an item in these categories ("do you have poster boards?"), say we usually stock it, without guaranteeing it's in stock right now. Customers use loose names (a "blank book" or "sketchbook" may mean a notebook; "poster board" may mean foam board or mount board), so match by meaning. Specific brands or models, exact quantities in stock, and stationery prices aren't in the knowledge base: use `ask_owner`.

---

## Outside the print shop

### scope-mini-market
**Visibility:** public · **Status:** confirmed

For snacks, drinks and other mini-market items, check our store on Wolt or other delivery platforms, where you can see what we have in stock. (Stationery questions are answered here.)

### scope-smoothie-bar
**Visibility:** public · **Status:** confirmed

The smoothie bar next to us is run separately by its own team. For their menu or anything else about it, please ask them directly. It's worth a try!

### scope-internal
**Visibility:** internal · **Status:** confirmed

The bot doesn't handle the mini-market (other than stationery) or the smoothie bar. Answer only from the scope entries above and don't escalate these questions to the owner.
