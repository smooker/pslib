#!/bin/bash
# install_local_deps.sh -- install Perl deps into pslib_db/local/
#
# pslib_db ships a prebuilt copy of DBD::SQLite for x86_64-linux under
# ./local/. If you're on a different architecture (or upgraded Perl),
# run this script to rebuild it from CPAN into the same prefix.
#
# Requires: cpan (gentoo: dev-lang/perl), gcc, sqlite3 dev headers
#           (gentoo emerge dev-perl/DBI dev-libs/expat for build deps).
#
# Usage:
#   ./install_local_deps.sh
#
# After: examples/0*.pl will use the rebuilt local/ tree automatically
# (Pslib::FontDB.pm bootstraps @INC from $module_dir/../../local/lib/perl5).

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
LOCAL="$DIR/local"

mkdir -p "$LOCAL"

export PERL_MM_USE_DEFAULT=1
export PERL_MM_OPT="INSTALL_BASE=$LOCAL"
export PERL_MB_OPT="--install_base $LOCAL"

# Force reinstall by passing -fT (notest, force):
cpan -fT DBD::SQLite

ls -lh "$LOCAL/lib/perl5/"*/auto/DBD/SQLite/SQLite.so 2>/dev/null \
    && echo "OK: $LOCAL is ready"
