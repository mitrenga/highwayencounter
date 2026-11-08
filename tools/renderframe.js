#!/usr/bin/env node
/**
 * Vykreslí snímek hry do PNG – kontrola očima, že se celý řetěz remaku složí
 * i bez prohlížeče.
 *
 *   ./tools/renderframe.js [--out build/gfx] [--frames 1,50,100]
 *
 * Běží `app/gameWorker.js` (worker, 50,08 Hz) a `app/screenComposer.js` (panel
 * z `data/panel.json`) a skládá obrazovku tak, jak ji uvidí hráč: hrací plocha
 * 256 × 152 nahoře, panel 256 × 40 dole.
 *
 * Na ploše je od M2 všechno, co v ní má být: kulisa zóny, sprity a jejich
 * řazení do hloubky, a od té doby, co je změřený **obsah zón**
 * (`data/highway.json`, `data/zones.json`), i barely, zdi a nepřátelé – zóna
 * se plní z tabulky dat silnice týmž pravidlem jako v originálu. Worker k tomu
 * posílá stav silnice (řízeného Vortona, výstřely, předměty), počítadlo `ZONE`
 * se mění podle toho, kam Vorton dojel, a od M6 s ním jde matice srážek
 * a hodiny hry (`TIME`). Smysl téhle kontroly je, že sedí geometrie, že panel
 * je bajt po bajtu ten z originálu a že se celý řetěz (worker → render) složí
 * i bez prohlížeče.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const url = require('url');
const vm = require('vm');
const zlib = require('zlib');

const ROOT = path.join(__dirname, '..');
const load = (name) => JSON.parse(fs.readFileSync(path.join(ROOT, 'data', name+'.json'), 'utf8'));

function writePNG(file, rgba, width, height) {
  const raw = Buffer.alloc((width*3+1)*height);
  let pos = 0;
  for (let y = 0; y < height; y++) {
    raw[pos++] = 0;
    for (let x = 0; x < width; x++) {
      const source = (y*width+x)*4;
      raw[pos++] = rgba[source];
      raw[pos++] = rgba[source+1];
      raw[pos++] = rgba[source+2];
    }
  }
  const chunk = (tag, payload) => {
    const length = Buffer.alloc(4);
    length.writeUInt32BE(payload.length);
    const body = Buffer.concat([Buffer.from(tag), payload]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(zlib.crc32 ? zlib.crc32(body) : crc32(body));
    return Buffer.concat([length, body, crc]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  fs.writeFileSync(file, Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]),
    chunk('IHDR', header),
    chunk('IDAT', zlib.deflateSync(raw, {level: 9})),
    chunk('IEND', Buffer.alloc(0)),
  ]));
}

let table = null;
function crc32(buffer) {
  if (!table) {
    table = new Int32Array(256);
    for (let i = 0; i < 256; i++) {
      let c = i;
      for (let k = 0; k < 8; k++) { c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1); }
      table[i] = c;
    }
  }
  let crc = -1;
  for (let i = 0; i < buffer.length; i++) {
    crc = (crc >>> 8) ^ table[(crc ^ buffer[i]) & 0xFF];
  }
  return (crc ^ -1) >>> 0;
}

function startWorker(onMessage) {
  const sandbox = {
    console, performance: {now: () => Date.now()},
    setTimeout: () => 0, clearTimeout: () => {},
    postMessage: onMessage,
    importScripts(name) {
      vm.runInContext(fs.readFileSync(path.join(ROOT, 'app', name.split('?')[0]), 'utf8'),
                      context, {filename: name});
    },
  };
  sandbox.self = sandbox;
  sandbox.location = {search: ''};
  const context = vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'app/gameWorker.js'), 'utf8'), context,
                  {filename: 'gameWorker.js'});
  return {send: (message) => sandbox.onmessage({data: message})};
}

async function main() {
  const args = process.argv.slice(2);
  const outArg = args.indexOf('--out');
  const out = outArg >= 0 ? args[outArg+1] : path.join(ROOT, 'build/gfx');
  // ovládání, ať se dá vykreslit i jízda: --keys accelerate,right
  const keysArg = args.indexOf('--keys');
  const controls = keysArg >= 0 ? args[keysArg+1].split(',') : [];
  const framesArg = args.indexOf('--frames');
  const wanted = (framesArg >= 0 ? args[framesArg+1] : '1,50')
                 .split(',').map((value) => parseInt(value, 10));

  global.atob = (data) => Buffer.from(data, 'base64').toString('binary');
  // screenComposer.js importuje ZXVideoRAM ze svision, takže hlavička potřebuje
  // window.srcVersion – shim se musí načíst jako první (R-001)
  await import(url.pathToFileURL(path.join(ROOT, 'app/svision/tools/nodeEnv.mjs')).href);
  const { ScreenComposer } = await import(url.pathToFileURL(path.join(ROOT, 'app/screenComposer.js')).href);
  const { ZXVideoRAM } = await import(url.pathToFileURL(path.join(ROOT, 'app/svision/js/platform/canvas2D/zx/zxVideoRAM.js')).href);

  // M8: číslice SCORE a HIGH a ukazatel POWER (data/score.json)
  // M2: obraz silnice po zónách, sprity a projekce
  const render = new ScreenComposer(load('panel'), load('panelfields'),
                                  load('font'), load('ending'), load('score'),
                                  load('scenery'), load('spriteframes'),
                                  load('projection'));

  let last = null;
  const worker = startWorker((message) => { if (message.id === 'frame') { last = message; } });
  worker.send({id: 'init', initData: {headless: true, zone: 30, vortons: 5,
                                      physics: load('physics'),
                                      objects: load('objects'),
                                      convoy: load('convoy'),
                                      enemies: load('enemies'),
                                      ending: load('ending'),
                                      // M8: zvuk a bodování
                                      sounds: load('sounds'),
                                      score: load('score'),
                                      // M2: projekce, animace a sprity výstřelů
                                      projection: load('projection'),
                                      // M2: co na silnici stojí a jak se tím
                                      // zóna plní
                                      highway: load('highway'),
                                      zones: load('zones')}});

  if (controls.length) {
    const message = {id: 'controls'};
    controls.forEach((name) => { message[name.trim()] = true; });
    worker.send(message);
  }
  fs.mkdirSync(out, {recursive: true});
  // the highway and the panel composed into one memory, the way the machine holds them
  const memory = new ZXVideoRAM();
  const screen = new Uint8ClampedArray(256*192*4);
  for (let frame = 0; frame <= Math.max.apply(null, wanted); frame++) {
    worker.send({id: 'tick'});
    if (wanted.indexOf(frame) < 0) { continue; }
    render.composeInto(memory, {vorton: last.vorton, convoy: last.convoy,
                                objects: last.objects, ending: last.ending,
                                zone: last.zone, cam: last.cam,
                                anim: last.anim});
    render.composePanelInto(memory, {zone: last.zone, score: last.score, high: last.high,
                               power: last.power, time: last.time,
                               vortons: last.vortons,
                               vortonMarks: last.vortonMarks,
                               endingMessage: !!(last.ending
                                                 && last.ending.panelMessage),
                               endingPanel: !!(last.ending
                                                 && last.ending.panelBlank)});
    memory.paint(screen, false);
    const file = path.join(out, 'frame'+String(frame).padStart(3, '0')+'.png');
    writePNG(file, screen, 256, 192);
    console.log('%s  snimek %s  ZONE %d  konvoj %s  ikony %s',
                path.relative(ROOT, file), String(frame).padStart(3), last.zone,
                last.objects.slice(1, 6).map((e) => e ? e.y : '-').join(','),
                last.vortonMarks.map((m) => m ? '#' : '.').join(''));
  }
}

main().catch((error) => { console.error(error); process.exit(1); });
