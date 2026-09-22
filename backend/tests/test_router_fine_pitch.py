"""Regression checks for narrow pad rows; no LLM or saved runs required."""
import unittest
from unittest.mock import patch

import numpy as np

from etch.catalog import CATALOG, Part
from etch.drc import collect_items, distance, run_drc
from etch.footprints import lqfp, qfn
from etch.model import Board, Component, Net
from etch.router import Router


def usb_board(rotation=0, offset=0.0):
    board = Board(40, 30, mounting_holes=False)
    board.components = [Component('J1', CATALOG['usb-c-16p'], x=20 + offset, y=15, rot=rotation)]
    for i, pads in enumerate([['A6', 'B6'], ['A7', 'B7'], ['A5'], ['B5']]):
        ref = f'R{i + 1}'
        board.components.append(Component(ref, CATALOG['r-0603'], x=12 + 5 * i, y=24))
        board.nets.append(Net(f'N{i}', [('J1', p) for p in pads] + [(ref, '1')], 'highspeed'))
    return board


def package_board(fp):
    part = Part('test-chip', 'Test chip', 'ic', '', fp, [])
    board = Board(30, 30, mounting_holes=False)
    board.components = [Component('U1', part, x=15.05, y=15.05)]
    for i in range(4):
        ref = f'R{i + 1}'
        board.components.append(Component(ref, CATALOG['r-0603'], x=4, y=10 + i * 3))
        board.nets.append(Net(f'N{i}', [('U1', str(i + 2)), (ref, '2')]))
    return board


