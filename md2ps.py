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
        self.margin_left = 42     # 15mm (binding)
        self.margin_right = 23    # 8mm
        self.margin_top = 36      # 12.7mm (gripper)
        self.margin_bottom = 36   # 12.7mm (gripper)
        self.qr_zone = 60
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
        self.line_height = 11
        self.code_line_height = 9
        self.section_gap = 6
        self.subsection_gap = 4

        # Fonts
        self.body_font = "Helvetica"
        self.bold_font = "Helvetica-Bold"
        self.code_font = "Courier"

        # Code blocks
        self.code_bg_gray = 0.94
        self.code_max_chars = 90

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
    """Remove markdown bold/italic/code/strikethrough markers."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'~~(.+?)~~', r'\1', text)
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
        return cfg.title_size + 4 + 10 + 12 + cfg.section_gap + 8

    if kind == 'h2':
        return cfg.section_gap + cfg.h2_size + 6 + 10

    if kind == 'h3':
        return cfg.line_height + cfg.h3_size + 1

    if kind == 'h4':
        return 3 + cfg.h4_size + 2

    if kind == 'text':
        doc.font(cfg.body_font, cfg.body_size)
        lines = doc._wrap_text(clean_md(block.content), cw)
        return cfg.line_height * len(lines)

    if kind == 'bullet':
        doc.font(cfg.body_font, cfg.bullet_size)
        lines = doc._wrap_text(clean_md(block.content), cw - 12)
        return cfg.line_height * len(lines)

    if kind == 'numbered':
        doc.font(cfg.body_font, cfg.bullet_size)
        lines = doc._wrap_text(clean_md(block.content[1]), cw - 20)
        return cfg.line_height * len(lines)

    if kind == 'code':
        n = len(block.content)
        return 2 + cfg.code_line_height * n + 4 + 6

    if kind == 'table':
        headers, rows = block.content
        return 4 + 14 + 13 * len(rows) + 6  # header + rows + gap

    if kind == 'hr':
        return 2

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
        return y - 2
    if kind == 'blank':
        return y - 1
    return y


def _render_title(block, doc, cfg, x, y, cw):
    doc.font(cfg.bold_font, cfg.title_size)
    doc.text(doc.A4W / 2, y, clean_md(block.content), align="center")
    y -= cfg.title_size + 4
    doc.font(cfg.body_font, 8)
    doc.text(doc.A4W / 2, y, "LZ1CCM / smooker / SCteam", align="center")
    y -= 10
    doc.font(cfg.body_font, 7)
    doc.text(doc.A4W / 2, y, datetime.now().strftime("%Y-%m-%dT%H:%M"), align="center")
    y -= 12
    doc.hr(y, x, doc.A4W - cfg.margin_right)
    y -= cfg.section_gap
    return y


def _render_h2(block, doc, cfg, x, y, cw, section_num):
    y -= cfg.section_gap
    doc.font(cfg.bold_font, cfg.h2_size)
    label = f"{section_num:02d}  {clean_md(block.content)}"
    tw = doc.string_width(label)
    box_h = cfg.h2_size + 6
    box_y = y - box_h
    line_y = box_y + box_h / 2
    # Line across full width
    doc.hr(line_y, x, doc.A4W - cfg.margin_right)
    # Light gray box behind text (same as code block bg)
    doc.rect(x, box_y, tw + 8, box_h, fill=True, gray=cfg.code_bg_gray, stroke=False)
    # Black border
    doc.rect(x, box_y, tw + 8, box_h, fill=False, gray=0, stroke=True, linewidth=0.5)
    doc.setgray(0)
    # Text centered in box
    doc.font(cfg.bold_font, cfg.h2_size)
    text_y = box_y + (box_h - cfg.h2_size) / 2 + cfg.h2_size * 0.2
    doc.text(x + 4, text_y, label)
    return box_y - 10


def _render_h3(block, doc, cfg, x, y, cw):
    y -= cfg.line_height  # space BEFORE h3 (separate from previous content)
    doc.font(cfg.bold_font, cfg.h3_size)
    doc.text(x + 5, y, clean_md(block.content))
    return y - cfg.h3_size - 1  # tight to own content


def _render_h4(block, doc, cfg, x, y, cw):
    y -= cfg.line_height * 0.7  # space before h4
    doc.font(cfg.bold_font, cfg.h4_size)
    doc.text(x + 10, y, clean_md(block.content))
    return y - cfg.h4_size - 2


def _render_text(block, doc, cfg, x, y, cw):
    doc.font(cfg.body_font, cfg.body_size)
    text = clean_md(block.content)
    for line in doc._wrap_text(text, cw):
        doc.text(x, y, line)
        y -= cfg.line_height
    return y


def _render_bullet(block, doc, cfg, x, y, cw):
    doc.font(cfg.body_font, cfg.bullet_size)
    text = clean_md(block.content)
    lines = doc._wrap_text(text, cw - 12)
    doc.text(x + 8, y, "\u2022 " + lines[0])
    y -= cfg.line_height
    for extra in lines[1:]:
        doc.text(x + 14, y, extra)
        y -= cfg.line_height
    return y


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
    return y


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
                  col_align=["left"] * len(headers))
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

    for i, block in enumerate(blocks):
        if block.kind == 'h2':
            section_num += 1

        # Measure
        needed = measure_block(block, doc, cfg)
        if block.kind in ('h2', 'h3', 'h4'):
            needed = measure_section(blocks, i, doc, cfg)

        # Page break if needed
        if cy - needed < bottom:
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
        ]

    apply_overlays(doc, cfg, overlays)
    doc.save()
    return doc.to_pdf(output_path)
