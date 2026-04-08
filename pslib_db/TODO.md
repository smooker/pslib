# pslib_db -- TODO

Skeleton works end-to-end: SQLite store, PFB import, CLI, render-from-DB
demo. The list below tracks everything that must land before this becomes
a viable replacement for `~/work/pslib/pslib.py` and the local
PostScript::Simple patches.

## P0 -- correctness bugs in the skeleton

- [ ] **classify() encoding misclassification (EType-Normal -> "macroman")**
      EType-Normal's default Encoding is effectively cp1251 (А..я sit in
      slots 0xC0..0xFF), but the heuristic only flags it as MacRoman
      because it sees `/Adieresis + /Aring + /ydieresis`. Need to look at
      slots 0xC0..0xFF specifically: if any of the names there are
      cyrillic letters (under any naming convention), encoding_class
      should be `cp1251` (or `cp1251-like`), not `macroman`. Probably do
      both heuristics and prefer cp1251 when slots 192..255 have
      cyrillic-shaped glyph names.

- [ ] **has_cyrillic = 0 for EType-Normal even though it renders cyrillic**
      The flag only checks for `/afii10NNN` glyph names. EType uses bare
      cyrillic names like `/A`, `/B` (overloaded with latin) AND/OR
      direct mapping by slot. Improve detection by:
        a) consulting an alias list (Wikipedia AGL aliases for cyrillic)
        b) checking if rendering byte 0xC1 produces a non-zero-width
           glyph that visually differs from latin /B
      The `cyrillic_widths_ok` step from below will give us (b) for free.

## P0 -- next functional milestones

- [ ] **cyrillic_widths_ok via gs stringwidth check**
      For each candidate font, run a tiny gs subprocess that
      `selectfont`s the embedded font, measures `stringwidth` for every
      cp1251 byte 0xC0..0xFF, and confirms widths are non-zero AND not
      identical to latin slots. Catches Helvetica/NimbusSans
      counterfeit cyrillic (gs substitute font has AFII names with
      zero widths -- silently broken in current pssimple_test.pdf).
      Set `cyrillic_widths_ok = 1` only if all 64 cyrillic bytes have
      sane widths.

- [ ] **TTF / OTF metadata extraction**
      DejaVu, Liberation, Nimbus, URW shipped as `.ttf` are 90% of the
      system fonts. Need a real sfnt parser:
        - `name` table (FontName, FamilyName, FullName, Weight)
        - `cmap` table (Unicode -> glyph name) for has_cyrillic /
          has_latin / has_greek detection
        - `head` table for FontBBox, ItalicAngle
        - `post` table for Adobe glyph names (so the same AFII heuristic
          applies as for Type 1)
      Pure Perl is doable (~300 LOC); alternatively bind Font::TTF or
      FreeType. Decide later.

- [ ] **PFA charstrings parser for `.t1` files without explicit Encoding**
      NimbusSans-Regular.t1 / NimbusRoman-Regular.t1 came back as
      `glyph_count=0` because their default Encoding section is delivered
      via the eexec-encrypted block, not the ASCII header. Either:
        a) implement the eexec decryption pass (Adobe Type 1 spec
           §6.1) and walk the CharStrings dict
        b) shell out to gs in -dNODISPLAY mode and dump CharStrings keys
           via PostScript

      Option (b) is what `font_debug.pl` already does for visual dumps;
      reusing that gives us free metadata for any font gs can load.

## P0 -- workflow & safety

