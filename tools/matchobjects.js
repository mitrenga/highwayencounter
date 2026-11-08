#!/usr/bin/env node
/**
 * Přehraje `app/highwayObjects.js` proti nahranému běhu originálu (M4).
 *
 *   ./tools/matchobjects.js [--scenario jmeno] [--verbose] [--traces build/otraces]
 *
 * Obdoba `matchphysics.js` z M3, jenže tam se porovnával jeden Vorton; tady
 * **celá silnice**: hráč, výstřely a všechny předměty, které na ní stojí.
 * Do portu jdou tytéž klávesy, jaké ten krok přečetla hra, a po každém kroku se
 * porovnává pozice, směr, rychlost i fáze animace každého objektu, který port
 * simuluje. Cíl je **nula rozdílů**.
 *
 * Co si port bere ze záznamu, a co se počítá a hlásí:
 *
 * * **konvoj a nepřátelé** ($1070 automatický Vorton, $0910 Lasertron,
 *   $0228 nepřítel). Jejich pohyb je M5 a M6; port je jen potřebuje mít na
 *   správném místě, aby se do nich dalo narazit, tak se každý krok přepíšou
 *   podle originálu.
 * * **objekty, které se v tabulce objeví** – při přechodu zóny originál
 *   natáhne obsah nové zóny z dat silnice. Kde ta data leží, se zatím neví
 *   (M2, `disasm_notes.md` §7), takže se nový obsah vezme ze záznamu.
 *
 * Nic jiného se neradí: srážky, strkání, dojezd, výstřely i to, kdy se přepne
 * zóna, musí port trefit sám.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const loadClassicScript = require(path.join(__dirname, '../app/svision/tools/classicScript.cjs'));

const ROOT = path.join(__dirname, '..');
global.VortonPhysics = loadClassicScript(path.join(ROOT, 'app/vortonPhysics.js'));
const VortonPhysics = global.VortonPhysics;
const HighwayWorld = loadClassicScript(path.join(ROOT, 'app/highwayObjects.js'));

const FIELDS = ['x', 'y', 'dir', 'speed', 'phase'];
// Co port simuluje, je hráč, výstřel a věci na silnici (druhy změřené v
// data/objects.json jako ty, které se samy nehýbou). Všechno ostatní – konvoj,
// Lasertron a nepřátelé – se hýbe podle pravidel M5 a M6; port o nich musí
// vědět, aby se do nich dalo narazit, ale nesimuluje je, takže se každý krok
// přepíšou podle originálu a každé takové přepsání se počítá.
function foreignClass(objects, cls) {
  return cls !== 0 && cls !== objects.shot['class']
      && objects.push.objectClasses.indexOf(cls) < 0;
}
// rychlost s horním bitem není rychlost: objekt je zničený a jeho druh se
// posouvá po tabulce animace (tools/dumpobjects.py)
const MAX_SPEED = 4;

function parseArgs(argv) {
  const args = {traces: path.join(ROOT, 'build/otraces'), scenario: null,
                verbose: false};
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--verbose') { args.verbose = true; }
    else if (argv[i] === '--scenario') { args.scenario = argv[++i]; }
    else if (argv[i] === '--traces') { args.traces = argv[++i]; }
    else { throw new Error('neznámý argument '+argv[i]); }
  }
  return args;
}

/** Záznam originálu `[slot, x, y, dir, speed, phase, cls, kind]` jako objekt. */
function toEntity(row) {
  return {x: row[1], y: row[2], dir: row[3], speed: row[4], phase: row[5],
          cls: row[6], kind: row[7]};
}

function bySlot(list) {
  const map = new Map();
  for (const row of list) { map.set(row[0], toEntity(row)); }
  return map;
}

