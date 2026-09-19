# Agent-ToDo (rfg)

Maßstab: spart Reads, verhindert falsche Applies, oder spart einen Roundtrip.

Erledigt (Harness): DAG, Worktree-Apply, Rollback, `context`/`tick`/`claim`, nested Impact, Cousin-Sources, MCP=`CLI`-Verben inkl. `root`/`RFG_ROOT`/`land`, Manual-Stage, Orakel-Gates, nested Default-Verify, `rfg land` (auch vs. Worktree-Commits; dirty nur tracked), C++-CLI `land`.

Identifier-Honesty: `ident-boundary` / `honest-init` / `skip-followup` / `tick-worktree-ctx` / failed-clear on re-verify. Clones: schema (`followup: manual` + `__all__`), emitter, clist (Verify-Fail bei Makro, dann Zwei-Step + Land).

## Überlegung (SWE-Kern, nicht Engine)

rfg ist Kampagnen-Kern: Goal → DAG → ein Zug im Worktree → Orakel → Land. Refactor ist der einzige *automatische* Zug (`replace`). Alles Bauen war `manual`. Das bleibt wahr: rfg schreibt keinen Feature-Code.

Ein SWE-Tool in diesem Pfad heißt **dieselbe Schleife, mehr Zugarten, schärfere Orakel** — nicht Devin, nicht Renderer, nicht LLM in rfg.

Später (nicht jetzt): denselben Kern in einer Game-Engine *repurposen* (`--root engine/`, Compile+Smoke als Orakel). Dafür muss der Kern Feature-Kampagnen führen können, ohne Engine-Semantik zu kennen. Deshalb Engine **nicht** in den Zielen; SWE-Hands/Orakel **schon**.

## Ziele (SWE-Harness)

Erledigt in `swe-scaffold` … `swe-followup`: engines `scaffold`/`run`, Acceptance-Kommandos in `progress`/`land`, Recipe `feature-module`, `{id}-followup` nach String-Skip. Timeout: `RFG_VERIFY_TIMEOUT` (Sekunden, Default 60).

Keine weiteren dünnen SWE-Ziele in dieser Runde.

C++-CLI: keine Parität für scaffold/run (Python führt).

## Crash-Recovery (erledigt, CR/QW 2026-09)

`.rfg/` bleibt gitignored. Backup nicht nur bei `land`: `apply`/`verify`/`tick` best-effort (`_backup_best_effort`, prune `LAND_BACKUP_KEEP`). `rfg backup` / `rfg restore <id>` (+ MCP), Exit 4 bei unbekanntem/kaputtem Id. `doctor.recovery` warnt bei incomplete store + vorhandenen Backups und dirty Worktree. Doku: README + Skill. Mtime-Skew `roadmap.yaml` vs `state.json` bewusst **kein** Warning (normal mid-campaign).

## Feedback Arm B (erledigt in Quality-Kampagne 2026-09-19)

Geholfen: `doctor` + `cxx_db_hint` + `plan --check`; `want`/`path`/`verify` + MCP-Parität; Cross-Verify; Land-Gate + `land-backups/`.

Früher fragil, jetzt Pins:
1. Absolutes/fremdes Worktree-gitdir: `worktree_diagnosis` + Heal in `ensure_worktree` (QW-06; `foreign-gitdir` / `broken-gitdir` in progress+doctor).
2. `run` verifiziert am Root, nicht im Stop-Engine-Worktree (`test_run_verify_runs_at_root_not_worktree`).
3. Zweiter nicht-leerer Agent: Exit 5 + `claimed_by` (QM-04; `same_claim_client`).
4. Ziel vs. Boundary bleibt Lektion, kein Code-Ziel: cxx-Subset ehrlich halten (`scripts/cxx-parity.py --boundary`).

Große Scopes gehen nur klein geschnitten: Goal + Acceptance als Gate; DAG mit 1 ID / 1 `want` / schmalem `path[]` / genau 1 echtem Verify; Engine pro Slice; Isolation + Recovery. Voll-Rewrite ≈ 30–50 Modul/Verb-Slices + schrumpfende Parity-Boundary.
Klein bleiben: ehrliche Boundary; 1–3 Steps für Fix/Heal/Spike/Survey; bei Exit 4 Scope verkleinern statt Guard biegen.

## Contract vs Cross-Verify (offen, gelernt 2026-09-19)

Want + FAIL-Satz + `path[]` + ein Verify reicht zum Fremd-Implementieren. Reibung sitzt um die Vorgabe:

- Verify-Testdatei nicht in `path[]`, oder Cross-Nachbar teilt `path[]` ohne die neue Semantik → apply Extra-Warnung, Cross-Verify rot.
- PreToolUse-Hook gated auf `dag.next_id`, nicht `claim_step` (Claim schaltet Writes nicht frei).
- `apply` staged den ganzen Dirty-Tree; Extra-Warnungen werden Rauschen.

Maßstab: verhindert falsche Applies / spart einen Roundtrip. Pin-Idee (warn-first, kein Gate): Step, dessen Verify-Testdatei nicht in `path[]`/`extras` liegt, oder dessen angewandter path-overlap-Nachbar die neue Semantik nicht kennt, warnt **bevor** apply Extra verschluckt. Hook an Claim binden oder den Mismatch benennen.

## Inventar 2026-09-19 (Techdebt + Feature-Stand)

