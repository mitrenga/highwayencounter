#!/usr/bin/env node
/**
 * Přehraje **nepřátele** portu proti nahranému běhu originálu (M6).
 *
 *   ./tools/matchenemies.js [--scenario jmeno] [--verbose] [--traces build/etraces]
 *
 * Stejný nápad jako `matchconvoy.js` (M5), jen posunutý o milník dál: **počítá
 * se jen to, co přidala M6** – čtyři rodiny nepřátel a animace zániku – a
 * všechno ostatní se bere ze záznamu, a to **ve chvíli, kdy na to v tabulce
 * přijde řada**. Kdyby se počítalo i ostatní, nesla by čísla M6 i 68 rozdílů
 * M4 (§14) a 2224 rozdílů M5 (§15) a nebylo by poznat, čí jsou.
 *
 * Dvě věci si port bere ze záznamu navíc a hlásí to:
 *
 * * **semínko generátoru** na začátku každého průchodu. Nepřátelé si směr
 *   tahají z generátoru hry (`$5C76`, `(254·SEED+253) mod 65537`), ze kterého
 *   si ale tahá i zvuk výbuchu a kreslení (`disasm_notes.md` §16). Dokud není
 *   zvuk změřený (M8), port sekvenci sám neudrží – hlásí se proto, v kolika
 *   průchodech se **v originálu tahalo i jinde**, protože právě v těch se port
 *   rozejde.
 * * **konec tabulky a okno světa**, protože oboje mění hra jinde: tabulku
 *   plní obsah zóny (M2) a okno posouvá čelo konvoje.
 *
 * Rozdíl se hlásí, když je nepřítel v portu jinde, jinak natočený, jinak
 * rychlý, v jiné fázi animace, na jiné dráze nebo jiného druhu než v
 * originálu. Průchody, ve kterých záznam nepřítele přepsal obsah nové zóny
 * (M2) nebo ho sundal řízený Vorton ve svém průchodu (M3/M4), se počítají
 * zvlášť – port je nesimuluje a předstírat to nemá.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const loadClassicScript = require(path.join(__dirname, '../app/svision/tools/classicScript.cjs'));

const ROOT = path.join(__dirname, '..');
global.VortonPhysics = loadClassicScript(path.join(ROOT, 'app/vortonPhysics.js'));
const VortonPhysics = global.VortonPhysics;
global.HighwayEnemies = loadClassicScript(path.join(ROOT, 'app/highwayEnemies.js'));
const HighwayEnemies = global.HighwayEnemies;
const HighwayWorld = loadClassicScript(path.join(ROOT, 'app/highwayObjects.js'));

const FIELDS = ['x', 'y', 'dir', 'speed', 'phase', 'lane', 'cls'];
const EMPTY_X = 0xFE;

function parseArgs(argv) {
  const args = {traces: path.join(ROOT, 'build/etraces'), scenario: null,
                verbose: false};
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--verbose') { args.verbose = true; }
    else if (argv[i] === '--scenario') { args.scenario = argv[++i]; }
    else if (argv[i] === '--traces') { args.traces = argv[++i]; }
    else { throw new Error('neznámý argument '+argv[i]); }
  }
  return args;
}

/** Záznam originálu `[slot, x, y, dir, speed, phase, cls, kind, lane, depth, b11, homeX, homeY]`. */
function toEntity(row) {
  return {x: row[1], y: row[2], dir: row[3], speed: row[4], phase: row[5],
          cls: row[6], kind: row[7], lane: row[8], depth: row[9],
          b11: row[10], homeX: row[11], homeY: row[12]};
}

function bySlot(list) {
  const map = new Map();
  for (const row of list) { map.set(row[0], toEntity(row)); }
  return map;
}

