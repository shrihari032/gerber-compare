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

### Google Colab

Open this repository in Colab, run the following setup cell, then run the
upload cell. The upload helper accepts any two filenames/extensions, asks which
is the original, writes every result into `Gerber_XOR_Comparison/`, displays
the numerical JSON, and starts the ZIP download.

```python
!pip -q install shapely matplotlib
from colab_runner import colab_upload_and_run
comparison = colab_upload_and_run()
```

For a normal non-interactive notebook workflow, call `run_comparison()` with
two paths and optional `dx_mm`, `dy_mm`, and `rotation_deg`. The generated
`raw_differences.json` records vector Boolean areas, region bounds, tolerance,
alignment, hashes, and any unsupported feature warnings. It is the source of
truth; `*.png` files are visualizations only.

#### Geometry-based significance and Gerber XOR deliverables

XOR area remains an engineering/reporting measurement only. It is **not** used
to ignore a difference. Every raw XOR component is evaluated after the Boolean
operation using a boundary-distance tolerance, an independent feature
translation tolerance, and geometric topology (component/hole count) check.
A topology change is always flagged. The raw `XOR_difference.gbr` is immutable
when either tolerance changes; only `XOR_difference_flagged.gbr` changes.

`run_comparison` exposes non-destructive physical-tolerance controls:

```python
from colab_runner import run_comparison
comparison = run_comparison(
    "original.gtl", "working.gtl",
    geometric_tolerance_mm=0.05,
    translation_tolerance_mm=0.10,
)
```

The local command line exposes the exact same conditioning and always creates
the Gerber/PNG/report outputs in one run (there is no second hidden step):

```bash
python3 gerber_compare_files.py original.gtl working.gtl \
  --geometric-tolerance-mm 0.05 --translation-tolerance-mm 0.10
```

Every detected region is retained in `raw_differences.json` and
`difference_regions.csv` with boundary/translation/topology metrics, a `FLAG`
or `IGNORE` decision, and a machine-readable reason code. `--min-flag-area-mm2`
is retained only as a deprecated compatibility argument and cannot affect that
decision. `XOR_difference.gbr` is a valid millimetre RS-274X region output for
the complete vector XOR; `XOR_difference_flagged.gbr` contains only selected
flagged regions. `flagged_differences.png` labels each flagged area with the
same region ID used in the detailed HTML/CSV reports. Changing the conditions
never changes the raw XOR.

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
