#!/usr/bin/python3
"""md2ps.py — Markdown to PostScript/PDF renderer.

High-level module on top of pslib. Parses markdown, measures block heights,
renders to PSDoc with orphan prevention. Generator script decides page breaks.

Usage:
    from pslib import PSDoc
    from md2ps import parse_markdown, measure_block, render_block, MdConfig

    blocks = parse_markdown(md_text)
    doc = PSDoc("out.ps", ...)
    for block in blocks:
        needed = measure_block(block, doc, cfg)
        if cy - needed < bottom:
            doc.new_page(); cy = top
        cy = render_block(block, doc, cfg, x, cy, w)

One-liner:
    from md2ps import md_to_pdf
    md_to_pdf("# Hello\\n## World\\nText here", "out.pdf")
"""

import re
import random
import string
from datetime import datetime

from pslib import PSDoc


# ============================================================================
# Block — parsed markdown element
# ============================================================================

class Block:
    """A parsed markdown block."""
    __slots__ = ('kind', 'content')

    def __init__(self, kind, content):
        self.kind = kind
        self.content = content

    def __repr__(self):
        c = repr(self.content)
        if len(c) > 40:
            c = c[:37] + '...'
        return f"Block({self.kind!r}, {c})"


# ============================================================================
# MdConfig — all rendering parameters with SCteam defaults
# ============================================================================

class MdConfig:
    """Rendering configuration. Override any parameter via kwargs."""

    def __init__(self, **kw):
        # Margins (points)
        self.margin_left = 57     # 20mm (binding)
        self.margin_right = 28    # 10mm
        self.margin_top = 28      # 10mm
        self.margin_bottom = 28   # 10mm
        self.qr_zone = 60
        self.header_h = 45        # band under margin_top: logo, title, QR (QR is 25 x 1.8)
        self.footer_h = 20

        # Font sizes
        self.title_size = 16
        self.h2_size = 12
        self.h3_size = 10
        self.h4_size = 9
        self.body_size = 8
        self.code_size = 7
        self.bullet_size = 8
        self.table_header_size = 8
        self.table_body_size = 7

        # Spacing
        self.line_height = 13
        self.code_line_height = 9
        self.section_gap = 6
        self.subsection_gap = 4
        self.para_gap = 4               # extra space after a paragraph / bullet / numbered item
        self.para_indent = 14           # first-line indent (≈ 1.5em)

        # Fonts
        self.body_font = "Helvetica"
        self.bold_font = "Helvetica-Bold"
        self.code_font = "Courier"

        # Code blocks
        self.code_bg_gray = 0.94
        self.code_max_chars = 90

        # Heading colours (RGB 0..1) -- the olive of the holong tech card
        # (holong/tools/tech_card.py GREEN)
        self.h2_bg_rgb     = (0.36, 0.42, 0.30)
        self.h2_text_rgb   = (1.0,  1.0,  1.0)       # white on olive
        self.h_text_rgb    = (0.36, 0.42, 0.30)      # h3/h4 olive text
        self.table_header_rgb = (0.36, 0.42, 0.30)   # table header fill

        # Orphan prevention (min lines after heading)
        self.h2_min_lines = 6
        self.h3_min_lines = 4
        self.h4_min_lines = 2

        # Apply overrides
        for k, v in kw.items():
            if hasattr(self, k):
                setattr(self, k, v)

    @property
    def content_top(self):
        return 842 - self.margin_top - self.qr_zone

    @property
    def bottom_limit(self):
        return self.margin_bottom + self.footer_h + 10

    @property
    def content_width(self):
        return 595 - self.margin_left - self.margin_right


# ============================================================================
# PARSE — markdown text to Block list
# ============================================================================

def clean_md(text):
    """Remove markdown bold/italic/code/strikethrough markers and link syntax."""
    # Links: [label](url) -> label
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    # Bold / italic / code / strike
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    # Stray escape backslashes left by html2text (e.g. "1\." -> "1.")
    text = re.sub(r'\\([.\-_*\[\](){}#+!])', r'\1', text)
    return text


