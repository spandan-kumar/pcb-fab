"""Rebuild bundled demos from saved netlists, with no agent or API calls.

Usage: uv run python -m tests.refresh_demos --output /tmp/etch-demos-new
Output must not exist. Nothing in the source bundle is modified. A manifest is
written only after every demo passes; copy the staged bundle after browser QA.
"""
import argparse
from collections import Counter
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from unittest.mock import patch
import uuid
import zipfile

from etch.analysis import ngspice_available, power_rails, spice_rail_step, thermal
from etch.catalog import CATALOG
from etch.drc import run_drc
from etch.exporter import export_all, netlist_json
from etch.kicad_export import kicad_cli
from etch.model import Board, Component, Net, antenna_keepouts
from etch.router import Router

DEMO_ROOT = Path(__file__).resolve().parents[2] / 'frontend/public/demo'


def require(condition, message):
    if not condition:
        raise ValueError(message)


@contextmanager
def local_only():
    """Fail closed on Python networking and non-EDA child processes."""
    allowed = {str(Path(p).resolve()) for p in (kicad_cli(), shutil.which('ngspice')) if p}
    popen = subprocess.Popen

    def local_process(args, *pos, **kwargs):
        require(isinstance(args, (list, tuple)) and args and not kwargs.get('shell')
                and not kwargs.get('executable'), 'Offline refresh disallows shell commands')
        executable = shutil.which(str(args[0]))
        require(executable and str(Path(executable).resolve()) in allowed,
                f'Offline refresh disallows process: {args[0]}')
        return popen(args, *pos, **kwargs)

    with ExitStack() as stack:
        for name in ('socket.socket.connect', 'socket.socket.connect_ex',
                     'socket.create_connection', 'socket.getaddrinfo'):
            stack.enter_context(patch(name, side_effect=RuntimeError('Offline refresh disallows networking')))
        stack.enter_context(patch('subprocess.Popen', side_effect=local_process))
        yield


def load_saved(folder, demo):
    """Preserve the package's full-precision placements, not rounded UI frames."""
    events = json.loads((folder / 'events.json').read_text())
    artifact = next(e for e in events if e['type'] == 'artifacts')
    package = folder / Path(artifact['zip_url']).name
    with zipfile.ZipFile(package) as archive:
        design = json.loads(archive.read('design.json'))
        netlist = json.loads(archive.read('netlist.json'))
        raw = archive.read('agent_output.md')
    require(design['name'] == netlist['name'] == demo['name'], 'Saved design names disagree')
    config = {k: v for k, v in design['board'].items() if k != 'layers'}
    require(design['board']['layers'] == 2, 'Only two-layer demos are supported')
    board = Board(name=design['name'], **config)
    snapshot = next(e['board'] for e in events if e['type'] == 'board')
    positions = next(e['positions'] for e in events if e['type'] == 'placement_final')
    board.texts = deepcopy(snapshot['texts'])
    for saved in netlist['components']:
        part = CATALOG[saved['part']]
        ref = saved['ref']
        require(part.footprint.name == saved['footprint']
                and part.footprint.to_json() == snapshot['footprints'][ref], f'{ref}: footprint changed')
        require([round(saved['x'], 3), round(saved['y'], 3), saved['rot']] == positions[ref],
                f'{ref}: package and replay placements disagree')
        board.components.append(Component(ref, part, saved['value'], saved['purpose'],
                                          saved['x'], saved['y'], saved['rot']))
    board.nets = [Net(**{**n, 'pins': [tuple(p.rsplit('.', 1)) for p in n['pins']]}) for n in netlist['nets']]
    require(json.loads(netlist_json(board)) == netlist, 'Reconstructed netlist differs from saved package')
    require(set(positions) == {c.ref for c in board.components}, 'Missing saved components')
    require(board.to_json() == snapshot, 'Saved board geometry or text differs from the package')
    return board, design, events, raw, hashlib.sha256(package.read_bytes()).hexdigest()


