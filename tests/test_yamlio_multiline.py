"""yamlio multiline roundtrip tests (R5, test-first)."""

import unittest

from rfg.types import Roadmap, Step
from rfg import yamlio


def _rt(want=None, verify=None, title="t", statement=None):
    rm = Roadmap(id="t")
    s = Step(id="s1", title=title, want=want or "", verify=verify or "")
    if statement is not None:
        rm.goal.statement = statement
    rm.steps.append(s)
    return yamlio.unmarshal_roadmap(yamlio.marshal_roadmap(rm))


class YamlMultilineTest(unittest.TestCase):
    def test_multiline_want_roundtrips(self):
        rm = _rt(want="line one\nFAIL: something broke")
        self.assertEqual(rm.steps[0].want, "line one\nFAIL: something broke")

    def test_multiline_verify_roundtrips(self):
        rm = _rt(want="w", verify="export A=1 && pytest -q\npython3 -c \"assert True\"")
        self.assertEqual(rm.steps[0].verify, "export A=1 && pytest -q\npython3 -c \"assert True\"")

    def test_quotes_colons_backslashes_survive(self):
        want = 'say "hi": C:\\tmp\\x\nFAIL: a"b\\c'
        rm = _rt(want=want)
        self.assertEqual(rm.steps[0].want, want)

    def test_single_line_unchanged(self):
        rm = _rt(want="plain want", verify="pytest -q", title="plain")
        self.assertEqual(rm.steps[0].want, "plain want")
        self.assertEqual(rm.steps[0].verify, "pytest -q")

    def test_fail_line_found_after_roundtrip(self):
        import re

        rm = _rt(want="behavior here\nFAIL: trigger without hint")
        self.assertTrue(re.search(r"(?m)^(FAIL|NEGATIV)\s*:\s*\S+", rm.steps[0].want))

    def test_store_save_load_multiline(self):
        import tempfile
        from rfg.store import Store

        with tempfile.TemporaryDirectory(prefix="rfg-yaml-") as td:
            st = Store(td)
            rm = Roadmap(id="t")
            rm.steps.append(Step(id="s1", title="t", want="a\nFAIL: b"))
            st.save_roadmap(rm)
            back = st.load_roadmap()
            self.assertEqual(back.steps[0].want, "a\nFAIL: b")


if __name__ == "__main__":
    unittest.main()
