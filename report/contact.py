import sys
from pathlib import Path
from PIL import Image
pages = sorted(Path('report/pages').glob('page-*.png'))
start, count, cols = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
sel = pages[start:start + count]
ims = [Image.open(p) for p in sel]
w, h = ims[0].size
rows = (len(ims) + cols - 1) // cols
sheet = Image.new('RGB', (cols * w, rows * h), 'white')
for i, im in enumerate(ims):
    sheet.paste(im, ((i % cols) * w, (i // cols) * h))
sheet.save(sys.argv[4])
print(sheet.size)
