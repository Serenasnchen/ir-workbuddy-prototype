"""Regression tests for the transcript analytics module (run from ROOT: python -I demo/pipeline/test_transcripts.py)."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "demo" / "pipeline"))

import transcripts as T  # noqa: E402

FIXED = ROOT / "data" / "parsed_fixed"
OUT = ROOT / "demo" / "data"


def load(q):
    return json.loads((FIXED / f"{q}.json").read_text(encoding="utf-8"))["turns"]


class AttributionTests(unittest.TestCase):
    def test_q2_2026_turn39_is_morgan_stanley(self):
        """The raw page labels the last question as 'Speaker 12'; the moderator hand-off names Morgan Stanley."""
        turns = load("q2-2026")
        raw12 = [t for t in turns if t.get("speaker_raw") == "Speaker 12"]
        self.assertTrue(raw12, "expected the raw 'Speaker 12' turn to be kept with its original label")
        self.assertTrue(all(t["role"] == "analyst" and t["org"] == "Morgan Stanley" for t in raw12))

    def test_no_unresolved_speaker_labels(self):
        for q in T.QUARTERS:
            for t in load(q):
                if t.get("role") == "analyst":
                    self.assertFalse(T.SPEAKER_N_RE.match(t.get("speaker", "")), f"{q}: unresolved {t.get('speaker')}")

    def test_roles_are_valid(self):
        for q in T.QUARTERS:
            roles = {t.get("role") for t in load(q)}
            self.assertTrue(roles <= {"mgmt", "analyst", "moderator"}, f"{q}: {roles}")


class OutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = json.loads((OUT / "m2_transcripts.json").read_text(encoding="utf-8"))
        q = json.loads((OUT / "question_units.json").read_text(encoding="utf-8"))
        cls.units = q if isinstance(q, list) else q.get("units", q.get("question_units", []))

    def test_twelve_quarters(self):
        self.assertEqual(len(self.m["heat"]["quarters"]), 12)

    def test_workbuddy_split_q2_2026(self):
        row = next(r for r in self.m["keywords"]["rows"] if r["keyword"] == "WorkBuddy")
        q2 = row["by_quarter"]["2026Q2"]
        self.assertEqual((q2["mgmt"], q2["analyst"]), (27, 4))

    def test_units_have_topics_and_short_excerpts(self):
        valid = set(T.TOPICS.keys())
        for u in self.units:
            self.assertTrue(u["topics"], u["q_id"])
            self.assertTrue(set(u["topics"]) <= valid, u["q_id"])
            self.assertLessEqual(len(u["excerpt"]), 200, u["q_id"])

    def test_every_source_id_resolves(self):
        ids = {s["id"] for s in self.m["sources"]}
        for u in self.units:
            for sid in u.get("src", []):
                self.assertIn(sid, ids)

    def test_no_email_or_absolute_user_paths(self):
        blob = json.dumps(self.m, ensure_ascii=False) + json.dumps(self.units, ensure_ascii=False)
        self.assertNotRegex(blob, r"[\w.+-]+@(?!example\.com)[\w-]+\.[\w.]+")
        self.assertNotIn("C:\\\\Users", blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
