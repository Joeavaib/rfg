# rfg

**rfg is a checker, not a factory.**

It leads **one campaign through one Git repo**, one step at a time, and
refuses to call a step done unless **your** test/build command is green.
You (or an AI) write the plan and the feature code. rfg remembers the goal,
hands out **one** next step, applies mechanical work in a Git worktree, and
can take the last move back.

It does **not** write product code, does **not** run an LLM, and does **not**
turn “Claude said the tests passed” into a green land. Where it cannot do
the job honestly (empty/`true` verify, C++ without `compile_commands.json`,
Rust macros), it **exits 4** instead of pretending.

That is the niche: AI-authored changes become a **contract plus a proof**,
or they did not happen. It will not give you your evenings back. It will
not stop a VP who forbids review. It will stop the lie that a chat log is
verification.

- Python 3.10+, **standard library only**, offline by default
- License: MIT · schema version 3 · package `1.0.0` (schema level, **not** a product claim)
- Trace harvest / SFT farming is a **sidecar**, not this repo

```
python3 rfg.py --help
python3 rfg.py --format json <command>   # agents: always JSON
```

Agents: read **`docs/agent.md`** once per session.

No support SLA. Clone it if you want the fence. Skip it if you want Autopilot.

---

## What it checks

| Piece | What it is |
|--------|------------|
| **Goal** | What is true when we are done (`plan --goal`, no `--step`) |
| **Roadmap** | DAG in `.rfg/roadmap.yaml` |
| **Step contract** | `want` (FAIL sentence is the contract) + `path[]` + optional `extras` + one **verify command** + `depends` |
| **Worktree** | `.rfg/worktree` — Git copy until `land` |
| **State** | `.rfg/state.json` — applied/verified/failed, claims, checkpoints |
| **Oracle** | **Your** command. rfg does not invent tests |

Git is the transaction. `rollback last` restores the last checkpoint. `land`
copies the worktree onto the repo **only** when every applied step is
verified and the **Land-Gate** is green.

**`verified ≠ done` is enforced:** `land` refuses applied-but-unverified
steps (exit 5).

Exit codes: `0` ok · `2` verify failed · `3` dirty tree · `4` unsupported
(will not guess) · `5` conflict (claim, unfinished land, budget).

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
  → next is null → land (worktree → root, Land-Gate + re-verify)
```

Do not mass-edit a rename. Do not read the whole tree to guess the next
file. `context` is the window.

JSON everywhere: `--format json`.

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

`replace` rewrites whole identifiers in the copy. String literals like
`"old_name"` are left alone. Red → `python3 rfg.py rollback last`.

## Quickstart: extend code

```
python3 rfg.py recipe apply feature-module --path extra/greet.py --verify "python3 -c 'import extra.greet'"
python3 rfg.py tick          # scaffold (if the recipe added one)
python3 rfg.py tick          # implement: STOP — write the file at repo root
python3 rfg.py apply
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

`plan --goal` **with** `--step` is exit 5; use `--want` on steps. Side files
go in `--extras`, not `path[]`. YAML field is `paths`, not `path`.

Ready-made mini-plans: `python3 rfg.py recipe list`. Profiles: `refactor`,
`feature`, `perf`, `debug`, `security`.

---

## Step kinds (`engine`)

| Engine | Who writes code | What `tick` does |
|--------|-----------------|------------------|
| `replace` | rfg (identifier rewrite) | apply + verify |
| `ast-grep` | rfg if the binary exists | apply + verify; else exit 4 |
| `scaffold` | rfg (empty files) | apply + verify |
| `run` | nobody — just a command | runs at **root** |
| `implement` | you / AI at **root** | claim + contract, stop |
| `manual` | you / AI on existing files | claim + contract, stop |
| `survey` | notes only, no code change | claim + contract, stop |

Unknown `--engine` fails at `plan`/`tick` (exit 4). There is **no**
`complexity` field (`additionalProperties: false`).

Verify must be a **shell command** with exactly one test-file token, e.g.
`python3 -m pytest tests/foo.py -q`. A bare path is executed as a program
and exits 126.

---

## Verify discipline

One oracle per step; the step command is only the start.

- **Cross-Verify (level 1):** `verify` also runs verifies of **direct
  dependents** and steps with **path overlap**, but only ones already
  applied. Pending steps never block. Failures: `cross-verify failed for …`
  plus per-step logs (`.rfg/verify/<step>__cross_<id>.log`). Over-budget
  related sets **warn**; they do not gate.
- **Land-Gate (level 2):** `land` re-runs the last step verify **plus**
  suite-level `rm.verify` **plus** executable goal acceptance. Missing
  toolchain **skips** the gate (logged). Trivial verify (`true` / empty) →
  revert + exit 4. Red gate → revert + exit 2.
- **Every verify leaves a log** under `.rfg/verify/`.
- **No silent scope:** `apply` stages declared `path[]` **and** extras, and
  **warns** when other files were staged (`plan --path` / `plan --extras`).
  Warn-first: extras are not a new gate.
- **Sham / weak verify:** `doctor` and `plan --check --strict` surface
  `true`, empty, or mismatched scope. Warn-first unless `--strict`.
