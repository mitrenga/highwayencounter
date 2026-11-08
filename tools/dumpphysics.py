#!/usr/bin/env python3
"""Odměří konstanty fyziky řízeného Vortona → `data/physics.json` (M3).

    PYTHONPATH=tools/vendor ./tools/dumpphysics.py [--out data/physics.json]

Nic se neodhaduje: každá konstanta se **vytáhne z běžícího originálu**
skriptovanými klávesami a měřením, co se v jeho paměti stane. Kde by
disassembly řekla víc (jak přesně vypadá kód, který to dělá), je to napsané
jako otevřená otázka v `sources/docs/disasm_notes.md` §12–§13.

Co se měří:

* **osm směrů** – posun na jednotku rychlosti pro každý směr 0–7,
* **rychlosti** – kolik jich je a co dělá `1` a `Q`,
* **časovač plynu** – posuvný registr `$8F1D`: kolik kroků trvá další stupeň,
* **otáčení** – jak často se smí otočit a čím je to řízené (`$8F13`),
* **okraj silnice** – meze souřadnice napříč silnicí,
* **délka kroku** – kolik T-stavů trvá průchod hlavní smyčkou (kolísá, M9).

Souřadnice objektu je **táž světová souřadnice**, ve které roste okno světa
`$8F05`: zóna je 176 dlouhá a při rychlosti 1 se `y` mění o 2 na krok. M3 to
četla jako „půljednotky" 352 dlouhé zóny; M4 délku zóny odměřila proti pozici
hráče a vyšlo **176** (`disasm_notes.md` §14).
"""
import argparse, json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

OUT = os.path.join(H.ROOT, 'data/physics.json')


def fresh():
    return H.gameplay()


def coast_to_rest(s):
    for _ in range(30):
        if s.player()['speed'] == 0:
            return
        s.step(('Q',))


def face(s, target):
    """Otočí stojícího Vortona na daný směr."""
    turn = 'P' if 0 < target <= 4 else 'O'
    for _ in range(40):
        if s.player()['dir'] == target:
            return
        s.step((turn,))
    raise RuntimeError('nepodařilo se otočit na směr %d' % target)


