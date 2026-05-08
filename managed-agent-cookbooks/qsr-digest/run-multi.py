#!/usr/bin/env python3
"""
QSR Digest — multi-agent runner.

Architecture:
  coordinator      orchestrates the pipeline, emits LOG lines
  └─ sector-reader runs 8 web searches, writes /out/raw_results.json
  └─ classifier    classifies results using knowledge base, writes /out/findings.json
  └─ note-writer   reads findings.json, builds Word doc

Usage:
  python3 run-multi.py          # run (reuse cached agents/env)
  python3 run-multi.py --reset  # fresh agents + env
  python3 run-multi.py --auth   # one-time Gmail OAuth setup
"""
import sys, json, re, pathlib, datetime, base64, email.message
import httpx, anthropic

COOKBOOK  = pathlib.Path(__file__).parent
ENV_FILE  = COOKBOOK.parent.parent / ".env"
ID_CACHE  = COOKBOOK / ".multi_ids.json"
OUT_DIR   = COOKBOOK / "out"
KB_DIR    = COOKBOOK / "knowledge-base"
BETA      = ["managed-agents-2026-04-01"]
MODEL     = "claude-opus-4-7"
TODAY     = datetime.date.today().strftime("%Y-%m-%d")

env_vars = dict(line.split("=", 1) for line in ENV_FILE.read_text().splitlines() if "=" in line)
API_KEY  = env_vars["ANTHROPIC_API_KEY"].strip()
client   = anthropic.Anthropic(api_key=API_KEY, timeout=httpx.Timeout(900.0, connect=10.0))


# ── Knowledge base ────────────────────────────────────────────────────────────

KB_FILES = [
    "Daniels Donuts.md",
    "LK Group.md",
    "GM vs Board Guide.md",
    "Research Priorities.md",
    "AU QSR Sector.md",
    "Krispy Kreme AU.md",
    "Donut King.md",
    "Brooklyn Donuts.md",
    "Collins Foods.md",
    "Queens Lane Capital.md",
]

def load_knowledge_base() -> str:
    sections = []
    for fname in KB_FILES:
        path = KB_DIR / fname
        if path.exists():
            text = path.read_text().strip()
            sections.append(f"### {fname.replace('.md', '')}\n{text}")
    return "\n\n".join(sections)

KB = load_knowledge_base()


# ── Agent system prompts ──────────────────────────────────────────────────────

COORDINATOR_PROMPT = f"""You are the LK Group QSR digest coordinator for Daniels Donuts. Today is {TODAY}.

You orchestrate three specialist subagents in sequence. Emit the exact LOG lines shown — they drive the live display.

---

## STAGE 1 — SEARCH

Emit:
LOG:STAGE:1:Searching — delegating to sector-reader subagent

Call the sector-reader subagent with this message:
"Run all 9 AU QSR searches for {TODAY}. Write results to /out/raw_results.json."

Wait for it to complete. Then emit:
LOG:STAGE:1:DONE:Raw results written to /out/raw_results.json

---

## STAGE 2 — CLASSIFY

Emit:
LOG:STAGE:2:Classifying — delegating to classifier subagent

Call the classifier subagent with this message:
"Read /out/raw_results.json. Classify all items using the knowledge base. Write classified items to /out/findings.json."

Wait for it to complete. Then emit:
LOG:STAGE:2:DONE:N items — H HIGH PRIORITY, M NORMAL

(Replace N, H, M with the actual counts the classifier reports back.)

---

## STAGE 3 — WRITE DOCUMENT

Emit:
LOG:STAGE:3:Writing — delegating to note-writer subagent

Call the note-writer subagent with this message:
"Read /out/findings.json. Build the Word digest document. Save to /out/qsr-digest-{TODAY}.docx."

Wait for it to complete. Then emit:
LOG:STAGE:3:DONE:/out/qsr-digest-{TODAY}.docx

---

Complete all three stages in order. Do not skip any stage.
"""

