"""Init sopagent TUI framework (OpenTUI port, simplified)."""
from .app import App
from .buffer import Cell, CellGrid
from .renderable import Renderable
from .widgets import Box, ScrollBox, Text

__all__ = ["App", "Cell", "CellGrid", "Renderable", "Box", "ScrollBox", "Text"]
