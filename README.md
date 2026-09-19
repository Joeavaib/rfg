# rfg

**rfg leads one campaign through one Git repo — one step at a time — and checks after every move whether the project still holds.**

It is a **local campaign leader**, not a compiler, chatbot, GitHub bot, or agent harness. You (or an AI) write the plan and the new code. rfg remembers the goal, hands out **one** next step, runs mechanical renames in a Git copy, runs **your** test/build command after every move, and can take the last move back.

Where it cannot do the job honestly (C++ without `compile_commands.json`, Rust macros, empty/`true` verify), it **exits 4** instead of saying “all good”.

- Python 3.10+, standard library only, offline by default
- License: MIT · schema version 3 · package version `1.0.0` (schema level, not a product claim)

```
python3 rfg.py --help
python3 rfg.py --format json <command>   # agents: always JSON
```

Agents: read **`docs/agent.md`** once per session instead of rediscovering the loop from the tree.

---

## Mental model

| Piece | What it is |
|--------|------------|
| **Goal** | What is true when we are done (`plan --goal`, no `--step`) |
| **Roadmap** | A DAG of steps in `.rfg/roadmap.yaml` |
| **Step contract** | `want` + `path[]` + optional `extras` + `verify` + `depends` |
| **Worktree** | `.rfg/worktree` — Git copy where steps land until `land` |
| **State** | `.rfg/state.json` — applied/verified/failed, claims, checkpoints |
| **Oracle** | **Your** command. rfg does not invent tests |

Git is the transaction. Mechanical apply and implement `apply` (copy of root edits) happen in the worktree. `rollback last` restores the last checkpoint. `land` copies the worktree onto the repo **only** when every applied step is verified and the land gate is green.

Step states: `ready` → `claimed` → `in_progress` → `implemented` / `applied` → `verified` (plus `blocked` / `failed`). **`verified ≠ done` is enforced:** `land` refuses applied-but-unverified steps (exit 5).

---

## The loop

```
Goal
  → Plan (DAG: want, paths, depends, one verify per step)
  → For each free step:
      1. next / context   contract (want, path, missing files ok)
      2. tick
           replace/scaffold/run → apply + verify in the worktree
           implement/manual/survey → claim, print contract, STOP
      3. (implement) you/AI edit at the **repo root**, then apply, then verify
      4. On red (exit 2): rollback last
  → next is null → land (worktree → root, gate + re-verify)
```

**Do not mass-edit a rename. Do not read the whole tree to guess the next file.** `context` is the window. Cousin snippets only with `context --sources`.

