#!/usr/bin/python3
"""example.py — Example: Generate a multi-page legal справка PDF using pslib.

Demonstrates: tables, tree, QR code, grid reference, page breaks,
margins, footer line, ISO timestamps, centered headers.

Usage: /usr/bin/python3 example.py
Output: example.ps + example.pdf in same directory.
"""

import os
import random
import string
import subprocess
from datetime import datetime
from pslib import PSDoc, md_table_to_ps

# ── Config ──────────────────────────────────────────────────────
DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PS = os.path.join(DIR, "example.ps")
OUT_PDF = os.path.join(DIR, "example.pdf")

COL1_W = 25      # Fixed "#" column width (all tables)
REF_W = 28       # Fixed "Ref" column width (last column)
EGN_W = 53       # Fixed "ЕГН" column width (10 digits + padding)
DATE_W = 58      # Fixed date column width ("XX.XX.XXXX" + padding)
NOWRAP_HEADERS = {"ЕГН": EGN_W, "Посл.": DATE_W, "#": COL1_W, "Ref": REF_W}
ML = 28          # Left margin 10mm
MR = 14          # Right margin 5mm
MT = 14          # Top margin 5mm
MB = 14          # Bottom margin 5mm
QR_ZONE = 60     # Reserved height for QR + RSC at top of each page
FOOTER_H = 20    # Footer zone height (line + timestamp + page num)
BODY_SZ = 8
HDR_SZ = 9
ROW_H = 14
SECT_GAP = 6
CONTENT_TOP = 842 - MT - QR_ZONE


# ── Sample data ─────────────────────────────────────────────────

SECTIONS = [
    ("Страни по делото", ["#", "Име", "Роля", "ЕГН", "Посл."],
     [["1", "Елена Димитрова Колева", "Ищец, счетоводител", "8503125481", "15.01.2026"],
      ["2", "Георги Стоянов Василев", "Ответник, инженер, Техноком ООД", "8211076320", "22.02.2026"]]),

    ("Деца", ["#", "Име", "Роля", "ЕГН", "Възраст"],
     [["3", "Никола Георгиев Василев", "Син, ученик, 9 клас", "0742156890", "16"],
      ["4", "Калина Георгиева Василева", "Дъщеря, ученичка, 6 клас", "1143028571", "13"]]),

    ("Съдебни състави", ["#", "Име", "Звание/Роля", "Посл."],
     [["5", "Светла Маринова", "Съдия, 22-ри състав, РС Пловдив", "10.01.2026"],
      ["6", "Десислава Тодорова", "Съдия, 45-ти състав, РС Пловдив", "18.02.2026"],
      ["7", "Петър Ангелов", "Секретар на съдия Тодорова", "18.02.2026"]]),

    ("Адвокати", ["#", "Име", "Звание/Роля", "Посл."],
     [["8", "Борислав Найденов", "Адвокат на ищеца", "22.02.2026"],
      ["9", "Красимир Стефанов", "Адвокат на ответника", "22.02.2026"]]),

    ("Свидетели", ["#", "Име", "Звание/Роля", "Посл."],
     [["10", "Мария Петкова", "Съседка, свидетел на инцидента", "05.11.2025"],
      ["11", "Тодор Благоев", "Колега на ответника", "12.11.2025"],
      ["12", "Ивайло Христов", "Приятел на семейството", "20.11.2025"]]),

    ("Полиция", ["#", "Име", "Звание/Роля", "Посл."],
     [["13", "Пламен Костов", "Комисар, началник 03 РУ", "2025"],
      ["14", "Даниела Стоянова", "Разсл. полицай, водещ разследването", "28.12.2025"],
      ["15", "Александър Методиев", "Ст. полицай, заповед за задържане", "18.10.2025"]]),

    ("Съдебна администрация", ["#", "Име", "Роля", "Посл."],
     [["16", "Надежда Кирилова", "Секретар на съдия Тодорова", "01.02.2026"],
      ["17", "Виолета Радева", "Деловодител", "28.10.2025"]]),

    ("Семейство", ["#", "Име", "Роля", "Посл."],
     [["18", "Стоян Василев", "Дядо (баща на ответника)", ""],
      ["19", "Пенка Колева", "Майка на ищеца (финансова подкрепа)", ""]]),
]

