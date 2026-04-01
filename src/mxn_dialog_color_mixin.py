"""Color management mixin for MxNGeneratorDialog."""

import os
import sys
import json
import random
import colorsys

from PyQt5.QtWidgets import QPushButton, QLabel, QColorDialog
from PyQt5.QtGui import QColor
from PyQt5.QtCore import QStandardPaths


class ColorMixin:
    """Mixin providing color picker management and settings persistence."""

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
