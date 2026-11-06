#!/usr/bin/env python3
"""Indicizza le sessioni locali di Claude Code (~/.claude/projects) e prepara il resume.

Solo libreria standard. Sottocomandi:
  list   [--days N | --all] [--project TXT] [--limit N] [--include-tmp] [--format json|text]
  find   <query> [--all]                  cerca per id, titolo, cartella o testo dei prompt
  resume <id|prefisso|testo> [--open]     stampa (o apre in un nuovo terminale) il comando di resume
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECTS_DIR = Path(os.environ.get("CLAUDE_PROJECTS_DIR", Path.home() / ".claude" / "projects"))
CACHE_FILE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "list-session" / "last-list.json"

# Tipi di record che ci interessano: tutti gli altri vengono scartati senza parsing JSON
# (i blob delle richieste API possono pesare MB per riga).
WANTED_TYPES = ("user", "assistant", "custom-title", "ai-title", "last-prompt")
TYPE_RE = re.compile(r'\{\s*"type"\s*:\s*"([a-z\-]+)"')
WANTED_RE = re.compile(r'"type"\s*:\s*"(?:%s)"' % "|".join(WANTED_TYPES))

# Prompt "finti" iniettati dall'harness, non scritti dall'utente.
NOISE_PREFIXES = (
    "This session is being continued",
    "<command-",
    "<local-command",
    "<system-reminder",
    "<bash-",
    "<task-notification",
    "<user-memory",
    "Caveat:",
    "[Request interrupted",
)
TMP_PREFIXES = ("/private/tmp", "/tmp", "/private/var/folders", "/var/folders")

MAX_PROMPT = 300
MAX_REPLY = 500


# Segreti da non riportare mai nel recap (token noti + "password: xxx" e simili).
SECRET_RES = [
    re.compile(r"\b(?:gh[pousr]_|github_pat_|sk-(?:ant-)?|xox[abpr]-|AKIA|AIza|glpat-)[A-Za-z0-9_\-]{4,}"),
    re.compile(r"(?i)\b(pass(?:word)?|pwd|token|secret|api[_ -]?key)(\s*[:=]\s*|\s+)((?=\S*[\d!@#$%^&*])\S{6,})"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def redact(text: str) -> str:
    text = SECRET_RES[0].sub("[REDACTED]", text)
    text = SECRET_RES[1].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
    return SECRET_RES[2].sub("[REDACTED PRIVATE KEY]", text)


def _clip(text: str, n: int) -> str:
    text = redact(" ".join(text.split()))
    return text if len(text) <= n else text[: n - 1] + "…"


def _is_candidate(line: str) -> bool:
    """Filtro economico prima del json.loads: True se la riga può essere un record utile."""
    # i record "di servizio" (es. api-request-blob, anche MB per riga) iniziano con il type
    m = TYPE_RE.match(line)
    if m:
        return m.group(1) in WANTED_TYPES
    # user/assistant hanno il type di primo livello in fondo alla riga
    return WANTED_RE.search(line) is not None


def _text_of(content) -> str:
    """Testo leggibile di un content (stringa o lista di blocchi); '' se sono solo tool."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def _is_real_prompt(text: str) -> bool:
    t = text.lstrip()
    return bool(t) and not t.startswith(NOISE_PREFIXES)