TREE = [
    {"text": "РС Пловдив (Районен съд)", "children": [
        {"text": "22-ри състав — съдия Светла Маринова"},
        {"text": "45-ти състав — съдия Десислава Тодорова", "children": [
            {"text": "секретар Надежда Кирилова"},
        ]},
    ]},
    {"text": "ОС Пловдив (Окръжен съд)", "children": [
        {"text": "председател Атанас Георгиев"},
        {"text": "докладчик Мария Стефанова"},
        {"text": "секретар Виолета Радева"},
    ]},
    {"text": "РП Пловдив (Районна прокуратура)", "children": [
        {"text": "Ивана Димова (водещ прокурор)"},
        {"text": "Стефан Колев (представител в съда)"},
    ]},
    {"text": "03 РУ Пловдив", "children": [
        {"text": "комисар Пламен Костов (началник)"},
        {"text": "разсл. полицай Даниела Стоянова"},
        {"text": "ст. полицай Александър Методиев (задържане)"},
    ]},
    {"text": "Техноком ООД", "children": [
        {"text": "инженер Георги Василев"},
    ]},
    {"text": "ПАК (Пловдивска адвокатска колегия)", "children": [
        {"text": "адв. Борислав Найденов (защита на ищеца)"},
        {"text": "адв. Красимир Стефанов (защита на ответника)"},
    ]},
    {"text": "Семейство Василеви-Колеви", "children": [
        {"text": "Георги Стоянов Василев (баща)"},
        {"text": "Елена Димитрова Колева (майка)"},
        {"text": "Никола Георгиев Василев (син, 16г.)"},
        {"text": "Калина Георгиева Василева (дъщеря, 13г.)"},
        {"text": "Стоян Василев (дядо)"},
        {"text": "Пенка Колева (баба по майчина линия)"},
    ]},
]

REF_HEADERS = ["Ref", "Файл", "Стр.", "Квадрант", "Описание"]
REF_ROWS = [
    ["A1", "protokol_01.pdf", "3", "AD07", "Показания на свидетел Петкова"],
    ["A2", "zapoved_24h.pdf", "1", "AB02", "Заповед за задържане"],
    ["-", "-", "-", "-", "(попълва се при анализ)"],
]


# ── Column widths ───────────────────────────────────────────────

def compute_widths(doc, headers, rows):
    """Compute col_widths: no-wrap for ЕГН, dates, #, Ref; rest auto-scaled."""
    ncols = len(headers)
    usable = doc.A4W - ML - MR

    saved = doc._current_font, doc._current_size
    doc._current_font = "Helvetica"
    doc._current_size = BODY_SZ

    fixed_cols = {0: COL1_W, ncols - 1: REF_W}
    for i, h in enumerate(headers):
        if h in NOWRAP_HEADERS:
            fixed_cols[i] = NOWRAP_HEADERS[h]

    widths = [0.0] * ncols
    for i in range(ncols):
        if i in fixed_cols:
            widths[i] = fixed_cols[i]
        else:
            w = doc.string_width(headers[i]) + 10
            for row in rows:
                if i < len(row):
                    rw = doc.string_width(str(row[i])) + 10
                    w = max(w, rw)
            widths[i] = w

    fixed_total = sum(fixed_cols.values())
    remaining = usable - fixed_total
    auto_total = sum(widths[i] for i in range(ncols) if i not in fixed_cols)
    if auto_total > 0:
        scale = remaining / auto_total
        for i in range(ncols):
            if i not in fixed_cols:
                widths[i] *= scale

    doc._current_font, doc._current_size = saved
    return widths


# ── Grid drawing ────────────────────────────────────────────────

def draw_grid_example(doc, x, y, cols=6, rows=4, cell_pt=17):
    """Draw a small checkerboard grid example for the reference spec."""
    doc.font("Helvetica", 5)
    for r in range(rows):
        for c in range(cols):
            gx = x + c * cell_pt
            gy = y + r * cell_pt
            if (r + c) % 2 == 0:
                doc._cmd(f"newpath {gx} {gy} moveto "
                         f"{cell_pt} 0 rlineto 0 {cell_pt} rlineto "
                         f"{cell_pt} neg 0 rlineto closepath "
                         f"gsave 0.88 setgray fill grestore")
            doc._cmd(f"0.2 setlinewidth 0 setgray "
                     f"newpath {gx} {gy} moveto "
                     f"{cell_pt} 0 rlineto 0 {cell_pt} rlineto "
                     f"{cell_pt} neg 0 rlineto closepath stroke")
    for c in range(cols):
        doc.text(x + c * cell_pt + cell_pt / 2, y - 8, "A" + chr(65 + c), align="center")
    for r in range(rows):
        doc.text(x - 12, y + r * cell_pt + cell_pt / 2 - 2, f"{r + 1:02d}")
    doc.font("Helvetica-Bold", 5)
    doc.text(x + 2 * cell_pt + cell_pt / 2, y + 1 * cell_pt + cell_pt / 2 - 2, "AC02", align="center")
    doc.font("Helvetica", 5)
    return y


# ── QR Code ─────────────────────────────────────────────────────

def generate_rsc():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


