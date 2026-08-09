# Multi-level continuation: how a stitch grows ring after ring

This folder is a handoff package. It explains how the generic continuation works,
how to produce a `ks = [x, y, z, …]` diagram sequence for any size, and exactly
where the algorithm currently gives out.

- **[ALGORITHM.md](ALGORITHM.md)** — what the pipeline does, step by step, and why
  each rule is the shape it is.
- **[DIAGRAMS.md](DIAGRAMS.md)** — producing frame sequences and audits for any
  `m`, `n`, `ks`.
- **[STATE.md](STATE.md)** — what works, what does not, and the open threads.
- **`algorithm/`** — a snapshot of the two modules at this commit, for reading.
  The live copies are `src/mxn_continuation_next.py` and
  `src/mxn_continuation_render.py`; **edit those, not these.** The snapshot is
  here so the folder can be read on its own.
- **`make_diagrams.py`** — the driver. It imports from `src/`, so it always runs
  the live algorithm.
- **[docs/](docs/README.md)** — rendered sequences: per-level SVG frames (they
  display right on GitHub) and self-contained HTML sheets, drawn by
  **`render_svg.py`** straight from the strand JSON, no OpenStrandStudio needed.

## The one-paragraph version

A starting stitch is a core (`_1`) with a ring of arms around it (`_2/_3`).
`build_level_one` retracts those arms to their outermost cross-band crossings
(the purple points), grows `_4/_5` there, and aligns the new ring. An aligned
ring is geometrically another starting-stitch ring, so the same constructor is
reused at every depth through a virtual `_2/_3` relabel. That recursion is the
whole idea; everything else keeps the relabel, masks and search honest as the
stitch grows.

## Quick start

```bash
# audit only — fast, no rendering
python3 continuation/make_diagrams.py --m 2 --n 2 --ks 1 1 -1

# with rendered frames (needs openstrandstudio on the path)
python3 continuation/make_diagrams.py --m 2 --n 2 --ks 1 1 -1 --render --out /tmp/seq
```

Every level prints one line:

```
L3 k=-1 ok/ok  gap 58.87/58.23  ext (30,110)(30,110)
       across 16/16  within 0  masks 8  stray 0  broken 0   k-based groups   WEAVE
```

`across` is the number of crossings between the ring's two bands, `within` the
number inside a band (must be zero — a band's arms are parallel), `stray` the
number of masks sitting on a pair that does not actually cross, and `broken`
the number of arms whose crossings fail to alternate over/under. A healthy
`m × n` ring has `(2m)(2n)` across, `0` within, `0` stray, `0` broken. **Gaps
alone do not tell you a level is good**; see ALGORITHM.md, "Why crossings and
not gaps".
