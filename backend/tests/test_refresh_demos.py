"""Offline demo reconstruction, safety guards and replay/export consistency."""
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from etch.model import Board, Net, Trace, Via
from tests.refresh_demos import DEMO_ROOT, check_replay, load_saved, local_only, refresh_bundle


class RefreshDemosTests(unittest.TestCase):
    def test_saved_designs_preserve_positions_and_start_without_copper(self):
        for demo in json.loads((DEMO_ROOT / 'index.json').read_text()):
            with self.subTest(board=demo['name']):
                board, design, events, raw, digest = load_saved(DEMO_ROOT / demo['run_id'], demo)
                self.assertEqual(board.name, design['name'])
                self.assertEqual(len(board.components), demo['stats']['components'] + 4)
                self.assertEqual(len(board.nets), demo['stats']['nets'])
                self.assertFalse(board.traces)
                self.assertFalse(board.vias)
                self.assertTrue(raw)
                self.assertEqual(len(digest), 64)
                self.assertEqual(board.texts, next(e['board']['texts'] for e in events if e['type'] == 'board'))

    def test_network_calls_are_blocked_and_guard_is_restored(self):
        connect = socket.socket.connect
        with local_only():
            with socket.socket() as sock:
                for call in (sock.connect, sock.connect_ex):
                    with self.assertRaisesRegex(RuntimeError, 'disallows networking'):
                        call(('127.0.0.1', 1))
            with self.assertRaisesRegex(RuntimeError, 'disallows networking'):
                socket.create_connection(('127.0.0.1', 1))
            with self.assertRaisesRegex(RuntimeError, 'disallows networking'):
                socket.getaddrinfo('example.invalid', 443)
        self.assertIs(socket.socket.connect, connect)

    def test_agent_and_shell_processes_are_blocked(self):
        with local_only():
            for command in (['claude', '--version'], ['curl', '--version'], ['python', '--version']):
                with self.subTest(command=command), self.assertRaisesRegex(ValueError, 'disallows process'):
                    subprocess.run(command)
            with self.assertRaisesRegex(ValueError, 'disallows shell commands'):
                subprocess.run('echo unexpected', shell=True)

    def test_only_resolved_eda_executable_is_allowed(self):
        with patch('tests.refresh_demos.kicad_cli', return_value='/bin/echo'), patch('subprocess.Popen') as popen:
            with local_only():
                subprocess.Popen(['/bin/echo', 'local-check'])
                with self.assertRaisesRegex(ValueError, 'disallows shell commands'):
                    subprocess.Popen(['/bin/echo'], executable='/bin/sh')
            popen.assert_called_once_with(['/bin/echo', 'local-check'])

    def test_replay_handles_resets_ripups_and_duplicate_geometry(self):
        trace = Trace('VCC', 'F.Cu', 0.4, [(1, 1), (2, 2)])
        via = Via('VCC', 2, 2)
        board = Board(10, 10, traces=[trace], vias=[via])
        copper = [{'type': 'trace', **trace.to_json()}, {'type': 'via', **via.to_json()}]
        check_replay(board, copper + [{'type': 'reset_routing'}] + copper)
        check_replay(board, copper + [{'type': 'ripup', 'net': 'VCC'}] + copper)
        for events in (copper + copper, copper[:1], copper + [{'type': 'ripup', 'net': 'VCC'}]):
            with self.assertRaisesRegex(ValueError, 'differ from exported board'):
                check_replay(board, events)

    def test_failure_never_publishes_manifest_or_edits_source(self):
        original = (DEMO_ROOT / 'index.json').read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'demos'
            with patch('tests.refresh_demos.kicad_cli', return_value='/bin/echo'), \
                    patch('tests.refresh_demos.ngspice_available', return_value=True), \
                    patch('tests.refresh_demos.refresh_one', side_effect=ValueError('DRC failure')):
                with self.assertRaisesRegex(ValueError, 'DRC failure'):
                    refresh_bundle(DEMO_ROOT, output, 'test')
                self.assertFalse((output / 'index.json').exists())
                with self.assertRaises(FileExistsError):
                    refresh_bundle(DEMO_ROOT, output, 'test')
                with self.assertRaisesRegex(ValueError, 'cannot replace the source'):
                    refresh_bundle(DEMO_ROOT, DEMO_ROOT, 'test')
        self.assertEqual((DEMO_ROOT / 'index.json').read_bytes(), original)

    def test_repaired_ground_requires_retry_event_to_clear_ui_failure(self):
        board = Board(10, 10)
        failure = {'type': 'route_fail', 'net': 'GND', 'reason': 'blocked stub'}
        with self.assertRaisesRegex(ValueError, 'stale routing failures'):
            check_replay(board, [failure])
        check_replay(board, [failure, {'type': 'route_begin', 'net': 'GND'}])
        board.nets = [Net('GND', [], 'gnd')]
        with self.assertRaisesRegex(ValueError, 'unrouted airwires'):
            check_replay(board, [])


if __name__ == '__main__':
    unittest.main()
