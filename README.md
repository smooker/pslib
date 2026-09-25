# pslib

PostScript Level 2 document generation library in Python.

Generates print-ready PS/PDF with **CP1251 Cyrillic support**, tables with word wrap, tree structures, text alignment, and font metrics caching.

## Features

- **Text** — left / center / right alignment, Cyrillic via CP1251 re-encoding
- **Tables** — auto column widths, word wrap (including character-level break), black header with white text, page breaks with continuation markers
- **Trees** — nested dict or flat format, PS connector lines, page breaks
- **Font metrics cache** — one Ghostscript call per font+size combo, then instant Python measurement. ~300x faster than per-string subprocess calls
- **Margins** — independent left / right / top / bottom
- **PS to PDF** — built-in `to_pdf()` via Ghostscript with font embedding

## Requirements

- Python 3.6+
- Ghostscript (`gs`) — for font metrics and PS-to-PDF conversion
- `qrencode` (optional) — for QR code generation in example.py

## Quick start

```python
from pslib import PSDoc

doc = PSDoc("output.ps", title="My Document")
doc.font("Helvetica-Bold", 16)
doc.text(50, 780, "Hello World")
doc.hr(770)

doc.font("Helvetica", 10)
doc.table(50, 720,
    headers=["#", "Name", "Role"],
    rows=[["1", "Ivan", "Engineer"],
          ["2", "Maria", "Designer"]],
    col_align=["right", "left", "left"])

doc.tree(50, 650, [
    {"text": "Root", "children": [
        {"text": "Child A"},
        {"text": "Child B", "children": [
            {"text": "Grandchild"},
        ]},
    ]}
])

doc.page_number()
doc.save()
doc.to_pdf("output.pdf")
```

## Cyrillic support

pslib automatically re-encodes standard PostScript fonts to CP1251 (Windows-1251). UTF-8 input is converted to CP1251 octal escapes.

Supported fonts: Helvetica, Helvetica-Bold, Helvetica-Oblique, Helvetica-BoldOblique, Courier, Courier-Bold, Times-Roman, Times-Bold, Times-Italic.

```python
doc.font("Helvetica", 12)
doc.text(50, 750, "Кирилица работи без проблем")
w = doc.string_width("Кирилица")  # instant measurement from cache
```

## Margins

```python
doc = PSDoc("out.ps",
    margin=28,          # left (default for all)
    margin_right=14,
    margin_top=74,      # top + reserved zone
    margin_bottom=34)   # bottom + footer zone
```

Tables and trees respect `margin_top` and `margin_bottom` for page breaks.

## Example

See [example.py](example.py) for a complete multi-page document with tables, tree, QR codes, grid reference system, and per-page footer. Generated output: [example.pdf](example.pdf).

## Coordinate system

- Origin (0, 0) = bottom-left corner
- Y grows upward
- A4 = 595 x 842 points
- 1 point = 1/72 inch = 0.353 mm

## MCP server

`mcp_server.py` exposes pslib to Claude Code (and any MCP client) as tools:
`md_to_pdf`, `render_template`, `template_list`, `template_info`,
`pdf_preview`, `measure_text`. Standard library only, plus `jinja2` for the
markdown templates.

Templates are code, not files: `templates.py` holds the registry (`report`,
`protocol`, `tk_card` = a production technology card). A client names a
template and sends data; the data is validated against the template's schema
and the PDF comes back inline (base64 resource) and is written under the out
dir (`--out-dir`, default `~/pslib-out`).

```bash
# local, one Claude Code session
claude mcp add pslib -- /usr/bin/python3 /path/to/pslib/mcp_server.py

# shared: one server on a host, clients connect over the VPN with a token
echo "<random 32+ chars>" > ~/.pslib-mcp-token
python3 mcp_server.py --http 192.0.2.10:7462
claude mcp add --transport http pslib http://192.0.2.10:7462/mcp \
    --header "Authorization: Bearer <token>"
```

Tests: `python3 tests/test_mcp.py` drives both transports end to end.

## License

MIT — see [LICENSE](LICENSE).
