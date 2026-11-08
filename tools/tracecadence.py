#!/usr/bin/env python3
"""Zaznamená **délku každého průchodu** hlavní smyčkou originálu (M9).

    PYTHONPATH=tools/vendor ./tools/tracecadence.py [--out build/ktraces] [--only jmeno]

Referenční záznamy pro `tools/matchcadence.js`. Pro každý scénář se nabootuje
originál a po každém průchodu hlavní smyčkou se uloží:

* kolik **T-stavů** ten průchod trval (to je to, co se má trefit),
* kolik záznamů se ten průchod **kreslilo** (délka seznamu na `$8D52`),
* kolik záznamů je v tabulce `$8A00` **živých** (ať jsou vidět, nebo ne),
* jakou **žádanku o zvuk** měla hra na začátku průchodu (`$8F15`) – zvuk se
  hraje synchronně uvnitř smyčky, takže si její délku prodlouží,
* jestli ten průchod originál **překresluje celou plochu** – to dělá při
  přechodu do další zóny a v průchodu po ztrátě řízeného Vortona.

Port ta čísla nedostane napovězená: `matchcadence.js` je bere jako popis
situace a ptá se `app/highwayCadence.js`, jak dlouho by v ní průchod trval.
"""
import argparse, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402
from dumpcadence import features                                  # noqa: E402

OUT = os.path.join(H.ROOT, 'build/ktraces')

# scénář = (jméno, popis, jak se hraje, kolik průchodů)
#   'demo' = režim 6 DEMONSTRATION, jinak hraný běh s daným semínkem
SCENARIOS = [
    ('demo', 'demonstrace – hra si projede celou silnici sama', 'demo', 1300),
    ('throttle', 'plný plyn od začátku, bez zatáčení', 'keys:1', 200),
    ('idle', 'nic se nemačká – silnice jede sama kolem konvoje', 'keys:', 200),
    ('firing', 'plný plyn s drženou střelbou – zvuk v každém druhém průchodu',
     'keys:1,SPACE', 200),
    ('turning', 'kroužení plnou rychlostí', 'keys:1,P', 200),
]
for seed in range(8):
    SCENARIOS.append(('random%d' % seed,
                      'pseudonáhodné mačkání včetně střelby, semínko %d' % seed,
                      'random:%d' % seed, 220))


def play(kind, passes):
    """Odehraje scénář a vrátí seznam průchodů."""
    if kind == 'demo':
        s = H.demo()
        keys_at = lambda i: ()
    elif kind.startswith('keys:'):
        s = H.gameplay()
        held = tuple(k for k in kind[5:].split(',') if k)
        keys_at = lambda i: held
    else:
        s = H.gameplay()
        rnd = random.Random(int(kind.split(':')[1]))
        plan = []
        held = ('1',)
        for _ in range(passes):
            if rnd.random() < 0.25:
                held = tuple(k for k in ('1', 'Q', 'O', 'P', 'SPACE')
                             if rnd.random() < 0.4)
            plan.append(held)
        keys_at = plan.__getitem__

    rows = []
    for i in range(passes):
        pre = features(s)
        try:
            t = s.step(keys_at(i))
        except RuntimeError:
            break
        post = features(s)
        zone = pre['window'] != post['window']
        # prázdná tabulka počítadel na konci průchodu = plocha se složila celá
        # znovu; bez změny zóny to znamená ztrátu řízeného Vortona
        repaint = zone or post['dirty'] == 0
        # první průchod po načtení cache je useknutý – hra stojí uprostřed
        # smyčky, takže se do záznamu nebere
        if i:
            rows.append({'t': t, 'drawn': post['drawn'], 'live': post['live'],
                         'sound': pre['sound'],
                         'repaint': repaint})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--only')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    index = []
    for name, note, kind, passes in SCENARIOS:
        if args.only and args.only != name:
            continue
        rows = play(kind, passes)
        with open(os.path.join(args.out, name + '.json'), 'w') as f:
            json.dump({'name': name, 'note': note, 'kind': kind,
                       'frameTstates': 69888, 'passes': rows}, f,
                      indent=1, ensure_ascii=False)
            f.write('\n')
        index.append({'name': name, 'note': note, 'passes': len(rows)})
        print('%-12s %4d průchodů  – %s' % (name, len(rows), note))

    if not args.only:
        with open(os.path.join(args.out, 'index.json'), 'w') as f:
            json.dump(index, f, indent=1, ensure_ascii=False)
            f.write('\n')
    print('%d scénářů, %d průchodů → %s'
          % (len(index), sum(e['passes'] for e in index),
             os.path.relpath(args.out, H.ROOT)))


if __name__ == '__main__':
    main()
