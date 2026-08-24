#!/usr/bin/env python3
"""Bisect what broke the template, starting from the one build that opened.

B0 is the original build verbatim (it opened without an error dialog). Each
other file changes exactly ONE thing relative to B0, so whichever files fail
identify the breaking change.

Run:  python3 diagnostics/build_bisect.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
BASELINE_COMMIT = "62b555e"

spec = importlib.util.spec_from_file_location("build_pbit", REPO_ROOT / "scripts" / "build_pbit.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)


def load_baseline() -> dict[str, bytes]:
    blob = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:Contoso-Readiness.pbit"],
        cwd=REPO_ROOT, capture_output=True, check=True,
    ).stdout
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "baseline.pbit"
    tmp.write_bytes(blob)
    with zipfile.ZipFile(tmp) as z:
        return {n: z.read(n) for n in z.namelist()}


def content_types_real_style(part_names: list[str]) -> bytes:
    overrides = "".join(
        f'<Override PartName="/{n}" ContentType='
        f'"{"application/json" if n in ("Settings", "Metadata") else ""}"/>'
        for n in part_names
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="json" ContentType=""/>'
        '<Default Extension="xml" ContentType=""/>'
        f"{overrides}</Types>"
    ).encode("utf-8")


def mashup_from_model(model: dict) -> bytes:
    """Build a mashup whose M matches the baseline model byte for byte."""
    param = model["model"]["expressions"][0]
    table = model["model"]["tables"][0]
    param_m = param["expression"]
    table_m = "\n".join(table["partitions"][0]["source"]["expression"])

    section1 = "\r\n\r\n".join(
        [
            "section Section1;",
            f"shared {param['name']} = {param_m};",
            f"shared {table['name']} = {table_m};",
        ]
    ) + "\r\n"

    inline = {param["name"]: param_m, table["name"]: table_m}
    original = bp.read_query
    bp.read_query = lambda key: inline[key]
    try:
        metadata = bp.mashup_metadata_xml(
            [
                {"name": param["name"], "file": param["name"], "role": "parameter", "result_type": "Text"},
                {"name": table["name"], "file": table["name"], "role": "table", "result_type": "Table"},
            ]
        )
    finally:
        bp.read_query = original

    return bp.build_mashup(section1, metadata)


def emit(filename: str, parts: dict[str, bytes], note: str) -> None:
    out = HERE / filename
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, payload in parts.items():
            z.writestr(name, payload)
    print(f"  {filename:<42} {note}")


def main() -> None:
    base = load_baseline()
    model = json.loads(base["DataModelSchema"].decode("utf-16-le"))

    print("Built:")
    emit("B0-baseline-verbatim.pbit", dict(base), "the original build, unchanged")

    v = dict(base)
    v["[Content_Types].xml"] = content_types_real_style(
        [n for n in v if n != "[Content_Types].xml"]
    )
    emit("B1-content-types.pbit", v, "only: content types changed to empty style")

    v = dict(base)
    v["Settings"] = bp.json_part(bp.package_json("Settings"))
    v["Metadata"] = bp.json_part(bp.package_json("Metadata"))
    emit("B2-settings-metadata.pbit", v, "only: real Settings/Metadata content")

    v = dict(base)
    v["DiagramLayout"] = bp.json_part(bp.package_json("DiagramLayout"))
    v["[Content_Types].xml"] = base["[Content_Types].xml"].replace(
        b'<Override PartName="/Report/Layout"',
        b'<Override PartName="/DiagramLayout" ContentType="application/json" />'
        b'<Override PartName="/Report/Layout"',
    )
    emit("B3-diagramlayout.pbit", v, "only: DiagramLayout part added")

    v = dict(base)
    v["Version"] = bp.utf16("1.25")
    emit("B4-version-1.25.pbit", v, "only: format version 1.28 -> 1.25")

    v = dict(base)
    downgraded = json.loads(base["DataModelSchema"].decode("utf-16-le"))
    downgraded["compatibilityLevel"] = 1550
    v["DataModelSchema"] = bp.json_part(downgraded)
    emit("B5-compat-1550.pbit", v, "only: compatibilityLevel 1567 -> 1550")

    v = dict(base)
    v["DataMashup"] = mashup_from_model(model)
    v["[Content_Types].xml"] = base["[Content_Types].xml"].replace(
        b'<Override PartName="/Version"',
        b'<Override PartName="/DataMashup" ContentType="" />'
        b'<Override PartName="/Version"',
    )
    emit("B6-mashup.pbit", v, "only: DataMashup part added  <-- prime suspect")


if __name__ == "__main__":
    main()
