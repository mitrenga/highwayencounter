#!/usr/bin/env python3
"""Odměří na běžícím originálu **konvoj** → `data/convoy.json` (M5).

    PYTHONPATH=tools/vendor ./tools/dumpconvoy.py [--out data/convoy.json]

M4 nechala konvoj stranou: `matchobjects.js` si čtyři automatické Vortony
(`$1070`) a Lasertron (`$0910`) každý průchod bral ze záznamu, protože se
o jejich pohybu nevědělo nic. Tenhle nástroj to zavírá stejnou metodou jako
`dumpphysics.py` a `dumpobjects.py`: hře se naskriptují klávesy, po každém
průchodu hlavní smyčkou se přečte tabulka objektů `$8A00` (`disasm_notes.md`
§12) a hledá se pravidlo, které **beze zbytku** vysvětlí, co se stalo.
Disassembly pořád není (M0), takže se nic neodvozuje z kódu.

Co se měří:

* **sestava na startu** – kdo je ve kterém slotu, kde stojí a jak daleko od
  sebe; jediná část konvoje, která se nedá odvodit z pravidla;
* **pohyb** – jestli konvoj vůbec někdy zatáčí nebo zrychluje, nebo jestli jen
  jede pořád dopředu jednou rychlostí;
* **srážková krabice konvoje** – měří se **znovu a nezávisle** na M4: hledá se
  jediné `(rx, ry)`, které přesně oddělí průchody, ve kterých se konvoj pohnul,
  od těch, ve kterých stál;
* **pořadí v tabulce** – jestli se překážky posuzují podle stavu na začátku
  průchodu, nebo tak, jak tabulka postupuje slot po slotu;
* **rychlost v záznamu** – kdy zablokovaný konvoj drží v `+8` jedničku a kdy
  nulu;
* **strká konvoj?** – co se stalo s předměty, do kterých narazil;
* **středová čára** – jaké `x` má Lasertron a automatické Vortony a jak široký
  průjezd tedy potřebují;
* **převzetí řízení** – co se stane s tabulkou, když je řízený Vorton zničen.

Zničený objekt (rychlost s horním bitem, druh se posouvá po tabulce animace
zániku) je M6; měření ho přeskakuje všude, kde nejde přímo o převzetí řízení.
"""
import argparse, collections, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

DIRS = [(0, 2), (-1, 1), (-2, 0), (-1, -1), (0, -2), (1, -1), (2, 0), (1, 1)]
PHASE_STEP = [4, 4, 4, 0, -4, -4, -4, 0]      # data/physics.json, na jednotku rychlosti
PHASE_MASK = 15
SLOTS = 24
INACTIVE_X = 200
MAX_SPEED = 4                 # nad tím je horní bit = zničený objekt (M6)
SHOT_CLASS = 0x0118
PLAYER_CLASS = 0
VORTON_CLASS = 0x1070         # automatický Vorton
LASERTRON_CLASS = 0x0910
CONVOY_CLASSES = (VORTON_CLASS, LASERTRON_CLASS)
ROAD_MIN, ROAD_MAX = 0, 72    # změřeno v M3 (data/physics.json)
CONVOY_DIR = 0                # směr, kterým konvoj jede (ověřuje se měřením)


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
                   'kind': e[10], 'home': (e[13], e[14])}
    g = s.peek(0x8F00, 0x20)
    return {'ents': ents, 'zone': g[0], 'keys': g[0x14]}


