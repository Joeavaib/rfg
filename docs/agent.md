# rfg for an agent (read this instead of the tree)

rfg is a **host-agnostic CLI**. Grok Build is one client. MCP tools are the same verbs as `python3 rfg.py --format json`. Prefer MCP; else CLI JSON. `root` / `RFG_ROOT` = `--root`.

**Do not** mass-edit a rename. **Do not** crawl the repo to find the next file. `context` is the contract. Cousin/impact snippets only with `context --sources`. You write feature code; rfg does not.

---

## Contract (keep this)

```
0 ok · 2 verify fail → rollback last (replace) · 3 dirty · 4 unsupported (do not guess) · 5 conflict
ready → claimed → in_progress → implemented/applied → verified
land refuses applied-but-unverified (exit 5). next null → land.
Store: .rfg/roadmap.yaml + state.json. Git is the transaction (.rfg/worktree).
progress always exits 0; health is data.ok. implemented includes verified.
```

Product goal once: `plan` with `goal`, **no** `step`. Step fields: `want`, `path` (JSON array ok, missing files ok), `verify`, `depends`, optional `extras`. `--goal` + `--step` together is exit 5.

Feature default engine is `implement` if there is no `--from`. Survey: `engine=survey`. Unknown engine: exit 4 at plan/tick.

---

## Loop

1. `doctor` first (git; `module` = this checkout’s binary). `init` if no `.rfg/`.
2. `plan --goal` then steps, **or** `recipe apply feature-module` / `feature-campaign` with `--step id:path:verify`.
3. `next` → `context` → `tick`.
4. **replace / scaffold / run:** `tick` = apply+verify. `apply --dry-run` if unsure.
5. **implement / manual / survey:** `tick` claims `in_progress` and returns `want`, `path`, `edit_root`, `after_edit: apply`. Untracked dirty root is ok. **Edit at repo root**, then `apply` (copies `path[]` and declared `extras` into the worktree; undeclared files refuse without `--allow-extra`), then `verify` (only from implemented; log `.rfg/verify/<step>.log`).
6. Exit 2 → `rollback last`. `next` null → `land`. Unfinished / failed → land exit 5. Dirty tracked root (except implement isolation) → exit 3.
7. `progress` for counts/exceptions (`data.ok`). Plan JSON from `plan --list` is ids/status, not file dumps. `impact` is counts; `files=true` / `--files` to list.

Test ROI (not a gate): `docs/test-focus.md`.

---

## Naive questions (first session) → answers

These are the expensive questions. Do not rediscover them from `rfg/*.py`.

**What is rfg?** A local plan-and-check loop for one campaign in one Git repo. Not an LLM, not a test framework, not Jira.

**Where do I edit?** Mechanical engines: nowhere — rfg rewrites the worktree. Stop engines (`implement`/`manual`/`survey`): **repo root**, then `apply` copies into `.rfg/worktree`. `run` executes at root (tracked-dirty needs `--force`).

**When is a missing file ok?** On `implement` / scaffold paths that do not exist yet. `context` lists `missing`. That is the contract, not an error.

**What may I change?** Files in this step’s `path[]`. Side artefacts (`rfgfeedback.md`) via `plan --extras`. `apply` warns if it staged undeclared files — extend path or extras; do not ignore the warning.

**What does verify run?** The step command as an **unsandboxed shell** (cwd root or worktree, may write anywhere — `roadmap.yaml` is a script host, review before running), then **Cross-Verify**: already-applied dependents and path-overlap neighbors. Pending neighbors never block. Logs under `.rfg/verify/`. Failures stay exit 2; labels (ENV/COST/PRE-EXISTING/REGRESS-SUSPECT) are hints.

**What does land run?** Last step verify + suite `rm.verify` (**Land-Gate**) + executable acceptance. Trivial/`true` verify → exit 4 + revert. Missing gate binary → skip + log, not fail. Open steps or applied-not-verified → exit 5.

**Can I `land` after only `apply`?** No.

**Why did I get 4?** Unsupported on purpose: Rust macros on replace, C++ without `compile_commands.json`, missing ast-grep binary, trivial verify, unknown engine, paid packs. Fix the engine/oracle; do not invent a parser.

**Why 3?** Tracked files dirty at root when rfg would apply mechanically, or land without a stop-engine worktree. Commit, stash, or finish the implement `apply`. Untracked files are ok for implement.

**Why 5?** Claim held by another `RFG_AGENT`, apply budget exhausted, land while next/failed nonempty, `plan --goal` with `--step`, `plan --check` findings.

**MCP vs CLI?** Same store, same exits. Core tools listed below. Extra catalog (`scan`/`fuzz`/`sbom`/fleet/…) only if `RFG_MCP_ALL=1`. `release` is core. `backup`/`restore` exist on CLI (and MCP schemas); use CLI if unsure.

**Claims?** `claim` / `tick` lock `state.claim_step` for `RFG_AGENT`. Empty agent on MCP apply is “this client”, not a second identity. Claims never leak across repos.

**Hub alignment?** Only steps with >10 neighbors get **one** extra alignment verify. Leaves (≤3) get none. Not transitive.

**Output too big?** Defaults cap agent-facing JSON (`--max-chars`, default 2000). Disk files stay full. `--max-chars 0` is the explicit uncapped override. `exceptions` never shrink.

**Recovery?** `.rfg/` is gitignored. `backup` lists `.rfg/land-backups/`. `restore <id>` (exit 4 unknown). `doctor` warns if store incomplete but backups exist. `rollback last` is the last **git** checkpoint in the worktree, not a YAML restore.

**cxx/rfg?** Subset binary (rename core). No Land-Gate, no Cross-Verify, no budgets. Do not assume Python parity.

**Fleet?** Read-only status over `fleet.yaml`. Not a scheduler.

**Who writes tests?** You. rfg only runs the command you put on the step / roadmap. Sham verifies (`true`, empty) are doctor warnings; `--strict` makes them errors — on `plan --check` as findings, on `tick --strict` / `land --strict` as a gate (verify must name a file under `path[]`/`extras`).

---

## Grok Build wiring (this checkout)

- Skill: `.grok/skills/rfg/SKILL.md` (`/rfg`) — slim; this file is the long form.
- MCP: `.grok/config.toml` → `python3 -m rfg mcp` with `PYTHONPATH` / `RFG_HOME`. Core = CLI campaign: init, plan, next, context, tick, apply, verify, land, rollback, claim, release, progress, doctor, recipe, why, impact.
- Plugin fallback: `plugin/rfg/mcp-launch.py` or `scripts/rfg-mcp.py`.
- Hooks: `.grok/hooks/rfg.json` — PreToolUse denies Write/StrReplace outside `dag.next_id` `path[]`, not `claim_step` (claiming another step does not unlock writes; `extras` do not unlock Write). `engine=manual` is allow-all; implement is gated. Stop blocks if a step is applied but not verified. Trust the folder (`/hooks-trust`).
- Plugin bundle: `plugin/rfg/` + `.grok-plugin/marketplace.json`.

Reload MCP with `r` on the MCP tab or a new session.

## Other repos

Install the plugin, or copy the skill to `~/.grok/skills/rfg/` and point user MCP at `scripts/rfg-mcp.py` with `RFG_HOME` = this checkout. Reload MCP. `doctor.checks.module` must be this tree; `user_skill` must mention `implement`.
