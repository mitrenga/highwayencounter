#!/usr/bin/env python3
"""Kdo v originálu **zapisuje do hrací plochy** – hledání kreslicí rutiny (M0/M2).

Sprity se v paměti hledáním osmibajtových sloupců nenašly (`disasm_notes.md` §8)
a znaková sada se v M7 našla až přes rutinu, která ji skládá (§2). Tenhle
nástroj dělá totéž pro grafiku: nechá běžet **originál** a u každého zápisu do
videopaměti hrací plochy (řádky 0–18) si zapíše, **která instrukce** ho udělala
a jaká adresa byla přitom na vrcholu zásobníku (tedy odkud je rutina volaná).

Měří se přes čistě pythonový `Simulator` SkoolKitu s podstrčenou pamětí, která
zápisy loguje; `CSimulator` (v C) se kvůli tomu vypíná, takže je to pomalejší,
ale krokuje se jen několik průchodů hlavní smyčkou.

    PYTHONPATH=tools/vendor ./tools/tracedraw.py [--steps 3] [--top 40]

Vypíše zapisující instrukce podle počtu zápisů, jejich volající a rozsah
adres, do kterých sahají – bitmapa zvlášť, atributy zvlášť.
"""
import argparse, collections, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib                                                # noqa: E402
from skoolkit.simulator import Simulator                         # noqa: E402
from skoolkit.simutils import PC, SP                             # noqa: E402

ROOT = highwaylib.ROOT
# hrací plocha: bitmapa znakových řádků 0-18 a jejich atributy
BITMAP_LO, BITMAP_HI = 0x4000, 0x57FF
ATTR_LO = 0x5800
ATTR_HI = ATTR_LO + highwaylib.PLAY_ROWS*32 - 1


class WatchedMemory(list):
    """Paměť simulátoru, která loguje zápisy do zvoleného rozsahu.

    Opcody SkoolKitu si `self.memory` zapamatují v uzávěrech při
    `create_opcodes()`, takže tuhle paměť je nutné podstrčit **před** tím a
    opcody pak postavit znovu.
    """

    def __init__(self, values, registers, lo=BITMAP_LO, hi=ATTR_HI):
        super().__init__(values)
        self.registers = registers
        self.lo, self.hi = lo, hi
        self.log = []
        self.enabled = True

    def __setitem__(self, addr, value):
        if self.enabled and type(addr) is int and self.lo <= addr <= self.hi:
            sp = self.registers[SP]
            self.log.append((self.registers[PC], addr,
                             list.__getitem__(self, sp)
                             + 256*list.__getitem__(self, (sp + 1) % 65536)))
        list.__setitem__(self, addr, value)


def watched_session(cache=highwaylib.CACHE, lo=BITMAP_LO, hi=ATTR_HI):
    """Rozehraná hra z cache, ale v pythonovém simulátoru s logující pamětí."""
    saved, highwaylib.CSimulator = highwaylib.CSimulator, None
    try:
        s = highwaylib.Session(cache)
    finally:
        highwaylib.CSimulator = saved
    if not isinstance(s.simulator, Simulator):
        raise SystemExit('nepodarilo se vynutit pythonovy Simulator')
    memory = WatchedMemory(s.simulator.memory, s.simulator.registers, lo, hi)
    s.simulator.memory = memory
    s.simulator.create_opcodes()          # uzávěry opcodů na novou paměť
    s.simulator.set_tracer(s.tracer)
    s.memory = memory
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--steps', type=int, default=3, help='kolik průchodů hlavní smyčkou')
    ap.add_argument('--top', type=int, default=40, help='kolik zapisujících instrukcí vypsat')
    ap.add_argument('--keys', default='', help='držené klávesy, např. 1 nebo 1,P')
    ap.add_argument('--range', help='jiný rozsah adres než videopaměť, např. E900-FBFF')
    args = ap.parse_args()

    keys = tuple(k.strip().upper() for k in args.keys.split(',') if k.strip())
    ranges = (('BITMAPA', BITMAP_LO, BITMAP_HI), ('ATRIBUTY', ATTR_LO, ATTR_HI))
    if args.range:
        lo, hi = (int(v, 16) for v in args.range.split('-'))
        ranges = (('$%04X-$%04X' % (lo, hi), lo, hi),)
    s = watched_session(lo=ranges[0][1], hi=ranges[-1][2])
    print('rozehrana hra: snimek %d, PC $%04X' % (s.frame, s.simulator.registers[PC]))

    s.memory.log.clear()
    for i in range(args.steps):
        t = s.step(keys)
        print('  prubeh %d: %d T-stavu, zapisu ve sledovanem rozsahu %d'
              % (i + 1, t, len(s.memory.log)))

    log = s.memory.log
    if not log:
        print('zadny zapis do hraci plochy – hra pravdepodobne nekresli')
        return

    for name, lo, hi in ranges:
        rows = [(pc, addr, ret) for pc, addr, ret in log if lo <= addr <= hi]
        print('\n=== %s ($%04X-$%04X): %d zapisu ===' % (name, lo, hi, len(rows)))
        by_pc = collections.defaultdict(lambda: [0, set(), collections.Counter()])
        for pc, addr, ret in rows:
            entry = by_pc[pc]
            entry[0] += 1
            entry[1].add(addr)
            entry[2][ret] += 1
        print('%-8s %8s  %-17s  %s' % ('instrukce', 'zapisu', 'rozsah adres', 'volajici (top zasobniku)'))
        for pc, (count, addrs, rets) in sorted(by_pc.items(), key=lambda kv: -kv[1][0])[:args.top]:
            callers = ' '.join('$%04X(%d)' % (r, n) for r, n in rets.most_common(3))
            print('$%04X    %8d  $%04X-$%04X %4d  %s'
                  % (pc, count, min(addrs), max(addrs), len(addrs), callers))


if __name__ == '__main__':
    main()
