#!/usr/bin/env node
/**
 * Přehraje **konvoj** portu proti nahranému běhu originálu (M5).
 *
 *   ./tools/matchconvoy.js [--scenario jmeno] [--verbose] [--traces build/ctraces]
 *
 * Obdoba `matchobjects.js` z M4, jenže obráceně: tam se počítal hráč, výstřely
 * a předměty a konvoj se bral ze záznamu; tady se **počítá konvoj** – čtyři
 * automatické Vortony (`$1070`) a Lasertron (`$0910`) – a všechno ostatní se
 * ze záznamu bere. Tak se měří jen to, co M5 přidala: kdyby se počítalo obojí,
 * čísla M5 by nesla i 68 zbylých rozdílů M4 (`disasm_notes.md` §14) a nebylo by
 * poznat, čí jsou.
 *
 * Aby to bylo poctivé, musí být cizí záznamy na svém místě **ve chvíli, kdy na
 * ně v tabulce přijde řada**, ne až po průchodu: řízený Vorton je slot 0, takže
 * konvoj ho vidí už posunutého, kdežto předměty (sloty 6 a výš) ještě na starém
 * místě. Port to umí – `HighwayWorld.step` se na řízeného Vortona ptá zpětným
 * voláním `drive` dřív, než sám cokoli udělá.
 *
 * Co se počítá a hlásí:
 *
 * * **rozdíl** – konvoj je v portu jinde, jinak natočený, jinak rychlý nebo
 *   v jiné fázi animace než v originálu;
 * * **předání řízení** – kolikrát v záznamu zahynul řízený Vorton, a jestli
 *   port převzal týž slot;
 * * **záznamů vzatých z originálu** – hráč, výstřely, předměty a nepřátelé
 *   (M4, M2 a M6), aby bylo vidět, kolik toho tenhle matcher neřeší.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const loadClassicScript = require(path.join(__dirname, '../app/svision/tools/classicScript.cjs'));

const ROOT = path.join(__dirname, '..');
global.VortonPhysics = loadClassicScript(path.join(ROOT, 'app/vortonPhysics.js'));
const VortonPhysics = global.VortonPhysics;
global.HighwayConvoy = loadClassicScript(path.join(ROOT, 'app/highwayConvoy.js'));
const HighwayWorld = loadClassicScript(path.join(ROOT, 'app/highwayObjects.js'));

const FIELDS = ['x', 'y', 'dir', 'speed', 'phase'];
const MAX_SPEED = 4;      // nad tím je horní bit: zničený objekt (M6)

function parseArgs(argv) {
  const args = {traces: path.join(ROOT, 'build/ctraces'), scenario: null,
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

/** Kdo je v záznamu zrovna řízený Vorton (druh 0, živý) – a v kterém slotu. */
function controlledSlot(map) {
  for (const [slot, e] of [...map.entries()].sort((a, b) => a[0]-b[0])) {
    if (e.cls === 0 && e.speed <= MAX_SPEED) { return slot; }
  }
  return -1;
}

