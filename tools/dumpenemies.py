#!/usr/bin/env python3
"""Odměří na běžícím originálu **nepřátele a pravidla srážek** → `data/enemies.json` (M6).

    PYTHONPATH=tools/vendor ./tools/dumpenemies.py [--out data/enemies.json]

M4 i M5 si nepřátele každý průchod brali ze záznamu, protože se o nich nevědělo
nic (`disasm_notes.md` §14, §15). Tenhle nástroj to zavírá – a proti M3/M4/M5
jinak: hra si totiž **pravidla drží v tabulkách**, a ty se dají z běžící hry
přečíst a pak na naměřených průchodech ověřit. Nic se neodhaduje ani netipuje:

* **kdo je čí druh.** Rodina objektu je horní bajt slova druhu (`+5/+6`) bez
  bitu 4 – proto se `$0330` a `$1378` chovají stejně. Rodin je jedenáct.
* **tabulka kroku** na `$8E00`: pro každou rychlost a každý z osmi směrů
  posun `x`, posun `y`, posun fáze animace a dva posuny hloubky.
* **matice srážek** na `$9000`: 11 × 11 dvoubajtových adres. Kdo do koho
  narazil, rozhoduje o tom, co se stane – a bajt `+11` záznamu je rovnou
  `22 × rodina`, tedy řádek téhle matice. Tím je vysvětlené i to, co M4
  naměřila u strkání a co M5 u konvoje.
* **náhoda.** Nepřátelé se rozhodují náhodně, ale ne nepředvídatelně: hra má
  vlastní generátor `SEED' = (254 × SEED + 253) mod 65537` nad spectráckou
  systémovou proměnnou `$5C76`, a ten se dá přenést bit po bitu. Ověřuje se
  měřením: po každém průchodu se hledá, kolikrát se generátor otočil.
* **rodiny nepřátel** 2, 3, 4 a 5 a jejich pohyb: kdo jede pořád rovně, kdo
  se vrtí, kdo si směr tahá z náhody a kdo se na překážce obrací.
* **zánik**: druh se posouvá po osmi od `$80`, dokud nedojde na `$DC`.
* **tabulka je delší než 24 záznamů** – §12 měřila jen první zóny.
* **rozmístění**: kolik čeho je v které zóně (z režimu `6 DEMONSTRATION`,
  který si projede celou silnici sám).
* **`TIME`**: co odpočítává a kdy ubere ukazateli dílek.

Odměřená pravidla se pak **přehrají proti originálu**: referenční model
(`enemy_pass()` níž) se pustí na každý naměřený průchod každého nepřítele a
hlásí se každý rozdíl. Tenhle model je předloha pro `app/highwayEnemies.js`;
nezávisle na něm ho na jiných scénářích kontroluje `tools/matchenemies.js`.
"""
import argparse, collections, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

SLOTS = 48                    # kolik záznamů se čte (naměřeno max 42, viz níž)
EMPTY_X, END_X = 0xFE, 0xFF   # prázdné místo / konec tabulky
FAMILY_MASK = 0xEF            # rodina = horní bajt druhu bez bitu 4
FAMILIES = 11
ROW_STRIDE = 22               # 11 dvoubajtových adres na řádek matice
STEP_TABLE = 0x8E00
DIR_MASKS = 0x8FF0
MATRIX = 0x9000
SEED_ADDR = 0x5C76
TABLE_PTR = 0x8F01
WINDOW = 0x8F05
TIME_COUNTER = 0x8F1A
TIME_BAR = 0x8F19
RND_MUL, RND_ADD, RND_MOD = 254, 253, 65537
ENEMY_FAMILIES = (2, 3, 4, 5)
BOX = 0x0F                    # krok se zahodí, když je rozdíl menší než 15, tj. ±7
DEATH_START, DEATH_STEP, DEATH_LIMIT = 0x80, 8, 0xDC
WANDER_LEFT, WANDER_RIGHT = 0xF5, 0x0A

