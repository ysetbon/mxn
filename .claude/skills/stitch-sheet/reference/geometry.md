# Stitch geometry — constants, closed forms, costs

Everything below was measured from the generator's own output and confirmed
against the aligner's own searches. Load this when the sheet needs to explain
*why* an angle is what it is, or when a search needs to be predicted rather than
brute-forced.

## Constants

| Quantity | Value | Where it comes from |
|---|---|---|
| strand width | 46 px | `strand_width` default in the align functions |
| stroke | 4 px | strand JSON |
| grid pitch | 112 px | distance between neighbouring ribbons |
| half pitch | 56 px | the offset between the two arm columns |
| gap floor | 56 px | `min_gap = strand_width + 10` |
| gap ceiling | 69 px | `max_gap = strand_width * 1.5` |
| angle grid | 0.01° | `_build_angle_values` quantises with `int(angle*100)` |
| combo guard | 10 M | `_get_alignment_combo_limit` (CPU) |

Ranking inside the aligner: smallest **first-last distance** (= `(strands − 1) ×
gap`) first, within a 2 px tie band the lowest **gap variance**, and for a
single-gap group the least total extension.

## Layout of a stitch

Sets are numbered horizontal `1 … n`, then vertical `n+1 … n+m`. For m = 1 the
2n horizontal continuation starts sit in two columns 120 px apart, rows 112 px
apart, the right column offset +56 px in y. The vertical pair's two starts
differ by `(−56, 112n + 8)`.

Strand counts (verified 1×1 … 3×3 and 1×1 … 1×8):

```
base 3(m+n) + base masks 2mn + continuation 2(m+n) + continuation masks 2mn
total = 5(m+n) + 4mn
```

## k = 0 — the box

Both align passes return `preserve_continuation`; the generated continuation is
already the answer. Every continuation runs straight along its own axis:

```
horizontal  _4 → 0°   _5 → 180°          (both hands)
vertical LH _4 → +90° _5 → −90°
vertical RH _4 → −90° _5 → +90°
horizontal bar = 112·m + 60 px    vertical bar = 112·n + 60 px
box footprint  = 112·(m+1) × 112·(n+1) px
```

## k = +1, m = 1 — the twist, in closed form

With `A = e(R_i) + e(L_i)` (a right/left pair on one row) and `B = e(L_i) +
e(R_i+1)` (across to the next row), equal spacing g forces

```
-(120 + A)·sin θ + 56·cos θ = g
 (120 + B)·sin θ - 168·cos θ = g
```

Subtracting kills g, adding gives it:

```
tan θ = 224 / T,          T = 240 + A + B
g     = (56·T − 112·δ) / √(224² + T²),   δ = B − A
ladder: e(R_i) = e₁ + (i−1)·δ,  e(L_i) = A − e(R_i),  e₁ = (A − (n−1)·δ)/2
vertical pair: |−56·sin θ − (112n + 8)·cos θ| = g
```

The optimum: spread = `(2n−1)·g` and `g ≥ 56`, so drive g to the floor and take
the least deformation, which empties the last arm (`e(R_n) = 0`, i.e.
`A = (n−1)·|δ|`). Verified optima (gap 56.005, uniform to machine precision):

| n | H · LH | V · LH | extensions (outermost pair first) |
|---|---|---|---|
| 1 | −129.96° | 140.04° | 0 |
| 2 | −141.28° | 117.15° | 39 0 |
| 3 | −146.68° | 108.50° | 67 0 34 |
| 4 | −150.11° | 104.01° | 90 0 60 30 |
| 5 | −152.57° | 101.27° | 109 0 82 27 55 |
| 6 | −154.46° | 99.42° | 127 0 102 25 76 51 |
| 7 | −155.98° | 98.09° | 143 0 119 24 95 48 72 |
| 8 | −157.23° | 97.09° | 158 0 136 23 113 45 90 68 |

