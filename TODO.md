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

## Contract vs Cross-Verify (teilweise, Kampagne CF 2026-09-19)

Want + FAIL-Satz + `path[]` + ein Verify reicht zum Fremd-Implementieren. Reibung sitzt um die Vorgabe.

Erledigt in `55478b7` (`current-loop-friction`):
- CF-02: `contract_warning` auf tick/apply/`--dry-run` (Exit 0), wenn Verify-Testdatei nicht in `path[]`/`extras`. `plan --check` bleibt kein Gate. Survey/Extras schweigen.
- CF-03: `plan.md` erste Seite Historical → README; `capabilities.yaml` überall `index_semantic`/`rename: false`.
- CF-04: Plugin zeigt auf Canonical-Skill; Budgets bleiben.
- CF-05: Hook/`agent.md` **nennen** `dag.next_id` vs `claim_step`. Verhalten unverändert.

Offen (primärer Weg, siehe unten): Hook an Claim binden; Apply staged weiter den Dirty-Tree (Warnung ≠ Isolation).

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

**Techdebt, das sich lohnt** — Rang nach der CF-Land-Runde, vor Trace-Farm-Feedback (2026-09-19 Abend). Kleine Modelle treffen zuerst die **Schleifen-Reibung**, nicht fehlende Semantik.

### Primärer Weg (nächste Kampagne, nicht neue Fläche)

Was den Worker umwirft, sobald er kein Frontier ist:

1. **Hook vs Claim** (`hook-claim-bind`) — PreToolUse immer noch `dag.next_id`, nicht `claim_step`. CF-05 hat es nur benannt. Falsche Datei / Shell-Bypass. Maßstab: verhindert falsche Writes.
2. **Apply staged den Dirty-Tree** — `contract_warning` (CF-02) warnt; Isolation fehlt. Land zog `docs/GROK-BUILD.md` extra mit. Warn-first: Extra nicht als Patch zählen (Farm filtert `path[]`; rfg staged trotzdem).
3. **Land-Gate vs Verify-Timeout** — `cmd_land` nutzt fest 60s, ignoriert `RFG_VERIFY_TIMEOUT`; nacktes `pytest` (init-Default) ohne `PYTHONPATH` sammelt nicht / läuft in Timeout. Land der CF-Kampagne ging erst, nachdem `rm.verify` auf die Acceptance gesetzt war. Pin: Land-Gate wie `cmd_verify` (Timeout-Env + `load_env`). Kein neues Gate, gleiche Semantik.
4. **`next` ≠ `recommend`** — Recommend = critical path / shortest verify-string. Farmer-Agent suchte `complexity` (existiert nicht, Schema `additionalProperties: false`). Doku/Skill eine Zeile: nimm `next.id`, nicht Recommend, nicht ein Complexity-Feld.

Nicht in rfg (Zusatz bleibt Zusatz): Trace-Farm `/home/joe/Dokumente/prod/rfg-farm`. Harvest nach Verify, vor `init`. `init` ohne Harvest = Contracts weg, nur nackte Diffs (98/103 Packets).

### Danach / nicht primär

- `cli-split` — `rfg/cli.py` ~3k Zeilen / 38 `cmd_*`. Jeder Slice trifft die Datei; Split ist eigene Kampagne, nicht „nebenbei“.
- `oracle-noise-cap` — 154 Doctor-Warnungen auf der 186er-Dogfood-Roadmap. Warn-first, kein Gate; Rauschen für Menschen, nicht für Verify.
- `cxx-claim-holder` — C++ `cmd_claim` überschreibt still; Python-Claim ist QM-04. Nur wenn cxx-Worker real sind.
- QM-05 `--allow-external-root` deferred (gotoharness).
- Ledger-Tombstones (I3, warn-only).
- `examples/cxx` dirty nach Land — Submodule, nicht Python-Land.

Erledigt in CF (nicht mehr offen): plan.md/capabilities-Lüge (CF-03), Skill-Pointer (CF-04), Contract-Warnung Testdatei (CF-02), Hook benannt (CF-05). Land: `55478b7`.

**Kein Debt** (bewusst nicht): Live-LSP/clangd/tree-sitter, semantisches Rename, LLM in rfg, parallele Claims, SaaS, Complexity-Feld, Traces im Kern, Game-Engine-Typen, Dirty-Apply für `replace`.

Spätere Kampagnen-IDs: `hook-claim-bind`, `apply-path-isolation` (warn-first), `land-gate-timeout`, `next-vs-recommend-doc`. Nicht: `complexity`, nicht Farmer in `rfg/*.py`.

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
