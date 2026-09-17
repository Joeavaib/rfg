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

## Crash-Recovery (offen, gelernt 2026-09-17)

Session-Crash + MCP-Neustart hat ungelandete Kampagne verloren: `.rfg/` ist gitignored, Backup gibt es nur bei `land` (`land-backups/`), `restore_roadmap_state` hat kein CLI/MCP-Verb.

Maßstab wie oben: kein stiller Verlust, ein Befehl zur Rettung.

- Backup nicht nur bei `land`: auch bei `apply`/`verify`/`tick` (best-effort, nie blockierend, prune wie `LAND_BACKUP_KEEP`).
- `rfg backup` / `rfg restore <id>` (+ MCP-Verben): listet `land-backups/`, stellt `roadmap.yaml` + `state.json` zurück, Fehler als Exit 4/5 statt still.
- `doctor` warnt: kein `.rfg/` aber Backups vorhanden / `roadmap.yaml` neuer als `state.json` / Worktree dirty.
- Doku: Recovery-Pfad in README (`land-backups/` kopieren) + Skill (`/rfg`) erwähnen.

## Feedback Arm B (A/B C++-Rewrite, 2026-09-17)

Geholfen: `doctor` + `cxx_db_hint` + `plan --check` (DB-Lage sofort klar, kein Exit-4-Raten); `context`/`tick`-Contract (`want`/`path`/`verify`) + MCP-Parität zum CLI; Cross-Verify fing echten Fehler (`run`-Verify im Worktree ohne Roadmap → Parity rot), danach `rollback last` + Fix `run`→`manual`; Land-Gate + Re-Verify (Acceptance-Suiten) + `land-backups/` gibt Vertrauen.

Fragil / offen:
1. Worktree mit absoluten Pfaden nach manuellem Klon: `state.worktree` zeigte auf `/prod/...`, `.rfg/worktree/.git` → prod-gitdir. Heilung nur über Umweg (`manual`-Tick + `rm -rf .rfg/worktree`).
2. `run` inkonsistent: Apply in Root, Verify in `state.worktree`. Frischer Worktree ohne Roadmap lässt Parity-Tests failen; `manual` (Verify in Root) als Workaround — Engine-Modell irreführend.
3. Claim-Agenten driften auseinander (CLI vs. MCP-`agent` vs. cxx-Default, `conflict: claimed by agent`), ohne `--agent` schwer reproduzierbar.
4. Ziel vs. Boundary: „funktional nach C++" suggeriert Vollparität, die das Repo explizit ausschließt — als RFG-Goal so nicht erfüllbar.

Große Scopes gehen nur klein geschnitten (Loop dafür gebaut): Goal + Acceptance als Gate (jedes `land` re-verifiziert); DAG mit 1 ID / 1 `want` / schmalem `path[]` / genau 1 echtem Verify; Engine pro Slice (`scaffold`/`implement`/`manual`/`run`/`survey`, `replace` nur mit DB); Isolation + Recovery (Checkpoint, `rollback`, `land-backups`, Cross-Verify). Voll-Rewrite ≈ 30–50 Modul/Verb-Slices + schrumpfende Parity-Boundary (`scripts/cxx-parity.py` als Acceptance).
Klein bleiben: ehrliche Boundary (kein Fake-Step wo C++ kein Pendant hat); 1–3 Steps für Fix/Heal/Spike/Survey; bei Exit 4 Scope verkleinern statt Guard biegen.

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
