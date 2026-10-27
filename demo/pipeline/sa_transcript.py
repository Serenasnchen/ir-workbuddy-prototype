"""Parse a StockAnalysis transcript page (saved HTML) into turns.

Output turns: [{"speaker": str, "title": str, "text": str}]
StockAnalysis 文字稿为第三方整理，非官方逐字稿；发言人归属可能有误，引用前以官方录音为准。

Usage (debug): python -I demo/pipeline/sa_transcript.py <saved.html>
"""
import html
import re
import sys


def _clean(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def parse_html(text):
    i = text.find('id="transcript-panel-full"')
    if i < 0:
        return []
    text = text[i:]
    blocks = re.split(r'<div class="border-t border-sharp pt-5[^"]*">', text)[1:]
    turns = []
    for b in blocks:
        m = re.search(r'<div class="text-lg font-bold[^"]*">(.*?)</div>', b, re.S)
        speaker = _clean(m.group(1)) if m else ""
        m2 = re.search(r'<div class="text-sm italic text-muted">(.*?)</div>', b, re.S)
        title = _clean(m2.group(1)) if m2 else ""
        sents = [_clean(s) for s in re.findall(r'<span class="transcript-sentence[^"]*"[^>]*>(.*?)</span>', b, re.S)]
        turns.append({"speaker": speaker, "title": title, "text": " ".join(s for s in sents if s)})
    return turns


def parse_file(path):
    with open(path, encoding="utf-8") as f:
        return parse_html(f.read())


if __name__ == "__main__":
    for n, t in enumerate(parse_file(sys.argv[1])):
        print(f"[{n}] {t['speaker']} | {t['title']}\n{t['text']}\n")
