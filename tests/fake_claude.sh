#!/bin/bash
# Stand-in for the `claude` CLI, used ONLY by the smoke tests. It never contacts anything.
# It prints a JSON result in the same shape as `claude -p --output-format json`, with SYNTHETIC numbers.
#   FAKE_LOG          file that receives one line per invocation (arguments + whether an API key was visible)
#   FAKE_SETUP_TOKENS tokens in a setup call (default 9000);  FAKE_FLOOR_TOKENS for the hello call (default 3000)
#   FAKE_RESUME       hit (default) | miss
#   FAKE_COST         total_cost_usd per call (default 0.01)
#   FAKE_FAIL         1 = every call returns is_error=true and exits 1;  FAKE_FAIL_ON=resume = only resume calls
set -u
if [ "${1:-}" = "--version" ]; then echo "0.0.0-fake (Claude Code)"; exit 0; fi
mode=floor; sid="00000000-0000-4000-8000-00000000f100"
args=("$@")
for i in "${!args[@]}"; do
  case "${args[$i]}" in
    --session-id) mode=setup;  sid="${args[$((i+1))]}";;
    --resume)     mode=resume; sid="${args[$((i+1))]}";;
  esac
done
[ -n "${FAKE_LOG:-}" ] && echo "mode=$mode keyset=${ANTHROPIC_API_KEY:+yes} args=$*" >> "$FAKE_LOG"
if [ ! -t 0 ]; then cat >/dev/null; fi
setup="${FAKE_SETUP_TOKENS:-9000}"; floor="${FAKE_FLOOR_TOKENS:-3000}"; cost="${FAKE_COST:-0.01}"
fail=0
[ "${FAKE_FAIL:-0}" = "1" ] && fail=1
[ "${FAKE_FAIL_ON:-}" = "$mode" ] && fail=1
case "$mode" in
  floor)  cc=$floor; cr=0 ;;
  setup)  cc=$setup; cr=0 ;;
  resume) if [ "${FAKE_RESUME:-hit}" = "miss" ]; then cc=$setup; cr=0; else cc=50; cr=$setup; fi ;;
esac
if [ "$fail" = "1" ]; then
  jq -n --arg sid "$sid" '{type:"result",subtype:"error_during_execution",is_error:true,api_error_status:429,result:"rate limit reached (fixture)",session_id:$sid,total_cost_usd:0,usage:{input_tokens:0,cache_creation_input_tokens:0,cache_read_input_tokens:0,output_tokens:0}}'
  exit 1
fi
jq -n --arg sid "$sid" --argjson cc "$cc" --argjson cr "$cr" --argjson cost "$cost" \
  '{type:"result",subtype:"success",is_error:false,api_error_status:null,result:"OK",session_id:$sid,total_cost_usd:$cost,
    usage:{input_tokens:6,cache_creation_input_tokens:$cc,cache_read_input_tokens:$cr,output_tokens:5,
           cache_creation:{ephemeral_5m_input_tokens:0,ephemeral_1h_input_tokens:$cc}}, _fixture:"synthetic, not a measurement"}'
