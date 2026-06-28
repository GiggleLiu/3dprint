# CLAUDE.md

The shared, agent-agnostic guide for this repo lives in **`AGENTS.md`** — imported
below so Codex, Cursor, Gemini, and Claude Code all follow the same instructions.
Keep repo guidance in `AGENTS.md`; this file only adds Claude-Code-specific notes.

@AGENTS.md

## Claude Code specifics

- **Skills are auto-discovered** from `.claude/skills/`. Invoke them through the
  **Skill tool** or their slash commands (e.g. `/onboard`) — don't read a `SKILL.md`
  manually with file tools; load it via the skill mechanism so it activates properly.
- The skill workflow order for printing is: `onboard` (first time) → `design-stl`
  (optional, to create a model) → `print-to-bambu` (preflight → slice → **confirm** →
  send → monitor).
- **Honor the confirmation gate** (AGENTS.md rule 1): never run `send.py` without
  `--dry-run` until the user has explicitly approved *this* slice.