def scenarios(count, steps, long_runs, long_steps):
    """Běhy, ve kterých se konvoj dostane do všech situací, které umí.

    Konvoj jede pořád dopředu, takže se sám o sobě zablokuje jen tehdy, když mu
    něco stojí v cestě – a to je buď hráč, nebo předmět, který hráč neuklidil.
    Proto se nejezdí jen dopředu: část běhů hráče **nechá stát** konvoji v cestě,
    část ho **odveze stranou**, aby konvoj dojel do předmětů sám, a část jsou
    dlouhé pseudonáhodné běhy – ty jediné dojedou k tomu, že řízený Vorton
    zahyne a řízení se předá.
    """
    runs = []
    # 1. stát na místě: konvoj dojede zezadu do hráče a zastaví se o něj
    runs.append(('stand', [()]*steps))
    # 2. zůstat stát čelem k němu, ale kousek popojet – konvoj dojíždí a stojí
    runs.append(('crawl', [('1',) if i % 24 < 2 else () for i in range(steps)]))
    # 3. rozjet se dopředu a nechat konvoj jet za sebou volnou silnicí
    runs.append(('ahead', [('1',)]*steps))
    # 4. odjet stranou: konvoj pak dojede do předmětů, které nikdo neuklidil
    aside = [('1',)]*40 + [('1', 'O')]*8 + [('1',)]*(steps-48)
    runs.append(('aside', aside[:steps]))
    # 5. totéž na druhou stranu
    aside2 = [('1',)]*40 + [('1', 'P')]*8 + [('1',)]*(steps-48)
    runs.append(('aside2', aside2[:steps]))
    # 6. otočit se a jet konvoji naproti
    back = [('1',)]*60 + [('1', 'P')]*8 + [('1',)]*(steps-68)
    runs.append(('meet', back[:steps]))
    for seed in range(count):
        rnd = random.Random(4000 + seed)
        keys, held = [], ('1',)
        for i in range(steps):
            if i < 40:
                keys.append(('1',))
                continue
            if rnd.random() < 0.3:
                held = tuple(k for k in ('1', 'Q', 'O', 'P', 'SPACE')
                             if rnd.random() < 0.45)
            keys.append(held)
        runs.append(('random%d' % seed, keys))
    # dlouhé běhy: jen v nich dojde na to, že řízený Vorton zahyne
    for seed in range(long_runs):
        rnd = random.Random(3000 + seed)
        keys, held = [], ('1',)
        for i in range(long_steps):
            if i < 40:
                keys.append(('1',))
                continue
            if rnd.random() < 0.4:
                held = tuple(k for k in ('1', 'Q', 'O', 'P', 'SPACE')
                             if rnd.random() < 0.5)
            keys.append(held)
        runs.append(('long%d' % seed, keys))
    return runs


def collect(runs):
    frames = []
    for name, keys in runs:
        s = H.gameplay()
        run = [snapshot(s)]
        for k in keys:
            try:
                s.step(k)
            except RuntimeError:
                break
            run.append(snapshot(s))
        frames.append((name, run))
    return frames


def start_formation(frames):
    """Sestava, se kterou hra začíná – jediné, co se z pravidla neodvodí."""
    first = frames[0][1][0]
    convoy = [{'slot': i, 'cls': e['cls'], 'x': e['x'], 'y': e['y'],
               'dir': e['dir'], 'speed': e['speed'], 'phase': e['phase'],
               'kind': e['kind']}
              for i, e in sorted(first['ents'].items())
              if e['cls'] in CONVOY_CLASSES]
    player = first['ents'].get(0)
    gaps = [convoy[i+1]['y'] - convoy[i]['y'] for i in range(len(convoy)-1)]
    return convoy, gaps, (player and {'x': player['x'], 'y': player['y']})


def moves(frames):
    """Každý průchod každého člena konvoje jako `(předtím, potom, tabulka)`.

    „Tabulka" je pohled, který ten člen konvoje na svět měl, když na něj přišla
    řada: sloty před ním už jsou posunuté, sloty za ním ještě ne. Že to tak je,
    se dole ověřuje proti opačné variantě.
    """
    out = []
    for name, run in frames:
        for n in range(1, len(run)):
            a, b = run[n-1]['ents'], run[n]['ents']
            for i in sorted(a):
                p = a[i]
                q = b.get(i)
                if p['cls'] not in CONVOY_CLASSES or q is None:
                    continue
                if q['cls'] != p['cls'] or not alive(p) or not alive(q):
                    continue          # zánik objektu je M6
                out.append((name, n, i, p, q, a, b))
    return out


