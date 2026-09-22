"""Full-width pad/trace/via joins, without an external KiCad dependency."""
import unittest
from unittest.mock import patch

import numpy as np

from etch.catalog import Part
from etch.drc import run_drc
from etch.footprints import Footprint, Pad
from etch.model import Board, Component, Net, Trace
from etch.router import Router


def junction_board(rotation=0):
    fp = Footprint('paired', [Pad('1', -1.1, 0, 1.1, 0.6), Pad('2', 1.1, 0, 1.1, 0.6)],
                   1.2, 1.2, 1, 'ic')
    board = Board(20, 20, mounting_holes=False)
    board.components = [Component('U1', Part('paired', 'Paired pins', 'ic', '', fp, []),
                                  x=10.05, y=10.05, rot=rotation)]
    board.nets = [Net('N', [('U1', '1'), ('U1', '2')])]
    return board


class JunctionTests(unittest.TestCase):
    def test_aligned_pads_join_exact_centres_in_every_rotation(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                board = junction_board(rotation)
                events = []
                router = Router(board, events.append, grid_pitch=0.2)
                self.assertTrue(router.route_net(0))
                self.assertEqual(len(board.traces), 1)
                self.assertEqual(len(board.traces[0].points), 2)
                self.assertEqual(set(board.traces[0].points), {p.center for p in router.pins.values()})
                self.assertAlmostEqual(board.traces[0].length, 2.2)
                self.assertEqual(run_drc(board)['errors'], 0)
                self.assertEqual([e for e in events if e['type'] == 'trace'],
                                 [{'type': 'trace', **board.traces[0].to_json()}])

    def test_direct_link_does_not_cross_another_net(self):
        board = junction_board()
        board.nets.append(Net('OTHER', []))
        board.traces.append(Trace('OTHER', 'F.Cu', 0.2, [(10, 8), (10, 12)]))
        router = Router(board)
        a, b = router.pins.values()
        self.assertIsNone(router._direct_pad_link(0, a, [b], 0.2))

    def test_direct_link_respects_keepouts_and_reserved_escapes(self):
        router = Router(junction_board())
        a, b = router.pins.values()
        x, y = router._cell(10.05, 10.05)
        router.hard[0, y, x] = True
        self.assertIsNone(router._direct_pad_link(0, a, [b], 0.2))
        router.hard[0, y, x] = False
        router.owner[0, y, x] = 2
        router.stub[0, y, x] = True
        self.assertIsNone(router._direct_pad_link(0, a, [b], 0.2))

    def test_off_grid_link_retains_its_clearance_after_partial_ripup(self):
        router = Router(junction_board())
        a, b = router.pins.values()
        path, end = router._direct_pad_link(0, a, [b], 0.2)
        rec = router._commit(0, 0.2, path, a.center, end, pin_key=('keep', '1'), straight=True)
        cell = path[len(path) // 2]
        self.assertAlmostEqual(rec.grid_offset, 0.070710678, places=6)
        self.assertGreaterEqual(float(router.radius[cell]), 0.15)
        router._commit(0, 0.2, [cell, (0, cell[1] + 1, cell[2])], pin_key=('remove', '1'))
        router.ripup(0, ('remove', '1'))
        self.assertGreaterEqual(float(router.radius[cell]), 0.15)
        self.assertAlmostEqual(router._pad_center_at(0, cell)[1], a.center[1])

    def test_connected_pad_interior_is_a_target_but_hard_cells_are_not(self):
        router = Router(junction_board())
        a, b = router.pins.values()
        blob = np.zeros_like(router.owner, dtype=bool)
        for cell in router.pad_cells[b.key]:
            blob[cell] = True
        interiors = sorted(router._interior_cache[b.key])
        router.hard[interiors[0]] = True
        with patch.object(router, '_astar', return_value=None) as search:
            router._route_pin_to_blob(0, a, blob, 0.2)
        target = search.call_args.args[1]
        self.assertFalse(target[interiors[0]])
        self.assertTrue(target[interiors[-1]])

    def test_via_junction_targets_the_centre_not_tangent_escape_cells(self):
        router = Router(junction_board())
        router._commit(0, 0.2, [(0, 25, 25), (1, 25, 25)])
        blob = np.zeros_like(router.owner, dtype=bool)
        blob[:, 25, 25] = True
        blob[0, 26, 27] = True  # endpoint can graze the 0.6 mm annulus
        pin = router.pins[('U1', '1')]
        with patch.object(router, '_astar', return_value=None) as search:
            router._route_pin_to_blob(0, pin, blob, 0.2)
        target = search.call_args.args[1]
        self.assertTrue(target[:, 25, 25].all())
        self.assertFalse(target[0, 26, 27])


if __name__ == '__main__':
    unittest.main()
