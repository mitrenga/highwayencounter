#!/usr/bin/env python3
"""Zaznamená běh originálu se **zaměřením na konvoj** (M5).

    PYTHONPATH=tools/vendor ./tools/traceconvoy.py [--out build/ctraces] [--only jmeno]

Obdoba `traceobjects.py` z M4 – ukládá se tatáž věc, celá tabulka objektů
`$8A00` po každém průchodu hlavní smyčkou (`disasm_notes.md` §12) – jenže
scénáře jsou psané tak, aby konvoj dělal všechno, co umí:

* stát mu v cestě a nechat se dotlačit;
* uhnout a nechat ho dojet do předmětů, které nikdo neuklidil;
* uklidit mu průjezd středem a nechat ho projet;
* projet s ním hranici zóny;
* a dlouhé běhy, ve kterých řízený Vorton zahyne a **řízení se předá**
  automatickému Vortonovi.

Scénáře jsou schválně **jiné** než ty, na kterých `dumpconvoy.py` pravidla
naměřil (jiná semínka, jiné skripty): matcher nemá přehrávat data, ze kterých
pravidlo vzniklo.
"""
import argparse, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

SLOTS = 24
INACTIVE_X = 200


def keys_of(script):
    return lambda i: script[i] if i < len(script) else ()


def block(steps):
    """Stát konvoji v cestě: nedělat nic, dokud do mě nedojede, pak popojet."""
    return [() if i % 30 < 22 else ('1',) for i in range(steps)]


def aside(steps, turn, at=40):
    """Rozjet se, uhnout stranou a nechat konvoj jet dál samotný."""
    return ([('1',)]*at + [('1', turn)]*8
            + [('1',)]*30 + [('Q',)]*10 + [()]*steps)[:steps]


def clear_lane(steps):
    """Uklidit průjezd středem: rozjet se, střílet dopředu a jet dál."""
    out = [('1',)]*30
    while len(out) < steps:
        out += [('1', 'SPACE')]*6 + [('1',)]*6
    return out[:steps]


def meet(steps):
    """Otočit se a jet konvoji naproti – čelní zastavení Lasertronu."""
    return ([('1',)]*70 + [('1', 'P')]*8 + [('1',)]*40 + [()]*steps)[:steps]


SCENARIOS = [
    ('block', 'stát konvoji v cestě a nechat ho zastavit se o mě', 300, block),
    ('aside', 'uhnout doleva a nechat konvoj dojet do neuklizených předmětů',
     300, lambda n: aside(n, 'O')),
    ('aside2', 'totéž doprava', 300, lambda n: aside(n, 'P')),
    ('clear', 'uklízet konvoji průjezd středem střelbou', 300, clear_lane),
    ('meet', 'otočit se a jet konvoji naproti', 300, meet),
    ('crossing', 'projet s konvojem hranicí zóny', 400,
     lambda n: [('1',)]*n),
    ('idle', 'nedělat vůbec nic – konvoj dojede a zastaví se', 200,
     lambda n: [()]*n),
]


def random_script(seed, steps, prefix=40):
    rnd = random.Random(9000 + seed)
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


for seed in range(6):
    SCENARIOS.append(('random%d' % seed,
                      'pseudonáhodné mačkání, semínko %d' % seed, 400,
                      lambda n, s=seed: random_script(s, n)))
# Dlouhé běhy, ve kterých řízený Vorton doopravdy zahyne a řízení se předá.
# Semínka nejsou vybraná náhodou: ze čtyřiceti pseudonáhodných běhů jsou to ty,
# ve kterých k předání dojde (u 6 dokonce dvakrát) – jinak by se to jediné
# pravidlo M5, které se týká hráče, na ničem neověřilo.
for seed in (6, 7, 9, 10, 13):
    SCENARIOS.append(('handover%d' % seed,
                      'dlouhý běh – řízený Vorton zahyne a řízení se předá, '
                      'semínko %d' % seed, 1200,
                      lambda n, s=seed: random_script(s, n)))


def snapshot(s):
    """Aktivní záznamy jako `[slot, x, y, dir, speed, phase, cls, kind]`."""
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


def record(name, desc, steps, script):
    s = H.gameplay()
    start = {'ents': snapshot(s), 'globals': globals_of(s)}
    keys = script(steps)
    rows = []
    for i in range(steps):
        try:
            s.step(tuple(keys[i]) if i < len(keys) else ())
        except RuntimeError as exc:
            print('  %s: zastaveno v kroku %d (%s)' % (name, i, exc))
            break
        g = globals_of(s)
        rows.append({'in': g['keys'], 'zone': g['zone'], 'window': g['window'],
                     'hit': g['hit'], 'timer': g['timer'],
                     'turnPhase': g['turnPhase'], 'ents': snapshot(s)})
    return {'name': name, 'note': desc,
            'source': 'originál v simulátoru, tools/traceconvoy.py',
            'start': start, 'steps': rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'build/ctraces'))
    ap.add_argument('--only', help='jen tenhle scénář')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    index = []
    for name, desc, steps, script in SCENARIOS:
        if args.only and args.only != name:
            continue
        trace = record(name, desc, steps, script)
        path = os.path.join(args.out, name + '.json')
        with open(path, 'w') as f:
            json.dump(trace, f, separators=(',', ':'))
        zones = len({r['zone'] for r in trace['steps']})
        print('%-12s %4d kroků, %d zón, %s'
              % (name, len(trace['steps']), zones, os.path.relpath(path, H.ROOT)))
        index.append({'name': name, 'note': desc, 'steps': len(trace['steps']),
                      'zones': zones})
    with open(os.path.join(args.out, 'index.json'), 'w') as f:
        json.dump(index, f, indent=1)


if __name__ == '__main__':
    main()
