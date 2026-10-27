"""M4 数字守门员单元测试。运行（在 ROOT 下）：python -I demo/pipeline/test_gatekeeper.py

覆盖：单位归一（亿元/billion/百万元/万股/%）、四舍五入一致判定、已知一致指标（总收入/资本开支五方一致）、
已知不一致（一般及行政开支文字 vs 表格）、注入错误被检出（528→582、方向反转、单位错误）、干净稿无红色告警、
注入的确定性、JS 实时检查器（若本机有 node）。
"""
import json
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True  # 不写 .pyc（字节码文件会记录本机绝对路径）
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gk_core as g  # noqa: E402
import gatekeeper as gk  # noqa: E402
import inject  # noqa: E402


class TestUnits(unittest.TestCase):
    def one(self, text, lang):
        ns = g.parse_numbers(text, lang)
        self.assertEqual(len(ns), 1, f"{text!r} -> {ns}")
        return ns[0]

    def test_billion_vs_yi(self):
        a = self.one("RMB52.8 billion", "en")
        b = self.one("人民币528 亿元", "zh")
        self.assertEqual((a.cls, a.value, a.half), ("RMB", 52800.0, 50.0))
        self.assertEqual((b.cls, b.value, b.half), ("RMB", 52800.0, 50.0))
        self.assertTrue(g.consistent(a.value, a.half, 52784, 0.5))      # 与表格 52,784 百万元四舍五入一致

    def test_million_and_unit_error(self):
        c = self.one("528 百万元", "zh")
        self.assertEqual(c.value, 528.0)
        self.assertFalse(g.consistent(c.value, c.half, 52784, 0.5))
        self.assertEqual(g.judge_mismatch(c.value, c.half, 52784, 0.5), "数量级/单位差异")

    def test_other_units(self):
        self.assertAlmostEqual(self.one("回购约3,738 万股股份", "zh").value, 37.38)
        self.assertEqual(self.one("approximately 37.4 million shares", "en").cls, "count")
        self.assertEqual(self.one("约169 亿港元", "zh").cls, "HKD")
        self.assertEqual(self.one("RMB7.433", "en").cls, "RMB1")
        p = self.one("同比增长0.8%", "zh")
        self.assertEqual((p.cls, p.value, p.half), ("pct", 0.8, 0.05))
        self.assertTrue(g.consistent(36.9, 0.05, 37, 0.5))     # PPT 36.9% 与新闻稿 37% 属四舍五入
        self.assertFalse(g.consistent(38.7e3, 50, 38808, 0.5))   # 38.7bn 与 38,808 百万元不一致
        self.assertEqual(g.judge_mismatch(38700, 50, 38808, 0.5), "末位差异")
        self.assertEqual(g.normalize("（人民幣百萬元）", "zh"), "(人民币百万元)")


class TestRegistryAndTieout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.regs = gk.build_all_registries(g.KINDS)
        cls.sources, cls.sid = gk.build_sources()
        cls.to = gk.tieout(cls.regs, cls.sid)

    def test_registry_size(self):
        n = sum(1 for e in self.regs[g.TARGET].values() if "value" in e)
        self.assertGreaterEqual(n, 40)

    def test_known_consistent_metrics(self):
        reg = self.regs[g.TARGET]
        self.assertEqual(reg["rev_total"]["value"], 204785)
        self.assertEqual(reg["capex"]["value"], 52784)
        rows = {r["id"]: r for r in self.to["rows"]}
        for mid in ("rev_total", "capex", "nonifrs_op"):
            for kind in g.KINDS:
                self.assertEqual(rows[mid]["cells"][kind]["status"], "一致", f"{mid} @ {kind}")

    def test_known_discrepancy(self):
        ga = [d for d in self.to["discrepancies"] if d["metric"] == "ga_exp"]
        self.assertTrue(ga)
        self.assertTrue(all(d["judgement"] == "末位差异" for d in ga))

    def test_capex_triad(self):
        cx = gk.capex_triad(self.regs, self.sid)
        got = {(r["basis"][:4], r["period"]): r["value_rmb_m"] for r in cx["rows"]}
        self.assertEqual(got[("会计口径", "1H26")], 84720)
        self.assertEqual(got[("现金支付", "1H26")], 96300)
        self.assertEqual(got[("现金支付", "FY2025")], 88300)
        self.assertEqual(got[("季度资本", "2Q26")], 59300)
        self.assertTrue(all(c["ok"] for c in cx["checks"]))


