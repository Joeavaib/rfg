from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from rfg import SCHEMA_VERSION, __version__, apply as applymod
from rfg import accept, audit, caps, context, cxxcompile, dag, edges, fleet, fmtutil, gitops, index, oracles as oramod
from rfg import progress, recipes, risk, scaffold, security, telemetry
from rfg.detect import FALLBACK_VERIFY, default_verify
from rfg.store import Store, claim_held_payload
from rfg.types import Budget, Checkpoint, Goal, Hypothesis, Oracle, Replace, Roadmap, Step
from rfg.types import coerce_depends_list, coerce_path_list, default_engine, is_contract, is_implement, is_mechanical, is_stop_engine, step_allowed_paths, step_observation, step_paths, step_want
from rfg.verify import clip_output, dispatch as run_verify, is_fallback_verify, is_sham_verify, is_trivial, looks_like_missing_binary, write_log as write_verify_log

OK, USAGE, VERIFY_FAIL, DIRTY, UNSUPPORTED, CONFLICT = 0, 1, 2, 3, 4, 5
ENGINES = ("replace", "", "ast-grep", "manual", "implement", "scaffold", "run", "survey")


def _gate_runnable(cmd: str) -> bool:
    """Skip the land gate when its binary is missing (e.g. go/cargo absent).

    A missing toolchain is a doctor/UX note, not a land failure: the step
    verifies already passed on a runnable toolchain.
    """
    try:
        parts = shlex.split(cmd or "")
    except ValueError:
        return True
    if not parts:
        return False
    first = parts[0]
    if "/" in first:
        return True
    return shutil.which(first) is not None


def _restrict_sid_to_epic(rm, state, sid: str, epic: str) -> tuple[str, str]:
    """Bind sid to --epic (warn-first). Never a gate; empty sid if none match."""
    from rfg import scope as _scope

    warning = ""
    if not epic:
        return sid, warning
    w = _scope.unknown_epic_warning([s.id for s in rm.steps], epic)
    if w:
        warning = w
    if sid and _scope.epic_of(sid) == epic:
        return sid, warning
    ready = [x for x in dag.ready_ids(rm, state) if _scope.epic_of(x) == epic]
    if ready:
        prev = sid or "next"
        note = f"epic {epic!r} skipped {prev}; using {ready[0]}"
        warning = f"{warning}; {note}" if warning else note
        return ready[0], warning
    note = f"epic {epic!r} has no ready step"
    warning = f"{warning}; {note}" if warning else note
    return "", warning


def _parse_epic_arg(args: list[str] | None) -> str:
    """--epic Filter aus CLI-Args lesen (``--epic GS`` / ``--epic=GS``).

    Reiner Anzeige-Filter, kein neues Verb, keine MCP-Flaeche, kein Gate:
    unbekannte Epics warnen (``warning``-Feld), exiten nie 5.
    """
    epic = ""
    argv = list(args or [])
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--epic" and i + 1 < len(argv):
            epic = argv[i + 1]
            i += 2
            continue
        if a.startswith("--epic="):
            epic = a.split("=", 1)[1]
            i += 1
            continue
        i += 1
    return epic


def current_agent() -> str:
    return (os.environ.get("RFG_AGENT") or "").strip()


def same_claim_client(state, agent: str) -> bool:
    """Empty agent (typical MCP apply) is this client, not a second identity."""
    if not state.claim_agent:
        return True
    if not agent:
        return True
    return state.claim_agent == agent


def cross_timeout_for(remaining_s: float, default_s: float) -> float:
    """Per-related timeout capped by remaining cross budget (D2).

    Never below the 5s floor so a nearly-exhausted budget still gets a
    probe instead of a zero-timeout instant fail.
    """
    try:
        default_s = float(default_s)
    except (TypeError, ValueError):
        default_s = 60.0
    try:
        remaining_s = float(remaining_s)
    except (TypeError, ValueError):
        return default_s
    if remaining_s <= 0:
        return 5.0
    return min(default_s, remaining_s)


def cross_budget_note(related_total, elapsed_s, budget) -> str:
    """Warn-only note when cross scope exceeds Budget (XB, never a gate).

    related_total > max_related or elapsed > max_seconds yields a label
    string; otherwise "". max_* = 0 disables (today's behavior). Pure
    function, stdlib-only, changes no exit (D3 pattern: label only).
    """
    try:
        total = int(related_total)
    except (TypeError, ValueError):
        total = 0
    try:
        elapsed = float(elapsed_s)
    except (TypeError, ValueError):
        elapsed = 0.0
    try:
        max_related = int(getattr(budget, "max_related", 0) or 0)
    except (TypeError, ValueError):
        max_related = 0
    try:
        max_seconds = float(getattr(budget, "max_seconds", 0) or 0)
    except (TypeError, ValueError):
        max_seconds = 0.0
    parts: list[str] = []
    if max_related > 0 and total > max_related:
        parts.append(f"related_total {total} > max_related {max_related}")
    if max_seconds > 0 and elapsed > max_seconds:
        parts.append(f"elapsed {elapsed:.1f}s > max_seconds {max_seconds:g}s")
    if not parts:
        return ""
    return "budget: " + "; ".join(parts)


def triage_cross_failure(code: int, output: str, was_red_before: bool) -> str:
    """Label-only triage for cross-verify failures (D3).

    ENV: missing binary/unsupported toolchain; COST: timeout (says
    nothing about correctness); PRE-EXISTING: neighbor already red
    before this step ran; else REGRESS-SUSPECT. Never changes exits —
    labels ride along in the message, VERIFY_FAIL stays as is.
    """
    if looks_like_missing_binary(code, output or ""):
        return "ENV/toolchain-missing"
    if code == 4:
        return "ENV/unsupported"
    if code == 2 and "verify timeout" in (output or ""):
        return "COST/timeout"
    if was_red_before:
        return "PRE-EXISTING/neighbor-already-red"
    return "REGRESS-SUSPECT/assert-fail"


def cross_verify_message(failures: list[tuple[str, str, int, str, str]]) -> str:
    """Remediation-carrying cross-verify error (Meridian: ortlose Meldungen).

    failures: (step_id, command, exit_code, output, log_path) per failed
    related step. Every entry names step + binary + log path; exit 127 /
    command-not-found appends the `.rfg/env` hint, other failures point
    at the stored log. Pure function so tests can assert the contract.
    """
    parts: list[str] = []
    hints: list[str] = []
    for sid, cmd, code, out, log in failures:
        try:
            toks = shlex.split(cmd or "")
        except ValueError:
            toks = (cmd or "").split()
        binary = toks[0].split("/")[-1] if toks else "?"
        detail = clip_output(out or "")[:500].strip()
        bit = f"{sid}: {binary} exit {code}"
        if detail:
            bit += f" ({detail})"
        bit += f" [log {log}]" if log else " [no log]"
        parts.append(bit)
        if looks_like_missing_binary(code, out or ""):
            hints.append(f"{binary} not found (step {sid}); hint: provide via .rfg/env PATH")
        elif log:
            hints.append(f"{sid}: see {log}")
    msg = "cross-verify failed for " + ",".join(s for s, _, _, _, _ in failures) + ": " + "; ".join(parts)
    if hints:
        msg += " hint: " + "; ".join(hints)
    return msg[:2000].strip()


def _ensure_followup(st: Store, rm: Roadmap, step: Step) -> str:
    fid = f"{step.id}-followup"
    if any(s.id == fid for s in rm.steps):
        return fid
    paths = list(step.replace.paths) if step.replace else []
    rm.steps.append(
        Step(
            id=fid,
            title="manual followup: remaining string literals",
            depends_on=[step.id],
            engine="manual",
            replace=Replace("", "", paths),
            verify=step.verify,
            oracle=step.oracle or "test",
        )
    )
    st.save_roadmap(rm)
    return fid


def _followup_manual(skipped, frm: str) -> str:
    for s in skipped or []:
        if s.get("reason") == "string_literal" and frm and frm in (s.get("example") or ""):
            return "manual"
    return ""


def verify_test_files(cmd: str) -> list[str]:
    """Test-file tokens in a verify command (1-zu-1 Testdatei-Regel)."""
    seen: list[str] = []
    for tok in (cmd or "").replace("'", " ").replace('"', " ").split():
        t = tok.strip().strip("\"'").split("::")[0].lstrip("./")
        if not t or t.startswith("-") or "=" in t:
            continue
        name = Path(t).name.lower()
        if not t.endswith(".py"):
            continue
        if not (
            name.startswith("test_")
            or name.endswith("_test.py")
            or t.startswith("tests/")
            or "/tests/" in t
            or t.startswith("test/")
        ):
            continue
        if t not in seen:
            seen.append(t)
    return seen


def contract_check_findings(steps: list[Step]) -> list[dict]:
    """plan --check extras: manual want + unique test file per step (QD-03)."""
    found: list[dict] = []
    owners: dict[str, list[str]] = {}
    for s in steps or []:
        eng = (s.engine or "").strip()
        if eng == "manual" and not (s.want or "").strip() and not (s.goal or "").strip():
            found.append(
                {
                    "kind": "missing-want",
                    "step": s.id,
                    "detail": f"manual step {s.id!r} has no want",
                }
            )
        if eng == "survey":
            continue
        for tf in verify_test_files(s.verify or ""):
            owners.setdefault(tf, []).append(s.id)
    for tf, ids in owners.items():
        if len(ids) < 2:
            continue
        shown = ", ".join(ids[:8])
        extra = f" +{len(ids) - 8}" if len(ids) > 8 else ""
        found.append(
            {
                "kind": "shared-test-file",
                "step": ids[0],
                "detail": (
                    f"test file {tf} used by {len(ids)} steps ({shown}{extra}); "
                    "1-zu-1 Testdatei-Regel"
                ),
            }
        )
    return found


def undeclared_verify_test_files(step: Step) -> list[str]:
    """Verify test files missing from path[]/extras. Survey exempt. Warn-first."""
    if (step.engine or "").strip() == "survey":
        return []
    allowed = [p.replace("\\", "/").lstrip("./") for p in step_allowed_paths(step)]
    missing: list[str] = []
    for tf in verify_test_files(step.verify or ""):
        norm = tf.replace("\\", "/").lstrip("./")
        name = Path(norm).name
        declared = False
        for p in allowed:
            if p == norm or p.endswith("/" + name) or Path(p).name == name:
                declared = True
                break
        if not declared:
            missing.append(tf)
    return missing


def contract_warning_for(step: Step) -> str:
    missing = undeclared_verify_test_files(step)
    if not missing:
        return ""
    shown = ", ".join(missing[:5])
    return (
        f"verify test file {shown} not in path[]/extras; "
        "extend via plan --path or allowlist via plan --extras"
    )


def _attach_contract_warning(payload: dict, step: Step) -> None:
    cw = contract_warning_for(step)
    if not cw:
        return
    payload["contract_warning"] = cw
    prev = (payload.get("warning") or "").strip()
    payload["warning"] = f"{prev}; {cw}" if prev else cw


HELP = """rfg — lead a multi-step refactor locally

Usage:
  rfg [--format json] [--root DIR] [--show-risk] [--max-chars N] <command>

  External --root outside cwd is warn-first (doctor names it). A hard
  --allow-external-root guard (exit 4) is deferred until gotoharness
  clients can send that flag; otherwise foreign campaigns break (QM-05).

Global output flags:
  --show-risk        include risk/format blocks (apply/next); default slim
  --max-chars N      cap agent-facing output (context/digest/export/impact);
                     default 2000, hard cap 8000 (0 = no cap, explicit override);
                     capped payloads say truncated

Commands:
   init                 create .rfg/roadmap.yaml and state
   status [--resume]    show roadmap DAG and next free step (--resume = 1-call session resume)
   resume               1-call session resume (goal, counts, last/next, git, drift, checkpoint)
   plan                 write or update steps / hypothesis (--from-impact stamps path)
  next                 print the next free step (includes claim/budget)
  apply [--dry-run] [--diff] [--show-risk]  apply next (or given) step in a git worktree
  context [step]       step contract + snippets for existing paths
  tick                 apply+verify if replace; stop with contract if manual/implement
  verify               run verify for an implemented/applied step
  land [--commit|--no-commit]  copy the apply worktree onto the root and re-verify
                        (--commit or RFG_AUTO_COMMIT=1 snapshots a local commit; never pushes)
  rollback last        restore the last checkpoint
  backup               list roadmap/state backups in .rfg/land-backups/
  restore [--dry-run] <id>  restore roadmap.yaml+state.json from a backup (exit 4 on unknown id)
  why                  explain why a step is ready/blocked
  impact [--symbol S]  file/import/export hit counts (index or SCIP)
  index                rebuild incremental file-hash index
  import-scip FILE     merge a SCIP JSON dump into the index
  mcp                  MCP stdio server (same operations as CLI)
  edges                list explicit cross-language edges (cgo, pyo3, napi, cxx-ffi)
  migrate              bump roadmap schema to current version
  claim [step]         lock the next (or given) step for RFG_AGENT
  release              drop the step claim
  audit                last audit.jsonl events
  progress             goal + counts + exceptions (non-dev)
  digest               write .rfg/digest.json (nightly / handoff)
  baseline             capture perf oracle metric into .rfg/baseline.json
  repro                run debug oracle (writes .rfg/repro.log)
  scan [--parse FILE]  security findings (parsed scanner JSON/SARIF) or scanner presence (no exploits)
  fuzz [--seconds N]   run fuzz command (oracle or built from present fuzzer) with timeout
  sbom                 write .rfg/sbom.json inventory (CycloneDX-lite)
  boundaries           FFI edges as trust boundaries
  fleet [status|next]  progress, or one {repo, step} across fleet.yaml
  export batch|dashboard  offline batch spec or static HTML snapshot
  recipe list|show|apply  bundled roadmap templates
  packs                list open vs paid packs; paid enable is exit 4
  doctor               check git, schema, languages, offline, formatters
  completion SHELL     print bash|zsh|fish completions
  man                  print the man page
  version              print rfg version

Exit codes:
  0 ok  2 verify fail  3 dirty  4 unsupported  5 conflict
"""

