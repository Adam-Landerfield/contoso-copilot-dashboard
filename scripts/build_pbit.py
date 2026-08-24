#!/usr/bin/env python3
"""Re-package Contoso-Readiness.pbit from the readable sources in src/.

A .pbit is an OPC (zip) package. Every part except [Content_Types].xml is
UTF-16 LE with no BOM. The part layout mirrors a genuine Power BI Desktop
template, including the binary /DataMashup container that holds the Power Query
document Desktop reads when it prompts for template parameters.

Run:  python3 scripts/build_pbit.py
"""

from __future__ import annotations

import io
import json
import struct
import sys
import zipfile
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
MODEL_DIR = SRC / "model"
PACKAGE_DIR = SRC / "package"
OUTPUT = REPO_ROOT / "Contoso-Readiness.pbit"

# Power BI stores these report properties as escaped JSON strings.
STRINGIFIED_KEYS = {"config", "filters", "query", "dataTransforms"}

# Order matters: it is also the order Power Query lists the queries in.
QUERIES = [
    {
        "name": "DataFolderPath",
        "file": "queries/DataFolderPath.pq",
        "role": "parameter",
        "result_type": "Text",
    },
    {
        "name": "Employees",
        "file": "queries/Employees.pq",
        "role": "table",
        "result_type": "Table",
    },
]

# Fixed so that rebuilds are byte-reproducible.
MASHUP_TIMESTAMP = "2026-08-24T00:00:00.0000000Z"

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="json" ContentType=""/>'
    '<Default Extension="xml" ContentType=""/>'
    '<Override PartName="/Version" ContentType=""/>'
    '<Override PartName="/DataMashup" ContentType=""/>'
    '<Override PartName="/DataModelSchema" ContentType=""/>'
    '<Override PartName="/DiagramLayout" ContentType=""/>'
    '<Override PartName="/Report/Layout" ContentType=""/>'
    '<Override PartName="/Settings" ContentType="application/json"/>'
    '<Override PartName="/Metadata" ContentType="application/json"/>'
    "</Types>"
)

XSD_NS = (
    'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
)

MASHUP_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="text/xml" />'
    '<Default Extension="m" ContentType="application/x-ms-m" />'
    "</Types>"
)

MASHUP_PACKAGE_XML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    f"<Package {XSD_NS}>"
    "<Version>2.114.322.0</Version>"
    "<MinVersion>1.5.3296.0</MinVersion>"
    "<Culture>en-US</Culture>"
    "</Package>"
)

MASHUP_PERMISSIONS = (
    '<?xml version="1.0" encoding="utf-8"?>'
    f"<PermissionList {XSD_NS}>"
    "<CanEvaluateFuturePackages>false</CanEvaluateFuturePackages>"
    "<FirewallEnabled>true</FirewallEnabled>"
    "</PermissionList>"
)

EMPTY_ZIP = b"PK\x05\x06" + b"\x00" * 18


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def _entry(name: str, value: str) -> str:
    return f'<Entry Type="{name}" Value="{_attr(value)}" />'


def mashup_metadata_xml(specs: list[dict]) -> str:
    """Per-query mashup metadata, mirroring what Power BI Desktop writes.

    Loaded queries carry LastAnalysisServicesFormulaText: the mashup's record of
    the M it handed to the model. Power BI validates the two against each other.
    """
    items = [
        "<Item><ItemLocation><ItemType>AllFormulas</ItemType><ItemPath /></ItemLocation>"
        "<StableEntries>"
        + _entry("IsTypeDetectionEnabled", "sTrue")
        + _entry("RunBackgroundAnalysis", "sFalse")
        + "</StableEntries></Item>"
    ]

    for spec in specs:
        if spec["role"] == "parameter":
            entries = [
                _entry("IsHidden", "l0"),
                _entry("LoadToReportDisabled", "l1"),
                _entry("FillErrorCode", "sUnknown"),
                _entry("FillLastUpdated", f"d{MASHUP_TIMESTAMP}"),
                _entry("ResultType", f"s{spec['result_type']}"),
            ]
        else:
            formula_text = json.dumps(
                {
                    "IncludesReferencedQueries": False,
                    "RootFormulaText": read_query(spec["file"]),
                    "ReferencedQueriesFormulaText": {},
                },
                separators=(",", ":"),
            )
            entries = [
                _entry("IsHidden", "l0"),
                _entry("IsDirectQuery", "l0"),
                _entry("LastAnalysisServicesFormulaText", "s" + formula_text),
                _entry("IsLastAnalysisServicesFormulaTextCollection", "l1"),
                _entry("LoadToReportDisabled", "l0"),
                _entry("FillErrorCode", "sUnknown"),
                _entry("FillLastUpdated", f"d{MASHUP_TIMESTAMP}"),
                _entry("ResultType", f"s{spec['result_type']}"),
            ]

        path = f"Section1/{quote(spec['name'], safe='')}"
        items.append(
            "<Item><ItemLocation><ItemType>Formula</ItemType>"
            f"<ItemPath>{path}</ItemPath></ItemLocation>"
            f"<StableEntries>{''.join(entries)}</StableEntries></Item>"
        )

    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f"<LocalPackageMetadataFile {XSD_NS}>"
        f"<Items>{''.join(items)}</Items>"
        "</LocalPackageMetadataFile>"
    )


def strip_comments(node):
    """Drop the "_comment" documentation keys used in the source files."""
    if isinstance(node, dict):
        return {k: strip_comments(v) for k, v in node.items() if not k.startswith("_")}
    if isinstance(node, list):
        return [strip_comments(item) for item in node]
    return node


