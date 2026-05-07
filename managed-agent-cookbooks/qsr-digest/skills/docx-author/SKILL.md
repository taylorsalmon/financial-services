---
name: docx-author
description: Produce a formatted Word document (.docx) on disk for the QSR weekly digest. Use instead of pptx-author — digest format is better suited to Word for GM and Board review.
---

# docx-author

Produces `./out/qsr-digest-[date].docx` from classified research items. This is the final output of the digest pipeline.

## Output Contract

- Write to `./out/qsr-digest-[date].docx` (date format: YYYY-MM-DD)
- Return the relative path in your final message so the orchestration layer can collect it
- Create `./out/` if it does not exist

## How to Build the Document

Write a short Python script and run it with Bash. Use `python-docx`.
First ensure it is installed: run `pip install -q python-docx` via Bash before executing the script.

```python
from docx import Document
from docx.shared import Pt, RGBColor
from datetime import date

doc = Document()

# Title
doc.add_heading(f"LK Group — QSR Intelligence Digest", 0)
doc.add_paragraph(f"Week of {date.today().strftime('%d %B %Y')}")
doc.add_paragraph("Prepared for: General Manager / Board | Daniels Donuts")
doc.add_paragraph("Sources: Public — ASX filings, news, public broker research")
doc.add_paragraph("")

# For each classified item:
for item in classified_items:
    # Audience badge + priority
    label = f"[{item['audience']}]"
    if item['priority'] == 'HIGH':
        label += " ★ HIGH PRIORITY"

    doc.add_heading(item['headline'], level=2)
    p = doc.add_paragraph()
    p.add_run(label).bold = True
    doc.add_paragraph(item['summary'])
    doc.add_paragraph(f"Why it matters: {item['why_it_matters']}")
    doc.add_paragraph(f"Source: {item['source_name']} — {item['source_url']}")
    doc.add_paragraph(f"Date: {item['date']}")
    doc.add_paragraph("")

doc.save(f"./out/qsr-digest-{date.today()}.docx")
```

## Document Structure

```
LK Group — QSR Intelligence Digest
Week of [date]
Prepared for: General Manager / Board | Daniels Donuts
─────────────────────────────────────────────────────

[HIGH PRIORITY items first, then NORMAL]

For each item:
  Headline
  [GM / Board / Both] ★ HIGH PRIORITY (if applicable)
  Summary (2–3 sentences)
  Why it matters: [one sentence, Daniels Donuts specific]
  Source: [name — URL]
  Date: [publication date]
```

## Conventions

- HIGH PRIORITY items appear first regardless of audience
- Within each priority tier: Both → Board → GM ordering
- Every item must have a source URL — no unsourced items in the final doc
- Flag any [UNSOURCED] items to the orchestrator rather than including them

## When NOT to Use

If `mcp__office__word_*` tools are available (Cowork plugin mode), use those instead — they drive the user's live Word document with review checkpoints. This skill is the file-producing version for headless managed-agent runs.
