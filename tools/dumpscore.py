#!/usr/bin/env python3
"""Odměří **bodování a číslice `SCORE`/`HIGH`** → `data/score.json` (M8).

    PYTHONPATH=tools/vendor ./tools/dumpscore.py [--out data/score.json]

`ZADANI.md` §4 se ptá, jak se v Highway Encounter počítají body, a otevřené to
zůstalo přes celou M6 i M7: při přechodu zóny se nezvětšil žádný bajt a při
dohrání se `SCORE` nezměnilo. Našlo se to až od zvuku – rutina, o které M7
psala jako o „blikání barvy" (`$A414`, `disasm_notes.md` §17), totiž **žádná
barva není**. Je to počítadlo bodů.

Co z toho vypadlo:

1. **Skóre je šest číslic a sedmá je nakreslená.** Číslice leží po jednom bajtu
   na `$A481`–`$A486`, `$A480` je `$FF` jako zarážka a kreslí se **zprava
   doleva** od `$529D` (znaková řádka 20, sloupec 29, druhá pixelová řádka
   buňky). Sloupec 30 se nekreslí nikdy – nula na konci je součástí obrázku
   panelu (`data/panel.json`), a **skóre je proto vždycky násobek deseti**.
2. **Číslice je uložená jako 1 až 10, ne 0 až 9.** Nula znamená „prázdno", a
   proto se vedoucí nuly nekreslí. Přičítání (`$A414`) bere bajt, nulu si
   opraví na jedničku, přičte a při `11` ho vrátí na `1` a jde o řád vejš.
3. **Body dává čtvero míst a všechna se dají přečíst z kódu**: `+1` (tedy 10
   bodů), `+25` dvakrát – to je zničený předmět rodiny 1 až 6, tentýž skok,
   který si říká o zvuk `blast` (`data/sounds.json`) – a `+100` za dohrání.
4. **`HIGH` se přepisuje na začátku nové hry**, ne na jejím konci: `$90F2`
   nejdřív porovná sedm bajtů skóre se sedmi bajty `HIGH` (`$A450`) a při
   větším je zkopíruje, a teprve pak skóre vynuluje. Proto ho žádný měřený
   běh nepřepsal – přepíše ho až ta hra po něm.
5. **Číslice mají vlastní písmo**, ne to z `data/font.json`: deset glyfů po
   pěti bajtech na `$A490`, kreslených po pixelových řádkách jedné buňky.

Všechno se **ověřuje měřením**: pro každou z naměřených hodnot se číslice
zapíšou do paměti, zavolá se kreslicí rutina originálu a porovná se, co
opravdu vyšlo na obrazovce, s tím, co říká tabulka glyfů. A přičítání se
změří tak, že se rutina pustí se známým `B` a přečte se výsledek.

Spouštět s `PYTHONPATH=tools/vendor` (vendorovaný SkoolKit, viz tools/README.md).
"""
import argparse, base64, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402
from skoolkit.simutils import PC, SP, B as REG_B                  # noqa: E402

SCORE = 0xA481          # šest číslic, $A480 je zarážka $FF
HIGH = 0xA489
DIGITS = 6
TAIL = 0xA487           # sedmý bajt, který se neukazuje (nula na panelu)
GLYPHS = 0xA490
GLYPH_ROWS = 5
ADD = 0xA414            # přičte B (v desítkách bodů)
DRAW_SCORE = 0xA42B
DRAW_HIGH = 0xA478
COMPARE = 0xA450
NEW_GAME = 0x90F2
SCORE_AT = 0x529D       # řádka 20, sloupec 29, pixelová řádka 2
HIGH_AT = 0x51DD        # řádka 22, sloupec 29, pixelová řádka 1
RETURN = 0x9B71
BLANK, MIN_DIGIT, MAX_DIGIT = 0, 1, 10

POWER_PTR = 0x8F18      # dolní bajt adresy v atributech – zásobník výstřelů
ATTR_PAGE = 0x5A        # horní bajt téže adresy ($A10F, $A1EA)
POWER_FULL = 0xA117     # LD A,$44 – plný dílek
POWER_EMPTY = 0xA1EE      # LD (HL),$00 – prázdný
LAMP_AT = 0x9BD9        # LD HL,$5A90 / LD (HL),A / INC L / LD (HL),A
LAMP_ON = 0x9BF8        # LD A,$42
ESCORT_COUNTER = 0x8F16

# Kde se přičítá. Adresa je `LD B,n`, hodnota se čte z paměti.
AWARDS = [
    (0x9BF3, 'postup', 'jediné místo mimo zánik a konec hry; přičte se, když '
             'je $8F16 rovno 4'),
    (0x9F18, 'zánik', 'zničený záznam rodiny 1 až 6 – tentýž skok, který si '
             'říká o zvuk `blast`'),
    (0x9F6E, 'zánik', 'druhá větev téhož zániku'),
    (0xA632, 'dohráno', 'koncová sekvence, hned u zvuku `destroy` (M7)'),
]


