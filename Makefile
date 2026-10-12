.PHONY: run test pytests uitests market sample-report
run:
	PYTHONPATH=backend uvicorn renewal.main:app --host 0.0.0.0 --port 8000 --reload
pytests:
	PYTHONPATH=backend pytest -q
tests: test
test: pytests uitests
uitests:
	node --test tests/frontend.test.mjs
market:
	PYTHONPATH=backend python -m renewal.pipelines.ingest
sample-report:
	PYTHONPATH=backend python scripts/create_demo_report.py
