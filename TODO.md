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
