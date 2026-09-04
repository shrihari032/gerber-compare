#!/usr/bin/env python3
"""Threshold, audit, and report stage for vector Gerber XOR regions.

Raw regions are supplied by the authoritative Boolean engine. This module never
removes them; it produces a separate flagged view based on an auditable config.
"""
import argparse, csv, html, json, struct, zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SOURCES = {"ORIGINAL_ONLY", "MANUFACTURER_ONLY"}
DEFAULT_FLAGS = ["ADDED_GEOMETRY", "REMOVED_GEOMETRY", "WIDTH_CHANGE", "LENGTH_CHANGE", "POSITION_CHANGE", "PAD_CHANGE", "FLASH_CHANGE", "REGION_CHANGE", "SHAPE_CHANGE", "REGISTRATION_CHANGE", "UNKNOWN_GEOMETRIC_DIFFERENCE"]

@dataclass
class Thresholds:
    area_mm2: float = .010
    area_mode: str = "absolute"
    relative_area_percent: float = .1
    width_mm: float = .010
    length_mm: float = .100
    edge_displacement_mm: float = .010
    registration_x_mm: float = .050
    registration_y_mm: float = .050
    registration_rotation_deg: float = .050
    logic: str = "OR"
    ignore_below_threshold: bool = True
    report_ignored_separately: bool = True
    flag_types: list[str] = field(default_factory=lambda: DEFAULT_FLAGS.copy())
    critical_area_mm2: float = 1.0
    critical_width_mm: float = .5
    critical_length_mm: float = 5.0

    @classmethod
    def load(cls, path: str | None) -> "Thresholds":
        values = json.loads(Path(path).read_text()) if path else {}
        allowed = {item.name for item in __import__('dataclasses').fields(cls)}
        result = cls(**{key: value for key, value in values.items() if key in allowed})
        if result.logic not in {"OR", "AND"}: raise ValueError("logic must be OR or AND")
        if result.area_mode not in {"absolute", "relative"}: raise ValueError("area_mode must be absolute or relative")
        if any(value < 0 for key, value in asdict(result).items() if isinstance(value, (int, float))): raise ValueError("thresholds must be non-negative")
        return result

@dataclass
class Region:
    id: str
    source: str
    classification: str
    area_mm2: float
    bbox_mm: list[float]
    length_mm: float
    width_mm: float
    edge_displacement_mm: float | None
    status: str = ""
    severity: str = ""
    reasons: list[str] = field(default_factory=list)

    @classmethod
    def make(cls, index: int, data: dict[str, Any]) -> "Region":
        source = data.get("source", "UNKNOWN_GEOMETRIC_DIFFERENCE")
        if source not in SOURCES: raise ValueError(f"region {index}: source must be ORIGINAL_ONLY or MANUFACTURER_ONLY")
        box = data.get("bbox_mm")
        if not isinstance(box, list) or len(box) != 4 or box[2] < box[0] or box[3] < box[1]: raise ValueError(f"region {index}: bbox_mm must be [min_x,min_y,max_x,max_y]")
        dx, dy = box[2]-box[0], box[3]-box[1]
        # Classification is conservative: source-derived additions/removals only.
        inferred = "REMOVED_GEOMETRY" if source == "ORIGINAL_ONLY" else "ADDED_GEOMETRY"
        return cls(f"{index:03d}", source, data.get("classification", inferred), float(data["area_mm2"]), box,
                   float(data.get("length_mm", max(dx, dy))), float(data.get("width_mm", min(dx, dy))),
                   None if data.get("edge_displacement_mm") is None else float(data["edge_displacement_mm"]))

def area_limit(t: Thresholds, original_area: float) -> float:
    return t.area_mm2 if t.area_mode == "absolute" else original_area * t.relative_area_percent / 100

