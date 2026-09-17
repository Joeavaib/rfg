"""Token-budget tests (K01-K03)."""
import json
import unittest


class TokenTest(unittest.TestCase):
    def test_max_chars_cap(self):
        from rfg import tokens as t
        # parsing + clamp
        self.assertEqual(t.parse_max_chars([]), 2000)
        self.assertEqual(t.parse_max_chars(["--max-chars", "500"]), 500)
        self.assertEqual(t.parse_max_chars(["--max-chars", "999999"]), 8000)
        self.assertEqual(t.parse_max_chars(["--max-chars", "junk"]), 2000)
        # small payload untouched except budget fields
        small = t.cap_data({"a": 1}, 2000)
        self.assertFalse(small["truncated"])
        self.assertEqual(small["max_chars"], 2000)
        # big payload shrinks and says so
        big = {"files": [{"path": f"f{i}.py"} for i in range(200)], "steps": list(range(200))}
        capped = t.cap_data(dict(big), 2000)
        self.assertTrue(capped["truncated"])
        self.assertLessEqual(capped["chars"], 2000)
        self.assertLess(len(capped["files"]), 200)
        # CLI wiring: context honors --max-chars
        import tempfile, os, subprocess
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       PYTHONPATH=str(Path(__file__).resolve().parent.parent))
            subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
            subprocess.check_call(["git", "commit", "--allow-empty", "-m", "i"],
                                  cwd=td, env=env, stdout=subprocess.DEVNULL)
            r = subprocess.run(["python3", "-m", "rfg", "--root", td, "--format", "json",
                                "init"], capture_output=True, text=True, env=env, cwd=td)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run(["python3", "-m", "rfg", "--root", td, "--format", "json",
                                "context", "--max-chars", "500"],
                               capture_output=True, text=True, env=env, cwd=td)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            data = json.loads(r.stdout)["data"]
            self.assertLessEqual(data["chars"], 500)
            self.assertEqual(data["max_chars"], 500)


    def test_slim_default(self):
        import tempfile, os, subprocess, json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       PYTHONPATH=str(Path(__file__).resolve().parent.parent))
            subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
            subprocess.check_call(["git", "commit", "--allow-empty", "-m", "i"],
                                  cwd=td, env=env, stdout=subprocess.DEVNULL)
            Path(td, "a.py").write_text("x=1\n")
            def rfg(*a):
                r = subprocess.run(["python3", "-m", "rfg", "--root", td, "--format", "json", *a],
                                   capture_output=True, text=True, env=env, cwd=td)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                return json.loads(r.stdout)["data"]
            rfg("init")
            Path(td, "b.py").write_text("foo=1\n")
            rfg("plan", "--step", "R", "--from", "foo", "--to", "bar",
                "--path", "b.py", "--want", "r", "--verify", "true")
            nxt = rfg("next")
            self.assertEqual(nxt["id"], "R")
            self.assertNotIn("risk", nxt)
            nxt = rfg("next", "--show-risk")
            self.assertIsInstance(nxt.get("risk"), dict)
            dry = rfg("apply", "--dry-run")
            self.assertNotIn("risk", dry)
            dry = rfg("apply", "--dry-run", "--show-risk")
            self.assertIsInstance(dry.get("risk"), dict)
            applied = rfg("apply", "--show-risk")
            self.assertIsInstance(applied.get("risk"), dict)
            self.assertIn("format", applied)


    def test_index_cap(self):
        import tempfile, os, subprocess, json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       PYTHONPATH=str(Path(__file__).resolve().parent.parent))
            subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
            subprocess.check_call(["git", "commit", "--allow-empty", "-m", "i"],
                                  cwd=td, env=env, stdout=subprocess.DEVNULL)
            for i in range(60):
                Path(td, f"m{i}.py").write_text(f"zzq_{i} = {i}\nprint('zzq')\n")
            def rfg(*a):
                r = subprocess.run(["python3", "-m", "rfg", "--root", td, "--format", "json", *a],
                                   capture_output=True, text=True, env=env, cwd=td)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                return json.loads(r.stdout)["data"]
            rfg("init")
            rep = rfg("impact", "--symbol", "zzq", "--files", "--max-chars", "8000")
            # hard deckel aus _cap_impact (24) + Token-Zählung aus K01/K03
            self.assertLessEqual(len(rep.get("files") or []), 24)
            self.assertTrue(rep.get("files_omitted") or rep.get("warning"))
            self.assertIn("token_estimate", rep)
            self.assertLessEqual(rep["chars"], 8000)
            # verify-Logs: Ausgabe geclippt mit Log-Hinweis, Volltext in Datei
            Path(td, "a.py").write_text("x=1\n")
            rfg("plan", "--step", "S", "--engine", "implement", "--path", "a.py",
                "--want", "x", "--verify", 'python3 -c "print(5000*\'y\')"')
            rfg("apply")
            ver = rfg("verify")
            self.assertIn("truncated, see log", ver.get("output") or "")
            logp = Path(td, (ver.get("log") or "").lstrip("/")) if (ver.get("log") or "").startswith("/") else Path(td, ver.get("log") or "")
            # log path is absolute under root
            self.assertTrue(Path(ver["log"]).is_file())
            self.assertGreater(len(Path(ver["log"]).read_text()), 5000)


    def test_limit_review(self):
        from rfg import tokens as t
        # 0 = explicit unlimited override, never silently clamped
        self.assertIsNone(t.parse_max_chars(["--max-chars", "0"]))
        self.assertIsNone(t.parse_max_chars(["--max-chars", "-5"]))
        self.assertEqual(t.parse_max_chars(["--max-chars", "999999"]), 8000)
        big = {"files": [{"path": f"f{i}.py"} for i in range(200)]}
        uncut = t.cap_data(dict(big), None)
        self.assertFalse(uncut["truncated"])
        self.assertEqual(len(uncut["files"]), 200)
        self.assertIsNone(uncut["max_chars"])
        # exceptions are never shrunk, even under tiny budgets
        exc = {"exceptions": [{"kind": "failed", "step": f"S{i}"} for i in range(50)],
               "files": [{"path": f"f{i}.py"} for i in range(200)]}
        capped = t.cap_data(dict(exc), 2000)
        self.assertEqual(len(capped["exceptions"]), 50)
        # sbom: file complete, emit budgeted
        import tempfile, os, subprocess, json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       PYTHONPATH=str(Path(__file__).resolve().parent.parent))
            subprocess.check_call(["git", "init", "-q"], cwd=td, env=env)
            deps = {f"dep-{i}": f"^{i}.0.0" for i in range(60)}
            Path(td, "package.json").write_text(json.dumps({"name": "x", "dependencies": deps}))
            r = subprocess.run(["python3", "-m", "rfg", "--root", td, "--format", "json",
                                "sbom", "--max-chars", "1500"],
                               capture_output=True, text=True, env=env, cwd=td)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            data = json.loads(r.stdout)["data"]
            self.assertLessEqual(data["chars"], 1500)
            self.assertEqual(data["count"], 61)  # nothing lost, only display shrunk
            full = json.loads((Path(td) / ".rfg" / "sbom.json").read_text())
            self.assertEqual(len(full["components"]), 61)


if __name__ == "__main__":
    unittest.main()
