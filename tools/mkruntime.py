#!/usr/bin/env python3
"""Udělá obraz RAM **v podobě, v jaké hra skutečně běží**.

    PYTHONPATH=tools/vendor ./tools/mkruntime.py [--out build/highwayencounter-run.bin]

`tap2sna.py` uloží snapshot v okamžiku, kdy dojede kazeta – tedy dřív, než se
hra rozběhne. Pro extrakci dat (znaková sada, sprity, silnice) je potřeba RAM
běžící hry, ne kazetový obraz: u Underwurlde se ukázalo, že si hra po nahrání
celý svůj blok v paměti posune, a než se na to přišlo, byla disassembly o bajt
rozsypaná (`sources/docs/disasm_notes.md` §9 tamtéž). Tady se to proto rovnou
změří: skript vypíše, kolik bajtů RAM za běhu odpovídá kazetovému obrazu bez
posunu a s posunem ±1.

Hra se nastartuje simulací menu OPTIONS – `1` (KEYBOARD) a `7` (START GAME),
viz `tools/playtrace.py`.
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

from skoolkit.snapshot import Snapshot                          # noqa: E402
from skoolkit.simulator import Simulator                        # noqa: E402
from skoolkit.simutils import from_snapshot                     # noqa: E402
from skoolkit.trace import Tracer                               # noqa: E402
try:
    from skoolkit.csimulator import CSimulator
except ImportError:                                             # pragma: no cover
    CSimulator = None

# kam hra sáhne v paměti (kazetový blok, sources/tape/README.md: 39169 B od 23755)
BLOCK = (23755, 23755+39169)


def boot(snapshot_path, frames=900, shots=None):
    """Spustí hru, projde menu a nechá ji dojít do rozehrané hry."""
    snapshot = Snapshot.get(snapshot_path)
    if snapshot is None:
        raise SystemExit('nelze nacist snapshot %s' % snapshot_path)
    cls = CSimulator or Simulator
    simulator = from_snapshot(cls, snapshot, {}, {'ay': [None]*16},
                              {'fast_djnz': False, 'fast_ldir': False}, None)
    tracer = Tracer(simulator, snapshot.border, snapshot.out7ffd, snapshot.outfffd,
                    list(snapshot.ay), snapshot.outfe, True)
    simulator.set_tracer(tracer)
    saved = {}

    def draw(scr, frame, border, keyboard):
        for i in range(8):
            keyboard[i] = 0
        if 400 <= frame < 440:
            keyboard[3] |= 1        # '1' – OPTIONS: KEYBOARD
        if 500 <= frame < 540:
            keyboard[4] |= 1 << 3   # '7' – START GAME
        if shots and frame in shots:
            saved[frame] = bytes(scr)
        return frame < frames

    tracer.run(snapshot.pc, -1, 0, 0, True, draw, None, None, None, '$', '04X', '04X')
    return simulator, saved


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('snapshot', nargs='?',
                    default=os.path.join(HERE, '..', 'build/highwayencounter.z80'))
    ap.add_argument('--out', default=os.path.join(HERE, '..', 'build/highwayencounter-run.bin'))
    ap.add_argument('--tape-image', default=os.path.join(HERE, '..', 'build/highwayencounter.bin'))
    ap.add_argument('--frames', type=int, default=900)
    ap.add_argument('--screen', help='kam uložit .scr rozehrané hry')
    args = ap.parse_args()

    shots = (args.frames-1,) if args.screen else None
    simulator, saved = boot(args.snapshot, args.frames, shots)
    ram = bytes(simulator.memory[0x4000:])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'wb') as f:
        f.write(ram)
    print('%s: %d B (RAM $4000-$FFFF za behu hry)' % (args.out, len(ram)))

    if args.screen and saved:
        with open(args.screen, 'wb') as f:
            f.write(saved[args.frames-1])
        print('%s: obrazovka rozehrane hry (snimek %d)' % (args.screen, args.frames-1))

    if os.path.isfile(args.tape_image):
        tape = open(args.tape_image, 'rb').read()
        total = BLOCK[1]-BLOCK[0]
        for shift in (0, -1, 1):
            same = 0
            for a in range(*BLOCK):
                b = a+shift-0x4000
                if 0 <= b < len(tape) and ram[a-0x4000] == tape[b]:
                    same += 1
            print('  posun %+d: %d B z %d (%.1f %%)' % (shift, same, total, 100.0*same/total))


if __name__ == '__main__':
    main()
