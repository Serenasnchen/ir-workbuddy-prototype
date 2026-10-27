"""Convert the report .docx to PDF with Microsoft Word (COM via PowerShell), then rasterise pages for review."""
import subprocess
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]


def to_pdf(docx: Path) -> Path:
    pdf = docx.with_suffix(".pdf")
    ps = (
        "$w = New-Object -ComObject Word.Application; $w.Visible = $false; "
        f"$d = $w.Documents.Open('{docx}'); $d.ExportAsFixedFormat('{pdf}', 17); $d.Close($false); $w.Quit()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    return pdf


def rasterise(pdf: Path, outdir: Path, dpi=70):
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("page-*.png"):
        old.unlink()
    doc = pymupdf.open(pdf)
    for i, page in enumerate(doc):
        page.get_pixmap(dpi=dpi).save(outdir / f"page-{i + 1:02d}.png")
    return len(doc)


if __name__ == "__main__":
    docx = Path(sys.argv[1])
    pdf = to_pdf(docx)
    n = rasterise(pdf, ROOT / "report" / "pages", dpi=int(sys.argv[2]) if len(sys.argv) > 2 else 70)
    print(pdf, n, "pages")
