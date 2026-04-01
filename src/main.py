"""Entry point for the MxN CAD Generator UI."""

import sys
from PyQt5.QtWidgets import QApplication
from mxn_cad_ui import MxNGeneratorDialog


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
