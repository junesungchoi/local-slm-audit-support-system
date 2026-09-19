from __future__ import annotations

import argparse
import json
from pathlib import Path

from core import AuditCase, DraftBuilder, RuleRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline audit-support prototype")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-case")
    init.add_argument("case_id")

    ingest = sub.add_parser("ingest")
    ingest.add_argument("case_id")
    ingest.add_argument("source", type=Path)

    analyse = sub.add_parser("analyse")
    analyse.add_argument("case_id")
    analyse.add_argument("--rules", type=Path, required=True)

    search = sub.add_parser("search")
    search.add_argument("case_id")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)

    draft = sub.add_parser("draft")
    draft.add_argument("case_id")
    draft.add_argument("--question", required=True)

    args = parser.parse_args()
    case = AuditCase(Path("cases"), args.case_id)

    if args.command == "init-case":
        case.initialise()
        print(f"Created {case.root}")
    elif args.command == "ingest":
        records = case.ingest(args.source)
        print(json.dumps({"ingested": len(records)}, ensure_ascii=False))
    elif args.command == "analyse":
        rules = json.loads(args.rules.read_text(encoding="utf-8"))
        result = RuleRunner(case).run(rules)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "search":
        print(json.dumps(case.search(args.query, args.limit), ensure_ascii=False, indent=2))
    elif args.command == "draft":
        output = DraftBuilder(case).create(args.question)
        print(output)


if __name__ == "__main__":
    main()