def filter_region(region: Region, t: Thresholds, original_area: float) -> Region:
    limit = area_limit(t, original_area)
    criteria = [("area", region.area_mm2, limit), ("width", region.width_mm, t.width_mm), ("length", region.length_mm, t.length_mm)]
    if region.edge_displacement_mm is not None: criteria.append(("edge displacement", region.edge_displacement_mm, t.edge_displacement_mm))
    enabled = [(name, actual, threshold, actual >= threshold) for name, actual, threshold in criteria if threshold > 0]
    type_enabled = region.classification in t.flag_types or region.source in t.flag_types
    passed = (any(item[3] for item in enabled) if t.logic == "OR" else bool(enabled) and all(item[3] for item in enabled)) and type_enabled
    if passed:
        region.status, region.severity = "FLAG", severity(region, t)
        region.reasons = [f"{name} {actual:.6g} meets threshold {threshold:.6g}" for name, actual, threshold, match in enabled if match]
    else:
        region.status, region.severity = "IGNORE", "INFORMATION"
        region.reasons = ([] if type_enabled else [f"type {region.classification} not selected for flagging"])
        region.reasons += [f"{name} {actual:.6g} below threshold {threshold:.6g}" for name, actual, threshold, match in enabled if not match]
        if region.area_mm2 < limit: region.classification = "BELOW_AREA_THRESHOLD"
        elif not region.reasons: region.reasons = ["no enabled threshold criterion"]
    return region

def severity(region: Region, t: Thresholds) -> str:
    critical = ((t.critical_area_mm2 > 0 and region.area_mm2 >= t.critical_area_mm2) or
                (t.critical_width_mm > 0 and region.width_mm >= t.critical_width_mm) or
                (t.critical_length_mm > 0 and region.length_mm >= t.critical_length_mm))
    return "CRITICAL" if critical else "WARNING"

def registration(data: dict[str, Any], t: Thresholds) -> dict[str, Any]:
    a = data.get("alignment", {})
    x, y, rotation = float(a.get("x_mm", 0)), float(a.get("y_mm", 0)), float(a.get("rotation_deg", 0))
    within = abs(x) <= t.registration_x_mm and abs(y) <= t.registration_y_mm and abs(rotation) <= t.registration_rotation_deg
    return {"x_mm": x, "y_mm": y, "rotation_deg": rotation, "status": "WITHIN REGISTRATION TOLERANCE" if within else "REGISTRATION DIFFERENCE"}

def write_gerber(path: Path, regions: list[Region]) -> None:
    lines = ["G04 Gerber comparison generated region bounding boxes*", "%FSLAX46Y46*%", "%MOMM*%", "%ADD10C,0.010*%", "D10*"]
    for r in regions:
        x1,y1,x2,y2 = r.bbox_mm
        f=lambda x: str(round(x*1_000_000)).zfill(10)
        lines += [f"X{f(x1)}Y{f(y1)}D02*", f"X{f(x2)}Y{f(y1)}D01*", f"X{f(x2)}Y{f(y2)}D01*", f"X{f(x1)}Y{f(y2)}D01*", f"X{f(x1)}Y{f(y1)}D01*"]
    path.write_text("\n".join(lines)+"\nM02*\n")

