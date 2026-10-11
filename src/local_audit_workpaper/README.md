# Local SLM Based Cybersecurity Audit Support System

This Windows desktop application is a local interface for Ollama and a Gemma 4 12B model. It is designed for one auditor working in a closed-network environment. It does not call a cloud service or external API.

## Start on Windows

1. Install Python 3.11 or later from python.org and select **Add python.exe to PATH** during installation.
2. Confirm that Ollama is running and that the local model is available.
3. Open the `local_audit_workpaper` folder.
4. Double-click `setup.bat` once.
5. Double-click `run.bat`.

If the application does not start, double-click `diagnose_python.bat`. A usable installation must report Python 3.11 or later. Windows can show a `python` command through a Microsoft Store alias even when Python is not actually installed; the revised batch files test the interpreter before starting the application.

The default model tag is `gemma4:12b`. If the local Ollama tag uses a different name, change the **Model** field on the Overview or Evidence page.

## Screens

- **Overview**: local model status and operating boundary.
- **Criteria**: upload `.xlsx`, `.docx`, `.pdf`, `.txt`, `.md`, or `.csv` audit criteria. The program keeps uploaded criteria in a local list and shows the selected criterion detail.
- **Evidence**: upload a local evidence file and select **Run Local Review**. The program retrieves candidate criteria by local keyword matching, then sends the evidence and candidate criteria only to the local Ollama service. It displays an evidence-based factual condition, a related criterion, and a draft finding.
- **Analysis**: select a saved case and use the internal **Risk & Control**, **Evidence Themes**, **Criteria Coverage**, or **Query** tabs. The first, second, and fourth tabs call only the configured local Ollama endpoint; Criteria Coverage calculates local keyword-overlap rankings without a model call.
- **Findings**: a register in the format Case Number, Case Name, Audit Criterion, Evidence, and Identified Finding.
- **Workpaper**: case list and a draft consolidated audit report for the selected case. **Generate Local Draft** calls only the configured local Ollama endpoint.

## Data boundary

The workspace state is stored in `data/audit_workspace.json` inside this program folder. It can contain evidence excerpts and generated drafts. Keep the whole application folder on an approved encrypted local drive and exclude it from cloud synchronisation. The source-code repository should not contain real evidence, credentials, local model files, or completed operational case folders.

The application prepares decision-support drafts only. The auditor must verify the source evidence, decide whether a criterion applies, and approve, edit, or reject all finding and workpaper text.
