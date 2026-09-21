# Contributing

rfg is a **checker**, not a factory. Patches that turn it into an agent, a
cloud, or an LLM wrapper will be declined.

## Invariants (do not “improve” these away)

- No LLM inside `rfg/`. The agent writes plans and code; rfg verifies.
- Standard library only in `rfg/`. No network in the core.
- Warn-first on scope heuristics; **exit 4** instead of guessing.
- Harvest / SFT farming lives **outside** this package.
- One step, one `want` (FAIL sentence is the contract), narrow `path[]`, one
  real verify **command** (not a bare test path).
- Shrink the step on exit 4. Do not bend the guard.

## How to work

```bash
python3 -m pytest tests/ -q
python3 scripts/diff_coverage.py
python3 scripts/mutation_sample.py
python3 scripts/cxx-parity.py --boundary
```

Use rfg on rfg for behavior changes: one id, one FAIL sentence, one test file
in `path[]`, verify is `python3 -m pytest tests/<that_file>.py -q`.

C++ `cxx/rfg` is a **subset** (rename core). Do not claim Python parity.
Python-only includes Land-Gate, Cross-Verify, `--max-chars`, `scan --parse`.

There is no SLA. Issues that ask for Autopilot, `complexity:` fields, or live
LSP/SCIP rename (`rename: false` in `schema/capabilities.yaml`) are out of
scope.
