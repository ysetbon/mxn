# MxN native web workspace

The redesigned controls use **OpenStrandStudio's actual Qt renderer** when the local renderer is running. Without it, the Starting stitch page falls back to the browser (see *Browser rendering* below). `native_renderer.py` calls the existing MxN `RenderMixin._ensure_canvas_prepared` and `_generate_image_in_memory`: the original loader creates `Strand`, `AttachedStrand`, and `MaskedStrand` objects and draws them in the original canvas order.

## Run

From the MxN repository: `python site/serve_native.py`, then open http://127.0.0.1:5174/.

Alternatively, double-click `start-native.cmd` in this directory. The renderer must remain running. Python with PyQt5 and the MxN and OpenStrandStudio checkouts are required. OpenStrandStudio is located in the sibling `OpenStrandStudio` directory by default; set `OPENSTRANDSTUDIO_DIR` to override it. Existing repository sources and assets are used directly and are not modified.

The privately hosted Site connects to this same loopback renderer. A browser may ask permission to access the local network or block that connection. The local URL serves the identical UI and avoids cross-origin access. Rendering from another computer requires the native renderer and source checkouts on that computer; the hosted page does not run Qt in Cloudflare.

## Browser rendering

When `/api/health` does not answer, `app.js` switches to the browser engine:

- `dist/generators.js` ports `mxn_lh.py`, `mxn_rh.py`, `mxn_lh_strech.py` and `mxn_rh_stretch.py`. `test_browser_generators.py` checks that it produces the same document as Python for every m, n in 1–10, both hands, standard and stretch (colors aside, which the site repaints from the palette).
- `dist/vendor/strand-renderer.js` is a verbatim copy of OpenStrandJS's standalone renderer, pinned to the commit in its header, with Paper.js 0.12.18 in `dist/vendor/paper-full.min.js`. Update it by copying a newer revision and changing that commit.
- Preview and PNG export (1×/2×/4×, transparent or white) use the same bounds as `RenderMixin._calculate_strands_bounds`, with shadows off as in the desktop preview. JSON export is the generated history document.
- `dist/markers.js` ports `EmojiRenderer` (`src/mxn_emoji_renderer.py`): endpoint slots and perimeter order, mirrored base labels rotated by k, animal PNGs cropped to their visible pixels, strand labels between endpoint and animal, the signed-k rotation indicator, and freeze/unfreeze of assignments for Continuation. Its images are the 50 animals of each set, copied from `src/emoji_assets/` to `dist/emoji/<set>/`. `test_browser_markers.py` (needs node and PyQt5) draws with the Python renderer through a recording painter and checks every marker, label box and indicator part against `computeMarkerLayout` for m, n in 1–6, many k, both hands, standard and stretch. Fonts are the browser's, so glyph shapes and label box sizes follow the installed fonts, as they do in Qt.
- Continuation is disabled in this mode and needs the local renderer. **Reconnect renderer** switches to it once it is running.

The hosted Site has to be republished from `dist/` to pick up these files.

## Animal markers

The Animal markers switch controls the original `EmojiRenderer` PNG overlay and original endpoint pairing/rotation logic, independently of strand labels. Select Fluent 3D, system PNG, Twemoji, OpenMoji, or JoyPixels using the installed original asset sets. The same setting is used for both preview and PNG export. Missing original assets retain the desktop renderer's own fallback behavior.

## Exports and scope

- JSON retains the original OpenStrandStudio history, geometry, masks, and custom strand colors.
- PNG export is rendered again by Qt at 1x, 2x, or 4x, with transparent or white background and the selected marker/label settings. The UI does not resize a screenshot for export.
- SVG export was removed: the previous browser approximation did not preserve native rendering.
- Shadow behavior matches the MxN desktop preview (disabled there), rather than inventing different settings.
- CPU alignment, angle ranges, and pair extensions are available on the Continuation page. GPU batches and exporting every solver attempt remain in the desktop application.
- The loopback server accepts only the local workspace and this private Site's origin. Requests use bounded input sizes, validated generation options, a bounded queue, and an image pixel budget. It exposes no arbitrary file writes or Python evaluation API. Qt calls run serially on the main thread.

## Verification

Run `python -m unittest test_native_renderer -v` in this directory. Tests exercise all six generator variants, validate real native strand classes, compare marker-on/off output without changing the strand document or center pixels, and compare PNG bytes against images rendered by an actual `MxNGeneratorDialog` for animals on and off with strand names enabled.

## UX direction

Keep the canvas separate from settings, group M/N and handedness together, label palette swatches H/V, open a dedicated Continuation page after generating a starting stitch, and move resolution/background options into the export dialog. Animal markers and strand labels are independent controls. Keep the last successful preview while another render runs and disable export when settings are outdated.

The existing hosting manifest identifies the published Site. Reuse its project ID when publishing; do not create a replacement Site. Source is included under `site/` in the MxN repository; the Sites service also has its own deployment source repository. Only the web UI is hosted. The Python bridge uses the local repositories.

The headless desktop comparison skips only checkbox/radio cosmetic proxy styles to avoid their shared-style teardown issue on Windows; the strand loading and drawing methods are not mocked.

Rotation fixes: the Windows offscreen renderer registers installed Segoe UI fonts so signed k values and labels render as real glyphs. Handedness controls match the desktop mapping (LH/CW, RH/CCW). Changing k or handedness refreshes the native preview automatically; stale requests cannot replace a newer preview.

## Starting stitch → Continuation
Generate starting stitch now navigates to a separate Continuation page. The original setup and result remain available through Back and the reference image. Continuation uses the desktop generator with the same dimensions, handedness, signed k, colors and artwork settings; as in the desktop app, it extends the outer strands when needed.

The page supports automatic first-strand or average/Gaussian angle ranges, custom H/V ranges, geometry-based angle guides, maximum/step extension search, manual opposite-pair extensions, original CPU H/V alignment, partial-result reporting, before/after comparison, and PNG/JSON export of the displayed geometry. Marker assignments are frozen by strand identity, matching desktop alignment. GPU batch and attempt-file exports remain desktop-only. No separate ratio setting exists in the inspected desktop alignment UI.

Snapshots are held by the running local renderer (64 recent versions). Restarting the renderer or reloading the browser requires generating again. The hosted UI continues to require this local service.