def parse_markdown(text):
    """Parse markdown text into list of Block objects."""
    lines = text.split('\n')
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            blocks.append(Block('blank', ''))
            i += 1
            continue

        # Headings (check h4 before h3 before h2 before h1)
        if stripped.startswith('#### '):
            blocks.append(Block('h4', stripped[5:].strip()))
            i += 1; continue
        if stripped.startswith('### '):
            blocks.append(Block('h3', stripped[4:].strip()))
            i += 1; continue
        if stripped.startswith('## '):
            blocks.append(Block('h2', stripped[3:].strip()))
            i += 1; continue
        if stripped.startswith('# '):
            blocks.append(Block('title', stripped[2:].strip()))
            i += 1; continue

        # Horizontal rule
        if stripped == '---' or stripped == '***' or stripped == '___':
            blocks.append(Block('hr', ''))
            i += 1; continue

        # Code block
        if stripped.startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i].rstrip())
                i += 1
            i += 1  # skip closing ```
            blocks.append(Block('code', code_lines))
            continue

        # Table
        if stripped.startswith('|') and '|' in stripped[1:]:
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            headers = [c.strip() for c in table_lines[0].split('|')[1:-1]]
            rows = []
            for tl in table_lines[2:]:  # skip separator row
                cells = [c.strip().replace('**', '')
                         for c in tl.split('|')[1:-1]]
                rows.append(cells)
            blocks.append(Block('table', (headers, rows)))
            continue

        # Bullet list
        if stripped.startswith('- ') or stripped.startswith('* '):
            blocks.append(Block('bullet', stripped[2:].strip()))
            i += 1; continue

        # Numbered list
        m = re.match(r'^(\d+)\.\s+(.+)', stripped)
        if m:
            blocks.append(Block('numbered', (m.group(1), m.group(2).strip())))
            i += 1; continue

        # Regular text
        blocks.append(Block('text', stripped))
        i += 1

    return blocks


# ============================================================================
# MEASURE — compute block heights
# ============================================================================

def measure_block(block, doc, cfg):
    """Return height in points this block needs to render."""
    kind = block.kind
    cw = cfg.content_width

    if kind == 'title':
        return cfg.title_size + 6 + cfg.section_gap + cfg.line_height + 8

    if kind == 'h2':
        doc.font(cfg.bold_font, cfg.h2_size)
        full_w = doc.A4W - cfg.margin_right - cfg.margin_left
        n = len(doc._wrap_text(clean_md(block.content), full_w - 12))
        return cfg.section_gap + (cfg.h2_size + 4) * n + 6 + 10

    if kind == 'h3':
        doc.font(cfg.bold_font, cfg.h3_size)
        n = len(doc._wrap_text(clean_md(block.content), cw - 5))
        return cfg.line_height + n * (cfg.h3_size + 2) + 3 + cfg.line_height

    if kind == 'h4':
        doc.font(cfg.bold_font, cfg.h4_size)
        n = len(doc._wrap_text(clean_md(block.content), cw - 10))
        return int(cfg.line_height * 0.7) + n * (cfg.h4_size + 2) + 3 + cfg.line_height

    if kind == 'text':
        doc.font(cfg.body_font, cfg.body_size)
        lines = doc._wrap_text(clean_md(block.content), cw)
        return cfg.line_height * len(lines) + cfg.para_gap

    if kind == 'bullet':
        doc.font(cfg.body_font, cfg.bullet_size)
        lines = doc._wrap_text(clean_md(block.content), cw - 12)
        return cfg.line_height * len(lines) + cfg.para_gap

    if kind == 'numbered':
        doc.font(cfg.body_font, cfg.bullet_size)
        lines = doc._wrap_text(clean_md(block.content[1]), cw - 20)
        return cfg.line_height * len(lines) + cfg.para_gap

    if kind == 'code':
        n = len(block.content)
        return 2 + cfg.code_line_height * n + 4 + 6

    if kind == 'table':
        headers, rows = block.content
        return 4 + 14 + 13 * len(rows) + 6  # header + rows + gap

    if kind == 'hr':
        return 2 + cfg.subsection_gap * 2  # breathing room above + below the line

    if kind == 'blank':
        return 1

    return cfg.line_height


