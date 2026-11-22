"""Tiny GTK 4 app used by the integration tests (GTK 4 reports AT-SPI
screen positions as 0,0, so it exercises window-relative coordinates).

Run with a Python that has PyGObject + GTK 4 (gir1.2-gtk-4.0):
    python3 gtk4_demo.py "Title" [--rows N]
"""

import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk  # noqa: E402

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
    if "--rows" in sys.argv:
        # A long scrolled list: most rows start out of view.
        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for i in range(int(sys.argv[sys.argv.index("--rows") + 1])):
            listing.append(Gtk.Button(label=f"Row {i}"))
        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(150)
        scroller.set_vexpand(True)
        scroller.set_child(listing)
        box.append(scroller)
    window.set_child(box)
    window.present()


# NON_UNIQUE: tests may run two demo windows at once.
app = Gtk.Application(application_id="dev.lcu.Gtk4Demo", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.connect("activate", activate)
app.run([])
