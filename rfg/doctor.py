from __future__ import annotations

import shutil
import sys
from pathlib import Path

from collections import Counter

from rfg import SCHEMA_VERSION, __version__
from rfg import caps, gitops, index, telemetry
import rfg as rfg_pkg
from rfg.detect import default_verify
from rfg.fmtutil import TOOLS
from rfg.store import Store
from rfg.types import BARE_SUITE, Step, step_paths
from rfg.verify import is_weak_verify, is_sham_verify


KNOWN_ENGINES = ("replace", "", "ast-grep", "manual", "implement", "scaffold", "run", "survey")


def unknown_engine_warnings(steps: list[Step], extra: Step | None = None) -> list[str]:
    """Hand-edited roadmaps can carry engines plan-time validation never saw."""
    warns: list[str] = []
    all_steps = list(steps)
    if extra is not None:
        all_steps = [s for s in all_steps if s.id != extra.id] + [extra]
    for s in all_steps:
        eng = (s.engine or "").strip()
        if eng and eng not in KNOWN_ENGINES:
            hint = " (use run with --verify 'bash ...')" if eng == "bash" else ""
            warns.append(f"{s.id} unknown engine {eng!r}{hint} (engines: replace|implement|manual|scaffold|run|survey|ast-grep)")
    return warns


TOOL_BINS = (
    "cargo",
    "rustc",
    "go",
    "pytest",
    "python",
    "python3",
    "npm",
    "node",
    "npx",
    "mvn",
    "mvnw",
    "gradle",
    "java",
    "javac",
    "make",
    "cmake",
    "bash",
    "sh",
    "dotnet",
    "php",
    "kotlinc",
    "tsc",
)


_CODE_EXTS = (".py", ".go", ".ts", ".tsx", ".js", ".rs", ".cc", ".cpp", ".h", ".hpp")
_EXT_SEGS = ("/py", "/go", "/ts", "/tsx", "/js", "/rs", "/cc", "/cpp", "/h", "/hpp")


def normalize_path_token(p: str) -> str:
    """Comparable form for verify-target vs path[] overlap checks.

    Strips leading ./, maps dots to slashes (dotted test IDs), and drops
    a trailing source extension so `tests/test_gaps.py` matches the
    `tests.test_gaps.GapsTest...` verify target.
    """
    n = (p or "").lstrip("./").replace(".", "/")
    for ext in _EXT_SEGS:
        if n.endswith(ext):
            n = n[: -len(ext)]
            break
    return n


def verify_bins(cmd: str) -> list[str]:
    """Binaries referenced by a verify shell line.

    Handles the `export FOO=... PATH=...:$PATH && mvn ...` wrapper the
    Meridian campaign needed: first-token checks miss the real binary.
    """
    if not cmd:
        return []
    import re
    import shlex

    # split shell chaining into segments, then shlex each segment
    parts = re.split(r"&&|\|\||[;|&()]", cmd)
    bins: list[str] = []
    for seg in parts:
        seg = seg.strip()
        if not seg:
            continue
        try:
            toks = shlex.split(seg)
        except ValueError:
            toks = seg.split()
        for tok in toks:
            t = tok.strip().strip("\"'")
            if not t or t.startswith("-") or t.startswith("$"):
                continue
            if "=" in t and not t.startswith("./") and "/" not in t.split("=")[0][:1]:
                # VAR=val assignment (JAVA_HOME=..., PATH=...)
                continue
            if t in ("export", "cd", "echo", "test", "true", "false"):
                continue
            base = t.split("/")[-1]
            if base in TOOL_BINS and base not in bins:
                bins.append(base)
            # only the command position matters per segment: first real token
            break
    return bins


