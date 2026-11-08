#!/usr/bin/env python3
"""Odměří **koncovou sekvenci a druhý průchod** → `data/ending.json` (M7).

    PYTHONPATH=tools/vendor ./tools/dumpending.py [--out data/ending.json]

Do M6 se všechno měřilo z první zóny: co bylo potřeba vyvolat, se dalo
naskriptovat klávesami. Konec hry ne – ten začne teprve, když **Lasertron
dojede na konec silnice**, a to je celá dohraná hra. Nástroj proto stojí na
`playrzx.py`: RZX záznam skutečného dohrání (`sources/tape/highway.rzx`) se
přehraje těsně před spuštění sekvence, uloží se snapshot (`build/ending.z80`)
a od něj se pak krokuje jako každý jiný běh – **sekvence si hru řídí sama**,
takže od téhle chvíle žádný vstup nepotřebuje a je deterministická.

Měří se stejně jako M6: co je v tabulkách a v kódu, se **přečte** (a je vidět,
z jaké adresy), a pak se to **ověří měřením** na skutečném běhu.

Co z toho vypadlo:

1. **Spouští to Lasertron, ne hráč.** Hlavní smyčka na `$9163` se v každém
   průchodu ptá dvakrát: je počítadlo zón aspoň `30`, a je `y` Lasertronu
   v okně od `$156C` = **5484**? Zóna je dlouhá 176 a Zone Zero začíná na 5280,
   takže je to **204 jednotek za začátkem Zone Zero**. Hráč u toho být nemusí.
2. **Scénář je posloupnost průchodů hlavní smyčky, ne snímků.** Sekvence si
   sama píše, co hra ten průchod „zmáčkla" (`$8F14`), a mezi kroky si nechá
   odběhnout přesný počet průchodů; ty počty jsou v kódu jako konstanty a
   nástroj je čte odtamtud, ne z pozorování.
3. **Zóna Zero není poslední.** Sekvence pustí Lasertron samotný (rychlost 1)
   a nechá kameru dojet, dokud `$8F1C` nedojede na **36** – za Zone Zero jsou
   ještě **další zóny konce**, které normální hra nikdy neukáže.
4. **Druhý průchod je jedno počítadlo a jeden průchod tabulkou.** `$8F89` je
   počítadlo dohraných her; na konci sekvence se zvýší (nejvýš na 2) a hra
   projde **tabulku dat silnice `$7B00`–`$89FF`** – 240 záznamů po 16 bajtech,
   týž formát jako živá tabulka na `$8A00` – a každému záznamu, jehož rodina je
   menší než 5, **přičte 1 k rychlosti** (bajt `+8`). To je celý „harder
   highway encounter": rychlejší nepřátelé, a **miny ne** (rodina 5 je zrovna
   nad hranicí). Při nové hře se to stejným průchodem zase odečte (`$8F8A`).
5. **Tabulka dat silnice se tím našla.** Že objekty zón leží na `$7B00`, byla
   otevřená otázka M2 (`disasm_notes.md` §10); tady se ukázala, protože po ní
   druhý průchod šlape. Ověřeno i tím, že se živé záznamy z rozehrané hry
   v téhle tabulce najdou.

Spouštět s `PYTHONPATH=tools/vendor` (vendorovaný SkoolKit, viz tools/README.md).
"""
import argparse, base64, collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402
import playrzx                                                    # noqa: E402

SNAPSHOT = os.path.join(H.ROOT, 'build/ending.z80')
SNAPSHOT_FRAME = 77700  # snímek záznamu těsně před spuštěním sekvence (měřeno)

# --- co se čte z kódu (adresa, opcode, k čemu to je) -------------------------
# Konstanty se berou **z paměti**, ne opsané sem: nástroj u každé zkontroluje,
# že na adrese opravdu stojí očekávaná instrukce, a když ne, spadne.
TRIGGER_ZONE = (0x9176, 0xFE)     # CP $1E   – počítadlo zón aspoň tolik
TRIGGER_Y = (0x9181, 0x21)        # LD HL,$156C – y Lasertronu

ENTITIES = 0x8A00
ENTITY_SIZE = 16
MASTER = 0x7B00                   # tabulka dat silnice
MASTER_END = 0x8A00
ZONE_COUNTER = 0x8F00
ZONE_COPY = 0x8F1C
PASS_COUNTER = 0x8F89             # počítadlo dohraných her
TABLE_PTR = 0x8F01                # ukazatel na začátek živé tabulky
KEYS_READ = 0x8F14

