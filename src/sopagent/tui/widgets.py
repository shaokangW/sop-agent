"""Widgets: Box / Text / ScrollBox (with stickyScroll state machine ported from OpenTUI).

ScrollBox.stickyScroll: when content grows, auto-follow to the sticky end (bottom)
only if the user hasn't manually scrolled away; if the user scrolled up, new content
won't yank them back; if they scroll back to the bottom, auto-follow re-engages.
This is a 1:1 port of OpenTUI's ScrollBox sticky-scroll state machine.
"""
from __future__ import annotations

from .buffer import CellGrid
from .renderable import Renderable


class Box(Renderable):
    def __init__(self) -> None:
        super().__init__()
        self.border = False
        self.title = ""
        self.bg = ""

    def render(self, grid: CellGrid) -> None:
        if self.bg:
            grid.fill_rect(self.screen_x, self.screen_y, self.width, self.height, " ", bg=self.bg)
        if self.border:
            # top/bottom + sides
            for x in range(self.width):
                grid.put(self.screen_x + x, self.screen_y, "─")
                if self.screen_y + self.height - 1 < grid.height:
                    grid.put(self.screen_x + x, self.screen_y + self.height - 1, "─")
            for y in range(self.height):
                grid.put(self.screen_x, self.screen_y + y, "│")
                if self.screen_x + self.width - 1 < grid.width:
                    grid.put(self.screen_x + self.width - 1, self.screen_y + y, "│")
        super().render(grid)


class Text(Renderable):
    def __init__(self, text: str = "", style: str = "") -> None:
        super().__init__()
        self._text = text
        self._style = style

    def set_text(self, text: str, style: str = "") -> None:
        self._text = text
        self._style = style

    def compute_intrinsic_size(self) -> tuple[int, int]:
        lines = self._text.split("\n")
        w = max((len(l) for l in lines), default=0)
        return max(self.min_width, w), max(self.min_height, len(lines))

    def render(self, grid: CellGrid) -> None:
        grid.put_text(self.screen_x, self.screen_y, self._text, fg=self._style, wrap=True)


class ScrollBox(Renderable):
    """A vertical scroll container with sticky-scroll (ported from OpenTUI)."""

    def __init__(self) -> None:
        super().__init__()
        self.flex_grow = 1.0
        # content = list of (style, text) lines
        self.lines: list[tuple[str, str]] = []
        self.cur: list[str] = []  # current streaming line
        self.scroll_top = 0
        # sticky state machine
        self.sticky_scroll = True
        self.sticky_start: str | None = "bottom"
        self._has_manual_scroll = False
        self._is_applying_sticky_scroll = False
        self._sticky_bottom = True

    # -- content -------------------------------------------------------
    def append_line(self, text: str, style: str = "") -> None:
        self.lines.append((style, text))
        self._recalculate()

    def stream_token(self, delta: str) -> None:
        self.cur.append(delta)
        self._recalculate()

    def flush_stream(self) -> None:
        if self.cur:
            self.lines.append(("", "".join(self.cur)))
            self.cur.clear()
            self._recalculate()

    # -- sticky state machine (ported from OpenTUI ScrollBox.ts) -------
    @property
    def scroll_height(self) -> int:
        return len(self.lines) + (1 if self.cur else 0)

    @property
    def max_scroll_top(self) -> int:
        return max(0, self.scroll_height - self.height)

    def _is_at_sticky_position(self) -> bool:
        if self.sticky_start == "bottom":
            return self.scroll_top >= self.max_scroll_top
        if self.sticky_start == "top":
            return self.scroll_top <= 0
        return True

    def _is_at_sticky_reengage_point(self) -> bool:
        return self._is_at_sticky_position()

    def _update_sticky_state(self) -> None:
        if not self.sticky_scroll:
            self._sync_manual_scroll_state()
            return
        if self.scroll_top <= 0:
            self._sticky_bottom = False
        elif self.scroll_top >= self.max_scroll_top:
            self._sticky_bottom = True
        self._sync_manual_scroll_state()

    def _sync_manual_scroll_state(self) -> None:
        if not self.sticky_scroll:
            self._has_manual_scroll = False
            return
        has_scrollable = self.max_scroll_top > 1
        if self._is_applying_sticky_scroll:
            if self._has_manual_scroll and has_scrollable and self._is_at_sticky_position():
                self._has_manual_scroll = False
            return
        self._has_manual_scroll = has_scrollable and not self._is_at_sticky_position()

    def _apply_sticky_start(self) -> None:
        self._is_applying_sticky_scroll = True
        try:
            if self.sticky_start == "bottom":
                self._sticky_bottom = True
                self.scroll_top = self.max_scroll_top
            elif self.sticky_start == "top":
                self._sticky_bottom = False
                self.scroll_top = 0
        finally:
            self._is_applying_sticky_scroll = False

    def _recalculate(self) -> None:
        """Called when content/size changes: re-apply sticky or re-engage."""
        if not self.sticky_scroll or not self.sticky_start:
            return
        if not self._has_manual_scroll:
            self._apply_sticky_start()
        elif self._is_at_sticky_reengage_point():
            self._has_manual_scroll = False
            self._apply_sticky_start()

    # -- user scroll actions ------------------------------------------
    def scroll_by(self, delta: int) -> None:
        self.scroll_top = max(0, min(self.max_scroll_top, self.scroll_top + delta))
        self._update_sticky_state()

    def scroll_to_bottom(self) -> None:
        self._has_manual_scroll = False
        self._apply_sticky_start()

    def page_up(self) -> None:
        self.scroll_by(-max(1, self.height - 1))

    def page_down(self) -> None:
        self.scroll_by(max(1, self.height - 1))

    # -- render -------------------------------------------------------
    def visible_lines(self, height: int) -> list[tuple[str, str]]:
        """Return the (style, text) lines visible in the current scroll window."""
        all_lines = list(self.lines)
        if self.cur:
            all_lines.append(("", "".join(self.cur)))
        top = self.scroll_top
        return all_lines[top : top + max(1, height)]

    def render(self, grid: CellGrid) -> None:
        visible = self.visible_lines(self.height)
        cy = self.screen_y
        for style, text in visible:
            if cy >= self.screen_y + self.height:
                break
            grid.put_text(self.screen_x, cy, text, fg=style, wrap=True)
            cy += 1
