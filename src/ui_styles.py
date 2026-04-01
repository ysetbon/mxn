"""Checkbox and radio button styling utilities for MxN CAD UI."""

from PyQt5.QtWidgets import QProxyStyle, QStyle, QStyleOptionButton
from PyQt5.QtCore import Qt, QRectF, QRect
from PyQt5.QtGui import QColor, QPainter, QPen, QBrush, QPainterPath


class _LargeIndicatorStyle(QProxyStyle):
    """Proxy style that enforces a specific checkbox indicator size."""

    def __init__(self, base_style, indicator_size=14):
        super().__init__(base_style)
        self._indicator_size = indicator_size

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (
            QStyle.PM_IndicatorWidth,
            QStyle.PM_IndicatorHeight,
            QStyle.PM_ExclusiveIndicatorWidth,
            QStyle.PM_ExclusiveIndicatorHeight,
        ):
            return self._indicator_size
        return super().pixelMetric(metric, option, widget)


def _apply_large_checkbox_indicator(checkbox, indicator_size=14):
    """Apply a fixed-size indicator style to a checkbox."""
    base_style = checkbox.style()
    if isinstance(base_style, _LargeIndicatorStyle):
        base_style = base_style.baseStyle()
    checkbox.setStyle(_LargeIndicatorStyle(base_style, indicator_size))
    checkbox.setMinimumHeight(max(checkbox.minimumHeight(), indicator_size + 4))


def _apply_radio_indicator_size(radio_button, indicator_size=14):
    """Apply a fixed-size indicator style to a radio button."""
    base_style = radio_button.style()
    if isinstance(base_style, _LargeIndicatorStyle):
        base_style = base_style.baseStyle()
    radio_button.setStyle(_LargeIndicatorStyle(base_style, indicator_size))
    radio_button.setMinimumHeight(max(radio_button.minimumHeight(), indicator_size + 4))


