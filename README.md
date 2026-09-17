# rfg

**rfg leads a campaign through your code — one move at a time — and checks after every move whether the project still holds.**

Renaming a type across 40 files, closing a feature gap in 8 steps, hardening a module: without a plan this becomes one giant diff, tests run at the very end, and when something breaks nobody knows which step caused it. rfg is a **local campaign leader**: it remembers the goal and the plan, hands out **one** next step, runs mechanical renames in a Git copy, runs **your** test/build command after every move, and can take the last move back.

rfg is not a compiler, not a chatbot, not a GitHub bot, and **not an agent harness**. The AI (or you) writes the plan and the new code. rfg writes mechanical renames itself and **does not lie**: where it cannot do something (C++ without a compile database, Rust macros, an empty verify), it exits 4 instead of saying “all good”.

- Python 3.10+, standard library only
- Runs offline, on your machine
- License: MIT

```
python3 rfg.py --help
```

---

## The loop

```
Goal (what is true when we are done)
   ↓
Plan: DAG of steps (want, paths, depends, one verify per step)
   ↓
For each free step:
   1. context  — the contract: want, paths (may be missing), verify
   2. tick     — replace/scaffold/run: execute + check
                 implement/manual: claim, contract, stop (you/AI edit, then apply)
   3. apply    — mechanical, or stage edited files into the worktree
   4. verify   — your command plus affected steps (see below); log kept
   5. On red: rollback last
   ↓
next is null → land (worktree → repo, with gate + re-verify)
```

State lives in `.rfg/roadmap.yaml` + `state.json`. Git is the transaction: work happens in a **Git worktree** (`.rfg/worktree`), `rollback last` restores the checkpoint, `land` copies back only when everything is verified.

Step states: `ready` → `claimed` → `in_progress` → `implemented` / `applied` → `verified` (plus `blocked` / `failed`). `verified ≠ done` is enforced: `land` refuses applied-but-unverified steps.

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

`tick` on a rename rewrites whole identifiers in the copy — strings like `"old_name"` are left alone. Red → `python3 rfg.py rollback last`.

## Quickstart: extend code

Same `init` / `next` / `tick` / `land` — different step kinds:

