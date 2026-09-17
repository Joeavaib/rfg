from __future__ import annotations

from rfg.types import Budget, Goal, Hypothesis, Oracle, Replace, Roadmap, Step


def _q(s: str) -> str:
    if s == "":
        return '""'
    if any(c in s for c in ':#"\'\n') or s.startswith(" "):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def marshal_roadmap(r: Roadmap) -> str:
    lines = [f"version: {r.version}", f"id: {_q(r.id)}", "hypothesis:"]
    h = r.hypothesis
    lines.append(f"  id: {_q(h.id)}")
    lines.append(f"  statement: {_q(h.statement)}")
    if h.symbol:
        lines.append(f"  symbol: {_q(h.symbol)}")
    if h.from_pat:
        lines.append(f"  from: {_q(h.from_pat)}")
    if h.to:
        lines.append(f"  to: {_q(h.to)}")
    g = r.goal
    if g.statement or g.acceptance or g.profile:
        lines.append("goal:")
        lines.append(f"  id: {_q(g.id)}")
        lines.append(f"  statement: {_q(g.statement)}")
        if g.profile:
            lines.append(f"  profile: {_q(g.profile)}")
        if g.acceptance:
            lines.append("  acceptance:")
            for a in g.acceptance:
                lines.append(f"    - {_q(a)}")
    if r.budget.max_applies:
        lines.append("budget:")
        lines.append(f"  max_applies: {r.budget.max_applies}")
    if r.verify:
        lines.append(f"verify: {_q(r.verify)}")
    if r.oracles:
        lines.append("oracles:")
        for o in r.oracles:
            lines.append(f"  - kind: {_q(o.kind)}")
            if o.command:
                lines.append(f"    command: {_q(o.command)}")
            if o.max_ms:
                lines.append(f"    max_ms: {o.max_ms}")
            if o.max_ratio:
                lines.append(f"    max_ratio: {o.max_ratio}")
    lines.append("steps:")
    for s in r.steps:
        lines.append(f"  - id: {_q(s.id)}")
        lines.append(f"    title: {_q(s.title)}")
        if s.depends_on:
            lines.append("    depends_on:")
            for d in s.depends_on:
                lines.append(f"      - {_q(d)}")
        if s.replace and (s.replace.from_pat or s.replace.to):
            lines.append("    replace:")
            lines.append(f"      from: {_q(s.replace.from_pat)}")
            lines.append(f"      to: {_q(s.replace.to)}")
            if s.replace.paths:
                lines.append("      paths:")
                for p in s.replace.paths:
                    lines.append(f"        - {_q(p)}")
        elif s.paths or (s.replace and s.replace.paths):
            lines.append("    paths:")
            for p in s.paths or s.replace.paths:
                lines.append(f"      - {_q(p)}")
        if s.verify:
            lines.append(f"    verify: {_q(s.verify)}")
        if s.oracle and s.oracle != "test":
            lines.append(f"    oracle: {_q(s.oracle)}")
        if s.engine:
            lines.append(f"    engine: {_q(s.engine)}")
        want = s.want or s.goal
        if want:
            lines.append(f"    want: {_q(want)}")
        if s.extras:
            lines.append("    extras:")
            for p in s.extras:
                lines.append(f"      - {_q(p)}")
        if s.diff_budget:
            lines.append(f"    diff_budget: {s.diff_budget}")
        if s.edge:
            lines.append(f"    edge: {_q(s.edge)}")
    return "\n".join(lines) + "\n"


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1].replace('\\"', '"')
    return s


def _split_kv(s: str) -> tuple[str, str] | None:
    i = s.find(":")
    if i < 0:
        return None
    return s[:i].strip(), s[i + 1 :].strip()


