#!/usr/bin/env python3
"""Zaznamená **koncovou sekvenci originálu** krok po kroku → `build/gtraces/` (M7).

    PYTHONPATH=tools/vendor ./tools/traceending.py [--out build/gtraces]

Obdoba `traceobjects.py` / `traceconvoy.py` / `traceenemies.py`, jen se scénář
nepíše: **píše si ho hra sama**. Od chvíle, kdy Lasertron dojede na konec
silnice, si sekvence do `$8F14` zapisuje, co se ten průchod „zmáčklo", takže
záznam nemá vstup, který by se dal měnit – má jediný možný běh, a ten se
zapisuje, aby ho `matchending.js` mohl přehrát portem.

Zaznamenávají se dvě věci vedle sebe:

* **body scénáře** (`marks`) – na každé hranici mezi dvěma částmi sekvence se
  uloží snímek, počítadlo zón, ukazatel tabulky, počítadlo dohraných her
  a celá tabulka objektů. Hranice jsou adresy, na které se dá doběhnout
  (`highwaylib.Session.run_to`);
* **průchody** (`steps`) – dokud sekvence běží hlavní smyčkou, ukládá se každý
  průchod zvlášť, jako u ostatních záznamů. Kus scénáře (rozpad lodi a
  prodleva po něm) hlavní smyčkou neběží; tam se počítají **snímky** a je to
  v záznamu vidět (`loop: false`).

Navíc se ukládá **tabulka dat silnice** `$7B00`–`$89FF` před druhým průchodem
a po něm, protože právě ona je to, co druhý průchod mění.

Spouštět s `PYTHONPATH=tools/vendor` (vendorovaný SkoolKit, viz tools/README.md).
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402
import dumpending as D                                            # noqa: E402

SLOTS = 48
STEP_FRAMES = 20            # kolik snímků nejvýš čekat na další průchod


def entities(s):
    """Tabulka tak, jak je – i s `$FE`/`$FF`, aby se dal zapsat konec."""
    start = s.peek(D.TABLE_PTR) | (s.peek(D.TABLE_PTR + 1) << 8)
    tab = s.peek(start, SLOTS * D.ENTITY_SIZE)
    rows, end = [], SLOTS
    for i in range(SLOTS):
        e = tab[i*D.ENTITY_SIZE:(i+1)*D.ENTITY_SIZE]
        if e[0] == 0xFF:
            end = i
            break
        if e[0] == 0xFE:
            continue
        rows.append([i, e[0], e[1] | e[2] << 8, e[7], e[8], e[9],
                     e[6] << 8 | e[5], e[10]])
    return rows, end, start


def state(s):
    rows, end, start = entities(s)
    return {
        'frame': s.frame,
        'ents': rows,
        'end': end,
        'table': '$%04X' % start,
        'zone': s.peek(D.ZONE_COUNTER),
        'zoneCopy': s.peek(D.ZONE_COPY),
        'keys': s.peek(D.KEYS_READ),
        'passes': s.peek(D.PASS_COUNTER),
    }


def speeds(s):
    """Rychlosti všech záznamů tabulky dat silnice, po řadě."""
    raw = s.peek(D.MASTER, D.MASTER_END - D.MASTER)
    return [[raw[i + 6] << 8 | raw[i + 5], raw[i + 8]]
            for i in range(0, len(raw), D.ENTITY_SIZE)]


def record():
    """Dvě nahrávky téhož běhu, protože se navzájem ruší.

    Doběhnout na hranici části scénáře a doběhnout na další průchod hlavní
    smyčky se nedá naráz: zastavit se dá vždycky jen na jedné adrese, a kdo
    hledá hranici, prošvihne průchod. Nahrává se proto dvakrát od téhož
    snapshotu – jednou po hranicích, jednou po průchodech – a spojí se to přes
    číslo snímku, které je v obou.
    """
    D.ending_snapshot()

    # --- 1. hranice částí scénáře ---------------------------------------
    s = H.Session(D.SNAPSHOT)
    if s.run_to(0xA617, frames=6000) is None:
        raise SystemExit('sekvence se v snapshotu nespustila')
    start = state(s)
    marks, master_before, master_after = [], None, None
    for addr, name, note in D.MARKS[1:]:
        if s.run_to(addr, frames=6000) is None:
            raise SystemExit('scenar se zastavil pred $%04X (%s)' % (addr, name))
        if name == 'secondPass':
            master_before = speeds(s)
        st = state(s)
        st['mark'] = name
        st['note'] = note
        st['at'] = '$%04X' % addr
        marks.append(st)
        if name == 'secondPass':
            s.run_to(0xA848, frames=50)
            master_after = speeds(s)

    # --- 2. průchody hlavní smyčky --------------------------------------
    end_frame = marks[-1]['frame']
    p = H.Session(D.SNAPSHOT)
    p.run_to(0xA617, frames=6000)
    steps = []
    while p.frame < end_frame:
        before = p.frame
        if p.run_to(H.STEP_PC, frames=STEP_FRAMES) is None:
            # sekvence zrovna kreslí a do hlavní smyčky se nevrací; zapíše se,
            # kolik snímků to stálo, ať čas v záznamu pořád sedí
            steps.append({'frame': p.frame, 'loop': False,
                          'frames': p.frame - before})
            continue
        st = state(p)
        st['loop'] = True
        steps.append(st)

    return {
        'name': 'ending',
        'note': 'koncová sekvence a druhý průchod, originál v simulátoru',
        'source': 'tools/traceending.py, z build/ending.z80 (RZX záznam)',
        'start': start,
        'marks': marks,
        'steps': steps,
        'master': {'before': master_before, 'after': master_after,
                   'stride': D.ENTITY_SIZE,
                   'note': 'druh a rychlost každého ze 240 záznamů tabulky '
                           'dat silnice před druhým průchodem a po něm'},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'build/gtraces'))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    trace = record()
    path = os.path.join(args.out, 'ending.json')
    with open(path, 'w') as f:
        json.dump(trace, f, separators=(',', ':'))
    loop = sum(1 for st in trace['steps'] if st.get('loop'))
    changed = sum(1 for a, b in zip(trace['master']['before'],
                                    trace['master']['after']) if a != b)
    print('%s: %d bodů scénáře, %d kroků (%d průchodů smyčkou, %d snímků '
          'mimo ni), %d záznamů silnice zrychleno'
          % (os.path.relpath(path, H.ROOT), len(trace['marks']),
             len(trace['steps']), loop, len(trace['steps']) - loop, changed))
    with open(os.path.join(args.out, 'index.json'), 'w') as f:
        json.dump([{'name': 'ending', 'note': trace['note'],
                    'marks': len(trace['marks']), 'steps': len(trace['steps'])}],
                  f, indent=1)


if __name__ == '__main__':
    main()