# co která adresa v matici srážek dělá; jména jsou z pohledu toho, kdo narazil
HANDLERS = {
    0x9ED7: 'stop',              # krok se zahodí (Vortonovi navíc ohlásí náraz)
    0x9E12: 'halveSpeed',        # krok se zahodí a rychlost se půlí
    0x9E6D: 'pushLasertron',     # Vorton do Lasertronu zezadu – rozjede ho
    0x9E8E: 'objectIntoObject',  # strčený předmět předá strčení dál (M4)
    0x9EBB: 'shotShoves',        # výstřel strčí předmět (M4)
    0x9EBF: 'shove',             # Vorton strčí předmět (M4)
    0x9F02: 'passThrough',       # nevšímat si a hledat dál
    0x9F06: 'killedByShot',      # nepřítele sundal výstřel
    0x9F20: 'dieOnEnemy',        # Vorton se dotkl nepřítele
    0x9F54: 'shotKillsEnemy',    # výstřel z pohledu výstřelu
    0x9F7D: 'shotMelts',         # bedna, která po zásahu roztaje
    0x9FB5: 'killVorton',        # nepřítel se dotkl Vortona
    0x9FDF: 'eatShot',           # výstřel se sní (řízený Vorton ho pustí)
    0x9FEF: 'shotStopsUnlessPlayer',
    0xA001: 'shotGone',
    0xA008: 'randomEvenDir',     # nový směr: náhodně 0/2/4/6
    0xA014: 'randomDir',         # nový směr: náhodně 0–7
    0xA020: 'randomLane',        # nová dráha z náhody, pak směr z její masky
    0xA02C: 'reverse',           # obrátit se
}
# rodina 7 = „okraj silnice / mimo okno", tam se skáče se sloupcem 7
WALL_COLUMN = 7
ROLE = {
    0: 'řízený i automatický Vorton',
    1: 'výstřel',
    2: 'nepřítel, který jede rovně a na překážce si hodí nový směr po 90°',
    3: 'nepřítel, který se vrtí a na překážce si hodí kterýkoli směr',
    4: 'nepřítel, který si směr tahá z náhody podle své dráhy',
    5: 'mina: jezdí tam a zpátky a výstřel ji nesundá',
    6: 'předmět, kterým nepřátelé i výstřely projdou',
    7: 'předmět, do kterého se dá narážet (řada napříč silnicí)',
    8: 'předmět, který po zásahu roztaje',
    9: 'Lasertron – a s bitem 4 nepohnutelný předmět, který bere rychlost, '
       'ale náraz neohlásí (M4 ho měřila jako $19F0)',
    10: 'předmět, který se dá strčit ($1A68) – a s nulovým bitem 4 jeho '
        'nepohnutelná varianta',
}

# Adresy v kódu, ze kterých se čtou konstanty pravidel. Do M6 se hra měřila
# jen zvenčí; §16 poprvé ukazuje i kód, takže se konstanty nečtou z odhadu,
# ale z bajtu, na kterém stojí – a hned se srovnají s tím, co říká měření.
CONST = {
    'boxX': 0x9E2E,          # CP $0F na rozdílu x
    'boxY': 0x9E41,          # CP $0F na rozdílu y
    'deathStep': 0x9CDF,     # ADD A,$08 v animaci zániku
    'deathLimit': 0x9CE1,    # CP $DC – kdy záznam zmizí
    'wanderLeft': 0x9DEC,    # CP $F5
    'wanderRight': 0x9DFD,   # CP $0A
    'timeReload': 0x91C1,    # LD HL,$0DAC – nabití počítadla TIME
    'timeBarEnd': 0x91AE,    # CP $D4 – kde ukazatel TIME končí
}


def rnd(seed):
    """Generátor hry: `SEED' = (254 × SEED + 253) mod 65537` na `$5C76`."""
    return (RND_MUL*seed + RND_ADD) % RND_MOD


def family(cls_high):
    return cls_high & FAMILY_MASK


class Rec:
    """Jeden 16bajtový záznam tabulky objektů, jak ho má originál."""
    __slots__ = ('b',)

    def __init__(self, b):
        self.b = bytearray(b)

    def __getitem__(self, i):
        return self.b[i]

    def __setitem__(self, i, v):
        self.b[i] = v & 0xFF

    @property
    def x(self):
        return self.b[0]

    @property
    def y(self):
        return self.b[1] | self.b[2] << 8

    def sety(self, v):
        self.b[1] = v & 0xFF
        self.b[2] = (v >> 8) & 0xFF

    def cls(self):
        return self.b[6] << 8 | self.b[5]


class Tables:
    """Tabulky, které si hra drží – přečtené z běžící hry, ne z odhadu."""

    def __init__(self, s):
        self.step = bytes(s.peek(STEP_TABLE, 0x100))
        self.masks = bytes(s.peek(DIR_MASKS, 16))
        self.matrix = [[s.peek(MATRIX + ROW_STRIDE*f + 2*o)
                        | s.peek(MATRIX + ROW_STRIDE*f + 2*o + 1) << 8
                        for o in range(FAMILIES)] for f in range(FAMILIES)]
        self.tablePtr = s.peek(TABLE_PTR) | s.peek(TABLE_PTR+1) << 8
        self.const = {k: s.peek(a) for k, a in CONST.items()}
        self.const['timeReload'] = (s.peek(CONST['timeReload'])
                                    | s.peek(CONST['timeReload']+1) << 8)
        self.constAddr = {k: '$%04X' % a for k, a in CONST.items()}

    def handler(self, sfam, ofam):
        return self.matrix[sfam][ofam]

    def name(self, sfam, ofam):
        return HANDLERS.get(self.handler(sfam, ofam),
                            '$%04X' % self.handler(sfam, ofam))


