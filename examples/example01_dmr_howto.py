#!/usr/bin/python3
"""example01_dmr_howto.py — Markdown to PDF converter via pslib.

Demonstrates pslib capabilities:
  - Markdown parser (headings, bullets, numbered lists, code blocks, tables)
  - Multi-page document with automatic page breaks
  - Section numbering (01 --, 02 --, ...)
  - Code blocks with gray background
  - Per-page QR code with RSC reference and SC logo
  - DRAFT watermark overlay
  - Footer with ISO timestamp and page numbers

Usage:
    python3 example01_dmr_howto.py [input.md]

If no input file given, uses a built-in DMR technical document.
Output: example01.ps + example01.pdf
"""

import os
import re
import math
import random
import string
from datetime import datetime

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pslib import PSDoc

DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PS = os.path.join(DIR, "example01.ps")
OUT_PDF = os.path.join(DIR, "example01.pdf")

# SCteam standard margins
ML = 42    # 15mm left (binding)
MR = 23    # 8mm right
MT = 36    # 12.7mm top (gripper)
MB = 36    # 12.7mm bottom (gripper)
QR_ZONE = 60
FOOTER_H = 20

# Font sizes
TITLE_SZ = 16
H2_SZ = 12
H3_SZ = 10
H4_SZ = 9
BODY_SZ = 8
CODE_SZ = 7
BULLET_SZ = 8
TABLE_HDR_SZ = 8
TABLE_BODY_SZ = 7

LINE_H = 11
CODE_LINE_H = 9
SECTION_GAP = 6
SUBSECTION_GAP = 4

CONTENT_W = 595 - ML - MR


def generate_rsc():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


def qr_matrix(data):
    try:
        import qrcode
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H,
                           box_size=1, border=0)
        qr.add_data(data)
        qr.make()
        return qr.get_matrix()
    except ImportError:
        return None


# ── Built-in demo content ──────────────────────────────────────

