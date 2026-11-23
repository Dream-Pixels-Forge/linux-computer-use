"""Tiny Qt 6 demo app used as an accessible target by the integration tests.

Run with a Python that has PySide6:
    python3 qt6_demo.py "Title" [--password] [--rows N]

Widgets mirror the GTK demos: a clicks label, an editable entry, a password
entry, a Count button and an optional long scrolled row list.
"""

import sys

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

title = sys.argv[1] if len(sys.argv) > 1 else "LCU Qt6 Demo"
app = QApplication(sys.argv)
window = QMainWindow()
window.setWindowTitle(title)
window.resize(360, 260)

widget = QWidget()
layout = QVBoxLayout(widget)

label = QLabel("Clicks: 0")
entry = QLineEdit()
entry.setAccessibleName("entry")
check = QCheckBox("Subscribe")
button = QPushButton("Count")
clicks = 0


def on_click() -> None:
    global clicks
    clicks += 1
    label.setText(f"Clicks: {clicks}")


button.clicked.connect(on_click)
for widget_ in (label, entry, check, button):
    layout.addWidget(widget_)

if "--password" in sys.argv:
    secret = QLineEdit()
    secret.setEchoMode(QLineEdit.EchoMode.Password)
    secret.setAccessibleName("password")
    layout.addWidget(secret)

if "--rows" in sys.argv:
    rows = int(sys.argv[sys.argv.index("--rows") + 1])
    listing = QVBoxLayout()
    for i in range(rows):
        row = QPushButton(f"Row {i}")
        row.clicked(lambda checked, i=i: label.setText(f"Picked {i}"))
        listing.addWidget(row)
    scroller = QScrollArea()
    scroller.setWidgetResizable(True)
    container = QWidget()
    container.setLayout(listing)
    scroller.setWidget(container)
    layout.addWidget(scroller)

window.setCentralWidget(widget)
window.show()
app.exec()
