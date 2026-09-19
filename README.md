# Local Audit Support Prototype

An offline-first prototype for analysing non-classified audit evidence. It keeps the original evidence unchanged, records SHA-256 hashes, runs transparent checks over CSV files, retrieves evidence with local BM25, and produces a draft that an auditor must review.

## Scope

- No cloud API or autonomous audit decision.
- Evidence and criteria remain in separate directories and indexes.
- Every citation in the output points to a stored evidence identifier.
- `ollama` is optional and invoked only through a local process. The default mode produces a deterministic, review-ready draft.

## Quick start

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp sample_rules.json rules.json
python app.py init-case CASE-2026-001
python app.py ingest CASE-2026-001 /path/to/submitted-files
python app.py analyse CASE-2026-001 --rules rules.json
python app.py search CASE-2026-001 "retired account privileged access"
python app.py draft CASE-2026-001 --question "Are inactive accounts controlled?"
```

The final draft is created under `cases/<case-id>/outputs/`. It is a working paper, not an audit conclusion.

## Expected folders

```
cases/<case-id>/
  originals/       # copied, never altered by the program
  extracted/       # text representations and CSV normalisation
  ledger.jsonl     # evidence identifiers, source positions, hashes
  analyses/        # transparent rule results
  outputs/         # review-ready drafts
criteria/          # approved, read-only criteria documents
```

For Excel input, export relevant sheets to CSV before the first prototype test. Support for XLSX can be added after the evidence and rule formats are agreed.