def measure_directions():
    """Posun a otočení animace za krok pro každý směr, na jednotku rychlosti.

    Fáze animace (`+9` v záznamu) se **nepočítá jen podle rychlosti**: Vorton je
    koule a v izometrii se od směru k směru mění i to, na kterou stranu se jeví,
    že se valí. Ve dvou směrech se fáze nemění vůbec. Tabulka se proto odměří
    stejně jako posun, směr po směru.
    """
    vectors, phases = {}, {}
    for target in range(8):
        s = fresh()
        # napřed kus dopředu, aby za Vortonem nestál konvoj a měřilo se volně
        for _ in range(20):
            s.step(('1',))
        coast_to_rest(s)
        face(s, target)
        prev = s.player()
        seen, spin = set(), set()
        for _ in range(12):
            s.step(('1',))
            p = s.player()
            if p['speed']:
                dx = (p['x'] - prev['x'])
                dy = (p['y'] - prev['y'])
                if (dx, dy) != (0, 0):
                    seen.add((dx // p['speed'], dy // p['speed']))
                    if p['speed'] == 1:
                        # jen při rychlosti 1: při 2 je posun o 8 a ±8 se
                        # v šestnáctce nedá rozeznat
                        d = (p['phase'] - prev['phase']) % 16
                        spin.add(d - 16 if d > 8 else d)
            prev = p
        if len(seen) != 1 or len(spin) != 1:
            raise RuntimeError('směr %d: nejednoznačný posun %s / fáze %s'
                               % (target, seen, spin))
        vectors[target] = list(seen.pop())
        phases[target] = spin.pop()
    return vectors, phases


def measure_speeds():
    """Kolik je rychlostních stupňů a po kolika krocích se přidávají.

    Měří se jen do prvního kroku, ve kterém do Vortona něco vrazilo (stojí,
    ačkoli má rychlost) – za srážkou už rychlost neurčuje plyn, ale náraz.
    """
    def drive(keyfn, steps):
        s = fresh()
        prev = s.player()
        out = []
        for i in range(steps):
            s.step(tuple(keyfn(i)))
            p = s.player()
            if p['speed'] and (p['x'], p['y']) == (prev['x'], prev['y']):
                break               # náraz – dál už se fyzika plynu neměří
            if p['speed'] != prev['speed']:
                out.append((i, prev['speed'], p['speed']))
            prev = p
        return out, prev['speed']

    ups, top_reached = drive(lambda i: ('1',), 60)
    top = max([u[2] for u in ups] + [top_reached])
    gaps = [ups[i + 1][0] - ups[i][0] for i in range(len(ups) - 1)]

    downs, _ = drive(lambda i: ('1',) if i < 20 else ('Q',), 40)
    downs = [d for d in downs if d[1] > d[2]]
    dgaps = [downs[i + 1][0] - downs[i][0] for i in range(len(downs) - 1)]

    # bez klávesy hra nezpomaluje vůbec – ověřit, ne předpokládat
    coast, coasted = drive(lambda i: ('1',) if i < 12 else (), 24)
    slowed = [c for c in coast if c[0] >= 12 and c[2] < c[1]]

    return {
        'max': top,
        'accelStepGaps': gaps,
        'decelStepGaps': dgaps,
        'firstAccelImmediate': ups[0][0] == 0,
        'firstDecelImmediate': downs[0][0] == 20,
        'coastsForever': not slowed and coasted == top,
    }


def measure_thrust_timer():
    """Posuvný registr `$8F1D`: hodnota po každém kroku plného plynu."""
    s = fresh()
    seq = []
    for _ in range(12):
        s.step(('1',))
        seq.append(s.peek(H.THRUST_TIMER))
    return {'reload': max(seq), 'sequence': seq}


def measure_turning():
    """Kdy se smí otočit: kroky, ve kterých se směr změnil, a stav `$8F13`."""
    out = {}
    for key, name in (('O', 'left'), ('P', 'right')):
        s = fresh()
        changes, phases = [], []
        prev = s.player()['dir']
        for i in range(20):
            s.step((key,))
            p = s.player()
            phases.append(p['turnPhase'])
            if p['dir'] != prev:
                changes.append(i)
                prev = p['dir']
        out[name] = {'stepsChanged': changes,
                     'phaseWhenTurned': sorted({phases[i] for i in changes}),
                     'delta': -1 if key == 'O' else 1}
    # obě zároveň = žádná otáčka
    s = fresh()
    start = s.player()['dir']
    for _ in range(12):
        s.step(('O', 'P'))
    out['bothKeysTurns'] = s.player()['dir'] != start
    out['everyNSteps'] = 2
    out['phaseByte'] = H.TURN_PHASE
    return out


def measure_road():
    """Meze souřadnice napříč silnicí – dojet k oběma okrajům a zůstat stát.

    Vrací i to, co náraz udělá s rychlostí a s časovačem plynu.
    """
    edges = {}
    hits = []
    for target, name in ((6, 'maxX'), (2, 'minX')):
        s = fresh()
        for _ in range(10):
            s.step(('1',))
        coast_to_rest(s)
        face(s, target)
        last = None
        prev = s.player()
        for _ in range(80):
            s.step(('1',))
            p = s.player()
            if (p['x'], p['y']) == (prev['x'], prev['y']) and prev['speed']:
                hits.append((prev['speed'], p['speed'], p['timer']))
            if p['speed'] == 0 and last == p['x']:
                break
            last = p['x']
            prev = p
        edges[name] = last
    drops = {h[0] - h[1] for h in hits}
    reloads = {h[1]: h[2] for h in hits}
    edges['speedDropOnHit'] = sorted(drops)
    edges['timerAfterHit'] = {str(k): v for k, v in sorted(reloads.items())}
    return edges


def measure_spawn():
    """Záznam řízeného Vortona hned po startu hry – odkud se v zóně 30 vyjíždí."""
    s = fresh()
    p = s.player()
    return {k: p[k] for k in ('x', 'y', 'cls', 'dir', 'speed', 'phase', 'kind')}


def measure_step_length():
    """Kolik T-stavů trvá průchod hlavní smyčkou (kolísá podle vytížení)."""
    s = fresh()
    lens = []
    for i in range(400):
        lens.append(s.step(('1',) if (i // 25) % 2 == 0 else ('O',)))
    lens.sort()
    fd = s.simulator.frame_duration
    return {'min': lens[0], 'max': lens[-1],
            'median': lens[len(lens) // 2],
            'mean': round(statistics.mean(lens)),
            'frameTstates': fd,
            'framesPerStepMean': round(statistics.mean(lens) / fd, 4)}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=OUT)
    args = ap.parse_args()

    print('směry…')
    vectors, phases = measure_directions()
    print('rychlosti…')
    speeds = measure_speeds()
    print('časovač plynu…')
    timer = measure_thrust_timer()
    print('otáčení…')
    turning = measure_turning()
    print('okraje silnice…')
    road = measure_road()
    print('start…')
    spawn = measure_spawn()
    print('délka kroku…')
    step = measure_step_length()

    accel_gaps = set(speeds['accelStepGaps']) | set(speeds['decelStepGaps'])
    data = {
        'note': ('Fyzika řízeného Vortona, odměřená z běžícího originálu '
                 '(tools/dumpphysics.py). Souřadnice je táž světová '
                 'souřadnice, ve které roste okno světa $8F05; jeden krok = '
                 'jeden průchod hlavní smyčkou hry, ne jeden snímek.'),
        'source': 'tools/dumpphysics.py, build/gameplay.z80',
        'units': {
            'coordinate': ('světová souřadnice; při rychlosti 1 se mění '
                           'o 2 na krok'),
            'zoneLength': 176,
            'step': 'jeden průchod hlavní smyčkou hry',
        },
        'directions': vectors,
        'phase': {
            'mask': 15,
            'perDirectionPerSpeed': phases,
            'note': ('o kolik se posune fáze animace za krok na jednotku '
                     'rychlosti; ve směrech 3 a 7 se koule jeví, že se nevalí'),
        },
        'speed': {
            'max': speeds['max'],
            'min': 0,
            'stepsPerChange': sorted(accel_gaps),
            'firstChangeImmediate': (speeds['firstAccelImmediate']
                                     and speeds['firstDecelImmediate']),
            'coastsForever': speeds['coastsForever'],
        },
        'thrustTimer': {
            'address': H.THRUST_TIMER,
            'reload': timer['reload'],
            'shiftRightEachStep': True,
            'sequence': timer['sequence'],
            'note': ('nabije se na reload při každé změně rychlosti a posouvá '
                     'se doprava každý krok, i když Vorton stojí; další změna '
                     'přijde, až je nula – tedy za osm kroků'),
        },
        'turning': turning,
        'collision': {
            'road': {'minX': road['minX'], 'maxX': road['maxX']},
            'speedDropOnHit': road['speedDropOnHit'],
            'timerAfterHit': road['timerAfterHit'],
            'timerReload': max(road['timerAfterHit'].values()),
            'onBlocked': ('krok se zahodí celý (x i y), fáze animace se '
                          'neposune, rychlost klesne o 1 a časovač plynu se '
                          'nastaví na timerReload – nebo na 0, když je '
                          'rychlost po nárazu nulová'),
        },
        'keys': {
            'address': H.KEYS_READ,
            'fire': H.KEY_FIRE, 'accelerate': H.KEY_ACCEL,
            'decelerate': H.KEY_DECEL, 'right': H.KEY_RIGHT, 'left': H.KEY_LEFT,
        },
        'spawn': spawn,
        'stepLength': step,
    }
    with open(args.out, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write('\n')
    print('%s: %d směrů, rychlosti 0–%d, silnice x %d–%d, krok %d T (%.2f snímku)'
          % (os.path.relpath(args.out, H.ROOT), len(vectors), speeds['max'],
             road['minX'], road['maxX'], step['mean'], step['framesPerStepMean']))
    print('náraz: rychlost -%s, časovač %s'
          % ('/'.join(str(d) for d in road['speedDropOnHit']),
             road['timerAfterHit']))


if __name__ == '__main__':
    main()
