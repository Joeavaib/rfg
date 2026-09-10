from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from rfg import SCHEMA_VERSION, __version__, apply as applymod
from rfg import caps, dag, edges, fmtutil, gitops, index, risk, telemetry
from rfg.store import Store
from rfg.types import Checkpoint, Hypothesis, Replace, Roadmap, Step
from rfg.verify import run as run_verify

OK, USAGE, VERIFY_FAIL, DIRTY, UNSUPPORTED, CONFLICT = 0, 1, 2, 3, 4, 5

HELP = """rfg — lead a multi-step refactor locally

Usage:
  rfg [--format json] [--root DIR] <command>

Commands:
  init                 create .rfg/roadmap.yaml and state
  status               show roadmap DAG and next free step
  plan                 write or update steps / hypothesis
  next                 print the next free step
  apply [--dry-run]    apply next (or given) step in a git worktree
  verify               run the verify command for the last applied step
  rollback last        restore the last checkpoint
  why                  explain why a step is ready/blocked
  impact [--symbol S]  file/import/export hit counts (index or SCIP)
  index                rebuild incremental file-hash index
  import-scip FILE     merge a SCIP JSON dump into the index
  mcp                  MCP stdio server (same operations as CLI)
  edges                list explicit cross-language edges (cgo, pyo3, napi, cxx-ffi)
  migrate              bump roadmap schema to current version
  doctor               check git, schema, languages, offline, formatters
  completion SHELL     print bash|zsh|fish completions
  man                  print the man page
  version              print rfg version

Exit codes:
  0 ok  2 verify fail  3 dirty  4 unsupported  5 conflict
"""


def default_roadmap() -> Roadmap:
    return Roadmap(
        version=SCHEMA_VERSION,
        id="roadmap-1",
        hypothesis=Hypothesis(
            id="h1",
            statement="Rename UserID string to typed ID",
            symbol="UserID",
            frm="UserID",
            to="UserIDTyped",
        ),
        verify="true",
        steps=[],
    )


