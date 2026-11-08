#!/usr/bin/env node
/**
 * Přehraje `app/vortonPhysics.js` proti nahranému běhu originálu (M3).
 *
 *   ./tools/matchphysics.js [--scenario jmeno] [--verbose] [--traces build/traces]
 *
 * Vstup: záznamy z `tools/tracephysics.py` (originál krokovaný po průchodech
 * hlavní smyčkou) a konstanty z `tools/dumpphysics.py`. Do portu jdou tytéž
 * klávesy, jaké ten krok přečetla hra, a porovnává se **celý stav Vortona na
 * konci kroku**: pozice, směr, rychlost, fáze animace i posuvný registr plynu.
 * Cíl je **nula rozdílů**.
 *
 * Jedna věc se do portu bere ze záznamu, a je to napsané ve výstupu: jestli
 * v cestě stál **předmět**. Okraje silnice port zná (změřené meze
 * v `data/physics.json`), ale co na silnici stojí, jsou data zóny – to je M2
 * a pravidla strkání jsou M4. Scénáře, které jedou po volné silnici a do
 * okrajů, se proto musí trefit **bez jediné nápovědy**; u ostatních se hlásí,
 * kolikrát ji port potřeboval. Až M4 dodá předměty, nápověda zmizí.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const loadClassicScript = require(path.join(__dirname, '../app/svision/tools/classicScript.cjs'));

const ROOT = path.join(__dirname, '..');
const VortonPhysics = loadClassicScript(path.join(ROOT, 'app/vortonPhysics.js'));

const FIELDS = ['x', 'y', 'dir', 'speed', 'phase', 'timer'];

function parseArgs(argv) {
  const args = {traces: path.join(ROOT, 'build/traces'), scenario: null,
                verbose: false};
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--verbose') { args.verbose = true; }
    else if (argv[i] === '--scenario') { args.scenario = argv[++i]; }
    else if (argv[i] === '--traces') { args.traces = argv[++i]; }
    else { throw new Error('neznámý argument '+argv[i]); }
  }
  return args;
}

function checkTrace(physics, trace, verbose) {
  const v = physics.spawn(trace.start.x, trace.start.y, trace.start.dir);
  v.speed = trace.start.speed;
  v.phase = trace.start.phase;
  v.timer = trace.start.timer;
  // $8F13 se do záznamu ukládá po kroku; `start` je stav před prvním krokem
  v.turnPhase = trace.start.turnPhase;

  const diffs = [];
  let hints = 0, prev = {x: trace.start.x, y: trace.start.y};
  for (let i = 0; i < trace.steps.length; i++) {
    const want = trace.steps[i];
    // Nápověda M2/M4: originál se nehnul, ačkoli rychlost měl – něco tam
    // stálo. Jestli to byl **náraz** (a stojí rychlost), říká příznak `$8F15`
    // ze záznamu; port se ptá až potom, co sám neuvidí okraj silnice, a každé
    // použití se počítá.
    const stoodStill = want.x === prev.x && want.y === prev.y;
    let asked = 0;
    const blocked = (nx, ny) => {
      if (!stoodStill) { return 0; }
      // A jestli to byl **náraz**, nebo se Vorton jen o něco opřel: originál
      // obojí umí (opřený o konvoj stojí několik kroků a rychlost si nechává,
      // do zdi ji ztrácí hned). Rozhodnout to je taky práce M2/M4, takže se
      // to sem zatím bere ze záznamu – že rychlost klesla.
      asked++;
      if (want.speed === v.speed) { return VortonPhysics.BLOCK_HOLD; }
      // rozdíl mezi HIT a SLOW je jen v tom, jestli srážka nabila časovač
      // plynu; obojí originál dělá (do okraje silnice a do většiny předmětů
      // nabije, do řady předmětů napříč silnicí ne – změřeno a opakovatelné),
      // a co je co, rozhodnou data zóny v M2
      const afterHit = v.speed-1 > 0 ? physics.hitReload : 0;
      return want.timer === afterHit ? VortonPhysics.BLOCK_HIT
                                     : VortonPhysics.BLOCK_SLOW;
    };
    physics.step(v, want.in, blocked);
    hints += asked;
    for (const f of FIELDS) {
      if (v[f] !== want[f]) {
        diffs.push({step: i, field: f, got: v[f], want: want[f], keys: want.in});
        // dál by se rozdíly jen množily z jednoho kořene; stav se srovná
        // a hlásí se první výskyt v každém kroku
        v[f] = want[f];
      }
    }
    prev = {x: want.x, y: want.y};
  }
  if (verbose && diffs.length) {
    for (const d of diffs.slice(0, 20)) {
      console.log('   krok '+d.step+' '+d.field+': port '+d.got
                  +', originál '+d.want+' (klávesy '+d.keys+')');
    }
  }
  return {diffs, hints};
}

function main() {
  const args = parseArgs(process.argv);
  const physicsPath = path.join(ROOT, 'data/physics.json');
  if (!fs.existsSync(physicsPath)) {
    console.error('chybí data/physics.json – spusť tools/dumpphysics.py');
    process.exit(2);
  }
  const data = JSON.parse(fs.readFileSync(physicsPath, 'utf8'));
  const physics = new VortonPhysics(data);

  const indexPath = path.join(args.traces, 'index.json');
  if (!fs.existsSync(indexPath)) {
    console.error('chybí %s – spusť tools/tracephysics.py', indexPath);
    process.exit(2);
  }
  const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));

  let steps = 0, bad = 0, hints = 0, scenarios = 0;
  for (const entry of index) {
    if (args.scenario && args.scenario !== entry.name) { continue; }
    const trace = JSON.parse(
      fs.readFileSync(path.join(args.traces, entry.name+'.json'), 'utf8'));
    const result = checkTrace(physics, trace, args.verbose);
    scenarios++;
    steps += trace.steps.length;
    bad += result.diffs.length;
    hints += result.hints;
    console.log((result.diffs.length ? '✗ ' : '✓ ')+entry.name.padEnd(14)
                +String(trace.steps.length).padStart(4)+' kroků, '
                +result.diffs.length+' rozdílů'
                +(result.hints ? ', '+result.hints+'× nápověda o předmětu (M2/M4)' : '')
                +' — '+trace.note);
  }
  console.log('\n'+scenarios+' scénářů, '+steps+' kroků, **'+bad
              +' rozdílů**, '+hints+'× nápověda o předmětu ('
              +(100*hints/steps).toFixed(1)+' % kroků)');
  process.exit(bad ? 1 : 0);
}

main();