SECTOR_READER_PROMPT = f"""You are the research agent for the LK Group QSR digest. Today is {TODAY}.

Run ALL 9 of these web searches — do not skip any:

1. web_search("Krispy Kreme Australia 2026")
2. web_search("Donut King Retail Food Group Australia 2026")
3. web_search("Collins Foods ASX CKF Australia 2026")
4. web_search("Brooklyn Donuts Australia 2026")
5. web_search("Australia fast food QSR wage labour 2026")
6. web_search("Uber Eats DoorDash Australia fees 2026")
7. web_search("Australia donut doughnut new opening 2026")
8. web_search("Daniels Donuts LK Group Australia 2026")
9. web_search("new doughnut donut brand Australia Singapore international 2026")

After all 9 searches, collect results that mention Australia and have a real URL.
Do NOT filter by date — include anything from the last 90 days. Let the classifier decide relevance.
Limit to a maximum of 15 raw results — take the most recent and most relevant ones only.

Write the results to /out/raw_results.json using bash:
bash: mkdir -p /out && python3 -c "import json; data = [...]; open('/out/raw_results.json','w').write(json.dumps(data, indent=2))"

Each item in the JSON array:
{{
  "headline": "...",
  "summary": "2-3 sentences",
  "source_url": "https://...",
  "source_name": "...",
  "date": "DD Mon YYYY",
  "companies_mentioned": ["..."]
}}

After writing the file, report back: "Search complete. N items written to /out/raw_results.json."
"""

CLASSIFIER_PROMPT = f"""You are the audience classifier for the LK Group QSR digest.

Read /out/raw_results.json using bash: bash: cat /out/raw_results.json

Apply these classification rules to every item:

## Audience
- GM: operational, day-to-day, costs, staff, local competition
- Board: strategic, M&A, financial markets, major competitor moves, regulatory
- Both: items that are both operationally and strategically significant

## Priority
- HIGH: directly matches a standing research priority (delivery fees, wage changes, competitor expansion, new entrants, donut sector openings)
- NORMAL: relevant but not an immediate strategic or operational flag

## Source filter
- Accept: ASX filings, AFR, The Australian, SMH, Reuters, Bloomberg, Inside Retail, QSR Media, Fair Work, government bodies, official company pages, broker research, trade publications, industry newsletters
- Reject ONLY: anonymous blogs with no author, pure social media posts, spam sites

## Geography filter
- Prefer Australian items. Also include international items (Singapore, US, UK) if they involve a brand that operates or is expanding into Australia — these are competitive intelligence.
- When in doubt, INCLUDE the item as NORMAL priority rather than cutting it.

## Calibration
Target 6-10 items per digest — hard cap at 10. Pick the most actionable items.
A new international donut brand opening in Australia is HIGH priority even if the source is a trade publication.
Include items from the last 90 days — not just 30.

## Knowledge base
Use this to calibrate classifications — these are authoritative facts about the client:

{KB}

---

After classifying, write ALL items to /out/findings.json using bash:
bash: python3 -c "import json; data = [...]; open('/out/findings.json','w').write(json.dumps(data, indent=2))"

Each item in the JSON array:
{{
  "headline": "...",
  "audience": "GM|Board|Both",
  "priority": "HIGH|NORMAL",
  "summary": "2-3 sentences",
  "why": "one sentence — name the implication for Daniels Donuts specifically",
  "source_name": "...",
  "url": "https://...",
  "date": "DD Mon YYYY"
}}

After writing, report back: "Classification complete. N items (H HIGH, M NORMAL) written to /out/findings.json."
"""

NOTE_WRITER_PROMPT = f"""You are the document writer for the LK Group QSR digest. Today is {TODAY}.

Read /out/findings.json using bash: bash: cat /out/findings.json

Then build a Word document using python-docx. Install if needed: pip install -q python-docx

Document structure:
- Header: LK Group — QSR Intelligence Digest | {TODAY} | N items (H HIGH PRIORITY)
- Sort: HIGH first, then NORMAL. Within each tier: Both → Board → GM
- Each item: headline, [audience] label, ★ HIGH PRIORITY if applicable, summary (2-3 sentences), "Why it matters:" line, source name + URL, date
- Missing URL → bold [UNSOURCED]
- Item older than 30 days → [DATED — verify still current]

Save to: /out/qsr-digest-{TODAY}.docx

After saving, report back: "Document complete. Saved to /out/qsr-digest-{TODAY}.docx"

If asked to output /out/findings.json, run: bash: cat /out/findings.json
and return the raw JSON content only, with no surrounding text.
"""


# ── Logging ───────────────────────────────────────────────────────────────────

def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")

def log(msg, icon="   "):
    print(f"[{ts()}] {icon}  {msg}", flush=True)

