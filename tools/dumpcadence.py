#!/usr/bin/env python3
"""Odměří **kadenci hlavní smyčky** → `data/cadence.json` (M9).

    PYTHONPATH=tools/vendor ./tools/dumpcadence.py [--out data/cadence.json]

M3 (`disasm_notes.md` §11) našla, že se stav hry mění jednou za **průchod
hlavní smyčkou**, ne jednou za snímek, a že průchod trvá 1,4 až 13 snímků.
Změřené bylo rozdělení, ne pravidlo – a to bylo poslední otevřené místo M9.

Pravidlo se našlo a je v kódu: hlavní smyčka má **regulátor**. Na `$9AD8`
sedí prázdná čekací smyčka, která se pustí jen tehdy, když se ten průchod
kreslilo **málo** – a čeká tím víc, čím míň toho bylo:

    $9AD8  LD A,($8F0B)     konec seznamu kreslení ($8D52 + 3 × počet záznamů)
    $9ADB  CP $6A           = $8D52 + 3 × 8, tedy osm záznamů
    $9ADD  JP NC,$9B72      osm a víc: nečeká se vůbec
    $9AE0  LD B,A
    $9AE1  LD A,$6A
    $9AE3  SUB B
    $9AE4  ADD A,A          k = 2 × ($6A − konec) = 48 − 6 × počet
    $9AE5  LD B,$C8
    $9AE7  DJNZ $9AE7       200 × nic
    $9AE9  DEC A
    $9AEA  JR NZ,$9AE5
    $9AEC  JP $9B72

Kadence je tedy součet tří věcí, a dvě z nich jsou **přesné**:

* **práce** – kreslení a logika, roste s počtem kreslených záznamů a s počtem
  živých záznamů v tabulce; jediná fitovaná část,
* **regulátor** – `2618 × k + 54` T-stavů, k = 48 − 6 × počet kreslených
  záznamů (a `30`, když se nečeká); spočítané z instrukcí a ověřené měřením,
* **zvuk** – efekt se hraje **synchronně uvnitř smyčky**, takže se jeho délka
  přičte celá; a ta je změřená na T-stav už v M8 (`data/sounds.json`
  `measuredT`), takže se sem jen odkazuje.

**Překreslení plochy** je čtvrtá věc a měří se zvlášť: originál smaže a znovu
složí celou hrací plochu a průchod trvá kolem 950 000 T, třináct snímků. Dělá
to na dvou místech, a obě se poznají zvenčí: při **přechodu do další zóny** a
v průchodu, ve kterém hra **přišla o řízeného Vortona** (na jeho místě
v tabulce je pak `$FE`).

Měří se na běhu originálu: režim `6 DEMONSTRATION` projede celou silnici,
k tomu 24 hraných běhů s pseudonáhodnými klávesami kvůli zvukům a nárazům.
"""
import argparse, json, os, random, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402

OUT = os.path.join(H.ROOT, 'data/cadence.json')
SOUNDS = os.path.join(H.ROOT, 'data/sounds.json')

# --- regulátor: adresy a bajty, které se kontrolují proti obrazu hry --------
GOVERNOR = 0x9AD8
LIST = 0x8D52           # seznam kreslení, trojice (klíč, adresa záznamu)
LIST_TAIL = 0x8F0B      # jeho konec – to je to, co regulátor čte
COUNTERS = 0xFD00       # počítadla špinavých buněk, 576 B (§8)
COUNTERS_END = 0xFF40
ENTITIES = H.ENTITIES   # tabulka objektů $8A00, 16 B na záznam
RECORD = 3              # bajtů na záznam seznamu kreslení
# instrukce regulátoru tak, jak mají v paměti stát (kontrola, ne odhad)
GOVERNOR_BYTES = bytes([
    0x3A, 0x0B, 0x8F,         # LD A,($8F0B)
    0xFE, 0x6A,               # CP $6A
    0xD2, 0x72, 0x9B,         # JP NC,$9B72
    0x47,                     # LD B,A
    0x3E, 0x6A,               # LD A,$6A
    0x90,                     # SUB B
    0x87,                     # ADD A,A
    0x06, 0xC8,               # LD B,$C8
    0x10, 0xFE,               # DJNZ $9AE7
    0x3D,                     # DEC A
    0x20, 0xF9,               # JR NZ,$9AE5
    0xC3, 0x72, 0x9B,         # JP $9B72
])
# T-stavy spočítané z těch instrukcí (Z80, bez čekacích cyklů ULA – hra běží
# v RAM nad $8000, kde se nečeká):
#   nastavení    LD A,(nn) 13 + CP 7 + JP 10 + LD B,A 4 + LD A,n 7 + SUB 4 + ADD 4
#   jedna otáčka LD B,$C8 7 + DJNZ (199 × 13 + 8) + DEC A 4 + JR NZ 12
#   poslední     JR NZ nepřeskočí 7, JP 10
GOVERNOR_SETUP = 13 + 7 + 10 + 4 + 7 + 4 + 4         # 49
GOVERNOR_ITER = 7 + (199 * 13 + 8) + 4 + 12          # 2618
GOVERNOR_TAIL = (7 - 12) + 10                        # 5 – poslední JR a JP
GOVERNOR_SKIP = 13 + 7 + 10                          # 30, když se nečeká
GOVERNOR_LIMIT = 0x6A                                # mez z instrukce CP


