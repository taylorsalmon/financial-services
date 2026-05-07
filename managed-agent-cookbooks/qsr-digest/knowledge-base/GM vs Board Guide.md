---
tags: [classification, agent-context, digest]
---

# GM vs Board Guide

Used by the digest classifier subagent to label every research item. Each item gets one of: `GM`, `Board`, or `Both`.

## GM — General Manager
Operational, tactical, short-to-medium term. The GM needs this to make decisions in the next 1–3 months.

- Competitor store openings in key trade areas
- Labour cost or award rate changes
- Delivery platform terms or fee changes
- Supplier issues (flour, sugar, dairy)
- Local planning or permit developments
- Consumer sentiment and foot traffic data
- Digital / loyalty program moves by [[Krispy Kreme AU]], [[Donut King]], [[Brooklyn Donuts]]

## Board
Strategic, capital allocation, long-term. The Board needs this to govern and make investment decisions.

- Competitor fundraising, M&A, or ownership changes
- Market size and category growth data
- Franchisor strategy shifts (RFG / [[Donut King]], [[Krispy Kreme AU]])
- Macro consumer spending trends
- [[Collins Foods]] results (QSR bellwether)
- Regulatory or policy shifts affecting the category
- [[LK Group]] / [[Queens Lane Capital]] portfolio signals

## Both
Items with immediate operational implications AND strategic signal value.

- [[Krispy Kreme AU]] / Hungry Jack's partnership — channel threat (GM) + strategic shift (Board)
- [[Donut King]] 57% digital growth — operational benchmark (GM) + strategic risk (Board)
- Category closures (Mr Donut, Donut Papi) — competitive relief (GM) + market health signal (Board)

## Output Format
For every item in the digest:
```
**[GM / Board / Both]** — [one-line "why this matters for Daniels Donuts"]
```

## Related
- [[Research Priorities]]
- [[Daniels Donuts]]
- [[AU QSR Sector]]
