"""Batch rendering infrastructure: shim classes, ImagePreviewWidget, and BatchWorker."""

import os
import json
import copy

from PyQt5.QtWidgets import QLabel, QSizePolicy
from PyQt5.QtCore import Qt, pyqtSignal, QRectF, QThread
from PyQt5.QtGui import QColor, QPixmap, QImage, QPainter, QPen, QBrush, QPainterPath

from ui_utils import (
    _get_active_history_state,
    _get_active_strands,
    _set_active_strands,
    _get_alignment_base_output_dir,
    _get_alignment_attempt_basename,
    _get_alignment_final_output_info,
    _build_alignment_summary_text,
    _build_alignment_attempt_text,
)


# ---------------------------------------------------------------------------
# Batch shim classes (lightweight stubs for headless JSON loading)
# ---------------------------------------------------------------------------

class _BatchLayerStateManager:
    """Minimal layer-state shim for batch JSON loading."""

    def __init__(self):
        self.layer_state = {"order": [], "shadow_overrides": {}}
        self._connections = {}

    def connect_layers(self, parent_layer, child_layer):
        self._connections.setdefault(parent_layer, set()).add(child_layer)

    def getConnections(self):
        return {key: sorted(value) for key, value in self._connections.items()}


class _BatchGroupPanel:
    """No-op group panel used by batch rendering."""

    def __init__(self):
        self.groups_loaded_from_json = False

    def create_group(self, _group_name, _group_strands):
        return None

    def refresh_group_alignment(self):
        return None


class _BatchGroupLayerManager:
    """Minimal group manager wrapper for batch rendering."""

    def __init__(self):
        self.group_panel = _BatchGroupPanel()


class _BatchLayerPanel:
    """No-op layer panel to satisfy loader refresh hooks."""

    def __init__(self):
        self.set_counts = {}
        self.current_set = 1

    def refresh(self):
        return None


class _BatchRenderCanvas:
    """Lightweight, non-QWidget canvas for batch deserialization and rendering."""

    def __init__(self):
        self.default_shadow_color = QColor(0, 0, 0, 150)
        self.default_stroke_color = QColor(0, 0, 0, 255)
        self.default_arrow_fill_color = QColor(0, 0, 0, 255)
        self.use_default_arrow_color = False
        self.num_steps = 2
        self.max_blur_radius = 29.99
        self.control_point_base_fraction = 1.0
        self.distance_multiplier = 2.0
        self.curve_response_exponent = 2.0
        self.enable_third_control_point = True
        self.enable_curvature_bias_control = False
        self.highlight_color = Qt.red
        self.zoom_factor = 1.0
        self.pan_offset_x = 0
        self.pan_offset_y = 0
        self.current_mode = None
        self._suppress_layer_panel_refresh = True
        self._suppress_repaint = True
        self.layer_panel = _BatchLayerPanel()
        self.reset_scene()

    def reset_scene(self):
        self.strands = []
        self.groups = {}
        self.strand_colors = {}
        self.selected_strand = None
        self.selected_attached_strand = None
        self.current_strand = None
        self.show_grid = False
        self.show_control_points = False
        self.shadow_enabled = False
        self.should_draw_names = False
        self.group_layer_manager = _BatchGroupLayerManager()
        self.layer_state_manager = _BatchLayerStateManager()

    def update(self):
        return None

    def repaint(self):
        return None


# ---------------------------------------------------------------------------
# ImagePreviewWidget
# ---------------------------------------------------------------------------

