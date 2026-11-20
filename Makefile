.PHONY: setup test pilot eval analyze scrub

setup:            ## venv with the one pinned dependency (pytest)
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

test: setup       ## smoke tests with a stub CLI. NO model calls, no plan usage.
	.venv/bin/python -m pytest -q tests

# The two targets below SPEND plan allowance. Their names matter: .claude/hooks/guard-spend.sh blocks them
# until the owner creates .claude/allow-spend. Both need CUM_COST_CAP_USD (see PLAN.md).
pilot:            ## empty-project floor + 4 sessions. Read /usage before and after.
	eval/gap_eval.sh pilot

eval:             ## full gap grid (n=3) + the 12-turn chain. Needs the pilot's floor first.
	eval/gap_eval.sh full 3
	eval/chain_eval.sh 12

analyze:          ## tokens per cell from eval/results (no model calls)
	python3 eval/analyze.py eval/results

scrub:            ## publishable copy of the results (session ids replaced)
	eval/scrub.sh
