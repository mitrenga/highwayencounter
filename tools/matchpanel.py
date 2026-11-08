#!/usr/bin/env python3
"""Porovná **panel složený z dat remaku** s panelem originálu, pixel po pixelu (M8).

    PYTHONPATH=tools/vendor ./tools/matchpanel.py [--frames 240] [--verbose]

Ostatní matchery přehrávají port proti záznamu chování; tenhle dělá totéž
s obrazem. Panel se **složí z datových souborů** – obrázek panelu
(`data/panel.json`), živá pole (`data/panelfields.json`) a od M8 i číslice
`SCORE`/`HIGH` (`data/score.json`) – a porovná se s tím, co má originál
v ten okamžik na obrazovce. Živé hodnoty se čtou z paměti běžící hry, ne
z portu: měří se, jestli **data stačí** panel nakreslit, ne jestli port
správně počítá.

Hlásí se rozdíly po buňkách a rovnou i to, do kterého pole panelu padly
(`sources/docs/screen_layout.md` §3), takže je vidět, co ještě chybí. Dnes
sedí orámování, popisky, pole `ZONE`, řada Vortonů, obě čísla i ukazatel
`POWER`; zbývá **lampa doprovodu Lasertronu** (dvě buňky na řádce 20,
`data/score.json` `lamp`), protože pravidlo, podle kterého se rozsvěcuje,
změřené není – a `TIME`, kterému se v žádném naměřeném běhu neubral dílek.

Spouštět s `PYTHONPATH=tools/vendor` (vendorovaný SkoolKit, viz tools/README.md).
"""
import argparse, base64, collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

PANEL_ROW = 19
PANEL_ROWS = 5
COLS = 32
ZONE_COUNTER = 0x8F00
SCORE_DIGITS = 0xA481
HIGH_DIGITS = 0xA489

# Pole panelu podle sources/docs/screen_layout.md §3 – jen na pojmenování
# rozdílů, nic se z toho nepočítá.
FIELDS = [
    ('lampa doprovodu', 20, 20, 16, 17),   # dvě buňky, viz disasm_notes.md §18
    ('ZONE', 19, 23, 0, 5),
    ('řada Vortonů', 19, 23, 5, 17),
    ('POWER', 19, 20, 18, 23),
    ('SCORE', 19, 20, 24, 31),
    ('TIME', 21, 22, 18, 23),
    ('HIGH', 21, 22, 24, 31),
]


def load(name):
    path = os.path.join(H.ROOT, 'data', name + '.json')
    if not os.path.isfile(path):
        raise SystemExit('chybi data/%s.json' % name)
    with open(path) as f:
        return json.load(f)


def decode(b64):
    return bytearray(base64.b64decode(b64))


def screen_panel(scr):
    """Bitmapa a atributy panelu ze snímku obrazovky, po řádkách shora dolů."""
    bitmap = bytearray()
    for y in range(PANEL_ROW * 8, (PANEL_ROW + PANEL_ROWS) * 8):
        third, line, row = y // 64, y % 8, (y % 64) // 8
        a = third * 2048 + line * 256 + row * 32
        bitmap += scr[a:a + COLS]
    return bitmap, bytearray(scr[6144 + PANEL_ROW * COLS:
                                 6144 + (PANEL_ROW + PANEL_ROWS) * COLS])


def blit(bitmap, block, col, row_in_panel, cols):
    rows = len(block) // cols
    for r in range(rows):
        for c in range(cols):
            bitmap[(row_in_panel * 8 + r) * COLS + col + c] = block[r * cols + c]


