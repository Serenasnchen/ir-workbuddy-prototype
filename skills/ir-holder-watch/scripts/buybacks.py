"""Parse HKEX Next Day Disclosure Returns (share repurchases) into a daily table, totals and anomaly checks.

Usage:
  python buybacks.py <folder_with_returns_pdf> [--out buybacks.json] [--year 2026]

Reads every PDF in the folder (download them from HKEXnews title search, category "Next Day Disclosure Returns").
Text extraction: `pdftotext -raw` if available, else PyMuPDF. Standard library otherwise.
Checks each day's average price (amount / shares) lies within the reported high/low; flags it if not, without
inferring a cause. Output labels: per-day figures 公开披露, totals and averages 计算.
"""
import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

ROW = re.compile(r"\d+\)\.\s+(\d{1,2} \w+ \d{4})\s+([\d,]+)\s+On the Exchange\s+HKD\s+([\d.]+)\s+HKD\s+([\d.]+)\s+HKD\s+([\d,]+(?:\.\d+)?)")


def text_of(pdf: Path) -> str:
    try:
        r = subprocess.run(["pdftotext", "-raw", pdf.name, "-"], cwd=str(pdf.parent), capture_output=True, timeout=120)
        if r.returncode == 0 and r.stdout:
            return r.stdout.decode("utf-8", "ignore")
    except FileNotFoundError:
        pass
    import pymupdf  # fallback
    with pymupdf.open(pdf) as d:
        return "\n".join(p.get_text() for p in d)


def dmy(s):
    return datetime.strptime(s, "%d %B %Y").date().isoformat()


def num(s):
    return float(s.replace(",", ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default="buybacks.json")
    ap.add_argument("--year", type=int)
    a = ap.parse_args()
    days, skipped = {}, []
    for pdf in sorted(Path(a.folder).glob("*.pdf")):
        t = text_of(pdf)
        rows = ROW.findall(t)
        if not rows:
            skipped.append(pdf.name)  # e.g. returns about other share changes
            continue
        for d, sh, hi, lo, amt in rows:
            iso = dmy(d)
            if a.year and not iso.startswith(str(a.year)):
                continue
            rec = days.setdefault(iso, {"date": iso, "shares": 0, "amount_hkd": 0.0, "high": 0.0, "low": 1e12, "files": []})
            rec["shares"] += int(sh.replace(",", ""))
            rec["amount_hkd"] += num(amt)
            rec["high"] = max(rec["high"], float(hi))
            rec["low"] = min(rec["low"], float(lo))
            rec["files"].append(pdf.name)
    daily = [days[k] for k in sorted(days)]
    anomalies = []
    for r in daily:
        r["vwap"] = round(r["amount_hkd"] / r["shares"], 4) if r["shares"] else None
        r["label"] = "公开披露"
        if r["vwap"] and not (r["low"] - 1e-6 <= r["vwap"] <= r["high"] + 1e-6):
            anomalies.append({"date": r["date"], "vwap": r["vwap"], "low": r["low"], "high": r["high"],
                              "note": "均价不在所报高低价之间；原件数值不自洽，原因不作推断", "label": "计算"})
    total = {"days": len(daily), "shares": sum(r["shares"] for r in daily),
             "amount_hkd": round(sum(r["amount_hkd"] for r in daily), 2), "label": "计算"}
    total["amount_yi_hkd"] = round(total["amount_hkd"] / 1e8, 2)
    out = {"total": total, "last_buyback": daily[-1]["date"] if daily else None, "anomalies": anomalies,
           "skipped_files": skipped, "daily": daily}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{total['days']} 个回购日，{total['shares']:,} 股，{total['amount_yi_hkd']:,.2f} 亿港元；最后一笔 {out['last_buyback']}")
    print(f"数据异常 {len(anomalies)} 处" + ("：" + "、".join(x["date"] for x in anomalies) if anomalies else ""))
    if skipped:
        print(f"跳过 {len(skipped)} 份非回购报表")


if __name__ == "__main__":
    main()
