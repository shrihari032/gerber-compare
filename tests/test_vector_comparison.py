import tempfile
import unittest
from pathlib import Path

from gerber_xor import Parser, compare

MM = """%FSLAX46Y46*%
%MOMM*%
%ADD10C,1.000000*%
D10*
X01000000Y01000000D03*
M02*
"""
INCH = """%FSLAX46Y46*%
%MOIN*%
%ADD25C,0.039370*%
D25*
X003937Y003937D03*
M02*
"""

class VectorComparisonTests(unittest.TestCase):
    def parse(self, contents):
        with tempfile.NamedTemporaryFile("w", suffix=".gbr", delete=False) as f:
            f.write(contents); name=f.name
        self.addCleanup(lambda: Path(name).unlink(missing_ok=True))
        return Parser().parse(name)

    def test_identical_geometry_with_different_units_and_aperture_numbers(self):
        a, b = self.parse(MM), self.parse(INCH)
        _, _, _, xor = compare(a, b)
        self.assertLess(xor.area, 0.0001)

    def test_added_flash_is_manufacturer_only(self):
        a = self.parse(MM)
        b = self.parse(MM.replace("M02*", "X02000000Y01000000D03*\nM02*"))
        original_only, manufacturer_only, _, _ = compare(a, b)
        self.assertTrue(original_only.is_empty)
        self.assertGreater(manufacturer_only.area, 0.7)