Live: `next` null, 186/186 verified, `progress.ok` true, `doctor.ok` true. Version `1.0.0` = Schema 3, kein Product-Claim. Python führt; `cxx/rfg` ist Rename-Kern.

Was **sitzt** (Kampagnen-Kern, nicht Parser): Goal → DAG → ein Zug im Worktree → Orakel → Land. Engines `replace`/`scaffold`/`run`/`implement`/`manual`/`survey`/`ast-grep`. MCP-Kern = CLI-Schleife (16 Verben). Land-Gate, Cross-Verify, backup/restore, recipes (7 YAML + Code-Rezept `feature-campaign`), `plan --check`, Claims (`RFG_AGENT`), Completions/Man, `migrate` → v3, GitHub-Workflow `rfg.yml` (unittest + doctor).

Was **da ist, aber dünn** (Ehrlichkeitsschicht, keine Semantik):

| Fläche | Stand | Grenze |
|--------|--------|--------|
| `impact` / `index` | Datei-Hash + `text.count` auf letztem Segment | kein Typ, kein Rename |
| `import-scip` | Dump mergen, Substring auf Symbol | kein Live-Indexer |
| `lsp.py` / `caps.py` | `shutil.which` | nie `textDocument/references` |
| `replace` | Identifier-Rewrite, skip Comment/String | `rename: false` in capabilities |
| `ast-grep` | Binary-Wrap, sonst Exit 4 | kein eigener Parser |
| `edges` / `boundaries` | Regex (cgo/pyo3/napi/cxx-ffi), `complete: false` | keine vollständige FFI |
| `scan`/`fuzz`/`sbom` | Parse JSON oder erstes Tool auf PATH | ohne Tool: Presence/Exit 4 |
| `fleet` | lokale `fleet.yaml`-Zeilen | kein Estate-Scheduler |
| `export dashboard` | statisches HTML | Paid Read-Dashboard = Exit 4 |
| `risk` | Heuristik 0–100 | kein semantisches Safety |
| `progress`/`digest` | Counts + Exceptions + Datei | keine PM-UI, kein Nightly-Daemon |
| H0–H7 in `docs/rfg-coverage-roadmap.md` | Protokoll/Orakel **gebaut** | nicht plan.md Phase-2/3-Semantik |

C++-Boundary (ehrlich): covered init/plan/next/context/tick/apply/verify-basic/land-basic/progress/claim/rollback (+ help nennt status/doctor). **Python-only:** Land-Gate, Cross-Verify, Budgets, scan/SARIF, fleet, perf-delta, recipe/MCP/why/impact/backup. C++ `cmd_claim` überschreibt still (Apply prüft Holder; Python-Claim ist QM-04). Keine scaffold/run-Parität.

**Techdebt, das sich lohnt** (Maßstab: Reads / falsche Applies / Roundtrip):

1. Contract vs Cross-Verify + Hook=`next_id` + apply staged dirty tree — schon offen oben.
2. `rfg/cli.py` ~2944 Zeilen / 38 `cmd_*` — God-Module; nächster Slice muss oft `cli.py` + Nachbar + Test anfassen.
3. `plan.md` und `schema/capabilities.yaml` versprechen SCIP/LSP/Rename; README und Doctrine (T4) sagen das Gegenteil. Cold-Agent liest plan.md → falscher Scope.
4. Dogfood-Roadmap: `doctor` oracles ~154 Warnungen (shared verify, depends ohne path, breadth) auf der gelandeten 186-Step-Kampagne. Warn-first, aber Rauschen; kein Gate.
5. Skill-Duplikat: `plugin/rfg/skills/rfg/SKILL.md` ≠ `.grok/skills/rfg/SKILL.md`.
6. QM-05 `--allow-external-root` hard-guard bewusst deferred (gotoharness).
7. Ledger `stale_functions` Tombstones geparkt (warn-only, I3).
8. `examples/cxx` Submodule bleibt oft dirty nach Land — nicht Teil des Python-Lands.

**Kein Debt** (bewusst nicht): Live-LSP/clangd/tree-sitter, semantisches Rename, LLM in rfg, parallele Claims, SaaS/Paid-Packs, Game-Engine-Typen, Dirty-Apply für `replace`.

Kampagne `current-loop-friction` (2026-09-19, Backup `20260919T013647-1fbe2857`): 5/5 verified, `next` null. Noch nicht gelandet.

Später (eigene Kampagnen, nicht diese): `hook-claim-bind`, `cli-split`, `oracle-noise-cap`, `cxx-claim-holder`, `qm05-external-root`, `ledger-tombstones`.

## Bewusst später / nicht in rfg

- Tick bleibt Stop bei `manual` — KI schreibt den Patch außerhalb.
- PR/CI, parallele Claims, Reviewer-Agent (Git-Host, nicht Harness).
- Game-Engine, ECS, Assets, Editor — Repurpose *mit* rfg, nicht *in* rfg.
- C++-`init` nested Verify (Python führt).

## Nicht tun

- clangd, Live-SCIP, tree-sitter, LLM in rfg
- Semantisches Rename / Full-SWE-Generator
- MCP-Fläche aufblasen (`RFG_MCP_ALL=1` für Packs; Kern = Kampagne inkl. doctor/recipe/why/impact)
- Stop-Hook bei jedem offenen `next` blocken
- SaaS / Paid-Packs / Jira
- Dirty-Apply für `replace`
- Engine-Typen (`Entity`, Szene, Shader) im rfg-Kern