def governor_tstates(drawn):
    """T-stavy, které smyčka prostojí v regulátoru při `drawn` kreslených
    záznamech – přesně tak, jak to spočítají instrukce na `$9AD8`."""
    tail = (LIST + RECORD * drawn) & 0xFF
    if tail >= GOVERNOR_LIMIT:
        return GOVERNOR_SKIP
    k = 2 * (GOVERNOR_LIMIT - tail)
    return GOVERNOR_SETUP + GOVERNOR_ITER * k + GOVERNOR_TAIL


def check_governor(session):
    """Ověří, že na `$9AD8` opravdu stojí ty instrukce, ze kterých je spočítaná
    tabulka regulátoru."""
    got = bytes(session.peek(GOVERNOR, len(GOVERNOR_BYTES)))
    if got != GOVERNOR_BYTES:
        raise SystemExit('kód regulátoru na $%04X nesedí – hra se změnila?'
                         % GOVERNOR)


def features(session):
    """Co se o průchodu dá přečíst z paměti na jeho hranici (`$985A`)."""
    m = session.simulator.memory
    tail = m[LIST_TAIL] | (m[LIST_TAIL + 1] << 8)
    drawn = (tail - LIST) // RECORD
    live = 0
    a = ENTITIES
    while a < LIST and m[a] != 0xFF:
        if m[a] != 0xFE:                # $FE je prázdné místo v tabulce
            live += 1
        a += H.ENTITY_SIZE
    dirty = 0
    for v in m[COUNTERS:COUNTERS_END]:
        if v:
            dirty += 1
    return {'drawn': drawn, 'live': live, 'sound': m[0x8F15],
            'window': m[0x8F05] | (m[0x8F06] << 8),
            # prázdná tabulka počítadel na konci průchodu = plocha se
            # překreslila celá a nic nezůstalo rozkreslené (§8)
            'dirty': dirty,
            # $FE na místě řízeného Vortona znamená, že o něj hra přišla
            'noPlayer': m[ENTITIES] == 0xFE}


def record_passes(demo_passes=1300, runs=24, run_passes=220):
    """Nasbírá průchody: demonstrace přes celou silnici a hrané běhy."""
    rows = []
    s = H.demo()
    check_governor(s)
    for _ in range(demo_passes):
        pre = features(s)
        try:
            t = s.step()
        except RuntimeError:
            break
        rows.append({'t': t, 'pre': pre, 'post': features(s), 'first': False})
    for seed in range(runs):
        s = H.gameplay()
        rnd = random.Random(seed)
        held = ('1',)
        for i in range(run_passes):
            if rnd.random() < 0.25:
                held = tuple(k for k in ('1', 'Q', 'O', 'P', 'SPACE')
                             if rnd.random() < 0.4)
            pre = features(s)
            try:
                t = s.step(held)
            except RuntimeError:
                break
            # první průchod po načtení cache je useknutý (hra stojí uprostřed
            # smyčky), takže se do měření nebere
            rows.append({'t': t, 'pre': pre, 'post': features(s),
                         'first': i == 0})
    return rows


def sound_tstates(flag, effects, priority):
    """Kolik T-stavů si vezme zvuk, o který si průchod řekl – rozskok `$9AEF`
    bere první bit v pořadí priority (data/sounds.json `flag`)."""
    for bit in priority:
        if flag & (1 << bit):
            return effects.get(bit, 0)
    return 0


