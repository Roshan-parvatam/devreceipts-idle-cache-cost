#!/bin/bash
# One long session with NO idle gap: a setup call and then N-1 resumes back to back, usage logged for every turn.
# Shows what each message costs in tokens as a conversation grows when the cache stays warm. Spends plan allowance.
#
#   CUM_COST_CAP_USD=<cap> eval/chain_eval.sh [TURNS=12]     needs the floor from `gap_eval.sh pilot`
set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"
keep_awake "$0" "$@"
preflight

TURNS="${1:-12}"
case "$TURNS" in ''|*[!0-9]*) die "usage: $0 [TURNS]";; esac
[ "$TURNS" -ge 2 ] || die "TURNS must be at least 2"
load_sizes

D="$RESULTS/chain"
[ -f "$D/meta.json" ] && { echo "skip: chain finished already"; exit 0; }
mkdir -p "$D"
VERSION="$("$CLAUDE_BIN" --version 2>/dev/null | head -n1)"
SID="$(new_uuid)"; WD="$(mktemp -d)"; PF="$(mktemp)"
trap 'rm -rf "$WD" "$PF"' EXIT
CHARS="$(make_prompt "chain-small" small "$PF")" || exit 1
STARTED="$(utc_now)"

echo "chain turn 1 (setup) ..."
claude_call "$D/turn-01.json" "$WD" "$PF" -p --session-id "$SID" "${COMMON_FLAGS[@]}" || exit 1
for i in $(seq 2 "$TURNS"); do
  n="$(printf '%02d' "$i")"; prev="$(printf '%02d' $((i - 1)))"
  # use the id the previous reply reports, in case a resume hands out a new one
  cur="$(jq -r '.session_id // empty' "$D/turn-$prev.json")"; cur="${cur:-$SID}"
  echo "chain turn $i ..."
  claude_call "$D/turn-$n.json" "$WD" "" -p "$PROMPT_OK" --resume "$cur" "${COMMON_FLAGS[@]}" || exit 1
done
jq -n --arg ver "$VERSION" --arg started "$STARTED" --argjson turns "$TURNS" --argjson chars "$CHARS" --arg sid "$SID" \
  '{cell:"chain", size_label:"small", turns:$turns, claude_version:$ver, started_at_utc:$started, doc_chars:$chars, session_id:$sid}' > "$D/meta.json"
echo "done. Per-turn usage is in $D/turn-*.json"
