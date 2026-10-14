# Local Audit Support Prototype

An offline-first prototype for analysing non-classified audit evidence. It keeps the original evidence unchanged, records SHA-256 hashes, runs transparent checks over CSV files, retrieves evidence with local BM25, and produces a draft that an auditor must review.

## Scope

- No cloud API or autonomous audit decision.
- Evidence and criteria remain in separate directories and indexes.
- Every citation in the output points to a stored evidence identifier.
- `ollama` is optional and invoked only through a local process. The default mode produces a deterministic, review-ready draft.

## Quick start
- 1. Download this repository as a ZIP file, extract it to an approved local folder, and do not place operational evidence in the source-code repository.
- 2. Open `src\local_audit_workpaper_v4`.
- 3. Install Python 3.11 or later and select **Add python.exe to PATH** during installation.
- 4. Start Ollama and confirm that the configured local model is available. The default model tag is `gemma4:12b`; change the Model field in the application if a different local tag is used.
- 5. Double-click `setup.bat` once to install the required Python packages.
- 6. Double-click `run.bat` to start the local desktop application. If it does not start, run `diagnose_python.bat`.
- 7. In **Criteria**, upload the audit-criteria file. In **Evidence**, upload the evidence file and select **Run Local Review**.
- 8. Review the draft in **Findings** and **Workpaper**. The system prepares decision-support drafts only; the auditor must verify the evidence and approve, revise, or reject all text.

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
