# Rendered sequences

Drawn straight from the strand JSON by [`../render_svg.py`](../render_svg.py) —
no OpenStrandStudio needed. Geometry, draw order and masks are exactly what the
algorithm produced; regenerate any sequence with:

```bash
python3 continuation/render_svg.py --out continuation/docs/2x2-seven-twists 1 1 -1 -1 -1 -1 -1
```

Self-contained HTML sheets (open in a browser):

- [`2x2_three_twists.html`](2x2_three_twists.html) — `ks = [1, 1, −1]`
- [`2x2_seven_twists.html`](2x2_seven_twists.html) — `ks = [1, 1, −1, −1, −1, −1, −1]`

## 2×2 · lh · cw · `ks = [1, 1, −1, −1, −1, −1, −1]`

Seven continuation rings, every level a complete weave (16/16 crossings across
the bands, none within a band, no stray masks, every arm alternating
over-under). All frames share one viewport, so the stitch genuinely grows.
Whites/greens are the horizontal sets, indigos the vertical sets; each set
keeps its colour outward, so any strand can be followed from the core to the
seventh ring.

| level | k | ext H · V | gap H / V | how it landed |
| --- | --- | --- | --- | --- |
| L1 | +1 | (40, 10) · (170, 150) | 56.30 / 56.81 | k-based groups |
| L2 | +1 | (150, 100) · (150, 100) | 56.80 / 65.94 | bands mirrored |
| L3 | −1 | (30, 110) · (30, 110) | 58.87 / 58.23 | seeded |
| L4 | −1 | (40, 40) · (70, 30) | 57.03 / 56.76 | seeded |
| L5 | −1 | (70, 30) · (70, 30) | 67.84 / 57.07 | bands mirrored |
| L6 | −1 | (60, 30) · (60, 30) | 63.62 / 57.12 | bands mirrored |
| L7 | −1 | (30, 110) · (30, 110) | 58.73 / 57.95 | seeded |

### Level 1 — first

![level 1](2x2-seven-twists/frame_L1.svg)

### Level 2 — ring 2

![level 2](2x2-seven-twists/frame_L2.svg)

### Level 3 — ring 3

![level 3](2x2-seven-twists/frame_L3.svg)

### Level 4 — ring 4

![level 4](2x2-seven-twists/frame_L4.svg)

### Level 5 — ring 5

![level 5](2x2-seven-twists/frame_L5.svg)

### Level 6 — ring 6

![level 6](2x2-seven-twists/frame_L6.svg)

### Level 7 — ring 7

![level 7](2x2-seven-twists/frame_L7.svg)
