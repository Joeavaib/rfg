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
from rfg.types import BARE_SUITE, ENGINES, Step, step_paths
from rfg.verify import is_weak_verify, is_sham_verify

# KD: warn-first scope breadth rule (no gate, no hard limit, exit 0).
# Broad path[] = ab BREADTH_THRESHOLD Dateien (5 warnt, 4 nicht) oder ein
# Dir-Eintrag, der auf mehr als MAX_FILES expandiert. Display kappt,
# Disk-Dateien bleiben voll, --max-chars 0 = unlimited (K11-Regel),
# exceptions schrumpfen nie.
#
# Whole-suite heuristic (oracle_warnings): a BARE_SUITE verify
# (`pytest`, `pytest -q`, …) on a broad step is extra-smelly (scoped
# claim, unscoped proof). Warn-first, no gate; survey steps stay exempt.
BREADTH_THRESHOLD = 5
SCOPE_HINT = "Scope verkleinern statt Guard biegen"


def _verify_covers_dep_path(cmd: str, path: str) -> bool:
    """True when the verify command names a dependency file (or test_<stem>)."""
    rel = (path or "").lstrip("./")
    if not rel or not cmd:
        return False
    name = Path(rel).name
    stem = Path(rel).stem
    if rel in cmd or name in cmd:
        return True
    if stem and (f"test_{stem}" in cmd or f"{stem}_test" in cmd):
        return True
    return False


def breadth_warnings(
    steps: list[Step], root: str | Path | None = None, extra: Step | None = None
) -> list[str]:
    """Warn bei breitem path[] (KD-1), rein warnend, kein Gate.

    - ab BREADTH_THRESHOLD (5) path[]-Eintraegen, oder
    - ein Dir-Eintrag expandiert (via expand_dir_paths) auf mehr als
      MAX_FILES Dateien.
    Gibt Warntexte zurueck, raised nie, exit 0 (kein Gate).
    """
    try:
        from rfg.context import MAX_FILES as _MAX_FILES
    except Exception:
        _MAX_FILES = 8
    all_steps = list(steps or [])
    if extra is not None:
        all_steps = [s for s in all_steps if s.id != extra.id] + [extra]
    warns: list[str] = []
    for s in all_steps:
        paths = step_paths(s)
        if not paths:
            continue
        if len(paths) >= BREADTH_THRESHOLD:
            warns.append(
                f"{s.id} broad scope: {len(paths)} path[] entries "
                f"(>={BREADTH_THRESHOLD}); warn-first, no gate; {SCOPE_HINT}"
            )
            continue
        if root is not None:
            try:
                from rfg.types import expand_dir_paths as _expand
            except Exception:
                _expand = None  # type: ignore
            if _expand is None:
                continue
            try:
                expanded = _expand(str(root), list(paths))
            except Exception:
                continue
            # nur Dir-Expansion zaehlt hier (reine File-Listen sind oben abgedeckt)
            has_dir = False
            try:
                rp = Path(str(root))
                for p in paths:
                    if (rp / p).is_dir():
                        has_dir = True
                        break
            except Exception:
                has_dir = False
            if has_dir and len(expanded) > int(_MAX_FILES):
                warns.append(
                    f"{s.id} broad scope: dir entry expands to {len(expanded)} files "
                    f"(>{int(_MAX_FILES)} MAX_FILES); warn-first, no gate; {SCOPE_HINT}"
                )
    # dedup preserve order
    seen: set[str] = set()
    out: list[str] = []
    for w in warns:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def unknown_engine_warnings(steps: list[Step], extra: Step | None = None) -> list[str]:
    """Hand-edited roadmaps can carry engines plan-time validation never saw."""
    warns: list[str] = []
    all_steps = list(steps)
    if extra is not None:
        all_steps = [s for s in all_steps if s.id != extra.id] + [extra]
    for s in all_steps:
        eng = (s.engine or "").strip()
        if eng and eng not in ENGINES:
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


