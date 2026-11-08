#!/usr/bin/env python3
"""Zaznamená běh originálu se **zaměřením na nepřátele** (M6).

    PYTHONPATH=tools/vendor ./tools/traceenemies.py [--out build/etraces] [--only jmeno]

Obdoba `traceobjects.py` (M4) a `traceconvoy.py` (M5), jen se ukládá o dvě věci
víc, protože bez nich se nepřátelé přehrát nedají:

* **celá tabulka objektů**, včetně nepoužitých míst – nepřítel nevidí záznamy
  za koncem tabulky (`x = $FF`) a přeskakuje prázdná místa (`$FE`), takže se
  konec tabulky musí zaznamenat, ne odhadnout;
* **semínko generátoru** `$5C76` na začátku každého průchodu a **okno světa**
  `$8F05`. Nepřátelé tahají směr z generátoru, ze kterého si tahá i zvuk
  výbuchu a kreslení (`disasm_notes.md` §16), takže port sekvenci sám neudrží;
  bere si semínko po průchodech a matcher každé takové vzetí počítá.

Scénáře jsou psané na nepřátele a schválně **jiné** než ty, na kterých
`dumpenemies.py` pravidla ověřoval:

* nechat je být a jen se koukat (rodina 5 se odráží, rodiny 2–4 chodí);
* jet dopředu do zón, kde jsou;
* střílet do nich (rodiny 2, 3, 4 se dají sundat, mina ne);
* dojet k nim a dotknout se jich (řízený Vorton zahyne a řízení se předá);
* režim `6 DEMONSTRATION`, který projede celou silnici sám a je jediný zdroj
  pozdějších rodin nepřátel;
* pseudonáhodné běhy.

Dva scénáře jsou psané **uzavřenou smyčkou** (`aim`): mezi průchody se přečte
tabulka a stiskne se, co je potřeba, aby se Vorton k nepříteli dostal. Hra se
tím nemění, jen se tím dá napsat skript, který se opravdu trefí – slepým
mačkáním se srážka s nepřítelem nepotká.
"""
import argparse, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402
import dumpenemies as E                                           # noqa: E402


def snapshot(s):
    """Tabulka tak, jak je – i s `$FE`/`$FF`, aby se dal zapsat konec."""
    tab = s.peek(H.ENTITIES, E.SLOTS*16)
    rows = []
    end = E.SLOTS
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


def globals_of(s):
    g = s.peek(0x8F00, 0x20)
    return {'zone': g[0], 'window': g[5] | (g[6] << 8),
            'keys': g[0x14], 'turnPhase': g[0x13],
            'hit': bool(g[0x15] & H.HIT_MASK), 'timer': g[0x1D],
            'seed': s.peek(0x5C76) | s.peek(0x5C77) << 8,
            'time': s.peek(0x8F1A) | s.peek(0x8F1B) << 8}


def state(s):
    ents, end = snapshot(s)
    return {'ents': ents, 'end': end, 'globals': globals_of(s)}


def record(name, desc, steps, script, closed=False, demo=False):
    s = H.demo() if demo else H.gameplay()
    start = state(s)
    keys = None if closed else script(steps)
    rows = []
    for i in range(steps):
        try:
            s.step(script(s) if closed else (tuple(keys[i]) if i < len(keys) else ()))
        except RuntimeError as exc:
            print('  %s: zastaveno v kroku %d (%s)' % (name, i, exc))
            break
        st = state(s)
        st['in'] = st['globals']['keys']
        rows.append(st)
    return {'name': name, 'note': desc,
            'source': 'originál v simulátoru, tools/traceenemies.py',
            'start': start, 'steps': rows}


def random_script(seed, steps, prefix=40):
    rnd = random.Random(2500 + seed)
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
    ('watch', 'nedělat nic a nechat nepřátele chodit', 300,
     lambda n: [()]*n, False, False),
    ('ahead', 'jet dopředu do zón, ve kterých nepřátelé jsou', 500,
     lambda n: [('1',)]*n, False, False),
    ('fire', 'jet dopředu a pořád střílet', 500,
     lambda n: [('1', 'SPACE') if i % 3 else ('1',) for i in range(n)],
     False, False),
    ('demo', 'režim 6 DEMONSTRATION – projede celou silnici sám a je jediný '
     'zdroj pozdějších rodin nepřátel', 1216, lambda n: [()]*n, False, True),
    ('ram', 'dojet k nejbližšímu nepříteli a dotknout se ho (uzavřená smyčka)',
     600, lambda s: E.hunt(s, False), True, False),
    ('shoot', 'zamířit na nejbližšího nepřítele a sestřelit ho (uzavřená '
     'smyčka)', 600, lambda s: E.hunt(s, True), True, False),
]
for seed in range(4):
    SCENARIOS.append(('random%d' % seed,
                      'pseudonáhodné mačkání, semínko %d' % seed, 500,
                      lambda n, s=seed: random_script(s, n), False, False))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'build/etraces'))
    ap.add_argument('--only', help='jen tenhle scénář')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    index = []
    for name, desc, steps, script, closed, demo in SCENARIOS:
        if args.only and args.only != name:
            continue
        trace = record(name, desc, steps, script, closed, demo)
        path = os.path.join(args.out, name + '.json')
        with open(path, 'w') as f:
            json.dump(trace, f, separators=(',', ':'))
        zones = len({r['globals']['zone'] for r in trace['steps']})
        enemies = sum(1 for r in trace['steps'] for e in r['ents']
                      if E.family(e[6] >> 8) in E.ENEMY_FAMILIES)
        print('%-12s %4d kroků, %d zón, %d průchodů nepřátel, %s'
              % (name, len(trace['steps']), zones, enemies,
                 os.path.relpath(path, H.ROOT)))
        index.append({'name': name, 'note': desc, 'steps': len(trace['steps']),
                      'zones': zones, 'enemyPasses': enemies})
    with open(os.path.join(args.out, 'index.json'), 'w') as f:
        json.dump(index, f, indent=1)


if __name__ == '__main__':
    main()
