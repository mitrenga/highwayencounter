#!/usr/bin/env python3
"""Vytáhne **panel** dole na obrazovce z běžící hry do `data/panel.json`.

    PYTHONPATH=tools/vendor ./tools/dumppanel.py [--frames 900] [data/panel.json]

Panel se nekreslí písmem: hra si ho drží jako hotový obrázek na **$6000**
(32 bajtů na pixelovou řádku, lineárně shora dolů) a na obrazovce leží na
`y = 152..185`, tedy ve znakových řádcích 19–23 (`sources/docs/screen_layout.md`).
Popisky `ZONE`, `POWER`, `SCORE`, `TIME`, `HIGH` i rámečky jsou součástí toho
obrázku – vlastní znaková sada hry je potřeba až na číslice, a kde v paměti
leží, je zatím otevřená otázka (`sources/docs/disasm_notes.md` §2).

Ukládá se **to, co je na obrazovce běžící hry**, ne obsah $6000: v $6000 jsou
ikony Vortonů ještě neposunuté a hra je na obrazovku kreslí posunuté o pixel.
Bitmapa i atributy jdou do JSON v base64, stejně jako u `mkscreen.py`.
"""
import argparse, base64, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

from mkruntime import boot                                      # noqa: E402

PANEL_ROW = 19          # první znaková řádka panelu
PANEL_ROWS = 5          # znakové řádky 19..23
BUFFER = 0x6000         # obrázek panelu v paměti hry


def screen_offset(y):
    third, char_row, pix = y >> 6, (y >> 3) & 7, y & 7
    return (third << 11) | (pix << 8) | (char_row << 5)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dst', nargs='?', default=os.path.join(HERE, '..', 'data/panel.json'))
    ap.add_argument('--snapshot', default=os.path.join(HERE, '..', 'build/highwayencounter.z80'))
    ap.add_argument('--frames', type=int, default=900)
    args = ap.parse_args()

    frame = args.frames-1
    simulator, saved = boot(args.snapshot, args.frames, (frame,))
    scr = saved[frame]

    top = PANEL_ROW*8
    bitmap = bytearray()
    for y in range(top, top+PANEL_ROWS*8):
        base = screen_offset(y)
        bitmap += scr[base:base+32]
    attributes = scr[6144+PANEL_ROW*32:6144+(PANEL_ROW+PANEL_ROWS)*32]

    data = {
        'note': 'panel z běžícího originálu (tools/dumppanel.py); znakové řádky '
                '%d–%d, bitmapa po pixelových řádcích + atributy'
                % (PANEL_ROW, PANEL_ROW+PANEL_ROWS-1),
        'source': 'build/highwayencounter.z80, snímek %d' % frame,
        'buffer': '$%04X' % BUFFER,
        'row': PANEL_ROW, 'rows': PANEL_ROWS,
        'width': 256, 'height': PANEL_ROWS*8,
        'bitmap': base64.b64encode(bytes(bitmap)).decode('ascii'),
        'attributes': base64.b64encode(bytes(attributes)).decode('ascii')
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.dst)), exist_ok=True)
    with open(args.dst, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print('%s (%d B bitmapy, %d B atributu)' % (args.dst, len(bitmap), len(attributes)))


if __name__ == '__main__':
    main()
