# claude-session-recap

A Claude Code plugin that stops you losing sessions.

You open Claude Code in many folders, have long useful conversations, and a week later you no
longer remember where they were, what they covered, or how to get back in. This plugin answers
that in one command.

| Command | What it does |
|---|---|
| `/session-recap:list-session [all \| <days> \| <folder filter>]` | Recap of the sessions on this computer: **where** (folder, branch), **name**, **what it is about**, **the last thing being done**, and the **command to resume it**. Default: last 30 days. |
| `/session-recap:resume-session <n \| id \| keywords> [print]` | Finds one session (row number from the last list, id/prefix or keywords) and reopens it in a new terminal window in the right folder (macOS), or prints the command. |

You can also just ask, e.g. *"which Claude sessions do I have?"* or *"reopen the one about the
login bug"*.

## Install

```bash
claude plugin marketplace add FranciIzzi/claude-session-recap
claude plugin install session-recap@claude-session-recap
```

Restart Claude Code. To update later: `claude plugin update session-recap@claude-session-recap`.

Requirements: Claude Code and Python 3.9+ (`python3` on PATH). No other dependencies.

## Example output

```
### 2. shop-backend  ·  today 15:42 · 227 messages 🟢 probably still open
📁 Where: ~/projects/shop/backend (branch main)
💬 About: debugging the login flow of the shop app on a physical device
⏭ Last thing: checking the auth middleware at the top of both login routes
▶️ cd /Users/me/projects/shop/backend && claude --resume 3f9c2a1e-…
```

## How it works

Claude Code stores each session as `~/.claude/projects/<encoded-folder>/<session-id>.jsonl`.
`skills/list-session/scripts/sessions.py` (standard library only) scans those files line by
line, skipping the heavy records before parsing them. It extracts:

- titles (the one you set with `/rename`, otherwise the auto-generated one);
- the folder the session was **started** in (where `claude --resume` must run), plus the folder
  where work actually ended if it changed with `cd`;
- timestamps, git branch, first prompt, last prompts and the last assistant reply.

It prints a compact JSON that Claude turns into the recap. On about 1 GB of sessions it runs in
1–2 s.

**Privacy:** everything stays on your machine. The script only reads local files. It masks
common secrets (GitHub/OpenAI/Anthropic/AWS/Slack tokens, `password: …`, private keys) as
`[REDACTED]`, and the skill is told never to repeat credentials. The only file it writes is the
row numbering of the last list, in `~/.cache/list-session/last-list.json`.

## Use the script directly

```bash
S=skills/list-session/scripts/sessions.py
python3 $S list --format text            # last 30 days
python3 $S list --all --project myapp    # filter by folder
python3 $S find login bug                # search
python3 $S resume 3 --open               # reopen row 3 of the last list (macOS)
```

Overrides: `CLAUDE_PROJECTS_DIR`, `XDG_CACHE_HOME`. Temp/scratchpad sessions are hidden unless
you pass `--include-tmp`.

## Limits

- Resume has to run from the folder where the session started. If that folder was moved or
  deleted, the command is still shown, with a warning.
- Opening a new window is macOS-only (Terminal or iTerm). On other systems the command is printed.
- The `.jsonl` format is internal to Claude Code and may change. Unknown records and truncated
  lines are ignored.

## Development

```bash
python3 -m unittest discover -s skills/list-session/tests
claude plugin validate .
```

## License

MIT © 2026 Francesco Izzi — D&D Partners S.r.l.
