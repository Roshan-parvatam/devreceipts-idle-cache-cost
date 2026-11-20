#!/bin/bash
# Make a publishable copy of the raw results: session ids replaced by short hashes, .err files left out.
# Fails (and removes the copy) if anything that looks like a home path or an email address is still in it.
#   eval/scrub.sh [SRC=eval/results] [DST=eval/results-public]
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="${1:-$HERE/results}"
DST="${2:-$HERE/results-public}"
[ -d "$SRC" ] || { echo "no results folder: $SRC" >&2; exit 1; }
rm -rf "$DST"
python3 -I "$HERE/analyze.py" scrub "$SRC" "$DST" || exit 1
if grep -rEn '/Users/|/home/|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[a-z]{2,}' "$DST" >/dev/null 2>&1; then
  echo "refusing to publish: personal-looking text found:" >&2
  grep -rEn '/Users/|/home/|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[a-z]{2,}' "$DST" | head -n 10 >&2
  rm -rf "$DST"; exit 1
fi
echo "scrubbed copy written to $DST"