class FinePitchTests(unittest.TestCase):
    def assert_connected(self, board):
        # Check the actual copper graph, independently of the router's flags.
        items = collect_items(board)
        for net in board.nets:
            copper = [it for it in items if it.net == net.name]
            reached = {0}
            pending = [0]
            while pending:
                a = copper[pending.pop()]
                for j, b in enumerate(copper):
                    if j in reached:
                        continue
                    same_via = a.kind == b.kind == 'circle' and a.ref == b.ref and a.a == b.a
                    if same_via or (a.layer == b.layer and distance(a, b) <= 1e-6):
                        reached.add(j)
                        pending.append(j)
            self.assertEqual(len(reached), len(copper), f'{net.name}: disconnected copper')

    def test_usb_interleaved_pins(self):
        for rotation, offset in [(0, 0.0), (90, 0.05), (180, 0.025), (270, 0.075)]:
            with self.subTest(rotation=rotation, offset=offset):
                board = usb_board(rotation, offset)
                router = Router(board, time_budget=60, grid_pitch=0.1)
                self.assertEqual(router.grid, 0.1)
                result = router.route_all()
                self.assertEqual(result['failed'], [])
                drc = run_drc(board, result['failed'], result['orphan_gnd'])
                self.assertEqual(drc['errors'], 0, drc['violations'])
                self.assert_connected(board)

    def test_fine_pitch_packages(self):
        for fp in [lqfp(48, 0.5, 7), qfn(32, 0.5, 5, 3.2)]:
            with self.subTest(package=fp.name):
                board = package_board(fp)
                router = Router(board, time_budget=60, grid_pitch=0.1)
                self.assertEqual(router.grid, 0.1)
                result = router.route_all()
                self.assertEqual(result['failed'], [])
                drc = run_drc(board, result['failed'], result['orphan_gnd'])
                self.assertEqual(drc['errors'], 0, drc['violations'])
                self.assert_connected(board)

    def test_automatic_refinement_recovers_a_coarse_grid_failure(self):
        # Match the automatic router's 10-second coarse-pass allowance. This
        # escape row needs rip-ups at 0.2 mm, but routes directly at 0.1 mm.
        coarse = Router(package_board(lqfp(48, 0.5, 7)), grid_pitch=0.2, time_budget=10)
        self.assertTrue(coarse.route_all()['failed'])
        board = package_board(lqfp(48, 0.5, 7))
        router = Router(board, time_budget=30)
        result = router.route_all()
        self.assertEqual(result['grid_mm'], 0.1)
        self.assertEqual(result['failed'], [])
        self.assertEqual(result['routed'], result['total'])
        self.assertEqual(run_drc(board)['errors'], 0)
        self.assert_connected(board)

    def test_grid_is_per_board(self):
        fine = Router(usb_board(), grid_pitch=0.1)
        coarse = Router(Board(10, 10))
        self.assertEqual(fine.grid, 0.1)
        self.assertEqual(coarse.grid, 0.2)
        self.assertIsNot(fine._interior_cache, coarse._interior_cache)
        self.assertEqual(fine._cell(1, 1), (10, 10))
        self.assertEqual(coarse._cell(1, 1), (5, 5))

    def test_routing_a_completed_net_is_idempotent(self):
        board = usb_board()
        router = Router(board, grid_pitch=0.1)
        self.assertTrue(router.route_net(0))
        traces, vias = list(board.traces), list(board.vias)
        self.assertTrue(router.route_net(0))
        self.assertEqual(board.traces, traces)
        self.assertEqual(board.vias, vias)
        router.ripup(0)
        self.assertNotIn(0, router._connected_nets)
        self.assertTrue(router.route_net(0))

    def test_refinement_keeps_the_better_board_and_event_stream(self):
        # Make the first pass incomplete without depending on a timeout or
        # placement heuristic. The real router performs the refined pass.
        original = Router._route_all
        for fine_succeeds in (True, False):
            with self.subTest(fine_succeeds=fine_succeeds):
                board, events = usb_board(), []
                coarse_traces = []

                def attempt(router):
                    result = original(router)
                    if router.grid == 0.2:
                        coarse_traces[:] = router.b.traces
                        result['failed'] = ['N0']
                    elif not fine_succeeds:
                        result['failed'] = ['N0', 'N1']
                    return result

                router = Router(board, events.append, time_budget=60)
                with patch.object(Router, '_route_all', attempt):
                    result = router.route_all()
                self.assertIs(router.b, board)
                self.assertEqual(router.grid, 0.1 if fine_succeeds else 0.2)
                if fine_succeeds:
                    self.assertEqual(result['failed'], [])
                    self.assert_connected(board)
                else:
                    self.assertEqual(board.traces, coarse_traces)
                # Replaying streamed resets/rip-ups must yield the chosen copper.
                traces = []
                for event in events:
                    if event['type'] == 'reset_routing':
                        traces = []
                    elif event['type'] == 'ripup':
                        traces = [t for t in traces if t['net'] != event['net']]
                    elif event['type'] == 'trace':
                        traces.append({k: v for k, v in event.items() if k != 'type'})
                self.assertEqual(traces, [t.to_json() for t in board.traces])

    def test_reserved_ground_escapes_are_not_connections(self):
        board = usb_board()
        board.nets = [Net('GND', [('J1', 'A6'), ('J1', 'B6')], 'gnd')]
        router = Router(board)
        # No lower copper is available to this pair of pads. A path to another
        # reserved escape must not be accepted as an existing ground connection.
        router.hard[1] = True
        self.assertFalse(router.route_gnd_stub(router.pins[('J1', 'A6')], allow_ripup=False))
        self.assertEqual(board.traces, [])

    def test_ripup_only_removes_actual_layer_conflicts(self):
        board = Board(10, 10, mounting_holes=False)
        board.nets = [Net('A', []), Net('B', [])]
        router = Router(board, grid_pitch=0.1)
        router.owner[1, 50, 50] = 2
        router.radius[1, 50, 50] = 0.1
        self.assertEqual(router._crossed_nets([(0, 50, 50)], 0.2), set())
        self.assertEqual(router._crossed_nets([(0, 50, 50), (1, 50, 50)], 0.2), {1})
        # A wide power trace must be found even beyond a via-sized search box.
        router.owner[0, 50, 60] = 2
        router.radius[0, 50, 60] = 1.0
        self.assertIn(1, router._crossed_nets([(0, 50, 50)], 0.2))

    def test_soft_search_cannot_override_hard_via_restrictions(self):
        router = Router(Board(10, 10, mounting_holes=False))
        blocked = np.ones_like(router.hard)
        blocked[:, 25, 25] = False
        via_ok = np.zeros_like(router.is_via)
        via_soft = np.ones_like(via_ok)
        path = router._astar([(0, 25, 25)], None, blocked, via_ok, (25, 25, 25, 25),
                             goal_bottom=True, via_soft=via_soft)
        self.assertIsNone(path)

    def test_failed_nets_are_not_counted_as_routed(self):
        board = usb_board()
        router = Router(board, grid_pitch=0.1)
        router.hard[:] = True
        result = router.route_all()
        self.assertEqual(result['routed'], 0)
        self.assertEqual(len(result['failed']), result['total'])

    def test_invalid_grid_is_rejected(self):
        for grid in (0, -0.1, float('inf'), float('nan')):
            with self.subTest(grid=grid), self.assertRaises(ValueError):
                Router(Board(10, 10), grid_pitch=grid)

    def test_top_ground_bridge_connects_separate_pour_islands(self):
        board = Board(10, 10, mounting_holes=False)
        board.nets = [Net('GND', [], 'gnd')]
        router = Router(board)
        mask = np.zeros_like(router.is_via)
        mask[8:13, 8:13] = mask[8:13, 38:43] = True
        router.pour_mask = lambda: mask
        router._commit(0, 0.2, [(1, 10, 10), (0, 10, 10), (0, 10, 40), (1, 10, 40)])
        labels, main, orphans = router.pour_islands()
        self.assertEqual(labels[10, 10], labels[10, 40])
        self.assertNotEqual(main, 0)
        self.assertEqual(orphans, [])


if __name__ == '__main__':
    unittest.main()
