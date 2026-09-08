"""Distance- and topology-based post-XOR significance analysis."""
from dataclasses import dataclass
import math
from shapely.geometry import Point
from shapely.ops import nearest_points
from gerber_xor import polygons

@dataclass(frozen=True)
class ComparisonConfig:
    geometric_tolerance_mm: float = 0.05
    translation_tolerance_mm: float = 0.05
    topology_check: bool = True
    def __post_init__(self):
        if self.geometric_tolerance_mm < 0 or self.translation_tolerance_mm < 0:
            raise ValueError("comparison tolerances must be non-negative")

def _topology(geometry):
    parts=polygons(geometry)
    return len(parts), sum(len(p.interiors) for p in parts)

def _nearest_component(component, candidates):
    return min(candidates, key=lambda c: component.distance(c)) if candidates else None

def _boundary_deviation(component, reference):
    """Maximum / sampled mean / p95 distance to the opposite boundary in mm."""
    if reference.is_empty: return float("inf"), float("inf"), float("inf")
    points=[]
    for ring in [component.exterior, *component.interiors]:
        coords=list(ring.coords); stride=max(1, len(coords)//128)
        points.extend(coords[::stride])
    distances=[reference.boundary.distance(Point(p)) for p in points]
    if not distances: return 0.,0.,0.
    distances.sort(); return max(distances),sum(distances)/len(distances),distances[min(len(distances)-1, math.ceil(len(distances)*.95)-1)]

class SignificanceAnalyzer:
    """Classifies raw XOR components; it never modifies the raw Boolean result."""
    def __init__(self, original, working, config=ComparisonConfig()):
        self.original, self.working, self.config = original, working, config
        self.original_components, self.working_components = polygons(original), polygons(working)
        self.original_topology, self.working_topology = _topology(original), _topology(working)

    def evaluate(self, component, source):
        source_parts=self.original_components if source == "ORIGINAL_ONLY" else self.working_components
        other_parts=self.working_components if source == "ORIGINAL_ONLY" else self.original_components
        owner=_nearest_component(component, source_parts)
        counterpart=_nearest_component(owner, other_parts) if owner else None
        if owner is None or counterpart is None:
            return self._result(component, source, None, None, "FLAG", "UNRESOLVED_GEOMETRY", "No corresponding geometry could be established safely.")
        max_dev,mean_dev,p95=_boundary_deviation(component,counterpart)
        a,b=owner.centroid,counterpart.centroid; dx=b.x-a.x; dy=b.y-a.y; translation=math.hypot(dx,dy)
        topology_changed=self.config.topology_check and self.original_topology != self.working_topology
        hausdorff=owner.hausdorff_distance(counterpart)
        if topology_changed: decision, code, reason="FLAG","TOPOLOGY_CHANGE","Geometric component or hole count changed."
        elif translation > self.config.translation_tolerance_mm: decision, code, reason="FLAG","TRANSLATION_EXCEEDED",f"Translation {translation:.6g} mm exceeds tolerance {self.config.translation_tolerance_mm:.6g} mm."
        elif max_dev > self.config.geometric_tolerance_mm: decision, code, reason="FLAG","BOUNDARY_DEVIATION_EXCEEDED",f"Boundary deviation {max_dev:.6g} mm exceeds tolerance {self.config.geometric_tolerance_mm:.6g} mm."
        else: decision, code, reason="IGNORE","WITHIN_GEOMETRIC_TOLERANCE",f"Boundary deviation {max_dev:.6g} mm is within tolerance {self.config.geometric_tolerance_mm:.6g} mm."
        return self._result(component,source,owner,counterpart,decision,code,reason,dx,dy,translation,max_dev,mean_dev,p95,hausdorff,topology_changed)

    def _result(self, component, source, owner, counterpart, decision, code, reason, dx=None, dy=None, translation=None, maximum=None, mean=None, p95=None, hausdorff=None, topology=False):
        return {"decision":decision,"reason_code":code,"reason":reason,"centroid_original_mm":None if owner is None else ([owner.centroid.x,owner.centroid.y] if source=="ORIGINAL_ONLY" else [counterpart.centroid.x,counterpart.centroid.y]),"centroid_working_mm":None if counterpart is None else ([counterpart.centroid.x,counterpart.centroid.y] if source=="ORIGINAL_ONLY" else [owner.centroid.x,owner.centroid.y]),"translation_dx_mm":dx,"translation_dy_mm":dy,"translation_distance_mm":translation,"boundary_max_deviation_mm":maximum,"boundary_mean_deviation_mm":mean,"boundary_p95_deviation_mm":p95,"hausdorff_distance_mm":hausdorff,"original_component_count":self.original_topology[0],"working_component_count":self.working_topology[0],"original_hole_count":self.original_topology[1],"working_hole_count":self.working_topology[1],"topology_changed":topology}
