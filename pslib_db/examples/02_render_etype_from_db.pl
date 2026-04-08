#!/usr/bin/perl
# 02_render_etype_from_db.pl -- end-to-end test:
#
# 1. Open the SQLite font registry
# 2. Pull EType-Normal's font_data BLOB
# 3. Decode the PFB segments to a PFA stream (binary -> hex inline)
# 4. Emit a minimal PostScript document that:
#      - includes the PFA inline in the prolog (no FONTPATH dependency)
#      - selects EType-Normal at several point sizes
#      - draws latin sample text + a 16-row glyph grid
# 5. ps2pdf to a viewable PDF
#
# Goal: prove that the SQLite catalog is sufficient -- the .pfb file
# never has to exist on disk during render. The DB is the source of
# truth.

use strict;
use warnings;
use FindBin qw($Bin);
use lib "$Bin/../lib";
use Pslib::FontDB;

my $DB     = "$Bin/../fonts.db";
my $FONT   = 'EType-Normal';
my $OUT_PS = "$Bin/../etype_dbtest.ps";
my $OUT_PDF = "$Bin/../etype_dbtest.pdf";

# -- 1. open db, fetch row ------------------------------------------
my $db  = Pslib::FontDB->new($DB);
my $row = $db->get_font($FONT)
    or die "no font '$FONT' in DB. Run examples/01_import_and_list.pl first.\n";

printf "Pulled %s from DB: %d bytes (%s, enc=%s, glyphs=%d)\n",
    $row->{ps_font_name},
    length($row->{font_data}),
    $row->{format},
    $row->{encoding_class},
    $row->{glyph_count};

$db->bump_use($FONT);

# -- 2. PFB binary -> PFA ASCII --------------------------------------
sub pfb_to_pfa {
    my ($blob) = @_;
    my $pfa = '';
    my $i = 0;
    while ($i < length($blob)) {
        last if ord(substr($blob, $i, 1)) != 0x80;
        my $type = ord(substr($blob, $i + 1, 1));
        last if $type == 3;
        my $len = unpack('V', substr($blob, $i + 2, 4));
        my $body = substr($blob, $i + 6, $len);
        $i += 6 + $len;
        if ($type == 1) {
            $pfa .= $body;
        } elsif ($type == 2) {
            my $hex = unpack('H*', $body);
            for (my $j = 0; $j < length($hex); $j += 64) {
                $pfa .= substr($hex, $j, 64) . "\n";
            }
        } else {
            die "unknown pfb segment type $type at offset $i\n";
        }
    }
    return $pfa;
}

my $pfa;
if ($row->{format} eq 'pfb') {
    $pfa = pfb_to_pfa($row->{font_data});
} elsif ($row->{format} eq 'pfa') {
    $pfa = $row->{font_data};
} else {
    die "format $row->{format} not supported by this skeleton renderer\n";
}

# -- 3. emit PostScript ---------------------------------------------
open my $ps, '>:raw', $OUT_PS or die "open $OUT_PS: $!";

print $ps "%!PS-Adobe-3.0\n";
print $ps "%%Creator: pslib_db skeleton render test\n";
print $ps "%%Pages: 1\n";
print $ps "%%DocumentMedia: A4 595 842 0 () ()\n";
print $ps "%%EndComments\n";

# inline embedded font in the prolog
print $ps "%%BeginProlog\n";
print $ps "%%BeginResource: font $FONT\n";
print $ps $pfa;
print $ps "%%EndResource\n";
print $ps "%%EndProlog\n";

print $ps "%%Page: 1 1\n";

# Title in Helvetica (gs builtin)
print $ps "/Helvetica findfont 16 scalefont setfont\n";
print $ps "50 800 moveto (pslib_db skeleton: $FONT pulled from SQLite) show\n";

print $ps "/Helvetica findfont 9 scalefont setfont\n";
my $size = length($row->{font_data});
print $ps "50 780 moveto (font_data BLOB: $size bytes; format $row->{format}; encoding_class $row->{encoding_class}) show\n";
print $ps "50 768 moveto (No FONTPATH, no on-disk PFB lookup. Renderer never sees the file.) show\n";

# Sample lines at multiple sizes
my @sizes = (24, 18, 14, 12, 10);
my $y = 720;
for my $sz (@sizes) {
    print $ps "/$FONT findfont $sz scalefont setfont\n";
    print $ps "50 $y moveto (${sz}pt: The quick brown fox jumps over the lazy dog) show\n";
    $y -= $sz + 6;
}

# 16x16 glyph grid in default Encoding
print $ps "/Helvetica findfont 9 scalefont setfont\n";
print $ps "50 580 moveto (Default Encoding glyph grid -- byte 0x00..0xFF, row=high nibble, col=low nibble:) show\n";

my $grid_left = 80;
my $grid_top  = 560;
my $cell      = 24;
my $glyph_sz  = 14;

# column headers
print $ps "/Helvetica findfont 7 scalefont setfont\n";
for my $col (0..15) {
    my $x = $grid_left + $col * $cell + $cell/2 - 3;
    my $hy = $grid_top + 4;
    printf $ps "%g %g moveto (%X) show\n", $x, $hy, $col;
}

for my $row_i (0..15) {
    # row label
    my $ly = $grid_top - $row_i * $cell - $cell + 8;
    print $ps "/Helvetica findfont 7 scalefont setfont\n";
    printf $ps "%g %g moveto (%02X) show\n", $grid_left - 18, $ly, $row_i * 16;
    # cells
    for my $col (0..15) {
        my $byte = $row_i * 16 + $col;
        my $cx = $grid_left + $col * $cell;
        my $cy = $grid_top - $row_i * $cell - $cell;
        # box
        print $ps "0.3 setlinewidth\n";
        printf $ps "newpath %g %g moveto %g 0 rlineto 0 %g rlineto %g 0 rlineto closepath stroke\n",
            $cx, $cy, $cell, $cell, -$cell;
        # glyph at byte index
        printf $ps "/$FONT findfont %g scalefont setfont\n", $glyph_sz;
        printf $ps "%g %g moveto (\\%03o) show\n",
            $cx + 4, $cy + 4, $byte;
    }
}

print $ps "showpage\n";
print $ps "%%EOF\n";
close $ps;

print "Wrote $OUT_PS (", -s $OUT_PS, " bytes)\n";

# -- 4. ps2pdf -------------------------------------------------------
system('ps2pdf', $OUT_PS, $OUT_PDF) == 0
    or die "ps2pdf failed: $?\n";
print "Wrote $OUT_PDF (", -s $OUT_PDF, " bytes)\n";

# -- 5. confirm bump_use worked -------------------------------------
my $r2 = $db->get_font($FONT);
printf "After render: use_count=%d, last_used_at=%s\n",
    $r2->{use_count}, $r2->{last_used_at};
