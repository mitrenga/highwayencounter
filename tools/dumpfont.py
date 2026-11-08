#!/usr/bin/env python3
"""Vytáhne **znakovou sadu** hry → `data/font.json` (M7, zavírá `disasm_notes.md` §2).

    PYTHONPATH=tools/vendor ./tools/dumpfont.py [--out data/font.json]

Od M1 to byla největší otevřená věc projektu: hra text zjevně sází (`OPTIONS`,
`INFORMATION`, `SCORE`, `HIGH`, `ZONE`), ale písmo se v paměti nenašlo –
hledaly se osmibajtové glyfy, prokládané, otočené, invertované i posunuté
(`disasm_notes.md` §2). Nenašlo se proto, že **glyf má pět bajtů, ne osm**,
a hra kolem něj buňku teprve skládá.

Našlo se to z druhého konce: koncová sekvence M7 tiskne text `CALL $B890`,
a ta rutina dělá tohle:

* kód znaku se ořízne na **`kód AND $3F`** a to je index glyfu;
* glyf je **pět bajtů od `$5B00`** (`$5B00 + 5 × index`), tedy hned nad
  atributovou částí videopaměti;
* na obrazovku se buňka skládá po pixelových řádkách jako
  **`00`, `$7F`, pět bajtů glyfu, `$7F`** – proto se osmibajtové hledání §2
  nemohlo chytit: buňka na obrazovce není glyf, je to glyf v rámečku;
* **bity 6 a 7 kódu vybírají atribut** ze čtyř možností, ne písmeno:
  `00 → $46`, `10 → $03`, `01 → $07`, `11 → $47`. Text se kreslí nadvakrát –
  nejdřív atributy celé řádky, pak bitmapa.

Řetězec je řada řádek: každá začíná trojicí **`(horní bajt adresy v bitmapě,
dolní bajt, horní bajt adresy v atributech)`** – dolní bajt je oběma společný –
a končí `$FF`; celý řetězec končí `$FE`.

Co je tady měřené a co odvozené:

* **bitmapy glyfů** se čtou z RAM běžící hry – měření;
* **skladba buňky a atributy** se čtou z rutiny `$B890` a ověřují se tím, že
  se **titulní obrazovka originálu rozebere zpátky na znaky**: každá buňka,
  která má rámeček `$7F`, se najde v tabulce glyfů;
* **který glyf je které písmeno** není v paměti nikde – je to to, co je na
  obrazovce vidět. Bere se proto ze dvou obrazovek, které hra sama napíše –
  titulní (`AUTHOR COSTA PANAYI`, menu `OPTIONS`, `COPYRIGHT 1985 VORTEX
  SOFTWARE`) a `5 INFORMATION` (`disasm_notes.md` §4): text se přiloží na
  dekódované indexy a mapa z toho vypadne. Kam v řádce text patří, se nehádá –
  zkusí se všechna posunutí a vezme se to, ve kterém si **žádný** glyf
  neodporuje. Nástroj hlásí, kolik glyfů se tím pojmenovalo a kolik sporů
  zbylo (dnes 36 glyfů a nula sporů).

Spouštět s `PYTHONPATH=tools/vendor` (vendorovaný SkoolKit, viz tools/README.md).
"""
import argparse, base64, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

FONT = 0x5B00           # základ tabulky glyfů (rutina $B890)
GLYPH_ROWS = 5          # pixelových řádek na glyf
GLYPHS = 0x40           # index je kód AND $3F
FRAME = 0x7F            # řádka rámečku nad glyfem a pod ním
PRINT = 0xB890          # tiskárna textu
LINE_END = 0xFF
STRING_END = 0xFE
# bity 7 a 6 kódu -> atribut (rutina $B8A0)
ATTRS = {(0, 0): 0x46, (1, 0): 0x03, (0, 1): 0x07, (1, 1): 0x47}

TITLE_FRAMES = 400      # ve snímku 400 je titulní obrazovka hotová (§4, měřeno)

