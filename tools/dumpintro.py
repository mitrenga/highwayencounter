#!/usr/bin/env python3
"""Odměří **intro, titulní obrazovku a attract mode** → `data/intro.json` (M7).

    PYTHONPATH=tools/vendor ./tools/dumpintro.py [--out data/intro.json]

Crash 20 psal „I loved the introduction as well" a ZADANI to nechalo na M7.
Intro je tohle: po nahrání zůstane chvíli stát **loading screen z kazety**, pak
se obraz smaže na prázdnou izometrickou mřížku a hra si na ni **kus po kuse
postaví nápis `HIGHWAY ENCOUNTER` v izometrii** – ne obrázkem, kreslí ho. Když
je hotový, přibude naráz zbytek titulní obrazovky (logo Vortexu, `AUTHOR COSTA
PANAYI`, menu `OPTIONS`, copyright) a hra čeká na volbu.

Attract mode je volba **`6 DEMONSTRATION`**. Nehraje se v něm: hra si jen
projede silnici zóna po zóně, pořád stejně rychle, hodiny `TIME` u toho stojí
(§16), a za Zone Zero to skončí obrazovkou `THERE IS ONLY ONE WAY TO ENCOUNTER
WHAT LIES BEYOND ZONE ZERO! SO GET ON WITH IT!` a čekáním na klávesu.

Co se měří a co ne:

* **časy intra** – snímek po snímku se počítá, kolik bajtů se v obraze změnilo;
  z toho vypadnou hranice fází a délka stavby nápisu;
* **titulní obrazovka** se ukládá jako obrázek (bitmapa + atributy) a zároveň
  se **rozebere zpátky na znaky** znakovou sadou z `data/font.json`, takže je
  v datech i text s pozicemi;
* **blikání volby** – jediná buňka atributů, která se na titulní obrazovce
  mění; měří se která, mezi jakými barvami a jak často;
* **demo** – po kolika **průchodech hlavní smyčky** přeskočí zóna, jestli
  ubývá `TIME`, kolik průchodů celé demo trvá a čím končí;
* **co intro kreslí**, se nepřekresluje: izometrický nápis je grafika a ta
  čeká na M2/M8. Uloží se referenční obrázek originálu, ne recept.

Spouštět s `PYTHONPATH=tools/vendor` (vendorovaný SkoolKit, viz tools/README.md).
"""
import argparse, base64, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                            # noqa: E402
import dumpfont                                                   # noqa: E402

TITLE_FRAMES = 400          # ve snímku 400 je titulní obrazovka hotová
BLINK_FRAMES = 300          # jak dlouho se kouká na blikání
DEMO_STEPS = 1400           # demo skončí dřív; strop, aby se to nezaseklo

ZONE_COUNTER = 0x8F00
TIME_COUNTER = 0x8F1A
DEMO_END_STRING = 0xA4D6

# konstanty konce dema, čtené z kódu ($A3A8 dál)
DEMO_ATTR = (0xA3B0, 0x36, 'atribut, kterým se hrací plocha přebarví')
DEMO_ROWS = (0xA3AC, 0x0E, 'kolik znakových řádek se přebarví')
DEMO_WAIT = (0xA3BE, 0x0E, 'vnější počítadlo čekání na klávesu')
DEMO_ANYKEY = (0xA3C8, 0xE6, 'maska kláves – kterákoli z pěti v půlřádce')


def frame_changes(session, frames):
    """Kolik bajtů obrazu se změnilo mezi snímky – hranice fází intra."""
    out, prev = [], None
    for _ in range(frames):
        session.run(1)
        scr = session.screen()
        if prev is not None:
            bitmap = sum(1 for a, b in zip(scr[:6144], prev[:6144]) if a != b)
            attrs = sum(1 for a, b in zip(scr[6144:], prev[6144:]) if a != b)
            out.append((session.frame, bitmap, attrs))
        prev = scr
    return out


