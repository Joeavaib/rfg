---
name: rfg
description: Lead a multi-step refactor or feature with rfg (roadmap DAG, worktree apply, verify, rollback)
---

# rfg

MCP = CLI (`root`/`RFG_ROOT`). Same loop as `python3 -m rfg`. `doctor` first. Goal: `plan --goal` without `--step`. Feature: `recipe apply feature-campaign`. `next` → `context` (slim; `--sources` for snippets) → `tick`. implement: tick claims; edit at root; `apply`; `verify`. After verify: MCP `harvest` (`root`=campaign). `next` null → `land`. Canonical: `.grok/skills/rfg/SKILL.md`. Test-Fokus: `docs/test-focus.md`. `impact` counts unless `files=true`. Recovery: `.rfg/` is gitignored; `backup` lists, `restore <id>` recovers (exit 4 unknown); `doctor` warns on incomplete store.
