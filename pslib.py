#!/usr/bin/python3
"""pslib.py v2 — PostScript generation library.

Generates Level 2 PostScript with CP1251 Cyrillic support.
Tables with word wrap, trees with PS lines, text with alignment.

v2: Font metrics cache — ONE GS call per font+size, then instant measurement.
    No more per-string subprocess calls. ~300x faster for large documents.

Usage:
    from pslib import PSDoc
    doc = PSDoc("output.ps", title="My Document")
    doc.font("Helvetica-Bold", 16)
    doc.text(50, 780, "Заглавие")
    doc.table(50, 750, headers=["#", "Име"], rows=[["1", "Иван"]])
    doc.page_number()
    doc.save()
    doc.to_pdf("output.pdf")
"""
import os
import shutil
import subprocess


class PSDoc:
    """PostScript document generator with Cyrillic + table support."""

    A4W = 595  # points
    A4H = 842

    # Standard PS fonts that support Cyrillic via CP1251 re-encoding
    CYRILLIC_FONTS = (
        "Helvetica", "Helvetica-Bold", "Helvetica-Oblique",
        "Helvetica-BoldOblique", "Courier", "Courier-Bold",
        "Times-Roman", "Times-Bold", "Times-Italic",
    )

    def __init__(self, filename, title="Document", margin=50, margin_top=None,
                 margin_bottom=None, margin_right=None, gs_path=None):
        self.filename = filename
        self.title = title
        self.margin = margin  # left margin (also default for hr())
        self.margin_top = margin_top if margin_top is not None else margin
        self.margin_bottom = margin_bottom if margin_bottom is not None else margin
        self.margin_right = margin_right if margin_right is not None else margin
        self.pages = [[]]
        self._fonts_used = set()
        self._current_font = None
        self._current_size = 10
        self._font_paths = {}
        self._metrics = {}  # (font, size) -> [256 floats]
        self._gs = gs_path or shutil.which("gs") or "/usr/bin/gs"

    # ── Font ──────────────────────────────────────────────────────

    def register_font(self, name, ttf_path):
        """Register a TTF font file for embedding."""
        self._font_paths[name] = ttf_path

    def font(self, name, size, cyrillic=True):
        """Set current font and size."""
        self._current_font = name
        self._current_size = size
        self._fonts_used.add(name)
        if cyrillic and name in self.CYRILLIC_FONTS:
            safe = name.replace("-", "_")
            self._cmd(f"/{safe}_Cyr {size} selectfont")
        else:
            self._cmd(f"/{name} {size} selectfont")

    # ── Text ──────────────────────────────────────────────────────

    def text(self, x, y, txt, align="left"):
        """Draw text at (x, y). align: left, center, right."""
        escaped = self._escape_ps(txt)
        if align == "left":
            self._cmd(f"{x} {y} moveto ({escaped}) show")
        elif align == "right":
            self._cmd(f"({escaped}) stringwidth pop neg {x} add {y} moveto ({escaped}) show")
        elif align == "center":
            self._cmd(f"({escaped}) stringwidth pop 2 div neg {x} add {y} moveto ({escaped}) show")

    # ── String measurement (v2: cached font metrics) ─────────────

    def _load_metrics(self, font_name, size):
        """Load all 256 CP1251 character widths in ONE GS call."""
        key = (font_name, size)
        if key in self._metrics:
            return self._metrics[key]

        if font_name in self.CYRILLIC_FONTS:
            ps_font = font_name.replace("-", "_") + "_Cyr"
        else:
            ps_font = font_name

        # Build PS program: re-encode fonts, select font, measure all 256 chars
        ps = self.CP1251_REENCODE + "\n"
        for base in self.CYRILLIC_FONTS:
            safe = base.replace("-", "_")
            ps += f"/{safe}_Cyr /{base} ReEncodeFont\n"
        ps += f"/{ps_font} {size} selectfont\n"
        for i in range(256):
            if i < 32:
                ps += "0 == flush\n"
            else:
                ps += f"(\\{i:03o}) stringwidth pop == flush\n"
        ps += "quit\n"

        result = subprocess.run(
            [self._gs, "-q", "-dBATCH", "-dNOPAUSE", "-dNODISPLAY", "-"],
            input=ps.encode("latin-1", errors="replace"),
            capture_output=True
        )

        widths = []
        for line in result.stdout.decode().strip().split('\n'):
            try:
                widths.append(float(line.strip()))
            except (ValueError, IndexError):
                widths.append(size * 0.5)
        while len(widths) < 256:
            widths.append(size * 0.5)

        self._metrics[key] = widths
        return widths

    def string_width(self, txt):
        """Measure string width using cached font metrics. Instant — no subprocess."""
        font = self._current_font or "Helvetica"
        size = self._current_size or 10
        metrics = self._load_metrics(font, size)
        try:
            return sum(metrics[b] for b in txt.encode('cp1251', errors='replace'))
        except Exception:
            return len(txt) * size * 0.5

    def fits_in(self, txt, max_width):
        """Check if text fits in given width."""
        w = self.string_width(txt)
        return w <= max_width, w

    # ── Lines & Boxes ─────────────────────────────────────────────

    def line(self, x1, y1, x2, y2, width=0.5):
        self._cmd(f"{width} setlinewidth {x1} {y1} moveto {x2} {y2} lineto stroke")

    def rect(self, x, y, w, h, fill=False, gray=0.92, stroke=True, linewidth=0.5):
        self._cmd(f"{linewidth} setlinewidth")
        self._cmd(f"newpath {x} {y} moveto {w} 0 rlineto 0 {h} rlineto {w} neg 0 rlineto closepath")
        if fill:
            self._cmd(f"gsave {gray} setgray fill grestore")
        if stroke:
            self._cmd("stroke")

    def setgray(self, gray):
        self._cmd(f"{gray} setgray")

    def setcolor(self, r, g, b):
        self._cmd(f"{r} {g} {b} setrgbcolor")

    def hr(self, y, x1=None, x2=None):
        self.line(x1 or self.margin, y, x2 or (self.A4W - self.margin), y, 0.5)

    # ── Table ─────────────────────────────────────────────────────

    def table(self, x, y, headers, rows, col_widths=None, font_name=None,
              header_size=9, body_size=8, row_height=14, col_align=None):
        """Draw a table with word-wrapped cells, black header, page breaks."""
        if font_name is None:
            font_name = self._current_font or "Helvetica"
        ncols = len(headers)
        usable_w = self.A4W - 2 * self.margin

        # Auto column widths
        if col_widths is None:
            saved = self._current_font, self._current_size
            self._current_font, self._current_size = font_name, body_size
            col_widths = [self.string_width(h) + 8 for h in headers]
            for row in rows:
                for i, cell in enumerate(row[:ncols]):
                    w = self.string_width(str(cell)) + 8
                    col_widths[i] = max(col_widths[i], w)
            total = sum(col_widths)
            if total > usable_w:
                col_widths = [w * usable_w / total for w in col_widths]
            self._current_font, self._current_size = saved

        table_w = sum(col_widths)
        if col_align is None:
            col_align = ["left"] * ncols
        while len(col_align) < ncols:
            col_align.append("left")

        def ty_offset(sz):
            return (row_height - sz) / 2 + sz * 0.2

        def draw_cell(cx, ty, txt, cw, align):
            if align == "right":
                self.text(cx + cw - 3, ty, txt, align="right")
            elif align == "center":
                self.text(cx + cw / 2, ty, txt, align="center")
            else:
                self.text(cx + 3, ty, txt)

        def draw_header(cy):
            """Black bg, white text, word-wrapped header."""
            self.font(font_name, header_size)
            hdr_lines = []
            max_hdr = 1
            for hi, h in enumerate(headers):
                wrapped = self._wrap_text(str(h), col_widths[hi] - 6)
                hdr_lines.append(wrapped)
                max_hdr = max(max_hdr, len(wrapped))
            hdr_h = row_height * max_hdr

            # Black rectangle
            self._cmd(f"newpath {x} {cy - hdr_h} moveto {table_w} 0 rlineto "
                      f"0 {hdr_h} rlineto {table_w} neg 0 rlineto closepath")
            self._cmd("gsave 0 setgray fill grestore")
            self._cmd("1 setgray")
            self.font(font_name, header_size)

            hcx = x
            for hi in range(ncols):
                hty = cy - row_height + ty_offset(header_size)
                for line in hdr_lines[hi]:
                    draw_cell(hcx, hty, line, col_widths[hi], "center")
                    hty -= row_height
                hcx += col_widths[hi]

            # White inner separators (all internal column borders)
            hcx = x
            for sep in range(ncols - 1):
                hcx += col_widths[sep]
                self.line(hcx, cy - 1, hcx, cy - hdr_h + 1, 0.3)

            # Black bounding box stroke on top — covers white artifacts at edges
            self._cmd("0 setgray")
            self._cmd(f"0.3 setlinewidth newpath {x} {cy - hdr_h} moveto "
                      f"{table_w} 0 rlineto 0 {hdr_h} rlineto "
                      f"{table_w} neg 0 rlineto closepath stroke")
            return cy - hdr_h

        def page_break(cy):
            self.font("Helvetica-Oblique", 6)
            self.text(x, cy - 10, "следва...")
            self.new_page()
            cy = self.A4H - self.margin_top
            self.font("Helvetica-Oblique", 6)
            self.text(x, cy, "...продължава")
            cy -= 10
            cy = draw_header(cy)
            self.font(font_name, body_size)
            return cy

        # Check if header + 2 rows fit
        cy = y
        self.font(font_name, header_size)
        est_hdr = row_height
        for hi, h in enumerate(headers):
            est_hdr = max(est_hdr, row_height * len(self._wrap_text(str(h), col_widths[hi] - 6)))
        if cy - est_hdr - row_height * 2 < self.margin_bottom:
            self.new_page()
            cy = self.A4H - self.margin_top

        cy = draw_header(cy)

        # Body
        self.font(font_name, body_size)
        for row in rows:
            if cy - row_height < self.margin_bottom:
                cy = page_break(cy)

            cell_lines = []
            max_lines = 1
            for i in range(ncols):
                cell = str(row[i]) if i < len(row) else ""
                wrapped = self._wrap_text(cell, col_widths[i] - 6)
                cell_lines.append(wrapped)
                max_lines = max(max_lines, len(wrapped))

            actual_h = row_height * max_lines
            if cy - actual_h < self.margin_bottom:
                cy = page_break(cy)

            cx = x
            for i in range(ncols):
                ty = cy - row_height + ty_offset(body_size)
                for cl in cell_lines[i]:
                    draw_cell(cx, ty, cl, col_widths[i], col_align[i])
                    ty -= row_height
                cx += col_widths[i]

            self._draw_borders(x, cy, col_widths, actual_h)
            cy -= actual_h

        return cy

    def _wrap_text(self, txt, max_width):
        """Word-wrap text. Long words broken by character."""
        if not txt:
            return [""]
        fits, _ = self.fits_in(txt, max_width)
        if fits:
            return [txt]

        lines = []
        current = ""
        for word in txt.split():
            test = f"{current} {word}".strip() if current else word
            fits, _ = self.fits_in(test, max_width)
            if fits:
                current = test
            else:
                if current:
                    lines.append(current)
                fits_word, _ = self.fits_in(word, max_width)
                if fits_word:
                    current = word
                else:
                    # Break long word by character
                    current = ""
                    for ch in word:
                        test_ch = current + ch
                        if self.fits_in(test_ch, max_width)[0]:
                            current = test_ch
                        else:
                            if current:
                                lines.append(current)
                            current = ch
        if current:
            lines.append(current)
        return lines or [""]

    def _draw_borders(self, x, y, col_widths, row_height):
        table_w = sum(col_widths)
        self.line(x, y, x + table_w, y, 0.3)
        self.line(x, y - row_height, x + table_w, y - row_height, 0.3)
        cx = x
        for w in col_widths:
            self.line(cx, y, cx, y - row_height, 0.3)
            cx += w
        self.line(cx, y, cx, y - row_height, 0.3)

    # ── Tree ──────────────────────────────────────────────────────

    def tree(self, x, y, data, font_name=None, font_size=8, indent=15,
             line_height=12, line_width=0.4, root_spacing=6):
        """Draw tree structure with PS connector lines."""
        if font_name is None:
            font_name = self._current_font or "Helvetica"

        flat = self._flatten_tree(data, 0) if data and isinstance(data[0], dict) \
            else self._annotate_last(data)

        self.font(font_name, font_size)
        cy = y
        active = set()
        prev_depth = -1

        for i, (depth, text, is_last) in enumerate(flat):
            if depth == 0 and prev_depth >= 0:
                cy -= root_spacing
                active.clear()

            if cy < self.margin_bottom + 20:
                self.font("Helvetica-Oblique", 6)
                self.text(x, cy - 10, "следва...")
                self.new_page()
                cy = self.A4H - self.margin_top
                self.font("Helvetica-Oblique", 6)
                self.text(x, cy, "...продължава")
                cy -= 12
                self.font(font_name, font_size)
                active.clear()

            tx = x + depth * indent
            mid_y = cy - line_height / 2 + font_size * 0.3

            for d in sorted(active):
                lx = x + d * indent + indent / 2
                self.line(lx, cy + line_height / 2, lx, cy - line_height / 2, line_width)

            if depth > 0:
                lx = x + (depth - 1) * indent + indent / 2
                self.line(lx, cy + line_height / 2, lx, mid_y, line_width)
                self.line(lx, mid_y, tx + 2, mid_y, line_width)
                if is_last:
                    active.discard(depth - 1)
                else:
                    active.add(depth - 1)

            self.text(tx + (indent / 2 + 4 if depth > 0 else 0), cy, text)
            cy -= line_height
            prev_depth = depth

        return cy

    def _flatten_tree(self, nodes, depth):
        flat = []
        for i, node in enumerate(nodes):
            flat.append((depth, node["text"], i == len(nodes) - 1))
            if "children" in node:
                flat.extend(self._flatten_tree(node["children"], depth + 1))
        return flat

    def _annotate_last(self, data):
        if not data:
            return []
        if len(data[0]) == 3:
            return data
        result = []
        for i, (depth, text) in enumerate(data):
            is_last = True
            for j in range(i + 1, len(data)):
                if data[j][0] < depth:
                    break
                if data[j][0] == depth:
                    is_last = False
                    break
            result.append((depth, text, is_last))
        return result

    # ── Page management ───────────────────────────────────────────

    def new_page(self):
        self.pages.append([])

    def page_number(self, y=30, align="right"):
        self._cmd(f"% PAGE_NUMBER_PLACEHOLDER {y} {align}")

    def _cmd(self, ps_command):
        self.pages[-1].append(ps_command)

    # ── PS encoding ───────────────────────────────────────────────

    @staticmethod
    def _escape_ps(txt):
        """Escape PS specials, encode Cyrillic as CP1251 octal."""
        out = []
        for ch in txt:
            if ch == '\\':
                out.append('\\\\')
            elif ch == '(':
                out.append('\\(')
            elif ch == ')':
                out.append('\\)')
            elif ord(ch) > 127:
                try:
                    for byte in ch.encode('cp1251'):
                        out.append(f'\\{byte:03o}')
                except UnicodeEncodeError:
                    out.append('?')
            else:
                out.append(ch)
        return ''.join(out)

    CP1251_REENCODE = """/Win1251Encoding StandardEncoding 256 array copy
dup 192 /afii10017 put % А
dup 193 /afii10018 put % Б
dup 194 /afii10019 put % В
dup 195 /afii10020 put % Г
dup 196 /afii10021 put % Д
dup 197 /afii10022 put % Е
dup 198 /afii10024 put % Ж
dup 199 /afii10025 put % З
dup 200 /afii10026 put % И
dup 201 /afii10027 put % Й
dup 202 /afii10028 put % К
dup 203 /afii10029 put % Л
dup 204 /afii10030 put % М
dup 205 /afii10031 put % Н
dup 206 /afii10032 put % О
dup 207 /afii10033 put % П
dup 208 /afii10034 put % Р
dup 209 /afii10035 put % С
dup 210 /afii10036 put % Т
dup 211 /afii10037 put % У
dup 212 /afii10038 put % Ф
dup 213 /afii10039 put % Х
dup 214 /afii10040 put % Ц
dup 215 /afii10041 put % Ч
dup 216 /afii10042 put % Ш
dup 217 /afii10043 put % Щ
dup 218 /afii10044 put % Ъ
dup 219 /afii10045 put % Ы
dup 220 /afii10046 put % Ь
dup 221 /afii10047 put % Э
dup 222 /afii10048 put % Ю
dup 223 /afii10049 put % Я
dup 224 /afii10065 put % а
dup 225 /afii10066 put % б
dup 226 /afii10067 put % в
dup 227 /afii10068 put % г
dup 228 /afii10069 put % д
dup 229 /afii10070 put % е
dup 230 /afii10072 put % ж
dup 231 /afii10073 put % з
dup 232 /afii10074 put % и
dup 233 /afii10075 put % й
dup 234 /afii10076 put % к
dup 235 /afii10077 put % л
dup 236 /afii10078 put % м
dup 237 /afii10079 put % н
dup 238 /afii10080 put % о
dup 239 /afii10081 put % п
dup 240 /afii10082 put % р
dup 241 /afii10083 put % с
dup 242 /afii10084 put % т
dup 243 /afii10085 put % у
dup 244 /afii10086 put % ф
dup 245 /afii10087 put % х
dup 246 /afii10088 put % ц
dup 247 /afii10089 put % ч
dup 248 /afii10090 put % ш
dup 249 /afii10091 put % щ
dup 250 /afii10092 put % ъ
dup 251 /afii10093 put % ы
dup 252 /afii10094 put % ь
dup 253 /afii10095 put % э
dup 254 /afii10096 put % ю
dup 255 /afii10097 put % я
dup 168 /afii10023 put % Ё
dup 184 /afii10071 put % ё
def

/ReEncodeFont { % /NewName /BaseName ReEncodeFont
  findfont dup length dict begin
    { 1 index /FID ne { def } { pop pop } ifelse } forall
    /Encoding Win1251Encoding def
    currentdict
  end
  definefont pop
} def
"""

    # ── Save & Convert ────────────────────────────────────────────

    def save(self):
        """Write PostScript file."""
        with open(self.filename, "wb") as f:
            def w(s):
                f.write(s.encode("latin-1", errors="replace"))

            w("%!PS-Adobe-3.0\n")
            w(f"%%Title: {self.title}\n")
            w(f"%%Pages: {len(self.pages)}\n")
            w("%%PageOrder: Ascend\n%%DocumentData: Clean7Bit\n%%EndComments\n\n")

            # Prolog: CP1251 re-encoding
            f.write(self.CP1251_REENCODE.encode("latin-1", errors="replace"))
            f.write(b"\n")
            for base in self.CYRILLIC_FONTS:
                safe = base.replace("-", "_")
                f.write(f"/{safe}_Cyr /{base} ReEncodeFont\n".encode("latin-1"))
            f.write(b"\n")

            # Pages
            for page_num, cmds in enumerate(self.pages, 1):
                w(f"\n%%Page: {page_num} {page_num}\n")
                for cmd in cmds:
                    if "PAGE_NUMBER_PLACEHOLDER" in cmd:
                        parts = cmd.split()
                        py, palign = parts[-2], parts[-1]
                        pt = self._escape_ps(f"стр {page_num} от {len(self.pages)}")
                        w(f"/Helvetica_Cyr 7 selectfont\n")
                        if palign == "right":
                            w(f"({pt}) stringwidth pop neg {self.A4W - self.margin_right} add {py} moveto ({pt}) show\n")
                        else:
                            w(f"({pt}) stringwidth pop 2 div neg {self.A4W // 2} add {py} moveto ({pt}) show\n")
                    else:
                        w(cmd + "\n")
                w("showpage\n")
            w("\n%%EOF\n")

    def to_pdf(self, pdf_path=None, font_paths=None):
        """Convert PS to PDF using Ghostscript."""
        if pdf_path is None:
            pdf_path = self.filename.rsplit(".", 1)[0] + ".pdf"

        cmd = [
            self._gs, "-q", "-dBATCH", "-dNOPAUSE",
            "-sDEVICE=pdfwrite", "-dEmbedAllFonts=true",
            "-dSubsetFonts=true", "-sPAPERSIZE=a4",
            f"-sOutputFile={pdf_path}",
        ]

        fpaths = set()
        if font_paths:
            fpaths.update(font_paths)
        for path in self._font_paths.values():
            fpaths.add(os.path.dirname(path))
        # System font dirs
        for d in ("/usr/share/fonts/dejavu", "/usr/share/fonts/noto"):
            if os.path.isdir(d):
                fpaths.add(d)

        if fpaths:
            cmd.append(f"-sFONTPATH={':'.join(fpaths)}")
        cmd.append(self.filename)

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"gs failed: {result.stderr}")
        return pdf_path


