#!/usr/bin/env python3
"""Odměří, **jak se zóna plní z tabulky dat silnice** → `data/zones.json` (M2).

    PYTHONPATH=tools/vendor ./tools/dumpzones.py [data/zones.json]
        [--zones 31] [--no-verify]

`dumphighway.py` tabulku vyjmul (`data/highway.json`), tohle je ta druhá
polovina: **kdy a které záznamy si z ní zóna vezme**. Otevřené to bylo od M2
(`disasm_notes.md` §10, pak §17) a zavřelo se to tak, že se rutina našla –
`tracedraw.py` s logující pamětí nad rozsahem živé tabulky ukázal, že do
`$8A90` a dál zapisuje `LDIR` na `$93E3`, volaný z `$92CE` – a přečetla:

    $93B7  LD IX,$7B00      ; scan začíná vždy na začátku tabulky
    $93BB  LD DE,$8A90      ; cíl je vždy 9. místo živé tabulky
    $93BE  LD A,$2C         ; a vejde se jich nejvýš 44
    $93C1  LD A,(IX+$00)    ; x záznamu
    $93C4  CP $FE           ; prázdné místo se přeskočí
    $93C8  HL = (IX+1,2)    ; y záznamu
    $93CE  BC = ($8F05)     ; okno světa
    $93D3  SBC HL,BC        ; y - okno
    $93D5  LD A,H / CP $02  ; **bere se, jen když je rozdíl pod 512**
    $93DA  BC = $000E
    $93E3  LDIR             ; zkopíruje bajty +0 až +13
    $93E5  (DE),IXl / IXh   ; a za ně adresu vzoru
    $93FD  LD A,$FF / (DE),A ; za poslední záznam značka konce

Kolem toho jsou další dvě rutiny, bez kterých by pravidlo nedávalo smysl:

* **`$92CE` zápis zpět, ještě před načtením.** Každý živý záznam od 9. místa
  se `LDIR`em (14 bajtů) uloží zpátky do záznamu, na který ukazuje jeho
  `+14/+15`. Tabulka na `$7B00` tedy **není jen data, je to stav světa**:
  strčený barel zůstane strčený a zničená věc zničená i po návratu do zóny.
* **`$9400` úklid, hned po načtení.** Projde tabulku a každému záznamu, jehož
  `+5` padne do `$80`–`$DF` (dolní bajt druhu se při zániku posouvá od `$80`
  po osmi, §12), nastaví `x` na `$FE` a shodí bit 7 rychlosti – tím se místo
  uvolní a zničená věc se už nenačte.

A `$92F5` k tomu počítá zónu a okno: `y` se zdola omezí na 176, pak se po 176
odečítá, dokud zbytek nespadne pod 176. Číslo kroků je zóna (`$8F1C`, do
panelu se ořezává na 32), `$8F07` je konec zóny, `$8F09 = $8F07 − 48` je
kamera a `$8F05 = $8F09 − 128` je okno. To potvrzuje, co M4 naměřila zvenčí
(`objects.json`: zóna = `y // 176`, kamera = okno + 128).

Konstanty se **čtou z bajtů hry**, ne opisují, a pravidlo se ověřuje proti
originálu: demo projede celou silnici a v každém přechodu se porovná, které
záznamy pravidlo vybere a které si vzala hra.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402
import dumphighway as D                                           # noqa: E402

LOAD = 0x93B7           # načtení zóny z tabulky dat silnice
WRITEBACK = 0x92CE      # zápis živých záznamů zpátky do tabulky
CLEANUP = 0x9400        # úklid zaniklých záznamů
ZONECALC = 0x92F5       # výpočet zóny, okna a kamery
LIVE = 0x8A00
FIRST_SLOT = 9          # $8A90 – devátý záznam živé tabulky
WINDOW = 0x8F05

# co se v rutině čte: adresa -> (očekávané opcody, offset konstanty, název)
CONSTANTS = [
    (0x93B7, [0xDD, 0x21], 2, 2, 'source', 'začátek tabulky, ze které se scanuje'),
    (0x93BB, [0x11], 1, 2, 'destination', 'kam v živé tabulce se sype'),
    (0x93BE, [0x3E], 1, 1, 'limit', 'nejvíc záznamů na zónu'),
    (0x93C4, [0xFE], 1, 1, 'emptyX', 'x, od kterého výš je záznam prázdný'),
    (0x93D6, [0xFE], 1, 1, 'spanHigh', 'horní bajt rozdílu y − okno, práh'),
    (0x93DA, [0x01], 1, 2, 'copyBytes', 'kolik bajtů se ze záznamu kopíruje'),
    (0x93FD, [0x3E], 1, 1, 'terminator', 'značka konce živé tabulky'),
    (0x940A, [0xFE], 1, 1, 'deadFrom', 'dolní bajt druhu: od téhle hodnoty zánik'),
    (0x940E, [0xFE], 1, 1, 'deadTo', '...a pod tuhle'),
]


def read_constants(memory):
    """Konstanty rutiny z bajtů hry – a kontrola, že na těch adresách opravdu
    stojí ta instrukce, kterou disassembly čekala."""
    out, bad = {}, []
    for addr, opcodes, off, size, name, note in CONSTANTS:
        got = list(memory[addr:addr+len(opcodes)])
        if got != opcodes:
            bad.append('$%04X: %s misto %s'
                       % (addr, ' '.join('%02X' % b for b in got),
                          ' '.join('%02X' % b for b in opcodes)))
        value = memory[addr+off]
        if size == 2:
            value |= memory[addr+off+1] << 8
        out[name] = {'value': value, 'at': '$%04X' % addr, 'note': note}
    return out, bad


def load_zone(table, window, limit, span, empty_x, copy_bytes):
    """Pravidlo rutiny `$93B7`, přepsané tak, jak ho hra vykoná."""
    taken = []
    for index in range(len(table)//16):
        record = table[index*16:(index+1)*16]
        if record[0] >= empty_x:
            continue
        y = record[1] | (record[2] << 8)
        if ((y - window) & 0xFFFF) >= span:
            continue
        taken.append(index)
        if len(taken) == limit:
            break
    return taken


def verify(rule, zones):
    """Projede demem celou silnici a v každém přechodu porovná, které záznamy
    pravidlo vybere, s tím, které si vzala hra (ukazatel `+14/+15`)."""
    s = H.demo()
    seen, records, diffs, prev = 0, 0, [], None
    for _ in range(6000):
        try:
            s.step()
        except RuntimeError:
            break
        zone = s.peek(0x8F00)
        if zone == prev:
            continue
        prev = zone
        window = s.peek(WINDOW) | (s.peek(WINDOW+1) << 8)
        table = s.peek(D.TABLE, D.COUNT*D.RECORD)
        want = load_zone(table, window, rule['limit'], rule['span'],
                         rule['emptyX'], rule['copyBytes'])
        live = s.peek(LIVE, (FIRST_SLOT + rule['limit'] + 1)*16)
        got = []
        for i in range(FIRST_SLOT, FIRST_SLOT + rule['limit'] + 1):
            e = live[i*16:(i+1)*16]
            if e[0] == 0xFF:
                break
            p = e[14] | (e[15] << 8)
            got.append((p - D.TABLE)//D.RECORD if D.TABLE <= p < D.TABLE_END else None)
        seen += 1
        records += max(len(want), len(got))
        if want != got:
            diffs.append({'zone': zone, 'window': window,
                          'missing': sorted(set(want) - set(got)),
                          'extra': sorted(set(got) - set(want))})
        if zone >= zones:
            break
    return {'zones': seen, 'records': records, 'differences': len(diffs),
            'detail': diffs, 'source': '6 DEMONSTRATION (projede celou silnici)'}


def writeback_check(zones=5):
    """Že `$92CE` opravdu ukládá stav zpátky: po přechodu se porovná tabulka
    dat silnice s tím, co bylo v živé tabulce před ním."""
    s = H.demo()
    prev, before, before_live = None, None, None
    out = []
    for _ in range(3000):
        try:
            s.step()
        except RuntimeError:
            break
        zone = s.peek(0x8F00)
        if zone != prev and prev is not None:
            table = s.peek(D.TABLE, D.COUNT*D.RECORD)
            changed = [i for i in range(D.COUNT)
                       if table[i*16:(i+1)*16] != before[i*16:(i+1)*16]]
            live = {}
            for i in range(FIRST_SLOT, 54):
                e = before_live[i*16:(i+1)*16]
                if e[0] == 0xFF:
                    break
                p = e[14] | (e[15] << 8)
                if D.TABLE <= p < D.TABLE_END:
                    live[(p - D.TABLE)//D.RECORD] = e[:14]
            out.append({'from': prev, 'to': zone, 'changed': len(changed),
                        'equalToLiveRecord': sum(1 for i in changed
                                                 if table[i*16:i*16+14] == live.get(i)),
                        'records': changed})
            if prev >= zones:
                break
        before = s.peek(D.TABLE, D.COUNT*D.RECORD)
        before_live = s.peek(LIVE, 54*16)
        prev = zone
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dst', nargs='?', default=os.path.join(H.ROOT, 'data/zones.json'))
    ap.add_argument('--zones', type=int, default=31, help='po kterou zónu ověřovat')
    ap.add_argument('--no-verify', action='store_true', help='jen přečíst konstanty')
    args = ap.parse_args()

    session = H.gameplay()
    constants, bad = read_constants(session.simulator.memory)
    if bad:
        raise SystemExit('rutina na těch adresách nestojí: ' + '; '.join(bad))

    rule = {
        'source': constants['source']['value'],
        'destinationSlot': (constants['destination']['value'] - LIVE)//16,
        'limit': constants['limit']['value'],
        'emptyX': constants['emptyX']['value'],
        'span': constants['spanHigh']['value'] << 8,
        'copyBytes': constants['copyBytes']['value'],
        'terminator': constants['terminator']['value'],
    }

    checked = None if args.no_verify else verify(rule, args.zones)
    back = None if args.no_verify else writeback_check()

    data = {
        'note': 'jak se zóna plní z tabulky dat silnice (tools/dumpzones.py). '
                'Konstanty jsou přečtené z bajtů rutiny $93B7, ne opsané, '
                'a pravidlo je ověřené proti originálu na celé silnici.',
        'source': 'build/gameplay.z80 (rozehraná hra), rutiny $92CE, $92F5, $93B7, $9400',
        'routines': {
            'writeBack': '$%04X' % WRITEBACK,
            'zoneAndWindow': '$%04X' % ZONECALC,
            'load': '$%04X' % LOAD,
            'cleanup': '$%04X' % CLEANUP,
            'order': ['writeBack', 'zoneAndWindow', 'load', 'cleanup'],
        },
        'load': {
            'from': '$%04X' % rule['source'],
            'toSlot': rule['destinationSlot'],
            'scan': 'celá tabulka od začátku, po 16 bajtech, v pořadí tabulky – '
                    'nic se nepředpočítává a nikde se nezačíná od minula',
            'skipEmptyX': '$%02X' % rule['emptyX'],
            'takeWhen': '((y - okno) & $FFFF) < %d' % rule['span'],
            'span': rule['span'],
            'spanNote': 'porovnává se horní bajt rozdílu proti %d, takže se bere '
                        'pás %d půljednotek za oknem – víc než tři zóny dopředu '
                        '(zóna je 176) a nic za oknem dozadu, protože odečtení '
                        'podteče' % (constants['spanHigh']['value'], rule['span']),
            'copyBytes': rule['copyBytes'],
            'pointerAt': '+14/+15 živého záznamu = adresa vzoru',
            'limit': rule['limit'],
            'limitNote': 'víc než %d záznamů se do zóny nevejde; s devíti pevnými '
                         'místy (hráč, konvoj, výstřely) má živá tabulka nejvýš '
                         '%d míst a za nimi značku konce'
                         % (rule['limit'], FIRST_SLOT + rule['limit']),
            'terminator': '$%02X' % rule['terminator'],
        },
        'writeBack': {
            'when': 'ještě před načtením nové zóny',
            'what': 'každý živý záznam od %d. místa až po značku konce se %d bajty '
                    'uloží zpátky do záznamu, na který ukazuje jeho +14/+15'
                    % (FIRST_SLOT, rule['copyBytes']),
            'meaning': 'tabulka na $7B00 není jen data, je to **stav světa**: '
                       'strčený barel zůstane strčený a zaniklá věc zaniklá '
                       'i po návratu do zóny',
            'measured': back,
        },
        'cleanup': {
            'when': 'hned po načtení',
            'what': 'záznam tabulky, jehož +5 padne do $%02X-$%02X, dostane '
                    'x = $%02X a shodí se mu bit 7 rychlosti'
                    % (constants['deadFrom']['value'],
                       constants['deadTo']['value'] - 1, rule['emptyX']),
            'meaning': 'dolní bajt druhu se při zániku posouvá od $80 po osmi '
                       '(disasm_notes.md §12), takže tohle je úklid zaniklých: '
                       'místo se uvolní a víckrát se nenačte',
        },
        'zoneAndWindow': {
            'clampY': 176,
            'step': 176,
            'zoneAt': '$8F1C', 'zonePanelAt': '$8F00', 'zonePanelMax': 32,
            'zoneEndAt': '$8F07', 'cameraAt': '$8F09', 'windowAt': '$%04X' % WINDOW,
            'camera': 'konec zóny − 48', 'window': 'kamera − 128',
            'note': 'potvrzuje, co M4 naměřila zvenčí (objects.json): zóna je '
                    'y // 176 a kamera je okno + 128',
        },
        'constants': constants,
        'verification': checked,
        'open': [
            'co který druh kreslí – rámec se s druhem spojit dá (tabulka $7A00), '
            'ale pojmenované to není',
        ],
    }

    with open(args.dst, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

    print('%s: pravidlo načtení zóny z $%04X' % (os.path.relpath(args.dst, H.ROOT),
                                                 rule['source']))
    print('  scan celé tabulky, bere ((y - okno) & $FFFF) < %d, kopíruje %d B, '
          'nejvýš %d záznamů od %d. místa'
          % (rule['span'], rule['copyBytes'], rule['limit'], rule['destinationSlot']))
    print('  konstanty přečtené z bajtů rutiny: %s'
          % ', '.join('%s=%d' % (k, v['value']) for k, v in constants.items()))
    if checked:
        print('  ověření: %d zón, %d záznamů, **%d rozdílů**'
              % (checked['zones'], checked['records'], checked['differences']))
        for d in checked['detail'][:5]:
            print('    zóna %d: chybí %s, navíc %s'
                  % (d['zone'], d['missing'], d['extra']))
    if back:
        print('  zápis zpět: %s'
              % ', '.join('%d→%d %d/%d' % (b['from'], b['to'],
                                           b['equalToLiveRecord'], b['changed'])
                          for b in back))


if __name__ == '__main__':
    main()