def screen_addr(row, col, line):
    return 0x4000 + (row // 8) * 2048 + line * 256 + (row % 8) * 32 + col


def decode_at(addr):
    """Z adresy ve videopaměti zpátky znaková řádka, sloupec a pixelová řádka."""
    off = addr - 0x4000
    third, line = (off >> 11) & 3, (off >> 8) & 7
    return {'row': third * 8 + ((off >> 5) & 7), 'col': off & 31, 'line': line,
            'at': '$%04X' % addr}


def call(addr, b=None, score=None, high=None):
    """Pustí rutinu originálu s návratem na `RETURN` a vrátí sezení."""
    s = H.gameplay()
    if s.run_to(0x9AEF, frames=60) is None:
        raise SystemExit('nedoslo se do hry')
    sim = s.simulator
    if score is not None:
        for i, v in enumerate(score):
            sim.memory[SCORE + i] = v
    if high is not None:
        for i, v in enumerate(high):
            sim.memory[HIGH + i] = v
    sp = (sim.registers[SP] - 2) & 0xFFFF
    sim.memory[sp] = RETURN & 0xFF
    sim.memory[sp + 1] = RETURN >> 8
    sim.registers[SP] = sp
    if b is not None:
        sim.registers[REG_B] = b
    sim.registers[PC] = addr
    s._start_pc = addr
    s._started = False
    if s.run_to(RETURN, frames=900) is None:
        raise SystemExit('rutina $%04X nedobehla' % addr)
    return s


def cell(scr, row, col):
    return bytes(scr[screen_addr(row, col, line) - 0x4000] for line in range(8))


def read_glyphs(mem):
    """Deset glyfů po pěti bajtech; nultý je prázdno (vedoucí nula)."""
    return [bytes(mem[GLYPHS + i * GLYPH_ROWS:GLYPHS + (i + 1) * GLYPH_ROWS])
            for i in range(MAX_DIGIT + 1)]


def expect(mem, addr, *opcodes):
    got = bytes(mem[addr:addr + len(opcodes)])
    if got != bytes(opcodes):
        raise SystemExit('na $%04X neceka %s, ale %s'
                         % (addr, ' '.join('%02X' % b for b in opcodes),
                            ' '.join('%02X' % b for b in got)))


def read_code(mem):
    expect(mem, ADD, 0x21, GLYPHS - 10 & 0xFF, GLYPHS >> 8)   # LD HL,$A486
    expect(mem, 0xA41F, 0xFE, MAX_DIGIT + 1)                  # CP $0B
    expect(mem, 0xA423, 0x36, MIN_DIGIT)                      # LD (HL),$01
    expect(mem, DRAW_SCORE, 0x11, SCORE_AT & 0xFF, SCORE_AT >> 8)
    expect(mem, DRAW_HIGH, 0x11, HIGH_AT & 0xFF, HIGH_AT >> 8)
    expect(mem, 0xA442, 0x06, GLYPH_ROWS)                     # LD B,$05
    expect(mem, COMPARE, 0x21, SCORE & 0xFF, SCORE >> 8)
    expect(mem, 0xA453, 0x11, HIGH & 0xFF, HIGH >> 8)
    expect(mem, 0xA456, 0x06, DIGITS + 1)                     # LD B,$07
    awards = []
    for addr, what, note in AWARDS:
        expect(mem, addr, 0x06)
        awards.append({'at': '$%04X' % addr, 'add': mem[addr + 1],
                       'points': mem[addr + 1] * 10, 'what': what, 'note': note})
    return awards


def measure_add(awards):
    """Přičtení se změří: rutina se pustí se známým B a přečte se výsledek."""
    for award in awards:
        s = call(ADD, award['add'], [MIN_DIGIT] * DIGITS)
        digits = list(s.peek(SCORE, DIGITS))
        value = 0
        for d in digits:
            value = value * 10 + (0 if d == BLANK else d - MIN_DIGIT)
        award['measured'] = value * 10
        if award['measured'] != award['points']:
            raise SystemExit('$%s: kod rika %d bodu, mereni %d'
                             % (award['at'], award['points'], award['measured']))
    return awards


def measure_draw(glyphs, count):
    """Zapsat číslice, nechat originál nakreslit, porovnat s tabulkou glyfů."""
    rnd = random.Random(8)
    checked, diffs, pictures = 0, 0, {}
    for case in range(count):
        digits = ([MIN_DIGIT + rnd.randrange(MAX_DIGIT) for _ in range(DIGITS)]
                  if case else list(range(MIN_DIGIT, MIN_DIGIT + DIGITS)))
        s = call(DRAW_SCORE, None, digits)
        scr = s.screen()
        where = decode_at(SCORE_AT)
        for i, digit in enumerate(reversed(digits)):
            col = where['col'] - i
            got = cell(scr, where['row'], col)
            want = glyphs[digit]
            checked += 1
            if bytes(got[where['line']:where['line'] + GLYPH_ROWS]) != want:
                diffs += 1
            if digit not in pictures:
                pictures[digit] = base64.b64encode(got).decode('ascii')
    return checked, diffs, pictures


def measure_power(mem):
    """`POWER` je zásobník výstřelů: tři dílky, a `$8F18` ukazuje na poslední plný.

    Změří se tak, že se ve hře drží střelba a pro každý snímek se přečte
    ukazatel i skutečné atributy panelu; z toho vypadne, které buňky to jsou a
    že je dílek plný právě tehdy, když jeho adresa není za ukazatelem.
    """
    full, empty = mem[POWER_FULL], mem[POWER_EMPTY]
    s = H.gameplay()
    seen, cells = {}, set()
    for _ in range(80):
        s.hold('SPACE', 20)
        s.hold('1', 20)
        s.run(20)
        pointer = s.peek(POWER_PTR)
        attrs = s.screen()[6144:]
        for col in range(32):
            for row in range(19, 24):
                addr = 0x5800 + row * 32 + col
                value = attrs[addr - 0x5800]
                if value in (full, empty):
                    seen.setdefault(addr, set()).add((value, pointer))
    for addr, values in seen.items():
        if len({v for v, _ in values}) > 1:
            cells.add(addr)          # dílek, který se za měření hnul
    if not cells:
        raise SystemExit('POWER se za mereni nehnul')
    # Dílek, který se za měření nehnul, ale sedí na pravidlo a **sousedí**
    # s hnutými, do ukazatele patří taky – jinak by z třídílkového zásobníku
    # zbyly dva jen proto, že se v měřených bězích třetí výstřel vždycky vrátil.
    row = (min(cells) - 0x5800) // 32
    for step in (-1, 1):
        addr = (min(cells) if step < 0 else max(cells)) + step
        while addr in seen and (addr - 0x5800) // 32 == row:
            if all((value == full) == (addr <= ATTR_PAGE * 256 + pointer)
                   for value, pointer in seen[addr]):
                cells.add(addr)
                addr += step
            else:
                break
    cells = sorted(cells)
    rule = all((value == full) == (addr <= ATTR_PAGE * 256 + pointer)
               for addr in cells for value, pointer in seen[addr])
    if not rule:
        raise SystemExit('POWER: pravidlo ukazatele nesedi')
    return {'cells': ['$%04X' % a for a in cells],
            'row': (cells[0] - 0x5800) // 32, 'cols': [(a - 0x5800) % 32 for a in cells],
            'pointer': '$%04X' % POWER_PTR, 'page': '$%02X' % ATTR_PAGE,
            'full': '$%02X' % full, 'empty': '$%02X' % empty,
            'spend': '$A1EF', 'refill': '$A10B',
            'pointerSeen': sorted({p for values in seen.values()
                                   for _, p in values
                                   if 0x5A00 + p in range(min(cells) - 1, max(cells) + 1)}),
            'moved': ['$%04X' % a for a in sorted(cells)
                      if len({v for v, _ in seen[a]}) > 1],
            'note': ('POWER není energie, je to zásobník výstřelů. $8F18 je '
                     'dolní bajt adresy v atributech; výstřel ho o jedna sníží '
                     'a do buňky zapíše prázdno, a jakmile výstřel dojede, '
                     '$A10B ho zvýší a zapíše plno. Dílek je plný právě tehdy, '
                     'když jeho adresa není za ukazatelem – ověřeno na každém '
                     'naměřeném snímku.')}


def measure_lamp(mem):
    """Dvě buňky, které se rozsvítí, když se doprovází Lasertron."""
    expect(mem, LAMP_AT, 0x21)
    expect(mem, LAMP_ON, 0x3E)
    base = mem[LAMP_AT + 1] | mem[LAMP_AT + 2] << 8
    return {'cells': ['$%04X' % base, '$%04X' % (base + 1)],
            'row': (base - 0x5800) // 32, 'cols': [(base - 0x5800) % 32,
                                                   (base - 0x5800) % 32 + 1],
            'on': '$%02X' % mem[LAMP_ON + 1], 'off': '$00',
            'counter': '$%04X' % ESCORT_COUNTER,
            'note': ('Dvě buňky, o kterých screen_layout.md §4 psal jen, že '
                     'jsou černé. Rozsvítí se ($42) v tomtéž průchodu, ve '
                     'kterém se přičte deset bodů za doprovod Lasertronu, a '
                     'zhasnou, jakmile se doprovod přeruší nebo počítadlo '
                     '$8F16 přeteče – takže blikají po dobu doprovodu.')}


