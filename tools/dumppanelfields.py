#!/usr/bin/env python3
"""Odměří **živá pole panelu** → `data/panelfields.json` (M5).

    PYTHONPATH=tools/vendor ./tools/dumppanelfields.py [--out data/panelfields.json]

`dumppanel.py` vytáhl panel jako obrázek – rámečky a popisky `ZONE`, `POWER`,
`SCORE`, `TIME`, `HIGH` (`screen_layout.md` §2). Co se na něm za hry **mění**,
tenhle nástroj měří zvlášť, a zase jen z běžící hry: znaková sada se pořád
nenašla (`disasm_notes.md` §2), takže se číslice nesázejí, ale **vyfotí** –
pro každou hodnotu zvlášť, přímo z videopaměti originálu.

Měří se dvě pole, obě patří k M5:

* **`ZONE`** – dvouciferné číslo velkým segmentovým písmem. Bere se z režimu
  `6 DEMONSTRATION`, ve kterém si hra projede všech 31 zón sama, takže se
  obrázek dá sejmout pro **každou** hodnotu, kterou hra kdy ukáže (30 až 0).
* **řada `1 2 3 4 5`** s ikonami Vortonů. Tady měření opravuje, co o ní ZADANI
  §7 předpokládalo: **neubývá jich**. Když zahyne automatický Vorton, na panelu
  se nezmění nic; ikona ztmavne (vyplní se) až u toho Vortona, kterého hráč
  začne řídit – a ta předchozí zůstane vyplněná taky. Řada tedy neukazuje,
  kolik Vortonů zbývá, ale **kolikátého v pořadí hráč zrovna řídí**. Změřeno
  tak, že se hrálo tak dlouho, dokud se řízení nepředalo (pseudonáhodné běhy,
  ve kterých řízený Vorton zahyne), a po každém předání se sejmul panel.
"""
import argparse, base64, collections, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

PANEL_ROW = 19          # první znaková řádka panelu (screen_layout.md §1)
PANEL_ROWS = 5
ZONES = 31              # 30 zón a Zone Zero (disasm_notes.md §7)

# Rámečky panelu ve znakových sloupcích (screen_layout.md §3). Které sloupce
# a řádky se doopravdy mění, se dole ověřuje měřením, ne odsud.
ZONE_BOX = {'col': 1, 'cols': 4, 'row': 20, 'rows': 3}
VORTON_ROW = 20         # znaková řádka s ikonami Vortonů
VORTON_COL = 6          # první sloupec první ikony
VORTON_STEP = 2         # každá ikona je široká dva znakové sloupce
VORTONS = 5


def screen_offset(y):
    return ((y >> 6) << 11) | ((y & 7) << 8) | (((y >> 3) & 7) << 5)


def cell_block(scr, col, row, cols, rows):
    """Bitmapa obdélníku znakových buněk, po pixelových řádkách."""
    out = bytearray()
    for y in range(row*8, (row+rows)*8):
        base = screen_offset(y)
        out += scr[base+col:base+col+cols]
    return bytes(out)


def attr_block(scr, col, row, cols, rows):
    out = bytearray()
    for r in range(row, row+rows):
        out += scr[6144 + r*32 + col: 6144 + r*32 + col + cols]
    return bytes(out)


def measure_zone_digits(limit=4000):
    """Obrázek pole `ZONE` pro každou hodnotu, kterou hra ukáže.

    Demo si projde celou silnici samo (`highwaylib.demo()`), takže stačí sledovat
    počítadlo zón na `$8F00` a po každé jeho změně sejmout obrázek. Ukazuje se
    `31 - n` (`disasm_notes.md` §7); že to tak doopravdy je, se pozná z toho, že
    se obrázek pro dvě různé hodnoty nikdy neopakuje.
    """
    s = H.demo()
    seen = {}
    attrs = collections.Counter()
    counter = None
    for _ in range(limit):
        try:
            s.step(())
        except RuntimeError:
            break
        n = s.peek(0x8F00)
        if n == counter:
            continue
        counter = n
        scr = s.screen()
        shown = ZONES - n
        seen[shown] = cell_block(scr, ZONE_BOX['col'], ZONE_BOX['row'],
                                 ZONE_BOX['cols'], ZONE_BOX['rows'])
        attrs[attr_block(scr, ZONE_BOX['col'], ZONE_BOX['row'],
                         ZONE_BOX['cols'], ZONE_BOX['rows'])] += 1
    return seen, attrs


