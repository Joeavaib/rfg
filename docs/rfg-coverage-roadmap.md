# rfg Abdeckungs-Roadmap

Nordstern: PM steckt Goals/Acceptance ab. Agents dürfen nur geführte Züge. Dieselbe Schleife für Feature, Refactor, Perf, Debug, Security — andere Orakel, nicht fünf Produkte.

Sechs Schichten (unten nach oben): Memory → Hands → Oracles → Profiles → Actors → Surfaces. Impact/Index ist Querschnitt. Nie Surface/Fleet bauen, bevor Memory+Oracle für die Fähigkeit stehen.

## Phasen

| Phase | Abdeckung | Done wenn |
|-------|-----------|-----------|
| **H0** | `.rfg/` Schemas, Status, Worktree, ein Verify, TS+patch/ast-grep | Wochenend-Handoff sichtbar im Repo |
| **H1** | Volle CLI-Schleife, Step-DAG, pluggable Verify, Go starten | Freitag Status → Montag `next` ohne Neu-Erklärung; CI kann verify |
| **H2** | MCP (5–8 Tools), Claim/Lock, Agent-Budgets, Audit; Plan-KI optional, Apply deterministisch | Cursor/Claude arbeiten Roadmap ohne Prompt-Roman |
| **H3** | PM-Goal-Vertrag (UI), Progress für Nicht-Devs, Nightly-Digest | Tech-Lead legt Welle an, morgens nur Exceptions |
| **H4** | Profile Profiling + Debugging (Baseline/Repro als Oracle) | Perf-Budget & Bug-Repro sind First-Class Roadmaps |
| **H5** | Security-Profil: Trust Boundaries, Scan/Fuzz-vorhanden, SBOM — keine Exploit-Hilfe | Security-Kampagne = Roadmap mit Gates |
| **H6** | Fleet, Multi-Repo, Export zu Batch Changes, Paid Packs | Platform steuert Estate-Wellen |
| **H7** | Schema-Evolution, FFI-Kanten, Recipe-Ökosystem, optional Read-Dashboard | Default in Agent-Loop + CI |

Fünf Verträge, in dieser Reihenfolge: Goal → Plan → Zug (nur Harness) → Orakel → Handoff/Audit. Fehlt einer: Chaos oder Theater.

Dauerhaft nicht: eigener Parser/IDE, „KI schreibt den Patch“ als Kern, Exploit-Bau, Jira-Ersatz, APM, perfektes C++-Rewrite.

Heuristik: pro Sprint entweder neues Oracle-Profil oder neue Sprache. Jede Phase endet mit einer Dogfood-Roadmap. Unsicherheit → Memory/Oracle schärfen, nicht mehr Apply-Magie.

H0–H7 gebaut. H7: Schema v3 (`migrate`), Recipe-Ökosystem (`recipe list|apply`), FFI-Recipe `cxx-ffi-manual`, optionales `export dashboard` (statisches HTML, kein Server). Paid Read-Dashboard bleibt Exit 4. Apply bleibt deterministisch.

## Härtung H (Stress-Feedback, gebaut)

- **Verify-Disziplin:** Cross-Verify Stufe 1 (Dependents + Pfad-Überlappung beim `verify`), Land-Gate Stufe 2 (`rm.verify`-Suite vor `land`, toolchain-bewusst), Extra-Warnung statt stillem `extra_omitted`, Verify-Dedup nur Warnung statt Exit-5-Bremse, Depends-Coercion für JSON-Array-Strings.
- **Test-Landschaft:** Diff-Presence-Gate (`scripts/diff_coverage.py`), stdlib-Property-Tests (Coercion, YAML-Roundtrip), Mutations-Stichprobe 4/4 (`scripts/mutation_sample.py`).

## Token-Effizienz K (gebaut)

- Output-Budgets: `--max-chars` (Default 2000, Cap 8000) für context/digest/export/impact, `truncated`/`chars`/`token_estimate`-Felder (`rfg/tokens.py`).
- Slim-Default: `risk`/`format` nur mit `--show-risk`; Index-Deckel (24 Dateien + Warnung) plus Token-Zählung; Verify-Logs Datei-only mit Clip-Hinweis.
- Fleet-Summary als kompaktes JSON (`fleet status`, `--full` für Details); Batch-Export gedeckelt mit Step-IDs.

## Orakel-Stand (gebaut)

- **H5-Security jetzt echt:** `scan --parse` für trivy/grype/pip-audit/osv-scanner mit Summary + SARIF (`.rfg/scan.sarif`), Exit 2 bei high/critical; `fuzz` baut echte Befehle (`--seconds`, Templates pro Fuzzer).
- **H4-Perf sichtbar:** `run_perf` speichert Last-Run, `progress` zeigt Baseline-vs-Last-Ratio (`perf`-Sektion).
- **C++-Boundary (ehrlich, kein Rewrite):** `cxx/rfg` = Rename-Kern (init/plan/next/context/tick/apply/verify-basic/land-basic/progress/claim/rollback); Python-only: Land-Gate, Cross-Verify, Budgets, Scan-Befunde, Fleet-Summary, Perf-Delta (`scripts/cxx-parity.py --boundary`).
- **DX:** Completions kennen alle globalen Flags, Man-Page dokumentiert Budgets, Telemetry bleibt opt-in/lokal-only und ist getestet.
