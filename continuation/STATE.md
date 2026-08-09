# Where this stands

Measured on this commit, LH, `cw`. "Weave" means `across = (2m)(2n)`,
`within = 0`, `stray = 0`, `broken = 0`.

Since the relabel composition landed (see ALGORITHM.md §2), **every level in
every measured case below aligns natively on the k-based groups** — the same
grouping, pairing and mask rule as level 1, at every depth. The
direction-family rescue and mask re-laying never fire any more (they remain as
a safety net); `bands mirrored` still fires on 3×3, and seeding regularly
short-circuits deep levels.

## Working

| case | levels | per-level ext H · V | gaps H / V | notes |
| --- | --- | --- | --- | --- |
| 2×2 `[1, 1, −1]` | 3/3 | `(40,10)·(170,150)`; `(150,100)·(150,100)`; `(30,110)·(30,110)` | `56.30/56.81`; `56.80/65.94`; `58.87/58.23` | L2 mirrored, L3 seeded |
| 2×2 `[1, 1, −1, −1, −1, −1, −1]` | 7/7 | see `docs/README.md` | 56.30–67.84 | seeded + mirrored, ~56 s |

Extensions stay near previously successful scales because each level's first
seed is level 1's own solution for that level's k, with a small bounded search
around it (see ALGORITHM.md, "Seeding from earlier levels"). Without seeding,
the full search can find valid weaves with needlessly long arms.

A level-3 `k = −1` ring now has the **mixed-set bands** a real `k = −1` twist
has (one arm from every set per band — compare level 1 at `k = −1`), because
the engine's own `k` machinery finally sees an honest starting stitch at that
depth. Under the old, uncomposed relabel it aligned into a `k = +1`-shaped
ring with clean audit numbers — gaps, crossings and stray all read fine on a
visibly wrong stitch. Rendered sequence:
<https://claude.ai/code/artifact/94547328-6fbf-4c2e-9729-45155199399c>

Level 1 intentionally differs from the legacy one-level generator: it now starts
at L0's purple crossing anchors. The regression invariant is geometric instead:
every new `_4/_5` strand starts exactly at its `_2/_3` parent's outermost
cross-band crossing. `test_level1_anchor.py` checks that invariant directly.

## Not working

**Max-k beyond level 1** — `k = 2` on 2×2 (the max-k special case). Its bespoke
level-1 layout is defined in grid coordinates and is not reproduced on a
rotated ring. Measured: `[1, 1, 2]` level 3 reaches `across 12/16, stray 2`;
`[2, 1]` level 2 only `4/16` with 820px arms. Known gap, predates this work.

**Cross-level masks** — none exist. Within a ring the weave is correct, but a
new ring lies entirely *on top of* the one below it; nothing decides who passes
over whom between levels. Deliberately out of scope so far.

## Regression check before you commit

Run the focused L0 → L1 anchor test first:

```bash
python3 -m unittest continuation.test_level1_anchor -v
```

Then run the 2×2 deep-chain audit. Every row must report `WEAVE`, with 16/16
cross-band crossings, 0 within-band crossings, 0 stray masks and 0 broken arms:

```bash
python3 continuation/make_diagrams.py --m 2 --n 2 --ks 1 1 -1 -1 -1 -1 -1
```

## Traps that cost time before

- **The relabel must be composed.** `build_level_relabel` without
  `prev_virtual_to_real` assumes the previous level's map was the identity —
  true only at level 2. From level 3 on the uncomposed map reverses each
  horizontal pair's spatial order, the k-based groups span ~55° and the level
  silently aligns into the wrong twist. Thread each level's `virtual_to_real`
  into the next `add_continuation_level`.
- **Every audit number can read clean on a wrong stitch.** The uncomposed
  relabel produced rings with perfect gaps, 16/16 crossings, 0 stray, 0 broken
  — as a k=+1-shaped ring, when the level's k was −1. Band *composition*
  matters: a `k = −1` ring's bands mix the sets; set-aligned bands at a
  `k = −1` level are themselves a red flag.
- **Gaps do not tell you a level is good**, nor the crossing total on its own
  (read `within` too), nor masks landing on real crossings (the wrong
  checkerboard half inverts who goes over), nor `stray 0` (the unmasked half
  resolves by the arms' draw order in the strand list — the audit's `broken`
  column counts over/under alternation failures directly).
- **The mirror must pin both bands.** Pinning only the receiver and letting
  the donor re-search "to its own optimum" lets the re-search escape the
  bounded grid the donor's combo came from: on 2×2 seven levels deep, H left
  its seeded (50, 40) for a long-armed (20, 170) while V sat pinned at
  (50, 40), and the level shipped tagged `bands mirrored` with two different
  bands. Both sides are pinned to the donor combo now.
- **The engine's gap rule** is between *consecutive strands in the group's
  order* for 3+ strands, not between the members of an outside-in pair. Pairing
  only decides which strands share an extension value.
- **`on_config_callback` fires only for valid configurations**, so anything
  built on it silently misses the rest of the search space.
- **The engine's CPU search runs in a process pool**, so monkeypatching
  `_evaluate_cpu_combo_chunk` in the parent does nothing. Patch
  `_search_combo_space_cpu` or `_compute_pair_angle_range`, which are called in
  the parent.
- **openstrandstudio is gitignored** and does not survive a new container.
  Re-clone and symlink before rendering (or use the Qt-free SVG route the
  stitch-sheet skill's `render_strands.py` demonstrates).

## Published write-ups

- Rendered L1–L3 sequence of 2×2 `[1, 1, −1]` (this commit's geometry):
  <https://claude.ai/code/artifact/94547328-6fbf-4c2e-9729-45155199399c>
- The window, the anchor and the masks, with before/after sequences:
  <https://claude.ai/code/artifact/0a66c084-8c46-451b-add0-37dce9a782e2>
- Earlier: repeat mechanism `07e05849-5a62-4044-953b-4afbc69c8aa9`, weld and
  crossing points `ca165b7c-9315-40d5-823a-5efe97f7f55a`, anchor A/B
  `af245f67-fb8d-4ec6-8a8e-f43d34c647a7`, twist sequences
  `e93fd1dd-6615-4415-9417-a2103dc389c3`, deep chain
  `1ad9cc4d-0796-432a-86f3-b16b91ac3a58` (predates these fixes; its conclusion
  that the third level cannot close is now out of date).
