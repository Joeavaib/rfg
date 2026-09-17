"""Perf/debug oracles: timed run, baseline, repro log. No APM."""

from __future__ import annotations

import json
import time
from pathlib import Path

from rfg.types import Oracle
from rfg.verify import run

BASELINE = "baseline.json"
LAST_RUN = "last_perf.json"
REPRO = "repro.log"


def baseline_path(root: str | Path) -> Path:
    return Path(root) / ".rfg" / BASELINE


def parse_metric(out: str, elapsed_ms: float):
    for line in reversed((out or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return float(line)
        except ValueError:
            continue
    return elapsed_ms


def timed_run(dir: str | Path, command: str, env_extra: dict | None = None) -> tuple[int, str, float]:
    t0 = time.perf_counter()
    code, out = run(dir, command, env_extra=env_extra)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return code, out, elapsed_ms


def last_run_path(root: str | Path) -> Path:
    return Path(root) / ".rfg" / LAST_RUN


def load_last_run(root: str | Path) -> dict | None:
    p = last_run_path(root)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_baseline(root: str | Path) -> dict | None:
    p = baseline_path(root)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def perf_delta(root: str | Path) -> dict:
    """Baseline vs last run with ratio; empty when nothing recorded."""
    base = load_baseline(root)
    last = load_last_run(root)
    if not base and not last:
        return {"recorded": False}
    out: dict = {"recorded": True, "baseline": base, "last": last}
    try:
        bm = float((base or {}).get("metric"))
        lm = float((last or {}).get("metric"))
        out["ratio"] = lm / bm if bm else None
    except (TypeError, ValueError):
        out["ratio"] = None
    return out
    p = baseline_path(root)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_baseline(root: str | Path, data: dict) -> Path:
    p = baseline_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


def run_perf(
    dir: str | Path,
    command: str,
    oracle: Oracle | None = None,
    store_root: str | Path | None = None,
    env_extra: dict | None = None,
) -> tuple[int, str]:
    code, out, elapsed = timed_run(dir, command, env_extra=env_extra)
    if code != 0:
        return code, out
    metric = parse_metric(out, elapsed)
    max_ms = oracle.max_ms if oracle else 0.0
    max_ratio = oracle.max_ratio if oracle else 0.0
    if max_ms and metric > max_ms:
        return 2, f"perf metric {metric} exceeds max_ms {max_ms}\n" + out
    base = load_baseline(store_root or dir)
    if max_ratio and base and base.get("metric") is not None:
        limit = float(base["metric"]) * max_ratio
        if metric > limit:
            return 2, f"metric {metric} exceeds baseline {base.get('metric')} * {max_ratio}\n" + out
    try:
        last_run_path(store_root or dir).write_text(
            json.dumps({"metric": metric, "elapsed_ms": elapsed, "command": command}) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    detail = json.dumps({"metric": metric, "elapsed_ms": elapsed, "ok": True})
    return 0, (out or "") + detail


def run_debug(dir: str | Path, command: str, env_extra: dict | None = None) -> tuple[int, str]:
    code, out = run(dir, command, env_extra=env_extra)
    p = Path(dir) / ".rfg" / REPRO
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(out or "", encoding="utf-8")
    return code, out


def capture_baseline(
    dir: str | Path,
    command: str,
    store_root: str | Path | None = None,
    env_extra: dict | None = None,
) -> dict:
    code, out, elapsed = timed_run(dir, command, env_extra=env_extra)
    if code != 0:
        raise RuntimeError("baseline command failed")
    metric = parse_metric(out, elapsed)
    data = {
        "kind": "perf",
        "metric": metric,
        "elapsed_ms": elapsed,
        "command": command,
    }
    save_baseline(store_root or dir, data)
    return data