# Body scénáře. Adresa je hranice mezi dvěma částmi – `highwaylib.run_to()`
# na ni doběhne, takže se dá změřit, kolik snímků která část trvala.
MARKS = [
    (0xA617, 'trigger', 'sekvence začíná: prvních pět záznamů (konvoj) dostane '
             'druh $80 a bit 7 rychlosti – to je animace zániku z §16'),
    (0xA643, 'salute', 'pět Vortonů odchází'),
    (0xA649, 'lasertronAlone', 'Lasertron zůstal sám; ukazatel tabulky $8F01 '
             'se posune na $8A50, takže se z něj stane nultý záznam'),
    (0xA667, 'panelMessage', 'do panelu se na místo pole ZONE vykreslí hláška '
             'LASERTRON ACTIVATED (obrázek z $A875, atribut $BA – bliká)'),
    (0xA694, 'lasertronRuns', 'Lasertron dostane rychlost 1 a jede sám'),
    (0xA6BB, 'endZonesDone', 'dojel: $8F1C došlo na 36, tedy pět zón za Zone Zero'),
    (0xA6D0, 'clear', 'obraz se smaže podle seznamu na $5BD7'),
    (0xA6FF, 'explosion', 'Lasertron se rozloží a vybuchne'),
    (0xA716, 'whiteOut', 'atributy celé hrací plochy zbělají ($47)'),
    (0xA723, 'shipBreakup', 'rozpad lodi – kreslí se ze scénáře na $A84B, '
             'bez průchodů hlavní smyčky'),
    (0xA7B5, 'afterBreakup', 'atributy zpátky na $07 a dlouhá prodleva'),
    (0xA7E0, 'rewind', 'konec tabulky se zkrátí na $8A90 a animace se přehraje '
             'pozpátku'),
    (0xA806, 'finale', '190 průchodů, ve kterých se po 55. vysází text'),
    (0xA818, 'text', 'PREPARE YOURSELF FOR THE NEXT HIGHWAY ENCOUNTER!'),
    (0xA821, 'secondPass', 'počítadlo $8F89 a zrychlení tabulky silnice'),
    (0x9107, 'newGame', 'zpátky do hry – nová hra na tvrdší silnici'),
]

# Konstanty scénáře: (jméno, adresa, očekávaný opcode, co to je)
CONSTS = [
    ('saluteEntities', 0xA618, 0x06, 'kolik prvních záznamů se pošle do zániku'),
    ('saluteKind', 0xA62B, None, 'druh, na který se přepíšou (spodní bajt)'),
    ('salutePasses', 0xA644, 0x06, 'průchodů po zániku pětice'),
    ('afterPointerPasses', 0xA650, 0x06, 'průchodů po posunu ukazatele tabulky'),
    ('lasertronSpeed', 0xA6B0, 0x36, 'rychlost, kterou Lasertron dostane'),
    ('endZoneLast', 0xA6B8, 0xFE, 'do jaké hodnoty $8F1C se jede'),
    ('clearPasses', 0xA6D1, 0x06, 'průchodů po smazání obrazu'),
    ('shapeSteps', 0xA6D7, 0x0E, 'kolikrát se druh Lasertronu posune'),
    ('shapePasses', 0xA6D9, 0x06, 'průchodů na jeden posun'),
    ('afterShapePasses', 0xA6EA, 0x06, 'průchodů po přeměně'),
    ('patchDuringExplosion', 0xA700, 0x3E,
     'bajt, který si sekvence zapíše do instrukce na $A1CE (co vybírá, '
     'změřené není – je to uvnitř kreslení, tedy M8)'),
    ('explosionPasses', 0xA705, 0x06, 'průchodů výbuchu'),
    ('explosionKeys', 0xA707, 0x3E, 'co si hra ty průchody „mačká" ($8F14)'),
    ('afterExplosionPasses', 0xA70C, 0x06, 'průchodů po výbuchu'),
    ('patchBack', 0xA712, 0x3E, 'a co tam zapíše zpátky ($16, jak to stojí '
     'v kódu na $A1CE)'),
    ('whiteAttr', 0xA71D, 0x36, 'atribut, kterým se hrací plocha zabělí'),
    ('plainAttr', 0xA7BC, 0x36, 'atribut zpátky'),
    ('rewindSteps', 0xA7E6, 0x0E, 'kolikrát se druh posune zpátky'),
    ('rewindPasses', 0xA7E8, 0x06, 'průchodů na jeden posun'),
    ('afterRewindPasses', 0xA7F9, 0x06, 'průchodů po zpětné přeměně'),
    ('finalePasses', 0xA807, 0x06, 'průchodů závěru'),
    ('textAtPass', 0xA814, 0xFE, 'na které hodnotě čítače se vysází text'),
    ('passCap', 0xA825, 0xFE, 'nejvyšší hodnota počítadla $8F89'),
    ('familyLimit', 0xA837, 0xFE, 'rodiny **pod** touhle hranicí se zrychlují'),
    ('explosionRecords', 0xA6F9, 0x06, 'kolik záznamů dostane při výbuchu jiný druh'),
    ('explosionKind', 0xA6FB, 0x36, 'a jaký (spodní bajt)'),
    ('finaleKind', 0xA805, 0x36, 'druh, na který se Lasertron přepíše v závěru'),
]
# adresy uvnitř tabulky objektů, ze kterých se dá spočítat, o kterou řadu jde
SLOT_CONSTS = [
    ('explosionFirst', 0xA6F6, 0x21, 5, 'první ze záznamů, které při výbuchu '
     'dostanou jiný druh'),
    ('tableEndAt', 0xA7E1, 0x21, 0, 'kam se po výbuchu zkrátí konec tabulky'),
    ('finaleKindAt', 0xA802, 0x21, 5, 'čí druh se v závěru přepíše'),
    ('finaleDeadAt', 0xA80A, 0x21, 8, 'čí rychlosti se v závěru každý průchod '
     'nastaví horní bit'),
]

