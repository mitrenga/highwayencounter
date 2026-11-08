#!/usr/bin/env python3
"""Vytáhne **tabulku dat silnice** z běžícího originálu → `data/highway.json` (M2).

    PYTHONPATH=tools/vendor ./tools/dumphighway.py [data/highway.json]
        [--passes N] [--list] [--zone N]

Kde objekty zón leží, byla otevřená otázka od M2 (`disasm_notes.md` §10) a
zavřela ji až M7: druhý průchod hry šlape po **240 záznamech po 16 bajtech na
`$7B00`–`$89FF`**, v témže formátu jako živá tabulka objektů na `$8A00` (§12,
§17). Tenhle nástroj tu tabulku vyjme – nic víc. **Jak se z ní zóna načítá**
(kolik záznamů, od kterého indexu, co se s nimi při přechodu stane) je pořád
neměřené a patří do `zones.json`; tady se proto neodhaduje, jen se zapisuje
obsah paměti a to, co se na něm dá ověřit.

Co nástroj kromě vyjmutí **změří**:

* **že se tabulka uvnitř zóny nemění** – přečte se, odsimuluje se `--passes`
  průchodů hlavní smyčkou (bez přechodu zóny) a přečte se znovu; rozdíl musí
  být nulový. **Mezi zónami se ale mění**: při každém přechodu do ní hra
  ukládá stav živých záznamů zpátky (`$92CE`, `tools/dumpzones.py`), takže je
  to zároveň data i **stav světa**. Vyjmuté je tedy to, čím silnice začíná;
* **že je to táž tabulka, ze které hra plní zóny** – živé záznamy z `$8A00`
  se v ní hledají na bajt přesně (§17 to naměřila z druhé strany: 12 ze 17);
* **že sedí formát §12** – bajt `+11` musí být `22 × rodina` u všech 240
  záznamů, a `+13/+14/+15` musí být kopie `x` a `y` téhož záznamu.

A co při tom měření vyšlo navíc: živý záznam **je kopie svého vzoru**. Bajty
`+0` až `+13` sedí bajt po bajtu a `+14/+15`, které §12 nechala jako „pevnou
dvojici (x, y)", nesou v živé tabulce **adresu vzoru** (`$7B00 + 16 × index`).
Načtení zóny tedy nic nedopočítává – kopíruje. Které záznamy a kdy, je pořád
`zones.json`.

Rodiny (horní bajt druhu bez bitu 4, §16) se jen sečtou; co která kreslí,
rozhodne až spárování se sprity, a to je taky `zones.json`.
"""
import argparse, base64, collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

TABLE = 0x7B00          # tabulka dat silnice (disasm_notes.md §17)
TABLE_END = 0x8A00      # končí přesně tam, kde začíná živá tabulka (§12)
RECORD = H.ENTITY_SIZE  # 16 B, týž formát jako živá tabulka
COUNT = (TABLE_END - TABLE) // RECORD    # 240
LIVE_SLOTS = 48         # kolik míst živé tabulky číst při křížové kontrole
INACTIVE_X = 0xFE       # v živé tabulce prázdné místo; konec tabulky je $FF
RUNTIME = os.path.join(H.ROOT, 'build/highwayencounter-run.bin')  # RAM $4000-


def decode(raw, index):
    """Jeden šestnáctibajtový záznam podle §12 – tytéž bajty, jen pojmenované."""
    cls = raw[5] | (raw[6] << 8)
    return {
        'index': index,
        'at': '$%04X' % (TABLE + index*RECORD),
        'x': raw[0],
        'y': raw[1] | (raw[2] << 8),
        'depth': raw[3] | (raw[4] << 8),
        'cls': '$%04X' % cls,
        'family': (cls >> 8) & ~0x10,
        'dir': raw[7],
        'speed': raw[8],
        'phase': raw[9],
        'kind': raw[10],
        'row': raw[11],
        'extra': raw[12],
        'spawn': {'x': raw[13], 'y': raw[14] | (raw[15] << 8)},
    }


def read_table(memory):
    block = bytes(memory[TABLE:TABLE_END])
    return block, [decode(block[i*RECORD:(i+1)*RECORD], i) for i in range(COUNT)]


def live_records(session):
    """Živá tabulka `$8A00` – jen obsazená místa (`x` pod `$FE`, §16)."""
    start = session.peek(0x8F01) | (session.peek(0x8F02) << 8)
    raw = session.peek(start, LIVE_SLOTS*RECORD)
    out = []
    for i in range(LIVE_SLOTS):
        e = raw[i*RECORD:(i+1)*RECORD]
        if e[0] == 0xFF:
            break
        if e[0] >= INACTIVE_X:
            continue
        out.append((i, e))
    return start, out


def check_format(records):
    """Co §12 a §16 o formátu tvrdí, ověřené na všech 240 záznamech."""
    row = [r for r in records if r['row'] != 22*r['family']]
    spawn = [r for r in records
             if r['spawn']['x'] != r['x'] or r['spawn']['y'] != r['y']]
    return {
        'rowIsFamilyTimes22': not row,
        'spawnIsRecordPosition': not spawn,
        'exceptions': [r['index'] for r in row + spawn],
    }


