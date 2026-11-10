#!/usr/bin/env python3
"""My Work Log — turn a day's digest into polished accomplishment statements.

Usage:  python3 summarize.py --date 2026-11-09 [--save]
Uses the Claude CLI headless with NO tools (text in → JSON out). If Claude is not
available it falls back to the rule-based draft in server.py.
"""
import argparse, glob, json, os, re, shutil, subprocess, sys
from pathlib import Path

from common import HERE, IS_WIN, cfg

CFG = cfg()
MAX_DIGEST = 30000


def claude_bin():
    """Find the Claude Code CLI (also when cron / Task Scheduler runs with a minimal PATH)."""
    found = shutil.which("claude")
    if found:
        return found
    if IS_WIN:
        ad = os.environ.get("APPDATA", "")
        cands = [os.path.join(ad, "npm", "claude.cmd"), os.path.expanduser(r"~\.local\bin\claude.exe"),
                 os.path.expanduser(r"~\AppData\Local\Programs\claude\claude.exe")]
    else:
        cands = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/claude")))
        cands += [os.path.expanduser("~/.local/bin/claude"), "/usr/local/bin/claude", "/opt/homebrew/bin/claude"]
    return next((c for c in reversed(cands) if os.path.exists(c)), None)


def compact_digest(date):
    p = HERE / "digest" / f"{date}.md"
    if not p.exists():
        return None
    lines = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if re.search(r"\[(claude|opencode)-cmd\]", ln):
            ln = ln[:160]          # commands: keep a short hint only
        lines.append(ln[:400])
    text = "\n".join(lines)
    return text[:MAX_DIGEST] + ("\n…(truncated)" if len(text) > MAX_DIGEST else "")


def build_prompt(date, formatted, digest):
    o = CFG["owner"]
    his = o.get("pronoun") or "their"
    he = {"his": "he", "her": "she"}.get(his, "they")
    who = ", ".join(x for x in (o.get("role"), o.get("organization")) if x)
    vocab = "\n".join(f"- {v}" for v in CFG.get("vocabulary", [])) or "- (none)"
    labels = CFG.get("domain_labels") or ["Development", "Documentation", "Research", "Workstation"]
    example_label = re.split(r"\s*\(", labels[0])[0]
    person = (CFG.get("people") or ["a teammate"])[0]
    extra = "".join(f"\n- {r}" for r in CFG.get("ai_extra_rules", []))
    sheet = CFG["sheet"].get("name") or "work log"
    return f"""You write the daily work log of {o['name']}{f' ({who})' if who else ''}.
Below is a machine-collected activity digest for {formatted}. It contains ONLY {his} own actions
(browser visits, {his} git commits and git actions, files {he} opened/changed, VS Code edits,
prompts {he} gave to AI coding assistants, and commands they ran for {'them' if he == 'they' else ('him' if he == 'he' else 'her')}).

Turn it into a short list of polished, professional accomplishment statements for {his}
"{sheet}" sheet.

RULES
- Group related activity into ONE item per meaningful piece of work (typically 3–8 items). Merge fragments.
- Each item: a domain label, a short title, ONE polished engineering statement (1–2 sentences,
  past tense, strong verbs: Implemented, Refactored, Deployed, Fixed, Tested, Verified, Investigated,
  Configured, Logged, Documented, Released, Reviewed).
- Translate raw file edits/commands into business outcomes. Example:
  raw "modified patient-register.component.ts and checked print layout" →
  "Refactored the patient registration UI component and verified the clinical report print layout."
- Domain labels (use the most specific that fits): {", ".join(labels)}.{extra}
- Known vocabulary:
{vocab}
- ONLY {his} own work. Never credit or mention teammates' work as {his}. Mention a person only when {he}
  handed work to them or verified their fix (e.g. "assigned to {person}").
- NEVER include passwords, tokens, API keys, credentials, account emails, or private/personal browsing.
- Skip noise: logging into sites, generic searches, opening ChatGPT/Gemini/Claude, screenshots.
- SKIP entirely anything about this work log itself: the "{sheet}" sheet, the
  "{HERE.name}" folder, work-log summaries, Gemini/ChatGPT chats about the work log.
- Setting up AI tools (Claude/ChatGPT connectors, plugins, skills, MCP, Claude Code) is "Workstation"
  work, never a product domain — and only worth an item if substantial.
- Judge the domain from the CONTENT of the activity, not from the digest heading it appears under.
- Meetings whose topic is unknown → one item with domain "[Unspecified Activity]".
- If the digest is empty or has nothing work-related, return an empty items list.
- status: "Completed" unless the digest shows the work is clearly ongoing ("In Progress").
- Do not invent facts that are not supported by the digest.

Respond with ONLY a JSON object, no prose, no code fences:
{{"items":[{{"module":"{example_label}","action":"Short title","details":"Polished statement.","status":"Completed"}}]}}

DIGEST
{digest}
"""


def ai_items(date, formatted):
    digest = compact_digest(date)
    if digest is None:
        raise RuntimeError("no digest — run collect.py first")
    exe = claude_bin()
    if not exe:
        raise RuntimeError("claude CLI not found")
    cmd = [exe, "-p", "--tools", "", "--output-format", "json", "--no-session-persistence",
           "--model", CFG.get("automation", {}).get("ai_model", "sonnet")]
    env = dict(os.environ, PATH=os.path.dirname(exe) + os.pathsep + os.environ.get("PATH", os.defpath))
    r = subprocess.run(cmd, input=build_prompt(date, formatted, digest), capture_output=True, text=True,
                       encoding="utf-8", timeout=600, cwd=HERE, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"claude exited {r.returncode}: {(r.stderr or r.stdout)[-400:]}")
    result = json.loads(r.stdout).get("result", "")
    m = re.search(r"\{[\s\S]*\}", result)
    if not m:
        raise RuntimeError("no JSON in Claude reply")
    items = json.loads(m.group(0)).get("items", [])
    clean = []
    for it in items:
        d = {k: str(it.get(k, "")).strip() for k in ("module", "action", "details", "status")}
        if d["details"]:
            d["status"] = d["status"] or "Completed"
            clean.append(d)
    return clean


def summarize(date, save=False, ai_only=False):
    sys.path.insert(0, str(HERE))
    from server import build, draft, formatted, read_json
    try:
        items, source, note = ai_items(date, formatted(date)), "ai", "written by Claude"
    except Exception as e:  # fall back to the rule-based draft
        if ai_only:
            raise
        items, source, note = draft(date)["items"], "auto", f"AI unavailable ({e}); rule-based draft"
    out = build(date, items)
    out["source"] = source
    if save:
        p = HERE / "output" / f"{date}.json"
        prev = read_json(p) or {}
        for k, v in prev.items():                                  # keep sheet + email history
            if k.startswith(("pushed_", "emailed_")):
                out[k] = v
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out, note


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()
    out, note = summarize(a.date, a.save)
    print(f"[{out.get('source')}] {note}\n{out['work_summary_text'] or '(no work items)'}")
