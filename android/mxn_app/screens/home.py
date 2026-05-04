"""Home screen: pick grid size + variant, generate the OpenStrandStudio JSON."""

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from mxn_app.core.generator import generate


_SIZE_VALUES = [str(i) for i in range(1, 11)]


class HomeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        root = BoxLayout(orientation="vertical", padding=12, spacing=10)

        title = Label(
            text="MxN CAD Generator",
            size_hint_y=None,
            height=44,
            font_size=22,
            bold=True,
        )
        root.add_widget(title)

        # Grid size row
        row_size = BoxLayout(orientation="horizontal", size_hint_y=None, height=48, spacing=8)
        row_size.add_widget(Label(text="M", size_hint_x=None, width=24))
        self.m_spinner = Spinner(text="3", values=_SIZE_VALUES, size_hint_x=None, width=80)
        row_size.add_widget(self.m_spinner)
        row_size.add_widget(Label(text="N", size_hint_x=None, width=24))
        self.n_spinner = Spinner(text="3", values=_SIZE_VALUES, size_hint_x=None, width=80)
        row_size.add_widget(self.n_spinner)
        row_size.add_widget(Label(text=""))
        root.add_widget(row_size)

        # Variant row
        row_variant = BoxLayout(orientation="horizontal", size_hint_y=None, height=48, spacing=8)
        row_variant.add_widget(Label(text="Variant", size_hint_x=None, width=80))
        self.variant_spinner = Spinner(text="LH", values=["LH", "RH"], size_hint_x=None, width=100)
        row_variant.add_widget(self.variant_spinner)
        row_variant.add_widget(Label(text="Stretch", size_hint_x=None, width=80))
        self.stretch_checkbox = CheckBox(active=False, size_hint_x=None, width=48)
        row_variant.add_widget(self.stretch_checkbox)
        row_variant.add_widget(Label(text=""))
        root.add_widget(row_variant)

        # Generate button
        self.generate_btn = Button(
            text="Generate JSON",
            size_hint_y=None,
            height=56,
            font_size=18,
        )
        self.generate_btn.bind(on_release=self._on_generate)
        root.add_widget(self.generate_btn)

        # Status label
        self.status_label = Label(
            text="",
            size_hint_y=None,
            height=28,
            color=(0.7, 0.7, 0.7, 1),
        )
        root.add_widget(self.status_label)

        # Output preview
        self.output = TextInput(
            text="",
            readonly=True,
            font_name="RobotoMono-Regular" if False else "Roboto",
            font_size=12,
            background_color=(0.96, 0.96, 0.96, 1),
        )
        scroll = ScrollView()
        scroll.add_widget(self.output)
        root.add_widget(scroll)

        self.add_widget(root)

    def _on_generate(self, _btn):
        try:
            m = int(self.m_spinner.text)
            n = int(self.n_spinner.text)
            variant = self.variant_spinner.text
            stretch = bool(self.stretch_checkbox.active)
            json_str = generate(m, n, variant, stretch)
        except Exception as exc:
            self.status_label.text = f"Error: {exc}"
            self.output.text = ""
            return

        label = f"{variant}{' stretch' if stretch else ''} {m}x{n}"
        self.status_label.text = f"Generated {label} ({len(json_str):,} chars)"
        # TextInput chokes on very large strings; show a head preview.
        max_chars = 8000
        self.output.text = (
            json_str if len(json_str) <= max_chars
            else json_str[:max_chars] + f"\n\n... [truncated, total {len(json_str):,} chars]"
        )
