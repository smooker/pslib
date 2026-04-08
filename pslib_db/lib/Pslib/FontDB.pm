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
    }
    return $self;
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

    $self->{dbh}->do(
        q{
        INSERT INTO fonts (
            ps_font_name, family, full_name, weight, italic_angle,
            format, sha256, file_size, original_filename,
            encoding_class, has_cyrillic, has_latin, has_greek,
            cyrillic_widths_ok, glyph_count,
            fontbbox_xmin, fontbbox_ymin, fontbbox_xmax, fontbbox_ymax,
            notes, font_data
        ) VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?, ?,?,?,?, ?,?)
        },
        undef,
        $info->{ps_font_name}, $info->{family}, $info->{full_name},
        $info->{weight}, $info->{italic_angle},
        $info->{format}, $sha, $size, $orig,
        $info->{encoding_class}, $info->{has_cyrillic}, $info->{has_latin},
        $info->{has_greek},
        $info->{cyrillic_widths_ok}, $info->{glyph_count},
        $info->{fontbbox_xmin}, $info->{fontbbox_ymin},
        $info->{fontbbox_xmax}, $info->{fontbbox_ymax},
        $meta{notes},
        $blob,  # BLOB last
    );

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
    } else {
        $ascii = '';   # TODO: TTF/OTF metadata extraction
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
