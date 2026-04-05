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
    QApplication, QSizePolicy, QFileDialog, QStyleOptionButton, QProxyStyle, QStyle
)
from PyQt5.QtCore import Qt, pyqtSignal, QStandardPaths, QSize, QRectF, QPointF, QThread, QRect
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

# Import extracted modules
from ui_utils import (
    EMOJI_SET_ITEMS,
    _get_active_history_state,
    _get_active_strands,
    _set_active_strands,
)
from ui_styles import (
    _apply_large_checkbox_indicator,
    _apply_radio_indicator_size,
    _install_custom_checkbox_checkmark,
    _install_custom_radio_inner_dot,
    _style_toggle_checkbox,
    _style_toggle_radio_button,
)
from batch_rendering import ImagePreviewWidget, BatchWorker
from full_auto_dialog import FullAutoDialog

# Import mixins
from mxn_dialog_theme_mixin import ThemeMixin
from mxn_dialog_color_mixin import ColorMixin
from mxn_dialog_render_mixin import RenderMixin
from mxn_dialog_alignment_mixin import AlignmentMixin


class MxNGeneratorDialog(AlignmentMixin, RenderMixin, ColorMixin, ThemeMixin, QDialog):
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
        self._syncing_variant_direction = False

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
        self._initialize_toggle_checkboxes()
        self._initialize_radio_buttons()

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
        self.emoji_k_spinner.valueChanged.connect(self._on_emoji_rotation_changed)

        self.emoji_dir_group = QButtonGroup(self)
        self.emoji_cw_radio = QRadioButton("CW")
        self.emoji_ccw_radio = QRadioButton("CCW")
        self.emoji_dir_group.addButton(self.emoji_cw_radio, 0)
        self.emoji_dir_group.addButton(self.emoji_ccw_radio, 1)
        self.emoji_cw_radio.setChecked(True)
        self.emoji_cw_radio.toggled.connect(self._on_emoji_direction_changed)
        self.emoji_ccw_radio.toggled.connect(self._on_emoji_direction_changed)

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
        self.angle_mode_combo.addItem("First strand \u00b120\u00b0", "first_strand")
        self.angle_mode_combo.addItem("Average \u2194 Gaussian bounds", "avg_gaussian")
        self.angle_mode_combo.setToolTip(
            "First strand: original method (first strand angle \u00b120\u00b0)\n"
            "Average \u2194 Gaussian: use the uniform average angle and Gaussian-weighted\n"
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

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

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
        """Re-render preview when emoji display options change."""
        # Emoji toggles should update preview immediately
        self._rerender_preview_if_possible()
        # Update continuation button state (depends on emoji checkbox)
        self._update_continuation_button_state()

    def _on_emoji_rotation_changed(self, _value):
        """Re-render preview and rebuild k-dependent pair controls."""
        self._on_emoji_settings_changed()
        self._refresh_pair_extension_controls(preserve_values=True)

    def _on_emoji_direction_changed(self, checked):
        """Keep direction and handedness in sync for the checked radio only."""
        if not checked:
            return
        if self._syncing_variant_direction:
            return

        self._syncing_variant_direction = True
        try:
            if self.emoji_cw_radio.isChecked():
                self.lh_radio.setChecked(True)
            else:
                self.rh_radio.setChecked(True)
        finally:
            self._syncing_variant_direction = False

        self._on_emoji_settings_changed()
        self._refresh_pair_extension_controls(preserve_values=True)

    def _on_refresh_emojis_clicked(self):
        """Force-refresh emoji rendering (clears cached emoji glyph images)."""
        if getattr(self, "_emoji_renderer", None) is not None:
            if hasattr(self._emoji_renderer, "clear_render_cache"):
                self._emoji_renderer.clear_render_cache()
            else:
                self._emoji_renderer.clear_cache()
        self._rerender_preview_if_possible()

    def _on_variant_changed(self, checked):
        """Keep handedness and direction in sync for the checked radio only."""
        if not checked:
            return
        if self._syncing_variant_direction:
            return

        self._syncing_variant_direction = True
        try:
            if hasattr(self, 'emoji_cw_radio'):
                if self.lh_radio.isChecked():
                    self.emoji_cw_radio.setChecked(True)
                else:
                    self.emoji_ccw_radio.setChecked(True)
        finally:
            self._syncing_variant_direction = False

        self._update_continuation_button_state()
        self._refresh_pair_extension_controls(preserve_values=False)

    def _on_background_settings_changed(self):
        """Re-render preview and update panel background when transparency changes."""
        self._update_preview_background_style()
        self._rerender_preview_if_possible()

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Full Auto
    # ------------------------------------------------------------------

    def _open_full_auto(self):
        """Open the Full Auto batch generation dialog."""
        dialog = FullAutoDialog(parent_dialog=self, parent=self)
        dialog.exec_()


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
