---
name: stitch-sheet
description: Generate a complete published reference sheet (artifact) for MxN stitches — starting stitch, continuation, alignment angles, gaps, extensions, table, chart and every diagram — for a given m range, n range, k and hand(s). Use when the user asks for the result/details/diagrams/angles of stitches by size, e.g. "m=1to8 n=1to8 k=-1 lh rh", "give me the twist stitches for 2x2..4x4 at k=2", "make a box stitch artifact for k=0", or any request to document mxn patterns as an artifact. Handles both k = 0 (box, no alignment) and k != 0 (twist, real alignment search).
---

# Stitch sheet

Turns `m`, `n`, `k`, hand(s) into one published artifact that documents the
whole family: starting stitch and finished stitch drawings, the aligner's angles
and gaps, a size table, an angle chart, and the rules.

Everything comes from the repo's own code in `src/` — never re-implement the
generator or the aligner, and never hand-draw a pattern.

## 1. Read the request

Extract: **m range**, **n range**, **k**, **hands** (default both), and whether
the user named the sheet. `m` counts vertical ribbons, `n` horizontal ones.
LH always runs `cw` and RH always `ccw` — never mix.

Valid k depends on size: square (`m == n`) allows `-(m-1) … m`; otherwise
`-(m+n-1) … (m+n)`. Sizes where the requested k is out of range are skipped by
`run_stitch.py` (exit code 3) — collect them and say so in the artifact and in
your reply. `run_stitch.py --check --m M --n N` prints a size's range.

Name it for what it is unless the user says otherwise: **k = 0 → "Box
Stitches"**, **k ≠ 0 → "Twist Stitches"** (add the k, e.g. "Twist Stitches ·
k = −1").

## 2. Check the environment once

```bash
python -c "import numpy" || pip install numpy      # the aligner's search needs it
```
PyQt5 is NOT needed — the continuation modules import cleanly without it.

## 3. Size the search before running anything

The horizontal search costs `(ext_max/step + 1) ** pairs` combinations, where
`pairs` is half the group's strand count (for m = 1, `pairs = n`); the vertical
group is the same with `m`. Measured throughput: **≈ 900 combos/s** on 3 CPU
workers. The aligner refuses more than 10 M combos outright.

At the default grid (0–200 / 10 px): 441 combos at 2 pairs (0.5 s), 9 261 at 3
(10 s), 194 481 at 4 (~4 min), 4.1 M at 5 (~75 min), 85.7 M at 6 (refused).
`--ext-step auto` (the default) therefore picks the finest step that fits
`--budget` (400 k combos ≈ 7 min per group) and records the choice.

Calibration worth knowing: at 1×3 k=+1, **step 20 reproduces step 10 exactly**,
while step 25 drifts ~1.2° and step 40 ~2°, with looser gaps. So coarsening to
20 is safe; past that, say in the sheet that the grid was coarsened.

Tell the user the estimated cost before launching a big sweep (an 8×8 grid is
64 sizes × 2 hands = 128 runs). Run long sweeps with `run_in_background: true`
and check on them, rather than blocking.

## 4. Run every stitch

```bash
S=.claude/skills/stitch-sheet/scripts
OUT=/tmp/.../stitch-run          # use the session scratchpad
for m in 1 2 3; do for n in 1 2 3; do for h in lh rh; do
  python $S/run_stitch.py --m $m --n $n --k -1 --hand $h --out $OUT
done; done; done
```

Each run writes `<tag>_start.json`, `<tag>_final.json` and `<tag>.json`
(summary: orders, mask lists, per-strand geometry, alignment result, search
settings, timings). One line per run is printed — check for `FAIL` or
`fallback`, and report them honestly rather than hiding them.

**On `fallback`, reach for `solve_stitch.py` before reaching for a finer grid.**
A fallback usually means the aligner's ±20° angle window did not contain a
solution, not that none exists — at k = −1 that is what happens to every 1 × n
above 1 × 3. Same arguments, same output files, plus `in_aligner_window` per
group so a solution the search could never have reached stays labelled:

