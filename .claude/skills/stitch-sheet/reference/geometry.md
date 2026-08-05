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

## k = −1, m = 1 — the swirl, in closed form

There is one, and it covers every n. Put the group's shared angle t against the
only coordinate that separates the lines, `W = x·sin t − y·cos t`; every gap the
aligner measures is `W_i+1 − W_i`, and extending a strand slides its start along
a fixed direction, so W is linear in that strand's pair extension. Reading order
`i = 0 … 2n−1`, pair index `0, 1, …, n−1, n−1, …, 1, 0`, `s = sin t`, `c = cos t`:

```
both ends   g = -88 s - 144 c - s·e_1 - c·e_0
odd  gaps   g =  (120 + e_j + e_j+1)·s +  56 c
even gaps   g = -(120 + e_j + e_j+1)·s - 168 c
middle      the same, with (e_j + e_j+1) replaced by 2·e_n-1
```

Same 120 / 56 / 168 frame as the k = +1 form above — k changes which continuation
joins which, not the frame they sit in. Verified against the generator's own
geometry for n = 2 … 8: max deviation 5 × 10⁻¹³ px.

Because the pair index is a palindrome, the interior equations come in identical
pairs: only **n** of the 2n−1 gap equations are distinct, against n+2 unknowns
(e_0 … e_n-1, g, t). So every size has a **two-parameter family** of exact
solutions — fix t and g and the extensions follow with no search:

```
U =  (g -  56 c)/s - 120       e_n-1 = (U or V)/2        by the parity of n-1
V = -(g + 168 c)/s - 120       e_j   = (U or V) - e_j+1  for j = n-2 … 1
                               e_0   = (-88 s - 144 c - s·e_1 - g)/c
```

Driving g to the 56 px floor minimises the aligner's first two ranking criteria
at once; least total extension is then its own third. That canonical pick, LH:

| n | H · LH | V · LH | spread | extensions (outermost pair first) |
|---|---|---|---|---|
| 2 | 141.063° | 70.177° | 168.03 | 14.63 19.22 |
| 3 | 141.279° | 77.378° | 280.05 | 29.92 39.39 0 |
| 4 | 146.675° | 80.819° | 392.07 | 25.02 67.12 0 33.56 |
| 5 | 150.109° | 82.803° | 504.09 | 22.81 89.81 0 59.87 29.94 |
| 6 | 152.573° | 84.091° | 616.11 | 21.60 109.50 0 82.13 27.38 54.75 |
| 7 | 154.464° | 84.988° | 728.13 | 20.86 127.14 0 101.71 25.43 76.29 50.86 |
| 8 | 155.980° | 85.648° | 840.15 | 20.38 143.26 0 119.38 23.88 95.50 47.75 71.63 |

Gaps are uniform at 56.010 px, gap variance ~10⁻²⁶. `scripts/solve_stitch.py`
does this end to end in about half a second per size, against the ~4 min the
combo search needs at 4 pairs.

That table is the *best* member of each family, not the only one. Two recorded
alternatives at 1 × 4, steered by hand and applied with `--h-angle/--h-ext`:

| | H · LH | H · RH | V · LH | ext (H) | mean gap | var | spread | Σ ext | in window |
|---|---|---|---|---|---|---|---|---|---|
| solved | 146.675° | 33.325° | 80.819° | 25.02 67.12 0 33.56 | 56.010 | ~0 | 392.07 | 125.7 | yes |
| picked 1 | 149.253° | 30.747° | 72.645° | 25.3 81.9 6.4 43.2 | 58.108 | 0.226 | 406.76 | 156.8 | **no** |
| picked 2 | 148.642° | 31.358° | 73.176° | 20.80 73.79 6.76 40.27 | 56.539 | 9.5e-6 | 395.78 | 141.6 | yes |

All three valid, all palindromic in their gaps. RH is the exact mirror in every
case (`180 − H_LH`, `−V_LH`, extensions unchanged, gaps equal to 10⁻⁹ px).

The pair is instructive about what each parameter buys. Picked 1 sits 2.6°
above the solved angle, which widens the gap to 58.11 and — because its
outermost pair is extended 25.3 px — swings the ±20° window down to
108.57–148.57°, past its own angle. Picked 2 comes back 0.6° to 148.642° and
evens the gaps out at 56.54: inside the window again, 15 px less total
extension, 11 px tighter overall.

