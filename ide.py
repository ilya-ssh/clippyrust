from __future__ import annotations
import sys, subprocess, threading, queue, time, re, textwrap, requests
from pathlib import Path
from typing import List, Optional
import readchar
import pyperclip
from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich.layout import Layout
from rust_book import RustBookViewer
from pygments import lex
from pygments.lexers import RustLexer
from pygments.token import Token
from system_info import make_neofetch_text, system_info, get_session_random_message
from config import CLIPPY_ASCII, CLIPPY_VERSION, LLM_NAME, LLAMA_MODE, LLAMA_VPN_BASE_URL, LLAMA_LOCAL_URL
from llama import is_server_running, stream_response, LLAMA_SERVER_URL
from callbacks import StreamingCallbackHandler, StreamingEditHandler
from llama import classify_question
import json, os
import urllib.parse, html, json, requests
import platform
import subprocess
from pathlib import Path

console = Console()

class RustTUIIDE:
    def __init__(self, start_path: str):
        self.current_path = Path(start_path).resolve()
        self.files: List[Path] = []
        self.selected_index = 0
        self.code_content: List[str] = [""]
        self.run_output = ""
        self.current_file: Optional[Path] = None
        self.show_explorer = False
        self.show_run_output = False
        self.show_chat = False
        self.mode = 'edit'
        self.book_viewer = RustBookViewer(self.current_path / "book")
        self.cursor_x = 0
        self.cursor_y = 0
        self.view_top = 0
        self.explorer_view_top = 0
        self.update_file_list()
        self.run_output_queue = queue.Queue()
        self.run_thread = None
        self.run_lock = threading.Lock()
        self.input_queue = queue.Queue()
        self.token_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.input_thread = threading.Thread(target=self._input_listener, daemon=True)
        self.input_thread.start()
        self.chat_messages: List[str] = []
        self.chat_input: str = ""
        self.chat_lock = threading.Lock()
        self.save_as_mode = False
        self.save_as_input: str = ""
        self.prompt_message: str = ""
        self.current_llm_response = ""
        self.chat_view_top = 0
        self.chat_autoscroll = True
        self.server_is_ready = False
        self.server_proc = None
        #self.server_start_attempted = False
        #self.server_start_time = None #удалить
        self.undo_stack = []
        self.redo_stack = []
        self.selection_range = None
        self.create_file_mode = False
        self.create_file_input = ""
        self.chat_selected_code_block_index = None
        self.test_active = False
        self.test_awaiting_answer = False
        self.test_q_count = 0
        self.test_chapter_text = ""
        self.test_questions_asked: List[str] = []

    def push_undo_state(self):
        self.undo_stack.append((self.code_content.copy(), self.cursor_x, self.cursor_y))
        self.redo_stack.clear()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append((self.code_content.copy(), self.cursor_x, self.cursor_y))
            state = self.undo_stack.pop()
            self.code_content, self.cursor_x, self.cursor_y = state
            self.selection_range = None

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append((self.code_content.copy(), self.cursor_x, self.cursor_y))
            state = self.redo_stack.pop()
            self.code_content, self.cursor_x, self.cursor_y = state
            self.selection_range = None

    def delete_selection(self):
        if self.selection_range is None:
            return
        sel_start, sel_end, sel_line = self.selection_range
        if sel_line != self.cursor_y:
            return
        line = self.code_content[sel_line]
        new_line = line[:sel_start] + line[sel_end:]
        self.code_content[sel_line] = new_line
        self.cursor_x = sel_start
        self.selection_range = None

    def select_word(self):
        line = self.code_content[self.cursor_y]
        if not line:
            return
        pattern = re.compile(r'\w+')
        for match in pattern.finditer(line):
            if match.start() <= self.cursor_x < match.end():
                self.selection_range = (match.start(), match.end(), self.cursor_y)
                return
        self.selection_range = None

    def select_line(self):
        line = self.code_content[self.cursor_y]
        self.selection_range = (0, len(line), self.cursor_y)

    def kill_llama_server(self):
        if self.server_proc is not None:
            if self.server_proc.poll() is None:
                self.server_proc.terminate()
                try:
                    self.server_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.server_proc.kill()
            console.print("Llama died")

    def _input_listener(self): #REFACTOR
        try:
            while not self.stop_event.is_set():
                key = readchar.readkey()
                mapped_key = self._map_key(key)
                if mapped_key:
                    self.input_queue.put(mapped_key)
        except Exception as e:
            print(f"{e}")

    def _map_key(self, key: str) -> Optional[str]: #REFACTOR
        if key == '\x02':                       
            return 'ctrl_b'
        if key == '\x1b':
            return readchar.key.ESC
        if key in ('\r', '\n'):        #Enter/Return
            return readchar.key.ENTER
        if key in ('\x08', '\x7f'):    # Backspace/DEL
            return readchar.key.BACKSPACE
        if key == '\t':                #Tab
            return '\t'
        if key == '\x03':
            return 'ctrl_c'
        if key == '\x0e':
            return 'ctrl_n'
        if key == '\x13':
            return 'ctrl_s'
        elif key == '\x1f':
            return 'ctrl_shift_s'
        if key == '\x1a':
            return 'ctrl_z'
        if key == '\x19':
            return 'ctrl_y'
        if key == '\x17':
            return 'ctrl_w'
        if key == '\x0c':
            return 'ctrl_l'
        if key == readchar.key.F5:
            return 'f5'
        if key == '\x1b':
            seq = key
            while True:
                ch = readchar.readkey()
                seq += ch
                if ch.isalpha() or ch == '~':
                    break
            if seq == '\x1b[A':
                return readchar.key.UP
            if seq == '\x1b[B':
                return readchar.key.DOWN
            if seq == '\x1b[C':
                return readchar.key.RIGHT
            if seq == '\x1b[D':
                return readchar.key.LEFT
            return None
        if key == 'T':
            return 'shift_t'
        if key == 'Q':
            return 'shift_q'
        return key

    def update_file_list(self):
        try:
            entries = list(self.current_path.iterdir())
            entries.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
            parent_entry = Path("...")
            entries.insert(0, parent_entry)
            self.files = entries
            if self.selected_index >= len(self.files):
                self.selected_index = max(len(self.files) - 1, 0)
            if self.explorer_view_top > self.selected_index:
                self.explorer_view_top = self.selected_index
            elif self.explorer_view_top + self.visible_explorer_lines() <= self.selected_index:
                self.explorer_view_top = self.selected_index - self.visible_explorer_lines() + 1
        except PermissionError:
            console.print(f"[red]Permission denied: {self.current_path}[/red]")
            self.current_path = self.current_path.parent
            self.update_file_list()

    def visible_explorer_lines(self) -> int:
        total_height = console.size.height
        body_height = total_height - 6
        return body_height

    def render_file_picker(self) -> Table:
        table = Table(show_header=True, header_style="bold cyan", box=None)
        table.add_column("Name", style="dim", width=40)
        table.add_column("Type", style="dim", width=12)
        visible_files = self.files[self.explorer_view_top:self.explorer_view_top + self.visible_explorer_lines()]
        for idx, file in enumerate(visible_files, start=self.explorer_view_top):
            style = "on blue bold" if idx == self.selected_index else ""
            if file.name == "...":
                name = "..."
                file_type = "Parent Dir"
            else:
                name = file.name + "/" if file.is_dir() else file.name
                file_type = "Directory" if file.is_dir() else "File"
            table.add_row(Text(name, style=style), Text(file_type, style=style))
        return table

    def pygments_token_to_rich_style(self, token_type): #добавить персонализацию
        token_style_map = {Token.Keyword: "bold blue",Token.Keyword.Constant: "bold blue",Token.Keyword.Declaration: "bold blue",Token.Keyword.Namespace: "bold blue",Token.Name: "white",Token.Name.Builtin: "cyan",Token.Name.Function: "cyan",Token.Name.Class: "cyan",Token.Literal.String: "green",Token.Literal.Number: "magenta",Token.Operator: "yellow",Token.Punctuation: "yellow",Token.Comment: "#636363",Token.Error: "bold red",}
        while token_type not in token_style_map and token_type.parent:
            token_type = token_type.parent
        return token_style_map.get(token_type, "white")

    def render_code_view(self) -> Panel:
        if not self.current_file:
            nf_text = make_neofetch_text(CLIPPY_ASCII, LLM_NAME, CLIPPY_VERSION)
            nf_text.no_wrap = True
            return Panel(nf_text, title="CLIPPY", border_style="green")
        if not any(line.strip() for line in self.code_content):
            return Panel(Text("This file is empty. Start coding!", style="italic"), title="Code Editor",border_style="green")
        total_lines = len(self.code_content)
        code_view_height = self.visible_lines()
        code_text = Text()
        lexer = RustLexer()
        for i in range(min(code_view_height, total_lines - self.view_top)):
            line_num = self.view_top + i
            if line_num < total_lines:
                line = self.code_content[line_num]
                actual_line_num = line_num + 1
                ln_str = f"{actual_line_num:4} | "
                if line_num == self.cursor_y:
                    code_text.append(ln_str, style="bold magenta")
                else:
                    code_text.append(ln_str, style="dim")
                start_idx = len(code_text)
                tokens = lex(line, lexer)
                for token_type, token_value in tokens:
                    style = self.pygments_token_to_rich_style(token_type)
                    code_text.append(token_value, style=style)
                if self.selection_range is not None and self.selection_range[2] == line_num:
                    sel_start, sel_end, _ = self.selection_range
                    sel_start = max(0, min(sel_start, len(line)))
                    sel_end = max(0, min(sel_end, len(line)))
                    code_text.stylize("on grey", start_idx + sel_start, start_idx + sel_end)
                if line_num == self.cursor_y:
                    if self.cursor_x <= len(line):
                        char_index = start_idx + self.cursor_x
                        code_text.stylize("reverse", char_index, char_index + 1)
            else:
                code_text.append("     | \n", style="dim")
        code_text.no_wrap = True
        return Panel(code_text, title=str(self.current_file) if self.current_file else "No File", border_style="green")
    def render_run_output(self) -> Panel:
        if not self.show_run_output:
            return Panel(Text("Run Output Hidden", style="italic"), title="Run Output", border_style="yellow")
        if not self.run_output:
            return Panel(Text("Run Output", style="italic"), title="Run Output", border_style="yellow")
        max_lines = max(5, (console.size.height - 10) // 4)
        output_lines = self.run_output.splitlines()
        if len(output_lines) > max_lines:
            output_to_display = "\n".join(output_lines[-max_lines:])
        else:
            output_to_display = self.run_output
        return Panel(Text(output_to_display), title="Run Output", border_style="yellow")
    def visible_chat_lines(self):
        total_height = console.size.height - 10
        if self.show_run_output:
            run_output_height = max(5, total_height // 4) + 2
            total_height -= run_output_height
        if self.show_explorer:
            total_height = int(total_height * 0.75)
        chat_height = int(total_height)
        if chat_height < 1:
            chat_height = 1
        return chat_height
    def get_chat_lines(self, max_width=100):
        lines = []
        for msg in self.chat_messages:
            role_color = "white"
            if msg.startswith("You:"):
                role_color = "green"
            elif msg.startswith("Bot:"):
                role_color = "blue"
            split_msg = msg.split("\n")
            for line in split_msg:
                wrapped_lines = textwrap.wrap(line, width=max_width)
                for wrapped_line in wrapped_lines:
                    lines.append((wrapped_line, role_color))
        return lines
    def get_chat_code_blocks(self):
        full_lines = [line for line, style in self.get_chat_lines()]
        blocks = []
        in_block = False
        start = None
        for i, line in enumerate(full_lines):
            if "```" in line:
                if not in_block:
                    in_block = True
                    start = i
                else:
                    blocks.append((start, i))
                    in_block = False
        return blocks
    def _crate_llm_queries(self, user_msg: str) -> list[str]:
        prompt = (
            "You are an assistant turning a natural-language question into "
            "up to three crates.io search terms.\n"
            "Return **only** a JSON array of strings, no comments.\n\n"
            f"Q: {user_msg}\nA:"
        )
        try:
            js = json.loads(self._llm_stream(prompt, max_tokens=32))
            if isinstance(js, list) and all(isinstance(s, str) for s in js):
                return js[:3]
        except Exception:
            pass
        return [user_msg]
    def _query_crates(self, term: str, n: int = 5) -> list[dict]:
        url = ("https://crates.io/api/v1/crates?"
               f"q={urllib.parse.quote_plus(term)}&per_page={n}")
        try:
            data = requests.get(url, timeout=10).json().get("crates", [])
            return [{
                "name": c["id"],
                "desc": html.unescape(c.get("description", "")[:120]),
                "link": f"https://crates.io/crates/{c['id']}"
            } for c in data]
        except Exception as e:
            self.enqueue_run_output(f"[red]crates.io error: {e}[/]")
            return []
    def _handle_crate_search(self, user_msg: str):
        queries = self._crate_llm_queries(user_msg)
        merged, seen = [], set()
        for q in queries:
            for crate in self._query_crates(q, 5):
                if crate["name"] not in seen:
                    seen.add(crate["name"])
                    merged.append(crate)
        if not merged:
            with self.chat_lock:
                self.chat_messages.append("Bot: Sorry, nothing found.")
            return
        prompt = (
            "You are a Rust expert recommending crates.\n"
            f"Original question: {user_msg}\n\n"
            "Here are search results as JSON:\n"
            + json.dumps(merged, ensure_ascii=False, indent=2) +
            "\n\nWrite a helpful answer, mention each crate once."
        )
        self.generate_response(prompt)
    def _scaffold_prompt(self, user_req: str) -> str:
        examples = r"""
    USER: make empty cargo project called demo
    JSON: [
      {"op":"mkdir","path":"demo"},
      {"op":"mkdir","path":"demo/src"},
      {"op":"write","path":"demo/Cargo.toml",
       "content":"[package]\nname=\"demo\"\nversion=\"0.1.0\"\nedition=\"2021\""},
      {"op":"write","path":"demo/src/main.rs",
       "content":"fn main() {\n    println!(\"hello\");\n}"}
    ]

    USER: create project foo and put hello-world in main.rs
    JSON: [
      {"op":"mkdir","path":"foo"},
      {"op":"mkdir","path":"foo/src"},
      {"op":"write","path":"foo/Cargo.toml",
       "content":"[package]\nname=\"foo\"\nversion=\"0.1.0\"\nedition=\"2021\""},
      {"op":"write","path":"foo/src/main.rs",
       "content":"fn main() {\n    println!(\"Hello, world!\");\n}"}
    ]
    """
        return (
          "You are a build-script generator for a Rust IDE.\n"
          "Reply **only** with a JSON array (no markdown fences, no commentary).\n"
          "Allowed ops: mkdir | write | append.\n"
          "All paths are *relative*.\n"
          + examples +
          f"\nUSER: {user_req}\nJSON:"
        )
    def _safe_path(self, rel_path: str) -> Path | None:
        if ".." in rel_path.replace("\\", "/"):
            return None
        return (self.current_path / rel_path).resolve()

    def _apply_build_ops(self, ops: list[dict]):
        for i, op in enumerate(ops, 1):
            try:
                kind = op["op"]
                path = self._safe_path(op["path"])
                if path is None:
                    self.enqueue_run_output(f"[red]Blocked unsafe path: {op['path']}[/]")
                    continue

                if kind == "mkdir":
                    path.mkdir(parents=True, exist_ok=True)

                elif kind in ("write", "append"):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    mode = "a" if kind == "append" else "w"
                    with path.open(mode, encoding="utf-8") as f:
                        f.write(op.get("content", ""))
                else:
                    self.enqueue_run_output(f"[yellow]Unknown op {kind!r} (skipped)[/]")
            except Exception as e:
                self.enqueue_run_output(f"[red]op #{i} failed: {e}[/]")

        self.update_file_list()
        self.enqueue_run_output("[green]scaffold complete[/]")
    def _handle_scaffold(self, user_message: str):
        prompt = self._scaffold_prompt(user_message)
        try:
            json_text = self._llm_stream(prompt, max_tokens=9000)
            ops = json.loads(json_text)
            if not isinstance(ops, list):
                raise ValueError("JSON root must be an array")
        except Exception as e:
            self.enqueue_run_output(f"[red]LLM/JSON error: {e}[/]")
            return
        self._apply_build_ops(ops)

    def render_chat_view(self) -> Panel:
        full_lines = self.get_chat_lines()
        visible_count = self.visible_chat_lines()
        max_top = max(0, len(full_lines) - visible_count)
        if self.chat_view_top > max_top:
            self.chat_view_top = max_top
        visible_lines = full_lines[self.chat_view_top:self.chat_view_top + visible_count]
        blocks = self.get_chat_code_blocks()
        selected_block = None
        if self.chat_selected_code_block_index is not None and blocks:
            selected_block = blocks[self.chat_selected_code_block_index]
        chat_display = Text()
        for i, (line_text, style_color) in enumerate(visible_lines, start=self.chat_view_top):
            if selected_block and selected_block[0] < i <= selected_block[1]:
                new_style = style_color + " reverse"
            else:
                new_style = style_color
            chat_display.append(line_text + "\n", style=new_style)
        input_prompt = Text(">> " + self.chat_input, style="bold green")
        chat_display.append("\n")
        chat_display.append(input_prompt)
        return Panel(chat_display, title="Chat", border_style="magenta")

    def render_layout(self) -> Group:
        if self.mode == "teacher":
            body_h = console.size.height - 6
            if self.show_chat:
                layout = Layout()
                layout.split_row(Layout(name="chapter", ratio=2),Layout(name="chat", ratio=1),)
                layout["chapter"].update(self.book_viewer.render(body_h))
                layout["chat"].update(self.render_chat_view())
                return Group(layout)
            else:
                return Group(self.book_viewer.render(body_h))
        if self.mode == "test":
            # full-screen chat
            return Group(self.render_chat_view())
        if self.create_file_mode:
            popup = Align.center(
                Panel(Text(f"New File - Enter file name: {self.create_file_input}", style="bold yellow"),title="New File", border_style="cyan"),vertical="middle")
            return Group(popup)
        if self.save_as_mode:
            popup = Align.center(
                Panel(Text(f"Save As - Enter file name: {self.save_as_input}", style="bold yellow"),title="Save As", border_style="cyan"),vertical="middle")
            return Group(popup)
        layout = Layout()
        layout.split_column(Layout(name="header", size=3),Layout(name="body", ratio=1),Layout(name="footer", size=3),)
        header = Align.center("📎 [bold magenta]Clippy[/bold magenta] - Rust TUI IDE")
        layout["header"].update(header)
        if self.show_explorer:
            layout["body"].split_row(Layout(name="file_picker", ratio=1),Layout(name="main_pane", ratio=3),)
        else:
            layout["body"].split_row(Layout(name="main_pane", ratio=3),)
        if self.show_explorer:
            file_picker = self.render_file_picker()
            layout["body"]["file_picker"].update(Panel(file_picker, title=str(self.current_path), border_style="blue"))
        layout["body"]["main_pane"].split_column(Layout(name="editor_and_chat", ratio=3),Layout(name="run_output", ratio=1) if self.show_run_output else Layout(name="run_output", visible=False),)
        if self.show_chat:
            layout["body"]["main_pane"]["editor_and_chat"].split_row(Layout(name="code_view", ratio=1),Layout(name="chat_panel", ratio=1),)
            code_view = self.render_code_view()
            layout["body"]["editor_and_chat"]["code_view"].update(code_view)
            chat_view = self.render_chat_view()
            layout["body"]["editor_and_chat"]["chat_panel"].update(chat_view)
        else:
            layout["body"]["editor_and_chat"].split_row(
                Layout(name="code_view", ratio=1),
            )
            code_view = self.render_code_view()
            layout["body"]["editor_and_chat"]["code_view"].update(code_view)
        if self.show_run_output:
            run_output = self.render_run_output()
            layout["body"]["main_pane"]["run_output"].update(run_output)
        cursor_info = f"Cursor: ({self.cursor_x + 1}, {self.cursor_y + 1})"
        run_output_state = "Visible" if self.show_run_output else "Hidden"
        chat_state = "Visible" if self.show_chat else "Hidden"
        footer_text = Text(f"↑/↓/←/→: Navigate | Enter: Open/Send | Backspace: Up/Delete | ~: Toggle Explorer | Ctrl+N: New File | F5: Run | "
        f"SHIFT+T: Toggle Run Output | Ctrl+S: Save | Ctrl+Shift+S: Save As | Tab: Toggle Chat | Shift+Q: Quit | "
        f"Ctrl+Z: Undo | Ctrl+Y: Redo | Ctrl+W: Select Word | Ctrl+L: Select Line | Ctrl+C: Copy Code | "
        f"q/a: Next/Prev Code Block | c: Copy Chat Code Block | {cursor_info} | Run Output: {run_output_state} | Chat: {chat_state}",style="dim")
        layout["footer"].update(Align.center(footer_text))
        return Group(layout)
    def visible_lines(self) -> int:
        total_height = console.size.height
        body_height = total_height - 8
        if self.show_run_output:
            run_output_height = max(5, body_height // 4) + 1
            code_view_height = body_height - run_output_height
        else:
            code_view_height = body_height
        return code_view_height
    def open_selected_file(self):
        if not self.files:
            return
        selected = self.files[self.selected_index]
        if selected.name == "...":
            self.go_up_directory()
            return
        if selected.is_dir():
            self.current_path = selected.resolve()
            self.update_file_list()
            self.mode = 'explorer'
        elif selected.is_file() and selected.suffix == ".rs":
            self.current_file = selected
            try:
                with selected.open("r", encoding="utf-8") as f:
                    self.code_content = f.read().split('\n')
                self.mode = 'edit'
                self.run_output = ""
                self.cursor_x = 0
                self.cursor_y = 0
                self.view_top = 0
            except Exception as e:
                console.print(f"Ошибка: {e}")
                self.code_content = [""]
                self.current_file = None
    def go_up_directory(self):
        if self.current_path.parent != self.current_path:
            self.current_path = self.current_path.parent
            self.update_file_list()
            self.mode = 'explorer'
    def run_rust_project(self):
        if not self.current_file:
            self.enqueue_run_output("No Rust file selected to run.")
            return
        project_dir = self.current_file.parent
        cargo_file = project_dir / "Cargo.toml"
        if not cargo_file.exists():
            self.enqueue_run_output("Not a Cargo project (Cargo.toml not found).")
            return
        if self.run_thread and self.run_thread.is_alive():
            self.enqueue_run_output("A run process is already in progress.")
            return
        self.run_thread = threading.Thread(target=self._run_cargo, args=(project_dir,), daemon=True)
        self.run_thread.start()

    def run_rust_file(self):
        if not self.current_file or self.current_file.suffix != ".rs":
            self.enqueue_run_output("Select a .rs file first.")
            return
        exe_path = self.current_file.with_suffix(".exe")
        compile_cmd = ["rustc", str(self.current_file), "-o", str(exe_path)]

        self.enqueue_run_output("[cyan]Compiling…[/cyan]")
        proc = subprocess.run(compile_cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            self.enqueue_run_output(f"[red]Compile error:[/red]\n{proc.stderr}")
            return
        if platform.system() == "Windows":
            quoted = f'"{exe_path}"'
            try:
                subprocess.Popen(f'start "" cmd /k {quoted}',cwd=exe_path.parent,shell=True,creationflags=subprocess.CREATE_NEW_CONSOLE)
                self.enqueue_run_output(f"[green]launched {exe_path.name} in a new terminal[/]")
            except Exception as e:
                self.enqueue_run_output(f"[red]Unable to spawn terminal: {e}[/]")
        else:
            self.enqueue_run_output("[yellow]Detached console only supported on Windows;running inline instead…[/]")
            super(RustTUIIDE, self).run_rust_file()

    def _run_cargo(self, project_dir: Path):
        try:
            self.enqueue_run_output("[Running 'cargo run'...]")
            process = subprocess.Popen(["cargo", "run"],cwd=project_dir,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,)
            while True:
                stdout_line = process.stdout.readline()
                stderr_line = process.stderr.readline()
                if stdout_line:
                    self.enqueue_run_output(stdout_line.rstrip())
                if stderr_line:
                    self.enqueue_run_output(stderr_line.rstrip())
                if not stdout_line and not stderr_line and process.poll() is not None:
                    break
            if process.returncode == 0:
                self.enqueue_run_output("[bold green]Cargo run completed successfully.[/bold green]")
            else:
                self.enqueue_run_output(f"[bold red]Cargo run failed with exit code {process.returncode}.[/bold red]")
        except subprocess.TimeoutExpired:
            self.enqueue_run_output("Cargo run timed out.")
        except Exception as e:
            self.enqueue_run_output(f"{e}")
    def enqueue_run_output(self, message: str):
        self.run_output_queue.put(message)
    def toggle_explorer(self):
        self.show_explorer = not self.show_explorer
        if self.show_explorer:
            self.mode = 'explorer'
        else:
            self.mode = 'edit'
    def toggle_run_output(self):
        self.show_run_output = not self.show_run_output
    def toggle_chat(self):
        self.show_chat = not self.show_chat
    def handle_chat_input(self, key: str):
        if key in ['q', 'a', 'c'] and self.chat_input == "":
            if key == 'q':
                blocks = self.get_chat_code_blocks()
                if blocks:
                    if self.chat_selected_code_block_index is None:
                        self.chat_selected_code_block_index = 0
                    else:
                        self.chat_selected_code_block_index = (self.chat_selected_code_block_index + 1) % len(blocks)
                    block_start = blocks[self.chat_selected_code_block_index][0]
                    self.chat_view_top = block_start
            elif key == 'a':
                blocks = self.get_chat_code_blocks()
                if blocks:
                    if self.chat_selected_code_block_index is None:
                        self.chat_selected_code_block_index = 0
                    else:
                        self.chat_selected_code_block_index = (self.chat_selected_code_block_index - 1) % len(blocks)
                    block_start = blocks[self.chat_selected_code_block_index][0]
                    self.chat_view_top = block_start
            elif key == 'c':
                blocks = self.get_chat_code_blocks()
                if blocks and self.chat_selected_code_block_index is not None:
                    start, end = blocks[self.chat_selected_code_block_index]
                    full_lines = [line for line, style in self.get_chat_lines()]
                    if end - start > 1:
                        code_content = "\n".join(full_lines[start + 1:end])
                    else:
                        code_content = ""
                    pyperclip.copy(code_content)
                    self.enqueue_run_output("Chat code block copied to clipboard.")
                    self.chat_selected_code_block_index = None
            return
        if key == readchar.key.UP:
            self.chat_autoscroll = False
            self.chat_view_top = max(0, self.chat_view_top - 1)
        elif key == readchar.key.DOWN:
            self.chat_autoscroll = False
            self.chat_view_top = min(max(0, len(self.get_chat_lines()) - self.visible_chat_lines()),
                                     self.chat_view_top + 1)
        elif key == readchar.key.ENTER:
            with self.chat_lock:
                if self.chat_input.strip():
                    user_message = self.chat_input.strip()
                    self.chat_messages.append(f"You: {user_message}")
                    chapter_ctx = ""
                    if self.mode in ("teacher", "test") and self.book_viewer.markdown_lines:
                        chapter_ctx = ("\n### Chapter context (for reference only do NOT quote verbatim)\n"+ "\n".join(self.book_viewer.markdown_lines[:800])+ "\n")
                    classification = classify_question(user_message)
                    self.enqueue_run_output(classification + user_message)
                    code_ctx = "\n".join(self.code_content)
                    if classification == "scaffold":threading.Thread(target=self._handle_scaffold,args=(user_message,),daemon=True).start()
                        self.chat_input = ""
                        return
                    elif classification == "crate_search":
                        threading.Thread(
                            target=self._handle_crate_search,
                            args=(user_message,),
                            daemon=True
                        ).start()
                        self.chat_input = ""
                        return
                    elif classification == "analysis":
                        prompt = ("You are a Rust expert. Analyse the user’s code and question.\n"
                        f"{chapter_ctx}"
                        "### User code\n" + code_ctx + "\n ### Question\n{user_message}\nA:")
                    elif classification == "edit":
                        edit_prompt = (
                            "You are a Rust refactoring assistant.\n Apply the user's requested change *only* to the code below.\n Output *exactly* the new source inside ```rust …``` fences.\n\n"
                            f"{chapter_ctx}"
                            "```rust\n" + code_ctx + "\n```\n\n"
                            "### Change requested:\n" + user_message + "\n```")
                        handler = StreamingEditHandler(self)
                        def _do_stream_edit():
                            self.enqueue_run_output("[bold blue]Applying edit…[/bold blue]")
                            stream_response(edit_prompt, callback_handler=handler)
                            handler.on_llm_end()           # 
                        threading.Thread(target=_do_stream_edit, daemon=True).start()
                        self.chat_input = ""
                        return       
                    else:
                        prompt = (
                            "You are a Rust expert answering a student.\n"
                            f"{chapter_ctx}"
                            f"Q: {user_message}\nA:")
                    threading.Thread(
                        target=self.generate_response,
                        args=(prompt,),
                        daemon=True
                    ).start()
                    self.chat_input = ""
            self.chat_autoscroll = True
        elif key == readchar.key.BACKSPACE:
            self.chat_input = self.chat_input[:-1]
        elif len(key) == 1 and key.isprintable():
            self.chat_input += key
            self.chat_autoscroll = True

    def _llm_stream(self, prompt: str, max_tokens: int = 9000) -> str:
        class _Tmp(StreamingCallbackHandler):
            def __init__(self, ide):
                super().__init__(ide)  
                self.collected: list[str] = []
            def on_llm_new_token(self, token: str):
                self.collected.append(token)
                super().on_llm_new_token(token)
        handler = _Tmp(self)
        stream_response(prompt,callback_handler=handler, max_tokens=max_tokens,)
        return "".join(handler.collected).strip()
    def _ask_next_test_question(self):
        banned = "\n".join(f"- {q}" for q in self.test_questions_asked) or "- (none yet)"
        prompt = (
            f"You are an examiner. Using ONLY information in the chapter below, write ONE short quiz question **in English** that has NOT been asked before. Do NOT repeat any question in the banned list.\n\n ### Chapter\n{self.test_chapter_text}\n\n ### Banned questions\n{banned}\n\n Return ONLY the question text, no extra commentary.")
        with self.chat_lock:
            self.chat_messages.append("Bot: ")

        question = self._llm_stream(prompt, max_tokens=64)
        self.test_questions_asked.append(question)
        self.test_awaiting_answer = True

    def _evaluate_answer(self, answer: str):
        prompt = (
            "You are grading a Rust textbook quiz.\n Reply with exactly this format:\n GRADE: Correct | Incorrect\n FEEDBACK: <max 30 words>\n\n"
            f"### Chapter\n{self.test_chapter_text}\n\n"
            f"### Question\n{self.test_questions_asked[-1]}\n"
            f"### Student answer\n{answer}\n")

        with self.chat_lock:
            self.chat_messages.append("Bot: ")

        self._llm_stream(prompt, max_tokens=72)   # appends tokens live
        self.test_q_count += 1

        if self.test_q_count < 8:
            self._ask_next_test_question()
        else:
            with self.chat_lock:
                self.chat_messages.append("\nBot:Test finished! Press Esc to return.")
            self.test_awaiting_answer = False

    def _start_test(self):
        self.mode = "test"
        self.show_chat = True
        self.chat_messages.clear()
        self.chat_input = ""
        self.test_active = True
        self.test_q_count = 0
        self.test_questions_asked.clear()
        self.test_chapter_text = "\n".join(self.book_viewer.markdown_lines)
        self._ask_next_test_question()

    def handle_input(self, key: str):
        if key == 'ctrl_b':
            if self.mode == "teacher":
                self.mode = "edit"
            else:
                self.mode = "teacher"
            return
        if key == '\t':
            if self.mode != "test":
                self.toggle_chat()
            return
        if self.mode == "teacher":
            # leave teacher mode
            if key == readchar.key.ESC:
                self.mode = "edit"
                return
            if self.show_chat and key not in (
                readchar.key.UP, readchar.key.DOWN,
                readchar.key.PAGE_UP, readchar.key.PAGE_DOWN,
                readchar.key.LEFT, readchar.key.RIGHT,
                readchar.key.ESC,
            ):
                self.handle_chat_input(key)
                return
            if self.book_viewer.open_chapter is None:
                if key == readchar.key.UP:
                    self.book_viewer.move_selection(-1)
                elif key == readchar.key.DOWN:
                    self.book_viewer.move_selection(+1)
                elif key in (readchar.key.ENTER, readchar.key.RIGHT):
                    self.book_viewer.open_selected()
                return
            if key == readchar.key.UP:
                self.book_viewer.row_scroll = max(0, self.book_viewer.row_scroll - 1)
            elif key == readchar.key.DOWN:
                self.book_viewer.row_scroll += 1
            elif key == readchar.key.PAGE_UP:
                self.book_viewer.scroll = max(0, self.book_viewer.scroll - 20)
            elif key == readchar.key.PAGE_DOWN:
                self.book_viewer.scroll += 20
            elif key == readchar.key.ESC:
                self.book_viewer.open_chapter = None
            elif key.lower() == 'r' and self.book_viewer.is_at_end(console.size.height - 8):
                self.book_viewer.scroll = 0         
            elif key.lower() == 't' and self.book_viewer.is_at_end(console.size.height - 8):
                self._start_test()                
            return
        if self.mode == "test":
            if key == readchar.key.ESC:
                self.mode = "teacher"
                self.test_active = False
                return
            if self.test_awaiting_answer:
                if key == readchar.key.BACKSPACE:
                    self.chat_input = self.chat_input[:-1]
                elif key == readchar.key.ENTER:
                    ans = self.chat_input.strip()
                    if ans:
                        with self.chat_lock:
                            self.chat_messages.append(f"You: {ans}")
                        self.chat_input = ""
                        self.test_awaiting_answer = False
                        threading.Thread(target=self._evaluate_answer, args=(ans,), daemon=True).start()
                elif len(key) == 1 and key.isprintable():
                    self.chat_input += key
            return
        if self.create_file_mode:
            if key == readchar.key.ENTER:
                filename = self.create_file_input.strip()
                self.create_new_file(filename)
                self.create_file_mode = False
                self.create_file_input = ""
            elif key == readchar.key.BACKSPACE:
                self.create_file_input = self.create_file_input[:-1]
            elif len(key) == 1 and key.isprintable():
                self.create_file_input += key
            return
        if self.save_as_mode:
            if key == readchar.key.ENTER:
                filename = self.save_as_input.strip()
                if filename:
                    self.save_file_as(filename)
                self.save_as_mode = False
                self.save_as_input = ""
                self.prompt_message = ""
            elif key == readchar.key.BACKSPACE:
                self.save_as_input = self.save_as_input[:-1]
            elif len(key) == 1 and key.isprintable():
                self.save_as_input += key
            return
        if key == 'shift_q':
            self.stop_event.set()
            sys.exit(0)
        if key == 'shift_t':
            self.toggle_run_output()
            return
        if key == '\t':
            self.toggle_chat()
            return
        if key == 'ctrl_s':
            self.save_file()
            return
        if key == 'ctrl_shift_s':
            self.save_as_mode = True
            self.save_as_input = ""
            self.prompt_message = "Save As - Enter new file name:"
            return
        if key == 'ctrl_c' and self.mode == 'edit':
            self.copy_code_to_clipboard()
            return
        if self.show_chat:
            self.handle_chat_input(key)
            return
        if self.mode == 'explorer':
            if key == readchar.key.UP:
                if self.selected_index > 0:
                    self.selected_index -= 1
                    if self.selected_index < self.explorer_view_top:
                        self.explorer_view_top -= 1
            elif key == readchar.key.DOWN:
                if self.selected_index < len(self.files) - 1:
                    self.selected_index += 1
                    if self.selected_index >= self.explorer_view_top + self.visible_explorer_lines():
                        self.explorer_view_top += 1
            elif key == readchar.key.PAGE_UP:
                self.explorer_view_top = max(self.explorer_view_top - self.visible_explorer_lines(), 0)
                self.selected_index = max(self.selected_index - self.visible_explorer_lines(), 0)
            elif key == readchar.key.PAGE_DOWN:
                max_view_top = max(len(self.files) - self.visible_explorer_lines(), 0)
                self.explorer_view_top = min(self.explorer_view_top + self.visible_explorer_lines(), max_view_top)
                self.selected_index = min(self.selected_index + self.visible_explorer_lines(), len(self.files) - 1)
            elif key == readchar.key.ENTER:
                self.open_selected_file()
            elif key == readchar.key.BACKSPACE:
                self.go_up_directory()
            elif key == '~':
                self.toggle_explorer()
            elif key == 'ctrl_n':
                self.create_file_mode = True
                self.create_file_input = ""
            elif key == 'f5':
                self.run_rust_file()
        elif self.mode == 'edit':
            if key == 'ctrl_z':
                self.undo()
                return
            elif key == 'ctrl_y':
                self.redo()
                return
            elif key == 'ctrl_w':
                self.select_word()
                return
            elif key == 'ctrl_l':
                self.select_line()
                return
            if key in (readchar.key.BACKSPACE,) or (len(key) == 1 and key.isprintable()):
                if self.selection_range is not None:
                    self.push_undo_state()
                    self.delete_selection()
            if key in (readchar.key.UP, readchar.key.DOWN, readchar.key.LEFT, readchar.key.RIGHT):
                self.selection_range = None
            if key == readchar.key.UP:
                if self.cursor_y > 0:
                    self.cursor_y -= 1
                    self.cursor_x = min(self.cursor_x, len(self.code_content[self.cursor_y]))
            elif key == readchar.key.DOWN:
                if self.cursor_y < len(self.code_content) - 1:
                    self.cursor_y += 1
                    self.cursor_x = min(self.cursor_x, len(self.code_content[self.cursor_y]))
            elif key == readchar.key.LEFT:
                if self.cursor_x > 0:
                    self.cursor_x -= 1
                elif self.cursor_y > 0:
                    self.cursor_y -= 1
                    self.cursor_x = len(self.code_content[self.cursor_y])
            elif key == readchar.key.RIGHT:
                if self.cursor_x < len(self.code_content[self.cursor_y]):
                    self.cursor_x += 1
                elif self.cursor_y < len(self.code_content) - 1:
                    self.cursor_y += 1
                    self.cursor_x = 0
            elif key == readchar.key.ENTER:
                self.push_undo_state()
                current_line = self.code_content[self.cursor_y]
                new_line = current_line[self.cursor_x:]
                self.code_content[self.cursor_y] = current_line[:self.cursor_x]
                self.code_content.insert(self.cursor_y + 1, new_line)
                self.cursor_y += 1
                self.cursor_x = 0
            elif key == readchar.key.BACKSPACE:
                self.push_undo_state()
                if self.selection_range is not None:
                    self.delete_selection()
                elif self.cursor_x > 0:
                    line = self.code_content[self.cursor_y]
                    self.code_content[self.cursor_y] = line[:self.cursor_x - 1] + line[self.cursor_x:]
                    self.cursor_x -= 1
                elif self.cursor_y > 0:
                    prev_line = self.code_content[self.cursor_y - 1]
                    current_line = self.code_content[self.cursor_y]
                    self.cursor_x = len(prev_line)
                    self.code_content[self.cursor_y - 1] = prev_line + current_line
                    del self.code_content[self.cursor_y]
                    self.cursor_y -= 1
            elif key == '~':
                self.toggle_explorer()
            elif key == 'f5':
                self.run_rust_file()
            elif len(key) == 1 and key.isprintable():
                self.push_undo_state()
                line = self.code_content[self.cursor_y]
                self.code_content[self.cursor_y] = line[:self.cursor_x] + key + line[self.cursor_x:]
                self.cursor_x += 1
            self.adjust_view()

    def adjust_view(self):
        code_view_height = self.visible_lines()
        center_offset = code_view_height // 2
        total_lines = len(self.code_content)
        if self.cursor_y < center_offset:
            self.view_top = 0
        elif self.cursor_y >= total_lines - center_offset:
            self.view_top = max(0, total_lines - code_view_height)
        else:
            self.view_top = self.cursor_y - center_offset

    def process_run_output(self):
        while not self.run_output_queue.empty():
            message = self.run_output_queue.get()
            with self.run_lock:
                if self.run_output:
                    self.run_output += "\n" + message
                else:
                    self.run_output = message
    def check_server_readiness(self):
        if not self.server_is_ready and is_server_running():
            self.server_is_ready = True
            with self.chat_lock:
                self.chat_messages.append("Connected to LLaMA server.")

    def save_file(self):
        if not self.current_file:
            self.enqueue_run_output("No file is currently open to save.")
            return
        try:
            with self.current_file.open("w", encoding="utf-8") as f:
                f.write('\n'.join(self.code_content))
            self.enqueue_run_output(f"[bold green]Saved {self.current_file}[/bold green]")
        except Exception as e:
            self.enqueue_run_output(f"{e}")
    def save_file_as(self, filename: str):
        if not filename:
            self.enqueue_run_output("Save As canceled: No file name provided.")
            return
        new_file = self.current_path / filename
        if new_file.exists():
            self.enqueue_run_output(f"[bold red]File '{filename}' already exists.[/bold red]")
            return
        try:
            with new_file.open("w", encoding="utf-8") as f:
                f.write('\n'.join(self.code_content))
            self.current_file = new_file
            self.enqueue_run_output(f"[bold green]Saved as {new_file}[/bold green]")
        except Exception as e:
            self.enqueue_run_output(f"Error saving file as '{filename}': {e}")
    def create_new_file(self, filename: str):
        if not filename:
            self.enqueue_run_output("New file creation cancelled: No file name provided.")
            return
        new_file = self.current_path / filename
        if new_file.exists():
            self.enqueue_run_output(f"[bold red]File '{filename}' already exists.[/bold red]")
            return
        try:
            new_file.touch()
            self.current_file = new_file
            self.code_content = [""]
            self.mode = 'edit'
            self.update_file_list()
            self.enqueue_run_output(f"[bold green]New file created: {new_file}[/bold green]")
        except Exception as e:
            self.enqueue_run_output(f"[bold red]Error creating new file '{filename}': {e}[/bold red]")
    def copy_code_to_clipboard(self):
        pyperclip.copy("\n".join(self.code_content))
        self.enqueue_run_output("Code copied to clipboard.")
    def generate_response(self, prompt: str):
        callback_handler = StreamingCallbackHandler(self)
        with self.chat_lock:
            if not self.server_is_ready:
                self.chat_messages.append("Bot: [WARN] LLaMA server is not ready yet. Please wait or check logs.")
                return
            self.chat_messages.append("Bot:")
        try:
            stream_response(prompt, callback_handler=callback_handler)
        except Exception as e:
            with self.chat_lock:
                self.chat_messages.append(f"Bot: [ERROR] {e}")
    def run(self):
        try:
            from rich.live import Live
            with Live(self.render_layout(), refresh_per_second=30, screen=True) as live:
                while not self.stop_event.is_set():
                    self.process_run_output()
                    self.check_server_readiness()
                    while not self.token_queue.empty():
                        token = self.token_queue.get()
                        with self.chat_lock:
                            if self.chat_messages and self.chat_messages[-1].startswith("Bot:"):
                                self.chat_messages[-1] += token
                            else:
                                self.chat_messages.append(f"Bot: {token}")
                        self.chat_autoscroll = True
                    lines = self.get_chat_lines()
                    visible_count = self.visible_chat_lines()
                    if self.chat_autoscroll:
                        self.chat_view_top = max(0, len(lines) - visible_count)
                    while not self.input_queue.empty():
                        key = self.input_queue.get()
                        self.handle_input(key)
                    lines = self.get_chat_lines()
                    visible_count = self.visible_chat_lines()
                    if self.chat_autoscroll:
                        self.chat_view_top = max(0, len(lines) - visible_count)
                    live.update(self.render_layout())
                    time.sleep(0.01)
        except KeyboardInterrupt:
            self.stop_event.set()
            console.print("[red]Exiting IDE...[/red]")
        finally:
            self.stop_event.set()
            self.kill_llama_server()


if __name__ == "__main__":
    ide = RustTUIIDE(".")
    ide.run()