function checkTrace(objects, physics, convoyData, trace, verbose) {
  const world = new HighwayWorld(objects, physics, convoyData);
  const start = bySlot(trace.start.ents);
  for (const [slot, e] of start) { world.put(slot, e); }
  world.zone = trace.start.globals.zone;
  world.playerSlot = controlledSlot(start);
  world.controlledSlots = [world.playerSlot];

  const diffs = [];
  let borrowed = 0, handovers = 0, handoverErrors = 0, steps = 0, standing = 0;
  for (let i = 0; i < trace.steps.length; i++) {
    const want = bySlot(trace.steps[i].ents);
    steps++;

    // Řízený Vorton se nepočítá – ten je M3/M4. Port ho dostane rovnou tam,
    // kde ho originál po tomhle průchodu má, a to **dřív, než se pohne konvoj**,
    // protože je v tabulce před ním.
    const drive = (slot, entity) => {
      const ref = want.get(slot);
      if (ref) {
        entity.x = ref.x; entity.y = ref.y; entity.dir = ref.dir;
        entity.speed = ref.speed; entity.phase = ref.phase;
      } else {
        world.entities[slot] = null;
      }
      borrowed++;
      return true;                 // řídím ho já, port ať ho nechá být
    };
    // Nepřátelé (M6) a cokoli dalšího, co port nesimuluje, na své řadě
    const adopt = (slot, entity) => {
      const ref = want.get(slot);
      if (ref) {
        entity.x = ref.x; entity.y = ref.y; entity.dir = ref.dir;
        entity.speed = ref.speed; entity.phase = ref.phase;
        borrowed++;
      }
    };

    world.step(trace.steps[i].in, adopt, drive);

    // předání řízení: v záznamu zahynul řízený Vorton a druh 0 dostal jiný slot
    const refSlot = controlledSlot(want);
    if (refSlot >= 0 && refSlot !== world.playerSlot) {
      handovers++;
      if (world.entities[world.playerSlot]
          && world.entities[world.playerSlot].cls === 0) {
        handoverErrors++;
        diffs.push({step: i, slot: world.playerSlot, field: 'řízení',
                    got: world.playerSlot, want: refSlot});
      }
      world.playerSlot = refSlot;
    } else if (refSlot >= 0 && world.controlledSlots.indexOf(refSlot) >= 0
               && world.controlledSlots[world.controlledSlots.length-1] === refSlot
               && world.controlledSlots.length > 1
               && i > 0 && controlledSlot(bySlot(trace.steps[i-1].ents)) !== refSlot) {
      handovers++;
    }

    for (let slot = 0; slot < HighwayWorld.SLOTS; slot++) {
      const got = world.entities[slot];
      const ref = want.get(slot);
      const ours = (ref && world.convoy.owns(ref.cls))
                || (got && world.convoy.owns(got.cls));
      if (!ours) {
        // hráč, výstřely, předměty, nepřátelé – tenhle matcher je neřeší
        if (slot !== world.playerSlot || ref) { world.put(slot, ref || null); }
        continue;
      }
      if (!ref || !got || ref.cls !== got.cls) {
        diffs.push({step: i, slot: slot, field: 'záznam',
                    got: got ? '$'+got.cls.toString(16).toUpperCase() : 'prázdno',
                    want: ref ? '$'+ref.cls.toString(16).toUpperCase() : 'prázdno'});
        world.put(slot, ref || null);
        continue;
      }
      // Otevřená otázka §15: čelo konvoje v originálu **stojí, i když má před
      // sebou volno**. Port jede – podle změřeného pravidla jet má – a rozdíl
      // je pak v každém dalším průchodu, dokud se srovná. Počítá se zvlášť,
      // aby bylo vidět, kolik rozdílů je tenhle jeden jev a kolik zbytek.
      const before = i > 0 ? bySlot(trace.steps[i-1].ents).get(slot) : start.get(slot);
      const originalStood = before && before.x === ref.x && before.y === ref.y;
      for (const f of FIELDS) {
        if (got[f] !== ref[f]) {
          if (originalStood) { standing++; }
          diffs.push({step: i, slot: slot, field: f, got: got[f], want: ref[f],
                      cls: ref.cls, standing: !!originalStood});
          got[f] = ref[f];    // srovnat, ať se rozdíly nemnoží z jednoho kořene
        }
      }
    }
    if (world.zone !== trace.steps[i].zone) {
      world.zone = trace.steps[i].zone;
    }
  }
  if (verbose && diffs.length) {
    for (const d of diffs.slice(0, 20)) {
      console.log('   krok '+d.step+' slot '+d.slot
                  +(d.cls === undefined ? '' : ' ($'+d.cls.toString(16).toUpperCase()+')')
                  +' '+d.field+': port '+d.got+', originál '+d.want
                  +(d.standing ? '  (stojící konvoj, §15)' : ''));
    }
  }
  return {diffs, borrowed, steps, handovers, handoverErrors, standing};
}

function main() {
  const args = parseArgs(process.argv);
  for (const f of ['data/objects.json', 'data/physics.json', 'data/convoy.json']) {
    if (!fs.existsSync(path.join(ROOT, f))) {
      console.error('chybí '+f+' – spusť tools/dumpconvoy.py');
      process.exit(2);
    }
  }
  const objects = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/objects.json'), 'utf8'));
  const convoy = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/convoy.json'), 'utf8'));
  const physics = new VortonPhysics(
    JSON.parse(fs.readFileSync(path.join(ROOT, 'data/physics.json'), 'utf8')));

  const indexPath = path.join(args.traces, 'index.json');
  if (!fs.existsSync(indexPath)) {
    console.error('chybí %s – spusť tools/traceconvoy.py', indexPath);
    process.exit(2);
  }
  const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));

  let steps = 0, bad = 0, borrowed = 0, scenarios = 0, clean = 0;
  let handovers = 0, handoverErrors = 0, standing = 0;
  for (const entry of index) {
    if (args.scenario && args.scenario !== entry.name) { continue; }
    const trace = JSON.parse(
      fs.readFileSync(path.join(args.traces, entry.name+'.json'), 'utf8'));
    const result = checkTrace(objects, physics, convoy, trace, args.verbose);
    scenarios++;
    steps += result.steps;
    bad += result.diffs.length;
    borrowed += result.borrowed;
    handovers += result.handovers;
    handoverErrors += result.handoverErrors;
    standing += result.standing;
    if (!result.diffs.length) { clean++; }
    console.log((result.diffs.length ? '✗ ' : '✓ ')+entry.name.padEnd(11)
                +String(result.steps).padStart(5)+' kroků, '
                +String(result.diffs.length).padStart(4)+' rozdílů'
                +(result.standing ? ' ('+result.standing+' na stojícím konvoji, §15)' : '')
                +(result.handovers ? ', '+result.handovers+'× předání řízení' : '')
                +' — '+entry.note);
  }
  console.log('\n'+scenarios+' scénářů, '+steps+' kroků, **'+bad+' rozdílů**, '
              +'z toho '+standing+' na průchodech, ve kterých konvoj originálu '
              +'stojí s volnou cestou (otevřená otázka §15), a '+(bad-standing)
              +' ostatních; '
              +clean+' scénářů sedí do posledního bajtu, '
              +handovers+'× předání řízení ('+handoverErrors+' chybně), '
              +borrowed+'× hráč, výstřel, předmět nebo nepřítel vzatý ze '
              +'záznamu (M2/M4/M6)');
  process.exit(bad ? 1 : 0);
}

main();
