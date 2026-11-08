#!/usr/bin/env python3
"""Odměří na běžícím originálu **pravidla silnice** → `data/objects.json` (M4).

    PYTHONPATH=tools/vendor ./tools/dumpobjects.py [--out data/objects.json]

Obdoba `dumpphysics.py`, jenže ta měřila jednoho Vortona; tady jde o svět kolem
něj: **do čeho se dá narazit, co se strkáním pohne, jak daleko doletí výstřel
a kde končí zóna**. Disassembly pořád není (M0), takže se nic neodvozuje z kódu –
každá konstanta vznikne tak, že se originálu naskriptují klávesy, po každém
průchodu hlavní smyčkou se přečte tabulka objektů `$8A00` (`disasm_notes.md`
§12) a hledá se pravidlo, které **beze zbytku** vysvětlí, co se stalo.

Co se měří:

* **srážková krabice** – jediné `(rx, ry)`, které na tisících kroků přesně
  oddělí kroky, co se povedly, od těch, co originál zahodil;
* **kdo blokuje** – které druhy objektů se do toho počítají (výstřely ne,
  proletí skrz);
* **strkání** – co udělá náraz s tím, do čeho se narazilo, a jak jeho pohyb
  dojíždí;
* **výstřel** – kde vzniká, jak rychle letí, jak dlouho žije a čím zaniká;
* **zóna** – kdy se přepne okno světa (kamera), měřeno proti pozici hráče.

Druh objektu je slovo z offsetu `+5/+6` záznamu. M3 u něj psala „nejspíš
rozhoduje, kdo objekt řídí"; měření M4 ukázalo, že je to **druh**: `0` řízený
Vorton, `$1070` automatický Vorton, `$0910` Lasertron, `$0118` výstřel,
`$0228` nepřítel a `$1A68`, `$19F0`, `$0A60`, `$0648`, `$17F8` věci na silnici.
Který z těch pěti je barel, bedna, skleněná krychle nebo cihlová zeď, tenhle
nástroj neřekne – to rozhodne až grafika (M2), a je to napsané mezi otevřenými
otázkami ve výstupním souboru.
"""
import argparse, collections, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

DIRS = [(0, 2), (-1, 1), (-2, 0), (-1, -1), (0, -2), (1, -1), (2, 0), (1, 1)]
KEY_ACCEL, KEY_DECEL, KEY_RIGHT, KEY_LEFT = 2, 4, 8, 16
SHOT_CLASS = 0x0118
INACTIVE_X = 200
ROAD_MIN, ROAD_MAX = 0, 72          # změřeno v M3 (data/physics.json)
SLOTS = 24
MAX_SPEED = 4                       # výstřel má 4, Vorton nejvýš 2
# Rychlost s nastaveným horním bitem ($80, $81, $44…) není rychlost: v takovém
# stavu je objekt **zničený** a jeho druh se posouvá po tabulce animace
# ($0080, $0088, $0090… po osmi). Měření to musí přeskočit, jinak si z umírání
# hráče udělá „náraz do ničeho".


def alive(e):
    return e['speed'] <= MAX_SPEED


def snapshot(s):
    tab = s.peek(H.ENTITIES, SLOTS * H.ENTITY_SIZE)
    ents = {}
    for i in range(SLOTS):
        e = tab[i*16:(i+1)*16]
        if e[0] >= INACTIVE_X:
            continue
        ents[i] = {'x': e[0], 'y': e[1] | (e[2] << 8), 'dir': e[7],
                   'speed': e[8], 'phase': e[9], 'cls': e[6] << 8 | e[5],
                   'kind': e[10]}
    g = s.peek(0x8F00, 0x20)
    return {'ents': ents, 'zone': g[0], 'window': g[5] | (g[6] << 8),
            'keys': g[0x14], 'turnPhase': g[0x13], 'timer': g[0x1D],
            'hit': bool(g[0x15] & 0x10)}


