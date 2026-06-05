# jobsearch

Sponsor-licensed UK job search pipeline. Pulls jobs from configurable boards, filters against the gov.uk Register of Licensed Sponsors, scores against the candidate's visa/salary/skills profile, picks the closest resume variant and tailors it via Claude, tracks state in SQLite, and pre-fills application forms with browser-use (human-in-the-loop, never auto-submits).

## Quick start

```bash
cp .env.example .env          # fill AWS_REGION + creds, RESUMES_DIR
make install                   # pip install -e .[apply,pdf,dev] + playwright chromium
make pipeline                  # sponsors -> ingest -> filter -> score -> tailor
make tracker                   # see what's in the queue
make apply JOB_ID=abc123       # pre-fill apply form, you review + submit
```

## Pipeline stages

1. **sponsors** - Pulls the gov.uk Register of Licensed Sponsors CSV (cached daily).
2. **ingest** - Scrapes configured boards (Indeed UK, Glassdoor UK, LinkedIn UK by default; add more under `src/jobsearch/ingest/sources/`).
3. **filter** - Fuzzy-matches each job's company against the sponsor register, drops non-sponsors.
4. **score** - A-F grade based on visa salary floor, SOC mapping, JD-keyword overlap with profile, location, sponsor confidence.
5. **tailor** - Picks the closest of 8 resume variants on disk, calls Claude (with prompt caching) to rewrite bullets for the JD, emits ATS-friendly `.docx` + `.pdf`.
6. **tracker** - SQLite app status: discovered/scored/tailored/applied/interview/offer/rejected.
7. **apply** - browser-use opens the JD's apply URL, pre-fills standard fields from `config/profile.yaml`, pauses for human review and submit.

## Adding a new job board

Drop a file at `src/jobsearch/ingest/sources/<name>.py` exposing a `class Source(BaseSource)` with a `fetch(query) -> pd.DataFrame` method, register the key in `sources/__init__.py`. That's it.

## Why this stack

- gov.uk Register CSV is the **only** authoritative sponsor list.
- Tailoring per-JD with Claude beats spraying the same resume.
- Human-in-the-loop on submit avoids LinkedIn ToS issues during a visa-critical period.
- See memory `MEMORY.md` for the full reasoning.
