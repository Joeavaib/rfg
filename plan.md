Kurze ehrliche Antwort: **Das Gesamtpaket gibt es so nicht.** Einzelteile schon – und die sind nicht klein.

## Was es schon gibt

Drei Schichten sind besetzt:

**1. Transformieren**  
ast-grep, GritQL, OpenRewrite, Polyglot Piranha. Die ändern Bäume. Sie führen keine Refactor-Roadmap.

**2. Kampagnen in der Firma**  
Codemod Campaigns, Moderne/OpenRewrite, Sourcegraph Batch Changes. Multi-Repo, PRs, Dashboards. Stark, aber Plattform/Enterprise, oft Java/JS-lastig, nicht lokal-first „nächster sicherer Step in diesem Repo“.

**3. Zählen und Planen ohne Semantik**  
`refactor-tracker` zählt Fortschritt über Shell-Commands. `roadmap-cli` / agentkan / refrakt planen Arbeit allgemein, nicht Code-Impact. SCIP indexiert Symbole, managed nichts.

Was fehlt als zusammenhängendes Produkt:

- Hypothese → Impact → Step → Checkpoint → Verify → Rollback  
- lokal, CLI-first, anbindbar  
- PY / TS / Go / Rust / C++ mit ehrlichen Capability-Stufen  
- Cross-Language-Kanten (cgo, pyo3, napi, cxx)  
- Plan als versioniertes Artefakt im Repo, nicht nur eine Cloud-Kampagne

Deshalb lohnt bauen. Nicht weil „Refactoring niemand macht“, sondern weil **Management + Semantik + Safety-Loop** noch niemand schlank für genau diesen Stack verdrahtet.

---

# Plan: `rfg` (Arbeitstitel)

Ziel v1: Ein nützliches lokales CLI, mit dem ein Mensch oder Agent ein großes Refactor **führen** kann, ohne alles auf einmal anzufassen.

## Prinzipien

1. Kern ist die Roadmap, nicht der Parser.  
2. Parser und Language Server leihen wir uns.  
3. Falsch ist schlimmer als „unsupported“.  
4. Alles, was ein Agent braucht, kommt als JSON + Exit-Code.  
5. Git ist das Transaktionssystem.

## Architektur

```text
CLI / MCP / JSON
        │
   Roadmap Engine     ← euer Produkt
   (plan, step, hypo, checkpoint, verify)
        │
   Impact Graph
   (files, symbols, refs, cross-lang edges)
        │
   ┌────┴─────────────────────┐
   Index A          Index B
   tree-sitter      SCIP + LSP
   ast-grep         gopls, rust-analyzer,
                    clangd, tsserver, pyright
        │
   Apply Adapters (pro Sprache, capability-gated)
        │
   git worktree + verify commands
```

## Phasen

### Phase 0 – Vertrag (1 Woche)

Festzurren, bevor Code wuchert.

- Repo-Layout: `crates/` oder `cmd/` + `schema/` + `testdata/`
- JSON Schema v0 für:
  - `Roadmap`
  - `Step`
  - `Hypothesis`
  - `Checkpoint`
  - `ImpactReport`
  - `Status`
- CLI-Oberfläche auf Papier: `init status plan next apply verify rollback why`
- Exit-Codes: `0 ok`, `2 verify fail`, `3 dirty`, `4 unsupported`, `5 conflict`
- Sprachen-Capability-Datei, erstmal nur deklarativ

Lieferobjekt: Schemas + `rfg --help` Mock + ein Fixture-Repo.

### Phase 1 – MVP, zwei Sprachen (3–5 Wochen)

Nur **TypeScript + Go**.

Kann:

- Workspace erkennen (`package.json`, `go.mod`)
- groben Index (Dateien, Exports, Imports) bauen
- Roadmap im Repo speichern: `.rfg/roadmap.yaml` + `.rfg/state.json`
- Hypothesis anlegen: „Rename `UserID` string → typed ID“
- Impact grob: Dateien + Trefferzahl
- Steps manuell in YAML, Abhängigkeiten als DAG
- `rfg next` zeigt den nächsten freien Step
- `rfg apply --dry-run` zeigt Diff
- Apply in **git worktree**
- `rfg verify` führt hinterlegtes Command aus
- `rfg rollback last` setzt Worktree/Checkpoint zurück
- `--format json` überall

Noch nicht: C++, Rust, echte Typauflösung, Multi-Repo-SaaS.