# Co titulní obrazovka **říká** – jediná kotva, kterou přiřazení glyf → písmeno
# má. Řádky jsou v pořadí shora dolů; nástroj si je na obrazovce najde sám.
TITLE_TEXT = [
    'AUTHOR COSTA PANAYI',
    'OPTIONS',
    '1 KEYBOARD',
    '2 INTERFACE 2',
    '3 KEMPSTON',
    '4 PROTEK/AGF',
    '5 INFORMATION',
    '6 DEMONSTRATION',
    '7 START GAME',
    'COPYRIGHT 1985 VORTEX SOFTWARE',
]
# a totéž na obrazovce `5 INFORMATION` – přidá písmena, která na titulní
# obrazovce nejsou (v rámečcích je ale druhé, menší písmo, takže se berou jen
# nadpisy, které hra sází touhle sadou)
INFO_TEXT = [
    'HIGHWAY  ENCOUNTER',
    'CLASSIFIED INFORMATION',
    'AUTO-VORTONS',
    'LASERTRON',
    'MAIN VORTON',
    'CONTROLS',
    'YOUR MISSION',
    'PRESS ANY KEY WHEN READY',
]
# a nakonec dva řetězce, které hra drží v paměti hotové: konec režimu
# `6 DEMONSTRATION` ($A4D6) a text druhého průchodu ($8FB0). Tady se nic
# neposouvá – kódy znaků jsou přesně ty, které se vytisknou –, takže přidají
# i písmena, která na obou obrazovkách nejsou (`Z`, `!`).
STRINGS = [
    (0xA4D6, [' THERE IS ', ' ONLY ONE WAY ', ' TO ENCOUNTER ',
              ' WHAT LIES BEYOND ', ' ZONE ZERO! ', ' SO GET ON WITH IT! ']),
    (0x8FB0, ['PREPARE YOURSELF', '  FOR THE NEXT  ', ' HIGHWAY ENCOUNTER! ']),
]
LINE_END, STRING_END = 0xFF, 0xFE


def read_string(session, addr, limit=400):
    """Řetězec pro rutinu `$B890`: řádky s trojicí adres, `$FF` konec řádky,
    `$FE` konec řetězce. Vrací indexy glyfů po řádkách."""
    lines, i, end = [], addr, addr + limit
    while i < end:
        i += 3                                       # hlavička řádky
        codes = []
        while i < end:
            b = session.peek(i)
            i += 1
            if b in (LINE_END, STRING_END):
                break
            codes.append(b & 0x3F)
        lines.append(codes)
        if b == STRING_END:
            break
    return lines


def screen_offset(y):
    return ((y >> 6) << 11) | ((y & 7) << 8) | (((y >> 3) & 7) << 5)


def cell(scr, row, col):
    return bytes(scr[screen_offset(row*8 + i) + col] for i in range(8))


def read_glyphs(session):
    """Pět bajtů na glyf od `$5B00`, jak je má hra v paměti."""
    raw = session.peek(FONT, GLYPHS * GLYPH_ROWS)
    return [bytes(raw[i*GLYPH_ROWS:(i+1)*GLYPH_ROWS]) for i in range(GLYPHS)]


def decode_screen(scr, glyphs):
    """Obrazovka zpátky na indexy glyfů. Buňka se počítá za znak jen tehdy,
    když má rámeček (`00`, `$7F`, …, `$7F`) a jejích pět řádek je v tabulce."""
    index = {}
    for i, g in enumerate(glyphs):
        index.setdefault(g, i)
    rows = []
    for row in range(24):
        out = []
        for col in range(32):
            c = cell(scr, row, col)
            if c[0] == 0 and c[1] == FRAME and c[7] == FRAME and c[2:7] in index:
                out.append((col, index[c[2:7]]))
            else:
                out.append((col, None))
        rows.append(out)
    return rows


def title_lines(rows):
    """Souvislé úseky znaků na obrazovce, shora dolů."""
    lines = []
    for r, row in enumerate(rows):
        run = []
        for col, idx in row:
            if idx is None:
                if len(run) > 2:
                    lines.append((r, run[0][0], [i for _, i in run]))
                run = []
            else:
                run.append((col, idx))
        if len(run) > 2:
            lines.append((r, run[0][0], [i for _, i in run]))
    return lines


def _conflicts(pairs):
    """Kolikrát vyjde jednomu glyfu víc různých znaků."""
    seen, bad = {}, []
    for idx, ch in pairs:
        if idx in seen and seen[idx] != ch:
            bad.append([idx, seen[idx], ch])
        else:
            seen[idx] = ch
    return seen, bad


