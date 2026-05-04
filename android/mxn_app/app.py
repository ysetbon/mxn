"""Kivy application class for the MxN CAD Generator."""

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager

from mxn_app.screens.home import HomeScreen


class MxNApp(App):
    title = "MxN CAD Generator"

    def build(self):
        sm = ScreenManager()
        sm.add_widget(HomeScreen(name="home"))
        return sm
