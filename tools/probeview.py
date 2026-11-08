#!/usr/bin/env python3
"""Změří, **jak originál mění obraz** – roluje se silnice, nebo se skáče po zónách?

    PYTHONPATH=tools/vendor ./tools/probeview.py [--frames N] [--out build/zones]

To je první a nejdůležitější otázka M0b (`MILNIKY.md`): C&VG 47 psalo o „scrolling
3D highway", Crash 20 o „one complete section of road at a time" a rozhodnout to
musí měření, ne recenze. Nástroj pustí režim `6 DEMONSTRATION` – attract mode
originálu, který si silnici projede sám – a snímek po snímku měří:

* kolik bajtů bitmapy hrací plochy se za snímek změnilo,
* kolik atributů hrací plochy je vynulovaných (tím hra maže obraz),
* jestli se obraz dá vysvětlit **posunem** o (dx, dy) – korelace přes celou
  hrací plochu pro posuny do ±24 px.

Pro každou zónu uloží obrazovku (PNG + `.scr`) do `--out`; to jsou referenční
obrázky pro `matchscreen.py` (M2) – kreslí je originál, ne remake.
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

import highwaylib as H                                          # noqa: E402
from scr2png import scr_to_rgb, write_png                        # noqa: E402

W, HGT = 256, H.PLAY_ROWS * 8       # hrací plocha 256 × 152


def to_bits(bitmap):
    return [[(bitmap[y*32 + x//8] >> (7 - x % 8)) & 1 for x in range(W)]
            for y in range(HGT)]


def best_shifts(a, b, rng=24, step=2, top=5):
    """Nejlepší posuny (shoda, dx, dy) – `a` posunuté o (dx, dy) proti `b`."""
    out = []
    for dy in range(-rng, rng+1):
        for dx in range(-rng, rng+1):
            same = tot = 0
            for y in range(0, HGT, step):
                yy = y + dy
                if not 0 <= yy < HGT:
                    continue
                ra, rb = a[y], b[yy]
                for x in range(0, W, step):
                    xx = x + dx
                    if 0 <= xx < W:
                        tot += 1
                        same += ra[x] == rb[xx]
            if tot > (HGT//step) * (W//step) * 0.6:
                out.append((same/tot, dx, dy))
    out.sort(reverse=True)
    return out[:top]


def save_shot(path, scr):
    write_png(path + '.png', scr_to_rgb(scr), 256)
    with open(path + '.scr', 'wb') as f:
        f.write(scr)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--frames', type=int, default=4000, help='kolik snímků demo odsimulovat')
    ap.add_argument('--out', default=os.path.join(H.ROOT, 'build/zones'),
                    help='kam ukládat obrazovky zón')
    ap.add_argument('--shift-frames', type=int, default=4,
                    help='u kolika největších změn zkusit korelaci posunu')
    ap.add_argument('--mode', choices=('demo', 'player'), default='demo',
                    help="demo = attract mode originálu (projede celou silnici), "
                         "player = rozehraná hra s drženou '1' FAST")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    if args.mode == 'demo':
        s = H.demo()
        keys = ()
    else:
        s = H.gameplay()
        keys = ('1',)   # FAST
    prev_bm = s.play_area()[0]
    prev_scr = s.screen()
    frames = []                 # (snímek, změna bitmapy, počet nulových atributů)
    blanks = []                 # snímky s vynulovanou hrací plochou
    shots = []                  # (snímek, obrazovka) po každém přechodu
    hold = []                   # (změna, snímek, bitmapa před, bitmapa po)
    in_blank = False

    for _ in range(args.frames):
        for k in keys:
            s.hold(k, 3)
        s.run(1)
        bm, at = s.play_area()
        zeros = sum(1 for a in at if a == 0)
        diff = sum(1 for x, y in zip(bm, prev_bm) if x != y)
        frames.append((s.frame, diff, zeros))
        if zeros > 500:
            in_blank = True
            blanks.append(s.frame)
        elif in_blank:
            in_blank = False
            shots.append((s.frame, s.screen()))
        hold.append((diff, s.frame, prev_bm, bm))
        prev_bm, prev_scr = bm, s.screen()

    total = len(frames)
    diffs = sorted((d for _, d, _ in frames), reverse=True)
    print('%s: %d snímků od snímku %d' % (args.mode, total, frames[0][0]))
    print('změna bitmapy hrací plochy za snímek: medián %d B, 99. percentil %d B, '
          'maximum %d B ze %d B'
          % (diffs[total//2], diffs[total//100], diffs[0], H.PLAY_ROWS*8*32))

    # přechody: hra vynuluje atributy hrací plochy na jeden až dva snímky
    runs = []
    for f in blanks:
        if runs and f == runs[-1][1] + 1:
            runs[-1][1] = f
        else:
            runs.append([f, f])
    print('přechodů (vynulované atributy hrací plochy): %d' % len(runs))
    if runs:
        lens = [b-a+1 for a, b in runs]
        gaps = [runs[i+1][0]-runs[i][0] for i in range(len(runs)-1)]
        print('  délka přechodu: %d–%d snímků' % (min(lens), max(lens)))
        if gaps:
            print('  rozestup přechodů: %d–%d snímků (medián %d)'
                  % (min(gaps), max(gaps), sorted(gaps)[len(gaps)//2]))

    # dá se největší změna vysvětlit posunem obrazu?
    hold.sort(key=lambda t: -t[0])
    print('korelace posunu u největších změn (shoda, dx, dy):')
    for diff, frame, a, b in hold[:args.shift_frames]:
        got = best_shifts(to_bits(a), to_bits(b))
        print('  snímek %5d, změna %4d B: %s'
              % (frame, diff, ', '.join('%.3f@(%+d,%+d)' % (r, dx, dy) for r, dx, dy in got)))

    for n, (frame, scr) in enumerate(shots):
        save_shot(os.path.join(args.out, 'zone%02d_f%05d' % (n, frame)), scr)
    print('uloženo %d obrazovek zón do %s' % (len(shots), os.path.relpath(args.out, H.ROOT)))


if __name__ == '__main__':
    main()