TEXT_STRING = 0x8FB0              # PREPARE YOURSELF…
DEMO_STRING = 0xA4D6              # konec režimu 6 DEMONSTRATION
MESSAGES = [                      # ostatní hlášky, které hra sází touž rutinou
    ('missionAborted', 0x9232),
    ('tooLate', 0x9247),
    ('gameOver', 0x926F),
    ('pauseMode', 0x92A0),
]
PANEL_MESSAGE = 0xA875            # obrázek hlášky do panelu
PANEL_MESSAGE_ROWS = 2            # znakové řádky panelu (20 a 21)
PANEL_MESSAGE_COLS = 8            # sloupce 8 až 15
PANEL_MESSAGE_GLYPH = 5           # pixelových řádek v buňce; zbytek je prázdný
PANEL_MESSAGE_AT = (0x5088, 0x50A8)
PANEL_MESSAGE_ATTRS = (0x5A88, 0x5AA8)
PANEL_MESSAGE_ATTR = 0xBA

LINE_END, STRING_END = 0xFF, 0xFE

PANEL_ROW = 19          # první znaková řádka panelu (screen_layout.md §1)
PANEL_ROWS = 5


def screen_offset(y):
    third, char_row, pix = y >> 6, (y >> 3) & 7, y & 7
    return (third << 11) | (pix << 8) | (char_row << 5)


def panel_picture(session):
    """Panel tak, jak ho sekvence nechá – ve stejném tvaru jako data/panel.json.

    Sekvence panel **přemaluje**: pole `ZONE` vyprázdní a řadu Vortonů smaže,
    a už je nevrátí. Fotí se proto celý panel v okamžiku, kdy je hláška
    LASERTRON ACTIVATED pryč a nová hra ještě nezačala – port ho od té chvíle
    kreslí místo obvyklého obrázku, a hlášku si na něj přiloží zvlášť."""
    scr = session.screen()
    bitmap = bytearray()
    for y in range(PANEL_ROW*8, (PANEL_ROW + PANEL_ROWS)*8):
        base = screen_offset(y)
        bitmap += scr[base:base + 32]
    attrs = scr[6144 + PANEL_ROW*32: 6144 + (PANEL_ROW + PANEL_ROWS)*32]
    return bytes(bitmap), bytes(attrs)


