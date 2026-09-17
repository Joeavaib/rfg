---
name: rfg
description: Lead a multi-step refactor or feature with rfg (roadmap DAG, worktree apply, verify, rollback)
---

# rfg

MCP = CLI (`root`/`RFG_ROOT`). Same loop as `python3 -m rfg`. `doctor` first. Goal: `plan --goal` without `--step`. Feature: `recipe apply feature-campaign`. `next` → `context` (slim; `--sources` for snippets) → `tick`. implement: tick claims; edit at root; `apply`; `verify`. `next` null → `land`. `impact` counts unless `files=true`.
