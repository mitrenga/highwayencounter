HIGHWAY ENCOUNTER
=================
Faithful browser remake of the 1985 Vortex Software ZX Spectrum classic — work in progress.

## About
Written by Costa Panayi and released by Vortex Software in August 1985 for the 48K ZX Spectrum,
Highway Encounter is an isometric strategy/shoot-'em-up: five Vortons have to push the Lasertron
down one long straight road, from Zone 30 to Zone Zero, and blow up the alien stronghold at the
end of it. Its defining idea is the inversion of the usual arcade contract — your spare lives are
not waiting safely at the bottom of the screen, they are out on the road with you, pushing the
bomb forward on their own, and they can all be destroyed before you ever get to play them. The
game keeps running off-screen, so clearing the way ahead and coming back for the convoy is the
whole game.

The original game logic is being rewritten in JavaScript from the original instructions and a
disassembly of the game (not emulated) — see `ZADANI.md` for the design and `MILNIKY.md` for the
plan. Sibling projects: Underwurlde, Manic Miner, Jet Set Willy (same ZX platform and svision
kernel), Cheeky Mouse, Stinger, Pleiads (arcade platform).

Two things make this one different from its siblings. The world is not a grid of flick-screen
rooms but **one continuous road drawn in isometric projection**, which means depth-sorted
drawing — nothing in the sibling projects does that. And the four automatic Vortons and the
Lasertron are **autonomous agents simulated whether or not the camera is looking at them**.
Both are scheduled early rather than late.

