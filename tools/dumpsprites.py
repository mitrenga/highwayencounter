#!/usr/bin/env python3
"""Vytáhne **sprity** originálu do `data/spriteframes.json` (M2).

Sprity se hledáním osmibajtových sloupců v RAM nenašly (`disasm_notes.md` §8)
a bylo to ze stejného důvodu jako u znakové sady: buňka na obrazovce není
uložený obrázek, protože ji rutina teprve skládá. `tools/tracedraw.py` proto
hledal **rutinu**, a našel ji:

* hrací plocha se nekreslí přímo na obrazovku. Hra ji skládá do **lineárního
  bufferu na `$E900`–`$FBFF`** (32 bajtů na pixelovou řádku, 152 řádek) a
  rutina na `$9A9B` z něj po znakových buňkách kopíruje na obrazovku jen ty,
  které mají nenulové počítadlo v tabulce `$FD00`–`$FF3F` (jedna buňka = jeden
  bajt) – proto se za snímek mění tak málo bajtů (§6);
* do bufferu kreslí rutina na `$98DC`. Sprit je **24 × 24 pixelů**, uložený
  po pixelových řádkách **zdola nahoru**, a každá řádka má **6 bajtů**: tři
  bajty masky (do bufferu se vloží `AND`) a tři bajty obrázku (`OR`). Jeden
  sprit má tedy **144 bajtů**;
* posun v rámci znakové buňky se nedělá předposunutými kopiemi: rutina si
  trojici bajtů posune sama (`SRA`/`RR`, `$9933` a `$99D1`) a která ze čtyř
  variant se použije, vybírá skoková tabulka na `$9915` podle fáze v záznamu
  objektu (`+9`, hodnoty 0, 4, 8, 12) – tedy **krok 2 pixely**, což je přesně
  ten izometrický rastr 2 : 1, který vyšel z korelace posunů (§6);
* který sprit se kreslí, říká tabulka **slov na `$7A00`** (128 položek),
  indexovaná `($8F00 + druh) + záznam[+5]`. Ukazatele míří do souvislého bloku
  **`$B980`–`$D8FF`**, tedy **56 rámců** po 144 bajtech.

Ukládá se celý blok rámců (base64) i tabulka ukazatelů; nic se nedokresluje ani
nedopočítává, je to obsah paměti originálu.

    PYTHONPATH=tools/vendor ./tools/dumpsprites.py [data/spriteframes.json]
        [--ascii N] [--sheet build/sprites.png]
"""
import argparse, base64, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib                                                # noqa: E402
from scr2png import write_png                                    # noqa: E402

POINTERS = 0x7A00       # tabulka slov: index -> adresa spritu
POINTER_COUNT = 128
FRAME_BYTES = 144       # 24 řádek po 6 bajtech (3 maska + 3 obrázek)
FRAME_ROWS = 24
FRAME_WIDTH = 24
ROW_BYTES = 6
# adresy rutin, které tohle všechno dělají (tools/tracedraw.py)
BLIT = 0x9A9B           # buffer -> obrazovka, po buňkách s počítadlem
DRAW = 0x98DC           # sprit -> buffer
SHIFT_TABLE = 0x9915    # skoková tabulka čtyř posunů (0, 2, 4, 6 px)
BUFFER = 0xE900         # buffer hrací plochy, 32 B na pixelovou řádku
COUNTERS = 0xFD00       # počítadla buněk, $FD00 + řádek*32 + sloupec
BANDS = 0x9BFC          # tabulka pásů, které blit kopíruje


def frame_rows(memory, addr):
    """Jeden sprit jako 24 řádek `(maska, obrázek)` odspodu nahoru."""
    return [(bytes(memory[addr+r*ROW_BYTES:addr+r*ROW_BYTES+3]),
             bytes(memory[addr+r*ROW_BYTES+3:addr+r*ROW_BYTES+6]))
            for r in range(FRAME_ROWS)]


def to_ascii(rows):
    """`#` obrázek, `.` průhledné (maska nechá pozadí), `?` vymazané na černo."""
    out = []
    for mask, data in reversed(rows):
        line = ''
        for i in range(3):
            for b in range(8):
                bit = 1 << (7-b)
                line += '#' if data[i] & bit else ('.' if mask[i] & bit else '?')
        out.append(line)
    return out