So **the angle sets the gap; the extensions only decide how evenly that gap is
shared.** Holding picked 1's 149.253° and moving two pairs about 1.5 px
(81.9 → 82.9, 6.4 → 4.9) drops the variance from 0.226 to 2.7 × 10⁻⁴ at an
unchanged 58.11 px mean. Choosing an angle by eye costs nothing in evenness —
it is the gap size being chosen.

(Picked 2's variance is 9.5 × 10⁻⁶ rather than ~0 only because its extensions
are recorded to 2 dp; at full precision it is uniform. The gaps span
56.535–56.543, i.e. 8 thousandths of a pixel.)

### Carrying a pick to another size

Read this way, each pick is **two lengths in px**: the gap it runs at, and how
far the shallowest arm is lifted off zero. The solved configuration is the case
where that lift is zero — which is exactly why it sits on the edge of the band
and is the least-extension member. Carrying both lengths unchanged fixes the
angle at any other size, because the lift rises monotonically from the band edge
to a peak before falling back to zero at the far edge (a different arm empties
at each end, so search the *rising* branch only). The vertical group is the same
with its single extension in place of the lift.

Carried from 1 × 4 to 1 × 5:

| | H · LH | H · RH | V · LH | mean gap | spread | Σ ext |
|---|---|---|---|---|---|---|
| picked 1 | 153.031° | 26.969° | 76.225° | 58.110 | 522.99 | 260.0 |
| picked 2 | 151.861° | 28.139° | 76.659° | 56.539 | 508.85 | 228.7 |

Both uniform to 10⁻⁸ and valid. The construction reproduces 1 × 4's vertical
angles to four decimals from the extension alone (72.6450 and 73.1759 against
the recorded 72.645 and 73.176), which is the only check available for it.

**This is a construction, not a derivation.** Two hand-picks at one size do not
determine a law. Two other carrying rules — the same number of degrees above the
band edge, or the same fraction of the band width — give angles within **0.36°**
of these and are equally valid; nothing in the geometry prefers one over
another. Both 1 × 5 picks fall outside the aligner's window, but so does its
solved configuration: nothing above 1 × 4 is reachable by that search at all.

`H_RH = 180 − H_LH` and `V_RH = −V_LH` hold **exactly** here, and not as a
coincidence: RH's geometry is LH's reflected about x = 1232 — measured 0.0 px
deviation, index for index in the horizontal group and in reverse order in the
vertical — and a reflection takes t to 180 − t while leaving the extensions
alone. Mirror RH rather than re-searching it (see the 2 × 2 disagreement below,
which is exactly what re-searching costs you).

## The corners — which side the outside pair runs

Not a strand-to-strand clearance. Every crossing between the horizontal and
vertical groups is masked and intended, so how deeply one overlaps another says
nothing about whether the stitch reads correctly. Measuring end-to-strand
distance and calling the overlaps defects was wrong, and the "corner-safe"
values derived that way were meaningless — they have been removed.

What matters at a corner is **which side of it the outside pair runs**. Each
group is a band of parallel lines whose edges are its outside pair, reading
indices 0 and last. The vertical continuations leave the woven block at fixed
corners that do not move when either group is aligned. A configuration is
corner-safe when the horizontal outside pair passes **outside** those corners
rather than cutting across inside them, so the measurement is the signed offset
of each corner from the nearer outer line, positive when outside.

Measured in that one direction only. The reverse is not a corner: at m = 1 the
vertical group is a single pair spanning one gap, so nearly every horizontal
start lies far outside its band and the number means nothing.

| size | source | margin | corner |
|---|---|---|---|
| 1 × 4 | solved | **+0.700** | `1_4`, outside |
| 1 × 4 | picked 1 | −4.256 | `1_4`, inside |
| 1 × 4 | picked 2 | **+0.706** | `1_4`, outside |
| 1 × 5 | solved | −3.666 | `1_4`, inside |
| 1 × 5 | picked 1 | −9.689 | `1_4`, inside |
| 1 × 5 | picked 2 | **−0.236** | `5_5`, inside |

1 × 4's configurations clear by about 0.7 px. 1 × 5's do not, and the margin is
what separates them — its picked 2 sits a quarter of a pixel inside, the outer
line effectively passing through the corner, against 3.7 px for solved and
9.7 px for picked 1.

`solve_stitch.py` reports the margin on every run and notes when the outside
pair cuts inside. `--min-corner N` searches both groups together for a margin of
at least N, which it has to: the margin moves with all four free parameters and
no per-group pass can see it.

### Where the margin comes from, and where it runs out