```bash
python $S/solve_stitch.py --m 1 --n 5 --k -1 --hand lh --out $OUT
python $S/solve_stitch.py --m 1 --n 5 --k -1 --hand rh --out $OUT \
       --mirror-of $OUT/lh_1x5_k-1.json      # RH is LH reflected — mirror, don't re-search
```

It solves rather than samples, so it returns uniform gaps at the 56 px floor in
under a second where the combo search needs minutes. `reference/geometry.md`
has the closed form it uses and the measurements behind the window diagnosis.

At **k = 0** both alignment passes return `preserve_continuation` with the
message *"k=0: _4/_5 alignment matches continuation exactly, no adjustment
needed"*. That is expected: the box needs no alignment. The same happens for the
special max-k case (`k == m+n` with `m ≠ n`).

## 5. Build and publish the sheet

```bash
python $S/build_sheet.py --results $OUT --out $OUT/sheet.html \
  --title "Twist Stitches · k = −1" \
  --eyebrow "mxn generator · reference"
```

It composes header, anatomy (naming key + one worked size), the five build
passes, an alignment section, the angle chart (only when angles actually move
across sizes), the size table and the gallery of every stitch. `--label
twist|box` overrides the wording; `--intro` overrides the lede.

Then look at it before publishing — screenshot with the headless browser and
read the image:

```bash
/opt/pw-browsers/chromium-1194/chrome-linux/chrome --headless --no-sandbox \
  --disable-gpu --hide-scrollbars --default-background-color=FFFFFFFF \
  --window-size=1200,1500 --screenshot=$OUT/check.png file://$OUT/sheet.html
```

Publish with the Artifact tool (favicon 🧵 for twists, 🔲 for boxes). If the user
asked to update an existing sheet, pass its `url`.

## 6. Non-negotiable correctness checks

- **Mask paint order.** Base masks must be drawn UNDER the `_4/_5` strands. The
  renderer classifies a mask by its member strands (`first_selected_strand` /
  `second_selected_strand`), never by splitting its name — once set numbers reach
  4 or 5, names like `5_3_4_2` are base masks that a string test gets wrong.
  Paint order is: base strands → base masks → `_4/_5` → `_4/_5` masks.
- **Colours.** The generator randomises colours past set 2, so the renderer
  re-colours deterministically: horizontal sets by index, vertical sets (detected
  from geometry) in indigo shades. Never present a randomised colour as meaningful.
- **Both hands.** RH mirrors LH. For m = 1, k = +1 the relation is exactly
  `H_RH = −(180 + H_LH)` and `V_RH = −V_LH` — a good sanity check, but verify per
  run rather than assuming it for every k.
- **Report what was skipped**: out-of-range k, coarsened grids, failed or
  fallback alignments, anything not run.

## Files

- `scripts/run_stitch.py` — one stitch: generate → align → summary JSON
- `scripts/solve_stitch.py` — same outputs, solved from the closed form instead
  of searched. Use it wherever `run_stitch.py` reports `fallback`
- `scripts/alignment_model.py` — the gap test and its inverse, standalone
- `scripts/predict_swirl.py` — a swirl straight from m and n: no generator, no
  probe, no search. `predict_swirl.py --m 13 --n 4`. Three cases cover all 64
  sizes of the 8 × 8 grid — 1 × 1 (which has no k = −1), the n ≥ 2 interior, and
  the n = 1 boundary, which is solved to a corner floor set by `--min-corner`
- `scripts/build_sheet.py` — results directory → artifact HTML
- `scripts/render_strands.py` — JSON → SVG (paint order, palette, labels)
- `assets/template.html` — page shell: CSS, layout, chart hover script
- `reference/geometry.md` — constants, the m = 1 closed form, cost table
