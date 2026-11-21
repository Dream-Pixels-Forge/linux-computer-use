"""Tiny GTK 4 app used by the integration tests (GTK 4 reports AT-SPI
screen positions as 0,0, so it exercises window-relative coordinates).

Run with a Python that has PyGObject + GTK 4 (gir1.2-gtk-4.0):
    python3 gtk4_demo.py "Title"
"""

import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

TITLE = sys.argv[1] if len(sys.argv) > 1 else "LCU GTK4"


def activate(app: Gtk.Application) -> None:
    window = Gtk.ApplicationWindow(application=app, title=TITLE)
    window.set_default_size(360, 220)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    label = Gtk.Label(label="Clicks: 0")
    button = Gtk.Button(label="Count")
    clicks = [0]

    def on_click(_button: Gtk.Button) -> None:
        clicks[0] += 1
        label.set_text(f"Clicks: {clicks[0]}")

    button.connect("clicked", on_click)
    box.append(label)
    box.append(Gtk.Entry())
    box.append(button)
    window.set_child(box)
    window.present()


app = Gtk.Application(application_id="dev.lcu.Gtk4Demo")
app.connect("activate", activate)
app.run([])
