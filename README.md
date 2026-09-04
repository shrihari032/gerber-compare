# Gerber comparison threshold and reporting workflow

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
