"""Renderable tree + simplified flexbox layout (Python port of OpenTUI Renderable.ts).

Each Renderable has x/y/width/height (layout result) + screenX/screenY (absolute)
+ children. Layout is a simplified flexbox: column/row direction with flexGrow.
Not a full Yoga port, but covers the HSplit/VSplit + flexGrow=1 cases we need.
"""
from __future__ import annotations

from typing import Callable, List, Optional


class Renderable:
    def __init__(self) -> None:
        self.children: List["Renderable"] = []
        self.parent: Optional["Renderable"] = None
        # layout
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0
        self.screen_x = 0
        self.screen_y = 0
        # flex
        self.flex_direction = "column"  # "column" | "row"
        self.flex_grow = 0.0
        self.flex_shrink = 0.0
        self.min_width = 0
        self.min_height = 0
        # render hook
        self.visible = True

    def add(self, child: "Renderable") -> "Renderable":
        child.parent = self
        self.children.append(child)
        return child

    def compute_intrinsic_size(self) -> tuple[int, int]:
        """Override: return (width, height) the content wants if not flex-grown."""
        w = self.min_width
        h = self.min_height
        for c in self.children:
            cw, ch = c.compute_intrinsic_size()
            if self.flex_direction == "column":
                w = max(w, cw)
                h += ch
            else:
                w += cw
                h = max(h, ch)
        return w, h

    def layout(self, x: int, y: int, width: int, height: int) -> None:
        """Assign x/y/width/height to self and children (simplified flexbox)."""
        self.x, self.y, self.width, self.height = x, y, width, height
        self.screen_x = (self.parent.screen_x if self.parent else 0) + x
        self.screen_y = (self.parent.screen_y if self.parent else 0) + y
        # distribute remaining space by flexGrow
        intrinsic = [c.compute_intrinsic_size() for c in self.children]
        if self.flex_direction == "column":
            total_h = sum(ih for _, ih in intrinsic)
            extra = max(0, height - total_h)
            growers = [c for c in self.children if c.flex_grow > 0]
            per = (extra / len(growers)) if growers else 0
            cy = y
            for c, (iw, ih) in zip(self.children, intrinsic):
                child_h = int(ih + (per if c.flex_grow > 0 else 0))
                child_w = width
                c.layout(x, cy, child_w, child_h)
                cy += child_h
        else:  # row
            total_w = sum(iw for iw, _ in intrinsic)
            extra = max(0, width - total_w)
            growers = [c for c in self.children if c.flex_grow > 0]
            per = (extra / len(growers)) if growers else 0
            cx = x
            for c, (iw, ih) in zip(self.children, intrinsic):
                child_w = int(iw + (per if c.flex_grow > 0 else 0))
                child_h = height
                c.layout(cx, y, child_w, child_h)
                cx += child_w

    def render(self, grid) -> None:
        """Override to draw into grid. Base just renders children."""
        for c in self.children:
            if c.visible:
                c.render(grid)

    def collect(self, out: list) -> None:
        if self.visible:
            out.append(self)
        for c in self.children:
            c.collect(out)
