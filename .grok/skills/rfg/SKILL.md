---
name: rfg
description: Lead a multi-step refactor with the local rfg CLI (roadmap, impact, apply in a git worktree, verify, rollback). Use when the user says refactor, rename across files, rfg, /rfg, next safe step, or wants a verify/rollback loop instead of one big patch.
---

# rfg

Drive refactors through `python3 rfg.py --format json` (or MCP tools `rfg__*` if the `rfg` server is connected). Do not hand-edit a mass rename when rfg can apply a step.

## Loop

1. `doctor` then `index` if needed.
2. `init` once; `plan --hypothesis … --symbol …` then one `--step` per DAG node (`--from` / `--to` / `--path` / `--depends` / `--verify`).
3. Repeat until `next` is null:
   - `next` / `status`
   - `apply --dry-run` — read `diff` and `risk`
   - `apply` (worktree)
   - `verify` — exit `2` means fail: `rollback last`, then stop or fix the step
4. C++ without `compile_commands.json`, or Rust macros: `engine: manual` or skip (exit `4`). Do not invent a semantic rename.

## Contract

Exit: `0` ok, `2` verify fail, `3` dirty, `4` unsupported, `5` conflict (diff budget).

Store: `.rfg/roadmap.yaml` (plan) + `.rfg/state.json` (progress). Git is the transaction.

Apply stays deterministic. Do not substitute an LLM patch for `rfg apply`.
