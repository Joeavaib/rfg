from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path


def load_env(root: str | Path) -> dict[str, str]:
    """Read .rfg/env (KEY=VAL per line) for toolchain-local setups.

    The verify shell inherits the rfg process env, not the caller's
    interactive session (e.g. PATH exports in /tmp/opencode/...).  A
    checked-in .rfg/env lets a step declare JAVA_HOME/PATH without
    embedding `export ... &&` in every verify command.  Values support
    $VAR/${VAR} expansion against the current process env plus earlier
    lines in the same file.  Missing file -> {}.
    """
    p = Path(root) / ".rfg" / "env"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    merged: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if not key or not key.replace("_", "").isalnum():
            continue
        # expand against process env + earlier lines so PATH+= works
        base = dict(os.environ)
        base.update(merged)
        val = os.path.expandvars(val)
        # os.path.expandvars uses os.environ only; re-expand $NAME from base
        # for keys not in os.environ (simple second pass for $PATH style).
        for k, v in base.items():
            if f"${k}" in val or "${" + k + "}" in val:
                val = val.replace(f"${k}", v).replace("${" + k + "}", v)
        merged[key] = val
    return merged


def env_path_which(root: str | Path, binary: str) -> str | None:
    """Resolve binary via .rfg/env PATH (None when absent/unresolvable).

    Doctor and verify hints use this so a toolchain that lives behind
    `.rfg/env` (user-local mvn, cargo with RUSTUP_HOME/CARGO_HOME, ...)
    is reported as resolvable instead of missing.
    """
    try:
        env = load_env(root)
    except Exception:
        return None
    path_val = (env.get("PATH") or "").strip()
    if not path_val or not binary:
        return None
    try:
        found = shutil.which(binary.strip().split("/")[-1], path=path_val)
    except Exception:
        return None
    return found


def looks_like_missing_binary(code: int, output: str) -> bool:
    """Exit 127 or shell 'command not found' means the binary is absent."""
    if code == 127:
        return True
    low = (output or "").lower()
    return "command not found" in low or "not recognized as an internal" in low


def env_hint_for_failure(code: int, output: str, command: str, step_id: str = "") -> str:
    """Remediation hint for 127/command-not-found verify failures.

    Always names the binary and step and points at `.rfg/env`, because
    verify shells inherit the rfg process env, not the caller's session
    exports (Meridian: mvn, cargo+RUSTUP_HOME/CARGO_HOME).
    """
    if not looks_like_missing_binary(code, output):
        return ""
    try:
        toks = shlex.split(command or "")
    except ValueError:
        toks = (command or "").split()
    binary = ""
    for tok in toks:
        t = tok.strip()
        if not t or t.startswith("-") or "=" in t or t in ("export", "cd", "bash", "sh"):
            continue
        binary = t.split("/")[-1]
        break
    where = f" (step {step_id})" if step_id else ""
    return (
        f"hint: verify {command!r}{where} failed with exit {code} "
        f"(command not found: {binary or 'unknown binary'}); "
        "declare the toolchain in .rfg/env (e.g. PATH=<dir>:$PATH, "
        "JAVA_HOME, RUSTUP_HOME/CARGO_HOME) so verify shells see it"
    )


def depth2_ids(steps, step) -> list[str]:
    """Dry-run BFS one hop beyond related_step_ids (D5, measure only).

    Counts what depth 2 *would* warn about: neighbors of neighbors,
    excluding depth-1 and self. Read-only, cycle-safe via visited set,
    deterministic. Never touches state, never gates — the caller only
    logs the count. Deciding warn-vs-block from the counts happens
    after measurement (~20 verifies), not here.
    """
    steps = list(steps or [])
    by_id: dict[str, object] = {}
    for s in steps:
        sid = getattr(s, "id", "")
        if sid and sid not in by_id:
            by_id[sid] = s
    me = getattr(step, "id", "")
    try:
        d1 = related_step_ids(steps, step)
    except Exception:
        return []
    seen = set(d1) | {me}
    out: list[str] = []
    for rid in d1:
        rs = by_id.get(rid)
        if rs is None:
            continue
        try:
            nxt = related_step_ids(steps, rs)
        except Exception:
            continue
        for nid in nxt:
            if nid not in seen:
                seen.add(nid)
                out.append(nid)
    return out


def _related_cap() -> int:
    """Cross-verify scope cap, env-tunable (default 10)."""
    try:
        return max(1, int(os.environ.get("RFG_RELATED_MAX") or 10))
    except ValueError:
        return 10