def build_map(lines, texts):
    """Přiloží známý text na dekódované indexy a vrátí mapu index → znak.

    Řádky obrazovky a texty jdou v témže pořadí shora dolů, ale řádka bývá
    o pár znaků delší: hra kolem textu sází ozdobné dílky. Kam v řádce text
    patří, se **nehádá** – zkusí se všechna posunutí a vezme se ta kombinace,
    ve které si žádný glyf neodporuje (jeden glyf, jeden znak). Kdyby jich
    bylo příliš, jede se hladově a nástroj to pozná podle počtu sporů."""
    pairs = list(zip(lines, texts))
    options = []
    for (row, col, run), text in pairs:
        span = len(run) - len(text)
        options.append([(run, text, off) for off in range(span + 1)] if span >= 0 else [])
    options = [o for o in options if o]
    total = 1
    for o in options:
        total *= len(o)

    def score(choice):
        acc = []
        for run, text, off in choice:
            acc += [(run[off + i], ch) for i, ch in enumerate(text)]
        return _conflicts(acc)

    best = None
    if total <= 200000:
        import itertools
        for choice in itertools.product(*options):
            mapping, bad = score(choice)
            key = (len(bad), sum(off for _, _, off in choice))
            if best is None or key < best[0]:
                best = (key, mapping, bad)
    else:                                                # pragma: no cover
        chosen = []
        for opt in options:
            pick = min(opt, key=lambda c: len(score(chosen + [c])[1]))
            chosen.append(pick)
        mapping, bad = score(chosen)
        best = ((len(bad), 0), mapping, bad)
    return best[1], best[2], len(options)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'data/font.json'))
    args = ap.parse_args()

    s = H.Session()
    s.run(TITLE_FRAMES)                      # titulní obrazovka i s menu
    glyphs = read_glyphs(s)
    rows = decode_screen(s.screen(), glyphs)
    lines = title_lines(rows)
    mapping, clashes, used = build_map(lines, TITLE_TEXT)

    # kolik buněk titulní obrazovky se rozebralo na znaky – kontrola skladby
    cells = sum(1 for row in rows for _, idx in row if idx is not None)

    # druhá kotva: obrazovka `5 INFORMATION`
    s.hold('1', 20)
    s.run(60)
    s.hold('5', 20)
    s.run(80)
    info_rows = decode_screen(s.screen(), glyphs)
    info_lines = title_lines(info_rows)
    info_map, info_clashes, info_used = build_map(info_lines, INFO_TEXT)
    for idx, ch in info_map.items():
        if idx in mapping and mapping[idx] != ch:
            clashes.append([idx, mapping[idx], ch])
        else:
            mapping[idx] = ch
    used += info_used
    cells += sum(1 for row in info_rows for _, idx in row if idx is not None)
    clashes += info_clashes

    # třetí kotva: hotové řetězce v paměti – kód za kódem, bez posouvání
    strings = 0
    for addr, texts in STRINGS:
        for codes, text in zip(read_string(s, addr), texts):
            if len(codes) != len(text):
                continue
            strings += 1
            for idx, ch in zip(codes, text):
                if idx in mapping and mapping[idx] != ch:
                    clashes.append([idx, mapping[idx], ch])
                else:
                    mapping[idx] = ch
    used += strings

    # mezera: znak, který se na obrazovce vyskytuje a v mapě mu vyšlo ' '
    space = sorted(i for i, c in mapping.items() if c == ' ')

    data = {
        'source': 'tools/dumpfont.py',
        'note': ('znaková sada originálu: pět bajtů na glyf od $5B00, index je '
                 'kód znaku AND $3F. Buňka na obrazovce není glyf – hra ji '
                 'skládá jako 00, $7F, pět bajtů glyfu, $7F, a proto ji '
                 'osmibajtové hledání disasm_notes.md §2 nenašlo.'),
        'base': '$%04X' % FONT,
        'glyphs': GLYPHS,
        'glyphRows': GLYPH_ROWS,
        'cellRows': 8,
        'cell': ['00', '$%02X' % FRAME, 'glyf 0-4', '$%02X' % FRAME],
        'codeMask': 0x3F,
        'printRoutine': '$%04X' % PRINT,
        'attributes': {'%d%d' % k: '$%02X' % v for k, v in ATTRS.items()},
        'attributesNote': ('bity 7 a 6 kódu nevybírají písmeno, ale barvu; '
                           'klíč je "bit7 bit6"'),
        'string': {
            'lineHeader': ['horní bajt adresy v bitmapě', 'společný dolní bajt',
                           'horní bajt adresy v atributech'],
            'lineEnd': '$%02X' % LINE_END,
            'stringEnd': '$%02X' % STRING_END,
        },
        'bitmaps': [base64.b64encode(g).decode('ascii') for g in glyphs],
        'map': {str(i): mapping[i] for i in sorted(mapping)},
        'space': ['$%02X' % i for i in space],
        'measured': {
            'titleLines': len(lines),
            'cells': cells,
            'anchorLines': used,
            'anchorLinesTotal': len(TITLE_TEXT) + len(INFO_TEXT)
                                + sum(len(t) for _, t in STRINGS),
            'mapped': len(mapping),
            'clashes': clashes,
        },
        'open': [
            'glyfy nad písmeny a číslicemi (indexy mimo mapu) jsou grafické '
            'dílky – co který kreslí, ukáže až pixelové srovnání (M8)',
            'obrazovka INFORMATION má **druhé, menší písmo** pro text v rámečcích '
            '(řetězce od $B640 jsou ASCII, disasm_notes.md §4); tahle tabulka '
            'je písmo velké, kterým se sázejí nadpisy, menu a hlášky hry',
        ],
    }
    with open(args.out, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print('%s: %d glyfů po %d bajtech od $%04X, pojmenováno %d '
          '(%d řádek kotevních obrazovek, %d buněk, %d sporů)'
          % (os.path.relpath(args.out, H.ROOT), GLYPHS, GLYPH_ROWS, FONT,
             len(mapping), used, cells, len(clashes)))


if __name__ == '__main__':
    main()
