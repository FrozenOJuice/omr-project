import json
import math

from PIL import Image

mark = json.load(open('data/ubc_template/mark.json'))
qs = {q['id']: q for page in mark['pages'] for q in page['questions']}

img = Image.open('/tmp/blank_prod_back.png').convert('L')
px = img.load()
W, H = img.size


def fill_ratio(cx, cy, r=7):
    # approximate scoreMask: full disk of radius r, count dark (<128) pixels
    total = dark = 0
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                total += 1
                if 0 <= x < W and 0 <= y < H and px[x, y] < 128:
                    dark += 1
    return dark / total if total else 0.0


for qid in ['F1', 'F2', 'F3', 'F4']:
    q = qs[qid]
    ratios = [(o['label'], fill_ratio(o['x'], o['y'])) for o in q['options']]
    ratios_sorted = sorted(r for _, r in ratios)
    max_gap = max(ratios_sorted[i + 1] - ratios_sorted[i] for i in range(len(ratios_sorted) - 1))
    print(f"{qid}: min={ratios_sorted[0]:.3f} max={ratios_sorted[-1]:.3f} maxGap={max_gap:.3f}")
    high = [(l, r) for l, r in ratios if r > ratios_sorted[0] + 0.1]
    if high:
        print(f"   above-baseline options: {high}")
