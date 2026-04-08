package Pslib::FontDB;

# Pslib::FontDB -- SQLite-backed PostScript font registry.
#
# Stores font binaries (PFB / PFA / TTF / OTF) plus metadata so the
# rest of pslib can ask "give me a cyrillic-capable font" without
# re-deriving everything every run.
#
# Schema lives in ../schema.sql -- this module just wraps DBI.
#
# Public API (skeleton -- not all wired yet):
#
#   Pslib::FontDB->new($db_path)            -- open or create
#   $db->import_font($file_or_blob, %meta)  -- read, classify, INSERT
#   $db->get_font($ps_font_name)            -- returns hashref incl. font_data BLOB
#   $db->find($where_hashref)               -- arrayref of matches
#   $db->list                               -- arrayref of name+meta rows (no BLOB)
#   $db->set_alias($alias, $ps_font_name)
#   $db->resolve_alias($alias)              -- returns ps_font_name or undef
#   $db->bump_use($ps_font_name)            -- last_used_at + use_count
#   $db->classify($font_blob)               -- internal, returns %meta hashref
#
# Self-contained: caller never touches DBI directly.

use strict;
use warnings;
use DBI;
use Digest::SHA  qw(sha256_hex);
use File::Basename qw(basename);
use File::Spec;
use Carp qw(croak);

our $VERSION = '0.01';

# -- Construction ----------------------------------------------------

sub new {
    my ($class, $db_path) = @_;
    croak "FontDB->new: db path required" unless $db_path;

    my $is_new = !-e $db_path;
    my $dbh = DBI->connect("dbi:SQLite:dbname=$db_path", "", "", {
        RaiseError => 1,
        PrintError => 0,
        AutoCommit => 1,
        sqlite_unicode => 1,
    });
    $dbh->do("PRAGMA foreign_keys = ON");
    $dbh->do("PRAGMA journal_mode = WAL");

    my $self = bless {
        dbh     => $dbh,
        db_path => $db_path,
    }, $class;

    if ($is_new) {
        $self->_apply_schema;
    } else {
        $self->_migrate;
    }
    return $self;
}

# Idempotent schema migration: add columns that newer versions of the
# code expect but older DBs may not have. SQLite ALTER TABLE ADD COLUMN
# is cheap (metadata only) and tolerates being called every startup.
sub _migrate {
    my ($self) = @_;
    my @cols = @{ $self->{dbh}->selectall_arrayref(
        "PRAGMA table_info(fonts)", { Slice => {} }
    ) };
    my %have = map { $_->{name} => 1 } @cols;
    my @add;
    push @add, ["preview_pdf",      "BLOB"] unless $have{preview_pdf};
    push @add, ["preview_built_at", "TEXT"] unless $have{preview_built_at};
    push @add, ["comment",          "TEXT"] unless $have{comment};
    push @add, ["metadata",         "TEXT"] unless $have{metadata};
    for my $a (@add) {
        my ($name, $type) = @$a;
        $self->{dbh}->do("ALTER TABLE fonts ADD COLUMN $name $type");
    }
}

sub dbh { $_[0]->{dbh} }

sub _apply_schema {
    my ($self) = @_;
    # schema.sql sits next to this module's parent dir
    my $here   = File::Basename::dirname(__FILE__);
    my $schema = File::Spec->catfile($here, '..', '..', 'schema.sql');
    croak "FontDB: schema.sql not found at $schema" unless -e $schema;

    open my $fh, '<', $schema or croak "open $schema: $!";
    local $/;
    my $sql = <$fh>;
    close $fh;

    # Strip line comments first (everything after `--` on each line),
    # then split on `;` and run.
    $sql =~ s/--[^\n]*//g;

    for my $stmt (split /;/, $sql) {
        $stmt =~ s/^\s+|\s+$//g;
        next unless length $stmt;
        $self->{dbh}->do($stmt);
    }
}

# -- Import ----------------------------------------------------------

