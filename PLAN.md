# PLAN: idle-cache-cost (DevReceipts Video #2)

Status: **planned, built, and run (pilot, full run and chain done on 16 Nov 2026).** Results are in `METRICS.md`; section 8 below lists the original result fields, now filled there (the owner's `/usage` readings are still `TODO: measure`).
Source of the design: `channel/HANDOFF.md` (architect review) plus the changes listed under "Changes from the handoff". `channel/ideas/idle-cache-cost.md` does not exist (no `/idea` file was written; the handoff holds the demand evidence).

## 1. The claim (it can be false)
After the user is away for a while, the next message in a resumed Claude Code session **re-writes the whole context to the cache instead of reading it**, and the break happens at the 5-minute mark.
Two parts, both testable: (a) a long gap turns a cache read into a cache write; (b) the break is at 5 minutes.
Part (b) is already in doubt: the real Video #1 result `eval/results/baseline-run1.json` in `claude-code-review-team` records all of its cache writes in the **1-hour** field (`ephemeral_1h_input_tokens`, 5m = 0). If plan logins write 1-hour entries, a 6-minute gap should still be a hit and the cliff would sit near 60 minutes. One file is a hint, not a result; the pilot checks it.

## 2. Design
| Item | Choice |
|---|---|
| Model, effort | Sonnet, medium (same as Video #1). `--setting-sources project,local`, plan login, API key unset. |
| Session | Setup call: a generated document in the prompt (via stdin) ending "Reply with only: OK", session saved (`--session-id <uuid>`, persistent temp working dir). Resume call: `-p "Reply with only: OK" --resume <uuid>` after the gap. |
| Gaps (minutes) | 0, 4, 6, 65 (handoff). Configurable with `GAPS="..."`. See decision D1. |
| Context size | Small and large. **Targets** for the setup total input tokens: 15,000 and 60,000. The document is sized as target minus the measured empty-project floor. |
| Reps | n = 3 per cell: 4 gaps x 2 sizes x 3 = 24 sessions (48 calls). |
| Extra runs | One 12-turn chain, no gap, small context (`eval/chain_eval.sh`). One empty-project "hello" floor call (measured first, inside `gap_eval.sh pilot`). |
| Identical across runs | Model, effort, flags, prompt wording, document generator, tools (defaults), empty working directory, reply instruction. |
| Different per session | The document text. Each session has its own seed in the first line so sessions cannot warm each other's cache (prefix match). Only the system prompt/tool prefix is shared. |
| Baseline | Gap 0 is the baseline (no idle time). The floor call is the "nothing in context" baseline. |
| Is it just better instructions? | No instructions vary. The only variable is elapsed time (and context size). |
| Deterministic scoring | Tokens from the CLI's JSON, classified by `eval/analyze.py`. No judge, no answer key. `reply_ok` only checks the reply was "OK". |
| Control | The gap-0 cell: if it is not mostly cache reads, the instrument is wrong (stop rule). |

### Scoring (fixed before any run)
T = setup total input tokens (input + cache_creation + cache_read). F = shared prefix, the total of the empty-project hello call.
- **hit**: resume `cache_read` >= 0.9 x T
- **miss**: resume `cache_creation` >= 0.9 x (T - F)   (the document part was written again)
- **partial**: anything else (for example prefix read, document partly re-written)
- **error / incomplete / invalid**: the run failed, has no resume, or T is not usable
Reported per cell: n, class counts, median and min-max of resume cache_read and cache_creation, plus the 5m/1h split of every write. **Tokens are the headline.** `total_cost_usd` is a list-price estimate, not a bill and not plan burn.

### Revision after the pilot (16 Nov 2026, before the full run): the "hit" rule and the gap-0 check
The pilot showed that every resume re-writes a few thousand tokens even with no gap (small, gap 0: 26,863 setup total, resume read 20,846 and wrote 6,449; small, 6 minutes: 24,889 setup total, resume read 20,780 and wrote 4,140; n = 1 each). Under the rule above neither could ever be a hit, so the rule was mis-specified, not the instrument. Revised, using only the pilot's gap-0 and gap-6 resumes (not its 65-minute ones) as the reason:
- **hit**: resume `cache_read` >= 0.9 x C, where C = the median resume `cache_read` of the gap-0 sessions of the same size ("reads as much as a back-to-back message does"). With no gap-0 control the original rule (>= 0.9 x T) applies.
- **miss** and **partial**: unchanged.
- **Instrument sanity (stop rule 4):** each gap-0 resume must read at least F_read + 0.9 x (T - F), where F_read = the cache_read of the empty-project call (the shared prefix that was warm) and F = its total. Gap 0 must read its document from the cache.
- **Cost accounting:** `total_cost_usd` of a resumed call is cumulative for the session (it includes the setup call). A resume's own cost is its total minus the setup's, and the cost cap counts the largest total per session once. The first cap implementation double-counted and is fixed (test: `test_cost_cap_counts_each_session_once_because_resume_totals_are_cumulative`).
Everything is still scored by `eval/analyze.py`. The revision was made after seeing 3 pilot resumes; the full run (n = 3 per cell) is the test of it.

### Changes from the handoff (flagged, because they change the design)
1. **Unique document per session** (the handoff said "a fixed generated document"). A shared document would let any session's call keep every other session's document cache warm.
2. **Miss rule measured against the document part**, not the whole setup total. With F = 0 it is exactly the handoff rule. With a shared prefix of roughly 12k tokens (Video #1's first call wrote about 12k), a perfectly rewritten document in a small cell would otherwise count as "partial". Found by thinking it through before any run; not a measured result.
3. **Document sizes come from the floor**, not a guess: pilot measures F first, then `analyze.py --sizes` calibrates chars-per-token from the real setup totals.
4. Runs start with a stagger (default 20 s), longest waits first, up to 12 sessions in flight, under `caffeinate` so the Mac does not sleep through a wait.

### Decisions taken after the pilot (owner delegated: "do it complete it", 16 Nov 2026)
- **D1 gaps: `GAPS="0 6 55 65"`.** The pilot's 6-minute resume was a hit and its 65-minute resumes were misses, and every write went into the 1-hour field. Gap 4 would duplicate gap 6; 55 and 65 bracket the 1-hour mark, which is where the break is now expected. Still 24 sessions.
- **D2 sizes: `TARGET_SMALL=25000`, `TARGET_LARGE=60000`** (setup totals, tokens), with calibrated chars per token 3.3225. The measured floor is 15,583 tokens, so the small context carries about 9.4k document tokens.
- **Cost cap `CUM_COST_CAP_USD=7`** for the full run (the pilot's own $0.83 counts toward it). Real prices are higher than the planner's range: a write costs $4 per million tokens (see METRICS.md). My estimate at list price, recomputed from the pilot: about $4.5 if gaps 0, 6, 55 hit and 65 misses, about $5.5 if 55 also misses; an estimate, not a result.

### Decisions for the owner (original wording, now settled above)
- **D1: gap values.** The allowance-planner suggests `GAPS="0 6 55 65"`: with a 1-hour write seen in the Video #1 data, 4 and 6 minutes probably duplicate each other and a 55-vs-65 pair would bracket the real cliff. Still 24 sessions. The handoff set 0/4/6/65. Not changed without your say; `GAPS` is one env var.
- **D2: sizes.** If the measured floor is above about 10k, "small = 15k total" leaves only a few thousand document tokens. Set `TARGET_SMALL` after the floor is known.

## 3. Allowance estimate (from `allowance-planner`; ALL ESTIMATES, nothing measured)
Prices used: Sonnet 5.5 list input $2/MTok, output $10/MTok, cache read $0.10/MTok (claude-api skill table, cached 2026-11-03). Cache-write price is **unverified**; bounded at $2.50-$4.00/MTok. Cross-check by me: `baseline-run1.json` back-solves to about $4.00/MTok for its cache writes (inference from one file, assuming the prices above), which is consistent with a 1-hour write costing 2x input.
Assumed shared prefix F: 12k tokens (assumption until the hello call).

| Piece | Estimate (list price) |
|---|---|
| Hello floor | $0.03-0.08 |
| Small setup / resume hit / resume miss | about $0.010-0.014 / $0.002-0.005 / $0.010-0.014 (more if the prefix is cold) |
| Large setup / resume hit / resume miss | about $0.12-0.195 / $0.006-0.012 / $0.12-0.195 |
| 12-turn chain | $0.04-0.12 |
| **Pilot (9 calls)** | **$0.35-0.55** |
| **Full run (24 sessions + chain + floor)** | **$2.1-3.8**, worst case (everything cold) $4.6-7.2 |

Tokens, full run: about 2.0M processed (range 1.9-2.2M), about 0.75M written, about 1.2M read; large setups dominate.
Rough plan-allowance conversion (ratio from Video #1's pilot, $0.29 estimated = +6 session points, +1 week point, an upper bound from a different, output-heavy workload): pilot about 7-11 session points and 1-2 week points; full run about 40-75 session points and 7-13 week points. **Rough, one-reading-per-percent noise, and cache-heavy runs may weigh differently. Replace with the pilot's own `/usage` readings.**
Drop first if tight: (1) the 12-turn chain, (2) one of the near-duplicate short gaps, (3) large n from 3 to 2 at gaps 0 and short, (4) large at gap 0 last.

## 4. Pilot (needs approval) and stop rules
Pilot = `gap_eval.sh pilot`: hello floor, then small at 0, 6, 65 min and large at 65 min (1 rep each).
After the pilot, check and write into METRICS.md:
- F (floor), real chars-per-token, real setup totals for small and large vs the 15k/60k targets
- every call's `cache_creation` split into 5m and 1h (any 5m write is a finding)
- gap 0: mostly cache read? gap 6: hit or miss? gap 65: miss?
- whether `--resume` kept the same session id (`meta.json`: `session_id` vs `resume_session_id`)
- whether the prompt over stdin arrived intact (setup total close to F + document estimate; `reply_ok` true)
- whether the setup's `cache_creation` is only about the document (prefix already warm) or includes the prefix
- `/usage` before and after (session %, week %), no other Claude use in between

**Stop** (the scripts enforce the first four; you check the rest):
1. any `is_error`, rate-limit text, non-JSON output or non-zero exit -> `results/STOP`, no further calls
2. summed `total_cost_usd` over `CUM_COST_CAP_USD` -> `results/STOP` (suggested: $0.80 for the pilot, $5 for the full run)
3. a resumed run whose reply is not "OK" (reported by `analyze.py`, `reply_ok`)
4. gap-0 not mostly hits (`analyze.py` prints the check)
5. session `/usage` jump of more than 9 points or week jump of more than 2 points over the pilot
6. the pilot projects (x 6.5) to over about 60% of one session window

## 5. What the owner must run
Historical list (the steps were done on 16 Nov 2026; `/usage` readings are still owed by the owner). In order:
1. `make test` (no model calls) to confirm the build on your machine.
2. Read `/usage` (session %, week %). Write them here: before = TODO: measure.
3. Create `.claude/allow-spend` (pilot-only note below). **Only after you read this plan.**
4. `CUM_COST_CAP_USD=0.80 make pilot` (takes at least 65 minutes because of the longest gap; run it in the background, keep the Mac plugged in and awake, do not use Claude Code meanwhile).
5. Read `/usage` again. After = TODO: measure.
6. `python3 eval/analyze.py eval/results`, then `python3 eval/analyze.py eval/results --sizes`; review against section 4; decide D1 and D2.
7. New `.claude/allow-spend` note for the full run; `CUM_COST_CAP_USD=5 make eval` (longest wait is 65 minutes plus start-up stagger; the chain runs at the end).
8. `make analyze`, `make scrub`; paste the numbers into METRICS.md; fill NOTES.md.
Do not use Claude Code on this account during the waits: your own messages can keep the shared prefix warm (report the shared prefix separately, which is what F and the miss rule are for).

### Exact approval note (pilot only), put in `.claude/allow-spend`
```
until=2026-11-18
note=Owner approves idle-cache-cost PILOT ONLY: floor + 4 sessions (9 calls), headless claude -p on plan login, Sonnet medium, no API key, usage credits off. Estimate (guess) $0.35-0.55 list price, about 7-11 session pts. Stop on any error or rate-limit, session jump >9 pts, week >2 pts, or summed total_cost_usd >$0.80. Full run needs a new note after pilot review.
```
Full-run note (after the pilot, with the pilot's real numbers): same wording with scope "24 sessions + chain + floor", the pilot-based estimate, and stop at a projected total above $5.

## 6. Invalidation risks (say them on camera)
- **Your own Claude use** during a wait warms the shared prefix. Stay off; the miss rule separates prefix from document.
- **Headless `-p --resume` may behave differently from the interactive app.** The result is about this path.
- **Plan allowance may weigh tokens differently from list prices.** Report tokens; quote `/usage` only as a cross-check.
- **Version drift:** `claude --version` and the start time are logged per session. The run could cross an update.
- **Thinking tokens / output noise:** logged (`output`), expected to be small, unmeasured.
- **n = 3**: report median and range, not a rate.
- **Sleep, network drops, a closed lid** stretch a gap: both planned and actual gap are logged (`gap_actual_s`).
- **Rate limits/other users:** concurrency (up to 12 sessions) is higher than a person would use; any rate-limit text stops the run.

## 7. Unverified until the pilot
Cache lifetime for plan logins (5m vs 1h); the 5m/1h sub-fields; whether `--resume` in `-p` mode reuses the cached prefix; stdin as the prompt; current list prices incl. cache-write; how the plan converts tokens to limits; chars-per-token for the filler text (assumed 4.0); the shared prefix F (assumed about 12k only for the estimate above).

## 8. Result fields (all `TODO: measure`)
Floor F: TODO: measure. Calibrated chars-per-token: TODO: measure. Per-cell class counts, median/range of cache_read and cache_creation (8 cells): TODO: measure. 5m vs 1h split: TODO: measure. Chain per-turn tokens: TODO: measure. `/usage` before/after the pilot and the full run: TODO: measure. Real total cost estimate: TODO: measure.
