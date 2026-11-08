#!/usr/bin/env python3
"""Odměří **izometrickou projekci a řazení do hloubky** → `data/projection.json` (M0b/M2).

Vychází z §8: hrací plocha se skládá v bufferu na `$E900` (32 B na pixelovou
řádku) a každý záznam objektu si nese adresu, kam se má sprit nakreslit, hotovou
v bajtech `+3/+4` (`$990D` k ní přičte `($8F03)`). Projekce je tedy v tom, kdo tu
adresu spočítal – a to se dá **ověřit proti hře samotné**: pro každý viditelný
záznam se dopředu spočítá řádek, sloupec a fáze posunu a porovná se s tím, co má
v paměti originál.

Změřené pravidlo (`$9871`–`$98D3` a `$9933`):

    d     = y − ($8F09)                 vzdálenost od kamery, musí být 0..255
    klíč  = (d >> 1) + (x >> 1) + 1     hloubka, po ní se řadí
    řádek = 158 − ((d + x) >> 1)        pixelová řádka, na které sprit stojí
    px    = d − x + 24                  vodorovně, v pixelech
    sloupec = px >> 3,  posun = px & 6  lichý pixel se zahodí, fáze = 2 × posun

Řazení do hloubky je jednoduchá vkládací setřídění do seznamu na `$8D52`
(trojice `klíč, adresa záznamu`, klíč klesá, nula končí): kreslí se odzadu
dopředu, tedy malíř. Vynechává se záznam s `x = $FE`, `$FF` seznam ukončuje
a vynechá se i `(IX+6)` rovné `$16` nebo `$19`.

    PYTHONPATH=tools/vendor ./tools/dumpproj.py [data/projection.json]
        [--frames 4000] [--mode demo|player]

`--frames` je počet **průchodů hlavní smyčkou**, ne snímků: čte se vždycky na
`$98DC`, kde je seznam setříděný a hotový.
"""
import argparse, collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib                                                # noqa: E402

BUFFER = 0xE900         # buffer hrací plochy (§8)
BUFFER_ROW = 32
CAMERA = 0x8F09         # w($8F09) – souřadnice, od které se počítá viditelnost
BASE = 0x8F03           # w($8F03) – přičítá se k záznamu[+3/+4] (`$990D`)
LIST = 0x8D52           # seznam setříděný do hloubky, trojice po 3 bajtech
SORTED_PC = 0x98DC      # tady je seznam hotový a začíná se kreslit
ENTITIES = 0x8A00
ENTITY_SIZE = 16
SKIP_AT_6 = (0x16, 0x19)
ANIM = 0x8F00           # $8F00 + druh = animační bajt druhu (§8)
KINDS = range(0x0D, 0x14)
SHOT_SLOTS = (6, 7, 8)
ROW_CONST = 158         # řádek = ROW_CONST − (d>>1) − (x>>1)
COL_CONST = 24          # px = d − x + COL_CONST


def project(x, y, camera):
    """Vrátí `(klíč, řádek, sloupec, fáze)`, nebo None, když je objekt za oknem."""
    d = (y - camera) & 0xFFFF
    if d > 0xFF:
        return None
    key = (d >> 1) + (x >> 1) + 1
    row = ROW_CONST - ((d + x) >> 1)
    px = d - x + COL_CONST
    # posun je vždycky sudý: lichý pixel hra zahodí (x i d vstupují do
    # klíče taky jen po posunu o bit, takže se zahazuje důsledně)
    return key, row, px >> 3, 2*(px & 6)


def visible(record):
    """Kreslí hra tenhle záznam? (`$9866`–`$988E` bez okna kamery.)"""
    return record[0] < 0xFE and record[6] not in SKIP_AT_6


