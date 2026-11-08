#!/usr/bin/env node
/**
 * Porovná **hrací plochu remaku s originálem, pixel po pixelu i s atributy**
 * (M2).
 *
 *   PYTHONPATH=tools/vendor ./tools/tracescreen.py
 *   ./tools/matchscreen.js [build/vtraces/screen-demo.json]
 *
 * Ze záznamu se vezme stav, který originál v tom průchodu měl – tabulka
 * objektů, kamera, číslo zóny a animační bajty – a týmž stavem se nechá
 * vykreslit `app/screenComposer.js`. Porovnává se výsledek: bitmapa hrací plochy
 * (4864 B) a jejích 608 atributů proti tomu, co má originál na obrazovce.
 *
 * Nekreslí se nic, co by remake dopočítával jinak než originál: co je vidět,
 * v jakém pořadí se to kreslí a který rámec to má, si počítá renderer sám –
 * ze záznamu jde jen tabulka a kamera. Animace a řazení se tím testují taky.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const url = require('url');

const ROOT = path.join(__dirname, '..');
const COLS = 32, ROWS = 19, CELL = 8;
const load = (name) => JSON.parse(fs.readFileSync(path.join(ROOT, 'data', name+'.json'), 'utf8'));
const decode = (base64) => Buffer.from(base64, 'base64');

async function main() {
  const traceFile = process.argv[2]
    || path.join(ROOT, 'build/vtraces/screen-demo.json');
  const trace = JSON.parse(fs.readFileSync(traceFile, 'utf8'));

  global.atob = (data) => Buffer.from(data, 'base64').toString('binary');
  // screenComposer.js importuje ZXVideoRAM ze svision, takže hlavička potřebuje
  // window.srcVersion – shim se musí načíst jako první (R-001)
  await import(url.pathToFileURL(path.join(ROOT, 'app/svision/tools/nodeEnv.mjs')).href);
  const { ScreenComposer } = await import(url.pathToFileURL(path.join(ROOT, 'app/screenComposer.js')).href);
  const { ZXVideoRAM } = await import(url.pathToFileURL(path.join(ROOT, 'app/svision/js/platform/canvas2D/zx/zxVideoRAM.js')).href);
  const render = new ScreenComposer(load('panel'), load('panelfields'),
                                  load('font'), load('ending'), load('score'),
                                  load('scenery'), load('spriteframes'),
                                  load('projection'));

  const memory = new ZXVideoRAM();
  const rgba = new Uint8ClampedArray(COLS*CELL*ROWS*CELL*4);
  const want = new Uint8ClampedArray(rgba.length);
  let passes = 0, differing = 0, pixels = 0, worst = null;
  // kolikátý průchod v zóně to je – u prvních se pozná, jestli rozdíly nejsou
  // jen v tom, kdy originál stojící objekty poprvé nakreslí
  const perAge = {};
  let lastZone = null, age = 0;
  const perZone = {};
  const perRow = {};
  // v attract modu si hra přes plochu píše DEMO MODE, a to není součástí obrazu
  // zóny – leží mimo parallelogram a do dat se nedostane (tools/dumpgfx.py)
  const BANNER_ROW = 1;
  let outside = 0;
  for (const frame of trace.frames) {
    // remake: tabulka objektů tak, jak ji posílá worker
    const objects = frame.records.map((r) => r.empty ? null : {
      x: r.x, y: r.y, dir: r.dir, speed: r.speed, phase: r.phase,
      cls: r.cls, kind: r.kind
    });
    render.composeInto(memory, {
      zone: frame.zone, cam: frame.cam, anim: frame.anim,
      vorton: objects[0], objects: objects
    });
    memory.paint(rgba, false, ScreenComposer.PLAY_AREA);
    // originál: jeho vlastní bitmapa a atributy, obarvené týmž ULA kódem
    ZXVideoRAM.paintLinear(want, decode(frame.bitmap), decode(frame.attributes),
                       COLS, ROWS, false);
    let bad = 0;
    for (let i = 0; i < rgba.length; i += 4) {
      if (rgba[i] !== want[i] || rgba[i+1] !== want[i+1]
          || rgba[i+2] !== want[i+2]) {
        bad++;
        const row = Math.floor((i/4/(COLS*CELL))/CELL);
        perRow[row] = (perRow[row] || 0) + 1;
        if (row !== BANNER_ROW) { outside++; }
      }
    }
    if (frame.zone !== lastZone) { lastZone = frame.zone; age = 0; } else { age++; }
    const bucket = age < 4 ? String(age) : '4+';
    perAge[bucket] = perAge[bucket] || {passes: 0, bad: 0};
    perAge[bucket].passes++;
    perAge[bucket].bad += bad;
    passes++;
    pixels += rgba.length/4;
    differing += bad;
    const zone = String(frame.zone);
    perZone[zone] = perZone[zone] || {passes: 0, bad: 0};
    perZone[zone].passes++;
    perZone[zone].bad += bad;
    if (!worst || bad > worst.bad) { worst = {bad: bad, frame: frame.frame, zone: frame.zone}; }
  }

  console.log('%d pruchodu, %d pixelu, rozdilnych %d (%s %%), mimo napis '
              + 'DEMO MODE (znakova radka %d) %d',
              passes, pixels, differing,
              (100*differing/Math.max(1, pixels)).toFixed(3), BANNER_ROW, outside);
  Object.keys(perZone).sort((a, b) => b-a).forEach((zone) => {
    const z = perZone[zone];
    console.log('  zona %s: %d pruchodu, %d rozdilnych pixelu (%s na pruchod)',
                zone, z.passes, z.bad, (z.bad/z.passes).toFixed(1));
  });
  console.log('  podle poradi pruchodu v zone: %s',
              Object.keys(perAge).sort().map((k) =>
                k+': '+perAge[k].bad+' / '+perAge[k].passes+' pruchodu').join(', '));
  const rows = Object.keys(perRow).sort((a, b) => a-b);
  if (rows.length) {
    console.log('  rozdily po znakovych radkach: %s',
                rows.map((r) => r+':'+perRow[r]).join(' '));
  }
  if (worst) {
    console.log('  nejhorsi pruchod: snimek %d, zona %d, %d pixelu',
                worst.frame, worst.zone, worst.bad);
  }
  process.exit(outside ? 1 : 0);
}

main().catch((error) => { console.error(error); process.exit(2); });