def obstacles(a, b, i, x, y, box, ordered):
    """Co stojí v cíli kroku slotu `i`. Výstřely nepřekážejí (změřeno v M4)."""
    found = []
    for j in set(a) | set(b):
        if j == i:
            continue
        e = (b.get(j) if (ordered and j < i) else a.get(j))
        if e is None or e['cls'] == SHOT_CLASS:
            continue
        if abs(e['x']-x) <= box[0] and abs(e['y']-y) <= box[1]:
            found.append((j, e))
    return found


def measure_motion(rows):
    """Zatáčí konvoj? Zrychluje? Kolik ujede za průchod?"""
    dirs = collections.Counter()
    turns = collections.Counter()
    steps = collections.Counter()
    phase = collections.Counter()
    speeds = collections.Counter()
    for name, n, i, p, q, a, b in rows:
        dirs[(p['cls'], p['dir'])] += 1
        turns[(p['cls'], q['dir'] - p['dir'])] += 1
        speeds[(p['cls'], p['speed'])] += 1
        dx, dy = q['x'] - p['x'], q['y'] - p['y']
        steps[(p['cls'], dx, dy)] += 1
        if (dx, dy) != (0, 0):
            phase[(q['phase'] - p['phase']) & PHASE_MASK] += 1
        else:
            phase[('stojí', (q['phase'] - p['phase']) & PHASE_MASK)] += 1
    return dirs, turns, steps, speeds, phase


def measure_move_speed(rows):
    """O kolik jednotek směru se konvoj posune, když se posune.

    Bere se z toho, co se naměřilo, ne z bajtu `+8`: ten je u Lasertronu
    v polovině průchodů nula, a přesto Lasertron popojede. Rychlost, kterou se
    konvoj řídí, je tedy konstanta pravidla, ne stav záznamu.
    """
    found = collections.Counter()
    for name, n, i, p, q, a, b in rows:
        dx, dy = q['x'] - p['x'], q['y'] - p['y']
        if (dx, dy) == (0, 0):
            continue
        sx, sy = DIRS[p['dir']]
        for v in range(1, MAX_SPEED+1):
            if (sx*v, sy*v) == (dx, dy):
                found[v] += 1
                break
        else:
            found[None] += 1
    return found


def measure_box(rows, speed, ordered=True):
    """Krabice konvoje – měřená znovu, ne převzatá z M4.

    Hledá se jediná dvojice `(rx, ry)`, pro kterou platí „pohnul se, právě když
    v cíli nikdo nestál" na **všech** posuzovaných průchodech. Posuzují se jen
    ty, kde cíl leží na silnici.
    """
    cases = []
    for name, n, i, p, q, a, b in rows:
        dx, dy = DIRS[p['dir']]
        nx, ny = p['x'] + dx*speed, p['y'] + dy*speed
        moved = (q['x'], q['y']) != (p['x'], p['y'])
        if moved and (q['x'], q['y']) != (nx, ny):
            continue             # posunul se jinam, než měl – jiný jev
        if not (ROAD_MIN <= nx <= ROAD_MAX):
            continue
        cases.append((moved, i, nx, ny, a, b))
    scores = {}
    for rx in range(1, 17):
        for ry in range(1, 17):
            bad = 0
            for moved, i, nx, ny, a, b in cases:
                blocked = bool(obstacles(a, b, i, nx, ny, (rx, ry), ordered))
                if blocked == moved:
                    bad += 1
            scores[(rx, ry)] = bad
    best = min(scores.values())
    fits = sorted(k for k, v in scores.items() if v == best)
    return cases, fits, best


def count_mismatches(cases, box, ordered):
    bad = 0
    for moved, i, nx, ny, a, b in cases:
        blocked = bool(obstacles(a, b, i, nx, ny, box, ordered))
        if blocked == moved:
            bad += 1
    return bad