def banner(text, char="─"):
    width = 62
    print(f"\n{char*width}", flush=True)
    print(f"  {text}", flush=True)
    print(f"{char*width}", flush=True)

def stage_banner(n, title):
    icons = {1: "🔍", 2: "🧠", 3: "✍️"}
    print(f"\n{'═'*62}", flush=True)
    print(f"  {icons.get(n,'▶')}  STAGE {n} — {title.upper()}", flush=True)
    print(f"{'═'*62}", flush=True)


# ── Agent + environment ───────────────────────────────────────────────────────

def load_cache():
    return json.loads(ID_CACHE.read_text()) if ID_CACHE.exists() else {}

def save_cache(data):
    ID_CACHE.write_text(json.dumps(data, indent=2))

def create_agents():
    log("Creating subagents...", "🤖")

    sector_reader = client.beta.agents.create(
        name="qsr-sector-reader",
        model=MODEL,
        system=SECTOR_READER_PROMPT,
        tools=[{"type": "agent_toolset_20260401",
                "default_config": {"enabled": False},
                "configs": [
                    {"name": "web_search", "enabled": True},
                    {"name": "bash",       "enabled": True},
                ]}],
        betas=BETA,
    )
    log(f"sector-reader:  {sector_reader.id}", "✅")

    classifier = client.beta.agents.create(
        name="qsr-classifier",
        model=MODEL,
        system=CLASSIFIER_PROMPT,
        tools=[{"type": "agent_toolset_20260401",
                "default_config": {"enabled": False},
                "configs": [
                    {"name": "bash", "enabled": True},
                    {"name": "read", "enabled": True},
                ]}],
        betas=BETA,
    )
    log(f"classifier:     {classifier.id}", "✅")

    note_writer = client.beta.agents.create(
        name="qsr-note-writer",
        model=MODEL,
        system=NOTE_WRITER_PROMPT,
        tools=[{"type": "agent_toolset_20260401",
                "default_config": {"enabled": False},
                "configs": [
                    {"name": "bash",  "enabled": True},
                    {"name": "read",  "enabled": True},
                    {"name": "write", "enabled": True},
                ]}],
        betas=BETA,
    )
    log(f"note-writer:    {note_writer.id}", "✅")

    coordinator = client.beta.agents.create(
        name="qsr-digest-coordinator",
        model=MODEL,
        system=COORDINATOR_PROMPT,
        tools=[{"type": "agent_toolset_20260401",
                "default_config": {"enabled": False},
                "configs": []}],
        multiagent={
            "type": "coordinator",
            "agents": [
                {"type": "agent", "id": sector_reader.id},
                {"type": "agent", "id": classifier.id},
                {"type": "agent", "id": note_writer.id},
            ],
        },
        betas=BETA,
    )
    log(f"coordinator:    {coordinator.id}", "✅")

    return {
        "coordinator_id":   coordinator.id,
        "sector_reader_id": sector_reader.id,
        "classifier_id":    classifier.id,
        "note_writer_id":   note_writer.id,
    }

def create_environment():
    log("Creating cloud environment (installing python-docx)...", "📦")
    env = client.beta.environments.create(
        name=f"qsr-multi-{TODAY}-{datetime.datetime.now().strftime('%H%M%S')}",
        config={
            "type": "cloud",
            "packages": {"pip": ["python-docx"]},
            "networking": {"type": "unrestricted"},
        },
        betas=BETA,
    )
    log(f"Environment:    {env.id}", "✅")
    return env.id


# ── Session runner ────────────────────────────────────────────────────────────

