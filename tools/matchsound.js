#!/usr/bin/env node
/**
 * Přehraje **žádanku zvuku** portu proti nahranému běhu originálu (M8).
 *
 *   ./tools/matchsound.js [--scenario jmeno] [--verbose] [--traces build/straces]
 *
 * `dumpsound.py` změřil, jak efekty zní – tady se měří to druhé: **kdy** si
 * o ně hra řekne. Originál si během průchodu nastavuje bity v bajtu `$8F15`
 * a na konci průchodu z nich rozskok `$9AEF` vybere jeden efekt a bajt
 * vynuluje; `tracesound.py` ten bajt zapsal v každém průchodu, i s celou
 * tabulkou objektů. Port se pustí na týchž průchodech a porovná se **celá
 * maska**, ne jen vítězný efekt – kdyby se porovnával jen ten, schoval by se
 * v prioritě každý omyl v tichém bitu.
 *
 * Aby čísla M8 nenesla rozdíly starších milníků, bere se ze záznamu na začátku
 * **každého** průchodu celá tabulka i semínko generátoru; port pak průchod
 * odjede sám se stisky ze záznamu. Počítá se tedy jen to, co přidala M8:
 * výstřel (bit 1), náraz (bit 4, tentýž příznak, který měřila M3) a zánik
 * podle rodiny (bity 6, 3 a 7).
 *
 * Semínko se navíc posune o tolik tahů, kolik jich spotřeboval efekt
 * přehraný v minulém průchodu (`data/sounds.json`, `draws`) – to je právě to,
 * co M6 nechala otevřené (`disasm_notes.md` §16). Kolik toho spotřebuje
 * kreslení, změřené pořád není, takže sedět nemusí všechno; hlásí se proto
 * zvlášť, v kolika průchodech se semínko rozešlo.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const loadClassicScript = require(path.join(__dirname, '../app/svision/tools/classicScript.cjs'));

const ROOT = path.join(__dirname, '..');
global.VortonPhysics = loadClassicScript(path.join(ROOT, 'app/vortonPhysics.js'));
const VortonPhysics = global.VortonPhysics;
global.HighwayEnemies = loadClassicScript(path.join(ROOT, 'app/highwayEnemies.js'));
global.HighwayConvoy = loadClassicScript(path.join(ROOT, 'app/highwayConvoy.js'));
const HighwayWorld = loadClassicScript(path.join(ROOT, 'app/highwayObjects.js'));

function parseArgs(argv) {
  const args = {traces: path.join(ROOT, 'build/straces'), scenario: null,
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

/** Kolik bodů dá zánik – z data/score.json, ne odtud. */
function killAward(score) {
  if (!score) { return 0; }
  for (const a of score.awards) {
    if (a.what === 'zánik') { return a.points; }
  }
  return 0;
}

/** Šest číslic originálu (1 až 10 pro 0 až 9, 0 je prázdno) na hodnotu. */
function scoreOf(digits, unit) {
  let value = 0;
  for (const d of digits) { value = value*10+(d === 0 ? 0 : d-1); }
  return value*unit;
}

function drawsOf(sounds, name) {
  for (const s of sounds.sounds) {
    if (s.name === name) { return s.draws || 0; }
  }
  return 0;
}

