# MxN Strand Studio

Create M × N strand patterns, generate continuations from a k offset, and align strands using the original MxN algorithms and [OpenStrandStudio](https://github.com/ysetbon/OpenStrandStudio) renderer.

## Open the site

**[Launch MxN Strand Studio](https://mxn-strand-studio.topspin-tech-0568.chatgpt.site)**

The hosted site is currently private and requires authorized access. The Starting stitch page works on its own: without a local renderer, the pattern is generated in the browser and drawn by [OpenStrandJS](https://github.com/ysetbon/OpenStrandJS), the browser port of the OpenStrandStudio renderer. Animal markers and strand labels are drawn in the browser too. The Continuation page needs the Python renderer running on your computer (below); when it is running, the site uses it for everything.

## Run locally

You need Python, PyQt5, the dependencies used by the MxN and OpenStrandStudio applications, and both source checkouts. Place OpenStrandStudio beside this repository:

```text
projects/
├── mxn/
└── OpenStrandStudio/
```

If OpenStrandStudio is elsewhere, set `OPENSTRANDSTUDIO_DIR` to its checkout directory.

From the MxN repository, start the web workspace:

```bash
python site/serve_native.py
```

Open [the local workspace](http://127.0.0.1:5174/) or the hosted site above. On Windows, you can also double-click `site/start-native.cmd`. If your browser blocks the hosted site's connection to the local renderer, use the local workspace.

To run the original desktop application:

```bash
python src/main.py
```

## Workflow

1. **Starting stitch:** choose dimensions, handedness, strand colors, and the k offset. Toggle PNG animal markers and strand labels independently.
2. **Continuation:** click **Generate starting stitch** to open a separate page carrying over your settings. Continuation uses the k-based endpoint pairing and extends outer strands as required by the desktop generator.
3. **Alignment:** preview automatic or custom horizontal/vertical angle ranges, set extension search limits, adjust individual opposite pairs, and click **Align strands**. Partial results are identified separately from successful alignments.
4. **Export:** download OpenStrandStudio JSON or a native PNG at 1×, 2×, or 4× resolution, with a transparent or white background.

Use **Back to Starting stitch** to return to the original setup and canvas. The Continuation page also includes a starting-stitch reference and a before/after alignment comparison.

## Rendering and limitations

- With the local renderer, patterns use the actual OpenStrandStudio strand classes, masks, layer order, and Qt rendering pipeline.
- Without it, `site/dist/generators.js` (a port of the four starting-stitch generators, checked against the Python output by `site/test_browser_generators.py`) builds the same JSON and a vendored copy of OpenStrandJS's `strand-renderer.js` draws it. Animal markers, strand labels and Continuation still run in Python.
- GPU batch workflows and exporting every alignment attempt remain in the desktop application.
- Workflow snapshots are temporary. Reloading the browser or restarting the renderer requires generating the pattern again.

See [the web workspace README](site/README.md) for implementation details and verification notes.

## Guided alignment search (experimental)

The alignment step normally evaluates every pair-extension combination against every angle. `src/mxn_guided_search.py` adds an optional guided mode: the grid is split into cells (one extension band per opposite pair × one third of the angle window), a policy picks the next cell from what earlier cells produced, and only that cell is evaluated — with the same validity math. If the guided phase finds nothing within its budget, the exhaustive search runs as before, so results are never worse than "not found".

Three policies are available:

- `jev` — [TypeSafe's Jev model](https://typesafe.ai) as the loop's strategist. It sees the group's geometry (strand order, each strand's start, target and extension direction, every gap at the best or closest configuration with its status against the 56–69 px rule) and each round answers, in one request: a strategy (`refine` a step from the anchor, `explore` a new band cell, or `stop`), per pair `shorter` / `keep` / `longer` plus a step size, the angle third, and band preferences for exploring. A refine evaluates the exact neighbourhood around the proposed point; an explore evaluates the top-ranked unexplored cell. Needs `pip install typesafe-sdk` and `TYPESAFE_API_KEY` in the environment; if either is missing the exhaustive search runs.
- `jev-bands` — the first Jev policy: only a band per pair, the angle third and a "stop now?" `Noul`. Kept for comparison.
- `heuristic` — deterministic, offline: probes around the closest result so far, shortest arms first. Useful as a baseline.

### Clearance rule

Independently of the search mode, every `_4/_5` arm must start at least half a strand width (23 px) before its first crossing with any arm of the other group, so it visibly passes over or under that group's first–last pair instead of starting inside it. Candidates that break this are rejected before the gap check, in the exhaustive and guided searches alike, and the Jev policy is told each strand's shortfall so it knows which pair to lengthen. Because H is solved before V, `align_level_parallel` (used by the web workspace and `run_stitch.py`) re-checks the H arms against the final V arms and solves H again against them when V's outer pair moved too much. Set `MXN_ALIGNMENT_CLEARANCE` to a pixel value to change the rule, or to `0` for the previous behaviour; the multi-level `mxn_continuation_next` pipeline keeps its own crossing checks and runs with the rule off.

**From the web workspace:** on the Continuation page, open **Jev guided search**, paste your TypeSafe key and click **Save key**. The key goes only to the renderer running on your computer (`127.0.0.1`); the browser never stores it and the page only ever shows its last four characters. **Use Jev for alignment** switches the guided search on or off. **Remember key on this computer** saves it to `~/.mxn/jev.json` (readable only by your user account; override the path with `MXN_JEV_CONFIG`) so it survives renderer restarts; turn it off, or click **Forget key**, to delete that file. Without remember, the key lasts until the renderer stops. A `TYPESAFE_API_KEY` environment variable is used when no key was pasted. The alignment status line reports whether Jev ran, how many calls and tokens it used, or that it found nothing and the full search ran.

Enable with `MXN_ALIGNMENT_GUIDED=jev` (or `jev-bands`, `heuristic`) for the desktop app, web workspace and CLIs, or pass `guided_search=` to `align_horizontal_strands_parallel` / `align_vertical_strands_parallel`. Tuning: `MXN_ALIGNMENT_GUIDED_BUDGET` (fraction of combos, default 0.35), `MXN_ALIGNMENT_GUIDED_BANDS` (default 4), `MXN_ALIGNMENT_GUIDED_ROUNDS` (default 40), `MXN_ALIGNMENT_GUIDED_PATIENCE` (rounds without improvement before stopping, default 3), `MXN_ALIGNMENT_GUIDED_STOP` (stop probability threshold, default 0.6). Alignment results carry a `search` entry describing which mode ran, how many combos it evaluated and, for Jev, how many calls and input tokens it used.

## Tests

From the repository root:

```bash
python -m unittest discover -s site -p test_native_renderer.py
python -m unittest discover -s site -p test_browser_generators.py   # needs node
```

The Qt-free SVG renderer used by the documentation and the stitch-sheet skill (`src/oss_svg.py`) is pixel-checked against OpenStrandStudio's own drawing with:

```bash
python -m unittest continuation/test_oss_svg.py
```

The native renderer tests cover native rendering, animal-marker toggles, rotation indicators, continuation snapshots, manual extensions, and agreement with the original alignment solver.