def qr_matrix(data):
    result = subprocess.run(
        ["/usr/bin/qrencode", "-t", "ASCII", "-m", "0", "-l", "H", data],
        capture_output=True, text=True
    )
    matrix = []
    for line in result.stdout.rstrip('\n').split('\n'):
        row = []
        for i in range(0, len(line), 2):
            row.append(line[i:i+2] == "##")
        matrix.append(row)
    return matrix


# ── Main ────────────────────────────────────────────────────────

def main():
    doc = PSDoc(OUT_PS, title="Справка за лицата (пример)",
                margin=ML, margin_top=MT + QR_ZONE, margin_bottom=MB + FOOTER_H,
                margin_right=MR)

    rsc = generate_rsc()
    iso_date = datetime.now().strftime("%Y-%m-%dT%H:%M")

    # Compute RSC font size to match date width
    rsc_text = f"RSC: {rsc}"
    doc.font("Courier-Bold", 6)
    date_w = doc.string_width(iso_date)
    doc.font("Courier-Bold", 7)
    rsc_w = doc.string_width(rsc_text)
    rsc_sz = 7 * date_w / rsc_w if rsc_w > 0 else 7

    # ── Document header ─────────────────────────────────────────
    doc.font("Helvetica-Bold", 14)
    doc.text(doc.A4W / 2, 790, "СПРАВКА ЗА ЛИЦАТА", align="center")
    doc.font("Helvetica", 10)
    doc.text(doc.A4W / 2, 775, "по преписка 12345/2025, РП Пловдив", align="center")

    cy = 758

    # ── Tables ──────────────────────────────────────────────────
    sect_num = 0
    for title, headers, rows in SECTIONS:
        sect_num += 1
        hdrs = [h.replace("Последно", "Посл.") for h in headers] + ["Ref"]
        rws = [row + ["-"] for row in rows]

        needed = SECT_GAP + HDR_SZ + 4 + ROW_H * min(2, len(rws) + 1)
        if cy - needed < MB + FOOTER_H:
            doc.new_page()
            cy = CONTENT_TOP

        cy -= SECT_GAP
        doc.font("Helvetica-Bold", HDR_SZ)
        doc.text(ML, cy, f"{sect_num:02d} — {title}")
        cy -= HDR_SZ + 2

        cw = compute_widths(doc, hdrs, rws)
        align = []
        for h in hdrs:
            if h == "#":
                align.append("right")
            elif h in ("Посл.", "ЕГН", "Ref"):
                align.append("center")
            else:
                align.append("left")

        cy = doc.table(ML, cy, hdrs, rws,
                       col_widths=cw, font_name="Helvetica",
                       header_size=HDR_SZ, body_size=BODY_SZ,
                       row_height=ROW_H, col_align=align)
        cy -= 8

    # ── Tree ────────────────────────────────────────────────────
    sect_num += 1
    needed = SECT_GAP + HDR_SZ + 4 + 10 * 5
    if cy - needed < MB + FOOTER_H:
        doc.new_page()
        cy = CONTENT_TOP

    cy -= SECT_GAP
    doc.font("Helvetica-Bold", HDR_SZ)
    doc.text(ML, cy, f"{sect_num:02d} — Институции (дървовидна структура)")
    cy -= 3
    doc.hr(cy, ML, doc.A4W - MR)
    cy -= 9

    cy = doc.tree(ML, cy, TREE, font_name="Helvetica", font_size=7,
                  indent=12, line_height=10, root_spacing=6)
    cy -= 12

    # ── Reference table ─────────────────────────────────────────
    sect_num += 1
    if cy - 80 < MB + FOOTER_H:
        doc.new_page()
        cy = CONTENT_TOP

    cy -= SECT_GAP
    doc.font("Helvetica-Bold", HDR_SZ)
    doc.text(ML, cy, f"{sect_num:02d} — Референции")
    cy -= HDR_SZ + 2

    ref_cw = [30, 120, 30, 50, doc.A4W - ML - MR - 230]
    cy = doc.table(ML, cy, REF_HEADERS, REF_ROWS,
                   col_widths=ref_cw, font_name="Helvetica",
                   header_size=HDR_SZ, body_size=BODY_SZ,
                   row_height=ROW_H,
                   col_align=["left", "left", "right", "left", "left"])
    cy -= 16

    # ── Grid specification ──────────────────────────────────────
    if cy - 120 < MB + FOOTER_H:
        doc.new_page()
        cy = CONTENT_TOP

    doc.font("Helvetica-Bold", 8)
    doc.text(ML, cy, "Спецификация за индексиране на хартиена информация")
    cy -= 12

    doc.font("Helvetica", 7)
    for sl in [
        "Грид 10x10 мм върху A4 (210x297 мм). Колони AA-AU (ляво-дясно), редове 01-29 (долу-горе).",
        "Двубуквените колони и цифровите редове са взаимно еднозначни — AC02 или 02AC е едно и също.",
        "Шахматно разположение за визуална ориентация. Начало: долу ляво (AA01).",
    ]:
        doc.text(ML, cy, sl)
        cy -= 10
    cy -= 6

    grid_bottom = cy - 4 * 17
    if grid_bottom < MB + FOOTER_H + 20:
        doc.new_page()
        cy = CONTENT_TOP
    draw_grid_example(doc, ML + 15, cy - 4 * 17, cols=6, rows=4, cell_pt=17)
    cy = cy - 4 * 17 - 8

    legend_x = ML + 15 + 6 * 17 + 10
    legend_y = cy + 4 * 17
    doc.font("Helvetica", 6)
    doc.text(legend_x, legend_y - 5, "Пример: AC02 = колона AC, ред 02")
    doc.text(legend_x, legend_y - 13, "Буквите винаги са колона, цифрите — ред.")

    # ── Footer text ─────────────────────────────────────────────
    cy -= 12
    doc.font("Helvetica-Oblique", 7)
    doc.text(ML, cy, "19 лица, 7 институции.")

    # ── Per-page: QR, footer line, timestamp, page numbers ──────
    iso_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    total_pages = len(doc.pages)
    for pg_idx in range(total_pages):
        cmds = doc.pages[pg_idx]
        if not any("PAGE_NUMBER_PLACEHOLDER" in c for c in cmds):
            cmds.append(f"% PAGE_NUMBER_PLACEHOLDER {MB + 2} right")

        # Footer line
        footer_line_y = MB + FOOTER_H - 4
        cmds.append(f"0.3 setlinewidth {ML} {footer_line_y} moveto "
                    f"{doc.A4W - MR - ML} 0 rlineto stroke")
        # ISO timestamp
        ts_escaped = doc._escape_ps(iso_ts)
        cmds.append(f"/Helvetica_Cyr 6 selectfont")
        cmds.append(f"{ML} {MB} moveto ({ts_escaped}) show")

        # QR code top-right
        pg_num = pg_idx + 1
        pg_matrix = qr_matrix(f"RSC:{rsc}/{pg_num}")
        qr_mod = 1.8
        qr_sz = len(pg_matrix) * qr_mod
        qr_px = doc.A4W - MR - qr_sz
        qr_py = doc.A4H - MT
        for r, row in enumerate(pg_matrix):
            for c, black in enumerate(row):
                if black:
                    px = qr_px + c * qr_mod
                    py = qr_py - (r + 1) * qr_mod
                    cmds.append(f"newpath {px} {py} moveto "
                                f"{qr_mod} 0 rlineto 0 {qr_mod} rlineto "
                                f"{qr_mod} neg 0 rlineto closepath fill")
        # White circle + SC label
        cx = qr_px + qr_sz / 2
        cy_c = qr_py - qr_sz / 2
        lbl_sz = qr_mod * 3.5
        lw_est = lbl_sz * 1.2
        radius = max(lw_est / 2, lbl_sz / 2) + 2.5
        cmds.append(f"gsave 1 setgray newpath "
                    f"{cx} {cy_c} {radius} 0 360 arc closepath fill grestore")
        cmds.append("0 setgray")
        sc_escaped = doc._escape_ps("SC")
        ty_sc = cy_c - lbl_sz * 0.35
        cmds.append(f"/Helvetica_Bold_Cyr {lbl_sz} selectfont")
        cmds.append(f"({sc_escaped}) stringwidth pop 2 div neg {cx} add {ty_sc} moveto ({sc_escaped}) show")

        # RSC + date left of QR
        lx = qr_px - 5
        rsc_label = doc._escape_ps(f"RSC: {rsc}")
        date_label = doc._escape_ps(iso_date)
        cmds.append(f"/Courier_Bold_Cyr {rsc_sz} selectfont")
        rsc_y = qr_py - rsc_sz
        cmds.append(f"({rsc_label}) stringwidth pop neg {lx} add {rsc_y} moveto ({rsc_label}) show")
        cmds.append(f"/Courier_Bold_Cyr 6 selectfont")
        cmds.append(f"({date_label}) stringwidth pop neg {lx} add {rsc_y - 9} moveto ({date_label}) show")

    # ── Save ────────────────────────────────────────────────────
    doc.save()
    pdf = doc.to_pdf(OUT_PDF)
    print(f"Generated: {pdf}")
    print(f"Pages: {len(doc.pages)}")
    print(f"Metrics: {len(doc._metrics)} font+size combos")


if __name__ == "__main__":
    main()