def word(session, addr, opcode, name):
    """Šestnáctibitový operand na adrese, se stejnou kontrolou jako `imm`."""
    if opcode is not None and session.peek(addr - 1) != opcode:
        raise SystemExit('$%04X (%s): cekal jsem opcode $%02X, je tam $%02X'
                         % (addr, name, opcode, session.peek(addr - 1)))
    return session.peek(addr) | (session.peek(addr + 1) << 8)


def slot_of(addr, offset):
    """Ze které řady tabulky `$8A00` adresa je (a čeká se, že sedí offset)."""
    return (addr - offset - ENTITIES) // ENTITY_SIZE


def imm(session, addr, opcode, name):
    """Bajt na adrese, s kontrolou, že před ním stojí očekávaná instrukce."""
    if opcode is not None and session.peek(addr - 1) != opcode:
        raise SystemExit('$%04X (%s): cekal jsem opcode $%02X, je tam $%02X'
                         % (addr, name, opcode, session.peek(addr - 1)))
    return session.peek(addr)


def read_string(session, addr, charmap=None, limit=400):
    """Řetězec pro rutinu `$B890` – řádky s trojicí adres, `$FF` konec řádky,
    `$FE` konec řetězce (viz `dumpfont.py`)."""
    lines, i, end = [], addr, addr + limit
    while i < end:
        hdr = session.peek(i, 3)
        i += 3
        codes = []
        while i < end:
            b = session.peek(i)
            i += 1
            if b in (LINE_END, STRING_END):
                break
            codes.append(b)
        text = ''.join((charmap or {}).get(str(c & 0x3F), '?') for c in codes)
        lines.append({
            'screen': '$%02X%02X' % (hdr[0], hdr[1]),
            'attributes': '$%02X%02X' % (hdr[2], hdr[1]),
            'codes': [int(c) for c in codes],
            'text': text,
        })
        if b == STRING_END:
            break
    return lines


def families(session, start, end):
    """Rodiny záznamů tabulky – horní bajt druhu bez bitu 4 (§16)."""
    out = collections.Counter()
    for a in range(start, end, ENTITY_SIZE):
        out[session.peek(a + 6) & 0xEF] += 1
    return out


