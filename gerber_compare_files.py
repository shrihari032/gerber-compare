#!/usr/bin/env python3
"""Compare two Gerbers and emit vector XOR Gerber, reports, and snapshots."""
import argparse, json
from colab_runner import run_comparison

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('original'); p.add_argument('working')
 p.add_argument('--output',default='Gerber_XOR_Comparison')
 p.add_argument('--dx-mm',type=float,default=0); p.add_argument('--dy-mm',type=float,default=0); p.add_argument('--rotation-deg',type=float,default=0)
 p.add_argument('--geometric-tolerance-mm',type=float,default=.05,help='Maximum boundary deviation to ignore (default: 0.05).')
 p.add_argument('--translation-tolerance-mm',type=float,default=.05,help='Maximum feature translation to ignore (default: 0.05).')
 p.add_argument('--no-topology-check',action='store_true',help='Disable geometric component/hole topology checks.')
 p.add_argument('--min-flag-area-mm2',type=float,help='Deprecated compatibility option; area no longer controls FLAG/IGNORE.')
 p.add_argument('--flag-source',choices=('ORIGINAL_ONLY','WORKING_ONLY'),action='append',dest='flag_sources',help='Deprecated compatibility option; source no longer controls FLAG/IGNORE.')
 args=p.parse_args()
 result=run_comparison(args.original,args.working,args.output,args.dx_mm,args.dy_mm,args.rotation_deg,args.geometric_tolerance_mm,args.translation_tolerance_mm,not args.no_topology_check,args.min_flag_area_mm2,args.flag_sources)
 print("GERBER XOR COMPARISON COMPLETE")
 print(json.dumps({key:result[key] for key in ('original_area_mm2','working_area_mm2','xor_area_mm2','difference_region_count','flagging')},indent=2))
 print(f"Raw XOR Gerber: {args.output}/XOR_difference.gbr")
 print(f"Flagged XOR Gerber: {args.output}/XOR_difference_flagged.gbr")
 print(f"Flagged snapshot: {args.output}/flagged_differences.png")
if __name__=='__main__': main()