Erfolgskriterium: Ihr könnt ein echtes mittelgroßes TS- oder Go-Repo in 4 Steps umbenennen, mit Rollback, ohne die CLI zu verlassen.

### Phase 2 – Semantik und Anbindung (4–6 Wochen)

- SCIP-Import, wo es Indexer gibt (scip-typescript, scip-go)
- Fallback: LSP `textDocument/references` für Rename-Impact
- `rfg impact --symbol pkg.Type.Method`
- ast-grep als optionaler Matcher in einem Step (`engine: ast-grep`)
- MCP-Server mit denselben Operationen wie die CLI
- CI-Beispiel: GitHub Action `rfg status --format json`
- inkrementeller Index über File-Hashes
- Python dazu: Syntax voll, Semantik nur wo pyright greift

Erfolgskriterium: Ein Agent kann `rfg next` → `apply --dry-run` → `verify` in einer Schleife fahren.

### Phase 3 – Rust + C++ ehrlich (6–8 Wochen)

- Rust über rust-analyzer / rust-analyzer-ähnlichen Index. Macros = `unsupported` oder manueller Step.
- C++ nur mit `compile_commands.json` + clangd. Ohne Compile-DB: nur syntaktische Suche, kein Rename.
- Cross-language Kanten v1: cgo, pyo3, napi – als explizite Edge-Typen, nicht magisch vollständig.
- Format-after-apply: `gofmt`, `rustfmt`, `ruff`, `prettier`, `clang-format`
- Diff-Budget und Risk-Score pro Step

Erfolgskriterium: Dieselbe Roadmap kann einen Go-Kern und ein TS-Frontend plus eine dokumentierte C++-FFI-Kante beschreiben. C++-Apply darf „manual“ sein.

### Phase 4 – Production-ready (4 Wochen parallel zu 3)

- Schema-Migration `rfg migrate`
- Signierte Releases (cargo-dist / goreleaser)
- Completions, man page, `rfg doctor`
- Golden-Tests auf öffentlichen Fixture-Repos je Sprache
- Property: apply + rollback = Identität
- Offline-Garantie, Telemetrie opt-in
- Doku: „so hängt ihr uns an just/make/CI“
- License-Check der Grammars

v1.0-Kriterium: Ein Fremder installiert das Binary, führt `doctor` aus, indexiert ein Polyglot-Repo, legt eine 5-Step-Roadmap an, überlebt Verify-Fail mit Rollback.

---

## Was ihr *nicht* in v1 baut

- GUI
- eigene Parser
- Cloud-Accounts
- „KI schreibt den Patch“
- perfektes C++-Template-Rewrite
- Multi-Tenant-Kampagnen à la Moderne

KI höchstens als optionaler `rfg hypothesize --from-prompt`, Output ist strukturierte Hypothesis, Apply bleibt deterministisch.

---

## Team-Schnitt / Reihenfolge der Module

1. `schema` + `cli`  
2. `store` (YAML/JSON im Repo)  
3. `gitops` (worktree, checkpoint, rollback)  
4. `index_syntax` (tree-sitter)  
5. `engine_roadmap` (DAG, next, status)  
6. `apply_patch`  
7. `verify`  
8. `index_semantic` (SCIP/LSP)  
9. `adapters/{ts,go,py,rs,cxx}`  
10. `mcp`

Jeder Adapter implementiert dasselbe Trait: `discover`, `index`, `resolve`, `preview`, `apply`, `format`, `capabilities`.

---

## Geld später, ohne es jetzt zur Bremse zu machen

v1 komplett OSS, Apache-2.0 oder MIT.  
Erst wenn `doctor` + CI-Loop sitzen: optionales Team-Paket (geteilte Roadmaps, Policy, Audit). Das ist dasselbe Muster wie OpenRewrite vs. Moderne – nur dass euer Open-Core das **Management** ist, nicht Java-Recipes.

---

## Risiko, das den Plan sprengen kann

C++-Semantik und Python-Dynamik. Deshalb Capability-Flags von Tag 1.  
Zweiter Killer: zu viel eigene Infra statt ast-grep/SCIP. Immer wrappen, nicht ersetzen.

---

Nächster handfester Schritt, wenn du startest: Phase-0-Schemas aufschreiben – die fünf JSON-Typen plus `rfg status --json` Beispiel. Daraus fällt die CLI fast von allein.
