#!/usr/bin/env python3
"""Zaznamená **přechody zón originálu** → `build/ztraces/` (M2).

    PYTHONPATH=tools/vendor ./tools/tracezones.py [--out build/ztraces]
        [--zones 31]

`dumpzones.py` pravidlo změřil, tohle je podklad, na kterém se ověřuje **port**:
pro každý přechod zóny se uloží stav, ze kterého hra vycházela (tabulka dat
silnice a živá tabulka před přechodem), a stav, ke kterému došla (tabulka dat
silnice po zápisu zpět a úklidu, a pořadí záznamů, které si zóna vzala – pozná
se podle ukazatele `+14/+15`).

Živá tabulka se čte na konci průchodu, tedy až se všechno pohnulo; porovnávat
se proto dá pořadí načtených záznamů, ne jejich souřadnice. Tabulka dat silnice
se mimo přechody nemění, takže ta se porovnává bajt po bajtu.

Přehrává se `tools/matchzones.js`.
"""
import argparse, base64, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402
import dumphighway as D                                           # noqa: E402

LIVE = 0x8A00
LIVE_SLOTS = 54         # 9 pevných + 44 z tabulky + značka konce
WINDOW = 0x8F05


def snapshot(s):
    return {'road': s.peek(D.TABLE, D.COUNT*D.RECORD),
            'live': s.peek(LIVE, LIVE_SLOTS*16),
            'window': s.peek(WINDOW) | (s.peek(WINDOW+1) << 8),
            'zone': s.peek(0x8F00)}


def sources(live):
    out = []
    for i in range(9, LIVE_SLOTS):
        e = live[i*16:(i+1)*16]
        if e[0] == 0xFF:
            break
        p = e[14] | (e[15] << 8)
        out.append((p - D.TABLE)//D.RECORD if D.TABLE <= p < D.TABLE_END else None)
    return out


def b64(data):
    return base64.b64encode(bytes(data)).decode('ascii')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'build/ztraces'))
    ap.add_argument('--zones', type=int, default=31)
    args = ap.parse_args()

    s = H.demo()
    os.makedirs(args.out, exist_ok=True)
    before = snapshot(s)
    steps = []
    while True:
        try:
            s.step()
        except RuntimeError:
            break
        now = snapshot(s)
        if now['zone'] != before['zone']:
            steps.append({
                'from': before['zone'], 'to': now['zone'],
                'window': now['window'],
                'before': {'road': b64(before['road']), 'live': b64(before['live'])},
                'after': {'road': b64(now['road']), 'sources': sources(now['live'])},
            })
            if now['zone'] >= args.zones:
                break
        before = now

    path = os.path.join(args.out, 'demo.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'note': 'přechody zón originálu (tools/tracezones.py); '
                           'přehrává tools/matchzones.js',
                   'source': '6 DEMONSTRATION',
                   'table': {'at': '$%04X' % D.TABLE, 'count': D.COUNT,
                             'recordBytes': D.RECORD},
                   'liveAt': '$%04X' % LIVE, 'liveSlots': LIVE_SLOTS,
                   'steps': steps}, f, ensure_ascii=False)
        f.write('\n')
    print('%s: %d přechodů zón (%s)'
          % (os.path.relpath(path, H.ROOT), len(steps),
             ' '.join('%d→%d' % (st['from'], st['to']) for st in steps[:8]) + ' …'))


if __name__ == '__main__':
    main()
