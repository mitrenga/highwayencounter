#!/usr/bin/env python3
"""Krokovatelný běh originálu v simulátoru – **základ všech extrakčních nástrojů**.

U Underwurlde tuhle roli hraje `roomlib.py`: nabootuje hru a nechá **originál
samotný** vykreslit libovolnou místnost. Highway Encounter nemá místnosti, ale
souvislou silnici, takže tady jde o totéž s kamerou: dojet hru do rozehraného
stavu a pak ji **krokovat po snímcích**, mezi snímky si číst paměť a mačkat
klávesy. Nic se nesimuluje po svém – kreslí originál.

Použití:

    import highwaylib
    s = highwaylib.gameplay()          # nabootuje (nebo vezme z cache)
    s.hold('1', 100)                   # FAST na 100 snímků
    s.run(100)                         # odsimuluje 100 snímků
    scr = s.screen()                   # 6912 B videopaměti
    b   = s.peek(0x91A4)               # čas z POKE

Boot je drahý (~900 snímků), takže se stav rozehrané hry ukládá do
`build/gameplay.z80` a příště se jen načte; `--rebuild` cache zahodí.

Spouštět s `PYTHONPATH=tools/vendor` (vendorovaný SkoolKit, viz tools/README.md).
"""
import contextlib, io, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)

from skoolkit.simulator import Simulator                         # noqa: E402
from skoolkit.simutils import from_snapshot, get_state, PC, T    # noqa: E402
from skoolkit.snapshot import Snapshot, write_snapshot           # noqa: E402
from skoolkit.trace import Tracer                                # noqa: E402
try:
    from skoolkit.csimulator import CSimulator
except ImportError:                                              # pragma: no cover
    CSimulator = None

ROOT = os.path.normpath(os.path.join(HERE, '..'))
SNAPSHOT = os.path.join(ROOT, 'build/highwayencounter.z80')
CACHE = os.path.join(ROOT, 'build/gameplay.z80')

# půlřádek klávesnice -> index v poli keyboard[] simulátoru (bit A8..A15 portu $xxFE)
ROWS = {'$FEFE': 0, '$FDFE': 1, '$FBFE': 2, '$F7FE': 3,
        '$EFFE': 4, '$DFFE': 5, '$BFFE': 6, '$7FFE': 7}
KEYS = {  # klávesa -> (půlřádek, bit)
    'CAPS': ('$FEFE', 0), 'Z': ('$FEFE', 1), 'X': ('$FEFE', 2), 'C': ('$FEFE', 3), 'V': ('$FEFE', 4),
    'A': ('$FDFE', 0), 'S': ('$FDFE', 1), 'D': ('$FDFE', 2), 'F': ('$FDFE', 3), 'G': ('$FDFE', 4),
    'Q': ('$FBFE', 0), 'W': ('$FBFE', 1), 'E': ('$FBFE', 2), 'R': ('$FBFE', 3), 'T': ('$FBFE', 4),
    'P': ('$DFFE', 0), 'O': ('$DFFE', 1), 'I': ('$DFFE', 2), 'U': ('$DFFE', 3), 'Y': ('$DFFE', 4),
    'L': ('$BFFE', 1), 'K': ('$BFFE', 2), 'J': ('$BFFE', 3), 'H': ('$BFFE', 4),
    '1': ('$F7FE', 0), '2': ('$F7FE', 1), '3': ('$F7FE', 2), '4': ('$F7FE', 3), '5': ('$F7FE', 4),
    '0': ('$EFFE', 0), '9': ('$EFFE', 1), '8': ('$EFFE', 2), '7': ('$EFFE', 3), '6': ('$EFFE', 4),
    'ENTER': ('$BFFE', 0),
    'SPACE': ('$7FFE', 0), 'SYMSHIFT': ('$7FFE', 1), 'M': ('$7FFE', 2), 'N': ('$7FFE', 3), 'B': ('$7FFE', 4),
}

# hrací plocha jsou znakové řádky 0-18, panel 19-23 (sources/docs/screen_layout.md)
PLAY_ROWS = 19
BOOT_SCRIPT = [  # (od snímku, do snímku, klávesa) – menu OPTIONS
    (400, 440, '1'),    # 1 KEYBOARD
    (500, 540, '7'),    # 7 START GAME
]
DEMO_SCRIPT = [  # totéž, ale `6 DEMONSTRATION` – hru hraje sama, projede celou silnici
    (400, 440, '1'),
    (500, 540, '6'),
]
BOOT_FRAMES = 900       # ve snímku 899 už hra běží (disasm_notes.md §5)

