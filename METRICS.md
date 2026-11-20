# Metrics

Pilot done (16 Nov 2026, 4 sessions + the empty-project call, 0 errors). Full run (24 sessions) and 12-turn chain done 16 Nov 2026, 0 errors, stop rules never fired. Rows come from `python3 eval/analyze.py eval/results`. The owner's `/usage` readings are still `TODO: measure`. Tokens are the headline; `total_cost_usd` is a list-price estimate, not a bill. Raw files: `eval/results/pilot/` (session ids are scrubbed by `eval/scrub.sh` before publishing).

Run facts: Claude Code 2.1.325. Model claude-sonnet-5-5, effort medium, plan login, headless `claude -p`. Pilot started 16 Nov 2026 about 14:25 UTC.

## Shared prefix (empty-project call, new session, empty folder)
Total input tokens F: 15,583 (2 plain, 6,517 written to the cache, 9,064 read from the cache). All 6,517 written tokens went into the 1-hour cache field; the 5-minute field was 0.
The first small-session design target was 15,000 tokens. It sat below the measured floor (15,583), so three pilot sessions never started (see NOTES.md); the target became 25,000.
Chars per token of the filler text, calibrated from the four pilot setups (median): 3.3225. The four values were 3.304 (large) and 3.34, 3.34 and 2.76 (small). The 2.76 session wrote about 2k more tokens at setup and at resume than its twin for unknown reasons.

## Pilot (1 session per cell; n = 1, so a hint and not a rate)
Resume tokens are what the resumed message used. Every call's cache writes were in the 1-hour field (5-minute field 0).

| Session | Setup total tokens | Resume cache_read | Resume cache_creation | Class (revised rule) |
|---|---|---|---|---|
| small, gap 0 | 26,863 | 20,846 | 6,449 | hit (this is the control) |
| small, gap 6 min | 24,889 | 20,780 | 4,140 | hit |
| small, gap 65 min | 24,896 | 9,064 | 17,851 | miss |
| large, gap 65 min | 69,355 | 9,064 | 60,322 | miss |

Reading it: at 6 minutes the resume read as much from the cache as the back-to-back one (20,780 vs 20,846), so the cached document did not expire at the 5-minute mark. At 65 minutes the resume read only the 9,064-token shared prefix and wrote everything else again (60,322 tokens in the large session). The full run (below) bracketed the break between 55 and 65 minutes.

List-price estimate per session (setup + resume own cost): small gap 0 $0.100, small gap 6 $0.083, small gap 65 $0.137, large gap 65 $0.484; empty-project call $0.027. Summed, each session counted once: $0.831. The large 65-minute resume alone cost $0.242 (the same as its setup, because it wrote the same number of tokens again).
Cost formula that reproduces the CLI's `total_cost_usd` exactly for these calls: input $2, 1-hour cache write $4, cache read $0.10, output $10 per million tokens (the cache-write price is therefore double the input price).
`/usage` before and after the pilot: TODO: measure (owner).
Checks: `--resume` kept the same session id: yes, 4 of 4. The prompt arrived intact over stdin: yes (all 4 replies were "OK" and the setup totals follow the document sizes). The 9,064-token shared prefix was already in the cache at every setup (read, not written).

## Full run (n = 3 per cell; median and min-max)
Run 16 Nov 2026, started about 15:40 UTC (21:12 IST), finished about 17:00 UTC. Gaps planned 0, 6, 55, 65 minutes (small about 25k tokens, large about 60k tokens at setup). Actual gaps were within 0.1 s of planned (all 24). `--resume` kept the same session id: 24 of 24. All 24 setup and resume replies were "OK". No STOP file, no errors, stop rules never fired (gap-0 sanity check: ok). Source: `python3 eval/analyze.py eval/results`.

| Gap (min) | Size | Classes | Setup total | Resume cache_read | Resume cache_creation |
|---|---|---|---|---|---|
| 0 | small | hit 3 of 3 | 25,048 (25,002-25,070) | 20,935 (20,891-20,961) | 4,142 (4,140-4,144) |
| 0 | large | hit 3 of 3 | 60,175 (60,136-60,250) | 56,062 (56,027-56,141) | 4,140 (4,140-4,144) |
| 6 | small | hit 3 of 3 | 25,015 (24,946-25,026) | 20,902 (20,835-20,913) | 4,144 (4,142-4,144) |
| 6 | large | hit 3 of 3 | 60,085 (59,869-60,098) | 55,972 (55,756-55,991) | 4,144 (4,138-4,144) |
| 55 | small | hit 3 of 3 | 25,055 (24,959-25,085) | 20,942 (20,846-20,974) | 4,144 (4,142-4,144) |
| 55 | large | hit 3 of 3 | 60,199 (59,965-60,388) | 56,090 (55,854-56,271) | 4,142 (4,140-4,148) |
| 65 | small | miss 3 of 3 | 24,975 (24,944-25,021) | 9,064 (9,064-9,064) | 15,942 (15,911-15,988) |
| 65 | large | miss 3 of 3 | 60,138 (59,974-60,291) | 9,064 (9,064-9,064) | 51,105 (50,941-51,258) |

Findings (each from the table above):
- **The "5-minute cache" did not show up in this setup.** At 6 minutes all 6 resumes (small and large) read the cached document, same as the back-to-back control. At 55 minutes all 6 still did.
- **At 65 minutes all 6 missed.** Each read only the 9,064-token shared prefix and wrote the rest of the context again (median 15,942 small, 51,105 large). So in this headless setup the break is between 55 and 65 minutes, which matches the 1-hour cache field: every cache write in every call went into the 1-hour field, the 5-minute field was 0.
- **Every resume wrote about 4,140 tokens even on a hit** (4,138-4,148 in all 18 hit sessions; same number for small and large). The cause is not known. It looks like a fixed per-resume cost, not growth with context size.
- **List-price cost of one resume (resume own cost = resume total minus setup total, median):** hit small $0.0187, hit large $0.0222; 65-minute miss small $0.0647, large $0.2054. A miss therefore cost about 3.5x (small) and 9.3x (large) a hit (derived from these medians). This is a list-price estimate, not a bill.
- Setup totals were within about 0.5% of the design targets, and the roughly 2k-token difference seen between two pilot setups did not recur in the 24 full-run setups (unexplained, not resolved).
- All results files summed (pilot + full run + chain, each session counted once): $5.39 list-price estimate (cap was $7).

## 12-turn chain (no gap, small context, one session, 12 messages in a row)
Per-turn tokens (input_tokens was 2 on every turn; output_tokens was 4 on every turn; all writes in the 1-hour field):

| Turn | cache_read | cache_creation |
|---|---|---|
| 1 (setup) | 9,064 | 16,068 |
| 2 (first resume) | 21,021 | 4,144 |
| 3 | 25,145 | 53 |
| 4-12 | 25,178 rising by 33 each turn to 25,442 | 53 each |

Reading it: after the first resume, each extra message only wrote 53 new tokens and read the whole earlier context from the cache. The first resume (turn 2) is the only one with the roughly 4,140-token rewrite. List-price cost of the session grew from $0.0652 (turn 1) to $0.1118 (turn 12) in total: about $0.0028 per extra turn, derived from the cost field.

## Plan usage (owner's `/usage`)
Before the full run: TODO: measure. After: TODO: measure. Pilot ratio for conversion: TODO: measure.

## Not measured (honest list)
Interactive (non-headless) resume (the app may behave differently), what happens between 55 and 65 minutes (no gap tested there), other models, other effort levels, real codebase contexts instead of filler text, how the plan converts tokens to limits, the cause of the roughly 2k-token difference between two small setups.
