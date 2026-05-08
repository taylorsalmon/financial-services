#!/usr/bin/env python3
"""
QSR Digest — single managed agent runner.

Usage:
  python3 run-single.py          # run (reuse cached agent/env)
  python3 run-single.py --reset  # fresh agent + env
  python3 run-single.py --auth   # one-time Gmail OAuth setup
"""
import sys, json, pathlib, datetime, base64, email.message
import httpx, anthropic

COOKBOOK = pathlib.Path(__file__).parent
ENV_FILE = COOKBOOK.parent.parent / ".env"
ID_CACHE = COOKBOOK / ".single_ids.json"
OUT_DIR  = COOKBOOK / "out"
KB_DIR   = COOKBOOK / "knowledge-base"
BETA     = ["managed-agents-2026-04-01"]
MODEL    = "claude-opus-4-7"
TODAY    = datetime.date.today().strftime("%Y-%m-%d")

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


# ── System prompt (loaded from agent orchestrator + knowledge base) ───────────

ORCHESTRATOR = (COOKBOOK / "agents" / "qsr-digest-orchestrator.md").read_text()

SYSTEM_PROMPT = (
    ORCHESTRATOR
    + f"\n\n---\n\n## KNOWLEDGE BASE\n\n"
    + "Use this intelligence — do not re-research these facts, they are authoritative.\n\n"
    + KB
)


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

