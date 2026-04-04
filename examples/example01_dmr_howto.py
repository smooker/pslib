#!/usr/bin/python3
"""example01_dmr_howto.py — Markdown to PDF via md2ps + pslib.

Demonstrates md2ps module: parse markdown, measure blocks, render with
automatic page breaks, QR code, footer. Uses built-in DMR HOWTO content
or reads from file argument.

Usage:
    python3 example01_dmr_howto.py [input.md]

Output: example01.ps + example01.pdf
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pslib import PSDoc
from md2ps import (parse_markdown, measure_block, measure_section,
                   render_block, apply_overlays, generate_rsc, MdConfig)

DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PS = os.path.join(DIR, "example01.ps")
OUT_PDF = os.path.join(DIR, "example01.pdf")

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
|  CACH | Payload | CACH | Payload          |
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


def main():
    cfg = MdConfig()

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
                margin=cfg.margin_left,
                margin_top=cfg.margin_top + cfg.qr_zone,
                margin_bottom=cfg.margin_bottom + cfg.footer_h,
                margin_right=cfg.margin_right)

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
    rsc = generate_rsc()
    now = datetime.now()
    apply_overlays(doc, cfg, [
        {'type': 'footer', 'timestamp': now.strftime("%Y-%m-%dT%H:%M:%S")},
        {'type': 'qr', 'rsc': rsc, 'date': now.strftime("%Y-%m-%dT%H:%M")},
    ])

    doc.save()
    pdf = doc.to_pdf(OUT_PDF)
    print(f"Generated: {pdf}")
    print(f"Pages: {len(doc.pages)}")


if __name__ == "__main__":
    main()