BUILTIN_MD = r"""# DMR с HackRF + GnuRadio — Практическо ръководство

## Обща информация

**DMR** (Digital Mobile Radio) е TDMA цифров протокол за радиовръзка.
Използва **4FSK** модулация в 12.5 kHz канал.

### Основни параметри
- Модулация: 4FSK (4-level Frequency Shift Keying)
- Девиация: ±1944 Hz (външни нива), ±648 Hz (вътрешни нива)
- Символна скорост: 4800 символа/сек
- Битрейт: 9600 bps
- TDMA: 2 timeslot-а по 30ms (60ms frame)
- Канална ширина: 12.5 kHz

### Наличен хардуер
- HackRF One — SDR трансивър (TX/RX, 1 MHz - 6 GHz, 20 MHz bandwidth)
- Baofeng DM-32UV — DMR радиостанция (приемник за тест)
- MMDVM Hotspot — RPi + AD чипове + STM32 (вкъщи)
- DMR ID: 2840765 (LZ1CCM)

---

## DMR Voice vs DMR Data

### Voice — изисква AMBE+2 кодек
- AMBE+2 е патентован кодек на DVSI (Digital Voice Systems Inc.)
- HR-C6000 чипът в Баофенга декодира AMBE+2 хардуерно
- Без AMBE+2 кодиране не може да се предава voice към стандартен DMR приемник

### Data — НЕ изисква AMBE+2
- DMR SMS, GPS, APRS — чист binary/text протокол
- Payload е в Data Header + Data Blocks, без voice кодек
- Напълно реалистично с HackRF + GnuRadio!

| Тип | AMBE+2 | Payload | Burst type |
|-----|--------|---------|------------|
| Voice | Задължителен | Vocoder битове | Voice LC |
| Data | НЕ | Binary/text | Data Header + Data Blocks |

---

## DMR протокол стек

### Физически слой (Layer 1)
- 4FSK модулация
- 4 символни нива, map-нати към ±1944 Hz и ±648 Hz
- Символ → бит mapping: +3→11, +1→01, -1→00, -3→10

### Data Link слой (Layer 2)
- CACH (Common Announcement Channel) — 24 бита, sync
- Data Header — source ID, dest ID, data type, blocks to follow
- Data Blocks — payload с FEC

### DMR Frame структура (60ms)
```
|--- Slot 1 (30ms) ---|--- Slot 2 (30ms) ---|
|  CACH | Payload | CACH | Payload           |
```

Всеки burst е 264 бита (54 + 12 + 54 + SYNC/EMB + 54 + 12 + 54)

### Sync Patterns — MS_DATA vs BS_DATA

DMR ползва 48-битови sync patterns в средата на всеки burst (битове 108-155).

| Pattern | Hex | Кой излъчва | Кога |
|---------|-----|-------------|------|
| BS_DATA | D5 D7 F7 7F D7 57 | Базова станция (repeater) | BS препраща data към MS |
| MS_DATA | 7F 7D 5D D5 7D FD | Мобилна станция (радио) | MS изпраща data |
| BS_VOICE | 75 5F D7 DF 75 F7 | Базова станция | BS препраща voice |
| MS_VOICE | 7D FF D5 F5 5D 57 | Мобилна станция | MS изпраща voice |

---

## Hard Decision vs Soft Decision декодиране

### Какво е Hard Decision?

Goertzel детекторът измерва енергията на 4-те FSK тона (±648, ±1944 Hz) за всеки символен период и избира тона с най-силна енергия. Резултатът е категоричен: "+3", "+1", "-1" или "-3". Това е hard decision — няма колебание, няма степен на сигурност.

Пример при шумен сигнал:
```
Goertzel енергии за 1 символ:
  +1944 Hz: 0.45   <- избран -> символ = +3
  +648 Hz:  0.41   <- почти същото! Може да е +1
  -648 Hz:  0.08
  -1944 Hz: 0.06
```

Hard decision: "+3". Но реално е 50/50 между +3 и +1.

### Какво е Soft Decision?

При soft decision вместо категорично 0/1 подаваме вероятност на всеки бит:
- "Този бит е 1 с 95% сигурност" — надежден
- "Този бит е 0 с 52% сигурност" — почти случаен

### Как се прилага към DMR BPTC(196,96)?

BPTC матрицата е 13 реда x 15 колони:
- Редове: Hamming(15,11) — 11 data + 4 parity
- Колони: Hamming(13,9) — 9 data + 4 parity
- Turbo итерация: редове → колони → редове

### LLR от Goertzel енергии

```
За символ с 4 тона, енергии E[0..3] (за -3, -1, +1, +3):

P(sym=k) = E[k] / sum(E[i])   (нормализирана вероятност)

За MSB (знак): P(MSB=0) = P(+1) + P(+3), P(MSB=1) = P(-1) + P(-3)
За LSB (амплитуда): P(LSB=0) = P(+1) + P(-1), P(LSB=1) = P(+3) + P(-3)

LLR = ln(P(bit=0) / P(bit=1))
  LLR > 0 -> бит вероятно = 0
  LLR < 0 -> бит вероятно = 1
  |LLR| голямо -> висока сигурност
  |LLR| ~ 0 -> ниска сигурност
```

### DMR dibit mapping

```
Символ -> Dibit (MSB, LSB):
  +3 -> (0, 1)    +1944 Hz, outer positive
  +1 -> (0, 0)    +648 Hz, inner positive
  -1 -> (1, 0)    -648 Hz, inner negative
  -3 -> (1, 1)    -1944 Hz, outer negative

MSB = знак (0 = положителен, 1 = отрицателен)
LSB = амплитуда (0 = inner ±648, 1 = outer ±1944)
```

---

## Следващи стъпки

1. DMR RX декодер — тест с IQ файлове
2. Soft decision BPTC decode
3. DMR SMS TX flowgraph
4. Тест с Баофенг приемник
"""


