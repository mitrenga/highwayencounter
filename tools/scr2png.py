#!/usr/bin/env python3
"""ZX Spectrum SCR (6912 B) -> PNG.

Bez zavislosti (jen zlib). Pouziti:
    ./tools/scr2png.py sources/media/screens/loading_screen.scr [out.png] [--scale N]

Adresovani obrazovky je nelinearni: bit 0-7 = X byte, radky jsou
poskladane po tretinach (Y = 0b 0 1 0 T T R R R  P P P, kde T = tretina,
R = radek znaku v tretine, P = pixelovy radek ve znaku).
"""
import sys, zlib, struct

# ZX paleta: 8 barev x 2 jasy (black je jednou, 0x0000EE vs 0x0000FF atd.)
PALETTE = [
    (0x00, 0x00, 0x00), (0x00, 0x00, 0xD7), (0xD7, 0x00, 0x00), (0xD7, 0x00, 0xD7),
    (0x00, 0xD7, 0x00), (0x00, 0xD7, 0xD7), (0xD7, 0xD7, 0x00), (0xD7, 0xD7, 0xD7),
    (0x00, 0x00, 0x00), (0x00, 0x00, 0xFF), (0xFF, 0x00, 0x00), (0xFF, 0x00, 0xFF),
    (0x00, 0xFF, 0x00), (0x00, 0xFF, 0xFF), (0xFF, 0xFF, 0x00), (0xFF, 0xFF, 0xFF),
]


def scr_to_rgb(data, flash_phase=0):
    if len(data) < 6912:
        raise SystemExit('SCR musi mit 6912 bajtu, ma %d' % len(data))
    rows = []
    for y in range(192):
        third, char_row, pix = y >> 6, (y >> 3) & 7, y & 7
        base = (third << 11) | (pix << 8) | (char_row << 5)
        attr_base = 6144 + (y >> 3) * 32
        row = bytearray()
        for cx in range(32):
            bits = data[base + cx]
            attr = data[attr_base + cx]
            ink, paper = attr & 7, (attr >> 3) & 7
            bright = 8 if attr & 0x40 else 0
            if attr & 0x80 and flash_phase:
                ink, paper = paper, ink
            fg, bg = PALETTE[ink + bright], PALETTE[paper + bright]
            for b in range(7, -1, -1):
                row += bytes(fg if bits >> b & 1 else bg)
        rows.append(bytes(row))
    return rows


def write_png(path, rows, width, scale=1):
    if scale > 1:
        rows = [b''.join(row[i * 3:i * 3 + 3] * scale for i in range(width))
                for row in rows for _ in range(scale)]
        width *= scale
    raw = b''.join(b'\x00' + r for r in rows)

    def chunk(tag, payload):
        return (struct.pack('>I', len(payload)) + tag + payload
                + struct.pack('>I', zlib.crc32(tag + payload) & 0xFFFFFFFF))

    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(chunk(b'IHDR', struct.pack('>IIBBBBB', width, len(rows), 8, 2, 0, 0, 0)))
        f.write(chunk(b'IDAT', zlib.compress(raw, 9)))
        f.write(chunk(b'IEND', b''))


def main(argv):
    args = [a for a in argv[1:] if not a.startswith('--')]
    scale = 1
    for a in argv[1:]:
        if a.startswith('--scale'):
            scale = int(a.split('=')[1]) if '=' in a else 1
    if not args:
        raise SystemExit(__doc__)
    src = args[0]
    dst = args[1] if len(args) > 1 else src.rsplit('.', 1)[0] + '.png'
    rows = scr_to_rgb(open(src, 'rb').read())
    write_png(dst, rows, 256, scale)
    print('%s -> %s (%dx%d)' % (src, dst, 256 * scale, 192 * scale))


if __name__ == '__main__':
    main(sys.argv)