def oracle_warnings(steps: list[Step], extra: Step | None = None) -> list[str]:
    warns: list[str] = []
    all_steps = list(steps)
    if extra is not None:
        all_steps = [s for s in all_steps if s.id != extra.id] + [extra]
    cmds = [s.verify for s in all_steps if s.verify]
    counts = Counter(cmds)
    for cmd, n in counts.items():
        if n >= 2:
            warns.append(f"verify {cmd!r} shared by {n} steps (dedup hint: per-step file target like 'pytest tests/test_x.py -q')")
        if n >= 10:
            warns.append(f"verify {cmd!r} used on {n} steps")
    for s in all_steps:
        cmd = s.verify or ""
        if not cmd:
            continue
        if cmd.strip() in BARE_SUITE:
            warns.append(f"{s.id} verify is a whole-suite command ({cmd.strip()})")
        if is_weak_verify(cmd):
            warns.append(f"{s.id} weak-verify (existence assert or fallback)")
        if is_sham_verify(cmd, engine=s.engine):
            warns.append(f"{s.id} sham-verify (tautology proves nothing)")
        paths = step_paths(s)
        if not paths:
            continue
        expanded = list(paths)
        try:
            from rfg.types import expand_dir_paths  # local to avoid cycle
        except Exception:
            expand_dir_paths = None  # type: ignore
        for tok in cmd.replace("'", " ").replace('"', " ").split():
            if ("/" in tok or tok.endswith(".py")) and not tok.startswith("-"):
                rel = tok.lstrip("./")
                # conventional src/ vs tests/ split is not noise-worthy
                if rel.startswith("tests/") or rel.startswith("test/"):
                    continue
                if "/tests/" in rel or "/test/" in rel:
                    continue
                if rel not in paths and not any(rel.endswith(p) or p.endswith(rel) for p in expanded):
                    if any(rel.endswith(ext) for ext in (".py", ".go", ".ts", ".rs", ".cc")):
                        warns.append(f"{s.id} verify names {rel} outside path")
        # Meridian M7: a scoped verify that touches no path[] entry smells
        # like sham coverage (pricing claimed, core tested). Heuristic on
        # the command text only: warn when the verify names explicit
        # non-test targets and none overlap path[]. Whole-suite commands
        # (no target tokens), the conventional src/tests split, survey
        # steps and non-test oracles (contract runners scope themselves)
        # are exempt. Standard term: cross-cutting validation rules
        # (see docs/GLOSSARY.md).
        if paths and (s.oracle or "test") == "test" and (s.engine or "").strip() != "survey":
            targets: list[str] = []
            for tok in cmd.replace("'", " ").replace('"', " ").split():
                t = tok.strip().strip("\"'").split("::")[0]
                if not t or t.startswith("-") or "=" in t:
                    continue
                if not (
                    "/" in t
                    or t.endswith((".py", ".go", ".ts", ".tsx", ".js", ".rs", ".cc", ".cpp", ".h", ".hpp"))
                ):
                    continue
                rel = t.lstrip("./")
                if not rel:
                    continue
                if rel.startswith(("tests/", "test/")) or "/tests/" in rel or "/test/" in rel:
                    continue
                targets.append(rel)
            if targets:
                exp = [normalize_path_token(p) for p in expanded]
                if not any(
                    n == e or n.startswith(e + "/") or e.startswith(n + "/")
                    for n in (normalize_path_token(t) for t in targets)
                    for e in exp
                ):
                    shown = ", ".join(paths[:3])
                    warns.append(
                        f"{s.id} verify does not reference any path[] entry ({shown}); scoped elsewhere?"
                    )
    seen: set[str] = set()
    out: list[str] = []
    for w in warns:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def structure_warnings(steps: list[Step]) -> list[dict]:
    """Roadmap structure findings, single-sourced from dag (V1.1).

    No second implementation of the checks lives here: doctor surfaces
    these as warnings, plan --check (V1.2) exits on them.
    """
    from rfg.dag import structure_findings as _findings
    from rfg.types import Roadmap as _Rm

    return _findings(_Rm(id="doctor", steps=list(steps or [])))


def toolchain_notes_for(cmds: list[tuple[str, str]], root: str | Path) -> list[str]:
    """Missing-binary notes for (step_id, verify_cmd) pairs.

    Shared by doctor (full roadmap) and plan/verify (focused step):
    plan/verify surface the same hints instead of doctor-only text.
    Binaries resolvable via `.rfg/env` PATH are reported as such,
    not as missing (feedback: undiscoverable .rfg/env).
    """
    import shutil as _shutil

    try:
        from rfg.verify import env_path_which as _env_which
    except Exception:
        _env_which = None  # type: ignore

    notes: list[str] = []
    seen_bins: set[str] = set()
    for sid, c in cmds:
        for b in verify_bins(c):
            if b in seen_bins:
                continue
            seen_bins.add(b)
            if _shutil.which(b) is None:
                via = _env_which(root, b) if _env_which else None
                if via:
                    notes.append(
                        f"{b} not on PATH but resolvable via .rfg/env PATH ({via}) for verify {c!r} (step {sid})"
                    )
                else:
                    # .rfg/env can provide user-local toolchains (feedback F7)
                    notes.append(
                        f"{b} missing for verify {c!r} (step {sid}); hint: install {b} or provide via .rfg/env PATH"
                    )
        # C++ compilers are not in TOOL_BINS (space-separated names)
        for comp in ("g++", "c++", "clang++"):
            if comp in (c or "") and _shutil.which(comp) is None and comp not in seen_bins:
                seen_bins.add(comp)
                notes.append(f"no C++ compiler for verify {c!r}; alternative: install g++ or use survey engine")
    return notes


