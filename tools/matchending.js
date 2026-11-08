#!/usr/bin/env node
/**
 * Přehraje **koncovou sekvenci** portu proti nahranému běhu originálu (M7).
 *
 *   ./tools/matchending.js [--verbose] [--traces build/gtraces]
 *
 * Stejný nápad jako `matchenemies.js` (M6), zase posunutý o milník: **počítá
 * se jen to, co přidala M7** – scénář konce hry a druhý průchod – a všechno
 * ostatní se bere ze záznamu ve chvíli, kdy na to v tabulce přijde řada. Kdyby
 * se počítalo i ostatní, nesla by čísla M7 i rozdíly M4 a M5 a nebylo by
 * poznat, čí jsou.
 *
 * Porovnávají se čtyři věci, a každá odpovídá na jinou otázku:
 *
 * 1. **Co sekvence udělá s konvojem.** Prvních pět záznamů má jít do animace
 *    zániku, kterou změřila M6 – `$80` ve spodním bajtu druhu a horní bit
 *    rychlosti – a po dvanácti průchodech z tabulky zmizet. Port počítá jen
 *    tyhle záznamy; ostatní se berou ze záznamu.
 * 2. **Jak dlouho která část scénáře trvá.** Port si počty průchodů bere
 *    z konstant, které `dumpending.py` přečetl z kódu; matcher je porovnává
 *    s tím, na kterém snímku byla která hranice v originálu.
 * 3. **Kam dojede Lasertron.** Sekvence ho pustí samotného a čeká, až kamera
 *    dojede na zónu 36 – pět zón za Zone Zero.
 * 4. **Co udělá druhý průchod s tabulkou dat silnice.** Záznam nese druh a
 *    rychlost všech 240 záznamů před ním a po něm; port dostane tu první řadu
 *    a musí z ní udělat druhou.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const loadClassicScript = require(path.join(__dirname, '../app/svision/tools/classicScript.cjs'));

const ROOT = path.join(__dirname, '..');
global.HighwayEnemies = loadClassicScript(path.join(ROOT, 'app/highwayEnemies.js'));
const HighwayEnemies = global.HighwayEnemies;
const HighwayEnding = loadClassicScript(path.join(ROOT, 'app/highwayEnding.js'));

const DYING_SLOTS = 5;       // řízený Vorton a čtyři automatické – ty sekvence zabije hned
const LASERTRON_SLOT = 5;    // …a Lasertron zůstane
const TABLE_BASE = 0x8A00;
const RECORD = 16;

function parseArgs(argv) {
  const args = {traces: path.join(ROOT, 'build/gtraces'), verbose: false};
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--verbose') { args.verbose = true; }
    else if (argv[i] === '--traces') { args.traces = argv[++i]; }
    else { throw new Error('neznámý argument '+argv[i]); }
  }
  return args;
}

/** Záznam originálu `[slot, x, y, dir, speed, phase, cls, kind]`. */
function toEntity(row) {
  return {x: row[1], y: row[2], dir: row[3], speed: row[4], phase: row[5],
          cls: row[6], kind: row[7]};
}

/**
 * Záznamy podle místa v tabulce, **posunuté o to, kam ukazuje `$8F01`**.
 *
 * Sekvence po zániku konvoje posune začátek tabulky o pět záznamů dál, takže
 * se v originálu od té chvíle čísluje jinak; port tabulku neposouvá, jen v ní
 * má prázdno. Posun se dopočítá z adresy, kterou záznam nese.
 */
function bySlot(list, table) {
  const shift = (parseInt(String(table).replace('$', ''), 16) - TABLE_BASE)/RECORD;
  const map = new Map();
  for (const row of list) { map.set(row[0] + shift, toEntity(row)); }
  return map;
}

/**
 * A world just big enough for the sequence: the table, and the M6 rule for a
 * record that is dying. Everything the sequence does not own is put back from
 * the recording every pass.
 */
function makeWorld(enemyData) {
  return {entities: new Array(64).fill(null),
          enemies: new HighwayEnemies(enemyData)};
}

