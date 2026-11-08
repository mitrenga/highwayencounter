#!/usr/bin/env python3
"""Zaznamená **hrací plochu originálu** i stav, ze kterého vznikla → `build/vtraces/`.

Podklad pro `tools/matchscreen.js`, který týmž stavem nechá vykreslit plochu
remaku (`app/screenComposer.js`) a porovná ji s originálem **bajt po bajtu včetně
atributů**.

V každém průchodu se zastaví na `$9AD8`, tedy hned za blitem bufferu na
obrazovku (§8) – v tu chvíli je na obrazovce hotový snímek – a uloží:

* obraz hrací plochy a jejích 608 atributů, jak je má originál;
* celou tabulku objektů (`$8A00`, po 16 bajtech, do `$FF`), ať si remake sám
  rozhodne, co je vidět a v jakém pořadí to kreslí;
* kameru `w($8F09)`, číslo zóny a **animační bajty** `$8F00 + druh`, aby se
  testovalo kreslení, ne to, jak si remake animaci odpočítává.

    PYTHONPATH=tools/vendor ./tools/tracescreen.py [--passes 120]
        [--mode demo|player] [--out build/vtraces]
"""
import argparse, base64, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib                                                # noqa: E402

BLITTED_PC = 0x9AD8     # hned za blitem bufferu na obrazovku
ENTITIES = 0x8A00
ENTITY_SIZE = 16
CAMERA = 0x8F09
ZONE_COUNTER = 0x8F00
ANIM = 0x8F00
KINDS = range(0x0D, 0x14)
ZONES = 31


def records(memory):
    """Celá tabulka objektů, jak ji originál má – včetně prázdných míst."""
    out = []
    index = 0
    while index < 256:
        record = bytes(memory[ENTITIES + index*ENTITY_SIZE:
                              ENTITIES + (index+1)*ENTITY_SIZE])
        if record[0] == 0xFF:
            break
        out.append({'x': record[0], 'y': record[1] | record[2] << 8,
                    'cls': record[5] | record[6] << 8, 'dir': record[7],
                    'speed': record[8], 'phase': record[9], 'kind': record[10],
                    'empty': record[0] == 0xFE})
        index += 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--passes', type=int, default=120)
    ap.add_argument('--mode', choices=('demo', 'player'), default='demo')
    ap.add_argument('--out', default=os.path.join(HERE, '..', 'build/vtraces'))
    args = ap.parse_args()

    session = (highwaylib.demo() if args.mode == 'demo'
               else highwaylib.gameplay())
    keys = () if args.mode == 'demo' else ('1',)
    memory = session.simulator.memory
    os.makedirs(args.out, exist_ok=True)

    # Začíná se **na hranici zóny**: kdo se do zóny přidá až uprostřed, nemůže
    # vědět, které stojící objekty do ní originál nakreslil při vstupu (§8),
    # a rozdíl by pak nebyl o kreslení, ale o tom, kde se záznam začal.
    zone_at_start = memory[ZONE_COUNTER]
    while True:
        if session.run_to(BLITTED_PC, frames=60, keys=keys) is None:
            raise SystemExit('nedoslo se na prechod zony')
        if memory[ZONE_COUNTER] != zone_at_start:
            break

    frames = []
    while len(frames) < args.passes:
        bitmap, attributes = session.play_area()
        frames.append({
            'pass': len(frames),
            'frame': session.frame,
            'zone': ZONES - memory[ZONE_COUNTER],
            'cam': memory[CAMERA] | memory[CAMERA+1] << 8,
            'anim': {str(kind): memory[ANIM + kind] for kind in KINDS},
            'records': records(memory),
            'bitmap': base64.b64encode(bytes(bitmap)).decode('ascii'),
            'attributes': base64.b64encode(bytes(attributes)).decode('ascii'),
        })
        if session.run_to(BLITTED_PC, frames=60, keys=keys) is None:
            break

    path = os.path.join(args.out, 'screen-%s.json' % args.mode)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'note': 'hrací plocha originálu a stav, ze kterého vznikla '
                           '(tools/tracescreen.py); čteno na $%04X, hned za '
                           'blitem bufferu na obrazovku' % BLITTED_PC,
                   'mode': args.mode, 'passes': len(frames),
                   'frames': frames}, f, ensure_ascii=False)
        f.write('\n')
    print('%s: %d pruchodu, zony %s'
          % (os.path.relpath(path, highwaylib.ROOT), len(frames),
             '-'.join(str(v) for v in (min((f['zone'] for f in frames), default=0),
                                       max((f['zone'] for f in frames), default=0)))))


if __name__ == '__main__':
    main()
