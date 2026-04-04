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

## License

MIT — see [LICENSE](LICENSE).
