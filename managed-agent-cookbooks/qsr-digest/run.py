#!/usr/bin/env python3
"""
QSR Digest — managed-agent runner.

Usage:
  python3 run.py           # deploy (if needed) + run
  python3 run.py --deploy  # force a fresh deploy then run
  python3 run.py --run     # run only (skip deploy, use saved agent ID)
"""
import sys, subprocess, pathlib, datetime, json, httpx
import anthropic

REPO_ROOT  = pathlib.Path(__file__).parent.parent.parent   # financial-services/
COOKBOOK   = pathlib.Path(__file__).parent                  # qsr-digest/
ENV_FILE   = REPO_ROOT / ".env"
ID_CACHE   = COOKBOOK / ".agent_ids.json"                   # saved after deploy
OUT_DIR    = COOKBOOK / "out"
BETA       = ["managed-agents-2026-04-01"]

# The environment gives the agent access to ./knowledge-base/ and ./out/ at runtime.
# Set via .agent_ids.json after first deploy, or hardcode after creating a new environment.
# To create a new environment with the knowledge-base files, run:
#   python3 run.py --new-env
FALLBACK_ENV_ID = "env_01NxoF8FrmTk3UqE7v2iP3Ko"

# ── env -----------------------------------------------------------------
env = dict(
    line.split("=", 1) for line in ENV_FILE.read_text().splitlines() if "=" in line
)
API_KEY = env["ANTHROPIC_API_KEY"].strip()
client  = anthropic.Anthropic(api_key=API_KEY, timeout=httpx.Timeout(600.0, connect=10.0))

TODAY = datetime.date.today().strftime("%Y-%m-%d")
NOW   = datetime.datetime.now().strftime("%H%M%S")


# ── logging -------------------------------------------------------------
def log(msg, emoji=""):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {emoji+'  ' if emoji else '   '}{msg}", flush=True)