def probes(count=16, steps=400, prefix=60):
    """Naskriptované běhy: rozjezd dopředu (konvoj stojí hráči v zádech, jinak
    by se k předmětům nedostal) a pak pseudonáhodné mačkání včetně střelby.

    Pár běhů se navíc **otočí a jede zpátky**: řada předmětů, do které se dá
    narazit bez toho, aby se hnula, leží na začátku silnice za zády hráče, a
    bez ní by měření o odpovědi na náraz nevědělo, že takové předměty existují.
    """
    runs = []
    for turn in ('P', 'O'):
        keys = [('1',)]*60
        keys += [('1', turn)]*8          # otočka o čtyři osminy dozadu
        keys += [('1',)]*(steps-len(keys))
        runs.append(keys)
    for seed in range(count):
        rnd = random.Random(seed)
        keys, held = [], ('1',)
        for i in range(steps):
            if i < prefix:
                keys.append(('1',))
                continue
            if rnd.random() < 0.3:
                held = tuple(k for k in ('1', 'Q', 'O', 'P', 'SPACE')
                             if rnd.random() < 0.45)
            keys.append(held)
        runs.append(keys)
    return runs


def collect(runs):
    frames = []
    for keys in runs:
        s = H.gameplay()
        run = [snapshot(s)]
        for k in keys:
            try:
                s.step(k)
            except RuntimeError:
                break
            run.append(snapshot(s))
        frames.append(run)
    return frames


def intended(prev, cur):
    """Kam se hráč **chtěl** ten krok pohnout (fyzika M3, data/physics.json)."""
    p = prev['ents'].get(0)
    if p is None or p['speed'] > MAX_SPEED:
        return None
    keys = cur['keys']
    d, v = p['dir'], p['speed']
    if (prev['turnPhase'] ^ 2) == 2:
        left, right = bool(keys & KEY_LEFT), bool(keys & KEY_RIGHT)
        if left != right:
            d = (d + (1 if right else -1)) & 7
    timer = prev['timer'] >> 1
    dec = bool(keys & KEY_DECEL)
    acc = (not dec) and bool(keys & KEY_ACCEL)
    if timer == 0:
        if acc and v < 2:
            v += 1
        elif dec and v > 0:
            v -= 1
    if v == 0:
        return None
    dx, dy = DIRS[d]
    return d, v, p['x'] + dx*v, p['y'] + dy*v


def measure_box(frames):
    """Najde `(rx, ry)`, které přesně oddělí zahozené kroky od povedených.

    Krok se posuzuje jen tam, kde cíl **leží na silnici** – okraj silnice je
    změřený už v M3 a blokuje sám o sobě.
    """
    cases = []
    for run in frames:
        for n in range(1, len(run)):
            prev, cur = run[n-1], run[n]
            want = intended(prev, cur)
            if want is None:
                continue
            d, v, nx, ny = want
            p0, p1 = prev['ents'].get(0), cur['ents'].get(0)
            if p0 is None or p1 is None or not alive(p0) or not alive(p1):
                continue
            moved = (p1['x'], p1['y']) != (p0['x'], p0['y'])
            if moved and (p1['x'], p1['y']) != (nx, ny):
                continue                     # neposunul se tam, kam měl – jiný jev
            if not (ROAD_MIN <= nx <= ROAD_MAX):
                continue
            cases.append((not moved, nx, ny, prev['ents']))
    fits = []
    for rx in range(1, 17):
        for ry in range(1, 17):
            fp = fn = 0
            for blocked, nx, ny, ents in cases:
                hit = any(e['cls'] != SHOT_CLASS and abs(e['x']-nx) <= rx
                          and abs(e['y']-ny) <= ry
                          for i, e in ents.items() if i)
                fp += hit and not blocked
                fn += blocked and not hit
            if fp == 0 and fn == 0:
                fits.append((rx, ry))
    # Které druhy vůbec překážejí: druh, který sám vysvětlí zahozený krok, je
    # překážka; druh, přes který se v jiném kroku prošlo, překážka není.
    blocking, transparent = set(), set()
    if fits:
        rx, ry = fits[0]
        for blocked, nx, ny, ents in cases:
            near = [e for i, e in ents.items()
                    if i and e['cls'] != SHOT_CLASS
                    and abs(e['x']-nx) <= rx and abs(e['y']-ny) <= ry]
            if blocked and len(near) == 1:
                blocking.add(near[0]['cls'])
            if not blocked:
                transparent.update(e['cls'] for e in near)
    return cases, fits, sorted(blocking), sorted(transparent)


