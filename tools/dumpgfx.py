#!/usr/bin/env python3
"""Vytáhne **obraz silnice zónu po zóně** do `data/scenery.json` (M2).

Kreslí ho originál sám a sejme se v jediném okamžiku, kdy je na obrazovce
**celý a bez objektů**: při přechodu do zóny. Rutina na `$97A6` tam přenese
`$D905` → `$4000`, tedy **18 znakových řádek (144 pixelových) z bloku pozadí**,
a hned za ní `$97DD` přenese 576 bajtů atributů z `$FD00`–`$FF3F`. Blok pozadí
je ten, ze kterého hra sprity mazává (§8), takže v něm žádný objekt není – a
protože se čte hned po přenosu a před prvním nakresleným spritem, je i obrazovka
v tu chvíli čistá kulisa.

Proč se to nedá vzít jinak:

* z bufferu `$E900` se za hry na obrazovku kopíruje jen **parallelogram** 363
  buněk z 608 (§8), takže zbytek plochy v žádném průchodu k dispozici není;
* obrazovka za hry nese objekty a v režimu `6 DEMONSTRATION` navíc nápis
  `DEMO MODE` – ten je ale v **bufferu**, ne v bloku pozadí, takže do obrazu
  zóny sejmutého při přechodu nezasahuje;
* znaková řádka 18 se nepřenáší vůbec (přenáší se 18 řádek, 0–17) – zůstává,
  jak byla, a §8 měřila, že se do ní nikdy nekreslí.

Ke každé zóně se ukládá bitmapa hrací plochy (19 znakových řádek po
pixelových řádkách) a jejích 608 atributů, oboje base64. Zóny se číslují jako
na panelu (`30` … `0`), stejně jako v `attrs.json`; vnitřní počítadlo hry je
`31 − zóna`.

Co tím **není** změřené: jak si hra ten obraz z tabulky dat silnice na `$7B00`
složí (`dumphighway.py`, `disasm_notes.md` §17). Tohle je fotografie výsledku,
ne recept – stejně jako panel a číslice `ZONE`.

    PYTHONPATH=tools/vendor ./tools/dumpgfx.py [data/scenery.json]
        [--png build/scenery]
"""
import argparse, base64, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib                                                # noqa: E402
from scr2png import write_png                                    # noqa: E402

PAINTED_PC = 0x97DF     # bitmapa i atributy zóny jsou na obrazovce, sprity ještě ne
ZONE_COUNTER = 0x8F00
ZONES = 31
ROWS = 19*8             # hrací plocha, pixelové řádky
ROW_BYTES = 32
PAINTED_ROWS = 18       # přechod přenáší 18 znakových řádek, ne 19
BACKGROUND = 0xD905
ATTR_BUFFER = 0xFD00
BANDS = 0x9BFC
# první zóna se nakreslí hned po výběru z menu, tedy ještě za bootem – proto se
# boot musí zastavit dřív než v `highwaylib.demo()`
START_FRAMES = 520


def bands(memory):
    """Tabulka pásů z `$9BFC`: `{znaková řádka: [od, do]}` – kreslený
    parallelogram, jediné místo, kde se za hry objeví objekty (§8)."""
    out = {}
    addr = BANDS
    while memory[addr]:
        count = memory[addr]
        screen = memory[addr+3] | memory[addr+4] << 8
        row = ((screen >> 11) & 3)*8 + ((screen >> 5) & 7)
        col = screen & 31
        out[row] = [col - count + 1, col]
        addr += 7
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dst', nargs='?',
                    default=os.path.join(HERE, '..', 'data/scenery.json'))
    ap.add_argument('--png', help='kam uložit PNG každé zóny (kontrola očima)')
    ap.add_argument('--waits', type=int, default=900,
                    help='kolik snímků nejvýš čekat na další přechod')
    args = ap.parse_args()

    # Attract mode si silnici projede sám; boot se zastaví hned po výběru `6`,
    # aby se stihl i obraz **první** zóny.
    session = highwaylib.Session(highwaylib.SNAPSHOT)
    session.run(START_FRAMES, script=highwaylib.DEMO_SCRIPT)
    memory = session.simulator.memory

    zones = {}
    band_table = None
    while len(zones) < ZONES:
        if session.run_to(PAINTED_PC, frames=args.waits) is None:
            break
        zone = ZONES - memory[ZONE_COUNTER]
        if not 0 <= zone < ZONES or str(zone) in zones:
            continue
        if band_table is None:
            band_table = bands(memory)
        bitmap, attributes = session.play_area()
        zones[str(zone)] = {
            'bitmap': base64.b64encode(bytes(bitmap)).decode('ascii'),
            'attributes': base64.b64encode(bytes(attributes)).decode('ascii'),
            'frame': session.frame,
        }
        print('  zona %2d: snimek %d' % (zone, session.frame))

    print('zon: %d z %d' % (len(zones), ZONES))
    data = {
        'note': 'obraz hrací plochy zónu po zóně, sejmutý z běžícího originálu '
                '(tools/dumpgfx.py) v okamžiku přechodu do zóny, kdy je na '
                'obrazovce celá kulisa a ještě žádný objekt: $97A6 přenese '
                '$D905 → $4000 (18 znakových řádek) a $97DD atributy '
                'z $FD00–$FF3F',
        'source': 'režim 6 DEMONSTRATION, obraz při přechodu do každé zóny',
        'zoneNumbers': 'jako na panelu, 30 … 0; vnitřní počítadlo hry je 31 − zóna',
        'rows': ROWS, 'rowBytes': ROW_BYTES, 'paintedRows': PAINTED_ROWS,
        'background': {'at': '$%04X' % BACKGROUND,
                       'attributes': '$%04X' % ATTR_BUFFER},
        'bands': {'at': '$%04X' % BANDS,
                  'note': 'z bufferu se za hry na obrazovku kopíruje jen tenhle '
                          'parallelogram – jen v něm se objeví objekty',
                  'rows': band_table or {}},
        'open': 'jak si hra obraz zóny složí z tabulky dat silnice na $7B00 '
                '(dumphighway.py) – tohle je fotografie výsledku, ne recept',
        'zones': zones,
    }
    with open(args.dst, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('%s: %d zon' % (os.path.relpath(args.dst, highwaylib.ROOT), len(zones)))

    if args.png:
        os.makedirs(args.png, exist_ok=True)
        for zone, entry in zones.items():
            bitmap = base64.b64decode(entry['bitmap'])
            rows = []
            for row in range(ROWS):
                line = bytearray()
                for col in range(ROW_BYTES):
                    byte = bitmap[row*ROW_BYTES + col]
                    for bit in range(8):
                        line += (b'\xff\xff\xff' if byte & (0x80 >> bit)
                                 else b'\x00\x00\x00')
                rows.append(bytes(line))
            write_png(os.path.join(args.png, 'zone%02d.png' % int(zone)),
                      rows, ROW_BYTES*8)
        print('%s: PNG %d zon' % (os.path.relpath(args.png, highwaylib.ROOT),
                                  len(zones)))


if __name__ == '__main__':
    main()
