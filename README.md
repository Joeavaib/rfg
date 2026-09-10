# rfg

Local CLI to **lead** a multi-step refactor: hypothesis → impact → step DAG → apply in a git worktree → verify → rollback.

## Commands

`init` `status` `plan` `next` `apply` `verify` `rollback` `why` `impact` `index` `import-scip` `mcp` `edges` `migrate` `doctor` `completion` `man` `version`

Phase 2: incremental file-hash index, Python syntax index, optional SCIP JSON import, `impact --symbol`, ast-grep engine (exit 4 if missing), MCP stdio, GitHub Action `rfg status --format json`.

Phase 3: Rust/C++ capability gates (macros / `compile_commands.json`), explicit edges (`rfg edges`: cgo, pyo3, napi, cxx-ffi), format-after-apply, per-step `diff_budget` and risk score. C++ apply without compile-db is exit 4 unless `engine: manual`.

Every command accepts `--format json`.

Exit codes: `0` ok, `2` verify fail, `3` dirty, `4` unsupported, `5` conflict.

## Store

- `.rfg/roadmap.yaml` — versioned plan
- `.rfg/state.json` — applied/verified steps and last checkpoint

## Run

```
python3 rfg.py --help
```

Python 3.10+ (stdlib only). MIT. Offline by default; telemetry opt-in (`RFG_TELEMETRY=1`) writes `.rfg/telemetry.log` only.

See `docs/INTEGRATION.md` for just/make/CI. Grok Build: `docs/GROK-BUILD.md` (skill `/rfg` + project MCP).
