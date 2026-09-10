# Hang rfg on just / make / CI

rfg is a local CLI. It does not need accounts or network. `RFG_OFFLINE=1` is the default posture (no sockets). Telemetry stays off unless `RFG_TELEMETRY=1` (local `.rfg/telemetry.log` only).

## make

```make
.PHONY: rfg-status rfg-doctor
rfg-status:
	python3 rfg.py status --format json
rfg-doctor:
	python3 rfg.py doctor --format json
```

## just

```just
rfg-status:
    python3 rfg.py status --format json

rfg-next:
    python3 rfg.py next --format json

rfg-doctor:
    python3 rfg.py doctor --format json
```

## GitHub Actions

See `.github/workflows/rfg.yml`. Typical step:

```yaml
- run: python3 rfg.py doctor --format json
- run: python3 rfg.py status --format json
```

Install: copy this repo or `python3 rfg.py` on `PYTHONPATH`. Completions: `python3 rfg.py completion bash`.