# --- adresy odměřené v běžící hře (sources/docs/disasm_notes.md §11-§13) -----
STEP_PC = 0x985A        # vykoná se právě jednou za průchod hlavní smyčkou
STEP_TIMEOUT = 20       # kolik snímků nejvýš čekat na STEP_PC
ENTITIES = 0x8A00       # tabulka objektů, 16 B na záznam; nultý je řízený Vorton
ENTITY_SIZE = 16
KEYS_READ = 0x8F14      # co hra ten krok přečetla z klávesnice (bitová maska)
TURN_PHASE = 0x8F13     # střídavá 0/2; otáčí se jen v krocích, kde je 2
HIT_FLAG = 0x8F15       # $10 v krocích, kdy hra hlásí náraz (a bere rychlost)
HIT_MASK = 0x10
THRUST_TIMER = 0x8F1D   # posuvný registr plynu: $FF, pak >>1 každý krok
KEY_FIRE, KEY_ACCEL, KEY_DECEL, KEY_RIGHT, KEY_LEFT = 1, 2, 4, 8, 16


class Session:
    """Jeden běh hry, který se dá krokovat po snímcích a číst mu do paměti."""

    def __init__(self, snapshot_path=SNAPSHOT):
        snapshot = Snapshot.get(snapshot_path)
        if snapshot is None:
            raise SystemExit('nelze nacist snapshot %s' % snapshot_path)
        cls = CSimulator or Simulator
        self.simulator = from_snapshot(cls, snapshot, {}, {'ay': [None]*16},
                                       {'fast_djnz': False, 'fast_ldir': False}, None)
        self.tracer = Tracer(self.simulator, snapshot.border, snapshot.out7ffd,
                             snapshot.outfffd, list(snapshot.ay), snapshot.outfe, True)
        self.simulator.set_tracer(self.tracer)
        self._start_pc = snapshot.pc
        self._started = False
        self._holds = {}        # klávesa -> do kterého snímku (absolutně) držet
        self._scr = None
        self.frame = self.simulator.registers[T] // self.simulator.frame_duration

    # --- klávesy ---------------------------------------------------------
    def hold(self, key, frames=6):
        """Držet klávesu následujících `frames` snímků."""
        if key not in KEYS:
            raise ValueError('neznama klavesa %r' % key)
        self._holds[key] = max(self._holds.get(key, 0), self.frame + frames)

    def release(self, key=None):
        if key is None:
            self._holds.clear()
        else:
            self._holds.pop(key, None)

    def tap(self, key, frames=6, gap=6):
        """Stisk a uvolnění – hra po volbě čeká na uvolnění klávesy (§4 notes)."""
        self.hold(key, frames)
        self.run(frames + gap)

    def _keyboard(self, keyboard):
        for i in range(8):
            keyboard[i] = 0
        for key, until in list(self._holds.items()):
            if until <= self.frame:
                del self._holds[key]
                continue
            row, bit = KEYS[key]
            keyboard[ROWS[row]] |= 1 << bit

    # --- běh -------------------------------------------------------------
    def run(self, frames=1, watch=None, script=()):
        """Odsimuluje `frames` snímků, po jednom.

        `watch(session, frame)` se volá po každém snímku – když vrátí False,
        běh se zastaví dřív. `script` je seznam `(od, do, klávesa)` v absolutních
        snímcích, jako `BOOT_SCRIPT`.
        """
        for _ in range(frames):
            self._step(script)
            if watch is not None and watch(self, self.frame) is False:
                return False
        return True

    def _step(self, script=()):
        """Jeden snímek. Zastavuje se **v polovině snímku**, ne na jeho hranici.

        Simulátor se dá přerušit jen v obslužné rutině `draw`, tedy hned po
        přijetí přerušení – a když se z takového místa pokračuje, hra si to
        rozhodí: naměřeno, že se pak vůbec nedostane ke kreslicí rutině
        (`$9915`, `$99D1`…) a obrazovka zůstane stát, i když všechno ostatní
        v RAM běží. Krokuje se proto na T-stavy: doběhne se doprostřed dalšího
        snímku, kde je pauza pro hru neškodná, a `draw` se používá jen na
        klávesnici. Rozdíl je měřitelný – `probeview.py` s tímhle krokováním
        dává tytéž výsledky jako běh bez krokování.
        """
        sim = self.simulator
        fd = sim.frame_duration
        t0 = sim.registers[T]
        max_t = (t0 // fd + 1) * fd + fd // 2 - t0

        def draw(scr, frame, border, keyboard):
            self.frame = frame
            self._scr = scr
            for start, end, key in script:
                if start <= frame < end:
                    self.hold(key, 1)
            self._keyboard(keyboard)
            return True

        pc = self._start_pc if not self._started else sim.registers[PC]
        self._started = True
        with contextlib.redirect_stdout(io.StringIO()):
            self.tracer.run(pc, -1, 0, max_t, True, draw, None, None, None, '$', '04X', '04X')
        self.frame = sim.registers[T] // fd

    # --- krokování po krocích herní smyčky --------------------------------
    def step(self, keys=()):
        """Odsimuluje **jeden průchod hlavní herní smyčkou** a drží u toho `keys`.

        Hlavní smyčka hry **není svázaná se snímkem**: jeden průchod trvá
        165 000–245 000 T-stavů (2,4–3,5 snímku) a jeho délka kolísá podle
        toho, kolik je co kreslit (`disasm_notes.md` §11). Krokovat po snímcích
        proto k měření fyziky nestačí – stav se mění jednou za průchod, ne
        jednou za snímek. Zastavuje se na `STEP_PC`, adrese, která se
        v každém průchodu vykoná právě jednou.

        Vrací počet T-stavů, které průchod trval. Vyhodí `RuntimeError`, když
        se na `STEP_PC` nedojde – tak se pozná `H` (HOLD), kterou se hra
        zastaví, i konec hry.
        """
        sim = self.simulator
        t0 = sim.registers[T]
        self._step_keys = tuple(keys)

        def draw(scr, frame, border, keyboard):
            self.frame = frame
            self._scr = scr
            for i in range(8):
                keyboard[i] = 0
            for key in self._step_keys:
                row, bit = KEYS[key]
                keyboard[ROWS[row]] |= 1 << bit
            return True

        pc = self._start_pc if not self._started else sim.registers[PC]
        self._started = True
        with contextlib.redirect_stdout(io.StringIO()):
            self.tracer.run(pc, STEP_PC, 0, sim.frame_duration * STEP_TIMEOUT,
                            True, draw, None, None, None, '$', '04X', '04X')
        self.frame = sim.registers[T] // sim.frame_duration
        if sim.registers[PC] != STEP_PC:
            raise RuntimeError('herní smyčka nedošla na $%04X (PC=$%04X) – '
                               'zastavená hra (HOLD), nebo konec hry'
                               % (STEP_PC, sim.registers[PC]))
        return sim.registers[T] - t0

    def run_to(self, addr, frames=200, keys=()):
        """Doběhne na adresu `addr` (nejvýš `frames` snímků) a vrátí, kolik
        T-stavů to trvalo, nebo `None`, když se tam nedošlo.

        Koncová sekvence (M7) se po krocích herní smyčky krokovat nedá: kus
        jejího scénáře (rozpad lodi, prodleva) se do smyčky vůbec nevrací,
        takže by `step()` hlásil konec hry. Měří se proto tak, že se doběhne
        na adresu, kterou hra vykoná na hranici jedné a druhé části scénáře,
        a čte se čas mezi nimi (`disasm_notes.md` §17)."""
        sim = self.simulator
        t0 = sim.registers[T]
        self._step_keys = tuple(keys)

        def draw(scr, frame, border, keyboard):
            self.frame = frame
            self._scr = scr
            for i in range(8):
                keyboard[i] = 0
            for key in self._step_keys:
                row, bit = KEYS[key]
                keyboard[ROWS[row]] |= 1 << bit
            return True

        pc = self._start_pc if not self._started else sim.registers[PC]
        self._started = True
        with contextlib.redirect_stdout(io.StringIO()):
            self.tracer.run(pc, addr, 0, sim.frame_duration * frames,
                            True, draw, None, None, None, '$', '04X', '04X')
        self.frame = sim.registers[T] // sim.frame_duration
        if sim.registers[PC] != addr:
            return None
        return sim.registers[T] - t0

    def entity(self, index=0):
        """Jeden záznam tabulky objektů na `$8A00` jako slovník (§12 notes)."""
        a = ENTITIES + index * ENTITY_SIZE
        e = self.simulator.memory[a:a + ENTITY_SIZE]
        return {'x': e[0], 'y': e[1] | (e[2] << 8),
                'cls': e[5] | (e[6] << 8), 'dir': e[7], 'speed': e[8],
                'phase': e[9], 'kind': e[10], 'raw': bytes(e)}

    def player(self):
        """Řízený Vorton je nultý záznam tabulky."""
        p = self.entity(0)
        p['keys'] = self.peek(KEYS_READ)
        p['turnPhase'] = self.peek(TURN_PHASE)
        p['timer'] = self.peek(THRUST_TIMER)
        p['hit'] = bool(self.peek(HIT_FLAG) & HIT_MASK)
        return p

    # --- čtení ------------------------------------------------------------
    def screen(self):
        """Videopaměť $4000-$5AFF (6912 B) na konci posledního snímku."""
        return bytes(self.simulator.memory[0x4000:0x5B00])

    def play_area(self):
        """Jen hrací plocha: bitmapa řádků 0-18 a jejich atributy."""
        scr = self.screen()
        bitmap = bytearray()
        for y in range(PLAY_ROWS * 8):
            third, line, row = y // 64, y % 8, (y % 64) // 8
            a = third*2048 + line*256 + row*32
            bitmap += scr[a:a+32]
        return bytes(bitmap), scr[6144:6144 + PLAY_ROWS*32]

    def blanked(self, limit=500):
        """Má hrací plocha vynulované atributy? Tím hra maže obraz při přechodu
        do další zóny (disasm_notes.md §7), takže je to detektor přechodu."""
        attrs = self.screen()[6144:6144 + PLAY_ROWS*32]
        return sum(1 for a in attrs if a == 0) > limit

    def peek(self, addr, n=None):
        if n is None:
            return self.simulator.memory[addr]
        return bytes(self.simulator.memory[addr:addr+n])

    def ram(self):
        return bytes(self.simulator.memory[0x4000:])

    # --- cache ------------------------------------------------------------
    def save(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        ram, registers, state, machine = get_state(self.simulator)
        write_snapshot(path, ram, registers, state, machine)
        return path


def boot(snapshot_path=SNAPSHOT, frames=BOOT_FRAMES, watch=None):
    """Nabootuje hru z kazetového snapshotu přes menu OPTIONS do rozehrané hry."""
    s = Session(snapshot_path)
    s.run(frames, watch=watch, script=BOOT_SCRIPT)
    return s


def demo(snapshot_path=SNAPSHOT, frames=BOOT_FRAMES):
    """Nabootuje hru do režimu `6 DEMONSTRATION` – attract mode originálu, který
    si silnici projede sám. Zdroj scénářů, dokud není `playrzx.py` (M0)."""
    s = Session(snapshot_path)
    s.run(frames, script=DEMO_SCRIPT)
    return s


def gameplay(cache=CACHE, rebuild=False, snapshot_path=SNAPSHOT):
    """Rozehraná hra – z cache, nebo nabootuje a cache vyrobí."""
    if rebuild or not os.path.isfile(cache):
        s = boot(snapshot_path)
        s.save(cache)
        return s
    return Session(cache)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rebuild', action='store_true', help='zahodit cache a nabootovat znovu')
    ap.add_argument('--frames', type=int, default=0, help='kolik snímků ještě odsimulovat')
    ap.add_argument('--scr', help='kam uložit .scr po dosimulování')
    args = ap.parse_args()

    s = gameplay(rebuild=args.rebuild)
    print('rozehrana hra: snimek %d, PC $%04X, cache %s'
          % (s.frame, s.simulator.registers[PC], os.path.relpath(CACHE, ROOT)))
    if args.frames:
        s.run(args.frames)
        print('po %d snimcich: snimek %d' % (args.frames, s.frame))
    if args.scr:
        with open(args.scr, 'wb') as f:
            f.write(s.screen())
        print('%s: obrazovka' % args.scr)


if __name__ == '__main__':
    main()
