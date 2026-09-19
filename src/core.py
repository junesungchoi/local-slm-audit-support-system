from __future__ import annotations

import csv
import fnmatch
import hashlib
import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TEXT_SUFFIXES = {".txt", ".md", ".csv"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9가-힣_/-]+", text.lower())


@dataclass
class EvidenceRecord:
    evidence_id: str
    source_file: str
    source_hash: str
    location: str
    text: str

    def as_dict(self) -> dict[str, str]:
        return self.__dict__


class AuditCase:
    def __init__(self, base: Path, case_id: str) -> None:
        self.root = base / case_id
        self.originals = self.root / "originals"
        self.extracted = self.root / "extracted"
        self.analyses = self.root / "analyses"
        self.outputs = self.root / "outputs"
        self.ledger = self.root / "ledger.jsonl"

    def initialise(self) -> None:
        for directory in (self.originals, self.extracted, self.analyses, self.outputs):
            directory.mkdir(parents=True, exist_ok=True)
        self.ledger.touch(exist_ok=True)

    def ingest(self, source: Path) -> list[EvidenceRecord]:
        self.initialise()
        inputs = [p for p in source.rglob("*") if p.is_file()] if source.is_dir() else [source]
        records: list[EvidenceRecord] = []
        for input_file in inputs:
            destination = self.originals / input_file.name
            if destination.exists() and sha256(destination) != sha256(input_file):
                raise ValueError(f"Duplicate filename with different bytes: {input_file.name}")
            if not destination.exists():
                shutil.copy2(input_file, destination)
            records.extend(self._extract(destination))
        with self.ledger.open("a", encoding="utf-8") as file:
            for record in records:
                file.write(json.dumps(record.as_dict(), ensure_ascii=False) + "\n")
        return records

    def _extract(self, source: Path) -> list[EvidenceRecord]:
        content = self._read_text(source)
        source_hash = sha256(source)
        extracted = self.extracted / f"{source.name}.txt"
        extracted.write_text(content, encoding="utf-8")
        parts = [line.strip() for line in content.splitlines() if line.strip()]
        return [EvidenceRecord(
            evidence_id=f"EV-{source_hash[:12]}-{number:04d}", source_file=source.name,
            source_hash=source_hash, location=f"line {number}", text=part,
        ) for number, part in enumerate(parts, start=1)]

    @staticmethod
    def _read_text(source: Path) -> str:
        if source.suffix.lower() in TEXT_SUFFIXES:
            return source.read_text(encoding="utf-8-sig", errors="replace")
        if source.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            return "\n".join(page.extract_text() or "" for page in PdfReader(source).pages)
        if source.suffix.lower() == ".docx":
            from docx import Document
            return "\n".join(paragraph.text for paragraph in Document(source).paragraphs)
        raise ValueError(f"Unsupported input: {source.suffix}. Export to TXT or CSV first.")

    def evidence(self) -> list[EvidenceRecord]:
        if not self.ledger.exists():
            return []
        return [EvidenceRecord(**json.loads(line)) for line in self.ledger.read_text(encoding="utf-8").splitlines() if line]

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query_terms = Counter(tokens(query))
        scored: list[tuple[float, EvidenceRecord]] = []
        for record in self.evidence():
            doc_terms = Counter(tokens(record.text))
            score = sum(query_terms[term] * doc_terms[term] for term in query_terms)
            if score:
                scored.append((float(score), record))
        return [{"score": score, **record.as_dict()} for score, record in sorted(scored, key=lambda x: x[0], reverse=True)[:limit]]


class RuleRunner:
    def __init__(self, case: AuditCase) -> None:
        self.case = case

    def run(self, rules: list[dict[str, Any]]) -> dict[str, Any]:
        output: list[dict[str, Any]] = []
        for rule in rules:
            for csv_file in self.case.originals.glob("*.csv"):
                if fnmatch.fnmatch(csv_file.name, rule["file_pattern"]):
                    output.extend(self._apply(csv_file, rule))
        report = {"executed_at": datetime.now(timezone.utc).isoformat(), "results": output}
        (self.case.analyses / "rule_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def _apply(self, csv_file: Path, rule: dict[str, Any]) -> list[dict[str, Any]]:
        with csv_file.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        required = set(rule.get("required_columns", []))
        if not rows or not required.issubset(rows[0]):
            return [{"rule_id": rule["id"], "status": "not_executed", "reason": "required columns absent", "file": csv_file.name}]
        flagged = []
        cutoff = None
        if rule.get("date_before"):
            cutoff = date.today() - timedelta(days=int(rule["date_before"]["days_ago"]))
        for number, row in enumerate(rows, start=2):
            matches = all(row.get(column, "").strip().lower() == str(value).lower() for column, value in rule.get("where", {}).items())
            if matches and cutoff:
                value = row.get(rule["date_before"]["column"], "")
                try:
                    matches = datetime.fromisoformat(value).date() < cutoff
                except ValueError:
                    matches = False
            if matches:
                flagged.append({"rule_id": rule["id"], "title": rule["title"], "criterion_id": rule.get("criterion_id"), "file": csv_file.name, "row": number, "record": row})
        return flagged


class DraftBuilder:
    def __init__(self, case: AuditCase) -> None:
        self.case = case

    def create(self, question: str) -> Path:
        evidence = self.case.search(question)
        findings_path = self.case.analyses / "rule_results.json"
        findings = json.loads(findings_path.read_text(encoding="utf-8")).get("results", []) if findings_path.exists() else []
        lines = ["# Audit-support working paper", "", f"Question: {question}", "", "## Factual condition"]
        if evidence:
            lines.extend(f"- {item['text']} [{item['evidence_id']}; {item['source_file']}, {item['location']}]" for item in evidence)
        else:
            lines.append("- Evidence insufficient for a factual statement. Additional evidence is required.")
        lines.extend(["", "## Rule-based observations"])
        lines.extend(f"- {item}" for item in findings) if findings else lines.append("- No rule result is available.")
        lines.extend(["", "## Auditor review", "- Confirm that each cited item is complete, current, and applicable.", "- Identify the approved audit criterion separately before reaching any conclusion.", "- This draft does not determine a violation or responsibility."])
        output = self.case.outputs / f"working_paper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        output.write_text("\n".join(lines), encoding="utf-8")
        return output
