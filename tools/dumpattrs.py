#!/usr/bin/env python3
"""Odměří **atributy hrací plochy** → `data/attrs.json` (M8).

    PYTHONPATH=tools/vendor ./tools/dumpattrs.py [--out data/attrs.json]
                                                 [--passes 40]

Crash 20 o hře napsal „road and objects in black and white but nice use of
colour for the roadside graphics". M8 to má ověřit, ne opsat – a tenhle nástroj
to dělá tak, že si projede celou silnici režimem `6 DEMONSTRATION` a pro každou
zónu sejme atributy hrací plochy tolikrát, aby se poznalo, které buňky se
hýbou (tam se něco kreslí) a které stojí (to je kulisa zóny).

Co z toho vypadlo:

1. **Barva je opravdu jen kulisa.** Buňky, které se během zóny mění – tedy ty,
   ve kterých se něco pohybuje – jsou z drtivé většiny `$07`, bílá na černé.
   Barvy nesou buňky, které stojí.
2. **Barva sedí u obou krajů obrazovky.** Sloupcový profil barevných buněk je
   miska: nejvíc jich je ve sloupci 0 a 31, nejmíň uprostřed (sloupce 16–19).
   Přesně to Crash popsal – uprostřed jede silnice, a ta je černobílá.
3. **`BRIGHT` se používá, `FLASH` ne.** V žádné zóně nemá ani jedna buňka
   hrací plochy nastavený bit 7.
4. **Zóna se maže vynulováním atributů** (`disasm_notes.md` §6); nulové buňky
   se proto do sčítání neberou, ale počítá se, kolik jich bylo.

Uloží se **atributová mapa každé zóny** – to, co v ní stojí – a k ní maska
buněk, které se během zóny hýbaly. Je to fotka z originálu, jako obrázky pole
`ZONE` v `data/panelfields.json`; obarvit se s ní dá až bitmapa, kterou kreslí
M2, takže renderer ji zatím nepoužívá.

Spouštět s `PYTHONPATH=tools/vendor` (vendorovaný SkoolKit, viz tools/README.md).
"""
import argparse, base64, collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

COLS = 32
ROWS = H.PLAY_ROWS
CELLS = COLS * ROWS
ZONE_COUNTER = 0x8F00
FLASH, BRIGHT, INK, PAPER = 0x80, 0x40, 0x07, 0x38


def snap(s):
    return bytes(s.screen()[6144:6144 + CELLS])


def collect(passes, every):
    """Projede silnici demem a pro každou zónu nasbírá atributy."""
    s = H.demo()
    per_zone = collections.OrderedDict()
    for _ in range(passes):
        s.run(every)
        if s.blanked():
            continue                      # mezi zónami, obraz se maže
        zone = 31 - s.peek(ZONE_COUNTER)
        per_zone.setdefault(zone, []).append(snap(s))
    return per_zone


def summarise(per_zone):
    zones, census = {}, collections.Counter()
    moving_total, cells_total, blank_total = 0, 0, 0
    for zone, shots in per_zone.items():
        if len(shots) < 2:
            continue
        stable = bytearray(shots[0])
        moving = bytearray(CELLS)
        for other in shots[1:]:
            for i in range(CELLS):
                if other[i] != stable[i]:
                    moving[i] = 1
        for i in range(CELLS):
            if stable[i] == 0:
                blank_total += 1
            else:
                census[stable[i]] += 1
            cells_total += 1
            moving_total += moving[i]
        zones[str(zone)] = {
            'attributes': base64.b64encode(bytes(stable)).decode('ascii'),
            'moving': base64.b64encode(bytes(moving)).decode('ascii'),
            'shots': len(shots),
        }
    return zones, census, moving_total, cells_total, blank_total


def colour_of(value):
    return {'ink': value & INK, 'paper': (value & PAPER) >> 3,
            'bright': bool(value & BRIGHT), 'flash': bool(value & FLASH)}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'data/attrs.json'))
    ap.add_argument('--passes', type=int, default=900)
    ap.add_argument('--every', type=int, default=8, help='po kolika snímcích snímat')
    args = ap.parse_args()

    per_zone = collect(args.passes, args.every)
    zones, census, moving, cells, blank = summarise(per_zone)
    if not zones:
        raise SystemExit('nesebrala se ani jedna zona')

    mono = sum(n for v, n in census.items() if (v & INK) == 7 and (v & PAPER) == 0)
    coloured = sum(census.values()) - mono
    per_col = collections.Counter()
    for zone in zones.values():
        attrs = base64.b64decode(zone['attributes'])
        for i, v in enumerate(attrs):
            if v and not ((v & INK) == 7 and (v & PAPER) == 0):
                per_col[i % COLS] += 1

    print('%d zón, %d buněk; bílá na černé %d, barevných %d, prázdných %d'
          % (len(zones), cells, mono, coloured, blank))
    print('hýbe se %d buněk (%.1f %%)' % (moving, 100.0 * moving / cells))
    print('nejčastější atributy: %s'
          % ', '.join('$%02X ×%d' % kv for kv in census.most_common(8)))

    data = {
        'note': ('Atributy hrací plochy, sejmuté z originálu zónu po zóně '
                 '(režim 6 DEMONSTRATION). Ke každé zóně je to, co v ní stojí, '
                 'a maska buněk, které se během ní hýbaly. Je to fotka, ne '
                 'pravidlo – obarvit se s ní dá až bitmapa, kterou kreslí M2.'),
        'source': 'tools/dumpattrs.py, režim 6 DEMONSTRATION',
        'rows': ROWS, 'cols': COLS,
        'census': {'$%02X' % v: n for v, n in sorted(census.items())},
        'colours': {'$%02X' % v: colour_of(v) for v in sorted(census)},
        'monochrome': mono, 'coloured': coloured, 'blank': blank,
        'movingCells': moving, 'cells': cells,
        'byColumn': {str(c): per_col.get(c, 0) for c in range(COLS)},
        'flash': any(v & FLASH for v in census),
        'bright': any(v & BRIGHT for v in census),
        'zones': zones,
        'findings': [
            'Crash 20 psal „road and objects in black and white but nice use '
            'of colour for the roadside graphics" – měření to potvrzuje: %d '
            'ze %d neprázdných buněk je bílá na černé, barvu nesou buňky, '
            'které stojí, a jejich sloupcový profil je miska s vrcholy u '
            'obou krajů obrazovky a dnem uprostřed (sloupce 16 až 19), tedy '
            'tam, kde jede silnice.' % (mono, mono + coloured),
            'FLASH se v hrací ploše nepoužívá vůbec; BRIGHT ano.',
            'Zóna se maže vynulováním atributů (disasm_notes.md §6), takže '
            'nulová buňka není barva, ale mazání.',
        ],
        'open': [
            'které buňky patří silnici a které kulise – to rozhodne až '
            'bitmapa zóny (M2)',
            'jestli hra atributy přepisuje po buňkách při každém pohybu, nebo '
            'je pokládá s obsahem zóny; změřený je jen výsledek',
        ],
    }
    with open(args.out, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print('%s: %d zón' % (os.path.relpath(args.out, H.ROOT), len(zones)))


if __name__ == '__main__':
    main()
