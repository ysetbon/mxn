"""Theme, GPU status, and MainWindow lifecycle mixin for MxNGeneratorDialog."""

from PyQt5.QtWidgets import QApplication, QCheckBox, QRadioButton
from ui_styles import (
    _apply_large_checkbox_indicator,
    _apply_radio_indicator_size,
    _install_custom_checkbox_checkmark,
    _install_custom_radio_inner_dot,
    _style_toggle_checkbox,
    _style_toggle_radio_button,
)


class ThemeMixin:
    """Mixin providing theme management, GPU detection, and MainWindow lifecycle."""

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

    def _iter_toggle_checkboxes(self):
        return self.findChildren(QCheckBox)

    def _iter_radio_buttons(self):
        return self.findChildren(QRadioButton)

    def _initialize_toggle_checkboxes(self):
        for checkbox in self._iter_toggle_checkboxes():
            _apply_large_checkbox_indicator(checkbox, indicator_size=14)
            _install_custom_checkbox_checkmark(checkbox)

    def _initialize_radio_buttons(self):
        for radio_button in self._iter_radio_buttons():
            _apply_radio_indicator_size(radio_button, indicator_size=14)
            _install_custom_radio_inner_dot(radio_button)

    def _restyle_toggle_checkboxes(self):
        is_dark_mode = (self.theme == 'dark')
        for checkbox in self._iter_toggle_checkboxes():
            _style_toggle_checkbox(checkbox, is_dark_mode, checkbox.isEnabled())

    def _restyle_radio_buttons(self):
        is_dark_mode = (self.theme == 'dark')
        for radio_button in self._iter_radio_buttons():
            _style_toggle_radio_button(radio_button, is_dark_mode, radio_button.isEnabled())

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
        self._restyle_toggle_checkboxes()
        self._restyle_radio_buttons()

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