def check(session, stats, diffs):
    """Porovná předpověď se stavem paměti pro všechny záznamy jednoho průchodu."""
    memory = session.simulator.memory
    camera = memory[CAMERA] | memory[CAMERA+1] << 8
    base = memory[BASE] | memory[BASE+1] << 8
    # seznam setříděný do hloubky, jak si ho hra postavila
    order = []
    addr = LIST
    while memory[addr]:
        order.append((memory[addr], memory[addr+1] | memory[addr+2] << 8))
        addr += 3
    for key, record_addr in order:
        record = bytes(memory[record_addr:record_addr+ENTITY_SIZE])
        x, y = record[0], record[1] | record[2] << 8
        got_pos = record[3] | record[4] << 8
        got_phase = record[9]
        want = project(x, y, camera)
        stats['records'] += 1
        if want is None:
            diffs.append(('mimo okno, a přesto v seznamu', record_addr, x, y, camera))
            continue
        want_key, row, col, phase = want
        got_off = ((got_pos + base) & 0xFFFF) - BUFFER
        want_off = row*BUFFER_ROW + col
        if want_key != key:
            diffs.append(('klíč', record_addr, key, want_key, None))
        if want_off != got_off:
            diffs.append(('adresa', record_addr, got_off, want_off,
                          (x, y, camera)))
        if phase != got_phase:
            diffs.append(('fáze', record_addr, got_phase, phase, (x, y, camera)))
        stats['keys'] += want_key == key
        stats['addresses'] += want_off == got_off
        stats['phases'] += phase == got_phase
    # je seznam vážně setříděný a je v něm všechno, co má být?
    keys = [k for k, _ in order]
    if keys != sorted(keys, reverse=True):
        diffs.append(('seznam není setříděný', LIST, keys, None, None))
    stats['lists'] += 1
    stats['listed'] += len(order)
    window = 0
    for index in range(0, 256):
        record = bytes(memory[ENTITIES+index*ENTITY_SIZE:
                              ENTITIES+(index+1)*ENTITY_SIZE])
        if record[0] == 0xFF:
            break
        if visible(record) and project(record[0], record[1] | record[2] << 8,
                                      camera) is not None:
            window += 1
    if window != len(order):
        diffs.append(('počet viditelných', LIST, len(order), window, None))
    return window


def animation(passes):
    """Odměří **animaci podle druhu**: bajt `$8F00 + druh` volí rámec v tabulce
    `$7A00` (§8). Vrátí pro každý druh posloupnost hodnot, jak dlouho každá
    vydrží a jestli se cyklí, nebo kmitá tam a zpět."""
    # vlastní běh: projekce projede demo až do konce, tady je potřeba čerstvé
    session = highwaylib.demo()
    memory = session.simulator.memory
    seqs = {kind: [] for kind in KINDS}
    for _ in range(passes):
        if session.run_to(SORTED_PC, frames=30) is None:
            break
        for kind in KINDS:
            seqs[kind].append(memory[ANIM + kind])
    out = {}
    for kind, values in seqs.items():
        if not values:
            continue
        runs = []
        current, count = values[0], 0
        for value in values:
            if value == current:
                count += 1
            else:
                runs.append((current, count))
                current, count = value, 1
        runs.append((current, count))
        # krajní úseky jsou nedoběhnuté, do periody se nepočítají
        lengths = collections.Counter(n for _, n in runs[1:-1])
        steps = [(a[0], b[0]) for a, b in zip(runs, runs[1:])]
        top = max(values)
        # kmitání pozná krok z nejvyšší hodnoty o dvě dolů; skok z nejvyšší
        # na nulu je naopak přetečení kruhu
        down = any(a == top and b == top - 2 for a, b in steps)
        out['$%02X' % kind] = {
            'values': sorted(set(values)),
            'holdPasses': lengths.most_common(1)[0][0] if lengths else None,
            # strojově čitelně, ať se z toho dá udělat animace v remaku
            'pattern': 'pingpong' if down and top else 'cycle',
            'patternNote': ('kmitá tam a zpět' if down and top
                            else 'jde v kruhu a přeteče na nulu'),
            'step': 2,
            'top': top,
        }
    return out