def check_replay(board, events):
    """Apply the frontend's copper event semantics, including resets and rip-ups."""
    traces, vias = [], []
    failed, routed = set(), set()
    for event in events:
        kind = event['type']
        if kind in ('board', 'reset_routing'):
            traces, vias = [], []
            failed, routed = set(), set()
        elif kind == 'ripup':
            traces = [t for t in traces if t['net'] != event['net']]
            vias = [v for v in vias if v['net'] != event['net']]
            failed.discard(event['net'])
            routed.discard(event['net'])
        elif kind == 'route_begin':
            failed.discard(event['net'])
            routed.add(event['net'])
        elif kind == 'route_fail':
            failed.add(event['net'])
            routed.discard(event['net'])
        elif kind == 'trace':
            traces.append({k: event[k] for k in ('net', 'layer', 'width', 'points')})
            routed.add(event['net'])
        elif kind == 'via':
            vias.append({k: event[k] for k in ('net', 'x', 'y', 'drill', 'diameter')})
    def counts(items):
        return Counter(json.dumps(item, sort_keys=True) for item in items)
    require(counts(traces) == counts(t.to_json() for t in board.traces), 'Replay traces differ from exported board')
    require(counts(vias) == counts(v.to_json() for v in board.vias), 'Replay vias differ from exported board')
    require(not failed, f'Replay retains stale routing failures: {sorted(failed)}')
    expected = {n.name for n in board.nets if len(n.pins) >= 2 or n.cls == 'gnd'}
    require(expected <= routed, f'Replay retains unrouted airwires: {sorted(expected - routed)}')


