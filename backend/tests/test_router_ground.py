"""Ground repair and manufacturing-rule regressions; no external tools needed."""
import json
import unittest
from unittest.mock import patch

import numpy as np

from etch.catalog import Part
from etch.drc import RULES, run_drc
from etch.footprints import Footprint, Pad
from etch.kicad_export import write_kicad_pcb, write_kicad_pro
from etch.model import Board, Component, Net, Via
from etch.router import Router


class GroundRoutingTests(unittest.TestCase):
    def test_ground_retries_reset_stale_ui_failures_without_hiding_new_failures(self):
        fp = Footprint('test', [Pad('1', 0, 0, 1, 1)], 1, 1, 1, 'header')
        board = Board(10, 10)
        board.components = [Component('J1', Part('test', 'Test', 'connector', '', fp, []), x=5, y=5)]
        board.nets = [Net('GND', [('J1', '1')], 'gnd')]
        events = []
        router = Router(board, events.append)

        def fail(pin, **kwargs):
            router.failed.append('GND')
            router.emit({'type': 'route_fail', 'net': 'GND', 'reason': 'blocked'})

        with patch.object(router, 'route_gnd_stub', side_effect=fail):
            router._route_all_gnd_stubs()
        self.assertEqual([e['type'] for e in events], ['route_begin', 'route_fail'])
        self.assertEqual(router.failed, ['GND'])
        events.clear()
        with patch.object(router, 'route_gnd_stub', return_value=True):
            router._route_all_gnd_stubs()
        self.assertEqual(events, [{'type': 'route_begin', 'net': 'GND', 'cls': 'gnd'}])
        self.assertEqual(router.failed, [])

    def test_pour_necks_below_exported_minimum_are_not_connections(self):
        board = Board(10, 10)
        board.nets = [Net('GND', [], 'gnd'), Net('OTHER', [])]
        router = Router(board, grid_pitch=0.1)
        # Parallel 0.2 mm traces leave only 0.2 mm of pour after clearance,
        # narrower than the 0.25 mm minimum used by KiCad's zone fill.
        for row in (30, 40):
            router.owner[1, row, :] = 2
            router.radius[1, row, :] = 0.1
        self.assertFalse(router.pour_mask()[35, 50])
        board.pour_min_thickness = 0
        self.assertTrue(router.pour_mask()[35, 50])

    def test_ground_repair_can_use_a_legal_narrow_corridor(self):
        board = Board(12, 2, corner_radius=0, mounting_holes=False)
        board.nets = [Net('GND', [], 'gnd'), Net('OTHER', [])]
        router = Router(board, grid_pitch=0.2)
        for layer in (0, 1):
            for row in (3, 7):
                router._commit(1, 0.2, [(layer, row, x) for x in range(20, 41)])
        for col in (10, 50):
            router._commit(0, 0.2, [(0, 5, col), (1, 5, col)])
        labels, main, orphans = router.pour_islands()
        self.assertEqual(len(orphans), 1)
        self.assertEqual(router.heal_islands(labels, main, orphans), 1)
        self.assertEqual(router.routes[0][-1].width, 0.2)
        self.assertEqual(router.pour_islands()[2], [])
        self.assertEqual(run_drc(board)['errors'], 0)

    def test_via_reuse_and_partial_ripup_keep_shared_holes(self):
        board = Board(10, 10)
        board.nets = [Net('GND', [], 'gnd')]
        events = []
        router = Router(board, events.append)
        a = router._commit(0, 0.2, [(0, 25, 15), (0, 25, 25), (1, 25, 25)], pin_key=('A', '1'))
        b = router._commit(0, 0.2, [(0, 15, 25), (0, 25, 25), (1, 25, 25)], pin_key=('B', '1'))
        self.assertEqual(len(board.vias), 1)
        self.assertIs(a.vias[0], b.vias[0])
        self.assertEqual(sum(e['type'] == 'via' for e in events), 1)
        router.ripup(0, ('A', '1'))
        self.assertEqual(len(board.vias), 1)
        self.assertTrue(router.is_via[25, 25])
        self.assertTrue((router.owner[:, 25, 25] == 1).all())
        router.ripup(0, ('B', '1'))
        self.assertEqual(board.vias, [])
        self.assertFalse(router.is_via[25, 25])

    def test_drill_spacing_applies_to_same_net_but_allows_reuse(self):
        board = Board(10, 10)
        board.nets = [Net('GND', [], 'gnd'), Net('OTHER', [])]
        router = Router(board, grid_pitch=0.1)
        router._commit(0, 0.2, [(0, 50, 50), (1, 50, 50)])
        hard = router._blocked_for(0, 0.2)[2]
        self.assertFalse(hard[50, 50])
        self.assertTrue(hard[50, 56])
        self.assertFalse(hard[50, 58])
        self.assertTrue(router._blocked_for(1, 0.2)[2][50, 50])

    def test_candidate_path_checks_spacing_between_its_new_vias(self):
        router = Router(Board(10, 10), grid_pitch=0.2)
        # A bottom-layer bridge is mandatory. Its first possible return via
        # is only 0.4 mm from the entry hole; a legal return is 0.8 mm away.
        blocked = np.ones_like(router.hard)
        blocked[0, 25, 20] = False
        blocked[1, 25, 20:25] = False
        blocked[0, 25, 22:26] = False
        via_ok = np.zeros_like(router.is_via)
        via_ok[25, [20, 22, 24]] = True
        target = np.zeros_like(blocked)
        target[0, 25, 25] = True
        path = router._astar([(0, 25, 20)], target, blocked, via_ok, (25, 25, 20, 25))
        self.assertIsNotNone(path)
        self.assertEqual([(y, x) for a, (l, y, x) in zip(path, path[1:]) if a[0] != l], [(25, 20), (25, 24)])
        via_ok[25, 24] = False
        self.assertIsNone(router._astar([(0, 25, 20)], target, blocked, via_ok, (25, 25, 20, 25)))

    def test_vias_respect_through_hole_drills(self):
        fp = Footprint('test', [Pad('1', 0, 0, 1.1, 1.1, 'circle', 'through', 0.8)], 1.1, 1.1, 1, 'header')
        board = Board(10, 10)
        board.components = [Component('J1', Part('test', 'Test', 'connector', '', fp, []), x=5, y=5)]
        board.nets = [Net('GND', [('J1', '1')], 'gnd')]
        router = Router(board, grid_pitch=0.1)
        hard = router._blocked_for(0, 0.2)[2]
        self.assertTrue(hard[50, 60])
        self.assertFalse(hard[50, 61])

    def test_drc_detects_too_close_same_net_drills(self):
        board = Board(10, 10)
        board.vias = [Via('GND', 5, 5), Via('GND', 5.4, 5)]
        self.assertTrue(any(v['code'] == 'hole_spacing' for v in run_drc(board)['violations']))
        board.vias[1].x = 5.8
        self.assertFalse(any(v['code'] == 'hole_spacing' for v in run_drc(board)['violations']))

    def test_export_shares_pour_and_drill_constraints(self):
        board = Board(10, 10, pour_min_thickness=0.3)
        board.nets = [Net('GND', [], 'gnd')]
        self.assertIn('(min_thickness 0.3)', write_kicad_pcb(board))
        rules = json.loads(write_kicad_pro(board))['board']['design_settings']['rules']
        self.assertEqual(rules['min_hole_to_hole'], RULES['hole_to_hole_mm'])


if __name__ == '__main__':
    unittest.main()