Status: **M2 done bar the contents of the zones** — the game now **draws the
highway**, and draws it to the last pixel (120 passes of a real game against the
original's own screen, attributes included, no differing pixel). Before that,
M8 gave it **sound** and, as it turned out, **scoring**; M9 has since given it
the original's own **cadence**, its controls and everything a release needs
except the release itself, which waits on the contents of the zones.
The controlled Vorton drives exactly as he does in the original
(M3, zero differences over 10 260 recorded passes), the road behaves —
collisions, shoving, the gun and the camera (M4) — the convoy drives itself
whether or not the camera is looking at it (M5), the enemies do too (M6, zero
differences over 17 124 recorded enemy passes), the game can be **finished**
(M7, zero differences over 802 passes of the end sequence), it **sounds
like the original** (M8, zero differences over 3220 flips of the speaker) — and
as of M2 it **looks** like it too, on the play area as well as on the panel.

Sound on this machine is one bit of a port, so it can be measured the way
nothing else in this project can: not approximately, but **T state by T state**.
The game turns out to have no music at all — in the whole 48K image there are
exactly three `OUT ($FE),A` instructions and all three sit inside sound
routines — and five effects, chosen by bits of a request byte the passes of the
main loop set and the end of the pass clears. Two generators make them: one
noise, one tone, twenty instructions apiece, both written out again in Python
and in JavaScript and replayed against the original until every flip of the
speaker landed on the same T state. The menu has a third generator of its own.
The border, measured across 185 322 writes to the port, is black.

Two things fell out of the sound that had been open far longer than M8.

* **The routine M7 had written down as "a flash of colour" is the score.**
  `$A414` does not touch a single attribute: it adds to a six-digit number at
  `$A481`, and the seventh digit — the trailing zero — is painted into the
  panel's picture, which is why every score in this game is a multiple of ten.
  There are four places that pay: **10** for escorting the Lasertron, **250**
  for destroying something, **1000** for finishing. `HIGH` is overwritten at the
  *start* of the next game rather than at the end of the last one, which is
  exactly why no recorded playthrough was ever seen to overwrite it. The digits
  are not set in the character set M7 found, either — the score has a five-byte
  font of its own.
* **`POWER` is the magazine of the gun.** One cell per barrel, empty while that
  barrel's shot is in flight — not the Vorton's energy, which is what the design
  notes had assumed.

The panel can now be assembled from the data files and compared with the
original pixel by pixel: 48 of 60 panels match byte for byte, and the other 12
differ in two cells — a lamp that lights while you escort the Lasertron, whose
rule is read from the code but not yet measured.

**The highway is drawn as of M2**, and it is drawn to the last pixel: 120 passes of a real game
compared against the original's own screen, bitmap and attributes, and **no differing pixel**.

The sprites had resisted every search of memory, and M2 found out why: the game never keeps a
screen cell anywhere, it **composes the play area in a linear buffer at `$E900`** and copies to
the screen only the character cells whose counter is non-zero — which is why a single
instruction in the whole game, `$9ABC`, writes to the play area's video memory. Following that
one instruction gave everything else. The erase background at `$D905`. The four two-pixel shift
variants, done by the routine rather than held as pre-shifted copies. The sprites: **56 frames
of 24x24 pixels**, mask and image three bytes at a time, bottom row first, in one block at
`$B980`. And the projection, which turned out to be readable rather than guessable, because
every record carries the address it draws at: **row `158 - ((d + x) >> 1)`, pixel `d - x + 24`**,
sorted by a depth key of `(d >> 1) + (x >> 1) + 1` and painted from the far end forward — zero
differences over 1217 passes, 31 zones and 8960 records.

The picture of each zone is a photograph, and deliberately so: at the pass that enters a zone
the original paints the whole play area from that background block, objects and all still to
come, so there is exactly one moment when the scenery is on the screen whole and clean. That is
where all 31 zones are taken from. What builds that picture out of the road's own table at
`$7B00` is the one big thing M2 still leaves open — which is why the remake drives down a road
that has the right scenery but holds nothing except the convoy: it does not yet know where the
barrels, the walls and the enemies stand.

No public disassembly of this game exists, so one is being written from scratch; on the other hand there
is a complete RZX recording of the game being finished, which gives a frame-exact reference run
to trace against — and as of M7 that recording is what the ending is measured
from.

## The cadence of the main loop
The game's state changes once per pass of its main loop, and that loop is not
tied to the interrupt: a pass takes anywhere from 1.4 to 13 frames. What made
the length what it was had been open since M3, and M9 found it in the code. At
the end of every pass, at `$9AD8`, sits an **empty delay loop** that runs only
when the pass drew fewer than eight records — and waits the more the less it
drew: 2618 T states per turn, `48 - 6 x records` turns. A governor. The game
pads a poor pass so that it takes about as long as a rich one: between four and
eight drawn records the *work* grows by 73 000 T states and the whole pass by
10 000.

That makes a pass four things added up, and three of them are exact — the
governor, counted off the instructions and checked against the running game to
the T state; the **sound**, which is played synchronously inside the loop and
whose every effect M8 had already measured; and the **repaint** of the play
area, which happens on entering a zone and on losing a Vorton. The fourth, the
work itself, is the one fitted term: 16 366 T states per drawn record and 2182
per live record on the road, seen or not, because the whole road is stepped.

`tools/matchcadence.js` is the one matcher in this project where zero
differences cannot be expected, and it says so: over 3764 recorded passes,
**99.6 % land within half a frame** of where the original put them and 93.4 %
within a quarter. What is left of the error is measured too — it is the number
of character cells a pass actually copies to the screen, and adding it would
cut the deviation by a fifth, which is not worth keeping the original's cell
counters for.

## Controls
The original's own keys — **1** fast, **Q** slow, **O** and **P** to turn,
**SPACE** to fire, **H** to hold and **A** to abort — and the arrow keys as
well. Everything can be remapped from SETTINGS, gamepads are supported (with
the whole game playable without a keyboard), and on a touch screen one half of
the border fires while the other is a joystick that turns on one axis and works
the throttle on the other, because this game needs both thumbs' worth of
control at once.

## Play now
not deployed yet — the road has the right scenery but nothing standing on it
until M2 knows the contents of the zones, and releasing that as 1.0 would mean
releasing a game with no barrels and no walls.

## Requirements
- PHP 8.1+
- nginx
- MySQL / MariaDB
- Node.js + terser, for building the bundle (`npm i -g terser`)
- es-check, for the ES2018 compatibility gate in `svtool verify` (`npm i -g es-check`)
- Python 3 for the tools in `tools/` (no third-party packages; SkoolKit vendored in `tools/vendor/`)

## Data taken from the original
Everything the remake carries is produced by a tool in `tools/` from the original tape or from
the running game — see `tools/README.md` and `data/README.md`. So far: the loading screen off
the tape (verified byte for byte against the block the tape loads into video memory) and the
panel, which the original keeps as a finished picture at $6000 rather than setting in a font;
the measured physics of the Vorton, the rules of the road, the convoy, the enemies and the
game's own collision matrix; the panel's live fields — the ZONE number is photographed for
every one of the 31 values the game shows, because that big segmented number is a picture of
its own rather than type; and, as of M7, the game's **character set**, the script of its
ending and the timing of its intro and its demonstration mode; as of M8, its **sound
routines**, its **scoring**, and the attributes of the play area zone by zone — which confirm
what Crash 20 wrote in words, that the road and the objects on it are black and white and the
colour is out at the sides. As of M2 there are also all **56 sprites** — the whole graphics
block of the game, mask and image together as the original stores them — the **picture of every
one of the 31 zones**, taken at the one pass where the original has it on the screen whole and
objectless, and the **projection** with the depth sort, read out of the addresses the records
carry rather than fitted to them.

## Install
(`~/` below refers to the project root, not your home directory.)
- clone this repository
- clone library repository https://github.com/mitrenga/svision
- check symlink ~/app/svision
- configure nginx (example: ~/config/nginx.conf)
- create path ~/js with permissions 0777
- create database (script: ~/config/createDB.sql)
- create configuration file ~/config/config.php (example: ~/config/config.php.sample)
- build the production bundle: ~/app/svision/tools/svtool build bundle

## Sources
Reference material — the original instructions and inlay, five period reviews in full transcript
(including the Crash 20 Crash Smash and a zone-by-zone walkthrough from Your Spectrum 19),
player tips and POKEs, the screenshot map of the whole highway, the loading screen and a frame
from the running game — lives in `sources/`; see `sources/README.md`. The tape image and the RZX
recording (`sources/tape/`) are outside git; the rest of `sources/` is tracked.

## License
See the [LICENSE](LICENSE) file.