def read_query(relative_path: str) -> str:
    path = MODEL_DIR / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"Expression file not found: {path}")
    return path.read_text(encoding="utf-8").rstrip("\n")


def read_expression(relative_path: str):
    """Read a .pq/.dax file as a TMSL expression (string, or list of lines)."""
    lines = read_query(relative_path).split("\n")
    return lines[0] if len(lines) == 1 else lines


def inline_expressions(node):
    """Replace {"expressionFile": "..."} with the file's contents."""
    if isinstance(node, dict):
        result = {}
        for key, value in node.items():
            if key == "expressionFile":
                result["expression"] = read_expression(value)
            else:
                result[key] = inline_expressions(value)
        return result
    if isinstance(node, list):
        return [inline_expressions(item) for item in node]
    return node


def stringify_nested_json(node):
    """Serialise the report properties Power BI expects as JSON strings."""
    if isinstance(node, dict):
        result = {}
        for key, value in node.items():
            if key in STRINGIFIED_KEYS and not isinstance(value, str):
                result[key] = json.dumps(
                    stringify_nested_json(value), separators=(",", ":"), ensure_ascii=False
                )
            else:
                result[key] = stringify_nested_json(value)
        return result
    if isinstance(node, list):
        return [stringify_nested_json(item) for item in node]
    return node


def build_model() -> dict:
    model = strip_comments(json.loads((MODEL_DIR / "model.json").read_text(encoding="utf-8")))
    return inline_expressions(model)


def build_layout() -> dict:
    layout = strip_comments(json.loads((SRC / "report" / "report.json").read_text(encoding="utf-8")))

    # Power BI keeps a copy of each visual's position on the container itself.
    for section in layout["sections"]:
        for container in section["visualContainers"]:
            position = container["config"]["layouts"][0]["position"]
            for key in ("x", "y", "z", "width", "height", "tabOrder"):
                container[key] = position[key]

    return stringify_nested_json(layout)


def build_section1() -> str:
    """The Power Query document: one `shared` declaration per query.

    Each member body must be byte-identical to the matching expression in the
    model, otherwise Power BI rejects the template with a MashupValidationError.
    """
    blocks = ["section Section1;"]
    for spec in QUERIES:
        blocks.append(f"shared {spec['name']} = {read_query(spec['file'])};")
    return "\r\n\r\n".join(blocks) + "\r\n"


def assert_model_matches_mashup(model: dict, section1: str) -> None:
    """Power BI rejects a template whose model M differs from its mashup M."""
    expressions = {e["name"]: e["expression"] for e in model["model"].get("expressions", [])}
    for table in model["model"]["tables"]:
        source = table["partitions"][0]["source"]
        if source.get("type") == "m":
            expressions[table["name"]] = source["expression"]

    for spec in QUERIES:
        name = spec["name"]
        found = expressions.get(name)
        if found is None:
            raise AssertionError(f"Query '{name}' has no matching expression in the model")
        joined = found if isinstance(found, str) else "\n".join(found)
        if f"shared {name} = {joined};" not in section1:
            raise AssertionError(
                f"Query '{name}' is not byte-identical between the model and Section1.m"
            )


def length_prefixed(payload: bytes) -> bytes:
    return struct.pack("<I", len(payload)) + payload


def build_mashup(section1: str, metadata_xml: str) -> bytes:
    """The binary /DataMashup container Power BI Desktop reads on open."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as mashup_package:
        mashup_package.writestr("Config/Package.xml", MASHUP_PACKAGE_XML.encode("utf-8-sig"))
        mashup_package.writestr("[Content_Types].xml", MASHUP_CONTENT_TYPES.encode("utf-8-sig"))
        mashup_package.writestr("Formulas/Section1.m", section1.encode("utf-8"))

    metadata = (
        struct.pack("<I", 0)
        + length_prefixed(metadata_xml.encode("utf-8-sig"))
        + length_prefixed(EMPTY_ZIP)
    )

    return (
        struct.pack("<I", 0)
        + length_prefixed(buffer.getvalue())
        + length_prefixed(MASHUP_PERMISSIONS.encode("utf-8-sig"))
        + length_prefixed(metadata)
        + struct.pack("<I", 0)  # permission bindings are machine-specific, so leave empty
    )


def utf16(text: str) -> bytes:
    return text.encode("utf-16-le")


def json_part(payload: dict) -> bytes:
    return utf16(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))


def package_json(name: str) -> dict:
    return json.loads((PACKAGE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def main() -> int:
    model = build_model()
    section1 = build_section1()
    assert_model_matches_mashup(model, section1)

    parts = [
        ("Version", utf16((PACKAGE_DIR / "Version.txt").read_text(encoding="utf-8").strip())),
        ("[Content_Types].xml", CONTENT_TYPES.encode("utf-8")),
        ("DataMashup", build_mashup(section1, mashup_metadata_xml(QUERIES))),
        ("DataModelSchema", json_part(model)),
        ("DiagramLayout", json_part(package_json("DiagramLayout"))),
        ("Report/Layout", json_part(build_layout())),
        ("Settings", json_part(package_json("Settings"))),
        ("Metadata", json_part(package_json("Metadata"))),
    ]

    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as package:
        for name, payload in parts:
            package.writestr(name, payload)

    size_kb = OUTPUT.stat().st_size / 1024
    print(f"Built {OUTPUT.relative_to(REPO_ROOT)} ({size_kb:.1f} KB)")
    for name, payload in parts:
        print(f"  {name:<24} {len(payload):>8,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