def run(coordinator_id, env_id):
    OUT_DIR.mkdir(exist_ok=True)
    banner(f"QSR Digest (multi-agent) — {TODAY}", "─")

    session = client.beta.sessions.create(
        agent={"id": coordinator_id, "type": "agent"},
        environment_id=env_id,
        title=f"QSR Digest Multi {TODAY}",
        betas=BETA,
    )
    log(f"Session:        {session.id}", "🔑")

    client.beta.sessions.events.send(
        session.id,
        events=[{"type": "user.message", "content": [{"type": "text",
            "text": f"Today is {TODAY}. Run the full QSR digest pipeline."}]}],
        betas=BETA,
    )

    agent_replied  = False
    stage2_summary = ""
    stage3_done    = False
    findings_json  = None

    def _send_msg(sid, msg):
        client.beta.sessions.events.send(
            sid,
            events=[{"type": "user.message", "content": [{"type": "text", "text": msg}]}],
            betas=BETA,
        )

    try:
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
                log(inp.get("query", "")[:72], "🌐")
            elif name == "bash":
                cmd = inp.get("command", "")
                if "pip install" in cmd:
                    log("Installing python-docx", "📦")
                elif "findings.json" in cmd and "cat" in cmd:
                    log("Reading findings from container", "📥")
                elif "findings.json" in cmd:
                    log("Classifier writing findings.json", "💾")
                elif "raw_results.json" in cmd:
                    log("Sector-reader writing raw_results.json", "💾")
                elif "python" in cmd:
                    log("Running document builder", "⚙️ ")
                else:
                    log(cmd[:70], "🐚")
            elif name == "write":
                log(f"Writing {inp.get('file_path','').split('/')[-1]}", "📝")

            elif etype == "agent.message" and text:
                agent_replied = True

                # Capture findings JSON if returned by the retrieval step
                stripped = text.strip()
                if stripped.startswith("[") and '"headline"' in stripped:
                    try:
                        findings_json = json.loads(stripped)
                        log(f"Findings captured: {len(findings_json)} items", "✅")
                        continue
                    except Exception:
                        pass
                if findings_json is None and '"headline"' in text:
                    m = re.search(r'(\[[\s\S]*?\])', text)
                    if m:
                        try:
                            findings_json = json.loads(m.group(1))
                            log(f"Findings captured: {len(findings_json)} items", "✅")
                            continue
                        except Exception:
                            pass

                for line in text.splitlines():
                    s = line.strip()
                    if s.startswith("LOG:STAGE:"):
                        parts     = s.split(":", 3)
                        stage_num = int(parts[2]) if parts[2].isdigit() else 0
                        detail    = parts[3] if len(parts) > 3 else ""
                        if "DONE" not in detail:
                            stage_banner(stage_num, detail)
                        else:
                            done_text = detail.replace("DONE:", "").strip()
                            log(done_text, "✅")
                            if stage_num == 2:
                                stage2_summary = done_text
                            elif stage_num == 3:
                                stage3_done = True
                    elif s and not s.startswith("LOG:") and s != "[empty message]":
                        log(s[:100], "💬")

            elif etype in ("session.status_idle", "session.status_complete"):
                if not agent_replied:
                    continue
                if stage3_done and findings_json is None:
                    stage3_done = False
                    log("Retrieving findings from container...", "📥")
                    _send_msg(session.id,
                        "Ask your note-writer subagent to run this bash command and relay "
                        "the output back to me as raw JSON only, with no other text:\n"
                        "cat /out/findings.json")
                elif findings_json is not None:
                    log("All data captured — complete", "✅")
                    break
                else:
                    log("Complete", "✅")
                    break
            elif etype == "session.status_failed":
                log("Session FAILED", "❌")
                break

    except Exception:
        if agent_replied:
            log("Complete (stream closed)", "✅")
        else:
            s = client.beta.sessions.retrieve(session.id, betas=BETA)
            log(f"Stream dropped — session status: {getattr(s, 'status', 'unknown')}", "⚠️")

    banner("Output", "─")
    log("Digest complete — Word doc built in session container", "📄")

    return {"summary": stage2_summary, "findings": findings_json or []}


# ── Gmail draft (shared with run-single.py logic) ─────────────────────────────