def measure_section(blocks, start_idx, doc, cfg):
    """Measure heading + content until next sub-heading.

    Returns (height, block_count) — block_count is the number of blocks
    in this section (including the heading). The generator uses block_count
    to skip page-break checks for blocks that belong to this section.

    Strategy:
    - h2: measures header + content until first h3 (h3 decides for itself)
    - h3: measures header + content recursively including h4 subsections
    - h4: measures header + content until next heading

    Each h3 is an indivisible unit — the generator measures it independently
    and decides whether it fits on the current page or moves to the next.
    This avoids the "big gap" problem where an entire h2 section gets
    pushed to a new page because one h3 subsection doesn't fit.
    """
    block = blocks[start_idx]
    total = measure_block(block, doc, cfg)
    level = block.kind  # 'h2', 'h3', 'h4'
    page_h = cfg.content_top - cfg.bottom_limit

    j = start_idx + 1
    while j < len(blocks):
        bj = blocks[j]
        kind = bj.kind

        # Stop at heading of same or higher level
        if level == 'h2' and kind == 'h2':
            break
        if level == 'h3' and kind in ('h2', 'h3'):
            break
        if level == 'h4' and kind in ('h2', 'h3', 'h4'):
            break

        # h2 stops at first sub-heading — h3 will measure itself
        if level == 'h2' and kind in ('h3', 'h4'):
            break

        # h3 recursively includes h4 subsections (small, keep together)
        if level == 'h3' and kind == 'h4':
            sub_h, sub_count = measure_section(blocks, j, doc, cfg)
            total += sub_h
            j += sub_count
            continue

        # Regular content block
        total += measure_block(bj, doc, cfg)
        j += 1

    count = j - start_idx
    return min(total, page_h), count


# ============================================================================
# RENDER — draw blocks to PSDoc
# ============================================================================

def render_block(block, doc, cfg, x, y, content_w, section_num=0):
    """Render a single block at (x, y). Returns new y position."""
    kind = block.kind

    if kind == 'title':
        return _render_title(block, doc, cfg, x, y, content_w)
    if kind == 'h2':
        return _render_h2(block, doc, cfg, x, y, content_w, section_num)
    if kind == 'h3':
        return _render_h3(block, doc, cfg, x, y, content_w)
    if kind == 'h4':
        return _render_h4(block, doc, cfg, x, y, content_w)
    if kind == 'text':
        return _render_text(block, doc, cfg, x, y, content_w)
    if kind == 'bullet':
        return _render_bullet(block, doc, cfg, x, y, content_w)
    if kind == 'numbered':
        return _render_numbered(block, doc, cfg, x, y, content_w)
    if kind == 'code':
        return _render_code(block, doc, cfg, x, y, content_w)
    if kind == 'table':
        return _render_table(block, doc, cfg, x, y, content_w)
    if kind == 'hr':
        y -= cfg.subsection_gap          # space ABOVE the line
        doc.hr(y, x, x + content_w)
        y -= 2 + cfg.subsection_gap      # line itself + space below
        return y
    if kind == 'blank':
        return y - 1
    return y


def _render_title(block, doc, cfg, x, y, cw):
    doc.font(cfg.bold_font, cfg.title_size)
    doc.text(doc.A4W / 2, y, clean_md(block.content), align="center")
    y -= cfg.title_size + 6
    doc.hr(y, x, doc.A4W - cfg.margin_right)
    y -= cfg.section_gap + cfg.line_height   # breathing room below title rule
    return y


def _render_header_title(block, doc, cfg):
    """The document title, in the header band between the logo and the QR,
    centred on the band. Shrinks to fit rather than running into either."""
    label = clean_md(block.content)
    band_top = doc.A4H - cfg.margin_top
    band_mid = band_top - cfg.header_h / 2
    # Room on each side of the page centre: the logo on the left; the QR
    # and its RSC/date labels (~60pt of Courier 6) on the right.
    left_room = doc.A4W / 2 - (cfg.margin_left + cfg.header_h + 10)
    right_room = (doc.A4W - cfg.margin_right - cfg.header_h - 5 - 60 - 10) - doc.A4W / 2
    max_w = 2 * min(left_room, right_room)
    size = cfg.title_size
    doc.font(cfg.bold_font, size)
    while size > 9 and doc.string_width(label) > max_w:
        size -= 0.5
        doc.font(cfg.bold_font, size)
    doc.text(doc.A4W / 2, band_mid - size * 0.72 / 2, label, align="center")
    rule_y = band_top - cfg.header_h - 6
    doc.hr(rule_y, cfg.margin_left, doc.A4W - cfg.margin_right)
    return rule_y - cfg.line_height          # first body baseline below the rule


