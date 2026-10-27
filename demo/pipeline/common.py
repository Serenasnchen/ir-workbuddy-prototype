"""Shared helpers for the IR Copilot demo pipeline (stdlib only).

Every module writes demo/data/<module>.json with the shape:
{
  "meta": {"module": str, "title": str, "as_of": "YYYY-MM-DD", "generated_by": "本地 Python" | "人工整理" | "WorkBuddy 实机",
           "script": str, "inputs": [{"path": str, "sha256": str}], "notes": str},
  "sources": [{"id": str, "title": str, "url": str, "date": str, "tier": int}],
  ... module payload; every number/quote carries "src": [source ids] and "label": one of LABELS ...
}
"""
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_SRC = ROOT / "data" / "src"
DATA_PARSED = ROOT / "data" / "parsed"
RESEARCH = ROOT / "data" / "research" / "parts"
OUT = ROOT / "demo" / "data"

AS_OF = "2026-10-26"

# Generic identity only. Never put a person's name or email in any request.
USER_AGENT = "Mozilla/5.0 (compatible; research-bot; contact@example.com)"

# Evidence labels used everywhere (report + HTML).
LABELS = ("公开披露", "结构化数据", "计算", "推断")

# Source tiers for quotes and figures, highest first.
TIERS = {
    1: "公司公告/港交所/SEC 文件",
    2: "公司官方 webcast / 官方新闻稿",
    3: "第三方文字稿（StockAnalysis 等，非官方逐字稿）",
    4: "媒体转述 / 券商观点转述（二手）",
}


def http_get(url, dest=None, delay=1.5, timeout=60):
    """Polite GET with a generic User-Agent. Returns bytes, optionally saves to dest."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    if dest:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(body)
    time.sleep(delay)
    return body


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def input_record(path):
    p = Path(path)
    return {"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(p)}


def write_module(name, payload):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def assert_no_email(text):
    """Fail if any email address other than the generic placeholder leaks into an output."""
    import re
    hits = [m for m in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text) if m != "contact@example.com"]
    if hits:
        raise ValueError(f"Email-like token found in output: {hits[:3]}")