def unmarshal_roadmap(text: str) -> Roadmap:
    r = Roadmap(hypothesis=Hypothesis(), steps=[])
    section = ""
    cur: Step | None = None
    cur_oracle: Oracle | None = None
    in_replace = in_paths = in_depends = in_accept = in_step_paths = in_extras = False

    def flush() -> None:
        nonlocal cur, in_replace, in_paths, in_depends, in_step_paths, in_extras
        if cur is not None:
            r.steps.append(cur)
            cur = None
        in_replace = in_paths = in_depends = in_step_paths = in_extras = False

    def flush_oracle() -> None:
        nonlocal cur_oracle
        if cur_oracle is not None:
            r.oracles.append(cur_oracle)
            cur_oracle = None

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        trim = line.strip()

        if indent == 0:
            flush()
            flush_oracle()
            kv = _split_kv(trim)
            if kv is None:
                continue
            key, val = kv
            section = key
            in_accept = False
            if key == "version":
                r.version = int(val or 0)
            elif key == "id":
                r.id = _unquote(val)
            elif key == "verify":
                r.verify = _unquote(val)
            continue

        if section == "budget":
            kv = _split_kv(trim)
            if kv and kv[0] == "max_applies":
                try:
                    r.budget = Budget(max_applies=int(kv[1] or 0))
                except ValueError:
                    r.budget = Budget()
            continue

        if section == "hypothesis":
            kv = _split_kv(trim)
            if not kv:
                continue
            key, val = kv
            val = _unquote(val)
            if key == "id":
                r.hypothesis.id = val
            elif key == "statement":
                r.hypothesis.statement = val
            elif key == "symbol":
                r.hypothesis.symbol = val
            elif key == "from":
                r.hypothesis.from_pat = val
            elif key == "to":
                r.hypothesis.to = val
            continue

        if section == "goal":
            if indent == 2:
                kv = _split_kv(trim)
                if not kv:
                    continue
                key, val = kv
                if key == "acceptance":
                    in_accept = True
                    continue
                in_accept = False
                val = _unquote(val)
                if key == "id":
                    r.goal.id = val
                elif key == "statement":
                    r.goal.statement = val
                elif key == "profile":
                    r.goal.profile = val
            elif in_accept and trim.startswith("- "):
                r.goal.acceptance.append(_unquote(trim[2:]))
            continue

        if section == "oracles":
            if indent == 2 and trim.startswith("- "):
                flush_oracle()
                cur_oracle = Oracle()
                rest = trim[2:]
                kv = _split_kv(rest)
                if kv and kv[0] == "kind":
                    cur_oracle.kind = _unquote(kv[1])
                continue
            if cur_oracle is None:
                continue
            kv = _split_kv(trim)
            if kv and kv[0] == "command":
                cur_oracle.command = _unquote(kv[1])
            elif kv and kv[0] == "kind":
                cur_oracle.kind = _unquote(kv[1])
            elif kv and kv[0] == "max_ms":
                try:
                    cur_oracle.max_ms = float(kv[1] or 0)
                except ValueError:
                    cur_oracle.max_ms = 0.0
            elif kv and kv[0] == "max_ratio":
                try:
                    cur_oracle.max_ratio = float(kv[1] or 0)
                except ValueError:
                    cur_oracle.max_ratio = 0.0
            continue

        if section == "steps":
            if indent == 2 and trim.startswith("- "):
                flush()
                cur = Step(id="")
                rest = trim[2:]
                kv = _split_kv(rest)
                if kv and kv[0] == "id":
                    cur.id = _unquote(kv[1])
                continue
            if cur is None:
                continue
            if indent == 4:
                kv = _split_kv(trim)
                if kv is None:
                    continue
                key, val = kv
                if key == "replace":
                    in_replace, in_depends, in_paths, in_step_paths, in_extras = True, False, False, False, False
                    cur.replace = cur.replace or Replace(from_pat="", to="")
                    continue
                if key == "depends_on":
                    in_depends, in_replace, in_paths, in_step_paths, in_extras = True, False, False, False, False
                    continue
                if key == "paths":
                    in_step_paths, in_replace, in_depends, in_paths, in_extras = True, False, False, False, False
                    continue
                if key == "extras":
                    in_extras, in_replace, in_depends, in_paths, in_step_paths = True, False, False, False, False
                    continue
                in_replace = in_depends = in_paths = in_step_paths = in_extras = False
                if key == "id":
                    cur.id = _unquote(val)
                elif key == "title":
                    cur.title = _unquote(val)
                elif key == "verify":
                    cur.verify = _unquote(val)
                elif key == "oracle":
                    cur.oracle = _unquote(val)
                elif key == "engine":
                    cur.engine = _unquote(val)
                elif key == "goal":
                    cur.goal = _unquote(val)
                    if not cur.want:
                        cur.want = cur.goal
                elif key == "want":
                    cur.want = _unquote(val)
                    if not cur.goal:
                        cur.goal = cur.want
                elif key == "diff_budget":
                    try:
                        cur.diff_budget = int(val or 0)
                    except ValueError:
                        cur.diff_budget = 0
                elif key == "edge":
                    cur.edge = _unquote(val)
                continue
            if indent == 6 and in_replace:
                kv = _split_kv(trim)
                if kv is None:
                    continue
                key, val = kv
                if key == "paths":
                    in_paths = True
                    continue
                if cur.replace is None:
                    cur.replace = Replace(from_pat="", to="")
                if key == "from":
                    cur.replace.from_pat = _unquote(val)
                elif key == "to":
                    cur.replace.to = _unquote(val)
                continue
            if indent >= 6 and in_depends and trim.startswith("- "):
                cur.depends_on.append(_unquote(trim[2:]))
                continue
            if indent >= 6 and in_step_paths and trim.startswith("- "):
                cur.paths.append(_unquote(trim[2:]))
                continue
            if indent >= 6 and in_extras and trim.startswith("- "):
                cur.extras.append(_unquote(trim[2:]))
                continue
            if indent >= 8 and in_paths and trim.startswith("- "):
                if cur.replace is None:
                    cur.replace = Replace(from_pat="", to="")
                cur.replace.paths.append(_unquote(trim[2:]))
    flush()
    flush_oracle()
    if not r.id:
        raise ValueError("roadmap missing id")
    return r