- Broad `path[]` (5+ files) with a skinny verify **warns** (doctor), it does
  not exit 4. Shrink the step; do not bend the guard.

---

## Output budgets (agent-facing)

Emitted JSON/text is capped; **files on disk are always complete**.

| Flag | Effect |
|------|--------|
| `--max-chars N` | Cap for `context`, `digest`, `export`, `impact`, `scan`, `fleet`, `sbom`. Default 2000, hard cap 8000, `0` = no cap |
| `--show-risk` | Include `risk`/`format` on `apply`/`next` |
| `--full` | `fleet status` with full per-repo dumps |

`exceptions` are never shrunk.

---

## Commands

Core loop: `init` `status` `plan` `next` `context` `tick` `apply` `verify` `rollback` `land` `why` `claim` `release` `progress`

Index: `impact` `index` `import-scip` `edges` `boundaries`

Checks: `baseline` `repro` `scan` `fuzz` `sbom`

Wrap-up: `digest` `export`

More: `recipe` `fleet` `doctor` `mcp` `packs` `migrate` `completion` `man` `version` `audit` `backup` `restore`

Notable:

- `plan --check` validates the roadmap read-only (exit 5 with findings).
- `next --epic PREFIX` is a **display** filter (warn-first, not a gate).
- `land --commit` or `RFG_AUTO_COMMIT=1` snapshots a **local** commit; never pushes.
- `scan --parse FILE` parses stored scanner JSON into findings + **SARIF**; no exploits.
- `fleet status` reads `fleet.yaml` — **Fleet-Summary**, not a scheduler.
- `packs` lists open vs paid packs; enabling paid packs is exit 4.
- Recovery: `.rfg/` is gitignored. `backup` / `restore <id>` (exit 4 on unknown id).

---

## Hosts: CLI, MCP, Skill

The local CLI **is** the software. MCP and Skill are doors into it.

| | CLI | MCP (core) | Skill `/rfg` |
|--|-----|------------|--------------|
| Lead a campaign | full | same loop | describes *how* |
| Write feature code | no | no | no (AI outside) |

Core MCP verbs match the loop. `root` / `RFG_ROOT` = `--root`.

rfg does not make agents smarter. It makes them worse at silently changing
too much — **if** the host loaded MCP and the agent does not bypass the loop.

---

## Languages — honestly

- **Go, Python, JS/TS:** index, impact, replace work well.
- **Rust:** macros → exit 4, except via `manual` / `implement`.
- **C++:** no `compile_commands.json` → no mechanical C++ apply (exit 4).

The `cxx/rfg` binary is a **subset** of the Python CLI (rename core), not
feature parity. Honest boundary (`python3 scripts/cxx-parity.py --boundary`):
covered are init/plan/next/context/tick/apply/verify-basic/land-basic/progress/claim/rollback;
**Python-only** are Land-Gate, Cross-Verify, output budgets (`--max-chars`,
`--show-risk`), `scan --parse`/SARIF, fleet summary, perf delta.

`schema/capabilities.yaml` is honest: `rename: false`, `index_semantic: false`.
There is no live LSP, no SCIP rename, no tree-sitter in core.

---

## What rfg is not

Not Devin. Not Copilot. Not a SaaS, Jira bot, GitHub App, or token counter.
Not an LLM. Harvest/QLoRA farming is **out of tree**.

Deliberately out: own parser, live SCIP, “the AI writes the patch and rfg
takes credit”. Doctrine: no network in core, no daemons past step end,
stdlib only, no writes outside worktree/`.rfg` until `land`. See
`docs/factory-line.md`.

If you want Autopilot, this repo will disappoint you on purpose.

---

## Maturity

Solid **control plane**, prototype **product**. The loop is deterministic and
tested. As a local discipline tool for an agent loop, rfg is serious. As an
MCP product (releases, support, sessions), it is not: single-maintainer,
stdio transport, no auth. `1.0.0` means schema 3, not “done”.

Where your tests are thin, rfg guarantees “step + affected green”, not
correctness. Warn-first on scope; exit 4 instead of inventing a compiler.

---

## Store layout

```
.rfg/
  roadmap.yaml    goal, hypothesis, profile, acceptance, steps
  state.json      applied/verified/failed, worktree, checkpoints, claims
  env             optional KEY=VAL for verify PATH
  verify/         one log per verify (+ Cross-Verify logs)
  worktree/       Git worktree where steps are applied
  digest.json     handoff snapshot
  audit.jsonl     append-only event log
  land-backups/   roadmap.yaml + state.json (newest 10)
  scan.sarif / sbom.json / baseline.json / last_perf.json / repro.log
```

---

## Development

```bash
python3 -m pytest tests/ -q
python3 scripts/diff_coverage.py     # Diff-Presence-Gate: changed rfg/ functions must be test-referenced
python3 scripts/mutation_sample.py   # Mutations-Stichprobe
python3 scripts/cxx-parity.py        # python vs cxx/rfg + boundary
```

See `CONTRIBUTING.md`. More: `docs/factory-line.md` · `docs/GLOSSARY.md` ·
`docs/agent.md` · `docs/INTEGRATION.md` · `docs/rfg-coverage-roadmap.md`.
