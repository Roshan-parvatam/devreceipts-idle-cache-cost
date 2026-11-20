# idle-cache-cost: what one Claude Code message costs after you step away

A measurement kit for DevReceipts Video #2. It resumes a saved Claude Code session after 0, 6, 55 and 65 minutes (configurable), at two context sizes, and logs the **tokens** of the resumed message: how many came from the prompt cache and how many were written again.

**Status: built, smoke-tested with a stub CLI, and run for real on 16 Nov 2026 (pilot, 24-session full run, 12-turn chain). Results are in `METRICS.md`; the scrubbed raw files (session ids replaced) are in `eval/results-public/`. The owner's `/usage` readings are still `TODO: measure`.**

## Needs
- Claude Code CLI logged in with your plan (no API key, usage credits off), `jq`, `python3`, `perl`. On macOS `caffeinate` keeps the Mac awake during the long waits.
- Python 3.10+ for the tests (pytest is the only dependency, pinned in `requirements.txt`).

## Run the tests (no model calls, no plan usage)
```bash
make test
```
The tests drive the scripts with `tests/fake_claude.sh`, a stand-in that prints synthetic JSON. `NO_MODEL_CALLS=1` makes the scripts refuse any other `claude` binary while testing.

## The experiment (spends plan allowance: read `PLAN.md` first)
```bash
cp .env.example .env              # no key goes in it
export CUM_COST_CAP_USD=0.80      # required; cap on summed total_cost_usd (a list-price estimate)
make pilot                        # empty-project floor + 4 sessions; read /usage before and after
python3 eval/analyze.py eval/results
python3 eval/analyze.py eval/results --sizes   # calibrate document sizes from the real floor
CUM_COST_CAP_USD=5 make eval      # full grid (n=3) + the 12-turn chain
make analyze
make scrub                        # eval/results-public: session ids replaced, safe to publish
```
Rules baked into the scripts: `ANTHROPIC_API_KEY` is always unset and `--bare` is never used. Any error, rate-limit text, non-JSON output, or going over the cost cap writes `eval/results/STOP` and no more calls are made. Finished sessions are skipped on a rerun. Delete `STOP` after you have read it.

## How it works
- `eval/gen_context.py` makes a filler document of about N tokens. Each session gets a different one (seed in the first line), because the cache matches on the prefix and a shared document would let sessions keep each other warm.
- `eval/gap_eval.sh` runs sessions: setup call, wait, `--resume` call. Raw JSON per call, plus `meta.json` with the planned and actual gap, CLI version and start time.
- `eval/chain_eval.sh` runs one 12-turn session with no gap, to see what each message costs as the context grows while the cache stays warm.
- `eval/analyze.py` reads the raw JSON and prints a table per cell (hit / miss / partial counts, median and range). The scoring rule is written in its docstring and in `PLAN.md` and was fixed before any run.
- `eval/scrub.sh` makes the publishable copy.

## What this does not claim
Tokens, not plan percentages, are the headline. `total_cost_usd` is the CLI's list-price estimate, not a bill and not how the plan counts usage. Headless `--resume` may differ from the interactive app. One model, one effort level, one account, n = 3 per cell. See `PLAN.md` section 6.

## Files
`PLAN.md` design, scoring, allowance estimate, approval note · `NOTES.md` failure log · `METRICS.md` results (full run, 16 Nov 2026) · `eval/` scripts · `tests/` smoke tests · `LICENSE` MIT