# ── Convenience ─────────────────────────────────────────────────

def md_table_to_ps(md_text):
    """Extract tables from markdown text. Returns list of (headers, rows)."""
    tables = []
    lines = md_text.strip().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and "|" in line[1:]:
            headers = [c.strip() for c in line.split("|")[1:-1]]
            i += 1
            if i < len(lines) and all(c in "|- :" for c in lines[i].replace("|", "")):
                i += 1
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip().replace("**", "") for c in lines[i].strip().split("|")[1:-1]]
                rows.append(cells)
                i += 1
            tables.append((headers, rows))
        else:
            i += 1
    return tables


if __name__ == "__main__":
    doc = PSDoc("/tmp/test_pslib.ps", title="pslib v2 test")
    doc.font("Helvetica-Bold", 16)
    doc.text(50, 780, "pslib v2 — Font Metrics Cache")
    doc.hr(770)
    doc.font("Helvetica", 10)
    w = doc.string_width("Тестов текст на кирилица")
    doc.text(50, 750, f"Width of 'Тестов текст на кирилица' = {w:.1f} pt")
    doc.table(50, 720,
              headers=["#", "Име", "Роля", "Дата"],
              rows=[
                  ["1", "Иван Петров", "Инженер", "2025-10-02"],
                  ["2", "Мария Георгиева", "Дизайнер", "2025-10-18"],
              ],
              col_align=["right", "left", "left", "left"])
    doc.page_number()
    doc.save()
    pdf = doc.to_pdf()
    print(f"Metrics loaded: {len(doc._metrics)} font+size combos")
    print(f"PDF: {pdf}")