class ImagePreviewWidget(QLabel):
    """A widget to display the exported image."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #1a1a1a; border: 1px solid #555;")
        self.setText("Generate a pattern to see preview")
        self.original_pixmap = None
        self._overlay_lines = []

    def set_image(self, image_path):
        """Load and display an image from file."""
        if os.path.exists(image_path):
            self.original_pixmap = QPixmap(image_path)
            self._overlay_lines = []
            self._update_scaled_pixmap()
        else:
            self.setText(f"Image not found:\n{image_path}")
            self.original_pixmap = None
            self._overlay_lines = []
            self.setAlignment(Qt.AlignCenter)
            self.update()

    def set_qimage(self, qimage):
        """Display a QImage directly (in-memory)."""
        if qimage and not qimage.isNull():
            self.original_pixmap = QPixmap.fromImage(qimage)
            self._overlay_lines = []
            self._update_scaled_pixmap()
        else:
            self.setText("Failed to generate image")
            self.original_pixmap = None
            self._overlay_lines = []
            self.setAlignment(Qt.AlignCenter)
            self.update()

    def clear(self):
        """Clear the preview."""
        self.original_pixmap = None
        self.setText("Generate a pattern to see preview")
        self._overlay_lines = []
        self.setAlignment(Qt.AlignCenter)
        self.update()

    def set_overlay_lines(self, lines):
        """Draw optional overlay text lines at the top of the preview widget."""
        self._overlay_lines = list(lines) if lines else []
        self.update()

    def paintEvent(self, event):
        """Paint base preview, then optional H/V set overlay text in widget coordinates."""
        super().paintEvent(event)

        if not self._overlay_lines or not self.original_pixmap or self.original_pixmap.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        font = painter.font()
        font.setBold(True)
        font.setPointSize(12)
        painter.setFont(font)
        fm = painter.fontMetrics()

        margin_x = 8
        margin_y = 8
        line_h = fm.height() + 2
        cur_y = margin_y + fm.ascent()
        outline_w = 2

        for text in self._overlay_lines:
            path = QPainterPath()
            path.addText(float(margin_x), float(cur_y), painter.font(), text)
            painter.setPen(QPen(QColor(255, 255, 255), outline_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0)))
            painter.drawPath(path)
            cur_y += line_h

        painter.end()

    def resizeEvent(self, event):
        """Handle resize to scale image properly."""
        super().resizeEvent(event)
        self._update_scaled_pixmap()

    def _update_scaled_pixmap(self):
        """Scale the pixmap to fit the widget while maintaining aspect ratio."""
        if self.original_pixmap and not self.original_pixmap.isNull():
            self.setAlignment(Qt.AlignCenter)
            scaled = self.original_pixmap.scaled(
                self.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.setPixmap(scaled)


# ---------------------------------------------------------------------------
# BatchWorker
# ---------------------------------------------------------------------------

class BatchWorker(QThread):
    """Runs the batch pipeline loop off the UI thread."""
    progress = pyqtSignal(int, int, str)       # (current_idx, total, status_text)
    log_message = pyqtSignal(str)              # log line
    finished_batch = pyqtSignal(int, int, int, int)  # (saved, skipped, errors, total)

    def __init__(self, combinations, params, parent=None):
        super().__init__(parent)
        self.combinations = combinations
        self.params = params
        self._stop_requested = False
        self._render_canvas = None

    def request_stop(self):
        self._stop_requested = True

    def _log(self, msg):
        self.log_message.emit(msg)

    def _get_render_canvas(self):
        if self._render_canvas is None:
            try:
                self._render_canvas = _BatchRenderCanvas()
            except Exception as e:
                self._log(f"ERROR: Failed to create batch render canvas: {e}")
                return None
        return self._render_canvas

    def _load_json_to_canvas(self, json_content):
        from openstrandstudio.src.save_load_manager import load_strands_from_data, apply_loaded_strands

        canvas = self._get_render_canvas()
        if not canvas:
            return None
        canvas.reset_scene()

        data = json.loads(json_content)
        current_state = _get_active_history_state(data)
        current_data = current_state.get("data") if current_state is not None else data
        if not current_data:
            return None

        strands, groups, _, _, _, _, _, shadow_overrides = load_strands_from_data(current_data, canvas)

        apply_loaded_strands(canvas, strands, groups, shadow_overrides)

        canvas.show_grid = False
        canvas.show_control_points = False
        canvas.shadow_enabled = False
        canvas.should_draw_names = False
        for strand in canvas.strands:
            strand.should_draw_shadow = False

        return self._calculate_bounds(canvas)

    def _calculate_bounds(self, canvas):
        if not canvas.strands:
            return QRectF(0, 0, 1200, 900)

        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        padding = 100

        for strand in canvas.strands:
            points = [strand.start, strand.end]
            if hasattr(strand, 'control_point1') and strand.control_point1:
                points.append(strand.control_point1)
            if hasattr(strand, 'control_point2') and strand.control_point2:
                points.append(strand.control_point2)
            for pt in points:
                min_x = min(min_x, pt.x())
                max_x = max(max_x, pt.x())
                min_y = min(min_y, pt.y())
                max_y = max(max_y, pt.y())

        if min_x == float('inf'):
            return QRectF(0, 0, 1200, 900)

        return QRectF(min_x - padding, min_y - padding,
                      max_x - min_x + 2 * padding, max_y - min_y + 2 * padding)

    def _render_image(self, bounds, scale_factor, transparent):
        from openstrandstudio.src.render_utils import RenderUtils

        canvas = self._get_render_canvas()
        if not canvas:
            return None

        w = int(bounds.width() * scale_factor)
        h = int(bounds.height() * scale_factor)
        image = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent if transparent else Qt.white)

        painter = QPainter(image)
        RenderUtils.setup_painter(painter, enable_high_quality=True)
        painter.scale(scale_factor, scale_factor)
        painter.translate(-bounds.x(), -bounds.y())

        for strand in canvas.strands:
            strand.draw(painter, skip_painter_setup=True)
        if canvas.current_strand:
            canvas.current_strand.draw(painter, skip_painter_setup=True)

        painter.end()
        return image

    @staticmethod
    def _build_batch_emoji_settings(
        draw_emojis,
        draw_strand_names,
        draw_arrows,
        k,
        direction,
        transparent,
    ):
        return {
            "show": draw_emojis,
            "show_strand_names": draw_strand_names,
            "show_rotation_indicator": draw_arrows,
            "k": k,
            "direction": direction,
            "transparent": transparent,
        }

    def _render_batch_overlays(self, canvas, bounds, base_image, scale_factor,
                               m, n, k, direction,
                               draw_emojis, draw_strand_names, draw_arrows,
                               transparent):
        from openstrandstudio.src.render_utils import RenderUtils

        w = base_image.width()
        h = base_image.height()

        emoji_settings = self._build_batch_emoji_settings(
            draw_emojis,
            draw_strand_names,
            draw_arrows,
            k,
            direction,
            transparent,
        )

        overlay = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        overlay.fill(Qt.transparent)

        ep = QPainter(overlay)
        RenderUtils.setup_painter(ep, enable_high_quality=True)
        ep.setCompositionMode(QPainter.CompositionMode_SourceOver)
        ep.scale(scale_factor, scale_factor)
        ep.translate(-bounds.x(), -bounds.y())

        if draw_emojis or draw_strand_names:
            self._emoji_renderer.draw_endpoint_emojis(
                ep, canvas, bounds, m, n, emoji_settings
            )
        if draw_arrows:
            self._emoji_renderer.draw_rotation_indicator(ep, bounds, emoji_settings, scale_factor)

        ep.end()

        painter = QPainter(base_image)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawImage(0, 0, overlay)
        painter.end()

        return base_image

    def _render_json_image(
        self,
        json_content,
        scale_factor,
        m,
        n,
        k,
        direction,
        draw_emojis,
        draw_strand_names,
        draw_arrows,
        transparent,
    ):
        bounds = self._load_json_to_canvas(json_content)
        if not bounds:
            return None

        image = self._render_image(bounds, scale_factor, transparent)
        if image is None or image.isNull():
            return image

        if draw_emojis or draw_strand_names or draw_arrows:
            canvas = self._get_render_canvas()
            if canvas:
                image = self._render_batch_overlays(
                    canvas,
                    bounds,
                    image,
                    scale_factor,
                    m,
                    n,
                    k,
                    direction,
                    draw_emojis,
                    draw_strand_names,
                    draw_arrows,
                    transparent,
                )

        return image

    def run(self):
        from mxn_lh_continuation import generate_json as generate_lh_continuation_json
        from mxn_rh_continuation import generate_json as generate_rh_continuation_json
        from mxn_lh_continuation import (
            align_horizontal_strands_parallel as align_horizontal_strands_parallel_lh,
            align_vertical_strands_parallel as align_vertical_strands_parallel_lh,
            apply_parallel_alignment as apply_parallel_alignment_lh,
        )
        from mxn_rh_continuation import (
            align_horizontal_strands_parallel as align_horizontal_strands_parallel_rh,
            align_vertical_strands_parallel as align_vertical_strands_parallel_rh,
            apply_parallel_alignment as apply_parallel_alignment_rh,
        )

        p = self.params
        combinations = self.combinations
        total = len(combinations)

        angle_mode = p['angle_mode']
        pair_ext_max = p['pair_ext_max']
        pair_ext_step = p['pair_ext_step']
        use_gpu = p['use_gpu']
        scale_factor = p['scale_factor']
        custom_colors = p['custom_colors']
        save_horizontal_valid = p['save_horizontal_valid']
        save_pre_align = p['save_pre_align']
        draw_emojis = p['draw_emojis']
        draw_strand_names = p['draw_strand_names']
        draw_arrows = p['draw_arrows']
        transparent = p['transparent']
        base_dir = p['base_dir']

        self._emoji_renderer = p['emoji_renderer']

        saved = 0
        skipped = 0
        errors = 0

        for idx, (m, n, k, direction, hand) in enumerate(combinations):
            if self._stop_requested:
                self._log(f"\nStopped by user after {idx}/{total}.")
                break

            status_text = (
                f"Processing {idx + 1}/{total}: {hand.upper()} {m}x{n} k={k} {direction.upper()} | "
                f"Saved: {saved}, Skipped: {skipped}, Errors: {errors}"
            )
            self.progress.emit(idx, total, status_text)

            try:
                self._log(f"[{idx + 1}/{total}] {hand.upper()} {m}x{n} k={k} {direction.upper()}")
                if hasattr(self._emoji_renderer, "unfreeze_emoji_assignments"):
                    self._emoji_renderer.unfreeze_emoji_assignments()

                pattern_type = hand
                base_output_dir = _get_alignment_base_output_dir(
                    base_dir,
                    m,
                    n,
                    k,
                    direction,
                    pattern_type,
                )
                attempt_dir = os.path.join(base_output_dir, "attempt_options")
                os.makedirs(attempt_dir, exist_ok=True)

                # --- Step 1: Generate continuation JSON ---
                if hand == "lh":
                    cont_json = generate_lh_continuation_json(m, n, k, direction)
                else:
                    cont_json = generate_rh_continuation_json(m, n, k, direction)

                cont_json = self._apply_colors_to_json(cont_json, custom_colors)

                # Save pre-alignment continuation (optional)
                if save_pre_align:
                    cont_dir = os.path.join(base_dir, "mxn", "mxn_continueing", f"mxn_{hand}_continuation")
                    os.makedirs(cont_dir, exist_ok=True)
                    cont_filename = f"mxn_{hand}_strech_{m}x{n}_continue_k{k}_{direction}.json"
                    with open(os.path.join(cont_dir, cont_filename), 'w') as f:
                        f.write(cont_json)

                # --- Step 2: Parse strands ---
                data = json.loads(cont_json)
                strands = _get_active_strands(data)

                # --- Step 3: Select alignment functions ---
                if hand == "lh":
                    align_h_fn = align_horizontal_strands_parallel_lh
                    align_v_fn = align_vertical_strands_parallel_lh
                    apply_fn = apply_parallel_alignment_lh
                else:
                    align_h_fn = align_horizontal_strands_parallel_rh
                    align_v_fn = align_vertical_strands_parallel_rh
                    apply_fn = apply_parallel_alignment_rh

                if draw_emojis or draw_strand_names or draw_arrows:
                    bounds = self._load_json_to_canvas(cont_json)
                    canvas = self._get_render_canvas()
                    if bounds and canvas and hasattr(self._emoji_renderer, "freeze_emoji_assignments"):
                        self._emoji_renderer.freeze_emoji_assignments(
                            canvas,
                            bounds,
                            m,
                            n,
                            self._build_batch_emoji_settings(
                                draw_emojis,
                                draw_strand_names,
                                draw_arrows,
                                k,
                                direction,
                                transparent,
                            ),
                        )

                h_result = {}
                v_result = {}
                attempt_count = [0]
                h_attempt_count = [0]
                v_attempt_count = [0]
                best_h_result_info = [None]

                def save_attempt_callback(angle_deg, extension, result, direction_type):
                    attempt_count[0] += 1
                    if direction_type == "horizontal":
                        h_attempt_count[0] += 1
                    else:
                        v_attempt_count[0] += 1

                    is_valid = bool(result.get("valid", False))
                    if direction_type == "horizontal" and is_valid and not save_horizontal_valid:
                        return

                    base_filename = _get_alignment_attempt_basename(
                        pattern_type,
                        m,
                        n,
                        k,
                        direction,
                        direction_type,
                        extension,
                        angle_deg,
                        is_valid,
                    )

                    configs = result.get("configurations")
                    if not configs and result.get("fallback"):
                        configs = result["fallback"].get("configurations")

                    attempt_strands = copy.deepcopy(strands)
                    if configs:
                        attempt_result = {"success": True, "configurations": configs}
                        attempt_strands = apply_fn(attempt_strands, attempt_result)

                    attempt_data = copy.deepcopy(data)
                    _set_active_strands(attempt_data, attempt_strands)
                    attempt_json = json.dumps(attempt_data, separators=(',', ':'))

                    attempt_scale = scale_factor if is_valid else scale_factor * 0.0625
                    image = self._render_json_image(
                        attempt_json,
                        attempt_scale,
                        m,
                        n,
                        k,
                        direction,
                        draw_emojis,
                        draw_strand_names,
                        draw_arrows,
                        transparent,
                    )
                    if image and not image.isNull():
                        image.save(os.path.join(attempt_dir, base_filename + ".png"))

                    with open(os.path.join(attempt_dir, base_filename + ".json"), 'w', encoding='utf-8') as f:
                        f.write(attempt_json)

                    attempt_text = _build_alignment_attempt_text(
                        pattern_type,
                        m,
                        n,
                        k,
                        direction,
                        angle_deg,
                        extension,
                        result,
                        direction_type,
                        attempt_count[0],
                        h_result_info=best_h_result_info[0] if direction_type == "vertical" else None,
                    )
                    with open(os.path.join(attempt_dir, base_filename + ".txt"), 'w', encoding='utf-8') as f:
                        f.write(attempt_text)

                # --- Step 4: Horizontal alignment ---
                h_result = align_h_fn(
                    strands, n,
                    angle_step_degrees=0.5,
                    max_extension=100.0,
                    on_config_callback=save_attempt_callback,
                    max_pair_extension=pair_ext_max,
                    pair_extension_step=pair_ext_step,
                    m=m, k=k, direction=direction,
                    use_gpu=use_gpu,
                    angle_mode=angle_mode,
                )

                h_success = h_result.get("success", False)
                if h_result["success"] or h_result.get("is_fallback"):
                    strands = apply_fn(strands, h_result)
                    h_angle = h_result.get("angle_degrees", 0)
                    h_gap = h_result.get("average_gap", 0)
                    self._log(f"  H: {'OK' if h_success else 'fallback'} angle={h_angle:.1f} gap={h_gap:.1f}px")
                else:
                    h_angle = None
                    h_gap = None
                    self._log(f"  H: FAILED - {h_result.get('message', '')}")

                h_info = {
                    'success': h_result.get("success", False),
                    'angle': f"{h_result.get('angle_degrees', 0):.2f}°",
                    'avg_gap': f"{h_result.get('average_gap', 0):.2f} px",
                    'gap_variance': h_result.get('gap_variance', 'N/A'),
                    'first_last_distance': h_result.get('first_last_distance', 'N/A'),
                    'pair_extensions': h_result.get('pair_extensions', 'N/A'),
                    'strand_details': [],
                }
                for cfg in h_result.get("configurations", []):
                    name = cfg.get("strand", {}).get("strand_4_5", {}).get("layer_name", "unknown")
                    ext = cfg.get("extension", 0)
                    length = cfg.get("length", 0)
                    h_info['strand_details'].append({'name': name, 'extension': ext, 'length': length})
                best_h_result_info[0] = h_info

                # --- Step 5: Vertical alignment ---
                v_result = align_v_fn(
                    strands, n, m,
                    angle_step_degrees=0.5,
                    max_extension=100.0,
                    on_config_callback=save_attempt_callback,
                    max_pair_extension=pair_ext_max,
                    pair_extension_step=pair_ext_step,
                    k=k, direction=direction,
                    use_gpu=use_gpu,
                    angle_mode=angle_mode,
                )

                v_success = v_result.get("success", False)
                if v_result["success"] or v_result.get("is_fallback"):
                    strands = apply_fn(strands, v_result)
                    v_angle = v_result.get("angle_degrees", 0)
                    v_gap = v_result.get("average_gap", 0)
                    self._log(f"  V: {'OK' if v_success else 'fallback'} angle={v_angle:.1f} gap={v_gap:.1f}px")
                else:
                    v_angle = None
                    v_gap = None
                    self._log(f"  V: FAILED - {v_result.get('message', '')}")

                # --- Step 6: Update strands in data ---
                _set_active_strands(data, strands)

                aligned_json = json.dumps(data, indent=2)

                # --- Step 7: Save outputs ---
                output_info = _get_alignment_final_output_info(
                    base_output_dir,
                    pattern_type,
                    m,
                    n,
                    k,
                    direction,
                    h_success,
                    h_angle,
                    v_success,
                    v_angle,
                )
                os.makedirs(output_info["output_subdir"], exist_ok=True)

                image = self._render_json_image(
                    aligned_json,
                    scale_factor,
                    m,
                    n,
                    k,
                    direction,
                    draw_emojis,
                    draw_strand_names,
                    draw_arrows,
                    transparent,
                )

                filename_base = output_info["filename_base"]
                output_dir = output_info["output_subdir"]
                if image and not image.isNull():
                    image.save(os.path.join(output_dir, filename_base + ".png"))

                with open(os.path.join(output_dir, filename_base + ".json"), 'w', encoding='utf-8') as f:
                    f.write(aligned_json)

                summary_text = _build_alignment_summary_text(
                    pattern_type,
                    m,
                    n,
                    k,
                    direction,
                    h_success,
                    h_angle,
                    h_gap,
                    h_result,
                    v_success,
                    v_angle,
                    v_gap,
                    v_result,
                    {
                        "h_angle_range_text": f"AUTO ({angle_mode})",
                        "v_angle_range_text": f"AUTO ({angle_mode})",
                        "custom_angles": False,
                        "pair_ext_max": pair_ext_max,
                        "pair_ext_step": pair_ext_step,
                        "max_extension": 100.0,
                        "angle_step": 0.5,
                        "strand_width": 46,
                    },
                )
                with open(os.path.join(output_dir, filename_base + ".txt"), 'w', encoding='utf-8') as f:
                    f.write(summary_text)

                result_label = "SOLUTION" if output_info["is_valid_solution"] else "PARTIAL"
                self._log(
                    f"  -> {result_label} | saved to .../{m}x{n}/k_{k}_{direction}_{hand}/ "
                    f"[{os.path.basename(output_dir)}] | attempts H={h_attempt_count[0]} V={v_attempt_count[0]}"
                )
                saved += 1

            except Exception as e:
                import traceback
                traceback.print_exc()
                self._log(f"  ERROR: {e}")
                errors += 1
            finally:
                if hasattr(self._emoji_renderer, "unfreeze_emoji_assignments"):
                    self._emoji_renderer.unfreeze_emoji_assignments()

        self.finished_batch.emit(saved, skipped, errors, total)

    @staticmethod
    def _apply_colors_to_json(json_content, custom_colors):
        if not custom_colors:
            return json_content
        data = json.loads(json_content)
        if data.get('type') == 'OpenStrandStudioHistory':
            for state in data.get('states', []):
                for strand in state.get('data', {}).get('strands', []):
                    sn = strand.get('set_number')
                    if sn and sn in custom_colors:
                        strand['color'] = custom_colors[sn]
        else:
            for strand in data.get('strands', []):
                sn = strand.get('set_number')
                if sn and sn in custom_colors:
                    strand['color'] = custom_colors[sn]
        return json.dumps(data, indent=2)
