# RFG Glossary

Standard terms used by RFG warnings, doctor hints, and docs. Prefer these
over ad-hoc German calques when writing steps, skills, or feedback.

## cross-cutting validation rules

Validations that span multiple steps or layers instead of a single
step contract. Examples in RFG:

- `doctor.oracle_warnings`: duplicate verifies, weak verifies, and
  verifies scoped outside their step's `path[]`.
- `doctor.breadth_warnings`: broad-scope steps (ab 5 `path[]`-Eintraegen
  oder Dir-Eintrag ueber `MAX_FILES`) plus whole-suite verify on broad
  scope (see `broad-scope` below).
- `context.packet`/`contract`: truncated-context flag (`truncated` plus
  `omitted`-Zaehler, see `truncated-context` below).
- `plan`/`verify` toolchain hints (same text as `doctor`, surfaced inline).
- Land gates (step re-verify + suite gate + acceptance commands).

(Nota bene: earlier drafts called these "verkantete Validierungen".
That term is non-standard; use "cross-cutting validation rules".)

## step contract

`want` + `path[]` (+ `extras`) + `verify` + `depends`. `context` renders
it; `tick` stops with it for implement/manual/survey engines.

## toolchain hint

A missing-binary note that names the binary, the step, and the remedy
(`install` or provide via `.rfg/env` PATH). Same text in `doctor`,
`plan` warnings/`toolchain`, and `verify` failures.

## acceptance prose

Goal acceptance items that are prose, not executable commands. Listed
as `acceptance_prose` in `progress`/`land` with a not-executed note;
they never gate. (See `rfg/accept.py`.)

## broad-scope

Breiter Step-Scope als cross-cutting validation rule (warn-first,
no gate, kein Gate, kein hartes Limit):

- Ausloeser: ab 5 `path[]`-Eintraegen (`BREADTH_THRESHOLD`) oder ein
  Dir-Eintrag, der via `expand_dir_paths` auf mehr als `MAX_FILES`
  Dateien expandiert (`doctor.breadth_warnings` in `rfg/doctor.py`).
- Schaerfung: Dir-`path[]` vs File-verify ausserhalb sowie
  Whole-Suite-Verify auf breitem Scope warnen ebenfalls
  (`doctor.oracle_warnings`, M7-Heuristik; `survey`-Steps bleiben exempt).
- Jede breadth-/mismatch-Warnung endet mit dem Hint
  `Scope verkleinern statt Guard biegen` und exit 0.
- Guard-Pin (kein-hartes-Limit): Scope-Warnungen gaten nie, setzen keine
  harten Limits, biegen keinen Guard; stattdessen Scope verkleinern.

## truncated-context

Gekappter Anzeigekontext als cross-cutting validation rule (warn-first,
no gate, kein Gate, kein hartes Limit):

- `context.packet`/`contract` melden Kappung durch `MAX_FILES` /
  `MAX_CHARS` / `MAX_TOTAL_LINES` via `truncated`-Flag plus
  `omitted`-Zaehler (`omitted_files`, `omitted_lines`).
- Anzeige kappt, Disk-Dateien bleiben voll; Ausnahmen (exceptions)
  schrumpfen nie; Prosa (acceptance prose) gated nie.
- K11-Regel: `--max-chars 0` = unlimited (expliziter Override, nur
  Anzeige-Budget, nie Disk-Kappung).
