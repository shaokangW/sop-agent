"""Tests for the self-built TUI framework core (OpenTUI port)."""
from __future__ import annotations

from sopagent.tui.app import App
from sopagent.tui.buffer import CellGrid
from sopagent.tui.renderable import Renderable
from sopagent.tui.widgets import Box, ScrollBox, Text


def test_cellgrid_put_text_and_diff():
    g = CellGrid(10, 3)
    g.put_text(0, 0, "hello", fg="fg:ansicyan")
    prev = CellGrid(10, 3)
    diff = g.diff_to_bytes(prev)
    assert b"hello" in diff
    assert b"\x1b[36m" in diff  # cyan SGR


def test_cellgrid_no_diff_when_same():
    g = CellGrid(5, 2)
    g.put_text(0, 0, "ab")
    prev = CellGrid(5, 2)
    prev.put_text(0, 0, "ab")
    assert g.diff_to_bytes(prev) == b"\x1b[0m"


def test_renderable_flex_column_layout():
    root = Renderable()
    root.flex_direction = "column"
    a = Renderable()
    a.min_height = 2
    b = Renderable()
    b.flex_grow = 1.0  # grows
    root.add(a)
    root.add(b)
    root.layout(0, 0, 10, 10)
    assert a.height == 2
    assert b.height == 8  # grew to fill


def test_scrollbox_sticky_auto_follow():
    """Content grows -> auto-scroll to bottom when user is at bottom."""
    sb = ScrollBox()
    sb.height = 3
    sb.sticky_start = "bottom"
    # add 5 lines -> scrollHeight 5, maxScrollTop 2, should stick to bottom
    for i in range(5):
        sb.append_line(f"line {i}")
    assert sb.scroll_top == 2  # at bottom
    assert not sb._has_manual_scroll


def test_scrollbox_sticky_user_scrolled_away():
    """User scrolls up -> new content does NOT yank back."""
    sb = ScrollBox()
    sb.height = 3
    for i in range(5):
        sb.append_line(f"line {i}")
    assert sb.scroll_top == 2  # at bottom
    # user scrolls up
    sb.scroll_by(-1)
    assert sb.scroll_top == 1
    assert sb._has_manual_scroll is True
    # new content arrives -> should NOT yank back to bottom
    sb.append_line("new line")
    assert sb.scroll_top == 1  # stayed where user scrolled to


def test_scrollbox_sticky_reengage_at_bottom():
    """User scrolls back to bottom -> auto-follow re-engages."""
    sb = ScrollBox()
    sb.height = 3
    for i in range(5):
        sb.append_line(f"line {i}")
    sb.scroll_by(-1)  # user scrolled up
    assert sb._has_manual_scroll is True
    # user scrolls back to bottom
    sb.scroll_to_bottom()
    assert sb.scroll_top == sb.max_scroll_top
    assert sb._has_manual_scroll is False


def test_app_render_frame():
    root = Box()
    root.add(Text("hi", "fg:ansicyan"))
    app = App(root, width=10, height=3)
    diff = app.render_frame()
    assert b"hi" in diff
    # second frame identical -> no diff
    app2 = App(root, width=10, height=3)
    app2.render_frame()
    diff2 = app2.render_frame()
    assert diff2 == b"\x1b[0m"


def test_scrollbox_render_visible_window():
    sb = ScrollBox()
    sb.height = 2
    for i in range(5):
        sb.append_line(f"line{i}")
    # scroll_top=3 -> visible lines 3,4
    sb.scroll_top = 3
    g = CellGrid(10, 2)
    sb.screen_x, sb.screen_y = 0, 0
    sb.width, sb.height = 10, 2
    sb.render(g)
    # line3 should be in row 0
    assert g.cells[0][0].char == "l"
    assert "3" in (g.cells[0][4].char if g.width > 4 else g.cells[0][0].char)
