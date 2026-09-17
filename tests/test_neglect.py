"""Neglected-tools tests (K04-K10)."""
import json
import unittest

TRIVY_FIXTURE = {
    "Results": [{
        "Target": "app",
        "Vulnerabilities": [
            {"VulnerabilityID": "CVE-2024-0001", "PkgName": "libx", "InstalledVersion": "1.0",
             "FixedVersion": "1.1", "Severity": "CRITICAL", "Title": "bad bug"},
            {"VulnerabilityID": "CVE-2024-0002", "PkgName": "liby", "InstalledVersion": "2.0",
             "FixedVersion": "", "Severity": "LOW", "Title": "minor"},
        ],
    }]
}

PIP_AUDIT_FIXTURE = {
    "dependencies": [{
        "name": "req", "version": "1.0",
        "vulns": [{"id": "PYSEC-1", "spec": ">=1.1", "fix_versions": ["1.1"],
                   "description": "req bug"}],
    }]
}

CLEAN_FIXTURE = {"Results": [{"Target": "app", "Vulnerabilities": []}]}


class NeglectTest(unittest.TestCase):
    def test_scan_sbom_findings(self):
        from rfg import security as sec
        # trivy parse + summary
        findings = sec.parse_scanner_output(json.dumps(TRIVY_FIXTURE), "trivy")
        self.assertEqual(len(findings), 2)
        by_id = {f["id"]: f for f in findings}
        self.assertEqual(by_id["CVE-2024-0001"]["severity"], "critical")
        self.assertEqual(by_id["CVE-2024-0002"]["severity"], "low")
        summary = sec.summarize_findings(findings)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["critical"], 1)
        self.assertEqual(summary["blocking"], 1)
        # pip-audit parse (severity unknown -> unknown bucket, not blocking)
        findings = sec.parse_scanner_output(json.dumps(PIP_AUDIT_FIXTURE))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["id"], "PYSEC-1")
        self.assertEqual(sec.summarize_findings(findings)["blocking"], 0)
        # garbage in, empty out
        self.assertEqual(sec.parse_scanner_output("nope{"), [])
        self.assertEqual(sec.parse_scanner_output(""), [])
        # CLI --parse mode: blocking fixture -> exit 2, clean -> exit 0
        import tempfile, os, subprocess
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       PYTHONPATH=str(Path(__file__).resolve().parent.parent))
            subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
            bad = Path(td, "bad.json")
            bad.write_text(json.dumps(TRIVY_FIXTURE))
            good = Path(td, "good.json")
            good.write_text(json.dumps(CLEAN_FIXTURE))
            r = subprocess.run(["python3", "-m", "rfg", "--root", td, "--format", "json",
                                "scan", "--parse", str(bad), "--tool", "trivy"],
                               capture_output=True, text=True, env=env, cwd=td)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            payload = json.JSONDecoder().raw_decode(r.stdout)[0]["data"]
            self.assertEqual(payload["summary"]["blocking"], 1)
            self.assertTrue(Path(payload["sarif"]).is_file())
            sarif = json.loads(Path(payload["sarif"]).read_text())
            self.assertEqual(sarif["version"], "2.1.0")
            r = subprocess.run(["python3", "-m", "rfg", "--root", td, "--format", "json",
                                "scan", "--parse", str(good)],
                               capture_output=True, text=True, env=env, cwd=td)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


    def test_fuzz_perf(self):
        from rfg import security as sec
        from rfg import oracles as ora
        # builder: empty without fuzzers, real command with one
        self.assertEqual(sec.fuzz_command([]), "")
        cmd = sec.fuzz_command(["go-test-fuzz"], seconds=45)
        self.assertIn("45", cmd)
        self.assertIn("go test", cmd)
        self.assertEqual(sec.fuzz_command(["cargo-fuzz"], seconds=10), 
                         "cargo fuzz run default -- -max_total_time=10")
        # perf delta: record baseline + last run, check ratio report
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(ora.perf_delta(td), {"recorded": False})
            base = ora.capture_baseline(td, 'python3 -c "print(2.0)"', store_root=td)
            self.assertAlmostEqual(base["metric"], 2.0)
            code, _ = ora.run_perf(td, 'python3 -c "print(4.0)"', store_root=td)
            self.assertEqual(code, 0)
            delta = ora.perf_delta(td)
            self.assertTrue(delta["recorded"])
            self.assertAlmostEqual(delta["ratio"], 2.0)
            # max_ratio breach still fails the oracle
            from rfg.types import Oracle
            code, out = ora.run_perf(td, 'python3 -c "print(9.0)"',
                                     Oracle(kind="perf", max_ratio=2.0), store_root=td)
            self.assertEqual(code, 2)
            self.assertIn("exceeds baseline", out)
            # progress carries the perf section
            from rfg.progress import report
            from rfg.types import Roadmap
            rep = report(td, Roadmap(), __import__("rfg.types", fromlist=["State"]).State())
            self.assertIn("perf", rep)
            self.assertTrue(rep["perf"]["recorded"])


    def test_fleet_json(self):
        import tempfile, os, subprocess, shutil
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       PYTHONPATH=str(Path(__file__).resolve().parent.parent))
            def rfg(*a, cwd=None):
                r = subprocess.run(["python3", "-m", "rfg", "--root", td, "--format", "json", *a],
                                   capture_output=True, text=True, env=env, cwd=cwd or td)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                return json.loads(r.stdout)["data"]
            a = Path(td, "a"); a.mkdir()
            b = Path(td, "b"); b.mkdir()
            for p in (a, b):
                subprocess.check_call(["git", "init", "-q"], cwd=p, env=env)
                subprocess.check_call(["git", "commit", "-q", "--allow-empty", "-m", "i"],
                                      cwd=p, env=env, stdout=subprocess.DEVNULL)
                (p / "x.py").write_text("x=1\n")
            rfg("init")
            for p, sid in ((a, "SA"), (b, "SB")):
                r = subprocess.run(["python3", "-m", "rfg", "--root", str(p), "--format", "json",
                                    "init"], capture_output=True, text=True, env=env, cwd=p)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                r = subprocess.run(["python3", "-m", "rfg", "--root", str(p), "--format", "json",
                                    "plan", "--step", sid, "--engine", "implement",
                                    "--path", "x.py", "--want", "w",
                                    "--verify", 'python3 -c "assert True"'],
                                   capture_output=True, text=True, env=env, cwd=p)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            (Path(td) / ".rfg").mkdir(exist_ok=True)
            (Path(td) / ".rfg" / "fleet.yaml").write_text(
                f"repos:\n  - name: one\n    path: {a}\n  - name: two\n    path: {b}\n")
            out = rfg("fleet", "status")
            self.assertTrue(out["ok"])
            self.assertEqual(out["totals"], {"repos": 2, "verified": 0, "failed": 0, "ready": 2})
            for row in out["repos"]:
                # compact: no full progress dump
                self.assertNotIn("progress", row)
                self.assertEqual(row["ready"], 1)
                self.assertEqual(row["total"], 1)
            self.assertIn("token_estimate", out)
            full = rfg("fleet", "status", "--full")
            self.assertIn("progress", full["repos"][0])


    def test_export_batch(self):
        import tempfile, os, subprocess
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       PYTHONPATH=str(Path(__file__).resolve().parent.parent))
            subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
            subprocess.check_call(["git", "commit", "-q", "--allow-empty", "-m", "i"],
                                  cwd=td, env=env, stdout=subprocess.DEVNULL)
            def rfg(*a):
                r = subprocess.run(["python3", "-m", "rfg", "--root", td, "--format", "json", *a],
                                   capture_output=True, text=True, env=env, cwd=td)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                return json.loads(r.stdout)["data"]
            rfg("init")
            for i in range(5):
                rfg("plan", "--step", f"E{i}", "--engine", "implement",
                    "--path", f"f{i}.py", "--want", f"w{i}",
                    "--verify", f'python3 -c "assert {i} == {i}"')
            full = rfg("export", "batch")
            self.assertEqual(full["steps"], [f"E{i}" for i in range(5)])
            self.assertTrue(Path(full["path"]).is_file())
            small = rfg("export", "batch", "--max-chars", "300")
            self.assertLessEqual(small["chars"], 300)
            self.assertTrue(small["truncated"])
            self.assertEqual(small["steps"], [f"E{i}" for i in range(5)])
            # digest nutzt dasselbe Budget, Logs als Pfade
            dig = rfg("digest", "--max-chars", "8000")
            self.assertLessEqual(dig["chars"], 8000)
            self.assertIn("token_estimate", dig)


    def test_dx_cleanup(self):
        from rfg import complete, telemetry
        # completion: all commands + current global flags in every shell
        for shell in ("bash", "zsh", "fish"):
            out = complete.render(shell)
            for cmd in ("init", "land", "scan", "fleet", "sbom"):
                self.assertIn(cmd, out)
            for flag in ("show-risk", "max-chars", "dry-run"):
                self.assertIn(flag, out, f"{shell} missing {flag}")
        with self.assertRaises(ValueError):
            complete.render("powershell")
        # man page: budgets documented
        from rfg import manpage
        text = manpage.text()
        self.assertIn("rfg", text)
        self.assertIn("max-chars", text)
        # telemetry decision: KEEP (opt-in, local-only) + tested
        import os
        os.environ.pop("RFG_TELEMETRY", None)
        self.assertFalse(telemetry.enabled())
        os.environ["RFG_TELEMETRY"] = "1"
        try:
            self.assertTrue(telemetry.enabled())
            import tempfile
            from pathlib import Path
            with tempfile.TemporaryDirectory() as td:
                telemetry.record(td, "test-event", {"k": 1})
                lines = (Path(td) / ".rfg" / "telemetry.log").read_text().strip().splitlines()
                self.assertEqual(len(lines), 1)
                import json
                row = json.loads(lines[0])
                self.assertEqual(row["event"], "test-event")
        finally:
            os.environ.pop("RFG_TELEMETRY", None)
        # disabled by default: no file; module never touches the network
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            telemetry.record(td, "x")
            self.assertFalse((Path(td) / ".rfg" / "telemetry.log").exists())
        src = Path(__file__).resolve().parent.parent / "rfg" / "telemetry.py"
        self.assertNotIn("import socket", src.read_text())


    def test_cxx_parity(self):
        import subprocess, sys
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        # boundary report: known python-only features are declared, not silent
        r = subprocess.run([sys.executable, str(root / "scripts" / "cxx-parity.py"), "--boundary"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        boundary = json.loads(r.stdout)
        for feat in ("land-gate", "cross-verify", "max-chars", "scan --parse"):
            self.assertTrue(any(feat in x for x in boundary["python_only"]), feat)
        self.assertIn("land-basic", boundary["covered"])
        # README documents the same boundary
        readme = (root / "README.md").read_text(encoding="utf-8")
        for feat in ("Land-Gate", "Cross-Verify", "--max-chars"):
            self.assertIn(feat, readme)
        # live parity check (needs built binary; skip without toolchain)
        r = subprocess.run(["make", "-C", str(root / "cxx")], capture_output=True, text=True)
        if r.returncode != 0 or not (root / "cxx" / "rfg").is_file():
            self.skipTest("cxx build unavailable")
        r = subprocess.run([sys.executable, str(root / "scripts" / "cxx-parity.py")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)


    def test_abschluss(self):
        import subprocess, sys
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        # Doku auf Stand
        readme = (root / "README.md").read_text(encoding="utf-8")
        roadmap = (root / "docs" / "rfg-coverage-roadmap.md").read_text(encoding="utf-8")
        for kw in ("--max-chars", "--show-risk", "Cross-Verify", "Land-Gate", "SARIF",
                   "Fleet-Summary", "Mutations-Stichprobe", "Diff-Presence-Gate"):
            self.assertTrue(kw in readme or kw in roadmap, kw)
        # Mutations-Stichprobe 4/4
        r = subprocess.run([sys.executable, "-m", "pytest",
                            "tests/test_quality.py::QualityTest::test_mutation_sample", "-q"],
                           capture_output=True, text=True, cwd=root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # Diff-Presence-Gate funktioniert (Fixture aus H06-Logik)
        from scripts import diff_coverage as dc
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
            (Path(td) / "rfg").mkdir()
            (Path(td) / "tests").mkdir()
            (Path(td) / "rfg" / "m.py").write_text("def g():\n    return 1\n")
            (Path(td) / "tests" / "test_m.py").write_text("x=1\n")
            subprocess.check_call(["git", "add", "-A"], cwd=td, env=env)
            subprocess.check_call(["git", "commit", "-qm", "i"], cwd=td, env=env)
            (Path(td) / "rfg" / "m.py").write_text("def g():\n    return 2\n")
            code, _ = dc.check(td, "HEAD")
            self.assertEqual(code, 2)  # ungated change detected


if __name__ == "__main__":
    unittest.main()