Hold the gaps uniform at the 56 px floor and the margin rises steadily with the
shared angle, so each size has exactly one angle where it crosses zero — the
least-turned configuration whose outside pair clears its corner. That crossing
is what the picked-2 rows aim at:

| n | crossing | margin there | Σ ext | best margin attainable at the floor |
|---|---|---|---|---|
| 4 | 146.674° | +0.699 | 125.70 | +7.237 (at 155.582°) |
| 5 | 153.258° | +0.000 | 243.57 | +3.847 (at 157.660°) |
| 6 | 158.006° | +0.000 | 424.04 | +1.233 (at 159.260°) |
| 7 | — | — | — | **never clears at the floor** |

The room runs out as n grows: the best margin available anywhere in the band
falls +7.24 → +3.85 → +1.23, and by 1 × 7 no angle at the floor puts the
outside pair outside the corner at all. Above that size the gap would have to
come off the floor, which costs spread, or the corner has to be accepted inside.

### 1 × 6, picked 2

```
H · LH 158.0065°  ext 3.5418 127.7393 40.4697 105.9219 62.2871 84.1045
V · LH  78.3165°  ext 35.2704
gaps 56.010 uniform, spread 616.11, vertical gap 61.850, margin +0.0008 outside
```

RH mirrors exactly: `H 21.9935°`, `V −78.3165°`. The vertical is your 1 × 5
vertical carried across on its own extension (35.2704 px at gap 61.850), a rule
that reproduces the 1 × 5 angle to four decimals.

### 1 × 5, picked 2

The configuration that gets closest to the corner, arrived at by hand:

```
H · LH 153.034°  ext 13.0371  97.1387  16.4454  70.2409  43.3432   gaps 56.010 uniform
V · LH  75.882°  ext 35.2704                                       gap  61.850
```

Spread 504.09 — the minimum, since spread is (2n−1)·g and g is at the floor.
RH mirrors exactly: `H 26.966°`, `V −75.882°`, same extensions.

### It is not m = 1 or k = −1 specific

The model is just the gap arithmetic, so the same solver runs on any size and
any k. Spot-checked against known answers: at 1 × 3, k = +1 it returns
−146.679° with extensions 67.13 / 0.02 / 33.57, reproducing the k = +1 closed
form's −146.68° and [67, 0, 34]. At k = −1 it improves sizes the sweep *did*
solve — 2 × 2 goes from spread 172.03, variance 0.465 to spread 168.03,
variance 10⁻²⁶ — and 3 × 3 and 2 × 3 also land on uniform 56.010 px gaps. Those
four sizes are what has been checked; a full 8 × 8 re-sweep has not been run.

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

**The hand mirror is not safe to derive from *a search*.** The geometry mirrors
exactly — RH is LH reflected about x = 1232, measured to 0.0 px — so mirroring a
*solution* is sound and is what `solve_stitch.py --mirror-of` does. What is not
sound is expecting two independent searches to agree. At 2 × 2 the two hands
settle on different optima — LH lands on angle 162.82°, spread 172.03, gap variance 0.465,
extensions [0, 70]; RH on 22.07° (not the mirrored 17.18°), spread 170.41,
variance 0.516, extensions [10, 30]. The two spreads are 1.6 px apart, inside the
aligner's own 2 px tie band, so both are legitimate. The geometry is symmetric;
the *search* is not guaranteed to be. Derive RH only with a verification pass, or
search it. (Those figures are from the 0.5° pass; refining the grid moves the
numbers but does **not** close the gap — see "The angle step is not a free knob"
below for the actual cause, which is the hand-dependent angle window.)

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

### What does *not* transfer: k → −k with a hand swap

Tempting, and wrong. Mirroring reverses the rim traversal, so `mirror(LH, k)`
looks like it should be `(RH, −k)` and a k = +1 sweep would come free with a
k = −1 one. Tested on the raw continuation directions *before* alignment (which
removes search noise from the question) at 2×2, 3×3, 2×3, 3×2 and 1×3: only 2–4
of the 8–12 continuations coincide, and **no reflection maps one set onto the
other** — not θ → 180 − θ, not θ → −θ.

k re-pairs which free end joins which, and reflection does not undo that
pairing, so +k and −k are different stitches rather than two views of one.
Generate each k.

What makes it look plausible is a coincidence at 2×2, where
`V_LH(k=+1) + V_LH(k=−1) = 179.99`. It breaks at every other size (3×3 → 182.24,
2×3 → 177.78, 1×3 → 186.11).

