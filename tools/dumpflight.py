#!/usr/bin/env python3
"""Vytáhne z originálu **scénář zkušebního letu** pro `testFlightPage.php` (M9).

    PYTHONPATH=tools/vendor ./tools/dumpflight.py [--frames 5000] [--width 76]

Sourozenecké projekty mají zkušební let napsaný rukou: řetězec kláves, kterým
se po nasazení hra sama projde a je vidět, jestli běží. Highway Encounter ho
psát rukou nemusí, protože má **záznam skutečného hráče** – `highway.rzx`,
26 minut dohrané hry, ze kterého se od M7 měří konec. Tenhle nástroj ho pustí
v simulátoru a zapíše, **co si hra v každém snímku přečetla z klávesnice**
(`$8F14`, `disasm_notes.md` §13) – tedy ne co hráč mačkal, ale co hra viděla.

Snímek, ne průchod: v jednotce snímků tiká i worker portu, takže se let odvíjí
ve stejném čase, ve kterém ho odehrál hráč. Výstup je mřížka znaků k vložení
do `testFlightPage.php`: běhy `NNc`, kde `c` je base32 z bitové masky kláves
originálu (FIRE 1, plyn 2, brzda 4, doprava 8, doleva 16) a `NN` volitelný
počet opakování.

**Demonstrace originálu se na tohle nehodí**, i když by se to nabízelo:
změřeno, že v režimu `6 DEMONSTRATION` zůstane `$8F14` po celý průběh na
`$14` – attract mode si Vortona vede sám a přes bajt klávesnice nejede.

Že let nedopadne stejně jako v originálu, je čekané a je to v pořádku: dokud
M2 nezná obsah zón, jede port po prázdné silnici. Zkušební let není matcher –
je to kontrola, že se nasazená hra rozjede, kreslí, zní a nespadne.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402
import playrzx                                                    # noqa: E402

# base32: 0-9 a A-V, jeden znak na masku kláves
ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUV'
MAX_RUN = 99            # dvouciferný počet opakování, jako u sourozenců


def record_rzx(frames, rzx=playrzx.RZX):
    """Maska kláves, kterou hra přečetla, snímek po snímku."""
    out = []

    def watch(pb, frame):
        out.append(pb.peek(H.KEYS_READ) & 0x1F)
        return len(out) < frames

    playrzx.Playback(rzx).run(watch=watch)
    return out


def encode(masks):
    """Běhové kódování: `NNc`, `NN` chybí, když je běh jeden snímek."""
    out = []
    i = 0
    while i < len(masks):
        j = i
        while j < len(masks) and masks[j] == masks[i]:
            j += 1
        run = j-i
        while run > 0:
            part = min(run, MAX_RUN)
            out.append(('%02d' % part if part > 1 else '') + ALPHABET[masks[i]])
            run -= part
        i = j
    return ''.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--frames', type=int, default=5000,
                    help='kolik snímků záznamu vzít (5000 je sto sekund letu)')
    ap.add_argument('--rzx', default=playrzx.RZX)
    ap.add_argument('--width', type=int, default=76,
                    help='znaků na řádek výstupu')
    ap.add_argument('--json', help='uložit i jako JSON (pro nástroje)')
    args = ap.parse_args()

    if not os.path.isfile(args.rzx):
        raise SystemExit('chybí %s – záznam je mimo git, viz sources/README.md'
                         % os.path.relpath(args.rzx, H.ROOT))

    masks = record_rzx(args.frames, args.rzx)
    script = encode(masks)
    # řádky se lámou jen mezi běhy, ať se dají spojit prostým slepením
    rows, row = [], ''
    i = 0
    while i < len(script):
        step = 3 if script[i].isdigit() else 1
        if len(row)+step > args.width:
            rows.append(row)
            row = ''
        row += script[i:i+step]
        i += step
    if row:
        rows.append(row)

    used = sorted(set(masks))
    print('// %d snímků záznamu hráče, %d znaků scénáře (tools/dumpflight.py)'
          % (len(masks), len(script)))
    for r in rows:
        print('      "%s",' % r)
    print('// masky kláves ve scénáři: %s'
          % ', '.join('%s=%d' % (ALPHABET[k], k) for k in used))

    if args.json:
        with open(args.json, 'w') as f:
            json.dump({'note': 'klávesy, které hra přečetla v záznamu hráče, '
                               'jeden běh na snímek (tools/dumpflight.py)',
                       'alphabet': ALPHABET, 'frames': len(masks),
                       'script': script}, f, indent=1, ensure_ascii=False)
            f.write('\n')


if __name__ == '__main__':
    main()