def run(root: str | Path) -> dict:
    root = Path(root)
    langs = index.discover_all(root)
    st = Store(root)
    schema = None
    schema_ok = True
    if st.exists():
        try:
            rm = st.load_roadmap()
            schema = rm.version
            schema_ok = rm.version >= SCHEMA_VERSION
        except Exception as e:
            schema_ok = False
            schema = str(e)
    tools = {}
    for spec in TOOLS.values():
        name = spec[0]
        tools[name] = shutil.which(name) is not None
    checks = {
        "python": {"ok": sys.version_info >= (3, 10), "detail": sys.version.split()[0]},
        "git": {"ok": shutil.which("git") is not None, "detail": shutil.which("git") or ""},
        "repo": {"ok": gitops.is_repo(root), "detail": str(root)},
        "roadmap": {"ok": st.exists(), "detail": str(st.roadmap_path) if st.exists() else "missing"},
        "schema": {"ok": schema_ok, "detail": schema},
        "languages": {"ok": bool(langs), "detail": langs},
        "compile_commands": {"ok": True, "detail": caps.has_compile_commands(root)},
        "rust_analyzer": {"ok": True, "detail": caps.rust_analyzer_ok()},
        "clangd": {"ok": True, "detail": caps.clangd_ok()},
        "offline": {"ok": True, "detail": telemetry.offline()},
        "telemetry": {"ok": not telemetry.enabled(), "detail": "opt-in" if telemetry.enabled() else "off"},
        "network": {"ok": True, "detail": "unused"},
        "vendored_grammars": {"ok": True, "detail": "none (stdlib parsers only)"},
        "formatters": {"ok": True, "detail": tools},
        "verify": {"ok": True, "detail": default_verify(root)},
        "module": {"ok": True, "detail": str(Path(rfg_pkg.__file__).resolve())},
        "server": {"ok": True, "detail": f"rfg {__version__} schema {SCHEMA_VERSION}"},
    }
    # toolchain alternatives: if planned verify binary is missing, suggest a stdlib fallback
    try:
        tc_notes: list[str] = []
        if st.exists() and schema_ok:
            try:
                _rm = st.load_roadmap()
                cmds = [(s.id, s.verify) for s in _rm.steps if s.verify] + ([("roadmap", _rm.verify)] if _rm.verify else [])
                tc_notes = toolchain_notes_for(cmds, root)
                # file-based hints: java is invisible to discover_all (no .java ext map)
                try:
                    has_java = any(root.rglob("*.java")) or (root / "pom.xml").is_file() or any(root.rglob("pom.xml"))
                except Exception:
                    has_java = False
                if has_java:
                    mentioned = {n.split(" missing")[0] for n in tc_notes}
                    for b in ("java", "javac", "mvn"):
                        if shutil.which(b) is None and b not in mentioned:
                            tc_notes.append(f"{b} missing but .java/pom.xml present; hint: install JDK+maven or provide via .rfg/env PATH")
                tc_notes.extend(unknown_engine_warnings(_rm.steps))
            except Exception:
                pass
        checks["toolchain"] = {"ok": True, "detail": tc_notes or "ok"}
    except Exception:
        pass
    user_skill = Path.home() / ".grok" / "skills" / "rfg" / "SKILL.md"
    skill_detail = "absent"
    if user_skill.is_file():
        try:
            skill_txt = user_skill.read_text(encoding="utf-8")
        except OSError:
            skill_txt = ""
        skill_detail = "implement" if "implement" in skill_txt else "rename-only (copy checkout .grok/skills/rfg)"
    checks["user_skill"] = {"ok": True, "detail": skill_detail}
    oracle_warn: list[str] = []
    if st.exists() and schema_ok:
        try:
            oracle_warn = oracle_warnings(st.load_roadmap().steps)
        except Exception:
            pass
    checks["oracles"] = {"ok": True, "detail": oracle_warn or "ok"}
    rust_note = ""
    if "rust" in (langs or []) and not caps.rust_analyzer_ok():
        rust_note = "replace on .rs with macros is exit 4; use engine manual/implement"
    checks["rust_macros"] = {"ok": True, "detail": rust_note or "ok"}
    cxx_hint = "ok"
    if "cpp" in (langs or []) and not caps.has_compile_commands(root):
        cxx_hint = (
            "no compile_commands.json; mechanical C++ apply is exit 4; "
            "minimal template: python3 -c \"from rfg.cxxcompile import minimal_db; "
            "import json; print(json.dumps(minimal_db('.', ['src/example.cpp']), indent=2))\" "
            "> compile_commands.json"
        )
    checks["cxx_db_hint"] = {"ok": True, "detail": cxx_hint}
    wt_note = "ok"
    try:
        wt = gitops.worktree_path(root)
        if wt.exists() and not gitops._gitdir_owned_by_root(wt, root):
            wt_note = (
                f".rfg/worktree/.git points outside {root}/.git/worktrees "
                "(stale absolute gitdir after manual clone); "
                "ensure_worktree will prune and recreate it"
            )
    except Exception:
        pass
    checks["worktree"] = {"ok": True, "detail": wt_note}
    # compile db missing is not a doctor failure; it's informational
    failed = [k for k, v in checks.items() if not v["ok"] and k in {"python", "git", "repo"}]
    return {
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "ok": not failed,
        "failed": failed,
        "checks": checks,
    }
