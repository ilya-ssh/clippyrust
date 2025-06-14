from __future__ import annotations
import re
from pathlib import Path
from typing import Dict, List, Tuple

from rich.console import RenderableType, Group, Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from md_rich import parse_markdown 
import shutil
def _slug_to_title(slug: str) -> str:
    #hello-world в Hello world
    return slug.replace("-", " ").capitalize()
def parse_rust_book_chapters(book_dir: Path) -> Dict[int, List[Tuple[str, Path]]]:
    patt = re.compile(r"^ch(\d+)-\d\d-(.+)\.md$", re.IGNORECASE)
    chapters: Dict[int, List[Tuple[str, Path]]] = {}
    for md in book_dir.glob("ch*-*.md"):
        m = patt.match(md.name)
        if not m:
            continue
        chap = int(m.group(1))
        chapters.setdefault(chap, []).append((_slug_to_title(m.group(2)), md))
    for chap in chapters:
        chapters[chap].sort(key=lambda t: t[0].lower())
    return dict(sorted(chapters.items()))
class RustBookViewer:
    def __init__(self, book_dir: Path):
        self.book_dir = book_dir
        self.chapters = parse_rust_book_chapters(book_dir)
        self.chapter_nums: List[int] = list(self.chapters.keys())
        self.selected_idx: int = 0
        self.open_chapter: int | None = None
        self.markdown_lines: List[str] = []
        self.rendered_lines: List[str] = []
        self.row_scroll: int = 0
    def move_selection(self, delta: int):
        if not self.chapter_nums:
            return
        self.selected_idx = max(0, min(self.selected_idx + delta, len(self.chapter_nums) - 1))
    def open_selected(self):
        if not self.chapter_nums:
            return
        self.load_chapter(self.chapter_nums[self.selected_idx])
    def load_chapter(self, chap_num: int):
        if chap_num not in self.chapters:
            return
        self.open_chapter = chap_num
        all_lines: list[str] = []
        for _title, md_path in self.chapters[chap_num]:
            all_lines.extend(md_path.read_text(encoding="utf-8").splitlines())
            all_lines.append("")          # blank line between files

        self.markdown_lines = all_lines
        md_renderable = parse_markdown("\n".join(all_lines))
        term_w = shutil.get_terminal_size().columns
        cons   = Console(width=term_w, record=True)
        if isinstance(md_renderable, list):
            for r in md_renderable:
                cons.print(r)
        else:
            cons.print(md_renderable)
        raw_lines = cons.export_text(styles=True).splitlines()
        self.rendered_lines = [Text.from_markup(line) for line in raw_lines]
        self.row_scroll = 0
    def is_at_end(self, height: int) -> bool:
        return self.open_chapter is not None and self.row_scroll + height >= len(self.rendered_lines)
    def _index_table(self) -> Table:
        tbl = Table(box=None, expand=True, show_header=False)
        tbl.add_column("")
        tbl.add_column("Chapter", style="green")
        for idx, chap in enumerate(self.chapter_nums):
            titles = ", ".join(t for t, _ in self.chapters[chap])
            if idx == self.selected_idx:
                chapter_cell = f"[on blue bold]Chapter {chap}: {titles}[/]"
                pointer = "▶"
            else:
                chapter_cell = f"Chapter {chap}: {titles}"
                pointer = ""
            tbl.add_row(pointer, chapter_cell)
        tbl.caption = "Arrows to move Enter to open Esc to exit"
        return tbl
    def visible_lines(self, height: int) -> list[str]:
        end = min(len(self.rendered_lines), self.row_scroll + height)
        return  self.rendered_lines[self.row_scroll : end]
    def visible_renderables(self, height: int):
            lines_per_view = height * 4
            slice_text = "\n".join(self.markdown_lines[self.scroll : self.scroll + lines_per_view])
            parsed = parse_markdown(slice_text) 
            if parsed is None:
                return []
            if isinstance(parsed, list):
                return parsed
            return [parsed]
    def _chapter_panel(self, body_height: int):
        content = self.visible_lines(body_height - 2)
        at_end  = self.is_at_end(body_height - 2)
        if at_end:
            content.append(
                Text("\n— End of chapter —  [T]est | [R]eread | [Esc] index",style="bold green"))
        return Panel(Group(*content), title=f"Chapter {self.open_chapter}", border_style="green", height=body_height)
    def visible_markdown(self, height: int) -> str:
        end = min(len(self.markdown_lines), self.scroll + height)
        return "\n".join(self.markdown_lines[self.scroll:end])
    def render(self, body_height: int) -> RenderableType:
        if self.open_chapter is None:
            return self._index_table()
        return self._chapter_panel(body_height)