def png(path: Path, regions: list[Region], mode: str) -> None:
    W=H=700; image=bytearray([255,255,255])*(W*H)
    if regions:
        x1=min(r.bbox_mm[0] for r in regions); y1=min(r.bbox_mm[1] for r in regions); x2=max(r.bbox_mm[2] for r in regions); y2=max(r.bbox_mm[3] for r in regions)
        scale=min((W-60)/max(x2-x1, .001),(H-60)/max(y2-y1, .001))
        for r in regions:
            if mode == "flagged" and r.status != "FLAG": continue
            if mode == "ignored" and r.status != "IGNORE": continue
            color=(220,50,47) if r.source=="ORIGINAL_ONLY" else (38,139,210)
            if r.status == "IGNORE": color=(140,140,140)
            ax=max(0,int(30+(r.bbox_mm[0]-x1)*scale)); bx=min(W,int(30+(r.bbox_mm[2]-x1)*scale)+1)
            ay=max(0,int(H-30-(r.bbox_mm[3]-y1)*scale)); by=min(H,int(H-30-(r.bbox_mm[1]-y1)*scale)+1)
            for yy in range(ay,by):
                for xx in range(ax,bx): image[(yy*W+xx)*3:(yy*W+xx+1)*3]=bytes(color)
            # Draw the report-table ID at the region's upper-left corner.
            glyphs = {"0":("111","101","101","101","111"),"1":("010","110","010","010","111"),"2":("111","001","111","100","111"),"3":("111","001","111","001","111"),"4":("101","101","111","001","001"),"5":("111","100","111","001","111"),"6":("111","100","111","101","111"),"7":("111","001","010","010","010"),"8":("111","101","111","101","111"),"9":("111","101","111","001","111")}
            for digit_index, digit in enumerate(r.id):
                for gy, row in enumerate(glyphs[digit]):
                    for gx, enabled in enumerate(row):
                        px, py = ax + digit_index * 5 + gx, ay + gy
                        if enabled == "1" and 0 <= px < W and 0 <= py < H: image[(py*W+px)*3:(py*W+px+1)*3] = b"\x00\x00\x00"
    raw=b''.join(b'\0'+bytes(image[y*W*3:(y+1)*W*3]) for y in range(H))
    chunk=lambda n,d: struct.pack('>I',len(d))+n+d+struct.pack('>I',zlib.crc32(n+d)&0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',W,H,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,9))+chunk(b'IEND',b''))
def report_data(raw: dict[str, Any], regions: list[Region], t: Thresholds) -> dict[str, Any]:
    original_area=float(raw.get("original_geometry_area_mm2", 0)); manufacturer_area=float(raw.get("manufacturer_geometry_area_mm2", 0))
    original_only=sum(r.area_mm2 for r in regions if r.source == "ORIGINAL_ONLY"); manufacturer_only=sum(r.area_mm2 for r in regions if r.source == "MANUFACTURER_ONLY")
    flagged=[r for r in regions if r.status == "FLAG"]; ignored=[r for r in regions if r.status == "IGNORE"]
    status="FAIL" if any(r.severity == "CRITICAL" for r in flagged) else "REVIEW" if flagged else "PASS"
    return {"report_title":"GERBER COMPARISON REPORT", "comparison":"Geometric XOR", "normalized_units":"mm", "original":raw.get("original","original.gbr"), "manufacturer":raw.get("manufacturer","manufacturer.gbr"), "thresholds":asdict(t), "alignment":registration(raw,t), "raw_results":{"original_geometry_area_mm2":original_area,"manufacturer_geometry_area_mm2":manufacturer_area,"common_geometry_area_mm2":float(raw.get("common_geometry_area_mm2", 0)),"original_only_area_mm2":original_only,"manufacturer_only_area_mm2":manufacturer_only,"total_xor_area_mm2":original_only+manufacturer_only,"raw_difference_regions":len(regions)}, "filtering":{"ignored_regions":len(ignored),"flagged_regions":len(flagged),"logic":t.logic,"area_effective_threshold_mm2":area_limit(t,original_area)}, "final_status":status, "status_rule":"PASS=no flagged regions; REVIEW=flagged regions below configured critical values; FAIL=a flagged region meets a configured critical area, width, or length value.", "regions":[asdict(r) for r in regions]}

def write_reports(out: Path, data: dict[str, Any]) -> None:
    regions=data["regions"]; raw=data["raw_results"]; filt=data["filtering"]
    (out/"comparison_report.json").write_text(json.dumps(data,indent=2)+"\n")
    fields=["id","classification","source","area_mm2","length_mm","width_mm","edge_displacement_mm","bbox_mm","status","severity","reasons"]
    with (out/"comparison_report.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in regions: w.writerow({**r,"bbox_mm":";".join(map(str,r["bbox_mm"])),"reasons":"; ".join(r["reasons"])})
    lines=["GERBER COMPARISON REPORT","="*24,f"Status: {data['final_status']}",f"Original: {data['original']}",f"Manufacturer: {data['manufacturer']}","", "RAW RESULTS"]
    lines += [f"{key}: {value}" for key,value in raw.items()] + ["", "THRESHOLD FILTERING",f"Ignored: {filt['ignored_regions']}",f"Flagged: {filt['flagged_regions']}",f"Logic: {filt['logic']}","", "USER THRESHOLDS",json.dumps(data['thresholds'],indent=2),"", "SIGNIFICANT DIFFERENCES"]
    for r in regions:
        if r["status"] == "FLAG": lines += [f"#{r['id']} {r['classification']} {r['source']}",f"Area: {r['area_mm2']} mm2; Length: {r['length_mm']} mm; Width: {r['width_mm']} mm",f"Bounding box: {r['bbox_mm']}",f"Status: {r['severity']}"]
    lines += ["", "IGNORED DIFFERENCES", f"{filt['ignored_regions']} regions were detected but excluded from the flagged result."]
    for r in regions:
        if r["status"] == "IGNORE": lines += [f"#{r['id']} reason: {'; '.join(r['reasons'])}; area: {r['area_mm2']}; bbox: {r['bbox_mm']}"]
    lines += ["", "FINAL RESULT", data["final_status"], data["status_rule"]]
    (out/"comparison_report.txt").write_text("\n".join(lines)+"\n")
    table="".join("<tr>"+"".join(f"<td>{html.escape(str(value))}</td>" for value in [r['id'],r['classification'],r['source'],r['area_mm2'],r['length_mm'],r['width_mm'],r['bbox_mm'][0],r['bbox_mm'][1],r['status'],r['severity'], '; '.join(r['reasons'])])+"</tr>" for r in regions)
    threshold_html=html.escape(json.dumps(data['thresholds'],indent=2))
    ignored="".join(f"<li><b>#{r['id']}</b>: {html.escape('; '.join(r['reasons']))}; area {r['area_mm2']} mm²; bbox {r['bbox_mm']}</li>" for r in regions if r['status']=='IGNORE') or "<li>None</li>"
    page=f'''<!doctype html><html><head><meta charset="utf-8"><title>Gerber Comparison Report</title><style>body{{font:14px system-ui;margin:2rem;color:#202020}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #bbb;padding:.4rem;text-align:left}}th{{background:#eee}}.status{{font-size:1.4rem;font-weight:bold}}pre{{background:#f5f5f5;padding:1rem}}img{{max-width:49%;border:1px solid #aaa}}</style></head><body><h1>GERBER COMPARISON REPORT</h1><p class="status">FINAL STATUS: {data['final_status']}</p><p><b>Original:</b> {html.escape(data['original'])}<br><b>Manufacturer:</b> {html.escape(data['manufacturer'])}<br><b>Comparison:</b> Geometric XOR (raw vector input is authoritative)</p><h2>Raw results</h2><pre>{html.escape(json.dumps(raw,indent=2))}</pre><h2>Threshold filtering</h2><p>Total geometric differences detected: {raw['raw_difference_regions']}<br>Differences ignored by threshold: {filt['ignored_regions']}<br>Significant differences flagged: {filt['flagged_regions']}</p><h2>Threshold audit trail</h2><pre>{threshold_html}</pre><h2>Difference regions</h2><table><tr><th>ID</th><th>Type</th><th>Source</th><th>Area mm²</th><th>Length mm</th><th>Width mm</th><th>X</th><th>Y</th><th>Status</th><th>Severity</th><th>Reason</th></tr>{table}</table><h2>Visual review</h2><p>Red: original-only; blue: manufacturer-only; gray: ignored. Region IDs correspond to the table and CSV.</p><img src="XOR_difference.png" alt="Raw XOR difference"><img src="overlay.png" alt="Overlay"><h2>Ignored differences</h2><p>Ignored regions remain in the raw XOR and are documented here.</p><ul>{ignored}</ul><h2>Decision rule</h2><p>{html.escape(data['status_rule'])}</p></body></html>'''
    (out/"comparison_report.html").write_text(page)

def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw-differences", required=True, help="JSON regions emitted by the vector Boolean stage")
    p.add_argument("--thresholds", help="JSON threshold configuration; defaults are explicit if omitted")
    p.add_argument("--output", default="comparison_output")
    args=p.parse_args(); raw=json.loads(Path(args.raw_differences).read_text()); t=Thresholds.load(args.thresholds)
    original_area=float(raw.get("original_geometry_area_mm2",0)); regions=[filter_region(Region.make(i,r),t,original_area) for i,r in enumerate(raw.get("regions",[]),1)]
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True); flagged=[r for r in regions if r.status=="FLAG"]
    write_gerber(out/"original_only.gbr",[r for r in regions if r.source=="ORIGINAL_ONLY"]); write_gerber(out/"manufacturer_only.gbr",[r for r in regions if r.source=="MANUFACTURER_ONLY"]); write_gerber(out/"XOR_difference.gbr",regions); write_gerber(out/"XOR_difference_filtered.gbr",flagged)
    for name, mode in [("overlay.png","all"),("XOR_difference.png","all"),("flagged_differences.png","flagged"),("ignored_differences.png","ignored")]: png(out/name,regions,mode)
    data=report_data(raw,regions,t); write_reports(out,data)
    (out/"comparison.log").write_text(f"Raw regions: {len(regions)}\nIgnored: {len(regions)-len(flagged)}\nFlagged: {len(flagged)}\nResult: {data['final_status']}\n")
    print(f"COMPARISON COMPLETE\nRaw differences: {len(regions)}\nIgnored: {len(regions)-len(flagged)}\nSignificant: {len(flagged)}\nResult: {data['final_status']}")
if __name__ == "__main__": main()