def enemy_pass(tables, recs, slot, seed, window):
    """**Referenční model jednoho průchodu nepřítele** – předloha portu.

    Přesně to, co dělá originál: vezme z tabulky kroku posun podle směru a
    rychlosti, podívá se, jestli cíl leží na silnici a v okně světa, projde
    tabulku od začátku a na prvním záznamu, který je v krabici ±7, skočí do
    matice srážek. Když nic nestojí v cestě, posune se, posune si fázi
    animace a hloubku a pak si rodiny 3 a 4 vytáhnou z generátoru nový směr.

    Mění `recs` na místě (i cizí záznamy, když je do nich zasaženo) a vrací
    `(seed, co se stalo)`.
    """
    e = recs[slot]
    speed = e[8] & ~0x40                 # bit 6 = „strčený v tomhle průchodu"
    e[8] = speed
    if speed == 0:
        return seed, 'idle'
    if speed & 0x80:                     # zánik: druh se posouvá po osmi
        nxt = e[5] + DEATH_STEP
        if nxt >= DEATH_LIMIT:
            e[0] = EMPTY_X
            e[8] = speed & ~0x80
            return seed, 'gone'
        e[5] = nxt
        return seed, 'dying'

    sfam = family(e[6])
    idx = (e[7]*8 + (((speed - 1) << 6) & 0xFF)) & 0xFF
    dx = tables.step[idx]
    dy = tables.step[(idx+1) & 0xFF] | tables.step[(idx+2) & 0xFF] << 8
    nx = (e.x + dx) & 0xFF
    ny = (e.y + dy) & 0xFFFF

    def act(handler, other):
        """Vrací `(seed, 'end'|'cont')` – co matice srážek řekla."""
        name = HANDLERS.get(handler)
        if name == 'passThrough':
            return seed, 'cont'
        if name == 'eatShot':
            if e[10] != 0x0E:            # řízený Vorton výstřel pustí
                other[0] = EMPTY_X
            return seed, 'cont'
        if name == 'killedByShot':
            other[0] = EMPTY_X
            e[8] |= 0x80
            e[5] = DEATH_START
            return seed, 'end'
        if name == 'killVorton':
            if sfam != 5:                # mina zůstane, ostatní zmizí s ním
                e[0] = EMPTY_X
            if other[5] < DEATH_START:
                other[5] = DEATH_START
                other[8] |= 0x80
                return seed, 'end'
            return seed, 'cont'
        if name == 'randomEvenDir':
            s2 = rnd(seed)
            e[7] = (s2 & 0xFF) & 6
            return s2, 'end'
        if name == 'randomDir':
            s2 = rnd(seed)
            e[7] = (s2 & 0xFF) & 7
            return s2, 'end'
        if name == 'randomLane':
            s2 = rnd(seed)
            e[12] = (s2 & 0xFF) & 7
            s2 = rnd(s2)
            lane = e[12]
            e[7] = ((s2 >> 8) & tables.masks[2*lane]) | tables.masks[2*lane+1]
            return s2, 'end'
        if name == 'reverse':
            e[7] = (e[7] + 4) & 7
            return seed, 'end'
        if name == 'halveSpeed':
            e[8] = (e[8] & ~0x40) >> 1
            return seed, 'end'
        return seed, 'end'                # stop a všechno ostatní: krok se zahodí

    if nx >= 0x49:                        # mimo silnici
        seed, _ = act(tables.handler(sfam, WALL_COLUMN), None)
        return seed, 'wall'
    if (((ny - window) & 0xFFFF) >> 8) >= 2:      # mimo okno světa
        seed, _ = act(tables.handler(sfam, WALL_COLUMN), None)
        return seed, 'window'

    left = (nx - 7) & 0xFF
    back = (ny - 7) & 0xFFFF
    j = 0
    while j < SLOTS:
        o = recs[j]
        if o[0] == END_X:
            break
        if o[0] == EMPTY_X or ((o[0] - left) & 0xFF) >= BOX:
            j += 1
            continue
        dyy = (o.y - back) & 0xFFFF
        if (dyy >> 8) != 0 or (dyy & 0xFF) >= BOX:
            j += 1
            continue
        if j == slot:
            j += 1
            continue
        seed, what = act(tables.handler(sfam, family(o[6])), o)
        if what == 'end':
            return seed, 'hit'
        j += 1

    e[0] = (left + 7) & 0xFF
    e.sety((back + 7) & 0xFFFF)
    phase = (tables.step[(idx+3) & 0xFF] + e[9]) & 0xFF
    if phase < 0x0D:
        depth = idx + 4
    else:
        phase = phase - 0x10 if phase < 0x80 else phase + 0x10
        depth = idx + 6
    e[9] = phase & 0xFF
    d = (e[3] | e[4] << 8) + (tables.step[depth & 0xFF]
                              | tables.step[(depth+1) & 0xFF] << 8)
    e[3] = d & 0xFF
    e[4] = (d >> 8) & 0xFF
    if sfam == 4:                         # nová dráha z masky své dráhy
        seed = rnd(seed)
        lane = e[12]
        e[7] = ((seed >> 8) & tables.masks[2*lane]) | tables.masks[2*lane+1]
    elif sfam == 3:                       # vrtění: o krok vlevo, vpravo, nebo nic
        seed = rnd(seed)
        low = seed & 0xFF
        if low >= WANDER_LEFT:
            e[7] = (e[7] - 1) & 7
        elif low < WANDER_RIGHT:
            e[7] = (e[7] + 1) & 7
    return seed, 'moved'


# --- sběr běhů ---------------------------------------------------------------

def snapshot(s):
    return {'tab': bytes(s.peek(H.ENTITIES, SLOTS*16)),
            'seed': s.peek(SEED_ADDR) | s.peek(SEED_ADDR+1) << 8,
            'window': s.peek(WINDOW) | s.peek(WINDOW+1) << 8,
            'zone': s.peek(0x8F00),
            'ptr': s.peek(TABLE_PTR) | s.peek(TABLE_PTR+1) << 8,
            'time': s.peek(TIME_COUNTER) | s.peek(TIME_COUNTER+1) << 8,
            'bar': s.peek(TIME_BAR)}


