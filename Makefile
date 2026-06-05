.PHONY: install ingest sponsors filter score tailor pipeline apply tracker clean smoke

PY ?= python

install:
	$(PY) -m pip install -e .[apply,pdf,dev]
	# python-jobspy 1.1.82 hard-pins numpy==1.26.3 (no Python 3.13 wheel).
	# Install with --no-deps and add its real runtime deps separately.
	$(PY) -m pip install --no-deps "python-jobspy>=1.1.80"
	$(PY) -m pip install tls-client markdownify regex beautifulsoup4
	$(PY) -m playwright install chromium

# Pull the gov.uk Register of Licensed Sponsors CSV into data/
sponsors:
	$(PY) -m jobsearch.cli sponsors fetch

# Scrape the configured boards into data/jobs_raw.parquet
ingest:
	$(PY) -m jobsearch.cli ingest run --config config/queries.yaml

# Drop non-sponsor rows -> data/jobs_filtered.parquet
filter:
	$(PY) -m jobsearch.cli filter run

# Score remaining rows -> data/jobs_scored.parquet
score:
	$(PY) -m jobsearch.cli score run

# Tailor resumes for the top-N scored jobs
tailor:
	$(PY) -m jobsearch.cli tailor run --top 10

# Tracker CRUD
tracker:
	$(PY) -m jobsearch.cli tracker list

# Apply (human-in-the-loop, never auto-submits)
apply:
	$(PY) -m jobsearch.cli apply run --job-id $(JOB_ID)

# End-to-end up to tailoring
pipeline: sponsors ingest filter score tailor

# Quick sanity check - tiny query, no network for sponsors if cached
smoke:
	$(PY) -m jobsearch.cli ingest run --config config/queries.smoke.yaml
	$(PY) -m jobsearch.cli filter run
	$(PY) -m jobsearch.cli score run

clean:
	rm -rf data/*.parquet output/* *.sqlite