# ── deploy --------------------------------------------------------------
def deploy() -> str:
    """Run deploy-managed-agent.sh and return the new agent ID."""
    log("Deploying agents (this uploads skills + creates subagents)...", "🚀")
    script = REPO_ROOT / "scripts" / "deploy-managed-agent.sh"
    result = subprocess.run(
        ["bash", str(script), "qsr-digest"],
        capture_output=True, text=True,
        env={**__import__("os").environ, "ANTHROPIC_API_KEY": API_KEY},
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        sys.exit(f"Deploy failed (exit {result.returncode})")

    agent_id = None
    for line in result.stdout.splitlines():
        if line.startswith("agent id:"):
            agent_id = line.split(":", 1)[1].strip()

    if not agent_id:
        print(result.stdout)
        sys.exit("Deploy succeeded but could not parse agent ID from output")

    # Save for future --run calls
    cached = {}
    if ID_CACHE.exists():
        cached = json.loads(ID_CACHE.read_text())
    cached["agent_id"] = agent_id
    cached["deployed_at"] = datetime.datetime.now().isoformat()
    ID_CACHE.write_text(json.dumps(cached, indent=2))

    log(f"Agent ID: {agent_id}", "✅")
    return agent_id


def get_cached_agent_id() -> str | None:
    if not ID_CACHE.exists():
        return None
    return json.loads(ID_CACHE.read_text()).get("agent_id")


def get_env_id() -> str:
    if ID_CACHE.exists():
        cached_env = json.loads(ID_CACHE.read_text()).get("env_id")
        if cached_env:
            return cached_env
    return FALLBACK_ENV_ID


def create_environment() -> str:
    """Upload knowledge-base files to a new managed-agent environment and save the env_id."""
    log("Creating new environment and uploading knowledge-base files...", "📂")
    import os

    # POST /v1/environments — creates an empty managed environment
    import urllib.request, urllib.error
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/environments",
        data=json.dumps({}).encode(),
        headers={
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "managed-agents-2026-04-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            env = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Failed to create environment: {e.read().decode()}")

    env_id = env["id"]
    log(f"Environment created: {env_id}", "✅")

    # Upload knowledge-base files
    kb_dir = COOKBOOK / "knowledge-base"
    for f in sorted(kb_dir.glob("*.md")):
        upload_req = urllib.request.Request(
            f"https://api.anthropic.com/v1/environments/{env_id}/files/knowledge-base/{f.name}",
            data=f.read_bytes(),
            headers={
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "managed-agents-2026-04-01",
                "content-type": "text/plain",
            },
            method="PUT",
        )
        try:
            urllib.request.urlopen(upload_req)
            log(f"  Uploaded: {f.name}", "📄")
        except urllib.error.HTTPError as e:
            log(f"  Warning: could not upload {f.name}: {e.read().decode()}", "⚠️")

    # Save to cache
    cached = json.loads(ID_CACHE.read_text()) if ID_CACHE.exists() else {}
    cached["env_id"] = env_id
    ID_CACHE.write_text(json.dumps(cached, indent=2))
    return env_id


# ── run -----------------------------------------------------------------
def run(agent_id: str):
    OUT_DIR.mkdir(exist_ok=True)
    OUTFILE = f"./out/qsr-digest-{TODAY}-{NOW}.md"

    print(f"\n{'─'*60}\n  QSR Digest — {TODAY}\n  Agent: {agent_id}\n{'─'*60}")

    env_id = get_env_id()
    session = client.beta.sessions.create(
        agent={"id": agent_id, "type": "agent"},
        environment_id=env_id,
        title=f"QSR Digest {TODAY} {NOW}",
        betas=BETA,
    )
    log(f"Environment: {env_id}", "📂")
    log(f"Session: {session.id}", "🔑")

    client.beta.sessions.events.send(
        session.id,
        events=[{"type": "user.message", "content": [{"type": "text",
            "text": f"Today is {TODAY}. Run the QSR digest pipeline. Output file: {OUTFILE}"}]}],
        betas=BETA,
    )
    log("Pipeline running...", "🏃")

    for event in client.beta.sessions.events.stream(session.id, betas=BETA, timeout=600.0):
        etype   = getattr(event, "type", "")
        name    = getattr(event, "name", "")
        inp     = getattr(event, "input", {})
        content = getattr(event, "content", None)
        text    = next(
            (getattr(b, "text", None) for b in (content or []) if getattr(b, "text", None)),
            None,
        )

        if name == "web_search":
            query = inp.get("query", "") if isinstance(inp, dict) else ""
            log(query[:70], "🌐")
        elif name == "write":
            fname = inp.get("file_path", "").split("/")[-1] if isinstance(inp, dict) else ""
            log(fname, "✍️")
        elif name == "bash":
            cmd = inp.get("command", "")[:60] if isinstance(inp, dict) else ""
            log(cmd, "🐚")
        elif etype == "session.thread_created":
            log("Subagent called...", "🤖")
        elif etype == "agent.thread_message_received" and text:
            log(f"Subagent done: {text[:60].replace(chr(10), ' ')}", "📥")
        elif etype == "agent.message" and text:
            log(text[:100].replace("\n", " "), "🎯")
        elif etype == "session.status_idle":
            log("Session idle — waiting...", "⏳")
        elif etype == "session.status_complete":
            log("Done", "✅")
            break
        elif etype == "session.status_failed":
            log("FAILED", "❌")
            break

    docx_files = sorted(OUT_DIR.glob(f"qsr-digest-{TODAY}*.docx"))
    md_files   = sorted(OUT_DIR.glob(f"qsr-digest-{TODAY}*.md"))
    out_files  = docx_files or md_files
    if out_files:
        log(f"Output: {out_files[-1].name}", "📝")
    else:
        log("No output file found in ./out/", "⚠️")


# ── main ----------------------------------------------------------------
if __name__ == "__main__":
    force_deploy = "--deploy" in sys.argv
    run_only     = "--run"    in sys.argv
    new_env      = "--new-env" in sys.argv

    if new_env:
        create_environment()
        log("Environment ready. Run again without --new-env to execute the digest.", "✅")
        sys.exit(0)

    if run_only:
        agent_id = get_cached_agent_id()
        if not agent_id:
            sys.exit("No cached agent ID — run without --run to deploy first.")
    elif force_deploy or not get_cached_agent_id():
        agent_id = deploy()
    else:
        agent_id = get_cached_agent_id()
        log(f"Using cached agent ID: {agent_id}", "💾")

    run(agent_id)