def play(sess, keys, steps):
    rows = [snapshot(sess)]
    for i in range(steps):
        try:
            sess.step(keys(i))
        except RuntimeError:
            break
        rows.append(snapshot(sess))
    return rows


def random_keys(seed, steps, prefix=40):
    rndm = random.Random(seed)
    out, held = [], ('1',)
    for i in range(steps):
        if i < prefix:
            out.append(('1',))
            continue
        if rndm.random() < 0.3:
            held = tuple(k for k in ('1', 'Q', 'O', 'P', 'SPACE')
                         if rndm.random() < 0.5)
        out.append(held)
    return lambda i: out[i] if i < len(out) else ()


DIRS = [(0, 2), (-1, 1), (-2, 0), (-1, -1), (0, -2), (1, -1), (2, 0), (1, 1)]


def dir_towards(dx, dy):
    """Který z osmi směrů vede nejblíž k `(dx, dy)`."""
    best, score = 0, None
    for d, (sx, sy) in enumerate(DIRS):
        n = (sx*sx + sy*sy) ** 0.5
        v = (sx*dx + sy*dy) / n
        if score is None or v > score:
            best, score = d, v
    return best


def hunt(sess, shoot):
    """Klávesy, které dovezou řízeného Vortona k nejbližšímu nepříteli.

    Uzavřená smyčka: mezi průchody se přečte tabulka a stiskne se, co je
    potřeba. Hra se tím nijak nemění – je to jen jiný způsob, jak napsat
    skript kláves, a jediný, kterým se dá **spolehlivě** dojet k tomu, aby se
    Vorton nepřítele dotkl (rodina 0, `dieOnEnemy`) nebo ho sestřelil
    (`killedByShot`). Bez toho se zánik na naměřených bězích neobjeví.
    """
    tab = sess.peek(H.ENTITIES, SLOTS*16)
    me = None
    targets = []
    for i in range(SLOTS):
        e = Rec(tab[i*16:(i+1)*16])
        if e[0] == END_X:
            break
        if e[0] == EMPTY_X or e[5] >= DEATH_START:
            continue
        if e.cls() == 0 and e[10] == 0x0E:
            me = e
        elif family(e[6]) in ENEMY_FAMILIES:
            targets.append(e)
    if me is None or not targets:
        return ('1',)
    t = min(targets, key=lambda e: abs(e.x-me.x) + abs(e.y-me.y))
    want = dir_towards(t.x - me.x, t.y - me.y)
    delta = (want - me[7]) & 7
    keys = []
    if delta:
        keys.append('P' if delta <= 4 else 'O')     # P otáčí o +1, O o −1
    if shoot and delta == 0:
        keys.append('SPACE')
    keys.append('1')
    return tuple(keys)


def play_closed(sess, keyfn, steps):
    """Jako `play()`, jen se klávesy počítají z toho, co je právě v tabulce."""
    rows = [snapshot(sess)]
    for i in range(steps):
        try:
            sess.step(keyfn(sess))
        except RuntimeError:
            break
        rows.append(snapshot(sess))
    return rows


def runs(count, steps, demo_steps):
    """Demo projede celou silnici a je jediný zdroj pozdějších rodin nepřátel;
    rozehraná hra k tomu přidá hráče, výstřely a zánik Vortona."""
    out = [('demo', play(H.demo(), lambda i: (), demo_steps))]
    out.append(('ahead', play(H.gameplay(), lambda i: ('1',), steps)))
    out.append(('fire', play(H.gameplay(),
                             lambda i: ('1', 'SPACE') if i % 4 < 2 else ('1',),
                             steps)))
    out.append(('ram', play_closed(H.gameplay(),
                                   lambda s: hunt(s, False), steps)))
    out.append(('shoot', play_closed(H.gameplay(),
                                     lambda s: hunt(s, True), steps)))
    for sd in range(count):
        out.append(('random%d' % sd,
                    play(H.gameplay(), random_keys(700+sd, steps), steps)))
    return out


# --- měření ------------------------------------------------------------------

def census(rows):
    """Co v které zóně stojí – z běhu, který projede celou silnici."""
    per_zone = collections.defaultdict(collections.Counter)
    seen = {}
    for r in rows:
        counted = set()
        for i in range(SLOTS):
            e = Rec(r['tab'][i*16:(i+1)*16])
            if e[0] in (EMPTY_X, END_X):
                if e[0] == END_X:
                    break
                continue
            key = (e.cls(), e[13], e[14], e[11])
            seen[e.cls()] = e[11]
            if key in counted:
                continue
            counted.add(key)
        for key in counted:
            per_zone[r['zone']]['$%04X' % key[0]] += 0
        # počítá se **nejvyšší počet záznamů druhu, který byl v zóně vidět zároveň**
        now = collections.Counter('$%04X' % Rec(r['tab'][i*16:(i+1)*16]).cls()
                                  for i in range(SLOTS)
                                  if r['tab'][i*16] not in (EMPTY_X, END_X))
        for k, v in now.items():
            if v > per_zone[r['zone']][k]:
                per_zone[r['zone']][k] = v
    return per_zone, seen