def oracle_warnings(
    steps: list[Step], extra: Step | None = None, root: str | Path | None = None
) -> list[str]:
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
            # KD-2: whole-suite verify on broad scope is extra smelly
            # (scoped claim, unscoped proof). Warn-first, no gate.
            try:
                _paths0 = step_paths(s)
                _broad = len(_paths0) >= BREADTH_THRESHOLD
                if not _broad and root is not None:
                    try:
                        from rfg.types import expand_dir_paths as _exp0
                        from rfg.context import MAX_FILES as _MF0
                    except Exception:
                        _exp0, _MF0 = None, 8  # type: ignore
                    if _exp0 is not None:
                        try:
                            _broad = len(_exp0(str(root), list(_paths0))) > int(_MF0)
                        except Exception:
                            _broad = False
                if _broad:
                    warns.append(
                        f"{s.id} whole-suite verify on broad scope "
                        f"({len(_paths0)} path[] entries); warn-first, no gate; {SCOPE_HINT}"
                    )
            except Exception:
                pass
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
        # KD-2: Dir-path[] via expand_dir_paths einbeziehen (wenn root bekannt),
        # damit Dir-Claim vs File-Verify ausserhalb nicht durchrutscht.
        if root is not None and expand_dir_paths is not None:
            try:
                expanded = expand_dir_paths(str(root), list(paths)) or list(paths)
            except Exception:
                expanded = list(paths)
        is_survey = (s.engine or "").strip() == "survey"
        is_test_oracle = (s.oracle or "test") == "test"
        # File-verify ausserhalb path[] (KD-2: survey-exempt bleibt).
        if is_test_oracle and not is_survey:
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
                            # KD-2: Dir-Praefix zaehlt als Referenz
                            # (path[] dir/ deckt verify dir/file ab).
                            nrel = normalize_path_token(rel)
                            covered = any(
                                nrel == e or nrel.startswith(e + "/") or e.startswith(nrel + "/")
                                for e in (normalize_path_token(p) for p in expanded)
                            )
                            if not covered:
                                warns.append(
                                    f"{s.id} verify names {rel} outside path; {SCOPE_HINT}"
                                )
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
                        f"{s.id} verify does not reference any path[] entry ({shown}); "
                        f"scoped elsewhere?; {SCOPE_HINT}"
                    )
    by_id = {s.id: s for s in all_steps if s.id}
    for s in all_steps:
        if (s.engine or "").strip() == "survey":
            continue
        cmd = s.verify or ""
        if not cmd:
            continue
        for dep_id in s.depends_on or []:
            dep = by_id.get(dep_id)
            if dep is None:
                continue
            dpaths = step_paths(dep)
            shown = dpaths[0] if dpaths else dep_id
            if dpaths and not any(_verify_covers_dep_path(cmd, p) for p in dpaths):
                warns.append(
                    f"{s.id} depends_on {dep_id} but verify does not name dependency "
                    f"path ({shown}); {SCOPE_HINT}"
                )
            if (dep.verify or "").strip() == cmd.strip():
                warns.append(
                    f"{s.id} verify identical to predecessor {dep_id} "
                    f"({cmd.strip()!r}); named {shown}; {SCOPE_HINT}"
                )
        paths = step_paths(s)
        if len(paths) >= BREADTH_THRESHOLD and cmd.strip():
            covered = [p for p in paths if _verify_covers_dep_path(cmd, p)]
            if len(covered) <= 2:
                hint = ", ".join(paths[:2])
                warns.append(
                    f"{s.id} verify names {len(covered)} file(s) for {len(paths)} "
                    f"path[] entries ({hint}); {SCOPE_HINT}"
                )
    try:
        warns.extend(breadth_warnings(all_steps))
    except Exception:
        pass
    seen: set[str] = set()
    out: list[str] = []
    for w in warns:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def epic_warnings(steps: list[Step], epic: str = "") -> list[str]:
    """Epic-Scope-Warnungen (GS3, warn-first, nie ein Gate).

    - unbekanntes/leeres Epic (kein Step traegt den Praefix) -> Warnung,
      kein Exit, kein Code 5.
    Reine String-Praefixe via :mod:`rfg.scope`, stdlib-only.
    """
    from rfg.scope import unknown_epic_warning as _unknown

    warns: list[str] = []
    if epic:
        w = _unknown([s.id for s in steps or []], epic)
        if w:
            warns.append(w + " (warn-first, no gate)")
    return warns


