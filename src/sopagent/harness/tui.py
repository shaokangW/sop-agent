"""ChatTUI: prompt_toolkit IO (terminal/IME/input) + self-built ScrollBox (stickyScroll).

The output area is a FormattedTextControl whose text is the *visible window*
of a self-built ScrollBox (sopagent.tui.widgets.ScrollBox). The ScrollBox owns
the full content + scroll_top + the stickyScroll state machine (1:1 port of
OpenTUI): auto-follow at bottom, detach on user scroll-up, re-engage on scroll
back to bottom. prompt_toolkit no longer needs to scroll — it just renders the
window we give it.
"""
from __future__ import annotations

import threading
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.styles import Style

from ..tui.widgets import ScrollBox
from .events import ApprovalRequest, ToolExecutedEvent, TurnEvent
from .interactive import InteractiveSession
from .markdown_render import markdown_to_fragments

_STYLE = Style(
    [
        ("user", "fg:ansicyan bold"),
        ("assistant", "fg:ansiwhite"),
        ("tool", "fg:ansigreen"),
        ("err", "fg:ansired"),
        ("warn", "fg:ansiyellow bold"),
        ("dim", "fg:#808080"),
    ]
)


class SlashCompleter(Completer):
    COMMANDS = ["/help", "/clear", "/tools", "/exit"]

    def get_completions(self, document, complete_event):  # noqa: ANN001
        text = document.text_before_cursor
        if text.startswith("/"):
            for cmd in self.COMMANDS:
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text))


class ChatTUI:
    def __init__(self, session: InteractiveSession) -> None:
        self.session = session
        self.out = ScrollBox()
        self.out.sticky_start = "bottom"
        self.out.height = 1000  # initial; updated by _after_render to real viewport
        self.mode = "chat"
        self._approval_event = threading.Event()
        self._decision: str | None = None
        self.viewport_height = 10
        self._build()

    # -- output: visible window of the self-built ScrollBox --------------
    def _render(self):
        return self.out.visible_lines(self.viewport_height)

    def _refresh(self) -> None:
        try:
            self.app.call_from_thread(self.app.invalidate)
        except Exception:
            try:
                self.app.invalidate()
            except Exception:
                pass

    def _after_render(self, _app: object = None) -> None:
        try:
            info = self.output_window.render_info
            if info:
                wh = getattr(info, "window_height", 0) or 0
                if wh:
                    self.viewport_height = wh
                    self.out.height = wh  # ScrollBox needs real viewport height for stickyScroll
        except Exception:
            pass

    # -- build UI ----------------------------------------------------------
    def _build(self) -> None:
        self.output_control = FormattedTextControl(text=self._render)
        self.input_buffer = Buffer(
            multiline=False,
            history=FileHistory(".chat_history"),
            completer=SlashCompleter(),
            accept_handler=self._accept,
        )
        self.output_window = Window(self.output_control, wrap_lines=True)

        kb = KeyBindings()

        @kb.add("pageup")
        def _pu(event):  # noqa: ANN001
            self.out.page_up()
            self._refresh()

        @kb.add("pagedown")
        def _pd(event):  # noqa: ANN001
            self.out.page_down()
            self._refresh()

        @kb.add("end")
        def _end(event):  # noqa: ANN001
            self.out.scroll_to_bottom()
            self._refresh()

        self.app = Application(
            layout=Layout(
                HSplit(
                    [
                        self.output_window,
                        Window(height=1, char="─"),
                        Window(
                            BufferControl(buffer=self.input_buffer, key_bindings=kb),
                            height=3,
                            style="bg:#1a1a1a",
                        ),
                    ]
                )
            ),
            style=_STYLE,
            full_screen=True,
        )
        self.app.after_render.add_handler(self._after_render)
        self.out.append_line(
            "sop-agent chat — Enter 提交 / PageUp 上翻(脱粘) / End 回底 / /help /exit\n\n",
            "class:dim",
        )

    # -- input -------------------------------------------------------------
    def _accept(self, buff: Buffer) -> bool:
        text = buff.text
        if self.mode == "approval":
            self._decision = "approve" if text.strip().lower() in ("y", "yes") else "reject"
            self._approval_event.set()
            return False
        if not text.strip():
            return False
        if text.strip() in ("/exit", "/quit", ":q"):
            self.app.exit()
            return False
        if text.strip() == "/clear":
            self.session.reset()
            self.out.lines.clear()
            self.out.cur.clear()
            self.out.scroll_to_bottom()
            self._refresh()
            return False
        if text.strip() == "/tools":
            self.out.append_line("tools: " + ", ".join(self.session.tool_names()) + "\n", "class:dim")
            self._refresh()
            return False
        if text.strip() == "/help":
            self.out.append_line("/help /tools /clear /exit | PageUp End\n", "class:dim")
            self._refresh()
            return False
        self.out.append_line(f">>> {text}\n", "class:user")
        self._refresh()
        Path("tui_debug.log").write_text(
            f"lines={len(self.out.lines)} scroll_top={self.out.scroll_top} "
            f"viewport={self.viewport_height} visible={self.out.visible_lines(self.viewport_height)[:3]}",
            encoding="utf-8",
        )
        threading.Thread(target=self._run_turn, args=(text.strip(),), daemon=True).start()
        return False

    def _flush_markdown(self) -> None:
        if self.out.cur:
            text = "".join(self.out.cur)
            if not text.endswith("\n"):
                text += "\n"
            for style, frag in markdown_to_fragments(text):
                self.out.append_line(frag, style)
            self.out.cur.clear()
            self.out._recalculate()
            self._refresh()

    # -- agent turn (background thread) -----------------------------------
    def _run_turn(self, text: str) -> None:
        self.session.on_token = lambda _sid, d: (self.out.stream_token(d), self._refresh())
        gen = self.session.ask(text)
        try:
            ev = next(gen)
            while True:
                if isinstance(ev, ApprovalRequest):
                    self._flush_markdown()
                    self.out.append_line(f"\n[需审批] {ev.reason}\n输入 y 同意 / n 拒绝\n", "class:warn")
                    self._refresh()
                    self.mode = "approval"
                    self._approval_event.wait()
                    self._approval_event.clear()
                    decision = self._decision or "approve"
                    self.mode = "chat"
                    self.out.append_line(f"  [审批: {decision}]\n", "class:tool")
                    self._refresh()
                    ev = gen.send(decision)
                elif isinstance(ev, ToolExecutedEvent):
                    self._flush_markdown()
                    mark = "ok" if ev.ok else "FAIL"
                    self.out.append_line(f"  [tool] {ev.name} {mark}\n", "class:tool" if ev.ok else "class:err")
                    self._refresh()
                    ev = next(gen)
                elif isinstance(ev, TurnEvent):
                    self._flush_markdown()
                    ev = next(gen)
                else:
                    ev = next(gen)
        except StopIteration:
            pass
        except Exception:
            Path("tui_run.log").write_text(__import__("traceback").format_exc(), encoding="utf-8")
            self.out.append_line("\n[发生错误，详见 tui_run.log]\n", "class:err")
            self._refresh()
            return
        self._flush_markdown()

    # -- run ---------------------------------------------------------------
    def run(self) -> None:
        try:
            self.app.run()
        except Exception:
            Path("tui_err.log").write_text(__import__("traceback").format_exc(), encoding="utf-8")
            raise
