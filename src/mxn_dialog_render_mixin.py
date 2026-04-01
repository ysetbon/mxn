"""Canvas rendering and image generation mixin for MxNGeneratorDialog."""

import os
import json
import hashlib

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QImage, QPainter


class RenderMixin:
    """Mixin providing canvas rendering, image generation, and emoji overlay."""

    def _calculate_strands_bounds(self, canvas):
        """Calculate the bounding box of all strands with padding."""
        if not canvas.strands:
            return QRectF(0, 0, 1200, 900)

        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')

        for strand in canvas.strands:
            points = [strand.start, strand.end]
            if hasattr(strand, 'control_point1') and strand.control_point1:
                points.append(strand.control_point1)
            if hasattr(strand, 'control_point2') and strand.control_point2:
                points.append(strand.control_point2)

            for point in points:
                min_x = min(min_x, point.x())
                max_x = max(max_x, point.x())
                min_y = min(min_y, point.y())
                max_y = max(max_y, point.y())

        padding = self.BOUNDS_PADDING
        return QRectF(min_x - padding, min_y - padding,
                      max_x - min_x + 2*padding, max_y - min_y + 2*padding)

    def _build_emoji_settings(self):
        """Build a consistent emoji settings dict for all render paths."""
        show_emojis = self.show_emojis_checkbox.isChecked() if hasattr(self, "show_emojis_checkbox") else True
        return {
            "show": show_emojis,
            "show_strand_names": self.show_strand_names_checkbox.isChecked() if hasattr(self, "show_strand_names_checkbox") else False,
            "show_rotation_indicator": show_emojis,
            "k": self.emoji_k_spinner.value() if hasattr(self, "emoji_k_spinner") else 0,
            "direction": "cw" if (hasattr(self, "emoji_cw_radio") and self.emoji_cw_radio.isChecked()) else "ccw",
            "transparent": self.transparent_checkbox.isChecked() if hasattr(self, "transparent_checkbox") else True,
        }

    def _render_emoji_overlay_layer(self, canvas, bounds, scale_factor, image_width, image_height):
        """
        Render emojis + rotation indicator into an isolated transparent layer.

        This keeps emoji painting independent from strand painter state and avoids
        pen/brush/composition bleed from strand drawing.
        """
        from openstrandstudio.src.render_utils import RenderUtils
        from PyQt5.QtGui import QPainter

        emoji_settings = self._build_emoji_settings()
        if not (
            emoji_settings.get("show", True)
            or emoji_settings.get("show_strand_names", False)
            or emoji_settings.get("show_rotation_indicator", False)
        ):
            return None

        emoji_layer = QImage(image_width, image_height, QImage.Format_ARGB32_Premultiplied)
        emoji_layer.fill(Qt.transparent)

        ep = QPainter(emoji_layer)
        RenderUtils.setup_painter(ep, enable_high_quality=True)
        ep.setCompositionMode(QPainter.CompositionMode_SourceOver)
        ep.scale(scale_factor, scale_factor)
        ep.translate(-bounds.x(), -bounds.y())

        self._emoji_renderer.draw_endpoint_emojis(
            ep, canvas, bounds, self.m_spinner.value(), self.n_spinner.value(), emoji_settings
        )
        self._emoji_renderer.draw_rotation_indicator(ep, bounds, emoji_settings, scale_factor)
        ep.end()

        return emoji_layer

    def _snapshot_canvas_geometry(self, strand_lookup):
        """Capture strand geometry by layer name for fast restore between attempts."""
        snapshot = {}
        failures = []
        for layer_name, strand in strand_lookup.items():
            try:
                cp1 = getattr(strand, "control_point1", None)
                cp2 = getattr(strand, "control_point2", None)
                cp_center = getattr(strand, "control_point_center", None)
                snapshot[layer_name] = {
                    "start": QPointF(strand.start),
                    "end": QPointF(strand.end),
                    "control_point1": QPointF(cp1) if cp1 is not None else None,
                    "control_point2": QPointF(cp2) if cp2 is not None else None,
                    "control_point_center": QPointF(cp_center) if cp_center is not None else None,
                    "control_point_center_locked": getattr(strand, "control_point_center_locked", False),
                }
            except Exception as snapshot_error:
                failures.append(f"{layer_name}: {snapshot_error}")

        if failures:
            preview = "; ".join(failures[:3])
            if len(failures) > 3:
                preview += f"; ... (+{len(failures) - 3} more)"
            raise RuntimeError(f"Snapshot failed for {len(failures)} strand(s): {preview}")

        return snapshot

    def _set_canvas_strand_geometry(
        self,
        strand,
        start,
        end,
        control_point1=None,
        control_point2=None,
        control_point_center=None,
        control_point_center_locked=None,
    ):
        """Set strand geometry and update shape exactly once."""
        start_pt = QPointF(start)
        end_pt = QPointF(end)

        # Intentional: setting _start/_end avoids triggering update_shape() twice via
        # public property setters; we then call update_shape() once at the end.
        if hasattr(strand, "_start"):
            strand._start = start_pt
        else:
            strand.start = start_pt

        if hasattr(strand, "_end"):
            strand._end = end_pt
        else:
            strand.end = end_pt

        if control_point1 is not None and hasattr(strand, "control_point1"):
            strand.control_point1 = QPointF(control_point1)
        if control_point2 is not None and hasattr(strand, "control_point2"):
            strand.control_point2 = QPointF(control_point2)
        if control_point_center is not None and hasattr(strand, "control_point_center"):
            strand.control_point_center = QPointF(control_point_center)
        if control_point_center_locked is not None and hasattr(strand, "control_point_center_locked"):
            strand.control_point_center_locked = control_point_center_locked

        if hasattr(strand, "update_shape"):
            strand.update_shape()

    def _restore_canvas_geometry(self, strand_lookup, snapshot, layer_names=None):
        """Restore strand geometry for a prepared attempt-render canvas."""
        if layer_names is None:
            items = snapshot.items()
        else:
            items = ((layer_name, snapshot.get(layer_name)) for layer_name in layer_names)

        missing_layers = []
        failed_layers = []
        for layer_name, geometry in items:
            if geometry is None:
                missing_layers.append(layer_name)
                continue
            strand = strand_lookup.get(layer_name)
            if strand is None:
                missing_layers.append(layer_name)
                continue
            try:
                self._set_canvas_strand_geometry(
                    strand,
                    geometry["start"],
                    geometry["end"],
                    control_point1=geometry.get("control_point1"),
                    control_point2=geometry.get("control_point2"),
                    control_point_center=geometry.get("control_point_center"),
                    control_point_center_locked=geometry.get("control_point_center_locked"),
                )
            except Exception as restore_error:
                failed_layers.append(f"{layer_name}: {restore_error}")

        if missing_layers or failed_layers:
            messages = []
            if missing_layers:
                sample = ", ".join(missing_layers[:5])
                if len(missing_layers) > 5:
                    sample += f", ... (+{len(missing_layers) - 5} more)"
                messages.append(f"missing {len(missing_layers)} layer(s): {sample}")
            if failed_layers:
                sample = "; ".join(failed_layers[:3])
                if len(failed_layers) > 3:
                    sample += f"; ... (+{len(failed_layers) - 3} more)"
                messages.append(f"restore failed for {len(failed_layers)} strand(s): {sample}")
            raise RuntimeError(" | ".join(messages))

    def _set_canvas_strand_line_geometry(self, strand, start_xy, end_xy):
        """Set straight strand geometry from dict points {x, y}."""
        start = QPointF(float(start_xy["x"]), float(start_xy["y"]))
        end = QPointF(float(end_xy["x"]), float(end_xy["y"]))
        self._set_canvas_strand_geometry(
            strand,
            start,
            end,
            control_point1=start,
            control_point2=end,
            control_point_center=QPointF(
                (start.x() + end.x()) * 0.5,
                (start.y() + end.y()) * 0.5,
            ),
        )

    def _apply_alignment_configs_to_canvas(self, strand_lookup, configs):
        """Apply alignment configs (from continuation solver) directly onto prepared canvas strands."""
        modified_layers = set()
        for config in configs or []:
            h_info = config.get("strand") or {}
            strand_4_5_info = h_info.get("strand_4_5") or {}
            strand_2_3_info = h_info.get("strand_2_3") or {}
            extended_start = config.get("extended_start")
            end_point = config.get("end")

            if not extended_start or not end_point:
                continue

            layer_4_5 = strand_4_5_info.get("layer_name")
            layer_2_3 = strand_2_3_info.get("layer_name")

            strand_4_5 = strand_lookup.get(layer_4_5)
            if strand_4_5 is not None:
                self._set_canvas_strand_line_geometry(strand_4_5, extended_start, end_point)
                if layer_4_5:
                    modified_layers.add(layer_4_5)

            strand_2_3 = strand_lookup.get(layer_2_3)
            if strand_2_3 is not None:
                current_start = {"x": strand_2_3.start.x(), "y": strand_2_3.start.y()}
                self._set_canvas_strand_line_geometry(strand_2_3, current_start, extended_start)
                if layer_2_3:
                    modified_layers.add(layer_2_3)

        return modified_layers

    def _render_current_canvas_image(self, canvas, scale_factor):
        """Render current prepared canvas state without JSON reload/cache lookups."""
        from openstrandstudio.src.render_utils import RenderUtils

        bounds = self._calculate_strands_bounds(canvas)
        canvas_width = max(800, min(4000, int(bounds.width())))
        canvas_height = max(600, min(3000, int(bounds.height())))
        canvas.setFixedSize(canvas_width, canvas_height)

        image_width = max(1, int(bounds.width() * scale_factor))
        image_height = max(1, int(bounds.height() * scale_factor))
        image = QImage(image_width, image_height, QImage.Format_ARGB32_Premultiplied)

        if self.transparent_checkbox.isChecked():
            image.fill(Qt.transparent)
        else:
            image.fill(Qt.white)

        painter = QPainter(image)
        RenderUtils.setup_painter(painter, enable_high_quality=True)
        painter.scale(scale_factor, scale_factor)
        painter.translate(-bounds.x(), -bounds.y())

        for strand in canvas.strands:
            strand.draw(painter, skip_painter_setup=True)

        if canvas.current_strand:
            canvas.current_strand.draw(painter, skip_painter_setup=True)

        emoji_layer = self._render_emoji_overlay_layer(
            canvas, bounds, scale_factor, image_width, image_height
        )
        if emoji_layer is not None:
            painter.save()
            painter.resetTransform()
            painter.drawImage(0, 0, emoji_layer)
            painter.restore()

        painter.end()
        return image

    def _export_json_to_image(self, json_path, output_path, scale_factor):
        """Export JSON to image using MainWindow and canvas (same as export_mxn_images.py)."""
        try:
            from openstrandstudio.src.main_window import MainWindow
            from openstrandstudio.src.save_load_manager import load_strands, load_strands_from_data, apply_loaded_strands
            from openstrandstudio.src.render_utils import RenderUtils
            from PyQt5.QtGui import QPainter
            from PyQt5.QtCore import QPointF

            main_window = self._get_main_window()
            if main_window is None:
                return False

            canvas = main_window.canvas

            # Clear existing strands
            canvas.strands = []
            canvas.strand_colors = {}
            canvas.selected_strand = None
            canvas.current_strand = None

            # Load JSON (handle history format)
            with open(json_path, 'r') as f:
                data = json.load(f)

            if data.get('type') == 'OpenStrandStudioHistory':
                current_step = data.get('current_step', 1)
                states = data.get('states', [])
                current_data = None
                for state in states:
                    if state['step'] == current_step:
                        current_data = state['data']
                        break

                if current_data:
                    strands, groups, _, _, _, _, _, shadow_overrides = load_strands_from_data(current_data, canvas)
                else:
                    return False
            else:
                strands, groups, _, _, _, _, _, shadow_overrides = load_strands(json_path, canvas)

            apply_loaded_strands(canvas, strands, groups, shadow_overrides)

            # Configure canvas for export
            canvas.show_grid = False
            canvas.show_control_points = False
            canvas.shadow_enabled = False
            canvas.should_draw_names = False

            if hasattr(canvas, 'is_attaching'):
                canvas.is_attaching = False
            if hasattr(canvas, 'attach_preview_strand'):
                canvas.attach_preview_strand = None

            for strand in canvas.strands:
                strand.should_draw_shadow = False

            # Calculate bounds and set canvas size dynamically
            bounds = self._calculate_strands_bounds(canvas)
            canvas_width = max(800, min(4000, int(bounds.width())))
            canvas_height = max(600, min(3000, int(bounds.height())))
            canvas.setFixedSize(canvas_width, canvas_height)
            canvas.zoom_factor = 1.0
            canvas.center_all_strands()
            canvas.update()
            QApplication.processEvents()

            # Create image sized to actual content bounds
            image_width = int(bounds.width() * scale_factor)
            image_height = int(bounds.height() * scale_factor)
            image = QImage(image_width, image_height, QImage.Format_ARGB32_Premultiplied)

            if self.transparent_checkbox.isChecked():
                image.fill(Qt.transparent)
            else:
                image.fill(Qt.white)

            painter = QPainter(image)
            RenderUtils.setup_painter(painter, enable_high_quality=True)
            painter.scale(scale_factor, scale_factor)

            # Translate to render content from bounds origin
            painter.translate(-bounds.x(), -bounds.y())

            for strand in canvas.strands:
                strand.draw(painter, skip_painter_setup=True)

            if canvas.current_strand:
                canvas.current_strand.draw(painter, skip_painter_setup=True)

            ### Legacy direct emoji painting path (kept for reference; disabled to avoid halo/stroke artifacts)
            ### emoji_settings = self._build_emoji_settings()
            ### self._emoji_renderer.draw_endpoint_emojis(
            ###     painter, canvas, bounds, self.m_spinner.value(), self.n_spinner.value(), emoji_settings
            ### )
            ### self._emoji_renderer.draw_rotation_indicator(painter, bounds, emoji_settings, scale_factor)

            # New path: render emojis in isolated layer, then composite over strands.
            emoji_layer = self._render_emoji_overlay_layer(
                canvas, bounds, scale_factor, image_width, image_height
            )
            if emoji_layer is not None:
                painter.save()
                painter.resetTransform()
                painter.drawImage(0, 0, emoji_layer)
                painter.restore()

            painter.end()

            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
            image.save(output_path)

            return True

        except Exception as e:
            import traceback
            traceback.print_exc()
            return False

    def _generate_image_in_memory(self, json_content, scale_factor):
        """Generate image in memory from JSON content string (no file I/O).

        Uses a cached strand layer to avoid re-drawing strands when only
        emoji settings (k, direction, show) or background change.
        """
        try:
            from openstrandstudio.src.render_utils import RenderUtils
            from PyQt5.QtGui import QPainter
            if not self._ensure_canvas_prepared(json_content):
                return None

            main_window = self._get_main_window()
            if main_window is None:
                return None

            canvas = main_window.canvas
            bounds = self._prepared_bounds or QRectF(0, 0, 1200, 900)

            image_width = int(bounds.width() * scale_factor)
            image_height = int(bounds.height() * scale_factor)

            # --- Step A: Strand layer (cached) ---
            strand_layer_key = (self._prepared_canvas_key, scale_factor)
            if (self._cached_strand_layer_key != strand_layer_key
                    or self._cached_strand_layer is None):
                # Render strands onto a transparent image
                strand_layer = QImage(image_width, image_height, QImage.Format_ARGB32_Premultiplied)
                strand_layer.fill(Qt.transparent)

                sp = QPainter(strand_layer)
                RenderUtils.setup_painter(sp, enable_high_quality=True)
                sp.scale(scale_factor, scale_factor)
                sp.translate(-bounds.x(), -bounds.y())

                for strand in canvas.strands:
                    strand.draw(sp, skip_painter_setup=True)

                if canvas.current_strand:
                    canvas.current_strand.draw(sp, skip_painter_setup=True)

                sp.end()

                self._cached_strand_layer = strand_layer
                self._cached_strand_layer_key = strand_layer_key

            # --- Step B: Composite final image ---
            image = QImage(image_width, image_height, QImage.Format_ARGB32_Premultiplied)

            if self.transparent_checkbox.isChecked():
                image.fill(Qt.transparent)
            else:
                image.fill(Qt.white)

            painter = QPainter(image)
            RenderUtils.setup_painter(painter, enable_high_quality=True)

            # Draw cached strand layer
            painter.drawImage(0, 0, self._cached_strand_layer)

            ### Legacy direct emoji painting path (kept for reference; disabled to avoid halo/stroke artifacts)
            ### painter.scale(scale_factor, scale_factor)
            ### painter.translate(-bounds.x(), -bounds.y())
            ### emoji_settings = self._build_emoji_settings()
            ### self._emoji_renderer.draw_endpoint_emojis(
            ###     painter, canvas, bounds, self.m_spinner.value(), self.n_spinner.value(), emoji_settings
            ### )
            ### self._emoji_renderer.draw_rotation_indicator(painter, bounds, emoji_settings, scale_factor)

            # New path: render emojis in isolated layer, then composite over strands.
            emoji_layer = self._render_emoji_overlay_layer(
                canvas, bounds, scale_factor, image_width, image_height
            )
            if emoji_layer is not None:
                painter.drawImage(0, 0, emoji_layer)

            painter.end()

            return image

        except Exception as e:
            import traceback
            traceback.print_exc()
            return None

    def _make_prepared_canvas_key(self, json_content):
        """Create a stable cache key for the current JSON content."""
        if not json_content:
            return None
        try:
            return hashlib.sha1(json_content.encode("utf-8")).hexdigest()
        except Exception:
            return str(len(json_content))

    def _ensure_canvas_prepared(self, json_content):
        """
        Prepare the hidden MainWindow canvas for fast re-rendering.

        This is the expensive part (load_strands/apply_loaded_strands). We do it once per
        JSON content, and reuse for quick toggles (background + emoji settings).
        """
        key = self._make_prepared_canvas_key(json_content)
        if key and key == self._prepared_canvas_key and self._prepared_bounds is not None:
            return True

        main_window = self._get_main_window()
        if main_window is None:
            return False

        from openstrandstudio.src.save_load_manager import load_strands, apply_loaded_strands
        import tempfile

        canvas = main_window.canvas

        # Clear existing strands
        canvas.strands = []
        canvas.strand_colors = {}
        canvas.selected_strand = None
        canvas.current_strand = None

        # Parse JSON content
        data = json.loads(json_content)

        # Handle history format - extract current state data
        if data.get('type') == 'OpenStrandStudioHistory':
            current_step = data.get('current_step', 1)
            states = data.get('states', [])
            current_data = None
            for state in states:
                if state['step'] == current_step:
                    current_data = state['data']
                    break
            if not current_data:
                return False
        else:
            current_data = data

        # Write to temp file for load_strands (it requires a file path)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump(current_data, tmp)
            temp_path = tmp.name

        try:
            strands, groups, _, _, _, _, _, shadow_overrides = load_strands(temp_path, canvas)
        finally:
            try:
                os.unlink(temp_path)
            except Exception:
                pass

        apply_loaded_strands(canvas, strands, groups, shadow_overrides)

        # Configure canvas for export/preview rendering
        canvas.show_grid = False
        canvas.show_control_points = False
        canvas.shadow_enabled = False
        canvas.should_draw_names = False

        if hasattr(canvas, 'is_attaching'):
            canvas.is_attaching = False
        if hasattr(canvas, 'attach_preview_strand'):
            canvas.attach_preview_strand = None

        # IMPORTANT for speed: keep the canvas un-panned/un-zoomed so Strand.draw can
        # use its faster path (it falls back to slow drawing when panned/zoomed).
        if hasattr(canvas, "zoom_factor"):
            canvas.zoom_factor = 1.0
        if hasattr(canvas, "pan_offset_x"):
            canvas.pan_offset_x = 0
        if hasattr(canvas, "pan_offset_y"):
            canvas.pan_offset_y = 0

        for strand in canvas.strands:
            strand.should_draw_shadow = False

        # Calculate bounds and set canvas size dynamically (helps internal optimizations)
        bounds = self._calculate_strands_bounds(canvas)
        canvas_width = max(800, min(4000, int(bounds.width())))
        canvas_height = max(600, min(3000, int(bounds.height())))
        canvas.setFixedSize(canvas_width, canvas_height)

        self._prepared_canvas_key = key
        self._prepared_bounds = bounds
        return True

    def _rerender_preview_if_possible(self):
        """Re-render the current preview image if we have JSON in memory."""
        if not self.current_json_data:
            return
        scale_factor = self.scale_combo.currentData()
        image = self._generate_image_in_memory(self.current_json_data, scale_factor)
        if image and not image.isNull():
            self.current_image = image
            self._update_preview_background_style()
            self.preview_widget.set_qimage(image)
            self.export_image_btn.setEnabled(True)
            self.save_color_settings()