```
python3 rfg.py recipe apply feature-module --path extra/greet.py --verify "python3 -c 'import extra.greet'"
python3 rfg.py tick          # scaffold
python3 rfg.py tick          # implement: stop — you/AI write the content
python3 rfg.py apply         # stage files into the worktree
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

JSON for scripts and agents: `--format json` everywhere. Exit codes: `0` ok · `2` verify failed · `3` dirty tree · `4` unsupported (won't guess) · `5` conflict.

---

## Step kinds (`engine`)

| Engine | What happens |
|--------|--------------|
| `replace` | Mechanical rename of whole identifiers (code only, never strings/comments) |
| `ast-grep` | Structural replace, if the binary exists |
| `scaffold` | Create empty files |
| `implement` | Feature contract: want, paths (may be missing), one verify. `tick` stops, you/AI write, `apply` stages, `verify` checks |
| `manual` | Hand work on existing files |
| `run` | Just a command (smoke) |
| `survey` | Notes-only investigation, no code change |

Ready-made mini-plans: `python3 rfg.py recipe list`. Profiles (same loop, different check): refactor, feature, perf, debug, security.

---

## Verify discipline

One oracle per step, and the step's own command is only the start:

- **Cross-verify (level 1):** `verify` also runs the verifies of direct dependents and steps with path overlap — but only ones already applied. Pending steps cannot pass yet and never block. Failures are reported as `cross-verify failed for …`, with per-step logs (`.rfg/verify/<step>__cross_<id>.log`).
- **Land gate (level 2):** `land` re-runs the last step's verify **plus** the suite-level `rm.verify` gate and the goal acceptance commands. A missing toolchain skips the gate (logged) instead of failing it.
- **Every verify leaves a log** under `.rfg/verify/`. Emitted output is clipped (`…[truncated, see log]…`); the file on disk is always complete.
- **No silent scope:** `apply` stages everything you changed (declared `path[]` *and* extras) and warns when files outside `path[]` were staged — extend `path[]` via `plan --path` or allowlist via `plan --extras` (e.g. `rfgfeedback.md`) if intentional.
- **No growth penalty:** identical verifies across steps warn with a dedup hint; they never block planning.

---

## Output budgets and token heuristic

Agent-facing output is budgeted; files on disk are always complete. Every capped payload says so (`truncated`, `chars`, `token_estimate`, `max_chars`).

| Flag | Effect |
|------|--------|
| `--max-chars N` | Cap for `context`, `digest`, `export`, `impact`, `scan`, `fleet`, `sbom`. Default 2000, hard cap 8000, `0` = no cap (explicit human override) |
| `--show-risk` | Include `risk`/`format` blocks in `apply`/`next`. Default is slim |
| `--full` | `fleet status` with full per-repo progress dumps (default is one compact row per repo) |

Safety info is never budgeted away: `exceptions` are never shrunk, and budget fields are always reported.

### Heuristic: what does rfg cost?

Measured on a small 2-step campaign (`--format json`, chars ≈ tokens ÷ 4):

| Command | ≈ Tokens |
|---------|----------|
| `next` / `tick` (contract) / `apply` | ~190 each |
| `verify` (small output) | ~50 (clipped; full text in the log file) |
| `progress` | ~145 |
| `impact --symbol` | ~85 |
| `context --sources` (real repo) | ~760 with snippets |

**Rule of thumb: one implement loop (`next` → `tick` → `apply` → `verify` → `progress`) costs ~750 tokens of rfg overhead per step.** As a share of context that is roughly:

- **≤ 25% gross on small steps** (2–3k tokens of code context),
- **< 10% on large steps** (10k+ tokens),
- **often net zero or negative**: the budget counts what rfg *costs*, not what it *saves* — no re-reading the tree every turn, no edits in the wrong files, no repeated full-suite runs (cross-verify covers only affected steps; the gate runs once at `land`). One prevented wrong turn costs more than ten rfg loops.

Worst cases are capped, not open-ended: index dumps are hard-capped (24 files + warning), logs are file-only, defaults are slim. Full truth is always one explicit flag away (`--show-risk`, `--max-chars 0`, `--full`) or a file read (`.rfg/verify/`, `.rfg/digest.json`, `.rfg/scan.sarif`, `.rfg/sbom.json`).

If overhead still hurts, make **steps bigger, not caps smaller**: fewer loops beat tighter budgets, and caps must never cost functionality.

---

## Commands

Core loop: `init` `status` `plan` `next` `context` `tick` `apply` `verify` `rollback` `land` `why` `claim` `release` `progress`
Index: `impact` `index` `import-scip` `edges` `boundaries`
Checks: `baseline` `repro` `scan` `fuzz` `sbom`
Wrap-up: `digest` `export`
More: `recipe` `fleet` `doctor` `mcp` `packs` `migrate` `completion` `man` `version` `audit`

Notable behaviors:

- `scan --parse FILE [--tool NAME]` parses stored scanner JSON (trivy, grype, pip-audit, osv-scanner) into findings + summary + SARIF (`.rfg/scan.sarif`); exits 2 on high/critical findings. Without `--parse` it runs the first present scanner as JSON. No exploits, no payloads, ever.
- `fuzz [--seconds N]` runs the configured fuzz command, or builds one from a present fuzzer (`--target` optional).
- `baseline` / `repro` feed the perf/debug oracles; `progress` shows baseline-vs-last-run ratio in its `perf` section.
- `fleet status` reads `fleet.yaml` and prints one compact row per repo (counts, `next`, totals). Read-only overview — no scheduler.
- `export batch` writes an offline batch spec (`.rfg/batch-changes.yaml`); `export dashboard` writes a static HTML snapshot. No server.
- `packs` lists open vs paid packs; enabling paid packs is exit 4.

---

## Hosts: CLI, MCP, Skill

The local CLI **is** the software. MCP and Skill are just doors into it — no second app.

| | CLI | MCP (core) | Skill `/rfg` |
|--|-----|------------|--------------|
| Lead a campaign | full | same loop | describes *how* |
| `doctor`, `recipe`, `why`, `impact` | yes | yes | mentioned |
| Extended verbs (`scan`/`fuzz`/`sbom`, fleet…) | yes | behind `RFG_MCP_ALL=1` | no |
| `--help`, completion, man | yes | no | no |
| Write new feature code | no | no | no (AI outside) |

Core MCP verbs: `init` `plan` `next` `context` `tick` `apply` `verify` `land` `rollback` `claim` `release` `progress` `doctor` `recipe` `why` `impact`. Same `.rfg/` store, same exit codes. `root` / `RFG_ROOT` = `--root`. `claim` when several agents share a repo (`RFG_AGENT`); claims are per-repo and never leak across repos.

rfg does not make agents smarter. It makes them worse at silently changing too much — **if** the host loaded the MCP and the agent does not bypass the loop.

---

## Languages — honestly

- **Go, Python, JS/TS:** index, impact, replace work well.
- **Rust:** macros → exit 4, except via `manual` / `implement`.
- **C++:** no `compile_commands.json` → no mechanical C++ apply (exit 4); verify should be a real compiler. Recipe: `cxx-ffi-manual`.
- The `cxx/rfg` binary is a **subset** of the Python CLI (rename core), not feature parity. Honest boundary (`python3 scripts/cxx-parity.py --boundary`): covered are init/plan/next/context/tick/apply/verify-basic/land-basic/progress/claim/rollback; **Python-only** are land gate, cross-verify, output budgets, `scan --parse`/SARIF, fleet summary, perf delta.

Uncertainty is sharpened with a better check command, not with more magic in the replace.

---

## What rfg is not

No SaaS, no Jira/Linear, no GitHub app, no token counter, no kill switch for other people's agents in the cloud. It is the **local** plan-and-check core for **one** campaign in **one** Git repo. Fleet is a status reader, not an estate scheduler.

Deliberately out: own parser, live SCIP, an LLM inside rfg, exploit building, “the AI writes the patch and rfg takes credit”.

---

## Maturity

Honest version: solid core, prototype product. The loop (plan → claim → apply → verify → land/rollback) is deterministic, tested (full suite green), and strict — `verified ≠ done` is enforced, not suggested. As a **local discipline tool for an agent loop**, rfg is serious. As an **MCP product** (spec coverage, releases, support), it is not finished: minimal stdio transport, no auth/sessions, single-maintainer, version `1.0.0` means schema level, not market-ready. Where your tests are thin, rfg guarantees “step + affected green”, not correctness.

---

## Store layout

```
.rfg/
  roadmap.yaml    goal, hypothesis, profile, acceptance, steps (want/paths/extras/depends/verify)
  state.json      applied/verified/failed, worktree, checkpoints, claims
  env             optional KEY=VAL toolchain env for verify (e.g. PATH with user-local mvn/go/cargo)
  verify/         one log per verify (+ cross-verify logs)
  worktree/       the Git worktree where steps are applied
  digest.json     handoff snapshot (full file; emitted output is budgeted)
  audit.jsonl     append-only event log
  scan.sarif      security findings (when scan ran)
  sbom.json       CycloneDX-lite inventory (always complete on disk)
  baseline.json / last_perf.json / repro.log   perf/debug oracle data
```

---

## Development

```bash
python3 -m pytest tests/ -q          # full suite
python3 scripts/diff_coverage.py     # changed rfg/ functions must be test-referenced
python3 scripts/mutation_sample.py   # sampled mutants must all be killed
python3 scripts/cxx-parity.py        # python vs cxx/rfg parity + boundary
```

Conventions: stdlib only, offline by default, every step needs a negative test, core files ship with cross-suite coverage, docs (`docs/rfg.1`, completions, this README) move with the flags.

More depth: `docs/rfg-coverage-roadmap.md` · agents: `docs/GROK-BUILD.md` · CI: `docs/INTEGRATION.md`.