sub import_font {
    my ($self, $source, %meta) = @_;

    # $source is a path on disk; future: also accept blob ref
    croak "import_font: source path required" unless defined $source;
    croak "import_font: $source not found"    unless -e $source;

    open my $fh, '<:raw', $source or croak "open $source: $!";
    local $/;
    my $blob = <$fh>;
    close $fh;

    my $sha = sha256_hex($blob);

    # Dedup check
    my $existing = $self->{dbh}->selectrow_hashref(
        "SELECT id, ps_font_name FROM fonts WHERE sha256 = ?",
        undef, $sha
    );
    if ($existing) {
        return {
            id           => $existing->{id},
            ps_font_name => $existing->{ps_font_name},
            already_present => 1,
        };
    }

    # Classify
    my $info = $self->classify($blob, $source);
    $info->{ps_font_name} || croak "import_font: classify could not find /FontName in $source";

    my $size = length $blob;
    my $orig = basename($source);

    require DBI;
    my $sth = $self->{dbh}->prepare(q{
        INSERT INTO fonts (
            ps_font_name, family, full_name, weight, italic_angle,
            format, sha256, file_size, original_filename,
            encoding_class, has_cyrillic, has_latin, has_greek,
            cyrillic_widths_ok, glyph_count,
            fontbbox_xmin, fontbbox_ymin, fontbbox_xmax, fontbbox_ymax,
            notes, font_data
        ) VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?, ?,?,?,?, ?,?)
    });
    my @text_params = (
        $info->{ps_font_name}, $info->{family}, $info->{full_name},
        $info->{weight}, $info->{italic_angle},
        $info->{format}, $sha, $size, $orig,
        $info->{encoding_class}, $info->{has_cyrillic}, $info->{has_latin},
        $info->{has_greek},
        $info->{cyrillic_widths_ok}, $info->{glyph_count},
        $info->{fontbbox_xmin}, $info->{fontbbox_ymin},
        $info->{fontbbox_xmax}, $info->{fontbbox_ymax},
        $meta{notes},
    );
    for my $i (0..$#text_params) {
        $sth->bind_param($i + 1, $text_params[$i]);
    }
    $sth->bind_param(21, $blob, DBI::SQL_BLOB());
    $sth->execute;

    my $id = $self->{dbh}->last_insert_id("", "", "fonts", "id");

    # Insert glyph rows (slot may be undef for glyphs not in default Encoding)
    if (my $glyphs = $info->{glyphs}) {
        my $sth = $self->{dbh}->prepare(
            "INSERT OR IGNORE INTO glyphs (font_id, slot, glyph_name) VALUES (?,?,?)"
        );
        for my $g (@$glyphs) {
            $sth->execute($id, $g->{slot}, $g->{name});
        }
    }

    return { id => $id, ps_font_name => $info->{ps_font_name}, %{$info} };
}

# -- Classification (skeleton) ---------------------------------------

