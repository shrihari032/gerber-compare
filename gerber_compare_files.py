#!/usr/bin/env python3
"""Compare two Gerber files through parsed vector geometry (never image XOR)."""
import argparse, hashlib, json
from pathlib import Path
from gerber_xor import Parser, compare, polygons

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(); p.add_argument('original'); p.add_argument('manufacturer'); p.add_argument('--output',default='Gerber_XOR_Comparison'); p.add_argument('--dx-mm',type=float,default=0); p.add_argument('--dy-mm',type=float,default=0); p.add_argument('--rotation-deg',type=float,default=0); args=p.parse_args()
 parser=Parser(); a=parser.parse(args.original); b=parser.parse(args.manufacturer); oa,mb,common,xor=compare(a,b,args.dx_mm,args.dy_mm,args.rotation_deg)
 regions=[]
 for source,geometry in [('ORIGINAL_ONLY',oa),('MANUFACTURER_ONLY',mb)]:
  for poly in polygons(geometry):
   minx,miny,maxx,maxy=poly.bounds; regions.append({'source':source,'area_mm2':poly.area,'bbox_mm':[minx,miny,maxx,maxy],'length_mm':max(maxx-minx,maxy-miny),'width_mm':min(maxx-minx,maxy-miny)})
 raw={'original':str(args.original),'manufacturer':str(args.manufacturer),'original_geometry_area_mm2':a.geometry.area,'manufacturer_geometry_area_mm2':b.geometry.area,'common_geometry_area_mm2':common.area,'alignment':{'x_mm':args.dx_mm,'y_mm':args.dy_mm,'rotation_deg':args.rotation_deg},'regions':regions,'traceability':{'original_sha256':sha(args.original),'manufacturer_sha256':sha(args.manufacturer),'normalization_units':'mm','internal_precision_nm':1},'unsupported_features':{'original':a.unsupported_features,'manufacturer':b.unsupported_features}}
 out=Path(args.output); out.mkdir(parents=True,exist_ok=True); raw_path=out/'raw_differences.json'; raw_path.write_text(json.dumps(raw,indent=2)+'\n')
 print(f'Parsed vector geometry: {len(regions)} raw XOR regions. Run gerber_compare.py --raw-differences {raw_path} --output {out}')
if __name__=='__main__': main()
