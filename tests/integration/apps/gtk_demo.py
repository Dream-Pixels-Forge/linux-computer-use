"""Tiny GTK 3 app used as an accessible target by the integration tests.

Run with a Python that has PyGObject + GTK 3 (e.g. /usr/bin/python3 with
python3-gi and gir1.2-gtk-3.0):  python3 gtk_demo.py "Title" [--password]
"""

import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

title = sys.argv[1] if len(sys.argv) > 1 else "LCU Demo"
window = Gtk.Window(title=title)
window.set_default_size(360, 260)
window.move(60, 60)

box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
label = Gtk.Label(label="Clicks: 0")
entry = Gtk.Entry()
check = Gtk.CheckButton(label="Subscribe")
button = Gtk.Button(label="Count")
clicks = 0


def on_click(_button: Gtk.Button) -> None:
    global clicks
    clicks += 1
    label.set_text(f"Clicks: {clicks}")


button.connect("clicked", on_click)
for widget in (label, entry, check, button):
    box.pack_start(widget, False, False, 0)
if "--password" in sys.argv:
    secret = Gtk.Entry()
    secret.set_visibility(False)
    box.pack_start(secret, False, False, 0)

window.add(box)
window.connect("destroy", Gtk.main_quit)
window.show_all()
Gtk.main()
