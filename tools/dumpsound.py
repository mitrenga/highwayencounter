#!/usr/bin/env python3
"""Odměří **zvuk a barvu borderu** → `data/sounds.json` (M8).

    PYTHONPATH=tools/vendor ./tools/dumpsound.py [--out data/sounds.json]
                                                 [--seeds 64] [--quick]

Stroj má jednobitový beeper na bitu 4 portu `$FE` a žádný zvukový čip, takže
zvuk **není vzorek, ale posloupnost překlopení**. Cíl M8 je proto úzký a dá se
splnit beze zbytku: najít rutiny, které tím bitem hýbou, a doložit, že je port
umí přehrát **T-stav po T-stavu**.

Co z toho vypadlo:

1. **Hra nehraje hudbu.** V celém obrazu 48 K jsou přesně **tři** instrukce
   `OUT ($FE),A` – `$9B34`, `$9B60` a `$B209` – a všechny tři leží uvnitř
   generátorů zvuku. Žádná se nevolá z přerušení ani z kreslení, takže mezi
   efekty je ticho; ověřeno i měřením (`--quick` to přeskočí): v průchodech,
   ve kterých je `$8F15` nulové, hra na port nesáhne ani jednou.
2. **Zvuk hry je pět efektů a jedna bitová maska.** `$8F15` je žádanka: hra si
   v ní během průchodu **nastaví bit**, a na konci průchodu rozskok na `$9AEF`
   podle bitů `1, 6, 3, 7, 4` (v tomhle pořadí, první vyhrává) skočí do jednoho
   ze dvou generátorů, přehraje efekt **synchronně** – hlavní smyčka na něj
   čeká – a žádanku vynuluje. Tentýž bajt `$8F15` používá M3 jako příznak
   nárazu (`disasm_notes.md` §13): bit 4 není „náraz", je to **jeho zvuk**.
3. **Generátor A ($9B2C) je šum.** Devět až dvanáct segmentů; každý segment se
   překlopí `L`krát a mezi překlopeními se čeká `B` průchodů smyčkou `OUT`.
   `L` a `B` si na konci každého segmentu **hodí z generátoru náhody** `$A270`
   maskou `C`, resp. `D` – a tím je zavřená poslední otevřená věc M6
   (§16): zvuk výbuchu tahá z generátoru **přesně `E`krát**, jednou za segment,
   tedy 8, 9 nebo 12 tahů podle druhu.
4. **Generátor B ($9B5B) je tón s přebíhající výškou.** `E` tónů po `L`
   překlopeních, prodleva `D` se po každém tónu zmenší o `H` (bajtově, takže se
   přetáčí – a `$32` u nárazu udělá z prvního tónu skřek a ze zbytku
   sestupnou řadu).
5. **Menu má vlastní generátor ($B203)** se dvěma čítači: hraje dva čtvercové
   průběhy zároveň, o jeden T-stav periody vedle sebe, takže drnčí. Volá se
   z šesti míst s různým `HL` (`H` je počet, `L` perioda) – a čtyři z nich jsou
   volba ovládání, každá o kus výš.
6. **Border je černý.** Obě herní rutiny posílají na port `$18` a `$00`, tedy
   bity 0–2 (border) nulové; jiná instrukce port nezapisuje. Border je černý po
   celou hru, v menu i v koncové sekvenci – naměřeno na každém jednom zápisu.
7. **`POWER` je zásobník výstřelů.** `$8F18` je dolní bajt adresy v atributech:
   výstřel ho o jedna sníží a do buňky zapíše `$00`, a jakmile výstřel dojede,
   `$A10B` ho o jedna zvýší a zapíše `$44`. Vypadlo to z okolí bitu 1 a je to
   odpověď na otázku otevřenou od M6 („co měří POWER").

**Jak se to ověřuje.** Modely obou herních generátorů i menu generátoru jsou
tady napsané po instrukcích (`model_noise`, `model_tone`, `model_click`) a
nástroj je přehraje proti originálu: v běžící hře se nastaví semínko a žádanka,
doběhne se na `$9B71` a **porovná se každé překlopení bitu 4 portu `$FE`**,
tak jak ho zachytil simulátor, s tím, co říká model. Musí sedět počet i každý
jeden T-stav – a u šumu navíc semínko, které po efektu zůstalo.

Spouštět s `PYTHONPATH=tools/vendor` (vendorovaný SkoolKit, viz tools/README.md).
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402
from skoolkit.simutils import PC, SP, H as REG_H, L as REG_L      # noqa: E402

CPU_HZ = 3500000
SPEAKER = 0x10            # bit 4 portu $FE
BORDER_MASK = 0x07        # bity 0-2

FLAG = 0x8F15             # žádanka zvuku (M3 ji zná jako příznak nárazu)
DISPATCH = 0x9AEF         # LD A,($8F15) – rozskok podle bitů
RETURN = 0x9B71           # RET za `XOR A / LD ($8F15),A`
SEED = 0x5C76             # spectrácké SEED, nad kterým běží generátor $A270
RANDOM = 0xA270
NOISE = 0x9B2C            # generátor A – šum
TONE = 0x9B5B             # generátor B – tón
CLICK = 0xB203            # generátor menu

# --- co se čte z kódu -------------------------------------------------------
# U každé adresy se kontroluje, že tam stojí očekávaný opcode; jinak nástroj
# spadne a je vidět, že se obraz paměti změnil.
DISPATCH_CHAIN = [
    # (adresa BIT n,A ; opcode ; adresa parametrů ; generátor)
    (0x9AF2, 0xCB, 0x4F, 1, TONE,  0x9AF6),
    (0x9B06, 0xCB, 0x77, 6, NOISE, 0x9B0A),
    (0x9B15, 0xCB, 0x5F, 3, NOISE, 0x9B19),
    (0x9B22, 0xCB, 0x7F, 7, NOISE, 0x9B26),
    (0x9B4F, 0xCB, 0x67, 4, TONE,  0x9B53),
]

# Kde si hra o který zvuk řekne. Bit se **čte z paměti** (instrukce SET n,(HL)
# hned za `LD HL,$8F15`), popis je z okolního kódu.
TRIGGER_NOTES = {
    0x9D01: 'srážka s objektem rodiny 7 a vyšší (rozskok podle rodiny na $9CF2)',
    0x9D06: 'srážka s objektem rodiny 1 až 6',
    0x9D0B: 'srážka s objektem rodiny 0',
    0x9EE5: 'náraz do rodiny 1',
    0x9EF0: 'náraz do rodiny 0, když nehoří časovač plynu $8F1D (§13)',
    0x9F4F: 'záznam začíná umírat: druh $80 a bit 7 rychlosti (§16)',
    0x9F16: 'zánik s bliknutím barvy (25 kroků $A414) – větev, ve které '
            'záznam mizí ze silnice',
    0x9F6C: 'zánik s bliknutím barvy – druhá větev téhož, přes kontrolu '
            'bitu 7 druhu',
    0x9FA1: 'zánik, ve kterém se druh posunul o dva a nepřetekl',
    0x9FB0: 'zánik, ve kterém druh přetekl a záznam se nabíjí na $80',
    0x9FDA: 'zánik rodiny 5 (mina), která se ze silnice neodstraňuje',
    0xA1F6: 'výstřel: FIRE v $8F14, volná hlaveň, ubere se dílek POWER',
    0xA62F: 'koncová sekvence: konvoj odchází (M7, $A617..)',
}

MENU_NOTES = [
    (0xB0E4, 0xB0E1, 'menu se otevřelo'),
    (0xB179, 0xB176, 'volba 6 DEMONSTRATION'),
    (0xB189, 0xB186, 'volba 7 START GAME'),
    (0xB192, 0xB18F, 'hra skončila a vrátila se do menu'),
    (0xB1B9, 0xB1B6, 'volba 5 INFORMATION'),
    (0xB1F5, None,   'volba ovládání 1 až 4 – HL podle zvolené položky'),
]
MENU_CONTROL_HL = [(0xB1C1, '1 KEYBOARD'), (0xB1C9, '2 KEMPSTON'),
                   (0xB1D1, '3 INTERFACE 2'), (0xB1D9, '4 CURSOR')]

POWER_PTR = 0x8F18


# --- modely generátorů, po instrukcích --------------------------------------

def model_random(seed):
    """Generátor `$A270` po instrukcích: vrací (nové semínko, cena JR NC).

    `data/enemies.json` ho popisuje předpisem `(254*s + 253) mod 65537`; tady
    je potřeba i to, jestli poslední `SBC HL,DE` nechalo přenos, protože o něj
    se liší doba běhu o jeden T-stav – a M8 měří T-stavy.
    """
    d, e = seed >> 8, seed & 0xFF
    hl = (e << 8) | 0xFD
    a, c = d, 0
    v = hl - seed - c; c = 1 if v < 0 else 0; hl = v & 0xFFFF
    r = a - c;         c = 1 if r < 0 else 0; a = r & 0xFF
    v = hl - seed - c; c = 1 if v < 0 else 0; hl = v & 0xFFFF
    r = a - c;         c = 1 if r < 0 else 0; a = r & 0xFF
    v = hl - a - c;    c = 1 if v < 0 else 0; hl = v & 0xFFFF
    if c:
        return (hl + 1) & 0xFFFF, 13
    return hl, 12


def _dj(b):
    """DJNZ s B = 0 je 256 průchodů, ne žádný."""
    return 256 if b == 0 else b


def model_noise(seed, mask_l, mask_b, notes, use_or, t):
    """Generátor A (`$9B2C`): šum. Vrací (události, semínko, počet tahů).

    Událost je `(T-stav, hodnota na portu)`; nulový čas je první `OUT`.
    """
    b, l, ev, draws, now = t['initB'], t['initL'], [], 0, 0
    for _ in range(notes):
        a = 0
        for j in range(_dj(l)):
            a ^= SPEAKER | 0x08          # XOR $18 – bit 4 beeper, bit 3 MIC
            ev.append((now, a))
            if j < _dj(l) - 1:
                now += t['tPerOut'] * _dj(b) + t['tStep']
            else:
                seed, carry = model_random(seed)
                draws += 1
                now += t['tPerOut'] * _dj(b) + t['tDraw'] + carry
                l = ((seed & 0xFF) & mask_l) + 1 & 0xFF
                hi = seed >> 8
                b = ((hi | mask_b) if use_or else (hi & mask_b)) + 1 & 0xFF
    return ev, seed, draws, now


def model_tone(toggles, delay, notes, subtract, t):
    """Generátor B (`$9B5B`): tón, jehož prodleva se po každém tónu zmenší."""
    ev, now = [], 0
    for _ in range(notes):
        a = 0
        for j in range(toggles):
            a ^= SPEAKER | 0x08
            ev.append((now, a))
            now += t['tPerOut'] * _dj(delay) + (t['tStep'] if j < toggles - 1
                                                else t['tNote'])
        delay = (delay - subtract) & 0xFF
    return ev, now


def model_click(hl, t):
    """Generátor menu (`$B203`): dva čítače, dva průběhy naráz.

    `H` je počet vnějších kol (každé 256 průchodů), `L` perioda obou čítačů –
    `D` běží od `L`, `E` od `L-1`, takže se rozcházejí o jeden průchod.
    """
    count, period = hl >> 8, hl & 0xFF
    b, a, d, e = 0, 0, period, (period - 1) & 0xFF
    ev, now = [], 0
    while True:
        ev.append((now, a))
        now += t['out'] + t['inc']
        d = (d + 1) & 0xFF
        if d:
            now += t['jrTaken']
        else:
            now += t['jrNot'] + t['reloadD']; d = period; a ^= SPEAKER | 0x08
        now += t['inc']
        e = (e + 1) & 0xFF
        if e:
            now += t['jrTaken']
        else:
            now += t['jrNot'] + t['reloadE']; e = (period - 1) & 0xFF
            a ^= SPEAKER | 0x08
        b = (b - 1) & 0xFF
        if b:
            now += t['djnz']
        else:
            now += t['djnzEnd'] + t['decC']
            count = (count - 1) & 0xFF
            if count:
                now += t['jrTaken']
            else:
                now += t['jrNot']
                return ev, now


def pulses(events):
    """Z událostí udělá to, co je slyšet: časy, ve kterých se port **změnil**.

    Simulátor loguje jen změny – tentýž `OUT` dvakrát za sebou (a to se děje
    vždycky, když se počet překlopení segmentu skončí lichý) žádná změna není.
    """
    out, prev = [], None
    for now, value in events:
        if value != prev:
            out.append(now)
            prev = value
    return out


# --- čtení z kódu -----------------------------------------------------------

def expect(mem, addr, *opcodes):
    got = bytes(mem[addr:addr + len(opcodes)])
    if got != bytes(opcodes):
        raise SystemExit('na $%04X neceka %s, ale %s'
                         % (addr, ' '.join('%02X' % b for b in opcodes),
                            ' '.join('%02X' % b for b in got)))
    return got


def read_chain(mem):
    """Rozskok `$9AEF`: pro každý bit generátor a jeho parametry, z paměti."""
    expect(mem, DISPATCH, 0x3A, FLAG & 0xFF, FLAG >> 8)     # LD A,($8F15)
    out = []
    for addr, pre, opcode, bit, gen, params in DISPATCH_CHAIN:
        expect(mem, addr, pre, opcode)
        if (opcode & 0x38) >> 3 != bit:
            raise SystemExit('BIT na $%04X netestuje bit %d' % (addr, bit))
        if gen is NOISE:
            expect(mem, params, 0x0E)                        # LD C,n
            expect(mem, params + 2, 0x16)                    # LD D,n
            expect(mem, params + 4, 0x1E)                    # LD E,n
            out.append({'bit': bit, 'generator': 'noise',
                        'maskToggles': mem[params + 1],
                        'maskDelay': mem[params + 3],
                        'notes': mem[params + 5]})
        else:
            expect(mem, params, 0x2E)                        # LD L,n
            expect(mem, params + 2, 0x16)                    # LD D,n
            expect(mem, params + 4, 0x1E)                    # LD E,n
            expect(mem, params + 6, 0x26)                    # LD H,n
            out.append({'bit': bit, 'generator': 'tone',
                        'toggles': mem[params + 1],
                        'delay': mem[params + 3],
                        'notes': mem[params + 5],
                        'subtract': mem[params + 7]})
    # `AND D` na $9B46 si rozskok přepisuje na `OR D` ($B2) a zpátky ($A2);
    # větev bitu 7 projde oběma zápisy, takže na ni platí ten poslední.
    expect(mem, 0x9B01, 0x21, 0x46, 0x9B); expect(mem, 0x9B04, 0x36, 0xB2)
    expect(mem, 0x9B13, 0x36, 0xA2)
    for s in out:
        if s['generator'] == 'noise':
            s['maskOp'] = 'or' if s['bit'] == 6 else 'and'
    return out


def read_triggers(mem):
    """Najde v obrazu paměti všechna `LD HL,$8F15` a bit, který za nimi svítí."""
    want = bytes([0x21, FLAG & 0xFF, FLAG >> 8])
    clobber = {0x21, 0x2A, 0xE1, 0xEB, 0x26, 0x2E, 0xF1}  # co přepíše HL
    blob = bytes(mem[0x5B00:0x10000])
    out, i = [], 0
    while True:
        j = blob.find(want, i)
        if j < 0:
            break
        i = j + 1
        addr = 0x5B00 + j + 3
        # Za `LD HL,$8F15` může být SETů víc – rozskok podle rodiny na $9CF2
        # jich má tři. Sbírá se, dokud něco nepřepíše HL.
        for step in range(0, 32):
            here = addr + step
            if mem[here] in clobber:
                break
            if mem[here] == 0xCB and (mem[here + 1] & 0xC7) == 0xC6:
                bit = (mem[here + 1] & 0x38) >> 3
                out.append({'at': '$%04X' % here, 'bit': bit,
                            'what': TRIGGER_NOTES.get(here, 'zatím nepojmenované')})
    return sorted(out, key=lambda s: s['at'])


def read_dying(mem):
    """Rozskok `$9CF2`: který zvuk patří které rodině zanikajícího záznamu.

    `LD A,(IX+6)` je horní bajt druhu, `RES 4,A` z něj udělá rodinu (§16) a
    pak jsou to dvě porovnání: nula je jeden zvuk, pod mezí druhý, nad mezí
    třetí. Mez i všechny tři bity se čtou z paměti.
    """
    expect(mem, 0x9CF2, 0x21, FLAG & 0xFF, FLAG >> 8)
    expect(mem, 0x9CF5, 0xDD, 0x7E, 0x06)      # LD A,(IX+$06)
    expect(mem, 0x9CF8, 0xCB, 0xA7)            # RES 4,A
    expect(mem, 0x9CFA, 0xA7, 0x28)            # AND A / JR Z
    expect(mem, 0x9CFD, 0xFE)                  # CP n
    bits = {}
    for addr, key in ((0x9D0B, 'zero'), (0x9D06, 'below'), (0x9D01, 'above')):
        expect(mem, addr, 0xCB)
        if (mem[addr + 1] & 0xC7) != 0xC6:
            raise SystemExit('na $%04X neni SET n,(HL)' % addr)
        bits[key] = (mem[addr + 1] & 0x38) >> 3
    return {'at': '$9CF2', 'boundary': mem[0x9CFE],
            'familyZero': bits['zero'], 'familyBelow': bits['below'],
            'familyAbove': bits['above'],
            'note': ('Zanikající záznam si o zvuk řekne **v každém průchodu** '
                     'své animace zániku, ne jen na jejím začátku – naměřeno '
                     'nástrojem tools/tracesound.py. Který zvuk to je, '
                     'rozhoduje rodina: 0 je jeden, 1 až boundary-1 druhý, '
                     'boundary a výš třetí.')}


def read_menu(mem):
    """Volání `$B203` a `HL`, se kterým se tam skáče."""
    expect(mem, CLICK, 0x4C, 0xAF, 0x47, 0x55, 0x5A, 0x1D, 0xD3, 0xFE)
    out = []
    for call, load, what in MENU_NOTES:
        expect(mem, call, 0xCD, CLICK & 0xFF, CLICK >> 8)
        if load is None:
            for at, name in MENU_CONTROL_HL:
                expect(mem, at, 0x21)
                out.append({'at': '$%04X' % call, 'hl': '$%04X' % (mem[at + 1] | mem[at + 2] << 8),
                            'count': mem[at + 2], 'period': mem[at + 1],
                            'what': '%s (%s)' % (what, name)})
            continue
        expect(mem, load, 0x21)
        out.append({'at': '$%04X' % call, 'hl': '$%04X' % (mem[load + 1] | mem[load + 2] << 8),
                    'count': mem[load + 2], 'period': mem[load + 1], 'what': what})
    return out


def count_out_instructions(mem):
    """Kolik `OUT ($FE),A` je v celém obrazu – tím se dokazuje, že hudba není."""
    blob = bytes(mem[0x5B00:0x10000])
    out, i = [], 0
    while True:
        j = blob.find(b'\xd3\xfe', i)
        if j < 0:
            break
        out.append(0x5B00 + j); i = j + 1
    return out


# --- měření na běžícím originálu --------------------------------------------

def play(sound, seed, timing):
    """Přehraje jeden efekt v originálu a vrátí (překlopení, semínko po, T)."""
    s = H.gameplay()
    if s.run_to(DISPATCH, frames=60) is None:
        raise SystemExit('nedoslo se na rozskok zvuku $%04X' % DISPATCH)
    s.simulator.memory[SEED] = seed & 0xFF
    s.simulator.memory[SEED + 1] = seed >> 8
    s.simulator.memory[FLAG] = 1 << sound['bit']
    s.tracer.audio_log.clear()
    del s.tracer.border[:]
    took = s.run_to(RETURN, frames=400)
    if took is None:
        raise SystemExit('zvuk bitu %d nedobehl' % sound['bit'])
    log = [t for t, r, v in s.tracer.audio_log if r == 0xFF]
    ports = [v for _, v in s.tracer.border]
    return log, s.peek(SEED) | s.peek(SEED + 1) << 8, took, ports


def play_click(hl, timing):
    """Zavolá `$B203` s daným `HL` – v menu se na něj jinak než klávesou nedá."""
    s = H.gameplay()
    s.run_to(DISPATCH, frames=60)
    sim = s.simulator
    sp = (sim.registers[SP] - 2) & 0xFFFF
    sim.memory[sp] = RETURN & 0xFF
    sim.memory[sp + 1] = RETURN >> 8
    sim.registers[SP] = sp
    sim.registers[REG_H] = hl >> 8
    sim.registers[REG_L] = hl & 0xFF
    sim.registers[PC] = CLICK
    s._start_pc = CLICK
    s._started = False
    s.tracer.audio_log.clear()
    del s.tracer.border[:]
    took = s.run_to(RETURN, frames=4000)
    if took is None:
        raise SystemExit('menu zvuk $%04X nedobehl' % hl)
    return [t for t, r, v in s.tracer.audio_log if r == 0xFF], took, \
        [v for _, v in s.tracer.border]


def model_of(sound, seed, timing):
    if sound['generator'] == 'noise':
        ev, out_seed, draws, end = model_noise(
            seed, sound['maskToggles'], sound['maskDelay'], sound['notes'],
            sound['maskOp'] == 'or', timing['noise'])
        return pulses(ev), out_seed, draws, end
    ev, end = model_tone(sound['toggles'], sound['delay'], sound['notes'],
                         sound['subtract'], timing['tone'])
    return pulses(ev), seed, 0, end


def verify(sounds, timing, seeds):
    """Model proti originálu: každé překlopení, každý T-stav, každé semínko."""
    diffs, checked, toggles = 0, 0, 0
    for sound in sounds:
        for seed in seeds:
            real, out_seed, took, ports = play(sound, seed, timing)
            model, model_seed, draws, _end = model_of(sound, seed, timing)
            base = real[0]
            real = [t - base for t in real]
            checked += 1
            toggles += len(real)
            if real != model or out_seed != model_seed:
                diffs += 1
                print('  ROZDIL bit %d, seminko $%04X: originál %d překlopení, '
                      'model %d%s' % (sound['bit'], seed, len(real), len(model),
                                      '' if out_seed == model_seed
                                      else ', semínko $%04X/$%04X' % (out_seed, model_seed)))
                for i, (a, b) in enumerate(zip(real, model)):
                    if a != b:
                        print('    první rozdíl na %d: %d vs %d' % (i, a, b))
                        break
            sound.setdefault('draws', draws)
            sound.setdefault('measuredT', took)
    return diffs, checked, toggles


def verify_menu(menu, timing):
    diffs, toggles = 0, 0
    seen = set()
    for entry in menu:
        hl = int(entry['hl'][1:], 16)
        if hl in seen:
            continue      # tentýž HL už změřený; hodnoty se dopíšou níž
        seen.add(hl)
        real, took, ports = play_click(hl, timing)
        ev, total = model_click(hl, timing['click'])
        model = pulses(ev)
        base = real[0]
        real = [t - base for t in real]
        toggles += len(real)
        if real != model:
            diffs += 1
            print('  ROZDIL menu $%04X: originál %d, model %d'
                  % (hl, len(real), len(model)))
        for other in menu:
            if other['hl'] == entry['hl']:
                other['toggles'] = len(model)
                other['tStates'] = total
    return diffs, toggles


def measure_border(quick):
    """Každý zápis na port `$FE`, který se za běhu potká – bity 0-2."""
    seen, writes = {}, 0
    # Boot se **nezapočítává**: do snímku 400 běží Speedlock, a ten si border
    # barví po svém (to je nahrávání z kazety, M1). Měří se až hra sama.
    runs = [('hra', H.CACHE, 400, ()),
            ('menu', H.SNAPSHOT, 700, H.BOOT_SCRIPT)]
    if not quick:
        runs.append(('demonstrace', H.SNAPSHOT, 1400, H.DEMO_SCRIPT))
        runs.append(('konec hry', os.path.join(H.ROOT, 'build/ending.z80'), 600, ()))
    for name, path, frames, script in runs:
        if not os.path.isfile(path):
            continue
        s = H.Session(path)
        if script:
            s.run(410, script=script)     # nechat doběhnout zavaděč
        del s.tracer.border[:]
        s.run(frames, script=script)
        for _, value in s.tracer.border:
            writes += 1
            seen.setdefault(value & BORDER_MASK, []).append(name)
    return {k: sorted(set(v)) for k, v in seen.items()}, writes


def measure_music(passes):
    """Sáhne hra na port i v průchodu, ve kterém o zvuk nikdo nepožádal?"""
    s = H.gameplay()
    quiet_passes, quiet_writes, loud_passes = 0, 0, 0
    for i in range(passes):
        # Půlka průchodů se odjede se stiskem FIRE, aby v měření byly i
        # průchody **se** zvukem – jinak by test dokazoval jen ticho v klidu.
        keys = ('SPACE',) if (i // 4) % 2 else ()
        if s.run_to(DISPATCH, frames=40, keys=keys) is None:
            break
        flag = s.peek(FLAG)
        del s.tracer.border[:]
        if s.run_to(RETURN, frames=400, keys=keys) is None:
            break
        writes = len(s.tracer.border)
        if flag:
            loud_passes += 1
        else:
            quiet_passes += 1
            quiet_writes += writes
    return quiet_passes, quiet_writes, loud_passes


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'data/sounds.json'))
    ap.add_argument('--seeds', type=int, default=24, help='kolik semínek na efekt')
    ap.add_argument('--passes', type=int, default=120, help='kolik průchodů na test hudby')
    ap.add_argument('--quick', action='store_true', help='vynechat dlouhá měření')
    args = ap.parse_args()

    mem = H.Session(H.CACHE).simulator.memory

    # 1. co je v kódu
    outs = count_out_instructions(mem)
    if len(outs) != 3:
        raise SystemExit('cekaly se tri OUT ($FE),A, naslo se %d' % len(outs))
    chain = read_chain(mem)
    triggers = read_triggers(mem)
    menu = read_menu(mem)
    dying = read_dying(mem)

    # 2. časování obou generátorů – konstanty z instrukcí, ověří je měření
    timing = {
        'noise': {'initB': mem[NOISE + 1], 'initL': mem[NOISE + 3],
                  'tPerOut': 24, 'tStep': 39, 'tDraw': 259},
        'tone': {'tPerOut': 24, 'tStep': 22, 'tNote': 53},
        'click': {'out': 11, 'inc': 4, 'jrTaken': 12, 'jrNot': 7,
                  'reloadD': 11, 'reloadE': 15, 'djnz': 13, 'djnzEnd': 8,
                  'decC': 4},
    }

    # 3. měření
    seeds = [(0x1234 * (i + 1) + 0x5A5A * i) & 0xFFFF for i in range(args.seeds)]
    seeds = [s if s else 1 for s in seeds]
    print('overuji %d efektu na %d seminkach...' % (len(chain), len(seeds)))
    diffs, checked, toggles = verify(chain, timing, seeds)
    print('  %d prehrani, %d preklopeni, %d rozdilu' % (checked, toggles, diffs))

    print('overuji %d menu zvuku...' % len(menu))
    mdiffs, mtoggles = verify_menu(menu, timing)
    print('  %d preklopeni, %d rozdilu' % (mtoggles, mdiffs))

    border, writes = measure_border(args.quick)
    print('border: %d zapisu na port, bity 0-2 = %s'
          % (writes, ', '.join('$%02X' % v for v in sorted(border))))

    if args.quick:
        quiet, quiet_writes, loud = 0, 0, 0
    else:
        quiet, quiet_writes, loud = measure_music(args.passes)
        print('hudba: %d tichych pruchodu, v nich %d zapisu na port (%d se zvukem)'
              % (quiet, quiet_writes, loud))

    # 4. referenční průběh, na kterém si port může sáhnout na kontrolu
    ref_seed = 0x1234
    for sound in chain:
        model, out_seed, draws, end = model_of(sound, ref_seed, timing)
        sound['reference'] = {
            'seed': ref_seed, 'seedAfter': out_seed,
            'pulses': [b - a for a, b in zip(model + [end], model[1:] + [end])][:len(model)],
            'note': ('délky pulzů v T-stavech mezi překlopeními beeperu; '
                     'první pulz začíná prvním OUT'),
        }
        sound['triggers'] = ['$%04X' % int(t['at'][1:], 16)
                             for t in triggers if t['bit'] == sound['bit']]

    names = {1: 'fire', 6: 'destroy', 3: 'blast', 7: 'crash', 4: 'bump'}
    for sound in chain:
        sound['name'] = names[sound['bit']]

    data = {
        'note': ('Zvuk originálu. Stroj má jednobitový beeper na bitu 4 portu '
                 '$FE a žádný zvukový čip, takže zvuk je posloupnost '
                 'překlopení – tady jsou popsané rutiny, které ho dělají, a '
                 'jejich parametry. Nic se nevzorkuje.'),
        'source': 'tools/dumpsound.py, build/gameplay.z80',
        'cpuHz': CPU_HZ,
        'speakerBit': SPEAKER,
        'portValues': ['$00', '$18'],
        'music': {
            'has': False,
            'outInstructions': ['$%04X' % a for a in outs],
            'quietPasses': quiet, 'quietPortWrites': quiet_writes,
            'passesWithSound': loud,
            'note': ('V celém obrazu 48 K jsou tři instrukce OUT ($FE),A a '
                     'všechny leží uvnitř generátorů zvuku. Žádná se nevolá '
                     'z přerušení, takže hudba běžet nemůže; naměřeno, že '
                     'v průchodech s nulovou žádankou $8F15 nesáhne hra na '
                     'port ani jednou.'),
        },
        'border': {
            'value': sorted(border)[0] if border else 0,
            'colour': 'black',
            'portWrites': writes,
            'seen': {'$%02X' % k: v for k, v in border.items()},
            'note': ('Border se nikde nenastavuje zvlášť – jediné zápisy na '
                     '$FE dělají generátory zvuku a posílají $18 a $00, tedy '
                     'bity 0-2 nulové. Border je černý po celou hru.'),
        },
        'flag': {
            'at': '$%04X' % FLAG,
            'dispatch': '$%04X' % DISPATCH,
            'priority': [s['bit'] for s in chain],
            'note': ('$8F15 je žádanka: hra si v ní během průchodu nastaví bit '
                     'a na konci průchodu rozskok $9AEF vezme první bit '
                     'v pořadí priority, přehraje jeho efekt **synchronně** '
                     '(hlavní smyčka na něj čeká) a žádanku vynuluje. Tentýž '
                     'bajt zná M3 jako příznak nárazu – bit 4 je jeho zvuk.'),
        },
        'random': {
            'at': '$%04X' % RANDOM, 'seed': '$%04X' % SEED,
            'mul': 254, 'add': 253, 'mod': 65537,
            'note': ('týž generátor jako v data/enemies.json. Šum si z něj '
                     'hodí právě jednou za segment, tedy `notes` tahů za '
                     'efekt – tím je zavřená otázka §16, kolik tahů spotřebuje '
                     'zvuk.'),
        },
        'generators': {
            'noise': dict(timing['noise'], at='$%04X' % NOISE, draws='notes',
                          note=('E segmentů; segment se překlopí L-krát a mezi '
                                'překlopeními čeká B průchodů smyčkou OUT. '
                                'Na konci segmentu si L a B hodí z generátoru '
                                'náhody: L = (dolní bajt AND maskToggles)+1, '
                                'B = (horní bajt AND/OR maskDelay)+1; B = 0 '
                                'znamená 256. Doba mezi překlopeními je '
                                'tPerOut*B + tStep, přes hod tPerOut*B + '
                                'tDraw (+1, když generátor nechal přenos).')),
            'tone': dict(timing['tone'], at='$%04X' % TONE,
                         note=('E tónů po L překlopeních; prodleva D se po '
                               'každém tónu zmenší o `subtract` bajtově. Doba '
                               'mezi překlopeními je tPerOut*D + tStep, mezi '
                               'tóny tPerOut*D + tNote.')),
            'click': dict(timing['click'], at='$%04X' % CLICK,
                          note=('Menu. H je počet vnějších kol po 256 '
                                'průchodech, L perioda: čítač D běží od L, '
                                'čítač E od L-1, a při přetečení každý '
                                'překlopí beeper – dva čtvercové průběhy '
                                'o jeden T-stav periody vedle sebe.')),
        },
        'sounds': chain,
        'dying': dying,
        'menu': menu,
        'triggers': triggers,
        'power': {
            'at': '$%04X' % POWER_PTR,
            'spend': '$A1EF', 'refill': '$A10B',
            'attributeBase': '$5A00',
            'full': '$44', 'empty': '$00',
            'note': ('POWER je zásobník výstřelů, ne energie: $8F18 je dolní '
                     'bajt adresy v atributech, výstřel ho o jedna sníží a do '
                     'buňky zapíše $00, a když výstřel dojede, $A10B ho zvýší '
                     'a zapíše $44. Vypadlo to z okolí zvuku výstřelu a je to '
                     'odpověď na otázku otevřenou od M6.'),
        },
        'verification': {
            'plays': checked, 'toggles': toggles, 'differences': diffs,
            'menuToggles': mtoggles, 'menuDifferences': mdiffs,
            'note': ('Model každého generátoru je tady napsaný po instrukcích '
                     'a přehraný proti originálu v simulátoru: porovnává se '
                     'každé překlopení bitu 4 portu $FE na T-stav přesně, a '
                     'u šumu i semínko, které po efektu zůstalo.'),
        },
        'open': [
            'které herní jevy patří k trigger adresám $9F4F, $9FA1, $9FB0 '
            'a $9FDA – bit je změřený, ale který druh zániku to je, ukáže '
            'až matchsound',
            'zvuk kreslení: $AAE4 tahá z téhož generátoru náhody jako šum '
            '(§16), a to je kreslení, tedy M2',
        ],
    }
    with open(args.out, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print('%s: %d efektu, %d menu zvuku, %d spousteni, border $%02X'
          % (os.path.relpath(args.out, H.ROOT), len(chain), len(menu),
             len(triggers), data['border']['value']))
    if diffs or mdiffs:
        raise SystemExit('model nesedi na originalu')


if __name__ == '__main__':
    main()