def _install_custom_checkbox_checkmark(checkbox):
    """Draw the same crisp white checkmark used in OpenStrandStudio dialogs."""
    if getattr(checkbox, "_mxn_custom_checkmark_installed", False):
        return

    original_paint_event = checkbox.paintEvent

    def custom_paint_event(event, _original=original_paint_event, _checkbox=checkbox):
        _original(event)

        if not _checkbox.isChecked():
            return

        painter = QPainter(_checkbox)
        painter.setRenderHint(QPainter.Antialiasing)

        style_option = QStyleOptionButton()
        _checkbox.initStyleOption(style_option)
        indicator_rect = _checkbox.style().subElementRect(
            QStyle.SE_CheckBoxIndicator, style_option, _checkbox
        )
        indicator_rect = QRect(indicator_rect.x(), indicator_rect.y(), indicator_rect.width(), indicator_rect.height())

        pen_width = max(1.6, indicator_rect.height() * 0.16)
        painter.setPen(QPen(QColor(255, 255, 255), pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

        left = indicator_rect.left()
        top = indicator_rect.top()
        width = indicator_rect.width()
        height = indicator_rect.height()

        check_path = QPainterPath()
        check_path.moveTo(left + width * 0.25, top + height * 0.55)
        check_path.lineTo(left + width * 0.42, top + height * 0.72)
        check_path.lineTo(left + width * 0.78, top + height * 0.28)
        painter.drawPath(check_path)
        painter.end()

    checkbox.paintEvent = custom_paint_event
    checkbox._mxn_custom_checkmark_installed = True


def _install_custom_radio_inner_dot(radio_button):
    """Draw a crisp white inner dot for checked radio buttons."""
    if getattr(radio_button, "_mxn_custom_radio_dot_installed", False):
        return

    original_paint_event = radio_button.paintEvent

    def custom_paint_event(event, _original=original_paint_event, _radio=radio_button):
        _original(event)

        if not _radio.isChecked():
            return

        painter = QPainter(_radio)
        painter.setRenderHint(QPainter.Antialiasing)

        style_option = QStyleOptionButton()
        _radio.initStyleOption(style_option)
        indicator_rect = _radio.style().subElementRect(
            QStyle.SE_RadioButtonIndicator, style_option, _radio
        )

        dot_diameter = max(4.0, min(indicator_rect.width(), indicator_rect.height()) * 0.36)
        center = indicator_rect.center()
        dot_rect = QRectF(
            center.x() - dot_diameter / 2.0,
            center.y() - dot_diameter / 2.0,
            dot_diameter,
            dot_diameter,
        )

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(dot_rect)
        painter.end()

    radio_button.paintEvent = custom_paint_event
    radio_button._mxn_custom_radio_dot_installed = True


def _style_toggle_checkbox(checkbox, is_dark_mode, is_enabled=None, spacing=8):
    """Apply the checkbox styling used by the shadow editor and mask grid dialogs."""
    if is_enabled is None:
        is_enabled = checkbox.isEnabled()

    if is_dark_mode:
        text_color = "#FFFFFF" if is_enabled else "#808080"
        indicator_border = "#666666"
        indicator_background = "#2A2A2A"
        hover_border = "#888888"
        hover_background = "#454545"
        checked_background = "#4A6FA5"
        checked_border = "#6A9FD5"
        checked_hover_background = "#5A7FB5"
        checked_hover_border = "#7AAFF5"
        disabled_indicator = "#1F1F1F"
        disabled_border = "#444444"
    else:
        text_color = "#000000" if is_enabled else "#AAAAAA"
        indicator_border = "#AAAAAA"
        indicator_background = "#FFFFFF"
        hover_border = "#888888"
        hover_background = "#F8F8F8"
        checked_background = "#A0C0E0"
        checked_border = "#7090C0"
        checked_hover_background = "#B0D0F0"
        checked_hover_border = "#8AA0D0"
        disabled_indicator = "#F0F0F0"
        disabled_border = "#BBBBBB"

    checkbox.setStyleSheet(f"""
        QCheckBox {{
            color: {text_color};
            spacing: {spacing}px;
            background-color: transparent;
        }}
        QCheckBox::indicator {{
            width: 14px;
            height: 14px;
            min-width: 14px;
            min-height: 14px;
            border: 2px solid {indicator_border};
            border-radius: 3px;
            background-color: {indicator_background};
        }}
        QCheckBox::indicator:hover {{
            border: 2px solid {hover_border};
            background-color: {hover_background};
        }}
        QCheckBox::indicator:checked {{
            background-color: {checked_background};
            border: 2px solid {checked_border};
        }}
        QCheckBox::indicator:checked:hover {{
            background-color: {checked_hover_background};
            border: 2px solid {checked_hover_border};
        }}
        QCheckBox::indicator:disabled {{
            background-color: {disabled_indicator};
            border: 2px solid {disabled_border};
        }}
    """)


def _style_toggle_radio_button(radio_button, is_dark_mode, is_enabled=None, spacing=7):
    """Apply a smaller radio-button style that matches the blue toggle palette."""
    if is_enabled is None:
        is_enabled = radio_button.isEnabled()

    if is_dark_mode:
        text_color = "#FFFFFF" if is_enabled else "#808080"
        indicator_border = "#8F8F8F"
        indicator_background = "#F4F4F4"
        hover_border = "#A8A8A8"
        hover_background = "#FFFFFF"
        checked_background = "#1976D2"
        checked_border = "#42A5F5"
        checked_hover_background = "#1E88E5"
        checked_hover_border = "#64B5F6"
        disabled_indicator = "#3A3A3A"
        disabled_border = "#575757"
    else:
        text_color = "#000000" if is_enabled else "#AAAAAA"
        indicator_border = "#9E9E9E"
        indicator_background = "#FFFFFF"
        hover_border = "#7E7E7E"
        hover_background = "#FFFFFF"
        checked_background = "#1976D2"
        checked_border = "#42A5F5"
        checked_hover_background = "#1E88E5"
        checked_hover_border = "#64B5F6"
        disabled_indicator = "#F0F0F0"
        disabled_border = "#C4C4C4"

    radio_button.setStyleSheet(f"""
        QRadioButton {{
            color: {text_color};
            spacing: {spacing}px;
            background-color: transparent;
        }}
        QRadioButton::indicator {{
            width: 14px;
            height: 14px;
            min-width: 14px;
            min-height: 14px;
            border: 2px solid {indicator_border};
            border-radius: 7px;
            background-color: {indicator_background};
        }}
        QRadioButton::indicator:hover {{
            border: 2px solid {hover_border};
            background-color: {hover_background};
        }}
        QRadioButton::indicator:checked {{
            background-color: {checked_background};
            border: 2px solid {checked_border};
        }}
        QRadioButton::indicator:checked:hover {{
            background-color: {checked_hover_background};
            border: 2px solid {checked_hover_border};
        }}
        QRadioButton::indicator:disabled {{
            background-color: {disabled_indicator};
            border: 2px solid {disabled_border};
        }}
    """)
