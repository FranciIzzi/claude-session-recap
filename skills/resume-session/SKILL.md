---
name: resume-session
description: Resume a specific local Claude Code session found with list-session — by row number, session id (or prefix) or keywords — opening it in a new terminal window in the right folder. Use when the user runs /resume-session or asks "riapri la sessione N", "riprendi la sessione su X", "resume the session about X", "riaprimi quella del coach".
argument-hint: "<number | session id | keywords> [print]"
---

# resume-session

Finds one session among those on this computer and reopens it with
`cd <project folder> && claude --resume <id>` (resume only works from the folder where the
session was started, which is why the script picks that folder).

Reply in the user's language.

## Steps

1. Script path: `<this skill dir>/../list-session/scripts/sessions.py` (shared with the
   sibling `list-session` skill). Below it is written as `sessions.py`.

2. If `$ARGUMENTS` is empty, run the `list-session` skill first (or ask which session).

3. Look the session up:
   ```bash
   python3 "<this skill dir>/../list-session/scripts/sessions.py" resume <query>
   ```
   - A small number (`3`) refers to the row numbers of the **last** `/list-session` output
     (saved in `~/.cache/list-session/last-list.json`).
   - An id or id prefix (`221e`) matches directly; anything else is matched as keywords
     against title, folder and prompts (all words must match).
   - Searches cover the last 30 days; if nothing is found, retry with `--all`.

4. Result handling:
   - **Several matches** (`count > 1`, output has `matches`): show them as a short numbered
     list (title · `~/path` · date) and ask the user which one (AskUserQuestion when ≤ 4,
     otherwise plain list). Then run `resume <id>` with the chosen id.
   - **No match**: say so and suggest running the `list-session` skill with `all`.
   - **One match** (output has `session`): continue.

5. Before opening, show a 3-line card: title, 📁 folder, ⏭ last thing being done
   (from `last_prompts` / `last_reply`), plus the full `resume_cmd` in a code block.
   - If `warning` is present (folder missing), show it and do **not** open: give the command
     only and explain the folder must be restored/moved back first.
   - If `last_ts` is within the last ~10 minutes the session may still be open in another
     terminal: say so and ask before opening a second copy.

6. Open it:
   - Default on macOS: rerun with `--open` — it opens a **new** Terminal/iTerm window
     running the command. Confirm with "aperta in una nuova finestra del terminale".
   - If the user passed `print` / `solo comando`, or on Linux/Windows, or if `opened` is
     false: just give the command to paste.
   - You cannot switch *this* conversation to another session; never claim you did.
