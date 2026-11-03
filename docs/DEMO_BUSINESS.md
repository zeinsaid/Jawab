# Demo business for onboarding: Noor Tailoring (made up)

> **Historical note.** Written on 30 Oct 2026 as the brief for the hackathon build (with Replit Agent, on Replit). Kept as the design record. Since then: the app runs on Render with SQLite or any Postgres instead of Replit PostgreSQL, the engine (`brain/`, `onboarding/`, prompts) is installed from [Shop-Assistant](https://github.com/zeinsaid/Shop-Assistant) instead of copied, and visitors get a private sandbox at `/try`. See the README for the current state.

A **fictional** business, used to show onboarding live. Any resemblance to a real shop is accidental. If asked on stage: "a made-up tailor shop, so I can show how a new business gets set up in two minutes."

## Paste this into `/start` (business name: Noor Tailoring)

```
Noor Tailoring & Alterations - خياطة نور
Shop 14, Al Karama Shopping Complex, Karama, Dubai. Near ADCB Metro Station exit 2.
Open Saturday to Thursday 10am - 10pm, Friday 4pm - 10pm.
WhatsApp for orders: we'll add the number later.

ALTERATIONS (AED)
Trousers shorten / تقصير بنطلون - 25
Trousers taper - 35
Shirt sleeves shorten - 30
Shirt taper (take in) - 40
Dress hem - 40 (lined dress 60)
Abaya shorten - 30
Kandura shorten - 25
Zip replacement - 30 (jackets 45)
Jacket sleeves - 70

CUSTOM TAILORING (AED, fabric not included)
Kandura - from 180
Abaya - from 250
Men's shirt - from 150
Suit (2 piece) - from 900

Express (same day) +50% if we can do it, ask first.
Normal alterations ready in 2 days. Custom tailoring 7 to 10 days.
Cash, card, Apple Pay.
Wedding and evening dresses: only by appointment with Noor.
```

## Short answers for the interviewer's questions

Use whichever fits; keep them short so the demo stays fast.

- **May the assistant quote the listed prices?** "Yes, quote the alteration prices as listed. Custom tailoring prices are 'from' prices; the final price is set after measuring and choosing the style."
- **What do customers ask most?** "Prices for shortening trousers and abayas, and how long it takes."
- **Anything the assistant must not quote?** "Wedding and evening dresses. Noor sees them in person. Also never promise express without asking us."
- **Who handles complaints?** "Me (Noor). Hand them to me."
- **Discounts?** "No discounts in chat. Regulars sometimes get a better price, but that's my decision; don't mention it."
- **Languages / tone?** "Arabic and English, friendly. If unsure, English."
- **Holding message when checking?** "One moment, let me check with Noor. / لحظة، سأتأكد من نور."
- **Fabric?** "We have some fabric in the shop, but customers usually bring their own. Fabric prices: ask me."

## What to ask the new bot afterwards (stage demo)

| Message | Expected |
|---|---|
| `كم سعر تقصير بنطلون؟` ("How much to shorten trousers?") | answer: AED 25, ready in 2 days, in Arabic |
| `can you do my abaya today?` | ask_owner (express needs asking first) |
| `I need my wedding dress altered` | handoff, ask_owner, or an answer that it's by appointment with Noor and can't be quoted in chat (never a price) |
| `do you do embroidery?` | ask_owner (not in the material), which then shows up in Noor's inbox |
