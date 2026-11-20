#!/bin/bash
# Shared helpers, sourced by gap_eval.sh and chain_eval.sh. Not meant to be run directly.
# Uses your Claude Code PLAN login: no API key, nothing billed. Every call is a headless `claude -p`.
# (No `set -e` here on purpose: failures are handled explicitly so one failed call leaves a STOP file.)

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$LIB_DIR/.." && pwd)"
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi

# An API key in the environment would override the plan login and bill the API. Always removed.
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN

RESULTS="${RESULTS_DIR:-$LIB_DIR/results}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
MODEL="${MODEL:-sonnet}"
EFFORT="${EFFORT:-medium}"
MAX_BUDGET_USD="${MAX_BUDGET_USD:-1}"      # per-call runaway guard (a list-price estimate, not billing)
TARGET_SMALL="${TARGET_SMALL:-15000}"      # DESIGN TARGET for the setup total, tokens (not a result)
TARGET_LARGE="${TARGET_LARGE:-60000}"
SLEEP_SCALE="${SLEEP_SCALE:-1}"            # tests set 0 so gaps do not really wait
STAGGER_S="${STAGGER_S:-20}"               # seconds between session starts (limits simultaneous large writes)
MAX_PAR="${MAX_PAR:-12}"
PROMPT_OK="Reply with only: OK"

die() { echo "$1" >&2; exit "${2:-1}"; }

preflight() {
  # Safety net for the smoke tests: with NO_MODEL_CALLS=1 only the stub CLI may run.
  if [ "${NO_MODEL_CALLS:-0}" = "1" ] && [ "$(basename "$CLAUDE_BIN")" != "fake_claude.sh" ]; then
    die "NO_MODEL_CALLS=1: refusing to run the real claude CLI" 3
  fi
  [ -n "${CUM_COST_CAP_USD:-}" ] || die "set CUM_COST_CAP_USD (cap on summed total_cost_usd, a list-price estimate; see PLAN.md) before running"
  command -v jq >/dev/null || die "jq is required (brew install jq)"
  command -v python3 >/dev/null || die "python3 is required"
  command -v "$CLAUDE_BIN" >/dev/null || die "claude CLI not found"
  mkdir -p "$RESULTS"
}

# Keep the Mac awake for the long waits (a sleeping Mac would stretch the gaps and ruin them).
keep_awake() {
  if [ -z "${IDLE_CAFFEINATED:-}" ] && command -v caffeinate >/dev/null; then
    export IDLE_CAFFEINATED=1
    exec caffeinate -ims "$@"
  fi
}

now_s()   { perl -MTime::HiRes=time -e 'printf "%.2f", time'; }
utc_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
new_uuid() { python3 -c 'import uuid; print(uuid.uuid4())'; }

# ---- stop rules ----
stop_now()  { [ -e "$RESULTS/STOP" ]; }
stop_with() { echo "$1" > "$RESULTS/STOP"; echo "STOP: $1" >&2; }

# Sum of the cost estimates so far. total_cost_usd of a resumed call is CUMULATIVE for its session (it includes the setup
# call), and so are the chain turns: count the largest total per session folder once. Files directly in RESULTS (the floor)
# count on their own. meta.json is never counted.
total_cost() {
  find "$RESULTS" -name '*.json' ! -name meta.json -print 2>/dev/null | while IFS= read -r f; do
    c=$(jq -r '.total_cost_usd // 0' "$f" 2>/dev/null || echo 0)
    d=$(dirname "$f"); if [ "$d" = "$RESULTS" ]; then k="$f"; else k="$d"; fi
    printf '%s\t%s\n' "$k" "${c:-0}"
  done | awk -F'\t' '{ if (!($1 in m) || $2+0 > m[$1]) m[$1]=$2+0 } END { s=0; for (k in m) s+=m[k]; printf "%.6f\n", s }'
}

check_cap() {
  local t over
  t=$(total_cost)
  over=$(awk -v t="$t" -v c="$CUM_COST_CAP_USD" 'BEGIN{print (t>c)?1:0}')
  if [ "$over" = "1" ]; then stop_with "cumulative cost estimate \$$t is over the cap \$$CUM_COST_CAP_USD"; return 1; fi
  return 0
}

