"""
Render MxN continuation JSON exactly the way main.py draws it.
==============================================================

The strand layers in this project are not simple lines: a set's ribbon is a
stack of `_1`/`_2`/`_3`/`_4`/`_5`/... strands with rounded attachment caps, and
the over/under weave comes from `MaskedStrand` entries that paint one strand
clipped to another. Only OpenStrandStudio knows how to draw that, so this
module does not re-implement any of it — it drives the application's own draw
path, the same one `main.py` uses:

    load_strands_from_data(...) -> apply_loaded_strands(canvas, ...)
    canvas.show_grid = False; show_control_points = False
    canvas.shadow_enabled = False; should_draw_names = False
    strand.should_draw_shadow = False   (every strand)
    bounds = content bbox + BOUNDS_PADDING
    RenderUtils.setup_painter(painter, enable_high_quality=True)
    painter.scale(scale); painter.translate(-bounds.x(), -bounds.y())
    for strand in canvas.strands: strand.draw(painter, skip_painter_setup=True)
    if canvas.current_strand: canvas.current_strand.draw(...)
    (optional) composite the emoji/name overlay from its own transparent layer

That sequence is lifted from `MxNGeneratorDialog._export_json_to_image` /
`_render_current_canvas_image` in `mxn_dialog_render_mixin.py`, which is what
`main.py` runs when it exports a pattern.

Because `canvas.strands` is drawn in list order, the JSON's strand order *is*
the layer order — including the masks that create the weave. Nothing here
sorts or re-stacks anything.

Canvas
------
`create_render_canvas()` prefers the real `MainWindow` canvas, so the render is
literally main.py's canvas. When the full UI stack cannot be imported (headless
box without QtMultimedia's audio libs, CI, a container), it falls back to
`batch_rendering._BatchRenderCanvas`, whose drawing configuration mirrors
`StrandDrawingCanvas.__init__` (num_steps, max_blur_radius,
control_point_base_fraction, distance_multiplier, curve_response_exponent,
enable_third_control_point, ...). Both canvases feed the identical draw loop.

Usage
-----
    from mxn_continuation_render import render_json_to_file
    render_json_to_file(json_text, "stitch.png", scale_factor=4.0)

CLI::

    python3 mxn_continuation_render.py stitch.json stitch.png --scale 4
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def _ensure_paths():
    """Put this repo and a sibling openstrandstudio checkout on sys.path.

    Same resolution order as `mxn_cad_ui.py`: look for `openstrandstudio/src`
    next to the repo, then one level up.
    """
    oss_parent = None
    oss_src = None
    for candidate_root in (_ROOT, os.path.dirname(_ROOT)):
        candidate_src = os.path.join(candidate_root, "openstrandstudio", "src")
        if os.path.isdir(candidate_src):
            oss_parent = candidate_root
            oss_src = candidate_src
            break
    for path in filter(None, (_HERE, _ROOT, oss_parent, oss_src)):
        if path not in sys.path:
            sys.path.insert(0, path)
    return oss_src


_OSS_SRC = _ensure_paths()


def _require_openstrandstudio():
    if _OSS_SRC is None:
        raise RuntimeError(
            "OpenStrandStudio was not found. This module renders through the "
            "application's own draw path, so it needs an `openstrandstudio/src` "
            f"checkout next to {_ROOT} or one directory above it."
        )


from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtWidgets import QApplication

from ui_utils import _get_active_history_state


__all__ = [
    "BOUNDS_PADDING",
    "ensure_qapplication",
    "create_render_canvas",
    "load_json_into_canvas",
    "calculate_strands_bounds",
    "render_canvas_image",
    "render_json_to_image",
    "render_json_to_file",
]


# Matches MxNGeneratorDialog.BOUNDS_PADDING and batch_generate_mxn.BOUNDS_PADDING.
BOUNDS_PADDING = 100


def ensure_qapplication():
    """Return the process QApplication, creating an offscreen one if needed."""
    app = QApplication.instance()
    if app is None:
        os.environ.setdefault("QT_LOGGING_RULES", "*=false")
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication(sys.argv[:1])
    return app


def _patch_batch_shims():
    """
    Teach the headless batch shims the loader hooks newer OpenStrandStudio
    revisions call. They are pure no-ops; without them `apply_loaded_strands`
    raises AttributeError on a shim canvas.
    """
    import batch_rendering

    for cls_name, hooks in (
        ("_BatchGroupPanel", ("sync_from_canvas", "clear_all", "update_group_display")),
        ("_BatchLayerPanel", ("update_layer_buttons_states",)),
    ):
        cls = getattr(batch_rendering, cls_name, None)
        if cls is None:
            continue
        for hook in hooks:
            if not hasattr(cls, hook):
                setattr(cls, hook, lambda self, *args, **kwargs: None)


def create_render_canvas(prefer_main_window=True):
    """
    Return (canvas, kind).

    kind is "main_window" when this is the real `main.py` canvas, or "batch"
    when the headless shim stood in for it. The draw loop is identical either
    way; only the surrounding UI differs.
    """
    _require_openstrandstudio()
    ensure_qapplication()

    if prefer_main_window:
        try:
            from openstrandstudio.src.main_window import MainWindow

            window = MainWindow()
            window.hide()
            window.canvas.hide()
            canvas = window.canvas
            # Keep a reference alive; the canvas does not own its window.
            canvas._mxn_owner_window = window
            return canvas, "main_window"
        except Exception:
            pass

    _patch_batch_shims()
    from batch_rendering import _BatchRenderCanvas

    return _BatchRenderCanvas(), "batch"


def _reset_canvas(canvas):
    if hasattr(canvas, "reset_scene"):
        canvas.reset_scene()
        return
    canvas.strands = []
    canvas.strand_colors = {}
    canvas.selected_strand = None
    canvas.current_strand = None


def load_json_into_canvas(json_content, canvas):
    """
    Load a pattern into `canvas` and apply main.py's export-time canvas flags.

    Args:
        json_content: JSON text, or an already-parsed dict.
        canvas:       from `create_render_canvas()`.

    Returns:
        The canvas, with `canvas.strands` in JSON order (= layer order).
    """
    from openstrandstudio.src.save_load_manager import (
        load_strands_from_data,
        apply_loaded_strands,
    )

    data = json.loads(json_content) if isinstance(json_content, (str, bytes)) else json_content
    state = _get_active_history_state(data)
    current = state.get("data") if state is not None else data
    if not current:
        raise ValueError("no strand data found in JSON")

    _reset_canvas(canvas)

    strands, groups, _, _, _, _, _, shadow_overrides = load_strands_from_data(current, canvas)
    apply_loaded_strands(canvas, strands, groups, shadow_overrides)

    canvas.show_grid = False
    canvas.show_control_points = False
    canvas.shadow_enabled = False
    canvas.should_draw_names = False
    if hasattr(canvas, "is_attaching"):
        canvas.is_attaching = False
    if hasattr(canvas, "attach_preview_strand"):
        canvas.attach_preview_strand = None
    for strand in canvas.strands:
        strand.should_draw_shadow = False

    return canvas


def calculate_strands_bounds(canvas, padding=BOUNDS_PADDING):
    """Content bounding box plus padding — same as `_calculate_strands_bounds`."""
    if not canvas.strands:
        return QRectF(0, 0, 1200, 900)

    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")

    for strand in canvas.strands:
        points = [strand.start, strand.end]
        if getattr(strand, "control_point1", None):
            points.append(strand.control_point1)
        if getattr(strand, "control_point2", None):
            points.append(strand.control_point2)
        for point in points:
            min_x = min(min_x, point.x())
            max_x = max(max_x, point.x())
            min_y = min(min_y, point.y())
            max_y = max(max_y, point.y())

    if min_x == float("inf"):
        return QRectF(0, 0, 1200, 900)

    return QRectF(min_x - padding, min_y - padding,
                  max_x - min_x + 2 * padding, max_y - min_y + 2 * padding)


def _render_overlay_layer(canvas, bounds, scale_factor, width, height,
                          emoji_settings, m, n, emoji_renderer=None):
    """
    Emojis / strand names / rotation indicator, painted into their own
    transparent layer — the same isolation `_render_emoji_overlay_layer` uses to
    keep the overlay's pen/brush state away from strand drawing.
    """
    if not emoji_settings:
        return None
    if not (emoji_settings.get("show")
            or emoji_settings.get("show_strand_names")
            or emoji_settings.get("show_rotation_indicator")):
        return None

    from openstrandstudio.src.render_utils import RenderUtils
    from mxn_emoji_renderer import EmojiRenderer

    renderer = emoji_renderer or EmojiRenderer()

    layer = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    layer.fill(Qt.transparent)

    painter = QPainter(layer)
    RenderUtils.setup_painter(painter, enable_high_quality=True)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    painter.scale(scale_factor, scale_factor)
    painter.translate(-bounds.x(), -bounds.y())

    if emoji_settings.get("show") or emoji_settings.get("show_strand_names"):
        renderer.draw_endpoint_emojis(painter, canvas, bounds, m, n, emoji_settings)
    if emoji_settings.get("show_rotation_indicator"):
        renderer.draw_rotation_indicator(painter, bounds, emoji_settings, scale_factor)

    painter.end()
    return layer


def render_canvas_image(canvas, bounds, scale_factor=2.0, transparent=False,
                        emoji_settings=None, m=None, n=None, emoji_renderer=None):
    """Draw a prepared canvas — the exact loop main.py's export runs."""
    from openstrandstudio.src.render_utils import RenderUtils

    if hasattr(canvas, "setFixedSize"):
        canvas.setFixedSize(max(800, min(4000, int(bounds.width()))),
                            max(600, min(3000, int(bounds.height()))))
        canvas.zoom_factor = 1.0

    width = max(1, int(bounds.width() * scale_factor))
    height = max(1, int(bounds.height() * scale_factor))

    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent if transparent else Qt.white)

    painter = QPainter(image)
    RenderUtils.setup_painter(painter, enable_high_quality=True)
    painter.scale(scale_factor, scale_factor)
    painter.translate(-bounds.x(), -bounds.y())

    # canvas.strands order IS the layer order, masks included. Do not re-sort.
    for strand in canvas.strands:
        strand.draw(painter, skip_painter_setup=True)
    if canvas.current_strand:
        canvas.current_strand.draw(painter, skip_painter_setup=True)

    overlay = _render_overlay_layer(canvas, bounds, scale_factor, width, height,
                                    emoji_settings, m, n, emoji_renderer)
    if overlay is not None:
        painter.save()
        painter.resetTransform()
        painter.drawImage(0, 0, overlay)
        painter.restore()

    painter.end()
    return image


