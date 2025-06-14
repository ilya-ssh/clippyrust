from __future__ import annotations
import re
from typing import Iterable, List

from markdown_it import MarkdownIt
from markdown_it.token import Token
from rich.console import RenderableType
from rich.markdown import Markdown 
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

md = (MarkdownIt("commonmark", {"html": True}).enable("table").enable("strikethrough"))
_CAPTION_RE = re.compile(r'<span\s+class="caption">(.*?)</span>', re.I | re.S)

def _tokens_to_rich(tokens: List[Token]) -> List[RenderableType]:
    """
    маркдаун в рич
    """
    out: List[RenderableType] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "fence": #код тэг
            language = (tok.info or "text").strip()
            code = tok.content.rstrip("\n")
            out.append(Syntax(code, language, line_numbers=False, theme="ansi_dark"))
            i += 1
            continue
        if tok.type == "table_open":
            header_cells = []
            i += 2              
            while tokens[i].type != "tr_close":
                if tokens[i].type == "inline":
                    header_cells.append(tokens[i].content)
                i += 1
            # body rows
            rows: list[list[str]] = []
            while tokens[i].type != "table_close":
                if tokens[i].type == "tr_open":
                    row: list[str] = []
                    i += 2
                    while tokens[i].type != "tr_close":
                        if tokens[i].type == "inline":
                            row.append(tokens[i].content)
                        i += 1
                    rows.append(row)
                else:
                    i += 1
            tbl = Table(box=None)
            for h in header_cells:
                tbl.add_column(Text(h, style="bold"))
            for r in rows:
                r += [""] * (len(header_cells) - len(r))
                tbl.add_row(*r)
            out.append(tbl)
            i += 1
            continue
        if tok.type == "paragraph_open" and tokens[i + 1].type == "inline":
            text = tokens[i + 1].content.strip()
            # convert <span class="caption">
            m = _CAPTION_RE.fullmatch(text)
            if m:
                out.append(Text(m.group(1), style="bold yellow"))
            else:
                out.append(Markdown(text))
            i += 3
            continue

        i += 1
    return out


def parse_markdown(md_text: str) -> List[RenderableType]:
    tokens = md.parse(md_text)
    return _tokens_to_rich(tokens)
