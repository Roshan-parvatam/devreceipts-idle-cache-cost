#!/bin/bash
# Idle-gap experiment. Uses your Claude Code plan login: NO API key, nothing billed. Spends plan allowance.
#
#   CUM_COST_CAP_USD=<cap> eval/gap_eval.sh pilot       empty-project floor + 4 sessions (small at 0, 6, 65 min; large at 65)
#   CUM_COST_CAP_USD=<cap> eval/gap_eval.sh full [N]    every gap x {small, large} x N reps (default 3); needs the pilot's floor
#
# One session = a setup call (a generated document pasted in, reply "OK", session saved), a wait, then a resume
# call (`--resume <id>`, reply "OK"). Each session gets its OWN document so sessions cannot warm each other.
# Read /usage before and after (PLAN.md), and run this as a background job: the 65-minute waits take over an hour.
#
# Env: GAPS="0 4 6 65" (minutes), ONLY="small 0 1;small 6 1" (just those sessions), CUM_COST_CAP_USD (required), MODEL=sonnet, EFFORT=medium, MAX_BUDGET_USD=1,
#      TARGET_SMALL=15000, TARGET_LARGE=60000 (setup totals, tokens), MAX_PAR=12, STAGGER_S=20
# Any error or rate-limit text, or going over the cost cap, writes results/STOP and no further calls are made.
set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"
keep_awake "$0" "$@"
preflight

MODE="${1:-}"; N=1
case "$MODE" in
  pilot) ;;
  full)  N="${2:-3}" ;;
  *)     die "usage: $0 pilot | full [N]" ;;
esac
GAPS="${GAPS:-0 4 6 65}"
VERSION="$("$CLAUDE_BIN" --version 2>/dev/null | head -n1)"

run_floor() {
  [ -f "$RESULTS/floor.json" ] && { echo "skip: floor.json exists"; return 0; }
  local wd; wd="$(mktemp -d)"
  echo "floor: one empty-project call to measure the shared system/tool prefix ..."
  claude_call "$RESULTS/floor.json" "$wd" "" -p "$PROMPT_OK" "${COMMON_FLAGS[@]}" --no-session-persistence
  local rc=$?
  rm -rf "$wd"; return $rc
}

wait_until() {   # wait_until EPOCH ; sleeps in short steps so a STOP written by another session ends the wait
  local target="$1" rem
  while :; do
    stop_now && return 1
    rem=$(awk -v t="$target" -v n="$(now_s)" 'BEGIN{r=t-n; print (r>0)?r:0}')
    [ "$(awk -v r="$rem" 'BEGIN{print (r>0)?1:0}')" = "1" ] || return 0
    sleep "$(awk -v r="$rem" 'BEGIN{print (r>15)?15:r}')"
  done
}

run_session() {   # run_session SIZE GAP_MINUTES REP
  local size="$1" gmin="$2" rep="$3" gs=$(( $2 * 60 ))
  local name="gap-${size}-g${gs}-rep${rep}" d="$RESULTS/gap-${size}-g$(( $2 * 60 ))-rep${3}"
  [ -f "$d/meta.json" ] && { echo "skip: $name"; return 0; }
  mkdir -p "$d"
  local sid wd pf chars started setup_end resume_start rc=0
  sid="$(new_uuid)"; wd="$(mktemp -d)"; pf="$(mktemp)"
  chars="$(make_prompt "$name" "$size" "$pf")" || { rm -rf "$wd" "$pf"; return 1; }
  started="$(utc_now)"
  echo "start: $name (setup now, resume after ${gmin} min)"
  if claude_call "$d/setup.json" "$wd" "$pf" -p --session-id "$sid" "${COMMON_FLAGS[@]}"; then
    setup_end="$(now_s)"
    if wait_until "$(awk -v e="$setup_end" -v g="$gs" -v s="$SLEEP_SCALE" 'BEGIN{printf "%.2f", e + g*s}')"; then
      resume_start="$(now_s)"
      if claude_call "$d/resume.json" "$wd" "" -p "$PROMPT_OK" --resume "$sid" "${COMMON_FLAGS[@]}"; then
        jq -n --arg cell gap --argjson rep "$rep" --arg size "$size" --argjson gp "$gs" \
              --argjson ga "$(awk -v a="$setup_end" -v b="$resume_start" 'BEGIN{printf "%.1f", b-a}')" \
              --arg ver "$VERSION" --arg started "$started" \
              --arg sw "$(cat "$d/setup.wall")" --arg rw "$(cat "$d/resume.wall")" \
              --argjson chars "$chars" --arg sid "$sid" --arg rsid "$(jq -r '.session_id // ""' "$d/resume.json")" \
              '{cell:$cell, rep:$rep, size_label:$size, gap_planned_s:$gp, gap_actual_s:$ga, claude_version:$ver,
                started_at_utc:$started, setup_wall_s:($sw|tonumber), resume_wall_s:($rw|tonumber),
                doc_chars:$chars, session_id:$sid, resume_session_id:$rsid}' > "$d/meta.json"
        echo "done: $name"
      else rc=1; fi
    else rc=1; fi
  else rc=1; fi
  rm -rf "$wd" "$pf"
  return $rc
}

if [ "$MODE" = "pilot" ]; then
  run_floor || exit 1
  load_sizes
  SESSIONS=("small 0 1" "small 6 1" "small 65 1" "large 65 1")
else
  load_sizes
  SESSIONS=()
  for rep in $(seq 1 "$N"); do
    for g in $(printf '%s\n' $GAPS | sort -rn); do      # longest waits start first
      for size in large small; do SESSIONS+=("$size $g $rep"); done
    done
  done
fi

# ONLY="small 0 1;small 6 1" runs just those sessions (size, gap in minutes, rep), e.g. to redo some after a fix
if [ -n "${ONLY:-}" ]; then IFS=';' read -ra SESSIONS <<< "$ONLY"; fi

PIDS=()
for spec in "${SESSIONS[@]}"; do
  stop_now && break
  while [ "$(jobs -rp | wc -l | tr -d ' ')" -ge "$MAX_PAR" ]; do sleep 0.2; done
  # shellcheck disable=SC2086
  run_session $spec &
  PIDS+=($!)
  sleep "$(awk -v s="$STAGGER_S" -v k="$SLEEP_SCALE" 'BEGIN{print s*k}')"
done

FAIL=0
for p in "${PIDS[@]:-}"; do [ -n "$p" ] && { wait "$p" || FAIL=1; }; done
if stop_now; then
  echo "STOPPED: $(cat "$RESULTS/STOP"). Read it, fix the cause, delete $RESULTS/STOP, rerun (finished sessions are skipped)." >&2
  exit 1
elif [ "$FAIL" = "1" ]; then
  echo "Some sessions did not run or did not finish (see the lines above; no STOP file was written). Fix the cause and rerun: finished sessions are skipped." >&2
  exit 1
fi
echo "done. Analyze with: python3 eval/analyze.py $RESULTS"