sub classify {
    my ($self, $blob, $hint_path) = @_;

    my %info = (
        format        => 'unknown',
        encoding_class => 'unknown',
        has_cyrillic  => 0,
        has_latin     => 0,
        has_greek     => 0,
        glyph_count   => 0,
        cyrillic_widths_ok => 0,
    );

    # Detect format
    if (length($blob) >= 1 && substr($blob, 0, 1) eq "\x80") {
        $info{format} = 'pfb';
    } elsif (substr($blob, 0, 4) eq "OTTO" || substr($blob, 0, 4) eq "\x00\x01\x00\x00") {
        $info{format} = (substr($blob, 0, 4) eq "OTTO") ? 'otf' : 'ttf';
    } elsif ($blob =~ /^%!PS-AdobeFont/) {
        $info{format} = 'pfa';
    } else {
        $info{format} = ($hint_path && $hint_path =~ /\.(\w+)$/) ? lc($1) : 'unknown';
    }

    # For PFB/PFA we can grep the ASCII header for FontName, FamilyName etc.
    # For TTF/OTF we'd need full sfnt parser; punt for now.
    my $ascii;
    if ($info{format} eq 'pfb') {
        # Strip 0x80 segment headers, take only ASCII (type=1) sections
        my @parts;
        my $i = 0;
        while ($i < length($blob)) {
            last if ord(substr($blob, $i, 1)) != 0x80;
            my $type = ord(substr($blob, $i + 1, 1));
            last if $type == 3;
            my $len = unpack('V', substr($blob, $i + 2, 4));
            push @parts, substr($blob, $i + 6, $len) if $type == 1;
            $i += 6 + $len;
        }
        $ascii = join("", @parts);
    } elsif ($info{format} eq 'pfa') {
        $ascii = $blob;
    } elsif ($info{format} eq 'ttf' || $info{format} eq 'otf') {
        # Minimal sfnt parser: just enough to populate ps_font_name + family + full_name
        # from the `name` table so import_font() can store the BLOB.
        my %t = _sfnt_tables($blob);
        if (my $nm = $t{name}) {
            my %n = _sfnt_name_records($blob, $nm);
            $info{ps_font_name} = $n{6};   # PostScript name
            $info{family}       = $n{1};
            $info{full_name}    = $n{4};
            $info{weight}       = $n{2};
        }
        # Glyph count from maxp
        if (my $mp = $t{maxp}) {
            $info{glyph_count} = unpack('n', substr($blob, $mp->{offset} + 4, 2));
        }
        # Unicode coverage from cmap -- sets has_latin / has_cyrillic / has_greek
        if (my $cm = $t{cmap}) {
            my @ranges = _sfnt_cmap_ranges($blob, $cm);
            for my $r (@ranges) {
                my ($s, $e) = @$r;
                $info{has_latin}    ||= ($s <= 0x005A && $e >= 0x0041);   # A..Z
                $info{has_cyrillic} ||= ($s <= 0x044F && $e >= 0x0410);   # А..я
                $info{has_greek}    ||= ($s <= 0x03A9 && $e >= 0x0391);   # Α..Ω
            }
        }
        $info{encoding_class} = 'sfnt';
        $ascii = '';
    } else {
        $ascii = '';
    }

    if ($ascii) {
        ($info{ps_font_name}) = $ascii =~ m{/FontName\s+/(\S+?)\s+def};
        ($info{family})       = $ascii =~ m{/FamilyName\s*\(([^)]*)\)};
        ($info{full_name})    = $ascii =~ m{/FullName\s*\(([^)]*)\)};
        ($info{weight})       = $ascii =~ m{/Weight\s*\(([^)]*)\)};
        ($info{italic_angle}) = $ascii =~ m{/ItalicAngle\s+(-?\d+(?:\.\d+)?)};
        if (my ($bb) = $ascii =~ m{FontBBox\s*\x7b\s*([^\x7d]+)\x7d}) {
            my @b = split /\s+/, $bb;
            @info{qw(fontbbox_xmin fontbbox_ymin fontbbox_xmax fontbbox_ymax)} = @b[0..3];
        }

        # Glyph slots from default Encoding
        my @glyphs;
        while ($ascii =~ /dup\s+(\d+)\s*\/(\S+?)\s+put/g) {
            push @glyphs, { slot => $1 + 0, name => $2 };
        }
        $info{glyph_count} = scalar @glyphs;
        $info{glyphs}      = \@glyphs;

        # Quick encoding-class heuristic
        my %name_set = map { $_->{name} => 1 } @glyphs;
        my $afii_seen = grep { /^afii10\d{3}$/ } keys %name_set;
        my $latin_seen = ($name_set{A} && $name_set{a});
        my $greek_seen = ($name_set{Alpha} || $name_set{Omega});
        $info{has_cyrillic} = ($afii_seen ? 1 : 0);
        $info{has_latin}    = ($latin_seen ? 1 : 0);
        $info{has_greek}    = ($greek_seen ? 1 : 0);

        if ($afii_seen)               { $info{encoding_class} = 'afii';    }
        elsif ($name_set{Adieresis} && $name_set{Aring} && $name_set{ydieresis}) {
                                        $info{encoding_class} = 'macroman'; }
        elsif ($latin_seen)           { $info{encoding_class} = 'latin';   }
        else                          { $info{encoding_class} = 'custom';  }
    }

    # cyrillic_widths_ok: TODO -- run gs subprocess to measure stringwidth
    # for each cp1251 byte and verify it's not all-zero. Skipped in skeleton.

    return \%info;
}

# -- Query -----------------------------------------------------------

sub get_font {
    my ($self, $name) = @_;
    return $self->{dbh}->selectrow_hashref(
        "SELECT * FROM fonts WHERE ps_font_name = ?",
        undef, $name
    );
}

sub list {
    my ($self) = @_;
    return $self->{dbh}->selectall_arrayref(
        q{
        SELECT id, ps_font_name, family, format, encoding_class,
               has_cyrillic, has_latin, glyph_count, file_size,
               added_at, use_count
        FROM fonts
        ORDER BY ps_font_name
        },
        { Slice => {} }
    );
}

