#!/usr/bin/perl
# 01_import_and_list.pl -- bootstrap demo: open fresh DB, import some
# system fonts + the bundled EType-Normal, then list.
use strict;
use warnings;
use FindBin qw($Bin);
use lib "$Bin/../lib";
use Pslib::FontDB;

my $DB = "$Bin/../fonts.db";
unlink $DB;   # demo: start fresh every time

my $db = Pslib::FontDB->new($DB);

my @CANDIDATES = (
    "$Bin/../../smookerps/fonts/EType-Normal.pfb",
    "/usr/share/fonts/urw-fonts/NimbusSans-Regular.t1",
    "/usr/share/fonts/urw-fonts/NimbusSans-Regular.pfb",
    "/usr/share/fonts/urw-fonts/NimbusRoman-Regular.t1",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/liberation-fonts/LiberationSans-Regular.ttf",
);

for my $path (@CANDIDATES) {
    next unless -e $path;
    my $r = eval { $db->import_font($path) };
    if ($@) {
        print "  FAIL  $path: $@";
        next;
    }
    if ($r->{already_present}) {
        printf "  SKIP  %s -- already present (%s)\n",
            $path, $r->{ps_font_name};
    } else {
        printf "  ADD   %s -> %s (%s, enc=%s, cyr=%d, glyphs=%d)\n",
            $path, $r->{ps_font_name},
            $r->{format} // '?',
            $r->{encoding_class} // '?',
            $r->{has_cyrillic} // 0,
            $r->{glyph_count} // 0;
    }
}

print "\n=== Catalog ===\n";
my $rows = $db->list;
printf "%-30s %-7s %-10s %-3s %-7s\n",
    'name', 'format', 'encoding', 'cyr', 'glyphs';
print '-' x 65, "\n";
for my $f (@$rows) {
    printf "%-30s %-7s %-10s %-3d %-7d\n",
        $f->{ps_font_name} // '?',
        $f->{format}       // '?',
        $f->{encoding_class} // '?',
        $f->{has_cyrillic} // 0,
        $f->{glyph_count}  // 0;
}
printf "\n%d font(s) in db (%s)\n", scalar @$rows, $DB;
