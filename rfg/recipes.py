from __future__ import annotations

from pathlib import Path

from rfg.types import Goal, Hypothesis, Roadmap, Step
from rfg.verify import is_fallback_verify
from rfg.yamlio import unmarshal_roadmap

PKG = Path(__file__).resolve().parent / "data" / "recipes"


def dirs(root: str | Path | None = None) -> list[Path]:
    out = [PKG]
    if root:
        extra = Path(root) / ".rfg" / "recipes"
        if extra.is_dir():
            out.append(extra)
    return out


def list_recipes(root: str | Path | None = None) -> list[dict]:
    found: dict[str, Path] = {}
    for d in dirs(root):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            found[p.stem] = p
    rows = []
    for name, path in sorted(found.items()):
        rm = unmarshal_roadmap(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "id": name,
                "path": str(path),
                "goal": rm.goal.statement,
                "profile": rm.goal.profile,
                "steps": [s.id for s in rm.steps],
            }
        )
    return rows


def load(name: str, root: str | Path | None = None) -> Roadmap:
    for d in reversed(dirs(root)):
        p = d / f"{name}.yaml"
        if p.is_file():
            return unmarshal_roadmap(p.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"unknown recipe: {name}")


def substitute(recipe: Roadmap, mapping: dict[str, str]) -> Roadmap:
    if not mapping:
        return recipe

    def s(text: str) -> str:
        out = text or ""
        for k, v in mapping.items():
            out = out.replace("{{" + k + "}}", v)
        if "from" in mapping:
            out = out.replace("Symbol", mapping["from"]) if out == "Symbol" else out
        if "to" in mapping:
            out = out.replace("NewSymbol", mapping["to"]) if out == "NewSymbol" else out
        return out

    recipe.hypothesis.statement = s(recipe.hypothesis.statement)
    recipe.hypothesis.symbol = s(recipe.hypothesis.symbol) if recipe.hypothesis.symbol else recipe.hypothesis.symbol
    recipe.hypothesis.from_pat = mapping.get("from", recipe.hypothesis.from_pat)
    recipe.hypothesis.to = mapping.get("to", recipe.hypothesis.to)
    recipe.goal.statement = s(recipe.goal.statement)
    for step in recipe.steps:
        step.title = s(step.title)
        if step.replace:
            if "{{from}}" in (step.replace.from_pat or "") or step.replace.from_pat in ("Symbol", "{{from}}"):
                step.replace.from_pat = mapping.get("from", step.replace.from_pat)
            else:
                step.replace.from_pat = s(step.replace.from_pat)
            if "{{to}}" in (step.replace.to or "") or step.replace.to in ("NewSymbol", "{{to}}"):
                step.replace.to = mapping.get("to", step.replace.to)
            else:
                step.replace.to = s(step.replace.to)
            step.replace.paths = [s(p) for p in step.replace.paths]
        step.verify = s(step.verify)
        step.goal = s(step.goal)
        step.want = s(step.want)
        step.paths = [s(p) for p in step.paths]
    return recipe


def apply_recipe(rm: Roadmap, recipe: Roadmap) -> Roadmap:
    ids = {s.id for s in rm.steps}
    for s in recipe.steps:
        if s.id not in ids:
            rm.steps.append(s)
    if recipe.goal.statement and not rm.goal.statement:
        rm.goal = recipe.goal
    elif recipe.goal.profile == "feature" and rm.goal.profile == "refactor":
        rm.goal.profile = "feature"
    kinds = {o.kind for o in rm.oracles}
    for o in recipe.oracles:
        if o.kind not in kinds:
            rm.oracles.append(o)
        else:
            for cur in rm.oracles:
                if cur.kind == o.kind and o.command and not cur.command:
                    cur.command = o.command
    if recipe.verify and not rm.verify:
        rm.verify = recipe.verify
    if any(s.verify for s in rm.steps) and is_fallback_verify(rm.verify):
        rm.verify = ""
    return rm


def campaign_recipe(goal: str, steps: list[dict], *, profile: str = "feature") -> Roadmap:
    """Build a feature DAG from [{id, path, verify, depends, want, engine}]."""
    rm = Roadmap(
        version=3,
        id="feature-campaign",
        hypothesis=Hypothesis(id="h1", statement=goal),
        goal=Goal(id="g1", statement=goal, profile=profile or "feature", acceptance=[]),
        verify="",
        steps=[],
    )
    for raw in steps:
        sid = str(raw.get("id") or "").strip()
        if not sid:
            continue
        path = raw.get("path") or raw.get("paths") or []
        if isinstance(path, str):
            paths = [path] if path else []
        else:
            paths = [str(p) for p in path if p]
        deps = raw.get("depends") or raw.get("depends_on") or []
        from rfg.types import coerce_depends_list as _coerce_deps

        deps = _coerce_deps(deps)
        rm.steps.append(
            Step(
                id=sid,
                title=str(raw.get("title") or sid),
                engine=str(raw.get("engine") or "implement"),
                want=str(raw.get("want") or raw.get("goal") or ""),
                paths=paths,
                verify=str(raw.get("verify") or ""),
                depends_on=[str(d) for d in deps],
            )
        )
    return rm
