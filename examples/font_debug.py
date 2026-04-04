#!/usr/bin/python3
"""font_debug.py — CP1251 Glyph Map for any PS font.

Generates a 16x16 grid showing all 256 byte positions in the
Win1251 re-encoded font. Useful for debugging character encoding,
finding glyph positions, and verifying Cyrillic mapping.

Usage:
    python3 font_debug.py [font_name]

    font_name: PostScript font name (default: Helvetica)
    Examples: Helvetica, Courier, Times-Roman, Helvetica-Bold

Output: font_debug.ps + font_debug.pdf
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pslib import PSDoc

DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PS = os.path.join(DIR, "font_debug.ps")
OUT_PDF = os.path.join(DIR, "font_debug.pdf")

# Grid layout
ML = 42
X0 = 52       # grid left edge
Y0 = 740      # grid top
CELL_W = 32
CELL_H = 32
GLYPH_SZ = 14
HDR_ROW = 8   # row/col header font size

# Special positions to highlight
HIGHLIGHTS = {
    149: ('bullet', 0.85),
    168: ('Ё', 0.90),
    177: ('plusminus', 0.85),
    184: ('ё', 0.90),
}


def main():
    font_name = sys.argv[1] if len(sys.argv) > 1 else "Helvetica"
    safe_name = font_name.replace("-", "_")
    cyr_name = f"{safe_name}_Cyr"

    doc = PSDoc(OUT_PS, title=f"Font Debug — {font_name}",
                margin=ML, margin_top=50, margin_bottom=40, margin_right=20)

    iso_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    cmds = doc.pages[0]

    # ── Header ─────────────────────────────────────────────────
    cmds.append(f"/{cyr_name} 16 selectfont")
    cmds.append(f"297 800 moveto ({doc._escape_ps(f'CP1251 Glyph Map — {font_name}')}) "
                f"dup stringwidth pop 2 div neg 0 rmoveto show")

    cmds.append(f"/Helvetica_Cyr 8 selectfont")
    cmds.append(f"297 784 moveto ({doc._escape_ps('Win1251 re-encoded — all 256 byte positions')}) "
                f"dup stringwidth pop 2 div neg 0 rmoveto show")

    cmds.append(f"/Helvetica_Cyr 7 selectfont")
    info = f"Font: {font_name}  |  Encoding: CP1251+StandardEncoding  |  {iso_ts}"
    cmds.append(f"297 770 moveto ({doc._escape_ps(info)}) "
                f"dup stringwidth pop 2 div neg 0 rmoveto show")

    # Divider line
    cmds.append(f"0.5 setlinewidth {ML} 762 moveto {595 - 20 - ML} 0 rlineto stroke")

    # ── Column headers (x0..xF) ────────────────────────────────
    cmds.append(f"/Courier_Bold_Cyr {HDR_ROW} selectfont")
    for c in range(16):
        cx = X0 + c * CELL_W + CELL_W / 2
        label = f"x{c:X}"
        cmds.append(f"({label}) stringwidth pop 2 div neg {cx} add "
                     f"{Y0 + 8} moveto ({label}) show")

    # ── Grid ───────────────────────────────────────────────────
    for row in range(16):
        y = Y0 - (row + 1) * CELL_H

        # Row header
        cmds.append(f"/Courier_Bold_Cyr {HDR_ROW} selectfont")
        label = f"{row:X}x"
        cmds.append(f"({label}) stringwidth pop neg {X0 - 4} add "
                     f"{y + CELL_H / 2 - 3} moveto ({label}) show")

        for col in range(16):
            pos = row * 16 + col
            x = X0 + col * CELL_W

            # Highlight special positions
            if pos in HIGHLIGHTS:
                _, gray = HIGHLIGHTS[pos]
                cmds.append(f"{gray} setgray newpath {x + 0.5} {y + 0.5} moveto "
                            f"{CELL_W - 1} 0 rlineto 0 {CELL_H - 1} rlineto "
                            f"{CELL_W - 1} neg 0 rlineto closepath fill")
                cmds.append("0 setgray")

            # Cell border
            cmds.append(f"0.2 setlinewidth newpath {x} {y} moveto "
                        f"{CELL_W} 0 rlineto 0 {CELL_H} rlineto "
                        f"{CELL_W} neg 0 rlineto closepath stroke")

            # Position number (top-left, small, gray)
            cmds.append(f"0.45 setgray /Helvetica findfont 4 scalefont setfont")
            cmds.append(f"{x + 1.5} {y + CELL_H - 5} moveto ({pos}) show")
            cmds.append("0 setgray")

            # The actual glyph
            if pos >= 32:
                cx = x + CELL_W / 2
                cmds.append(f"/{cyr_name} {GLYPH_SZ} selectfont")
                cmds.append(f"(\\{pos:03o}) stringwidth pop 2 div neg "
                            f"{cx} add {y + 7} moveto (\\{pos:03o}) show")

    # ── Legend ─────────────────────────────────────────────────
    legend_y = Y0 - 16 * CELL_H - 20

    cmds.append(f"/Helvetica_Bold_Cyr 8 selectfont")
    cmds.append(f"{X0} {legend_y} moveto (Legend) show")
    legend_y -= 12

    cmds.append(f"/Helvetica_Cyr 7 selectfont")
    for pos, (name, gray) in sorted(HIGHLIGHTS.items()):
        # Color swatch
        cmds.append(f"{gray} setgray newpath {X0} {legend_y - 1} moveto "
                    f"8 0 rlineto 0 8 rlineto -8 0 rlineto closepath fill")
        cmds.append("0 setgray")
        cmds.append(f"0.2 setlinewidth newpath {X0} {legend_y - 1} moveto "
                    f"8 0 rlineto 0 8 rlineto -8 0 rlineto closepath stroke")
        cmds.append(f"/Helvetica_Cyr 7 selectfont")
        cmds.append(f"{X0 + 12} {legend_y} moveto "
                    f"(pos {pos} = /{name}) show")
        legend_y -= 11

    legend_y -= 6
    cmds.append(f"/Helvetica_Cyr 7 selectfont")
    cmds.append(f"{X0} {legend_y} moveto "
                f"(Positions 0-31: control chars \\(not shown\\). "
                f"192-255: Cyrillic A-\\377.) show")
    legend_y -= 10
    cmds.append(f"{X0} {legend_y} moveto "
                f"(Re-encoding: StandardEncoding + Win1251 overrides "
                f"\\(192-255, 168, 184, 149, 177\\).) show")

    # ── Footer ─────────────────────────────────────────────────
    cmds.append(f"0.3 setlinewidth {ML} 38 moveto {595 - 20 - ML} 0 rlineto stroke")
    cmds.append(f"/Helvetica_Cyr 6 selectfont")
    cmds.append(f"{ML} 28 moveto ({doc._escape_ps(iso_ts)}) show")
    cmds.append(f"(pslib font debug) stringwidth pop neg {595 - 20} add 28 moveto "
                f"(pslib font debug) show")

    doc.save()
    pdf = doc.to_pdf(OUT_PDF)
    print(f"Generated: {pdf}")
    print(f"Font: {font_name} ({cyr_name})")


if __name__ == "__main__":
    main()