function checkScript(trace, ending, enemyData, verbose) {
  const world = makeWorld(enemyData);
  const start = bySlot(trace.start.ents, trace.start.table);
  for (const [slot, e] of start) { world.entities[slot] = e; }

  ending.start(world);
  const diffs = [];
  const phases = new Map();
  let passes = 0, borrowed = 0, dying = 0, deaths = 0, lasertronBorrowed = 0;

  let frame = trace.start.frame;
  for (const row of trace.steps) {
    // Snímky, ve kterých se sekvence nevrací do hlavní smyčky, jsou taky část
    // scénáře – rozpad lodi a prodleva po něm se jenom kreslí. Port je počítá
    // po snímcích a matcher mu je odtiká, ať v obou běží stejný čas.
    for (; frame < row.frame; frame++) { ending.frame(world); }
    if (!row.loop) { continue; }
    const phase = ending.view.phase;
    const beat = ending.step(world);
    passes++;
    if (beat.done) {
      // hotovo: to, co v záznamu následuje, je už nová hra (M3–M6), ne konec
      break;
    }
    phases.set(phase, (phases.get(phase) || 0) + 1);
    // the M6 dying animation, which is what the sequence set the convoy to —
    // and, in the closing stretch, the Lasertron as well
    for (let slot = 0; slot <= LASERTRON_SLOT; slot++) {
      const e = world.entities[slot];
      if (e && world.enemies.isDead(e)) {
        dying++;
        if (world.enemies.stepDying(world, slot, e)) { deaths++; }
      }
    }
    const want = bySlot(row.ents, row.table);
    // Where the Lasertron **is** belongs to M5, which matched it pass by pass
    // already; M7 owns only what the sequence writes into it, so its place on
    // the road is taken from the recording and its kind and speed are not.
    const lasertron = world.entities[LASERTRON_SLOT];
    const recorded = want.get(LASERTRON_SLOT);
    if (lasertron && recorded) {
      lasertron.x = recorded.x;
      lasertron.y = recorded.y;
      lasertron.phase = recorded.phase;
      // ...and its speed too, once the sequence has set it going: what stops
      // it at the end of the road is the convoy's own rule, which M5 matched
      // pass by pass. What the **sequence** writes into the record — its kind —
      // is what M7 owns and what is compared.
      lasertron.speed = recorded.speed;
      borrowed++;
      lasertronBorrowed++;
    }
    // everything outside the convoy is the recording's, at its turn
    for (let slot = LASERTRON_SLOT+1; slot < world.entities.length; slot++) {
      if (want.has(slot)) { world.entities[slot] = want.get(slot); borrowed++; }
      else { world.entities[slot] = null; }
    }
    for (let slot = 0; slot <= LASERTRON_SLOT; slot++) {
      const got = world.entities[slot];
      const expected = want.get(slot) || null;
      if (!got && !expected) { continue; }
      if (!got || !expected) {
        diffs.push({pass: passes, slot, field: 'record',
                    got: got ? 'je' : 'není', want: expected ? 'je' : 'není'});
        continue;
      }
      const fields = (slot === LASERTRON_SLOT) ? ['cls'] : ['cls', 'speed'];
      for (const field of fields) {
        if (got[field] !== expected[field]) {
          diffs.push({pass: passes, slot, field, got: got[field],
                      want: expected[field]});
        }
      }
    }
  }
  if (verbose) {
    for (const d of diffs.slice(0, 20)) {
      console.log('   průchod '+d.pass+' slot '+d.slot+' '+d.field
                  +': port '+d.got+', originál '+d.want);
    }
  }
  return {diffs, passes, phases, borrowed, dying, deaths, lasertronBorrowed};
}

/** Where the sequence takes the camera: five zones past Zone Zero. */
function checkEndZone(trace, ending) {
  const last = trace.marks.find((m) => m.mark === 'endZonesDone');
  const want = last ? last.zoneCopy : null;
  const got = ending.k('endZoneLast', null);
  return {got, want, ok: got === want};
}

/** What one finished game does to the road's own table. */
function checkSecondPass(trace, ending, enemyData) {
  const before = trace.master.before.map((row) => ({cls: row[0], speed: row[1]}));
  const after = trace.master.after;
  ending.harden(before, 1, enemyData.familyMask);
  const diffs = [];
  for (let i = 0; i < after.length; i++) {
    if (before[i].speed !== after[i][1]) {
      diffs.push({record: i, got: before[i].speed, want: after[i][1]});
    }
  }
  let changed = 0;
  for (let i = 0; i < after.length; i++) {
    if (trace.master.before[i][1] !== after[i][1]) { changed++; }
  }
  return {diffs, changed, records: after.length};
}

/** How long each part of the script took the original, in frames. */
function checkTiming(trace, ending) {
  const rows = [];
  let previous = trace.start.frame;
  for (const mark of trace.marks) {
    rows.push({name: mark.mark, frames: mark.frame - previous});
    previous = mark.frame;
  }
  return rows;
}

function main() {
  const args = parseArgs(process.argv);
  for (const f of ['data/ending.json', 'data/enemies.json']) {
    if (!fs.existsSync(path.join(ROOT, f))) {
      console.error('chybí '+f+' – spusť tools/dumpending.py');
      process.exit(2);
    }
  }
  const endingData = JSON.parse(
    fs.readFileSync(path.join(ROOT, 'data/ending.json'), 'utf8'));
  const enemyData = JSON.parse(
    fs.readFileSync(path.join(ROOT, 'data/enemies.json'), 'utf8'));
  const tracePath = path.join(args.traces, 'ending.json');
  if (!fs.existsSync(tracePath)) {
    console.error('chybí '+tracePath+' – spusť tools/traceending.py');
    process.exit(2);
  }
  const trace = JSON.parse(fs.readFileSync(tracePath, 'utf8'));

  const ending = new HighwayEnding(endingData, 2.41);
  const script = checkScript(trace, ending, enemyData, args.verbose);
  const zone = checkEndZone(trace, ending);
  const second = checkSecondPass(trace, ending, enemyData);
  const timing = checkTiming(trace, ending);

  console.log((script.diffs.length ? '✗' : '✓')+' scénář      '
              +String(script.passes).padStart(4)+' průchodů, '
              +script.diffs.length+' rozdílů v konvoji ('+script.dying
              +' průchodů animace zániku, '+script.deaths+' záznamů zmizelo)');
  console.log((zone.ok ? '✓' : '✗')+' konec zón   port jede do zóny '+zone.got
              +', originál do '+zone.want);
  console.log((second.diffs.length ? '✗' : '✓')+' druhý průch. '
              +second.changed+' z '+second.records
              +' záznamů silnice zrychleno, '+second.diffs.length+' rozdílů');
  console.log('\nčásti scénáře (snímků v originálu):');
  for (const row of timing) {
    console.log('  '+row.name.padEnd(16)+String(row.frames).padStart(5));
  }
  console.log('\nfáze, které port napočítal (průchodů):');
  for (const [name, count] of script.phases) {
    console.log('  '+String(name).padEnd(16)+String(count).padStart(5));
  }
  const bad = script.diffs.length + second.diffs.length + (zone.ok ? 0 : 1);
  console.log('\n'+script.passes+' průchodů sekvence, '+script.borrowed
              +' záznamů vzatých ze záznamu, **'+bad+' rozdílů**');
  process.exit(bad ? 1 : 0);
}

main();