def match_live(block, live):
    """Živé záznamy `$8A00` hledané v tabulce dat silnice.

    Hledá se na `(x, y, druh)`; záznam, který se od načtení zóny pohnul, se
    nenajde (§17 to naměřila z druhé strany: 12 ze 17). U těch, které se najdou,
    se pak měří, **čím se živý záznam od svého vzoru liší** – a odpověď je, že
    ničím až na poslední dva bajty: `+0` až `+13` sedí bajt po bajtu a
    `+14/+15` živý záznam nese **adresu svého vzoru** v tabulce
    (`$7B00 + 16 × index`). Tím se zavírá i to, co §12 nechala u `+13/+14/+15`
    otevřené jako „pevnou dvojici (x, y)": v tabulce dat silnice je to kopie
    pozice, v živé tabulce ukazatel zpátky.
    """
    triple, misses, pairs = 0, [], []
    prefix_ok, pointer_ok = 0, 0
    offsets = collections.Counter()
    for slot, e in live:
        found = None
        for i in range(COUNT):
            t = block[i*RECORD:(i+1)*RECORD]
            if t[0:3] == e[0:3] and t[5:7] == e[5:7]:
                found = (i, t)
                break
        if found is None:
            misses.append(slot)
            continue
        index, t = found
        triple += 1
        for o in range(RECORD):
            if t[o] != e[o]:
                offsets[o] += 1
        prefix_ok += t[0:14] == e[0:14]
        pointer_ok += (e[14] | (e[15] << 8)) == TABLE + index*RECORD
        pairs.append({'slot': slot, 'record': index,
                      'pointer': '$%04X' % (e[14] | (e[15] << 8))})
    return {
        'live': len(live),
        'positionAndClass': triple,
        'notFound': misses,
        'bytes0to13Identical': prefix_ok,
        'tailIsPointerToRecord': pointer_ok,
        'differingOffsets': {str(k): v for k, v in sorted(offsets.items())},
        'pairs': pairs,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dst', nargs='?', default=os.path.join(H.ROOT, 'data/highway.json'))
    ap.add_argument('--passes', type=int, default=200,
                    help='kolik průchodů hlavní smyčkou odsimulovat pro kontrolu '
                         'neměnnosti tabulky (0 = nekontrolovat)')
    ap.add_argument('--list', action='store_true', help='vypsat všechny záznamy')
    ap.add_argument('--zone', type=int, help='vypsat záznamy, jejichž y padne do zóny N')
    ap.add_argument('--rebuild', action='store_true', help='nabootovat hru znovu')
    args = ap.parse_args()

    session = H.gameplay(rebuild=args.rebuild)
    block, records = read_table(session.simulator.memory)

    # 1. je to táž tabulka, jakou má hra po nahrání z kazety?
    tape = None
    if os.path.isfile(RUNTIME):
        ram = open(RUNTIME, 'rb').read()
        image = ram[TABLE-0x4000:TABLE_END-0x4000]
        tape = {'file': os.path.relpath(RUNTIME, H.ROOT),
                'bytesEqual': sum(1 for a, b in zip(block, image) if a == b),
                'bytes': len(block)}

    # 2. živé záznamy rozehrané hry se v ní musí najít
    start, live = live_records(session)
    matched = match_live(block, live)

    # 3. tabulka se za běhu nemění
    stable = None
    if args.passes:
        for _ in range(args.passes):
            try:
                session.step()
            except RuntimeError:
                break
        again, _ = read_table(session.simulator.memory)
        stable = {'passes': args.passes,
                  'bytesChanged': sum(1 for a, b in zip(block, again) if a != b),
                  'note': 'uvnitř zóny se tabulka nemění; při přechodu do ní hra '
                          'ukládá stav živých záznamů zpátky ($92CE, data/zones.json)'}

    zone_length = 176
    objects = os.path.join(H.ROOT, 'data/objects.json')
    if os.path.isfile(objects):
        with open(objects, encoding='utf-8') as f:
            zone_length = json.load(f)['zone']['length']

    families = collections.Counter(r['family'] for r in records)
    classes = collections.Counter(r['cls'] for r in records)
    kinds = collections.Counter(r['kind'] for r in records)
    zones = collections.Counter(r['y'] // zone_length for r in records)

    data = {
        'note': 'tabulka dat silnice originálu (tools/dumphighway.py): 240 záznamů '
                'po 16 bajtech na $7B00-$89FF, týž formát jako živá tabulka objektů '
                'na $8A00 (disasm_notes.md §12, §17). Je to obsah paměti, nic se '
                'nedokresluje ani nedopočítává.',
        'source': 'build/gameplay.z80 (rozehraná hra)',
        'table': {'at': '$%04X' % TABLE, 'to': '$%04X' % (TABLE_END-1),
                  'count': COUNT, 'recordBytes': RECORD,
                  'endsWhereLiveTableBegins': '$%04X' % TABLE_END,
                  'terminator': 'žádný – všech 240 míst je obsazených (x je 0-72, '
                                'nikde $FE ani $FF, kterými se značí prázdno a konec '
                                'v živé tabulce)'},
        'record': {
            '+0': 'x napříč silnicí (0-72)',
            '+1,+2': 'y podél silnice, 16 bitů',
            '+3,+4': 'posun v kreslicím bufferu',
            '+5,+6': 'druh objektu; horní bajt bez bitu 4 je rodina (§16)',
            '+7': 'směr 0-7',
            '+8': 'rychlost 0-2',
            '+9': 'posun spritu v buňce',
            '+10': 'druh pro volbu spritu',
            '+11': '22 × rodina – řádek matice srážek na $9000',
            '+12': 'u rodiny 4 dráha, u rodiny 5 směr vzniku, jinak 0',
            '+13,+14,+15': 'v tabulce dat silnice kopie x a y téhož záznamu '
                           '(změřeno tady, na všech 240); v živé tabulce $8A00 je '
                           '+13 táž kopie x, ale +14/+15 nese adresu vzoru v téhle '
                           'tabulce ($7B00 + 16 × index) – tím je zavřená „pevná '
                           'dvojice (x, y)", kterou §12 nechala otevřenou',
        },
        'records': records,
        'raw': base64.b64encode(block).decode('ascii'),
        'summary': {
            'families': {str(k): v for k, v in sorted(families.items())},
            'classes': {k: v for k, v in sorted(classes.items())},
            'kinds': {str(k): v for k, v in sorted(kinds.items())},
            'speeds': {str(k): v for k, v in
                       sorted(collections.Counter(r['speed'] for r in records).items())},
            'y': {'min': min(r['y'] for r in records),
                  'max': max(r['y'] for r in records)},
            'byZone': {str(k): v for k, v in sorted(zones.items())},
            'zoneLength': zone_length,
            'zoneNote': 'zóna = y // %d je aritmetika z objects.json, ne změřené '
                        'pravidlo načítání: tabulka podle y **není seřazená** '
                        '(%d míst, kde y klesne), takže index záznamu a číslo zóny '
                        'spolu přímo nesouvisí. Co z toho hra při přechodu bere, '
                        'je zones.json.'
                        % (zone_length,
                           sum(1 for a, b in zip(records, records[1:])
                               if b['y'] < a['y'])),
        },
        'verification': {
            'formatHolds': check_format(records),
            'againstRuntimeImage': tape,
            'againstLiveTable': dict(matched, liveTableAt='$%04X' % start),
            'unchangedInsideZone': stable,
        },
        'open': [
            'který druh je barel, bedna, skleněná krychle nebo zeď – to řekne až '
            'spárování se sprity (spriteframes.json)',
        ],
    }

    with open(args.dst, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

    print('%s: %d záznamů po %d B z $%04X-$%04X'
          % (os.path.relpath(args.dst, H.ROOT), COUNT, RECORD, TABLE, TABLE_END-1))
    print('  rodiny: %s' % ', '.join('%d×%d' % (v, k) for k, v in sorted(families.items())))
    print('  y %d-%d, zóny %d-%d, %d zón zastoupeno'
          % (data['summary']['y']['min'], data['summary']['y']['max'],
             min(zones), max(zones), len(zones)))
    fmt = data['verification']['formatHolds']
    print('  formát §12: +11 = 22×rodina %s, +13/+14/+15 = kopie x,y %s'
          % ('ANO' if fmt['rowIsFamilyTimes22'] else 'NE',
             'ANO' if fmt['spawnIsRecordPosition'] else 'NE'))
    if tape:
        print('  proti %s: %d z %d B shodných'
              % (tape['file'], tape['bytesEqual'], tape['bytes']))
    print('  živá tabulka $%04X: %d záznamů, %d se najde na (x,y,druh); '
          'z nich %d sedí v bajtech +0..+13 a %d má na +14/+15 adresu svého vzoru'
          % (start, matched['live'], matched['positionAndClass'],
             matched['bytes0to13Identical'], matched['tailIsPointerToRecord']))
    if stable:
        print('  uvnitř zóny: po %d průchodech změněno %d B (musí být 0; '
              'při přechodu zóny se do ní zapisuje zpět)'
              % (stable['passes'], stable['bytesChanged']))

    if args.list or args.zone is not None:
        for r in records:
            if args.zone is not None and r['y'] // zone_length != args.zone:
                continue
            print('  %3d %s x %2d y %4d zóna %2d druh %s rodina %2d '
                  'směr %d rychlost %d sprit $%02X'
                  % (r['index'], r['at'], r['x'], r['y'], r['y'] // zone_length,
                     r['cls'], r['family'], r['dir'], r['speed'], r['kind']))


if __name__ == '__main__':
    main()