def table_length(all_rows):
    """Kde v tabulce leží konec – §12 měřila 24 záznamů, je jich víc."""
    ends = collections.Counter()
    for name, rows in all_rows:
        for r in rows:
            end = None
            for i in range(SLOTS):
                if r['tab'][i*16] == END_X:
                    end = i
                    break
            ends[end] += 1
    return ends


def classes_by_family(all_rows):
    fam = collections.defaultdict(collections.Counter)
    b11 = collections.defaultdict(collections.Counter)
    kinds = collections.defaultdict(collections.Counter)
    for name, rows in all_rows:
        for r in rows:
            for i in range(SLOTS):
                e = Rec(r['tab'][i*16:(i+1)*16])
                if e[0] == END_X:
                    break
                if e[0] == EMPTY_X:
                    continue
                if e[5] >= DEATH_START:          # záznam v animaci zániku
                    continue
                f = family(e[6])
                fam[f]['$%04X' % e.cls()] += 1
                b11[f][e[11]] += 1
                kinds[f][e[10]] += 1
    return fam, b11, kinds


def measure_random(all_rows):
    """Kolikrát se generátor mezi průchody otočil – a kdo ho ještě používá.

    Vlastní model níž spotřebuje jen tahy nepřátel; zbytek jsou tahy, které
    si hra vzala jinde (zvuk a kreslení výbuchu, `disasm_notes.md` §16).
    """
    hist = collections.Counter()
    for name, rows in all_rows:
        for n in range(1, len(rows)):
            a, b = rows[n-1]['seed'], rows[n]['seed']
            v, k = a, 0
            while v != b and k < 64:
                v = rnd(v)
                k += 1
            hist[k if v == b else None] += 1
    return hist


def measure_time(all_rows):
    """`TIME`: co odpočítává `$8F1A` a kdy ubere ukazatel `$8F19` dílek."""
    deltas = collections.Counter()
    reloads = collections.Counter()
    bars = collections.Counter()
    for name, rows in all_rows:
        for n in range(1, len(rows)):
            d = (rows[n-1]['time'] - rows[n]['time'])
            if d == 1:
                deltas[1] += 1
            elif rows[n]['time'] > rows[n-1]['time']:
                reloads[rows[n]['time']] += 1
            else:
                deltas[d] += 1
            if rows[n]['bar'] != rows[n-1]['bar']:
                bars[(rows[n-1]['bar'], rows[n]['bar'])] += 1
    return deltas, reloads, bars


def measure_death(all_rows):
    """Animace zániku: kolik průchodů trvá a jak jde druh."""
    lengths = collections.Counter()
    steps = collections.Counter()
    causes = collections.Counter()
    for name, rows in all_rows:
        active = {}
        for n in range(1, len(rows)):
            for i in range(SLOTS):
                p = Rec(rows[n-1]['tab'][i*16:(i+1)*16])
                q = Rec(rows[n]['tab'][i*16:(i+1)*16])
                if p[0] in (EMPTY_X, END_X):
                    continue
                if (q[8] & 0x80) and not (p[8] & 0x80) and q[0] not in (EMPTY_X, END_X):
                    active[i] = [q[5], 1, family(q[6])]
                    causes[(family(p[6]), '$%02X' % q[5])] += 1
                elif i in active:
                    if q[0] in (EMPTY_X, END_X) or not (q[8] & 0x80):
                        lengths[(active[i][2], active[i][1])] += 1
                        del active[i]
                    else:
                        steps[q[5] - active[i][0]] += 1
                        active[i] = [q[5], active[i][1]+1, active[i][2]]
    return lengths, steps, causes


