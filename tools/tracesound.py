#!/usr/bin/env python3
"""Zaznamená běh originálu se **zaměřením na žádanku zvuku** → `build/straces/` (M8).

    PYTHONPATH=tools/vendor ./tools/tracesound.py [--out build/straces] [--only jmeno]
                                                  [--report]

`dumpsound.py` změřil, **jak** efekty zní. Tenhle nástroj měří to druhé: **kdy**
si o ně hra řekne. Zastavuje se v každém průchodu na rozskoku `$9AEF`, tedy
v okamžiku, kdy si hra žádanku `$8F15` přečte a hned nato vynuluje – to je
jediné místo, kde je celá vidět. Ukládá se k ní **celá tabulka objektů**
(stejně jako v `traceenemies.py`, i s `$FE`/`$FF`), stav hráče, semínko
generátoru a okno světa, takže se dá průchod přehrát portem.

`--report` na záznamech spočítá **souhrn**: ke každému bitu žádanky to, co se
v tabulce ten průchod stalo. Tím se pojmenují spouštěče, které `dumpsound.py`
umí najít v kódu, ale ne pojmenovat – rodina zanikajícího záznamu, výstřel,
náraz. Nic se neodhaduje: v tabulce se porovnává průchod s průchodem.

Scénáře jsou schválně jiné než ty, na kterých se měřilo v M3–M6, a hlavně
takové, ve kterých je co slyšet: střelba, nájezdy do předmětů, dojíždění
k nepřátelům a celá demonstrace.
"""
import argparse, collections, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402
import dumpenemies as E                                           # noqa: E402
import dumpsound as S                                             # noqa: E402


def snapshot(s):
    """Tabulka tak, jak je – i s `$FE`/`$FF`, aby se dal zapsat konec."""
    tab = s.peek(H.ENTITIES, E.SLOTS*16)
    rows, end = [], E.SLOTS
    for i in range(E.SLOTS):
        e = tab[i*16:(i+1)*16]
        if e[0] == E.END_X:
            end = i
            break
        if e[0] == E.EMPTY_X:
            continue
        rows.append([i, e[0], e[1] | e[2] << 8, e[7], e[8], e[9],
                     e[6] << 8 | e[5], e[10], e[12], e[3] | e[4] << 8,
                     e[11], e[13], e[14]])
    return rows, end


def state(s, flag):
    ents, end = snapshot(s)
    g = s.peek(0x8F00, 0x20)
    return {'ents': ents, 'end': end, 'sound': flag,
            'globals': {'zone': g[0], 'window': g[5] | (g[6] << 8),
                        'keys': g[0x14], 'turnPhase': g[0x13],
                        'timer': g[0x1D],
                        'seed': s.peek(S.SEED) | s.peek(S.SEED + 1) << 8,
                        'ptr': g[1] | g[2] << 8,
                        # M8: šest číslic skóre ($A481), aby se dalo změřit,
                        # kdy přesně se přičítá (tools/dumpscore.py)
                        'score': list(s.peek(0xA481, 6))}}


def pass_at_dispatch(s, keys):
    """Doběhne na `$9AEF`, přečte žádanku a nechá efekt dohrát.

    Zvuk běží **synchronně** – hlavní smyčka na něj čeká – takže se musí
    doběhnout až za něj, jinak by se další průchod počítal odjinud.
    """
    if s.run_to(S.DISPATCH, frames=60, keys=keys) is None:
        return None
    flag = s.peek(S.FLAG)
    st = state(s, flag)
    if s.run_to(S.RETURN, frames=400, keys=keys) is None:
        return None
    return st


def record(name, desc, steps, script, closed=False, demo=False):
    s = H.demo() if demo else H.gameplay()
    start = state(s, 0)
    keys = None if closed else script(steps)
    rows = []
    for i in range(steps):
        held = script(s) if closed else (tuple(keys[i]) if i < len(keys) else ())
        st = pass_at_dispatch(s, held)
        if st is None:
            print('  %s: zastaveno v kroku %d' % (name, i))
            break
        st['in'] = st['globals']['keys']
        rows.append(st)
    return {'name': name, 'note': desc,
            'source': 'originál v simulátoru, tools/tracesound.py',
            'start': start, 'steps': rows}


def random_script(seed, steps, prefix=40):
    rnd = random.Random(800 + seed)
    out, held = [], ('1',)
    for i in range(steps):
        if i < prefix:
            out.append(('1',))
            continue
        if rnd.random() < 0.35:
            held = tuple(k for k in ('1', 'Q', 'O', 'P', 'SPACE')
                         if rnd.random() < 0.5)
        out.append(held)
    return out


