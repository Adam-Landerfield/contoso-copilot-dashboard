# Contoso Copilot Readiness

A Power BI template (`Contoso-Readiness.pbit`) built entirely from source files in
this repo. Power BI Desktop is only ever needed to *open* the result — nothing in
here is produced by editing a `.pbix` by hand.

## Rebuild

```bash
python3 scripts/build_pbit.py
```

That is the only step. It re-packages `Contoso-Readiness.pbit` at the repo root
from everything under `src/`. No dependencies beyond the Python standard library.

## Opening the template

1. Open `Contoso-Readiness.pbit` in Power BI Desktop.
2. It prompts for a single parameter, **DataFolderPath**.
3. Enter the full path of the *folder* holding `Contoso-Entra-Users-RAW.csv`
   (the `data` folder of this repo), e.g. `C:\Contoso\data`. Do not include the
   file name. Forward slashes and a trailing separator are both tolerated.
4. Power BI loads the CSV and renders the **Copilot Readiness** page.

## Source layout

| Path | What it is |
| --- | --- |
| `src/model/model.json` | Tabular model (TMSL) — tables, columns, measures, the parameter |
| `src/model/queries/DataFolderPath.pq` | The `DataFolderPath` Power Query parameter |
| `src/model/queries/Employees.pq` | M query that reads and shapes the CSV |
| `src/model/measures/*.dax` | One DAX measure per file |
| `src/report/report.json` | Report layout, with nested config written as real JSON |
| `src/package/` | `Version`, `Settings`, `Metadata` and `DiagramLayout` package parts |
| `scripts/build_pbit.py` | Packages all of the above into the `.pbit` |

`model.json` references the `.pq` / `.dax` files through `expressionFile` keys.
The build script inlines them, escapes the nested report JSON the way Power BI
expects, and writes each package part as UTF-16 LE inside the zip container that
makes up a `.pbit`. It also generates the binary `DataMashup` part — the Power
Query document Power BI Desktop reads when it prompts for template parameters —
from the same `.pq` files, so there is a single source of truth for the M code.

## The report page

**Copilot Readiness** (1280 x 720) contains:

- Four cards: total employees, Copilot-licensed employees, licence coverage %,
  and the largest department by headcount.
- A clustered bar chart of employees per department, split by licence status.
- A `Country` slicer that filters the whole page.

Every figure is derived from the loaded CSV — there are no hardcoded numbers.