def shot_kinds():
    """Odměří, jaký **druh** má výstřel v každém ze svých tří slotů – na něm
    závisí, který rámec se mu vybere. Demo nestřílí, tak se drží SPACE ve hře."""
    session = highwaylib.gameplay()
    memory = session.simulator.memory
    seen = collections.defaultdict(collections.Counter)
    for _ in range(150):
        try:
            session.step(('SPACE', '1'))
        except RuntimeError:
            break
        for slot in SHOT_SLOTS:
            record = memory[ENTITIES + slot*ENTITY_SIZE:
                            ENTITIES + (slot+1)*ENTITY_SIZE]
            if record[0] < 0xFE:
                seen[slot][(record[10], record[5])] += 1
    out = {}
    for slot, counter in seen.items():
        (kind, field5), _ = counter.most_common(1)[0]
        out[str(slot)] = {'kind': '$%02X' % kind, 'field5': field5}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dst', nargs='?',
                    default=os.path.join(HERE, '..', 'data/projection.json'))
    ap.add_argument('--frames', type=int, default=1500,
                    help='kolik snímků projet (demo projede celou silnici)')
    ap.add_argument('--mode', choices=('demo', 'player'), default='demo')
    args = ap.parse_args()

    if args.mode == 'demo':
        session = highwaylib.demo()
    else:
        session = highwaylib.gameplay()
    stats = dict(records=0, keys=0, addresses=0, phases=0, lists=0, listed=0)
    diffs = []
    zones = set()
    # Čte se v jediném místě, kde je seznam hotový: na `$98DC`, tedy hned po
    # tom, co průchod dojde na konec tabulky ($FF) a začne kreslit. Uprostřed
    # průchodu je seznam rozestavěný a porovnávat by se nedalo.
    passes = 0
    while passes < args.frames:
        if session.run_to(SORTED_PC, frames=30) is None:
            print('nedoslo se na $%04X – konec hry nebo zastavena hra' % SORTED_PC)
            break
        passes += 1
        memory = session.simulator.memory
        zones.add(memory[0x8F00])
        check(session, stats, diffs)
        if len(diffs) > 20:
            break

    args.frames = passes
    print('projito %d pruchodu, %d zon, %d seznamu, %d zaznamu'
          % (passes, len(zones), stats['lists'], stats['records']))
    print('  klice     %6d/%d' % (stats['keys'], stats['records']))
    print('  adresy    %6d/%d' % (stats['addresses'], stats['records']))
    print('  faze      %6d/%d' % (stats['phases'], stats['records']))
    print('  rozdilu:  %d' % len(diffs))
    for d in diffs[:20]:
        print('   ', d)

    print('animace podle druhu a sprity vystrelu...')
    anim = animation(300)
    shots = shot_kinds()

    data = {
        'note': 'izometrická projekce a řazení do hloubky, odměřené na běžícím '
                'originálu (tools/dumpproj.py); ověřené proti tomu, co má hra '
                'sama v paměti – adresa spritu, fáze posunu i pořadí kreslení',
        'source': 'režim %s, %d průchodů, %d zón' % (args.mode, args.frames, len(zones)),
        'buffer': {'at': '$%04X' % BUFFER, 'rowBytes': BUFFER_ROW, 'rows': 152},
        'projection': {
            'distance': 'd = y − w($%04X), objekt se kreslí jen pro 0 ≤ d ≤ 255' % CAMERA,
            'row': 'řádek = %d − ((d + x) >> 1)' % ROW_CONST,
            'pixel': 'px = d − x + %d' % COL_CONST,
            'column': 'sloupec = px >> 3',
            'shift': 'posun = px & 6 – lichý pixel hra zahodí; '
                     'fáze v záznamu (+9) = 2 × posun, tedy 0, 4, 8, 12',
            'rowConst': ROW_CONST, 'colConst': COL_CONST,
            'slope': '2 : 1 – krok 1 v x je 1 px vodorovně a půl řádky svisle',
        },
        'depth': {
            'key': 'klíč = (d >> 1) + (x >> 1) + 1',
            'row': 'klíč půlí x a d každé zvlášť (`SRL`/`SRL`/`ADD` na $9892), '
                   'řádek půlí jejich součet – když jsou obě lichá, liší se '
                   'o jednu řádku',
            'list': {'at': '$%04X' % LIST, 'entry': 'klíč, adresa záznamu (3 B)',
                     'order': 'klíč klesá, kreslí se v pořadí seznamu (odzadu '
                              'dopředu), nula seznam ukončuje'},
            'skip': {'x': '$FE vynechat, $FF ukončit tabulku',
                     'field6': ['$%02X' % v for v in SKIP_AT_6]},
        },
        'sprite': {
            'index': 'bajtový posun do tabulky $7A00 = '
                     '(($8F00 + druh) + záznam[+5]) AND $FF; rámec je slovo, '
                     'které tam leží (data/spriteframes.json)',
            'animation': anim,
            'animationNote': 'animační bajt druhu; u řízeného Vortona ($0E) '
                             'to není animace, ale 2 × směr – tedy osm '
                             'natočení, změřeno na otáčení',
            'controlledVorton': '$8F0E = 2 × směr',
            'shotSlots': shots,
        },
        'verified': {'passes': args.frames, 'zones': len(zones),
                     'records': stats['records'], 'lists': stats['lists'],
                     'keys': stats['keys'], 'addresses': stats['addresses'],
                     'phases': stats['phases'], 'differences': len(diffs)},
    }
    with open(args.dst, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('%s: zapsano' % os.path.relpath(args.dst, highwaylib.ROOT))


if __name__ == '__main__':
    main()
