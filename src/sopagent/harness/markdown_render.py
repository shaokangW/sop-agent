"""Markdown -> prompt_toolkit FormattedText fragments.

Uses markdown_it_py (already installed via rich). Walks the token stream and
emits list[(style, text)] consumable by FormattedTextControl. Styles use
built-in prompt_toolkit attributes + ANSI named colors, so no Style registration
needed.
"""
from __future__ import annotations

from typing import List, Tuple

from markdown_it import MarkdownIt

_MD = MarkdownIt("commonmark", {"html": False})

Fragments = List[Tuple[str, str]]

_HEADING_STYLE = {
    1: "bold fg:ansimagenta",
    2: "bold fg:ansicyan",
    3: "bold fg:ansigreen",
    4: "bold fg:ansiblue",
    5: "bold fg:ansiblue",
    6: "bold fg:ansiblue",
}
_CODE_BLOCK_STYLE = "bg:#1e1e2e fg:ansiwhite"
_INLINE_CODE_STYLE = "fg:ansiyellow"
_BOLD_STYLE = "bold"
_ITALIC_STYLE = "italic"
_LINK_STYLE = "fg:ansiblue underline"
_BULLET_STYLE = "fg:ansicyan"
_HR_STYLE = "fg:ansiblack"


def _join(*styles: str) -> str:
    return " ".join(s for s in styles if s)


def _render_inline(children, cont: str = "") -> Fragments:
    out: Fragments = []
    stack = [""]

    def cur() -> str:
        return _join(*stack)

    for tok in children or []:
        t = tok.type
        if t == "text":
            out.append((cur(), tok.content))
        elif t in ("softbreak", "hardbreak"):
            out.append((cur(), "\n" + cont))
        elif t == "code_inline":
            out.append((_join(cur(), _INLINE_CODE_STYLE), tok.content))
        elif t == "strong_open":
            stack.append(_BOLD_STYLE)
        elif t == "strong_close":
            if len(stack) > 1:
                stack.pop()
        elif t == "em_open":
            stack.append(_ITALIC_STYLE)
        elif t == "em_close":
            if len(stack) > 1:
                stack.pop()
        elif t == "link_open":
            stack.append(_LINK_STYLE)
        elif t == "link_close":
            if len(stack) > 1:
                stack.pop()
        elif t == "image":
            out.append((_join(cur(), _ITALIC_STYLE), "[img]"))
        else:
            out.append((cur(), tok.content))
    return out


def markdown_to_fragments(md: str) -> Fragments:
    """markdown string -> prompt_toolkit FormattedTextControl list[(style, text)]."""
    tokens = _MD.parse(md or "")
    out: Fragments = []
    lists: list[dict] = []
    item: dict | None = None

    def emit(style: str, text: str) -> None:
        if text:
            out.append((style, text))

    def blank() -> None:
        if out and not out[-1][1].endswith("\n"):
            emit("", "\n")

    def flush_prefix() -> None:
        nonlocal item
        if item and item["first"]:
            emit("", item["indent"])
            emit(_BULLET_STYLE, item["bullet"])
            item["first"] = False

    def cont() -> str:
        return item["indent"] + " " * len(item["bullet"]) if item else ""

    i, n = 0, len(tokens)
    while i < n:
        tok = tokens[i]
        t = tok.type
        if t == "heading_open":
            lvl = int(tok.tag[1:])
            blank()
            out.append((_HEADING_STYLE.get(lvl, _HEADING_STYLE[6]), ""))
            out.extend(_render_inline(tokens[i + 1].children, cont()))
            emit("", "\n")
            i += 3
        elif t == "paragraph_open":
            blank()
            flush_prefix()
            out.extend(_render_inline(tokens[i + 1].children, cont()))
            emit("", "\n")
            i += 3
        elif t in ("bullet_list_open", "ordered_list_open"):
            lists.append({"ordered": t == "ordered_list_open", "idx": 1})
            i += 1
        elif t in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
            i += 1
        elif t == "list_item_open":
            depth = len(lists) - 1
            L = lists[-1]
            bullet = f'{L["idx"]}. ' if L["ordered"] else "- "
            item = {"indent": "  " * depth, "bullet": bullet, "first": True}
            i += 1
        elif t == "list_item_close":
            if lists:
                lists[-1]["idx"] += 1
            item = None
            i += 1
        elif t in ("fence", "code_block"):
            blank()
            for line in tok.content.rstrip("\n").split("\n"):
                emit(_CODE_BLOCK_STYLE, line + "\n")
            i += 1
        elif t == "hr":
            blank()
            emit(_HR_STYLE, "-" * 40 + "\n")
            i += 1
        elif t == "blockquote_open":
            blank()
            emit(_ITALIC_STYLE, "| ")
            i += 1
        elif t == "blockquote_close":
            emit("", "\n")
            i += 1
        else:
            i += 1
    return out
