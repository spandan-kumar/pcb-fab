"""Fast disk dilation must preserve every original clearance-mask cell."""
import math
import unittest

import numpy as np

from etch.drc import RULES
from etch.model import Board, Net
from etch.router import CLR, VIA_DIA, VIA_DRILL, Router, dilate


def reference_dilate(mask, radius):
    """Original offset-by-offset disk expansion."""
    result = np.zeros_like(mask)
    ny, nx = mask.shape
    reach = math.ceil(radius)
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            if dx * dx + dy * dy >= radius * radius or abs(dx) >= nx or abs(dy) >= ny:
                continue
            y0, y1 = max(0, dy), min(ny, ny + dy)
            x0, x1 = max(0, dx), min(nx, nx + dx)
            result[y0:y1, x0:x1] |= mask[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    return result


def reference_masks(router, ni, width):
    """Original per-radius calculation on a pad-free board."""
    own = ni + 1
    hard = router.hard.copy()
    soft = np.zeros_like(hard)
    own_via = router.is_via & (router.owner[0] == own) & (router.owner[1] == own)
    via_hard = router.hard[0] | router.hard[1] | router.via_drill_block
    via_hard |= reference_dilate(router.is_via, (VIA_DRILL + RULES['hole_to_hole_mm'] - 1e-6) / router.grid) & ~own_via
    via_soft = np.zeros_like(via_hard)
    other = (router.owner > 0) & (router.owner != own) & (router.radius > 0)
    stubs = other & router.stub
    for layer in (0, 1):
        hard[layer] |= reference_dilate(stubs[layer], (width / 2 + CLR + 0.1) / router.grid)
    via_hard |= reference_dilate(stubs[0] | stubs[1], (VIA_DIA / 2 + CLR + 0.1) / router.grid)
    traces = other & ~router.stub
    for radius in np.unique(router.radius[traces]):
        tier = traces & (router.radius == radius)
        track_r = (width / 2 + CLR + float(radius)) / router.grid
        via_r = (VIA_DIA / 2 + CLR + float(radius)) / router.grid
        protected = tier & np.isin(router.owner, [n + 1 for n in router._active_nets if n != ni])
        for layer in (0, 1):
            soft[layer] |= reference_dilate(tier[layer], track_r)
            hard[layer] |= reference_dilate(protected[layer], track_r)
        via_soft |= reference_dilate(tier[0] | tier[1], via_r)
        via_hard |= reference_dilate(protected[0] | protected[1], via_r)
    hard &= router.owner != own
    soft &= router.owner != own
    hard |= router.no_route
    return hard, soft, via_hard, via_soft


class ClearanceMaskTests(unittest.TestCase):
    def test_clearance_masks_match_original_expansion(self):
        rng = np.random.default_rng(812)
        for grid in (0.1, 0.2):
            router = Router(Board(8, 8, mounting_holes=False), grid_pitch=grid)
            router.nets = [Net('OWN', []), Net('OTHER', []), Net('PROTECTED', [])]
            # Includes near-identical floating radii and disk-boundary values.
            radii = np.concatenate([np.linspace(0.1, 0.55, 24),
                                    [0.3, np.nextafter(np.float32(0.3), np.float32(1))],
                                    [grid * np.sqrt(k) - CLR - 0.1 for k in (35, 40, 45)]])
            radii = radii[radii > 0]
            for i, radius in enumerate(radii):
                layer, y, x = i % 2, int(rng.integers(3, router.ny - 3)), int(rng.integers(3, router.nx - 3))
                router.owner[layer, y, x] = 1 + i % 3
                router.radius[layer, y, x] = radius
                router.stub[layer, y, x] = i % 7 == 0
            router.is_via[5, 5] = True
            router.owner[:, 5, 5] = 1
            router.radius[:, 5, 5] = 0.3
            router.no_route[0, 10, 10] = True
            original_radii = router.radius.copy()
            for active in ({0}, {0, 2}):
                router._active_nets = active
                for width in (0.2, 0.4, 1.0):
                    with self.subTest(grid=grid, width=width, active=active):
                        expected = reference_masks(router, 0, width)
                        actual = router._blocked_for(0, width)
                        for a, b in zip(actual, expected):
                            np.testing.assert_array_equal(a, b)
                        np.testing.assert_array_equal(router.radius, original_radii)

    def test_disk_expansion_matches_reference_at_boundaries_and_edges(self):
        rng = np.random.default_rng(815)
        radii = [0, 0.1, 1, 1.01, math.sqrt(2), math.nextafter(math.sqrt(2), 0),
                 math.nextafter(math.sqrt(2), math.inf), 2, math.sqrt(5), 5.8, 10]
        for shape in ((1, 1), (1, 8), (8, 1), (13, 17)):
            for density in (0, 0.1, 0.5, 1):
                mask = rng.random(shape) < density
                original = mask.copy()
                for radius in radii:
                    with self.subTest(shape=shape, density=density, radius=radius):
                        np.testing.assert_array_equal(dilate(mask, radius), reference_dilate(mask, radius))
                        np.testing.assert_array_equal(mask, original)


if __name__ == '__main__':
    unittest.main()
