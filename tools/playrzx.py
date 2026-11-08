#!/usr/bin/env python3
"""Přehrání **RZX záznamu** originálu s krokováním a snímáním paměti (M7).

    PYTHONPATH=tools/vendor ./tools/playrzx.py --timeline
    PYTHONPATH=tools/vendor ./tools/playrzx.py --scr build/ending --from 77800 --to 79900
    PYTHONPATH=tools/vendor ./tools/playrzx.py --dump build/ending.z80 --at 77700

`highwaylib.py` umí hru **nabootovat a hrát ji sám** – na M3 až M6 to stačilo,
protože všechno, co se měřilo, se dá vyvolat naskriptovanými klávesami z první
zóny. M7 ne: koncová sekvence začne teprve tehdy, když **Lasertron dojede na
konec silnice**, a to je celá dohraná hra. Na to je v `sources/tape/highway.rzx`
záznam skutečného hráče, který hru dohrál – 80 385 snímků, 26 minut, a na jeho
konci je koncová sekvence i **začátek druhého průchodu**.

RZX je záznam **vstupů**, ne obrazu: v simulátoru běží tentýž kód hry a čte
tytéž hodnoty z portů, takže výsledek je bit po bitu tentýž běh, jaký hráč
odehrál. Přehrání celého záznamu trvá kolem sedmi sekund, takže se nic
necachuje – kromě snapshotu, kterým se dá do koncové sekvence skočit
(`--dump`), a ten pak krokuje `highwaylib.Session` jako každý jiný běh.

Ověření, že záznam a naše kazeta jsou táž edice: adresy stavu hry z
`disasm_notes.md` §7 v záznamu sedí (počítadlo zón na `$8F00` jde 1…31,
světová souřadnice na `$8F05` roste o 176 na zónu) – `--timeline` to vypíše.

Spouštět s `PYTHONPATH=tools/vendor` (vendorovaný SkoolKit, viz tools/README.md).
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

from skoolkit import rzxplay                                      # noqa: E402
from skoolkit.simutils import get_state, PC                       # noqa: E402
from skoolkit.snapshot import write_snapshot                      # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
RZX = os.path.join(ROOT, 'sources/tape/highway.rzx')

# Stav hry (disasm_notes.md §7) – čte se i tady, ať se pozná, že je to táž hra.
ZONE_COUNTER = 0x8F00
WORLD = 0x8F05


class _Options:
    """To, co `rzxplay.process_block` čeká od argparse. Nic z toho nepoužíváme
    jinak než přes tenhle modul, takže je to schválně na jednom místě."""
    force = True        # kazetový snapshot v záznamu je 48K, kontrolu nepotřebuje
    cmio = False        # přesné časování ULA k ničemu není a stojí čas
    python = False      # když je přeložený CSimulator, ať se použije
    quiet = True
    map = None
    trace = None
    screen = False
    snapshot = None
    dump = None
    flags = '0'
    scale = 1
    fps = 50

    def __init__(self, stop=0):
        self.stop = stop


class Playback:
    """Jedno přehrání záznamu. `watch(pb, frame)` se volá po každém snímku;
    když vrátí False, přehrávání skončí (pokračovat se v něm už nedá – RZX se
    přehrává jedním tahem, na skoky je `--dump` a `highwaylib.Session`)."""

    def __init__(self, path=RZX):
        self.path = path
        self.blocks = rzxplay.parse_rzx(path)
        self.context = rzxplay.RZXContext(self)
        self.context.total_frames = sum(
            len(b.obj.frames) for b in self.blocks
            if isinstance(b.obj, rzxplay.InputRecording))
        self.frame = 0
        self._watch = None
        self._scr = None

    # --- rozhraní, které si `rzxplay` vyzvedne jako `context.screen` -------
    def draw(self, scr, frame, border):
        self.frame = frame
        self._scr = scr
        if self._watch is not None:
            return self._watch(self, frame) is not False
        return True

    # --- běh --------------------------------------------------------------
    def run(self, watch=None, stop=0):
        self._watch = watch
        options = _Options(stop)
        blocks = list(self.blocks)
        while blocks:
            rzxplay.process_block(blocks.pop(0).obj, options, 0, self.context)
            if self.context.stop:
                break
        return self.frame

    @property
    def total_frames(self):
        return self.context.total_frames

    # --- čtení ------------------------------------------------------------
    @property
    def memory(self):
        return self.context.simulator.memory

    def peek(self, addr, n=None):
        m = self.memory
        if n is None:
            return m[addr]
        return bytes(m[addr:addr + n])

    def word(self, addr):
        m = self.memory
        return m[addr] | (m[addr + 1] << 8)

    def screen(self):
        return bytes(self.memory[0x4000:0x5B00])

    def ram(self):
        return bytes(self.memory[0x4000:])

    def pc(self):
        return self.context.simulator.registers[PC]

    def save(self, path):
        """Snapshot z právě dosaženého snímku – odsud se dá pokračovat
        `highwaylib.Session(path)`, tedy krokovat po krocích herní smyčky."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        ram, registers, state, machine = get_state(self.context.simulator)
        write_snapshot(path, ram, registers, state, machine)
        return path