def parse_markdown(text):
    """Parse markdown text into structured blocks."""
    lines = text.split('\n')
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            blocks.append(('blank', ''))
            i += 1
            continue

        if stripped.startswith('#### '):
            blocks.append(('h4', stripped[5:].strip()))
            i += 1; continue
        if stripped.startswith('### '):
            blocks.append(('h3', stripped[4:].strip()))
            i += 1; continue
        if stripped.startswith('## '):
            blocks.append(('h2', stripped[3:].strip()))
            i += 1; continue
        if stripped.startswith('# '):
            blocks.append(('title', stripped[2:].strip()))
            i += 1; continue

        if stripped == '---':
            blocks.append(('hr', ''))
            i += 1; continue

        if stripped.startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i].rstrip())
                i += 1
            i += 1
            blocks.append(('code', code_lines))
            continue

        if stripped.startswith('|') and '|' in stripped[1:]:
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            headers = [c.strip() for c in table_lines[0].split('|')[1:-1]]
            rows = []
            for tl in table_lines[2:]:
                cells = [c.strip().replace('**', '')
                         for c in tl.split('|')[1:-1]]
                rows.append(cells)
            blocks.append(('table', (headers, rows)))
            continue

        if stripped.startswith('- ') or stripped.startswith('* '):
            blocks.append(('bullet', stripped[2:].strip()))
            i += 1; continue

        m = re.match(r'^(\d+)\.\s+(.+)', stripped)
        if m:
            blocks.append(('numbered', (m.group(1), m.group(2).strip())))
            i += 1; continue

        blocks.append(('text', stripped))
        i += 1

    return blocks


