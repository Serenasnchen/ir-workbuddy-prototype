"""Pre-register the Top-10 expected topics before an earnings call, and verify them afterwards.

Usage:
  python prereg.py seal <top10.json>                 # canonicalise, write <top10>.sealed.json with SHA-256 + UTC time
  python prereg.py verify <top10.sealed.json> <sha256>  # recompute and compare with the published hash
  python prereg.py score <top10.sealed.json> <asked_topics.json>  # after the call: which topics were actually asked

top10.json: {"company": "...", "call_date": "YYYY-MM-DD", "topics": [{"rank": 1, "topic": "...", "why": "..."}, ...]}
asked_topics.json: ["topic", ...]  (taken from the post-call transcript)
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def seal(path):
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    body = canonical(obj)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    out = Path(path).with_suffix(".sealed.json")
    out.write_text(json.dumps({"payload": obj, "canonical": body, "sha256": digest,
                               "sealed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"SHA-256: {digest}\n已写入 {out}。请把哈希写进提交的材料，会后用 verify 核对。")


def verify(path, expected):
    sealed = json.loads(Path(path).read_text(encoding="utf-8"))
    digest = hashlib.sha256(canonical(sealed["payload"]).encode("utf-8")).hexdigest()
    ok = digest == expected.strip().lower()
    print(("一致" if ok else "不一致") + f"：{digest}")
    return 0 if ok else 1


def score(path, asked_path):
    sealed = json.loads(Path(path).read_text(encoding="utf-8"))
    asked = {a.strip().lower() for a in json.loads(Path(asked_path).read_text(encoding="utf-8"))}
    topics = sealed["payload"]["topics"]
    hits = [t for t in topics if t["topic"].strip().lower() in asked]
    for t in topics:
        print(("✓ " if t in hits else "  ") + f"{t['rank']:>2}. {t['topic']}")
    print(f"\n命中 {len(hits)}/{len(topics)}（只报实测值）")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "seal":
        seal(sys.argv[2])
    elif cmd == "verify":
        sys.exit(verify(sys.argv[2], sys.argv[3]))
    elif cmd == "score":
        score(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        sys.exit(2)
