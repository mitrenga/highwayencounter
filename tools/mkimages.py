#!/usr/bin/env python3
"""Vyrobí obrázky webu z originálního loading screenu.

    ./tools/mkimages.py

Z `sources/media/screens/loading_screen.scr` (titulní obrazovka originálu)
udělá `images/cover.png`, `images/poster.png`, ikony aplikace a `favicon.ico`.
Škáluje se celočíselně nejbližším sousedem, aby zůstaly ostré pixely.
Ikona je čtvercový výřez z titulní grafiky – nic dokresleného.

Definitivní ikony a favicon budou z `svision/tools/make-app-icons`
a `make-favicon` až v M7; tohle je zatím poctivá výplň z originálu.
"""
import os, struct, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scr2png import scr_to_rgb, write_png                       # noqa: E402

ROOT = os.path.join(HERE, '..')
SRC = os.path.join(ROOT, 'sources/media/screens/loading_screen.scr')
# čtvercový výřez titulní grafiky (Vorton, výstřel a mimozemšťan): x, y, strana
CROP = (56, 20, 150)


def resample(rows, width, size):
    """Nejbližší soused na přesnou velikost (ikony musí mít rozměr z názvu)."""
    step = width/size
    out = []
    for r in range(size):
        src = rows[min(len(rows)-1, int(r*step))]
        out.append(b''.join(src[int(c*step)*3:int(c*step)*3+3] for c in range(size)))
    return out


def scale(rows, width, factor):
    out = []
    for row in rows:
        line = b''.join(row[x*3:x*3+3]*factor for x in range(width))
        for _ in range(factor):
            out.append(line)
    return out, width*factor


def crop(rows, x, y, side):
    return [row[x*3:(x+side)*3] for row in rows[y:y+side]]


def png_bytes(rows, width):
    raw = b''.join(b'\x00' + r for r in rows)

    def chunk(tag, p):
        return (struct.pack('>I', len(p)) + tag + p
                + struct.pack('>I', zlib.crc32(tag + p) & 0xFFFFFFFF))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, len(rows), 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9))
            + chunk(b'IEND', b''))


def write_ico(path, images):
    """ICO s PNG payloady (podporují všechny dnešní prohlížeče)."""
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = 6 + 16*len(images)
    entries, payloads = b'', b''
    for size, data in images:
        entries += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32,
                               len(data), offset)
        payloads += data
        offset += len(data)
    open(path, 'wb').write(header + entries + payloads)


def main():
    rows = scr_to_rgb(open(SRC, 'rb').read())
    images = os.path.join(ROOT, 'images')
    os.makedirs(images, exist_ok=True)

    cover, width = scale(rows, 256, 2)
    open(os.path.join(images, 'cover.png'), 'wb').write(png_bytes(cover, width))
    poster, width = scale(rows, 256, 4)
    open(os.path.join(images, 'poster.png'), 'wb').write(png_bytes(poster, width))

    x, y, side = CROP
    icon = crop(rows, x, y, side)
    for size in (192, 256, 512, 1024, 1980):
        open(os.path.join(images, 'app-icon-%dx%d.png' % (size, size)), 'wb').write(
            png_bytes(resample(icon, side, size), size))

    # app-icon.svg jen obalí nejmenší ikonu, aby manifest měl i vektorový odkaz
    small, width = scale(icon, side, 1)
    import base64
    data = base64.b64encode(png_bytes(small, width)).decode('ascii')
    open(os.path.join(images, 'app-icon.svg'), 'w').write(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="%d" height="%d" viewBox="0 0 %d %d" shape-rendering="crispEdges">'
        '<image image-rendering="pixelated" width="%d" height="%d" '
        'xlink:href="data:image/png;base64,%s"/></svg>\n'
        % (side, side, side, side, side, side, data))

    ico = [(size, png_bytes(resample(icon, side, size), size))
           for size in (16, 32, 48, 64)]
    write_ico(os.path.join(ROOT, 'favicon.ico'), ico)
    write_ico(os.path.join(images, 'favicon.ico'), ico)

    print('images/: cover.png, poster.png, app-icon-*.png, app-icon.svg, favicon.ico')


if __name__ == '__main__':
    main()
