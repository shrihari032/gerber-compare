"""Vector RS-274X reader and geometric XOR engine.

Coordinates are normalised to millimetres and snapped to a 1 nm grid before
GEOS operations.  This module intentionally has no raster comparison path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math, re
from pathlib import Path
from typing import Iterable

from shapely.affinity import rotate, translate
from shapely.geometry import GeometryCollection, LineString, Point, Polygon
from shapely.ops import unary_union

NM_MM = 0.000001
APERTURE_ALIASES = {
    "C": "C", "CIRCLE": "C", "CIRCULAR": "C",
    "R": "R", "RECTANGLE": "R", "VB_RECTANGLE": "R",
    "O": "O", "OBROUND": "O", "OBLONG": "O", "OVAL": "O", "VB_OBROUND": "O", "VB_OVAL": "O",
    "P": "P", "POLYGON": "P",
}

class GerberError(ValueError): pass

@dataclass
class Aperture:
    kind: str
    values: list[float]
    rotation: float = 0.0

    def shape(self, x: float, y: float):
        if self.kind == "C": return Point(x, y).buffer(self.values[0] / 2, quad_segs=32)
        if self.kind == "R":
            w, h = self.values[:2]; return Polygon([(x-w/2,y-h/2),(x+w/2,y-h/2),(x+w/2,y+h/2),(x-w/2,y+h/2)])
        if self.kind == "O":
            w, h = self.values[:2]
            if w == h: return Point(x, y).buffer(w / 2, quad_segs=32)
            if w > h: return LineString([(x-(w-h)/2,y),(x+(w-h)/2,y)]).buffer(h/2, cap_style=1, quad_segs=32)
            return LineString([(x,y-(h-w)/2),(x,y+(h-w)/2)]).buffer(w/2, cap_style=1, quad_segs=32)
        if self.kind == "P":
            diameter, vertices = self.values[:2]
            pts=[(x+diameter/2*math.cos(math.radians(self.rotation+90+i*360/vertices)), y+diameter/2*math.sin(math.radians(self.rotation+90+i*360/vertices))) for i in range(int(vertices))]
            return Polygon(pts)
        raise GerberError(f"unsupported aperture {self.kind}")

    def stroke(self, start: tuple[float,float], end: tuple[float,float]):
        if self.kind == "C": return LineString([start,end]).buffer(self.values[0]/2, cap_style=1, quad_segs=32)
        # RS-274X arbitrary aperture sweep is a Minkowski sum; unioning flashes
        # plus the swept bounding envelope is exact for R/O only when axis-aligned.
        # Preserve safety rather than claiming unsupported sweeps are exact.
        if self.kind in {"R", "O", "P"}: return unary_union([self.shape(*start), self.shape(*end), LineString([start,end]).buffer(max(self.values[:2])/2, cap_style=3)])
        raise GerberError(f"unsupported stroke aperture {self.kind}")

@dataclass
class ParsedGerber:
    path: str
    units: str = ""
    format: str = ""
    zero_suppression: str = ""
    apertures: dict[int,Aperture] = field(default_factory=dict)
    geometry: object = field(default_factory=GeometryCollection)
    command_count: int = 0
    regions: int = 0
    arcs: int = 0
    flashes: int = 0
    unsupported_features: list[str] = field(default_factory=list)
    aperture_aliases: list[dict[str, str]] = field(default_factory=list)

def _tokens(text: str) -> Iterable[str]:
    # Parameters retain percent delimiters; ordinary commands are star delimited.
    for token in re.findall(r"%.*?%|[^*]+", text.replace("\r", "").replace("\n", ""), re.S):
        token=token.strip()
        if token: yield token.strip("*")

class Parser:
    def parse(self, path: str | Path) -> ParsedGerber:
        result=ParsedGerber(str(path)); text=Path(path).read_text(encoding="utf-8", errors="replace")
        x=y=0.0; selected=None; operation=2; interpolation=1; polarity="D"; geometry=GeometryCollection(); region=False; contours=[]; contour=[]
        def apply(new_geometry):
            """Apply polarity immediately: later dark objects can refill clear areas."""
            nonlocal geometry
            try:
                geometry = geometry.union(new_geometry) if polarity == "D" else geometry.difference(new_geometry)
            except Exception as exc:
                raise GerberError(f"Boolean geometry failure while applying {polarity} polarity: {exc}") from exc
        for raw in _tokens(text):
            result.command_count += 1
            token=raw.strip()
            if token.startswith("%"):
                body=token.strip("%").rstrip("*")
                if body.startswith("FS"):
                    m=re.search(r"FS([LTD])A?X(\d)(\d)Y(\d)(\d)",body)
                    if not m: raise GerberError(f"invalid FS command: {body}")
                    if m.group(2,3)!=m.group(4,5): raise GerberError("different X/Y formats are unsupported")
                    result.zero_suppression={"L":"leading","T":"trailing","D":"decimal"}[m.group(1)]; result.format=f"{m.group(2)}:{m.group(3)}"; continue
                if body.startswith("MO"):
                    result.units="inch" if body[2:].startswith("IN") else "mm" if body[2:].startswith("MM") else ""; continue
                if body.startswith("ADD"):
                    # Some CAM exporters use named templates such as
                    # VB_RECTANGLE instead of directly naming R/C/O.
                    m=re.fullmatch(r"ADD(\d+)([A-Za-z_][A-Za-z0-9_]*)(?:,(.*))?",body)
                    if not m: raise GerberError(f"malformed aperture definition: {body}")
                    name, parameters=m.group(2).upper(),m.group(3) or ""
                    kind=APERTURE_ALIASES.get(name)
                    if kind is None:
                        result.unsupported_features.append(f"aperture macro {m.group(2)} (D{m.group(1)})")
                        raise GerberError(f"unsupported aperture macro {m.group(2)} in {body}")
                    try: vals=[float(v) * (25.4 if result.units=="inch" else 1) for v in re.split(r"[Xx]",parameters) if v]
                    except ValueError as exc: raise GerberError(f"non-numeric aperture parameter in {body}") from exc
                    if kind == "P" and len(vals)>=2: vals[1] /= (25.4 if result.units=="inch" else 1)
                    required={"C":1,"R":2,"O":2,"P":2}[kind]
                    if len(vals) < required: raise GerberError(f"aperture {body} requires {required} parameter(s)")
                    if name != kind: result.aperture_aliases.append({"original_aperture_name":m.group(2),"normalized_aperture_type":kind,"aperture_code":f"D{m.group(1)}"})
                    result.apertures[int(m.group(1))]=Aperture(kind,vals, vals[2] if kind=="P" and len(vals)>2 else 0); continue
                if body.startswith("LP"): polarity=body[2:3]; continue
                if body.startswith(("TF","TA","TD","TO","AM","LM","LR","LS")):
                    if body.startswith("AM"): result.unsupported_features.append("aperture macro")
                    continue
                continue
            if token.startswith("G04") or token.startswith("M02"): continue
            if "G36" in token: region=True; contours=[]; contour=[]; continue
            if "G37" in token:
                if contour: contours.append(contour)
                if not contours: raise GerberError("empty region")
                # Gerber region contours are filled according to their nesting.
                # Symmetric difference gives an even/odd fill and correctly makes
                # an inner contour a hole without relying on winding direction.
                geom=GeometryCollection()
                for points in contours:
                    if len(points) < 3: raise GerberError("region contour has fewer than three points")
                    geom=geom.symmetric_difference(Polygon(points))
                apply(geom); result.regions+=1; region=False; continue
            g=re.search(r"G0?([123])",token)
            if g: interpolation=int(g.group(1))
            d=re.search(r"D0?([123])",token)
            if d: operation=int(d.group(1))
            select=re.fullmatch(r"D(\d+)",token)
            if select and int(select.group(1))>=10: selected=int(select.group(1)); continue
            if not ("X" in token or "Y" in token): continue
            if not result.format or not result.units: raise GerberError("FS and MO must precede coordinates")
            nx=self._coord(re.search(r"X([+-]?\d+(?:\.\d+)?)",token), x, result); ny=self._coord(re.search(r"Y([+-]?\d+(?:\.\d+)?)",token), y, result)
            if operation==2: x,y=nx,ny; contour.append((x,y)) if region else None; continue
            if selected not in result.apertures: raise GerberError("drawing operation without selected aperture")
            ap=result.apertures[selected]
            if operation==3: geom=ap.shape(nx,ny); result.flashes+=1
            elif region: contour.append((nx,ny)); x,y=nx,ny; continue
            elif interpolation in (2,3):
                im=re.search(r"I([+-]?\d+)",token); jm=re.search(r"J([+-]?\d+)",token)
                if not im or not jm: raise GerberError("arc missing I/J")
                cx=x+self._coord(im,0,result); cy=y+self._coord(jm,0,result); geom=self._arc((x,y),(nx,ny),(cx,cy),interpolation==3,ap); result.arcs+=1
            else: geom=ap.stroke((x,y),(nx,ny))
            apply(geom); x,y=nx,ny
        if not result.format or not result.units: raise GerberError("not an RS-274X Gerber: missing FS or MO")
        if region: raise GerberError("unterminated G36 region")
        result.geometry=self._snap(geometry)
        return result

    def _coord(self,m, previous, r):
        if not m: return previous
        value=m.group(1)
        if "." in value: n=float(value)
        else:
            digits=int(r.format.split(":")[1]); sign=-1 if value.startswith("-") else 1; n=sign*int(value.lstrip("+-"))/10**digits
        return n*(25.4 if r.units=="inch" else 1)
    def _arc(self,a,b,c,ccw,ap):
        radius=math.dist(a,c); start=math.atan2(a[1]-c[1],a[0]-c[0]); end=math.atan2(b[1]-c[1],b[0]-c[0])
        delta=(end-start)%(2*math.pi) if ccw else -((start-end)%(2*math.pi)); delta=delta or (2*math.pi if ccw else -2*math.pi)
        steps=max(8,math.ceil(abs(delta)*radius / .01)); pts=[(c[0]+radius*math.cos(start+delta*i/steps),c[1]+radius*math.sin(start+delta*i/steps)) for i in range(steps+1)]
        return ap.stroke(pts[0],pts[-1]) if len(pts)==2 else LineString(pts).buffer(ap.values[0]/2, cap_style=1, quad_segs=32)
    def _snap(self,g):
        # Coordinate precision declared as 1 nm; GEOS still performs the Boolean.
        try:
            from shapely import set_precision
            return set_precision(g, NM_MM)
        except ImportError: return g

def compare(original: ParsedGerber, manufacturer: ParsedGerber, dx=0., dy=0., rotation_deg=0.):
    b=rotate(translate(manufacturer.geometry,dx,dy),rotation_deg,origin="centroid") if rotation_deg else translate(manufacturer.geometry,dx,dy)
    only_a=original.geometry.difference(b); only_b=b.difference(original.geometry); xor=only_a.union(only_b)
    return only_a, only_b, original.geometry.intersection(b), xor

def polygons(geometry):
    if geometry.is_empty: return []
    if geometry.geom_type=="Polygon": return [geometry]
    if geometry.geom_type in {"MultiPolygon","GeometryCollection"}: return [p for g in geometry.geoms for p in polygons(g)]
    return []
