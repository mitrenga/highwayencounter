#!/usr/bin/env python3
"""Zaznamená **originál krok po kroku** při skriptovaných klávesách (M3).

    PYTHONPATH=tools/vendor ./tools/tracephysics.py [--out build/traces] [--only jmeno]

Referenční záznamy pro `tools/matchphysics.js`: pro každý scénář se nabootuje
rozehraná hra, drží se předepsané klávesy a po **každém průchodu hlavní smyčkou**
(ne po snímku – `highwaylib.Session.step`, `disasm_notes.md` §11) se uloží stav
řízeného Vortona: pozice, směr, rychlost, fáze animace, posuvný registr plynu
a to, co hra ten krok přečetla z klávesnice.

Vstup se do záznamu bere **tak, jak ho přečetla hra** (`$8F14`), ne jak ho psal
scénář – tím z porovnání vypadne otázka, ve kterém snímku se klávesa snímá.

Krok, ve kterém se Vorton nehnul, ačkoli měl rychlost, je označený `blocked`:
tam do něj něco vrazilo. Okraj silnice port pozná sám (`data/physics.json`),
předměty na silnici ne – ty jsou M2/M4, takže `matchphysics.js` u nich bere
odpověď ze záznamu a hlásí, kolikrát ji potřeboval.
"""
import argparse, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

# scénář = (jméno, popis, počet kroků, funkce krok -> klávesy)
SCENARIOS = [
    ('accelerate', 'plný plyn z klidu rovně po silnici', 40,
     lambda i: ('1',)),
    ('coast', 'plyn na 20 kroků, pak nic – hra sama nebrzdí', 60,
     lambda i: ('1',) if i < 20 else ()),
    ('brake', 'plyn na 20 kroků, pak Q až do zastavení', 50,
     lambda i: ('1',) if i < 20 else ('Q',)),
    ('stopgo', 'rozjet, zabrzdit do klidu, znovu rozjet', 70,
     lambda i: ('1',) if (i < 20 or i >= 45) else ('Q',)),
    ('tapthrottle', 'plyn ťukaný obden – časovač plynu běží dál', 30,
     lambda i: ('1',) if i % 2 == 0 else ()),
    ('turnleft', 'O z klidu, víc než celá otáčka', 40,
     lambda i: ('O',)),
    ('turnright', 'P z klidu, víc než celá otáčka', 40,
     lambda i: ('P',)),
    ('bothturn', 'O a P zároveň – nesmí se otočit', 20,
     lambda i: ('O', 'P')),
    ('boththrottle', '1 a Q zároveň – brzda vyhraje nad plynem', 40,
     lambda i: ('1',) if i < 16 else ('1', 'Q')),
    ('firing', 'plyn a zatáčení s drženou střelbou – nesmí do fyziky mluvit', 40,
     lambda i: ('1', 'SPACE') if i < 20 else ('1', 'SPACE', 'P')),
    ('wallright', 'plyn a P až na pravý okraj silnice', 45,
     lambda i: ('1',) if i < 6 else ('1', 'P') if i < 10 else ('1',)),
    ('wallleft', 'plyn a O až na levý okraj silnice', 45,
     lambda i: ('1',) if i < 6 else ('1', 'O') if i < 10 else ('1',)),
    ('circle', 'kroužení plnou rychlostí', 60,
     lambda i: ('1', 'P') if i >= 12 else ('1',)),
    ('zigzag', 'střídavé zatáčky s plynem i brzdou', 80,
     lambda i: (('1',) if i % 20 < 12 else ('Q',))
               + (('O',) if i % 40 < 20 else ('P',)) if i >= 8 else ('1',)),
]


def random_scenario(seed, steps=600):
    """Pseudonáhodné mačkání – to, co scénáře psané rukou nenapadne.

    Klávesy se generují dopředu z pevného semínka, takže je běh opakovatelný;
    do záznamu se stejně ukládá to, co ten krok přečetla hra.
    """
    rnd = random.Random(seed)
    keys, held = [], ()
    for i in range(steps):
        if rnd.random() < 0.25:
            held = tuple(k for k in ('1', 'Q', 'O', 'P', 'SPACE')
                         if rnd.random() < 0.4)
        keys.append(held)
    return keys.__getitem__


for seed in range(16):
    SCENARIOS.append(('random%d' % seed,
                      'pseudonáhodné mačkání včetně střelby, semínko %d' % seed,
                      600, random_scenario(seed)))


def record(name, desc, steps, keyfn):
    s = H.gameplay()
    start = s.player()
    rows = []
    prev = (start['x'], start['y'])
    tstates = []
    for i in range(steps):
        keys = tuple(keyfn(i))
        try:
            dt = s.step(keys)
        except RuntimeError as exc:
            print('  %s: zastaveno v kroku %d (%s)' % (name, i, exc))
            break
        p = s.player()
        moved = (p['x'], p['y']) != prev
        rows.append({
            'in': p['keys'], 'x': p['x'], 'y': p['y'], 'dir': p['dir'],
            'speed': p['speed'], 'phase': p['phase'], 'timer': p['timer'],
            'turnPhase': p['turnPhase'],
            # $8F15 bit 4: hra ohlásila náraz. Když se Vorton nehnul a tenhle
            # příznak není, něco mu jen stálo v cestě, aniž by to byl náraz –
            # rychlost si nechává. Rozdíl je měřený, ne odvozený.
            'hit': p['hit'],
            'blocked': bool(p['speed'] and not moved),
        })
        prev = (p['x'], p['y'])
        tstates.append(dt)
    return {
        'name': name,
        'note': desc,
        'source': 'originál v simulátoru, tools/tracephysics.py',
        'start': {k: start[k] for k in ('x', 'y', 'dir', 'speed', 'phase',
                                        'timer', 'turnPhase')},
        'tstatesPerStep': {'min': min(tstates), 'max': max(tstates),
                           'mean': round(sum(tstates) / len(tstates))},
        'steps': rows,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'build/traces'),
                    help='kam ukládat záznamy')
    ap.add_argument('--only', help='jen tenhle scénář')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    index = []
    for name, desc, steps, keyfn in SCENARIOS:
        if args.only and args.only != name:
            continue
        trace = record(name, desc, steps, keyfn)
        path = os.path.join(args.out, name + '.json')
        with open(path, 'w') as f:
            json.dump(trace, f, separators=(',', ':'))
        blocked = sum(1 for r in trace['steps'] if r['blocked'])
        print('%-14s %3d kroků, %2d zablokovaných, %s'
              % (name, len(trace['steps']), blocked,
                 os.path.relpath(path, H.ROOT)))
        index.append({'name': name, 'note': desc, 'steps': len(trace['steps']),
                      'blocked': blocked})
    with open(os.path.join(args.out, 'index.json'), 'w') as f:
        json.dump(index, f, indent=1)


if __name__ == '__main__':
    main()