class TestChecker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = gk.build_all_registries(g.REF_KINDS)
        cls.corpus = gk.build_corpus(g.TARGET, g.REF_KINDS)
        cls.en, _ = gk.draft_paragraphs(g.TARGET, "release_en")
        cls.zh, _ = gk.draft_paragraphs(g.TARGET, "release_zh")

    def run_check(self, paras, lang, twin):
        return gk.check_draft(paras, lang, g.TARGET, self.ref[g.TARGET], self.corpus, twin, "zh" if lang == "en" else "en")[0]

    def test_clean_drafts_no_red(self):
        for paras, lang, twin in ((self.en, "en", self.zh), (self.zh, "zh", self.en)):
            red = [f for f in self.run_check(paras, lang, twin) if f["severity"] == "red"]
            self.assertEqual(red, [], f"{lang}: {red[:3]}")

    def _mutate(self, paras, old, new):
        out = list(paras)
        for i, t in enumerate(out):
            if old in t:
                out[i] = t.replace(old, new, 1)
                return out, i, out[i].index(new)
        self.fail(f"not found: {old}")

    def test_injected_528_to_582(self):
        zh1, i, pos = self._mutate(self.zh, "人民币528 亿元", "人民币582 亿元")
        fl = [f for f in self.run_check(zh1, "zh", self.en) if f["para"] == i and f["severity"] == "red"]
        self.assertTrue(any(f["rule"] == "R1" and f.get("metric") == "capex" for f in fl), fl)
        self.assertTrue(any(f["rule"] == "R3" for f in fl), fl)     # 英文稿仍是 52.8，双语不一致

    def test_injected_direction_flip(self):
        en1, i, pos = self._mutate(self.en, "up 11% over", "down 11% over")
        fl = [f for f in self.run_check(en1, "en", self.zh) if f["para"] == i]
        self.assertTrue(any(f["rule"] == "R2" for f in fl), fl)

    def test_injected_unit_error(self):
        en1, i, pos = self._mutate(self.en, "RMB43.6 billion", "RMB43.6 million")
        fl = [f for f in self.run_check(en1, "en", self.zh) if f["para"] == i]
        self.assertTrue(any(f.get("judgement") == "数量级/单位差异" for f in fl), fl)

    def test_injection_deterministic(self):
        a = inject.make_injections(self.en, self.zh, seed=7, n=30)
        b = inject.make_injections(self.en, self.zh, seed=7, n=30)
        self.assertEqual(a[2], b[2])
        self.assertEqual(len(a[2]), 30)
        self.assertEqual({k["cat"] for k in a[2]}, set(inject.CATS))


class TestJsChecker(unittest.TestCase):
    def test_js_registry_marks_582(self):
        node = shutil.which("node")
        out = gk.ROOT / "demo" / "data" / "m4_gatekeeper.json"
        if not node or not out.exists():
            self.skipTest("node 或 m4_gatekeeper.json 不可用")
        js = (HERE / "m4_checker.js").as_posix()
        code = ("const M=require(%s);const d=JSON.parse(require('fs').readFileSync(%s,'utf8'));"
                "const a=M.check('资本开支为人民币582亿元，同比增加176%%。',d.js_registry,'zh');"
                "const b=M.check('Capital expenditure was RMB52.8 billion, up 176%% YoY.',d.js_registry,'en');"
                "console.log(JSON.stringify([a.map(x=>x.status),b.map(x=>x.status)]));") % (
            json.dumps(js), json.dumps(out.as_posix()))
        r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        a, b = json.loads(r.stdout.strip())
        self.assertIn("bad", a)
        self.assertEqual(set(b), {"ok"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
