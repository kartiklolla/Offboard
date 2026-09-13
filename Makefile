.PHONY: eval demo scorecard report test

test:
	python3 -m unittest discover -s tests -v

eval:
	python3 -m evals.runner --mode twin

demo:
	python3 cli.py run --user dhruv@acme.dev --mode live --dry-run

scorecard:
	python3 -m report.scorecard --results evals/results/final.json --baseline evals/results/baseline.json --mutants evals/results/mutants.json --trace traces/live-dry.jsonl traces/demo.jsonl --compare traces/evals/compare-heuristic/h1_full_run.jsonl traces/evals/compare-gullible/h1_full_run.jsonl traces/evals/compare-anthropic/h1_full_run.jsonl --out scorecard.html

report:
	python3 -m evals.runner --matrix --label final
	python3 -m evals.mutants
	python3 -m evals.runner --only h1_full_run --model heuristic --label compare-heuristic
	python3 -m evals.runner --only h1_full_run --model gullible --label compare-gullible
	$(MAKE) scorecard

console:
	python3 -m report.console --trace traces/demo.jsonl --out console.html --scorecard scorecard.html

console-live:
	python3 -m report.console --trace traces/run.jsonl --serve 8765 --scorecard scorecard.html

app:
	python3 -m report.app --serve 8765 --mode twin --model heuristic --scorecard scorecard.html

app-live:
	set -a; . ./.env; set +a; .venv/bin/python -m report.app --serve 8765 --mode live --model heuristic \
	  --hr hr.json --apps github,slack,sheets --sheet "$$GOOGLE_SHEET_ID" --scorecard scorecard.html