def _render_h2(block, doc, cfg, x, y, cw, section_num):
    y -= cfg.section_gap
    doc.font(cfg.bold_font, cfg.h2_size)
    label = f"{section_num:02d}  {clean_md(block.content)}"
    full_w = doc.A4W - cfg.margin_right - x
    lines = doc._wrap_text(label, full_w - 12)
    line_h = cfg.h2_size + 4
    box_h = line_h * len(lines) + 6
    box_y = y - box_h
    if box_y < cfg.margin_bottom:
        sys.stderr.write(f"[md2ps] WARN: h2 '{label[:50]}...' overflows printable area\n")
    # Filled box, full content width, no outline
    doc.rect(x, box_y, full_w, box_h, fill=True, rgb=cfg.h2_bg_rgb, stroke=False)
    r, g, b = cfg.h2_text_rgb
    doc.setcolor(r, g, b)
    doc.font(cfg.bold_font, cfg.h2_size)
    # Centre the text block vertically: cap height (Helvetica 718/1000 em)
    # is what the eye sees, so centre that, not the em box.
    cap_h = cfg.h2_size * 0.72
    block_h = line_h * (len(lines) - 1) + cap_h
    ty = box_y + (box_h - block_h) / 2 + line_h * (len(lines) - 1)
    for line in lines:
        doc.text(x + 6, ty, line)
        ty -= line_h
    doc.setgray(0)
    return box_y - 10


def _render_h3(block, doc, cfg, x, y, cw):
    y -= cfg.line_height  # space BEFORE h3 (separate from previous content)
    doc.font(cfg.bold_font, cfg.h3_size)
    label = clean_md(block.content)
    r, g, b = cfg.h_text_rgb
    doc.setcolor(r, g, b)
    lines = doc._wrap_text(label, cw - 5)
    last_baseline = y
    for line in lines:
        doc.text(x + 5, y, line)
        last_baseline = y
        y -= cfg.h3_size + 2
    underline_y = last_baseline - 3
    doc.hr(underline_y, x + 5, doc.A4W - cfg.margin_right)
    doc.setgray(0)
    return underline_y - cfg.line_height


def _render_h4(block, doc, cfg, x, y, cw):
    y -= cfg.line_height * 0.7  # space before h4
    doc.font(cfg.bold_font, cfg.h4_size)
    label = clean_md(block.content)
    r, g, b = cfg.h_text_rgb
    doc.setcolor(r, g, b)
    lines = doc._wrap_text(label, cw - 10)
    last_baseline = y
    for line in lines:
        doc.text(x + 10, y, line)
        last_baseline = y
        y -= cfg.h4_size + 2
    underline_y = last_baseline - 3
    doc.hr(underline_y, x + 10, doc.A4W - cfg.margin_right)
    doc.setgray(0)
    return underline_y - cfg.line_height


def _render_text(block, doc, cfg, x, y, cw):
    doc.font(cfg.body_font, cfg.body_size)
    text = clean_md(block.content)
    lines = doc._wrap_text(text, cw - cfg.para_indent)  # narrower for first line
    for i, line in enumerate(lines):
        if i == 0:
            doc.text(x + cfg.para_indent, y, line)
        else:
            doc.text(x, y, line)
        y -= cfg.line_height
    return y - cfg.para_gap


def _render_bullet(block, doc, cfg, x, y, cw):
    doc.font(cfg.body_font, cfg.bullet_size)
    text = clean_md(block.content)
    lines = doc._wrap_text(text, cw - 12)
    doc.text(x + 8, y, "\u2022 " + lines[0])
    y -= cfg.line_height
    for extra in lines[1:]:
        doc.text(x + 14, y, extra)
        y -= cfg.line_height
    return y - cfg.para_gap


def _render_numbered(block, doc, cfg, x, y, cw):
    num, text = block.content
    text = clean_md(text)
    doc.font(cfg.bold_font, cfg.bullet_size)
    doc.text(x + 5, y, f"{num}.")
    doc.font(cfg.body_font, cfg.bullet_size)
    lines = doc._wrap_text(text, cw - 20)
    doc.text(x + 18, y, lines[0])
    y -= cfg.line_height
    for extra in lines[1:]:
        doc.text(x + 18, y, extra)
        y -= cfg.line_height
    return y - cfg.para_gap


