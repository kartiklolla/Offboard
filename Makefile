.PHONY: eval demo scorecard test

test:
	python3 -m unittest discover -s tests -v

eval:
	python3 -m evals.runner --mode twin

demo:
	python3 cli.py run --user dhruv@acme.dev --mode live --dry-run

scorecard:
	python3 -m report.scorecard --trace traces/run.jsonl --out scorecard.html