def object_classes(stat):
    """Druhy, které se **samy nehýbou** – to jsou věci na silnici.

    Konvoj, nepřátelé a výstřely se hýbou v každém kroku, předmět se pohne jen
    tehdy, když do něj někdo strčí; hranice mezi tím je v datech propastná
    (předměty pod 3 %% kroků, ostatní nad 90 %%), ne zvolená.
    """
    return sorted(c for c, st in stat.items()
                  if c and st['seen'] > 50 and st['moved'] / st['seen'] < 0.1)


def measure_response(frames):
    """Co udělá **náraz Vortona** podle toho, do čeho narazil.

    M3 změřila tři odpovědi originálu na zablokovaný krok, ale nevěděla, která
    kdy platí (`disasm_notes.md` §13 bod 5). Tady se to dá spočítat: u každého
    zahozeného kroku se najde, co v cestě stálo, a přiřadí se k tomu, jestli
    hra ohlásila náraz (`$8F15` bit 4), o kolik klesla rychlost a jestli se
    ten předmět pohnul.
    """
    stat = collections.defaultdict(lambda: {'hit': 0, 'noHit': 0,
                                            'moved': 0, 'still': 0,
                                            'keptSpeed': 0, 'lostSpeed': 0})
    for run in frames:
        for n in range(1, len(run)):
            prev, cur = run[n-1], run[n]
            want = intended(prev, cur)
            if want is None:
                continue
            d, v, nx, ny = want
            p0, p1 = prev['ents'].get(0), cur['ents'].get(0)
            if p0 is None or p1 is None or not alive(p0) or not alive(p1):
                continue
            if (p1['x'], p1['y']) != (p0['x'], p0['y']):
                continue                      # krok se povedl
            if not (ROAD_MIN <= nx <= ROAD_MAX):
                continue                      # okraj silnice, ne předmět
            blocker = None
            for i in sorted(prev['ents']):
                e = prev['ents'][i]
                if i == 0 or e['cls'] == SHOT_CLASS:
                    continue
                if abs(e['x']-nx) <= 7 and abs(e['y']-ny) <= 7:
                    blocker = (i, e)
                    break
            if blocker is None:
                continue
            i, e = blocker
            st = stat[e['cls']]
            after = cur['ents'].get(i)
            st['hit' if cur['hit'] else 'noHit'] += 1
            if after is not None and after['cls'] == e['cls']:
                st['moved' if (after['x'], after['y']) != (e['x'], e['y'])
                   else 'still'] += 1
            st['keptSpeed' if p1['speed'] == v else 'lostSpeed'] += 1
    return stat