RH mirrors: `H_RH = −(180 + H_LH)`, `V_RH = −V_LH`.

1 × 1 is 50.04° off the axis, **not** 45° — at 45° the gap would be 45.25 px,
under the floor.

### Using it to skip the brute force

Because the extension parameter only slides a `_4/_5` start along its `_2/_3`
direction, the same geometry can be applied directly to the strands and the
aligner then run with `max_pair_extension=0` and a tight
`custom_angle_min/max` window — it validates and applies in well under a second
for any n. Only do this where the closed form is known to hold (m = 1, k = +1);
otherwise let the search run.

## Two exact symmetries — forecast instead of searching

Measured across the full 8 × 8 sweep at k = −1, both hands (63 sizes, 126 runs),
to a 0.02° tolerance:

```
transpose    V_LH(m, n) = H_LH(n, m) − 90      63/63 exact
             V_RH(m, n) = −V_LH(m, n)          63/63 exact
hand mirror  H_RH(m, n) = 180 − H_LH(m, n)     62/63 — breaks at 2 × 2
```

The transpose one is the useful one: a stitch's vertical group is its transpose's
horizontal group turned 90°, so **every angle in a grid follows from the
horizontal LH search alone** — one independent quantity per (m, n) rather than
four. On an 8 × 8 grid that is a 4× cut in search cost.

**The hand mirror is not safe to derive from.** At 2 × 2 the two hands settle on
different optima — LH lands on angle 162.82°, spread 172.03, gap variance 0.465,
extensions [0, 70]; RH on 22.07° (not the mirrored 17.18°), spread 170.41,
variance 0.516, extensions [10, 30]. The two spreads are 1.6 px apart, inside the
aligner's own 2 px tie band, so both are legitimate and the tie broke differently
per hand. The geometry is symmetric; the *search* is not guaranteed to be. Derive
RH only with a verification pass, or search it.

Extensions transpose too (`V_ext(m, n) == H_ext(n, m)`) wherever both groups
actually solved; where one of them fell back the extension vectors diverge, so
only trust the extension half on solved groups.

Note the hand mirror here is `H_RH = 180 − H_LH`, **not** the `−(180 + H_LH)`
that holds for m = 1, k = +1 — the relation is k-dependent, so verify it per
sweep rather than carrying it across k.

To exploit this, search `align_horizontal_strands_parallel` for LH only, then
apply the derived angle and extensions to the other three groups instead of
re-searching. Validate on a size already computed the slow way before trusting a
whole sweep to it.

## Where k = −1 stops solving

Same sweep: a group whose pair count is ≥ 7 never aligned — the aligner returned
`is_fallback` with gaps around 150 px, far outside the `[56, 69]` band. This is
not a search-budget artifact: raising `max_pair_extension` from 200 to 600 made
1 × 8 *worse* (gap 69.8 → 79.3), and a 40× finer grid did not clear it either.
Pair counts ≤ 5 always solved; 6 solved except where both dimensions were 6+.
When a group solves at k = −1 it solves cleanly (gaps 57–61 px); there is no
ambiguous middle.

## Search cost

`combos = (ext_max / step + 1) ** pairs`, throughput ≈ 900 combos/s (3 workers).

| pairs | step 10 | time | step 20 | step 40 |
|---|---|---|---|---|
| 2 | 441 | 0.5 s | 121 | 36 |
| 3 | 9 261 | 10 s | 1 331 | 216 |
| 4 | 194 481 | ~4 min | 14 641 | 1 296 |
| 5 | 4.1 M | ~75 min | 161 051 | 7 776 |
| 6 | 85.7 M | refused | 1.77 M | 46 656 |
| 8 | 3.8 e10 | refused | 214 M | 1.68 M |

Calibrated at 1×3, k=+1: step 20 reproduces step 10 exactly; step 25 drifts
1.2°; step 40 drifts 2° and widens the gap from 56.6 to 59.2.
