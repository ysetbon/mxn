"""
MxN CAD Generator UI for OpenStrandStudio
Generates MxN strand patterns using mxn_lh.py/mxn_rh.py and displays exported images
"""

import os
import sys
import json
import copy
import math
import random
import colorsys
import hashlib
import warnings
import logging

# Suppress warnings and logging for cleaner output
logging.basicConfig(level=logging.CRITICAL)
logging.getLogger().setLevel(logging.CRITICAL)
logging.getLogger('LayerStateManager').disabled = True
os.environ['PYTHONWARNINGS'] = 'ignore'
warnings.filterwarnings('ignore')
os.environ["QT_LOGGING_RULES"] = "*=false"

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSpinBox, QRadioButton,
    QButtonGroup, QScrollArea, QWidget, QGroupBox,
    QComboBox, QCheckBox, QColorDialog, QMessageBox, QTextEdit, QProgressBar,
    QApplication, QSizePolicy, QFileDialog
)
from PyQt5.QtCore import Qt, pyqtSignal, QStandardPaths, QSize, QRectF, QPointF
from PyQt5.QtGui import QColor, QPixmap, QImage, QFont, QPainter, QPen, QBrush, QPainterPath

# Add local and sibling repo paths for imports.
script_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(script_dir)

openstrandstudio_parent = None
openstrandstudio_src = None
for candidate_root in (root_dir, os.path.dirname(root_dir)):
    candidate_src = os.path.join(candidate_root, "openstrandstudio", "src")
    if os.path.isdir(candidate_src):
        openstrandstudio_parent = candidate_root
        openstrandstudio_src = candidate_src
        break

for path in filter(None, (script_dir, root_dir, openstrandstudio_parent, openstrandstudio_src)):
    if path not in sys.path:
        sys.path.insert(0, path)

# Import generators
from mxn_lh import generate_json as generate_lh_json
from mxn_rh import generate_json as generate_rh_json
from mxn_lh_strech import generate_json as generate_lh_strech_json
from mxn_rh_stretch import generate_json as generate_rh_stretch_json
from mxn_lh_continuation import generate_json as generate_lh_continuation_json
from mxn_rh_continuation import generate_json as generate_rh_continuation_json
from mxn_lh_continuation import (
    align_horizontal_strands_parallel as align_horizontal_strands_parallel_lh,
    align_vertical_strands_parallel as align_vertical_strands_parallel_lh,
    apply_parallel_alignment as apply_parallel_alignment_lh,
    print_alignment_debug as print_alignment_debug_lh,
    get_parallel_alignment_preview as get_parallel_alignment_preview_lh,
    get_alignment_combo_guard,
)
from mxn_rh_continuation import (
    align_horizontal_strands_parallel as align_horizontal_strands_parallel_rh,
    align_vertical_strands_parallel as align_vertical_strands_parallel_rh,
    apply_parallel_alignment as apply_parallel_alignment_rh,
    print_alignment_debug as print_alignment_debug_rh,
    get_parallel_alignment_preview as get_parallel_alignment_preview_rh,
)

# Import emoji renderer (handles all emoji/label drawing logic)
from mxn_emoji_renderer import EmojiRenderer


EMOJI_SET_ITEMS = [
    ("Default (System)", "default"),
    ("Twemoji (Twitter)", "twemoji"),
    ("OpenMoji", "openmoji"),
    ("JoyPixels", "joypixels"),
    ("Fluent 3D (Microsoft)", "fluent"),
]


def _get_active_history_state(data):
    """Return the current-step history state dict, or None for plain documents."""
    if not isinstance(data, dict) or data.get("type") != "OpenStrandStudioHistory":
        return None

    current_step = data.get("current_step", 1)
    for state in data.get("states", []):
        if isinstance(state, dict) and state.get("step") == current_step:
            state_data = state.get("data")
            if isinstance(state_data, dict):
                return state
    return None


def _get_active_strands(data):
    """Return the strands list for the active history step or plain document."""
    state = _get_active_history_state(data)
    if state is not None:
        return state.get("data", {}).get("strands", [])
    return data.get("strands", []) if isinstance(data, dict) else []


def _set_active_strands(data, strands):
    """Write strands back only to the active history step or plain document."""
    state = _get_active_history_state(data)
    if state is not None:
        state.setdefault("data", {})["strands"] = strands
    elif isinstance(data, dict):
        data["strands"] = strands


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