def phases(changes):
    """Hranice fází: první změna, největší přepis, poslední změna bitmapy."""
    moved = [c for c in changes if c[1] or c[2]]
    if not moved:
        return {}
    wipe = max(changes, key=lambda c: c[1])
    bitmap_moves = [c for c in changes if c[1]]
    return {
        'loadingScreenUntil': moved[0][0] - 1,
        'wipeAt': wipe[0],
        'wipeBytes': wipe[1],
        'buildFrom': wipe[0] + 1,
        'buildUntil': bitmap_moves[-1][0],
        'buildFrames': bitmap_moves[-1][0] - wipe[0],
        'buildSteps': len([c for c in bitmap_moves if c[0] > wipe[0]]),
    }


def blink(session, frames=BLINK_FRAMES):
    """Buňka atributů, která na hotové titulní obrazovce bliká."""
    prev, events = None, []
    for _ in range(frames):
        session.run(1)
        attrs = session.screen()[6144:]
        if prev is not None:
            for i, (a, b) in enumerate(zip(prev, attrs)):
                if a != b:
                    events.append((session.frame, i, a, b))
        prev = attrs
    if not events:
        return None
    cells = sorted(set(e[1] for e in events))
    gaps = [events[i+1][0] - events[i][0] for i in range(len(events) - 1)]
    return {
        'cells': [{'row': c // 32, 'col': c % 32} for c in cells],
        'colours': sorted(set('$%02X' % e[3] for e in events)),
        'changes': len(events),
        'periodFrames': round(sum(gaps) / len(gaps), 2) if gaps else None,
        'note': ('na titulní obrazovce se mění jediná buňka atributů – '
                 'oddělovač u vybrané volby ovládání; přebarvuje se mezi '
                 'dvěma z barev, které umí tiskárna textu ($B890)'),
    }


def demo(steps=DEMO_STEPS):
    """Attract mode: po kolika průchodech skáče zóna a čím to skončí."""
    s = H.demo()
    zones, time_seen, keys_seen = [], set(), set()
    last = None
    ended = None
    for i in range(steps):
        try:
            s.step(())
        except RuntimeError:
            ended = i
            break
        time_seen.add(s.peek(TIME_COUNTER) | (s.peek(TIME_COUNTER + 1) << 8))
        keys_seen.add(s.peek(H.KEYS_READ))
        z = s.peek(ZONE_COUNTER)
        if z != last:
            zones.append((i, z))
            last = z
    gaps = [zones[i+1][0] - zones[i][0] for i in range(len(zones) - 1)]
    return s, {
        'zones': len(zones),
        'firstZoneAtStep': zones[0][0] if zones else None,
        'stepsPerZone': sorted(set(gaps)),
        'lastZone': zones[-1][1] if zones else None,
        'endedAtStep': ended,
        'stepsAfterLastZone': None if ended is None or not zones
                              else ended - zones[-1][0],
        'timeCounterValues': sorted(time_seen),
        'timeRunsDown': len(time_seen) > 1,
        'keysRead': sorted('$%02X' % k for k in keys_seen),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'data/intro.json'))
    args = ap.parse_args()

    charmap = {}
    font_path = os.path.join(H.ROOT, 'data/font.json')
    if os.path.isfile(font_path):
        with open(font_path) as f:
            charmap = json.load(f).get('map', {})

    # --- intro ----------------------------------------------------------
    s = H.Session()
    changes = frame_changes(s, TITLE_FRAMES)
    intro = phases(changes)

    scr = s.screen()
    glyphs = dumpfont.read_glyphs(s)
    rows = dumpfont.decode_screen(scr, glyphs)
    lines = []
    for row, col, run in dumpfont.title_lines(rows):
        lines.append({'row': row, 'col': col,
                      'codes': [int(i) for i in run],
                      'text': ''.join(charmap.get(str(i), '?') for i in run)})

    marker = blink(s)

    # --- demo -----------------------------------------------------------
    ds, demo_measured = demo()
    demo_attr = ds.peek(DEMO_ATTR[0])
    demo_scr = ds.screen()

    data = {
        'source': 'tools/dumpintro.py',
        'note': ('intro, titulní obrazovka a attract mode originálu. Obrázky '
                 'jsou referenční snímky originálu – izometrický nápis se '
                 'nepřekresluje, dokud není projekce a sprity (M2/M8).'),
        'intro': dict(intro, note=(
            'po nahrání stojí loading screen z kazety; pak se obraz smaže '
            'na prázdnou mřížku a hra si na ni po kusech postaví izometrický '
            'nápis HIGHWAY ENCOUNTER. Zbytek titulní obrazovky přibude naráz '
            'na konci. Časy jsou ve snímcích od startu hry.')),
        'title': {
            'frames': TITLE_FRAMES,
            'lines': lines,
            'bitmap': base64.b64encode(scr[:6144]).decode('ascii'),
            'attributes': base64.b64encode(scr[6144:]).decode('ascii'),
            'note': ('text se rozebral znakovou sadou z data/font.json; '
                     'bitmapa a atributy jsou celá obrazovka originálu, jak '
                     'ji hra nakreslí'),
        },
        'marker': marker,
        'menu': {
            'keys': {'1': 'KEYBOARD', '2': 'INTERFACE 2', '3': 'KEMPSTON',
                     '4': 'PROTEK/AGF', '5': 'INFORMATION',
                     '6': 'DEMONSTRATION', '7': 'START GAME'},
            'halfRows': ['$F7FE', '$EFFE'],
            'note': ('hra snímá jen dvě půlřádky klávesnice, takže volby jsou '
                     'číslice, ne písmena; hru spouští 7 (disasm_notes.md §4)'),
        },
        'demo': dict(demo_measured, **{
            'at': '$A8D5',
            'endScreen': {
                'at': '$%04X' % DEMO_END_STRING,
                'attribute': '$%02X' % demo_attr,
                'rows': ds.peek(DEMO_ROWS[0]),
                'lines': [l['text'] for l in _read_string(ds, DEMO_END_STRING, charmap)],
                'bitmap': base64.b64encode(demo_scr[:6144]).decode('ascii'),
                'attributes': base64.b64encode(demo_scr[6144:]).decode('ascii'),
            },
            'anyKeyMask': '$%02X' % ds.peek(DEMO_ANYKEY[0]),
            'note': ('demo nehraje – jede stále stejně a jen překlápí zóny; '
                     'hodiny TIME v něm stojí. Po Zone Zero se hrací plocha '
                     'přebarví a vysází se závěrečný text; hra pak čeká na '
                     'kteroukoli klávesu, s časovým limitem.'),
        }),
        'open': [
            'jak se izometrický nápis kreslí (a z jakých dat) – grafika, M2/M8',
            'hra sama demo nespustí: titulní obrazovka čeká libovolně dlouho '
            'a attract mode se musí vybrat klávesou 6 (měřeno 3000 snímků)',
            'volby 2 KEMPSTON / 3 INTERFACE 2 / 4 PROTEK-AGF jsou joysticky '
            'originálu; v remaku jsou z nich nastavení ovládání (ZADANI §5)',
        ],
    }
    with open(args.out, 'w') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print('%s: intro %s–%s (stavba %s snímků), %d řádek titulní obrazovky, '
          'demo %d zón po %s průchodech'
          % (os.path.relpath(args.out, H.ROOT), intro.get('loadingScreenUntil'),
             intro.get('buildUntil'), intro.get('buildFrames'), len(lines),
             demo_measured['zones'], demo_measured['stepsPerZone']))


def _read_string(session, addr, charmap, limit=400):
    """Týž formát jako `dumpending.read_string`, jen bez závislosti na něm."""
    lines, i, end = [], addr, addr + limit
    while i < end:
        i += 3
        codes = []
        while i < end:
            b = session.peek(i)
            i += 1
            if b in (0xFF, 0xFE):
                break
            codes.append(b)
        lines.append({'codes': [int(c) for c in codes],
                      'text': ''.join(charmap.get(str(c & 0x3F), '?') for c in codes)})
        if b == 0xFE:
            break
    return lines


if __name__ == '__main__':
    main()