function checkTrace(objects, physics, enemyData, trace, verbose) {
  const world = new HighwayWorld(objects, physics, null, enemyData);
  const enemies = world.enemies;
  world.borrowAll = true;
  const start = bySlot(trace.start.ents);
  for (const [slot, e] of start) { world.put(slot, e); }
  world.endSlot = trace.start.end;
  world.zone = trace.start.globals.zone;

  const diffs = [];
  let borrowed = 0, steps = 0, passes = 0, zoneLoad = 0, killedByPlayer = 0;
  let shifted = 0, shiftedDiffs = 0, deaths = 0;
  let before = start;
  let prev = trace.start.globals;
  for (let i = 0; i < trace.steps.length; i++) {
    const row = trace.steps[i];
    const want = bySlot(row.ents);
    steps++;

    // Co hra mění jinde: semínko generátoru, okno světa a konec tabulky.
    enemies.borrowSeed(prev.seed);
    world.windowStart = prev.window;
    world.endSlot = (i === 0 ? trace.start.end : trace.steps[i-1].end);

    // Řízený Vorton (M3/M4) i konvoj (M5) se berou ze záznamu na své řadě.
    const place = (slot, entity) => {
      const ref = want.get(slot);
      if (ref) {
        entity.x = ref.x; entity.y = ref.y; entity.dir = ref.dir;
        entity.speed = ref.speed; entity.phase = ref.phase;
        entity.cls = ref.cls; entity.lane = ref.lane;
      } else {
        world.entities[slot] = null;
      }
      borrowed++;
      return true;
    };
    world.step(row.in, place, place);

    // Otočil se generátor v tomhle průchodu i někde jinde než u nepřátel?
    // Pak si port tahal z posunuté sekvence a rozdíly z toho se počítají
    // zvlášť – není to chyba pravidla, je to nezměřený zvuk (M8).
    const drifted = enemies.seed !== row.globals.seed;
    if (drifted) { shifted++; }

    for (let slot = 0; slot < HighwayWorld.SLOTS; slot++) {
      const got = world.entities[slot];
      const ref = want.get(slot);
      const was = before.get(slot);
      const ours = (was && (enemies.owns(was.cls) || (was.speed & 0x80)))
                || (got && (enemies.owns(got.cls) || (got.speed & 0x80)));
      if (!ours) {
        world.put(slot, ref || null);
        continue;
      }
      passes++;
      if (was && (was.speed & 0x80) && (!ref || !got)) { deaths++; }
      if (ref && was && (ref.homeX !== was.homeX || ref.homeY !== was.homeY
                         || ref.b11 !== was.b11)) {
        zoneLoad++;                       // záznam přepsal obsah nové zóny (M2)
      } else if (!ref && got) {
        // nepřítele sundal řízený Vorton ve svém průchodu – ten je M3/M4
        killedByPlayer++;
      } else if (ref && got) {
        for (const f of FIELDS) {
          if (got[f] !== ref[f]) {
            const d = {step: i, slot: slot, field: f, got: got[f],
                       want: ref[f], cls: ref.cls, drifted: drifted};
            if (drifted) { shiftedDiffs++; } else { diffs.push(d); }
            break;
          }
        }
      } else if (!ref !== !got) {
        const d = {step: i, slot: slot, field: 'záznam',
                   got: got ? '$'+got.cls.toString(16).toUpperCase() : 'prázdno',
                   want: ref ? '$'+ref.cls.toString(16).toUpperCase() : 'prázdno',
                   drifted: drifted};
        if (drifted) { shiftedDiffs++; } else { diffs.push(d); }
      }
      world.put(slot, ref || null);
    }
    before = want;
    prev = row.globals;
  }
  if (verbose && diffs.length) {
    for (const d of diffs.slice(0, 20)) {
      console.log('   krok '+d.step+' slot '+d.slot
                  +(d.cls === undefined ? '' : ' ($'+d.cls.toString(16).toUpperCase()+')')
                  +' '+d.field+': port '+d.got+', originál '+d.want);
    }
  }
  return {diffs, borrowed, steps, passes, zoneLoad, killedByPlayer, shifted,
          shiftedDiffs, deaths, seeds: enemies.borrowedSeeds};
}

function main() {
  const args = parseArgs(process.argv);
  for (const f of ['data/objects.json', 'data/physics.json', 'data/enemies.json']) {
    if (!fs.existsSync(path.join(ROOT, f))) {
      console.error('chybí '+f+' – spusť tools/dumpenemies.py');
      process.exit(2);
    }
  }
  const objects = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/objects.json'), 'utf8'));
  const enemyData = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/enemies.json'), 'utf8'));
  const physics = new VortonPhysics(
    JSON.parse(fs.readFileSync(path.join(ROOT, 'data/physics.json'), 'utf8')));

  const indexPath = path.join(args.traces, 'index.json');
  if (!fs.existsSync(indexPath)) {
    console.error('chybí '+indexPath+' – spusť tools/traceenemies.py');
    process.exit(2);
  }
  const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));

  let steps = 0, bad = 0, borrowed = 0, scenarios = 0, clean = 0, passes = 0;
  let zoneLoad = 0, killedByPlayer = 0, shifted = 0, shiftedDiffs = 0;
  let deaths = 0, seeds = 0;
  for (const entry of index) {
    if (args.scenario && args.scenario !== entry.name) { continue; }
    const trace = JSON.parse(
      fs.readFileSync(path.join(args.traces, entry.name+'.json'), 'utf8'));
    const r = checkTrace(objects, physics, enemyData, trace, args.verbose);
    scenarios++;
    steps += r.steps; bad += r.diffs.length; borrowed += r.borrowed;
    passes += r.passes; zoneLoad += r.zoneLoad; killedByPlayer += r.killedByPlayer;
    shifted += r.shifted; shiftedDiffs += r.shiftedDiffs; deaths += r.deaths;
    seeds += r.seeds;
    if (!r.diffs.length) { clean++; }
    console.log((r.diffs.length ? '✗ ' : '✓ ')+entry.name.padEnd(11)
                +String(r.steps).padStart(5)+' kroků, '
                +String(r.passes).padStart(5)+' průchodů nepřátel, '
                +String(r.diffs.length).padStart(4)+' rozdílů'
                +(r.shiftedDiffs ? ' ('+r.shiftedDiffs+' na posunutém generátoru, §16)' : '')
                +' — '+entry.note);
  }
  console.log('\n'+scenarios+' scénářů, '+steps+' kroků, '+passes
              +' průchodů nepřátel, **'+bad+' rozdílů**, a '+shiftedDiffs
              +' v průchodech, ve kterých si originál tahal z generátoru i '
              +'jinde než u nepřátel (zvuk a kreslení, §16; '+shifted
              +' takových průchodů); '+clean+' scénářů sedí do posledního '
              +'bajtu. Mimo to '+zoneLoad+'× přepsal záznam obsah nové zóny '
              +'(M2), '+killedByPlayer+'× sundal nepřítele řízený Vorton ve '
              +'svém průchodu (M3/M4) a '+deaths+'× doběhla animace zániku; '
              +seeds+'× vzaté semínko a '+borrowed+'× hráč, konvoj, výstřel '
              +'nebo předmět vzatý ze záznamu');
  process.exit(bad ? 1 : 0);
}

main();