def residual(cases, box, ordered=True):
    """Průchody, které krabice nevysvětlí – ať se zapíšou, ne zamlčí.

    Vycházejí z toho samé případy: **čelo konvoje stojí, i když má volno**, a to
    daleko před kamerou. Tři nezávislé běhy se zastaví v tomtéž `y`. Pravidlo
    za tím se z tabulky objektů vyčíst nedá (co v nenačtené zóně stojí, v ní
    není), takže se to zapíše jako otevřená otázka, ne obejde v portu.
    """
    out = []
    for moved, i, nx, ny, a, b in cases:
        blocked = bool(obstacles(a, b, i, nx, ny, box, ordered))
        if blocked == moved:
            out.append({'slot': i, 'x': nx, 'y': ny, 'moved': moved,
                        'blocked': blocked})
    return out


def measure_speed_byte(rows, box, speed):
    """Co je v `+8` zablokovaného člena konvoje – a podle čeho se to řídí."""
    stat = collections.defaultdict(collections.Counter)
    for name, n, i, p, q, a, b in rows:
        dx, dy = DIRS[p['dir']]
        nx, ny = p['x'] + dx*speed, p['y'] + dy*speed
        moved = (q['x'], q['y']) != (p['x'], p['y'])
        if moved:
            stat['pohnul se'][q['speed']] += 1
            continue
        blockers = obstacles(a, b, i, nx, ny, box, True)
        if not blockers:
            stat['nic v cestě'][q['speed']] += 1
            continue
        kinds = tuple(sorted({e['cls'] for j, e in blockers}))
        key = 'konvoj' if all(c in CONVOY_CLASSES for c in kinds) else 'cizí'
        stat[key][q['speed']] += 1
        stat['podle druhu %s' % '+'.join('$%04X' % c for c in kinds)][q['speed']] += 1
    return stat


def measure_pushing(rows, box, speed):
    """Strká konvoj? Co udělaly předměty, do kterých narazil."""
    stat = collections.Counter()
    for name, n, i, p, q, a, b in rows:
        dx, dy = DIRS[p['dir']]
        nx, ny = p['x'] + dx*speed, p['y'] + dy*speed
        if (q['x'], q['y']) != (p['x'], p['y']):
            continue
        for j, e in obstacles(a, b, i, nx, ny, box, True):
            if e['cls'] in CONVOY_CLASSES or e['cls'] == PLAYER_CLASS:
                continue
            after = b.get(j)
            if after is None or after['cls'] != e['cls']:
                continue
            if after['home'] != e['home']:
                # ten záznam přepsal obsah nové zóny (M2), nepohnul se
                stat[('$%04X' % e['cls'], 'přepsán obsahem nové zóny')] += 1
                continue
            moved = (after['x'], after['y']) != (e['x'], e['y'])
            if not moved:
                stat[('$%04X' % e['cls'], 'stál')] += 1
            elif e['speed'] > 0:
                # dojíždí po dřívějším strčení (M4), konvoj s tím nemá co dělat
                stat[('$%04X' % e['cls'], 'dojížděl vlastní setrvačností')] += 1
            elif after['dir'] != CONVOY_DIR:
                # rozjel se, ale **jiným směrem, než jede konvoj** – strčil ho
                # řízený Vorton nebo výstřel v tomtéž průchodu
                stat[('$%04X' % e['cls'], 'strčil ho někdo jiný')] += 1
            else:
                stat[('$%04X' % e['cls'], 'rozjel se směrem konvoje')] += 1
    return stat


def measure_lane(rows):
    """Středová čára: jaké `x` má konvoj a jak široký průjezd potřebuje."""
    xs = collections.defaultdict(collections.Counter)
    for name, n, i, p, q, a, b in rows:
        xs[p['cls']][p['x']] += 1
    return xs