def verify(tables, all_rows):
    """Přehraj model na každém naměřeném průchodu nepřítele a hlas rozdíly."""
    fields = {0: 'x', 1: 'y', 2: 'y', 5: 'druh', 7: 'směr', 8: 'rychlost',
              9: 'fáze', 12: 'dráha', 3: 'hloubka', 4: 'hloubka'}
    tot = collections.Counter()
    bad = collections.Counter()
    desync = collections.Counter()
    zone_load = 0
    trimmed = 0
    removed = 0
    examples = []
    for name, rows in all_rows:
        for n in range(1, len(rows)):
            a, b = rows[n-1], rows[n]
            recs = [Rec(a['tab'][i*16:(i+1)*16]) for i in range(SLOTS)]
            after = [Rec(b['tab'][i*16:(i+1)*16]) for i in range(SLOTS)]
            seed = a['seed']
            here = []
            for slot in range(SLOTS):
                if recs[slot][0] == END_X:
                    break
                if recs[slot][0] == EMPTY_X:
                    continue
                f = family(recs[slot][6])
                if f in ENEMY_FAMILIES and (recs[slot][8] & 0x7F):
                    before = Rec(recs[slot].b)
                    seed, what = enemy_pass(tables, recs, slot, seed, a['window'])
                    ref = after[slot]
                    if ref[0] == END_X:
                        trimmed += 1              # tabulku zkrátil obsah zóny
                    elif ref[0] == EMPTY_X and recs[slot][0] != EMPTY_X:
                        # nepřítele sundal někdo, koho tohle měření nepočítá:
                        # řízený Vorton se ho dotkl ve **svém** průchodu
                        # (rodina 0, `dieOnEnemy`), a ten je M3/M4
                        removed += 1
                    elif (ref[13], ref[14], ref[11]) != (before[13], before[14],
                                                         before[11]):
                        zone_load += 1            # záznam přepsal obsah zóny (M2)
                    else:
                        tot[f] += 1
                        diff = [k for k in fields if recs[slot][k] != ref[k]]
                        if diff:
                            here.append({'run': name, 'step': n, 'slot': slot,
                                         'class': '$%04X' % before.cls(),
                                         'what': what,
                                         'field': fields[diff[0]],
                                         'got': recs[slot][diff[0]],
                                         'want': ref[diff[0]],
                                         'family': f})
                recs[slot] = Rec(after[slot].b)
            # Otočil se generátor v tomhle průchodu ještě někde jinde než
            # u nepřátel? Pak nemá port čím se řídit – tahá si z posunuté
            # sekvence (zvuk výbuchu a kreslení, §16). Takové rozdíly se
            # počítají zvlášť, ne schovávají.
            elsewhere = seed != b['seed']
            for d in here:
                if elsewhere:
                    desync[(d['family'], d['field'])] += 1
                else:
                    bad[(d['family'], d['field'])] += 1
                    if len(examples) < 8:
                        examples.append(d)
    return tot, bad, desync, zone_load, trimmed, removed, examples


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'data/enemies.json'))
    ap.add_argument('--runs', type=int, default=4, help='pseudonáhodných běhů')
    ap.add_argument('--steps', type=int, default=800)
    ap.add_argument('--demo-steps', type=int, default=1216,
                    help='kroků režimu 6 DEMONSTRATION (projede celou silnici)')
    args = ap.parse_args()

    tables = Tables(H.gameplay())
    all_rows = runs(args.runs, args.steps, args.demo_steps)
    steps = sum(len(r)-1 for _, r in all_rows)
    print('%d běhů, %d kroků originálu' % (len(all_rows), steps))

    fam, b11, kinds = classes_by_family(all_rows)
    for f in sorted(fam):
        print('rodina %2d (%s) b11=%s druhy=%s'
              % (f, ROLE.get(f, '?'), sorted(b11[f]),
                 sorted(fam[f], key=lambda k: -fam[f][k])))

    print('matice srážek $9000 (řádek = kdo narazil, sloupec = do koho):')
    for f in range(FAMILIES):
        print('  %2d %s' % (f, ' '.join('%-18s' % tables.name(f, o)
                                        for o in range(FAMILIES))))

    ends = table_length(all_rows)
    longest = max(k for k in ends if k is not None)
    print('konec tabulky: nejdál %d záznamů, histogram %s'
          % (longest, dict(sorted((k, v) for k, v in ends.items()
                                  if k is not None))))

    hist = measure_random(all_rows)
    print('otoček generátoru mezi průchody: %s'
          % dict(sorted((k, v) for k, v in hist.items() if k is not None)))

    deltas, reloads, bars = measure_time(all_rows)
    # ukazatel na startu rozehrané hry – z prvního snímku běhu, který hraje hráč
    bar_start = next(r[1][0]['bar'] for r in all_rows if r[0] != 'demo')
    ticks = bar_start - tables.const['timeBarEnd'] + 1
    print('TIME: ubývání %s, nabití %s, ukazatel %s, start $%02X → %d dílků, '
          'tedy %d průchodů na celou hru'
          % (dict(deltas), dict(reloads), dict(bars), bar_start, ticks,
             ticks*tables.const['timeReload']))

    lengths, dsteps, causes = measure_death(all_rows)
    print('zánik: délky %s, posun druhu %s, začátky %s'
          % (dict(sorted(lengths.items())), dict(dsteps),
             {('rodina %d' % k[0], k[1]): v for k, v in causes.items()}))

    tot, bad, desync, zone_load, trimmed, removed, examples = verify(tables, all_rows)
    n = sum(tot.values())
    print('model proti originálu: %d průchodů nepřátel, **%d rozdílů** (%.3f %%) '
          'a %d v průchodech, ve kterých si hra tahala z generátoru i jinde '
          '(zvuk a kreslení, §16); mimo to %d průchodů přepsal obsah nové '
          'zóny, %d zkrátilo tabulku a v %d sundal nepřítele řízený Vorton '
          've svém průchodu'
          % (n, sum(bad.values()), 100.0*sum(bad.values())/max(1, n),
             sum(desync.values()), zone_load, trimmed, removed))
    for k, v in sorted(bad.items()):
        print('   rodina %d, %s: %d' % (k[0], k[1], v))
    for k, v in sorted(desync.items()):
        print('   (posunutý generátor) rodina %d, %s: %d' % (k[0], k[1], v))
    for e in examples:
        print('   %s krok %d slot %d %s (%s): %s port %d, originál %d'
              % (e['run'], e['step'], e['slot'], e['class'], e['what'],
                 e['field'], e['got'], e['want']))

    per_zone, b11_of = census(all_rows[0][1])
    dirs = [{'and': tables.masks[2*i], 'or': tables.masks[2*i+1]}
            for i in range(8)]
    stepdata = []
    for speed in range(1, 5):
        rows = []
        for d in range(8):
            i = (d*8 + (((speed-1) << 6) & 0xFF)) & 0xFF
            dy = tables.step[i+1] | tables.step[i+2] << 8
            rows.append({'dx': tables.step[i] - (256 if tables.step[i] > 127 else 0),
                         'dy': dy - (65536 if dy > 32767 else 0),
                         'phase': tables.step[i+3] - (256 if tables.step[i+3] > 127 else 0),
                         'depth': tables.step[i+4] | tables.step[i+5] << 8,
                         'depthWrapped': tables.step[i+6] | tables.step[i+7] << 8})
        stepdata.append(rows)

    data = {
        'note': ('Nepřátelé a matice srážek (M6), odměřené na běžícím '
                 'originálu (tools/dumpenemies.py). Rodina objektu je horní '
                 'bajt slova druhu bez bitu 4; podle ní se řídí pohyb i to, '
                 'co se stane při srážce. Souřadnice, směry a jeden krok jsou '
                 'tytéž jednotky jako v data/physics.json, objects.json '
                 'a convoy.json: jeden krok je jeden průchod hlavní smyčkou.'),
        'source': 'tools/dumpenemies.py, build/gameplay.z80',
        'measuredOn': {'runs': len(all_rows), 'steps': steps,
                       'enemyPasses': n, 'differences': sum(bad.values()),
                       'zoneLoadPasses': zone_load,
                       'tableTrimmedPasses': trimmed,
                       'killedByPlayerPasses': removed,
                       'differencesOnShiftedGenerator': sum(desync.values())},
        'table': {
            'start': tables.tablePtr, 'startAddr': '$%04X' % tables.tablePtr,
            'pointer': '$%04X' % TABLE_PTR,
            'emptyX': EMPTY_X, 'endX': END_X,
            'longestSeen': longest, 'slots': SLOTS,
            'note': ('tabulka objektů je delší, než měřila §12: prázdné místo '
                     'má v `x` $FE, konec tabulky $FF, a nejdál se naměřilo '
                     '%d záznamů. Začátek tabulky je ukazatel na %s '
                     '(v naměřených bězích pořád $%04X).'
                     % (longest, '$%04X' % TABLE_PTR, tables.tablePtr)),
        },
        'familyMask': FAMILY_MASK,
        'enemyFamilies': list(ENEMY_FAMILIES),
        'families': [
            {'index': f, 'b11': sorted(b11[f]), 'role': ROLE.get(f),
             'classes': sorted(fam[f]), 'kinds': sorted(kinds[f]),
             'passes': sum(fam[f].values())}
            for f in sorted(fam)],
        'steps': {
            'table': '$%04X' % STEP_TABLE,
            'perSpeed': stepdata,
            'note': ('tabulka kroku hry: index je směr × 8 + (rychlost−1) × 64. '
                     'Ke každému směru posun `x`, 16bitový posun `y`, posun '
                     'fáze animace a dva posuny hloubky – druhý se použije, '
                     'když fáze přeteče.'),
        },
        'dirMasks': {
            'table': '$%04X' % DIR_MASKS,
            'perLane': dirs,
            'note': ('rodina 4 si směr tahá z generátoru a maskuje ho podle '
                     'své dráhy (bajt +12): `směr = (náhoda >> 8 & and) | or`. '
                     'Dráhy 0–3 dávají dvojici směrů, 4–5 čtveřici, 6–7 jediný '
                     'směr.'),
        },
        'wander': {
            'left': WANDER_LEFT, 'right': WANDER_RIGHT,
            'note': ('rodina 3 si po každém povedeném kroku vytáhne náhodu: '
                     'dolní bajt ≥ $F5 (11 z 256) otočí o krok vlevo, < $0A '
                     '(10 z 256) o krok vpravo, jinak jede dál rovně.'),
        },
        'random': {
            'seed': '$%04X' % SEED_ADDR, 'mul': RND_MUL, 'add': RND_ADD,
            'mod': RND_MOD,
            'drawsHistogram': {str(k): v for k, v in sorted(
                (k, v) for k, v in hist.items() if k is not None)},
            'note': ('generátor hry sedí na spectrácké systémové proměnné '
                     '$5C76 a je to `SEED\' = (254 × SEED + 253) mod 65537`. '
                     'Tahají z něj nepřátelé rodin 2, 3 a 4 – a taky zvuk '
                     'výbuchu a kreslení, takže sekvenci nedrží samotní '
                     'nepřátelé; port si proto na začátku každého průchodu '
                     'bere semínko ze záznamu a matcher to počítá '
                     '(disasm_notes.md §16).'),
        },
        'collision': {
            'matrix': '$%04X' % MATRIX, 'rowStride': ROW_STRIDE,
            'box': {'x': (BOX-1)//2, 'y': (BOX-1)//2},
            'range': BOX,
            'wallColumn': WALL_COLUMN,
            'handlers': [[tables.name(f, o) for o in range(FAMILIES)]
                         for f in range(FAMILIES)],
            'addresses': [['$%04X' % tables.handler(f, o) for o in range(FAMILIES)]
                          for f in range(FAMILIES)],
            'note': ('matice 11 × 11: řádek je rodina toho, kdo narazil '
                     '(bajt +11 záznamu je rovnou 22 × řádek), sloupec rodina '
                     'toho, do koho narazil; sloupec 7 se použije i pro okraj '
                     'silnice a pro cíl mimo okno světa. Krabice je táž ±7 '
                     'jako v M4 a M5 – v kódu je to jedno srovnání se 15.'),
        },
        'death': {
            'clsLow': DEATH_START, 'step': DEATH_STEP, 'limit': DEATH_LIMIT,
            'passes': sorted({k[1] for k in lengths}),
            'lengths': {'rodina %d, %d průchodů' % k: v
                        for k, v in sorted(lengths.items())},
            'note': ('zničený záznam má v rychlosti horní bit a jeho druh se '
                     'posouvá od $80 po osmi; když dojde na $DC, záznam '
                     'z tabulky zmizí. To je těch 12 průchodů, které naměřila '
                     'M5 u předání řízení.'),
        },
        'time': {
            'counter': '$%04X' % TIME_COUNTER, 'bar': '$%04X' % TIME_BAR,
            'reload': tables.const['timeReload'],
            'reloadsSeen': sorted(reloads) or None,
            'barEnd': tables.const['timeBarEnd'],
            'barStart': bar_start,
            'ticks': ticks,
            'passesTotal': ticks*tables.const['timeReload'],
            'perStep': dict(deltas),
            'barSteps': {'%d→%d' % k: v for k, v in bars.items()},
            'note': ('`TIME` je 16bitové počítadlo na $8F1A, které ubývá o 1 '
                     'každý průchod hlavní smyčkou; když dojde na nulu, ubere '
                     'se ukazateli jeden znakový dílek a počítadlo se nabije '
                     'znovu. Ukazatel je ukazatel do videopaměti: začíná na '
                     '$%02X a hra skončí, až spadne pod $%02X – to je %d dílků '
                     'a %d průchodů hlavní smyčky na celou hru (při naměřené '
                     'délce průchodu 2,41 snímku asi %d sekund). V naměřených '
                     'bězích se ani jeden dílek neubral, tak dlouhé nejsou.'
                     % (bar_start, tables.const['timeBarEnd'], ticks,
                        ticks*tables.const['timeReload'],
                        round(ticks*tables.const['timeReload']*2.41/50))),
        },
        'census': {str(z): dict(sorted(per_zone[z].items()))
                   for z in sorted(per_zone)},
        'censusNote': ('kolik čeho bylo v které zóně **nejvíc vidět zároveň** '
                       'při běhu režimu 6 DEMONSTRATION, který si projede celou '
                       'silnici sám. Není to tabulka dat silnice (ta je M2), je '
                       'to sčítání toho, co se v zóně objevilo.'),
        'constants': {
            'readFrom': tables.constAddr,
            'values': tables.const,
            'note': ('konstanty pravidel přečtené z kódu hry na adresách výš '
                     '(§16): krabice je srovnání s 15, tedy ±7; animace zániku '
                     'jde po osmi do $DC; vrtění rodiny 3 má hranice $F5 a $0A; '
                     '`TIME` se nabíjí na %d a ukazatel končí na $%02X.'
                     % (tables.const['timeReload'], tables.const['timeBarEnd'])),
        },
        'verify': {
            'enemyPasses': n,
            'differencesOnShiftedGenerator': sum(desync.values()),
            'shiftedPerFamily': {'rodina %d, %s' % k: v
                                 for k, v in sorted(desync.items())},
            'perFamily': {str(k): v for k, v in sorted(tot.items())},
            'differences': sum(bad.values()),
            'differencesPerFamily': {'rodina %d, %s' % k: v
                                     for k, v in sorted(bad.items())},
            'examples': examples,
            'note': ('referenční model z těchhle tabulek se přehrál na každém '
                     'naměřeném průchodu každého nepřítele. Průchody, ve '
                     'kterých záznam přepsal obsah nové zóny nebo se tabulka '
                     'zkrátila, se nepočítají – to je M2.'),
        },
        'open': [
            'kdo přesně tahá z generátoru mimo nepřátele: zvuk výbuchu '
            '($9B3D) a kreslení ($AAE4). Než bude zvuk změřený (M8), nedrží '
            'port sekvenci sám a semínko si bere ze záznamu.',
            'co je která rodina předmětů graficky – skleněná krychle, cihlová '
            'zeď, kulisa (M2); změřené je, že rodina 8 po zásahu **roztaje** '
            '(druh se posouvá po dvou), což je ta „bedna, co se rozteče" '
            'z Crash 20.',
            'bodování: v naměřených bězích se při přechodu zóny nezvětšil '
            'žádný bajt mimo tabulku objektů, takže se skóre za zónu '
            'průběžně nepřičítá; kde se počítá, zůstává otevřené (ZADANI §4) '
            'a bez znakové sady (§2) se stejně nedá nakreslit.',
            'kolik dílků má ukazatel TIME a co se stane, až dojde – '
            'v naměřených bězích se nevyčerpal.',
            'co se mění v druhém průchodu hry (M7).',
        ],
    }
    with open(args.out, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print('%s: nepřátelé' % os.path.relpath(args.out, H.ROOT))


if __name__ == '__main__':
    main()