def _render_code(block, doc, cfg, x, y, cw):
    code_lines = block.content
    y -= 2
    bg_h = len(code_lines) * cfg.code_line_height + 4
    doc.rect(x, y - bg_h, cw, bg_h,
             fill=True, gray=cfg.code_bg_gray, stroke=True, linewidth=0.3)
    doc.setgray(0)
    doc.font(cfg.code_font, cfg.code_size)
    code_y = y - cfg.code_line_height + 1
    for cl in code_lines:
        if len(cl) > cfg.code_max_chars:
            cl = cl[:cfg.code_max_chars - 3] + "..."
        doc.text(x + 4, code_y, cl)
        code_y -= cfg.code_line_height
    return code_y - 6


def _render_table(block, doc, cfg, x, y, cw):
    headers, rows = block.content
    y -= 4
    y = doc.table(x, y, headers, rows,
                  font_name=cfg.body_font,
                  header_size=cfg.table_header_size,
                  body_size=cfg.table_body_size,
                  row_height=13,
                  col_align=["left"] * len(headers),
                  header_rgb=cfg.table_header_rgb)
    return y - 6


# ============================================================================
# OVERLAYS — QR, footer, watermark (applied after all content)
# ============================================================================

def generate_rsc(length=8):
    """Generate random alphanumeric reference code."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def _qr_matrix(data):
    """Generate QR code matrix. Returns None if qrcode not installed."""
    try:
        import qrcode
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H,
                           box_size=1, border=0)
        qr.add_data(data)
        qr.make()
        return qr.get_matrix()
    except ImportError:
        return None


def apply_overlays(doc, cfg, overlays):
    """Apply per-page overlays after all content is rendered.

    overlays: list of dicts, each with 'type' key:
        {'type': 'footer', 'timestamp': '2026-04-04T12:00:00'}
        {'type': 'qr', 'rsc': 'ABC12345', 'date': '2026-04-04T12:00'}
        {'type': 'watermark', 'text': 'DRAFT', 'gray': 0.92, 'size': 140}
    """
    import math
    total_pages = len(doc.pages)

    for pg_idx in range(total_pages):
        cmds = doc.pages[pg_idx]
        for ov in overlays:
            if ov['type'] == 'watermark':
                _overlay_watermark(doc, cfg, cmds, ov)
            elif ov['type'] == 'footer':
                _overlay_footer(doc, cfg, cmds, pg_idx, total_pages, ov)
            elif ov['type'] == 'qr':
                _overlay_qr(doc, cfg, cmds, pg_idx, ov)
            elif ov['type'] == 'logo':
                _overlay_logo(doc, cfg, cmds, ov)


# The SC team mark: an S (green) woven through a C (blue), three stroked
# cubic paths. Taken verbatim from https://ntr.smooker.org/favicon.svg
# (the same mark as /cs-logo.svg there, without its dark card and text).
# SVG user space, y down; viewBox 60 35 210 240.
_LOGO_VIEWBOX = (60, 35, 210, 240)
_LOGO_STROKE = 24
_LOGO_GREEN = (106 / 255, 153 / 255, 85 / 255)    # #6A9955
_LOGO_BLUE = (125 / 255, 184 / 255, 224 / 255)    # #7DB8E0
_LOGO_PATHS = [   # drawn in order: S tail behind C, C, S top in front
    (_LOGO_GREEN, "250 178 moveto 260 210 245 240 215 250 curveto "
                  "185 260 150 255 135 242 curveto"),
    (_LOGO_BLUE,  "260 160 moveto 260 220 215 260 160 260 curveto "
                  "105 260 70 225 70 185 curveto 70 145 105 112 160 112 curveto "
                  "195 112 218 125 232 142 curveto"),
    (_LOGO_GREEN, "225 45 moveto 180 45 140 65 140 95 curveto "
                  "140 125 170 138 200 148 curveto 230 158 248 168 250 178 curveto"),
]


def _overlay_logo(doc, cfg, cmds, ov):
    """SC team logo, top-left, fitted into a size x size box. Pure vector:
    the SVG paths are replayed as PostScript curves, nothing rasterised."""
    s = ov.get('size', cfg.header_h)
    vx, vy, vw, vh = _LOGO_VIEWBOX
    k = s / max(vw, vh)
    tx = cfg.margin_left + (s - vw * k) / 2
    ty = doc.A4H - cfg.margin_top - (s - vh * k) / 2
    cmds.extend([
        "gsave",
        # SVG y-down user space onto the page: flip y, then shift the viewBox origin
        f"{tx} {ty} translate {k} {-k} scale {-vx} {-vy} translate",
        f"1 setlinecap 1 setlinejoin {_LOGO_STROKE} setlinewidth",
    ])
    for (r, g, b), path in _LOGO_PATHS:
        cmds.append(f"{r:.4f} {g:.4f} {b:.4f} setrgbcolor newpath {path} stroke")
    cmds.append("grestore")


def _overlay_watermark(doc, cfg, cmds, ov):
    import math
    text = ov.get('text', 'DRAFT')
    gray = ov.get('gray', 0.92)
    size = ov.get('size', 140)
    angle = math.degrees(math.atan2(doc.A4H, doc.A4W))
    wm = [
        "gsave", f"{gray} setgray",
        f"/Helvetica_Bold_Cyr findfont {size} scalefont setfont",
        f"{doc.A4W / 2} {doc.A4H / 2 - 40} translate",
        f"{angle} rotate",
        f"0 0 moveto ({doc._escape_ps(text)}) dup stringwidth pop "
        f"2 div neg 0 rmoveto show",
        "grestore",
    ]
    for i, cmd in enumerate(wm):
        cmds.insert(i, cmd)


def _overlay_footer(doc, cfg, cmds, pg_idx, total_pages, ov):
    ts = ov.get('timestamp', datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    footer_y = cfg.margin_bottom + cfg.footer_h - 4
    ml = cfg.margin_left
    mr = cfg.margin_right

    cmds.append(f"0.3 setlinewidth {ml} {footer_y} moveto "
                f"{doc.A4W - mr - ml} 0 rlineto stroke")
    ts_esc = doc._escape_ps(ts)
    cmds.append(f"/Helvetica_Cyr 6 selectfont")
    cmds.append(f"{ml} {cfg.margin_bottom} moveto ({ts_esc}) show")
    pn_esc = doc._escape_ps(f"p. {pg_idx + 1}/{total_pages}")
    cmds.append(f"({pn_esc}) stringwidth pop neg "
                f"{doc.A4W - mr} add {cfg.margin_bottom} moveto ({pn_esc}) show")


def _overlay_qr(doc, cfg, cmds, pg_idx, ov):
    rsc = ov.get('rsc', generate_rsc())
    date_str = ov.get('date', datetime.now().strftime("%Y-%m-%dT%H:%M"))
    mr = cfg.margin_right
    mt = cfg.margin_top

    matrix = _qr_matrix(f"RSC:{rsc}/{pg_idx + 1}")
    if not matrix:
        return

    qr_mod = 1.8
    qr_sz = len(matrix) * qr_mod
    qr_px = doc.A4W - mr - qr_sz
    qr_py = doc.A4H - mt

    # Draw QR modules
    for r, row in enumerate(matrix):
        for c, black in enumerate(row):
            if black:
                px = qr_px + c * qr_mod
                py = qr_py - (r + 1) * qr_mod
                cmds.append(f"newpath {px} {py} moveto "
                            f"{qr_mod} 0 rlineto 0 {qr_mod} rlineto "
                            f"{qr_mod} neg 0 rlineto closepath fill")

    # White circle + SC label in center
    cx = qr_px + qr_sz / 2
    cy_c = qr_py - qr_sz / 2
    lbl_sz = qr_mod * 3.5
    radius = max(lbl_sz * 1.2 / 2, lbl_sz / 2) + 2.5
    cmds.append(f"gsave 1 setgray newpath "
                f"{cx} {cy_c} {radius} 0 360 arc closepath fill grestore")
    cmds.append("0 setgray")
    sc_esc = doc._escape_ps("SC")
    ty_sc = cy_c - lbl_sz * 0.35
    cmds.append(f"/Helvetica_Bold_Cyr {lbl_sz} selectfont")
    cmds.append(f"({sc_esc}) stringwidth pop 2 div neg "
                f"{cx} add {ty_sc} moveto ({sc_esc}) show")

    # RSC + date labels left of QR
    lx = qr_px - 5
    rsc_label = doc._escape_ps(f"RSC: {rsc}")
    date_label = doc._escape_ps(date_str)

    # Scale RSC font to match date width
    doc.font("Courier-Bold", 6)
    date_w = doc.string_width(date_str)
    doc.font("Courier-Bold", 7)
    rsc_w = doc.string_width(f"RSC: {rsc}")
    rsc_sz = 7 * date_w / rsc_w if rsc_w > 0 else 7

    cmds.append(f"/Courier_Bold_Cyr {rsc_sz} selectfont")
    rsc_y = qr_py - rsc_sz
    cmds.append(f"({rsc_label}) stringwidth pop neg "
                f"{lx} add {rsc_y} moveto ({rsc_label}) show")
    cmds.append(f"/Courier_Bold_Cyr 6 selectfont")
    cmds.append(f"({date_label}) stringwidth pop neg "
                f"{lx} add {rsc_y - 9} moveto ({date_label}) show")


# ============================================================================
# CONVENIENCE — md_to_pdf one-liner
# ============================================================================

def md_to_pdf(md_text, output_path, cfg=None, overlays=None, title="Document"):
    """Convert markdown text to PDF in one call.

    Args:
        md_text: Markdown string
        output_path: Output PDF path
        cfg: MdConfig (defaults to SCteam config)
        overlays: List of overlay dicts (default: footer + QR)
        title: Document title metadata
    """
    if cfg is None:
        cfg = MdConfig()

    ps_path = output_path.rsplit('.', 1)[0] + '.ps'
    doc = PSDoc(ps_path, title=title,
                margin=cfg.margin_left,
                margin_top=cfg.margin_top + cfg.qr_zone,
                margin_bottom=cfg.margin_bottom + cfg.footer_h,
                margin_right=cfg.margin_right)

    blocks = parse_markdown(md_text)
    x = cfg.margin_left
    cw = cfg.content_width
    page_top = cfg.content_top
    bottom = cfg.bottom_limit
    cy = page_top
    section_num = 0

    page_h = cfg.content_top - cfg.bottom_limit
    skip_until = -1

    # A leading `# title` goes into the header band, beside the logo and QR.
    header_title = next((i for i, b in enumerate(blocks) if b.kind != 'blank'), None)
    if header_title is not None and blocks[header_title].kind == 'title':
        cy = min(cy, _render_header_title(blocks[header_title], doc, cfg))
    else:
        header_title = None

    for i, block in enumerate(blocks):
        if i == header_title:
            continue
        if block.kind == 'h2':
            section_num += 1

        # Measure
        if block.kind in ('h2', 'h3', 'h4') and i >= skip_until:
            height, block_count = measure_section(blocks, i, doc, cfg)
            # Edge case: if the whole section is taller than a page, don't
            # skip internal page-break checks — fall back to per-block mode.
            # Otherwise skip_until would cause overflow under bottom_limit.
            if height >= page_h:
                needed = measure_block(block, doc, cfg)
                check_break = True  # skip_until stays unchanged
            else:
                needed = height
                skip_until = i + block_count
                check_break = True
        elif i < skip_until:
            needed = measure_block(block, doc, cfg)
            check_break = False
        else:
            needed = measure_block(block, doc, cfg)
            check_break = True

        # Page break if needed
        if check_break and cy - needed < bottom:
            doc.new_page()
            cy = page_top

        # Render
        cy = render_block(block, doc, cfg, x, cy, cw, section_num)

    # Overlays
    if overlays is None:
        rsc = generate_rsc()
        now = datetime.now()
        overlays = [
            {'type': 'footer', 'timestamp': now.strftime("%Y-%m-%dT%H:%M:%S")},
            {'type': 'qr', 'rsc': rsc, 'date': now.strftime("%Y-%m-%dT%H:%M")},
            {'type': 'logo'},
        ]

    apply_overlays(doc, cfg, overlays)
    doc.save()
    return doc.to_pdf(output_path)
