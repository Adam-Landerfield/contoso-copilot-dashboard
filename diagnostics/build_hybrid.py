#!/usr/bin/env python3
"""Graft my content into Microsoft's working template container.

The Microsoft sample opens on the target machine, so it is a known-good chassis.
H1 keeps every Microsoft "housekeeping" part and swaps in only my model, mashup
and report. H2 keeps my own housekeeping parts and adds just the four parts I
never emit. Whichever opens narrows the fault to one side.

Delete this folder once the issue is resolved.

Run:  python3 diagnostics/build_hybrid.py
"""

from __future__ import annotations

import importlib.util
import os
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
REFERENCE = Path(os.environ.get("TMPDIR", "/tmp")) / "sample.pbit"

spec = importlib.util.spec_from_file_location("build_pbit", REPO_ROOT / "scripts" / "build_pbit.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)

# Microsoft parts that describe their report, not the package plumbing.
THEIR_REPORT_PARTS = ("Report/Layout", "Report/LinguisticSchema", "Report/MobileState")

# The parts I have never emitted.
PLUMBING = ("Connections", "SecurityBindings", "docProps/custom.xml", "_rels/.rels")


def content_types(part_names: list[str]) -> bytes:
    overrides = "".join(
        f'<Override PartName="/{n}" ContentType='
        f'"{"application/json" if n in ("Settings", "Metadata") else ""}"/>'
        for n in part_names
        if n != "_rels/.rels"
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="json" ContentType=""/>'
        '<Default Extension="xml" ContentType=""/>'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        f"{overrides}</Types>"
    ).encode("utf-8")


def my_content() -> dict[str, bytes]:
    model = bp.build_model()
    section1 = bp.build_section1()
    bp.assert_model_matches_mashup(model, section1)
    return {
        "DataMashup": bp.build_mashup(section1, bp.mashup_metadata_xml(bp.QUERIES)),
        "DataModelSchema": bp.json_part(model),
        "DiagramLayout": bp.json_part(bp.package_json("DiagramLayout")),
        "Report/Layout": bp.json_part(bp.build_layout()),
    }


def emit(filename: str, parts: dict[str, bytes], note: str) -> None:
    parts = dict(parts)
    parts["[Content_Types].xml"] = content_types(
        [n for n in parts if n != "[Content_Types].xml"]
    )
    ordered = ["[Content_Types].xml"] + [n for n in parts if n != "[Content_Types].xml"]
    out = HERE / filename
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ordered:
            z.writestr(name, parts[name])
    size = out.stat().st_size / 1024
    print(f"  {filename:<34} {size:>7.1f} KB   {note}")
    print(f"      parts: {', '.join(ordered)}")


def main() -> None:
    if not REFERENCE.is_file():
        raise SystemExit(f"Reference template not found: {REFERENCE}")

    with zipfile.ZipFile(REFERENCE) as z:
        theirs = {n: z.read(n) for n in z.namelist()}

    mine = my_content()

    print("Built:")

    # H1: their plumbing, my content.
    h1 = {
        n: b
        for n, b in theirs.items()
        if n != "[Content_Types].xml"
        and n not in THEIR_REPORT_PARTS
        and not n.startswith("Report/CustomVisuals/")
        and not n.startswith("Report/StaticResources/")
        and n not in ("DataMashup", "DataModelSchema", "DiagramLayout")
    }
    h1.update(mine)
    emit("H1-their-plumbing-my-content.pbit", h1, "Microsoft's Version/Settings/Metadata + plumbing")

    # H2: my plumbing, plus only the four parts I never emit.
    h2 = {
        "Version": bp.utf16((REPO_ROOT / "src" / "package" / "Version.txt").read_text().strip()),
        "Settings": bp.json_part(bp.package_json("Settings")),
        "Metadata": bp.json_part(bp.package_json("Metadata")),
        **mine,
        **{n: theirs[n] for n in PLUMBING if n in theirs},
    }
    emit("H2-my-plumbing-plus-missing-parts.pbit", h2, "my Version/Settings/Metadata + their plumbing")


if __name__ == "__main__":
    main()
