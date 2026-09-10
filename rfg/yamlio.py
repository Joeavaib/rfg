from __future__ import annotations

from rfg.types import Hypothesis, Replace, Roadmap, Step


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
    if h.frm:
        lines.append(f"  from: {_q(h.frm)}")
    if h.to:
        lines.append(f"  to: {_q(h.to)}")
    if r.verify:
        lines.append(f"verify: {_q(r.verify)}")
    lines.append("steps:")
    for s in r.steps:
        lines.append(f"  - id: {_q(s.id)}")
        lines.append(f"    title: {_q(s.title)}")
        if s.depends_on:
            lines.append("    depends_on:")
            for d in s.depends_on:
                lines.append(f"      - {_q(d)}")
        if s.replace:
            lines.append("    replace:")
            lines.append(f"      from: {_q(s.replace.frm)}")
            lines.append(f"      to: {_q(s.replace.to)}")
            if s.replace.paths:
                lines.append("      paths:")
                for p in s.replace.paths:
                    lines.append(f"        - {_q(p)}")
        if s.verify:
            lines.append(f"    verify: {_q(s.verify)}")
        if s.engine:
            lines.append(f"    engine: {_q(s.engine)}")
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
    in_replace = in_paths = in_depends = False

    def flush() -> None:
        nonlocal cur, in_replace, in_paths, in_depends
        if cur is not None:
            r.steps.append(cur)
            cur = None
        in_replace = in_paths = in_depends = False

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        trim = line.strip()

        if indent == 0:
            flush()
            kv = _split_kv(trim)
            if kv is None:
                continue
            key, val = kv
            section = key
            if key == "version":
                r.version = int(val or 0)
            elif key == "id":
                r.id = _unquote(val)
            elif key == "verify":
                r.verify = _unquote(val)
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
                r.hypothesis.frm = val
            elif key == "to":
                r.hypothesis.to = val
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
                    in_replace, in_depends, in_paths = True, False, False
                    cur.replace = cur.replace or Replace(frm="", to="")
                    continue
                if key == "depends_on":
                    in_depends, in_replace, in_paths = True, False, False
                    continue
                in_replace = in_depends = in_paths = False
                if key == "id":
                    cur.id = _unquote(val)
                elif key == "title":
                    cur.title = _unquote(val)
                elif key == "verify":
                    cur.verify = _unquote(val)
                elif key == "engine":
                    cur.engine = _unquote(val)
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
                    cur.replace = Replace(frm="", to="")
                if key == "from":
                    cur.replace.frm = _unquote(val)
                elif key == "to":
                    cur.replace.to = _unquote(val)
                continue
            if indent >= 6 and in_depends and trim.startswith("- "):
                cur.depends_on.append(_unquote(trim[2:]))
                continue
            if indent >= 8 and in_paths and trim.startswith("- "):
                if cur.replace is None:
                    cur.replace = Replace(frm="", to="")
                cur.replace.paths.append(_unquote(trim[2:]))
    flush()
    if not r.id:
        raise ValueError("roadmap missing id")
    return r