def measure_high():
    """`HIGH` se přepisuje na začátku nové hry, ne na jejím konci."""
    lower = call(COMPARE, None, [1, 1, 1, 1, 1, 2], [1, 1, 1, 1, 1, 5])
    higher = call(COMPARE, None, [1, 1, 1, 1, 1, 9], [1, 1, 1, 1, 1, 5])
    return {'kept': list(lower.peek(HIGH, DIGITS)),
            'taken': list(higher.peek(HIGH, DIGITS))}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'data/score.json'))
    ap.add_argument('--cases', type=int, default=12, help='kolik hodnot kreslit')
    args = ap.parse_args()

    mem = H.Session(H.CACHE).simulator.memory
    awards = measure_add(read_code(mem))
    glyphs = read_glyphs(mem)
    checked, diffs, pictures = measure_draw(glyphs, args.cases)
    high = measure_high()
    power = measure_power(mem)
    lamp = measure_lamp(mem)
    print('kreslení: %d číslic, %d rozdílů' % (checked, diffs))
    print('body: %s' % ', '.join('%s %+d' % (a['what'], a['points']) for a in awards))
    print('POWER: %d dílků na řádce %d, sloupce %s; lampa doprovodu: sloupce %s'
          % (len(power['cells']), power['row'], power['cols'], lamp['cols']))

    data = {
        'note': ('Bodování a číslice SCORE/HIGH originálu. Skóre je šest '
                 'číslic a sedmá je nakreslená v panelu, takže je vždycky '
                 'násobek deseti. Číslice mají vlastní pětibajtové písmo, '
                 'jiné než data/font.json.'),
        'source': 'tools/dumpscore.py, build/gameplay.z80',
        'digits': DIGITS,
        'store': {'score': '$%04X' % SCORE, 'high': '$%04X' % HIGH,
                  'terminator': '$FF', 'tail': '$%04X' % TAIL,
                  'blank': BLANK, 'first': MIN_DIGIT, 'last': MAX_DIGIT,
                  'note': ('Číslice je 1 až 10 pro 0 až 9; 0 znamená prázdno, '
                           'a proto se vedoucí nuly nekreslí. Sedmý bajt se '
                           'neukazuje.')},
        'unit': 10,
        'awards': awards,
        'high': dict(high, at='$%04X' % COMPARE, when='$%04X' % NEW_GAME,
                     note=('HIGH se přepisuje na **začátku nové hry**: nejdřív '
                           'se porovná sedm bajtů skóre se sedmi bajty HIGH a '
                           'při větším se zkopírují, a teprve pak se skóre '
                           'vynuluje. Proto ho žádný měřený běh nepřepsal.')),
        'glyphs': {'at': '$%04X' % GLYPHS, 'rows': GLYPH_ROWS,
                   'bytes': base64.b64encode(b''.join(glyphs)).decode('ascii'),
                   'note': ('deset glyfů po pěti bajtech, index je hodnota '
                            'číslice; nultý je prázdno')},
        'cells': {'score': decode_at(SCORE_AT), 'high': decode_at(HIGH_AT),
                  'direction': 'zprava doleva',
                  'pictures': pictures,
                  'note': ('Kreslí se zprava doleva od uvedené buňky, pět '
                           'pixelových řádek od `line`. `pictures` je celá '
                           'buňka tak, jak ji originál nechal – osm bajtů, '
                           'takže je v ní i to, co kolem glyfu už na panelu '
                           'bylo.')},
        'power': power,
        'lamp': lamp,
        'verification': {'digitsDrawn': checked, 'differences': diffs,
                         'note': ('číslice se zapsaly do paměti, nechal je '
                                  'nakreslit originál a porovnalo se to '
                                  's tabulkou glyfů')},
        'open': [
            'přesné pravidlo doprovodu Lasertronu ($9B72–$9BF5): z kódu je '
            'vidět, že se prochází nejvýš čtyři záznamy zpět od Lasertronu a '
            'hledá se Vorton do 16 jednotek za ním, ale změřené to není – '
            'proto port těch deset bodů zatím nepřičítá a matchsound.js je '
            'počítá zvlášť',
            'ukazatel TIME: kde přesně ubývá dílek, měřila M6 ($8F19), ale '
            'pixelově porovnaný není – v žádném naměřeném běhu se neubral',
        ],
    }
    with open(args.out, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print('%s: %d číslic, %d míst, kde se přičítá'
          % (os.path.relpath(args.out, H.ROOT), DIGITS, len(awards)))
    if diffs:
        raise SystemExit('glyfy nesedi na obrazovku')


if __name__ == '__main__':
    main()