function checkTrace(objects, physics, enemyData, convoyData, sounds, score, trace, verbose) {
  const world = new HighwayWorld(objects, physics, convoyData, enemyData, sounds);
  const rows = trace.steps;
  const diffs = [];
  let steps = 0, asked = 0, drifted = 0, driftedDiffs = 0, eventDiffs = 0;
  let scored = 0, scoreDiffs = 0, escort = 0;
  const award = killAward(score), unit = score ? score.unit : 10;
  let played = 0, seed = trace.start.globals.seed, lastDraws = 0;

  for (let i = 0; i < rows.length; i++) {
    const before = i === 0 ? trace.start : rows[i-1];
    // Celá tabulka i okolí ze záznamu: M8 měří žádanku, ne svět.
    for (let slot = 0; slot < HighwayWorld.SLOTS; slot++) { world.put(slot, null); }
    for (const row of before.ents) { world.put(row[0], toEntity(row)); }
    world.endSlot = before.end;
    world.windowStart = before.globals.window;
    world.zone = before.globals.zone;
    world.sound = 0;

    // Semínko: to ze záznamu je z $9AEF, tedy **před** tahy zvuku. Zvuk
    // minulého průchodu si jich vzal tolik, kolik říká data/sounds.json.
    seed = before.globals.seed;
    for (let d = 0; d < lastDraws; d++) {
      seed = (enemyData.random.mul*seed + enemyData.random.add) % enemyData.random.mod;
    }
    if (world.enemies) { world.enemies.borrowSeed(seed); }

    // Řízený Vorton si nese dvě věci mimo tabulku – střídavou fázi otáčení
    // a posuvný registr plynu (M3) – a ty se ze záznamu berou taky, jinak by
    // se port po pár průchodech otáčel jinam.
    const player = world.entities[world.playerSlot];
    if (player) {
      player.turnPhase = before.globals.turnPhase;
      player.timer = before.globals.timer;
    }
    const out = world.step(rows[i].in, null, null);
    steps++;
    if (rows[i].sound) { asked++; }
    if (out.play) { played++; }
    lastDraws = out.play ? drawsOf(sounds, out.play) : 0;

    // M8: body. Originál přičte za zničený záznam rodiny 1 až 6; přičítání
    // za doprovod Lasertronu ($9BF3) port zatím nemá, takže se počítá zvlášť.
    if (score && rows[i].globals.score && before.globals.score) {
      const gain = scoreOf(rows[i].globals.score, unit)
                 - scoreOf(before.globals.score, unit);
      let mine = 0;
      for (const family of (out.destroyed || [])) {
        if (family >= 1 && family < sounds.dying.boundary) { mine += award; }
      }
      if (gain === mine) { scored += mine ? 1 : 0; }
      else if (mine === 0 && gain === unit) { escort++; }
      else {
        scoreDiffs++;
        if (verbose) {
          console.log('   body krok '+i+': port +'+mine+', originál +'+gain
                      +' (zničeno '+JSON.stringify(out.destroyed)+')');
        }
      }
    }

    const seedDrifted = world.enemies && world.enemies.seed !== rows[i].globals.seed;
    if (seedDrifted) { drifted++; }
    // Rozdíly se dělí na dvě hromádky. Bity výstřelu a nárazu říkají, jestli
    // se ta **událost** vůbec stala – a to je M3/M4, kde jich `matchobjects.js`
    // hlásí 68 (§14); nesly by se sem a nebylo by poznat, čí jsou. M8 vlastní
    // to druhé: který efekt si o sebe řekne **zanikající záznam**, a to jsou
    // bity zániku.
    const mine = (1 << sounds.dying.familyZero) | (1 << sounds.dying.familyBelow)
               | (1 << sounds.dying.familyAbove);
    if (((out.sound ^ rows[i].sound) & mine) !== 0) {
      const d = {step: i, got: out.sound, want: rows[i].sound, drifted: seedDrifted};
      if (seedDrifted) { driftedDiffs++; } else { diffs.push(d); }
    } else if (out.sound !== rows[i].sound) {
      eventDiffs++;
    }
  }
  if (verbose && diffs.length) {
    for (const d of diffs.slice(0, 20)) {
      console.log('   krok '+d.step+': port $'+d.got.toString(16).toUpperCase()
                  +', originál $'+d.want.toString(16).toUpperCase());
    }
  }
  return {diffs, steps, asked, played, drifted, driftedDiffs, eventDiffs,
          scored, scoreDiffs, escort};
}

