# Gerber XOR Comparator

Gerber XOR Comparator is a vector-first RS-274X comparison workflow for PCB
engineering review.  It parses each input into normalised millimetre geometry,
performs GEOS Boolean operations, and only then renders review PNGs.  PNGs are
never used as the comparison authority.

## Complete vector comparison workflow

Install the geometry dependency and compare two files:

```bash
python3 -m pip install -r requirements.txt
python3 gerber_compare_files.py original.gbr manufacturer.gbr \
  --output Gerber_XOR_Comparison
python3 gerber_compare.py \
  --raw-differences Gerber_XOR_Comparison/raw_differences.json \
  --thresholds examples/thresholds.json --output Gerber_XOR_Comparison
```

The first command performs RS-274X interpretation and a vector Boolean XOR;
the second applies auditable thresholds and writes reports. Coordinates are
converted to millimetres and snapped to a 1 nm grid prior to Boolean work.
Supported interpreted features include `FS`, `MO`, `AD` circular, rectangular,
obround and polygon apertures, `D01` strokes, `D02` moves, `D03` flashes,
`G01`/`G02`/`G03`, regions, and `LP` dark/clear polarity. X2 attributes are
ignored as metadata. Aperture macros and transforms are explicitly recorded as
unsupported instead of producing an identical result claim.

### Alignment

Use `--dx-mm`, `--dy-mm`, and `--rotation-deg` for a recorded manual
registration transform. The values are propagated to the report's alignment
audit. Automatic registration requires engineering review and is deliberately
not silently applied.

### Windows build

Run `build_windows.bat` on Windows with Python installed. It installs Shapely
and PyInstaller and creates `dist/GerberXORComparator.exe`. Shapely is licensed
under BSD-3-Clause and is backed by GEOS (LGPL-2.1-or-later).

### Tests

```bash
python3 -m unittest discover -s tests -v
```

## Thresholding and audit/report stage

This repository provides the **thresholding and audit/report stage** for a Gerber
comparison.  It deliberately treats raw Boolean geometry as immutable input:
`XOR_difference.gbr` is always written from every raw region, while
`XOR_difference_filtered.gbr` contains only regions that the configured filter
flags.

## Run

```bash
python3 gerber_compare.py --raw-differences examples/raw_differences.json \
  --thresholds examples/thresholds.json --output comparison_output
```

`--raw-differences` is JSON emitted by a vector Boolean engine.  Each region
needs `source` (`ORIGINAL_ONLY` or `MANUFACTURER_ONLY`), `area_mm2`, and a
`bbox_mm` (`[min_x, min_y, max_x, max_y]`).  Optional `length_mm`, `width_mm`,
`edge_displacement_mm`, and `classification` values are preserved. The complete
input schema and an example are in `examples/raw_differences.json`.

This separation is intentional: filtering must **never** modify the underlying
A XOR B calculation. The tool also emits a complete per-region audit in HTML,
text, JSON, and CSV plus Gerber and PNG review artifacts.

## EAGLE workflow

Install `gerber_xor.ulp` in EAGLE's ULP directory and run it. It presents the
**GERBER COMPARISON — DIFFERENCE THRESHOLDS** configuration dialog before
comparison and writes `comparison_thresholds.json`. Pass that file to the
comparison/reporting stage above (or to the host's Boolean-comparison adapter).
The ULP is intentionally a configuration frontend; it does not claim that a
raster image is an authoritative Boolean comparison.

## Status rules

* **PASS** — no raw regions passed the user-selected filter.
* **REVIEW** — one or more regions were flagged, but none exceeded a configured
  critical threshold.
* **FAIL** — a flagged region met one of the explicitly configured critical
  area, width, or length values.

All defaults are visible, editable, and included in each report's threshold
audit trail. The default combination logic is `OR`.
