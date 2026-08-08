# Making a `ks = [x, y, z, …]` diagram

## The audit

```bash
python3 continuation/make_diagrams.py --m 2 --n 2 --ks 1 1 -1
```

One `k` per level. `--ks 1 1 -1` means: first twist at `k = 1`, second at
`k = 1`, third at `k = -1`. Also takes `--hand lh|rh` and `--direction cw|ccw`.

```
=== 2x2 lh cw ks=[1, 1, -1]   (a healthy ring: across 16, within 0, stray 0) ===
  L1 k=1  ok/ok  gap   56.43/56.41   ext (80, 60)(80, 60)
        across  16/16  within  0  masks  8  stray  0  broken  0   k-based groups   WEAVE
  L2 k=1  ok/ok  gap   56.58/56.60   ext (90, 70)(90, 70)
        across  16/16  within  0  masks  8  stray  0  broken  0   k-based groups   WEAVE
  L3 k=-1 ok/ok  gap   56.48/56.43   ext (80, 60)(80, 60)
        across  16/16  within  0  masks  8  stray  0  broken  0   regrouped, masks re-laid   WEAVE
```

Exit status is 0 only when every level is a weave, so it drops straight into a
loop or a CI check.

### Reading a row

| field | meaning |
| --- | --- |
| `ok / fb / FAIL` | H and V search outcome. **`ok` does not mean the level is good** |
| `gap` | mean perpendicular gap in each band; the search targets `[56, 69]` |
| `ext` | the winning extension per outside-in pair, measured **from the purple points** (ALGORITHM.md §4) |
| `across` | crossings between the ring's two bands. Must be `(2m)(2n)` |
| `within` | crossings inside a band. Must be `0` — a band's arms are parallel |
| `masks` | masks on this level. Half the crossings get one; the rest come from draw order |
| `stray` | masks sitting on a pair that does not cross. Must be `0` |
| `broken` | arms whose crossings do not alternate over/under. Must be `0` — `stray 0` alone does not guarantee the weave, because the unmasked half depends on the arms' draw order |
| last column | which corrections fired: `regrouped`, `bands mirrored`, `masks re-laid` |

The last three columns are the ones that matter. A level can report `ok/ok` with
textbook gaps on a ring that is not a weave — see ALGORITHM.md §7.

## The frames

```bash
python3 continuation/make_diagrams.py --m 2 --n 2 --ks 1 1 -1 \
    --render --out /tmp/seq
```

Writes one PNG per stage — starting stitch, then each twist — plus a JSON report.
All frames in a run share one viewport, so they read as a progression rather than
each being cropped to its own content.

Rendering needs **openstrandstudio** importable (`mxn_continuation_render.py`
raises a clear error otherwise). It is gitignored here, so in a fresh container:

```bash
git clone <openstrandstudio> /workspace/openstrandstudio
ln -s /workspace/openstrandstudio ~/openstrandstudio
```

Set `QT_QPA_PLATFORM=offscreen` for headless runs; the driver's renderer falls
back to a batch canvas when the real main window is unavailable and prints which
it used.

## The purple-point diagram

```bash
python3 continuation/make_anchor_diagram.py --m 2 --n 2 --k 1
```

Draws the source ring with **purple** at each arm's outermost crossing —
extension 0 — and **red** at where the arm ended before retraction. Writes
`anchor-<m>x<n>-k<k>.svg` next to the script. This is the picture to reach for
when explaining what an extension number is measured from.

## Comparing two variants

To A/B a change, run the same case twice with the pipeline switched, sharing one
viewport so the rows line up. The switches are module-level and resolved at call
time:

```python
import mxn_continuation_next as NX

NX.ANCHOR = "flat"                              # 52px setback instead of purple points
NX._plan_family_rescue = lambda *a, **kw: None  # k-based groups only
```

Restore them in a `finally`. Render both stage lists in **one**
`render_sequence` call and split the returned frames, so both rows get the same
bounds.

## Running several in parallel

Each case is one process, so shells are the unit of parallelism:

```bash
for ks in "1 1 -1" "1 1 1" "1 -1"; do
  python3 continuation/make_diagrams.py --m 2 --n 2 --ks $ks \
      --out /tmp/seq > "/tmp/seq/2x2_${ks// /_}.log" 2>&1 &
done
wait
```

Rough costs on this container: 2×2 to level 3 is about 1–2 minutes, 3×3 to level
3 is 10–50 minutes depending on contention. The search itself already uses a
process pool, so more than three or four concurrent cases stops helping.
