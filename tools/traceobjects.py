#!/usr/bin/env python3
"""Zaznamená **celý svět originálu krok po kroku** – hráče i všechny objekty (M4).

    PYTHONPATH=tools/vendor ./tools/traceobjects.py [--out build/otraces] [--only jmeno]

Obdoba `tracephysics.py` z M3, jenže tam stačil řízený Vorton; tady se ukládá
**celá tabulka objektů `$8A00`** (24 záznamů po 16 B, `disasm_notes.md` §12)
po každém průchodu hlavní smyčkou, plus počítadlo zón a světové okno z `$8F00`.

Z toho se dá přehrát `app/highwayObjects.js` proti originálu
(`tools/matchobjects.js`) a ptát se na věci, na které M3 neuměla odpovědět:
do čeho se dá narazit, co se strkáním pohne a co ne, kam letí výstřel a co
udělá s tím, do čeho trefí.

Scénáře jsou psané tak, aby se do předmětů **skutečně narazilo**: konvoj stojí
hráči v zádech, takže se musí nejdřív rozjet dopředu (`--prefix`), a teprve pak
zatáčet, brzdit a střílet.
"""
import argparse, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

SLOTS = 24
INACTIVE_X = 200        # neaktivní záznam má v `x` $FE/$FF (změřeno)


def push_scenario(prefix, turn_at, turn_key, turns, tail):
    """Rozjet se dopředu, pak se stočit a jet dál – tím se najíždí do předmětů."""
    def keys(i):
        if i < prefix:
            return ('1',)
        if i < turn_at:
            return ('1',)
        if i < turn_at + turns*2:
            return ('1', turn_key)
        return ('1',)
    return keys


SCENARIOS = [
    ('pushahead', 'rozjet se a tlačit předměty rovně před sebou', 260,
     lambda i: ('1',)),
    ('pushslow', 'totéž, ale rychlostí 1 – strká se jinak než v plné rychlosti', 260,
     lambda i: ('1',) if i < 8 else (('Q',) if i % 16 == 0 else ())),
    ('pushright', 'rozjet se, stočit doprava a strkat napříč silnicí', 260,
     push_scenario(60, 60, 'P', 2, 0)),
    ('pushleft', 'rozjet se, stočit doleva a strkat napříč silnicí', 260,
     push_scenario(60, 60, 'O', 2, 0)),
    ('pushback', 'rozjet se a otočit se zpátky proti konvoji', 260,
     push_scenario(80, 80, 'P', 4, 0)),
    ('pushdiag', 'strkání po úhlopříčce', 260,
     push_scenario(60, 60, 'P', 1, 0)),
    ('shootahead', 'rozjet se, zastavit a střílet do toho, co stojí vepředu', 260,
     lambda i: ('1',) if i < 40 else (('Q',) if i < 50 else ('SPACE',))),
    ('shootmove', 'střílet za jízdy – výstřel předjede hráče', 260,
     lambda i: ('1', 'SPACE') if i >= 20 else ('1',)),
    ('shootturn', 'střílet do stran za zatáčení', 260,
     lambda i: ('1',) if i < 40 else ('SPACE', 'P') if i % 20 < 4 else ('SPACE',)),
    ('shootrow', 'zastavit se a vystřílet celý zásobník do řady předmětů', 300,
     lambda i: ('1',) if i < 30 else ('Q',) if i < 40 else
               (('SPACE',) if (i // 10) % 2 == 0 else ())),
    ('crossing', 'projet hranicí zóny a tlačit předmět přes ni', 300,
     lambda i: ('1',)),
    ('edgeandpush', 'najet na okraj silnice a jet podél něj do předmětů', 300,
     push_scenario(20, 20, 'P', 2, 0)),
]


def random_scenario(seed, steps, prefix=60):
    """Pseudonáhodné mačkání po rozjezdu – to, co scénáře psané rukou nenapadne."""
    rnd = random.Random(1000 + seed)
    keys, held = [], ('1',)
    for i in range(steps):
        if i < prefix:
            keys.append(('1',))
            continue
        if rnd.random() < 0.3:
            held = tuple(k for k in ('1', 'Q', 'O', 'P', 'SPACE')
                         if rnd.random() < 0.45)
        keys.append(held)
    return keys.__getitem__


for seed in range(12):
    SCENARIOS.append(('random%d' % seed,
                      'pseudonáhodné mačkání po rozjezdu, semínko %d' % seed,
                      400, random_scenario(seed, 400)))


def snapshot(s):
    """Aktivní záznamy tabulky objektů jako `[slot, x, y, dir, speed, phase, cls, kind]`.

    `cls` je slovo z offsetu +5/+6. V M3 bylo označené jako „nejspíš rozhoduje,
    kdo objekt řídí" (`disasm_notes.md` §12); měření M4 z něj udělalo **druh
    objektu**: řízený Vorton má 0, výstřel `$0118`, automatický Vorton `$1070`,
    Lasertron `$0910`, předměty na silnici `$1A68`, `$19F0`, `$0A60`, `$0648`,
    `$17F8`, nepřítel `$0228`.
    """
    tab = s.peek(H.ENTITIES, SLOTS * H.ENTITY_SIZE)
    out = []
    for i in range(SLOTS):
        e = tab[i*16:(i+1)*16]
        if e[0] >= INACTIVE_X:
            continue
        out.append([i, e[0], e[1] | (e[2] << 8), e[7], e[8], e[9],
                    e[6] << 8 | e[5], e[10]])
    return out


def globals_of(s):
    g = s.peek(0x8F00, 0x20)
    return {'zone': g[0], 'window': g[5] | (g[6] << 8),
            'keys': g[0x14], 'turnPhase': g[0x13],
            'hit': bool(g[0x15] & H.HIT_MASK), 'timer': g[0x1D]}


def record(name, desc, steps, keyfn):
    s = H.gameplay()
    start = {'ents': snapshot(s), 'globals': globals_of(s)}
    rows = []
    for i in range(steps):
        try:
            s.step(tuple(keyfn(i)))
        except RuntimeError as exc:
            print('  %s: zastaveno v kroku %d (%s)' % (name, i, exc))
            break
        g = globals_of(s)
        rows.append({'in': g['keys'], 'zone': g['zone'], 'window': g['window'],
                     'hit': g['hit'], 'timer': g['timer'],
                     'turnPhase': g['turnPhase'], 'ents': snapshot(s)})
    return {'name': name, 'note': desc,
            'source': 'originál v simulátoru, tools/traceobjects.py',
            'start': start, 'steps': rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'build/otraces'))
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
        zones = len({r['zone'] for r in trace['steps']})
        print('%-12s %3d kroků, %d zón, %s'
              % (name, len(trace['steps']), zones, os.path.relpath(path, H.ROOT)))
        index.append({'name': name, 'note': desc, 'steps': len(trace['steps']),
                      'zones': zones})
    with open(os.path.join(args.out, 'index.json'), 'w') as f:
        json.dump(index, f, indent=1)


if __name__ == '__main__':
    main()