Note also that k = +1's hand mirror is `H_RH = −(180 + H_LH)` while k = −1's is
`H_RH = 180 − H_LH`, and the transpose law that is exact 63/63 at k = −1 is only
approximate at k = +1 (off ~1–2° at 2×3 and 3×2). Re-derive these per k.

## Where k = −1 stops solving — and why it is the window, not the geometry

Observed first as: a group whose pair count is ≥ 7 never aligned, and at m = 1
nothing above 1 × 3 aligned either — `is_fallback`, gaps up to 170 px, far
outside the `[56, 69]` band. Raising `max_pair_extension` from 200 to 600 made
1 × 8 *worse* (gap 69.8 → 79.3), and a 40× finer grid did not clear it.

**Exact solutions exist at every one of those sizes.** The blocker is the
aligner's search *domain*. Re-asked as an exact feasibility question — is there
any point at all in the space the search was allowed to visit — over the m = 1
family, LH horizontal:

| size | any solution inside the window | on the 10 px extension grid | what actually blocked it |
|---|---|---|---|
| 1 × 2 | 123.62–153.67° | 123.62–153.67° | nothing, the sweep found it |
| 1 × 3 | 141.32–153.67° | 141.32–151.42° | nothing, the sweep found it |
| 1 × 4 | 146.67–151.42° | **147.62–147.72°** | the angle step. One extension vector works, [30, 80, 0, 40], across 0.10° — and the sweep stepped 0.5°. |
| 1 × 5 … 1 × 8 | none | none | the angle window |

The window is `first strand's direction to its target ± 20°`, and it is
recomputed per combo **after** that strand has been extended — so extending the
outermost pair swings it down. 1 × 5 needs 150.11°, which its window contains at
e₀ = 0 (113.67–153.67°); but reaching 150.11° needs e₀ = 22.8 px, and at that
extension the window has moved to 109.03–149.03° and no longer contains it. The
same trap at 1 × 6, 1 × 7, 1 × 8. No angle step and no extension grid can close
that — the domain is empty, so `is_fallback` was the honest answer to the
question the aligner was asked.

Use `scripts/solve_stitch.py` for these instead of refining the search. It works
off the closed form above rather than the window, and it reports
`in_aligner_window` per group so a solution the aligner could never have reached
is visible as such rather than silently mixed in with ones it could.

(The 57–61 px gaps first measured for solved groups were a separate artifact, of
the 0.5° angle grid — re-searched at 0.1° they tighten to roughly 56.1–56.9 px,
against a 56 px floor.)

## The angle step is not a free knob

`--angle-step 0.5` looks harmless and is not. The aligner quantises angles at
0.01°, and an optimum that falls between the steps of a coarser grid simply
cannot be represented, so the search settles for a worse one.

Caught by checking a k = +1 run against the closed-form values: 1 × 2 at k = +1
should be `H_LH = -141.28°, gap 56.005, ext [39, 0]`; at `--angle-step 0.5` the
search returned `-145.00°, gap 57.35`. Refining to 0.01° puts the vertical group
back on the reference value exactly (117.15°) and the horizontal within 0.05 px
of the optimal spread.

The same error runs through a whole k = -1 sweep done at 0.5°. Re-searching the
solved sizes at 0.1°, holding the extension grid fixed:

| | groups | mean spread gain |
|---|---|---|
| square sizes (angle grid alone) | 16 | **+5.39 px** |
| non-square (angle + finer vertical ext) | 40 | +3.18 px |

Worst case measured was 4 × 4, gap `58.71 -> 56.78`, spread gain **13.52 px**.
Every group tested improved; none were unchanged.

Cost is roughly **16x** per 5x refinement in angle step, not the ~5x a naive
linear model predicts — budget accordingly. Refining a fallback run is wasted
work: it has no valid solution to converge to.

Note `run_stitch.py` takes one `--ext-step` for both groups, so on a non-square
size, re-running with the horizontal step also refines the vertical extension
grid. Only square sizes isolate the angle effect cleanly.

### The 2 x 2 hand disagreement is not resolution

`H_LH + H_RH = 180` holds 13/14 on the refined sizes but stays broken at 2 x 2
(183.99, versus 184.89 at 0.5°). Refining the angle step, refining the extension
grid and raising the extension ceiling all fail to close it. The cause is the
`first_strand` angle window: it spans ±20° around an initial angle that differs
per hand, so the mirrored optimum can sit outside the window RH ever searches.
Derive RH by mirroring LH (see H6 above); do not expect its own search to agree.

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
