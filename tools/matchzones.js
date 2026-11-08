#!/usr/bin/env node
/**
 * Přehraje **plnění zón** portu proti nahranému běhu originálu (M2).
 *
 *   ./tools/matchzones.js [--traces build/ztraces] [--verbose]
 *
 * `dumpzones.py` změřil pravidlo a ověřil ho ještě v pythonu; tenhle matcher
 * ověřuje **port**: `HighwayWorld.enterZone()` v `app/highwayObjects.js`.
 * Z každého zaznamenaného přechodu (`tools/tracezones.py`) se vezme stav před
 * ním – tabulka dat silnice a živá tabulka originálu – nasype se do světa
 * portu, zavolá se `enterZone()` a porovná se:
 *
 * * **tabulka dat silnice bajt po bajtu** – to ověří zápis zpět (`$92CE`)
 *   i úklid zaniklých (`$9400`). Mimo přechody se ta tabulka nemění, takže
 *   se porovnat dá přesně;
 * * **pořadí načtených záznamů** – které záznamy si zóna vzala a v jakém
 *   pořadí (`$93B7`). Souřadnice se neporovnávají: živá tabulka se v záznamu
 *   čte na konci průchodu, kdy se už všechno pohnulo.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const loadClassicScript = require(path.join(__dirname, '../app/svision/tools/classicScript.cjs'));

const ROOT = path.join(__dirname, '..');
global.VortonPhysics = loadClassicScript(path.join(ROOT, 'app/vortonPhysics.js'));
const VortonPhysics = global.VortonPhysics;
const HighwayWorld = loadClassicScript(path.join(ROOT, 'app/highwayObjects.js'));

const load = (name) =>
  JSON.parse(fs.readFileSync(path.join(ROOT, 'data', name+'.json'), 'utf8'));
// bajty záznamu, které port vede (data/highway.json `record`); +11 je 22×rodina
// a +13 kopie x, obojí port nepočítá, takže se neporovnávají
const FIELDS = [['x', 0], ['y', 1], ['depth', 3], ['cls', 5], ['dir', 7],
                ['speed', 8], ['phase', 9], ['kind', 10], ['lane', 12]];

function decode(b64) {
  return Buffer.from(b64, 'base64');
}

/** Jeden šestnáctibajtový záznam na to, co z něj port vede. */
function record(raw, at) {
  return {x: raw[at], y: raw[at+1] | (raw[at+2] << 8),
          depth: raw[at+3] | (raw[at+4] << 8),
          cls: raw[at+5] | (raw[at+6] << 8), dir: raw[at+7], speed: raw[at+8],
          phase: raw[at+9], kind: raw[at+10], lane: raw[at+12]};
}

function main() {
  const args = {traces: path.join(ROOT, 'build/ztraces'), verbose: false};
  for (let i = 2; i < process.argv.length; i++) {
    if (process.argv[i] === '--verbose') { args.verbose = true; }
    else if (process.argv[i] === '--traces') { args.traces = process.argv[++i]; }
    else { throw new Error('neznámý argument '+process.argv[i]); }
  }
  const trace = JSON.parse(fs.readFileSync(path.join(args.traces, 'demo.json'), 'utf8'));
  const highway = load('highway'), zones = load('zones'), objects = load('objects');
  const physics = new VortonPhysics(load('physics'));

  let diffTable = 0, diffOrder = 0, records = 0, cells = 0;
  trace.steps.forEach((step) => {
    const world = new HighwayWorld(objects, physics);
    if (!world.setRoad(highway, zones)) {
      throw new Error('chybí data/highway.json nebo data/zones.json');
    }
    // stav, ze kterého originál do přechodu šel
    const beforeRoad = decode(step.before.road);
    const beforeLive = decode(step.before.live);
    for (let i = 0; i < world.roadTable.length; i++) {
      const r = record(beforeRoad, i*16);
      Object.assign(world.roadTable[i], r);
    }
    world.endSlot = 9;
    for (let slot = 9; slot < trace.liveSlots; slot++) {
      if (beforeLive[slot*16] === 0xFF) { break; }
      const pointer = beforeLive[slot*16+14] | (beforeLive[slot*16+15] << 8);
      const source = (pointer - 0x7B00)/16;
      const e = world.put(slot, record(beforeLive, slot*16));
      if (source === (source|0) && source >= 0 && source < world.roadTable.length) {
        e.source = source;
      }
      world.endSlot = slot + 1;
    }

    world.enterZone(step.to);

    // 1. tabulka dat silnice po zápisu zpět a úklidu – bajt po bajtu
    const afterRoad = decode(step.after.road);
    for (let i = 0; i < world.roadTable.length; i++) {
      const want = record(afterRoad, i*16), got = world.roadTable[i];
      records++;
      FIELDS.forEach(([name]) => {
        cells++;
        if (want[name] !== got[name]) {
          diffTable++;
          if (args.verbose && diffTable <= 20) {
            console.log('  zóna %d→%d, záznam %d, %s: port %d, originál %d',
                        step.from, step.to, i, name, got[name], want[name]);
          }
        }
      });
    }
    // 2. co si zóna vzala a v jakém pořadí
    const got = [];
    for (let slot = 9; slot < world.endSlot; slot++) {
      got.push(world.entities[slot] ? world.entities[slot].source : null);
    }
    const want = step.after.sources;
    if (got.length !== want.length || got.some((v, i) => v !== want[i])) {
      diffOrder++;
      console.log('✗ zóna %d→%d: port vzal %d záznamů %j, originál %d %j',
                  step.from, step.to, got.length, got, want.length, want);
    }
  });

  console.log('\n%d přechodů zón, %d záznamů tabulky (%d porovnaných hodnot), '
              + '**%d rozdílů v tabulce** a **%d v pořadí načtení**',
              trace.steps.length, records, cells, diffTable, diffOrder);
  process.exit(diffTable || diffOrder ? 1 : 0);
}

main();
