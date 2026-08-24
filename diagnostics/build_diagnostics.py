#!/usr/bin/env python3
"""Build a series of increasingly complex .pbit files to isolate what Power BI rejects.

Open them in Power BI Desktop in order and note which is the first to fail.
Delete this folder once the issue is resolved.

Run:  python3 diagnostics/build_diagnostics.py
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

spec = importlib.util.spec_from_file_location("build_pbit", REPO_ROOT / "scripts" / "build_pbit.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)


def content_types(part_names: list[str]) -> bytes:
    overrides = "".join(
        f'<Override PartName="/{n}" ContentType="{"application/json" if n in ("Settings", "Metadata") else ""}"/>'
        for n in part_names
        if n != "[Content_Types].xml"
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="json" ContentType=""/>'
        '<Default Extension="xml" ContentType=""/>'
        f"{overrides}</Types>"
    ).encode("utf-8")


EMPTY_LAYOUT = {
    "id": 0,
    "resourcePackages": [],
    "layoutOptimization": 0,
    "publicCustomVisuals": [],
    "pods": [],
    "filters": "[]",
    "config": json.dumps(
        {"version": "5.32", "activeSectionIndex": 0, "defaultDrillFilterOtherVisuals": True},
        separators=(",", ":"),
    ),
    "sections": [
        {
            "name": "Page1",
            "displayName": "Page 1",
            "ordinal": 0,
            "width": 1280,
            "height": 720,
            "displayOption": 1,
            "filters": "[]",
            "config": "{}",
            "visualContainers": [],
        }
    ],
}

STATIC_M = 'let\n    Source = #table(type table [Value = text], {{"A"}, {"B"}})\nin\n    Source'

PARAM_M = '"C:\\Data" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'


def make_model(name: str, table_name: str, table_m: str, parameter: bool) -> dict:
    model: dict = {
        "culture": "en-US",
        "sourceQueryCulture": "en-US",
        "defaultPowerBIDataSourceVersion": "powerBI_V3",
        "dataAccessOptions": {"legacyRedirects": True, "returnErrorValuesAsNull": True},
        "tables": [
            {
                "name": table_name,
                "columns": [
                    {
                        "name": "Value",
                        "dataType": "string",
                        "sourceColumn": "Value",
                        "summarizeBy": "none",
                    }
                ],
                "partitions": [
                    {
                        "name": table_name,
                        "mode": "import",
                        "source": {"type": "m", "expression": table_m.split("\n")},
                    }
                ],
            }
        ],
    }
    order = [table_name]
    if parameter:
        model["expressions"] = [
            {"name": "DataFolderPath", "kind": "m", "expression": PARAM_M}
        ]
        order.insert(0, "DataFolderPath")
    model["annotations"] = [{"name": "PBI_QueryOrder", "value": json.dumps(order)}]
    return {"name": name, "compatibilityLevel": 1550, "model": model}


def section1(members: list[tuple[str, str]]) -> str:
    blocks = ["section Section1;"] + [f"shared {n} = {m};" for n, m in members]
    return "\r\n\r\n".join(blocks) + "\r\n"


def write(filename: str, model: dict, members: list[tuple[str, str]], with_mashup: bool, layout: dict) -> None:
    parts = [
        ("Version", bp.utf16("1.25")),
        ("DataModelSchema", bp.json_part(model)),
        ("DiagramLayout", bp.json_part({"version": "1.1.0", "diagrams": []})),
        ("Report/Layout", bp.json_part(layout)),
        ("Settings", bp.json_part(bp.package_json("Settings"))),
        ("Metadata", bp.json_part(bp.package_json("Metadata"))),
    ]
    if with_mashup:
        parts.insert(1, ("DataMashup", bp.build_mashup(section1(members))))

    names = [n for n, _ in parts]
    out = HERE / filename
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as pkg:
        pkg.writestr("[Content_Types].xml", content_types(names))
        for name, payload in parts:
            pkg.writestr(name, payload)
    print(f"  {filename}")


def main() -> None:
    employees_m = bp.read_query("queries/Employees.pq")
    full_model = bp.build_model()

    print("Built:")
    write(
        "T1-minimal-with-mashup.pbit",
        make_model("T1", "Demo", STATIC_M, parameter=False),
        [("Demo", STATIC_M)],
        with_mashup=True,
        layout=EMPTY_LAYOUT,
    )
    write(
        "T2-minimal-no-mashup.pbit",
        make_model("T2", "Demo", STATIC_M, parameter=False),
        [],
        with_mashup=False,
        layout=EMPTY_LAYOUT,
    )
    write(
        "T3-with-parameter.pbit",
        make_model("T3", "Demo", STATIC_M, parameter=True),
        [("DataFolderPath", PARAM_M), ("Demo", STATIC_M)],
        with_mashup=True,
        layout=EMPTY_LAYOUT,
    )
    write(
        "T4-real-model-no-visuals.pbit",
        full_model,
        [("DataFolderPath", bp.read_query("queries/DataFolderPath.pq")), ("Employees", employees_m)],
        with_mashup=True,
        layout=EMPTY_LAYOUT,
    )


if __name__ == "__main__":
    main()