COMMAND_HELP = {
    "plan": """rfg plan — campaign goal or one step

Usage:
  rfg plan --goal TEXT [--profile feature|refactor] [--acceptance CMD]
  rfg plan --step ID --want TEXT --path FILE [--extras FILE] [--verify CMD] [--depends ID]
            [--engine replace|implement|manual|scaffold|run|survey|ast-grep]
            [--from SYM --to SYM] [--diff-budget N] [--oracle KIND] [--edge NAME]
            [--from-impact]
  rfg plan --list   list all steps (id/status/engine)
  rfg plan          compact definition of the next step (want/path/verify)
  rfg plan --check  validate roadmap read-only (exit 5 with findings, 0 when clean)
                    (--strict adds sham-verify errors)

--goal without --step sets the product goal. --goal with --step is exit 5; use --want.
--path on an existing step merges and dedups. --extras allowlists side
  artefacts (e.g. rfgfeedback.md) without polluting path[].
Unknown --engine fails fast (exit 4) instead of failing at tick.
""",
    "next": """rfg next — next free step plus ready[] and recommend

Usage:
  rfg next [--epic PREFIX]
Epic filter is display-only (warn-first, never a gate, no MCP param).
""",
    "context": """rfg context — step contract (want, path, missing, verify)

Usage:
  rfg context [STEP] [--sources]
Cousins only with --sources.
""",
    "apply": """rfg apply — apply a step in a git worktree

Usage:
  rfg apply [STEP] [--dry-run] [--diff] [--force] [--agent NAME]
""",
    "tick": """rfg tick — apply+verify (replace) or claim+contract (implement/manual)

Usage:
  rfg tick [STEP] [--agent NAME]
""",
    "impact": """rfg impact — symbol/file hit counts

Usage:
  rfg impact [--symbol S]
Caps dumps when hits > 500 (warning: too broad).
""",
}


def _upsert_oracle(rm: Roadmap, kind: str, **fields) -> None:
    kind = kind or "test"
    for o in rm.oracles:
        if o.kind == kind:
            for k, v in fields.items():
                setattr(o, k, v)
            return
    o = Oracle(kind=kind)
    for k, v in fields.items():
        setattr(o, k, v)
    rm.oracles.append(o)


def default_roadmap(root: str | Path | None = None) -> Roadmap:
    verify = default_verify(root) if root is not None else ""
    return Roadmap(
        version=SCHEMA_VERSION,
        id="roadmap-1",
        hypothesis=Hypothesis(
            id="h1",
            statement="",
            symbol="",
            from_pat="",
            to="",
        ),
        goal=Goal(
            id="g1",
            statement="",
            profile="refactor",
            acceptance=[],
        ),
        verify=verify,
        oracles=[
            Oracle(kind="test", command=verify),
            Oracle(kind="perf", command=""),
            Oracle(kind="debug", command=""),
            Oracle(kind="security", command=""),
        ],
        steps=[],
    )