def related_step_ids(steps, step) -> list[str]:
    """Stufe 1 cross-verify scope: direct dependents + path overlap.

    Ranked, not lottery (D1): dependents first (causal edge), then
    rarity (idf-damped overlap so God-Files like rfg/cli.py shared by
    58 steps don't dominate), then step id (deterministic). Downstream
    weighting is parked (no measured need yet). Capped at
    RFG_RELATED_MAX (default 10). Self is excluded.
    """
    try:
        from rfg.types import step_paths as _paths
    except Exception:
        return []
    import math

    me = getattr(step, "id", "")
    mine = set(_paths(step) or [])
    steps = list(steps or [])
    n = max(1, len(steps))
    df: dict[str, int] = {}
    for s in steps:
        try:
            ps = set(_paths(s) or [])
        except Exception:
            ps = set()
        for p in ps:
            df[p] = df.get(p, 0) + 1
    dependents: list[str] = []
    scored: list[tuple[float, str]] = []
    for s in steps:
        sid = getattr(s, "id", "")
        if not sid or sid == me:
            continue
        if me and me in (getattr(s, "depends_on", None) or []):
            dependents.append(sid)
            continue
        try:
            shared = mine & set(_paths(s) or [])
        except Exception:
            shared = set()
        if mine and shared:
            rarity = sum(math.log(n / max(1, df.get(p, 1))) for p in shared)
            scored.append((-rarity, sid))
    dependents.sort()
    scored.sort()
    out = list(dependents) + [sid for _, sid in scored]
    seen: set[str] = set()
    deduped: list[str] = []
    for sid in out:
        if sid not in seen:
            seen.add(sid)
            deduped.append(sid)
    return deduped[: _related_cap()]


def is_trivial(command: str | None) -> bool:
    """true/empty is not a real verify command."""
    s = (command or "").strip().lower()
    return s in ("", "true")


def dispatch(
    dir: str | Path,
    command: str,
    kind: str = "test",
    timeout: float | None = 60.0,
    env_extra: dict[str, str] | None = None,
) -> tuple[int, str]:
    """H1 test oracle runs command. perf/debug/security without a command stay exit 4."""
    kind = (kind or "test").strip().lower() or "test"
    if kind not in ("test", "perf", "debug", "security"):
        return 4, f"unsupported oracle kind: {kind}"
    if kind != "test" and not (command or "").strip():
        return 4, f"unsupported: {kind} oracle stub (no command)"
    if kind == "security" and not (command or "").strip():
        return 4, "unsupported: security oracle stub (no command until H5)"
    return run(dir, command, timeout=timeout, env_extra=env_extra)


def run(
    dir: str | Path,
    command: str,
    timeout: float | None = 60.0,
    env_extra: dict[str, str] | None = None,
) -> tuple[int, str]:
    if is_trivial(command):
        return 4, "unsupported: trivial verify (need a real command, not true/empty)"
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    try:
        r = subprocess.run(
            command,
            cwd=dir,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout if timeout and timeout > 0 else None,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return 2, "verify timeout"
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


OUTPUT_LIMIT = 2000


def clip_output(text: str, limit: int = OUTPUT_LIMIT) -> str:
    """Tail of command output for MCP/CLI JSON. Full text stays in the verify log."""
    s = text or ""
    if len(s) <= limit:
        return s
    keep = max(0, limit - 36)
    return "…[truncated, see log]…\n" + s[-keep:]


def write_log(
    root: str | Path,
    step_id: str,
    command: str,
    code: int,
    output: str,
    elapsed_ms: float | None = None,
) -> str:
    """Write `.rfg/verify/<step>.log`. `elapsed_ms` (D4, optional) goes
    into the `$`-header for cost measurement; never gates anything."""
    p = Path(root) / ".rfg" / "verify" / f"{step_id}.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    head = f"$ {command}"
    if elapsed_ms is not None:
        try:
            head += f" elapsed_ms={float(elapsed_ms):.1f}"
        except (TypeError, ValueError):
            pass
    body = f"{head}\nexit {code}\n\n{output or ''}"
    if not body.endswith("\n"):
        body += "\n"
    p.write_text(body, encoding="utf-8")
    return str(p)


def is_fallback_verify(command: str | None) -> bool:
    return (command or "").strip() in ("", "true", "test -n ok")


def is_weak_verify(command: str | None, engine: str | None = None) -> bool:
    s = (command or "").lower()
    if is_fallback_verify(command) or is_trivial(command):
        return True
    # survey steps are notes-only; ls/grep checks are appropriate, not weak
    if (engine or "").strip().lower() == "survey":
        return False
    markers = ("path.exists", "exists()", "os.path.exists", "test -e ", "test -f ", "test -d ")
    return any(m in s for m in markers)


_SHAM_MARKERS = ("assert true", "asserttrue(true)", "exit 0")


def is_sham_verify(command: str | None, engine: str | None = None) -> bool:
    """Tautological verifies prove nothing (V2, strict layer).

    `assert True` / `assertTrue(True)` / `exit 0` pass without touching
    any code, so they are sham even though they are not trivial/weak by
    the older markers. Survey steps are notes-only and exempt; empty
    commands belong to the trivial layer, not sham. Targeted selection
    (`-k`, `--deselect`, file targets) is legitimate scoping, not sham.
    """
    if (engine or "").strip().lower() == "survey":
        return False
    s = " ".join((command or "").lower().split())
    if not s:
        return False
    return any(m in s for m in _SHAM_MARKERS)