class CLI:
    def __init__(self, root: str, json_out: bool, dry: bool) -> None:
        self.root = str(Path(root).resolve())
        self.json = json_out
        self.dry = dry

    def emit(self, command: str, data, diff: str | None = None, ok: bool = True, error: str | None = None) -> None:
        env = {"ok": ok, "command": command}
        if error:
            env["error"] = error
        if data is not None:
            env["data"] = data
        if diff is not None:
            env["diff"] = diff
        if self.json or True:
            text = json.dumps(env, indent=2)
            if self.json:
                print(text)
            else:
                if diff and command == "apply" and data and data.get("dry_run"):
                    print(diff, end="" if diff.endswith("\n") else "\n")
                else:
                    print(text)

    def emit_err(self, command: str, msg: str) -> None:
        if self.json:
            print(json.dumps({"ok": False, "command": command, "error": msg}, indent=2))
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
        st.init(default_roadmap())
        telemetry.record(self.root, "init")
        self.emit("init", {"roadmap": str(st.roadmap_path), "state": str(st.state_path)})
        return OK

    def cmd_status(self) -> int:
        try:
            _, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("status", str(e))
            return USAGE
        s = dag.compute(rm, state)
        if gitops.is_repo(self.root):
            s["dirty"] = gitops.dirty(self.root)
        self.emit("status", s)
        return OK

    def cmd_next(self) -> int:
        try:
            _, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("next", str(e))
            return USAGE
        self.emit("next", dag.compute(rm, state))
        return OK

    def cmd_plan(self, args: list[str]) -> int:
        st = Store(self.root)
        try:
            rm = st.load_roadmap()
        except FileNotFoundError:
            rm = default_roadmap()
        state = st.load_state()
        step = Step(id="")
        have = False
        i = 0
        while i < len(args):
            a = args[i]

            def val() -> str:
                nonlocal i
                if i + 1 < len(args):
                    i += 1
                    return args[i]
                return ""

            if a == "--step":
                step.id = val()
                have = True
            elif a == "--title":
                step.title = val()
                have = True
            elif a == "--from":
                if step.replace is None:
                    step.replace = Replace(frm="", to="")
                step.replace.frm = val()
                have = True
            elif a == "--to":
                if step.replace is None:
                    step.replace = Replace(frm="", to="")
                step.replace.to = val()
                have = True
            elif a == "--depends":
                d = val()
                step.depends_on = [x for x in d.split(",") if x]
            elif a == "--verify":
                v = val()
                if have:
                    step.verify = v
                else:
                    rm.verify = v
            elif a == "--hypothesis":
                rm.hypothesis.statement = val()
            elif a == "--symbol":
                rm.hypothesis.symbol = val()
                rm.hypothesis.frm = rm.hypothesis.symbol
            elif a == "--path":
                if step.replace is None:
                    step.replace = Replace(frm="", to="")
                step.replace.paths.append(val())
                have = True
            elif a == "--engine":
                step.engine = val()
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
            i += 1
        if have and step.id:
            found = False
            for idx, s in enumerate(rm.steps):
                if s.id == step.id:
                    if step.title:
                        s.title = step.title
                    if step.replace:
                        s.replace = step.replace
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
                    rm.steps[idx] = s
                    found = True
                    break
            if not found:
                if not step.title:
                    step.title = step.id
                rm.steps.append(step)
        st.save_roadmap(rm)
        if not st.state_path.is_file():
            st.write_state(state)
        self.emit("plan", dag.compute(rm, state))
        return OK

    def cmd_apply(self, args: list[str]) -> int:
        try:
            st, rm, state = self.load()
        except FileNotFoundError as e:
            self.emit_err("apply", str(e))
            return USAGE
        sid = dag.next_id(rm, state)
        for a in args:
            if a != "--dry-run" and not a.startswith("-"):
                sid = a
        if not sid:
            self.emit_err("apply", "no free step")
            return OK
        step = dag.step_by_id(rm, sid)
        if not step:
            self.emit_err("apply", "unknown step " + sid)
            return USAGE
        if step.engine and step.engine not in ("replace", "", "ast-grep", "manual"):
            self.emit_err("apply", "unsupported engine: " + step.engine)
            return UNSUPPORTED
        if step.engine == "ast-grep":
            from rfg import astgrep

            if not astgrep.available():
                self.emit_err("apply", "unsupported engine: ast-grep (binary not found)")
                return UNSUPPORTED
        edge_list = edges.scan(self.root)
        rels_preview = applymod.changed_rels(self.root, step) if step.replace else []
        macros = False
        for rel in rels_preview:
            if not rel.endswith(".rs"):
                continue
            try:
                txt = Path(self.root, rel).read_text(encoding="utf-8")
            except OSError:
                continue
            if caps.rust_has_macros(txt) or (step.replace and caps.looks_like_macro_use(step.replace.frm)):
                macros = True
        if step.replace and caps.looks_like_macro_use(step.replace.frm):
            macros = True
        cpp_touch = caps.cpp_paths(rels_preview) or (
            step.replace is not None and caps.cpp_paths(step.replace.paths)
        )
        cpp_no_db = cpp_touch and not caps.has_compile_commands(self.root)
        if macros and step.engine != "manual":
            self.emit_err("apply", "unsupported: rust macros (set engine: manual)")
            return UNSUPPORTED
        if cpp_no_db and step.engine != "manual":
            self.emit_err("apply", "unsupported: C++ apply without compile_commands.json")
            return UNSUPPORTED
        target = self.root
        if not self.dry:
            if not gitops.is_repo(self.root):
                self.emit_err("apply", "not a git repository")
                return USAGE
            if gitops.dirty(self.root) and not state.worktree:
                self.emit_err("apply", "working tree dirty")
                return DIRTY
            try:
                h = gitops.head(self.root)
                wt = gitops.ensure_worktree(self.root)
                target = str(wt)
                state.worktree = target
                try:
                    snap = gitops.snapshot(wt, "rfg checkpoint before " + sid)
                except RuntimeError:
                    snap = h
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
        if step.engine == "manual":
            diff, hits = "", 0
        else:
            try:
                if step.engine == "ast-grep":
                    from rfg import astgrep

                    diff, hits = astgrep.run(target, step, dry=True)
                else:
                    diff, hits = applymod.patch(target, step)
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
        rs = risk.score(
            step,
            hits=hits,
            diff_lines=lines,
            edges=edge_list,
            macros=macros,
            cpp_no_db=cpp_no_db,
        )
        if self.dry:
            self.emit(
                "apply",
                {
                    "step": sid,
                    "dry_run": True,
                    "hits": hits,
                    "diff": diff,
                    "risk": rs,
                    "manual": step.engine == "manual",
                    "edge": step.edge,
                },
                diff=diff,
            )
            return OK
        if step.engine == "manual":
            n = 0
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
        formatted = []
        if step.engine != "manual":
            changed = applymod.changed_rels(target, step) if step.replace else []
            formatted = fmtutil.format_paths(target, changed)
        dag.mark_applied(state, sid)
        st.write_state(state)
        self.emit(
            "apply",
            {
                "step": sid,
                "hits": n,
                "worktree": target,
                "diff": diff,
                "risk": rs,
                "format": formatted,
                "manual": step.engine == "manual",
                "edge": step.edge,
            },
        )
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
            self.emit_err("verify", "no applied step")
            return USAGE
        step = dag.step_by_id(rm, sid)
        if not step:
            self.emit_err("verify", "unknown step")
            return USAGE
        cmd = step.verify or rm.verify
        directory = state.worktree or self.root
        code, out = run_verify(directory, cmd)
        if code != 0:
            if sid not in state.failed:
                state.failed.append(sid)
            st.write_state(state)
            self.emit_err("verify", (out + " verify failed").strip())
            return VERIFY_FAIL
        if sid not in state.verified:
            state.verified.append(sid)
        st.write_state(state)
        self.emit("verify", {"step": sid, "command": cmd, "output": out})
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
        try:
            gitops.reset_hard(target, cp.commit)
        except RuntimeError as e:
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
        self.emit(
            "rollback",
            {"checkpoint": cp.id, "commit": cp.commit, "step": cp.step_id, "target": target},
        )
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
                "blocked": "waiting on: " + ", ".join(found["depends_on"]),
                "applied": "already applied; run verify",
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
            query = rm.hypothesis.symbol or rm.hypothesis.frm
            hyp_id = rm.hypothesis.id
        except FileNotFoundError:
            pass
        i = 0
        while i < len(args):
            if args[i] == "--symbol" and i + 1 < len(args):
                query = args[i + 1]
                i += 2
                continue
            if not args[i].startswith("-"):
                query = args[i]
            i += 1
        want_lsp = "--lsp" in args
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

        report = doctor_run(self.root)
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
    filtered: list[str] = []
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
        if a == "--root" and i + 1 < len(argv):
            root = argv[i + 1]
            i += 2
            continue
        if a.startswith("--root="):
            root = a.split("=", 1)[1]
            i += 1
            continue
        if a in ("-h", "--help"):
            return "help", [], True, json_out, dry, root
        filtered.append(a)
        i += 1
    if not root:
        root = str(Path.cwd())
    if not filtered:
        return "help", [], False, json_out, dry, root
    return filtered[0], filtered[1:], False, json_out, dry, root


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd, rest, help_flag, json_out, dry, root = parse_args(argv)
    if cmd == "help" or help_flag:
        print(HELP)
        return OK
    c = CLI(root, json_out, dry)
    mapping = {
        "init": lambda: c.cmd_init(rest),
        "status": c.cmd_status,
        "plan": lambda: c.cmd_plan(rest),
        "next": c.cmd_next,
        "apply": lambda: c.cmd_apply(rest),
        "verify": lambda: c.cmd_verify(rest),
        "rollback": lambda: c.cmd_rollback(rest),
        "why": lambda: c.cmd_why(rest),
        "impact": lambda: c.cmd_impact(rest),
        "index": lambda: c.cmd_index(rest),
        "import-scip": lambda: c.cmd_import_scip(rest),
        "mcp": lambda: c.cmd_mcp(rest),
        "edges": lambda: c.cmd_edges(rest),
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
