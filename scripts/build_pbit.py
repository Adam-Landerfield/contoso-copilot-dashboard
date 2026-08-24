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

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
MODEL_DIR = SRC / "model"
PACKAGE_DIR = SRC / "package"
OUTPUT = REPO_ROOT / "Contoso-Readiness.pbit"

# Power BI stores these report properties as escaped JSON strings.
STRINGIFIED_KEYS = {"config", "filters", "query", "dataTransforms"}

# Order matters: it is also the order Power Query lists the queries in.
QUERIES = [
    ("DataFolderPath", "queries/DataFolderPath.pq"),
    ("Employees", "queries/Employees.pq"),
]

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

MASHUP_METADATA_XML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    f"<LocalPackageMetadataFile {XSD_NS}>"
    "<Items><Item>"
    "<ItemLocation><ItemType>AllFormulas</ItemType><ItemPath /></ItemLocation>"
    '<StableEntries><Entry Type="IsTypeDetectionEnabled" Value="sTrue" /></StableEntries>'
    "</Item></Items>"
    "</LocalPackageMetadataFile>"
)

EMPTY_ZIP = b"PK\x05\x06" + b"\x00" * 18


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
            for key in ("x", "y", "z", "width", "height"):
                container[key] = position[key]

    return stringify_nested_json(layout)


def build_section1() -> str:
    """The Power Query document: one `shared` declaration per query."""
    blocks = ["section Section1;"]
    for name, relative_path in QUERIES:
        lines = read_query(relative_path).split("\n")
        # Hoist the file's leading comment block above the declaration.
        header = []
        while lines and (lines[0].startswith("//") or not lines[0].strip()):
            header.append(lines.pop(0))
        body = "\n".join(lines)
        blocks.append("\r\n".join(header + [f"shared {name} = {body};"]))
    return "\r\n\r\n".join(blocks) + "\r\n"


def length_prefixed(payload: bytes) -> bytes:
    return struct.pack("<I", len(payload)) + payload


def build_mashup() -> bytes:
    """The binary /DataMashup container Power BI Desktop reads on open."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as mashup_package:
        mashup_package.writestr("Config/Package.xml", MASHUP_PACKAGE_XML.encode("utf-8-sig"))
        mashup_package.writestr("[Content_Types].xml", MASHUP_CONTENT_TYPES.encode("utf-8-sig"))
        mashup_package.writestr("Formulas/Section1.m", build_section1().encode("utf-8"))

    metadata = (
        struct.pack("<I", 0)
        + length_prefixed(MASHUP_METADATA_XML.encode("utf-8-sig"))
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
    parts = [
        ("Version", utf16((PACKAGE_DIR / "Version.txt").read_text(encoding="utf-8").strip())),
        ("[Content_Types].xml", CONTENT_TYPES.encode("utf-8")),
        ("DataMashup", build_mashup()),
        ("DataModelSchema", json_part(build_model())),
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