def compose(panel, fields, score, zone, marks, score_digits, high_digits,
            power_pointer=None):
    """Panel tak, jak ho remake složí z dat."""
    bitmap = decode(panel['bitmap'])
    attrs = decode(panel['attributes'])
    picture = fields['zone']['values'].get(str(zone))
    if picture:
        blit(bitmap, decode(picture), fields['zone']['col'],
             fields['zone']['rowInPanel'], fields['zone']['cols'])
        za = decode(fields['zone']['attributes'])
        for r in range(fields['zone']['rows']):
            for c in range(fields['zone']['cols']):
                attrs[(fields['zone']['rowInPanel'] + r) * COLS
                      + fields['zone']['col'] + c] = za[r * fields['zone']['cols'] + c]
    row = fields['vortons']
    for i in range(row['count']):
        icon = row['icons'][i]
        block = icon['controlled'] if marks[i] else icon['waiting']
        if block:
            blit(bitmap, decode(block), row['col'] + i * row['step'],
                 row['rowInPanel'], row['step'])
    if score:
        glyphs = decode(score['glyphs']['bytes'])
        rows = score['glyphs']['rows']
        for digits, where in ((score_digits, score['cells']['score']),
                              (high_digits, score['cells']['high'])):
            r = where['row'] - PANEL_ROW
            for i, digit in enumerate(reversed(digits)):
                col = where['col'] - i
                for line in range(rows):
                    bitmap[(r * 8 + where['line'] + line) * COLS + col] = \
                        glyphs[digit * rows + line]
    # M8: POWER je zásobník výstřelů – dílek je plný právě tehdy, když jeho
    # adresa není za ukazatelem $8F18 (data/score.json `power`).
    if score and power_pointer is not None and 'power' in score:
        bar = score['power']
        for cell_at in bar['cells']:
            addr = int(cell_at[1:], 16)
            full = addr <= int(bar['page'][1:], 16) * 256 + power_pointer
            attrs[(addr - 0x5800) - PANEL_ROW * COLS] = \
                int((bar['full'] if full else bar['empty'])[1:], 16)
    return bitmap, attrs


def field_of(row, col):
    for name, r0, r1, c0, c1 in FIELDS:
        if r0 <= row <= r1 and c0 <= col <= c1:
            return name
    return 'jinde'


def compare(panel, fields, score, session, marks):
    scr = session.screen()
    got_bitmap, got_attrs = screen_panel(scr)
    zone = session.peek(ZONE_COUNTER)
    want_bitmap, want_attrs = compose(
        panel, fields, score, 31 - zone, marks,
        list(session.peek(SCORE_DIGITS, 6)), list(session.peek(HIGH_DIGITS, 6)),
        session.peek(0x8F18))
    cells = collections.Counter()
    for r in range(PANEL_ROWS):
        for c in range(COLS):
            bad = got_attrs[r * COLS + c] != want_attrs[r * COLS + c]
            for line in range(8):
                if got_bitmap[(r * 8 + line) * COLS + c] != want_bitmap[(r * 8 + line) * COLS + c]:
                    bad = True
            if bad:
                cells[field_of(PANEL_ROW + r, c)] += 1
    return cells


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--frames', type=int, default=240, help='kolik snímků porovnat')
    ap.add_argument('--every', type=int, default=20, help='po kolika snímcích')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    panel = load('panel')
    fields = load('panelfields')
    score = None
    if os.path.isfile(os.path.join(H.ROOT, 'data/score.json')):
        score = load('score')

    total, clean, cells = 0, 0, collections.Counter()
    marks0 = [True, False, False, False, False]
    # Třetí běh je se stisknutou střelbou schválně: `POWER` je zásobník
    # výstřelů (data/sounds.json `power`), takže se jinak vůbec nehne a
    # porovnání by ho nezkusilo.
    runs = (('hra', H.gameplay, marks0, ()),
            ('demonstrace', H.demo, marks0, ()),
            ('střelba', H.gameplay, marks0, ('SPACE', '1')))
    for name, make, marks, keys in runs:
        s = make()
        for i in range(args.frames // args.every):
            for key in keys:
                s.hold(key, args.every)
            s.run(args.every)
            bad = compare(panel, fields, score, s, marks)
            total += 1
            if not bad:
                clean += 1
            cells.update(bad)
            if args.verbose and bad:
                print('  %s snímek %d: %s'
                      % (name, s.frame, ', '.join('%s %d buněk' % kv
                                                  for kv in bad.most_common())))
    print('%d panelů porovnáno, %d sedí do posledního pixelu' % (total, clean))
    if cells:
        print('rozdílné buňky podle pole:')
        for field, n in cells.most_common():
            print('  %-14s %5d' % (field, n))
    else:
        print('nula rozdílů')


if __name__ == '__main__':
    main()
