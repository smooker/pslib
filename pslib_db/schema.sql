-- pslib_db: SQLite-backed PostScript font registry
-- Schema v1 (2026-04-08)

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- Each row is one font binary plus everything we know about it.
-- font_data is the raw .pfa / .pfb / .ttf / .otf file as a BLOB so the
-- catalog is fully self-contained -- you can rsync fonts.db between
-- machines and pslib will keep working.
CREATE TABLE IF NOT EXISTS fonts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ps_font_name      TEXT    NOT NULL,           -- /FontName from the file (Helvetica, EType-Normal, ...)
    family            TEXT,                       -- /FamilyName
    full_name         TEXT,                       -- /FullName
    weight            TEXT,                       -- "Medium", "Bold", ...
    italic_angle      REAL,
    format            TEXT    NOT NULL,           -- pfb | pfa | ttf | otf | builtin
    sha256            TEXT    NOT NULL UNIQUE,    -- dedup key
    file_size         INTEGER,
    original_filename TEXT,                       -- whatever path it came from
    source_url        TEXT,                       -- if downloaded from web
    added_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    last_used_at      TEXT,
    use_count         INTEGER NOT NULL DEFAULT 0,
    -- Encoding metadata, filled by classify step:
    encoding_class    TEXT,                       -- afii | macroman | winansi | iso8859 | custom | unknown
    has_cyrillic      INTEGER,                    -- 0/1 -- found afii10017+ glyphs?
    has_latin         INTEGER,                    -- 0/1
    has_greek         INTEGER,                    -- 0/1
    cyrillic_widths_ok INTEGER,                   -- 0/1 -- gs reported sane stringwidth, not all-zero
    glyph_count       INTEGER,                    -- total glyphs in CharStrings
    fontbbox_xmin     REAL,
    fontbbox_ymin     REAL,
    fontbbox_xmax     REAL,
    fontbbox_ymax     REAL,
    notes             TEXT,
    comment           TEXT,                       -- free-form user comment
    metadata          TEXT,                       -- raw extracted metadata (PS header, FontInfo, copyright, creation date, ...)
    preview_built_at  TEXT,
    -- Binary blobs LAST so SELECT without "*" stays fast:
    font_data         BLOB    NOT NULL,
    preview_pdf       BLOB                          -- 1-page rendered preview (regenerated on demand)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_fonts_ps_font_name
    ON fonts(ps_font_name);

-- Per-glyph table for fast lookups (which slot has which glyph,
-- which AFII names exist in this font, etc.)
CREATE TABLE IF NOT EXISTS glyphs (
    font_id     INTEGER NOT NULL REFERENCES fonts(id) ON DELETE CASCADE,
    slot        INTEGER,            -- 0..255 in the font's default Encoding (NULL if not in default Encoding)
    glyph_name  TEXT    NOT NULL,   -- /A, /afii10017, /Adieresis, ...
    has_outline INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (font_id, glyph_name)
);

CREATE INDEX IF NOT EXISTS idx_glyphs_slot
    ON glyphs(font_id, slot);

CREATE INDEX IF NOT EXISTS idx_glyphs_name
    ON glyphs(glyph_name);

-- Aliases: logical name -> ps_font_name. Lets you say
-- "use 'sans-bold' wherever I previously used a specific font" and
-- swap implementations later.
CREATE TABLE IF NOT EXISTS aliases (
    alias        TEXT PRIMARY KEY,
    ps_font_name TEXT NOT NULL,
    note         TEXT,
    FOREIGN KEY (ps_font_name) REFERENCES fonts(ps_font_name)
        ON DELETE CASCADE ON UPDATE CASCADE
);
