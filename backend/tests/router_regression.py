"""Fixed-placement router benchmarks, independent of LLMs and ignored runs/.

Usage: uv run python -m tests.router_regression UNO328C C3BEACON --kicad
Omit board names to run all six examples, including the dense motor-driver layout.
Exit status is nonzero if any selected board is incomplete or fails DRC.
"""
import argparse
import json
import tempfile
import time
from pathlib import Path

from etch.catalog import CATALOG
from etch.drc import run_drc
from etch.kicad_export import run_kicad_drc, write_kicad_pcb, write_kicad_pro
from etch.model import Board, Component, Net
from etch.pipeline import _keepouts
from etch.power_routing import width_summary
from etch.router import Router


def load_board(name):
    fixtures = json.loads((Path(__file__).parent / 'fixtures/router_boards.json').read_text())
    data = fixtures[name]
    board = Board(**data['board'])
    for c in data['components']:
        x, y, rot = c['position']
        board.components.append(Component(c['ref'], CATALOG[c['part']], c['value'], x=x, y=y, rot=rot))
    board.nets = [Net(**{**n, 'pins': [tuple(p) for p in n['pins']]}) for n in data['nets']]
    return board


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('boards', nargs='*')
    parser.add_argument('--budget', type=float, default=200)
    parser.add_argument('--grid', type=float, help='Force one grid; disables automatic refinement')
    parser.add_argument('--kicad', action='store_true', help='Require an independent KiCad DRC/connectivity check')
    parser.add_argument('--strict-kicad', action='store_true', help='Require KiCad with zero errors, warnings and unconnected items')
    parser.add_argument('--strict-power', action='store_true', help='Also fail on unmet power-width targets')
    args = parser.parse_args()
    names = args.boards or list(json.loads((Path(__file__).parent / 'fixtures/router_boards.json').read_text()))
    failed = False
    for name in names:
        board = load_board(name)
        started = time.monotonic()
        result = Router(board, time_budget=args.budget, grid_pitch=args.grid).route_all()
        drc = run_drc(board, result['failed'], result['orphan_gnd'])
        report = {'board': name, 'seconds': round(time.monotonic() - started, 2),
                  **result, 'drc_errors': drc['errors'], 'drc_warnings': drc['warnings'],
                  'power_widths': [{'net': n.name, **width_summary(board, n)} for n in board.nets if n.cls == 'power']}
        passed = not result['failed'] and not result['orphan_gnd'] and drc['passed']
        if args.strict_power:
            passed = passed and all(p['width_ok'] for p in report['power_widths'])
        if args.kicad or args.strict_kicad:
            # Keep files/reports available for inspection when a board fails.
            directory = Path(tempfile.mkdtemp(prefix='etch-router-regression-'))
            pcb = directory / f'{name}.kicad_pcb'
            pcb.write_text(write_kicad_pcb(board, _keepouts(board)))
            pcb.with_suffix('.kicad_pro').write_text(write_kicad_pro(board))
            kicad = run_kicad_drc(str(pcb)) or {'available': False}
            report.update(kicad=kicad, artifacts=str(directory))
            passed = passed and kicad.get('available', False) and kicad.get('drc_passed', False)
            if args.strict_kicad:
                passed = passed and kicad.get('warnings') == 0
        report['passed'] = passed
        failed |= not passed
        print(json.dumps(report), flush=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