class CLI:
    def __init__(self, root: str, json_out: bool, dry: bool, show_diff: bool = False, compact: bool = False, show_risk: bool = False) -> None:
        self.root = root
        self.json = json_out
        self.dry = dry
        self.show_diff = show_diff
        self.compact = compact
        self.show_risk = show_risk
        self._capture: list[dict] | None = None

    def emit(self, command: str, data, diff: str | None = None, ok: bool = True, error: str | None = None) -> None:
        env = {"ok": ok, "command": command}
        if error:
            env["error"] = error
        if data is not None:
            env["data"] = data
        if diff is not None:
            env["diff"] = diff
        if self._capture is not None:
            self._capture.append(env)
            return
        if self.json or True:
            text = json.dumps(env, separators=(",", ":")) if self.compact else json.dumps(env, indent=2)
            if self.json:
                print(text)
            else:
                if diff and command == "apply" and data and data.get("dry_run"):
                    print(diff, end="" if diff.endswith("\n") else "\n")
                else:
                    print(text)

    def emit_err(self, command: str, msg: str, extra: dict | None = None) -> None:
        env = {"ok": False, "command": command, "error": msg}
        if extra:
            env.update(extra)
        if self._capture is not None:
            self._capture.append(env)
            return
        if self.json:
            print(json.dumps(env, separators=(",", ":")) if self.compact else json.dumps(env, indent=2))
        else:
            print(msg, file=sys.stderr)

    def load(self):
        st = Store(self.root)
        rm = st.load_roadmap()
        state = st.load_state()
        return st, rm, state

    def cmd_init(self, _args: list[str]) -> int:
        st = Store(self.root)
        if st.exists():
            self.emit_err("init", "roadmap already exists")
            return CONFLICT
        st.init(default_roadmap(self.root))
        telemetry.record(self.root, "init")
        payload = {"roadmap": str(st.roadmap_path), "state": str(st.state_path)}
        if not gitops.is_repo(self.root):
            payload["warning"] = "not a git repository; doctor fails until git init (needed for worktree/rollback/land)"
        self.emit("init", payload)
        return OK

    def cmd_status(self, args: list[str] | None = None) -> int:
        try:
            _, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("status", str(e))
            return USAGE
        if args and "--resume" in list(args):
            return self.cmd_resume()
        s = dag.compute(rm, state)
        if gitops.is_repo(self.root):
            s["dirty"] = progress.apply_dirty(self.root, rm, state)
        s["goal"] = {
            "id": rm.goal.id,
            "statement": rm.goal.statement,
            "profile": rm.goal.profile,
            "acceptance": list(rm.goal.acceptance),
        }
        s["profile"] = rm.goal.profile
        s["oracles"] = [{"kind": o.kind, "command": o.command} for o in rm.oracles]
        sid = s.get("next") or ""
        step = dag.step_by_id(rm, sid) if sid else None
        s["next_step"] = self._step_json(rm, state, step, dag.blocked_reason(rm, state))
        s["claim_step"] = state.claim_step
        s["claim_agent"] = state.claim_agent
        s["applies_used"] = state.applies_used
        s["budget"] = {"max_applies": rm.budget.max_applies}
        self.emit("status", s)
        return OK

    def cmd_resume(self) -> int:
        """One-call session resume (RES-A): goal, counts, last/next, git, drift, checkpoint."""
        try:
            _, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("resume", str(e))
            return USAGE
        from rfg import resume as _resume

        self.emit("resume", _resume.report(self.root, rm, state))
        return OK

    def _step_json(self, rm, state, step: Step | None, blocked: str) -> dict:
        if step is None:
            d = {
                "id": None,
                "engine": "",
                "from": "",
                "to": "",
                "path": [],
                "depends": [],
                "verify": rm.verify,
                "oracle": "test",
                "edge": "",
                "blocked_reason": blocked or "no free step",
                "next": None,
                "claim_step": state.claim_step,
                "claim_agent": state.claim_agent,
                "applies_used": state.applies_used,
                "budget": {"max_applies": rm.budget.max_applies},
            }
            if self.show_risk:
                d["risk"] = None
            return d
        frm = step.replace.from_pat if step.replace else ""
        to = step.replace.to if step.replace else ""
        paths = step_paths(step)
        exists, missing = context.path_split(self.root, paths)
        loc = context.where_to_edit(self.root, state, step)
        rs = None
        if self.show_risk and step.replace and frm:
            try:
                prev = applymod.preview(self.root, step)
                rs = risk.score(
                    step,
                    hits=prev["hits"],
                    diff_lines=risk.diff_line_count(prev["diff"]),
                    edges=edges.scan(self.root),
                    macros=False,
                    cpp_no_db=False,
                )
            except (ValueError, OSError):
                rs = None
        d = {
            "id": step.id,
            "engine": default_engine(step.engine, from_pat=frm),
            "want": step_want(step),
            "goal": step_want(step),
            "from": frm,
            "to": to,
            "path": paths,
            "exists": exists,
            "missing": missing,
            "depends": list(step.depends_on),
            "verify": step_observation(step, rm.verify),
            "oracle": step.oracle or "test",
            "edge": step.edge,
            "status": dag.step_status(rm, state, step),
            "blocked_reason": blocked,
            "next": step.id,
            "title": step.title,
            "worktree": loc["worktree"],
            "edit_root": loc["edit_root"],
            "after_edit": loc["after_edit"],
            "claim_step": state.claim_step,
            "claim_agent": state.claim_agent,
            "applies_used": state.applies_used,
            "budget": {"max_applies": rm.budget.max_applies},
        }
        if self.show_risk:
            d["risk"] = rs
        return d

    def cmd_next(self, args: list[str] | None = None) -> int:
        try:
            _, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("next", str(e))
            return USAGE
        epic = _parse_epic_arg(args)
        sid = dag.next_id(rm, state)
        step = dag.step_by_id(rm, sid) if sid else None
        rec, rec_why = dag.recommend(rm, state)
        ready = dag.ready_ids(rm, state)
        warning = ""
        if epic:
            from rfg import scope as _scope

            scoped = [s for s in ready if _scope.epic_of(s) == epic]
            w = _scope.unknown_epic_warning([s.id for s in rm.steps], epic)
            if w:
                warning = w
            if scoped:
                sid = scoped[0]
                step = dag.step_by_id(rm, sid) if sid else None
                rec, rec_why = dag.recommend(rm, state, epic)
                ready = scoped
            else:
                sid = ""
                step = None
                rec, rec_why = "", (warning or f"unknown epic {epic!r}")
                ready = []
        body = self._step_json(rm, state, step, dag.blocked_reason(rm, state))
        body["ready"] = ready[:8]
        if len(ready) > 8:
            body["ready_omitted"] = len(ready) - 8
        body["recommend"] = rec or None
        body["recommend_reason"] = rec_why
        if epic:
            body["epic"] = epic
        if warning:
            body["warning"] = warning
        self.emit("next", body)
        return OK

    def cmd_context(self, args: list[str]) -> int:
        try:
            _, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("context", str(e))
            return USAGE
        sid = dag.next_id(rm, state)
        include_sources = False
        for a in args:
            if a == "--sources":
                include_sources = True
            elif not a.startswith("-"):
                sid = a
        step = dag.step_by_id(rm, sid) if sid else None
        data = context.packet(self.root, rm, state, step, sources=include_sources)
        from rfg import tokens as _tokens

        data = _tokens.cap_data(data, _tokens.parse_max_chars(args))
        self.emit("context", data)
        return OK

    def cmd_tick(self, args: list[str]) -> int:
        try:
            st, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("tick", str(e))
            return USAGE
        sid = dag.next_id(rm, state)
        agent = current_agent()
        epic = _parse_epic_arg(args)
        i = 0
        while i < len(args):
            if args[i] == "--agent" and i + 1 < len(args):
                agent = args[i + 1]
                i += 2
                continue
            if args[i] == "--epic" and i + 1 < len(args):
                i += 2
                continue
            if args[i].startswith("--epic="):
                i += 1
                continue
            if not args[i].startswith("-"):
                sid = args[i]
            i += 1
        epic_warning = ""
        if epic:
            sid, epic_warning = _restrict_sid_to_epic(rm, state, sid, epic)
        step = dag.step_by_id(rm, sid) if sid else None
        if step is not None:
            frm = step.replace.from_pat if step.replace else ""
            step.engine = default_engine(step.engine, from_pat=frm)
            if step.engine not in ENGINES:
                hint = " (use run with verify 'bash ...')" if step.engine == "bash" else ""
                self.emit_err("tick", f"unsupported engine: {step.engine}{hint} (fix via plan --step {step.id} --engine run|implement|manual)")
                return UNSUPPORTED
        if step is None:
            body = {"action": "done", "context": context.tick_view(self.root, rm, state, step)}
            if epic:
                body["epic"] = epic
            if epic_warning:
                body["warning"] = epic_warning
            self.emit("tick", body)
            return OK
        if is_stop_engine(step.engine):
            if state.claim_step and state.claim_step != step.id and state.claim_agent:
                self.emit_err(
                    "tick",
                    f"conflict: held {state.claim_step}",
                    claim_held_payload(state),
                )
                return CONFLICT
            if not same_claim_client(state, agent):
                self.emit_err(
                    "tick",
                    f"conflict: held by {state.claim_agent}",
                    claim_held_payload(state),
                )
                return CONFLICT
            if gitops.is_repo(self.root):
                try:
                    wt = gitops.ensure_worktree(self.root)
                    state.worktree = str(wt)
                except RuntimeError:
                    pass
            state.claim_step = step.id
            state.claim_agent = agent or state.claim_agent or "agent"
            if step.id not in state.started:
                state.started.append(step.id)
            st.write_state(state)
            loc = context.where_to_edit(self.root, state, step)
            reason = step.engine or "manual"
            tick_payload = {
                "action": "stop",
                "reason": reason,
                "status": "in_progress",
                "claimed": True,
                "want": step_want(step),
                "path": step_paths(step),
                "extras": list(step.extras or []),
                "verify": step.verify or rm.verify,
                "worktree": loc["worktree"],
                "edit_root": loc["edit_root"],
                "after_edit": loc["after_edit"],
                "claim_agent": state.claim_agent,
                "context": context.tick_view(self.root, rm, state, step),
                **({"epic": epic} if epic else {}),
                **({"warning": epic_warning} if epic_warning else {}),
            }
            _attach_contract_warning(tick_payload, step)
            self.emit("tick", tick_payload)
            self._backup_best_effort()
            return OK
        # scaffold and run apply+verify like replace
        self._capture = []
        try:
            apply_args = [sid] if sid else []
            code = self.cmd_apply(apply_args)
            if code == 0:
                v = self.cmd_verify([sid] if sid else [])
                code = v
            events = list(self._capture)
        finally:
            self._capture = None
        _, rm2, state2 = self.load()
        step2 = dag.step_by_id(rm2, sid)
        here = state2.worktree or self.root
        followup = ""
        for ev in events:
            if ev.get("command") == "apply":
                followup = (ev.get("data") or {}).get("followup") or ""
        self.emit(
            "tick",
            {
                "action": "applied" if code == 0 else "failed",
                "code": code,
                "events": events,
                "followup": followup,
                "context": context.tick_view(here if Path(here).is_dir() else self.root, rm2, state2, step2),
            },
        )
        return code

    def cmd_plan(self, args: list[str]) -> int:
        st = Store(self.root)
        try:
            rm = st.load_roadmap()
        except FileNotFoundError:
            rm = default_roadmap(self.root)
        state = st.load_state()
        if "--check" in (args or []):
            # V1.2: read-only validation gate. Never writes roadmap or
            # state (mtime-proof); exits 5 with findings, 0 when clean.
            # V2: --strict additionally errors on sham-verify tautologies.
            from rfg.doctor import structure_warnings as _struct_w

            try:
                findings = _struct_w(rm.steps)
            except Exception:
                findings = []
            findings.extend(contract_check_findings(rm.steps))
            if "--strict" in (args or []):
                for s in rm.steps:
                    if (
                        (s.oracle or "test") == "test"
                        and (s.engine or "").strip() != "survey"
                        and is_sham_verify(s.verify, engine=s.engine)
                    ):
                        findings.append(
                            {
                                "kind": "sham-verify",
                                "step": s.id,
                                "detail": f"verify {s.verify!r} is a tautology (proves nothing)",
                            }
                        )
            out = {
                "ok": not findings,
                "findings": findings,
                "counts": {"total": len(rm.steps), "findings": len(findings)},
            }
            if findings:
                self.emit("plan", {**out, "check": True}, ok=False,
                          error=f"check failed: {len(findings)} finding(s)")
                return CONFLICT
            self.emit("plan", {**out, "check": True})
            return OK
        step = Step(id="")
        have = False
        from_impact = False
        list_mode = False
        goal_arg = ""
        hyp_arg = ""
        acc_args: list[str] = []
        engine_explicit = False
        replace_explicit = False
        i = 0
        while i < len(args):
            a = args[i]

            def val() -> str:
                nonlocal i
                if i + 1 < len(args):
                    i += 1
                    return args[i]
                return ""

            if a in ("--list", "--all", "-l"):
                list_mode = True
            elif a == "--step":
                step.id = val()
                have = True
            elif a == "--title":
                step.title = val()
                have = True
            elif a == "--from":
                if step.replace is None:
                    step.replace = Replace(from_pat="", to="")
                step.replace.from_pat = val()
                replace_explicit = True
                have = True
            elif a == "--to":
                if step.replace is None:
                    step.replace = Replace(from_pat="", to="")
                step.replace.to = val()
                replace_explicit = True
                have = True
            elif a == "--depends":
                d = val()
                try:
                    step.depends_on = coerce_depends_list(d)
                except ValueError as e:
                    msg = str(e)
                    if not msg.startswith("unsupported"):
                        msg = f"unsupported: {msg}"
                    self.emit_err("plan", msg)
                    return UNSUPPORTED
            elif a == "--verify":
                v = val()
                if have:
                    step.verify = v
                else:
                    rm.verify = v
            elif a == "--hypothesis":
                hyp_arg = val()
            elif a == "--symbol":
                rm.hypothesis.symbol = val()
                rm.hypothesis.from_pat = rm.hypothesis.symbol
            elif a == "--from-impact":
                from_impact = True
                have = True
            elif a == "--path":
                try:
                    plist = coerce_path_list(val())
                except ValueError as e:
                    msg = str(e)
                    if not msg.startswith("unsupported"):
                        msg = f"unsupported: {msg}"
                    self.emit_err("plan", msg)
                    return UNSUPPORTED
                for p in plist:
                    if p not in step.paths:
                        step.paths.append(p)
                    if step.replace is not None and p not in step.replace.paths:
                        step.replace.paths.append(p)
                have = True
            elif a in ("--extras", "--extra", "--extras-path"):
                try:
                    plist = coerce_path_list(val())
                except ValueError as e:
                    msg = str(e)
                    if not msg.startswith("unsupported"):
                        msg = f"unsupported: {msg}"
                    self.emit_err("plan", msg)
                    return UNSUPPORTED
                for p in plist:
                    if p and p not in step.extras:
                        step.extras.append(p)
                have = True
            elif a == "--engine":
                step.engine = val()
                if step.engine == "notes":
                    step.engine = "survey"
                engine_explicit = True
                have = True
            elif a == "--diff-budget":
                try:
                    step.diff_budget = int(val() or 0)
                except ValueError:
                    step.diff_budget = 0
                have = True
            elif a == "--edge":
                step.edge = val()
                have = True
            elif a == "--oracle":
                step.oracle = val()
                have = True
            elif a == "--goal":
                goal_arg = val()
            elif a == "--want":
                step.want = val()
                have = True
            elif a == "--profile":
                rm.goal.profile = val()
            elif a == "--acceptance":
                acc_args.append(val())
            elif a == "--budget":
                try:
                    rm.budget = Budget(max_applies=int(val() or 0))
                except ValueError:
                    pass
            elif a == "--oracle-cmd":
                k = step.oracle if have and step.oracle and step.oracle != "test" else (
                    rm.goal.profile if rm.goal.profile in ("perf", "debug", "security") else "perf"
                )
                _upsert_oracle(rm, k, command=val())
            elif a == "--max-ms":
                k = step.oracle if have and step.oracle and step.oracle != "test" else "perf"
                try:
                    _upsert_oracle(rm, k, max_ms=float(val() or 0))
                except ValueError:
                    pass
            elif a == "--max-ratio":
                k = step.oracle if have and step.oracle and step.oracle != "test" else "perf"
                try:
                    _upsert_oracle(rm, k, max_ratio=float(val() or 0))
                except ValueError:
                    pass
            i += 1
        if hyp_arg and not (have and step.id):
            rm.hypothesis.statement = hyp_arg
        if acc_args and not (have and step.id):
            rm.goal.acceptance.extend(acc_args)
        if goal_arg and have and step.id:
            self.emit_err("plan", "conflict: --goal is campaign-only; use --want with --step")
            return CONFLICT
        if goal_arg:
            rm.goal.statement = goal_arg
        if step.want and not step.goal:
            step.goal = step.want
        # Fail fast on unknown engines: tick/apply would only say
        # "unsupported engine" later. Suggest the closest builtin.
        if engine_explicit and step.engine and step.engine not in ENGINES:
            hint = ""
            if step.engine == "bash":
                hint = " (use engine run with --verify 'bash ...' or implement/manual)"
            elif step.engine in ("maven", "mvn", "gradle", "npm", "cargo", "pytest", "go"):
                hint = f" (toolchains are verify commands, not engines; use implement/manual/run with --verify)"
            self.emit_err(
                "plan",
                f"unsupported engine: {step.engine}{hint} (engines: {', '.join(e or 'implement' for e in ENGINES if e)})",
            )
            return UNSUPPORTED
        existing = next((s for s in rm.steps if have and step.id and s.id == step.id), None)
        if have and step.id and not step.engine:
            if existing is not None and not engine_explicit and not replace_explicit:
                pass  # field-preserving update: keep existing engine
            elif step.replace and step.replace.from_pat:
                step.engine = "replace"
            elif existing is None:
                step.engine = "implement"
            # updates without explicit engine/from stay engine-empty so merge below skips
        if step.replace is not None:
            for p in step.paths:
                if p not in step.replace.paths:
                    step.replace.paths.append(p)
        profile_switched = ""
        if (
            have
            and step.engine in ("implement", "scaffold", "run")
            and rm.goal.profile == "refactor"
            and not (step.replace and step.replace.from_pat)
        ):
            rm.goal.profile = "feature"
            profile_switched = "profile switched: refactor → feature (implement/scaffold/run)"
        impact_note = ""
        if from_impact and have:
            q = ""
            if step.replace and step.replace.from_pat:
                q = step.replace.from_pat
            q = q or rm.hypothesis.symbol or rm.hypothesis.from_pat
            if q:
                if step.replace is None:
                    step.replace = Replace(from_pat=q, to="")
                rep = index.impact(self.root, q)
                files = sorted(rep.get("files") or [], key=lambda x: -int(x.get("hits") or 0))
                seen = set(step.replace.paths)
                for f in files:
                    p = f.get("path") or ""
                    if not p or p in seen:
                        continue
                    step.replace.paths.append(p)
                    seen.add(p)
                    if len(step.replace.paths) >= 8:
                        break
                if not step.replace.paths:
                    impact_note = "no index, path unchanged"
            else:
                impact_note = "no index, path unchanged"
        if have and step.id:
            found = False
            for idx, s in enumerate(rm.steps):
                if s.id == step.id:
                    if step.title:
                        s.title = step.title
                    if step.replace:
                        if s.replace is None:
                            s.replace = step.replace
                        else:
                            if step.replace.from_pat:
                                s.replace.from_pat = step.replace.from_pat
                            if step.replace.to:
                                s.replace.to = step.replace.to
                            for p in step.replace.paths:
                                if p and p not in s.replace.paths:
                                    s.replace.paths.append(p)
                    if step.depends_on:
                        s.depends_on = step.depends_on
                    if step.verify:
                        s.verify = step.verify
                    if step.engine:
                        s.engine = step.engine
                    if step.diff_budget:
                        s.diff_budget = step.diff_budget
                    if step.edge:
                        s.edge = step.edge
                    if step.oracle:
                        s.oracle = step.oracle
                    if step.goal:
                        s.goal = step.goal
                    if step.want:
                        s.want = step.want
                    if step.paths:
                        seen = list(s.paths)
                        for p in step.paths:
                            if p and p not in seen:
                                seen.append(p)
                        s.paths = seen
                    if step.extras:
                        seen_e = list(s.extras or [])
                        for p in step.extras:
                            if p and p not in seen_e:
                                seen_e.append(p)
                        s.extras = seen_e
                    rm.steps[idx] = s
                    found = True
                    break
            if not found:
                if not step.title:
                    step.title = step.id
                rm.steps.append(step)
        if any(s.verify for s in rm.steps) and is_fallback_verify(rm.verify):
            rm.verify = ""
        from rfg.doctor import oracle_warnings

        warns = oracle_warnings(rm.steps)
        # H03: identical verifies warn (with dedup hint) but never block growth.
        # The old " used on N steps" conflict punished large campaigns instead
        # of suggesting deduplication, so it is warning-only now.
        # Unknown engines are a plan-time error above, but hand-edited
        # roadmaps can still carry them: surface as warnings, not silence.
        from rfg.doctor import unknown_engine_warnings as _unknown_eng

        warns = list(warns) + _unknown_eng(rm.steps)
        cw_focus = step if have else dag.step_by_id(rm, dag.next_id(rm, state) or "")
        if cw_focus is not None:
            cw = contract_warning_for(cw_focus)
            if cw and cw not in warns:
                warns.append(cw)
        # M1: plan surfaces the same toolchain hints as doctor (not doctor-only).
        from rfg.doctor import toolchain_notes_for as _tc_notes

        try:
            _tc_cmds = [(s.id, s.verify) for s in rm.steps if s.verify]
            if rm.verify:
                _tc_cmds.append(("roadmap", rm.verify))
            tc_notes = _tc_notes(_tc_cmds, self.root)
        except Exception:
            tc_notes = []
        for _n in tc_notes:
            if _n not in warns:
                warns.append(_n)
        # V1.1: roadmap structure findings surface as warnings (single
        # source: dag via doctor). plan --check (V1.2) will exit on them.
        try:
            from rfg.doctor import structure_warnings as _struct_w

            for _f in _struct_w(rm.steps):
                _w = f"{_f.get('step')} {_f.get('kind')}: {_f.get('detail')}"
                if _w not in warns:
                    warns.append(_w)
        except Exception:
            pass
        st.save_roadmap(rm)
        if not st.state_path.is_file():
            st.write_state(state)
        out = dag.slim_plan(rm, state)
        steps = out.get("steps") or []
        epic = _parse_epic_arg(args)
        epic_warning = ""
        if epic:
            from rfg import scope as _scope

            steps = [s for s in steps if _scope.epic_of(s.get("id") or "") == epic]
            out["epic"] = epic
            w = _scope.unknown_epic_warning([s.id for s in rm.steps], epic)
            if w:
                epic_warning = w
                out["warning"] = w
        out["counts"] = {
            "total": len(steps),
            "ready": sum(1 for s in steps if s.get("status") in ("ready", "claimed", "in_progress")),
        }
        if list_mode:
            out["steps"] = steps
            out["list"] = True
            if warns:
                out["warnings"] = warns
            if epic_warning:
                out.setdefault("warnings", []).append(epic_warning)
            if tc_notes:
                out["toolchain"] = tc_notes
            if profile_switched:
                out.setdefault("warnings", []).append(profile_switched)
            self.emit("plan", out)
            return OK
        sid = step.id if have and step.id else out.get("next")
        focused = dag.step_by_id(rm, sid) if sid else None
        out["steps"] = [s for s in steps if s.get("id") == sid][:1]
        if focused is not None:
            # Compact step definition: plan without --step is useful without
            # a second context call (feedback: rfgfeedback B1/B3).
            out["step"] = focused.id
            out["title"] = focused.title
            out["engine"] = focused.engine or default_engine(focused.engine, from_pat=(focused.replace.from_pat if focused.replace else ""))
            out["want"] = step_want(focused)
            out["path"] = step_paths(focused)
            out["extras"] = list(focused.extras or [])
            out["verify"] = step_observation(focused, rm.verify)
            out["depends"] = list(focused.depends_on)
            out["status"] = dag.step_status(rm, state, focused)
        elif have and step.id:
            # Fallback when no focused step resolved: never echo the unmerged
            # delta as if it were state (Meridian: a verify-only update
            # answered "path":[]). Re-read the merged roadmap entry.
            _merged = dag.step_by_id(rm, step.id)
            _src = _merged if _merged is not None else step
            out["step"] = step.id
            out["engine"] = _src.engine
            out["path"] = step_paths(_src)
            out["extras"] = list(_src.extras or [])
            out["verify"] = _src.verify
        if impact_note:
            out["impact"] = {"hits": 0, "note": impact_note}
        if epic:
            out["epic"] = epic
        if epic_warning:
            out["warning"] = epic_warning
        if warns:
            out["warnings"] = warns
        if epic_warning:
            out.setdefault("warnings", []).append(epic_warning)
        if tc_notes:
            out["toolchain"] = tc_notes
        if profile_switched:
            out.setdefault("warnings", []).append(profile_switched)
        self.emit("plan", out)
        return OK

    def cmd_apply(self, args: list[str]) -> int:
        try:
            st, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("apply", str(e))
            return USAGE
        sid = dag.next_id(rm, state)
        agent = current_agent()
        force = False
        epic = _parse_epic_arg(args)
        i = 0
        while i < len(args):
            if args[i] == "--dry-run":
                i += 1
                continue
            if args[i] == "--force":
                force = True
                i += 1
                continue
            if args[i] == "--agent" and i + 1 < len(args):
                agent = args[i + 1]
                i += 2
                continue
            if args[i] == "--epic" and i + 1 < len(args):
                i += 2
                continue
            if args[i].startswith("--epic="):
                i += 1
                continue
            if not args[i].startswith("-"):
                sid = args[i]
            i += 1
        epic_warning = ""
        if epic:
            sid, epic_warning = _restrict_sid_to_epic(rm, state, sid, epic)
        if not sid:
            if epic:
                self.emit(
                    "apply",
                    {"step": None, "epic": epic, "warning": epic_warning or "no free step"},
                )
                return OK
            self.emit_err("apply", "no free step")
            return OK
        if rm.budget.max_applies and state.applies_used >= rm.budget.max_applies:
            self.emit_err("apply", f"conflict: apply budget {rm.budget.max_applies} exhausted")
            return CONFLICT
        if state.claim_step and state.claim_step != sid:
            self.emit_err("apply", f"conflict: step {sid} not claimed (held: {state.claim_step})")
            return CONFLICT
        if not same_claim_client(state, agent):
            self.emit_err(
                "apply",
                f"conflict: claimed by {state.claim_agent}",
                claim_held_payload(state),
            )
            return CONFLICT
        step = dag.step_by_id(rm, sid)
        if not step:
            self.emit_err("apply", "unknown step " + sid)
            return USAGE
        checkpoint_warn = ""
        frm0 = step.replace.from_pat if step.replace else ""
        step.engine = default_engine(step.engine, from_pat=frm0)
        if step.engine and step.engine not in ENGINES:
            self.emit_err("apply", "unsupported engine: " + step.engine)
            return UNSUPPORTED
        if step.engine == "ast-grep":
            from rfg import astgrep

            if not astgrep.available():
                self.emit_err("apply", "unsupported engine: ast-grep (binary not found)")
                return UNSUPPORTED
        edge_list = edges.scan(self.root)
        rels_preview = []
        if not is_stop_engine(step.engine) and step.replace and step.replace.from_pat:
            rels_preview = applymod.changed_rels(self.root, step)
        macros = False
        for rel in rels_preview:
            if not rel.endswith(".rs"):
                continue
            try:
                txt = Path(self.root, rel).read_text(encoding="utf-8")
            except OSError:
                continue
            if caps.rust_has_macros(txt) or (step.replace and caps.looks_like_macro_use(step.replace.from_pat)):
                macros = True
        if step.replace and caps.looks_like_macro_use(step.replace.from_pat):
            macros = True
        cpp_touch = caps.cpp_paths(rels_preview) or (
            step.replace is not None and caps.cpp_paths(step.replace.paths)
        )
        cpp_no_db = cpp_touch and not caps.has_compile_commands(self.root)
        if macros and step.engine not in ("manual", "implement", "scaffold", "run"):
            self.emit_err("apply", "unsupported: rust macros (set engine: manual)")
            return UNSUPPORTED
        if cpp_no_db and step.engine not in ("manual", "implement", "scaffold", "run"):
            from rfg import cxxcompile as cxxc

            hint_paths = list(step.replace.paths) if step.replace else []
            self.emit_err("apply", cxxc.missing_db_hint(self.root, hint_paths))
            return UNSUPPORTED
        target = self.root
        no_head = gitops.is_repo(self.root) and not gitops.has_head(self.root)
        isolation = False
        forced_dirty: list[str] = []
        if not self.dry:
            if not gitops.is_repo(self.root):
                self.emit_err("apply", "not a git repository")
                return USAGE
            if step.engine == "run" or no_head:
                # QW-05: run executes blindly at root — on a tracked-dirty
                # tree that needs explicit --force (names files); stop
                # engines isolate via worktree, run never does.
                if step.engine == "run" and not force and gitops.dirty_tracked(self.root):
                    dirty_files = gitops.dirty_tracked_files(self.root)
                    named = ", ".join(dirty_files[:10]) or "tracked files"
                    self.emit_err(
                        "apply",
                        f"working tree dirty (tracked): {named}; "
                        "re-run with --force to run on the dirty root",
                    )
                    return DIRTY
                if step.engine == "run" and force:
                    forced_dirty = list(gitops.dirty_tracked_files(self.root))
                target = self.root
                isolation = False
                if no_head:
                    state.worktree = self.root
            elif is_stop_engine(step.engine):
                try:
                    h = gitops.head(self.root)
                    wt = gitops.ensure_worktree(self.root)
                    target = str(wt)
                    isolation = True
                    state.worktree = target
                    try:
                        snap = gitops.snapshot(wt, "rfg checkpoint before " + sid)
                        if gitops.snapshot_fallback:
                            checkpoint_warn = (
                                "git identity missing; checkpoint committed as rfg@local"
                            )
                    except RuntimeError as e:
                        snap = h
                        checkpoint_warn = (
                            f"checkpoint snapshot failed ({e}); harvest may see 0 packets"
                        )
                    cp = Checkpoint(
                        id=f"cp-{sid}-{int(datetime.now(timezone.utc).timestamp())}",
                        step_id=sid,
                        commit=snap,
                        worktree=target,
                        created_at=datetime.now(timezone.utc).isoformat(),
                    )
                    state.last_checkpoint = cp
                    state.checkpoints.append(cp)
                except RuntimeError:
                    target = self.root
                    isolation = False
            else:
                dirty = gitops.dirty_tracked(self.root) and not state.worktree
                if dirty and not is_stop_engine(step.engine):
                    self.emit_err("apply", "working tree dirty")
                    return DIRTY
                if dirty and is_stop_engine(step.engine) and not force:
                    dirty_files = gitops.dirty_tracked_files(self.root)
                    named = ", ".join(dirty_files[:10]) or "tracked files"
                    self.emit_err(
                        "apply",
                        f"working tree dirty (tracked): {named}; "
                        "re-run with --force to apply onto the dirty root",
                    )
                    return DIRTY
                if dirty and is_stop_engine(step.engine):
                    forced_dirty = list(gitops.dirty_tracked_files(self.root))
                    target = self.root
                else:
                    try:
                        h = gitops.head(self.root)
                        wt = gitops.ensure_worktree(self.root)
                        target = str(wt)
                        isolation = True
                        state.worktree = target
                        try:
                            snap = gitops.snapshot(wt, "rfg checkpoint before " + sid)
                            if gitops.snapshot_fallback:
                                checkpoint_warn = (
                                    "git identity missing; checkpoint committed as rfg@local"
                                )
                        except RuntimeError as e:
                            snap = h
                            checkpoint_warn = (
                                f"checkpoint snapshot failed ({e}); harvest may see 0 packets"
                            )
                        cp = Checkpoint(
                            id=f"cp-{sid}-{int(datetime.now(timezone.utc).timestamp())}",
                            step_id=sid,
                            commit=snap,
                            worktree=target,
                            created_at=datetime.now(timezone.utc).isoformat(),
                        )
                        state.last_checkpoint = cp
                        state.checkpoints.append(cp)
                    except RuntimeError as e:
                        self.emit_err("apply", str(e))
                        return CONFLICT
        compact = {"files": [], "skipped": [], "hits": 0}
        staged: list[str] = []
        if step.engine in ("manual", "implement", "run", "survey"):
            diff, hits = "", 0
        elif step.engine == "scaffold":
            rels = step_paths(step)
            planned = scaffold.plan(target, rels)
            compact = {
                "files": [{"path": p, "hits": 1} for p in planned],
                "skipped": [],
                "hits": len(planned),
            }
            diff, hits = "", len(planned)
        else:
            try:
                if step.engine == "ast-grep":
                    from rfg import astgrep

                    diff, hits = astgrep.run(target, step, dry=True)
                    compact = {"files": [], "skipped": [], "hits": hits}
                else:
                    prev = applymod.preview(target, step)
                    diff, hits = prev["diff"], prev["hits"]
                    compact = applymod.compact_dry_run(prev)
            except FileNotFoundError as e:
                self.emit_err("apply", str(e))
                return UNSUPPORTED
            except (ValueError, RuntimeError) as e:
                self.emit_err("apply", str(e))
                return USAGE
        lines = risk.diff_line_count(diff)
        if risk.over_budget(step, lines):
            self.emit_err("apply", f"conflict: diff {lines} lines exceeds budget {step.diff_budget}")
            return CONFLICT
        rs = None
        if self.show_risk:
            rs = risk.score(
                step,
                hits=hits,
                diff_lines=lines,
                edges=edge_list,
                macros=macros,
                cpp_no_db=cpp_no_db,
            )
        frm = step.replace.from_pat if step.replace else ""
        followup = _followup_manual(compact.get("skipped"), frm)
        zero_hits = list(compact.get("zero_hits") or [])
        if self.dry:
            payload = {
                "step": sid,
                "dry_run": True,
                "hits": hits,
                "files": compact["files"],
                "skipped": compact["skipped"],
                "manual": is_stop_engine(step.engine),
                "edge": step.edge,
                "followup": followup,
                "zero_hits": zero_hits,
            }
            if self.show_risk:
                payload["risk"] = rs
            if step.engine == "replace" and hits == 0:
                payload["warning"] = f"0 hits in {len(zero_hits)} path(s); check scope"
            _attach_contract_warning(payload, step)
            if checkpoint_warn:
                payload["checkpoint_warning"] = checkpoint_warn
                prev = (payload.get("warning") or "").strip()
                payload["warning"] = f"{prev}; {checkpoint_warn}" if prev else checkpoint_warn
            if self.show_diff:
                payload["diff"] = diff
                self.emit("apply", payload, diff=diff)
            else:
                self.emit("apply", payload)
            self._backup_best_effort()
            return OK
        if step.engine in ("manual", "implement", "run", "survey"):
            n = 0
        elif step.engine == "scaffold":
            rels = step_paths(step)
            created = scaffold.apply(target, rels)
            n = len(created)
            compact = {
                "files": [{"path": p, "hits": 1} for p in created],
                "skipped": [],
                "hits": n,
            }
        else:
            try:
                if step.engine == "ast-grep":
                    from rfg import astgrep

                    n = astgrep.run(target, step, dry=False)[1]
                else:
                    n = applymod.apply_step(target, step)
            except FileNotFoundError as e:
                self.emit_err("apply", str(e))
                return UNSUPPORTED
            except (ValueError, RuntimeError) as e:
                self.emit_err("apply", str(e))
                return CONFLICT
        # Format-after-apply runs for every engine, report-only (never a gate):
        # agent-written implement/manual code needs it most; mechanical-only
        # plus show_risk-gated left Go/Rust files unformatted (Meridian).
        # Missing formatters are skipped with a "not on PATH" note, never faked.
        formatted = []
        if step.engine not in ("manual", "implement", "run", "scaffold", "survey"):
            changed = applymod.changed_rels(target, step) if step.replace else []
            formatted = fmtutil.format_paths(target, changed)
        extra_edits: list[str] = []
        extra_omitted = 0
        extra_show: list[str] = []
        stop_present: list[str] = []
        if is_stop_engine(step.engine) and not self.dry:
            from rfg.types import expand_dir_paths as _expand
            from rfg.types import step_allowed_paths as _allowed

            declared_raw = _allowed(step)
            expanded = _expand(self.root, declared_raw)
            # dir entries count as declared via their expanded files
            present = [
                p
                for p in (expanded or declared_raw)
                if (Path(target) / p).is_file() or (Path(self.root) / p).is_file()
            ]
            # a bare dir path present on disk satisfies the declaration
            for d in declared_raw:
                if (Path(self.root) / d).is_dir() or (Path(target) / d).is_dir():
                    present = sorted(set(present) | {d})
            missing = [p for p in (expanded or declared_raw) if p not in present and not (Path(self.root) / p).is_dir()]
            if declared_raw and not present and step.engine != "survey":
                want = ",".join(declared_raw)
                have = ",".join(sorted(gitops.changed_rels(self.root))[:10])
                self.emit_err(
                    "apply",
                    f"not implemented: missing {','.join(missing) or want} "
                    f"(want path[]={want}; changed on root={have or 'none'}; "
                    "fix: write the file then re-apply, or extend path[] via plan --path)",
                )
                return USAGE
            declared = set(present) | set(declared_raw)
            extra_edits = [
                p
                for p in gitops.changed_rels(self.root)
                if p not in declared
                and (Path(self.root) / p).is_file()
                and gitops.is_campaign_edit(p, self.root)
            ]
            extra_show = sorted(extra_edits)[:20]
            extra_omitted = len(extra_edits)
            compact = {
                "files": [{"path": p, "hits": 1} for p in present],
                "skipped": [],
                "hits": len(present) + len(extra_edits),
            }
            n = len(present) + len(extra_edits)
            stop_present = list(present + extra_edits)
            wt = state.worktree or target
            if Path(wt).resolve() != Path(self.root).resolve():
                staged = gitops.stage_paths(self.root, wt, present + extra_edits, overwrite=True)
        if is_stop_engine(step.engine) and stop_present and not self.dry:
            # report-only: agent-written files get the same format pass as
            # mechanical ones; failures/notes never block the apply.
            try:
                formatted = fmtutil.format_paths(self.root, stop_present)
            except Exception:
                formatted = []
        dag.mark_applied(state, sid)
        if is_mechanical(step.engine):
            state.applies_used += 1
        st.write_state(state)
        if followup == "manual":
            _ensure_followup(st, rm, step)
        audit.record(self.root, "apply", step=sid, agent=agent, hits=n if not self.dry else 0)
        payload = {
            "step": sid,
            "hits": n,
            "worktree": target,
            "files": compact.get("files") or [],
            "skipped": compact.get("skipped") or [],
            "manual": is_stop_engine(step.engine),
            "edge": step.edge,
            "staged": staged,
            "extra": extra_show,
            "extra_count": extra_omitted,
            "extra_omitted": 0,
            "extra_staged": extra_show,
            "followup": followup,
            "claim_agent": state.claim_agent or agent,
            "isolation": isolation,
            "zero_hits": zero_hits if step.engine in ("replace", "ast-grep") else [],
        }
        if self.show_risk:
            payload["risk"] = rs
        # format report is always present (possibly "not on PATH" notes);
        # it never gates the apply.
        payload["format"] = formatted
        if step.engine in ("replace", "ast-grep") and n == 0:
            payload["warning"] = f"0 hits in {len(zero_hits)} path(s); check scope"
        if extra_omitted and is_stop_engine(step.engine):
            extra_hint = (
                f"{extra_omitted} extra file(s) outside path[] staged: "
                f"{', '.join(extra_show[:5])}; extend path[] via plan --path or allowlist via plan --extras if intentional"
            )
            payload["warning"] = extra_hint if not payload.get("warning") else payload["warning"] + "; " + extra_hint
            payload["extra_warning"] = extra_hint
        _attach_contract_warning(payload, step)
        if checkpoint_warn:
            payload["checkpoint_warning"] = checkpoint_warn
            prev = (payload.get("warning") or "").strip()
            payload["warning"] = f"{prev}; {checkpoint_warn}" if prev else checkpoint_warn
        if step.extras:
            payload["extras"] = list(step.extras)
        if forced_dirty:
            payload["forced_dirty"] = forced_dirty
        if no_head:
            payload["warning"] = "no-head-commit"
            payload["no_head_commit"] = True
        if self.show_diff:
            payload["diff"] = diff
            self.emit("apply", payload, diff=diff)
        else:
            self.emit("apply", payload)
        self._backup_best_effort()
        return OK

    def cmd_verify(self, args: list[str]) -> int:
        try:
            st, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("verify", str(e))
            return USAGE
        sid = state.applied[-1] if state.applied else ""
        if args:
            sid = args[0]
        if not sid:
            nxt = dag.next_id(rm, state) or "STEP"
            self.emit_err(
                "verify",
                f"no implemented step (apply after edit); fix: rfg tick {nxt} (claim+contract), edit root files, then rfg apply {nxt}",
            )
            return USAGE
        step = dag.step_by_id(rm, sid)
        if not step:
            self.emit_err("verify", "unknown step")
            return USAGE
        if sid not in state.applied:
            loc0 = context.where_to_edit(self.root, state, step)
            self.emit_err(
                "verify",
                f"not implemented (apply after edit); fix: rfg apply {sid} after editing root "
                f"(edit_root={loc0.get('edit_root')}, after_edit={loc0.get('after_edit')}), then rfg verify {sid}",
            )
            return USAGE
        kind = (step.oracle or "").strip()
        if not kind or kind == "test":
            if rm.goal.profile in ("perf", "debug", "security") and not step.verify:
                kind = rm.goal.profile
            else:
                kind = kind or "test"
        cmd = step_observation(step, "")
        if step.engine == "survey":
            cmd = cmd or "echo survey"
            log_path = write_verify_log(self.root, sid, cmd, 0, "survey: no code change")
            if sid not in state.verified:
                state.verified.append(sid)
            state.failed = [x for x in state.failed if x != sid]
            if state.claim_step == sid:
                state.claim_step = ""
                state.claim_agent = ""
            st.write_state(state)
            self.emit("verify", {"step": sid, "command": cmd, "output": "survey", "log": log_path, "engine": "survey"})
            self._write_last_stand_best_effort()
            return OK
        if not cmd and not is_contract(step.engine):
            for o in rm.oracles:
                if o.kind == kind:
                    cmd = o.command
                    break
            if not cmd and kind == "test":
                cmd = rm.verify
        if not cmd or (not step.verify and is_fallback_verify(cmd)):
            self.emit_err("verify", "unsupported: trivial verify (need a real command, not true/empty)")
            return UNSUPPORTED
        paths = step_paths(step)
        if kind == "test" and (is_trivial(cmd) or cmd.strip() == "test -n ok"):
            here = state.worktree or self.root
            if cxxcompile.should_default(here, paths) or cxxcompile.should_default(self.root, paths):
                cmd = cxxcompile.command(here if Path(here, "compile_commands.json").is_file() else self.root, paths)
        loc = context.where_to_edit(self.root, state, step)
        # run applies at root without isolation, so it must also verify at
        # root: a fresh worktree has neither the roadmap nor root-untracked
        # files, and worktree-relative commands (parity, scripts/) fail there
        # spuriously while apply saw root.
        run_at_root = (step.engine or "") == "run"
        directory = self.root if (loc.get("edit_root") or run_at_root) else (state.worktree or self.root)
        if kind == "test" and is_trivial(cmd):
            self.emit_err("verify", "unsupported: trivial verify (need a real command, not true/empty)")
            return UNSUPPORTED
        from rfg.verify import load_env as _load_env

        try:
            env_extra = _load_env(self.root) or None
        except Exception:
            env_extra = None
        ora = next((o for o in rm.oracles if o.kind == kind), None)
        if kind == "perf":
            code, out = oramod.run_perf(directory, cmd, ora, store_root=self.root, env_extra=env_extra)
        elif kind == "debug":
            code, out = oramod.run_debug(directory, cmd, env_extra=env_extra)
        else:
            try:
                timeout = float(os.environ.get("RFG_VERIFY_TIMEOUT") or 60)
            except ValueError:
                timeout = 60.0
            code, out = run_verify(directory, cmd, kind, timeout=timeout, env_extra=env_extra)
        log_path = write_verify_log(self.root, sid, cmd, code, out)
        # R4: ledger event (best-effort, ignored path, never breaks verify).
        try:
            from rfg import ledger as _ledger

            _ledger.record_verify_event(self.root, sid, sid, code, log_path)
        except Exception:
            pass
        if code == 4:
            self.emit_err("verify", (out or "unsupported oracle").strip())
            return UNSUPPORTED
        if code != 0:
            if sid not in state.failed:
                state.failed.append(sid)
            st.write_state(state)
            # M1: verify failures surface the doctor toolchain hint inline
            # (same text as doctor/plan), so agents need no extra doctor call.
            # M2: exit 127 / command-not-found names binary+step and points
            # at .rfg/env (verify shells miss session PATH exports).
            try:
                from rfg.doctor import toolchain_notes_for as _tc_v

                _hints = _tc_v([(sid, cmd)], self.root)
            except Exception:
                _hints = []
            try:
                from rfg.verify import env_hint_for_failure as _env_hint

                _missing = _env_hint(code, out, cmd, sid)
            except Exception:
                _missing = ""
            if _missing and _missing not in _hints:
                _hints.append(_missing)
            # M6: test failures name the stored log so the next step is known.
            _msg = (clip_output(out) + f" verify failed [log {log_path}]").strip()
            if _hints:
                _msg = (_msg + " hint: " + "; ".join(_hints)).strip()
            self.emit_err("verify", _msg)
            return VERIFY_FAIL
        # Stufe 1 cross-verify: dependents + path-overlap steps must still pass.
        from rfg.verify import related_step_ids as _related

        cross_failed: list[str] = []
        cross_items: list[tuple[str, str, int, str, str]] = []
        skipped: list[dict] = []
        failed_before = set(state.failed)
        try:
            related = _related(rm.steps, step)
        except Exception:
            related = []
        import time as _time

        try:
            cross_budget = float(os.environ.get("RFG_CROSS_BUDGET") or 120)
        except ValueError:
            cross_budget = 120.0
        try:
            deadline = _time.monotonic() + cross_budget
        except Exception:
            deadline = 0.0
        # F1: dedup memo (opt-in RFG_DEDUP_MEMO=1). Identical related
        # commands run once; reuse is listed, never silent. Default off.
        memo_on = os.environ.get("RFG_DEDUP_MEMO") == "1"
        memo: dict[tuple[str, str], tuple[int, str, str, str]] = {}

        def _memo_key(kind: str, cmd: str) -> tuple[str, str]:
            return (kind or "", " ".join((cmd or "").split()))
        deduped: list[dict] = []
        # XB: cross-section elapsed for budget_note (warn-only, D4-style
        # measure-only; never ordering, deadline, or gates).
        try:
            _cross_t0 = _time.monotonic()
        except Exception:
            _cross_t0 = 0.0
        for rid in related:
            rs = dag.step_by_id(rm, rid)
            if not rs:
                continue
            # Only already-implemented steps are meaningful cross-signal;
            # pending dependents cannot pass yet and must not block this verify.
            if rid not in state.applied and rid not in state.verified:
                continue
            rcmd = step_observation(rs, "")
            if not rcmd or is_trivial(rcmd):
                continue
            rkind = (rs.oracle or "test")
            mk = _memo_key(rkind, rcmd)
            if memo_on and mk in memo:
                _m_code, _m_out, _m_log, _m_via = memo[mk]
                deduped.append({"step": rid, "via": _m_via, "reason": "identical-command"})
                if _m_code != 0:
                    cross_failed.append(rid)
                    cross_items.append((rid, rcmd, _m_code, _m_out, _m_log))
                continue
            try:
                timeout2 = float(os.environ.get("RFG_VERIFY_TIMEOUT") or 60)
            except ValueError:
                timeout2 = 60.0
            # D2: deadline with skip-with-reason (never silent); the
            # per-verify timeout is capped by the remaining budget.
            try:
                remaining = deadline - _time.monotonic()
            except Exception:
                remaining = timeout2
            if deadline and remaining < 5.0:
                skipped.append({"step": rid, "reason": "budget-exhausted"})
                continue
            timeout2 = cross_timeout_for(remaining if deadline else timeout2, timeout2)
            # D4: measure only — elapsed feeds log header + ledger event,
            # never ordering, budget, or gates.
            try:
                _t0 = _time.monotonic()
            except Exception:
                _t0 = 0.0
            rcode, rout = run_verify(directory, rcmd, (rs.oracle or "test"), timeout=timeout2, env_extra=env_extra)
            try:
                _elapsed = (_time.monotonic() - _t0) * 1000.0 if _t0 else None
            except Exception:
                _elapsed = None
            rlog = write_verify_log(self.root, f"{sid}__cross_{rid}", rcmd, rcode, rout,
                                    elapsed_ms=_elapsed)
            if memo_on and rcode == 0:
                memo[mk] = (rcode, rout, rlog, rid)
            if rcode == 2 and "verify timeout" in (rout or ""):
                # Degrade, don't fail: a timeout says nothing about
                # correctness (DYN-4 triage: cost-noise, not regress).
                skipped.append(
                    {
                        "step": rid,
                        "reason": "timeout",
                        "triage": triage_cross_failure(rcode, rout, rid in failed_before),
                    }
                )
                continue
            if rcode != 0:
                cross_failed.append(rid)
                cross_items.append((rid, rcmd, rcode, rout, rlog))
        if cross_failed:
            if sid not in state.failed:
                state.failed.append(sid)
            st.write_state(state)
            triage = "; ".join(
                f"{rid}: {triage_cross_failure(rcode, rout, rid in failed_before)}"
                for rid, _, rcode, rout, _ in cross_items
            )
            self.emit_err("verify", cross_verify_message(cross_items) + f" triage: {triage}")
            return VERIFY_FAIL
        if sid not in state.verified:
            state.verified.append(sid)
        state.failed = [x for x in state.failed if x != sid]
        if state.claim_step == sid:
            state.claim_step = ""
            state.claim_agent = ""
        st.write_state(state)
        audit.record(self.root, "verify", step=sid, command=cmd)
        payload = {"step": sid, "command": cmd, "output": clip_output(out), "log": log_path}
        if skipped:
            # D2: skips are visible (never silent, never counted as pass).
            payload["skipped"] = skipped
        if deduped:
            # F1: memo reuse is listed with source (never silent).
            payload["deduped"] = deduped
        try:
            # D5: depth-2 dry-run counter (warn-only measurement).
            from rfg.verify import depth2_ids as _depth2
            from rfg.verify import depth2_warn_threshold as _d2_thr

            _d2 = _depth2(rm.steps, step)
            try:
                _d2_thr_val = _d2_thr()
            except Exception:
                _d2_thr_val = 10
        except Exception:
            _d2 = []
            _d2_thr_val = 10
        if _d2:
            payload["depth2_would_warn"] = _d2
        # XB: depth-2 warn count/threshold (warn-only label, never gates,
        # exit unchanged; log path already in payload["log"] per D3).
        try:
            payload["depth2_warn"] = {"count": len(_d2), "threshold": int(_d2_thr_val)}
        except Exception:
            payload["depth2_warn"] = {"count": len(_d2), "threshold": 10}
        # XB: truncation visibility (warn-only; ranking/cap/exit unchanged).
        try:
            from rfg.verify import related_total_count as _rtotal

            _rtotal_val = int(_rtotal(rm.steps, step))
        except Exception:
            try:
                _rtotal_val = len(related)
            except Exception:
                _rtotal_val = 0
        try:
            _rlen = len(related)
        except Exception:
            _rlen = 0
        payload["related_total"] = _rtotal_val
        payload["related_truncated"] = bool(_rtotal_val > _rlen)
        # XB: cross-budget note (warn-only; RFG_CROSS_BUDGET deadline,
        # all exits, and max_applies path unchanged; max_*=0 disables).
        try:
            # Cross-section seconds (not per-verify elapsed_ms) feed budget_note.
            _cross_elapsed = (_time.monotonic() - _cross_t0) if _cross_t0 else 0.0
        except Exception:
            _cross_elapsed = 0.0
        try:
            _bn = cross_budget_note(_rtotal_val, _cross_elapsed, rm.budget)
        except Exception:
            _bn = ""
        if _bn:
            payload["budget_note"] = _bn
        self.emit("verify", payload)
        self._backup_best_effort()
        self._write_last_stand_best_effort()
        return OK

    def _maybe_autocommit(self, rm, state, args: list[str]) -> dict:
        """Opt-in local snapshot commit after a successful land.

        Enabled by `--commit` or `RFG_AUTO_COMMIT=1`, disabled by
        `--no-commit`. Commits everything git sees except `.rfg/`
        (always excluded; gitignore honored otherwise) with a generated
        message. Never pushes. Any failure (or a clean tree) degrades
        to a payload note; the land itself already succeeded and stays
        exit 0.
        """
        force = "--commit" in (args or [])
        off = "--no-commit" in (args or [])
        if off or (os.environ.get("RFG_AUTO_COMMIT") != "1" and not force):
            return {}
        try:
            if not gitops.is_repo(self.root):
                return {"commit_skipped": "not a git repository"}
            total = len(rm.steps)
            done = len(state.verified)
            last_sid = list(state.verified)[-1] if state.verified else ""
            last_title = ""
            if last_sid:
                _ls = dag.step_by_id(rm, last_sid)
                last_title = (_ls.title if _ls else "") or ""
            if last_sid:
                msg = f"rfg land: {last_sid} {last_title} (RFG-verifiziert) — {rm.goal.statement} ({done}/{total} verified)".strip()
            else:
                msg = f"rfg land: {rm.goal.statement} ({done}/{total} verified)"
            sha = gitops.commit_all(self.root, msg)
        except Exception as e:
            return {"commit_warning": f"auto-commit failed ({e}); land itself succeeded"}
        if not sha:
            return {"commit_skipped": "tree clean, nothing to commit"}
        return {"commit": sha}

    def _state_backup_payload(self) -> dict:
        """Best-effort roadmap/state backup for successful lands (R6).

        Never fails the land: `.rfg/` is gitignored, so this copy is the
        only harness-side recovery path. Returns {}-with-warning on error.
        """
        try:
            return {"state_backup": gitops.backup_roadmap_state(self.root)}
        except OSError as e:
            return {"warning": f"state backup failed: {e}"}

    def _backup_best_effort(self) -> None:
        """Best-effort roadmap/state backup after mutating loop commands (CR1).

        Side-effect only, never raises, never changes emitted payloads:
        `.rfg/` is gitignored, so frequent copies are the only
        harness-side recovery path after a crash. Ids are
        content-addressed (`<ts>-<sha8>`), prune caps at LAND_BACKUP_KEEP.
        """
        try:
            gitops.backup_roadmap_state(self.root)
        except OSError:
            pass

    def _write_last_stand_best_effort(self) -> None:
        """Best-effort `.rfg/last-stand.md` handoff (RES-B).

        Called after successful verify/land with the fresh store state.
        Never raises, never changes payloads or exits: a missing handoff
        must not break the loop (generat, sonst verrottet es).
        """
        try:
            from rfg import resume as _resume

            _resume.write_last_stand(self.root)
        except Exception:
            pass

    def cmd_land(self, args: list[str]) -> int:
        try:
            st, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("land", str(e))
            return USAGE
        if not gitops.is_repo(self.root):
            self.emit_err("land", "not a git repository")
            return USAGE
        if dag.next_id(rm, state) or state.failed:
            self.emit_err("land", "conflict: roadmap unfinished (next or failed steps)")
            return CONFLICT
        unverified = [s for s in state.applied if s not in state.verified]
        if unverified:
            self.emit_err("land", "conflict: applied but not verified: " + ",".join(unverified))
            return CONFLICT
        wt = state.worktree or ""
        landing_wt = bool(wt) and Path(wt).resolve() != Path(self.root).resolve() and Path(wt).is_dir()
        stop_applied = any(
            is_stop_engine((dag.step_by_id(rm, sid) or Step(id="x")).engine) for sid in state.applied
        )
        if gitops.dirty_tracked(self.root) and not (landing_wt and stop_applied):
            self.emit_err("land", "working tree dirty")
            return DIRTY
        if not wt or Path(wt).resolve() == Path(self.root).resolve() or not Path(wt).is_dir():
            sid = state.verified[-1] if state.verified else ""
            step = dag.step_by_id(rm, sid) if sid else None
            cmd = (step.verify if step else "") or rm.verify
            no_tx = not gitops.has_head(self.root) or (not wt) or Path(wt).resolve() == Path(self.root).resolve()
            if no_tx:
                payload = {
                    "files": [],
                    "deleted": [],
                    "noop": True,
                    "reason": "noop-no-transaction",
                    "reverify": "skipped",
                    "verify": cmd,
                    "no_head_commit": not gitops.has_head(self.root),
                    "acceptance_prose": accept.prose(rm),
                }
                payload.update(self._maybe_autocommit(rm, state, args))
                payload.update(self._state_backup_payload())
                self.emit("land", payload)
                self._write_last_stand_best_effort()
                return OK
            if is_fallback_verify(cmd) or is_trivial(cmd):
                payload = {"files": [], "deleted": [], "noop": True, "reverify": "skipped", "verify": cmd, "acceptance_prose": accept.prose(rm)}
                payload.update(self._maybe_autocommit(rm, state, args))
                payload.update(self._state_backup_payload())
                self.emit("land", payload)
                self._write_last_stand_best_effort()
                return OK
            code, out = run_verify(self.root, cmd, "test")
            write_verify_log(self.root, sid or "land", cmd, code, out)
            if code != 0:
                self.emit_err("land", ((out or "") + " land verify failed").strip())
                return VERIFY_FAIL
            gate = (rm.verify or "").strip()
            if gate and gate != (cmd or "").strip() and not is_fallback_verify(gate) and not is_trivial(gate):
                if not _gate_runnable(gate):
                    write_verify_log(self.root, "land__gate", gate, 4, "skipped: toolchain binary missing")
                else:
                    gcode, gout = run_verify(self.root, gate, "test")
                    write_verify_log(self.root, "land__gate", gate, gcode, gout)
                    if gcode != 0:
                        self.emit_err("land", ((gout or "") + " land gate failed").strip())
                        return VERIFY_FAIL
            acc_code, acc_out, acc_rows = accept.run_all(self.root, rm)
            if acc_code != 0:
                self.emit_err("land", ((acc_out or "") + " land acceptance failed").strip())
                return VERIFY_FAIL
            self.emit(
                "land",
                {
                    "files": [],
                    "deleted": [],
                    "noop": True,
                    "reverify": True,
                    "verify": cmd,
                    "output": clip_output(out),
                    "acceptance": acc_rows,
                    "acceptance_prose": accept.prose(rm),
                    **self._maybe_autocommit(rm, state, args),
                    **self._state_backup_payload(),
                },
            )
            self._write_last_stand_best_effort()
            return OK
        result = gitops.land(self.root, wt)
        sid = state.verified[-1] if state.verified else ""
        step = dag.step_by_id(rm, sid) if sid else None
        cmd = (step.verify if step else "") or rm.verify
        if result.get("noop"):
            payload = {"files": [], "deleted": [], "noop": True, "verify": cmd, "acceptance_prose": accept.prose(rm)}
            payload.update(self._maybe_autocommit(rm, state, args))
            payload.update(self._state_backup_payload())
            self.emit("land", payload)
            self._write_last_stand_best_effort()
            return OK
        if is_trivial(cmd):
            gitops.revert_land(self.root, result.get("backups") or [])
            self.emit_err("land", "unsupported: trivial verify (need a real command, not true/empty)")
            return UNSUPPORTED
        code, out = run_verify(self.root, cmd, "test")
        if code != 0:
            gitops.revert_land(self.root, result.get("backups") or [])
            self.emit_err("land", ((out or "") + " land verify failed").strip())
            return VERIFY_FAIL
        # Stufe 2 gate: the suite-level rm.verify must also pass, even when the
        # last step has its own narrow verify. Stufe 3 (transitive core-file
        # closure) is covered by keeping this gate a real suite command.
        gate = (rm.verify or "").strip()
        if gate and gate != (cmd or "").strip() and not is_fallback_verify(gate) and not is_trivial(gate):
            if not _gate_runnable(gate):
                write_verify_log(self.root, "land__gate", gate, 4, "skipped: toolchain binary missing")
            else:
                gcode, gout = run_verify(self.root, gate, "test")
                write_verify_log(self.root, "land__gate", gate, gcode, gout)
                if gcode != 0:
                    gitops.revert_land(self.root, result.get("backups") or [])
                    self.emit_err("land", ((gout or "") + " land gate failed").strip())
                    return VERIFY_FAIL
        acc_code, acc_out, acc_rows = accept.run_all(self.root, rm)
        if acc_code != 0:
            gitops.revert_land(self.root, result.get("backups") or [])
            self.emit_err("land", ((acc_out or "") + " land acceptance failed").strip())
            return VERIFY_FAIL
        audit.record(self.root, "land", step=sid, files=len(result.get("files") or []))
        self.emit(
            "land",
            {
                "files": result.get("files") or [],
                "deleted": result.get("deleted") or [],
                "noop": False,
                "verify": cmd,
                "output": clip_output(out),
                "acceptance": acc_rows,
                "acceptance_prose": accept.prose(rm),
                **self._maybe_autocommit(rm, state, args),
                **self._state_backup_payload(),
            },
        )
        self._write_last_stand_best_effort()
        return OK

    def cmd_rollback(self, args: list[str]) -> int:
        try:
            st, _, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("rollback", str(e))
            return USAGE
        what = args[0] if args else "last"
        if what != "last":
            self.emit_err("rollback", "only 'last' is supported")
            return UNSUPPORTED
        if not state.last_checkpoint:
            self.emit_err("rollback", "no checkpoint")
            return USAGE
        cp = state.last_checkpoint
        target = state.worktree or self.root
        backup_dir = str(Path(self.root) / ".rfg" / "rollback-backup" / cp.id)
        backed_up: list[str] = []
        try:
            backed_up = gitops.backup_untracked(target, backup_dir)
        except Exception:
            backed_up = []
        try:
            gitops.reset_hard(target, cp.commit)
        except RuntimeError as e:
            try:
                backed_up = gitops.backup_untracked(self.root, backup_dir) or backed_up
            except Exception:
                pass
            try:
                gitops.reset_hard(self.root, cp.commit)
                target = self.root
            except RuntimeError:
                self.emit_err("rollback", str(e))
                return CONFLICT
        state.applied = [a for a in state.applied if a != cp.step_id]
        state.verified = [a for a in state.verified if a != cp.step_id]
        state.failed = [a for a in state.failed if a != cp.step_id]
        state.last_checkpoint = None
        st.write_state(state)
        audit.record(self.root, "rollback", step=cp.step_id, commit=cp.commit)
        payload = {"checkpoint": cp.id, "commit": cp.commit, "step": cp.step_id, "target": target}
        if backed_up:
            payload["untracked_backed_up"] = backed_up[:20]
            payload["untracked_backup_dir"] = backup_dir
            payload["warning"] = f"untracked worktree files backed up to {backup_dir} before reset --hard"
        self.emit("rollback", payload)
        return OK

    def cmd_backup(self, args: list[str]) -> int:
        """List roadmap/state backups (newest sorts last). Never fails."""
        rfg = Path(self.root) / ".rfg" / gitops.LAND_BACKUP_DIR
        try:
            backups = sorted(p.name for p in rfg.iterdir() if p.is_dir()) if rfg.is_dir() else []
        except OSError:
            backups = []
        self.emit("backup", {"backups": backups})
        return OK

    def cmd_restore(self, args: list[str]) -> int:
        """Restore roadmap.yaml+state.json from a backup id.

        `restore --dry-run <id>` only shows what would change (per-file
        would_change plus sizes, manifest status) and writes nothing.
        Exit 4 on unknown/unreadable/corrupt backups (won't guess): pick
        an id from `rfg backup` first.
        """
        dry = "--dry-run" in (args or []) or bool(getattr(self, "dry", False))
        bid = next((a for a in (args or []) if not a.startswith("-")), "")
        if not bid:
            self.emit_err("restore", "usage: rfg restore [--dry-run] <id> (see rfg backup)")
            return USAGE
        if dry:
            try:
                preview = gitops.diff_roadmap_state(self.root, bid)
            except OSError as e:
                self.emit_err("restore", str(e))
                return UNSUPPORTED
            self.emit("restore", preview)
            return OK
        try:
            restored = gitops.restore_roadmap_state(self.root, bid)
        except OSError as e:
            self.emit_err("restore", str(e))
            return UNSUPPORTED
        audit.record(self.root, "restore", step=bid)
        self.emit("restore", restored)
        return OK

    def cmd_claim(self, args: list[str]) -> int:
        try:
            st, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("claim", str(e))
            return USAGE
        agent = current_agent()
        sid = dag.next_id(rm, state)
        i = 0
        while i < len(args):
            if args[i] == "--agent" and i + 1 < len(args):
                agent = args[i + 1]
                i += 2
                continue
            if not args[i].startswith("-"):
                sid = args[i]
            i += 1
        if not sid:
            self.emit_err("claim", "no free step")
            return USAGE
        if not same_claim_client(state, agent):
            self.emit_err(
                "claim",
                f"conflict: held by {state.claim_agent}",
                claim_held_payload(state),
            )
            return CONFLICT
        state.claim_step = sid
        if agent:
            state.claim_agent = agent
        elif not state.claim_agent:
            state.claim_agent = "agent"
        st.write_state(state)
        audit.record(self.root, "claim", step=sid, agent=agent)
        self.emit("claim", {"step": sid, "agent": agent})
        return OK

    def cmd_release(self, args: list[str]) -> int:
        try:
            st, _, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("release", str(e))
            return USAGE
        prev = {"step": state.claim_step, "agent": state.claim_agent}
        state.claim_step = ""
        state.claim_agent = ""
        st.write_state(state)
        audit.record(self.root, "release", **prev)
        self.emit("release", prev)
        return OK

    def cmd_baseline(self, args: list[str]) -> int:
        try:
            _, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("baseline", str(e))
            return USAGE
        ora = next((o for o in rm.oracles if o.kind == "perf" and o.command), None)
        cmd = (ora.command if ora else "") or rm.verify
        if is_trivial(cmd):
            self.emit_err("baseline", "unsupported: no perf oracle command")
            return UNSUPPORTED
        directory = state.worktree or self.root
        try:
            data = oramod.capture_baseline(directory, cmd, store_root=self.root)
        except ValueError as e:
            self.emit_err("baseline", str(e))
            return UNSUPPORTED
        except RuntimeError as e:
            self.emit_err("baseline", str(e))
            return VERIFY_FAIL
        audit.record(self.root, "baseline", metric=data.get("metric"))
        self.emit("baseline", data)
        return OK

    def cmd_repro(self, args: list[str]) -> int:
        try:
            _, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("repro", str(e))
            return USAGE
        ora = next((o for o in rm.oracles if o.kind == "debug" and o.command), None)
        cmd = (ora.command if ora else "") or rm.verify
        if is_trivial(cmd):
            self.emit_err("repro", "unsupported: no debug oracle command")
            return UNSUPPORTED
        directory = state.worktree or self.root
        code, out = oramod.run_debug(directory, cmd)
        audit.record(self.root, "repro", code=code)
        self.emit("repro", {"command": cmd, "output": out, "log": str(Path(directory) / ".rfg" / "repro.log")})
        if code == 4:
            return UNSUPPORTED
        return OK if code == 0 else VERIFY_FAIL

    def cmd_progress(self, args: list[str]) -> int:
        try:
            _, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("progress", str(e))
            return USAGE
        data = progress.report(self.root, rm, state)
        epic = _parse_epic_arg(args)
        if epic:
            from rfg import scope as _scope

            data["epic"] = epic
            data["ready"] = [s for s in data.get("ready") or [] if _scope.epic_of(s) == epic]
            nxt = data.get("next")
            if nxt and _scope.epic_of(nxt) != epic:
                data["next"] = data["ready"][0] if data["ready"] else None
            w = _scope.unknown_epic_warning([s.id for s in rm.steps], epic)
            if w:
                data["warning"] = w
        self.emit("progress", data, ok=bool(data.get("ok")))
        return OK

    def cmd_digest(self, args: list[str]) -> int:
        try:
            _, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("digest", str(e))
            return USAGE
        data = progress.write_digest(self.root, rm, state)
        audit.record(self.root, "digest", exceptions=len(data.get("exceptions") or []))
        from rfg import tokens as _tokens

        data = _tokens.cap_data(data, _tokens.parse_max_chars(args))
        self.emit("digest", data, ok=bool(data.get("ok")))
        return OK

    def cmd_audit(self, args: list[str]) -> int:
        limit = 50
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                limit = 50
        rows = audit.read(self.root, limit=limit)
        self.emit("audit", {"events": rows})
        return OK

    def cmd_why(self, args: list[str]) -> int:
        try:
            _, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("why", str(e))
            return USAGE
        s = dag.compute(rm, state)
        sid = s["next"] or ""
        if args:
            sid = args[0]
        found = next((x for x in s["steps"] if x["id"] == sid), None)
        reason = "unknown step"
        status = ""
        if found:
            status = found["status"]
            reason = {
                "ready": "all dependencies are done; this is the next free step",
                "claimed": "claimed; tick or edit path then apply",
                "in_progress": "in progress; edit path then apply",
                "blocked": "waiting on: " + ", ".join(found.get("depends_on") or []),
                "applied": "already applied; run verify",
                "implemented": "files present; run verify",
                "verified": "already verified",
                "failed": "verify failed; rollback or fix",
            }.get(status, status)
        self.emit("why", {"step": sid, "status": status, "reason": reason})
        return OK

    def cmd_impact(self, args: list[str]) -> int:
        query = ""
        hyp_id = ""
        try:
            _, rm, _ = self.load()
            query = rm.hypothesis.symbol or rm.hypothesis.from_pat
            hyp_id = rm.hypothesis.id
        except FileNotFoundError:
            pass
        i = 0
        while i < len(args):
            if args[i] == "--symbol" and i + 1 < len(args):
                query = args[i + 1]
                i += 2
                continue
            if args[i] == "--max-chars" and i + 1 < len(args):
                i += 2
                continue
            if not args[i].startswith("-"):
                query = args[i]
            i += 1
        want_lsp = "--lsp" in args
        want_files = "--files" in args
        langs = index.discover_all(self.root)
        if not langs:
            self.emit_err("impact", "unsupported workspace (need go.mod, package.json, or Python project)")
            return UNSUPPORTED
        if want_lsp:
            from rfg import lsp

            if not any(lsp.references_available(x) for x in langs):
                self.emit_err("impact", "unsupported: no LSP (gopls/tsserver/pyright) on PATH")
                return UNSUPPORTED
        rep = index.impact(self.root, query)
        rep["hypothesis_id"] = hyp_id
        rep["languages"] = langs
        files = list(rep.get("files") or [])
        rep["files_total"] = len(files)
        if not want_files:
            rep["files"] = []
            if files:
                rep["files_omitted"] = len(files)
        from rfg import tokens as _tokens

        rep = _tokens.cap_data(rep, _tokens.parse_max_chars(args))
        self.emit("impact", rep)
        return OK

    def cmd_index(self, args: list[str]) -> int:
        data = index.build_index(self.root)
        self.emit("index", data.get("stats") or data)
        return OK

    def cmd_import_scip(self, args: list[str]) -> int:
        if not args:
            self.emit_err("import-scip", "need path to SCIP JSON")
            return USAGE
        if args[0].startswith("http://") or args[0].startswith("https://"):
            if telemetry.offline() or True:
                self.emit_err("import-scip", "unsupported: remote SCIP URL (offline; pass a local file)")
                return UNSUPPORTED
        p = Path(args[0])
        if not p.is_file():
            self.emit_err("import-scip", f"not found: {p}")
            return USAGE
        scip = json.loads(p.read_text(encoding="utf-8"))
        idx = index.merge_scip(self.root, scip)
        self.emit("import-scip", {"occurrences": len(idx.get("scip") or [])})
        return OK

    def cmd_mcp(self, args: list[str]) -> int:
        from rfg.mcp import serve

        serve(root=self.root)
        return OK

    def cmd_edges(self, args: list[str]) -> int:
        found = edges.scan(self.root)
        self.emit("edges", {"edges": found, "complete": False})
        return OK

    def _security_cmd(self) -> str:
        try:
            _, rm, _ = self.load()
        except FileNotFoundError:
            return ""
        for o in rm.oracles:
            if o.kind == "security" and o.command:
                return o.command
        return rm.verify if rm.goal.profile == "security" else ""

    def cmd_scan(self, args: list[str]) -> int:
        # scan --parse FILE [--tool NAME]: parse stored scanner JSON (no binary
        # needed; oracle- and test-friendly). Exit 2 on high/critical findings.
        if "--parse" in args:
            try:
                fpath = args[args.index("--parse") + 1]
            except IndexError:
                self.emit_err("scan", "need file after --parse")
                return USAGE
            tool = ""
            if "--tool" in args:
                try:
                    tool = args[args.index("--tool") + 1]
                except IndexError:
                    tool = ""
            p = Path(fpath)
            if not p.is_file():
                p = Path(self.root) / fpath
            try:
                text = p.read_text(encoding="utf-8")
            except OSError as e:
                self.emit_err("scan", f"not found: {fpath} ({e})")
                return USAGE
            findings = security.parse_scanner_output(text, tool)
            summary = security.summarize_findings(findings)
            sarif = security.write_sarif(self.root, findings, tool or "scan")
            audit.record(self.root, "scan", code=2 if summary["blocking"] else 0)
            from rfg import tokens as _tokens

            payload = _tokens.cap_data(
                {"ran": True, "mode": "parse", "tool": tool or "auto",
                 "findings": findings, "summary": summary, "sarif": str(sarif)},
                _tokens.parse_max_chars(args),
            )
            self.emit("scan", payload)
            if summary["blocking"]:
                self.emit_err("scan", f"blocking findings: {summary['blocking']} high/critical")
                return VERIFY_FAIL
            return OK
        cmd = self._security_cmd()
        present = security.scanners_present()
        if cmd and not is_trivial(cmd):
            code, out = run_verify(self.root, cmd, "security")
            audit.record(self.root, "scan", code=code)
            self.emit("scan", {"ran": True, "command": cmd, "output": out, "present": present})
            if code == 4:
                return UNSUPPORTED
            return OK if code == 0 else VERIFY_FAIL
        if not present:
            self.emit_err("scan", "unsupported: no scanner on PATH and no security oracle command")
            return UNSUPPORTED
        tool = present[0]
        code, out = security.run_scanner_json(self.root, tool)
        if code == 4:
            self.emit("scan", {"ran": False, "present": present, "command": ""})
            return OK
        findings = security.parse_scanner_output(out, tool)
        summary = security.summarize_findings(findings)
        sarif = security.write_sarif(self.root, findings, tool)
        audit.record(self.root, "scan", code=2 if summary["blocking"] else 0)
        from rfg import tokens as _tokens

        payload = _tokens.cap_data(
            {"ran": True, "mode": "run", "tool": tool,
             "findings": findings, "summary": summary, "sarif": str(sarif)},
            _tokens.parse_max_chars(args),
        )
        self.emit("scan", payload)
        if summary["blocking"]:
            self.emit_err("scan", f"blocking findings: {summary['blocking']} high/critical")
            return VERIFY_FAIL
        return OK

    def cmd_fuzz(self, args: list[str]) -> int:
        present = security.fuzzers_present()
        seconds = security.FUZZ_DEFAULT_SECONDS
        if "--seconds" in args:
            try:
                seconds = int(args[args.index("--seconds") + 1])
            except (IndexError, ValueError):
                seconds = security.FUZZ_DEFAULT_SECONDS
        target = ""
        if "--target" in args:
            try:
                target = args[args.index("--target") + 1]
            except IndexError:
                target = ""
        cmd = ""
        try:
            _, rm, _ = self.load()
            for o in rm.oracles:
                if o.kind == "security" and "fuzz" in (o.command or "").lower():
                    cmd = o.command
                    break
        except FileNotFoundError:
            pass
        if not cmd or is_trivial(cmd):
            cmd = security.fuzz_command(present, seconds, target)
        if cmd and not is_trivial(cmd):
            try:
                timeout = float(os.environ.get("RFG_VERIFY_TIMEOUT") or max(60, seconds + 30))
            except ValueError:
                timeout = max(60, seconds + 30)
            code, out = run_verify(self.root, cmd, "security", timeout=timeout)
            self.emit("fuzz", {"ran": True, "command": cmd, "output": out, "present": present,
                               "seconds": seconds})
            return OK if code == 0 else (UNSUPPORTED if code == 4 else VERIFY_FAIL)
        if not present:
            self.emit_err("fuzz", "unsupported: no fuzzer on PATH and no fuzz command")
            return UNSUPPORTED
        self.emit("fuzz", {"ran": False, "present": present})
        return OK

    def cmd_sbom(self, args: list[str]) -> int:
        path, data = security.write_sbom(self.root)
        audit.record(self.root, "sbom", components=len(data.get("components") or []))
        from rfg import tokens as _tokens

        # file on disk stays complete; only the emitted list is budgeted
        payload = _tokens.cap_data(
            {"path": str(path), "count": len(data.get("components") or []),
             "components": data["components"]},
            _tokens.parse_max_chars(args),
        )
        self.emit("sbom", payload)
        return OK

    def cmd_boundaries(self, args: list[str]) -> int:
        found = security.boundaries(self.root)
        self.emit("boundaries", {"boundaries": found, "complete": False})
        return OK

    def cmd_fleet(self, args: list[str]) -> int:
        what = args[0] if args else "status"
        if what == "next":
            data = fleet.next_step(self.root)
            audit.record(self.root, "fleet", action="next", repo=data.get("repo") or "")
            self.emit("fleet", data)
            return OK
        if what not in ("status",):
            self.emit_err("fleet", "unsupported: fleet status|next")
            return UNSUPPORTED
        from rfg import tokens as _tokens

        if "--full" in args:
            data = fleet.collect(self.root)
        else:
            data = fleet.summary(self.root)
        data = _tokens.cap_data(data, _tokens.parse_max_chars(args))
        audit.record(self.root, "fleet", repos=len(data.get("repos") or []))
        self.emit("fleet", data)
        return OK if data.get("ok") else VERIFY_FAIL

    def cmd_export(self, args: list[str]) -> int:
        what = args[0] if args else "batch"
        if what == "dashboard":
            try:
                _, rm, state = self.load()
            except FileNotFoundError as e:
                self.emit_err("export", str(e))
                return USAGE
            data = progress.write_dashboard(self.root, rm, state)
            audit.record(self.root, "export", kind="dashboard")
            from rfg import tokens as _tokens

            data = _tokens.cap_data(data, _tokens.parse_max_chars(args))
            self.emit("export", data)
            return OK
        if what != "batch":
            self.emit_err("export", "unsupported: export batch|dashboard")
            return UNSUPPORTED
        try:
            path, text = fleet.export_batch(self.root)
        except FileNotFoundError as e:
            self.emit_err("export", str(e))
            return USAGE
        audit.record(self.root, "export", kind="batch")
        from rfg import tokens as _tokens

        try:
            _, _rm, _ = self.load()
            step_ids = [s.id for s in _rm.steps]
        except FileNotFoundError:
            step_ids = []
        capped = _tokens.cap_data(
            {"kind": "batch", "path": str(path), "lines": text.count("\n") + 1,
             "steps": step_ids, "text": text},
            _tokens.parse_max_chars(args),
        )
        self.emit("export", capped)
        return OK

    def cmd_recipe(self, args: list[str]) -> int:
        action = args[0] if args else "list"
        if action == "list":
            self.emit("recipe", {"recipes": recipes.list_recipes(self.root)})
            return OK
        if action in ("show", "apply") and len(args) < 2:
            self.emit_err("recipe", "need recipe id")
            return USAGE
        name = args[1] if len(args) > 1 else ""
        if action == "apply" and name == "feature-campaign":
            goal = ""
            profile = "feature"
            camp: list[dict] = []
            i = 2
            while i < len(args):
                if args[i] == "--goal" and i + 1 < len(args):
                    goal = args[i + 1]
                    i += 2
                    continue
                if args[i] == "--profile" and i + 1 < len(args):
                    profile = args[i + 1]
                    i += 2
                    continue
                if args[i] == "--step" and i + 1 < len(args):
                    parts = args[i + 1].split(":", 2)
                    row: dict = {"id": parts[0], "engine": "implement"}
                    if len(parts) > 1:
                        row["path"] = [p for p in parts[1].split(",") if p]
                    if len(parts) > 2:
                        row["verify"] = parts[2]
                    camp.append(row)
                    i += 2
                    continue
                if args[i] == "--depends" and i + 1 < len(args):
                    a, _, b = args[i + 1].partition(":")
                    for row in camp:
                        if row.get("id") == a and b:
                            row.setdefault("depends", [])
                            if isinstance(row["depends"], str):
                                row["depends"] = coerce_depends_list(row["depends"])
                            for dep in coerce_depends_list(b):
                                if dep and dep not in row["depends"]:
                                    row["depends"].append(dep)
                    i += 2
                    continue
                if args[i] == "--want" and i + 1 < len(args) and camp:
                    camp[-1]["want"] = args[i + 1]
                    i += 2
                    continue
                i += 1
            rec = recipes.campaign_recipe(goal, camp, profile=profile)
            st = Store(self.root)
            try:
                rm = st.load_roadmap()
            except FileNotFoundError:
                rm = default_roadmap(self.root)
            if goal:
                rm.goal.statement = goal
                rm.goal.profile = profile
            rm = recipes.apply_recipe(rm, rec)
            st.save_roadmap(rm)
            if not st.state_path.is_file():
                st.write_state(st.load_state())
            audit.record(self.root, "recipe", id=name)
            self.emit("recipe", {"applied": name, "steps": [s.id for s in rm.steps], "goal": rm.goal.statement})
            return OK
        try:
            rec = recipes.load(name, self.root)
        except FileNotFoundError as e:
            self.emit_err("recipe", str(e))
            return USAGE
        if action == "show":
            self.emit("recipe", {"id": name, "steps": [s.id for s in rec.steps], "goal": rec.goal.statement})
            return OK
        if action == "apply":
            mapping: dict[str, str] = {}
            i = 2
            while i < len(args):
                if args[i] in ("--from", "--to", "--symbol", "--path", "--verify", "--goal") and i + 1 < len(args):
                    key = {
                        "--from": "from",
                        "--to": "to",
                        "--symbol": "symbol",
                        "--path": "path",
                        "--verify": "verify",
                        "--goal": "goal",
                    }[args[i]]
                    mapping[key] = args[i + 1]
                    i += 2
                    continue
                i += 1
            rec = recipes.substitute(rec, mapping)
            if mapping.get("goal"):
                rec.goal.statement = mapping["goal"]
            st = Store(self.root)
            try:
                rm = st.load_roadmap()
            except FileNotFoundError:
                rm = default_roadmap()
            rm = recipes.apply_recipe(rm, rec)
            st.save_roadmap(rm)
            if not st.state_path.is_file():
                st.write_state(st.load_state())
            audit.record(self.root, "recipe", id=name)
            self.emit("recipe", {"applied": name, "steps": [s.id for s in rm.steps]})
            return OK
        self.emit_err("recipe", "unsupported: recipe list|show|apply")
        return UNSUPPORTED

    def cmd_packs(self, args: list[str]) -> int:
        if args and args[0] == "enable":
            name = args[1] if len(args) > 1 else ""
            kind, allowed = fleet.pack_info(name)
            if not allowed:
                self.emit_err("packs", f"unsupported: pack {name or '?'} is {kind or 'unknown'} (not in this tree)")
                return UNSUPPORTED
            self.emit("packs", {"enabled": name, "kind": kind})
            return OK
        self.emit(
            "packs",
            {"open": list(fleet.OPEN_PACKS), "paid": list(fleet.PAID_PACKS)},
        )
        return OK

    def cmd_migrate(self, args: list[str]) -> int:
        from rfg.schemaver import migrate_roadmap, needs_migrate

        try:
            st, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("migrate", str(e))
            return USAGE
        before = rm.version
        if not needs_migrate(rm):
            self.emit("migrate", {"from": before, "to": rm.version, "changed": False})
            return OK
        rm = migrate_roadmap(rm)
        st.save_roadmap(rm)
        self.emit("migrate", {"from": before, "to": rm.version, "changed": True})
        return OK

    def cmd_doctor(self, args: list[str]) -> int:
        from rfg.doctor import run as doctor_run

        verbose = "--verbose" in (args or [])
        report = doctor_run(self.root, verbose=verbose)
        self.emit("doctor", report)
        return OK if report["ok"] else USAGE

    def cmd_completion(self, args: list[str]) -> int:
        from rfg.complete import render

        shell = args[0] if args else "bash"
        try:
            text = render(shell)
        except ValueError as e:
            self.emit_err("completion", str(e))
            return USAGE
        if self.json:
            self.emit("completion", {"shell": shell, "script": text})
        else:
            print(text, end="" if text.endswith("\n") else "\n")
        return OK

    def cmd_man(self, args: list[str]) -> int:
        from rfg.manpage import text as man_text

        body = man_text()
        if self.json:
            self.emit("man", {"text": body})
        else:
            print(body, end="" if body.endswith("\n") else "\n")
        return OK

    def cmd_version(self, args: list[str]) -> int:
        self.emit("version", {"version": __version__, "schema": SCHEMA_VERSION})
        return OK