def parse_session(path: Path) -> dict | None:
    """Riassume un file .jsonl di sessione; None se non contiene una conversazione reale."""
    info = {
        "id": path.stem,
        "file": str(path),
        "custom_title": None,
        "ai_title": None,
        "cwd": None,
        "first_cwd": None,
        "last_cwd": None,
        "git_branch": None,
        "first_ts": None,
        "last_ts": None,
        "user_msgs": 0,
        "assistant_msgs": 0,
        "first_prompt": None,
        "last_prompts": [],
        "last_reply": None,
    }
    try:
        fh = path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"[list-session] impossibile leggere {path}: {exc}", file=sys.stderr)
        return None
    with fh:
        for line in fh:
            if not _is_candidate(line):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # riga troncata (sessione ancora in scrittura): la ignoriamo
            rtype = rec.get("type")
            if rtype not in WANTED_TYPES:
                continue
            if rtype == "custom-title":
                info["custom_title"] = rec.get("customTitle") or info["custom_title"]
                continue
            if rtype == "ai-title":
                info["ai_title"] = rec.get("aiTitle") or info["ai_title"]
                continue
            if rtype == "last-prompt":
                continue
            if rec.get("isSidechain"):
                continue
            ts = rec.get("timestamp")
            if ts:
                info["first_ts"] = info["first_ts"] or ts
                info["last_ts"] = ts
            if rec.get("cwd"):
                # il cwd di avvio coincide con la cartella codificata del progetto;
                # quelli successivi cambiano se durante la sessione si fa `cd`
                if info["cwd"] is None and encode_dir(rec["cwd"]) == path.parent.name:
                    info["cwd"] = rec["cwd"]
                info["first_cwd"] = info["first_cwd"] or rec["cwd"]
                info["last_cwd"] = rec["cwd"]
            if rec.get("gitBranch"):
                info["git_branch"] = rec["gitBranch"]
            text = _text_of((rec.get("message") or {}).get("content"))
            if rtype == "user":
                if rec.get("isMeta") or not _is_real_prompt(text):
                    continue
                info["user_msgs"] += 1
                clipped = _clip(text, MAX_PROMPT)
                info["first_prompt"] = info["first_prompt"] or clipped
                info["last_prompts"] = (info["last_prompts"] + [clipped])[-3:]
            elif rtype == "assistant" and text.strip():
                info["assistant_msgs"] += 1
                info["last_reply"] = _clip(text, MAX_REPLY)
    if info["user_msgs"] == 0:
        return None
    info["cwd"] = info["cwd"] or info["first_cwd"]
    info["title"] = info["custom_title"] or info["ai_title"] or _clip(info["first_prompt"] or "", 60)
    info["cwd_exists"] = bool(info["cwd"]) and Path(info["cwd"]).is_dir()
    info["resume_cmd"] = resume_command(info)
    return info