class FullAutoDialog(QDialog):
    """Dialog for fully automated batch generation: continuation + parallel alignment."""

    def __init__(self, parent_dialog, parent=None):
        super().__init__(parent or parent_dialog)
        self.parent_dialog = parent_dialog
        self.theme = parent_dialog.theme if parent_dialog else 'dark'
        self._stop_requested = False
        self._running = False
        self._main_window = None
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

        self.save_all_valid_folders_cb = QCheckBox("Save extra output folders")
        self.save_all_valid_folders_cb.setChecked(True)
        self.save_all_valid_folders_cb.setToolTip(
            "When checked, fully valid results also save to valid_options and partial\n"
            "results save to partial_options. When unchecked, only best_solution is kept."
        )
        align_lay.addWidget(self.save_all_valid_folders_cb, 4, 0, 1, 2)

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
        self.batch_show_emojis_cb.setChecked(False)
        self.batch_show_emojis_cb.setToolTip("Draw animal emoji markers at strand endpoints")
        overlay_lay.addWidget(self.batch_show_emojis_cb)

        self.batch_show_strand_names_cb = QCheckBox("Show strand names")
        self.batch_show_strand_names_cb.setChecked(False)
        self.batch_show_strand_names_cb.setToolTip("Show strand names like '3_2(s)' at each endpoint")
        overlay_lay.addWidget(self.batch_show_strand_names_cb)

        self.batch_show_arrows_cb = QCheckBox("Show rotation arrow + numbers")
        self.batch_show_arrows_cb.setChecked(False)
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

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

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
        import tempfile
        from openstrandstudio.src.save_load_manager import load_strands, apply_loaded_strands

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

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump(current_data, tmp)
            temp_path = tmp.name

        try:
            strands, groups, _, _, _, _, _, shadow_overrides = load_strands(temp_path, canvas)
        finally:
            os.unlink(temp_path)

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
        save_extra_outputs = self.save_all_valid_folders_cb.isChecked()

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
        self._log("")

        self.progress_bar.setMaximum(total)

        saved = 0
        skipped = 0
        errors = 0
        base_dir = os.path.dirname(os.path.abspath(__file__))

        for idx, (m, n, k, direction, hand) in enumerate(combinations):
            if self._stop_requested:
                self._log(f"\nStopped by user after {idx}/{total}.")
                break

            self.progress_bar.setValue(idx)
            self.summary_label.setText(
                f"Processing {idx + 1}/{total}: {hand.upper()} {m}x{n} k={k} {direction.upper()} | "
                f"Saved: {saved}, Skipped: {skipped}, Errors: {errors}"
            )
            QApplication.processEvents()

            try:
                self._log(f"[{idx + 1}/{total}] {hand.upper()} {m}x{n} k={k} {direction.upper()}")

                # --- Step 1: Generate continuation JSON ---
                if hand == "lh":
                    cont_json = generate_lh_continuation_json(m, n, k, direction)
                else:
                    cont_json = generate_rh_continuation_json(m, n, k, direction)

                cont_json = self._apply_colors_to_json(cont_json, custom_colors)

                # Save pre-alignment continuation
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

                # --- Step 4: Horizontal alignment ---
                h_result = align_h_fn(
                    strands, n,
                    angle_step_degrees=0.5,
                    max_extension=100.0,
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
                    self._log(f"  H: FAILED - {h_result.get('message', '')}")

                # --- Step 5: Vertical alignment ---
                v_result = align_v_fn(
                    strands, n, m,
                    angle_step_degrees=0.5,
                    max_extension=100.0,
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
                    self._log(f"  V: FAILED - {v_result.get('message', '')}")

                # --- Step 6: Update strands in data ---
                _set_active_strands(data, strands)

                aligned_json = json.dumps(data, indent=2)

                # --- Step 7: Save outputs ---
                is_valid = h_success and v_success
                diagram_name = f"{m}x{n}"
                base_output_dir = os.path.join(
                    base_dir, "mxn", "mxn_output", diagram_name,
                    f"k_{k}_{direction}_{hand}"
                )

                h_tag = f"h{h_result.get('angle_degrees', 0):.1f}" if h_success else "h_fail"
                v_tag = f"v{v_result.get('angle_degrees', 0):.1f}" if v_success else "v_fail"
                fname = f"mxn_{hand}_{m}x{n}_k{k}_{direction}_{h_tag}_{v_tag}"

                # Decide which folders to save into
                save_dirs = []
                if is_valid:
                    save_dirs.append(os.path.join(base_output_dir, "best_solution"))
                    if save_extra_outputs:
                        save_dirs.append(os.path.join(base_output_dir, "valid_options"))
                else:
                    if save_extra_outputs:
                        save_dirs.append(os.path.join(base_output_dir, "partial_options"))

                if not save_dirs:
                    self._log("  -> skipped (partial result, extra output folders disabled)")
                    skipped += 1
                    continue

                # Render the image once
                bounds = self._load_json_to_canvas(aligned_json)
                image = None
                if bounds:
                    image = self._render_image(bounds, scale_factor)
                    # Render emoji / text overlay if requested
                    if image and not image.isNull() and (draw_emojis or draw_strand_names or draw_arrows):
                        main_window = self._get_main_window()
                        if main_window:
                            image = self._render_batch_overlays(
                                main_window.canvas, bounds, image, scale_factor,
                                m, n, k, direction,
                                draw_emojis, draw_strand_names, draw_arrows,
                            )

                # Save to each target folder
                for output_dir in save_dirs:
                    os.makedirs(output_dir, exist_ok=True)
                    with open(os.path.join(output_dir, f"{fname}.json"), 'w', encoding='utf-8') as f:
                        f.write(aligned_json)
                    if image and not image.isNull():
                        image.save(os.path.join(output_dir, f"{fname}.png"))

                result_str = "VALID" if is_valid else "partial"
                folders_str = " + ".join(os.path.basename(d) for d in save_dirs)
                self._log(f"  -> {result_str} | saved to .../{diagram_name}/k_{k}_{direction}_{hand}/ [{folders_str}]")
                saved += 1

            except Exception as e:
                import traceback
                traceback.print_exc()
                self._log(f"  ERROR: {e}")
                errors += 1

        processed = total if not self._stop_requested else (idx + 1 if combinations else 0)
        self.progress_bar.setValue(processed)
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
        if self._main_window:
            self._main_window.close()
            self._main_window = None
        super().closeEvent(event)


class MxNGeneratorDialog(QDialog):
    """Dialog for generating MxN strand patterns with live image preview."""

    pattern_generated = pyqtSignal(str)  # Emits JSON path when generated
    BOUNDS_PADDING = 100

    def __init__(self, parent=None):
        super().__init__(parent)

        # Remove Windows context help button
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # Get theme from parent (default to dark for standalone)
        self.theme = self._get_theme()

        # State variables
        self.m_value = 2  # Default M (vertical strands)
        self.n_value = 2  # Default N (horizontal strands)
        self.colors = {}  # {set_number: QColor}
        self.color_buttons = {}  # {set_number: QPushButton}
        self.hex_labels = {}  # {set_number: QLabel}

        # In-memory storage for generated content
        self.current_json_data = None  # JSON string in memory
        self.current_image = None  # QImage in memory
        self._continuation_json_data = None  # Original continuation data (before any extension)
        self._suppress_auto_save = False  # Block auto-save during programmatic resets

        # Emoji renderer (handles all endpoint emoji drawing logic)
        self._emoji_renderer = EmojiRenderer()

        # Base directory for output
        self.base_dir = os.path.dirname(os.path.abspath(__file__))

        # MainWindow instance for export (created lazily)
        self._main_window = None

        # Cache: keep a prepared canvas/bounds for fast re-renders
        # (toggling background / emoji settings should NOT reload strands)
        self._prepared_canvas_key = None
        self._prepared_bounds = None

        # Strand layer cache: avoids re-drawing all strands when only emoji settings change
        self._cached_strand_layer = None       # QImage with strands on transparent bg
        self._cached_strand_layer_key = None   # (canvas_key, scale_factor)

        # Setup UI
        self.setup_ui()
        self._apply_theme()

        # Load saved settings
        self.load_color_settings()

        # Initialize color pickers for default M x N
        self.update_color_pickers()

    def _get_theme(self):
        """Get current theme from parent window hierarchy."""
        main_window = self.parent()
        while main_window and not hasattr(main_window, 'current_theme'):
            main_window = main_window.parent() if hasattr(main_window, 'parent') else None
        return main_window.current_theme if main_window else 'dark'

    def _get_main_window(self):
        """Get or create a MainWindow instance for export."""
        if self._main_window is None:
            app = QApplication.instance()
            original_app_stylesheet = app.styleSheet() if app else ""
            try:
                from openstrandstudio.src.main_window import MainWindow
                self._main_window = MainWindow()
                self._main_window.hide()
                self._main_window.canvas.hide()
            except Exception as e:
                print(f"Failed to create MainWindow: {e}")
                return None
            finally:
                # MainWindow applies a global QApplication stylesheet in __init__.
                # Restore the pre-existing app style so this dialog keeps its theme.
                if app is not None:
                    app.setStyleSheet(original_app_stylesheet)
                self._apply_theme()
                self._update_preview_background_style()
        return self._main_window

    def _get_gpu_runtime_status(self):
        """Return whether CUDA/CuPy is ready and the active NVIDIA device name."""
        try:
            from mxn_lh_continuation import _check_cupy_available
            if not _check_cupy_available():
                return False, None, "CPU only: CuPy/CUDA unavailable"

            import cupy as cp

            device_name = "NVIDIA GPU"
            try:
                props = cp.cuda.runtime.getDeviceProperties(0)
                if isinstance(props, dict):
                    device_name = props.get("name", device_name)
                else:
                    device_name = getattr(props, "name", device_name)
                if isinstance(device_name, bytes):
                    device_name = device_name.decode("utf-8", errors="ignore")
                device_name = str(device_name).strip() or "NVIDIA GPU"
            except Exception:
                pass

            return True, device_name, f"GPU ready: {device_name}"
        except Exception:
            return False, None, "CPU only: CuPy/CUDA unavailable"

    def _get_alignment_backend_label(self, use_gpu=None):
        """Describe the compute backend that alignment will use."""
        if use_gpu is None:
            use_gpu = self.use_gpu_cb.isChecked() if hasattr(self, 'use_gpu_cb') else False

        gpu_available, device_name, _ = self._get_gpu_runtime_status()
        if use_gpu and gpu_available:
            return f"GPU: {device_name}"
        if use_gpu:
            return "CPU fallback"
        if gpu_available:
            return f"CPU (GPU ready: {device_name})"
        return "CPU"

    def _update_gpu_status_ui(self):
        """Refresh the GPU checkbox and status text."""
        if not hasattr(self, 'use_gpu_cb') or not hasattr(self, 'gpu_status_label'):
            return

        gpu_available, device_name, status_text = self._get_gpu_runtime_status()

        if gpu_available:
            self.use_gpu_cb.setEnabled(True)
            self.use_gpu_cb.setToolTip(f"Use NVIDIA GPU for faster alignment search ({device_name})")
            if self.use_gpu_cb.isChecked():
                self.gpu_status_label.setText(f"Alignment device: GPU selected ({device_name})")
            else:
                self.gpu_status_label.setText(f"Alignment device: CPU selected | GPU ready: {device_name}")
        else:
            self.use_gpu_cb.setChecked(False)
            self.use_gpu_cb.setEnabled(False)
            self.use_gpu_cb.setToolTip("CuPy not installed or no CUDA GPU found. Install with: pip install cupy-cuda12x")
            self.gpu_status_label.setText(f"Alignment device: {status_text}")

    def _on_gpu_toggle_changed(self, checked):
        """Update backend summary when the GPU checkbox changes."""
        self._update_gpu_status_ui()
        self._update_calc_count_label()

    def setup_ui(self):
        """Setup the main UI layout with image preview."""
        self.setWindowTitle('MxN Pattern Generator')
        self.setMinimumSize(900, 700)
        self.resize(1100, 800)

        main_layout = QHBoxLayout(self)
        # Tighter outer padding
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # Left panel - Controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        # Tighter inner padding + spacing between groups
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(6)
        # Don't hard-fix the width; DPI/font scaling can otherwise crop content.
        # Use a scroll area wrapper so the control panel is always fully accessible.
        # Keep this compact so the preview isn't starved for space
        left_panel.setMinimumWidth(420)

        # === Grid Size Section ===
        self._setup_grid_size_section(left_layout)

        # === Variant Selection Section ===
        self._setup_variant_section(left_layout)

        # === Colors Section (Scrollable) ===
        self._setup_colors_section(left_layout)

        # === Export Options Section ===
        self._setup_export_section(left_layout)

        # === Endpoint Emojis Section ===
        self._setup_endpoint_emojis_section(left_layout)

        # === Action Buttons ===
        self._setup_action_buttons(left_layout)

        # Don't force extra empty space at the bottom; the scroll area can handle overflow.

        # Right panel - Image Preview
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(5)

        preview_label = QLabel("Preview")
        preview_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        right_layout.addWidget(preview_label)

        self.preview_widget = ImagePreviewWidget()
        right_layout.addWidget(self.preview_widget)

        # Ensure preview panel background matches transparency setting
        self._update_preview_background_style()

        # Add panels to main layout
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        # If the window is narrow / DPI scaling is high, allow horizontal scrolling
        # rather than clipping labels and controls.
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setWidget(left_panel)
        left_scroll.setMinimumWidth(440)
        main_layout.addWidget(left_scroll)
        main_layout.addWidget(right_panel, 1)  # Give preview more space

    def _setup_grid_size_section(self, parent_layout):
        """Create grid size M x N spinboxes."""
        group = QGroupBox("Grid Size")
        # Stack into 2 rows so it doesn't clip on smaller widths.
        layout = QGridLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        # M spinner (vertical strands)
        m_label = QLabel("M (Vertical):")
        self.m_spinner = QSpinBox()
        self.m_spinner.setRange(1, 10)
        self.m_spinner.setValue(self.m_value)
        self.m_spinner.setMinimumWidth(60)
        self.m_spinner.valueChanged.connect(self._on_grid_size_changed)

        # N spinner (horizontal strands)
        n_label = QLabel("N (Horiz):")
        self.n_spinner = QSpinBox()
        self.n_spinner.setRange(1, 10)
        self.n_spinner.setValue(self.n_value)
        self.n_spinner.setMinimumWidth(60)
        self.n_spinner.valueChanged.connect(self._on_grid_size_changed)

        layout.addWidget(m_label, 0, 0)
        layout.addWidget(self.m_spinner, 0, 1)
        layout.addWidget(n_label, 1, 0)
        layout.addWidget(self.n_spinner, 1, 1)
        layout.setColumnStretch(2, 1)

        parent_layout.addWidget(group)

    def _setup_variant_section(self, parent_layout):
        """Create LH/RH variant radio buttons."""
        group = QGroupBox("Variant")
        # Use VBoxLayout for simpler vertical stacking without clipping
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.variant_group = QButtonGroup(self)

        self.lh_radio = QRadioButton("Left-Hand (LH)")
        self.rh_radio = QRadioButton("Right-Hand (RH)")
        self.stretch_checkbox = QCheckBox("Stretch")
        # Stretch doesn't change set count, but clearing preview/status is still desired
        self.stretch_checkbox.stateChanged.connect(self._on_grid_size_changed)

        self.variant_group.addButton(self.lh_radio, 0)
        self.variant_group.addButton(self.rh_radio, 1)

        # Update continuation button when variant changes (RH not supported yet)
        self.lh_radio.toggled.connect(self._on_variant_changed)
        self.rh_radio.toggled.connect(self._on_variant_changed)

        self.lh_radio.setChecked(True)  # Default to LH

        layout.addWidget(self.lh_radio)
        layout.addWidget(self.rh_radio)
        layout.addWidget(self.stretch_checkbox)

        parent_layout.addWidget(group)

    def _setup_colors_section(self, parent_layout):
        """Create scrollable color picker area."""
        group = QGroupBox("Set Colors")
        group_layout = QVBoxLayout(group)

        # Info label
        self.colors_info_label = QLabel()
        self.colors_info_label.setWordWrap(True)
        group_layout.addWidget(self.colors_info_label)

        # Scrollable area for color pickers
        self.colors_scroll = QScrollArea()
        self.colors_scroll.setWidgetResizable(True)
        self.colors_scroll.setMinimumHeight(150)
        self.colors_scroll.setMaximumHeight(250)

        self.colors_container = QWidget()
        self.colors_layout = QGridLayout(self.colors_container)
        self.colors_layout.setSpacing(6)
        self.colors_layout.setContentsMargins(5, 5, 5, 5)

        self.colors_scroll.setWidget(self.colors_container)
        group_layout.addWidget(self.colors_scroll)

        # Color action buttons
        color_buttons_layout = QHBoxLayout()

        self.reset_colors_btn = QPushButton("Reset")
        self.reset_colors_btn.clicked.connect(self.reset_colors)

        self.random_colors_btn = QPushButton("Random")
        self.random_colors_btn.clicked.connect(self.generate_random_colors)

        color_buttons_layout.addWidget(self.reset_colors_btn)
        color_buttons_layout.addWidget(self.random_colors_btn)
        color_buttons_layout.addStretch()

        group_layout.addLayout(color_buttons_layout)
        parent_layout.addWidget(group)

    def _setup_export_section(self, parent_layout):
        """Create image export options."""
        group = QGroupBox("Image Export")
        layout = QVBoxLayout(group)

        row1 = QHBoxLayout()
        # Scale factor dropdown
        scale_label = QLabel("Scale:")
        self.scale_combo = QComboBox()
        self.scale_combo.addItem("1x", 1.0)
        self.scale_combo.addItem("2x", 2.0)
        self.scale_combo.addItem("4x", 4.0)
        self.scale_combo.setCurrentIndex(2)  # Default to 4x
        self.scale_combo.setMinimumWidth(80)

        row1.addWidget(scale_label)
        row1.addWidget(self.scale_combo)
        row1.addStretch()

        layout.addLayout(row1)

        # Transparent background checkbox
        self.transparent_checkbox = QCheckBox("Transparent Background")
        self.transparent_checkbox.setChecked(True)
        self.transparent_checkbox.stateChanged.connect(self._on_background_settings_changed)
        layout.addWidget(self.transparent_checkbox)

        parent_layout.addWidget(group)

    def _setup_endpoint_emojis_section(self, parent_layout):
        """Create endpoint emoji marker options (rotate labels around perimeter)."""
        group = QGroupBox("Endpoint Emojis")
        layout = QGridLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        self.show_emojis_checkbox = QCheckBox("Show animal markers")
        self.show_emojis_checkbox.setChecked(True)
        self.show_emojis_checkbox.stateChanged.connect(self._on_emoji_settings_changed)

        # Checkbox to show strand names (e.g., "3_2(s)", "1_3(e)") at emoji positions
        self.show_strand_names_checkbox = QCheckBox("Show strand names")
        self.show_strand_names_checkbox.setChecked(False)
        self.show_strand_names_checkbox.setToolTip("Show strand names like '3_2(s)' at each endpoint\n(s)=start, (e)=end")
        self.show_strand_names_checkbox.stateChanged.connect(self._on_emoji_settings_changed)

        k_label = QLabel("Rotation k:")
        self.emoji_k_spinner = QSpinBox()
        self.emoji_k_spinner.setRange(-9999, 9999)
        self.emoji_k_spinner.setValue(0)
        self.emoji_k_spinner.valueChanged.connect(self._on_emoji_settings_changed)

        self.emoji_dir_group = QButtonGroup(self)
        self.emoji_cw_radio = QRadioButton("CW")
        self.emoji_ccw_radio = QRadioButton("CCW")
        self.emoji_dir_group.addButton(self.emoji_cw_radio, 0)
        self.emoji_dir_group.addButton(self.emoji_ccw_radio, 1)
        self.emoji_cw_radio.setChecked(True)
        self.emoji_cw_radio.toggled.connect(self._on_emoji_settings_changed)
        self.emoji_ccw_radio.toggled.connect(self._on_emoji_settings_changed)

        self.refresh_emojis_btn = QPushButton("Refresh emoji painting")
        self.refresh_emojis_btn.setToolTip("Clear emoji render cache to remove colored halos/strokes")
        self.refresh_emojis_btn.clicked.connect(self._on_refresh_emojis_clicked)

        # Emoji set selector
        emoji_set_label = QLabel("Emoji style:")
        self.emoji_set_combo = QComboBox()
        for label, value in EMOJI_SET_ITEMS:
            self.emoji_set_combo.addItem(label, value)
        self.emoji_set_combo.currentIndexChanged.connect(self._on_emoji_set_changed)

        layout.addWidget(self.show_emojis_checkbox, 0, 0, 1, 3)
        layout.addWidget(self.show_strand_names_checkbox, 1, 0, 1, 3)
        layout.addWidget(emoji_set_label, 2, 0)
        layout.addWidget(self.emoji_set_combo, 2, 1, 1, 2)
        layout.addWidget(k_label, 3, 0)
        layout.addWidget(self.emoji_k_spinner, 3, 1)
        layout.addWidget(self.emoji_cw_radio, 3, 2)
        layout.addWidget(self.emoji_ccw_radio, 4, 2)
        layout.addWidget(self.refresh_emojis_btn, 5, 0, 1, 3)

        parent_layout.addWidget(group)

    def _setup_action_buttons(self, parent_layout):
        """Create main action buttons."""
        # Generate button (prominent)
        self.generate_btn = QPushButton("Generate && Preview")
        self.generate_btn.setMinimumHeight(40)
        self.generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #2e7d32;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #388e3c;
            }
            QPushButton:pressed {
                background-color: #1b5e20;
            }
        """)
        self.generate_btn.clicked.connect(self.generate_and_preview)
        parent_layout.addWidget(self.generate_btn)

        # Export buttons row
        export_layout = QHBoxLayout()

        # Export JSON button
        self.export_json_btn = QPushButton("Export JSON")
        self.export_json_btn.setMinimumHeight(35)
        self.export_json_btn.setEnabled(False)  # Disabled until generation
        self.export_json_btn.setStyleSheet("""
            QPushButton {
                background-color: #1565c0;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        self.export_json_btn.clicked.connect(self.export_json)
        export_layout.addWidget(self.export_json_btn)

        # Export Image button
        self.export_image_btn = QPushButton("Export Image")
        self.export_image_btn.setMinimumHeight(35)
        self.export_image_btn.setEnabled(False)  # Disabled until generation
        self.export_image_btn.setStyleSheet("""
            QPushButton {
                background-color: #7b1fa2;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #8e24aa;
            }
            QPushButton:pressed {
                background-color: #6a1b9a;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        self.export_image_btn.clicked.connect(self.export_image)
        export_layout.addWidget(self.export_image_btn)

        parent_layout.addLayout(export_layout)

        # Continuation button (only enabled when stretch + emojis are on)
        self.continuation_btn = QPushButton("Generate Continuation (+4, +5)")
        self.continuation_btn.setMinimumHeight(35)
        self.continuation_btn.setEnabled(False)  # Disabled until base pattern generated
        self.continuation_btn.setToolTip("Generate continuation strands based on current emoji pairing (requires Stretch mode + Emojis)")
        self.continuation_btn.setStyleSheet("""
            QPushButton {
                background-color: #e65100;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #ef6c00;
            }
            QPushButton:pressed {
                background-color: #d84315;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        self.continuation_btn.clicked.connect(self.generate_continuation)
        parent_layout.addWidget(self.continuation_btn)

        # Angle Range Preview and Controls
        angle_group = QGroupBox("Angle Range Settings")
        angle_group.setStyleSheet("QGroupBox { font-weight: bold; color: #aaa; }")
        angle_layout = QVBoxLayout(angle_group)
        angle_layout.setSpacing(5)

        # Preview button
        self.preview_angles_btn = QPushButton("Preview Angle Ranges")
        self.preview_angles_btn.setMinimumHeight(30)
        self.preview_angles_btn.setEnabled(False)
        self.preview_angles_btn.setToolTip("Show dotted lines for angle search ranges")
        self.preview_angles_btn.setStyleSheet("""
            QPushButton {
                background-color: #5c5c5c;
                color: white;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #6c6c6c;
            }
            QPushButton:disabled {
                background-color: #444;
                color: #888;
            }
        """)
        self.preview_angles_btn.clicked.connect(self.preview_angle_ranges)
        angle_layout.addWidget(self.preview_angles_btn)

        # Show H/V set toggles
        hv_set_layout = QHBoxLayout()
        self.show_h_set_cb = QCheckBox("Show H set")
        self.show_h_set_cb.setToolTip("Show horizontal strand set names on preview")
        self.show_h_set_cb.stateChanged.connect(self._on_hv_set_toggle)
        hv_set_layout.addWidget(self.show_h_set_cb)
        self.show_v_set_cb = QCheckBox("Show V set")
        self.show_v_set_cb.setToolTip("Show vertical strand set names on preview")
        self.show_v_set_cb.stateChanged.connect(self._on_hv_set_toggle)
        hv_set_layout.addWidget(self.show_v_set_cb)
        angle_layout.addLayout(hv_set_layout)

        # Horizontal angle range
        h_angle_layout = QHBoxLayout()
        h_angle_layout.addWidget(QLabel("H:"))
        self.h_angle_min_spin = QSpinBox()
        self.h_angle_min_spin.setRange(-360, 360)
        self.h_angle_min_spin.setValue(0)
        self.h_angle_min_spin.setSuffix("°")
        self.h_angle_min_spin.setToolTip("Horizontal min angle")
        h_angle_layout.addWidget(self.h_angle_min_spin)
        h_angle_layout.addWidget(QLabel("to"))
        self.h_angle_max_spin = QSpinBox()
        self.h_angle_max_spin.setRange(-360, 360)
        self.h_angle_max_spin.setValue(40)
        self.h_angle_max_spin.setSuffix("°")
        self.h_angle_max_spin.setToolTip("Horizontal max angle")
        h_angle_layout.addWidget(self.h_angle_max_spin)
        angle_layout.addLayout(h_angle_layout)

        # Vertical angle range
        v_angle_layout = QHBoxLayout()
        v_angle_layout.addWidget(QLabel("V:"))
        self.v_angle_min_spin = QSpinBox()
        self.v_angle_min_spin.setRange(-360, 360)
        self.v_angle_min_spin.setValue(-90)
        self.v_angle_min_spin.setSuffix("°")
        self.v_angle_min_spin.setToolTip("Vertical min angle")
        v_angle_layout.addWidget(self.v_angle_min_spin)
        v_angle_layout.addWidget(QLabel("to"))
        self.v_angle_max_spin = QSpinBox()
        self.v_angle_max_spin.setRange(-360, 360)
        self.v_angle_max_spin.setValue(-50)
        self.v_angle_max_spin.setSuffix("°")
        self.v_angle_max_spin.setToolTip("Vertical max angle")
        v_angle_layout.addWidget(self.v_angle_max_spin)
        angle_layout.addLayout(v_angle_layout)

        # Angle calculation mode
        angle_mode_layout = QHBoxLayout()
        angle_mode_layout.addWidget(QLabel("Mode:"))
        self.angle_mode_combo = QComboBox()
        self.angle_mode_combo.addItem("First strand ±20°", "first_strand")
        self.angle_mode_combo.addItem("Average ↔ Gaussian bounds", "avg_gaussian")
        self.angle_mode_combo.setToolTip(
            "First strand: original method (first strand angle ±20°)\n"
            "Average ↔ Gaussian: use the uniform average angle and Gaussian-weighted\n"
            "average angle as the two ends of the search range"
        )
        self.angle_mode_combo.currentIndexChanged.connect(self._on_angle_mode_changed)
        angle_mode_layout.addWidget(self.angle_mode_combo)
        angle_layout.addLayout(angle_mode_layout)

        # Use custom angles checkbox
        self.use_custom_angles_cb = QCheckBox("Use custom angle ranges")
        self.use_custom_angles_cb.setToolTip("If checked, use the angles above instead of auto-detected values")
        angle_layout.addWidget(self.use_custom_angles_cb)

        # Pair extension search controls (outer loop parameters)
        ext_search_label = QLabel("Pair Extension Search:")
        ext_search_label.setStyleSheet("color: #aaa; font-size: 11px; margin-top: 5px;")
        angle_layout.addWidget(ext_search_label)

        ext_search_layout = QHBoxLayout()
        ext_search_layout.addWidget(QLabel("Max:"))
        self.pair_ext_max_spin = QSpinBox()
        self.pair_ext_max_spin.setRange(0, 1000)
        self.pair_ext_max_spin.setValue(200)
        self.pair_ext_max_spin.setSingleStep(50)
        self.pair_ext_max_spin.setSuffix("px")
        self.pair_ext_max_spin.setToolTip("Maximum pair extension to search (outer loop upper bound)")
        ext_search_layout.addWidget(self.pair_ext_max_spin)

        ext_search_layout.addWidget(QLabel("Step:"))
        self.pair_ext_step_spin = QSpinBox()
        self.pair_ext_step_spin.setRange(1, 100)
        self.pair_ext_step_spin.setValue(10)
        self.pair_ext_step_spin.setSingleStep(1)
        self.pair_ext_step_spin.setSuffix("px")
        self.pair_ext_step_spin.setToolTip("Pair extension step size (outer loop increment)")
        ext_search_layout.addWidget(self.pair_ext_step_spin)
        angle_layout.addLayout(ext_search_layout)

        # Auto-save preset when any alignment parameter changes
        self.h_angle_min_spin.valueChanged.connect(self._auto_save_alignment_preset)
        self.h_angle_max_spin.valueChanged.connect(self._auto_save_alignment_preset)
        self.v_angle_min_spin.valueChanged.connect(self._auto_save_alignment_preset)
        self.v_angle_max_spin.valueChanged.connect(self._auto_save_alignment_preset)
        self.use_custom_angles_cb.stateChanged.connect(self._auto_save_alignment_preset)
        self.pair_ext_max_spin.valueChanged.connect(self._auto_save_alignment_preset)
        self.pair_ext_step_spin.valueChanged.connect(self._auto_save_alignment_preset)
        self.pair_ext_max_spin.valueChanged.connect(self._update_calc_count_label)
        self.pair_ext_step_spin.valueChanged.connect(self._update_calc_count_label)

        # Pair extension offset controls (direct extension, no alignment)
        ext_offset_label = QLabel("Opposite Pair Extensions:")
        ext_offset_label.setStyleSheet("color: #aaa; font-size: 11px; margin-top: 5px;")
        angle_layout.addWidget(ext_offset_label)

        self.pair_ext_hint = QLabel("Values are per opposite pair from current k/direction order.")
        self.pair_ext_hint.setStyleSheet("color: #888; font-size: 10px;")
        angle_layout.addWidget(self.pair_ext_hint)

        # Horizontal opposite pairs (_2/_3 names)
        self.h_pair_group = QGroupBox("H Opposite Pairs")
        self.h_pair_group.setStyleSheet("QGroupBox { color: #aaa; font-weight: bold; }")
        self.h_pair_group_layout = QVBoxLayout(self.h_pair_group)
        self.h_pair_group_layout.setContentsMargins(6, 6, 6, 6)
        self.h_pair_group_layout.setSpacing(4)
        angle_layout.addWidget(self.h_pair_group)

        # Vertical opposite pairs (_2/_3 names)
        self.v_pair_group = QGroupBox("V Opposite Pairs")
        self.v_pair_group.setStyleSheet("QGroupBox { color: #aaa; font-weight: bold; }")
        self.v_pair_group_layout = QVBoxLayout(self.v_pair_group)
        self.v_pair_group_layout.setContentsMargins(6, 6, 6, 6)
        self.v_pair_group_layout.setSpacing(4)
        angle_layout.addWidget(self.v_pair_group)

        # Dynamic pair controls: {(left_label, right_label): QSpinBox}
        self.h_pair_ext_spins = {}
        self.v_pair_ext_spins = {}
        self._refresh_pair_extension_controls(preserve_values=False)

        # Connect spinboxes to update preview when values change
        self.h_angle_min_spin.valueChanged.connect(self._on_angle_spin_changed)
        self.h_angle_max_spin.valueChanged.connect(self._on_angle_spin_changed)
        self.v_angle_min_spin.valueChanged.connect(self._on_angle_spin_changed)
        self.v_angle_max_spin.valueChanged.connect(self._on_angle_spin_changed)

        parent_layout.addWidget(angle_group)

        # Store preview state
        self._angle_preview_active = False
        self._angle_preview_data = None

        # Status label
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #888; font-size: 11px;")
        parent_layout.addWidget(self.status_label)

        # Calculation count label (shows estimated work before pressing align)
        self.calc_count_label = QLabel("")
        self.calc_count_label.setWordWrap(True)
        self.calc_count_label.setStyleSheet("color: #ffab40; font-size: 11px; margin-top: 3px;")
        parent_layout.addWidget(self.calc_count_label)

        # GPU toggle checkbox
        self.use_gpu_cb = QCheckBox("Use GPU (CuPy)")
        self.use_gpu_cb.setChecked(False)
        self.use_gpu_cb.setStyleSheet("color: #4fc3f7; font-size: 11px;")
        self.use_gpu_cb.toggled.connect(self._on_gpu_toggle_changed)
        parent_layout.addWidget(self.use_gpu_cb)

        self.gpu_status_label = QLabel("")
        self.gpu_status_label.setWordWrap(True)
        self.gpu_status_label.setStyleSheet("color: #7dd3fc; font-size: 11px; margin-top: 2px;")
        parent_layout.addWidget(self.gpu_status_label)
        self._update_gpu_status_ui()

        self.save_horizontal_valid_cb = QCheckBox("Save horizontal valid images/txt/json")
        self.save_horizontal_valid_cb.setChecked(True)
        self.save_horizontal_valid_cb.setToolTip(
            "When enabled, valid horizontal alignment attempts are exported to the attempt_options folder"
        )
        self.save_horizontal_valid_cb.setStyleSheet("color: #c5e1a5; font-size: 11px;")
        self.save_horizontal_valid_cb.stateChanged.connect(self._auto_save_alignment_preset)
        parent_layout.addWidget(self.save_horizontal_valid_cb)

        # Align Parallel button (only enabled after continuation is generated)
        self.align_parallel_btn = QPushButton("Align Parallel (_4/_5)")
        self.align_parallel_btn.setMinimumHeight(35)
        self.align_parallel_btn.setEnabled(False)  # Disabled until continuation generated
        self.align_parallel_btn.setToolTip("Make horizontal _4/_5 strands parallel with equal spacing")
        self.align_parallel_btn.setStyleSheet("""
            QPushButton {
                background-color: #00838f;
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #0097a7;
            }
            QPushButton:pressed {
                background-color: #006064;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        self.align_parallel_btn.clicked.connect(self.align_parallel_strands)
        parent_layout.addWidget(self.align_parallel_btn)

        # Full Auto Batch button
        self.full_auto_btn = QPushButton("Full Auto Batch")
        self.full_auto_btn.setMinimumHeight(40)
        self.full_auto_btn.setToolTip(
            "Open automated batch generation: continuation + alignment\n"
            "for multiple M/N, K, direction, and handedness combinations"
        )
        self.full_auto_btn.setStyleSheet("""
            QPushButton {
                background-color: #6a1b9a;
                color: white;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #7b1fa2; }
            QPushButton:pressed { background-color: #4a148c; }
        """)
        self.full_auto_btn.clicked.connect(self._open_full_auto)
        parent_layout.addWidget(self.full_auto_btn)

    def _on_grid_size_changed(self):
        """Handle grid size change."""
        self.update_color_pickers()
        self.preview_widget.clear()
        self.status_label.setText("")
        # Clear in-memory data and disable export buttons
        self.current_json_data = None
        self.current_image = None
        self._continuation_json_data = None  # Clear stored continuation
        # Invalidate prepared-canvas cache and strand layer cache
        self._prepared_canvas_key = None
        self._prepared_bounds = None
        self._cached_strand_layer = None
        self._cached_strand_layer_key = None
        self._emoji_renderer.clear_cache()
        self.export_json_btn.setEnabled(False)
        self.export_image_btn.setEnabled(False)
        self.continuation_btn.setEnabled(False)
        self.align_parallel_btn.setEnabled(False)
        if hasattr(self, 'preview_angles_btn'):
            self.preview_angles_btn.setEnabled(False)
        self._refresh_pair_extension_controls(preserve_values=False)

    def _on_emoji_set_changed(self):
        """Switch emoji asset set and re-render."""
        set_name = self.emoji_set_combo.currentData()
        if set_name and getattr(self, "_emoji_renderer", None) is not None:
            self._emoji_renderer.set_emoji_set(set_name)
        self._rerender_preview_if_possible()

    def _on_emoji_settings_changed(self):
        """Re-render preview when emoji options change (no geometry changes)."""
        # Emoji toggles should update preview immediately
        self._rerender_preview_if_possible()
        # Update continuation button state (depends on emoji checkbox)
        self._update_continuation_button_state()
        # Keep pair controls synchronized with k/direction.
        self._refresh_pair_extension_controls(preserve_values=True)

    def _on_refresh_emojis_clicked(self):
        """Force-refresh emoji rendering (clears cached emoji glyph images)."""
        if getattr(self, "_emoji_renderer", None) is not None:
            if hasattr(self._emoji_renderer, "clear_render_cache"):
                self._emoji_renderer.clear_render_cache()
            else:
                self._emoji_renderer.clear_cache()
        self._rerender_preview_if_possible()

    def _on_variant_changed(self):
        """Handle LH/RH variant change - update continuation button state."""
        self._update_continuation_button_state()
        self._refresh_pair_extension_controls(preserve_values=False)

    def _on_background_settings_changed(self):
        """Re-render preview and update panel background when transparency changes."""
        self._update_preview_background_style()
        self._rerender_preview_if_possible()

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

    def _update_preview_background_style(self):
        """
        Keep preview background consistent with the app theme.

        In dark theme we keep a dark preview panel at all times to avoid a
        bright frame around centered generated images.
        """
        if not hasattr(self, "preview_widget") or self.preview_widget is None:
            return

        if self.theme == 'dark':
            bg = "#1a1a1a"
            border = "#555"
        else:
            bg = "#ffffff"
            border = "#cccccc"

        self.preview_widget.setStyleSheet(f"background-color: {bg}; border: 1px solid {border};")

    def update_color_pickers(self):
        """Dynamically update color pickers when M or N changes."""
        m = self.m_spinner.value()
        n = self.n_spinner.value()
        total_sets = m + n

        # Update info label
        self.colors_info_label.setText(
            f"Total {total_sets} sets: H(1-{n}), V({n + 1}-{n + m})"
        )

        # Clear existing widgets from layout
        while self.colors_layout.count():
            item = self.colors_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.color_buttons.clear()
        self.hex_labels.clear()

        # Create color pickers for each set
        row = 0

        # Horizontal sets (1 to n)
        for i in range(1, n + 1):
            self._add_color_picker_row(row, i, f"H{i}", is_horizontal=True)
            row += 1

        # Vertical sets (n+1 to n+m)
        for i in range(n + 1, n + m + 1):
            self._add_color_picker_row(row, i, f"V{i - n}", is_horizontal=False)
            row += 1

    def _add_color_picker_row(self, row, set_num, label_text, is_horizontal):
        """Add a single color picker row to the grid."""
        # Color button
        color_btn = QPushButton()
        color_btn.setFixedSize(32, 32)

        # Get existing color or generate default
        if set_num not in self.colors:
            self.colors[set_num] = self._get_default_color(set_num)

        color = self.colors[set_num]
        self._update_color_button_style(color_btn, color)

        color_btn.clicked.connect(lambda checked, s=set_num: self._pick_color(s))
        self.color_buttons[set_num] = color_btn

        # Label
        type_indicator = "H" if is_horizontal else "V"
        label = QLabel(f"Set {set_num} ({type_indicator})")
        label.setMinimumWidth(70)

        # Hex display
        hex_label = QLabel(color.name().upper())
        hex_label.setMinimumWidth(60)
        self.hex_labels[set_num] = hex_label

        # Add to layout
        self.colors_layout.addWidget(color_btn, row, 0)
        self.colors_layout.addWidget(label, row, 1)
        self.colors_layout.addWidget(hex_label, row, 2)

    def _pick_color(self, set_num):
        """Open color dialog for a specific set."""
        current_color = self.colors.get(set_num, QColor(255, 255, 255))

        color_dialog = QColorDialog(current_color, self)
        color_dialog.setOption(QColorDialog.ShowAlphaChannel)
        color_dialog.setOption(QColorDialog.DontUseNativeDialog)
        color_dialog.setWindowTitle(f"Select Color for Set {set_num}")

        # Apply theme styling
        self._style_color_dialog(color_dialog)

        if color_dialog.exec_() == QColorDialog.Accepted:
            new_color = color_dialog.currentColor()
            if new_color.isValid():
                self.colors[set_num] = new_color
                self._update_color_button_style(self.color_buttons[set_num], new_color)

                # Update hex label
                if set_num in self.hex_labels:
                    self.hex_labels[set_num].setText(new_color.name().upper())

    def _update_color_button_style(self, button, color):
        """Update button background to show the color."""
        hex_color = color.name()
        brightness = (color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000
        border_color = "#666" if brightness > 128 else "#333"

        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {hex_color};
                border: 2px solid {border_color};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border: 2px solid #888;
            }}
        """)

    def _get_default_color(self, set_num):
        """Get default color for a set number."""
        default_colors = {
            1: QColor(255, 255, 255),  # White
            2: QColor(85, 170, 0),     # Green
        }
        if set_num in default_colors:
            return default_colors[set_num]

        # Generate a pleasant random color
        h = random.random()
        s = random.uniform(0.4, 0.8)
        l = random.uniform(0.4, 0.6)
        r, g, b = [int(x * 255) for x in colorsys.hls_to_rgb(h, l, s)]
        return QColor(r, g, b)

    def reset_colors(self):
        """Reset all colors to defaults."""
        self.colors.clear()
        self.update_color_pickers()

    def generate_random_colors(self):
        """Generate random colors for all sets."""
        m = self.m_spinner.value()
        n = self.n_spinner.value()

        for set_num in range(1, m + n + 1):
            h = random.random()
            s = random.uniform(0.5, 0.9)
            l = random.uniform(0.4, 0.7)
            r, g, b = [int(x * 255) for x in colorsys.hls_to_rgb(h, l, s)]
            self.colors[set_num] = QColor(r, g, b)

        self.update_color_pickers()

    def generate_and_preview(self):
        """Generate JSON and image in memory, then show preview."""
        # Clear any frozen emoji assignments from previous alignment
        self._emoji_renderer.unfreeze_emoji_assignments()
        
        m = self.m_spinner.value()
        n = self.n_spinner.value()
        is_lh = self.lh_radio.isChecked()
        is_stretch = self.stretch_checkbox.isChecked()
        variant = ("lh" if is_lh else "rh") + ("_stretch" if is_stretch else "")
        scale_factor = self.scale_combo.currentData()

        self.status_label.setText("Generating pattern...")
        QApplication.processEvents()

        try:
            # Step 1: Generate JSON using the actual generator
            if is_lh:
                json_content = generate_lh_strech_json(m, n) if is_stretch else generate_lh_json(m, n)
            else:
                json_content = generate_rh_stretch_json(m, n) if is_stretch else generate_rh_json(m, n)

            # Step 2: Apply custom colors to the JSON
            data = json.loads(json_content)
            custom_colors = {}
            for set_num, qcolor in self.colors.items():
                custom_colors[set_num] = {
                    "r": qcolor.red(),
                    "g": qcolor.green(),
                    "b": qcolor.blue(),
                    "a": qcolor.alpha()
                }

            # Apply colors to all states
            if data.get('type') == 'OpenStrandStudioHistory':
                for state in data.get('states', []):
                    strands = state.get('data', {}).get('strands', [])
                    for strand in strands:
                        set_num = strand.get('set_number')
                        if set_num and set_num in custom_colors:
                            strand['color'] = custom_colors[set_num]

            json_content = json.dumps(data, indent=2)

            # Store JSON in memory (no file saving)
            self.current_json_data = json_content

            self.status_label.setText("Rendering image...")
            QApplication.processEvents()

            # Step 3: Generate image in memory
            image = self._generate_image_in_memory(json_content, scale_factor)

            if image and not image.isNull():
                # Store image in memory
                self.current_image = image

                # Keep preview panel styling stable before showing the pixmap
                self._update_preview_background_style()

                # Show the image in preview
                self.preview_widget.set_qimage(image)

                # Enable export buttons
                self.export_json_btn.setEnabled(True)
                self.export_image_btn.setEnabled(True)

                # Enable continuation button if stretch mode and emojis are on
                self._update_continuation_button_state()

                self.status_label.setText(
                    f"Generated {m}x{n} {variant.upper()} pattern in memory\nUse export buttons to save files"
                )
                self.save_color_settings()
            else:
                self.status_label.setText("Failed to generate image")
                self.export_json_btn.setEnabled(False)
                self.export_image_btn.setEnabled(False)
                self.continuation_btn.setEnabled(False)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_label.setText(f"Error: {str(e)}")
            self.export_json_btn.setEnabled(False)
            self.export_image_btn.setEnabled(False)
            self.continuation_btn.setEnabled(False)

    def _update_continuation_button_state(self):
        """Enable continuation button only when stretch mode + emojis are on + pattern generated."""
        # Guard: button may not exist during initialization
        if not hasattr(self, 'continuation_btn'):
            return

        can_continue = (
            self.current_json_data is not None and
            self.show_emojis_checkbox.isChecked() and
            self.stretch_checkbox.isChecked()
        )
        self.continuation_btn.setEnabled(can_continue)

        # Update tooltip based on state
        if not self.stretch_checkbox.isChecked():
            self.continuation_btn.setToolTip("Requires Stretch mode to be enabled")
        elif not self.show_emojis_checkbox.isChecked():
            self.continuation_btn.setToolTip("Requires Emojis to be shown")
        elif self.current_json_data is None:
            self.continuation_btn.setToolTip("Generate a base pattern first")
        else:
            self.continuation_btn.setToolTip("Generate continuation strands based on current emoji pairing")

        # Update align parallel button state
        self._update_align_parallel_button_state()

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

    def generate_continuation(self):
        """Generate continuation pattern (_4, _5 strands) based on current emoji pairing."""
        m = self.m_spinner.value()
        n = self.n_spinner.value()
        k = self.emoji_k_spinner.value()
        direction = "cw" if self.emoji_cw_radio.isChecked() else "ccw"
        is_lh = self.lh_radio.isChecked()
        scale_factor = self.scale_combo.currentData()

        self.status_label.setText("Generating continuation pattern...")
        QApplication.processEvents()

        try:
            # Generate continuation JSON
            if is_lh:
                json_content = generate_lh_continuation_json(m, n, k, direction)
            else:
                json_content = generate_rh_continuation_json(m, n, k, direction)

            # Apply custom colors to the JSON
            data = json.loads(json_content)
            custom_colors = {}
            for set_num, qcolor in self.colors.items():
                custom_colors[set_num] = {
                    "r": qcolor.red(),
                    "g": qcolor.green(),
                    "b": qcolor.blue(),
                    "a": qcolor.alpha()
                }

            # Apply colors to all states
            if data.get('type') == 'OpenStrandStudioHistory':
                for state in data.get('states', []):
                    strands = state.get('data', {}).get('strands', [])
                    for strand in strands:
                        set_num = strand.get('set_number')
                        if set_num and set_num in custom_colors:
                            strand['color'] = custom_colors[set_num]

            json_content = json.dumps(data, indent=2)

            # Store JSON in memory
            self.current_json_data = json_content
            # Store original continuation (before any extension is applied)
            self._continuation_json_data = json_content

            # Reset dynamic pair-extension controls for the new continuation.
            # Suppress auto-save so resets don't overwrite the saved preset.
            self._suppress_auto_save = True
            self._refresh_pair_extension_controls(preserve_values=False)
            self._reset_pair_extension_values()
            self._suppress_auto_save = False

            # Invalidate canvas cache and strand layer cache (new strands)
            self._prepared_canvas_key = None
            self._prepared_bounds = None
            self._cached_strand_layer = None
            self._cached_strand_layer_key = None
            self._emoji_renderer.clear_cache()

            self.status_label.setText("Rendering continuation image...")
            QApplication.processEvents()

            # Generate image in memory
            image = self._generate_image_in_memory(json_content, scale_factor)

            if image and not image.isNull():
                self.current_image = image
                self.preview_widget.set_qimage(image)

                self.export_json_btn.setEnabled(True)
                self.export_image_btn.setEnabled(True)
                self.align_parallel_btn.setEnabled(True)  # Enable parallel alignment
                self.preview_angles_btn.setEnabled(True)  # Enable angle preview

                # Auto-save JSON to appropriate continuation folder
                pattern_type = "lh" if is_lh else "rh"
                output_dir = os.path.join(script_dir, "mxn", "mxn_continueing", f"mxn_{pattern_type}_continuation")
                os.makedirs(output_dir, exist_ok=True)

                filename = f"mxn_{pattern_type}_strech_{m}x{n}_continue_k{k}_{direction}.json"
                output_path = os.path.join(output_dir, filename)

                with open(output_path, 'w') as f:
                    f.write(json_content)

                print(f"\nExported JSON to: {output_path}")

                self.status_label.setText(
                    f"Generated {m}x{n} {pattern_type.upper()} continuation (k={k}, {direction.upper()})\n"
                    f"Saved to: {filename}"
                )
                self.save_color_settings()

                # Load alignment preset if one exists for this combination
                self._suppress_auto_save = True
                if self._load_alignment_preset(m, n, k, direction, pattern_type):
                    self.status_label.setText(
                        f"Generated {m}x{n} {pattern_type.upper()} continuation (k={k}, {direction.upper()})\n"
                        f"Saved to: {filename} | Preset loaded"
                    )
                self._suppress_auto_save = False
            else:
                self.status_label.setText("Failed to generate continuation image")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_label.setText(f"Error generating continuation: {str(e)}")

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
                print(f"  Initial angle: {h_data['initial_angle']:.1f}°")
                print(f"  Range: {h_data['angle_min']:.1f}° to {h_data['angle_max']:.1f}°")

            if preview_data["vertical"]:
                v_data = preview_data["vertical"]
                self.v_angle_min_spin.setValue(math.floor(v_data["angle_min"]))
                self.v_angle_max_spin.setValue(math.ceil(v_data["angle_max"]))
                print(f"Vertical order: {v_data.get('strand_order', [])}")
                print(f"  First: {v_data['first_name']}, Last: {v_data['last_name']}")
                print(f"  Initial angle: {v_data['initial_angle']:.1f}°")
                print(f"  Range: {v_data['angle_min']:.1f}° to {v_data['angle_max']:.1f}°")

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
            label_text = f"H: {self.h_angle_min_spin.value()}° to {self.h_angle_max_spin.value()}°"
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
            label_text = f"V: {self.v_angle_min_spin.value()}° to {self.v_angle_max_spin.value()}°"
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
                print_alignment_fn = print_alignment_debug_lh
            else:
                align_horizontal_fn = align_horizontal_strands_parallel_rh
                align_vertical_fn = align_vertical_strands_parallel_rh
                apply_alignment_fn = apply_parallel_alignment_rh
                print_alignment_fn = print_alignment_debug_rh

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

            if use_custom:
                print(f"\n*** Using CUSTOM angle ranges (checkbox IS checked) ***")
                print(f"  Horizontal: {h_custom_min}° to {h_custom_max}°")
                print(f"  Vertical: {v_custom_min}° to {v_custom_max}°")
            else:
                print(f"\n*** Using AUTO angle ranges (checkbox NOT checked, mode={angle_mode}) ***")
                print(f"  Will use angle mode '{angle_mode}' for range calculation")

            # ============================================================
            # SETUP OUTPUT FOLDERS FOR ALL ATTEMPTS
            # ============================================================
            script_dir = os.path.dirname(os.path.abspath(__file__))
            is_lh = self.lh_radio.isChecked()
            pattern_type = "lh" if is_lh else "rh"
            k = self.emoji_k_spinner.value() if hasattr(self, 'emoji_k_spinner') else 0
            direction = "cw" if (hasattr(self, 'emoji_cw_radio') and self.emoji_cw_radio.isChecked()) else "ccw"
            diagram_name = f"{m}x{n}"

            base_output_dir = os.path.join(
                script_dir,
                "mxn", "mxn_output", diagram_name, f"k_{k}_{direction}_{pattern_type}"
            )
            attempt_dir = os.path.join(base_output_dir, "attempt_options")
            os.makedirs(attempt_dir, exist_ok=True)

            attempt_count = [0]  # Use list to allow modification in nested function
            best_h_result_info = [None]  # Mutable container for horizontal result info (set after H phase)
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
                lines.append(f"Attempt: #{attempt_num} | Angle: {angle_deg:.1f}° | Extension: {extension}px | Status: {status_str}")
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
                lines.append(f"|  Line Vector:      ({line_ux:+.3f}, {line_uy:+.3f})   |  Angle: {line_angle:.1f}°" + " " * 20 + "|")
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

                        if attempt_count[0] % 20 == 0:  # Log every 20th save
                            print(f"  Saved {attempt_count[0]} images...")
                except Exception as e:
                    print(f"  Error saving attempt {attempt_count[0]}: {e}")

            # ============================================================
            # FREEZE EMOJI ASSIGNMENTS BEFORE ALIGNMENT
            # ============================================================
            # Capture current emoji-to-strand mapping so emojis stay with their
            # original strands even after positions change during alignment
            print("\n" + "="*60)
            print("FREEZING EMOJI ASSIGNMENTS (pre-alignment)")
            print("="*60)
            
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
            print("\n" + "="*60)
            print("ALIGN HORIZONTAL STRANDS")
            print("="*60)
            print(f"  H angle range: {h_custom_min}° to {h_custom_max}°")
            print(f"  V angle range: {v_custom_min}° to {v_custom_max}°")
            print(f"  angle_step=0.5°, max_extension=100.0px")
            print(f"  pair_ext_max={pair_ext_max}px, pair_ext_step={pair_ext_step}px")
            print(f"  k={k}, direction={direction}, m={m}, n={n}")

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

            print_alignment_fn(h_result)

            if h_result["success"] or h_result.get("is_fallback"):
                strands = apply_alignment_fn(strands, h_result)
                h_success = h_result["success"]  # Only True for real solutions, not fallback
                h_angle = h_result.get("angle_degrees", 0)
                h_gap = h_result.get("average_gap", 0)
                if h_result.get("is_fallback"):
                    worst_gap = h_result.get("worst_gap", 0)
                    print(f"Horizontal FALLBACK applied: angle={h_angle:.2f}°, avg_gap={h_gap:.1f}px, worst_gap={worst_gap:.1f}px")
                else:
                    print(f"Horizontal alignment applied: angle={h_angle:.2f}°, gap={h_gap:.1f}px")
            else:
                print(f"Horizontal alignment failed: {h_result.get('message', 'Unknown')}")

            # Build horizontal result info for vertical txt files
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

            # ============================================================
            # VERTICAL ALIGNMENT
            # ============================================================
            print("\n" + "="*60)
            print("ALIGN VERTICAL STRANDS")
            print("="*60)
            print(f"  V angle range: {v_custom_min}° to {v_custom_max}°")
            print(f"  angle_step=0.5°, max_extension=100.0px")
            print(f"  pair_ext_max={pair_ext_max}px, pair_ext_step={pair_ext_step}px")
            print(f"  k={k}, direction={direction}, m={m}, n={n}")

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

            print_alignment_fn(v_result)

            if v_result["success"] or v_result.get("is_fallback"):
                strands = apply_alignment_fn(strands, v_result)
                v_success = v_result["success"]  # Only True for real solutions, not fallback
                v_angle = v_result.get("angle_degrees", 0)
                v_gap = v_result.get("average_gap", 0)
                if v_result.get("is_fallback"):
                    worst_gap = v_result.get("worst_gap", 0)
                    print(f"Vertical FALLBACK applied: angle={v_angle:.2f}°, avg_gap={v_gap:.1f}px, worst_gap={worst_gap:.1f}px")
                else:
                    print(f"Vertical alignment applied: angle={v_angle:.2f}°, gap={v_gap:.1f}px")
            else:
                print(f"Vertical alignment failed: {v_result.get('message', 'Unknown')}")

            # ============================================================
            # UPDATE AND RENDER
            # ============================================================
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
                    status_parts.append(f"H: {h_angle:.1f}°, gap={h_gap:.1f}px")
                else:
                    status_parts.append("H: failed")
                if v_success:
                    status_parts.append(f"V: {v_angle:.1f}°, gap={v_gap:.1f}px")
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
        print(f"\n>>> ENTERING SAVE BLOCK <<<")
        print(f"h_success={h_success}, v_success={v_success}")
        print(f"h_angle={h_angle}, v_angle={v_angle}")
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
            print(f"\n=== SAVING OUTPUT ===")
            print(f"Output dir: {output_subdir}")

            # Create filename with pattern details
            h_status = f"h{h_angle:.1f}" if h_success and h_angle is not None else "h_fail"
            v_status = f"v{v_angle:.1f}" if v_success and v_angle is not None else "v_fail"
            filename_base = f"mxn_{pattern_type}_{m}x{n}_k{k}_{direction}_{h_status}_{v_status}"

            # Save image
            if self.current_image and not self.current_image.isNull():
                img_path = os.path.join(output_subdir, f"{filename_base}.png")
                save_result = self.current_image.save(img_path)
                result_type = "SOLUTION" if is_valid_solution else "INVALID"
                print(f"{result_type} saved: {img_path}")
                print(f"Save result: {save_result}")
            else:
                print(f"ERROR: No image to save! current_image={self.current_image}")

            # Save aligned JSON next to the image in the same output folder.
            json_path = os.path.join(output_subdir, f"{filename_base}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(self.current_json_data)
            print(f"JSON saved: {json_path}")

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
                    f.write(f"Angle: {h_angle:.2f}°\n")
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
                    f.write(f"Angle: {v_angle:.2f}°\n")
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
                f.write(f"H angle: {h_angle:.2f}°\n" if h_angle is not None else "H angle: N/A\n")
                f.write(f"H gap: {h_gap:.2f} px\n" if h_gap is not None else "H gap: N/A\n")
                f.write(f"H success: {h_success}\n")

                f.write("\n")
                f.write("PARAMETERS\n")
                f.write("-" * 40 + "\n")
                f.write(f"H angle range: {self.h_angle_min_spin.value()}° to {self.h_angle_max_spin.value()}°\n")
                f.write(f"V angle range: {self.v_angle_min_spin.value()}° to {self.v_angle_max_spin.value()}°\n")
                f.write(f"Custom angles: {self.use_custom_angles_cb.isChecked()}\n")
                f.write(f"Pair ext max: {self.pair_ext_max_spin.value()}px\n")
                f.write(f"Pair ext step: {self.pair_ext_step_spin.value()}px\n")
                f.write(f"Max extension: 100.0px\n")
                f.write(f"Angle step: 0.5°\n")
                f.write(f"Strand width: 46px\n")

            print(f"TXT saved: {txt_path}")

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
            print(f"Preset saved: {preset_path}")

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
            from openstrandstudio.src.save_load_manager import load_strands, apply_loaded_strands
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
                    import tempfile
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
                        json.dump(current_data, tmp)
                        temp_path = tmp.name

                    strands, groups, _, _, _, _, _, shadow_overrides = load_strands(temp_path, canvas)
                    os.unlink(temp_path)
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

    def export_json(self):
        """Export the current JSON data to a file chosen by the user."""
        if not self.current_json_data:
            QMessageBox.warning(self, "No Data", "Please generate a pattern first.")
            return

        m = self.m_spinner.value()
        n = self.n_spinner.value()
        is_stretch = self.stretch_checkbox.isChecked()
        base_variant = "lh" if self.lh_radio.isChecked() else "rh"
        variant = base_variant + ("_strech" if (is_stretch and base_variant == "lh") else ("_stretch" if is_stretch else ""))
        default_name = f"mxn_{variant}_{m}x{n}.json"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export JSON",
            default_name,
            "JSON Files (*.json);;All Files (*)"
        )

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.current_json_data)
                self.status_label.setText(f"JSON exported to:\n{os.path.basename(file_path)}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export JSON:\n{str(e)}")

    def export_image(self):
        """Export the current image to a file chosen by the user."""
        if not self.current_image or self.current_image.isNull():
            QMessageBox.warning(self, "No Image", "Please generate a pattern first.")
            return

        m = self.m_spinner.value()
        n = self.n_spinner.value()
        is_stretch = self.stretch_checkbox.isChecked()
        base_variant = "lh" if self.lh_radio.isChecked() else "rh"
        variant = base_variant + ("_strech" if (is_stretch and base_variant == "lh") else ("_stretch" if is_stretch else ""))
        default_name = f"mxn_{variant}_{m}x{n}.png"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Image",
            default_name,
            "PNG Files (*.png);;JPEG Files (*.jpg *.jpeg);;All Files (*)"
        )

        if file_path:
            try:
                self.current_image.save(file_path)
                self.status_label.setText(f"Image exported to:\n{os.path.basename(file_path)}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export image:\n{str(e)}")

    def get_settings_directory(self):
        """Get settings directory."""
        app_name = "OpenStrand Studio"
        if sys.platform.startswith('darwin'):
            program_data_dir = os.path.expanduser('~/Library/Application Support')
            return os.path.join(program_data_dir, app_name)
        else:
            program_data_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
            return program_data_dir

    def save_color_settings(self):
        """Save current color configuration to settings file."""
        settings_dir = self.get_settings_directory()
        os.makedirs(settings_dir, exist_ok=True)

        file_path = os.path.join(settings_dir, 'mxn_cad_colors.json')

        colors_data = {
            'last_m': self.m_spinner.value(),
            'last_n': self.n_spinner.value(),
            'last_variant': 'lh' if self.lh_radio.isChecked() else 'rh',
            'last_stretch': bool(self.stretch_checkbox.isChecked()),
            'emoji': {
                'enabled': bool(getattr(self, "show_emojis_checkbox", None) and self.show_emojis_checkbox.isChecked()),
                'show_strand_names': bool(getattr(self, "show_strand_names_checkbox", None) and self.show_strand_names_checkbox.isChecked()),
                'k': int(getattr(self, "emoji_k_spinner", None).value()) if getattr(self, "emoji_k_spinner", None) else 0,
                'dir': 'cw' if (getattr(self, "emoji_cw_radio", None) and self.emoji_cw_radio.isChecked()) else 'ccw',
                'set': self.emoji_set_combo.currentData() if getattr(self, "emoji_set_combo", None) else 'default',
            },
            'colors': {}
        }

        for set_num, qcolor in self.colors.items():
            colors_data['colors'][str(set_num)] = {
                'r': qcolor.red(),
                'g': qcolor.green(),
                'b': qcolor.blue(),
                'a': qcolor.alpha()
            }

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(colors_data, f, indent=2)
        except Exception as e:
            print(f"Failed to save color settings: {e}")

    def load_color_settings(self):
        """Load color configuration from settings file."""
        settings_dir = self.get_settings_directory()
        file_path = os.path.join(settings_dir, 'mxn_cad_colors.json')

        if not os.path.exists(file_path):
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                colors_data = json.load(f)

            if 'last_m' in colors_data:
                self.m_spinner.setValue(colors_data['last_m'])
            if 'last_n' in colors_data:
                self.n_spinner.setValue(colors_data['last_n'])

            if colors_data.get('last_variant') == 'rh':
                self.rh_radio.setChecked(True)
            else:
                self.lh_radio.setChecked(True)

            if 'last_stretch' in colors_data:
                self.stretch_checkbox.setChecked(bool(colors_data.get('last_stretch')))

            # Emoji settings (optional)
            emoji = colors_data.get('emoji') or {}
            if hasattr(self, "show_emojis_checkbox") and "enabled" in emoji:
                self.show_emojis_checkbox.setChecked(bool(emoji.get("enabled")))
            if hasattr(self, "show_strand_names_checkbox") and "show_strand_names" in emoji:
                self.show_strand_names_checkbox.setChecked(bool(emoji.get("show_strand_names")))
            if hasattr(self, "emoji_k_spinner") and "k" in emoji:
                try:
                    self.emoji_k_spinner.setValue(int(emoji.get("k", 0)))
                except Exception:
                    pass
            if hasattr(self, "emoji_set_combo") and "set" in emoji:
                idx = self.emoji_set_combo.findData(emoji.get("set", "default"))
                if idx >= 0:
                    self.emoji_set_combo.setCurrentIndex(idx)
            if hasattr(self, "emoji_cw_radio") and hasattr(self, "emoji_ccw_radio") and "dir" in emoji:
                if str(emoji.get("dir", "cw")).lower() == "ccw":
                    self.emoji_ccw_radio.setChecked(True)
                else:
                    self.emoji_cw_radio.setChecked(True)

            if 'colors' in colors_data:
                for set_num_str, color_dict in colors_data['colors'].items():
                    set_num = int(set_num_str)
                    self.colors[set_num] = QColor(
                        color_dict['r'],
                        color_dict['g'],
                        color_dict['b'],
                        color_dict.get('a', 255)
                    )

        except Exception as e:
            print(f"Failed to load color settings: {e}")

    def _open_full_auto(self):
        """Open the Full Auto batch generation dialog."""
        dialog = FullAutoDialog(parent_dialog=self, parent=self)
        dialog.exec_()

    def _apply_theme(self):
        """Apply theme-based styling to the dialog."""
        if self.theme == 'dark':
            self.setStyleSheet("""
                QDialog {
                    background-color: #2C2C2C;
                    color: white;
                }
                QGroupBox {
                    background-color: transparent;
                    color: white;
                    border: 1px solid #555;
                    border-radius: 4px;
                    margin-top: 8px;
                    padding-top: 10px;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px;
                    background-color: transparent;
                }
                QLabel {
                    color: white;
                    background-color: transparent;
                }
                QSpinBox, QComboBox {
                    background-color: #3D3D3D;
                    color: white;
                    border: 1px solid #555;
                    padding: 5px;
                    border-radius: 3px;
                    min-height: 20px;
                }
                QSpinBox::up-button, QSpinBox::down-button {
                    background-color: #4D4D4D;
                    border: none;
                    width: 16px;
                }
                QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                    background-color: #5D5D5D;
                }
                QRadioButton, QCheckBox {
                    color: white;
                    background-color: transparent;
                }
                QRadioButton::indicator, QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                }
                QScrollArea {
                    background-color: #3D3D3D;
                    border: 1px solid #555;
                    border-radius: 4px;
                }
                QScrollArea > QWidget > QWidget {
                    background-color: #3D3D3D;
                }
                QPushButton {
                    background-color: #404040;
                    color: white;
                    border: 1px solid #555;
                    padding: 6px 12px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #505050;
                    border: 1px solid #666;
                }
                QPushButton:pressed {
                    background-color: #353535;
                }
                QPushButton:disabled {
                    background-color: #2a2a2a;
                    color: #666666;
                }
            """)
        else:
            self.setStyleSheet("""
                QDialog {
                    background-color: #F5F5F5;
                    color: black;
                }
                QGroupBox {
                    color: black;
                    border: 1px solid #CCC;
                    border-radius: 4px;
                    margin-top: 8px;
                    padding-top: 10px;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px;
                }
                QLabel {
                    color: black;
                }
                QSpinBox, QComboBox {
                    background-color: white;
                    color: black;
                    border: 1px solid #CCC;
                    padding: 5px;
                    border-radius: 3px;
                    min-height: 20px;
                }
                QRadioButton, QCheckBox {
                    color: black;
                }
                QScrollArea {
                    background-color: white;
                    border: 1px solid #CCC;
                    border-radius: 4px;
                }
                QScrollArea > QWidget > QWidget {
                    background-color: white;
                }
                QPushButton {
                    background-color: #FFFFFF;
                    color: black;
                    border: 1px solid #CCCCCC;
                    padding: 6px 12px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #E8E8E8;
                    border: 1px solid #AAAAAA;
                }
                QPushButton:pressed {
                    background-color: #D0D0D0;
                }
                QPushButton:disabled {
                    background-color: #F0F0F0;
                    color: #AAAAAA;
                }
            """)

    def _style_color_dialog(self, dialog):
        """Apply theme styling to QColorDialog."""
        is_dark = self.theme == 'dark'

        if is_dark:
            dialog.setStyleSheet("""
                QColorDialog { background-color: #2C2C2C; color: white; }
                QColorDialog QWidget { background-color: #2C2C2C; color: white; }
                QColorDialog QPushButton {
                    background-color: #404040;
                    color: white;
                    border: 1px solid #555;
                    padding: 6px 12px;
                    border-radius: 4px;
                }
                QColorDialog QPushButton:hover { background-color: #505050; }
                QLabel { color: white; }
                QLineEdit { background-color: #3D3D3D; color: white; border: 1px solid #555; }
                QSpinBox { background-color: #3D3D3D; color: white; border: 1px solid #555; }
            """)
        else:
            dialog.setStyleSheet("""
                QColorDialog { background-color: #FFFFFF; color: #000000; }
                QColorDialog QPushButton {
                    background-color: #F0F0F0;
                    color: #000000;
                    border: 1px solid #BBBBBB;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
                QColorDialog QPushButton:hover { background-color: #E0E0E0; }
            """)

    def closeEvent(self, event):
        """Clean up when dialog closes."""
        if self._main_window:
            self._main_window.close()
            self._main_window = None
        super().closeEvent(event)


def main():
    """Standalone entry point for the dialog."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    dialog = MxNGeneratorDialog()
    dialog.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