function checkTrace(objects, physics, trace, verbose) {
  const world = new HighwayWorld(objects, physics);
  const start = bySlot(trace.start.ents);
  for (const [slot, e] of start) { world.put(slot, e); }
  const player0 = world.player();
  if (player0) {
    player0.timer = trace.start.globals.timer;
    player0.turnPhase = trace.start.globals.turnPhase;
  }
  world.zone = trace.start.globals.zone;

  const diffs = [];
  let hints = 0, seeded = 0, steps = 0, died = -1;
  let zone = trace.start.globals.zone;
  for (let i = 0; i < trace.steps.length; i++) {
    const want = bySlot(trace.steps[i].ents);
    // Konvoj a nepřátelé: port je nesimuluje, ale **na jejich řadě v tabulce**
    // je potřeba mít je tam, kde je originál po tomhle průchodu má – objekt
    // o slot níž je vidí ještě na starém místě, o slot výš už na novém, a na
    // tom záleží.
    const adopt = (slot, entity) => {
      const ref = want.get(slot);
      if (ref) {
        entity.x = ref.x; entity.y = ref.y; entity.dir = ref.dir;
        entity.speed = ref.speed; entity.phase = ref.phase;
        hints++;
      }
    };
    // Zničený Vorton (druh se posune po tabulce animace zániku, rychlost má
    // horní bit) je M6, ne M4: tam záznam pro tenhle port končí.
    const me = want.get(HighwayWorld.PLAYER);
    if (!me || me.cls !== 0 || me.speed > MAX_SPEED) { died = i; break; }
    steps++;
    world.step(trace.steps[i].in, adopt);

    // Přechod zóny: originál natáhne celý obsah nové zóny z dat silnice, a ta
    // data se zatím nenašla (M2). Port tedy dostane novou zónu ze záznamu –
    // celou, ne jen sloty, kde se změnil druh objektu.
    const newZone = trace.steps[i].zone !== zone;
    zone = trace.steps[i].zone;

    for (let slot = 0; slot < HighwayWorld.SLOTS; slot++) {
      const got = world.entities[slot];
      const ref = want.get(slot);
      const foreign = (ref && foreignClass(objects, ref.cls))
                   || (got && foreignClass(objects, got.cls));
      const dead = (ref && ref.speed > MAX_SPEED) || (got && got.speed > MAX_SPEED);
      // Řízený Vorton se nikdy nepřepisuje celý: nese si stav plynu ($8F1D)
      // a střídavý příznak otáčení ($8F13), které v tabulce objektů nejsou,
      // takže by se s ním zahodily. Opravují se u něj jen porovnávaná pole.
      const isPlayer = slot === HighwayWorld.PLAYER;
      if (!isPlayer && (foreign || dead)) {
        // M5/M6, nebo zničený objekt v animaci zániku – přepsat a jít dál
        world.put(slot, ref || null);
        if (ref) { hints++; }
        continue;
      }
      if (!isPlayer && ref && (newZone || !got || got.cls !== ref.cls)) {
        // nový obsah zóny z dat silnice (M2) – vzít ze záznamu
        world.put(slot, ref);
        seeded++;
        continue;
      }
      if (!ref && got && !isPlayer) {
        if (world.isShot(got) && !newZone) {
          diffs.push({step: i, slot: slot, field: 'výstřel', got: 'letí',
                      want: 'zanikl'});
        }
        world.put(slot, null);
        continue;
      }
      if (!ref || !got) { continue; }
      for (const f of FIELDS) {
        if (got[f] !== ref[f]) {
          diffs.push({step: i, slot: slot, field: f, got: got[f], want: ref[f],
                      cls: ref.cls, keys: trace.steps[i].in});
          got[f] = ref[f];      // srovnat, ať se rozdíly nemnoží z jednoho kořene
        }
      }
    }
    if (world.zone !== trace.steps[i].zone) {
      diffs.push({step: i, slot: -1, field: 'zóna', got: world.zone,
                  want: trace.steps[i].zone});
      world.zone = trace.steps[i].zone;
    }
  }
  if (verbose && diffs.length) {
    for (const d of diffs.slice(0, 20)) {
      console.log('   krok '+d.step+' slot '+d.slot
                  +(d.cls === undefined ? '' : ' ($'+d.cls.toString(16).toUpperCase()+')')
                  +' '+d.field+': port '+d.got+', originál '+d.want);
    }
  }
  return {diffs, hints, seeded, steps, died};
}

function main() {
  const args = parseArgs(process.argv);
  for (const f of ['data/objects.json', 'data/physics.json']) {
    if (!fs.existsSync(path.join(ROOT, f))) {
      console.error('chybí '+f+' – spusť tools/dumpobjects.py');
      process.exit(2);
    }
  }
  const objects = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/objects.json'), 'utf8'));
  const physics = new VortonPhysics(
    JSON.parse(fs.readFileSync(path.join(ROOT, 'data/physics.json'), 'utf8')));

  const indexPath = path.join(args.traces, 'index.json');
  if (!fs.existsSync(indexPath)) {
    console.error('chybí %s – spusť tools/traceobjects.py', indexPath);
    process.exit(2);
  }
  const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));

  let steps = 0, bad = 0, hints = 0, seeded = 0, scenarios = 0;
  for (const entry of index) {
    if (args.scenario && args.scenario !== entry.name) { continue; }
    const trace = JSON.parse(
      fs.readFileSync(path.join(args.traces, entry.name+'.json'), 'utf8'));
    const result = checkTrace(objects, physics, trace, args.verbose);
    scenarios++;
    steps += result.steps;
    bad += result.diffs.length;
    hints += result.hints;
    seeded += result.seeded;
    console.log((result.diffs.length ? '✗ ' : '✓ ')+entry.name.padEnd(12)
                +String(result.steps).padStart(4)+' kroků, '
                +String(result.diffs.length).padStart(4)+' rozdílů, '
                +result.seeded+'× obsah zóny ze záznamu (M2)'
                +(result.died >= 0 ? ', konec: Vorton zničen (M6)' : '')
                +' — '+entry.note);
  }
  console.log('\n'+scenarios+' scénářů, '+steps+' kroků, **'+bad+' rozdílů**; '
              +hints+'× stav konvoje a nepřátel (M5/M6) a '+seeded
              +'× obsah zóny (M2) vzatý ze záznamu');
  process.exit(bad ? 1 : 0);
}

main();
