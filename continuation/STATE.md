# Where this stands

Measured on this commit, LH, `cw`. "Weave" means `across = (2m)(2n)`,
`within = 0`, `stray = 0`.

## Working

| case | level | k | gap H / V | extensions | verdict |
| --- | --- | --- | --- | --- | --- |
| 2×2 `[1, 1, −1]` | 1 | 1 | 56.43 / 56.41 | (80, 60)(80, 60) | weave |
| | 2 | 1 | 56.58 / 56.60 | (90, 70)(90, 70) | weave |
| | 3 | −1 | 56.48 / 56.43 | (80, 60)(80, 60) | weave, regrouped + masks re-laid |
| 2×2 `[1, 1, 1]` | 3 | 1 | 56.90 / 56.90 | (20, 190)(20, 190) | weave, regrouped + masks re-laid |
| 2×2 `[1, −1]` | 2 | −1 | 56.13 / 56.11 | (30, 100)(30, 100) | weave |
| 3×3 `[1, 1, 1]` | 3 | 1 | 56.81 / 56.96 | (30, 120, 130)(50, 40, 30) | weave, regrouped |

Level 1 is bit-identical to the published twist across every `k` on 2×2 and 3×3
— same angle, same extensions, same gaps, all 16 groups. That is the regression
test to re-run after touching anything (see below).

## Not working

**3×3 `[1, 1, −1]` at level 3** — `across 34/36`, `within 0`, `stray 0`, gaps
56.61 / 56.37, extensions `(10, 30, 20)(90, 50, 70)`. Two crossings short and
the bands still disagree. The band-copy was attempted: H is the near band, and
its `(10, 30, 20)` is **never a valid configuration for V**, so the copy could
not be applied.

`_mirror_extensions` was then extended to try the far band as donor when the
near one cannot donate. **That change is committed but not yet verified on
3×3** — a 3×3 level-3 run is 10–50 minutes. It is a no-op on 2×2, where the
bands already agree, and 2×2 was re-verified after it landed. Verifying it is
the obvious next task:

```bash
python3 continuation/make_diagrams.py --m 3 --n 3 --ks 1 1 -1 --out /tmp/seq
```

**Level 4 onward** — infeasible on both sizes, and for a different reason from
level 3.

| case | level 4 | gaps | across |
| --- | --- | --- | --- |
| 2×2 `[1, 1, −1, −1]` | fb/fb | 147.97 / 147.97 | 0/16 |
| 3×3 `[1, 1, −1, −1]` | fb/fb | 161.95 / 286.01 | 2/36 |

On 2×2 the rescue does fire and finds a clean split (78.51° of k-based fan down
to 18.10° of family fan), and the retry finds nothing either. Sweeping every
heading at every extension on a 0–600px grid: **0 of 441 combos have a valid
configuration**, for the direction families and the k-based groups alike. Not a
grouping problem, not a window problem, not an anchor problem.

The binding constraint is likely that middle strands cannot extend
(`allow_inner_extensions=False`), so they must already lie on the required
parallel lines, which gets harder as the ring distorts. **Unproven** — the
cheapest test is to re-run the level-4 sweep with `allow_inner_extensions=True`
and see whether any combo becomes valid. If that is the answer, the fix is a
policy question (how much inner extension is acceptable) rather than a search
one.

Note the stray-mask counts at level 4 (8 on 2×2, 18 on 3×3, i.e. all of them)
are a *consequence* of the broken ring, not a separate fault: `_relay_masks`
correctly declines to re-pair when no arrangement puts every mask on a crossing.

**2×2 at `k = 2`, level 3** — `across 0/16`. That is the max-k case, whose
bespoke level-1 layout is defined in grid coordinates and has never been
reproduced on a rotated ring. Known gap, predates this work.

**Cross-level masks** — none exist. Within a ring the weave is correct, but a
new ring lies entirely *on top of* the one below it; nothing decides who passes
over whom between levels. Deliberately out of scope so far.

## Regression check before you commit

Level 1 must not move. Cheapest form:

```bash
for k in -1 1 2; do python3 continuation/make_diagrams.py --m 2 --n 2 --ks $k; done
for k in -2 -1 1 2 3; do python3 continuation/make_diagrams.py --m 3 --n 3 --ks $k; done
```

Expected level-1 values, for comparison:

| size | k | angle H | ext H | gap H |
| --- | --- | --- | --- | --- |
| 2×2 | −1 | 162.82 | (0, 70) | 57.34 |
| 2×2 | 1 | −162.82 | (80, 60) | 56.43 |
| 2×2 | 2 | 47.38 | (40, 0) | 56.69 |
| 3×3 | −2 | −34.80 | (40, 30, 0) | 57.59 |
| 3×3 | −1 | 165.60 | (10, 60, 40) | 56.59 |
| 3×3 | 1 | −168.97 | (140, 100, 120) | 56.86 |
| 3×3 | 2 | 22.53 | (20, 120, 90) | 58.06 |
| 3×3 | 3 | −133.45 | (50, 40, 0) | 56.76 |

## Traps that cost time before

- **Gaps do not tell you a level is good.** 2×2 `[1, 1, 1]` level 3 once
  reported `ok/ok` at 56.47 / 56.60 on a ring carrying 8 of its 16 crossings.
- **Nor does the crossing total on its own.** A ring reaches `(2m)(2n)` through
  the wrong pairs just as easily — same-set arms crossing each other. Always
  read `within` too.
- **Nor do masks landing on real crossings.** Several arrangements do that while
  covering a different half of the checkerboard, which inverts who goes over.
- **The engine's gap rule** is between *consecutive strands in the group's
  order* for 3+ strands, not between the members of an outside-in pair. Pairing
  only decides which strands share an extension value. Modelling it the other
  way produces confident, wrong conclusions.
- **`on_config_callback` fires only for valid configurations**, so anything
  built on it silently misses the rest of the search space.
- **The engine's CPU search runs in a process pool**, so monkeypatching
  `_evaluate_cpu_combo_chunk` in the parent does nothing. Patch
  `_search_combo_space_cpu` or `_compute_pair_angle_range`, which are called in
  the parent.
- **openstrandstudio is gitignored** and does not survive a new container.
  Re-clone and symlink before rendering.

## Published write-ups

- The window, the anchor and the masks, with before/after sequences:
  <https://claude.ai/code/artifact/0a66c084-8c46-451b-add0-37dce9a782e2>
- Earlier: repeat mechanism `07e05849-5a62-4044-953b-4afbc69c8aa9`, weld and
  crossing points `ca165b7c-9315-40d5-823a-5efe97f7f55a`, anchor A/B
  `af245f67-fb8d-4ec6-8a8e-f43d34c647a7`, twist sequences
  `e93fd1dd-6615-4415-9417-a2103dc389c3`, deep chain
  `1ad9cc4d-0796-432a-86f3-b16b91ac3a58` (predates these fixes; its conclusion
  that the third level cannot close is now out of date).
