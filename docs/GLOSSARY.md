# RFG Glossary

Standard terms used by RFG warnings, doctor hints, and docs. Prefer these
over ad-hoc German calques when writing steps, skills, or feedback.

## cross-cutting validation rules

Validations that span multiple steps or layers instead of a single
step contract. Examples in RFG:

- `doctor.oracle_warnings`: duplicate verifies, weak verifies, and
  verifies scoped outside their step's `path[]`.
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