def encode_dir(cwd: str) -> str:
    """Stessa codifica usata da Claude Code per i nomi delle cartelle in ~/.claude/projects."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def resume_command(info: dict) -> str:
    sid = info["id"]
    if info.get("cwd"):
        return f"cd {shlex.quote(info['cwd'])} && claude --resume {sid}"
    return f"claude --resume {sid}"


def _parse_ts(ts: str | None) -> datetime:
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def collect(projects_dir: Path = PROJECTS_DIR, days: int | None = 30, project: str | None = None,
            include_tmp: bool = False, limit: int | None = None) -> list[dict]:
    if not projects_dir.is_dir():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    sessions = []
    # solo file di primo livello: le sottocartelle <id>/subagents contengono i subagent
    for path in projects_dir.glob("*/*.jsonl"):
        if cutoff and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
            continue  # scarto veloce prima del parsing
        info = parse_session(path)
        if not info:
            continue
        if not include_tmp and (info["cwd"] or "").startswith(TMP_PREFIXES):
            continue
        if project and project.lower() not in (info["cwd"] or "").lower():
            continue
        sessions.append(info)
    sessions.sort(key=lambda s: _parse_ts(s["last_ts"]), reverse=True)
    for i, s in enumerate(sessions, 1):
        s["n"] = i
    return sessions[:limit] if limit else sessions


def save_numbering(sessions: list[dict], cache_file: Path = CACHE_FILE) -> None:
    """Salva n -> id dell'ultimo `list`, così `resume N` punta alla stessa riga vista dall'utente."""
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({str(s["n"]): s["id"] for s in sessions}))
    except OSError as exc:
        print(f"[list-session] impossibile salvare la numerazione: {exc}", file=sys.stderr)


def load_numbering(cache_file: Path = CACHE_FILE) -> dict[str, str]:
    try:
        return json.loads(cache_file.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[list-session] numerazione in cache illeggibile: {exc}", file=sys.stderr)
        return {}


def find(query: str, sessions: list[dict], numbering: dict[str, str] | None = None) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    if q.isdigit() and len(q) < 4:  # numero di riga del recap
        sid = (numbering or {}).get(q)
        if sid:
            hit = [s for s in sessions if s["id"] == sid]
            if hit:
                return hit
        if 0 < int(q) <= len(sessions):
            return [sessions[int(q) - 1]]
    exact = [s for s in sessions if s["id"].lower().startswith(q)]
    if exact:
        return exact
    def haystack(s):
        return " ".join(filter(None, [s["title"], s["custom_title"], s["ai_title"], s["cwd"],
                                      s["first_prompt"], *s["last_prompts"]])).lower()
    words = q.split()
    return [s for s in sessions if all(w in haystack(s) for w in words)]


def open_in_terminal(cmd: str) -> bool:
    """Apre il comando in una nuova finestra di terminale (solo macOS). True se riuscito."""
    if sys.platform != "darwin":
        return False
    app = "iTerm" if os.environ.get("TERM_PROGRAM") == "iTerm.app" else "Terminal"
    escaped = cmd.replace("\\", "\\\\").replace('"', '\\"')
    if app == "iTerm":
        script = f'tell application "iTerm"\n activate\n set w to (create window with default profile)\n tell current session of w to write text "{escaped}"\nend tell'
    else:
        script = f'tell application "Terminal"\n activate\n do script "{escaped}"\nend tell'
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[list-session] osascript fallito: {res.stderr.strip()}", file=sys.stderr)
        return False
    return True


def _fmt_text(sessions: list[dict]) -> str:
    out = []
    for s in sessions:
        out.append(f"{s['n']:>3}. {s['title']}  [{(s['last_ts'] or '')[:16].replace('T', ' ')}]")
        out.append(f"     dir: {s['cwd']}{'' if s['cwd_exists'] else '  (cartella non trovata)'}")
        out.append(f"     resume: {s['resume_cmd']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list")
    pl.add_argument("--days", type=int, default=30)
    pl.add_argument("--all", action="store_true", help="nessun limite di giorni")
    pl.add_argument("--project")
    pl.add_argument("--limit", type=int)
    pl.add_argument("--include-tmp", action="store_true")
    pl.add_argument("--format", choices=["json", "text"], default="json")

    for name in ("find", "resume"):
        sp = sub.add_parser(name)
        sp.add_argument("query", nargs="+")
        sp.add_argument("--all", action="store_true", help="cerca anche oltre gli ultimi 30 giorni")
        sp.add_argument("--include-tmp", action="store_true")
        if name == "resume":
            sp.add_argument("--open", action="store_true", help="apre un nuovo terminale (macOS)")

    a = p.parse_args(argv)

    if a.cmd == "list":
        sessions = collect(days=None if a.all else a.days, project=a.project,
                           include_tmp=a.include_tmp, limit=a.limit)
        save_numbering(sessions)
        if a.format == "text":
            print(_fmt_text(sessions) or "Nessuna sessione trovata.")
        else:
            json.dump({"projects_dir": str(PROJECTS_DIR), "count": len(sessions), "sessions": sessions},
                      sys.stdout, ensure_ascii=False, indent=1)
            print()
        return 0

    # la numerazione deve combaciare con quella di `list` (stessi filtri di default)
    sessions = collect(days=None if a.all else 30, include_tmp=a.include_tmp)
    matches = find(" ".join(a.query), sessions, load_numbering())
    if a.cmd == "find" or len(matches) != 1:
        json.dump({"query": " ".join(a.query), "count": len(matches), "matches": matches},
                  sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0 if matches else 1

    s = matches[0]
    result = {"session": s, "resume_cmd": s["resume_cmd"], "opened": False}
    if not s["cwd_exists"]:
        result["warning"] = f"La cartella {s['cwd']} non esiste più: il resume potrebbe non trovare la sessione."
    if a.open:
        result["opened"] = open_in_terminal(s["resume_cmd"])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
