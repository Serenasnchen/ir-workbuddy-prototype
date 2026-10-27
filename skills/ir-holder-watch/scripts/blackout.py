"""Compute the share-repurchase blackout window before a results board meeting (HKEX Listing Rule 10.06(2)(e)).

Usage:
  python blackout.py --board 2026-11-18 [--last-buyback 2026-10-15] [--announce 2026-11-18]

Rule summary (verify against the current Listing Rules with Compliance before relying on it):
an issuer may not repurchase shares on the Exchange during the 30 days immediately preceding the earlier of
(a) the board meeting date for approving results and (b) the results publication deadline, until the results
announcement is published. The output separates the rule window [计算] from what was observed [公开披露];
it never infers why repurchases stopped.
"""
import argparse
import json
from datetime import date, timedelta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True, help="board meeting date YYYY-MM-DD")
    ap.add_argument("--announce", help="results announcement date (default: same as board date)")
    ap.add_argument("--last-buyback", help="last observed repurchase date from next-day disclosure returns")
    a = ap.parse_args()
    board = date.fromisoformat(a.board)
    announce = date.fromisoformat(a.announce) if a.announce else board
    start = board - timedelta(days=30)
    out = {
        "rule": "上市规则第 10.06(2)(e) 条：审议业绩的董事会会议（或业绩公布期限，以较早者为准）前 30 日起至业绩公布日止，不得在联交所回购股份",
        "rule_window": {"start": start.isoformat(), "end": announce.isoformat(), "label": "计算"},
        "note": "日历以合规部门为准；本工具只做提醒",
    }
    if a.last_buyback:
        last = date.fromisoformat(a.last_buyback)
        out["observed"] = {"last_buyback": last.isoformat(), "label": "公开披露",
                           "gap_days_before_window": (start - last).days,
                           "comment": "仅陈述事实，不推断回购停止的原因"}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