def refresh_one(source, destination, demo, revision):
    board, design, original, raw, source_hash = load_saved(source / demo['run_id'], demo)
    run_id = uuid.uuid4().hex[:10]  # New paths also invalidate cached PNGs and ZIPs.
    engine_files = sorted((Path(__file__).resolve().parents[1] / 'etch').glob('*.py'))
    engine_hash = hashlib.sha256(b''.join(p.name.encode() + b'\0' + p.read_bytes() for p in engine_files)).hexdigest()
    provenance = {'mode': 'offline-refresh', 'source_run_id': demo['run_id'],
                  'source_package_sha256': source_hash, 'engine_base_commit': revision, 'engine_sources_sha256': engine_hash,
                  'refreshed_at': datetime.now(timezone.utc).isoformat(), 'agent_calls': 0,
                  'preserved': ['design', 'components', 'netlist', 'placements'],
                  'timing': 'Archived pre-routing timeline followed by measured local rebuild time.'}
    events = []
    for old in original:
        if old['type'] == 'status' and old['stage'] == 'routing':
            break
        event = deepcopy(old)
        if event['type'] == 'run':
            event.update(run_id=run_id, backend='offline-refresh', kicad=True, ngspice=ngspice_available(),
                         refresh=provenance)
        elif event['type'] == 'status' and event['state'] == 'start' and event['stage'] in ('architect', 'schematic', 'placement'):
            event['message'] = 'Replaying saved design / placement — no agent call'
        events.append(event)
    events.insert(1, {'type': 'thought', 't': 0, 'text':
                     '**Offline refresh.** Design and placement below are archived. '
                     'Copper, DRC, simulations and exports were rebuilt locally with the current engine; no model was called.\n\n'})
    require(events and events[-1]['type'] == 'status' and events[-1]['stage'] == 'placement',
            'Saved recording has no complete pre-routing timeline')
    previous = 0
    for seq, event in enumerate(events, 1):
        previous = max(previous, event.get('t', previous))
        event.update(seq=seq, t=previous)
    offset, started = previous + 0.6, time.monotonic()

    def emit(event):
        events.append({**event, 'seq': len(events) + 1, 't': round(offset + time.monotonic() - started, 3)})

    def status(stage, state, message=''):
        emit({'type': 'status', 'stage': stage, 'state': state, 'message': message})
        print(f'{board.name}: {stage} {state} {message}', flush=True)

    status('routing', 'start', 'Routing saved placement locally')
    result = Router(board, on_event=emit, time_budget=200).route_all()
    require(not result['failed'] and not result['orphan_gnd'] and result['routed'] == result['total'],
            f'{board.name}: incomplete routing: {result}')
    check_replay(board, events)
    status('routing', 'done', f"{result['length_mm']} mm copper, {result['vias']} vias")
    status('drc', 'start')
    drc = run_drc(board, result['failed'], result['orphan_gnd'])
    require(drc['passed'] and drc['errors'] == drc['warnings'] == 0, f'{board.name}: ETCH DRC failed: {drc}')
    emit({'type': 'drc', **drc})
    status('drc', 'done', '0 errors, 0 warnings')
    status('thermal', 'start')
    therm = thermal(board, emit)
    status('thermal', 'done', f"Hotspot {therm['max_c']} °C")
    status('power', 'start')
    rails = power_rails(board)
    require(all(r['width_ok'] and r['drop_ok'] for r in rails), f'{board.name}: power checks failed: {rails}')
    emit({'type': 'power', 'rails': rails})
    spice = spice_rail_step(board)
    require(spice is not None, f'{board.name}: ngspice simulation failed')
    emit(spice)
    status('power', 'done', f'{len(rails)} rails checked; ngspice transient complete')
    stats = {'components': sum(c.footprint.style != 'hole' for c in board.components), 'nets': len(board.nets),
             'traces': len(board.traces), 'vias': len(board.vias), 'total_trace_mm': result['length_mm'],
             'routed_pct': 100.0, 'drc_errors': 0, 'ripups': result['ripups'], 'power_width_warnings': 0}
    status('export', 'start', 'Exporting and checking KiCad, Gerbers and render')
    with tempfile.TemporaryDirectory(prefix='etch-demo-export-') as work:
        work = Path(work)
        (work / 'agent_output.md').write_bytes(raw)
        (work / 'refresh.json').write_text(json.dumps(provenance, indent=2) + '\n')
        exported = export_all(board, design, drc, stats, str(work), antenna_keepouts(board), True)
        report = exported['kicad']
        require(report.get('available') and report.get('drc_passed')
                and report.get('violations') == report.get('warnings') == report.get('unconnected') == 0,
                f'{board.name}: KiCad DRC failed: {report}')
        require(report.get('render') and (work / 'render-top.png').is_file(), 'Missing KiCad render')
        require(any((work / 'kicad/gerbers').glob('*.drl')), 'Missing KiCad drill export')
        for name in (exported['zip'], exported['gerber_zip']):
            with zipfile.ZipFile(work / name) as archive:
                require(archive.testzip() is None and archive.namelist(), f'Invalid archive: {name}')
        # The UI needs the report summary, not the build machine's temporary path.
        report = {k: v for k, v in report.items() if k != 'report'}
        emit({'type': 'artifacts', 'run_id': run_id, 'files': exported['files'], 'kicad': report,
              'zip_url': f"/demo/{run_id}/{exported['zip']}",
              'gerber_zip_url': f"/demo/{run_id}/{exported['gerber_zip']}",
              'render_url': f'/demo/{run_id}/render-top.png'})
        status('export', 'done', 'KiCad DRC PASS: 0 errors, 0 warnings, 0 unconnected')
        stats.update(elapsed_s=round(offset + time.monotonic() - started, 1), kicad_drc_passed=True)
        emit({'type': 'done', 'stats': stats})
        target = destination / run_id
        target.mkdir()
        for name in (exported['zip'], exported['gerber_zip'], 'render-top.png'):
            shutil.copy2(work / name, target / name)
        (target / 'events.json').write_text(json.dumps(events, separators=(',', ':')) + '\n')
    return {**demo, 'run_id': run_id, 'stats': stats, 'refresh': provenance}


def refresh_bundle(source, destination, revision):
    require(kicad_cli() and ngspice_available(), 'KiCad and ngspice are required; nothing was changed')
    demos = json.loads((source / 'index.json').read_text())
    require(destination.resolve() != source.resolve(), 'Output cannot replace the source bundle')
    destination.mkdir(parents=True, exist_ok=False)
    with local_only():
        rebuilt = [refresh_one(source, destination, demo, revision) for demo in demos]
    # A failed run leaves no usable manifest and never edits the source bundle.
    (destination / 'index.json').write_text(json.dumps(rebuilt, indent=2) + '\n')
    return rebuilt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEMO_ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=DEMO_ROOT.parents[2], text=True).strip()
    rebuilt = refresh_bundle(args.source, args.output, revision)
    print(json.dumps({'output': str(args.output), 'demos': [d['name'] for d in rebuilt], 'agent_calls': 0}), flush=True)


if __name__ == '__main__':
    main()
