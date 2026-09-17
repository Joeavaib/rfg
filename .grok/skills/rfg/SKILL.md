---
name: rfg
description: Lead a multi-step refactor or feature with rfg (roadmap DAG, worktree apply, verify, rollback). Use when the user says refactor, rename, rfg, /rfg, next safe step, or wants a verify/rollback loop.
---

# rfg

MCP = CLI (`root` / `RFG_ROOT`). Prefer MCP. Else `python3 rfg.py --format json`. Do not mass-edit a rename. Do not read the tree; `context` is the window. Core: `plan` `next` `tick` `apply` `verify` `land`.

`doctor` first (git; `module` = binary). Product goal once: `plan --goal` without `--step`. Step: `--want --path --verify --depends` (missing path ok). Feature: `recipe apply feature-module` or `feature-campaign --step id:path:verify`.

## Loop

1. `init` if no `.rfg/`. Feature default `--engine implement` if no `--from`. Survey: `--engine survey`. `path` may be a JSON array.
2. `next` → `context` (exists/missing; `--sources` for snippets) → `tick`. Plan JSON is ids only. `impact` counts; `--files` to list.
3. Replace/scaffold/run: `tick` apply+verify (`apply --dry-run` if unsure). implement/manual/survey: `tick` claims `in_progress` + contract. Untracked dirty root is ok. Edit at root, then `apply`, then `verify`.
4. Exit 2 → `rollback last`. `next` null → `land`. Unfinished = 5.
5. `progress` exceptions only (`data.ok`). `implemented` counts reached apply, even after verify.

## Contract

`0` ok · `2` verify fail · `3` dirty · `4` unsupported · `5` conflict. `ready` → `in_progress` → `implemented`/`applied` → `verified`. Store: `.rfg/roadmap.yaml` + `state.json`. Git is the transaction.