def create_agent():
    log("Creating managed agent...", "🤖")
    agent = client.beta.agents.create(
        name="qsr-digest-single",
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
    log(f"Agent:       {agent.id}", "✅")
    return agent.id

def create_environment():
    log("Creating cloud environment (installing python-docx)...", "📦")
    env = client.beta.environments.create(
        name=f"qsr-digest-{TODAY}-{datetime.datetime.now().strftime('%H%M%S')}",
        config={
            "type": "cloud",
            "packages": {"pip": ["python-docx"]},
            "networking": {"type": "unrestricted"},
        },
        betas=BETA,
    )
    log(f"Environment: {env.id}", "✅")
    return env.id


# ── Session runner ────────────────────────────────────────────────────────────

def run(agent_id, env_id):
    OUT_DIR.mkdir(exist_ok=True)
    banner(f"QSR Digest — {TODAY}  |  agent: {agent_id[:24]}…", "─")

    session = client.beta.sessions.create(
        agent={"id": agent_id, "type": "agent"},
        environment_id=env_id,
        title=f"QSR Digest {TODAY}",
        betas=BETA,
    )
    log(f"Session:     {session.id}", "🔑")

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

    import re as _re

    def _send_msg(session_id, msg):
        client.beta.sessions.events.send(
            session_id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": msg}]}],
            betas=BETA,
        )

    def _retrieve_findings(session_id):
        """Send a bash command to print findings.json and capture it."""
        log("Retrieving findings from container...", "📥")
        _send_msg(session_id,
            "Run this bash command and output ONLY the raw JSON, nothing else:\n"
            "bash: cat /out/findings.json")

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
                    log("Installing python-docx in container", "📦")
                elif "findings.json" in cmd and "cat" in cmd:
                    log("Reading findings from container", "📥")
                elif "findings.json" in cmd:
                    log("Writing findings.json", "💾")
                elif "python" in cmd:
                    log("Running document builder", "⚙️ ")
                else:
                    log(cmd[:70], "🐚")
            elif name == "write":
                log(f"Writing {inp.get('file_path','').split('/')[-1]}", "📝")

            elif etype == "agent.message" and text:
                agent_replied = True
                # Check for JSON payload (findings retrieval response)
                stripped = text.strip()
                if stripped.startswith("[") and '"headline"' in stripped:
                    try:
                        findings_json = __import__("json").loads(stripped)
                        log(f"Findings captured: {len(findings_json)} items", "✅")
                        continue
                    except Exception:
                        pass
                # Also try extracting JSON from within the text
                if findings_json is None and '"headline"' in text:
                    m = _re.search(r'(\[[\s\S]*\])', text)
                    if m:
                        try:
                            findings_json = __import__("json").loads(m.group(1))
                            log(f"Findings captured: {len(findings_json)} items", "✅")
                            continue
                        except Exception:
                            pass

                for line in text.splitlines():
                    s = line.strip()
                    if s.startswith("LOG:STAGE:"):
                        parts = s.split(":", 3)
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
                    elif s and not s.startswith("LOG:"):
                        log(s[:100], "💬")

            elif etype in ("session.status_idle", "session.status_complete"):
                if not agent_replied:
                    continue
                if stage3_done and findings_json is None:
                    # Stage 3 done but no JSON yet — retrieve it
                    stage3_done = False  # prevent re-triggering
                    _retrieve_findings(session.id)
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


# ── Gmail draft ───────────────────────────────────────────────────────────────

def gmail_draft(result: dict):
    creds_path = COOKBOOK / "gmail-credentials.json"
    token_path = COOKBOOK / "gmail-token.json"

    if not creds_path.exists():
        log("Gmail not configured — run with --auth to set up (see GMAIL_SETUP.md)", "📧")
        return

    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        log("Run: pip install google-auth-oauthlib google-api-python-client", "⚠️")
        return

    SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json())
        else:
            log("Token missing or expired — run with --auth to re-authenticate", "⚠️")
            return

    service = build("gmail", "v1", credentials=creds)
    to_email = env_vars.get("DIGEST_TO_EMAIL", "").strip()
    if not to_email:
        log("DIGEST_TO_EMAIL not set in .env — skipping Gmail draft", "⚠️")
        return

    summary  = result.get("summary", "")
    findings = result.get("findings", [])

    if not findings:
        log("No findings to email — check terminal output", "⚠️")
        return

    high   = [f for f in findings if f.get("priority", "").upper() == "HIGH"]
    normal = [f for f in findings if f.get("priority", "").upper() != "HIGH"]

    n_total = len(findings)
    n_high  = len(high)

    def sort_key(f):
        order = {"Both": 0, "Board": 1, "GM": 2}
        return order.get(f.get("audience", ""), 3)

    high.sort(key=sort_key)
    normal.sort(key=sort_key)

    def fmt_item(f, star):
        headline = f.get("headline", "")
        audience = f.get("audience", "")
        summ     = f.get("summary", "")
        why      = f.get("why", "")
        src_name = f.get("source_name", "")
        url      = f.get("url", "")
        date     = f.get("date", "")
        source_line = f"{src_name} — {url}" if url else f"[UNSOURCED] {src_name}"
        prefix = "★" if star else "•"
        out = [f"{prefix} HIGH PRIORITY" if star else "•",
               f"[{audience}] {headline}",
               f"→ {why}" if why else "",
               f"   {summ}" if summ else "",
               f"   Source: {source_line}",
               f"   {date}" if date else "",
               ""]
        return "\n".join(l for l in out if l != "")

    lines = [
        "LK Group — QSR Intelligence Digest",
        f"{TODAY}  |  Daniels Donuts  |  {n_total} items  |  {n_high} HIGH PRIORITY",
        "Sources: Public — ASX filings, news, public broker research",
        "Review and send to relevant stakeholders. Do not forward without review.",
        "=" * 65,
        "",
    ]

    if high:
        lines += ["★ HIGH PRIORITY", "─" * 65, ""]
        for f in high:
            lines.append(fmt_item(f, True))

    if normal:
        lines += ["• NORMAL", "─" * 65, ""]
        for f in normal:
            lines.append(fmt_item(f, False))

    # Board summary
    board_items = [f for f in findings if f.get("audience") in ("Board", "Both")]
    gm_items    = [f for f in findings if f.get("audience") in ("GM", "Both")]

    lines += ["", "─" * 65, "FOR THE BOARD", "─" * 65]
    for f in board_items:
        lines.append(f"  {f.get('headline','')[:90]}")
    lines += ["", "─" * 65, "FOR THE GM", "─" * 65]
    for f in gm_items:
        lines.append(f"  {f.get('headline','')[:90]}")

    lines += [
        "",
        "─" * 65,
        f"Generated by LK Group QSR Digest Agent · Powered by Anthropic Claude",
        "This is a draft — review items above and send to distribute, or discard to suppress.",
    ]

    body = "\n".join(lines)

    msg = email.message.EmailMessage()
    msg["To"]      = to_email
    msg["From"]    = to_email
    msg["Subject"] = f"LK Group QSR Digest — {TODAY} — {n_total} items ({n_high} HIGH)"
    msg.set_content(body)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    log(f"Gmail draft created → {to_email}  ({n_total} items)", "📧")


def gmail_auth():
    """One-time OAuth flow — saves gmail-token.json."""
    creds_path = COOKBOOK / "gmail-credentials.json"
    token_path = COOKBOOK / "gmail-token.json"
    if not creds_path.exists():
        print(f"\nMissing: {creds_path}")
        print("Follow GMAIL_SETUP.md to download credentials.json from Google Cloud.\n")
        sys.exit(1)
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Run: pip install google-auth-oauthlib google-api-python-client")
        sys.exit(1)
    SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    print(f"✅  Token saved to {token_path}")
    print("You're set — run without --auth to produce the digest.")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--auth" in sys.argv:
        gmail_auth()
        sys.exit(0)

    reset = "--reset" in sys.argv
    if reset and ID_CACHE.exists():
        ID_CACHE.unlink()
        log("Cache cleared", "🗑️")

    cache    = load_cache()
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

    log(f"Agent:       {agent_id}", "💾")
    log(f"Environment: {env_id}", "💾")

    result = run(agent_id, env_id)
    gmail_draft(result)
