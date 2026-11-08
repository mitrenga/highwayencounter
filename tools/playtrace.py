#!/usr/bin/env python3
"""Spustí hru v Z80 simulátoru, odsimuluje stisky kláves a uloží snímky obrazovky.

    PYTHONPATH=tools/vendor ./tools/playtrace.py [--frames N] [--out DIR] [--map FILE]

Klávesnice se adresuje po **půlřádcích** stejně jako na skutečném Spectru
(viz sources/docs/hw_notes.md §6). Skript kláves je dole v `SCRIPT`:
`(snímek_od, snímek_do, 'půlřádek', bit)`.

Snímky obrazovky se ukládají jako PNG přes `scr2png.py`.
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

from scr2png import scr_to_rgb, write_png                      # noqa: E402
from skoolkit.snapshot import Snapshot                          # noqa: E402
from skoolkit.simulator import Simulator                        # noqa: E402
from skoolkit.simutils import from_snapshot                     # noqa: E402
from skoolkit.trace import Tracer                               # noqa: E402
try:
    from skoolkit.csimulator import CSimulator
except ImportError:                                             # pragma: no cover
    CSimulator = None

# klávesnice po půlřádcích – jeden zdroj pro všechny nástroje
from highwaylib import ROWS, KEYS                               # noqa: E402

# (od snímku, do snímku, klávesa) – snímky se počítají od začátku běhu
SCRIPT = [
    (400, 440, '1'),    # OPTIONS: 1 KEYBOARD
    (500, 540, '7'),    # 7 START GAME
]
# ve kterých snímcích uložit obrazovku
SHOTS = (450, 560, 620, 700, 900, 1200, 1600, 2200)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('snapshot', nargs='?', default=os.path.join(HERE, '..', 'build/highwayencounter.z80'))
    ap.add_argument('--frames', type=int, default=1300, help='kolik snímků odsimulovat')
    ap.add_argument('--out', default=os.path.join(HERE, '..', 'build'), help='kam ukládat PNG')
    ap.add_argument('--map', help='soubor pro mapu pokrytí (adresy provedených instrukcí)')
    args = ap.parse_args()

    snapshot = Snapshot.get(args.snapshot)
    if snapshot is None:
        raise SystemExit('nelze nacist snapshot %s' % args.snapshot)
    cls = CSimulator or Simulator
    simulator = from_snapshot(cls, snapshot, {}, {'ay': [None] * 16},
                              {'fast_djnz': False, 'fast_ldir': False}, None)
    tracer = Tracer(simulator, snapshot.border, snapshot.out7ffd, snapshot.outfffd,
                    list(snapshot.ay), snapshot.outfe, True)
    simulator.set_tracer(tracer)

    os.makedirs(args.out, exist_ok=True)
    saved = []

    def draw(scr, frame, border, keyboard):
        for i in range(8):
            keyboard[i] = 0
        for start, end, key in SCRIPT:
            if start <= frame < end:
                row, bit = KEYS[key]
                keyboard[ROWS[row]] |= 1 << bit
        if frame in SHOTS:
            path = os.path.join(args.out, 'frame%05d.png' % frame)
            write_png(path, scr_to_rgb(bytes(scr)), 256)
            with open(path[:-4] + '.scr', 'wb') as f:
                f.write(bytes(scr))
            saved.append(path)
        return frame < args.frames

    exec_map = set() if args.map else None
    tracer.run(snapshot.pc, -1, 0, 0, True, draw, exec_map, None, None, '$', '04X', '04X')
    for p in saved:
        print('ulozeno', p)
    if exec_map is not None:
        with open(args.map, 'w') as f:
            for a in sorted(exec_map):
                f.write('$%04X\n' % a)
        print('mapa pokryti: %s (%d adres)' % (args.map, len(exec_map)))


if __name__ == '__main__':
    main()
