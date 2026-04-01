"""Parallel strand alignment mixin for MxNGeneratorDialog."""

import os
import json
import copy
import math

from PyQt5.QtWidgets import QApplication, QLabel, QHBoxLayout, QSpinBox
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QBrush

from ui_utils import _get_active_strands, _set_active_strands


class AlignmentMixin:
    """Mixin providing parallel strand alignment pipeline, angle preview, and presets."""

    def _update_align_parallel_button_state(self):
        """Enable align parallel button only when continuation has been generated (_4/_5 strands exist)."""
        # Guard: button may not exist during initialization
        if not hasattr(self, 'align_parallel_btn'):
            return

        # Check if we have _4/_5 strands in current data
        has_continuation = False
        if self.current_json_data:
            try:
                data = json.loads(self.current_json_data)
                strands = _get_active_strands(data)

                has_continuation = any(
                    s.get('layer_name', '').endswith('_4') or s.get('layer_name', '').endswith('_5')
                    for s in strands
                )
            except:
                pass

        self.align_parallel_btn.setEnabled(has_continuation)
        if hasattr(self, 'preview_angles_btn'):
            self.preview_angles_btn.setEnabled(has_continuation)

        # Update tooltip
        if not has_continuation:
            self.align_parallel_btn.setToolTip("Generate continuation first (need _4/_5 strands)")
        else:
            self.align_parallel_btn.setToolTip("Make horizontal _4/_5 strands parallel with equal spacing")

        self._update_calc_count_label()

    def _update_calc_count_label(self):
        """Update the label showing estimated number of calculations for alignment."""
        if not hasattr(self, 'calc_count_label'):
            return

        # Need continuation data to count strands
        if not self.current_json_data:
            self.calc_count_label.setText("")
            return

        try:
            data = json.loads(self.current_json_data)
            strands = _get_active_strands(data)

            # Count horizontal and vertical _4/_5 strands using k-based grouping
            m = self.m_spinner.value()
            n = self.n_spinner.value()
            k = self.emoji_k_spinner.value() if hasattr(self, 'emoji_k_spinner') else 0
            direction = "cw" if (hasattr(self, 'emoji_cw_radio') and self.emoji_cw_radio.isChecked()) else "ccw"
            is_lh = self.lh_radio.isChecked()

            if is_lh:
                from mxn_lh_continuation import _build_k_based_strand_sets as build_sets_lh
                build_sets = build_sets_lh
            else:
                from mxn_rh_continuation import _build_k_based_strand_sets as build_sets_rh
                build_sets = build_sets_rh

            h_names_set, h_order_list, v_names_set, v_order_list = build_sets(m, n, k, direction)

            # Count _4/_5 strands that match k-based groups
            h_count = 0
            v_count = 0
            for s in strands:
                ln = s.get('layer_name', '')
                if ln.endswith('_4') or ln.endswith('_5'):
                    if ln in h_names_set:
                        h_count += 1
                    elif ln in v_names_set:
                        v_count += 1

            if h_count == 0 and v_count == 0:
                self.calc_count_label.setText("")
                return

            h_pairs = (h_count + 1) // 2  # ceiling division for odd counts (middle strand is solo pair)
            v_pairs = (v_count + 1) // 2

            pair_ext_max = self.pair_ext_max_spin.value()
            pair_ext_step = self.pair_ext_step_spin.value()
            ext_steps = len(range(0, pair_ext_max + pair_ext_step, pair_ext_step)) if pair_ext_step > 0 else 1

            h_combos = ext_steps ** h_pairs
            v_combos = ext_steps ** v_pairs
            total = h_combos + v_combos
            use_gpu = (
                hasattr(self, 'use_gpu_cb') and
                self.use_gpu_cb.isEnabled() and
                self.use_gpu_cb.isChecked()
            )

            label_lines = [
                f"Calculations: H={h_combos:,} ({h_count} strands, {h_pairs} pairs) + "
                f"V={v_combos:,} ({v_count} strands, {v_pairs} pairs) = {total:,} total"
            ]

            h_guard = get_alignment_combo_guard(
                h_combos,
                h_pairs,
                pair_ext_max,
                pair_ext_step,
                use_gpu=use_gpu,
            )
            v_guard = get_alignment_combo_guard(
                v_combos,
                v_pairs,
                pair_ext_max,
                pair_ext_step,
                use_gpu=use_gpu,
            )

            if h_guard:
                label_lines.append(
                    f"CPU guard: H search too large, use Pair ext step >= {h_guard['suggested_step']}px "
                    f"(~{h_guard['suggested_total_combos']:,} combos)."
                )
            if v_guard:
                label_lines.append(
                    f"CPU guard: V search too large, use Pair ext step >= {v_guard['suggested_step']}px "
                    f"(~{v_guard['suggested_total_combos']:,} combos)."
                )

            self.calc_count_label.setText("\n".join(label_lines))
        except Exception:
            self.calc_count_label.setText("")

    def _on_angle_spin_changed(self):
        """Update the angle preview when spinbox values change."""
        if self._angle_preview_active and self._angle_preview_data:
            self._draw_angle_preview(self._angle_preview_data)

    def _on_hv_set_toggle(self):
        """Redraw H/V set labels when checkboxes are toggled."""
        if self._angle_preview_active and self._angle_preview_data:
            # Re-draw full angle preview (includes labels)
            self._draw_angle_preview(self._angle_preview_data)
        elif self.current_image:
            # No angle preview active — draw labels on the base image
            self._draw_hv_set_labels_only()

    def _draw_hv_set_labels_only(self):
        """Draw H/V set labels as a widget overlay without modifying the base image."""
        if not self.current_image:
            return

        show_h = self.show_h_set_cb.isChecked()
        show_v = self.show_v_set_cb.isChecked()

        if not show_h and not show_v:
            # Nothing to show — restore base image
            self.preview_widget.set_qimage(self.current_image)
            self.preview_widget.set_overlay_lines([])
            return

        # Compute the H/V sets from current parameters
        h_order_23, v_order_23 = self._get_current_order_lists_23()

        def convert_23_to_45(order_23):
            out = []
            for label in order_23:
                parts = label.split("_")
                if len(parts) != 2:
                    continue
                out.append(f"{parts[0]}_{'4' if parts[1] == '2' else '5'}")
            return out

        h_order = convert_23_to_45(h_order_23)
        v_order = convert_23_to_45(v_order_23)

        self.preview_widget.set_qimage(self.current_image)
        self.preview_widget.set_overlay_lines(
            self._build_hv_set_overlay_lines(
                h_order if show_h else None,
                v_order if show_v else None
            )
        )

    def _build_hv_set_overlay_lines(self, h_order, v_order):
        """Build H/V set labels as plain text lines for preview overlay."""
        lines = []
        if h_order:
            lines.append("H: " + ", ".join(h_order))
        if v_order:
            lines.append("V: " + ", ".join(v_order))
        return lines

    def _get_current_order_lists_23(self):
        """Return (_2/_3) horizontal and vertical order lists for current m/n/k/direction and variant."""
        m = self.m_spinner.value()
        n = self.n_spinner.value()
        k = self.emoji_k_spinner.value() if hasattr(self, "emoji_k_spinner") else 0
        direction = "cw" if (hasattr(self, "emoji_cw_radio") and self.emoji_cw_radio.isChecked()) else "ccw"

        try:
            if hasattr(self, "lh_radio") and self.lh_radio.isChecked():
                from mxn_lh_continuation import get_horizontal_order_k, get_vertical_order_k
            else:
                from mxn_rh_continuation import get_horizontal_order_k, get_vertical_order_k

            h_order = get_horizontal_order_k(m, n, k, direction) or []
            v_order = get_vertical_order_k(m, n, k, direction) or []
            return h_order, v_order
        except Exception as e:
            print(f"Failed to build order lists for pair controls: {e}")
            return [], []

    def _build_opposite_pairs(self, order_list):
        """
        Build first-last opposite pairs from a perimeter order list.
        Example: [a,b,c,d] -> [(a,d), (b,c)]
        """
        total = len(order_list)
        return [(order_list[i], order_list[total - 1 - i]) for i in range(total // 2)]

    def _clear_layout_widgets(self, layout):
        """Delete all items in a layout recursively."""
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            child_widget = item.widget()
            if child_layout is not None:
                self._clear_layout_widgets(child_layout)
            if child_widget is not None:
                child_widget.deleteLater()

    def _refresh_pair_extension_controls(self, preserve_values=True):
        """Rebuild H/V opposite-pair extension rows from current k-order."""
        if not hasattr(self, "h_pair_group_layout") or not hasattr(self, "v_pair_group_layout"):
            return

        prev_h = {}
        prev_v = {}
        if preserve_values and hasattr(self, "h_pair_ext_spins"):
            for pair, spin in self.h_pair_ext_spins.items():
                prev_h[f"{pair[0]}|{pair[1]}"] = spin.value()
        if preserve_values and hasattr(self, "v_pair_ext_spins"):
            for pair, spin in self.v_pair_ext_spins.items():
                prev_v[f"{pair[0]}|{pair[1]}"] = spin.value()

        h_order, v_order = self._get_current_order_lists_23()
        h_pairs = self._build_opposite_pairs(h_order)
        v_pairs = self._build_opposite_pairs(v_order)

        self._clear_layout_widgets(self.h_pair_group_layout)
        self._clear_layout_widgets(self.v_pair_group_layout)
        self.h_pair_ext_spins = {}
        self.v_pair_ext_spins = {}

        if not h_pairs:
            self.h_pair_group_layout.addWidget(QLabel("No pairs"))
        for left, right in h_pairs:
            row = QHBoxLayout()
            lbl = QLabel(f"{left} <-> {right}")
            lbl.setStyleSheet("color: #bbb;")
            spin = QSpinBox()
            spin.setRange(-200, 500)
            spin.setSingleStep(4)
            spin.setSuffix("px")
            spin.setToolTip("Apply this extension to both strands in the pair")
            key = f"{left}|{right}"
            spin.setValue(prev_h.get(key, 0))
            spin.valueChanged.connect(self._on_pair_extension_changed)
            spin.valueChanged.connect(self._auto_save_alignment_preset)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(spin)
            self.h_pair_group_layout.addLayout(row)
            self.h_pair_ext_spins[(left, right)] = spin

        if not v_pairs:
            self.v_pair_group_layout.addWidget(QLabel("No pairs"))
        for left, right in v_pairs:
            row = QHBoxLayout()
            lbl = QLabel(f"{left} <-> {right}")
            lbl.setStyleSheet("color: #bbb;")
            spin = QSpinBox()
            spin.setRange(-200, 500)
            spin.setSingleStep(4)
            spin.setSuffix("px")
            spin.setToolTip("Apply this extension to both strands in the pair")
            key = f"{left}|{right}"
            spin.setValue(prev_v.get(key, 0))
            spin.valueChanged.connect(self._on_pair_extension_changed)
            spin.valueChanged.connect(self._auto_save_alignment_preset)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(spin)
            self.v_pair_group_layout.addLayout(row)
            self.v_pair_ext_spins[(left, right)] = spin

    def _build_pair_extension_maps(self):
        """Return two maps ({base_label:_2/_3 -> value}) for horizontal and vertical pairs."""
        h_map = {}
        v_map = {}

        for (left, right), spin in getattr(self, "h_pair_ext_spins", {}).items():
            value = spin.value()
            h_map[left] = value
            h_map[right] = value

        for (left, right), spin in getattr(self, "v_pair_ext_spins", {}).items():
            value = spin.value()
            v_map[left] = value
            v_map[right] = value

        return h_map, v_map

    def _reset_pair_extension_values(self):
        """Reset all dynamic pair extension controls to 0."""
        for spin in getattr(self, "h_pair_ext_spins", {}).values():
            spin.blockSignals(True)
            spin.setValue(0)
            spin.blockSignals(False)
        for spin in getattr(self, "v_pair_ext_spins", {}).values():
            spin.blockSignals(True)
            spin.setValue(0)
            spin.blockSignals(False)

    def _on_pair_extension_changed(self):
        """Directly apply extension to _4/_5 starts when spinbox changes (no alignment algorithm)."""
        if not self._continuation_json_data:
            return

        try:
            import math

            scale_factor = self.scale_combo.currentData()

            # Per-pair extension maps keyed by _2/_3 labels (e.g. "4_2", "1_3")
            h_ext_map, v_ext_map = self._build_pair_extension_maps()

            # Parse original continuation data (fresh copy)
            data = json.loads(self._continuation_json_data)
            data = copy.deepcopy(data)

            strands = _get_active_strands(data)

            if not strands:
                return

            # Build lookup for quick access
            strand_lookup = {s["layer_name"]: s for s in strands}

            # Find _4/_5 strands and their corresponding _2/_3 strands
            for strand in strands:
                if strand.get("type") != "AttachedStrand":
                    continue

                layer_name = strand.get("layer_name", "")

                # Process _4 strands
                if layer_name.endswith("_4"):
                    # Find corresponding _2 strand
                    base_name = layer_name[:-1]  # e.g., "1_" from "1_4"
                    s2_name = base_name + "2"
                    ext_value = h_ext_map.get(s2_name, v_ext_map.get(s2_name, 0))

                    if ext_value == 0:
                        continue  # No extension needed for this pair

                    if s2_name in strand_lookup:
                        s2 = strand_lookup[s2_name]
                        # Get _2/_3 direction
                        s2_dx = s2["end"]["x"] - s2["start"]["x"]
                        s2_dy = s2["end"]["y"] - s2["start"]["y"]
                        s2_len = math.sqrt(s2_dx**2 + s2_dy**2)

                        if s2_len > 0.001:
                            # Normalize direction
                            nx = s2_dx / s2_len
                            ny = s2_dy / s2_len

                            # Extend _4 start along _2 direction
                            old_start = strand["start"]
                            new_start_x = old_start["x"] + ext_value * nx
                            new_start_y = old_start["y"] + ext_value * ny

                            # Update _4 start (keep end fixed!)
                            strand["start"] = {"x": new_start_x, "y": new_start_y}
                            if strand.get("control_points") and len(strand["control_points"]) > 0:
                                strand["control_points"][0] = {"x": new_start_x, "y": new_start_y}

                            # Update control_point_center
                            strand["control_point_center"] = {
                                "x": (new_start_x + strand["end"]["x"]) / 2,
                                "y": (new_start_y + strand["end"]["y"]) / 2,
                            }

                            # Update _2 end to match _4 start
                            s2["end"] = {"x": new_start_x, "y": new_start_y}
                            if s2.get("control_points") and len(s2["control_points"]) > 1:
                                s2["control_points"][1] = {"x": new_start_x, "y": new_start_y}
                            s2["control_point_center"] = {
                                "x": (s2["start"]["x"] + new_start_x) / 2,
                                "y": (s2["start"]["y"] + new_start_y) / 2,
                            }

                # Process _5 strands
                elif layer_name.endswith("_5"):
                    # Find corresponding _3 strand
                    base_name = layer_name[:-1]  # e.g., "1_" from "1_5"
                    s3_name = base_name + "3"
                    ext_value = h_ext_map.get(s3_name, v_ext_map.get(s3_name, 0))

                    if ext_value == 0:
                        continue  # No extension needed for this pair

                    if s3_name in strand_lookup:
                        s3 = strand_lookup[s3_name]
                        # Get _2/_3 direction
                        s3_dx = s3["end"]["x"] - s3["start"]["x"]
                        s3_dy = s3["end"]["y"] - s3["start"]["y"]
                        s3_len = math.sqrt(s3_dx**2 + s3_dy**2)

                        if s3_len > 0.001:
                            # Normalize direction
                            nx = s3_dx / s3_len
                            ny = s3_dy / s3_len

                            # Extend _5 start along _3 direction
                            old_start = strand["start"]
                            new_start_x = old_start["x"] + ext_value * nx
                            new_start_y = old_start["y"] + ext_value * ny

                            # Update _5 start (keep end fixed!)
                            strand["start"] = {"x": new_start_x, "y": new_start_y}
                            if strand.get("control_points") and len(strand["control_points"]) > 0:
                                strand["control_points"][0] = {"x": new_start_x, "y": new_start_y}

                            # Update control_point_center
                            strand["control_point_center"] = {
                                "x": (new_start_x + strand["end"]["x"]) / 2,
                                "y": (new_start_y + strand["end"]["y"]) / 2,
                            }

                            # Update _3 end to match _5 start
                            s3["end"] = {"x": new_start_x, "y": new_start_y}
                            if s3.get("control_points") and len(s3["control_points"]) > 1:
                                s3["control_points"][1] = {"x": new_start_x, "y": new_start_y}
                            s3["control_point_center"] = {
                                "x": (s3["start"]["x"] + new_start_x) / 2,
                                "y": (s3["start"]["y"] + new_start_y) / 2,
                            }

            # Update strands in data
            _set_active_strands(data, strands)

            # Update current JSON data
            self.current_json_data = json.dumps(data, indent=2)

            # Invalidate geometry cache but keep emoji assignments
            self._prepared_canvas_key = None
            self._prepared_bounds = None
            self._cached_strand_layer = None
            self._cached_strand_layer_key = None
            self._emoji_renderer.clear_render_cache()

            # Re-render
            image = self._generate_image_in_memory(self.current_json_data, scale_factor)

            if image and not image.isNull():
                self.current_image = image
                self.preview_widget.set_qimage(image)
                active_h = sum(1 for s in self.h_pair_ext_spins.values() if s.value() != 0)
                active_v = sum(1 for s in self.v_pair_ext_spins.values() if s.value() != 0)
                self.status_label.setText(f"Pair extensions applied: H pairs={active_h}, V pairs={active_v}")
            else:
                self.status_label.setText("Failed to render")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_label.setText(f"Extension error: {str(e)}")

    def _on_angle_mode_changed(self):
        """Re-run preview when angle mode dropdown changes."""
        if self.current_json_data and self.preview_angles_btn.isEnabled():
            self.preview_angle_ranges()

    def preview_angle_ranges(self):
        """Preview the angle ranges for parallel alignment with dotted lines."""
        if not self.current_json_data:
            self.status_label.setText("No pattern data available")
            return

        m = self.m_spinner.value()
        n = self.n_spinner.value()

        try:
            # Parse current JSON data
            data = json.loads(self.current_json_data)
            strands = _get_active_strands(data)

            if not strands:
                self.status_label.setText("No strands found")
                return

            # Get preview data (use k-based grouping for correct H/V sets)
            k = self.emoji_k_spinner.value() if hasattr(self, 'emoji_k_spinner') else 0
            direction = "cw" if (hasattr(self, 'emoji_cw_radio') and self.emoji_cw_radio.isChecked()) else "ccw"
            angle_mode = self.angle_mode_combo.currentData() if hasattr(self, 'angle_mode_combo') else "first_strand"
            preview_fn = get_parallel_alignment_preview_lh if self.lh_radio.isChecked() else get_parallel_alignment_preview_rh
            preview_data = preview_fn(strands, n, m, k=k, direction=direction, angle_mode=angle_mode)
            self._angle_preview_data = preview_data

            # Update spin boxes with detected angles
            if preview_data["horizontal"]:
                h_data = preview_data["horizontal"]
                self.h_angle_min_spin.setValue(math.floor(h_data["angle_min"]))
                self.h_angle_max_spin.setValue(math.ceil(h_data["angle_max"]))
                print(f"Horizontal order: {h_data.get('strand_order', [])}")
                print(f"  First: {h_data['first_name']}, Last: {h_data['last_name']}")
                print(f"  Initial angle: {h_data['initial_angle']:.1f}\u00b0")
                print(f"  Range: {h_data['angle_min']:.1f}\u00b0 to {h_data['angle_max']:.1f}\u00b0")

            if preview_data["vertical"]:
                v_data = preview_data["vertical"]
                self.v_angle_min_spin.setValue(math.floor(v_data["angle_min"]))
                self.v_angle_max_spin.setValue(math.ceil(v_data["angle_max"]))
                print(f"Vertical order: {v_data.get('strand_order', [])}")
                print(f"  First: {v_data['first_name']}, Last: {v_data['last_name']}")
                print(f"  Initial angle: {v_data['initial_angle']:.1f}\u00b0")
                print(f"  Range: {v_data['angle_min']:.1f}\u00b0 to {v_data['angle_max']:.1f}\u00b0")

            # Draw preview with dotted lines
            self._draw_angle_preview(preview_data)

            self._angle_preview_active = True
            self.status_label.setText("Angle ranges shown. Edit values and click Align Parallel.")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_label.setText(f"Error previewing angles: {str(e)}")

    def _draw_angle_preview(self, preview_data):
        """Draw dotted lines on the preview showing angle ranges."""
        if not self.current_image:
            return

        import math

        # Get scale factor and bounds for coordinate transformation
        scale_factor = self.scale_combo.currentData()
        bounds = self._prepared_bounds or QRectF(0, 0, 1200, 900)
        offset_x = bounds.x()
        offset_y = bounds.y()

        def transform_coord(x, y):
            """Transform strand coordinates to image coordinates."""
            img_x = (x - offset_x) * scale_factor
            img_y = (y - offset_y) * scale_factor
            return img_x, img_y

        # Create a copy of the current image to draw on
        preview_image = self.current_image.copy()
        painter = QPainter(preview_image)
        painter.setRenderHint(QPainter.Antialiasing)

        line_length = 150 * scale_factor  # Scale line length too

        # Draw horizontal angle preview (cyan/teal color)
        if preview_data["horizontal"]:
            h_data = preview_data["horizontal"]

            # First strand - draw from start position
            start_x, start_y = transform_coord(h_data["first_start"]["x"], h_data["first_start"]["y"])

            # Draw min angle line (dotted)
            pen = QPen(QColor(0, 255, 255), 4, Qt.DashLine)
            painter.setPen(pen)
            angle_min_rad = math.radians(self.h_angle_min_spin.value())
            end_x = start_x + line_length * math.cos(angle_min_rad)
            end_y = start_y + line_length * math.sin(angle_min_rad)
            painter.drawLine(int(start_x), int(start_y), int(end_x), int(end_y))

            # Draw max angle line (dotted)
            angle_max_rad = math.radians(self.h_angle_max_spin.value())
            end_x = start_x + line_length * math.cos(angle_max_rad)
            end_y = start_y + line_length * math.sin(angle_max_rad)
            painter.drawLine(int(start_x), int(start_y), int(end_x), int(end_y))

            # Draw arc between angles
            arc_radius = 60 * scale_factor
            pen.setWidth(3)
            painter.setPen(pen)
            arc_rect = QRectF(start_x - arc_radius, start_y - arc_radius, arc_radius * 2, arc_radius * 2)
            start_angle = int(-self.h_angle_min_spin.value() * 16)  # Qt uses 1/16 degree
            span_angle = int(-(self.h_angle_max_spin.value() - self.h_angle_min_spin.value()) * 16)
            painter.drawArc(arc_rect, start_angle, span_angle)

            # Label with background
            label_text = f"H: {self.h_angle_min_spin.value()}\u00b0 to {self.h_angle_max_spin.value()}\u00b0"
            font = painter.font()
            font.setPointSize(int(12 * scale_factor))
            font.setBold(True)
            painter.setFont(font)
            # Draw background rect
            painter.fillRect(int(start_x + 10), int(start_y - 25 * scale_factor),
                           int(len(label_text) * 8 * scale_factor), int(20 * scale_factor),
                           QColor(0, 0, 0, 180))
            painter.setPen(QPen(QColor(0, 255, 255), 1))
            painter.drawText(int(start_x + 15), int(start_y - 10 * scale_factor), label_text)

            # Also draw for last strand (lighter color)
            last_x, last_y = transform_coord(h_data["last_start"]["x"], h_data["last_start"]["y"])
            pen = QPen(QColor(0, 200, 200), 3, Qt.DotLine)
            painter.setPen(pen)
            # Last strand goes opposite direction
            angle_min_rad = math.radians(self.h_angle_min_spin.value() + 180)
            end_x = last_x + line_length * math.cos(angle_min_rad)
            end_y = last_y + line_length * math.sin(angle_min_rad)
            painter.drawLine(int(last_x), int(last_y), int(end_x), int(end_y))
            angle_max_rad = math.radians(self.h_angle_max_spin.value() + 180)
            end_x = last_x + line_length * math.cos(angle_max_rad)
            end_y = last_y + line_length * math.sin(angle_max_rad)
            painter.drawLine(int(last_x), int(last_y), int(end_x), int(end_y))

            # Draw a circle at first/last start points
            painter.setPen(QPen(QColor(0, 255, 255), 3))
            painter.setBrush(QBrush(QColor(0, 255, 255, 100)))
            painter.drawEllipse(int(start_x - 8), int(start_y - 8), 16, 16)
            painter.drawEllipse(int(last_x - 8), int(last_y - 8), 16, 16)

        # Draw vertical angle preview (orange color)
        if preview_data["vertical"]:
            v_data = preview_data["vertical"]

            # First strand
            start_x, start_y = transform_coord(v_data["first_start"]["x"], v_data["first_start"]["y"])

            # Draw min angle line
            pen = QPen(QColor(255, 165, 0), 4, Qt.DashLine)
            painter.setPen(pen)
            angle_min_rad = math.radians(self.v_angle_min_spin.value())
            end_x = start_x + line_length * math.cos(angle_min_rad)
            end_y = start_y + line_length * math.sin(angle_min_rad)
            painter.drawLine(int(start_x), int(start_y), int(end_x), int(end_y))

            # Draw max angle line
            angle_max_rad = math.radians(self.v_angle_max_spin.value())
            end_x = start_x + line_length * math.cos(angle_max_rad)
            end_y = start_y + line_length * math.sin(angle_max_rad)
            painter.drawLine(int(start_x), int(start_y), int(end_x), int(end_y))

            # Arc
            arc_radius = 60 * scale_factor
            pen.setWidth(3)
            painter.setPen(pen)
            arc_rect = QRectF(start_x - arc_radius, start_y - arc_radius, arc_radius * 2, arc_radius * 2)
            start_angle = int(-self.v_angle_min_spin.value() * 16)
            span_angle = int(-(self.v_angle_max_spin.value() - self.v_angle_min_spin.value()) * 16)
            painter.drawArc(arc_rect, start_angle, span_angle)

            # Label with background
            label_text = f"V: {self.v_angle_min_spin.value()}\u00b0 to {self.v_angle_max_spin.value()}\u00b0"
            painter.fillRect(int(start_x + 10), int(start_y - 25 * scale_factor),
                           int(len(label_text) * 8 * scale_factor), int(20 * scale_factor),
                           QColor(0, 0, 0, 180))
            painter.setPen(QPen(QColor(255, 165, 0), 1))
            painter.drawText(int(start_x + 15), int(start_y - 10 * scale_factor), label_text)

            # Last strand
            last_x, last_y = transform_coord(v_data["last_start"]["x"], v_data["last_start"]["y"])
            pen = QPen(QColor(255, 120, 0), 3, Qt.DotLine)
            painter.setPen(pen)
            angle_min_rad = math.radians(self.v_angle_min_spin.value() + 180)
            end_x = last_x + line_length * math.cos(angle_min_rad)
            end_y = last_y + line_length * math.sin(angle_min_rad)
            painter.drawLine(int(last_x), int(last_y), int(end_x), int(end_y))
            angle_max_rad = math.radians(self.v_angle_max_spin.value() + 180)
            end_x = last_x + line_length * math.cos(angle_max_rad)
            end_y = last_y + line_length * math.sin(angle_max_rad)
            painter.drawLine(int(last_x), int(last_y), int(end_x), int(end_y))

            # Draw circles at first/last start points
            painter.setPen(QPen(QColor(255, 165, 0), 3))
            painter.setBrush(QBrush(QColor(255, 165, 0, 100)))
            painter.drawEllipse(int(start_x - 8), int(start_y - 8), 16, 16)
            painter.drawEllipse(int(last_x - 8), int(last_y - 8), 16, 16)

        # Draw H/V set labels at the top of the image
        show_h = hasattr(self, 'show_h_set_cb') and self.show_h_set_cb.isChecked()
        show_v = hasattr(self, 'show_v_set_cb') and self.show_v_set_cb.isChecked()

        overlay_lines = []
        if show_h or show_v:
            h_order = preview_data["horizontal"].get("strand_order", []) if (show_h and preview_data["horizontal"]) else None
            v_order = preview_data["vertical"].get("strand_order", []) if (show_v and preview_data["vertical"]) else None
            overlay_lines = self._build_hv_set_overlay_lines(h_order, v_order)

        painter.end()

        # Update preview widget
        self.preview_widget.set_qimage(preview_image)
        self.preview_widget.set_overlay_lines(overlay_lines)

    def align_parallel_strands(self):
        """Align horizontal AND vertical _4/_5 strands to be parallel with equal spacing."""
        if not self.current_json_data:
            self.status_label.setText("No pattern data available")
            return

        m = self.m_spinner.value()
        n = self.n_spinner.value()
        scale_factor = self.scale_combo.currentData()

        # Track results (initialized here so save always has access)
        h_success = False
        v_success = False
        h_angle = None
        v_angle = None
        h_gap = None
        v_gap = None
        h_result = {}
        v_result = {}
        attempt_count = [0]  # Mutable counter for attempt callback

        try:
            use_gpu = self.use_gpu_cb.isChecked() if hasattr(self, 'use_gpu_cb') else False
            backend_label = self._get_alignment_backend_label(use_gpu)
            self.status_label.setText(f"Searching for parallel alignment... [{backend_label}]")
            QApplication.processEvents()

            # Parse current JSON data
            data = json.loads(self.current_json_data)

            # Get strands from the data
            strands = _get_active_strands(data)

            if not strands:
                self.status_label.setText("No strands found in current data")
                return

            # Check if we have _4/_5 strands (continuation must be generated first)
            has_continuation = any(
                s.get('layer_name', '').endswith('_4') or s.get('layer_name', '').endswith('_5')
                for s in strands
            )
            if not has_continuation:
                self.status_label.setText("Generate continuation first (need _4/_5 strands)")
                return

            if self.lh_radio.isChecked():
                align_horizontal_fn = align_horizontal_strands_parallel_lh
                align_vertical_fn = align_vertical_strands_parallel_lh
                apply_alignment_fn = apply_parallel_alignment_lh
            else:
                align_horizontal_fn = align_horizontal_strands_parallel_rh
                align_vertical_fn = align_vertical_strands_parallel_rh
                apply_alignment_fn = apply_parallel_alignment_rh

            # Read pair extension search parameters from UI
            pair_ext_max = self.pair_ext_max_spin.value()
            pair_ext_step = self.pair_ext_step_spin.value()

            # Check if using custom angles
            use_custom = self.use_custom_angles_cb.isChecked()
            h_custom_min = self.h_angle_min_spin.value() if use_custom else None
            h_custom_max = self.h_angle_max_spin.value() if use_custom else None
            v_custom_min = self.v_angle_min_spin.value() if use_custom else None
            v_custom_max = self.v_angle_max_spin.value() if use_custom else None

            angle_mode = self.angle_mode_combo.currentData() if hasattr(self, 'angle_mode_combo') else "first_strand"

            # ============================================================
            # SETUP OUTPUT FOLDERS FOR ALL ATTEMPTS
            # ============================================================
            script_dir = os.path.dirname(os.path.abspath(__file__))
            is_lh = self.lh_radio.isChecked()
            pattern_type = "lh" if is_lh else "rh"
            k = self.emoji_k_spinner.value() if hasattr(self, 'emoji_k_spinner') else 0
            direction = "cw" if (hasattr(self, 'emoji_cw_radio') and self.emoji_cw_radio.isChecked()) else "ccw"
            diagram_name = f"{m}x{n}"

            print("\n" + "=" * 60)
            print("  ALIGN PARALLEL \u2014 START")
            print("=" * 60)
            print(f"  Pattern: {pattern_type.upper()} {m}x{n} | k={k} | dir={direction}")
            print(f"  Backend: {backend_label}")
            if use_custom:
                print(f"  Angle mode: CUSTOM")
                print(f"    H range: {h_custom_min}\u00b0 to {h_custom_max}\u00b0")
                print(f"    V range: {v_custom_min}\u00b0 to {v_custom_max}\u00b0")
            else:
                print(f"  Angle mode: AUTO ({angle_mode})")
            print(f"  Pair ext: max={pair_ext_max}px, step={pair_ext_step}px")
            print("=" * 60, flush=True)

            base_output_dir = os.path.join(
                script_dir,
                "mxn", "mxn_output", diagram_name, f"k_{k}_{direction}_{pattern_type}"
            )
            attempt_dir = os.path.join(base_output_dir, "attempt_options")
            os.makedirs(attempt_dir, exist_ok=True)

            best_h_result_info = [None]  # Mutable container for horizontal result info (set after H phase)
            h_attempt_count = [0]
            v_attempt_count = [0]
            attempt_render_contexts = {}

            def get_attempt_render_context(direction_type):
                """
                Build a prepared-canvas render context once per direction search.
                Keeps alignment logic unchanged while avoiding per-attempt JSON reload.
                """
                context = attempt_render_contexts.get(direction_type)
                if context is not None:
                    return context

                try:
                    # Build stage data using the current "strands" list in this scope.
                    stage_data = copy.deepcopy(data)
                    _set_active_strands(stage_data, strands)

                    stage_json = json.dumps(stage_data, separators=(',', ':'))
                    if not self._ensure_canvas_prepared(stage_json):
                        return None

                    main_window = self._get_main_window()
                    if not main_window:
                        return None

                    canvas = main_window.canvas
                    strand_lookup = {
                        s.layer_name: s for s in canvas.strands
                        if hasattr(s, "layer_name") and s.layer_name
                    }
                    snapshot = self._snapshot_canvas_geometry(strand_lookup)
                    context = {
                        "canvas": canvas,
                        "strand_lookup": strand_lookup,
                        "snapshot": snapshot,
                    }
                    attempt_render_contexts[direction_type] = context
                    return context
                except Exception as context_error:
                    print(f"Fast attempt render context failed ({direction_type}): {context_error}")
                    return None

            def generate_analysis_text(angle_deg, extension, result, direction_type, attempt_num, h_result_info=None):
                """Generate detailed analysis text for this configuration."""
                import math

                lines = []
                lines.append("=" * 80)
                lines.append("                    PARALLEL ALIGNMENT ANALYSIS")
                lines.append("=" * 80)

                is_valid = result.get("valid", False)
                status_str = "VALID" if is_valid else "INVALID"
                lines.append(f"Pattern: {pattern_type.upper()} {m}x{n} | K: {k} | Direction: {direction.upper()}")
                lines.append(f"Attempt: #{attempt_num} | Angle: {angle_deg:.1f}\u00b0 | Extension: {extension}px | Status: {status_str}")
                lines.append("=" * 80)
                lines.append("")

                # Get configurations
                configs = result.get("configurations")
                if not configs and result.get("fallback"):
                    configs = result["fallback"].get("configurations")

                if not configs or len(configs) < 2:
                    lines.append(f"No configurations available. Reason: {result.get('reason', 'Unknown')}")
                    return "\n".join(lines)

                # Get data from result or fallback
                data_source = result if result.get("configurations") else result.get("fallback", result)
                gaps = data_source.get("gaps", [])
                signed_gaps = data_source.get("signed_gaps", [])
                min_gap = data_source.get("min_gap", 46.0)
                max_gap = data_source.get("max_gap", 69.0)
                average_gap = data_source.get("average_gap", 0)

                dir_label = "HORIZONTAL" if direction_type == "horizontal" else "VERTICAL"
                lines.append("-" * 80)
                lines.append(f"                           {dir_label} STRANDS")
                lines.append("-" * 80)
                lines.append("")

                # Extract strand names in order
                strand_names = []
                for cfg in configs:
                    strand_info = cfg.get("strand", {})
                    strand_4_5 = strand_info.get("strand_4_5", {})
                    name = strand_4_5.get("layer_name", "unknown")
                    strand_names.append(name)

                lines.append(f"Strand Order: {strand_names}")
                lines.append("")

                # Reference line info (first strand)
                first_cfg = configs[0]
                first_start = first_cfg.get("extended_start", {})
                first_end = first_cfg.get("end", {})

                dx = first_end.get("x", 0) - first_start.get("x", 0)
                dy = first_end.get("y", 0) - first_start.get("y", 0)
                line_len = math.sqrt(dx*dx + dy*dy)

                if line_len > 0.001:
                    line_ux, line_uy = dx / line_len, dy / line_len
                    # Perpendicular unit vector - matches algorithm's cross product sign convention
                    perp_ux, perp_uy = line_uy, -line_ux
                else:
                    line_ux, line_uy = 1.0, 0.0
                    perp_ux, perp_uy = 0.0, -1.0

                line_angle = math.degrees(math.atan2(dy, dx))

                lines.append("+" + "-" * 78 + "+")
                lines.append(f"|  REFERENCE LINE (First Strand: {strand_names[0]})" + " " * (78 - 35 - len(strand_names[0])) + "|")
                lines.append("+" + "-" * 78 + "+")
                lines.append(f"|  Line Vector:      ({line_ux:+.3f}, {line_uy:+.3f})   |  Angle: {line_angle:.1f}\u00b0" + " " * 20 + "|")
                lines.append(f"|  Perpendicular:    ({perp_ux:+.3f}, {perp_uy:+.3f})   |  (positive direction for gaps)" + " " * 8 + "|")
                lines.append("+" + "-" * 78 + "+")
                lines.append("")

                # First to last reference
                if len(configs) >= 2:
                    last_cfg = configs[-1]
                    last_start = last_cfg.get("extended_start", {})

                    # Calculate signed distance from first to last
                    # Using the perpendicular: distance = (point - line_start) dot perpendicular
                    fx, fy = first_start.get("x", 0), first_start.get("y", 0)
                    lx, ly = last_start.get("x", 0), last_start.get("y", 0)
                    first_to_last_dist = (lx - fx) * perp_ux + (ly - fy) * perp_uy
                    expected_sign = "+" if first_to_last_dist >= 0 else "-"

                    lines.append("+" + "-" * 78 + "+")
                    lines.append("|  REFERENCE DIRECTION (First -> Last)" + " " * 40 + "|")
                    lines.append("+" + "-" * 78 + "+")
                    lines.append(f"|  {strand_names[0]} -> {strand_names[-1]}" + " " * (78 - 6 - len(strand_names[0]) - len(strand_names[-1])) + "|")
                    lines.append(f"|  Signed Distance: {first_to_last_dist:+.1f} px" + " " * 50 + "|")
                    ref_vec = f"({perp_ux:+.3f}, {perp_uy:+.3f})" if first_to_last_dist >= 0 else f"({-perp_ux:+.3f}, {-perp_uy:+.3f})"
                    lines.append(f"|  Direction Vector: {ref_vec}  <- perpendicular unit vector" + " " * 18 + "|")
                    lines.append(f"|  Expected Sign: {expected_sign} (all gaps must be {expected_sign} to maintain order)" + " " * 15 + "|")
                    lines.append("+" + "-" * 78 + "+")
                    lines.append("")

                # Gap table
                lines.append("+" + "-" * 12 + "+" + "-" * 12 + "+" + "-" * 21 + "+" + "-" * 8 + "+" + "-" * 22 + "+")
                lines.append("|   PAIR     |  DISTANCE  |  DIRECTION VECTOR   |  SIGN  |  STATUS              |")
                lines.append("+" + "-" * 12 + "+" + "-" * 12 + "+" + "-" * 21 + "+" + "-" * 8 + "+" + "-" * 22 + "+")

                crossing_detected = []
                gap_details = []  # Store details for each gap

                for i in range(len(configs) - 1):
                    cfg1 = configs[i]
                    cfg2 = configs[i + 1]

                    name1 = strand_names[i]
                    name2 = strand_names[i + 1]
                    pair_str = f"{name1}->{name2}"

                    # Get the LINE (from cfg1) and POINT (from cfg2)
                    line_start = cfg1.get("extended_start", {})
                    line_end = cfg1.get("end", {})
                    point = cfg2.get("extended_start", {})

                    lsx, lsy = line_start.get("x", 0), line_start.get("y", 0)
                    lex, ley = line_end.get("x", 0), line_end.get("y", 0)
                    px, py = point.get("x", 0), point.get("y", 0)

                    # Calculate this pair's line direction and perpendicular
                    pair_dx = lex - lsx
                    pair_dy = ley - lsy
                    pair_len = math.sqrt(pair_dx*pair_dx + pair_dy*pair_dy)

                    if pair_len > 0.001:
                        pair_line_ux, pair_line_uy = pair_dx / pair_len, pair_dy / pair_len
                        pair_perp_ux, pair_perp_uy = pair_line_uy, -pair_line_ux
                    else:
                        pair_line_ux, pair_line_uy = 1.0, 0.0
                        pair_perp_ux, pair_perp_uy = 0.0, -1.0

                    # Get gap info
                    if i < len(signed_gaps):
                        sg = signed_gaps[i]
                        abs_gap = abs(sg)

                        # Note: signed_gaps already has sign flipped for odd indices in the algorithm
                        sign = "+" if sg >= 0 else "-"

                        # Direction vector - use first strand's perpendicular for consistency
                        # (since algorithm flips sign for odd gaps to normalize to first strand's direction)
                        if sg >= 0:
                            dir_vec = f"({perp_ux:+.3f}, {perp_uy:+.3f})"
                        else:
                            dir_vec = f"({-perp_ux:+.3f}, {-perp_uy:+.3f})"

                        # Check if matches expected
                        matches = (sign == expected_sign)

                        # Determine status
                        if not matches:
                            status = "X CROSSED!"
                            crossing_detected.append((name1, name2, sign, expected_sign))
                        elif abs_gap < min_gap:
                            status = f"X TOO SMALL (<{min_gap:.0f})"
                        elif abs_gap > max_gap:
                            status = f"X TOO LARGE (>{max_gap:.0f})"
                        else:
                            status = "V VALID"

                        lines.append(f"| {pair_str:10} | {abs_gap:8.1f}px | {dir_vec:19} |   {sign}    | {status:20} |")

                        # Store details for later
                        gap_details.append({
                            "pair": pair_str,
                            "line_start": (lsx, lsy),
                            "line_end": (lex, ley),
                            "point": (px, py),
                            "signed_dist": sg,
                            "line_vec": (pair_line_ux, pair_line_uy),
                            "perp_vec": (pair_perp_ux, pair_perp_uy),
                            "sign_flipped": (i % 2 == 1),  # Odd gaps have sign flipped
                        })
                    else:
                        lines.append(f"| {pair_str:10} |     N/A    |         N/A         |  N/A   | N/A                  |")

                lines.append("+" + "-" * 12 + "+" + "-" * 12 + "+" + "-" * 21 + "+" + "-" * 8 + "+" + "-" * 22 + "+")

                # Add detailed calculation info
                if gap_details:
                    lines.append("")
                    lines.append("DETAILED GAP CALCULATIONS:")
                    lines.append("-" * 80)
                    for idx, detail in enumerate(gap_details):
                        line_strand = strand_names[idx]
                        point_strand = strand_names[idx + 1]
                        lines.append(f"  {detail['pair']}:")
                        lines.append(f"    LINE from {line_strand}:")
                        lines.append(f"      Start: ({detail['line_start'][0]:.1f}, {detail['line_start'][1]:.1f})")
                        lines.append(f"      End:   ({detail['line_end'][0]:.1f}, {detail['line_end'][1]:.1f})")
                        lines.append(f"    POINT from {point_strand}:")
                        lines.append(f"      Coords: ({detail['point'][0]:.1f}, {detail['point'][1]:.1f})")
                        lines.append(f"    Line Vector:   ({detail['line_vec'][0]:+.3f}, {detail['line_vec'][1]:+.3f})")
                        lines.append(f"    Perp Vector:   ({detail['perp_vec'][0]:+.3f}, {detail['perp_vec'][1]:+.3f})")
                        sign_note = " (sign flipped for _5 line)" if detail.get('sign_flipped') else ""
                        lines.append(f"    Signed Distance: {detail['signed_dist']:+.2f} px{sign_note}")
                        lines.append("")
                lines.append("")

                # Crossing warning
                if crossing_detected:
                    for (n1, n2, actual, expected) in crossing_detected:
                        lines.append(f"  WARNING: CROSSING DETECTED at {n1} -> {n2}:")
                        exp_vec = f"({perp_ux:+.3f}, {perp_uy:+.3f})" if expected == "+" else f"({-perp_ux:+.3f}, {-perp_uy:+.3f})"
                        act_vec = f"({perp_ux:+.3f}, {perp_uy:+.3f})" if actual == "+" else f"({-perp_ux:+.3f}, {-perp_uy:+.3f})"
                        lines.append(f"      Expected vector: {exp_vec}")
                        lines.append(f"      Actual vector:   {act_vec}  <- OPPOSITE DIRECTION!")
                        lines.append(f"      This means {n2} is on the WRONG SIDE of {n1}'s line.")
                    lines.append("")

                # Summary
                lines.append("Summary:")
                lines.append(f"  * Valid Range: {min_gap:.1f} px - {max_gap:.1f} px")
                if gaps:
                    lines.append(f"  * Average Gap: {average_gap:.1f} px")
                    lines.append(f"  * Min Gap: {min(gaps):.1f} px")
                    lines.append(f"  * Max Gap: {max(gaps):.1f} px")

                if crossing_detected:
                    lines.append(f"  * Direction Check: X FAILED ({len(crossing_detected)} crossing(s) detected)")
                else:
                    lines.append("  * Direction Check: V ALL VECTORS MATCH REFERENCE")

                # Gap check
                gaps_in_range = all(min_gap <= g <= max_gap for g in gaps) if gaps else True
                if gaps_in_range and not crossing_detected:
                    lines.append("  * Gap Check: V PASSED")
                elif not gaps_in_range:
                    lines.append("  * Gap Check: X FAILED (gaps out of range)")

                lines.append("")
                lines.append("=" * 80)
                lines.append("                              FINAL RESULT")
                lines.append("=" * 80)

                reason = result.get("reason", "")
                if is_valid:
                    lines.append(f"  {dir_label}: V PASSED (Angle: {angle_deg:.1f}deg, Avg Gap: {average_gap:.1f} px)")
                    lines.append("")
                    lines.append("  Overall: V VALID SOLUTION")
                else:
                    lines.append(f"  {dir_label}: X FAILED ({reason})")
                    lines.append("")
                    lines.append("  Overall: X INVALID")

                lines.append("=" * 80)

                # For vertical attempts, include the horizontal result that was used
                if direction_type == "vertical" and h_result_info is not None:
                    lines.append("")
                    lines.append("")
                    lines.append("=" * 80)
                    lines.append("        HORIZONTAL RESULT USED (Best from horizontal phase)")
                    lines.append("=" * 80)
                    lines.append(f"  Status: {'SUCCESS' if h_result_info.get('success') else 'FAILED/FALLBACK'}")
                    lines.append(f"  Angle: {h_result_info.get('angle', 'N/A')}")
                    lines.append(f"  Average Gap: {h_result_info.get('avg_gap', 'N/A')}")
                    lines.append(f"  Gap Variance: {h_result_info.get('gap_variance', 'N/A')}")
                    lines.append(f"  First-Last Distance: {h_result_info.get('first_last_distance', 'N/A')}")
                    lines.append(f"  Pair Extensions: {h_result_info.get('pair_extensions', 'N/A')}")
                    h_strands = h_result_info.get('strand_details', [])
                    if h_strands:
                        lines.append(f"  Strand Order: {[s['name'] for s in h_strands]}")
                        for s in h_strands:
                            lines.append(f"    {s['name']}: extension={s['extension']:.1f}px, length={s['length']:.1f}px")
                    lines.append("=" * 80)

                return "\n".join(lines)

            def save_attempt_callback(angle_deg, extension, result, direction_type):
                """Save each attempted configuration as an image and analysis text."""
                attempt_count[0] += 1
                if direction_type == "horizontal":
                    h_attempt_count[0] += 1
                else:
                    v_attempt_count[0] += 1

                try:
                    # Attempt-level validity is per-direction only; never treat it as
                    # a full solution (full solution requires BOTH horizontal+vertical pass).
                    is_valid = result.get("valid", False)
                    save_horizontal_valid = (
                        self.save_horizontal_valid_cb.isChecked()
                        if hasattr(self, "save_horizontal_valid_cb")
                        else True
                    )
                    if direction_type == "horizontal" and is_valid and not save_horizontal_valid:
                        return
                    output_dir = attempt_dir

                    # Create filename (without extension)
                    status = "valid" if is_valid else "invalid"
                    base_filename = f"{pattern_type}_{m}x{n}_k{k}_{direction}_{direction_type}_ext{extension}_ang{angle_deg:.1f}_{status}"

                    # Get configurations - either from direct result or from fallback
                    configs = result.get("configurations")
                    if not configs and result.get("fallback"):
                        configs = result["fallback"].get("configurations")

                    # Use reduced scale for invalid images to speed up export
                    attempt_scale = scale_factor if is_valid else scale_factor * 0.0625

                    # Fast path: render from a prepared canvas by applying/restoring geometry in memory.
                    img = None
                    context = get_attempt_render_context(direction_type)
                    if context is not None:
                        modified_layers = set()
                        try:
                            if configs:
                                modified_layers = self._apply_alignment_configs_to_canvas(
                                    context["strand_lookup"], configs
                                )
                            img = self._render_current_canvas_image(context["canvas"], attempt_scale)
                        except Exception as fast_render_error:
                            print(
                                f"Fast attempt render failed ({direction_type}, "
                                f"ang={angle_deg:.1f}, ext={extension}): {fast_render_error}"
                            )
                            img = None
                        finally:
                            try:
                                self._restore_canvas_geometry(
                                    context["strand_lookup"],
                                    context["snapshot"],
                                    layer_names=modified_layers
                                )
                            except Exception as restore_error:
                                print(
                                    f"Fast attempt restore failed ({direction_type}): "
                                    f"{restore_error}"
                                )
                                attempt_render_contexts.pop(direction_type, None)
                                img = None

                    # Fallback path: keep old JSON-based flow for robustness.
                    if img is None or img.isNull():
                        if context is not None:
                            print(
                                f"Using JSON fallback render ({direction_type}, "
                                f"ang={angle_deg:.1f}, ext={extension})"
                            )
                        strands_copy = copy.deepcopy(strands)
                        if configs:
                            # Create a result-like dict with the configurations
                            result_for_apply = {"success": True, "configurations": configs}
                            strands_copy = apply_alignment_fn(strands_copy, result_for_apply)

                        # Update JSON data with this configuration
                        data_copy = copy.deepcopy(data)
                        _set_active_strands(data_copy, strands_copy)

                        json_copy = json.dumps(data_copy, separators=(',', ':'))
                        img = self._generate_image_in_memory(json_copy, attempt_scale)

                    if img and not img.isNull():
                        img_path = os.path.join(output_dir, base_filename + ".png")
                        img.save(img_path)

                        # Generate and save analysis text
                        h_info_for_txt = best_h_result_info[0] if direction_type == "vertical" else None
                        analysis_text = generate_analysis_text(angle_deg, extension, result, direction_type, attempt_count[0], h_result_info=h_info_for_txt)
                        txt_path = os.path.join(output_dir, base_filename + ".txt")
                        with open(txt_path, 'w', encoding='utf-8') as f:
                            f.write(analysis_text)

                        # Save JSON with this attempt's alignment applied
                        try:
                            attempt_strands = copy.deepcopy(strands)
                            if configs:
                                attempt_result = {"success": True, "configurations": configs}
                                attempt_strands = apply_alignment_fn(attempt_strands, attempt_result)
                            attempt_data = copy.deepcopy(data)
                            _set_active_strands(attempt_data, attempt_strands)
                            json_path = os.path.join(output_dir, base_filename + ".json")
                            with open(json_path, 'w', encoding='utf-8') as jf:
                                json.dump(attempt_data, jf, separators=(',', ':'))
                        except Exception as json_err:
                            print(f"  Error saving attempt JSON: {json_err}")
                except Exception as e:
                    print(f"  Error saving attempt {attempt_count[0]}: {e}")

            # ============================================================
            # FREEZE EMOJI ASSIGNMENTS BEFORE ALIGNMENT
            # ============================================================
            # Capture current emoji-to-strand mapping so emojis stay with their
            # original strands even after positions change during alignment
            print("\n  [1/4] Freezing emoji assignments...")

            if self._ensure_canvas_prepared(self.current_json_data):
                main_window = self._get_main_window()
                if main_window:
                    canvas = main_window.canvas
                    bounds = self._prepared_bounds
                    emoji_settings = {
                        "show": self.show_emojis_checkbox.isChecked() if hasattr(self, "show_emojis_checkbox") else True,
                        "k": self.emoji_k_spinner.value() if hasattr(self, "emoji_k_spinner") else 0,
                        "direction": "cw" if (hasattr(self, "emoji_cw_radio") and self.emoji_cw_radio.isChecked()) else "ccw",
                    }
                    self._emoji_renderer.freeze_emoji_assignments(canvas, bounds, m, n, emoji_settings)

            # ============================================================
            # HORIZONTAL ALIGNMENT
            # ============================================================
            print(f"\n  [2/4] HORIZONTAL alignment \u2014 searching...", flush=True)

            h_result = align_horizontal_fn(
                strands,
                n,
                angle_step_degrees=0.5,
                max_extension=100.0,
                custom_angle_min=h_custom_min,
                custom_angle_max=h_custom_max,
                on_config_callback=save_attempt_callback,
                max_pair_extension=pair_ext_max,
                pair_extension_step=pair_ext_step,
                m=m, k=k, direction=direction,
                use_gpu=use_gpu,
                angle_mode=angle_mode,
            )

            if h_result["success"] or h_result.get("is_fallback"):
                strands = apply_alignment_fn(strands, h_result)
                h_success = h_result["success"]  # Only True for real solutions, not fallback
                h_angle = h_result.get("angle_degrees", 0)
                h_gap = h_result.get("average_gap", 0)
                if h_result.get("is_fallback"):
                    worst_gap = h_result.get("worst_gap", 0)
                    print(f"        H result: FALLBACK  angle={h_angle:.2f}\u00b0  avg_gap={h_gap:.1f}px  worst_gap={worst_gap:.1f}px  ({h_attempt_count[0]} attempts saved)")
                else:
                    print(f"        H result: OK  angle={h_angle:.2f}\u00b0  gap={h_gap:.1f}px  ({h_attempt_count[0]} attempts saved)")
            else:
                print(f"        H result: FAILED  {h_result.get('message', 'Unknown')}  ({h_attempt_count[0]} attempts saved)")

            # Build horizontal result info for vertical txt files
            h_info = {
                'success': h_result.get("success", False),
                'angle': f"{h_result.get('angle_degrees', 0):.2f}\u00b0",
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

            # ============================================================
            # VERTICAL ALIGNMENT
            # ============================================================
            print(f"\n  [3/4] VERTICAL alignment \u2014 searching...", flush=True)

            v_result = align_vertical_fn(
                strands,
                n,
                m,
                angle_step_degrees=0.5,
                max_extension=100.0,
                custom_angle_min=v_custom_min,
                custom_angle_max=v_custom_max,
                on_config_callback=save_attempt_callback,
                max_pair_extension=pair_ext_max,
                pair_extension_step=pair_ext_step,
                k=k, direction=direction,
                use_gpu=use_gpu,
                angle_mode=angle_mode,
            )

            if v_result["success"] or v_result.get("is_fallback"):
                strands = apply_alignment_fn(strands, v_result)
                v_success = v_result["success"]  # Only True for real solutions, not fallback
                v_angle = v_result.get("angle_degrees", 0)
                v_gap = v_result.get("average_gap", 0)
                if v_result.get("is_fallback"):
                    worst_gap = v_result.get("worst_gap", 0)
                    print(f"        V result: FALLBACK  angle={v_angle:.2f}\u00b0  avg_gap={v_gap:.1f}px  worst_gap={worst_gap:.1f}px  ({v_attempt_count[0]} attempts saved)")
                else:
                    print(f"        V result: OK  angle={v_angle:.2f}\u00b0  gap={v_gap:.1f}px  ({v_attempt_count[0]} attempts saved)")
            else:
                print(f"        V result: FAILED  {v_result.get('message', 'Unknown')}  ({v_attempt_count[0]} attempts saved)")

            # ============================================================
            # UPDATE AND RENDER
            # ============================================================
            print(f"\n  [4/4] Rendering final image...")
            _set_active_strands(data, strands)

            # Update current JSON data
            self.current_json_data = json.dumps(data, indent=2)

            # Invalidate cache and re-render
            # Use clear_render_cache() to keep emoji assignments stable (same emojis)
            # while only clearing the glyph image cache
            self._prepared_canvas_key = None
            self._prepared_bounds = None
            self._cached_strand_layer = None
            self._cached_strand_layer_key = None
            self._emoji_renderer.clear_render_cache()

            self.status_label.setText("Re-rendering with parallel alignment...")
            QApplication.processEvents()

            # Generate new image (always, so we can save it)
            image = self._generate_image_in_memory(self.current_json_data, scale_factor)

            if image and not image.isNull():
                self.current_image = image
                self.preview_widget.set_qimage(image)

                # Build status message
                status_parts = []
                if h_success:
                    status_parts.append(f"H: {h_angle:.1f}\u00b0, gap={h_gap:.1f}px")
                else:
                    status_parts.append("H: failed")
                if v_success:
                    status_parts.append(f"V: {v_angle:.1f}\u00b0, gap={v_gap:.1f}px")
                else:
                    status_parts.append("V: failed")

                self.status_label.setText(
                    f"Parallel alignment [{backend_label}]: " + " | ".join(status_parts)
                )
            else:
                self.status_label.setText("Failed to render image")

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error during alignment: {str(e)}")
            # h_success, v_success, h_angle, v_angle are already initialized before try block

        # ============================================================
        # SAVE TO PARALLEL OUTPUT FOLDERS (always runs)
        # ============================================================
        h_str = f"angle={h_angle:.1f}\u00b0" if h_angle is not None else "N/A"
        v_str = f"angle={v_angle:.1f}\u00b0" if v_angle is not None else "N/A"
        print(f"\n  Saving outputs...  H={'OK' if h_success else 'FAIL'}({h_str})  V={'OK' if v_success else 'FAIL'}({v_str})")
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            is_lh = self.lh_radio.isChecked()
            pattern_type = "lh" if is_lh else "rh"
            k = self.emoji_k_spinner.value() if hasattr(self, 'emoji_k_spinner') else 0
            direction = "cw" if (hasattr(self, 'emoji_cw_radio') and self.emoji_cw_radio.isChecked()) else "ccw"

            # Create diagram name based on pattern parameters
            diagram_name = f"{m}x{n}"

            # Base output directory: mxn_output/{diagram_name}/k_{k}_{direction}_{pattern_type}/
            pattern_type = "lh" if is_lh else "rh"
            base_output_dir = os.path.join(
                script_dir,
                "mxn", "mxn_output", diagram_name, f"k_{k}_{direction}_{pattern_type}"
            )

            # Determine if solution is valid (both H and V succeeded)
            is_valid_solution = h_success and v_success

            if is_valid_solution:
                output_subdir = os.path.join(base_output_dir, "best_solution")
            else:
                output_subdir = os.path.join(base_output_dir, "partial_options")

            os.makedirs(output_subdir, exist_ok=True)

            # Create filename with pattern details
            h_status = f"h{h_angle:.1f}" if h_success and h_angle is not None else "h_fail"
            v_status = f"v{v_angle:.1f}" if v_success and v_angle is not None else "v_fail"
            filename_base = f"mxn_{pattern_type}_{m}x{n}_k{k}_{direction}_{h_status}_{v_status}"

            # Save image
            if self.current_image and not self.current_image.isNull():
                img_path = os.path.join(output_subdir, f"{filename_base}.png")
                save_result = self.current_image.save(img_path)
                result_type = "SOLUTION" if is_valid_solution else "PARTIAL"
                print(f"  {result_type} image -> {os.path.basename(img_path)}")
            else:
                print(f"  ERROR: No image to save!")

            # Save aligned JSON next to the image in the same output folder.
            json_path = os.path.join(output_subdir, f"{filename_base}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(self.current_json_data)

            # Save TXT with full alignment details (both H and V)
            txt_path = os.path.join(output_subdir, f"{filename_base}.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"Pattern: {pattern_type.upper()} {m}x{n} k={k} {direction}\n")
                f.write(f"Result: {'SOLUTION' if is_valid_solution else 'INVALID'}\n")
                f.write("=" * 60 + "\n\n")

                # Horizontal details
                f.write("HORIZONTAL ALIGNMENT\n")
                f.write("-" * 40 + "\n")
                if h_success:
                    f.write(f"Status: SUCCESS\n")
                    f.write(f"Angle: {h_angle:.2f}\u00b0\n")
                    f.write(f"Average gap: {h_gap:.2f} px\n")
                    f.write(f"Gap variance: {h_result.get('gap_variance', 'N/A')}\n")
                    f.write(f"First-last distance: {h_result.get('first_last_distance', 'N/A')}\n")
                    f.write(f"Pair extensions: {h_result.get('pair_extensions', 'N/A')}\n")
                    for i, cfg in enumerate(h_result.get("configurations", [])):
                        name = cfg.get("strand", {}).get("strand_4_5", {}).get("layer_name", f"strand_{i}")
                        ext = cfg.get("extension", 0)
                        length = cfg.get("length", 0)
                        f.write(f"  {name}: extension={ext:.1f}px, length={length:.1f}px\n")
                else:
                    f.write(f"Status: FAILED\n")
                    f.write(f"Message: {h_result.get('message', 'Unknown')}\n")

                f.write("\n")

                # Vertical details (includes horizontal reference)
                f.write("VERTICAL ALIGNMENT\n")
                f.write("-" * 40 + "\n")
                if v_success:
                    f.write(f"Status: SUCCESS\n")
                    f.write(f"Angle: {v_angle:.2f}\u00b0\n")
                    f.write(f"Average gap: {v_gap:.2f} px\n")
                    f.write(f"Gap variance: {v_result.get('gap_variance', 'N/A')}\n")
                    f.write(f"First-last distance: {v_result.get('first_last_distance', 'N/A')}\n")
                    f.write(f"Pair extensions: {v_result.get('pair_extensions', 'N/A')}\n")
                    for i, cfg in enumerate(v_result.get("configurations", [])):
                        name = cfg.get("strand", {}).get("strand_4_5", {}).get("layer_name", f"strand_{i}")
                        ext = cfg.get("extension", 0)
                        length = cfg.get("length", 0)
                        f.write(f"  {name}: extension={ext:.1f}px, length={length:.1f}px\n")
                else:
                    f.write(f"Status: FAILED\n")
                    f.write(f"Message: {v_result.get('message', 'Unknown')}\n")

                f.write("\n")
                f.write("HORIZONTAL REFERENCE (for vertical context)\n")
                f.write("-" * 40 + "\n")
                f.write(f"H angle: {h_angle:.2f}\u00b0\n" if h_angle is not None else "H angle: N/A\n")
                f.write(f"H gap: {h_gap:.2f} px\n" if h_gap is not None else "H gap: N/A\n")
                f.write(f"H success: {h_success}\n")

                f.write("\n")
                f.write("PARAMETERS\n")
                f.write("-" * 40 + "\n")
                f.write(f"H angle range: {self.h_angle_min_spin.value()}\u00b0 to {self.h_angle_max_spin.value()}\u00b0\n")
                f.write(f"V angle range: {self.v_angle_min_spin.value()}\u00b0 to {self.v_angle_max_spin.value()}\u00b0\n")
                f.write(f"Custom angles: {self.use_custom_angles_cb.isChecked()}\n")
                f.write(f"Pair ext max: {self.pair_ext_max_spin.value()}px\n")
                f.write(f"Pair ext step: {self.pair_ext_step_spin.value()}px\n")
                f.write(f"Max extension: 100.0px\n")
                f.write(f"Angle step: 0.5\u00b0\n")
                f.write(f"Strand width: 46px\n")

            print(f"  Output dir: {output_subdir}")
            print("=" * 60)
            print("  ALIGN PARALLEL \u2014 DONE")
            result_label = "SOLUTION" if is_valid_solution else "PARTIAL"
            print(f"  Result: {result_label}")
            if h_success:
                print(f"    H: angle={h_angle:.1f}\u00b0  gap={h_gap:.1f}px")
            else:
                print(f"    H: FAILED")
            if v_success:
                print(f"    V: angle={v_angle:.1f}\u00b0  gap={v_gap:.1f}px")
            else:
                print(f"    V: FAILED")
            if attempt_count[0] > 0:
                print(f"  Attempt images saved: {attempt_count[0]}")
            print("=" * 60 + "\n")

            if not (h_success or v_success):
                self.status_label.setText(
                    "Could not find parallel alignment (saved to partial_options folder)"
                )

        except Exception as save_error:
            import traceback
            traceback.print_exc()
            print(f"Error saving output: {str(save_error)}")
            self.status_label.setText(f"Error saving: {str(save_error)}")

    def _auto_save_alignment_preset(self):
        """Auto-save preset whenever any alignment parameter changes in the UI."""
        if self._suppress_auto_save:
            return
        m = self.m_spinner.value()
        n = self.n_spinner.value()
        k = self.emoji_k_spinner.value() if hasattr(self, 'emoji_k_spinner') else 0
        direction = "cw" if (hasattr(self, 'emoji_cw_radio') and self.emoji_cw_radio.isChecked()) else "ccw"
        pattern_type = "lh" if self.lh_radio.isChecked() else "rh"
        self._save_alignment_preset(m, n, k, direction, pattern_type)

    def _save_alignment_preset(self, m, n, k, direction, pattern_type):
        """Save current alignment UI parameters as a preset for this m/n/k/direction."""
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            preset_dir = os.path.join(
                script_dir,
                "mxn", "mxn_presets"
            )
            os.makedirs(preset_dir, exist_ok=True)

            # Collect opposite pair extension values
            h_opposite_pairs = {}
            for (left, right), spin in getattr(self, "h_pair_ext_spins", {}).items():
                h_opposite_pairs[f"{left}|{right}"] = spin.value()
            v_opposite_pairs = {}
            for (left, right), spin in getattr(self, "v_pair_ext_spins", {}).items():
                v_opposite_pairs[f"{left}|{right}"] = spin.value()

            preset = {
                "m": m,
                "n": n,
                "k": k,
                "direction": direction,
                "pattern_type": pattern_type,
                "use_custom_angles": self.use_custom_angles_cb.isChecked(),
                "h_angle_min": self.h_angle_min_spin.value(),
                "h_angle_max": self.h_angle_max_spin.value(),
                "v_angle_min": self.v_angle_min_spin.value(),
                "v_angle_max": self.v_angle_max_spin.value(),
                "pair_ext_max": self.pair_ext_max_spin.value(),
                "pair_ext_step": self.pair_ext_step_spin.value(),
                "save_horizontal_valid": (
                    self.save_horizontal_valid_cb.isChecked()
                    if hasattr(self, "save_horizontal_valid_cb")
                    else True
                ),
                "h_opposite_pairs": h_opposite_pairs,
                "v_opposite_pairs": v_opposite_pairs,
            }

            filename = f"preset_{pattern_type}_{m}x{n}_k{k}_{direction}.json"
            preset_path = os.path.join(preset_dir, filename)
            with open(preset_path, "w", encoding="utf-8") as f:
                json.dump(preset, f, indent=2)

        except Exception as e:
            print(f"Error saving preset: {e}")

    def _load_alignment_preset(self, m, n, k, direction, pattern_type):
        """Load alignment preset for this m/n/k/direction if it exists, and apply to UI."""
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            preset_dir = os.path.join(
                script_dir,
                "mxn", "mxn_presets"
            )
            filename = f"preset_{pattern_type}_{m}x{n}_k{k}_{direction}.json"
            preset_path = os.path.join(preset_dir, filename)

            if not os.path.exists(preset_path):
                print(f"No preset found: {preset_path}")
                return False

            with open(preset_path, "r", encoding="utf-8") as f:
                preset = json.load(f)

            self.use_custom_angles_cb.setChecked(preset.get("use_custom_angles", False))
            self.h_angle_min_spin.setValue(preset.get("h_angle_min", 0))
            self.h_angle_max_spin.setValue(preset.get("h_angle_max", 40))
            self.v_angle_min_spin.setValue(preset.get("v_angle_min", -90))
            self.v_angle_max_spin.setValue(preset.get("v_angle_max", -50))
            self.pair_ext_max_spin.setValue(preset.get("pair_ext_max", 200))
            self.pair_ext_step_spin.setValue(preset.get("pair_ext_step", 10))
            if hasattr(self, "save_horizontal_valid_cb"):
                self.save_horizontal_valid_cb.setChecked(preset.get("save_horizontal_valid", True))

            # Load opposite pair extension values
            h_opp = preset.get("h_opposite_pairs", {})
            for (left, right), spin in getattr(self, "h_pair_ext_spins", {}).items():
                key = f"{left}|{right}"
                if key in h_opp:
                    spin.setValue(h_opp[key])

            v_opp = preset.get("v_opposite_pairs", {})
            for (left, right), spin in getattr(self, "v_pair_ext_spins", {}).items():
                key = f"{left}|{right}"
                if key in v_opp:
                    spin.setValue(v_opp[key])

            print(f"Preset loaded: {preset_path}")
            return True

        except Exception as e:
            print(f"Error loading preset: {e}")
            return False
