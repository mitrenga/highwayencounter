#!/usr/bin/env node
/**
 * Přehraje `app/highwayCadence.js` proti nahraným průchodům originálu (M9).
 *
 *   ./tools/matchcadence.js [--scenario jmeno] [--verbose] [--traces build/ktraces]
 *
 * Vstup: záznamy z `tools/tracecadence.py` (délka každého průchodu hlavní
 * smyčkou originálu v T-stavech) a konstanty z `tools/dumpcadence.py`. Port
 * dostane jen popis situace – kolik se kreslilo, kolik je živých záznamů,
 * jaký zvuk se hraje a jestli se mění zóna – a řekne, jak dlouho by ten
 * průchod trval.
 *
 * Na rozdíl od ostatních matcherů tohohle projektu se **nula rozdílů čekat
 * nedá**, a je poctivé to říct rovnou: dvě ze tří částí modelu jsou přesné
 * (regulátor spočítaný z instrukcí a zvuk změřený v M8 na T-stav), ale práce
 * průchodu je fit. Zbytek rozptylu je v tom, kolik znakových buněk se ten
 * průchod opravdu přenáší na obrazovku; změřeno, že by přidání toho počtu
 * srazilo odchylku ze 7 200 na 5 700 T, tedy o pětinu – za to, že by si port
 * musel vést počítadla buněk originálu, to nestojí.
 *
 * Měří se proto chyba: kolik průchodů se trefí do osminy, čtvrtiny, půlky a
 * celého snímku. Za hotové se považuje **99 % průchodů do půl snímku**
 * (10 ms); kolik jich je do čtvrt snímku, se vypisuje vedle toho.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const loadClassicScript = require(path.join(__dirname, '../app/svision/tools/classicScript.cjs'));

const ROOT = path.join(__dirname, '..');
const HighwayCadence = loadClassicScript(path.join(ROOT, 'app/highwayCadence.js'));

const GOAL_HALF = 99;   // % průchodů, které se musí trefit do půl snímku

function parseArgs(argv) {
  const args = {traces: path.join(ROOT, 'build/ktraces'), scenario: null,
                verbose: false};
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--verbose') { args.verbose = true; }
    else if (argv[i] === '--scenario') { args.scenario = argv[++i]; }
    else if (argv[i] === '--traces') { args.traces = argv[++i]; }
    else { throw new Error('neznámý argument '+argv[i]); }
  }
  return args;
}

/** Jméno efektu, o který si předchozí průchod řekl (žádanka $8F15). */
function soundName(cadence, flag, priority, bits) {
  for (const bit of priority) {
    if (flag & (1 << bit)) {
      for (const name of Object.keys(bits)) {
        if (bits[name] === bit) { return name; }
      }
    }
  }
  return false;
}

function checkTrace(cadence, data, trace, verbose) {
  const frame = trace.frameTstates || 69888;
  const priority = (data.sound && data.sound.priority) || [];
  const bits = (data.sound && data.sound.bits) || {};
  const errors = [];
  const buckets = {eighth: 0, quarter: 0, half: 0, whole: 0};
  let worst = null;

  for (let i = 0; i < trace.passes.length; i++) {
    const want = trace.passes[i];
    const got = Math.round(cadence.passTstates(want.drawn, want.live,
                                    soundName(cadence, want.sound, priority, bits),
                                    want.repaint));
    const err = got-want.t;
    errors.push(err);
    const a = Math.abs(err);
    if (a < frame/8) { buckets.eighth++; }
    if (a < frame/4) { buckets.quarter++; }
    if (a < frame/2) { buckets.half++; }
    if (a < frame) { buckets.whole++; }
    if (!worst || a > Math.abs(worst.err)) {
      worst = {pass: i, err: err, got: got, want: want};
    }
  }

  errors.sort((a, b) => a-b);
  const abs = errors.map(Math.abs).sort((a, b) => a-b);
  const result = {
    passes: trace.passes.length,
    median: errors[errors.length >> 1],
    p95: abs[Math.floor(abs.length*0.95)],
    max: abs[abs.length-1],
    buckets: buckets,
    worst: worst
  };
  if (verbose && worst) {
    console.log('   nejhorší průchod '+worst.pass+': port '+worst.got
                +' T, originál '+worst.want.t+' T ('+(worst.err > 0 ? '+' : '')
                +worst.err+'), kresleno '+worst.want.drawn+', živých '
                +worst.want.live+(worst.want.repaint ? ', překreslení plochy' : ''));
  }
  return result;
}

function main() {
  const args = parseArgs(process.argv);
  const dataPath = path.join(ROOT, 'data/cadence.json');
  if (!fs.existsSync(dataPath)) {
    console.error('chybí data/cadence.json – spusť tools/dumpcadence.py');
    process.exit(2);
  }
  const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
  const cadence = new HighwayCadence(data);

  const indexPath = path.join(args.traces, 'index.json');
  if (!fs.existsSync(indexPath)) {
    console.error('chybí %s – spusť tools/tracecadence.py', indexPath);
    process.exit(2);
  }
  const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));

  const frame = data.frameTstates || 69888;
  let passes = 0, scenarios = 0;
  const total = {eighth: 0, quarter: 0, half: 0, whole: 0};
  let worst = null;

  for (const entry of index) {
    if (args.scenario && args.scenario !== entry.name) { continue; }
    const trace = JSON.parse(
      fs.readFileSync(path.join(args.traces, entry.name+'.json'), 'utf8'));
    const r = checkTrace(cadence, data, trace, args.verbose);
    scenarios++;
    passes += r.passes;
    for (const k of Object.keys(total)) { total[k] += r.buckets[k]; }
    if (!worst || Math.abs(r.worst.err) > Math.abs(worst.err)) { worst = r.worst; }
    const pct = 100*r.buckets.half/r.passes;
    console.log((pct >= GOAL_HALF ? '✓ ' : '✗ ')+entry.name.padEnd(12)
                +String(r.passes).padStart(5)+' průchodů, '
                +(100*r.buckets.quarter/r.passes).toFixed(1).padStart(5)
                +' % do čtvrt snímku, '
                +pct.toFixed(1).padStart(5)+' % do půl snímku, '
                +'medián '+(r.median > 0 ? '+' : '')+Math.round(r.median)+' T, '
                +'nejhůř '+Math.round(r.max)+' T ('
                +(r.max/frame).toFixed(2)+' snímku) — '+trace.note);
  }

  const pct = (k) => (100*total[k]/passes).toFixed(1);
  console.log('\n'+scenarios+' scénářů, '+passes+' průchodů: '
              +pct('eighth')+' % do osminy snímku, '+pct('quarter')
              +' % do čtvrt snímku, **'+pct('half')+' % do půl snímku**, '
              +pct('whole')+' % do snímku');
  if (worst) {
    console.log('nejhorší průchod z celku: port '+worst.got+' T, originál '
                +worst.want.t+' T, rozdíl '+(worst.err > 0 ? '+' : '')
                +worst.err+' T ('+(Math.abs(worst.err)/frame).toFixed(2)
                +' snímku)');
  }
  const ok = 100*total.half/passes >= GOAL_HALF;
  console.log(ok ? 'kadence sedí (cíl je '+GOAL_HALF+' % do půl snímku)'
                 : 'kadence nesedí – cíl je '+GOAL_HALF+' % do půl snímku');
  process.exit(ok ? 0 : 1);
}

main();