JSON everywhere: `--format json`. Exit codes: `0` ok · `2` verify failed · `3` dirty tree · `4` unsupported (won't guess) · `5` conflict (claim, unfinished land, budget).

---

## Quickstart: rename

```
python3 rfg.py doctor
python3 rfg.py init
python3 rfg.py plan --goal "Typed IDs" --profile refactor
python3 rfg.py plan --step rename-foo --from old_name --to new_name --engine replace
python3 rfg.py next
python3 rfg.py tick              # apply + verify in the worktree
python3 rfg.py land
```

`replace` rewrites whole identifiers in the copy. String literals like `"old_name"` are left alone. Red → `python3 rfg.py rollback last`.

## Quickstart: extend code

Same `init` / `next` / `tick` / `land` — different engines:

```
python3 rfg.py recipe apply feature-module --path extra/greet.py --verify "python3 -c 'import extra.greet'"
python3 rfg.py tick          # scaffold (if the recipe added one)
python3 rfg.py tick          # implement: STOP — write the file at repo root
python3 rfg.py apply         # copy path[] and other root edits into the worktree
python3 rfg.py verify
python3 rfg.py land
```

Multi-step, recipe `feature-campaign`:

```
python3 rfg.py plan --goal "Invoice from WhatsApp" --profile feature
python3 rfg.py recipe apply feature-campaign \
  --goal "Invoice from WhatsApp" \
  --step M01:extract.py:pytest tests/test_extract.py \
  --step M02:ops.py:pytest tests/test_ops.py \
  --depends M02:M01
```

`plan --goal` **with** `--step` is exit 5; use `--want` on steps. Missing `path` on a new feature is normal. Side files (notes, `rfgfeedback.md`) go in `--extras`, not `path[]`.

Ready-made mini-plans: `python3 rfg.py recipe list`. Profiles (same loop, different check): `refactor`, `feature`, `perf`, `debug`, `security`.

---

## Step kinds (`engine`)

| Engine | Who writes code | What `tick` does |
|--------|-----------------|------------------|
| `replace` | rfg (identifier rewrite) | apply + verify |
| `ast-grep` | rfg if the binary exists | apply + verify; else exit 4 |
| `scaffold` | rfg (empty files) | apply + verify |
| `run` | nobody — just a command | runs at **root** (needs `--force` if tracked-dirty) |
| `implement` | you / AI at **root** | claim + contract, stop |
| `manual` | you / AI on existing files | claim + contract, stop |
| `survey` | notes only, no code change | claim + contract, stop |

Unknown `--engine` fails at `plan`/`tick` (exit 4), not later.

---

## Verify discipline

One oracle per step; the step command is only the start.

- **Cross-Verify (level 1):** `verify` also runs verifies of **direct dependents** and steps with **path overlap**, but only ones already applied. Pending steps never block. Failures: `cross-verify failed for …` plus per-step logs (`.rfg/verify/<step>__cross_<id>.log`). Failures are labeled (ENV / COST / PRE-EXISTING / REGRESS-SUSPECT) without changing the exit. Over-budget related sets **warn** (`budget: …`); they do not gate.
- **Land-Gate (level 2):** `land` re-runs the last step verify **plus** suite-level `rm.verify` **plus** executable goal acceptance. Missing toolchain **skips** the gate (logged) instead of failing it. Trivial verify (`true` / empty) → revert + exit 4. Red gate → revert worktree copy + exit 2.
- **Every verify leaves a log** under `.rfg/verify/`. Emitted output is clipped (`…[truncated, see log]…`); the file is complete.
- **No silent scope:** `apply` stages declared `path[]` **and** extras, and **warns** when other files were staged — extend `path[]` (`plan --path`) or allowlist (`plan --extras`).
- **No growth penalty:** identical verifies across steps warn (dedup hint); they never block planning.
- **Sham / weak verify:** `doctor` and `plan --check --strict` surface `true`, empty, or mismatched scope. They warn-first unless `--strict`.
- **Hub alignment:** only hubs (>10 neighbors) get **one** extra alignment verify (a dependent, else strongest overlap). Leaves (≤3) get none, never transitive. Enough = own verify green + 1 alignment green + land gate green.
- **Acceptance prose** (non-command goal text) is listed, never gated.

---

## Output budgets (agent-facing)

Emitted JSON/text is capped; **files on disk are always complete**. Capped payloads say `truncated`, `chars`, `token_estimate`, `max_chars`.

| Flag | Effect |
|------|--------|
| `--max-chars N` | Cap for `context`, `digest`, `export`, `impact`, `scan`, `fleet`, `sbom`. Default 2000, hard cap 8000, `0` = no cap |
| `--show-risk` | Include `risk`/`format` on `apply`/`next` (default slim) |
| `--full` | `fleet status` with full per-repo dumps (default: one row) |

`exceptions` are never shrunk. Safety fields always report.

**Rule of thumb:** one implement loop (`next` → `tick` → `apply` → `verify` → `progress`) is ~750 tokens of rfg overhead. Make **steps bigger**, not caps smaller, if that hurts. Full truth: `--show-risk`, `--max-chars 0`, `--full`, or read `.rfg/verify/`, `.rfg/digest.json`.

---

## Commands

Core loop: `init` `status` `plan` `next` `context` `tick` `apply` `verify` `rollback` `land` `why` `claim` `release` `progress`

Index: `impact` `index` `import-scip` `edges` `boundaries`

Checks: `baseline` `repro` `scan` `fuzz` `sbom`

Wrap-up: `digest` `export`

More: `recipe` `fleet` `doctor` `mcp` `packs` `migrate` `completion` `man` `version` `audit` `backup` `restore`

Notable:

- `plan --check` validates the roadmap read-only (exit 5 with findings). `--strict` turns sham-verify into errors.
- `next --epic PREFIX` is a **display** filter (warn-first, never a gate, not on MCP).
- `land --commit` or `RFG_AUTO_COMMIT=1` snapshots a **local** commit after a successful land; never pushes.
- `scan --parse FILE` parses stored scanner JSON (trivy, grype, pip-audit, osv-scanner) into findings + SARIF (`.rfg/scan.sarif`); exit 2 on high/critical. Without `--parse` it runs the first present scanner as JSON. No exploits, no payloads.
- `fuzz [--seconds N]` runs the configured fuzz command, or builds one from a present fuzzer.
- `fleet status` reads `fleet.yaml` — one compact row per repo. Read-only; not a scheduler.
- `packs` lists open vs paid packs; enabling paid packs is exit 4.
- Recovery: `.rfg/` is gitignored. `backup` lists `.rfg/land-backups/` (roadmap+state, pruned to 10). `restore <id>` copies both back (exit 4 on unknown id). `doctor` warns when the store is incomplete but backups exist.

---

## Hosts: CLI, MCP, Skill

The local CLI **is** the software. MCP and Skill are doors into it.

| | CLI | MCP (core) | Skill `/rfg` |
|--|-----|------------|--------------|
| Lead a campaign | full | same loop | describes *how* |
| `doctor`, `recipe`, `why`, `impact` | yes | yes | mentioned |
| Extended (`scan`/`fuzz`/`sbom`, fleet…) | yes | `RFG_MCP_ALL=1` | no |
| `--help`, completion, man | yes | no | no |
| Write feature code | no | no | no (AI outside) |

Core MCP verbs: `init` `plan` `next` `context` `tick` `apply` `verify` `land` `rollback` `claim` `release` `progress` `doctor` `recipe` `why` `impact`. Same `.rfg/` store, same exit codes. `root` / `RFG_ROOT` = `--root`. `claim` when several agents share a repo (`RFG_AGENT`); claims are per-repo.

rfg does not make agents smarter. It makes them worse at silently changing too much — **if** the host loaded MCP and the agent does not bypass the loop.

---

## Languages — honestly

- **Go, Python, JS/TS:** index, impact, replace work well.
- **Rust:** macros → exit 4, except via `manual` / `implement`.
- **C++:** no `compile_commands.json` → no mechanical C++ apply (exit 4); verify should be a real compiler. Recipe: `cxx-ffi-manual`.
- The `cxx/rfg` binary is a **subset** of the Python CLI (rename core), not feature parity. Honest boundary (`python3 scripts/cxx-parity.py --boundary`): covered are init/plan/next/context/tick/apply/verify-basic/land-basic/progress/claim/rollback; **Python-only** are Land-Gate, Cross-Verify, output budgets, `scan --parse`/SARIF, fleet summary, perf delta.

Uncertainty is sharpened with a better check command, not with more magic in replace.

---

## What rfg is not

No SaaS, no Jira/Linear, no GitHub app, no token counter, no cloud kill switch. It is the **local** plan-and-check core for **one** campaign in **one** Git repo. Fleet is a status reader, not an estate scheduler.

Deliberately out: own parser, live SCIP, an LLM inside rfg, exploit building, “the AI writes the patch and rfg takes credit”. Doctrine (tripwires): no network in core, no daemons past step end, stdlib only, no writes outside worktree/`.rfg` until `land`. See `docs/factory-line.md`.

---

## Maturity

Solid core, prototype product. The loop is deterministic and tested. As a **local discipline tool for an agent loop**, rfg is serious. As an **MCP product** (spec coverage, releases, support), it is not finished: minimal stdio transport, no auth/sessions, single-maintainer. Where your tests are thin, rfg guarantees “step + affected green”, not correctness.

---

## Store layout

```
.rfg/
  roadmap.yaml    goal, hypothesis, profile, acceptance, steps
  state.json      applied/verified/failed, worktree, checkpoints, claims
  env             optional KEY=VAL for verify PATH (e.g. user-local go/mvn)
  verify/         one log per verify (+ cross-verify logs)
  worktree/       Git worktree where steps are applied
  digest.json     handoff snapshot
  audit.jsonl     append-only event log
  land-backups/   roadmap.yaml + state.json (land + successful tick/apply/verify; newest 10)
  scan.sarif / sbom.json / baseline.json / last_perf.json / repro.log
```

---

## Development

```bash
python3 -m pytest tests/ -q
python3 scripts/diff_coverage.py     # changed rfg/ functions must be test-referenced
python3 scripts/mutation_sample.py   # sampled mutants must be killed
python3 scripts/cxx-parity.py        # python vs cxx/rfg + boundary
```

Conventions: stdlib only, offline by default, every step needs a negative test, docs (`docs/rfg.1`, completions, this README) move with the flags. Test ROI checklist (not a gate): `docs/test-focus.md`.

More: `docs/factory-line.md` · `docs/GLOSSARY.md` · `docs/agent.md` · `docs/INTEGRATION.md` · `docs/rfg-coverage-roadmap.md`.
