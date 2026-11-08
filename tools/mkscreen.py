#!/usr/bin/env python3
"""Převede ZX `.scr` (6912 B) na datový soubor remaku.

    ./tools/mkscreen.py <vstup.scr> [data/loading.json] [--name "LOADING SCREEN"]

Uloží celou obrazovku 256×192 jako bitmapu po pixelových řádcích (6144 B,
lineárně shora dolů – nelineární adresování Spectra se rozplete tady, ne
v prohlížeči) a 768 B atributů, obojí base64. Použité pro loading screen
z originální kazety (`tapeLoadingModel`).
"""
import argparse, base64, json, os


def screen_offset(y):
    third, char_row, pix = y >> 6, (y >> 3) & 7, y & 7
    return (third << 11) | (pix << 8) | (char_row << 5)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('dst', nargs='?', default='data/loading.json')
    ap.add_argument('--name', default='LOADING SCREEN')
    args = ap.parse_args()

    scr = open(args.src, 'rb').read()
    if len(scr) != 6912:
        raise SystemExit('cekam 6912 B .scr, mam %d' % len(scr))
    bitmap = bytearray()
    for y in range(192):
        base = screen_offset(y)
        bitmap += scr[base:base+32]

    data = {
        'note': 'obrazovka z originálu (tools/mkscreen.py), bitmapa po pixelových '
                'řádcích + atributy',
        'name': args.name,
        'source': os.path.basename(args.src),
        'width': 256, 'height': 192,
        'bitmap': base64.b64encode(bytes(bitmap)).decode('ascii'),
        'attributes': base64.b64encode(scr[6144:6912]).decode('ascii')
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.dst)), exist_ok=True)
    with open(args.dst, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    print('%s -> %s' % (args.src, args.dst))


if __name__ == '__main__':
    main()