sub find {
    my ($self, $where) = @_;
    $where ||= {};
    my @clauses;
    my @binds;
    for my $k (sort keys %$where) {
        push @clauses, "$k = ?";
        push @binds, $where->{$k};
    }
    my $sql = "SELECT id, ps_font_name FROM fonts";
    $sql   .= " WHERE " . join(" AND ", @clauses) if @clauses;
    return $self->{dbh}->selectall_arrayref($sql, { Slice => {} }, @binds);
}

sub set_alias {
    my ($self, $alias, $ps_font_name, $note) = @_;
    $self->{dbh}->do(
        "INSERT OR REPLACE INTO aliases (alias, ps_font_name, note) VALUES (?,?,?)",
        undef, $alias, $ps_font_name, $note
    );
}

sub resolve_alias {
    my ($self, $alias) = @_;
    my ($name) = $self->{dbh}->selectrow_array(
        "SELECT ps_font_name FROM aliases WHERE alias = ?", undef, $alias
    );
    return $name;
}

sub bump_use {
    my ($self, $name) = @_;
    $self->{dbh}->do(
        "UPDATE fonts SET use_count = use_count + 1, last_used_at = datetime('now') WHERE ps_font_name = ?",
        undef, $name
    );
}

# -- Preview ---------------------------------------------------------

# Save a 1-page preview PDF blob into the font row.
# Caller renders the PDF however it likes and just hands us the bytes.
# Uses explicit SQL_BLOB binding so DBD::SQLite does not try to UTF-8
# encode the binary data (PDF contains lots of NUL and high bytes).
sub save_preview {
    my ($self, $name, $pdf_blob) = @_;
    croak "save_preview: name + pdf bytes required" unless $name && defined $pdf_blob;
    require DBI;
    my $sth = $self->{dbh}->prepare(
        "UPDATE fonts SET preview_pdf = ?, preview_built_at = datetime('now') WHERE ps_font_name = ?"
    );
    $sth->bind_param(1, $pdf_blob, DBI::SQL_BLOB());
    $sth->bind_param(2, $name);
    $sth->execute;
    my ($len) = $self->{dbh}->selectrow_array(
        "SELECT length(preview_pdf) FROM fonts WHERE ps_font_name = ?",
        undef, $name
    );
    return $len;
}

# Pull the preview PDF blob back out (or undef if none stored yet).
sub get_preview {
    my ($self, $name) = @_;
    my ($blob) = $self->{dbh}->selectrow_array(
        "SELECT preview_pdf FROM fonts WHERE ps_font_name = ?",
        undef, $name
    );
    return $blob;
}

# -- Export ----------------------------------------------------------

sub export_font {
    my ($self, $name, $out_path) = @_;
    my $row = $self->{dbh}->selectrow_hashref(
        "SELECT format, font_data FROM fonts WHERE ps_font_name = ?",
        undef, $name
    );
    return unless $row;
    open my $fh, '>:raw', $out_path or croak "open $out_path: $!";
    print $fh $row->{font_data};
    close $fh;
    return 1;
}

# -- Bulk import -----------------------------------------------------

sub import_dir {
    my ($self, $dir, %opts) = @_;
    my @found;
    require File::Find;
    File::Find::find(sub {
        return unless -f $_;
        return unless /\.(pfb|pfa|ttf|otf)$/i;
        push @found, $File::Find::name;
    }, $dir);
    my %stats = (scanned => scalar @found, imported => 0, skipped => 0, failed => 0);
    # ps_font_name is also UNIQUE, but for raw slurp we use basename + sha8 suffix
    # to guarantee uniqueness without an extra SELECT round-trip.
    my $sth = $self->{dbh}->prepare(
        "INSERT OR IGNORE INTO fonts
            (ps_font_name, format, sha256, file_size, original_filename, font_data)
         VALUES (?, ?, ?, ?, ?, ?)"
    );
    $self->{dbh}->begin_work;
    for my $f (@found) {
        eval {
            open my $fh, '<:raw', $f or die "open: $!";
            local $/; my $blob = <$fh>; close $fh;
            my $sha = sha256_hex($blob);
            my $base = basename($f);
            (my $name = $base) =~ s/\.(pfb|pfa|ttf|otf)$//i;
            (my $fmt  = lc(($f =~ /\.(\w+)$/)[0] || 'unknown'));
            # short sha8 suffix avoids ps_font_name collisions deterministically
            my $ps_name = "${name}#" . substr($sha, 0, 8);
            $sth->bind_param(1, $ps_name);
            $sth->bind_param(2, $fmt);
            $sth->bind_param(3, $sha);
            $sth->bind_param(4, length($blob));
            $sth->bind_param(5, $f);
            $sth->bind_param(6, $blob, DBI::SQL_BLOB());
            $sth->execute;
            if ($sth->rows == 0) { $stats{skipped}++ } else { $stats{imported}++ }
        };
        if ($@) { $stats{failed}++; warn "  ! $f: $@" if $opts{verbose}; }
    }
    $self->{dbh}->commit;
    return \%stats;
}

