"""Unit tests for X11 driver helpers."""

from linux_computer_use.drivers.x11 import parse_window_query

GEOMETRY = "WINDOW=7\nX=20\nY=30\nWIDTH=800\nHEIGHT=600\nSCREEN=0\n"


def test_parse_full_query():
    assert parse_window_query(GEOMETRY + "Editor\n1907\n", 0) == (
        {"x": 20, "y": 30, "width": 800, "height": 600}, "Editor", 1907,
    )


def test_window_without_pid():
    # xdotool prints geometry and name, then fails on getwindowpid
    assert parse_window_query(GEOMETRY + "\n", 1) == (
        {"x": 20, "y": 30, "width": 800, "height": 600}, "", 0,
    )


def test_numeric_title_without_pid_is_not_taken_as_pid():
    assert parse_window_query(GEOMETRY + "2048\n", 1)[1:] == ("2048", 0)  # type: ignore[index]


def test_multiline_title():
    assert parse_window_query(GEOMETRY + "line one\nline two\n42\n", 0)[1:] == (  # type: ignore[index]
        "line one\nline two", 42,
    )


def test_missing_window():
    assert parse_window_query("", 1) is None
