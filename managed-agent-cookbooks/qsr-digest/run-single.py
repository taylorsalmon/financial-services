#!/usr/bin/env python3
"""
QSR Digest — single managed agent runner.
One agent: searches, classifies, writes the Word doc.

Usage:
  python3 run-single.py          # run (reuse cached agent/env)
  python3 run-single.py --reset  # delete cache, create fresh agent + env
"""
import sys, json, pathlib, datetime, httpx
import anthropic

COOKBOOK   = pathlib.Path(__file__).parent
ENV_FILE   = COOKBOOK.parent.parent / ".env"
ID_CACHE   = COOKBOOK / ".single_ids.json"
OUT_DIR    = COOKBOOK / "out"
BETA       = ["managed-agents-2026-04-01"]
MODEL      = "claude-opus-4-7"
TODAY      = datetime.date.today().strftime("%Y-%m-%d")
NOW        = datetime.datetime.now().strftime("%H%M%S")

env = dict(line.split("=", 1) for line in ENV_FILE.read_text().splitlines() if "=" in line)
API_KEY = env["ANTHROPIC_API_KEY"].strip()
client = anthropic.Anthropic(api_key=API_KEY, timeout=httpx.Timeout(900.0, connect=10.0))

SYSTEM_PROMPT = """You are the LK Group QSR intelligence analyst. You do three things in sequence:

## STEP 1 — SEARCH
Run all 8 of these web searches. Do not skip any.

1. web_search("Krispy Kreme Australia 2026")
2. web_search("Donut King Retail Food Group Australia 2026")
3. web_search("Collins Foods ASX CKF Australia 2026")
4. web_search("Brooklyn Donuts Australia 2026")
5. web_search("Australia fast food QSR wage labour 2026")
6. web_search("Uber Eats DoorDash Australia fees 2026")
7. web_search("Australia donut doughnut new opening 2026")
8. web_search("Daniels Donuts LK Group Australia 2026")

Collect every relevant result. Only keep items about Australia from the last 30 days with a real URL.

## STEP 2 — CLASSIFY
For each item, assign:
- audience: GM, Board, or Both
  - Board: strategic, financial, market structure, M&A, investor sentiment
  - GM: operational, staffing, delivery platforms, local competitor moves
  - Both: directly affects both day-to-day ops AND board-level strategy
- priority: HIGH or NORMAL
  - HIGH: competitor expansion, delivery fee changes, labour cost changes, new donut concepts
  - NORMAL: general sector background
- why_it_matters: one sentence specific to Daniels Donuts. Name the implication, not the observation.

Reject items with no real URL. Reject US-only items.

## STEP 3 — WRITE DOCUMENT
Write a Word document using python-docx via bash. Save to ./out/qsr-digest-DATE.docx

The document must have:
- Header: "LK Group — QSR Intelligence Digest | DATE | N items (H HIGH PRIORITY)"
- Items sorted: HIGH PRIORITY first, then NORMAL. Within each tier: Both → Board → GM
- Each item shows: headline, [audience] label, ★ HIGH PRIORITY if applicable, summary, "Why it matters:" line, source name + URL, date
- Any item missing a URL: bold [UNSOURCED]
- Any item older than 30 days: [DATED — verify still current]

Use this python-docx script as your starting point — run it via bash:

```python
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import json, datetime

doc = Document()
# ... build document from your classified items ...
doc.save('./out/qsr-digest-YYYY-MM-DD.docx')
print('Saved')
```

When done, output the file path on its own line.
"""


def log(msg, icon="  "):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {icon} {msg}", flush=True)


def load_cache():
    if ID_CACHE.exists():
        return json.loads(ID_CACHE.read_text())
    return {}


def save_cache(data):
    ID_CACHE.write_text(json.dumps(data, indent=2))


def create_agent():
    log("Creating managed agent...", "🤖")
    agent = client.beta.agents.create(
        name=f"qsr-digest-single",
        model=MODEL,
        system=SYSTEM_PROMPT,
        tools=[{
            "type": "agent_toolset_20260401",
            "default_config": {"enabled": False},
            "configs": [
                {"name": "web_search", "enabled": True},
                {"name": "bash",       "enabled": True},
                {"name": "write",      "enabled": True},
                {"name": "read",       "enabled": True},
            ],
        }],
        betas=BETA,
    )
    log(f"Agent: {agent.id}", "✅")
    return agent.id


def create_environment():
    log("Creating environment (installing python-docx)...", "📦")
    env = client.beta.environments.create(
        name=f"qsr-digest-env-{TODAY}-{NOW}",
        config={
            "type": "cloud",
            "packages": {"pip": ["python-docx"]},
            "networking": {"type": "unrestricted"},
        },
        betas=BETA,
    )
    log(f"Environment: {env.id}", "✅")
    return env.id


def run(agent_id, env_id):
    OUT_DIR.mkdir(exist_ok=True)

    print(f"\n{'─'*60}")
    print(f"  QSR Digest — {TODAY}")
    print(f"  Agent:       {agent_id}")
    print(f"  Environment: {env_id}")
    print(f"{'─'*60}\n")

    session = client.beta.sessions.create(
        agent={"id": agent_id, "type": "agent"},
        environment_id=env_id,
        title=f"QSR Digest {TODAY}",
        betas=BETA,
    )
    log(f"Session: {session.id}", "🔑")

    client.beta.sessions.events.send(
        session.id,
        events=[{"type": "user.message", "content": [{"type": "text",
            "text": f"Today is {TODAY}. Run the full QSR digest pipeline. Output to ./out/qsr-digest-{TODAY}.docx"}]}],
        betas=BETA,
    )
    log("Running pipeline...", "🏃")

    for event in client.beta.sessions.events.stream(session.id, betas=BETA, timeout=None):
        etype   = getattr(event, "type", "")
        name    = getattr(event, "name", "")
        inp     = getattr(event, "input", {}) or {}
        content = getattr(event, "content", None)
        text    = next(
            (getattr(b, "text", None) for b in (content or []) if getattr(b, "text", None)),
            None,
        )

        if name == "web_search":
            log(inp.get("query", "")[:80], "🌐")
        elif name == "bash":
            log(inp.get("command", "")[:70], "🐚")
        elif name == "write":
            log(inp.get("file_path", "").split("/")[-1], "✍️")
        elif etype == "agent.message" and text:
            snippet = text[:100].replace("\n", " ")
            log(snippet, "💬")
        elif etype == "session.status_complete":
            log("Complete", "✅")
            break
        elif etype == "session.status_failed":
            log("FAILED", "❌")
            break

    out = sorted(OUT_DIR.glob(f"qsr-digest-{TODAY}*.docx"))
    if out:
        log(f"Output: {out[-1]}", "📄")
    else:
        log("No .docx found in ./out/ — check session output above", "⚠️")


if __name__ == "__main__":
    reset = "--reset" in sys.argv

    if reset and ID_CACHE.exists():
        ID_CACHE.unlink()
        log("Cache cleared", "🗑️")

    cache = load_cache()
    agent_id = cache.get("agent_id")
    env_id   = cache.get("env_id")

    if not agent_id:
        agent_id = create_agent()
        cache["agent_id"] = agent_id
        save_cache(cache)

    if not env_id:
        env_id = create_environment()
        cache["env_id"] = env_id
        save_cache(cache)

    log(f"Using agent: {agent_id}", "💾")
    log(f"Using env:   {env_id}", "💾")

    run(agent_id, env_id)
