# rfg in Grok Build

rfg is a host-agnostic CLI. Grok Build is one client.

## Driver loop

MCP tools use the same verbs as the CLI (`init` `plan` `next` `context` `tick` `apply` `verify` `land` `rollback` `claim` `progress` `doctor` `recipe` `why` `impact`).

Same loop as the README: doctor → init → plan (product goal once; steps are want/path/verify) → next/context/tick → land.

`tick` apply+verify when `engine=replace`. implement/manual: `tick` claims `in_progress` and returns the contract (`want`, `path`, `edit_root`, `after_edit: apply`) — not exit 4. Edit at root, then `apply` (copies `path` **and** other root edits into the worktree), then `verify` (only from implemented; log at `.rfg/verify/<step>.log`). Missing files are normal in `context`. Cousin sources only with `context --sources`. `next` includes `ready[]` and a recommend. `plan --goal` without `--step` is the product goal. Exit 2 → `rollback last` (replace). `next` null → `land` (worktree copy, or root re-verify). `progress` always exits 0; health is `data.ok`. `implemented` is reached-apply, including verified. Dirty only after a mechanical apply left tracked files dirty. Feature start: `recipe apply feature-module` or `recipe apply feature-campaign --step id:path:verify`. Contract context includes `neighbors`/`signatures`, not the package. Extra tools: `RFG_MCP_ALL=1`. User-level MCP must launch this checkout (`scripts/rfg-mcp.py` + `RFG_HOME`); copy this skill to `~/.grok/skills/rfg/`.

Do not read the repo; `context` is the contract. Cousin/impact sources only with `context --sources`.

## This project

- Skill: `.grok/skills/rfg/SKILL.md` (`/rfg`)
- MCP: `.grok/config.toml` → `python3 -m rfg mcp` with `PYTHONPATH` / `RFG_HOME` (core = CLI campaign: init, plan, next, context, tick, apply, verify, land, rollback, claim, progress, doctor, recipe, why, impact). Feature: recipe / implement → apply after edit → verify. `RFG_MCP_ALL=1` lists packs. Plugin fallback: `plugin/rfg/mcp-launch.py` or `scripts/rfg-mcp.py`.
- Hooks: `.grok/hooks/rfg.json` — PreToolUse denies writes outside `step.path` on replace steps; Stop blocks if a step is applied but not verified. Trust the folder (`/hooks-trust`).
- Plugin bundle: `plugin/rfg/` + `.grok-plugin/marketplace.json` for `grok plugin install`.

Reload MCP with `r` on the MCP tab or a new session.

## Other repos

Install the plugin, or copy the skill to `~/.grok/skills/rfg/` and point user MCP at `scripts/rfg-mcp.py` with `RFG_HOME` = this checkout. Reload MCP (`r` on the MCP tab). `doctor.checks.module` must be this tree; `user_skill` must say `implement`.