def gmail_draft(result: dict):
    creds_path = COOKBOOK / "gmail-credentials.json"
    token_path = COOKBOOK / "gmail-token.json"

    if not creds_path.exists():
        log("Gmail not configured — run with --auth to set up", "📧")
        return

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        log("Run: pip install google-auth-oauthlib google-api-python-client", "⚠️")
        return

    SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
    creds  = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json())
        else:
            log("Token missing or expired — run with --auth to re-authenticate", "⚠️")
            return

    service  = build("gmail", "v1", credentials=creds)
    to_email = env_vars.get("DIGEST_TO_EMAIL", "").strip()
    if not to_email:
        log("DIGEST_TO_EMAIL not set in .env — skipping Gmail draft", "⚠️")
        return

    summary  = result.get("summary", "")
    findings = result.get("findings", [])

    if not findings:
        log("No findings to email — check terminal output", "⚠️")
        return

    high   = sorted([f for f in findings if f.get("priority","").upper() == "HIGH"],
                    key=lambda f: {"Both":0,"Board":1,"GM":2}.get(f.get("audience",""),3))
    normal = sorted([f for f in findings if f.get("priority","").upper() != "HIGH"],
                    key=lambda f: {"Both":0,"Board":1,"GM":2}.get(f.get("audience",""),3))

    n_total, n_high = len(findings), len(high)

    def fmt_item(f, star):
        src = f"{f.get('source_name','')} — {f.get('url','')}" if f.get("url") else f"[UNSOURCED] {f.get('source_name','')}"
        lines = [
            f"{'★ HIGH PRIORITY' if star else '•'}",
            f"[{f.get('audience','')}] {f.get('headline','')}",
            f"→ {f.get('why','')}" if f.get("why") else "",
            f"   {f.get('summary','')}" if f.get("summary") else "",
            f"   Source: {src}",
            f"   {f.get('date','')}" if f.get("date") else "",
            "",
        ]
        return "\n".join(l for l in lines if l != "")

    body_lines = [
        "LK Group — QSR Intelligence Digest",
        f"{TODAY}  |  Daniels Donuts  |  {n_total} items  |  {n_high} HIGH PRIORITY",
        "Sources: Public — ASX filings, news, public broker research",
        "Review and send to relevant stakeholders. Do not forward without review.",
        "=" * 65, "",
    ]
    if high:
        body_lines += ["★ HIGH PRIORITY", "─" * 65, ""]
        for f in high:
            body_lines.append(fmt_item(f, True))
    if normal:
        body_lines += ["• NORMAL", "─" * 65, ""]
        for f in normal:
            body_lines.append(fmt_item(f, False))

    board_items = [f for f in findings if f.get("audience") in ("Board","Both")]
    gm_items    = [f for f in findings if f.get("audience") in ("GM","Both")]

    body_lines += ["", "─" * 65, "FOR THE BOARD", "─" * 65]
    for f in board_items:
        body_lines.append(f"  {f.get('headline','')[:90]}")
    body_lines += ["", "─" * 65, "FOR THE GM", "─" * 65]
    for f in gm_items:
        body_lines.append(f"  {f.get('headline','')[:90]}")
    body_lines += [
        "", "─" * 65,
        "Generated by LK Group QSR Digest Agent (multi-agent) · Powered by Anthropic Claude",
        "This is a draft — review items above and send to distribute, or discard to suppress.",
    ]

    msg = email.message.EmailMessage()
    msg["To"]      = to_email
    msg["From"]    = to_email
    msg["Subject"] = f"LK Group QSR Digest — {TODAY} — {n_total} items ({n_high} HIGH)"
    msg.set_content("\n".join(body_lines))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    log(f"Gmail draft created → {to_email}  ({n_total} items)", "📧")


def gmail_auth():
    creds_path = COOKBOOK / "gmail-credentials.json"
    token_path = COOKBOOK / "gmail-token.json"
    if not creds_path.exists():
        print(f"\nMissing: {creds_path}")
        sys.exit(1)
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Run: pip install google-auth-oauthlib google-api-python-client")
        sys.exit(1)
    SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
    flow   = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds  = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    print(f"✅  Token saved to {token_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--auth" in sys.argv:
        gmail_auth()
        sys.exit(0)

    reset = "--reset" in sys.argv
    if reset and ID_CACHE.exists():
        ID_CACHE.unlink()
        log("Cache cleared", "🗑️")

    cache = load_cache()

    # Create all 4 agents if any are missing
    if not all(cache.get(k) for k in ("coordinator_id","sector_reader_id","classifier_id","note_writer_id")):
        ids = create_agents()
        cache.update(ids)
        save_cache(cache)

    if not cache.get("env_id"):
        cache["env_id"] = create_environment()
        save_cache(cache)

    log(f"Coordinator:    {cache['coordinator_id']}", "💾")
    log(f"Sector-reader:  {cache['sector_reader_id']}", "💾")
    log(f"Classifier:     {cache['classifier_id']}", "💾")
    log(f"Note-writer:    {cache['note_writer_id']}", "💾")
    log(f"Environment:    {cache['env_id']}", "💾")

    result = run(cache["coordinator_id"], cache["env_id"])
    gmail_draft(result)
