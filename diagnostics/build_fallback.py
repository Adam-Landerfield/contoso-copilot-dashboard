#!/usr/bin/env python3
"""Fallback build: the real template plus OPC document-properties parts.

Only needed if Contoso-Readiness.pbit still fails. H1 proved the content is
valid but also carried four parts the main build omits; this adds clean,
self-generated equivalents of the two that can be authored safely.

Delete this folder once the template is confirmed working.

Run:  python3 diagnostics/build_fallback.py
"""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

spec = importlib.util.spec_from_file_location("build_pbit", REPO_ROOT / "scripts" / "build_pbit.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)

CUSTOM_PROPS = (
    '<?xml version="1.0" encoding="utf-8" standalone="yes"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
    'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes" />'
).encode("utf-8")

RELS = (
    '<?xml version="1.0" encoding="utf-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" '
    'Target="docProps/custom.xml" />'
    "</Relationships>"
).encode("utf-8")

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="json" ContentType=""/>'
    '<Default Extension="xml" ContentType=""/>'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Override PartName="/Version" ContentType=""/>'
    '<Override PartName="/DataMashup" ContentType=""/>'
    '<Override PartName="/DataModelSchema" ContentType=""/>'
    '<Override PartName="/DiagramLayout" ContentType=""/>'
    '<Override PartName="/Report/Layout" ContentType=""/>'
    '<Override PartName="/Settings" ContentType="application/json"/>'
    '<Override PartName="/Metadata" ContentType="application/json"/>'
    '<Override PartName="/docProps/custom.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>'
    "</Types>"
).encode("utf-8")


def main() -> None:
    source = zipfile.ZipFile(REPO_ROOT / "Contoso-Readiness.pbit")
    parts = {n: source.read(n) for n in source.namelist()}
    parts["[Content_Types].xml"] = CONTENT_TYPES
    parts["docProps/custom.xml"] = CUSTOM_PROPS
    parts["_rels/.rels"] = RELS

    out = HERE / "F1-with-docprops.pbit"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, payload in parts.items():
            z.writestr(name, payload)

    print(f"Built {out.name} ({out.stat().st_size / 1024:.1f} KB)")
    print("  parts:", ", ".join(parts))


if __name__ == "__main__":
    main()
