"""Full Auto batch generation dialog."""

import os
import json

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSpinBox,
    QComboBox, QCheckBox, QMessageBox, QTextEdit, QProgressBar,
    QApplication, QGroupBox, QWidget, QScrollArea,
)
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QImage, QPainter

from mxn_emoji_renderer import EmojiRenderer
from ui_utils import EMOJI_SET_ITEMS, _get_active_history_state
from ui_styles import (
    _apply_large_checkbox_indicator,
    _install_custom_checkbox_checkmark,
    _style_toggle_checkbox,
)
from batch_rendering import BatchWorker


class FullAutoDialog(QDialog):
    """Dialog for fully automated batch generation: continuation + parallel alignment."""

    def __init__(self, parent_dialog, parent=None):
        super().__init__(parent or parent_dialog)
        self.parent_dialog = parent_dialog
        self.theme = parent_dialog.theme if parent_dialog else 'dark'
        self._stop_requested = False
        self._running = False
        self._main_window = None
        self._worker = None
        self._emoji_renderer = EmojiRenderer()

        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setup_ui()
        self._initialize_emoji_set()
        self._apply_theme()

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def setup_ui(self):
        self.setWindowTitle('Full Auto Generation')
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # ---- Left panel: parameters ----
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(6)
        left_panel.setMinimumWidth(350)

        # Grid Size Range
        grid_group = QGroupBox("Grid Size Range")
        grid_lay = QGridLayout(grid_group)
        grid_lay.setContentsMargins(8, 8, 8, 8)
        grid_lay.setHorizontalSpacing(8)
        grid_lay.setVerticalSpacing(6)

        grid_lay.addWidget(QLabel("M min:"), 0, 0)
        self.m_min_spin = QSpinBox()
        self.m_min_spin.setRange(1, 10)
        self.m_min_spin.setValue(2)
        grid_lay.addWidget(self.m_min_spin, 0, 1)

        grid_lay.addWidget(QLabel("M max:"), 0, 2)
        self.m_max_spin = QSpinBox()
        self.m_max_spin.setRange(1, 10)
        self.m_max_spin.setValue(3)
        grid_lay.addWidget(self.m_max_spin, 0, 3)

        grid_lay.addWidget(QLabel("N min:"), 1, 0)
        self.n_min_spin = QSpinBox()
        self.n_min_spin.setRange(1, 10)
        self.n_min_spin.setValue(2)
        grid_lay.addWidget(self.n_min_spin, 1, 1)

        grid_lay.addWidget(QLabel("N max:"), 1, 2)
        self.n_max_spin = QSpinBox()
        self.n_max_spin.setRange(1, 10)
        self.n_max_spin.setValue(3)
        grid_lay.addWidget(self.n_max_spin, 1, 3)

        left_layout.addWidget(grid_group)

        # K Range
        k_group = QGroupBox("K Value Range")
        k_lay = QGridLayout(k_group)
        k_lay.setContentsMargins(8, 8, 8, 8)
        k_lay.setHorizontalSpacing(8)
        k_lay.setVerticalSpacing(6)

        k_lay.addWidget(QLabel("K min:"), 0, 0)
        self.k_min_spin = QSpinBox()
        self.k_min_spin.setRange(-9999, 9999)
        self.k_min_spin.setValue(-2)
        k_lay.addWidget(self.k_min_spin, 0, 1)

        k_lay.addWidget(QLabel("K max:"), 0, 2)
        self.k_max_spin = QSpinBox()
        self.k_max_spin.setRange(-9999, 9999)
        self.k_max_spin.setValue(2)
        k_lay.addWidget(self.k_max_spin, 0, 3)

        self.auto_k_range_cb = QCheckBox("Auto K range (per M,N)")
        self.auto_k_range_cb.setChecked(False)
        self.auto_k_range_cb.setToolTip(
            "Automatically compute K range for each (M,N) pair:\n"
            "  M=N: K from -(M-1) to M  (2M values)\n"
            "  M\u2260N: K from -(M+N-1) to (M+N)  (2(M+N) values)"
        )
        self.auto_k_range_cb.stateChanged.connect(self._on_auto_k_toggled)
        k_lay.addWidget(self.auto_k_range_cb, 1, 0, 1, 4)

        left_layout.addWidget(k_group)

        # Options
        opts_group = QGroupBox("Options")
        opts_layout = QVBoxLayout(opts_group)
        opts_layout.setContentsMargins(8, 8, 8, 8)
        opts_layout.setSpacing(6)

        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Direction:"))
        self.cw_cb = QCheckBox("CW")
        self.cw_cb.setChecked(True)
        self.ccw_cb = QCheckBox("CCW")
        self.ccw_cb.setChecked(True)
        dir_layout.addWidget(self.cw_cb)
        dir_layout.addWidget(self.ccw_cb)
        dir_layout.addStretch()
        opts_layout.addLayout(dir_layout)

        hand_layout = QHBoxLayout()
        hand_layout.addWidget(QLabel("Handedness:"))
        self.lh_cb = QCheckBox("LH")
        self.lh_cb.setChecked(True)
        self.rh_cb = QCheckBox("RH")
        self.rh_cb.setChecked(True)
        hand_layout.addWidget(self.lh_cb)
        hand_layout.addWidget(self.rh_cb)
        hand_layout.addStretch()
        opts_layout.addLayout(hand_layout)

        angle_layout = QHBoxLayout()
        angle_layout.addWidget(QLabel("Angle mode:"))
        self.angle_mode_combo = QComboBox()
        self.angle_mode_combo.addItem("First strand \u00b120\u00b0", "first_strand")
        self.angle_mode_combo.addItem("Average \u2194 Gaussian bounds", "avg_gaussian")
        self.angle_mode_combo.setCurrentIndex(1)  # Default to Gaussian
        angle_layout.addWidget(self.angle_mode_combo)
        opts_layout.addLayout(angle_layout)

        left_layout.addWidget(opts_group)

        # Alignment Settings
        align_group = QGroupBox("Alignment Settings")
        align_lay = QGridLayout(align_group)
        align_lay.setContentsMargins(8, 8, 8, 8)
        align_lay.setHorizontalSpacing(8)
        align_lay.setVerticalSpacing(6)

        align_lay.addWidget(QLabel("Pair ext max:"), 0, 0)
        self.pair_ext_max_spin = QSpinBox()
        self.pair_ext_max_spin.setRange(0, 1000)
        self.pair_ext_max_spin.setValue(200)
        self.pair_ext_max_spin.setSingleStep(50)
        self.pair_ext_max_spin.setSuffix("px")
        align_lay.addWidget(self.pair_ext_max_spin, 0, 1)

        align_lay.addWidget(QLabel("Pair ext step:"), 1, 0)
        self.pair_ext_step_spin = QSpinBox()
        self.pair_ext_step_spin.setRange(1, 100)
        self.pair_ext_step_spin.setValue(10)
        self.pair_ext_step_spin.setSingleStep(1)
        self.pair_ext_step_spin.setSuffix("px")
        align_lay.addWidget(self.pair_ext_step_spin, 1, 1)

        align_lay.addWidget(QLabel("Scale:"), 2, 0)
        self.scale_combo = QComboBox()
        self.scale_combo.addItem("1x", 1.0)
        self.scale_combo.addItem("2x", 2.0)
        self.scale_combo.addItem("4x", 4.0)
        self.scale_combo.setCurrentIndex(2)
        align_lay.addWidget(self.scale_combo, 2, 1)

        self.use_gpu_cb = QCheckBox("Use GPU (CuPy)")
        self.use_gpu_cb.setChecked(False)
        align_lay.addWidget(self.use_gpu_cb, 3, 0, 1, 2)

        self.save_horizontal_valid_cb = QCheckBox("Save horizontal valid images/txt/json")
        self.save_horizontal_valid_cb.setChecked(
            self.parent_dialog.save_horizontal_valid_cb.isChecked()
            if (
                self.parent_dialog
                and hasattr(self.parent_dialog, "save_horizontal_valid_cb")
            )
            else True
        )
        self.save_horizontal_valid_cb.setToolTip(
            "When enabled, valid horizontal alignment attempts are exported to the attempt_options folder"
        )
        align_lay.addWidget(self.save_horizontal_valid_cb, 4, 0, 1, 2)

        self.save_pre_align_cb = QCheckBox("Save pre-alignment JSON")
        self.save_pre_align_cb.setChecked(False)
        self.save_pre_align_cb.setToolTip(
            "Save the raw continuation JSON before alignment.\n"
            "Disable for faster batch processing."
        )
        align_lay.addWidget(self.save_pre_align_cb, 5, 0, 1, 2)

        left_layout.addWidget(align_group)

        # Overlay / Emoji Settings
        overlay_group = QGroupBox("Image Overlays")
        overlay_lay = QVBoxLayout(overlay_group)
        overlay_lay.setContentsMargins(8, 8, 8, 8)
        overlay_lay.setSpacing(6)

        emoji_set_row = QHBoxLayout()
        emoji_set_row.addWidget(QLabel("Emoji style:"))
        self.batch_emoji_set_combo = QComboBox()
        for label, value in EMOJI_SET_ITEMS:
            self.batch_emoji_set_combo.addItem(label, value)
        self.batch_emoji_set_combo.currentIndexChanged.connect(self._on_batch_emoji_set_changed)
        emoji_set_row.addWidget(self.batch_emoji_set_combo, 1)
        overlay_lay.addLayout(emoji_set_row)

        self.batch_show_emojis_cb = QCheckBox("Show emoji markers")
        self.batch_show_emojis_cb.setChecked(
            bool(
                self.parent_dialog
                and hasattr(self.parent_dialog, "show_emojis_checkbox")
                and self.parent_dialog.show_emojis_checkbox.isChecked()
            )
        )
        self.batch_show_emojis_cb.setToolTip("Draw animal emoji markers at strand endpoints")
        overlay_lay.addWidget(self.batch_show_emojis_cb)

        self.batch_show_strand_names_cb = QCheckBox("Show strand names")
        self.batch_show_strand_names_cb.setChecked(
            bool(
                self.parent_dialog
                and hasattr(self.parent_dialog, "show_strand_names_checkbox")
                and self.parent_dialog.show_strand_names_checkbox.isChecked()
            )
        )
        self.batch_show_strand_names_cb.setToolTip("Show strand names like '3_2(s)' at each endpoint")
        overlay_lay.addWidget(self.batch_show_strand_names_cb)

        self.batch_show_arrows_cb = QCheckBox("Show rotation arrow + numbers")
        self.batch_show_arrows_cb.setChecked(
            bool(
                self.parent_dialog
                and hasattr(self.parent_dialog, "show_emojis_checkbox")
                and self.parent_dialog.show_emojis_checkbox.isChecked()
            )
        )
        self.batch_show_arrows_cb.setToolTip("Draw rotation direction arrow and number labels")
        overlay_lay.addWidget(self.batch_show_arrows_cb)

        left_layout.addWidget(overlay_group)

        # Combination count label
        self.combo_count_label = QLabel("")
        self.combo_count_label.setWordWrap(True)
        self.combo_count_label.setStyleSheet("color: #ffab40; font-size: 11px;")
        left_layout.addWidget(self.combo_count_label)

        # Connect controls to update count
        for spin in (self.m_min_spin, self.m_max_spin, self.n_min_spin,
                     self.n_max_spin, self.k_min_spin, self.k_max_spin):
            spin.valueChanged.connect(self._update_combo_count)
        for cb in (self.cw_cb, self.ccw_cb, self.lh_cb, self.rh_cb):
            cb.stateChanged.connect(self._update_combo_count)
        self.auto_k_range_cb.stateChanged.connect(self._update_combo_count)
        self._update_combo_count()

        # Run button
        self.run_btn = QPushButton("Run Full Auto")
        self.run_btn.setMinimumHeight(40)
        self.run_btn.setStyleSheet("""
            QPushButton {
                background-color: #2e7d32;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #388e3c; }
            QPushButton:pressed { background-color: #1b5e20; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        self.run_btn.clicked.connect(self.run_pipeline)
        left_layout.addWidget(self.run_btn)

        # Stop button
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setMinimumHeight(35)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #c62828;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #e53935; }
            QPushButton:pressed { background-color: #b71c1c; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        self.stop_btn.clicked.connect(self._request_stop)
        left_layout.addWidget(self.stop_btn)

        left_layout.addStretch()

        # ---- Right panel: progress & log ----
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(5)

        progress_label = QLabel("Progress")
        progress_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        right_layout.addWidget(progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(25)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #3D3D3D;
                border: 1px solid #555;
                border-radius: 3px;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #2e7d32;
                border-radius: 2px;
            }
        """)
        right_layout.addWidget(self.progress_bar)

        self.summary_label = QLabel("Ready")
        self.summary_label.setStyleSheet("color: #aaa; font-size: 12px;")
        self.summary_label.setWordWrap(True)
        right_layout.addWidget(self.summary_label)

        log_label = QLabel("Log")
        log_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        right_layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #ccc;
                border: 1px solid #555;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        right_layout.addWidget(self.log_text)

        # ---- Assemble panels ----
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setWidget(left_panel)
        left_scroll.setMinimumWidth(370)

        main_layout.addWidget(left_scroll)
        main_layout.addWidget(right_panel, 1)
        self._initialize_toggle_checkboxes()

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _iter_toggle_checkboxes(self):
        return self.findChildren(QCheckBox)

    def _initialize_toggle_checkboxes(self):
        for checkbox in self._iter_toggle_checkboxes():
            _apply_large_checkbox_indicator(checkbox, indicator_size=14)
            _install_custom_checkbox_checkmark(checkbox)

    def _restyle_toggle_checkboxes(self):
        is_dark_mode = (self.theme == 'dark')
        for checkbox in self._iter_toggle_checkboxes():
            _style_toggle_checkbox(checkbox, is_dark_mode, checkbox.isEnabled())

    def _apply_theme(self):
        if self.theme == 'dark':
            self.setStyleSheet("""
                QDialog { background-color: #2C2C2C; color: white; }
                QGroupBox {
                    background-color: transparent; color: white;
                    border: 1px solid #555; border-radius: 4px;
                    margin-top: 8px; padding-top: 10px; font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin; left: 10px; padding: 0 3px;
                    background-color: transparent;
                }
                QLabel { color: white; background-color: transparent; }
                QSpinBox, QComboBox {
                    background-color: #3D3D3D; color: white;
                    border: 1px solid #555; padding: 5px; border-radius: 3px; min-height: 20px;
                }
                QSpinBox::up-button, QSpinBox::down-button {
                    background-color: #4D4D4D; border: none; width: 16px;
                }
                QSpinBox::up-button:hover, QSpinBox::down-button:hover { background-color: #5D5D5D; }
                QRadioButton, QCheckBox { color: white; background-color: transparent; }
                QRadioButton::indicator, QCheckBox::indicator { width: 16px; height: 16px; }
                QScrollArea { background-color: #3D3D3D; border: 1px solid #555; border-radius: 4px; }
                QScrollArea > QWidget > QWidget { background-color: #3D3D3D; }
                QPushButton {
                    background-color: #404040; color: white;
                    border: 1px solid #555; padding: 6px 12px; border-radius: 4px;
                }
                QPushButton:hover { background-color: #505050; border: 1px solid #666; }
                QPushButton:pressed { background-color: #353535; }
                QPushButton:disabled { background-color: #2a2a2a; color: #666666; }
            """)
        else:
            self.setStyleSheet("""
                QDialog { background-color: #F5F5F5; color: black; }
                QGroupBox {
                    color: black; border: 1px solid #CCC; border-radius: 4px;
                    margin-top: 8px; padding-top: 10px; font-weight: bold;
                }
                QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
                QLabel { color: black; }
                QSpinBox, QComboBox {
                    background-color: white; color: black;
                    border: 1px solid #CCC; padding: 5px; border-radius: 3px; min-height: 20px;
                }
                QRadioButton, QCheckBox { color: black; }
                QScrollArea { background-color: white; border: 1px solid #CCC; border-radius: 4px; }
                QScrollArea > QWidget > QWidget { background-color: white; }
                QPushButton {
                    background-color: #FFFFFF; color: black;
                    border: 1px solid #CCCCCC; padding: 6px 12px; border-radius: 4px;
                }
                QPushButton:hover { background-color: #E8E8E8; border: 1px solid #AAAAAA; }
                QPushButton:pressed { background-color: #D0D0D0; }
                QPushButton:disabled { background-color: #F0F0F0; color: #AAAAAA; }
            """)
        self._restyle_toggle_checkboxes()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_initial_emoji_set(self):
        if self.parent_dialog is not None:
            if hasattr(self.parent_dialog, "emoji_set_combo"):
                set_name = self.parent_dialog.emoji_set_combo.currentData()
                if set_name:
                    return set_name
            if hasattr(self.parent_dialog, "_emoji_renderer") and self.parent_dialog._emoji_renderer is not None:
                try:
                    return self.parent_dialog._emoji_renderer.get_emoji_set()
                except Exception:
                    pass
        return "default"

    def _initialize_emoji_set(self):
        set_name = self._get_initial_emoji_set()
        self._emoji_renderer.set_emoji_set(set_name)
        if hasattr(self, "batch_emoji_set_combo"):
            idx = self.batch_emoji_set_combo.findData(set_name)
            if idx >= 0:
                self.batch_emoji_set_combo.blockSignals(True)
                self.batch_emoji_set_combo.setCurrentIndex(idx)
                self.batch_emoji_set_combo.blockSignals(False)

    def _on_batch_emoji_set_changed(self):
        set_name = self.batch_emoji_set_combo.currentData() if hasattr(self, "batch_emoji_set_combo") else None
        if set_name:
            self._emoji_renderer.set_emoji_set(set_name)

    def _log(self, msg):
        self.log_text.append(msg)
        QApplication.processEvents()

    def _request_stop(self):
        self._stop_requested = True
        if self._worker:
            self._worker.request_stop()
        self._log("Stop requested... finishing current task.")

    @staticmethod
    def _compute_auto_k_range(m, n):
        """Return (k_min, k_max) for a given (m, n) pair.

        Rules (from the user's specification):
          m == n  : k in [-(m-1), m]         →  2m values
          m != n  : k in [-(m+n-1), (m+n)]   →  2(m+n) values
        """
        if m == n:
            return -(m - 1), m
        else:
            return -(m + n - 1), m + n

    def _on_auto_k_toggled(self, state):
        """Enable / disable the manual K spin boxes when auto-K is toggled."""
        auto = self.auto_k_range_cb.isChecked()
        self.k_min_spin.setEnabled(not auto)
        self.k_max_spin.setEnabled(not auto)
        self._update_combo_count()

    def _get_full_auto_range_error(self):
        """Validate the current full-auto range controls and return an error string if invalid."""
        m_min = self.m_min_spin.value()
        m_max = self.m_max_spin.value()
        n_min = self.n_min_spin.value()
        n_max = self.n_max_spin.value()

        if m_min > m_max:
            return "M min cannot be greater than M max."
        if n_min > n_max:
            return "N min cannot be greater than N max."
        if not self.auto_k_range_cb.isChecked() and self.k_min_spin.value() > self.k_max_spin.value():
            return "K min cannot be greater than K max when Auto K range is disabled."
        return None

    def _update_combo_count(self):
        m_min = self.m_min_spin.value()
        m_max = self.m_max_spin.value()
        n_min = self.n_min_spin.value()
        n_max = self.n_max_spin.value()
        dir_count = int(self.cw_cb.isChecked()) + int(self.ccw_cb.isChecked())
        hand_count = int(self.lh_cb.isChecked()) + int(self.rh_cb.isChecked())
        range_error = self._get_full_auto_range_error()

        if range_error:
            self.combo_count_label.setText(f"Invalid range: {range_error}")
            return

        if self.auto_k_range_cb.isChecked():
            # Count real combinations when auto-K is on (k range varies per m,n)
            total = 0
            for m in range(m_min, m_max + 1):
                for n in range(n_min, n_max + 1):
                    k_lo, k_hi = self._compute_auto_k_range(m, n)
                    total += (k_hi - k_lo + 1) * dir_count * hand_count
            self.combo_count_label.setText(
                f"Auto-K: {total} combinations (K range varies per M,N pair)"
            )
        else:
            m_count = max(0, m_max - m_min + 1)
            n_count = max(0, n_max - n_min + 1)
            k_count = max(0, self.k_max_spin.value() - self.k_min_spin.value() + 1)
            total = m_count * n_count * k_count * dir_count * hand_count
            self.combo_count_label.setText(
                f"Combinations: {m_count}M x {n_count}N x {k_count}K x {dir_count}dir x {hand_count}hand = {total} total"
            )

    def _get_main_window(self):
        if self._main_window is None:
            app = QApplication.instance()
            original_stylesheet = app.styleSheet() if app else ""
            try:
                from openstrandstudio.src.main_window import MainWindow
                self._main_window = MainWindow()
                self._main_window.hide()
                self._main_window.canvas.hide()
            except Exception as e:
                self._log(f"ERROR: Failed to create MainWindow: {e}")
                return None
            finally:
                if app is not None:
                    app.setStyleSheet(original_stylesheet)
                self._apply_theme()
        return self._main_window

    def _load_json_to_canvas(self, json_content):
        from openstrandstudio.src.save_load_manager import load_strands_from_data, apply_loaded_strands

        main_window = self._get_main_window()
        if not main_window:
            return None
        canvas = main_window.canvas

        canvas.strands = []
        canvas.strand_colors = {}
        canvas.selected_strand = None
        canvas.current_strand = None

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

        return QRectF(min_x - padding, min_y - padding,
                      max_x - min_x + 2 * padding, max_y - min_y + 2 * padding)

    def _render_image(self, bounds, scale_factor):
        from openstrandstudio.src.render_utils import RenderUtils

        main_window = self._get_main_window()
        if not main_window:
            return None
        canvas = main_window.canvas

        w = int(bounds.width() * scale_factor)
        h = int(bounds.height() * scale_factor)
        image = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.white)

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

    def _get_colors_from_parent(self):
        colors = {}
        if self.parent_dialog and hasattr(self.parent_dialog, 'colors'):
            for set_num, qcolor in self.parent_dialog.colors.items():
                colors[set_num] = {
                    "r": qcolor.red(), "g": qcolor.green(),
                    "b": qcolor.blue(), "a": qcolor.alpha()
                }
        return colors

    def _apply_colors_to_json(self, json_content, custom_colors):
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

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def run_pipeline(self):
        if self._running:
            return

        self._running = True
        self._stop_requested = False
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_text.clear()
        self.progress_bar.setValue(0)

        # Gather parameters
        m_min, m_max = self.m_min_spin.value(), self.m_max_spin.value()
        n_min, n_max = self.n_min_spin.value(), self.n_max_spin.value()
        auto_k = self.auto_k_range_cb.isChecked()
        k_min_manual, k_max_manual = self.k_min_spin.value(), self.k_max_spin.value()

        directions = []
        if self.cw_cb.isChecked():
            directions.append("cw")
        if self.ccw_cb.isChecked():
            directions.append("ccw")

        handedness = []
        if self.lh_cb.isChecked():
            handedness.append("lh")
        if self.rh_cb.isChecked():
            handedness.append("rh")

        if not directions or not handedness:
            self._log("ERROR: Select at least one direction and one handedness.")
            self._finish()
            return

        range_error = self._get_full_auto_range_error()
        if range_error:
            self._log(f"ERROR: {range_error}")
            self.summary_label.setText(range_error)
            QMessageBox.warning(self, "Invalid Range", range_error)
            self._finish()
            return

        angle_mode = self.angle_mode_combo.currentData()
        pair_ext_max = self.pair_ext_max_spin.value()
        pair_ext_step = self.pair_ext_step_spin.value()
        use_gpu = self.use_gpu_cb.isChecked()
        scale_factor = self.scale_combo.currentData()
        custom_colors = self._get_colors_from_parent()
        save_horizontal_valid = self.save_horizontal_valid_cb.isChecked()
        save_pre_align = self.save_pre_align_cb.isChecked()

        # Overlay flags
        draw_emojis = self.batch_show_emojis_cb.isChecked()
        draw_strand_names = self.batch_show_strand_names_cb.isChecked()
        draw_arrows = self.batch_show_arrows_cb.isChecked()

        # Build combination list
        combinations = []
        for m in range(m_min, m_max + 1):
            for n in range(n_min, n_max + 1):
                if auto_k:
                    k_lo, k_hi = self._compute_auto_k_range(m, n)
                else:
                    k_lo, k_hi = k_min_manual, k_max_manual
                for k in range(k_lo, k_hi + 1):
                    for direction in directions:
                        for hand in handedness:
                            combinations.append((m, n, k, direction, hand))

        total = len(combinations)
        self._log(f"Starting Full Auto: {total} combinations")
        k_desc = "Auto" if auto_k else f"{k_min_manual} to {k_max_manual}"
        self._log(f"  M: {m_min}-{m_max}, N: {n_min}-{n_max}, K: {k_desc}")
        self._log(f"  Directions: {directions}, Handedness: {handedness}")
        self._log(f"  Angle mode: {angle_mode}")
        self._log(f"  Pair ext max: {pair_ext_max}px, step: {pair_ext_step}px")
        self._log(f"  GPU: {'Yes' if use_gpu else 'No'}")
        self._log(f"  Save horizontal valid attempts: {'Yes' if save_horizontal_valid else 'No'}")
        self._log("")

        self.progress_bar.setMaximum(total)

        params = {
            'angle_mode': angle_mode,
            'pair_ext_max': pair_ext_max,
            'pair_ext_step': pair_ext_step,
            'use_gpu': use_gpu,
            'scale_factor': scale_factor,
            'custom_colors': custom_colors,
            'save_horizontal_valid': save_horizontal_valid,
            'save_pre_align': save_pre_align,
            'draw_emojis': draw_emojis,
            'draw_strand_names': draw_strand_names,
            'draw_arrows': draw_arrows,
            'transparent': (
                self.parent_dialog.transparent_checkbox.isChecked()
                if self.parent_dialog and hasattr(self.parent_dialog, "transparent_checkbox")
                else True
            ),
            'base_dir': os.path.dirname(os.path.abspath(__file__)),
            'emoji_renderer': self._emoji_renderer,
        }

        self._worker = BatchWorker(combinations, params, parent=self)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.log_message.connect(self._on_worker_log)
        self._worker.finished_batch.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_progress(self, idx, total, status_text):
        self.progress_bar.setValue(idx)
        self.summary_label.setText(status_text)

    def _on_worker_log(self, msg):
        self.log_text.append(msg)

    def _on_worker_finished(self, saved, skipped, errors, total):
        self.progress_bar.setValue(total)
        self.summary_label.setText(
            f"Complete: {saved} saved, {skipped} skipped, {errors} errors out of {total} total"
        )
        self._log(f"\n=== COMPLETE ===")
        self._log(f"Saved: {saved}, Skipped: {skipped}, Errors: {errors}, Total: {total}")
        self._finish()

    def _render_batch_overlays(self, canvas, bounds, base_image, scale_factor,
                               m, n, k, direction,
                               draw_emojis, draw_strand_names, draw_arrows):
        """Composite emoji / strand-name / arrow overlays onto *base_image*."""
        from openstrandstudio.src.render_utils import RenderUtils

        w = base_image.width()
        h = base_image.height()

        emoji_settings = {
            "show": draw_emojis,
            "show_strand_names": draw_strand_names,
            "show_rotation_indicator": draw_arrows,
            "k": k,
            "direction": direction,
            "transparent": True,
        }

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

        # Composite overlay onto base image
        painter = QPainter(base_image)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawImage(0, 0, overlay)
        painter.end()

        return base_image

    def _finish(self):
        self._running = False
        self._stop_requested = False
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def closeEvent(self, event):
        if self._running:
            self._stop_requested = True
            if self._worker:
                self._worker.request_stop()
                self._worker.wait(5000)
        if self._main_window:
            self._main_window.close()
            self._main_window = None
        super().closeEvent(event)
