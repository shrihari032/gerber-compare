import unittest
from shapely.geometry import box
from shapely.affinity import translate
from significance import ComparisonConfig, SignificanceAnalyzer

class SignificanceTests(unittest.TestCase):
    def decision(self, original, working, config):
        delta=original.symmetric_difference(working)
        if delta.is_empty: return []
        analyzer=SignificanceAnalyzer(original,working,config)
        source="ORIGINAL_ONLY" if not original.difference(working).is_empty else "WORKING_ONLY"
        return [analyzer.evaluate(part,source) for part in (delta.geoms if hasattr(delta,'geoms') else [delta])]

    def test_small_pad_change_is_ignored_by_distance_not_area(self):
        results=self.decision(box(0,0,2,2),box(.01,.01,1.99,1.99),ComparisonConfig(.05,.05))
        self.assertTrue(all(r['decision']=='IGNORE' for r in results))

    def test_larger_pad_change_is_flagged(self):
        results=self.decision(box(0,0,2,2),box(.1,.1,1.9,1.9),ComparisonConfig(.05,.5))
        self.assertTrue(any(r['reason_code']=='BOUNDARY_DEVIATION_EXCEEDED' for r in results))

    def test_translation_tolerance_is_independent(self):
        original=box(0,0,2,2); working=translate(original,.08,0)
        self.assertTrue(any(r['decision']=='FLAG' for r in self.decision(original,working,ComparisonConfig(.2,.05))))
        self.assertTrue(all(r['decision']=='IGNORE' for r in self.decision(original,working,ComparisonConfig(.2,.1))))

    def test_topology_change_always_flags(self):
        original=box(0,0,10,.2); working=original.difference(box(4.999,0,5.001,.2))
        results=self.decision(original,working,ComparisonConfig(1,1))
        self.assertTrue(any(r['reason_code']=='TOPOLOGY_CHANGE' for r in results))