def render_json_to_image(json_content, scale_factor=2.0, transparent=False,
                         canvas=None, emoji_settings=None, m=None, n=None,
                         emoji_renderer=None):
    """
    Render a pattern JSON to a QImage through the application's draw path.

    Args:
        json_content:  JSON text or parsed dict (history envelope or plain doc).
        scale_factor:  pixels per canvas unit.
        transparent:   transparent background instead of white.
        canvas:        reuse a canvas from `create_render_canvas()`; one is
                       created (and thrown away) if omitted.
        emoji_settings: optional dict with "show", "show_strand_names",
                       "show_rotation_indicator", "k", "direction". Omit for
                       strand layers only — which is what main.py draws with
                       the overlay checkboxes off.
        m, n:          grid size, required only when emoji_settings is given.
    """
    if canvas is None:
        canvas, _ = create_render_canvas()
    load_json_into_canvas(json_content, canvas)
    bounds = calculate_strands_bounds(canvas)
    return render_canvas_image(canvas, bounds, scale_factor, transparent,
                               emoji_settings, m, n, emoji_renderer)


def render_json_to_file(json_content, out_path, scale_factor=2.0, transparent=False,
                        canvas=None, emoji_settings=None, m=None, n=None,
                        emoji_renderer=None):
    """Render to `out_path`. Returns the QImage."""
    image = render_json_to_image(json_content, scale_factor, transparent, canvas,
                                 emoji_settings, m, n, emoji_renderer)
    directory = os.path.dirname(os.path.abspath(out_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not image.save(out_path):
        raise IOError(f"failed to write {out_path}")
    return image


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Render a pattern JSON exactly the way main.py draws it.")
    parser.add_argument("json_path")
    parser.add_argument("out_path")
    parser.add_argument("--scale", type=float, default=2.0)
    parser.add_argument("--transparent", action="store_true")
    parser.add_argument("--batch-canvas", action="store_true",
                        help="skip MainWindow and use the headless canvas shim")
    parser.add_argument("--emojis", action="store_true", help="draw the emoji overlay")
    parser.add_argument("--strand-names", action="store_true", help="draw strand names")
    parser.add_argument("--m", type=int, default=None, help="required with --emojis/--strand-names")
    parser.add_argument("--n", type=int, default=None, help="required with --emojis/--strand-names")
    parser.add_argument("--k", type=int, default=0)
    parser.add_argument("--direction", choices=["cw", "ccw"], default="cw")
    args = parser.parse_args(argv)

    emoji_settings = None
    if args.emojis or args.strand_names:
        if args.m is None or args.n is None:
            parser.error("--m and --n are required when drawing the overlay")
        emoji_settings = {
            "show": args.emojis,
            "show_strand_names": args.strand_names,
            "show_rotation_indicator": args.emojis,
            "k": args.k,
            "direction": args.direction,
            "transparent": args.transparent,
        }

    with open(args.json_path, "r", encoding="utf-8") as handle:
        json_text = handle.read()

    canvas, kind = create_render_canvas(prefer_main_window=not args.batch_canvas)
    image = render_json_to_file(json_text, args.out_path, args.scale, args.transparent,
                                canvas, emoji_settings, args.m, args.n)
    print(f"canvas: {kind}  layers: {len(canvas.strands)}")
    print(f"saved: {args.out_path} ({image.width()}x{image.height()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
