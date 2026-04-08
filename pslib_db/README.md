# pslib_db -- SQLite-backed PostScript font registry

A self-contained Perl skeleton for managing PostScript fonts via SQLite.
The catalog stores font binaries (PFB / PFA / TTF / OTF) **and** their
classification metadata (encoding, glyph map, cyrillic/latin/greek
coverage, BBox, widths sanity, ...). Once a font is in the DB, the rest
of pslib never has to re-derive any of that information.

This is the prep work for **pslib v3** (port to C). The Perl version
locks down the API and the schema first.

## Layout

```
pslib_db/
  schema.sql                  fonts + glyphs + aliases tables
  lib/Pslib/FontDB.pm         DBI wrapper, classify() heuristics
  bin/pslib-font              CLI: init/import/list/show/glyphs/dump/alias
  examples/01_import_and_list.pl
  fonts/                      (created on first run; user dropbox)
  fonts.db                    (created on first run)
```

## Quick start

```sh
cd pslib_db
./bin/pslib-font init
./bin/pslib-font import ../smookerps/fonts/EType-Normal.pfb
./bin/pslib-font import /usr/share/fonts/dejavu/DejaVuSans.ttf
./bin/pslib-font list
./bin/pslib-font show EType-Normal
./bin/pslib-font glyphs EType-Normal | head -20
```

Or run the demo end-to-end:

```sh
perl examples/01_import_and_list.pl
```

## Why SQLite

- **Self-contained**: the .db file is the catalog. `rsync fonts.db` to
  another machine and it Just Works -- no FONTPATH, no symlinks.
- **Dedup**: SHA-256 of every binary is a UNIQUE column.
- **Queryable**: "give me a font with `has_cyrillic=1` and `format='pfb'`".
- **Indexed glyph table**: "which fonts contain `/afii10018`?".
- **Easy C port**: SQLite3 ships a single `.c` + `.h`. The same schema
  carries over to libpslib.so verbatim, just swap DBI for sqlite3.h.
- **Auditable**: `added_at`, `last_used_at`, `use_count`, `notes`,
  `source_url` all in plain SQL columns.

## What classify() looks at

For PFB / PFA we parse the ASCII header and pull:

- `/FontName`, `/FamilyName`, `/FullName`, `/Weight`, `/ItalicAngle`,
  `/FontBBox`
- All `dup N /name put` lines from the default `Encoding` array

From the glyph names we infer:

- `has_cyrillic` -- presence of any `/afii10NNN` glyph
- `has_latin`    -- presence of `/A` and `/a`
- `has_greek`    -- presence of `/Alpha` or `/Omega`
- `encoding_class`:
  - `afii`     -- has AFII glyphs (works with our CP1251 ReEncodeFont)
  - `macroman` -- has the diagnostic `Adieresis/Aring/ydieresis` triple
  - `latin`    -- has basic Latin only
  - `custom`   -- none of the above

TTF/OTF metadata extraction is TODO (sfnt parsing or FreeType bindings).

## What's still TODO

- [ ] **TTF/OTF**: full sfnt parser for `name` table + `cmap` -> glyph list
- [ ] **cyrillic_widths_ok**: subprocess gs to measure stringwidth of
  every cp1251 byte and reject fonts whose cyrillic widths are zero
  (catches the NimbusSans counterfeit-cyrillic problem)
- [ ] **auto-import**: scan `/usr/share/fonts/*` on first `new()` and
  bootstrap the catalog
- [ ] **doc.pm**: a `Pslib::Doc` PSDoc-style writer that pulls fonts
  from the registry instead of relying on FONTPATH
- [ ] **C port**: same schema, sqlite3 amalgamation, libpslib_fontdb.so

## Why Perl first

Skeleton-iterating in Perl is fast: API mistakes are cheap to fix.
Once `Pslib::FontDB` and `Pslib::Doc` stabilize and we've shipped one
real document with them, we lock the schema and rewrite in C with
`sqlite3.c` + a thin pslib_doc.c renderer. The C port becomes a
mechanical translation, not a design effort.