def measure_push(frames, objects):
    """Co udělá náraz s tím, do čeho se narazilo, a jak ten pohyb dojíždí."""
    transfer = collections.Counter()      # (rychlost strkajícího -> rychlost strčeného)
    decay = collections.Counter()         # (rychlost před -> rychlost po volném kroku)
    moves = collections.Counter()         # posun na jednotku rychlosti
    for run in frames:
        for n in range(1, len(run)):
            prev, cur = run[n-1], run[n]
            for i, a in prev['ents'].items():
                b = cur['ents'].get(i)
                if b is None or b['cls'] != a['cls'] or a['cls'] in (0, SHOT_CLASS):
                    continue
                if not alive(a) or not alive(b):
                    continue
                if a['cls'] not in objects:
                    continue              # konvoj a nepřátelé mají vlastní pohyb (M5/M6)
                dx, dy = b['x'] - a['x'], b['y'] - a['y']
                if a['speed'] == 0 and (dx or dy):
                    # rozhýbal ho ten krok někdo: kdo, a jakou rychlostí?
                    for j, m in prev['ents'].items():
                        if j == i or m['speed'] == 0:
                            continue
                        mdx, mdy = DIRS[m['dir']]
                        tx, ty = m['x'] + mdx*m['speed'], m['y'] + mdy*m['speed']
                        if not alive(m):
                            continue
                        if abs(a['x']-tx) <= 7 and abs(a['y']-ty) <= 7 \
                                and b['dir'] == m['dir']:
                            transfer[(m['speed'], b['speed'])] += 1
                            step = DIRS[b['dir']]
                            if step[0] or step[1]:
                                mv = (dx // step[0]) if step[0] else (dy // step[1])
                                moves[(m['speed'], mv)] += 1
                            break
                elif a['speed'] > 0:
                    decay[(a['speed'], b['speed'])] += 1
    return transfer, decay, moves


def measure_reload(frames):
    """Kadence střelby: jak dlouho je slot po výstřelu obsazený a jaká je
    mezera mezi dvěma výstřely jedné dávky.

    Měří se na krocích, kdy hráč **drží spoušť**, takže se nečeká na hráče:
    rozestupy výstřelů z téhož slotu a rozestupy po sobě jdoucích výstřelů.
    """
    per_slot = collections.Counter()
    between = collections.Counter()
    for run in frames:
        last_slot, last_any = {}, None
        for n in range(1, len(run)):
            prev, cur = run[n-1], run[n]
            for i, e in cur['ents'].items():
                if e['cls'] != SHOT_CLASS:
                    continue
                old = prev['ents'].get(i)
                if old is not None and old['cls'] == SHOT_CLASS:
                    continue
                if i in last_slot:
                    per_slot[n - last_slot[i]] += 1
                if last_any is not None:
                    between[n - last_any] += 1
                last_slot[i] = n
                last_any = n
    return per_slot, between


def measure_flight(frames):
    """Kolik kroků výstřel letí, než mu dojde dolet.

    Počítá se, kolikrát se týž výstřel objeví v tabulce – „týž" se pozná podle
    toho, že jeho pozice sedí na tu předchozí plus jeho krok; jinak by splynul
    s výstřelem, který se do uvolněného slotu narodí v tomtéž průchodu.
    """
    counts = collections.Counter()
    for run in frames:
        live = {}
        for n in range(1, len(run)):
            prev, cur = run[n-1], run[n]
            for i in range(SLOTS):
                now = cur['ents'].get(i)
                old = prev['ents'].get(i)
                now = now if now and now['cls'] == SHOT_CLASS else None
                old = old if old and old['cls'] == SHOT_CLASS else None
                cont = False
                if now and old:
                    dx, dy = DIRS[old['dir']]
                    cont = (now['x'] == old['x'] + dx*old['speed']
                            and now['y'] == old['y'] + dy*old['speed'])
                if now and cont:
                    live[i] = live.get(i, 1) + 1
                else:
                    if old:
                        counts[live.pop(i, 0)] += 1
                    if now:
                        live[i] = 1
    return counts


def measure_shots(frames):
    """Kde výstřel vzniká, jak letí, jak dlouho žije a čím zaniká."""
    spawn = collections.Counter()
    phases = collections.Counter()
    speeds = collections.Counter()
    deaths = collections.Counter()
    lifetimes = collections.Counter()
    cadence = collections.Counter()
    slots = collections.Counter()
    for run in frames:
        birth = {}
        last_fire = None
        for n in range(1, len(run)):
            prev, cur = run[n-1], run[n]
            for i, e in cur['ents'].items():
                if e['cls'] != SHOT_CLASS:
                    continue
                old = prev['ents'].get(i)
                if old is not None and old['cls'] == SHOT_CLASS:
                    continue
                p = prev['ents'].get(0)
                if p is None:
                    continue
                birth[i] = n
                slots[i] += 1
                speeds[e['speed']] += 1
                phases[e['phase']] += 1
                spawn[(e['x']-p['x'], e['y']-p['y'], e['dir'] == p['dir'])] += 1
                if last_fire is not None:
                    cadence[n - last_fire] += 1
                last_fire = n
            for i, old in prev['ents'].items():
                if old['cls'] != SHOT_CLASS:
                    continue
                now = cur['ents'].get(i)
                if now is not None and now['cls'] == SHOT_CLASS:
                    continue
                dx, dy = DIRS[old['dir']]
                nx, ny = old['x'] + dx*old['speed'], old['y'] + dy*old['speed']
                if any(j != i and e['cls'] != SHOT_CLASS
                       and abs(e['x']-nx) <= 7 and abs(e['y']-ny) <= 7
                       for j, e in prev['ents'].items()):
                    deaths['trefil'] += 1
                elif not (ROAD_MIN <= nx <= ROAD_MAX):
                    deaths['mimoSilnici'] += 1
                else:
                    deaths['dolet'] += 1
                    if i in birth:
                        lifetimes[n - birth[i]] += 1
    return spawn, speeds, deaths, lifetimes, cadence, slots, phases


def measure_zone(frames):
    """Kdy se přepne okno světa. Měří se proti pozici hráče, ne konvoje.

    Vrací i délku zóny: hledá se jediné `L`, pro které u **každého** přechodu
    (tam i zpátky) platí `zóna = y // L`. Vychází z toho 176 – tedy tolik,
    o kolik na zónu poroste i světová souřadnice `$8F05` (`disasm_notes.md`
    §7). Souřadnice objektu a světová souřadnice jsou tedy **totéž měřítko**;
    „půljednotky", jak to četla M3, to nejsou.
    """
    changes = []
    for run in frames:
        for n in range(1, len(run)):
            if run[n]['zone'] == run[n-1]['zone']:
                continue
            p = run[n-1]['ents'].get(0)
            if p is None:
                continue
            changes.append({'zoneFrom': run[n-1]['zone'], 'zoneTo': run[n]['zone'],
                            'playerY': p['y'], 'window': run[n-1]['window'],
                            'windowAfter': run[n]['window']})
    lengths = [L for L in range(1, 513)
               if all(c['playerY'] // L == c['zoneTo'] for c in changes)]
    return changes, lengths


def classes(frames):
    stat = collections.defaultdict(lambda: {'seen': 0, 'moved': 0,
                                            'speeds': collections.Counter(),
                                            'kinds': set()})
    for run in frames:
        for n in range(1, len(run)):
            for i, a in run[n-1]['ents'].items():
                b = run[n]['ents'].get(i)
                st = stat[a['cls']]
                st['seen'] += 1
                st['speeds'][a['speed']] += 1
                st['kinds'].add(a['kind'])
                if b is not None and b['cls'] == a['cls'] \
                        and (b['x'], b['y']) != (a['x'], a['y']):
                    st['moved'] += 1
    return stat


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'data/objects.json'))
    ap.add_argument('--runs', type=int, default=16)
    ap.add_argument('--steps', type=int, default=400)
    args = ap.parse_args()

    frames = collect(probes(args.runs, args.steps))
    steps = sum(len(r)-1 for r in frames)
    print('%d běhů, %d kroků originálu' % (len(frames), steps))

    cases, fits, blocking, transparent = measure_box(frames)
    print('srážková krabice: %d posuzovaných kroků, sedí %s'
          % (len(cases), fits or 'nic – pravidlo není obdélník!'))
    print('   překáží: %s;  projde se skrz: %s'
          % (['$%04X' % c for c in blocking],
             ['$%04X' % c for c in transparent]))
    cls = classes(frames)
    objects = object_classes(cls)
    transfer, decay, moves = measure_push(frames, objects)
    response = measure_response(frames)
    # Strkat se dá to, co se po nárazu pohnulo **a samo se nehýbe**: konvoj se
    # taky „pohnul", ale ten jede po svém (M5), ne proto, že do něj někdo vrazil.
    pushable = sorted(c for c, st in response.items()
                      if st['moved'] and c in objects)
    fixed = sorted(c for c, st in response.items()
                   if not st['moved'] and c in objects)
    print('náraz podle druhu:')
    for c, st in sorted(response.items()):
        print('   $%04X  náraz ohlášen %3d×, neohlášen %3d×, pohnulo se %3d×, '
              'stálo %3d×, rychlost zůstala %3d×, klesla %3d×'
              % (c, st['hit'], st['noHit'], st['moved'], st['still'],
                 st['keptSpeed'], st['lostSpeed']))
    print('předměty (samy se nehýbou): %s' % ['$%04X' % c for c in objects])
    print('strkání: přenos rychlosti %s' % dict(transfer))
    print('         dojezd %s' % dict(decay))
    spawn, sspeeds, deaths, lifetimes, cadence, slots, sphases = measure_shots(frames)
    per_slot, between = measure_reload(frames)
    flight = measure_flight(frames)
    # dolet je ten **nejdelší** let, ne nejčastější: většina výstřelů do něčeho
    # trefí dřív, a průměr by tak měřil, jak je na silnici plno
    moves = (max(flight) - 1) if flight else None
    reload_steps = min(per_slot) if per_slot else 0
    gap_steps = min(between) if between else 0
    print('výstřel: slot obsazený %d kroků, mezera v dávce %d kroků, dolet %s kroků'
          % (reload_steps, gap_steps, moves))
    print('výstřel: vznik %s' % spawn.most_common(4))
    print('         zánik %s, dolet %s' % (dict(deaths), lifetimes.most_common(3)))
    zone, zone_lengths = measure_zone(frames)
    print('zóna: %d přechodů, délka zóny sedí na %s' % (len(zone), zone_lengths))

    box = fits[0] if fits else None
    zone_len = zone_lengths[0] if zone_lengths else None
    crossings = [{'playerY': c['playerY'], 'zoneTo': c['zoneTo'],
                  'window': c['windowAfter']} for c in zone]
    data = {
        'note': ('Pravidla silnice odměřená na běžícím originálu '
                 '(tools/dumpobjects.py). Souřadnice jsou v půljednotkách '
                 'světové souřadnice, jeden krok je jeden průchod hlavní '
                 'smyčkou hry – stejné jednotky jako data/physics.json.'),
        'source': 'tools/dumpobjects.py, build/gameplay.z80',
        'measuredOn': {'runs': len(frames), 'steps': steps,
                       'blockingDecisions': len(cases)},
        'entityTable': {'address': H.ENTITIES, 'slots': SLOTS,
                        'recordSize': H.ENTITY_SIZE, 'inactiveX': INACTIVE_X,
                        'classOffset': 5,
                        'note': 'druh objektu je slovo z offsetu +5/+6'},
        'collision': {
            'box': {'x': box[0] if box else None, 'y': box[1] if box else None},
            'note': ('krok se zahodí, když v cílové pozici stojí objekt s |dx| '
                     '<= box.x a |dy| <= box.y; jediná dvojice, která na '
                     'naměřených krocích nedělá ani falešný poplach, ani '
                     'přehlédnutí'),
            'blockingClasses': blocking,
            'blockingNote': ('druhy, které samy o sobě vysvětlí zahozený krok; '
                             'co v seznamu není (výstřely, nepřátelé), se dá '
                             'projet i prostrkat skrz'),
            'transparentClasses': sorted(set([SHOT_CLASS]) | set(transparent)),
            'pushableClasses': pushable,
            'fixedClasses': fixed,
            'response': {('$%04X' % c): st for c, st in sorted(response.items())},
            'responseNote': ('do čeho se dá strčit, to náraz ohlásí ($8F15 bit 4) '
                             'a Vortonovi vezme rychlost i časovač plynu; co se '
                             'strčit nedá (řada napříč silnicí, $19F0), to '
                             'rychlost sebere taky, ale náraz **neohlásí** ani '
                             'jednou z 519 naměřených srážek a časovač nechá '
                             'běžet, takže se do řady dá narážet pořád dokola. '
                             'Třetí odpověď z M3 – „opřít se a rychlost si '
                             'nechat" – se v těchhle bězích nepotvrdila: '
                             'o konvoj se hráč rychlost pokaždé připravil '
                             '(keptSpeed 0). Kdy tedy platí, zůstává otevřené '
                             '(M5).'),
            'transparentNote': 'výstřely nikoho neblokují – hráč jimi projíždí',
            'road': {'minX': ROAD_MIN, 'maxX': ROAD_MAX},
        },
        'push': {
            'takesPusherDirection': True,
            'speedFromPusher': sorted({k[0] for k in transfer}),
            'speedAfterOwnStep': {('%d->%d' % k): v
                                  for k, v in sorted(decay.items())},
            'speedAfterOwnStepNote': ('kolikrát byl objekt na začátku průchodu '
                                      'v rychlosti A a na konci v B; povedený '
                                      'krok ji půlí, zablokovaný o jiný objekt '
                                      'ji nechá aspoň na 1'),
            'objectClasses': objects,
            'objectClassesHex': ['$%04X' % c for c in objects],
            'decay': 'halve',
            'note': ('do čeho se narazí, to převezme směr i rychlost toho, kdo '
                     'do něj narazil, popojede ještě v tomtéž kroku a rychlost '
                     'si pak každý krok půlí (4 → 2 → 1 → 0)'),
        },
        'shot': {
            'class': SHOT_CLASS,
            'slots': sorted(slots),
            'spawnOffsetSteps': 4,
            'speed': sorted(sspeeds),
            'phase': sorted(sphases),
            'lifetimeSteps': (lifetimes.most_common(1)[0][0]-1 if lifetimes else None),
            'slotReloadSteps': (reload_steps or None),
            'gapSteps': (gap_steps or None),
            'lifetimeHistogram': dict(sorted(lifetimes.items())),
            'cadenceSteps': sorted(cadence),
            'deaths': dict(deaths),
            'note': ('vzniká 4 kroky před hráčem v jeho směru, letí rychlostí 4 '
                     '(tedy 8 půljednotek na krok) a zaniká, když do něčeho '
                     'trefí, když opustí silnici, nebo když mu dojde dolet; '
                     'do čeho trefí, to strčí stejně jako náraz Vortonem'),
        },
        'zone': {
            'length': zone_len,
            'fromPlayer': True,
            'crossings': crossings,
            'note': ('okno světa (kamera) je zóna, ve které stojí **hráč**: '
                     'zóna = y // %s, a čte se z pozice, ve které hráč krok '
                     'začal. Kamera se neposouvá, při přechodu skočí '
                     '(disasm_notes.md §6), a skočí i zpátky, když hráč '
                     'hranici přejede nazpátek – změřeno.' % zone_len),
        },
        'classes': {('$%04X' % c): {'seen': st['seen'], 'moved': st['moved'],
                                    'speeds': dict(st['speeds']),
                                    'kinds': sorted(st['kinds'])}
                    for c, st in sorted(cls.items())},
        'open': [
            'který druh je barel, bedna, skleněná krychle, cihlová zeď nebo mina '
            '– rozhodne až grafika (M2)',
            'odkud se berou objekty při přechodu zóny (tabulka dat silnice, M2)',
            'pohyb konvoje ($1070, $0910) a nepřátel ($0228) – M5 a M6',
        ],
    }
    with open(args.out, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print('%s: pravidla silnice' % os.path.relpath(args.out, H.ROOT))


if __name__ == '__main__':
    main()