def ending_snapshot(rebuild=False):
    """Snapshot těsně před spuštěním sekvence – z RZX záznamu, s cache."""
    if rebuild or not os.path.isfile(SNAPSHOT):
        playrzx.snapshot_at(SNAPSHOT_FRAME, SNAPSHOT)
    return SNAPSHOT


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'data/ending.json'))
    ap.add_argument('--rebuild', action='store_true',
                    help='znovu přehrát RZX a vyrobit build/ending.z80')
    args = ap.parse_args()

    charmap = {}
    font_path = os.path.join(H.ROOT, 'data/font.json')
    if os.path.isfile(font_path):
        with open(font_path) as f:
            charmap = json.load(f).get('map', {})

    ending_snapshot(args.rebuild)
    s = H.Session(SNAPSHOT)

    # --- 1. spoušť ------------------------------------------------------
    zone_min = imm(s, TRIGGER_ZONE[0], TRIGGER_ZONE[1], 'trigger zone')
    trigger_y = s.peek(0x9181) | (s.peek(0x9182) << 8)
    if s.peek(0x9180) != 0x21:
        raise SystemExit('$9180: cekal jsem LD HL,nn')

    # --- 2. konstanty scénáře -------------------------------------------
    consts = {}
    for name, addr, opcode, note in CONSTS:
        consts[name] = {'value': imm(s, addr, opcode, name),
                        'at': '$%04X' % addr, 'note': note}
    for name, addr, opcode, offset, note in SLOT_CONSTS:
        target = word(s, addr, opcode, name)
        consts[name] = {'value': slot_of(target, offset),
                        'address': '$%04X' % target, 'offset': offset,
                        'at': '$%04X' % addr, 'note': note}

    # --- 3. scénář změřený na běhu --------------------------------------
    phases, prev_frame = [], None
    trigger_state = None
    master_before = None
    for addr, name, note in MARKS:
        frames = s.run_to(addr, frames=6000)
        if frames is None:
            raise SystemExit('scenar se zastavil pred $%04X (%s)' % (addr, name))
        if name == 'trigger':
            trigger_state = {
                'zoneCounter': s.peek(ZONE_COUNTER),
                'lasertronY': s.peek(ENTITIES + 5*ENTITY_SIZE + 1)
                              | (s.peek(ENTITIES + 5*ENTITY_SIZE + 2) << 8),
                'entities': [s.peek(ENTITIES + i*ENTITY_SIZE, ENTITY_SIZE).hex(' ')
                             for i in range(6)],
            }
        if name == 'text':
            panel_bitmap, panel_attrs = panel_picture(s)
        if name == 'secondPass':
            master_before = s.peek(MASTER, MASTER_END - MASTER)
            pass_before = s.peek(PASS_COUNTER)
        phases.append({
            'name': name, 'at': '$%04X' % addr, 'note': note,
            'frame': s.frame,
            'framesSincePrevious': None if prev_frame is None else s.frame - prev_frame,
            'zoneCopy': s.peek(ZONE_COPY),
            'tablePointer': '$%04X' % (s.peek(TABLE_PTR) | (s.peek(TABLE_PTR+1) << 8)),
        })
        prev_frame = s.frame

    # --- 4. druhý průchod: co se v tabulce silnice změnilo ---------------
    master_after = s.peek(MASTER, MASTER_END - MASTER)
    changed = [i for i in range(len(master_before)) if master_before[i] != master_after[i]]
    by_offset = collections.Counter(i % ENTITY_SIZE for i in changed)
    by_family = collections.Counter(master_before[i - 8 + 6] & 0xEF for i in changed)
    deltas = collections.Counter(master_after[i] - master_before[i] for i in changed)

    # --- 5. texty --------------------------------------------------------
    ending_text = read_string(s, TEXT_STRING, charmap)
    messages = {name: read_string(s, addr, charmap) for name, addr in MESSAGES}
    demo_text = read_string(s, DEMO_STRING, charmap)
    panel_msg = s.peek(PANEL_MESSAGE,
                       PANEL_MESSAGE_ROWS * PANEL_MESSAGE_COLS * PANEL_MESSAGE_GLYPH)

    data = {
        'source': 'tools/dumpending.py',
        'note': ('koncová sekvence v Zone Zero a druhý průchod. Sekvence si '
                 'hru řídí sama – píše si, co hra ten průchod „zmáčkla" '
                 '($8F14) – takže je od spuštění deterministická a měří se '
                 'krokováním, ne přehráváním vstupů.'),
        'from': {'rzx': 'sources/tape/highway.rzx', 'frame': SNAPSHOT_FRAME,
                 'snapshot': 'build/ending.z80'},
        'trigger': {
            'at': '$9172',
            'zoneCounterAtLeast': zone_min,
            'lasertronY': trigger_y,
            'window': 256,
            'note': ('hlavní smyčka se každý průchod ptá, jestli je počítadlo '
                     'zón aspoň %d a `y` Lasertronu v okně 256 jednotek od '
                     '%d – to je %d jednotek za začátkem Zone Zero (30 × 176 '
                     '= 5280). Spouští to Lasertron, ne hráč.'
                     % (zone_min, trigger_y, trigger_y - 30*176)),
            'measured': trigger_state,
        },
        'script': {
            'constants': consts,
            'phases': phases,
            'totalFrames': phases[-1]['frame'] - phases[0]['frame'],
            'note': ('`framesSincePrevious` je změřený čas mezi dvěma body '
                     'scénáře; počty **průchodů** jsou v `constants` a čtou se '
                     'z kódu. Průchod trvá 2,4 snímku (§11), takže se dají '
                     'porovnat.'),
        },
        'endZones': {
            'zoneCopy': '$8F1C',
            'last': consts['endZoneLast']['value'],
            'note': ('Zone Zero (počítadlo 31) není poslední: sekvence nechá '
                     'Lasertron jet, dokud $8F1C nedojede na %d, tedy přes '
                     'dalších pět zón, které normální hra nikdy neukáže.'
                     % consts['endZoneLast']['value']),
        },
        'secondPass': {
            'counter': '$%04X' % PASS_COUNTER,
            'counterBefore': pass_before,
            'counterAfter': s.peek(PASS_COUNTER),
            'cap': consts['passCap']['value'],
            'masterTable': {'start': '$%04X' % MASTER, 'end': '$%04X' % MASTER_END,
                            'stride': ENTITY_SIZE,
                            'records': (MASTER_END - MASTER) // ENTITY_SIZE},
            'speedOffset': 8,
            'speedDelta': 1,
            'familyBelow': consts['familyLimit']['value'],
            'resetRoutine': '$8F8A',
            'measured': {
                'changedBytes': len(changed),
                'byOffset': {str(k): v for k, v in sorted(by_offset.items())},
                'byFamily': {str(k): v for k, v in sorted(by_family.items())},
                'deltas': {str(k): v for k, v in sorted(deltas.items())},
                'familiesInTable': {str(k): v for k, v in
                                    sorted(families(s, MASTER, MASTER_END).items())},
            },
            'note': ('celý „harder highway encounter" je tohle: rychlost (+8) '
                     'o 1 výš každému záznamu tabulky silnice, jehož rodina je '
                     'pod %d. Miny (rodina 5) tedy rychlejší **nejsou**. Při '
                     'nové hře to $8F8A stejným průchodem odečte zpátky.'
                     % consts['familyLimit']['value']),
            'open': ['strop počítadla (%d) je přečtený z kódu ($A825), ne '
                     'změřený: RZX záznam má jedno dohrání, ne tři'
                     % consts['passCap']['value']],
        },
        'text': {
            'ending': ending_text,
            'messages': messages,
            'demoEnd': demo_text,
            'note': ('texty se sázejí rutinou $B890 znakovou sadou z '
                     'data/font.json; `codes` jsou bajty tak, jak leží '
                     'v paměti (bity 6 a 7 vybírají barvu)'),
        },
        'panel': {
            'row': PANEL_ROW, 'rows': PANEL_ROWS,
            'bitmap': base64.b64encode(panel_bitmap).decode('ascii'),
            'attributes': base64.b64encode(panel_attrs).decode('ascii'),
            'note': ('panel, jak ho sekvence nechá: pole ZONE prázdné a řada '
                     'Vortonů smazaná. Sejmuto v okamžiku, kdy je hláška pryč '
                     'a nová hra ještě nezačala – jinak by port kreslil pod '
                     'sekvencí panel z rozehrané hry, včetně čísla zóny, '
                     'které originál smazal.'),
        },
        'panelMessage': {
            'at': '$%04X' % PANEL_MESSAGE,
            'rows': PANEL_MESSAGE_ROWS, 'cols': PANEL_MESSAGE_COLS,
            'glyphRows': PANEL_MESSAGE_GLYPH,
            'screen': ['$%04X' % a for a in PANEL_MESSAGE_AT],
            'attributeAddresses': ['$%04X' % a for a in PANEL_MESSAGE_ATTRS],
            'attribute': '$%02X' % PANEL_MESSAGE_ATTR,
            'bitmap': base64.b64encode(panel_msg).decode('ascii'),
            'note': ('LASERTRON ACTIVATED se do panelu **nesází znakovou '
                     'sadou** – je to hotový obrázek: dvě znakové řádky (20 a '
                     '21) po osmi sloupcích, v každé buňce pět pixelových '
                     'řádek dat a kolem nich prázdno. Bajty jdou po sloupcích, '
                     'pět na buňku, a atribut $BA (bliká, červená na bílé) se '
                     'zapíše celé osmici.'),
        },
        'open': [
            'co vybírá bajt, který si sekvence zapisuje do instrukce na $A1CE '
            '(konstanty patchDuringExplosion a patchBack) – je to uvnitř '
            'kreslení, takže to rozhodne M8',
            'jak se kreslí rozpad lodi ($A723, scénář na $A84B a vyrovnávací '
            'paměti $D90C/$E60C) – je to grafika, a ta čeká na M8',
            'co kreslí zóny za Zone Zero ($A8D6 rozskakuje podle $8F1C na šest '
            'obsluh) – taky grafika, M2/M8',
            'zvuky sekvence ($9B2C, $9B5B, $A414) – M8',
            'bodování na konci hry: SCORE se za dohrání nemění a HIGH se '
            'nepřepisuje v žádném měřeném běhu (ZADANI §4 zůstává otevřené)',
        ],
    }
    with open(args.out, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print('%s: scénář %d bodů, %d snímků; druhý průchod %d záznamů (%s), '
          'strop %d'
          % (os.path.relpath(args.out, H.ROOT), len(phases),
             data['script']['totalFrames'], len(changed),
             ', '.join('rodina %d: %d' % (k, v) for k, v in sorted(by_family.items())),
             consts['passCap']['value']))


if __name__ == '__main__':
    main()