function main() {
  const args = parseArgs(process.argv);
  const need = ['data/objects.json', 'data/physics.json', 'data/enemies.json',
                'data/sounds.json'];
  for (const f of need) {
    if (!fs.existsSync(path.join(ROOT, f))) {
      console.error('chybí '+f+' – spusť tools/dumpsound.py');
      process.exit(2);
    }
  }
  const read = (f) => JSON.parse(fs.readFileSync(path.join(ROOT, f), 'utf8'));
  const objects = read('data/objects.json');
  const enemyData = read('data/enemies.json');
  const sounds = read('data/sounds.json');
  const convoyData = fs.existsSync(path.join(ROOT, 'data/convoy.json'))
    ? read('data/convoy.json') : null;
  const score = fs.existsSync(path.join(ROOT, 'data/score.json'))
    ? read('data/score.json') : null;
  const physics = new VortonPhysics(read('data/physics.json'));

  const indexPath = path.join(args.traces, 'index.json');
  if (!fs.existsSync(indexPath)) {
    console.error('chybí '+indexPath+' – spusť tools/tracesound.py');
    process.exit(2);
  }
  const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));

  let steps = 0, bad = 0, asked = 0, played = 0, clean = 0, scenarios = 0;
  let drifted = 0, driftedDiffs = 0, eventDiffs = 0;
  let scored = 0, scoreDiffs = 0, escort = 0;
  for (const entry of index) {
    if (args.scenario && args.scenario !== entry.name) { continue; }
    const trace = JSON.parse(
      fs.readFileSync(path.join(args.traces, entry.name+'.json'), 'utf8'));
    const r = checkTrace(objects, physics, enemyData, convoyData, sounds, score,
                         trace, args.verbose);
    scenarios++;
    steps += r.steps; bad += r.diffs.length; asked += r.asked; played += r.played;
    drifted += r.drifted; driftedDiffs += r.driftedDiffs;
    eventDiffs += r.eventDiffs;
    scored += r.scored; scoreDiffs += r.scoreDiffs; escort += r.escort;
    if (!r.diffs.length) { clean++; }
    console.log((r.diffs.length ? '✗ ' : '✓ ')+entry.name.padEnd(11)
                +String(r.steps).padStart(5)+' průchodů, '
                +String(r.asked).padStart(4)+' se zvukem, '
                +String(r.diffs.length).padStart(4)+' rozdílů'
                +(r.eventDiffs ? ' (+'+r.eventDiffs+' v bitech výstřelu a nárazu, M4)' : '')
                +(r.driftedDiffs ? ' ('+r.driftedDiffs+' na posunutém generátoru)' : '')
                +' — '+entry.note);
  }
  console.log('\n'+scenarios+' scénářů, '+steps+' průchodů, '+asked
              +' z nich si v originálu o zvuk řeklo, **'+bad+' rozdílů** '
              +'v masce žádanky; '+clean+' scénářů sedí do posledního bitu. '
              +'Port sám přehrál '+played+' efektů; v '+drifted+' průchodech '
              +'se rozešlo semínko generátoru (kreslení, §16) a '+driftedDiffs
              +' rozdílů padlo na ně.\nBity výstřelu a nárazu se tímhle '
              +'matcherem **ověřit nedají** a hlásí se jen pro pořádek ('
              +eventDiffs+' rozešlých): říkají, jestli se událost stala, a to '
              +'je M3/M4 – navíc tři počítadla nabíjení hlavní v záznamu '
              +'nejsou, takže se port po pár stech průchodech s originálem '
              +'rozejde v tom, kdy může vystřelit. Měří je matchphysics.js a '
              +'matchobjects.js.\nBody: '+scored+'× přičetl port tolik co '
              +'originál a '+scoreDiffs+'× ne (a jsou to tytéž průchody jako '
              +'rozdíly výš – port v nich zabil o průchod jinam); '+escort
              +'× přičetl originál deset bodů za doprovod Lasertronu ($9BF3), '
              +'a to pravidlo port zatím nemá (data/score.json `open`).');
  process.exit(bad ? 1 : 0);
}

main();