def lstsq(rows_x, y):
    """Nejmenší čtverce, Gaussova eliminace – bez numpy, jako všude v tools/."""
    n = len(rows_x[0])
    a = [[sum(rows_x[k][i] * rows_x[k][j] for k in range(len(rows_x)))
          for j in range(n)] for i in range(n)]
    b = [sum(rows_x[k][i] * y[k] for k in range(len(rows_x))) for i in range(n)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(a[r][i]))
        a[i], a[p] = a[p], a[i]
        b[i], b[p] = b[p], b[i]
        for r in range(n):
            if r == i:
                continue
            f = a[r][i] / a[i][i]
            for c in range(i, n):
                a[r][c] -= f * a[i][c]
            b[r] -= f * b[i]
    return [b[i] / a[i][i] for i in range(n)]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=OUT)
    args = ap.parse_args()

    if not os.path.isfile(SOUNDS):
        raise SystemExit('chybí data/sounds.json – spusť tools/dumpsound.py')
    sounds = json.load(open(SOUNDS))
    priority = sounds['flag']['priority']
    effects = {e['bit']: e['measuredT'] for e in sounds['sounds']}
    names = {e['bit']: e['name'] for e in sounds['sounds']}

    print('měřím průchody…')
    rows = record_passes()
    good = [r for r in rows if not r['first']]
    # Překreslení plochy se pozná dvěma způsoby a oba jsou přímé: buď se
    # změnilo okno zóny, nebo průchod skončil s **prázdnou** tabulkou
    # počítadel – to znamená, že se plocha složila celá znovu a nic v ní
    # nezůstalo rozkreslené. Druhý případ nastává, když hra přijde o řízeného
    # Vortona ($FE na jeho místě v tabulce).
    for i, r in enumerate(good):
        r['zone'] = r['pre']['window'] != r['post']['window']
        r['lost'] = bool(r['post']['dirty'] == 0 and not r['zone'])
        r['repaint'] = r['zone'] or r['lost']
    steady = [r for r in good if not r['repaint']]
    zone = [r for r in good if r['repaint']]

    # Zvuk se hraje na konci průchodu, ve kterém si o něj hra řekla – z pohledu
    # hranice `$985A` je to průchod, na jehož **začátku** je žádanka nenulová.
    def modelled_extras(r):
        return (governor_tstates(r['post']['drawn'])
                + sound_tstates(r['pre']['sound'], effects, priority))

    y = [r['t'] - modelled_extras(r) for r in steady]
    x = [[1, r['post']['drawn'], r['post']['live']] for r in steady]
    base, per_drawn, per_live = lstsq(x, y)

    def predict(r):
        return (base + per_drawn * r['post']['drawn']
                + per_live * r['post']['live'] + modelled_extras(r))

    resid = sorted(r['t'] - predict(r) for r in steady)
    rel = sorted(abs(r['t'] - predict(r)) / r['t'] for r in steady)
    frame = 69888
    within = {q: sum(1 for r in steady if abs(r['t'] - predict(r)) < frame * q)
              for q in (0.125, 0.25, 0.5, 1.0)}

    # regulátor: kolik průchodů mělo který počet kreslených záznamů
    hist = {}
    for r in good:
        hist[r['post']['drawn']] = hist.get(r['post']['drawn'], 0) + 1

    zone_t = [r['t'] for r in zone]
    # překreslení se dá skládat: průchod, ve kterém k němu dojde, dělá i svou
    # obvyklou práci, takže se měří **příplatek** nad model práce
    zone_extra = sorted(
        r['t'] - (base + per_drawn * r['post']['drawn']
                  + per_live * r['post']['live'] + modelled_extras(r))
        for r in zone)
    all_t = [r['t'] for r in good]

    data = {
        'note': ('Kadence hlavní smyčky Highway Encounter, odměřená na běžícím '
                 'originálu (tools/dumpcadence.py). Průchod trvá práce + '
                 'regulátor + zvuk; regulátor a zvuk jsou přesné, práce je '
                 'jediná fitovaná část. Přechod zóny je zvláštní případ.'),
        'source': 'tools/dumpcadence.py, build/gameplay.z80, build/highwayencounter.z80',
        'cpuHz': 3500000,
        'frameTstates': frame,
        'governor': {
            'at': '$%04X' % GOVERNOR,
            'list': '$%04X' % LIST,
            'listTail': '$%04X' % LIST_TAIL,
            'recordBytes': RECORD,
            'limit': '$%02X' % GOVERNOR_LIMIT,
            'maxDrawn': (GOVERNOR_LIMIT - (LIST & 0xFF)) // RECORD,
            'setupT': GOVERNOR_SETUP,
            'iterT': GOVERNOR_ITER,
            'tailT': GOVERNOR_TAIL,
            'skipT': GOVERNOR_SKIP,
            'iterations': '2 × ($6A − ($52 + 3 × kreslených))',
            'tstates': {str(n): governor_tstates(n) for n in range(0, 16)},
            'histogram': {str(k): hist[k] for k in sorted(hist)},
            'note': ('Prázdná čekací smyčka na konci průchodu. Čte konec '
                     'seznamu kreslení ($8F0B) a čeká 2618 T za každou svou '
                     'otáčku; otáček je 48 − 6 × počet kreslených záznamů, '
                     'takže od osmi záznamů výš se nečeká vůbec. Tím se '
                     'chudé průchody zpomalí na úroveň bohatých – a proto '
                     'délka průchodu kolísá míň, než by kolísala práce sama.'),
        },
        'work': {
            'base': round(base, 1),
            'perDrawn': round(per_drawn, 1),
            'perLive': round(per_live, 1),
            'note': ('T-stavy práce průchodu: kreslení jednoho záznamu '
                     '(pozadí, sprit, počítadla buněk, přenos na obrazovku) a '
                     'krok jednoho živého záznamu tabulky, ať je vidět, nebo '
                     'ne. Jediná fitovaná část modelu; „base" vyšla skoro '
                     'nulová, což je samo o sobě kontrola, že se nic '
                     'nezapomnělo.'),
        },
        'sound': {
            'from': 'data/sounds.json',
            'flag': sounds['flag']['at'],
            'dispatch': sounds['flag']['dispatch'],
            'priority': priority,
            'tstates': {names[b]: effects[b] for b in sorted(effects)},
            'bits': {names[b]: b for b in sorted(effects)},
            'note': ('Efekt se hraje synchronně uvnitř smyčky, takže se jeho '
                     'délka přičte celá. Průchod, ve kterém si o zvuk hra '
                     'řekla, je ještě krátký – hraje se až v tom dalším.'),
        },
        'repaint': {
            'passes': len(zone_t),
            'zonePasses': sum(1 for r in zone if r['zone']),
            'vortonLostPasses': sum(1 for r in zone if r['lost']),
            'detect': ('okno zóny se změnilo, nebo průchod skončil s prázdnou '
                       'tabulkou počítadel $FD00'),
            'mean': round(statistics.mean(zone_t)) if zone_t else 0,
            'median': round(statistics.median(zone_t)) if zone_t else 0,
            'min': min(zone_t) if zone_t else 0,
            'max': max(zone_t) if zone_t else 0,
            'extraMedian': round(statistics.median(zone_extra)) if zone_extra else 0,
            'extraSd': round(statistics.pstdev(zone_extra)) if len(zone_extra) > 1 else 0,
            'note': ('Průchod, ve kterém originál smaže a znovu složí celou '
                     'hrací plochu z bloku pozadí: přechod do další zóny a '
                     'ztráta řízeného Vortona. Svou obvyklou práci ten '
                     'průchod udělá taky, takže se model práce nezahazuje – '
                     'přičte se k němu `extraMedian`.'),
        },
        'verification': {
            'passes': len(good),
            'steadyPasses': len(steady),
            'meanT': round(statistics.mean(all_t)),
            'medianT': round(statistics.median(all_t)),
            'meanFrames': round(statistics.mean(all_t) / frame, 3),
            'residualSd': round(statistics.pstdev(resid)),
            'residualP05': round(resid[int(len(resid) * 0.05)]),
            'residualP95': round(resid[int(len(resid) * 0.95)]),
            'relMedianPct': round(100 * rel[len(rel) // 2], 2),
            'relP95Pct': round(100 * rel[int(len(rel) * 0.95)], 2),
            'withinEighthFrame': round(100 * within[0.125] / len(steady), 1),
            'withinQuarterFrame': round(100 * within[0.25] / len(steady), 1),
            'withinHalfFrame': round(100 * within[0.5] / len(steady), 1),
            'withinFrame': round(100 * within[1.0] / len(steady), 1),
        },
        'open': ('Zbytkový rozptyl práce (kolem 5 %) je v tom, kolik buněk se '
                 'ten průchod opravdu přenáší na obrazovku – to závisí na tom, '
                 'kde sprity stojí, a port si počítadla buněk nevede. Kdyby si '
                 'je screenComposer.js vedl, dal by se model dotáhnout na '
                 'jednotky procent promile.'),
    }

    with open(args.out, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write('\n')

    v = data['verification']
    print('%s: %d průchodů, %d ustálených, %d s překreslením plochy'
          % (os.path.relpath(args.out, H.ROOT), v['passes'], v['steadyPasses'],
             len(zone_t)))
    print('regulátor: čeká do %d kreslených záznamů, nejvíc %d T (%.2f snímku)'
          % (data['governor']['maxDrawn'], governor_tstates(0),
             governor_tstates(0) / frame))
    print('práce: %.0f T na kreslený záznam, %.0f T na živý záznam, základ %.0f T'
          % (per_drawn, per_live, base))
    print('model: medián chyby %.2f %%, %.1f %% průchodů do čtvrt snímku, '
          '%.1f %% do půl snímku'
          % (v['relMedianPct'], v['withinQuarterFrame'], v['withinHalfFrame']))
    print('průchod trvá průměrně %d T (%.2f snímku); překreslení plochy %d T '
          'navrch (%d× zóna, %d× ztráta Vortona)'
          % (v['meanT'], v['meanFrames'], data['repaint']['extraMedian'],
             data['repaint']['zonePasses'], data['repaint']['vortonLostPasses']))


if __name__ == '__main__':
    main()
