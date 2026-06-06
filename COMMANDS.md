# jobsearch — All commands

Reference of every command to install, run, and operate the pipeline. Run from project root unless noted.

## 0. One-time setup

```bash
# Copy env template and fill AWS_REGION + creds, RESUMES_DIR, etc.
cp .env.example .env

# Install package + extras + Playwright Chromium (handles the numpy/jobspy pin workaround)
make install

# Equivalent manual install (if `make` is unavailable on Windows)
python -m pip install -e ".[apply,pdf,dev,dashboard]"
python -m pip install --no-deps "python-jobspy>=1.1.80"
python -m pip install tls-client markdownify regex beautifulsoup4
python -m playwright install chromium
```

## 1. Daily one-shot (recommended)

```bash
# Full pipeline: sponsors -> ingest -> filter -> score -> tailor -> review, then opens output/jobs.xlsx
bash run.sh

# Variants
bash run.sh --top 20                       # tailor more roles
bash run.sh --skip-tailor --skip-review    # cheap re-score only (no Bedrock spend)
bash run.sh --skip-sponsors                # use cached sponsor register
bash run.sh --top 15 --skip-sponsors       # mix flags freely
```

`run.sh` pre-flight checks: `aws sts get-caller-identity --profile fitai`, `.env` present, `jobsearch` importable. If SSO has expired:

```bash
aws sso login --profile fitai
```

## 2. Pipeline via Make

```bash
make pipeline       # sponsors + ingest + filter + score + tailor (top 10)
make sponsors       # refresh gov.uk Register of Licensed Sponsors CSV
make ingest         # scrape boards into data/jobs_raw.parquet
make filter         # drop non-sponsors -> data/jobs_filtered.parquet
make score          # A-F grade -> data/jobs_scored.parquet
make tailor         # tailor top-N resumes (calls Bedrock)
make tracker        # print SQLite tracker table
make smoke          # tiny ingest using config/queries.smoke.yaml
make clean          # rm parquet, output/, *.sqlite
```

## 3. Pipeline via CLI (full control)

```bash
# End-to-end with flag passthrough
python -m jobsearch.cli pipeline run --config config/queries.yaml --top 10
python -m jobsearch.cli pipeline run --skip-sponsors --skip-tailor --skip-review

# Sponsors
python -m jobsearch.cli sponsors fetch
python -m jobsearch.cli sponsors fetch --force          # bypass 24h cache

# Ingest (scrape boards)
python -m jobsearch.cli ingest run --config config/queries.yaml
python -m jobsearch.cli ingest run --config config/queries.smoke.yaml

# Filter (sponsor match)
python -m jobsearch.cli filter run
python -m jobsearch.cli filter run --no-export          # skip Excel sidecar

# Score (A-F)
python -m jobsearch.cli score run
python -m jobsearch.cli score run --no-export

# Tailor (Bedrock-backed resume rewrites)
python -m jobsearch.cli tailor run --top 10
python -m jobsearch.cli tailor run --top 15 --offset 10 # ranks 11-25
python -m jobsearch.cli tailor run --top 10 --no-export

# Review pass on tailored resumes
python -m jobsearch.cli tailor review --top 10
python -m jobsearch.cli tailor review --offset 10 --top 15
python -m jobsearch.cli tailor review --job-id abc123
python -m jobsearch.cli tailor review --job-id abc,def  # multiple ids

# Export
python -m jobsearch.cli export xlsx
python -m jobsearch.cli export xlsx --out output/snapshot.xlsx
```

## 4. Tracker (SQLite app status)

```bash
python -m jobsearch.cli tracker list
python -m jobsearch.cli tracker list --status applied --limit 100
python -m jobsearch.cli tracker set <JOB_ID> applied --notes "submitted via portal"
python -m jobsearch.cli tracker set <JOB_ID> withdrawn
python -m jobsearch.cli tracker reconcile --dry-run    # preview changes
python -m jobsearch.cli tracker reconcile              # re-key + dedupe
```

Valid statuses: `discovered`, `scored`, `tailored`, `applied`, `interview`, `offer`, `rejected`, `withdrawn`, `skipped`.

## 5. Apply (human-in-the-loop)

```bash
# Manual: opens the JD URL in your default browser, you submit
python -m jobsearch.cli apply run --job-id <JOB_ID>
python -m jobsearch.cli apply run --job-id <JOB_ID> --mode manual

# browser-use agent pre-fills (often blocked by SSO/captchas)
python -m jobsearch.cli apply run --job-id <JOB_ID> --mode browser-use

# Or via Make
make apply JOB_ID=<JOB_ID>
```

## 6. Answer generator (cover-letter / portal questions)

```bash
python -m jobsearch.cli answer --job-id <JOB_ID> -q "Why this role?"
python -m jobsearch.cli answer --job-id <JOB_ID> -q "Why us?" --tone warm --max-words 150
python -m jobsearch.cli answer --job-id <JOB_ID> -q "..." --tone formal --no-append
```

Tones: `concise`, `professional`, `warm`, `formal`. Appends to `<job>.answers.md` unless `--no-append`.

## 7. Web dashboard

```bash
bash dashboard.sh                    # http://127.0.0.1:8000
bash dashboard.sh --port 9000
bash dashboard.sh --host 0.0.0.0 --port 8000

# Or directly
python -m jobsearch.cli dashboard
python -m jobsearch.cli dashboard --port 9000 --reload    # dev auto-reload
```

Reads `jobs_scored.parquet` + `tracker.sqlite` live; status updates persist to SQLite.

## 8. Tests / lint

```bash
pytest
pytest tests/test_<file>.py -k <name>
ruff check src tests
ruff format src tests
```

## 9. Troubleshooting quick refs

```bash
# AWS SSO expired (Bedrock 403)
aws sso login --profile fitai

# Inspect parquet artefacts
python -c "import pandas as pd; print(pd.read_parquet('data/jobs_scored.parquet').head())"

# Inspect SQLite tracker
python -c "import sqlite3, json; c=sqlite3.connect('tracker.sqlite'); print([r for r in c.execute('select job_id,status from apps limit 20')])"

# Reset everything
make clean
```