def stale_epic_warnings(rm, state) -> list[str]:
    """Stale Epics: Gruppe vorhanden, aber nichts verified/ready.

    Rein warnend (warn-first), kein Gate, kein Exit.
    """
    from rfg.dag import step_status as _status
    from rfg.scope import epic_of as _epic_of

    groups: dict[str, list] = {}
    for s in rm.steps or []:
        e = _epic_of(s.id)
        if e:
            groups.setdefault(e, []).append(s)
    warns: list[str] = []
    for e in sorted(groups):
        members = groups[e]
        verified = sum(1 for s in members if _status(rm, state, s) == "verified")
        ready = sum(1 for s in members if _status(rm, state, s) in ("ready", "claimed", "in_progress"))
        if verified == 0 and ready == 0:
            warns.append(f"stale epic {e!r} ({len(members)} steps, none verified/ready); warn-first, no gate")
    return warns


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


def _oracle_type(w: str) -> str:
    """Group key for same-type oracle warnings (RES-D, 1 Summenzeile pro Typ)."""
    if "but verify does not name dependency path" in w:
        return "dependency-path-mismatch"
    if "verify names" in w and "path[] entries" in w:
        return "verify-coverage-thin"
    if "broad scope" in w:
        return "broad-scope"
    if "verify does not reference any path[] entry" in w:
        return "verify-scope-elsewhere"
    if "verify names" in w and "outside path" in w:
        return "verify-outside-path"
    if "identical to predecessor" in w:
        return "verify-identical-predecessor"
    if "shared by" in w and "steps" in w:
        return "verify-shared"
    if "whole-suite" in w:
        return "whole-suite-verify"
    if "weak-verify" in w:
        return "weak-verify"
    if "sham-verify" in w:
        return "sham-verify"
    if "unknown engine" in w:
        return "unknown-engine"
    return "other"


def summarize_oracle_warnings(warns: list[str]) -> list[str]:
    """Collapse same-type oracle warnings to 1 summary line each (RES-D).

    Details stay available via `rfg doctor --verbose`. Warn-first, no gate.
    """
    groups: dict[str, list[str]] = {}
    for w in warns or []:
        groups.setdefault(_oracle_type(w), []).append(w)
    out: list[str] = []
    for typ in sorted(groups):
        items = groups[typ]
        if len(items) == 1:
            out.append(items[0])
            continue
        example = items[0].split(";")[0][:100]
        out.append(
            f"{len(items)}x {typ} (z.B. {example}; "
            f"{len(items) - 1} weitere; Details mit --verbose)"
        )
    return out