def snapshot_at(frame, path, rzx=RZX):
    """Přehraje záznam do `frame` a uloží snapshot. Vrátí `Playback`."""
    pb = Playback(rzx)

    def watch(p, f):
        return f < frame

    pb.run(watch=watch)
    pb.save(path)
    return pb


def timeline(rzx=RZX, watch_addrs=(ZONE_COUNTER,)):
    """Seznam `(snímek, hodnoty)` pro každou změnu sledovaných bajtů."""
    out = []
    state = [None]

    def w(pb, frame):
        cur = tuple(pb.peek(a) for a in watch_addrs) + (pb.word(WORLD),)
        if cur != state[0]:
            out.append((frame, cur))
            state[0] = cur
        return True

    Playback(rzx).run(watch=w)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rzx', default=RZX, help='záznam (default sources/tape/highway.rzx)')
    ap.add_argument('--timeline', action='store_true',
                    help='vypsat každou změnu počítadla zón a světové souřadnice')
    ap.add_argument('--scr', metavar='DIR', help='ukládat obrazovky do adresáře')
    ap.add_argument('--from', dest='start', type=int, default=0, help='od snímku')
    ap.add_argument('--to', dest='end', type=int, default=0, help='do snímku (0 = do konce)')
    ap.add_argument('--every', type=int, default=25, help='jak často ukládat obrazovku')
    ap.add_argument('--dump', metavar='FILE', help='uložit snapshot (.z80/.szx)')
    ap.add_argument('--at', type=int, default=0, help='ve kterém snímku uložit snapshot')
    args = ap.parse_args()

    if args.dump:
        pb = snapshot_at(args.at, args.dump, args.rzx)
        print('%s: snimek %d, PC $%04X, zona %d'
              % (os.path.relpath(args.dump, ROOT), pb.frame, pb.pc(),
                 pb.peek(ZONE_COUNTER)))
        return

    if args.timeline:
        for frame, (zone, world) in timeline(args.rzx):
            print('f=%6d zona=%3d svet=%5d' % (frame, zone, world))
        return

    if args.scr:
        os.makedirs(args.scr, exist_ok=True)
        end = args.end or 1 << 30
        saved = [0]

        def w(pb, frame):
            if args.start <= frame <= end and frame % args.every == 0:
                with open(os.path.join(args.scr, 'f%05d.scr' % frame), 'wb') as f:
                    f.write(pb.screen())
                saved[0] += 1
            return frame <= end

        pb = Playback(args.rzx)
        pb.run(watch=w)
        print('%s: %d obrazovek' % (os.path.relpath(args.scr, ROOT), saved[0]))
        return

    pb = Playback(args.rzx)
    pb.run(stop=args.end)
    print('prehrano %d snimku z %d, PC $%04X'
          % (pb.frame, pb.total_frames, pb.pc()))


if __name__ == '__main__':
    main()
