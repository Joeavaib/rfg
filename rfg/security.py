"""Security gates: inventory SBOM, scanner/fuzz presence, trust boundaries.

Does not generate exploits, payloads, or attack PoCs.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from rfg import edges

SCANNERS = ("trivy", "grype", "govulncheck", "pip-audit", "cargo-audit", "osv-scanner")
FUZZERS = ("cargo-fuzz", "afl-fuzz", "honggfuzz", "jazzer")


SEVERITIES = ("critical", "high", "medium", "low", "unknown")

_SCANNER_JSON_FLAGS = {
    "trivy": ["fs", ".", "--format", "json", "--quiet"],
    "grype": ["dir:.", "-o", "json", "--only-fixed", "false"],
    "pip-audit": ["--format=json"],
    "osv-scanner": ["--format", "json", "./..."],
    "cargo-audit": ["--json"],
    "govulncheck": ["-json", "./..."],
}


def normalize_severity(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if s.startswith("crit"):
        return "critical"
    if s.startswith("high"):
        return "high"
    if s.startswith("med") or s.startswith("moderate"):
        return "medium"
    if s.startswith("low") or s.startswith("negligible"):
        return "low"
    return "unknown"


def parse_scanner_output(text: str, tool: str = "") -> list[dict]:
    """Parse scanner JSON into findings. Unknown/unparseable input yields []."""
    try:
        data = json.loads(text or "")
    except (json.JSONDecodeError, TypeError):
        return []
    tool = (tool or "").lower()
    if tool in ("", "trivy") and isinstance(data, dict) and "Results" in data:
        tool = "trivy"
    if tool in ("", "grype") and isinstance(data, dict) and "matches" in data:
        tool = "grype"
    if tool in ("", "pip-audit") and isinstance(data, dict) and "dependencies" in data:
        tool = "pip-audit"
    if tool in ("", "osv-scanner") and isinstance(data, dict) and "results" in data:
        tool = "osv-scanner"
    out: list[dict] = []
    if tool == "trivy":
        for res in (data.get("Results") or []):
            target = res.get("Target") or ""
            for v in res.get("Vulnerabilities") or []:
                out.append({
                    "tool": "trivy", "id": v.get("VulnerabilityID") or "",
                    "severity": normalize_severity(v.get("Severity")),
                    "package": (v.get("PkgName") or "") + "@" + (v.get("InstalledVersion") or ""),
                    "target": target, "title": v.get("Title") or "",
                    "fixed": v.get("FixedVersion") or "",
                })
    elif tool == "grype":
        for m in data.get("matches") or []:
            vuln = m.get("vulnerability") or {}
            art = m.get("artifact") or {}
            out.append({
                "tool": "grype", "id": vuln.get("id") or "",
                "severity": normalize_severity(vuln.get("severity")),
                "package": (art.get("name") or "") + "@" + (art.get("version") or ""),
                "target": "", "title": vuln.get("description") or "",
                "fixed": (vuln.get("fix") or {}).get("versions") or "",
            })
    elif tool == "pip-audit":
        for dep in data.get("dependencies") or []:
            name = dep.get("name") or ""
            ver = dep.get("version") or (dep.get("spec") or "")
            for v in dep.get("vulns") or []:
                specs = ",".join(v.get("spec") or [])
                out.append({
                    "tool": "pip-audit", "id": v.get("id") or "",
                    "severity": normalize_severity((v.get("severity") or "") or "unknown"),
                    "package": f"{name}@{ver}", "target": "", "title": v.get("description") or v.get("details") or "",
                    "fixed": (v.get("fix_versions") or [specs])[0] if (v.get("fix_versions") or [specs]) else "",
                })
    elif tool == "osv-scanner":
        for res in data.get("results") or []:
            for pkg in res.get("packages") or []:
                info = pkg.get("package") or {}
                name = info.get("name") or ""
                ver = info.get("version") or ""
                for v in pkg.get("vulnerabilities") or pkg.get("vulns") or []:
                    sev = "unknown"
                    for s in v.get("severity") or []:
                        if s.get("type", "").endswith("CVSS_V3"):
                            score = s.get("score") or ""
                            try:
                                f = float(str(score).split("/")[0].split(":")[-1])
                                sev = "critical" if f >= 9 else "high" if f >= 7 else "medium" if f >= 4 else "low"
                            except ValueError:
                                pass
                    out.append({
                        "tool": "osv-scanner", "id": v.get("id") or v.get("aliases", [""])[0] if v.get("aliases") else (v.get("id") or ""),
                        "severity": sev, "package": f"{name}@{ver}", "target": "",
                        "title": v.get("summary") or "", "fixed": "",
                    })
    return [f for f in out if f.get("id") or f.get("package").strip("@")]


def summarize_findings(findings: list[dict]) -> dict:
    counts = {s: 0 for s in SEVERITIES}
    for f in findings or []:
        counts[normalize_severity(f.get("severity"))] += 1
    return {"total": len(findings or []), **counts,
            "blocking": counts["critical"] + counts["high"]}


def write_sarif(root: str | Path, findings: list[dict], tool: str = "scan") -> Path:
    rules: dict[str, dict] = {}
    results = []
    for f in findings or []:
        rid = f.get("id") or "finding"
        sev = normalize_severity(f.get("severity"))
        level = {"critical": "error", "high": "error", "medium": "warning"}.get(sev, "note")
        rules.setdefault(rid, {"id": rid, "shortDescription": {"text": (f.get("title") or rid)[:200]}})
        results.append({
            "ruleId": rid, "level": level,
            "message": {"text": f"{f.get('package')}: {f.get('title') or rid}"[:500]},
        })
    sarif = {"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
             "runs": [{"tool": {"driver": {"name": tool, "rules": list(rules.values())}},
                       "results": results}]}
    p = Path(root) / ".rfg" / "scan.sarif"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sarif, indent=2) + "\n", encoding="utf-8")
    return p


def run_scanner_json(root: str | Path, tool: str, timeout: float = 120.0) -> tuple[int, str]:
    """Run a present scanner with JSON flags. Returns (returncode, stdout)."""
    import subprocess

    if tool not in _SCANNER_JSON_FLAGS or shutil.which(tool) is None:
        return 4, f"unsupported: scanner {tool} not available"
    try:
        r = subprocess.run([tool, *_SCANNER_JSON_FLAGS[tool]], cwd=root,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 2, "scanner timeout"
    return r.returncode, r.stdout or ""


def scanners_present() -> list[str]:
    return [n for n in SCANNERS if shutil.which(n)]


def fuzzers_present() -> list[str]:
    found = [n for n in FUZZERS if shutil.which(n)]
    go = shutil.which("go")
    if go:
        found.append("go-test-fuzz")
    return found


FUZZ_DEFAULT_SECONDS = 30

_FUZZ_TEMPLATES = {
    "cargo-fuzz": "cargo fuzz run default -- -max_total_time={s}",
    "afl-fuzz": "afl-fuzz -V {s} -i fuzz/in -o fuzz/out -- {target}",
    "honggfuzz": "honggfuzz --timeout {s} -- {target}",
    "jazzer": "jazzer --target_class={target} -- -max_total_time={s}",
    "go-test-fuzz": "go test -run=NONE -fuzz=. -fuzztime={s}s ./...",
}


def fuzz_command(present: list[str] | None = None, seconds: int = FUZZ_DEFAULT_SECONDS, target: str = "") -> str:
    """Build a real fuzz command from present fuzzers (empty when none)."""
    present = present if present is not None else fuzzers_present()
    try:
        seconds = max(1, int(seconds))
    except (ValueError, TypeError):
        seconds = FUZZ_DEFAULT_SECONDS
    for name in present:
        tmpl = _FUZZ_TEMPLATES.get(name)
        if tmpl:
            return tmpl.format(s=seconds, target=target or "fuzz-target")
    return ""


def boundaries(root: str | Path) -> list[dict]:
    out = []
    for e in edges.scan(root):
        item = dict(e)
        item["trust_boundary"] = True
        out.append(item)
    return out


def _go_mods(root: Path) -> list[dict]:
    p = root / "go.mod"
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8", errors="replace")
    comps = []
    m = re.search(r"^module\s+(\S+)", text, re.M)
    if m:
        comps.append({"type": "application", "name": m.group(1), "version": ""})
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("require ") and not line.endswith("("):
            parts = line.split()
            if len(parts) >= 3:
                comps.append({"type": "library", "name": parts[1], "version": parts[2]})
        elif re.match(r"^\S+\s+v\d", line) and not line.startswith("module"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].startswith("v"):
                comps.append({"type": "library", "name": parts[0], "version": parts[1]})
    return comps


def _npm(root: Path) -> list[dict]:
    p = root / "package.json"
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    comps = []
    if data.get("name"):
        comps.append({"type": "application", "name": data["name"], "version": str(data.get("version") or "")})
    for section in ("dependencies", "devDependencies"):
        for name, ver in (data.get(section) or {}).items():
            comps.append({"type": "library", "name": name, "version": str(ver)})
    return comps


def _py(root: Path) -> list[dict]:
    comps = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        name = re.search(r'^name\s*=\s*"([^"]+)"', text, re.M)
        ver = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
        if name:
            comps.append(
                {"type": "application", "name": name.group(1), "version": ver.group(1) if ver else ""}
            )
    req = root / "requirements.txt"
    if req.is_file():
        for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, _, ver = line.partition("==")
            comps.append({"type": "library", "name": name.strip(), "version": ver.strip()})
    return comps


def sbom(root: str | Path) -> dict:
    root = Path(root)
    components = _go_mods(root) + _npm(root) + _py(root)
    seen = set()
    uniq = []
    for c in components:
        key = (c["name"], c.get("version"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": uniq,
    }


def write_sbom(root: str | Path) -> tuple[Path, dict]:
    data = sbom(root)
    p = Path(root) / ".rfg" / "sbom.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p, data