def run(root: str | Path, verbose: bool = False) -> dict:
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
        # RES-D: recovery steht im ersten Drittel (Key-Position, nicht erst unten).
        # Die spaetere Zuweisung aktualisiert nur das Detail (gleiche Position).
        "recovery": {"ok": True, "detail": "ok"},
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
    # QM-02: external root visibility (warn-first, never a gate). A resolved
    # root outside the caller cwd means cross-campaign ops — worth naming
    # so the wrong repo never wins silently (hard guard needs harness flag
    # coordination and stays out until then).
    try:
        here = Path.cwd().resolve()
        rt = Path(root).resolve()
        if rt == here:
            root_note = "ok (root == cwd)"
        else:
            try:
                rt.relative_to(here)
                root_note = f"root {rt} inside cwd {here}"
            except ValueError:
                root_note = (
                    f"root {rt} outside cwd {here} "
                    "(cross-campaign op? pass --root explicitly per call)"
                )
    except Exception:
        root_note = "ok"
    checks["root"] = {"ok": True, "detail": root_note}
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
    if verbose:
        oracle_detail: object = oracle_warn or "ok"
    else:
        oracle_detail = summarize_oracle_warnings(oracle_warn) or "ok"
    checks["oracles"] = {"ok": True, "detail": oracle_detail}
    stale_fns: list[str] = []
    try:
        from rfg import ledger as _ledger

        stale_fns = _ledger.stale_functions(root)
    except Exception:
        stale_fns = []
    checks["ledger_stale"] = {"ok": True, "detail": stale_fns or "ok"}
    epic_notes: list[str] = []
    epic_summary = "ok"
    if st.exists() and schema_ok:
        try:
            _rm = st.load_roadmap()
            _state = st.load_state()
            epic_notes = stale_epic_warnings(_rm, _state)
            from rfg.scope import epic_of as _eo

            _counts: dict[str, int] = {}
            for _s in _rm.steps or []:
                _e = _eo(_s.id)
                if _e:
                    _counts[_e] = _counts.get(_e, 0) + 1
            epic_summary = ", ".join(f"{e}:{n}" for e, n in sorted(_counts.items())) or "none"
            if epic_notes:
                epic_summary += " | " + "; ".join(epic_notes)
        except Exception:
            pass
    checks["epics"] = {"ok": True, "detail": epic_summary}
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
        diag = gitops.worktree_diagnosis(root)
        wt_note = diag.get("detail") or "ok"
    except Exception:
        wt_note = "ok"
    checks["worktree"] = {"ok": True, "detail": wt_note}
    rec_notes: list[str] = []
    try:
        rfgd = root / ".rfg"
        rm_p, st_p = rfgd / "roadmap.yaml", rfgd / "state.json"
        bakd = rfgd / gitops.LAND_BACKUP_DIR
        bak_count = len([p for p in bakd.iterdir() if p.is_dir()]) if bakd.is_dir() else 0
        if (not rm_p.is_file() or not st_p.is_file()) and bak_count:
            rec_notes.append(
                f"store incomplete but {bak_count} backup(s) present; "
                "see rfg backup / rfg restore <id>"
            )
        # NOTE: roadmap-newer-than-state mtime skew is normal mid-campaign
        # (plan rewrites the roadmap before the next apply), so it is
        # deliberately not warned about.
        wt = gitops.worktree_path(root)
        if wt.is_dir() and gitops.is_repo(str(wt)) and gitops.dirty_tracked(str(wt)):
            rec_notes.append(
                "git-dirty in .rfg/worktree "
                "(uncommitted tracked files; land copies worktree onto root)"
            )
        # RES-D Wortwahl: git-dirty (uncommittet) vs. worktree-drift (Root!=Worktree).
        try:
            from rfg.resume import _worktree_drift as _drift_of

            _st = st.load_state()
            _rm = st.load_roadmap()
            _drift = _drift_of(root, _st)
            if _drift.get("drift"):
                _files = ",".join((_drift.get("files") or [])[:5]) or "files differ"
                rec_notes.append(f"worktree-drift: root differs from .rfg/worktree ({_files})")
        except Exception:
            pass
    except Exception:
        pass
    # Position bleibt (Key existiert seit oben im ersten Drittel).
    checks["recovery"] = {"ok": True, "detail": rec_notes or "ok"}
    # compile db missing is not a doctor failure; it's informational
    failed = [k for k, v in checks.items() if not v["ok"] and k in {"python", "git", "repo"}]
    return {
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "ok": not failed,
        "failed": failed,
        "checks": checks,
    }
