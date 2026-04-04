#!/usr/bin/python3
"""dmr_results.py — DMR RX decode results as professional PDF.

Demonstrates pslib capabilities:
  - Document header with title/subtitle hierarchy
  - Multiple tables with custom column alignment and widths
  - Bulleted notes section
  - Per-page QR code with RSC reference and SC logo
  - Footer with ISO timestamp and page numbers
  - Goertzel (1958) — single-bin DFT method attribution

Output: dmr_results.ps + dmr_results.pdf
"""

import os
import random
import string
from datetime import datetime

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pslib import PSDoc

DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PS = os.path.join(DIR, "example00.ps")
OUT_PDF = os.path.join(DIR, "example00.pdf")

# SCteam standard margins (for binding + gripper)
ML = 42    # 15mm left
MR = 23    # 8mm right
MT = 36    # 12.7mm top
MB = 36    # 12.7mm bottom
QR_ZONE = 60
FOOTER_H = 20
BODY_SZ = 8
HDR_SZ = 9
ROW_H = 14


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


def main():
    doc = PSDoc(OUT_PS, title="DMR RX Decode Results",
                margin=ML, margin_top=MT + QR_ZONE,
                margin_bottom=MB + FOOTER_H,
                margin_right=MR)

    rsc = generate_rsc()
    iso_date = datetime.now().strftime("%Y-%m-%dT%H:%M")
    iso_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # RSC font size — scale to match date width
    rsc_text = f"RSC: {rsc}"
    doc.font("Courier-Bold", 6)
    date_w = doc.string_width(iso_date)
    doc.font("Courier-Bold", 7)
    rsc_w = doc.string_width(rsc_text)
    rsc_sz = 7 * date_w / rsc_w if rsc_w > 0 else 7

    # ── Document header ────────────────────────────────────────
    doc.font("Helvetica-Bold", 16)
    doc.text(doc.A4W / 2, 788, "DMR RX DECODE RESULTS", align="center")

    doc.font("Helvetica", 9)
    doc.text(doc.A4W / 2, 773,
             "HackRF One + Baofeng DM-32UV / 439.9875 MHz simplex / D-SMS (ETSI)",
             align="center")

    doc.font("Helvetica-Bold", 10)
    doc.text(doc.A4W / 2, 758, "Goertzel 4-Tone Energy Detector", align="center")

    doc.font("Helvetica-Oblique", 8)
    doc.text(doc.A4W / 2, 745,
             "Gerald Goertzel (1958) \u2014 single-bin DFT for non-coherent FSK detection",
             align="center")

    cy = 732
    doc.hr(cy, ML, doc.A4W - MR)
    cy -= 14

    # ── Info block ─────────────────────────────────────────────
    doc.font("Helvetica", 7)
    info_lines = [
        "Decoder: dmr_rx.cpp (GnuRadio 3.10.12, C++ pipeline)",
        "DSP: dc_blocker(D=512) + freq_xlating_fir LPF 6250 Hz + Goertzel at \xb1648, \xb11944 Hz",
        "Protocol: Golay(20,8) ECC + BPTC(196,96) Hamming turbo + CRC-CCITT",
        "4FSK: \xb1648 Hz (inner, sym \xb11), \xb11944 Hz (outer, sym \xb13), 4800 sym/s, 9600 bps",
        "All captures: 02.04.2026, LZ1CCM (2840765) / smooker, SCteam",
    ]
    for line in info_lines:
        doc.text(ML, cy, line)
        cy -= 9
    cy -= 4

    # ── Top 6 table ────────────────────────────────────────────
    doc.font("Helvetica-Bold", HDR_SZ)
    doc.text(ML, cy, "Top 6 \u2014 BPF/Goertzel method (sorted by Golay OK)")
    cy -= HDR_SZ + 2

    top_headers = ["#", "File", "Size", "Center MHz", "Gains (l/g/a)",
                   "Offset Hz", "FM", "BPF"]
    top_rows = [
        ["5",  "capture4.iq",          "60M", "439.9875", "l40 g62 a1", "0",      "1",  "28"],
        ["13", "capture_offset_01.iq",  "60M", "439.000",  "l24 g40 a1", "987500", "12", "21"],
        ["6",  "capture5.iq",           "47M", "439.9875", "l40 g62 a1", "0",      "4",  "18"],
        ["12", "capture_offset.iq",     "52M", "439.975",  "l24 g36 a1", "12500",  "12", "15"],
        ["10", "capture_lowgain.iq",    "34M", "439.9875", "l32 g48 a1", "0",      "0",  "14"],
        ["3",  "capture2.iq",           "56M", "439.9875", "l8 g20 a0",  "0",      "9",  "13"],
    ]
    top_widths = [25, 130, 30, 60, 70, 55, 30, 30]
    remaining = doc.A4W - ML - MR - sum(top_widths)
    top_widths[1] += remaining

    cy = doc.table(ML, cy, top_headers, top_rows,
                   col_widths=top_widths, font_name="Helvetica",
                   header_size=HDR_SZ, body_size=BODY_SZ,
                   row_height=ROW_H,
                   col_align=["right", "left", "right", "right", "left",
                              "right", "right", "right"])
    cy -= 16

    # ── Full table ─────────────────────────────────────────────
    doc.font("Helvetica-Bold", HDR_SZ)
    doc.text(ML, cy, "Full capture list (all from 02.04.2026)")
    cy -= HDR_SZ + 2

    full_headers = ["#", "Time", "File", "Size", "Center", "Gains",
                    "Offset", "FM", "BPF"]
    full_rows = [
        ["1",  "18:19", "capture_cf32.iq",       "217M", "439.9875",
         "l16 g32 a0", "0",      "\u2014", "\u2014"],
        ["2",  "18:20", "capture.iq",             "63M",  "439.9875",
         "l16 g32 a0", "0",      "0",  "\u2014"],
        ["3",  "18:29", "capture2.iq",            "56M",  "439.9875",
         "l8 g20 a0",  "0",      "9",  "13"],
        ["4",  "18:37", "capture3.iq",            "48M",  "439.9875",
         "l40 g62 a1", "0",      "7",  "7"],
        ["5",  "18:39", "capture4.iq",            "60M",  "439.9875",
         "l40 g62 a1", "0",      "1",  "28"],
        ["6",  "18:42", "capture5.iq",            "47M",  "439.9875",
         "l40 g62 a1", "0",      "4",  "18"],
        ["7",  "20:11", "capture.iq",             "63M",  "439.9875",
         "?",          "0",      "0",  "\u2014"],
        ["8",  "20:12", "capture_maxgain.iq",     "29M",  "439.9875",
         "l40 g62 a1", "0",      "3",  "1"],
        ["9",  "20:17", "capture_maxgain_new.iq", "33M",  "439.9875",
         "l40 g62 a1", "0",      "0",  "\u2014"],
        ["10", "20:19", "capture_lowgain.iq",     "34M",  "439.9875",
         "l32 g48 a1", "0",      "0",  "14"],
        ["11", "20:22", "capture_medgain.iq",     "34M",  "439.9875",
         "l24 g36 a1", "0",      "3",  "9"],
        ["12", "20:27", "capture_offset.iq",      "52M",  "439.975",
         "l24 g36 a1", "12500",  "12", "15"],
        ["13", "20:33", "capture_offset_01.iq",   "60M",  "439.000",
         "l24 g40 a1", "987500", "12", "21"],
    ]
    full_widths = [25, 35, 130, 30, 55, 65, 50, 25, 25]
    remaining = doc.A4W - ML - MR - sum(full_widths)
    full_widths[2] += remaining

    cy = doc.table(ML, cy, full_headers, full_rows,
                   col_widths=full_widths, font_name="Helvetica",
                   header_size=HDR_SZ, body_size=BODY_SZ,
                   row_height=ROW_H,
                   col_align=["right", "right", "left", "right", "right",
                              "left", "right", "right", "right"])
    cy -= 16

    # ── Notes ──────────────────────────────────────────────────
    doc.font("Helvetica-Bold", HDR_SZ)
    doc.text(ML, cy, "Notes")
    cy -= HDR_SZ + 2

    doc.font("Helvetica", 7)
    notes = [
        "capture_offset_01.iq contains FM carrier ONLY (not DMR SMS). "
        "Used for PPM measurement: 0.08 ppm.",
        "BPF method: Goertzel 4-tone energy detector at \xb1648/\xb11944 Hz. "
        "No clock recovery needed.",
        "FM method: quadrature_demod_cf + Mueller-Muller symbol_sync_ff "
        "(loop_bw=0.045).",
        "All CRC FAIL \u2014 BER ~15-20%, need <5% for CRC OK. "
        "Next step: new capture in DMR/digital mode.",
        "DC blocker (D=512, ~3.9 kHz notch at 2 Msps) enables decoding "
        "of DC-tuned captures (offset=0).",
        "Optimal HackRF gains: LNA=24, VGA=36-40, amp ON. "
        "MAX gains (LNA=40, VGA=62) cause ADC saturation.",
        "Goertzel method: 2x improvement over FM demod "
        "(28 vs 1 Golay OK on capture4.iq).",
    ]
    for note in notes:
        doc.text(ML + 5, cy, "\u2022 " + note)
        cy -= 9

    # ── Per-page overlays: QR, footer ─────────────────────────
    total_pages = len(doc.pages)

    for pg_idx in range(total_pages):
        cmds = doc.pages[pg_idx]

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
            # White circle + SC
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

            # RSC + date
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
    print(f"Pages: {len(doc.pages)}, Metrics: {len(doc._metrics)} font combos")


if __name__ == "__main__":
    main()
