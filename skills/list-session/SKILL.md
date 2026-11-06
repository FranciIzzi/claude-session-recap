---
name: list-session
description: Recap of every Claude Code session stored on this computer — where it lives, what it is called, what it is about, the last thing being done, and the exact command to resume it. Use when the user runs list-session or asks things like "which sessions do I have", "where was that conversation about X", "list my Claude sessions", "recap delle sessioni", "dove avevamo lavorato su X", "che sessioni ho aperto".
argument-hint: "[all | <days> | <project filter>]"
---

# list-session

Builds a readable recap of the local Claude Code sessions (`~/.claude/projects/**/<id>.jsonl`)
so the user can find lost conversations and jump back into them.

Reply in the user's language (the examples below are in Italian because that is the author's).

## 1. Collect the data (always via the script)

Run the bundled script from this skill's directory — never read the `.jsonl` files by hand
(they can be hundreds of MB and contain private content):

```bash
python3 "<this skill dir>/scripts/sessions.py" list [options]
```

Map `$ARGUMENTS` to options:

| Argument | Options |
|---|---|
| empty | `--days 30` (default) |
| `all` / `tutte` / `tutto` | `--all` |
| a number, e.g. `7` | `--days 7` |
| any other text, e.g. `tenaglia` | `--all --project tenaglia` (substring of the folder path) |
| `tmp` anywhere | add `--include-tmp` (scratchpad/temp sessions, hidden by default) |

The script prints JSON: `{count, sessions: [...]}`, newest first. Each session has:
`n` (row number, also saved for `/resume-session N`), `id`, `title`, `custom_title`
(name chosen by the user), `ai_title`, `cwd` (folder to resume from), `last_cwd` (where work
actually ended, can differ after `cd`), `cwd_exists`, `git_branch`, `first_ts`, `last_ts`,
`user_msgs`, `first_prompt`, `last_prompts` (last 3 user prompts), `last_reply` (last
assistant text), `resume_cmd`.

## 2. Write the recap

Group sessions by project folder (`cwd`); order groups by their most recent session.
For every session write one compact block, keeping the script's `n`:

```
### 3. Software da studiare  ·  oggi 13:17 · 22 messaggi
📁 **Dove:** `~/Desktop/D&D/pdfcraft` (branch `main`)
💬 **Di cosa si parla:** analisi del progetto pdfcraft per capire come estrarre…
⏭ **Ultima cosa:** stavamo verificando dove si trova il progetto sul Mac e…
▶️ `cd '/Users/…/D&D/pdfcraft' && claude --resume fbfd61dc-…`
```

Rules:
- **Title**: `custom_title` if present (the user named it — show it as is), else `ai_title`,
  else a short title you derive from `first_prompt`.
- **Di cosa si parla**: 1–2 lines synthesised from titles + `first_prompt` + `last_prompts`.
  Don't copy raw prompts; describe the topic.
- **Ultima cosa**: 1–2 lines from the last prompts and `last_reply` — what was being done and,
  if evident, what was left open.
- **Dove**: show paths with `~`. If `last_cwd` differs from `cwd`, add "· lavoravamo in `<last_cwd>`".
- Write the resume command in full (it must be copy-pasteable; keep the quoting from `resume_cmd`).
- Flags to add when relevant: ⚠️ folder no longer exists (`cwd_exists: false`);
  ⚠️ interrupted (last reply is an API/connection error); 🟢 probably still open (`last_ts`
  within the last ~10 minutes — this includes the current session).
- Relative dates: "oggi 13:17", "ieri", "3 giorni fa", then dates.
- If there are more than ~25 sessions, give full blocks to the 15 most recent and a one-line
  list (`n. title — ~/path — date`) for the rest.

Privacy: the script masks common secrets as `[REDACTED]`. Never reproduce passwords, tokens,
keys or similar that slip through anyway: describe them ("la password del server") instead.

Close with one line telling the user how to resume one with the `resume-session` skill —
`/resume-session <n | id | keywords>`, or `/session-recap:resume-session …` when installed as a plugin.

## 3. Follow-ups

If the user asks for more detail on one session, run
`python3 "<this skill dir>/scripts/sessions.py" find <id>` and, only if needed, read the
last part of that session's file (`tail` on the `file` path, filtering `"type":"user"` /
`"type":"assistant"` lines) — never dump it whole.
