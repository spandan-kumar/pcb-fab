"""Power-width policy, geometric widening, and honest rail-status regressions."""
import unittest
from unittest.mock import patch

from etch.analysis import power_rails
from etch.catalog import Part
from etch.drc import Item, collect_items, distance, run_drc, _pt_seg
from etch.exporter import readme
from etch.footprints import Footprint, Pad
from etch.model import Board, Component, Net, Trace
from etch.power_routing import widen_traces, width_summary
from etch.router import Router


def power_board(current=800):
    small = Footprint('small', [Pad('1', 0, 0, 0.4, 0.8)], 0.4, 0.8, 1, 'ic')
    big = Footprint('big', [Pad('1', 0, 0, 2, 2)], 2, 2, 1, 'connector')
    board = Board(20, 16, mounting_holes=False)
    board.components = [Component('U1', Part('small', 'Small pin', 'ic', '', small, []), x=4, y=8),
                        Component('J1', Part('big', 'Power source', 'connector', '', big, []), x=16, y=8)]
    board.nets = [Net('VCC', [('U1', '1'), ('J1', '1')], 'power', 5, current)]
    return board


class PowerRoutingTests(unittest.TestCase):
    def test_current_class_targets_and_local_neckdowns(self):
        for current, width in ((100, 0.4), (600, 0.6), (1500, 1.0)):
            with self.subTest(current=current):
                board = power_board(current)
                events = []
                router = Router(board, events.append)
                self.assertTrue(router.route_net(0))
                self.assertTrue(any(t.width == 0.2 for t in board.traces))
                self.assertGreater(sum(t.length for t in board.traces if t.width == width), 9)
                self.assertTrue(width_summary(board, board.nets[0])['width_ok'])
                self.assertEqual(run_drc(board)['errors'], 0)
                self.assertEqual([e for e in events if e['type'] == 'trace'],
                                 [{'type': 'trace', **t.to_json()} for t in board.traces])

    def test_congestion_preserves_clearance_and_reports_narrow_trunk(self):
        board = power_board()
        board.nets.append(Net('OTHER', []))
        board.traces = [Trace('OTHER', 'F.Cu', 0.2, [(8, 8.45), (12, 8.45)])]
        path = Trace('VCC', 'F.Cu', 0.2, [(4, 8), (16, 8)])
        grown = widen_traces(board, board.nets[0], [path])
        board.traces += grown
        self.assertAlmostEqual(sum(t.length for t in grown), path.length)
        for a in collect_items(board):
            for b in collect_items(board):
                if a.net != b.net and a.layer == b.layer:
                    self.assertGreaterEqual(distance(a, b), 0.18 - 1e-6)
        self.assertGreater(width_summary(board, board.nets[0])['constrained_mm'], 3)
        drc = run_drc(board)
        self.assertEqual(drc['errors'], 0)
        self.assertTrue(any(v['code'] == 'power_width' for v in drc['violations']))
        self.assertIn('Power routing needs review', readme(board, {}, drc, None, {}))

    def test_router_detours_for_full_width_instead_of_taking_narrow_shortcut(self):
        board = power_board()
        board.nets.append(Net('OTHER', []))
        router = Router(board)
        router._commit(1, 0.2, [(0, 42, x) for x in range(40, 61)])
        self.assertTrue(router.route_net(0))
        self.assertTrue(width_summary(board, board.nets[0])['width_ok'])
        self.assertGreater(sum(t.length for t in board.traces if t.net == 'VCC'), 12)
        self.assertEqual(run_drc(board)['errors'], 0)

    def test_power_trunks_route_before_signal_and_ground_vias(self):
        board = power_board()
        board.nets += [Net('GND', [], 'gnd'), Net('OTHER', [])]
        events = []
        result = Router(board, events.append).route_all()
        self.assertEqual(result['failed'], [])
        self.assertEqual([e['net'] for e in events if e['type'] == 'route_begin'][:2], ['VCC', 'GND'])
        self.assertTrue(width_summary(board, board.nets[0])['width_ok'])

    def test_connected_but_width_limited_board_refines_without_losing_better_result(self):
        for fine_succeeds in (True, False):
            with self.subTest(fine_succeeds=fine_succeeds):
                board, events = power_board(), []

                def attempt(router):
                    fine = router.grid == 0.1
                    trace = Trace('VCC', 'F.Cu', 0.6 if fine else 0.2, [(4, 8), (16, 8)])
                    router.b.traces = [trace]
                    router.emit({'type': 'trace', **trace.to_json()})
                    return {'failed': ['VCC'] if fine and not fine_succeeds else [], 'orphan_gnd': 0,
                            'grid_mm': router.grid}

                router = Router(board, events.append, time_budget=60)
                router._refine = True
                with patch.object(Router, '_route_all', attempt):
                    result = router.route_all()
                self.assertEqual(result['failed'], [])
                self.assertEqual(result['grid_mm'], 0.1 if fine_succeeds else 0.2)
                self.assertEqual(width_summary(board, board.nets[0])['width_ok'], fine_succeeds)
                replay = []
                for event in events:
                    if event['type'] == 'reset_routing':
                        replay = []
                    elif event['type'] == 'trace':
                        replay.append({k: v for k, v in event.items() if k != 'type'})
                self.assertEqual(replay, [t.to_json() for t in board.traces])

    def test_voltage_drop_cannot_hide_width_failure_or_missing_copper(self):
        board = power_board(1)
        board.traces = [Trace('VCC', 'F.Cu', 0.2, [(4, 8), (16, 8)])]
        rail = power_rails(board)[0]
        self.assertTrue(rail['drop_ok'])
        self.assertFalse(rail['width_ok'])
        self.assertFalse(rail['ok'])
        board.traces = []
        self.assertFalse(power_rails(board)[0]['ok'])

    def test_export_keeps_width_warning_when_drc_list_is_truncated(self):
        board = power_board()
        board.traces = [Trace('VCC', 'F.Cu', 0.2, [(4, 8), (16, 8)])]
        package_readme = readme(board, {}, {'violations': []}, None, {})
        self.assertIn('Power routing needs review', package_readme)
        self.assertIn('VCC: target 0.6 mm', package_readme)
        self.assertIn('below target outside pad escapes', package_readme)
        board.traces = []
        self.assertIn('no routed copper to verify', readme(board, {}, {}, None, {}))

    def test_unrouted_escape_reservations_are_not_widened_over(self):
        board = power_board()
        reserved = Item('circle', 'OTHER', 'F.Cu', 'escape', (10, 8.5), 0.1)
        grown = widen_traces(board, board.nets[0], [Trace('VCC', 'F.Cu', 0.2, [(4, 8), (16, 8)])], [reserved])
        board.traces = grown
        for it in collect_items(board):
            if it.kind == 'seg':
                self.assertGreaterEqual(distance(it, reserved), 0.18 - 1e-6)

    def test_smd_pad_does_not_excuse_bottom_layer_or_remote_neckdowns(self):
        board = power_board()
        net = board.nets[0]
        board.traces = [Trace('VCC', 'F.Cu', 0.2, [(4, 8), (4.8, 8)])]
        self.assertTrue(width_summary(board, net)['width_ok'])
        board.traces[0].layer = 'B.Cu'
        self.assertFalse(width_summary(board, net)['width_ok'])
        board.traces = [Trace('VCC', 'F.Cu', 0.2, [(4, 8), (7, 8)])]
        self.assertGreater(width_summary(board, net)['constrained_mm'], 1)

    def test_widening_preserves_corners_endpoints_and_never_shrinks(self):
        board = Board(20, 20)
        net = Net('VCC', [], 'power', 5, 600)
        board.nets = [net]
        path = Trace('VCC', 'F.Cu', 0.2, [(3, 3), (8, 3), (8, 8), (4, 8)])
        grown = widen_traces(board, net, [path])
        self.assertEqual(len(grown), 1)
        self.assertEqual(grown[0].points, path.points)
        self.assertEqual(grown[0].width, 0.6)
        path.width = 1.0
        self.assertTrue(all(t.width == 1.0 for t in widen_traces(board, net, [path])))

    def test_widening_respects_holes_and_board_edges(self):
        board = Board(20, 20, corner_radius=0)
        hole = Footprint('hole', [Pad('1', 0, 0, 1, 1, 'circle', 'through', 1, plated=False)], 1, 1, 1, 'hole')
        board.components = [Component('H1', Part('hole', 'Hole', 'mechanical', '', hole, []), x=10, y=10)]
        net = Net('VCC', [], 'power', 5, 2000)
        board.nets = [net]
        for y in (0.5, 9.1):
            grown = widen_traces(board, net, [Trace('VCC', 'F.Cu', 0.2, [(2, y), (18, y)])])
            for tr in grown:
                for a, b in zip(tr.points, tr.points[1:]):
                    if y == 0.5:
                        self.assertGreaterEqual(y - tr.width / 2, 0.3 - 1e-6)
                    else:
                        self.assertGreaterEqual(_pt_seg(10, 10, *a, *b) - tr.width / 2 - 0.5, 0.254 - 1e-6)

    def test_partial_ripup_restores_variable_width_occupancy(self):
        board = Board(20, 20)
        board.nets = [Net('VCC', [], 'power', 5, 600), Net('OTHER', [])]
        router = Router(board)
        rec = router._commit(0, 0.2, [(0, 50, x) for x in range(15, 86)], pin_key=('keep', '1'))
        self.assertTrue(any(t.width == 0.6 for t in rec.traces))
        self.assertGreaterEqual(float(router.radius[0, 50, 50]), 0.3)
        self.assertTrue(router._blocked_for(1, 0.2)[1][0, 52, 50])
        router._commit(0, 0.2, [(0, y, 50) for y in range(50, 66)], pin_key=('remove', '1'))
        router.ripup(0, ('remove', '1'))
        self.assertGreaterEqual(float(router.radius[0, 50, 50]), 0.3)
        self.assertTrue(router._blocked_for(1, 0.2)[1][0, 52, 50])
        self.assertAlmostEqual(sum(t.length for t in board.traces), 14)


if __name__ == '__main__':
    unittest.main()