def parse_args(argv: list[str]):
    json_out = False
    root = ""
    dry = False
    show_diff = False
    show_risk = False
    filtered: list[str] = []
    help_flag = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--format" and i + 1 < len(argv) and argv[i + 1] == "json":
            json_out = True
            i += 2
            continue
        if a in ("--format=json", "--json"):
            json_out = True
            i += 1
            continue
        if a.startswith("--format=") and a.split("=", 1)[1] == "json":
            json_out = True
            i += 1
            continue
        if a == "--dry-run":
            dry = True
            i += 1
            continue
        if a == "--diff":
            show_diff = True
            i += 1
            continue
        if a == "--show-risk":
            show_risk = True
            i += 1
            continue
        if a == "--root" and i + 1 < len(argv):
            # QM-05: hard --allow-external-root (exit 4) is deferred until
            # gotoharness clients send the flag. Until then --root outside
            # cwd stays allowed; doctor warns. FAIL: Guard lands uncoordinated.
            root = argv[i + 1]
            i += 2
            continue
        if a.startswith("--root="):
            root = a.split("=", 1)[1]
            i += 1
            continue
        if a in ("-h", "--help"):
            help_flag = True
            i += 1
            continue
        filtered.append(a)
        i += 1
    if not root:
        root = str(Path.cwd())
    if not filtered:
        return "help", [], help_flag, json_out, dry, root, show_diff, show_risk
    return filtered[0], filtered[1:], help_flag, json_out, dry, root, show_diff, show_risk


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd, rest, help_flag, json_out, dry, root, show_diff, show_risk = parse_args(argv)
    if cmd == "help" or not cmd:
        print(HELP)
        return OK
    if help_flag:
        print(COMMAND_HELP.get(cmd, HELP))
        return OK
    c = CLI(root, json_out, dry, show_diff, show_risk=show_risk)
    mapping = {
        "init": lambda: c.cmd_init(rest),
        "status": lambda: c.cmd_status(rest),
        "resume": lambda: c.cmd_resume(),
        "plan": lambda: c.cmd_plan(rest),
        "next": lambda: c.cmd_next(rest),
        "context": lambda: c.cmd_context(rest),
        "tick": lambda: c.cmd_tick(rest),
        "apply": lambda: c.cmd_apply(rest),
        "verify": lambda: c.cmd_verify(rest),
        "land": lambda: c.cmd_land(rest),
        "rollback": lambda: c.cmd_rollback(rest),
        "backup": lambda: c.cmd_backup(rest),
        "restore": lambda: c.cmd_restore(rest),
        "claim": lambda: c.cmd_claim(rest),
        "release": lambda: c.cmd_release(rest),
        "audit": lambda: c.cmd_audit(rest),
        "baseline": lambda: c.cmd_baseline(rest),
        "repro": lambda: c.cmd_repro(rest),
        "progress": lambda: c.cmd_progress(rest),
        "digest": lambda: c.cmd_digest(rest),
        "why": lambda: c.cmd_why(rest),
        "impact": lambda: c.cmd_impact(rest),
        "index": lambda: c.cmd_index(rest),
        "import-scip": lambda: c.cmd_import_scip(rest),
        "mcp": lambda: c.cmd_mcp(rest),
        "edges": lambda: c.cmd_edges(rest),
        "scan": lambda: c.cmd_scan(rest),
        "fuzz": lambda: c.cmd_fuzz(rest),
        "sbom": lambda: c.cmd_sbom(rest),
        "boundaries": lambda: c.cmd_boundaries(rest),
        "fleet": lambda: c.cmd_fleet(rest),
        "export": lambda: c.cmd_export(rest),
        "recipe": lambda: c.cmd_recipe(rest),
        "packs": lambda: c.cmd_packs(rest),
        "migrate": lambda: c.cmd_migrate(rest),
        "doctor": lambda: c.cmd_doctor(rest),
        "completion": lambda: c.cmd_completion(rest),
        "man": lambda: c.cmd_man(rest),
        "version": lambda: c.cmd_version(rest),
    }
    fn = mapping.get(cmd)
    if not fn:
        c.emit_err(cmd, "unknown command: " + cmd)
        return USAGE
    return fn()


if __name__ == "__main__":
    raise SystemExit(main())