# claude_call OUT CWD STDIN_FILE|"" ARGS...
# Runs the CLI in CWD, JSON to OUT, stderr to OUT.err, real wall seconds to OUT-without-.json + .wall.
# Writes the STOP file and returns 1 on any error, rate-limit text, non-JSON output or cost-cap breach.
claude_call() {
  local out="$1" cwd="$2" stdin_file="$3" rc=0 t0 t1 bad=""
  shift 3
  stop_now && return 1
  check_cap || return 1
  t0=$(now_s)
  if [ -n "$stdin_file" ]; then
    ( cd "$cwd" && "$CLAUDE_BIN" "$@" < "$stdin_file" ) > "$out" 2> "$out.err" || rc=$?
  else
    ( cd "$cwd" && "$CLAUDE_BIN" "$@" < /dev/null ) > "$out" 2> "$out.err" || rc=$?
  fi
  t1=$(now_s)
  awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.1f", b-a}' > "${out%.json}.wall"
  if ! jq -e . "$out" >/dev/null 2>&1; then bad="output is not JSON (exit code $rc)"
  elif [ "$(jq -r '.is_error // false' "$out")" = "true" ]; then bad="is_error ($(jq -r '.subtype // "?"' "$out"))"
  elif [ "$(jq -r '.api_error_status // "null"' "$out")" != "null" ]; then bad="api_error_status $(jq -r '.api_error_status' "$out")"
  elif [ "$rc" -ne 0 ]; then bad="exit code $rc"
  elif jq -r '.result // ""' "$out" | grep -Eiq 'rate.?limit|usage limit|limit reached'; then bad="rate-limit text in the reply"
  elif grep -Eiq 'rate.?limit|usage limit|limit reached' "$out.err"; then bad="rate-limit text on stderr"
  fi
  if [ -n "$bad" ]; then stop_with "$bad: $out"; return 1; fi
  return 0
}

COMMON_FLAGS=(--model "$MODEL" --effort "$EFFORT" --output-format json --setting-sources project,local --max-budget-usd "$MAX_BUDGET_USD")

# ---- sizes: documents are sized from the measured floor ----
load_sizes() {
  FLOOR_TOTAL=""; CPT="4.0"
  [ -f "$RESULTS/sizes.env" ] && . "$RESULTS/sizes.env"          # may set CPT (calibrated by analyze.py --sizes)
  FLOOR_TOTAL=""
  if [ -f "$RESULTS/floor.json" ]; then
    FLOOR_TOTAL=$(jq '(.usage.input_tokens // 0) + (.usage.cache_creation_input_tokens // 0) + (.usage.cache_read_input_tokens // 0)' "$RESULTS/floor.json")
  fi
  if [ -z "$FLOOR_TOTAL" ] || [ "$FLOOR_TOTAL" -le 0 ]; then
    die "no floor measurement yet: run 'eval/gap_eval.sh pilot' first (it measures the empty-project floor)"
  fi
  # fail before any call if a target leaves no room for a document (found in the real pilot)
  doc_tokens_for small >/dev/null
  doc_tokens_for large >/dev/null
}

doc_tokens_for() {   # size label -> document tokens = target setup total minus the shared prefix
  local target; if [ "$1" = "small" ]; then target="$TARGET_SMALL"; else target="$TARGET_LARGE"; fi
  local dt=$((target - FLOOR_TOTAL))
  [ "$dt" -ge 100 ] || die "target $target tokens is not above the measured floor $FLOOR_TOTAL: set TARGET_$(echo "$1" | tr a-z A-Z) higher"
  echo "$dt"
}

# make_prompt LABEL SIZE OUTFILE -> writes document + final instruction; echoes the character count of the document
make_prompt() {
  local label="$1" size="$2" out="$3" dt
  dt=$(doc_tokens_for "$size") || exit 1
  python3 -I "$LIB_DIR/gen_context.py" --tokens "$dt" --cpt "$CPT" --label "$label" > "$out" || return 1
  wc -c < "$out" | tr -d ' '
  printf '\n\n---\n%s\n' "$PROMPT_OK" >> "$out"
}

reply_ok() { [ "$(jq -r '.result // ""' "$1" | tr -d '[:space:]')" = "OK" ]; }