def icon(scr, index):
    return cell_block(scr, VORTON_COL + index*VORTON_STEP, VORTON_ROW,
                      VORTON_STEP, 1)


def controlled_slot(s):
    tab = s.peek(H.ENTITIES, 24 * H.ENTITY_SIZE)
    for i in range(24):
        e = tab[i*16:(i+1)*16]
        if e[0] < 200 and (e[6] << 8 | e[5]) == 0 and e[8] <= 4:
            return i
    return None


def random_script(seed, steps, prefix=40):
    rnd = random.Random(seed)
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


def measure_vorton_row(seeds, steps):
    """Jak řada ikon reaguje na to, že se řízení předá dalšímu Vortonovi.

    Hraje se, dokud řízený Vorton nezahyne; po každém předání se sejme řada
    a zapíše se, který slot se zrovna řídí. Z toho vypadne, jestli ikony
    ubývají (neubývají) a která ikona patří kterému slotu.
    """
    icons = {}          # (index ikony, stav) -> bitmapa
    marks = []          # co bylo vyplněné po každém předání
    deaths = 0
    for seed in seeds:
        s = H.gameplay()
        script = random_script(seed, steps)
        ctrl = controlled_slot(s)
        base = [icon(s.screen(), k) for k in range(VORTONS)]
        for k in range(VORTONS):
            icons.setdefault((k, 'controlled' if k == ctrl else 'waiting'),
                             base[k])
        for keys in script:
            try:
                s.step(keys)
            except RuntimeError:
                break
            now = controlled_slot(s)
            if now is None or now == ctrl:
                continue
            deaths += 1
            ctrl = now
            row = [icon(s.screen(), k) for k in range(VORTONS)]
            filled = [k for k in range(VORTONS)
                      if row[k] != icons.get((k, 'waiting'), row[k])]
            for k in range(VORTONS):
                state = 'controlled' if row[k] != icons.get((k, 'waiting')) \
                        else 'waiting'
                icons.setdefault((k, state), row[k])
            marks.append({'seed': seed, 'controlledSlot': ctrl,
                          'filledIcons': filled})
    return icons, marks, deaths


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'data/panelfields.json'))
    ap.add_argument('--seeds', type=int, default=24,
                    help='kolik pseudonáhodných běhů zkusit kvůli předání řízení')
    ap.add_argument('--steps', type=int, default=1200)
    args = ap.parse_args()

    digits, zone_attrs = measure_zone_digits()
    print('ZONE: %d hodnot (%s..%s), různých obrázků %d, atributy %s'
          % (len(digits), min(digits), max(digits),
             len(set(digits.values())), ['%d× %s' % (v, a.hex())
                                         for a, v in zone_attrs.most_common(2)]))

    icons, marks, deaths = measure_vorton_row(range(9000, 9000+args.seeds),
                                              args.steps)
    have = sorted(icons)
    print('Vortoni: %d předání řízení, sejmuto %s'
          % (deaths, [(k, st) for k, st in have]))
    for m in marks[:8]:
        print('   po předání na slot %d vyplněné ikony %s'
              % (m['controlledSlot'], m['filledIcons']))
    controlled = [icons[k] for k in icons if k[1] == 'controlled']
    same = len(set(controlled)) == 1
    common = controlled[0] if same and controlled else None
    print('   vyplněná ikona je na všech naměřených místech %s'
          % ('stejná' if same else 'RŮZNÁ'))

    data = {
        'note': ('Živá pole panelu, sejmutá z běžícího originálu '
                 '(tools/dumppanelfields.py). Číslice se nesázejí písmem – '
                 'znaková sada hry se zatím nenašla (disasm_notes.md §2) – '
                 'takže je tu pro každou hodnotu obrázek přímo z videopaměti.'),
        'source': 'tools/dumppanelfields.py, build/gameplay.z80 a režim '
                  '6 DEMONSTRATION',
        'panelRow': PANEL_ROW,
        'zone': {
            'col': ZONE_BOX['col'], 'row': ZONE_BOX['row'],
            'cols': ZONE_BOX['cols'], 'rows': ZONE_BOX['rows'],
            'rowInPanel': ZONE_BOX['row'] - PANEL_ROW,
            'values': {str(k): base64.b64encode(v).decode('ascii')
                       for k, v in sorted(digits.items())},
            'attributes': base64.b64encode(
                zone_attrs.most_common(1)[0][0]).decode('ascii'),
            'distinct': len(set(digits.values())),
            'note': ('bitmapa pole ZONE pro každou hodnotu, kterou hra ukáže '
                     '(31 − počítadlo zón, disasm_notes.md §7); vzato z režimu '
                     '6 DEMONSTRATION, který si projde všechny zóny sám'),
        },
        'vortons': {
            'row': VORTON_ROW, 'rowInPanel': VORTON_ROW - PANEL_ROW,
            'col': VORTON_COL, 'step': VORTON_STEP, 'count': VORTONS,
            'icons': [{'index': k,
                       # Vyplněná ikona: naměřená tam, kam se hráč v měření
                       # dostal (ikony 1 až 3), a na zbylých místech tatáž –
                       # protože na všech naměřených místech vyšla bajt po
                       # bajtu stejná. To je jediné místo v M5, kde se něco
                       # dopočítává, a je to tady označené (`measured`).
                       'controlled': base64.b64encode(
                           icons.get((k, 'controlled'), common)).decode('ascii')
                       if common else None,
                       'controlledMeasured': (k, 'controlled') in icons,
                       'waiting': (base64.b64encode(icons[(k, 'waiting')])
                                   .decode('ascii')
                                   if (k, 'waiting') in icons else None),
                       'waitingMeasured': (k, 'waiting') in icons}
                      for k in range(VORTONS)],
            'sameControlledGlyph': same,
            'handovers': deaths,
            'marks': marks,
            'note': ('řada `1 2 3 4 5` **neubývá**: zánik automatického Vortona '
                     'na panelu nezmění nic. Vyplněná (tmavá) ikona je ta, '
                     'jejíhož Vortona hráč řídí, a **zůstane vyplněná i potom** '
                     '– po převzetí dalšího jsou vyplněné obě. Řada tedy '
                     'ukazuje, kolikátého Vortona v pořadí hráč už spotřeboval, '
                     'ne kolik jich zbývá; ZADANI §7 to četlo obráceně.'),
        },
        'open': [
            'vyplněná ikona pátého (a čtvrtého) Vortona se nenaměřila: ani '
            'v jednom z běhů se hráč nedostal tak hluboko, aby ho začal řídit. '
            'Bere se ta, která vyšla na všech místech, kam se měření dostalo, '
            'bajt po bajtu stejná – jediný dopočet v M5, a je označený '
            '(`controlledMeasured`).',
            'POWER a TIME jsou sloupcové ukazatele – co měří, je M6',
            'SCORE a HIGH se sázejí číslicemi znakové sady, a ta se zatím '
            'nenašla (disasm_notes.md §2)',
        ],
    }
    with open(args.out, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print('%s: živá pole panelu' % os.path.relpath(args.out, H.ROOT))


if __name__ == '__main__':
    main()
