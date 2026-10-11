"""Local SLM Based Cybersecurity Audit Support System.

Windows desktop interface for a locally running Ollama model.  The application
does not send evidence to an external service.  It prepares reviewable drafts;
the auditor remains responsible for the final professional judgment.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from xml.etree import ElementTree as ET

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - handled in the interface
    load_workbook = None

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - handled in the interface
    PdfReader = None


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
STATE_FILE = DATA_DIR / "audit_workspace.json"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:12b")

COLORS = {
    "bg": "#111d2b", "panel": "#17283b", "panel_2": "#1d3047",
    "entry": "#0e1a28", "border": "#2a4a6b", "accent": "#3d8ee8",
    "text": "#e8f0f8", "muted": "#a5b8cb", "success": "#53b786",
    "warning": "#d9a74a", "danger": "#df6b6b",
}

STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "are",
    "was", "were", "shall", "should", "must", "have", "has", "not", "all",
    "any", "such", "each", "under", "upon", "than", "when", "where", "been",
}


class LocalStore:
    """Persists only the local workspace metadata and generated drafts."""

    def __init__(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        self.data = {"criteria": [], "cases": []}
        if STATE_FILE.exists():
            try:
                self.data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        self.data.setdefault("criteria", [])
        self.data.setdefault("cases", [])

    def save(self) -> None:
        STATE_FILE.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_criteria(self, records: list[dict]) -> None:
        self.data["criteria"].extend(records)
        self.save()

    def upsert_case(self, record: dict) -> None:
        for index, item in enumerate(self.data["cases"]):
            if item["case_id"] == record["case_id"]:
                self.data["cases"][index] = record
                self.save()
                return
        self.data["cases"].append(record)
        self.save()

    def get_case(self, case_id: str) -> dict | None:
        return next((item for item in self.data["cases"] if item["case_id"] == case_id), None)


def read_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        document = archive.read("word/document.xml")
    root = ET.fromstring(document)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(namespace + "p"):
        words = [node.text or "" for node in paragraph.iter(namespace + "t")]
        line = "".join(words).strip()
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs)


def read_xlsx(path: Path) -> str:
    if load_workbook is None:
        raise RuntimeError("Excel support requires openpyxl. Run setup.bat once before using .xlsx files.")
    workbook = load_workbook(path, data_only=True, read_only=True)
    lines = []
    for sheet in workbook.worksheets:
        lines.append(f"Worksheet: {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            values = [str(value).strip() for value in row if value not in (None, "")]
            if values:
                lines.append(" | ".join(values))
    return "\n".join(lines)


def extract_text(path_name: str) -> str:
    path = Path(path_name)
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".log"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        return read_docx(path)
    if suffix in {".xlsx", ".xlsm"}:
        return read_xlsx(path)
    if suffix == ".pdf":
        if PdfReader is None:
            raise RuntimeError("PDF support requires pypdf. Run setup.bat once before using PDF files.")
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    raise RuntimeError("Supported files are .txt, .md, .csv, .log, .docx, .xlsx, .xlsm, and text-based .pdf.")


def split_text(text: str, size: int = 1600) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(cleaned) <= size:
        return [cleaned]
    chunks, start = [], 0
    while start < len(cleaned):
        end = min(start + size, len(cleaned))
        boundary = max(cleaned.rfind("\n", start, end), cleaned.rfind(". ", start, end))
        if boundary <= start + 300:
            boundary = end
        chunks.append(cleaned[start:boundary].strip())
        start = boundary + 1
    return [chunk for chunk in chunks if chunk]


def normalise_tokens(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
    return {word for word in words if word not in STOP_WORDS}


def retrieve_criteria(evidence: str, criteria: list[dict], limit: int = 3) -> list[dict]:
    evidence_tokens = normalise_tokens(evidence)
    ranked = []
    for criterion in criteria:
        criterion_tokens = normalise_tokens(criterion["text"])
        overlap = len(evidence_tokens & criterion_tokens)
        ranked.append((overlap, criterion))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in ranked[:limit] if item[0] > 0] or [item[1] for item in ranked[:limit]]


def post_to_ollama(model: str, prompt: str) -> str:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach local Ollama at {OLLAMA_URL}. Check that Ollama is running. ({exc.reason})") from exc
    except TimeoutError as exc:
        raise RuntimeError("The local model did not respond within five minutes.") from exc
    return (body.get("response") or "").strip()


def parse_sections(response: str) -> tuple[str, str, str]:
    labels = ["FACTUAL CONDITION", "RELATED CRITERION", "DRAFT FINDING"]
    pattern = r"(?:\[)?(" + "|".join(labels) + r")(?:\])?\s*:?"
    matches = list(re.finditer(pattern, response, flags=re.IGNORECASE))
    sections = {label: "" for label in labels}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(response)
        sections[match.group(1).upper()] = response[match.end():end].strip(" \n:-")
    if not any(sections.values()):
        return response, "No separate criterion section was returned.", "Review the model response before use."
    return sections[labels[0]], sections[labels[1]], sections[labels[2]]


class AuditWorkbench(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Audit Workpaper — Local")
        self.geometry("1280x800")
        self.minsize(1100, 680)
        self.configure(bg=COLORS["bg"])
        self.store = LocalStore()
        self.current_page = "Evidence"
        self.current_criterion_id: str | None = None
        self.current_case_id: str | None = None
        self.model_name = tk.StringVar(value=DEFAULT_MODEL)
        self.case_id_var = tk.StringVar(value="CASE-001")
        self.case_name_var = tk.StringVar(value="Access Control Review")
        self.analysis_case_var = tk.StringVar()
        self.analysis_tab_var = tk.StringVar(value="Risk & Control")
        self.status_var = tk.StringVar(value="Ready — local processing only")
        self._configure_style()
        self._build_shell()
        self.show_page("Evidence")

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", background=COLORS["entry"], fieldbackground=COLORS["entry"], foreground=COLORS["text"], rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background=COLORS["panel_2"], foreground=COLORS["text"], relief="flat", font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#254d77")])
        style.configure("TScrollbar", background=COLORS["panel_2"], troughcolor=COLORS["bg"], bordercolor=COLORS["bg"], arrowcolor=COLORS["text"])

    def _build_shell(self) -> None:
        sidebar = tk.Frame(self, bg="#0c1825", width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="▣  CASE-001", bg="#102236", fg=COLORS["text"], anchor="w", padx=18, pady=17, font=("Segoe UI", 10, "bold")).pack(fill="x", pady=(14, 10))
        self.nav_buttons = {}
        for name in ("Overview", "Evidence", "Criteria", "Analysis", "Findings", "Workpaper"):
            button = tk.Button(sidebar, text=name, command=lambda value=name: self.show_page(value), anchor="w", bd=0, padx=26, pady=10, font=("Segoe UI", 10), bg="#0c1825", fg=COLORS["muted"], activebackground="#1f436c", activeforeground=COLORS["text"])
            button.pack(fill="x")
            self.nav_buttons[name] = button
        tk.Frame(sidebar, bg="#263a51", height=1).pack(fill="x", padx=16, pady=18)
        for name in ("Export", "Settings"):
            tk.Button(sidebar, text=name, command=lambda value=name: self.show_placeholder(value), anchor="w", bd=0, padx=26, pady=9, font=("Segoe UI", 10), bg="#0c1825", fg=COLORS["muted"], activebackground="#1f436c", activeforeground=COLORS["text"]).pack(fill="x")
        tk.Label(sidebar, text="Local SLM only\nNo cloud transfer", bg="#0c1825", fg="#6f879f", justify="left", anchor="w", padx=26, font=("Segoe UI", 9)).pack(side="bottom", fill="x", pady=22)

        self.main = tk.Frame(self, bg=COLORS["bg"])
        self.main.pack(side="left", fill="both", expand=True)
        self.header = tk.Frame(self.main, bg="#0d1927", height=54)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)
        tk.Label(self.header, text="Audit Workpaper — Local", bg="#0d1927", fg=COLORS["text"], font=("Segoe UI", 11, "bold"), padx=18).pack(side="left", pady=16)
        tk.Label(self.header, textvariable=self.status_var, bg="#0d1927", fg=COLORS["muted"], font=("Segoe UI", 9), padx=18).pack(side="right", pady=18)
        self.content = tk.Frame(self.main, bg=COLORS["bg"])
        self.content.pack(fill="both", expand=True)

    def _clear_content(self) -> None:
        for widget in self.content.winfo_children():
            widget.destroy()

    def _select_nav(self, page: str) -> None:
        for name, button in self.nav_buttons.items():
            active = name == page
            button.configure(bg="#1f436c" if active else "#0c1825", fg=COLORS["text"] if active else COLORS["muted"])

    def _page_title(self, parent: tk.Widget, title: str, subtitle: str = "") -> None:
        tk.Label(parent, text=title, bg=COLORS["bg"], fg=COLORS["text"], font=("Segoe UI", 17, "bold"), anchor="w").pack(fill="x", padx=28, pady=(23, 0))
        if subtitle:
            tk.Label(parent, text=subtitle, bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=28, pady=(4, 16))

    def section(self, parent: tk.Widget, title: str, icon: str = "□") -> tuple[tk.Frame, tk.Frame]:
        card = tk.Frame(parent, bg=COLORS["panel"], highlightbackground=COLORS["border"], highlightthickness=1)
        heading = tk.Frame(card, bg=COLORS["panel_2"], height=32)
        heading.pack(fill="x")
        heading.pack_propagate(False)
        tk.Label(heading, text=f"{icon}  {title}", bg=COLORS["panel_2"], fg=COLORS["text"], font=("Segoe UI", 10, "bold"), anchor="w", padx=12).pack(fill="both", expand=True)
        body = tk.Frame(card, bg=COLORS["panel"], padx=11, pady=10)
        body.pack(fill="both", expand=True)
        return card, body

    def text_box(self, parent: tk.Widget, height: int = 7, editable: bool = True) -> tk.Text:
        text = tk.Text(parent, height=height, wrap="word", bg=COLORS["entry"], fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", padx=10, pady=8, font=("Consolas", 10 if not editable else 10))
        if not editable:
            text.configure(state="disabled")
        return text

    def set_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def show_page(self, page: str) -> None:
        self.current_page = page
        self._clear_content()
        self._select_nav(page)
        getattr(self, f"build_{page.lower()}")()

    def make_button(self, parent: tk.Widget, text: str, command, style: str = "primary") -> tk.Button:
        background = COLORS["accent"] if style == "primary" else COLORS["panel_2"]
        foreground = "#ffffff" if style == "primary" else COLORS["text"]
        return tk.Button(parent, text=text, command=command, bd=0, padx=14, pady=8, bg=background, fg=foreground, activebackground="#57a2f3" if style == "primary" else "#28415c", activeforeground="#ffffff", font=("Segoe UI", 9, "bold"))

    def build_overview(self) -> None:
        self._page_title(self.content, "Overview", "Local audit support workspace")
        grid = tk.Frame(self.content, bg=COLORS["bg"])
        grid.pack(fill="both", expand=True, padx=28, pady=5)
        grid.columnconfigure((0, 1), weight=1)
        summary, body = self.section(grid, "System Status", "●")
        summary.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=8)
        tk.Label(body, text="Model", bg=COLORS["panel"], fg=COLORS["muted"], anchor="w").pack(fill="x")
        model_entry = tk.Entry(body, textvariable=self.model_name, bg=COLORS["entry"], fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", font=("Consolas", 10))
        model_entry.pack(fill="x", pady=(5, 12), ipady=7)
        status_label = tk.Label(body, text="Not checked", bg=COLORS["panel"], fg=COLORS["muted"], anchor="w", font=("Segoe UI", 10))
        status_label.pack(fill="x", pady=(2, 8))
        self.make_button(body, "Check Local Ollama", lambda: self.check_ollama(status_label)).pack(anchor="w")
        boundary, body = self.section(grid, "Operating Boundary", "▣")
        boundary.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=8)
        tk.Label(body, text="• Local Ollama endpoint: 127.0.0.1\n• Evidence remains on this device\n• Criteria are stored in the local workspace\n• Draft findings require auditor review\n• No external API or cloud processing", bg=COLORS["panel"], fg=COLORS["text"], justify="left", anchor="nw", font=("Segoe UI", 10), pady=2).pack(fill="both", expand=True)
        workflow, body = self.section(grid, "Workflow", "→")
        workflow.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=8)
        tk.Label(body, text="Upload criteria  →  Upload evidence  →  Retrieve related criteria  →  Generate a local review draft  →  Auditor review  →  Findings and workpaper", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 11, "bold"), justify="left", wraplength=850, anchor="w").pack(fill="both", expand=True)

    def check_ollama(self, label: tk.Label) -> None:
        label.configure(text="Checking local Ollama…", fg=COLORS["muted"])
        def work() -> None:
            try:
                with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=8) as response:
                    models = [item.get("name", "") for item in json.loads(response.read().decode("utf-8")).get("models", [])]
                available = self.model_name.get().strip() in models
                message = "Ready — selected model is available" if available else "Ollama is running; confirm the model tag"
                self.after(0, lambda: (label.configure(text=message, fg=COLORS["success"] if available else COLORS["warning"]), self.status_var.set(message)))
            except Exception as exc:  # UI status only
                self.after(0, lambda: (label.configure(text="Ollama is not reachable", fg=COLORS["danger"]), self.status_var.set(str(exc))))
        threading.Thread(target=work, daemon=True).start()

    def build_criteria(self) -> None:
        self._page_title(self.content, "Criteria", "Upload audit standards, regulations, or consolidated Excel criteria files")
        toolbar = tk.Frame(self.content, bg=COLORS["bg"])
        toolbar.pack(fill="x", padx=28, pady=(0, 12))
        self.make_button(toolbar, "Upload Criteria File", self.upload_criteria).pack(side="left")
        tk.Label(toolbar, text=f"{len(self.store.data['criteria'])} criteria currently stored locally", bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 9), padx=14).pack(side="left")
        area = tk.Frame(self.content, bg=COLORS["bg"])
        area.pack(fill="both", expand=True, padx=28, pady=(0, 28))
        area.columnconfigure(0, weight=2); area.columnconfigure(1, weight=3); area.rowconfigure(0, weight=1)
        left, lbody = self.section(area, "Criteria List", "▤")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        self.criteria_tree = ttk.Treeview(lbody, columns=("title", "source"), show="headings", selectmode="browse")
        self.criteria_tree.heading("title", text="Criterion"); self.criteria_tree.heading("source", text="Source")
        self.criteria_tree.column("title", width=210); self.criteria_tree.column("source", width=105)
        self.criteria_tree.pack(fill="both", expand=True)
        self.criteria_tree.bind("<<TreeviewSelect>>", self.show_criterion_detail)
        for item in self.store.data["criteria"]:
            self.criteria_tree.insert("", "end", iid=item["id"], values=(item["title"], item["source"]))
        right, rbody = self.section(area, "Criterion Detail", "□")
        right.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        self.criterion_detail = self.text_box(rbody, height=18, editable=False)
        self.criterion_detail.pack(fill="both", expand=True)
        if self.store.data["criteria"]:
            first = self.store.data["criteria"][0]
            self.criteria_tree.selection_set(first["id"])
            self.show_criterion_detail()
        else:
            self.set_text(self.criterion_detail, "Upload an Excel, Word, PDF, or text file to create the local criteria repository.")

    def upload_criteria(self) -> None:
        path = filedialog.askopenfilename(title="Upload Audit Criteria", filetypes=[("Supported files", "*.xlsx *.xlsm *.docx *.pdf *.txt *.md *.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            text = extract_text(path)
            if not text.strip():
                raise RuntimeError("No extractable text was found in the selected file.")
            records = []
            for number, chunk in enumerate(split_text(text), start=1):
                first_line = next((line.strip() for line in chunk.splitlines() if line.strip()), "Untitled criterion")
                title = first_line[:90]
                records.append({"id": str(uuid.uuid4()), "title": title, "source": Path(path).name, "text": chunk, "uploaded_at": datetime.now().isoformat(timespec="seconds")})
            self.store.add_criteria(records)
            self.status_var.set(f"Loaded {len(records)} criterion record(s) locally")
            self.show_page("Criteria")
        except Exception as exc:
            messagebox.showerror("Criteria upload", str(exc))

    def show_criterion_detail(self, _event=None) -> None:
        selection = self.criteria_tree.selection()
        if not selection:
            return
        self.current_criterion_id = selection[0]
        criterion = next((item for item in self.store.data["criteria"] if item["id"] == self.current_criterion_id), None)
        if criterion:
            self.set_text(self.criterion_detail, f"Source: {criterion['source']}\nUploaded: {criterion['uploaded_at']}\n\n{criterion['text']}")

    def build_evidence(self) -> None:
        self._page_title(self.content, "Evidence", "Load an evidence file, retrieve related criteria, and prepare a reviewable draft")
        top = tk.Frame(self.content, bg=COLORS["bg"])
        top.pack(fill="x", padx=28, pady=(0, 12))
        for label, variable, width in (("Case Number", self.case_id_var, 18), ("Case Name", self.case_name_var, 31), ("Model", self.model_name, 22)):
            group = tk.Frame(top, bg=COLORS["bg"]); group.pack(side="left", padx=(0, 12))
            tk.Label(group, text=label, bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w")
            tk.Entry(group, textvariable=variable, width=width, bg=COLORS["entry"], fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", font=("Segoe UI", 10)).pack(ipady=6)
        self.make_button(top, "Upload Evidence", self.upload_evidence).pack(side="right", pady=17)
        self.make_button(top, "Run Local Review", self.run_review).pack(side="right", padx=8, pady=17)
        self.evidence_path = tk.StringVar(value="No evidence file loaded")
        tk.Label(self.content, textvariable=self.evidence_path, bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=30, pady=(0, 8))
        stack = tk.Frame(self.content, bg=COLORS["bg"])
        stack.pack(fill="both", expand=True, padx=28, pady=(0, 25))
        stack.rowconfigure((0, 1, 2), weight=1); stack.columnconfigure(0, weight=1)
        evidence, ebody = self.section(stack, "Evidence Excerpt", "▤")
        evidence.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        self.evidence_text = self.text_box(ebody, height=5, editable=False); self.evidence_text.pack(fill="both", expand=True)
        criterion, cbody = self.section(stack, "Related Criterion", "▥")
        criterion.grid(row=1, column=0, sticky="nsew", pady=8)
        self.related_text = self.text_box(cbody, height=5, editable=False); self.related_text.pack(fill="both", expand=True)
        finding, fbody = self.section(stack, "Final Finding", "▣")
        finding.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        tk.Label(fbody, text="Draft field intentionally left incomplete for auditor review.", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(0, 5))
        self.finding_text = self.text_box(fbody, height=5, editable=True); self.finding_text.pack(fill="both", expand=True)
        existing = self.store.get_case(self.case_id_var.get().strip())
        if existing:
            self.evidence_path.set(existing.get("source", "Loaded local case"))
            self.set_text(self.evidence_text, existing.get("evidence", "")); self.set_text(self.related_text, existing.get("criterion", ""))
            self.finding_text.insert("1.0", existing.get("finding", ""))

    def upload_evidence(self) -> None:
        path = filedialog.askopenfilename(title="Upload Evidence", filetypes=[("Supported files", "*.xlsx *.xlsm *.docx *.pdf *.txt *.md *.csv *.log"), ("All files", "*.*")])
        if not path:
            return
        try:
            text = extract_text(path)
            if not text.strip():
                raise RuntimeError("No extractable text was found in the selected file.")
            self.evidence_path.set(path)
            self.set_text(self.evidence_text, text[:8000])
            self.set_text(self.related_text, "Click Run Local Review to retrieve related criteria and prepare a draft.")
            self.finding_text.delete("1.0", "end")
            self.status_var.set("Evidence loaded locally — ready for review")
        except Exception as exc:
            messagebox.showerror("Evidence upload", str(exc))

    def run_review(self) -> None:
        evidence = self.evidence_text.get("1.0", "end").strip()
        if not evidence or evidence.startswith("Click Run"):
            messagebox.showwarning("Evidence", "Upload an evidence file before starting the local review.")
            return
        if not self.store.data["criteria"]:
            messagebox.showwarning("Criteria", "Upload at least one audit criteria file before starting the local review.")
            return
        case_id = self.case_id_var.get().strip() or "CASE-001"
        case_name = self.case_name_var.get().strip() or "Untitled Case"
        selected = retrieve_criteria(evidence, self.store.data["criteria"])
        context = "\n\n".join(f"[{item['title']}]\n{item['text']}" for item in selected)
        self.set_text(self.related_text, "Retrieving and reviewing with the local model…")
        self.status_var.set("Local model review is running…")
        prompt = f"""You are a cybersecurity audit-support assistant operating locally. Do not make a final audit conclusion, assign responsibility, or add facts not present in the evidence. Use the supplied audit criteria only as candidate criteria. Prepare a short, reviewable draft in plain English with these exact headings:\n\nFACTUAL CONDITION:\nRELATED CRITERION:\nDRAFT FINDING:\n\nEvidence:\n{evidence[:8000]}\n\nCandidate audit criteria:\n{context[:9000]}\n\nThe factual condition must stay close to the evidence. The draft finding must state that the auditor must verify applicability and evidence before using it."""
        def work() -> None:
            try:
                response = post_to_ollama(self.model_name.get().strip(), prompt)
                factual, criterion, finding = parse_sections(response)
                combined_evidence = factual or evidence[:1800]
                selected_text = criterion or (selected[0]["text"] if selected else "")
                record = {
                    "case_id": case_id, "case_name": case_name, "source": self.evidence_path.get(),
                    "evidence": combined_evidence, "source_evidence": evidence[:8000], "criterion": selected_text,
                    "finding": finding, "model": self.model_name.get().strip(),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
                self.store.upsert_case(record)
                self.after(0, lambda: self._show_review_result(record))
            except Exception as exc:
                self.after(0, lambda: self._review_error(str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _show_review_result(self, record: dict) -> None:
        self.set_text(self.evidence_text, record["evidence"])
        self.set_text(self.related_text, record["criterion"])
        self.finding_text.delete("1.0", "end"); self.finding_text.insert("1.0", record["finding"])
        self.status_var.set("Local draft is ready for auditor review")

    def _review_error(self, detail: str) -> None:
        self.set_text(self.related_text, "The local review could not be completed. See the message below.")
        self.status_var.set("Local model review failed")
        messagebox.showerror("Local review", detail)

    def build_analysis(self) -> None:
        self._page_title(self.content, "Analysis", "Case-based analysis tools grounded in local evidence and the uploaded criteria repository")
        if not self.store.data["cases"]:
            card, body = self.section(self.content, "Analysis Workspace", "▤")
            card.pack(fill="both", expand=True, padx=28, pady=(0, 28))
            tk.Label(body, text="Upload evidence and run a local review before using the analysis tools. Saved cases will then be available for analysis.", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 11), wraplength=720, justify="left").pack(anchor="w", padx=18, pady=22)
            return
        if not self.analysis_case_var.get() or not self.store.get_case(self.analysis_case_var.get()):
            self.analysis_case_var.set(self.store.data["cases"][0]["case_id"])
        controls = tk.Frame(self.content, bg=COLORS["bg"])
        controls.pack(fill="x", padx=28, pady=(0, 10))
        tk.Label(controls, text="Case", bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(side="left", padx=(0, 7))
        choices = [f"{item['case_id']} — {item['case_name']}" for item in self.store.data["cases"]]
        self.analysis_lookup = {f"{item['case_id']} — {item['case_name']}": item["case_id"] for item in self.store.data["cases"]}
        selected_label = next((label for label, identifier in self.analysis_lookup.items() if identifier == self.analysis_case_var.get()), choices[0])
        self.analysis_case_label = tk.StringVar(value=selected_label)
        chooser = ttk.Combobox(controls, textvariable=self.analysis_case_label, values=choices, state="readonly", width=42)
        chooser.pack(side="left", ipady=3)
        chooser.bind("<<ComboboxSelected>>", lambda _event: self._change_analysis_case())
        tabs = tk.Frame(self.content, bg=COLORS["bg"])
        tabs.pack(fill="x", padx=28, pady=(2, 11))
        self.analysis_tabs = {}
        for name in ("Risk & Control", "Evidence Themes", "Criteria Coverage", "Query"):
            button = tk.Button(tabs, text=name, command=lambda value=name: self.show_analysis_tab(value), bd=0, padx=15, pady=8, font=("Segoe UI", 9, "bold"), bg=COLORS["panel_2"] if name != self.analysis_tab_var.get() else COLORS["accent"], fg=COLORS["text"], activebackground="#57a2f3", activeforeground="#ffffff")
            button.pack(side="left", padx=(0, 6))
            self.analysis_tabs[name] = button
        self.analysis_body = tk.Frame(self.content, bg=COLORS["bg"])
        self.analysis_body.pack(fill="both", expand=True, padx=28, pady=(0, 28))
        self.show_analysis_tab(self.analysis_tab_var.get())

    def _change_analysis_case(self) -> None:
        self.analysis_case_var.set(self.analysis_lookup[self.analysis_case_label.get()])
        self.show_analysis_tab(self.analysis_tab_var.get())

    def _analysis_case(self) -> dict | None:
        return self.store.get_case(self.analysis_case_var.get())

    def _analysis_context(self, case: dict) -> str:
        return f"Case number: {case['case_id']}\nCase name: {case['case_name']}\n\nEvidence:\n{case.get('source_evidence') or case.get('evidence', '')}\n\nRelated criterion:\n{case.get('criterion', '')}\n\nExisting draft finding:\n{case.get('finding', '')}"

    def show_analysis_tab(self, tab: str) -> None:
        self.analysis_tab_var.set(tab)
        for name, button in getattr(self, "analysis_tabs", {}).items():
            button.configure(bg=COLORS["accent"] if name == tab else COLORS["panel_2"])
        for widget in self.analysis_body.winfo_children():
            widget.destroy()
        if tab == "Risk & Control":
            self.build_risk_control_analysis()
        elif tab == "Evidence Themes":
            self.build_evidence_themes_analysis()
        elif tab == "Criteria Coverage":
            self.build_criteria_coverage_analysis()
        else:
            self.build_query_analysis()

    def _analysis_panel(self, title: str, help_text: str, button_text: str, callback) -> tk.Text:
        card, body = self.section(self.analysis_body, title, "▣")
        card.pack(fill="both", expand=True)
        action = tk.Frame(body, bg=COLORS["panel"])
        action.pack(fill="x", pady=(0, 8))
        tk.Label(action, text=help_text, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9), justify="left", anchor="w", wraplength=700).pack(side="left", fill="x", expand=True)
        self.make_button(action, button_text, callback).pack(side="right", padx=(12, 0))
        output = self.text_box(body, height=21, editable=False)
        output.pack(fill="both", expand=True)
        return output

    def build_risk_control_analysis(self) -> None:
        self.analysis_output = self._analysis_panel("Risk and Control Analysis", "Identifies audit focus areas, risk indicators, possible control gaps, and evidence that still needs confirmation. It does not produce a final conclusion.", "Run Local Analysis", lambda: self.run_analysis("risk"))
        case = self._analysis_case()
        cached = (case or {}).get("analysis", {}).get("risk", "")
        self.set_text(self.analysis_output, cached or "Select Run Local Analysis to review the saved case evidence and criterion with the local model.")

    def build_evidence_themes_analysis(self) -> None:
        self.analysis_output = self._analysis_panel("Evidence Themes", "Groups recurring terms or patterns in the selected case and identifies material exceptions for auditor follow-up.", "Analyse Themes", lambda: self.run_analysis("themes"))
        case = self._analysis_case()
        cached = (case or {}).get("analysis", {}).get("themes", "")
        self.set_text(self.analysis_output, cached or "Select Analyse Themes to examine the selected case evidence locally.")

    def build_criteria_coverage_analysis(self) -> None:
        card, body = self.section(self.analysis_body, "Criteria Coverage", "▥")
        card.pack(fill="both", expand=True)
        tk.Label(body, text="Candidate criteria are ranked through local keyword overlap with the selected case evidence. The score is a retrieval aid, not a determination of applicability.", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=850, justify="left", anchor="w").pack(fill="x", pady=(0, 9))
        tree = ttk.Treeview(body, columns=("rank", "criterion", "source", "score"), show="headings")
        for col, heading, width in (("rank", "Rank", 75), ("criterion", "Candidate Criterion", 480), ("source", "Source", 250), ("score", "Keyword Overlap", 145)):
            tree.heading(col, text=heading); tree.column(col, width=width, minwidth=75, stretch=True)
        tree.pack(fill="both", expand=True)
        case = self._analysis_case()
        evidence = (case or {}).get("source_evidence") or (case or {}).get("evidence", "")
        evidence_tokens = normalise_tokens(evidence)
        ranked = []
        for item in self.store.data["criteria"]:
            score = len(evidence_tokens & normalise_tokens(item["text"]))
            ranked.append((score, item))
        ranked.sort(key=lambda value: value[0], reverse=True)
        for number, (score, item) in enumerate(ranked[:25], start=1):
            tree.insert("", "end", values=(number, item["title"], item["source"], score))
        if not ranked:
            tk.Label(body, text="No uploaded criteria are available. Add audit criteria from the Criteria menu.", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 10)).place(relx=0.5, rely=0.55, anchor="center")

    def build_query_analysis(self) -> None:
        card, body = self.section(self.analysis_body, "Grounded Case Query", "?")
        card.pack(fill="both", expand=True)
        tk.Label(body, text="Ask a focused audit question about the selected case. The local model receives only the selected case evidence, its retrieved criterion, and the question.", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9), justify="left", anchor="w", wraplength=850).pack(fill="x", pady=(0, 8))
        self.analysis_question = self.text_box(body, height=3, editable=True)
        self.analysis_question.insert("1.0", "What evidence should the auditor confirm before relying on this draft finding?")
        self.analysis_question.pack(fill="x", pady=(0, 8))
        self.make_button(body, "Ask Local Model", lambda: self.run_analysis("query")).pack(anchor="e", pady=(0, 8))
        self.analysis_output = self.text_box(body, height=14, editable=False)
        self.analysis_output.pack(fill="both", expand=True)
        case = self._analysis_case()
        cached = (case or {}).get("analysis", {}).get("query", "")
        self.set_text(self.analysis_output, cached or "The response will identify its evidence basis and will not issue a final audit conclusion.")

    def run_analysis(self, kind: str) -> None:
        case = self._analysis_case()
        if not case:
            messagebox.showwarning("Analysis", "Select a case first.")
            return
        context = self._analysis_context(case)
        prompts = {
            "risk": """Review the case below as a cybersecurity audit-support assistant. Do not make a final audit conclusion, assign responsibility, or add facts. Use the exact headings: ANALYSIS SUMMARY, AUDIT FOCUS, RISK INDICATORS, POSSIBLE CONTROL GAP, EVIDENCE TO CONFIRM. Make each section concise and state uncertainty where evidence is incomplete.""",
            "themes": """Review the case below as a cybersecurity audit-support assistant. Do not make a final audit conclusion or add facts. Use the exact headings: MAIN THEMES, OBSERVED PATTERNS, MATERIAL EXCEPTIONS, FOLLOW-UP QUESTIONS. Ground every point in the supplied case material.""",
            "query": """Answer the auditor's question using only the supplied case material. Do not make a final audit conclusion, assign responsibility, or add facts. Use the exact headings: RESPONSE, EVIDENCE BASIS, AUDITOR CHECKS.""",
        }
        question = ""
        if kind == "query":
            question = self.analysis_question.get("1.0", "end").strip()
            if not question:
                messagebox.showwarning("Analysis", "Enter a question first.")
                return
        self.set_text(self.analysis_output, "Local analysis is running…")
        self.status_var.set("Local analysis is running…")
        prompt = f"{prompts[kind]}\n\n{context}\n\nAuditor question:\n{question}" if question else f"{prompts[kind]}\n\n{context}"
        def work() -> None:
            try:
                response = post_to_ollama(self.model_name.get().strip(), prompt)
                case.setdefault("analysis", {})[kind] = response
                case["updated_at"] = datetime.now().isoformat(timespec="seconds")
                self.store.upsert_case(case)
                self.after(0, lambda: (self.set_text(self.analysis_output, response), self.status_var.set("Local analysis is ready for auditor review")))
            except Exception as exc:
                self.after(0, lambda: (self.set_text(self.analysis_output, "The local analysis could not be completed."), self.status_var.set("Local analysis failed"), messagebox.showerror("Analysis", str(exc))))
        threading.Thread(target=work, daemon=True).start()

    def build_findings(self) -> None:
        self._page_title(self.content, "Findings", "Reviewable issues generated from the local evidence workflow")
        area = tk.Frame(self.content, bg=COLORS["bg"])
        area.pack(fill="both", expand=True, padx=28, pady=(0, 28))
        table, tbody = self.section(area, "Finding Register", "▣")
        table.pack(fill="both", expand=True)
        columns = ("case_id", "case_name", "criterion", "evidence", "finding")
        self.findings_tree = ttk.Treeview(tbody, columns=columns, show="headings", selectmode="browse")
        labels = {"case_id": "Case Number", "case_name": "Case Name", "criterion": "Audit Criterion", "evidence": "Evidence", "finding": "Identified Finding"}
        widths = {"case_id": 100, "case_name": 155, "criterion": 250, "evidence": 260, "finding": 295}
        for column in columns:
            self.findings_tree.heading(column, text=labels[column]); self.findings_tree.column(column, width=widths[column], minwidth=80, stretch=True)
        self.findings_tree.pack(fill="both", expand=True)
        self.findings_tree.bind("<<TreeviewSelect>>", self.open_finding_case)
        for case in self.store.data["cases"]:
            self.findings_tree.insert("", "end", iid=case["case_id"], values=(case["case_id"], case["case_name"], self.one_line(case.get("criterion", "")), self.one_line(case.get("evidence", "")), self.one_line(case.get("finding", ""))))
        if not self.store.data["cases"]:
            tk.Label(tbody, text="No findings have been prepared. Run a local review from the Evidence page.", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 10)).place(relx=0.5, rely=0.5, anchor="center")

    def one_line(self, text: str, length: int = 120) -> str:
        return re.sub(r"\s+", " ", text).strip()[:length]

    def open_finding_case(self, _event=None) -> None:
        selection = self.findings_tree.selection()
        if not selection:
            return
        case = self.store.get_case(selection[0])
        if case:
            self.case_id_var.set(case["case_id"]); self.case_name_var.set(case["case_name"]); self.show_page("Evidence")

    def build_workpaper(self) -> None:
        self._page_title(self.content, "Workpaper", "Draft consolidated audit report by case")
        area = tk.Frame(self.content, bg=COLORS["bg"])
        area.pack(fill="both", expand=True, padx=28, pady=(0, 28))
        area.columnconfigure(0, weight=2); area.columnconfigure(1, weight=3); area.rowconfigure(0, weight=1)
        left, lbody = self.section(area, "Case Workpapers", "▤")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        self.workpaper_tree = ttk.Treeview(lbody, columns=("case_id", "case_name", "report"), show="headings", selectmode="browse")
        for col, label, width in (("case_id", "Case Number", 100), ("case_name", "Case Name", 170), ("report", "Consolidated Audit Report", 180)):
            self.workpaper_tree.heading(col, text=label); self.workpaper_tree.column(col, width=width)
        self.workpaper_tree.pack(fill="both", expand=True)
        self.workpaper_tree.bind("<<TreeviewSelect>>", self.show_workpaper)
        for case in self.store.data["cases"]:
            self.workpaper_tree.insert("", "end", iid=case["case_id"], values=(case["case_id"], case["case_name"], "Draft available"))
        right, rbody = self.section(area, "Consolidated Audit Report", "▣")
        right.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        actions = tk.Frame(rbody, bg=COLORS["panel"]); actions.pack(fill="x", pady=(0, 8))
        self.make_button(actions, "Generate Local Draft", self.generate_workpaper).pack(side="left")
        self.workpaper_text = self.text_box(rbody, height=20, editable=True); self.workpaper_text.pack(fill="both", expand=True)
        if self.store.data["cases"]:
            first = self.store.data["cases"][0]
            self.workpaper_tree.selection_set(first["case_id"]); self.show_workpaper()
        else:
            self.workpaper_text.insert("1.0", "Run a local evidence review first. Cases with saved findings will appear here.")

    def show_workpaper(self, _event=None) -> None:
        selection = self.workpaper_tree.selection()
        if not selection:
            return
        self.current_case_id = selection[0]
        case = self.store.get_case(self.current_case_id)
        if not case:
            return
        report = case.get("workpaper") or self.default_workpaper(case)
        self.workpaper_text.delete("1.0", "end"); self.workpaper_text.insert("1.0", report)

    def default_workpaper(self, case: dict) -> str:
        return f"""CASE NUMBER: {case['case_id']}
CASE NAME: {case['case_name']}

DRAFT CONSOLIDATED AUDIT REPORT

1. Evidence reviewed
{case.get('evidence', '')}

2. Related audit criterion
{case.get('criterion', '')}

3. Draft finding for auditor review
{case.get('finding', '')}

4. Auditor review note
Confirm the source evidence, criterion applicability, scope, and any required additional evidence before issuing an audit conclusion."""

    def generate_workpaper(self) -> None:
        if not self.current_case_id:
            messagebox.showwarning("Workpaper", "Select a case first.")
            return
        case = self.store.get_case(self.current_case_id)
        if not case:
            return
        self.status_var.set("Generating a local workpaper draft…")
        prompt = f"""Prepare a concise DRAFT CONSOLIDATED AUDIT REPORT for an auditor. Do not issue a final conclusion, assign responsibility, or introduce new facts. Keep the sections Evidence reviewed, Related audit criterion, Draft finding, and Auditor review note. State clearly that the auditor must verify the result before use.\n\nCase number: {case['case_id']}\nCase name: {case['case_name']}\nEvidence: {case.get('evidence', '')}\nCriterion: {case.get('criterion', '')}\nDraft finding: {case.get('finding', '')}"""
        def work() -> None:
            try:
                draft = post_to_ollama(self.model_name.get().strip(), prompt)
                case["workpaper"] = draft
                case["updated_at"] = datetime.now().isoformat(timespec="seconds")
                self.store.upsert_case(case)
                self.after(0, lambda: (self.workpaper_text.delete("1.0", "end"), self.workpaper_text.insert("1.0", draft), self.status_var.set("Local workpaper draft is ready for auditor review")))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Workpaper", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def show_placeholder(self, page: str) -> None:
        self._clear_content()
        self._select_nav("")
        self._page_title(self.content, page)
        tk.Label(self.content, text=f"{page} is not included in this prototype screen set.", bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 11)).pack(anchor="w", padx=28, pady=30)


if __name__ == "__main__":
    AuditWorkbench().mainloop()
