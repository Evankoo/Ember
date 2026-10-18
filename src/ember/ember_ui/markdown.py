"""The controlled Markdown subset both workbench editions render: raw HTML is always escaped."""
from __future__ import annotations

import html
import re
from urllib.parse import quote


def inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", safe_link, escaped)
    return escaped


def safe_link(match: re.Match[str]) -> str:
    # Markdown remains the source of truth, but source links are intentionally
    # presentation-only in the workbench. Keep their labels readable without
    # exposing machine-specific or Typora-oriented link targets in HTML.
    return match.group(1)


def markdown_to_html(markdown: str) -> str:
    """Render the controlled Markdown subset used by Ember, escaping raw HTML."""
    lines = markdown.splitlines()
    out: list[str] = []
    paragraph: list[str] = []
    list_type = ""
    in_code = False
    code: list[str] = []
    table: list[list[str]] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append(f"<p>{inline(' '.join(x.strip() for x in paragraph))}</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = ""

    def flush_table() -> None:
        nonlocal table
        if not table:
            return
        rows = table
        table = []
        if len(rows) > 1 and all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in rows[1]):
            head, body = rows[0], rows[2:]
        else:
            head, body = rows[0], rows[1:]
        out.append("<div class=\"md-table\"><table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>")
        out.extend("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in body)
        out.append("</tbody></table></div>")

    for line in [*lines, ""]:
        if line.startswith("```"):
            flush_paragraph(); flush_list(); flush_table()
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
                code = []
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        if line.startswith("|") and line.rstrip().endswith("|"):
            flush_paragraph(); flush_list()
            table.append([cell.strip() for cell in line.strip().strip("|").split("|")])
            continue
        flush_table()
        if not line.strip():
            flush_paragraph(); flush_list(); continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph(); flush_list()
            level = min(len(heading.group(1)) + 1, 6)
            text = heading.group(2).strip()
            anchor_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
            anchor = quote(re.sub(r"\s+", "-", anchor_text))
            out.append(f'<h{level} id="{anchor}">{inline(text)}</h{level}>')
            continue
        item = re.match(r"^\s*([-*]|\d+\.)\s+(.+)$", line)
        if item:
            flush_paragraph()
            wanted = "ol" if item.group(1)[0].isdigit() else "ul"
            if list_type != wanted:
                flush_list(); out.append(f"<{wanted}>"); list_type = wanted
            out.append(f"<li>{inline(item.group(2))}</li>")
            continue
        if line.startswith(">"):
            flush_paragraph(); flush_list()
            out.append(f"<blockquote>{inline(line.lstrip('> ').strip())}</blockquote>")
            continue
        paragraph.append(line)
    return "\n".join(out)