# -- Classify pass over already-stored rows --------------------------
# After a bulk slurp the rows have only filename + sha. Walk them all,
# extract real metadata from the BLOB, and UPDATE in place.

sub classify_all {
    my ($self, %opts) = @_;
    my $rows = $self->{dbh}->selectall_arrayref(
        "SELECT id, ps_font_name, format, original_filename, font_data
         FROM fonts",
        { Slice => {} }
    );
    my %stats = (scanned => scalar @$rows, updated => 0, failed => 0);
    my $upd = $self->{dbh}->prepare(
        "UPDATE fonts SET
            ps_font_name = ?, family = ?, full_name = ?, weight = ?,
            italic_angle = ?, encoding_class = ?,
            has_cyrillic = ?, has_latin = ?, has_greek = ?,
            glyph_count = ?,
            fontbbox_xmin = ?, fontbbox_ymin = ?, fontbbox_xmax = ?, fontbbox_ymax = ?,
            metadata = ?
         WHERE id = ?"
    );
    $self->{dbh}->begin_work;
    for my $r (@$rows) {
        my $info = eval { $self->classify($r->{font_data}, $r->{original_filename}) };
        if ($@ || !$info) {
            $stats{failed}++;
            warn "  ! id=$r->{id} $r->{original_filename}: $@" if $opts{verbose};
            next;
        }
        # Build a small metadata dump for the new column
        my $meta_text = join("\n",
            "ps_font_name: " . ($info->{ps_font_name} // ''),
            "family: "       . ($info->{family}       // ''),
            "full_name: "    . ($info->{full_name}    // ''),
            "weight: "       . ($info->{weight}       // ''),
            "format: "       . ($info->{format}       // ''),
            "encoding: "     . ($info->{encoding_class} // ''),
            "glyphs: "       . ($info->{glyph_count}  // 0),
            "source: "       . ($r->{original_filename} // ''),
        );
        # Keep collision-safe ps_font_name when classify gave us a real one
        my $new_name = $info->{ps_font_name} // $r->{ps_font_name};
        # If collision with another row, fall back to old slurp name
        if ($new_name ne $r->{ps_font_name}) {
            my ($busy) = $self->{dbh}->selectrow_array(
                "SELECT 1 FROM fonts WHERE ps_font_name = ? AND id != ?",
                undef, $new_name, $r->{id}
            );
            $new_name = $r->{ps_font_name} if $busy;
        }
        $upd->execute(
            $new_name,
            $info->{family},
            $info->{full_name},
            $info->{weight},
            $info->{italic_angle},
            $info->{encoding_class},
            $info->{has_cyrillic},
            $info->{has_latin},
            $info->{has_greek},
            $info->{glyph_count},
            $info->{fontbbox_xmin}, $info->{fontbbox_ymin},
            $info->{fontbbox_xmax}, $info->{fontbbox_ymax},
            $meta_text,
            $r->{id},
        );
        $stats{updated}++;
    }
    $self->{dbh}->commit;
    return \%stats;
}

# -- Minimal sfnt (TTF/OTF) parser -----------------------------------
# Just enough to extract `name` table records and glyph count.

sub _sfnt_tables {
    my ($blob) = @_;
    return () if length($blob) < 12;
    my $num = unpack('n', substr($blob, 4, 2));
    my %t;
    for my $i (0 .. $num - 1) {
        my $rec = substr($blob, 12 + $i * 16, 16);
        my ($tag, undef, $off, $len) = unpack('a4 N N N', $rec);
        $t{$tag} = { offset => $off, length => $len };
    }
    return %t;
}

sub _sfnt_cmap_ranges {
    my ($blob, $tab) = @_;
    my $base = $tab->{offset};
    return () if $base + 4 > length($blob);
    my (undef, $num) = unpack('nn', substr($blob, $base, 4));
    my @subs;
    for my $i (0 .. $num - 1) {
        my ($plat, $enc, $off) = unpack('nnN', substr($blob, $base + 4 + $i * 8, 8));
        push @subs, { plat => $plat, enc => $enc, offset => $base + $off };
    }
    # Pick a Unicode-capable subtable: prefer (3,10) UCS4, then (3,1) UCS2, then (0,*).
    my @prio = (
        (grep { $_->{plat} == 3 && $_->{enc} == 10 } @subs),
        (grep { $_->{plat} == 3 && $_->{enc} == 1  } @subs),
        (grep { $_->{plat} == 0 } @subs),
    );
    return () unless @prio;
    my $sub = $prio[0];
    my $off = $sub->{offset};
    my $fmt = unpack('n', substr($blob, $off, 2));
    my @ranges;
    if ($fmt == 4) {
        my $segX2 = unpack('n', substr($blob, $off + 6, 2));
        my $seg = $segX2 / 2;
        my $end_off   = $off + 14;
        my $start_off = $end_off + 2 + $segX2;   # +reservedPad
        for my $i (0 .. $seg - 1) {
            my $end   = unpack('n', substr($blob, $end_off   + $i * 2, 2));
            my $start = unpack('n', substr($blob, $start_off + $i * 2, 2));
            next if $start == 0xFFFF;   # sentinel
            push @ranges, [$start, $end];
        }
    } elsif ($fmt == 12) {
        my $ngroups = unpack('N', substr($blob, $off + 12, 4));
        for my $i (0 .. $ngroups - 1) {
            my ($s, $e) = unpack('NN', substr($blob, $off + 16 + $i * 12, 8));
            push @ranges, [$s, $e];
        }
    }
    return @ranges;
}

sub _sfnt_name_records {
    my ($blob, $tab) = @_;
    my $base = $tab->{offset};
    return () if $base + 6 > length($blob);
    my (undef, $count, $str_off) = unpack('nnn', substr($blob, $base, 6));
    my $strings_base = $base + $str_off;
    my %out;   # name_id => string (best candidate wins)
    for my $i (0 .. $count - 1) {
        my $rec = substr($blob, $base + 6 + $i * 12, 12);
        my ($plat, $enc, $lang, $nid, $slen, $soff) = unpack('nnnnnn', $rec);
        my $raw = substr($blob, $strings_base + $soff, $slen);
        my $str;
        if ($plat == 3 || ($plat == 0)) {
            # UTF-16BE
            $str = eval { require Encode; Encode::decode('UTF-16BE', $raw) } // $raw;
        } else {
            $str = $raw;
        }
        $str =~ s/\0//g;
        # Prefer English (lang 0x0409 / 0) -- only overwrite if we don't have one yet,
        # or if this is the english record
        my $is_english = ($plat == 3 && $lang == 0x0409) || ($plat == 1 && $lang == 0) || ($plat == 0);
        if (!exists $out{$nid} || $is_english) {
            $out{$nid} = $str;
        }
    }
    return %out;
}

1;
__END__

=head1 NAME

Pslib::FontDB -- SQLite-backed PostScript font registry

=head1 SYNOPSIS

  use Pslib::FontDB;

  my $db = Pslib::FontDB->new("$ENV{HOME}/.pslib/fonts.db");

  $db->import_font('/usr/share/fonts/dejavu/DejaVuSans.ttf');
  $db->import_font('./fonts/EType-Normal.pfb');

  my $row = $db->get_font('Helvetica');
  print "encoding=$row->{encoding_class} cyr=$row->{has_cyrillic}\n";

  for my $f (@{ $db->list }) {
      printf "%-30s %-8s %-10s cyr=%d\n",
          $f->{ps_font_name}, $f->{format},
          $f->{encoding_class}, $f->{has_cyrillic};
  }

=head1 STATUS

Skeleton -- works for PFB/PFA classification + storage. TODO:

=over

=item * TTF / OTF metadata via sfnt parsing (FreeType bindings or pure-Perl)

=item * cyrillic_widths_ok via gs stringwidth measurement subprocess

=item * Auto-import scan of /usr/share/fonts on first new()

=item * pslib-font CLI wrapper (bin/pslib-font)

=item * C port (libpslib_fontdb) once API stabilizes

=back

=cut