def clean_md(text):
    """Remove markdown bold/italic/code markers."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    return text


def main():
    # Read markdown source
    md_file = sys.argv[1] if len(sys.argv) > 1 else None
    if md_file and os.path.isfile(md_file):
        with open(md_file, 'r', encoding='utf-8') as f:
            md_text = f.read()
        print(f"Reading: {md_file}")
    else:
        md_text = BUILTIN_MD
        print("Using built-in DMR HOWTO content")

    blocks = parse_markdown(md_text)

    doc = PSDoc(OUT_PS, title="DMR HOWTO",
                margin=ML, margin_top=MT + QR_ZONE,
                margin_bottom=MB + FOOTER_H,
                margin_right=MR)

    rsc = generate_rsc()
    iso_date = datetime.now().strftime("%Y-%m-%dT%H:%M")
    iso_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    bottom_limit = MB + FOOTER_H + 10

    cy = 842 - MT - QR_ZONE
    section_num = 0

    for block_type, content in blocks:

        if block_type == 'title':
            doc.font("Helvetica-Bold", TITLE_SZ)
            doc.text(doc.A4W / 2, cy, clean_md(content), align="center")
            cy -= TITLE_SZ + 4
            doc.font("Helvetica", 8)
            doc.text(doc.A4W / 2, cy, "LZ1CCM / smooker / SCteam", align="center")
            cy -= 10
            doc.font("Helvetica", 7)
            doc.text(doc.A4W / 2, cy, iso_date, align="center")
            cy -= 12
            doc.hr(cy, ML, doc.A4W - MR)
            cy -= SECTION_GAP
            continue

        if block_type == 'h2':
            section_num += 1
            if cy - H2_SZ - LINE_H * 3 < bottom_limit:
                doc.new_page()
                cy = 842 - MT - QR_ZONE
            cy -= SECTION_GAP
            # Line across full width
            line_y = cy - H2_SZ * 0.3
            doc.hr(line_y, ML, doc.A4W - MR)
            # White rect behind text, then text on top of line
            doc.font("Helvetica-Bold", H2_SZ)
            label = f"{section_num:02d} -- {clean_md(content)}"
            tw = doc.string_width(label)
            # White background: 4pt padding around text
            doc.rect(ML - 1, line_y - H2_SZ * 0.4, tw + 8, H2_SZ + 4,
                     fill=True, gray=1.0, stroke=False)
            doc.setgray(0)
            doc.font("Helvetica-Bold", H2_SZ)
            doc.text(ML + 2, line_y - H2_SZ * 0.3, label)
            cy = line_y - H2_SZ - 4
            continue

        if block_type == 'h3':
            if cy - H3_SZ - LINE_H * 2 < bottom_limit:
                doc.new_page()
                cy = 842 - MT - QR_ZONE
            cy -= SUBSECTION_GAP
            doc.font("Helvetica-Bold", H3_SZ)
            doc.text(ML + 5, cy, clean_md(content))
            cy -= H3_SZ + 3
            continue

        if block_type == 'h4':
            if cy - H4_SZ - LINE_H * 2 < bottom_limit:
                doc.new_page()
                cy = 842 - MT - QR_ZONE
            cy -= 3
            doc.font("Helvetica-Bold", H4_SZ)
            doc.text(ML + 10, cy, clean_md(content))
            cy -= H4_SZ + 2
            continue

        if block_type == 'text':
            text = clean_md(content)
            doc.font("Helvetica", BODY_SZ)
            lines = doc._wrap_text(text, CONTENT_W)
            for line in lines:
                if cy < bottom_limit:
                    doc.new_page()
                    cy = 842 - MT - QR_ZONE
                doc.text(ML, cy, line)
                cy -= LINE_H
            continue

        if block_type == 'bullet':
            text = clean_md(content)
            if cy < bottom_limit:
                doc.new_page()
                cy = 842 - MT - QR_ZONE
            doc.font("Helvetica", BULLET_SZ)
            lines = doc._wrap_text(text, CONTENT_W - 12)
            doc.text(ML + 8, cy, "\u2022 " + lines[0])
            cy -= LINE_H
            for extra in lines[1:]:
                doc.text(ML + 14, cy, extra)
                cy -= LINE_H
            continue

        if block_type == 'numbered':
            num, text = content
            text = clean_md(text)
            if cy < bottom_limit:
                doc.new_page()
                cy = 842 - MT - QR_ZONE
            doc.font("Helvetica-Bold", BULLET_SZ)
            doc.text(ML + 5, cy, f"{num}.")
            doc.font("Helvetica", BULLET_SZ)
            lines = doc._wrap_text(text, CONTENT_W - 20)
            doc.text(ML + 18, cy, lines[0])
            cy -= LINE_H
            for extra in lines[1:]:
                doc.text(ML + 18, cy, extra)
                cy -= LINE_H
            continue

        if block_type == 'code':
            code_lines = content
            if cy - CODE_LINE_H * 3 < bottom_limit:
                doc.new_page()
                cy = 842 - MT - QR_ZONE
            cy -= 2
            # Count lines that fit
            avail = int((cy - bottom_limit) / CODE_LINE_H)
            n_lines = min(len(code_lines), max(avail, 2))
            bg_h = n_lines * CODE_LINE_H + 4
            doc.rect(ML, cy - bg_h, CONTENT_W, bg_h,
                     fill=True, gray=0.94, stroke=True, linewidth=0.3)
            doc.setgray(0)
            doc.font("Courier", CODE_SZ)
            code_y = cy - CODE_LINE_H + 1
            for cl in code_lines:
                if code_y < bottom_limit:
                    doc.new_page()
                    cy = 842 - MT - QR_ZONE
                    code_y = cy - CODE_LINE_H + 1
                    remaining_cl = code_lines[code_lines.index(cl):]
                    bg_h2 = min(len(remaining_cl) * CODE_LINE_H + 4,
                                cy - bottom_limit)
                    doc.rect(ML, cy - bg_h2, CONTENT_W, bg_h2,
                             fill=True, gray=0.94, stroke=True, linewidth=0.3)
                    doc.setgray(0)
                    doc.font("Courier", CODE_SZ)
                if len(cl) > 90:
                    cl = cl[:87] + "..."
                doc.text(ML + 4, code_y, cl)
                code_y -= CODE_LINE_H
            cy = code_y - 2
            continue

        if block_type == 'table':
            headers, rows = content
            if cy - TABLE_HDR_SZ - 13 * 3 < bottom_limit:
                doc.new_page()
                cy = 842 - MT - QR_ZONE
            cy -= 4
            cy = doc.table(ML, cy, headers, rows,
                           font_name="Helvetica",
                           header_size=TABLE_HDR_SZ,
                           body_size=TABLE_BODY_SZ,
                           row_height=13,
                           col_align=["left"] * len(headers))
            cy -= 6
            continue

        if block_type == 'hr':
            # Skip — h2 sections already draw their own line
            cy -= 2
            continue

        if block_type == 'blank':
            cy -= 1  # minimal spacing for blanks
            continue

    # ── Per-page overlays ──────────────────────────────────────
    total_pages = len(doc.pages)
    wm_angle = math.degrees(math.atan2(doc.A4H, doc.A4W))

    # RSC font size
    doc.font("Courier-Bold", 6)
    date_w = doc.string_width(iso_date)
    doc.font("Courier-Bold", 7)
    rsc_w = doc.string_width(f"RSC: {rsc}")
    rsc_sz = 7 * date_w / rsc_w if rsc_w > 0 else 7

    for pg_idx in range(total_pages):
        cmds = doc.pages[pg_idx]

        # DRAFT watermark
        wm = [
            "gsave", "0.92 setgray",
            "/Helvetica_Bold_Cyr findfont 140 scalefont setfont",
            f"{doc.A4W / 2} {doc.A4H / 2 - 40} translate",
            f"{wm_angle} rotate",
            "0 0 moveto (DRAFT) dup stringwidth pop 2 div neg 0 rmoveto show",
            "grestore",
        ]
        for i, cmd in enumerate(wm):
            cmds.insert(i, cmd)

        # Footer
        footer_y = MB + FOOTER_H - 4
        cmds.append(f"0.3 setlinewidth {ML} {footer_y} moveto "
                    f"{doc.A4W - MR - ML} 0 rlineto stroke")
        ts_esc = doc._escape_ps(iso_ts)
        cmds.append(f"/Helvetica_Cyr 6 selectfont")
        cmds.append(f"{ML} {MB} moveto ({ts_esc}) show")
        pn_esc = doc._escape_ps(f"p. {pg_idx + 1}/{total_pages}")
        cmds.append(f"({pn_esc}) stringwidth pop neg "
                    f"{doc.A4W - MR} add {MB} moveto ({pn_esc}) show")

        # QR code top-right
        pg_matrix = qr_matrix(f"RSC:{rsc}/{pg_idx + 1}")
        if pg_matrix:
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

            lx = qr_px - 5
            rsc_label = doc._escape_ps(f"RSC: {rsc}")
            date_label = doc._escape_ps(iso_date)
            cmds.append(f"/Courier_Bold_Cyr {rsc_sz} selectfont")
            rsc_y = qr_py - rsc_sz
            cmds.append(f"({rsc_label}) stringwidth pop neg "
                        f"{lx} add {rsc_y} moveto ({rsc_label}) show")
            cmds.append(f"/Courier_Bold_Cyr 6 selectfont")
            cmds.append(f"({date_label}) stringwidth pop neg "
                        f"{lx} add {rsc_y - 9} moveto ({date_label}) show")

    doc.save()
    pdf = doc.to_pdf(OUT_PDF)
    print(f"Generated: {pdf}")
    print(f"Pages: {total_pages}")


if __name__ == "__main__":
    main()
