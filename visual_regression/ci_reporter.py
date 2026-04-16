from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
from xml.etree.ElementTree import Element, ElementTree, SubElement


def write_junit_xml(
    output_path: Path,
    suite_name: str,
    cases: List[Dict[str, object]],
    elapsed_seconds: float,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    failures = sum(1 for case in cases if case.get("status") == "FAIL")
    errors = sum(1 for case in cases if case.get("status") == "ERROR")
    skipped = sum(1 for case in cases if case.get("status") == "SKIP")

    root = Element(
        "testsuite",
        attrib={
            "name": suite_name,
            "tests": str(len(cases)),
            "failures": str(failures),
            "errors": str(errors),
            "skipped": str(skipped),
            "time": f"{elapsed_seconds:.3f}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

    for case in cases:
        testcase = SubElement(
            root,
            "testcase",
            attrib={
                "classname": "visual_regression",
                "name": str(case.get("name")),
                "time": f"{float(case.get('duration_seconds', 0.0)):.3f}",
            },
        )

        status = str(case.get("status"))
        message = str(case.get("message", ""))
        report_path = str(case.get("report", ""))
        mismatch_pct = case.get("mismatch_pct")
        threshold_pct = case.get("threshold_pct")

        if status == "FAIL":
            detail = (
                f"Mismatch {mismatch_pct}% exceeded threshold {threshold_pct}%."
                f" Report: {report_path}"
            )
            failure = SubElement(testcase, "failure", attrib={"message": message or "Visual mismatch"})
            failure.text = detail
        elif status == "ERROR":
            error = SubElement(testcase, "error", attrib={"message": message or "Execution error"})
            error.text = f"Case errored. Report: {report_path}"
        elif status == "SKIP":
            skip = SubElement(testcase, "skipped", attrib={"message": message or "Skipped"})
            skip.text = message

        out = SubElement(testcase, "system-out")
        out.text = (
            f"status={status}\n"
            f"mismatch_pct={mismatch_pct}\n"
            f"threshold_pct={threshold_pct}\n"
            f"report={report_path}\n"
        )

    tree = ElementTree(root)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
