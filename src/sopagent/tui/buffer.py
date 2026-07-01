"""Cell-grid frame buffer + line-diff output (Python simplification of OpenTUI buffer.ts/renderer.ts).

A Cell is one terminal cell: char + fg + bg + attrs. CellGrid is a W×H grid.
render_diff compares against previous grid and emits VT100/ANSI bytes to move
the cursor and rewrite only changed cells (line-level diff, not full Zig cell
diff, but good enough).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class Cell:
    char: str = " "
    fg: str = ""  # prompt_toolkit-style style string, e.g. "bold fg:ansicyan"
    bg: str = ""


def _sgr(style: str) -> str:
    """Convert a style string to SGR escape (best-effort, 16 colors + bold/italic/underline)."""
    if not style:
        return "\x1b[0m"
    codes = []
    for part in style.split():
        if part == "bold":
            codes.append("1")
        elif part == "italic":
            codes.append("3")
        elif part == "underline":
            codes.append("4")
        elif part.startswith("fg:ansi"):
            name = part[7:]
            m = {"black": "30", "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36", "white": "37"}
            if name in m:
                codes.append(m[name])
        elif part.startswith("bg:ansi"):
            name = part[7:]
            m = {"black": "40", "red": "41", "green": "42", "yellow": "43", "blue": "44", "magenta": "45", "cyan": "46", "white": "47"}
            if name in m:
                codes.append(m[name])
    return ("\x1b[" + ";".join(codes) + "m") if codes else "\x1b[0m"


class CellGrid:
    def __init__(self, width: int, height: int) -> None:
        self.width = max(1, width)
        self.height = max(1, height)
        self.cells: List[List[Cell]] = [[Cell() for _ in range(self.width)] for _ in range(self.height)]

    def resize(self, width: int, height: int) -> None:
        width, height = max(1, width), max(1, height)
        if width == self.width and height == self.height:
            return
        new = [[Cell() for _ in range(width)] for _ in range(height)]
        for y in range(min(height, self.height)):
            for x in range(min(width, self.width)):
                new[y][x] = self.cells[y][x]
        self.cells, self.width, self.height = new, width, height

    def clear(self) -> None:
        self.cells = [[Cell() for _ in range(self.width)] for _ in range(self.height)]

    def put(self, x: int, y: int, char: str, fg: str = "", bg: str = "") -> None:
        if 0 <= x < self.width and 0 <= y < self.height and char:
            self.cells[y][x] = Cell(char, fg, bg)

    def put_text(self, x: int, y: int, text: str, fg: str = "", bg: str = "", wrap: bool = True) -> int:
        """Write text at (x,y) wrapping at width. Returns next y after the text."""
        cx, cy = x, y
        for ch in text:
            if ch == "\n":
                cx = x
                cy += 1
                continue
            if cx >= self.width and wrap:
                cx = x
                cy += 1
            if cy >= self.height:
                break
            if cx < self.width:
                self.cells[cy][cx] = Cell(ch, fg, bg)
            cx += 1
        return cy + 1

    def fill_rect(self, x: int, y: int, w: int, h: int, char: str = " ", fg: str = "", bg: str = "") -> None:
        for yy in range(y, min(y + h, self.height)):
            for xx in range(x, min(x + w, self.width)):
                self.cells[yy][xx] = Cell(char, fg, bg)

    def diff_to_bytes(self, prev: "CellGrid") -> bytes:
        """Emit ANSI bytes to turn prev into self (line-level diff)."""
        out = bytearray()
        last_style = ""
        for y in range(min(self.height, prev.height)):
            line_changed = False
            for x in range(min(self.width, prev.width)):
                a, b = self.cells[y][x], prev.cells[y][x]
                if a.char != b.char or a.fg != b.fg or a.bg != b.bg:
                    line_changed = True
                    break
            if not line_changed:
                continue
            out += f"\x1b[{y + 1};1H".encode()  # move cursor to line start
            for x in range(min(self.width, prev.width)):
                c = self.cells[y][x]
                style = (c.fg + " " + c.bg).strip()
                if style != last_style:
                    out += _sgr(style).encode()
                    last_style = style
                out += c.char.encode("utf-8")
        out += b"\x1b[0m"
        return bytes(out)