SCENARIOS = [
    ('fire', 'jet dopředu a pořád střílet – zvuk výstřelu a zánik terčů', 400,
     lambda n: [('1', 'SPACE') if i % 3 else ('1',) for i in range(n)], False, False),
    ('shove', 'najíždět do předmětů, ať se ozve náraz', 400,
     lambda n: [('1',) if i % 40 < 30 else ('1', 'P') for i in range(n)], False, False),
    ('demo', 'režim 6 DEMONSTRATION – projede celou silnici sám', 900,
     lambda n: [()]*n, False, True),
    ('ram', 'dojet k nejbližšímu nepříteli a dotknout se ho (uzavřená smyčka)',
     900, lambda s: E.hunt(s, False), True, False),
    ('shoot', 'zamířit na nejbližšího nepřítele a sestřelit ho (uzavřená smyčka)',
     900, lambda s: E.hunt(s, True), True, False),
    ('deep', 'projet co nejdál a přitom pořád střílet – jediná cesta k rodinám '
     'nepřátel z pozdějších zón', 1200,
     lambda n: [('1', 'SPACE') if i % 2 else ('1',) for i in range(n)], False, False),
]
for seed in range(3):
    SCENARIOS.append(('random%d' % seed,
                      'pseudonáhodné mačkání, semínko %d' % seed, 400,
                      lambda n, s=seed: random_script(s, n), False, False))


# --- souhrn: co se v tabulce stalo v průchodu, který si o zvuk řekl ---------

def by_slot(rows):
    return {r[0]: r for r in rows}


def events(prev, cur):
    """Co se mezi dvěma průchody v tabulce změnilo – slovy portu."""
    out = collections.Counter()
    was, now = by_slot(prev['ents']), by_slot(cur['ents'])
    for slot, rec in now.items():
        old = was.get(slot)
        dying = bool(rec[4] & 0x80)
        was_dying = bool(old[4] & 0x80) if old else False
        family = E.family(rec[6] >> 8)
        if dying and not was_dying:
            out['zaniká rodina %d' % family] += 1
        elif dying and was_dying and rec[6] != old[6]:
            out['dohořívá rodina %d' % family] += 1
        if old is None:
            out['nový záznam rodiny %d' % family] += 1
    for slot, rec in was.items():
        if slot not in now:
            out['zmizel záznam rodiny %d' % E.family(rec[6] >> 8)] += 1
    if cur['globals']['keys'] & H.KEY_FIRE and not (prev['globals']['keys'] & H.KEY_FIRE):
        out['stisk FIRE'] += 1
    return out


def report(traces):
    """Pro každý bit žádanky: co se v takových průchodech dělo."""
    per_bit = collections.defaultdict(collections.Counter)
    counts = collections.Counter()
    total = 0
    for trace in traces:
        rows = trace['steps']
        for i in range(1, len(rows)):
            total += 1
            flag = rows[i]['sound']
            if not flag:
                continue
            what = events(rows[i-1], rows[i])
            for bit in range(8):
                if flag & (1 << bit):
                    counts[bit] += 1
                    for key, n in what.items():
                        per_bit[bit][key] += n
    print('\nsouhrn: %d průchodů, %d s žádankou' % (total, sum(counts.values())))
    names = {1: 'fire', 3: 'blast', 4: 'bump', 6: 'destroy', 7: 'crash'}
    for bit in sorted(counts):
        print('  bit %d (%s): %d průchodů' % (bit, names.get(bit, '?'), counts[bit]))
        for key, n in per_bit[bit].most_common(8):
            print('      %-32s %d' % (key, n))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'build/straces'))
    ap.add_argument('--only', help='jen tenhle scénář')
    ap.add_argument('--report', action='store_true', help='jen souhrn z hotových záznamů')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    if args.report:
        traces = []
        for name in sorted(os.listdir(args.out)):
            if name.endswith('.json') and name != 'index.json':
                with open(os.path.join(args.out, name)) as f:
                    traces.append(json.load(f))
        report(traces)
        return

    index, traces = [], []
    for name, desc, steps, script, closed, demo in SCENARIOS:
        if args.only and args.only != name:
            continue
        trace = record(name, desc, steps, script, closed, demo)
        path = os.path.join(args.out, name + '.json')
        with open(path, 'w') as f:
            json.dump(trace, f, separators=(',', ':'))
        loud = sum(1 for r in trace['steps'] if r['sound'])
        print('%-12s %4d průchodů, %3d se zvukem, %s'
              % (name, len(trace['steps']), loud, os.path.relpath(path, H.ROOT)))
        index.append({'name': name, 'note': desc, 'steps': len(trace['steps']),
                      'withSound': loud})
        traces.append(trace)
    with open(os.path.join(args.out, 'index.json'), 'w') as f:
        json.dump(index, f, indent=1)
    report(traces)


if __name__ == '__main__':
    main()
