#!/usr/bin/env python3
"""Re-package Contoso-Readiness.pbit from the readable sources in src/.

A .pbit is an OPC (zip) package. Every part except [Content_Types].xml is
UTF-16 LE encoded with no BOM, which is what Power BI Desktop expects.

Run:  python3 scripts/build_pbit.py
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
MODEL_DIR = SRC / "model"
OUTPUT = REPO_ROOT / "Contoso-Readiness.pbit"

# Power BI stores these report properties as escaped JSON strings.
STRINGIFIED_KEYS = {"config", "filters", "query", "dataTransforms"}

CONTENT_TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/Version" ContentType="" />
  <Override PartName="/Settings" ContentType="application/json" />
  <Override PartName="/Metadata" ContentType="application/json" />
  <Override PartName="/DataModelSchema" ContentType="application/json" />
  <Override PartName="/Report/Layout" ContentType="application/json" />
</Types>
"""


def strip_comments(node):
    """Drop the "_comment" documentation keys used in the source files."""
    if isinstance(node, dict):
        return {k: strip_comments(v) for k, v in node.items() if not k.startswith("_")}
    if isinstance(node, list):
        return [strip_comments(item) for item in node]
    return node


def read_expression(relative_path: str):
    """Read a .pq/.dax file as a TMSL expression (string, or list of lines)."""
    path = MODEL_DIR / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"Expression file not found: {path}")
    lines = path.read_text(encoding="utf-8").rstrip("\n").split("\n")
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


def utf16(text: str) -> bytes:
    return text.encode("utf-16-le")


def json_part(payload: dict) -> bytes:
    return utf16(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))


def main() -> int:
    version = (SRC / "package" / "Version.txt").read_text(encoding="utf-8").strip()
    settings = json.loads((SRC / "package" / "Settings.json").read_text(encoding="utf-8"))
    metadata = json.loads((SRC / "package" / "Metadata.json").read_text(encoding="utf-8"))

    parts = [
        ("[Content_Types].xml", CONTENT_TYPES.encode("utf-8")),
        ("Version", utf16(version)),
        ("Settings", json_part(settings)),
        ("Metadata", json_part(metadata)),
        ("DataModelSchema", json_part(build_model())),
        ("Report/Layout", json_part(build_layout())),
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
