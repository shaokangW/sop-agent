"""App skeleton: render loop + terminal IO.

The terminal IO (raw mode / alternate screen / key parsing with IME + kitty)
is the largest remaining piece — it needs either prompt_toolkit's Output/Vt100Input
(abstraction over VT100/Win32, IME support) or a from-scratch Windows console
implementation. This module provides the render-loop logic that's testable
without a real terminal.
"""
from __future__ import annotations

from .buffer import CellGrid
from .renderable import Renderable


class App:
    def __init__(self, root: Renderable, width: int = 80, height: int = 24) -> None:
        self.root = root
        self.grid = CellGrid(width, height)
        self.prev = CellGrid(width, height)

    def resize(self, width: int, height: int) -> None:
        self.grid.resize(width, height)
        self.prev.resize(width, height)

    def render_frame(self) -> bytes:
        """Layout root into grid, return diff bytes vs previous frame."""
        self.grid.clear()
        self.root.layout(0, 0, self.grid.width, self.grid.height)
        self.root.render(self.grid)
        diff = self.grid.diff_to_bytes(self.prev)
        # current becomes previous for next frame
        self.prev, self.grid = self.grid, CellGrid(self.grid.width, self.grid.height)
        return diff