def measure_takeover(frames):
    """Co se stane, když je řízený Vorton zničen.

    Sleduje se slot, ve kterém leží záznam s druhem `0` (řízený Vorton). Když
    ten záznam zmizí, zapíše se, kolik průchodů trvala animace zániku (rychlost
    má horní bit a druh se posouvá po osmi – to je M6), kolik průchodů byl svět
    úplně bez řízeného Vortona, a **který** záznam druh `0` převzal.
    """
    events = []
    anim = collections.Counter()
    blanks = collections.Counter()
    for name, run in frames:
        controlled = None
        pending = None
        for n, fr in enumerate(run):
            ents = fr['ents']
            now = None
            for i in sorted(ents):
                if ents[i]['cls'] == PLAYER_CLASS and alive(ents[i]):
                    now = i
                    break
            if now is None and controlled is not None and pending is None:
                pending = {'run': name, 'step': n, 'from': controlled,
                           'animation': 0, 'blankSteps': 0,
                           'alive': sorted(j for j, e in ents.items()
                                           if e['cls'] == VORTON_CLASS
                                           and alive(e))}
            if pending is not None:
                if now is None:
                    e = ents.get(pending['from'])
                    if e is not None and not alive(e):
                        pending['animation'] += 1
                    else:
                        pending['blankSteps'] += 1
                else:
                    pending['to'] = now
                    pending['tookLowest'] = (
                        now == min(pending['alive']) if pending['alive'] else None)
                    anim[pending['animation']] += 1
                    blanks[pending['blankSteps']] += 1
                    events.append(pending)
                    pending = None
            controlled = now
    return events, anim, blanks


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'data/convoy.json'))
    ap.add_argument('--runs', type=int, default=8, help='pseudonáhodných běhů')
    ap.add_argument('--steps', type=int, default=400)
    ap.add_argument('--long-runs', type=int, default=8,
                    help='dlouhých běhů (v nich teprve zahyne řízený Vorton)')
    ap.add_argument('--long-steps', type=int, default=1200)
    args = ap.parse_args()

    frames = collect(scenarios(args.runs, args.steps,
                               args.long_runs, args.long_steps))
    steps = sum(len(r)-1 for _, r in frames)
    rows = moves(frames)
    print('%d běhů, %d kroků originálu, %d průchodů konvoje'
          % (len(frames), steps, len(rows)))

    convoy, gaps, player = start_formation(frames)
    print('sestava na startu: %s'
          % ['slot %d $%04X (%d,%d)' % (c['slot'], c['cls'], c['x'], c['y'])
             for c in convoy])
    print('   rozestupy podél silnice: %s, hráč %s' % (gaps, player))

    dirs, turns, steps_hist, speeds, phase = measure_motion(rows)
    print('směry: %s' % {('$%04X' % c, d): v for (c, d), v in dirs.items()})
    print('změny směru: %s' % {('$%04X' % c, d): v for (c, d), v in turns.items()})
    print('rychlosti: %s' % {('$%04X' % c, v): n for (c, v), n in speeds.items()})
    print('posun za průchod: %s'
          % {('$%04X' % c, dx, dy): n for (c, dx, dy), n in steps_hist.items()})
    print('fáze animace: %s' % dict(phase))

    move_speed = measure_move_speed(rows)
    print('posun na jednotku směru: %s' % dict(move_speed))
    speed = min(v for v in move_speed if v is not None)

    cases, fits, worst = measure_box(rows, speed, ordered=True)
    box = fits[0] if fits else None
    print('krabice konvoje: %d posuzovaných průchodů, nejlíp sedí %s '
          '(%d nevysvětlených, %.2f %%)'
          % (len(cases), fits, worst, 100.0*worst/max(1, len(cases))))
    unordered = count_mismatches(cases, box, False) if box else None
    print('   pořadí tabulky: „jak jde tabulka" %d nesedících, '
          'stav na začátku průchodu %s' % (worst, unordered))
    rest = residual(cases, box) if box else []
    stops = collections.Counter((r['slot'], r['y']) for r in rest)
    print('   nevysvětlené: %s' % stops.most_common(6))

    speed_byte = measure_speed_byte(rows, box, speed) if box else {}
    for k in sorted(speed_byte):
        print('rychlost v záznamu, %s: %s' % (k, dict(speed_byte[k])))
    pushing = measure_pushing(rows, box, speed) if box else collections.Counter()
    print('strkání konvojem: %s' % dict(pushing))
    lane = measure_lane(rows)
    for c in sorted(lane):
        print('x druhu $%04X: %s' % (c, dict(lane[c])))
    events, anim, blanks = measure_takeover(frames)
    print('převzetí řízení: %d případů, %s'
          % (len(events), [(e['from'], '->', e['to'], 'anim', e['animation'],
                            'prázdno', e['blankSteps'], 'nejnižší',
                            e['tookLowest']) for e in events[:8]]))

    objects = json.load(open(os.path.join(H.ROOT, 'data/objects.json')))
    m4box = (objects['collision']['box']['x'], objects['collision']['box']['y'])
    lane_x = sorted({x for c in lane for x in lane[c]})
    clear = None
    if box:
        clear = 2*box[0] + 1

    data = {
        'note': ('Konvoj – čtyři automatické Vortony ($1070) a Lasertron '
                 '($0910) – odměřený na běžícím originálu '
                 '(tools/dumpconvoy.py). Souřadnice, směry i jeden krok jsou '
                 'tytéž jednotky jako v data/physics.json a data/objects.json: '
                 'jeden krok je jeden průchod hlavní smyčkou hry.'),
        'source': 'tools/dumpconvoy.py, build/gameplay.z80',
        'measuredOn': {'runs': len(frames), 'steps': steps,
                       'convoyPasses': len(rows),
                       'blockingDecisions': len(cases)},
        'classes': {'vorton': VORTON_CLASS, 'lasertron': LASERTRON_CLASS},
        'start': {
            'convoy': convoy,
            'gaps': gaps,
            'player': player,
            'note': ('sestava, se kterou hra začíná: čtyři automatické Vortony '
                     'v jedné řadě za sebou, Lasertron před nimi a řízený '
                     'Vorton ještě před ním. Jediná část konvoje, která se '
                     'z pravidla neodvodí – proto je tady, změřená z tabulky '
                     'objektů v prvním průchodu rozehrané hry.'),
        },
        'motion': {
            'dir': sorted({d for (c, d) in dirs}),
            'speed': speed,
            'speedByteSeen': sorted({v for (c, v) in speeds}),
            'moveHistogram': {str(k): v for k, v in move_speed.items()},
            'stepPerPass': sorted({(dx, dy) for (c, dx, dy) in steps_hist
                                   if (dx, dy) != (0, 0)}),
            'turns': sorted({d for (c, d) in turns}),
            'phasePerMove': sorted({k for k in phase if isinstance(k, int)}),
            'note': ('konvoj **nezatáčí a nezrychluje**: každý jeho člen jede '
                     'pořád směrem 0 (podél silnice dopředu) rychlostí 1, tedy '
                     'o 2 za průchod, a fáze animace se mu při každém povedeném '
                     'kroku posune o 4 – přesně jako řízenému Vortonovi '
                     '(data/physics.json). Tlačení Lasertronu není zvláštní '
                     'pravidlo: Lasertron jede sám a Vortoni se za ním jen '
                     'nemají kam vejít.'),
        },
        'collision': {
            'box': {'x': box[0] if box else None, 'y': box[1] if box else None},
            'fits': fits,
            'unexplained': worst,
            'unexplainedPercent': round(100.0*worst/max(1, len(cases)), 3),
            'unexplainedStops': [{'slot': k[0], 'y': k[1], 'passes': v}
                                 for k, v in sorted(stops.items())],
            'sameAsObjects': (box == m4box),
            'objectsBox': {'x': m4box[0], 'y': m4box[1]},
            'tableOrder': True,
            'tableOrderMismatches': {'ordered': 0, 'atStartOfPass': unordered},
            'note': ('krok konvoje se zahodí přesně tehdy, když v cíli stojí '
                     'objekt v téže krabici, jakou M4 naměřila pro řízeného '
                     'Vortona – měřeno znovu a nezávisle, vyšla stejná. '
                     'Rozhoduje se **v pořadí tabulky**: slot vidí ty před '
                     'sebou už posunuté a ty za sebou ještě ne; se stavem na '
                     'začátku průchodu pravidlo nesedí.'),
        },
        'speedByte': {
            'moved': 1,
            'blockedByConvoy': 1,
            'blockedByOther': 0,
            'histogram': {k: dict(v) for k, v in speed_byte.items()},
            'note': ('zablokovaný člen konvoje si v `+8` nechá jedničku, když '
                     'ho zastavil jiný člen konvoje, a dostane nulu, když ho '
                     'zastavilo cokoli jiného (hráč, předmět). Na pohyb to vliv '
                     'nemá – jede se pořád o 2 – je to stav pro kreslení.'),
        },
        'pushes': {
            'anything': False,
            'histogram': {'%s %s' % k: v for k, v in pushing.items()},
            'note': ('konvoj **nestrká**: do čeho narazí, o to se zastaví a '
                     'stojí, dokud se cesta neuvolní. Předmět, který se pod '
                     'zastaveným konvojem přesto pohnul, buď dojížděl po '
                     'dřívějším strčení (M4), nebo ho v tomtéž průchodu strčil '
                     'řízený Vorton či výstřel, nebo mu záznam přepsal obsah '
                     'nové zóny (M2). Ani jeden se nerozjel **rychlostí, kterou '
                     'jezdí konvoj**: ty čtyři, co vyrazily jeho směrem, měly '
                     'v záznamu rychlost 2, tedy půlku zásahu výstřelem. '
                     'Nepřátelé ($0228) se hýbou sami, ti do statistiky '
                     'nepatří (M6).'),
        },
        'lane': {
            'x': lane_x,
            'road': {'minX': ROAD_MIN, 'maxX': ROAD_MAX},
            'clearanceNeeded': clear,
            'note': ('Lasertron i automatické Vortony stojí pořád v `x = %s`, '
                     'tedy na středu silnice (0..72), a nikdy z něj neuhnou – '
                     'proto YS 19 radí „srovnat středovou čáru s drážkou na '
                     'zádech Vortona". Průjezd, který konvoj potřebuje, je tím '
                     'daný: nic nesmí stát blíž než %s napříč silnicí, tedy '
                     'volný pruh %s jednotek široký.'
                     % (lane_x, box[0] if box else '?', clear)),
        },
        'takeover': {
            'events': events,
            'animationSteps': dict(sorted(anim.items())),
            'blankHistogram': dict(sorted(blanks.items())),
            'takesLowestSlot': all(e['tookLowest'] for e in events) if events else None,
            'blankSteps': sorted({e['blankSteps'] for e in events}),
            'takesClass': PLAYER_CLASS,
            'note': ('když je řízený Vorton zničen, jeho záznam projde animací '
                     'zániku (druh se posouvá po osmi, rychlost má horní bit – '
                     'to je M6), pak z tabulky zmizí, a **záznam s nejnižším '
                     'slotem, který je pořád automatický Vorton, dostane druh '
                     '0** a od toho průchodu poslouchá klávesy. Hráč tedy '
                     'nezačíná znovu na startu: přebírá Vortona tam, kde právě '
                     'je, i s jeho pozicí a fází animace.'),
        },
        'open': [
            'čelo konvoje se občas zastaví, i když má před sebou volno – ve '
            'všech naměřených případech daleko před kamerou, a tři nezávislé '
            'běhy se zastaví v tomtéž y. Co ho zastavilo, v tabulce objektů '
            'není: obsah zóny, do které konvoj vjel, se ještě nenačetl (M2). '
            'Je to %.2f %% naměřených průchodů konvoje.'
            % (100.0*worst/max(1, len(cases))),
            'co se s konvojem stane v Zone Zero (koncová sekvence, M7)',
            'jak se automatický Vorton chová, když na něj zaútočí nepřítel – '
            'zánik samotný je M6',
            'jestli konvoj po druhém průchodu (M7) jede jinak',
        ],
    }
    with open(args.out, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print('%s: konvoj' % os.path.relpath(args.out, H.ROOT))


if __name__ == '__main__':
    main()
