"""Google Colab entry point for a vector-only Gerber XOR comparison.

The functions are deliberately usable outside Colab for regression tests.
"""
from __future__ import annotations
import csv, hashlib, html, json, shutil
from pathlib import Path
from shapely.affinity import rotate, translate
from shapely.geometry import GeometryCollection
from shapely.ops import unary_union
from gerber_xor import Parser, compare, polygons

GEOMETRY_TOLERANCE_MM = 0.001

def _hash(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()

def _region_rows(original_only, working_only, min_flag_area_mm2, flag_sources):
    rows=[]
    for source, geom in (("ORIGINAL_ONLY", original_only), ("WORKING_ONLY", working_only)):
        for poly in polygons(geom):
            minx,miny,maxx,maxy=poly.bounds; c=poly.centroid
            flagged = source in flag_sources and poly.area >= min_flag_area_mm2
            reason = "meets selected source and minimum-area condition" if flagged else ("source not selected for flagging" if source not in flag_sources else f"area {poly.area:.6g} mm² below {min_flag_area_mm2:.6g} mm²")
            rows.append({"region_id":len(rows)+1,"source":source,"area_mm2":poly.area,"min_x_mm":minx,"min_y_mm":miny,"max_x_mm":maxx,"max_y_mm":maxy,"width_mm":maxx-minx,"height_mm":maxy-miny,"centroid_x_mm":c.x,"centroid_y_mm":c.y,"status":"FLAG" if flagged else "IGNORE","reason":reason,"_geometry":poly})
    return rows

def _plot(path, layers, title, labels=None):
    import matplotlib.pyplot as plt
    fig, ax=plt.subplots(figsize=(9,9), dpi=180)
    for geometry, color, label in layers:
        for poly in polygons(geometry):
            x,y=poly.exterior.xy; ax.fill(x,y,facecolor=color,edgecolor="black",linewidth=.25,alpha=.72,label=label)
            label=None
            for ring in poly.interiors: ax.fill(*ring.xy, color="white")
    if labels:
        for row in labels:
            ax.annotate(str(row["region_id"]), (row["centroid_x_mm"], row["centroid_y_mm"]), ha="center", va="center", fontsize=7, weight="bold")
    ax.set_aspect("equal"); ax.set_title(title); ax.set_xlabel("X (mm)"); ax.set_ylabel("Y (mm)"); ax.grid(True,linewidth=.3)
    handles, labels=ax.get_legend_handles_labels()
    if handles: ax.legend(handles,labels,loc="best")
    fig.tight_layout(); fig.savefig(path); plt.close(fig)

def _format_coordinate(value):
    """FS 4:6 fixed-point coordinate in normalized millimetres."""
    return f"{round(value * 1_000_000):010d}"

def write_xor_gerber(path, geometry):
    """Write exact polygon/holes as RS-274X regions (no bbox approximation)."""
    lines=["G04 Vector Gerber XOR output: filled polygon regions*", "%FSLAX46Y46*%", "%MOMM*%", "G01*"]
    for polygon in polygons(geometry):
        lines.append("G36*")
        for ring in [polygon.exterior, *polygon.interiors]:
            points=list(ring.coords)
            if len(points) < 4: continue
            first=points[0]; lines.append(f"X{_format_coordinate(first[0])}Y{_format_coordinate(first[1])}D02*")
            for x,y in points[1:]: lines.append(f"X{_format_coordinate(x)}Y{_format_coordinate(y)}D01*")
        lines.append("G37*")
    path.write_text("\n".join(lines)+"\nM02*\n")

def run_comparison(original_file, working_file, output_dir="Gerber_XOR_Comparison", dx_mm=0.0, dy_mm=0.0, rotation_deg=0.0, min_flag_area_mm2=0.0, flag_sources=("ORIGINAL_ONLY", "WORKING_ONLY")):
    """Calculate vector XOR and apply auditable user-selected flag conditions.

    Raw XOR is always written.  ``min_flag_area_mm2`` and ``flag_sources`` only
    affect the separate filtered Gerber and flagged snapshot, never raw data.
    """
    output=Path(output_dir); output.mkdir(parents=True,exist_ok=True)
    original_path, working_path=Path(original_file),Path(working_file)
    if not original_path.is_file() or not working_path.is_file(): raise FileNotFoundError("Both selected Gerber files must exist")
    parser=Parser(); original=parser.parse(original_path); working=parser.parse(working_path)
    original_only, working_only, common, xor=compare(original,working,dx_mm,dy_mm,rotation_deg)
    flag_sources=set(flag_sources)
    if min_flag_area_mm2 < 0 or not flag_sources.issubset({"ORIGINAL_ONLY", "WORKING_ONLY"}): raise ValueError("invalid flag conditions")
    rows=_region_rows(original_only,working_only,min_flag_area_mm2,flag_sources)
    xor_bounds=None if xor.is_empty else dict(zip(("min_x_mm","min_y_mm","max_x_mm","max_y_mm"),xor.bounds))
    if xor_bounds: xor_bounds.update(width_mm=xor_bounds['max_x_mm']-xor_bounds['min_x_mm'],height_mm=xor_bounds['max_y_mm']-xor_bounds['min_y_mm'])
    flagged=[row for row in rows if row["status"]=="FLAG"]; ignored=[row for row in rows if row["status"]=="IGNORE"]
    filtered_xor=unary_union([row["_geometry"] for row in flagged]) if flagged else GeometryCollection()
    result={"original_file":original_path.name,"working_file":working_path.name,"units":"mm","geometry_tolerance_mm":GEOMETRY_TOLERANCE_MM,"original_area_mm2":original.geometry.area,"working_area_mm2":working.geometry.area,"common_area_mm2":common.area,"original_only_area_mm2":original_only.area,"working_only_area_mm2":working_only.area,"xor_area_mm2":xor.area,"percentage_difference":0 if original.geometry.area == 0 else xor.area/original.geometry.area*100,"alignment":{"dx_mm":dx_mm,"dy_mm":dy_mm,"rotation_deg":rotation_deg},"xor_bounding_box":xor_bounds,"difference_region_count":len(rows),"flagging":{"minimum_area_mm2":min_flag_area_mm2,"selected_sources":sorted(flag_sources),"flagged_regions":len(flagged),"ignored_regions":len(ignored),"flagged_area_mm2":filtered_xor.area},"difference_regions":[{key:value for key,value in row.items() if key != "_geometry"} for row in rows],"traceability":{"original_sha256":_hash(original_path),"working_sha256":_hash(working_path),"normalization_units":"mm"},"unsupported_features":{"original":original.unsupported_features,"working":working.unsupported_features}}
    (output/'raw_differences.json').write_text(json.dumps(result,indent=2)+"\n")
    fields=list(result["difference_regions"][0]) if rows else ["region_id","source","area_mm2","min_x_mm","min_y_mm","max_x_mm","max_y_mm","width_mm","height_mm","centroid_x_mm","centroid_y_mm","status","reason"]
    with (output/'difference_regions.csv').open('w',newline='') as f: writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader(); writer.writerows(result["difference_regions"])
    write_xor_gerber(output/'XOR_difference.gbr', xor)
    write_xor_gerber(output/'XOR_difference_flagged.gbr', filtered_xor)
    _plot(output/'original.png',[(original.geometry,'#4575b4','Original')],"Original vector geometry")
    transformed=rotate(translate(working.geometry,dx_mm,dy_mm),rotation_deg,origin='centroid') if rotation_deg else translate(working.geometry,dx_mm,dy_mm)
    _plot(output/'working.png',[(transformed,'#d73027','Working')],"Working vector geometry")
    _plot(output/'common.png',[(common,'#66a61e','Common')],"Common vector geometry")
    _plot(output/'original_only.png',[(original_only,'#d73027','Original-only')],"Original-only geometry")
    _plot(output/'working_only.png',[(working_only,'#4575b4','Working-only')],"Working-only geometry")
    _plot(output/'xor.png',[(original_only,'#d73027','Original-only'),(working_only,'#4575b4','Working-only')],"Vector XOR")
    _plot(output/'xor_comparison.png',[(original_only,'#d73027','Original-only (removed)'),(working_only,'#4575b4','Working-only (added)')],"Gerber XOR comparison")
    _plot(output/'flagged_differences.png',[(filtered_xor,'#ff8c00','Flagged XOR')],"Flagged difference-area snapshot", flagged)
    warning=original.unsupported_features+working.unsupported_features
    images=''.join(f'<figure><img src="{name}"><figcaption>{name}</figcaption></figure>' for name in ['original.png','working.png','common.png','original_only.png','working_only.png','xor.png','flagged_differences.png'])
    table=''.join('<tr>'+''.join(f'<td>{html.escape(str(row[column]))}</td>' for column in fields)+'</tr>' for row in result['difference_regions'])
    (output/'report.html').write_text(f'<!doctype html><meta charset="utf-8"><title>Gerber XOR report</title><style>body{{font:14px sans-serif;margin:2em}}img{{max-width:48%;border:1px solid #aaa}}figure{{display:inline-block;margin:8px}}td,th{{border:1px solid #ccc;padding:4px}}</style><h1>Gerber Vector XOR Report</h1><h2>Flagging audit</h2><pre>{html.escape(json.dumps(result["flagging"],indent=2))}</pre><p>Raw XOR: <code>XOR_difference.gbr</code>; flagged-only XOR: <code>XOR_difference_flagged.gbr</code>. Ignored regions remain in raw XOR.</p><h2>Results</h2><pre>{html.escape(json.dumps(result,indent=2))}</pre>'+('<h2>WARNING: unsupported features</h2><p>'+html.escape('; '.join(warning))+'</p>' if warning else '')+f'<h2>Detailed difference report</h2><table><tr>{"".join(f"<th>{html.escape(column)}</th>" for column in fields)}</tr>{table}</table><h2>Images</h2>'+images)
    archive=shutil.make_archive(str(output/'comparison_results'),'zip',output)
    result['zip_file']=archive
    return result

def colab_upload_and_run():
    """Interactive final Colab cell; uploads exactly two Gerber files and downloads ZIP."""
    from google.colab import files
    uploaded=files.upload()
    if len(uploaded) != 2: raise ValueError(f"Upload exactly two Gerber files; received {len(uploaded)}")
    names=list(uploaded); print("Uploaded files:", *[f"\n  [{i}] {name}" for i,name in enumerate(names)])
    original_index=int(input("Original file number [0]: ") or 0); working_index=int(input("Working file number [1]: ") or 1)
    if original_index == working_index or original_index not in range(2) or working_index not in range(2): raise ValueError("Choose two different valid file numbers")
    result=run_comparison(names[original_index],names[working_index]); print(json.dumps(result,indent=2)); files.download(result['zip_file']); return result