- [ ] **Auto-import scan of /usr/share/fonts/* on first new()**
      First time `Pslib::FontDB->new` opens a brand-new DB, walk the
      standard font dirs (DejaVu, Liberation, Nimbus, URW, gs Fonts)
      and import everything. Subsequent runs are no-ops (sha256 dedup).
      Then the user already has the whole system catalog without any
      explicit setup.

- [ ] **`pslib-font test <name>`** -- render a 1-page test PDF for the
      named font (latin alphabet, digits, cyrillic alphabet, glyph
      grid). Stores PDF as `/tmp/pslib-test-<name>.pdf` and prints the
      path. This is the visual verification users will reach for any
      time they suspect a font is broken.

- [ ] **`pslib-font search`** -- query helpers like
      `pslib-font search --has-cyrillic --format=pfb` so the catalog
      becomes useful, not just queryable.

## P1 -- next big chunk

- [ ] **`Pslib::Doc`** -- PSDoc-style document writer that uses the
      registry directly:
        $doc->use_font('Helvetica');           # auto-pulled from DB
        $doc->text(20, 280, 'Здравей', font => 'Helvetica');
      The font BLOB is inlined into the prolog on first use; no
      FONTPATH. Replaces the current PostScript::Simple patches.

- [ ] **encoding decision lives in the registry**, not in the document
      writer. text() asks the registry "what encoding does this font
      want for cp1251 cyrillic input?" and the registry returns:
        - `direct`  (font's default Encoding already sits at cp1251 byte
                     positions -- e.g. EType-Normal)
        - `afii_reencode` (font has AFII glyphs, needs ReEncodeFont
                     prolog -- e.g. Helvetica via gs substitute)
        - `none`    (font cannot render cyrillic)

- [ ] **Aliases table actually used**
      `set_alias('sans-bold', 'Helvetica-Bold')` is in the schema; wire
      it into get_font / find so logical names work.

- [ ] **Backup / dump format**
      `pslib-font export-all <dir>` writes one .pfb/.pfa per row plus a
      json metadata sidecar. Lets us round-trip the catalog through git
      if we ever want to.

## P2 -- ports / packaging

- [ ] **C port (`libpslib_fontdb.so` + `pslib-font` C CLI)**
      Once Pslib::FontDB and Pslib::Doc API are stable. Lift schema.sql
      verbatim, embed sqlite3.c amalgamation, translate the methods 1:1.
      Single `.so` per platform, no interpreter required.

- [ ] **Python binding**
      Either ctypes wrapper around the C lib, or a thin reimplementation
      that talks to the same fonts.db. Replaces ~/work/pslib/pslib.py
      font handling.

## P2 -- nice-to-have

- [ ] **Glyph rendering preview cache** -- store one tiny PNG per
      glyph in a `glyph_previews` table (or file dir) so a future
      `pslib-font show <name>` can print actual glyph art on a
      sixel-capable terminal.

- [ ] **`source_url` enrichment** -- if we ever pull a font off the web
      (Google Fonts, Eurotype archive, etc), record where it came from
      so we can re-fetch / verify.

- [ ] **Multi-DB merging** (`pslib-font merge other.db`) -- handy when
      claude@st and claude@sw2 want to share their catalogs.

- [ ] **`PSLIB_FONTDB` env var documentation** in README

## Discovered during this session, not yet recorded elsewhere

- **Helvetica/NimbusSans counterfeit cyrillic** -- gs substitutes
  Helvetica with NimbusSans-Regular which has AFII glyph names but
  zero / counterfeit widths. End result in pssimple_test.pdf was a
  collapsed line of overlapping glyphs. Detection lives in
  `cyrillic_widths_ok` check. Must remember to add NimbusSans to a
  blacklist for cyrillic use until/unless gs ships a real cyrillic
  Helvetica replacement.

- **EType-Normal IS a cyrillic font** -- earlier in this session I was
  wrong (twice) about it being latin-only. Glyph dump confirms full
  cyrillic block in slots 0xC0..0xFF. The classifier needs to learn
  this so we never misclassify it again.

- **pdftotext is unreliable for cp1251-encoded fonts** -- always render
  PDF to PNG via gs and visually inspect when verifying cyrillic. Note
  this in the pslib_db rendering tests.

- **smookerps lib/PostScript/Simple.pm patches** (loadfont, puttext,
  :raw output, units=mm default) become **deprecated** once Pslib::Doc
  is in place. Move the underlying PFA encoding logic into Pslib::Doc
  / Pslib::FontDB so it's testable in isolation.