def sheet(memory, base, count, columns=8):
    """Kontaktní list všech rámců – obrázek bíle, vymazané pozadí černě."""
    cell = FRAME_WIDTH + 2
    rows_out = [bytearray(b'\x00\x00\x40' * (columns*cell))
                for _ in range(((count+columns-1)//columns) * (FRAME_ROWS+2))]
    for index in range(count):
        art = to_ascii(frame_rows(memory, base + index*FRAME_BYTES))
        ox, oy = (index % columns)*cell + 1, (index // columns)*(FRAME_ROWS+2) + 1
        for y, line in enumerate(art):
            row = rows_out[oy+y]
            for x, ch in enumerate(line):
                colour = b'\xff\xff\xff' if ch == '#' else (
                         b'\x00\x00\x00' if ch == '?' else b'\x20\x20\x50')
                row[(ox+x)*3:(ox+x)*3+3] = colour
    return [bytes(r) for r in rows_out], columns*cell


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dst', nargs='?',
                    default=os.path.join(HERE, '..', 'data/spriteframes.json'))
    ap.add_argument('--ascii', type=int, default=0, metavar='N',
                    help='vypsat prvních N rámců jako ASCII (kontrola očima)')
    ap.add_argument('--sheet', help='kam uložit PNG kontaktní list všech rámců')
    args = ap.parse_args()

    session = highwaylib.gameplay()
    memory = session.simulator.memory

    pointers = [memory[POINTERS+2*i] | memory[POINTERS+2*i+1] << 8
                for i in range(POINTER_COUNT)]
    unique = sorted(set(pointers))
    base, top = unique[0], unique[-1] + FRAME_BYTES
    count = (top - base)//FRAME_BYTES
    if any((addr - base) % FRAME_BYTES for addr in unique):
        raise SystemExit('ukazatele nejsou na hranici %d B – rámec není 144 B'
                         % FRAME_BYTES)
    if len(unique) != count:
        print('pozor: %d rámců v rozsahu, ale jen %d z nich tabulka používá'
              % (count, len(unique)))

    frames = [bytes(memory[base+i*FRAME_BYTES:base+(i+1)*FRAME_BYTES])
              for i in range(count)]
    data = {
        'note': 'sprity originálu (tools/dumpsprites.py); rámec 24×24 px, '
                'pixelové řádky zdola nahoru, na řádku 3 B masky (AND) '
                'a 3 B obrázku (OR)',
        'source': 'build/gameplay.z80 (rozehraná hra)',
        'frame': {'width': FRAME_WIDTH, 'height': FRAME_ROWS,
                  'rows': FRAME_ROWS, 'rowBytes': ROW_BYTES,
                  'bytes': FRAME_BYTES, 'order': 'zdola nahoru',
                  'mask': 'první 3 bajty řádku, do bufferu přes AND',
                  'image': 'další 3 bajty řádku, do bufferu přes OR'},
        'block': {'at': '$%04X' % base, 'to': '$%04X' % (top-1), 'count': count},
        'pointers': {'at': '$%04X' % POINTERS, 'count': POINTER_COUNT,
                     'index': 'slovo = adresa rámce; volí se '
                              '($8F00 + druh) + záznam[+5]',
                     'frames': [(p - base)//FRAME_BYTES for p in pointers]},
        'routines': {'blit': '$%04X' % BLIT, 'draw': '$%04X' % DRAW,
                     'shifts': '$%04X' % SHIFT_TABLE,
                     'shiftStep': 2, 'shiftVariants': 4,
                     'phaseInRecord': 9},
        'buffer': {'at': '$%04X' % BUFFER, 'rowBytes': 32, 'rows': 152,
                   'counters': '$%04X' % COUNTERS, 'bands': '$%04X' % BANDS,
                   'address': '$E900 + pixelový řádek*32 + sloupec'},
        'frames': [base64.b64encode(f).decode('ascii') for f in frames],
    }

    with open(args.dst, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('%s: %d rámců po %d B z $%04X-$%04X, tabulka %d ukazatelů na $%04X'
          % (os.path.relpath(args.dst, highwaylib.ROOT), count, FRAME_BYTES,
             base, top-1, POINTER_COUNT, POINTERS))

    for index in range(min(args.ascii, count)):
        print('\n--- rámec %d, $%04X ---' % (index, base + index*FRAME_BYTES))
        for line in to_ascii(frame_rows(memory, base + index*FRAME_BYTES)):
            print('  ' + line)

    if args.sheet:
        rows, width = sheet(memory, base, count)
        os.makedirs(os.path.dirname(os.path.abspath(args.sheet)), exist_ok=True)
        write_png(args.sheet, rows, width, scale=2)
        print('%s: kontaktní list %d rámců'
              % (os.path.relpath(args.sheet, highwaylib.ROOT), count))


if __name__ == '__main__':
    main()
