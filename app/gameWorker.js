// begin code

/**
 * Highway Encounter game worker.
 *
 * The tick is the frame rate of the original machine: 3.5 MHz / 69888 T states
 * = 50.08 Hz, because the game logic hangs off the ULA interrupt
 * (sources/docs/hw_notes.md, ZADANI chap. 1). One tick is one step of the
 * original's main loop.
 *
 * The controlled Vorton's physics is here as of M3 — not in this file, but in
 * vortonPhysics.js, driven by the constants tools/dumpphysics.py measured on
 * the running original (data/physics.json) and checked step by step against
 * recorded runs of it (tools/matchphysics.js). The road he drives on is M4 and
 * lives in highwayObjects.js: the collision box, the shoving, the shots and
 * the zone the camera shows, all measured the same way
 * (tools/dumpobjects.py, tools/matchobjects.js). The convoy of four automatic
 * Vortons and the Lasertron came with M5 (highwayConvoy.js), the four families
 * of enemy and the game's clock with M6 (highwayEnemies.js), and the end of
 * the game and the harder pass after it with M7 (highwayEnding.js). Still
 * missing and **not** invented here: **what stands in each zone** — M7 found
 * where that table lives ($7B00, disasm_notes.md chap. 17) but not yet how a
 * zone is loaded out of it (M2) — and the **scoring**, which the original does
 * not add up as you go and which has not been found (M6, ZADANI chap. 4).
 *
 * The one thing the shell already takes seriously is that the world is **not**
 * a grid of rooms: the whole road is simulated whether or not the camera is
 * looking at it (ZADANI chap. 3.3), so the state kept here is the state of the
 * road, not of a visible screen. The camera is simply the zone the controlled
 * Vorton stands in — it does not scroll, it jumps, and it jumps back if he
 * drives back (measured, disasm_notes.md chap. 6 and 14).
 *
 * ### The tick is not the step
 *
 * The timer here still runs at the machine's 50.08 Hz, but a **step of the
 * game** is one pass of the original's main loop, and that loop is not tied to
 * the interrupt: a pass takes 2.4 to 3.5 frames and its length moves with how
 * much there is to draw (sources/docs/disasm_notes.md chap. 11).
 *
 * M9 measured how long: the length of the next pass is asked of
 * highwayCadence.js after every step, out of what that pass actually did —
 * how many records it drew, how many are alive on the road, what sound it
 * plays and whether the play area is repainted. The rule behind it is a
 * **governor** in the original's own code, an empty delay loop that pads a
 * pass with fewer than eight drawn records (data/cadence.json,
 * tools/dumpcadence.py). Without data/cadence.json the worker falls back to
 * the old constant, `stepLength.framesPerStepMean` from data/physics.json.
 *
 * ★ One measured thing is **deliberately not reproduced**: the pass in which
 * the original wipes and rebuilds the whole play area on entering a zone
 * (712 283 T-states on top, a quarter of a second — data/cadence.json
 * `repaint`, disasm_notes.md §19). The remake draws the new zone in one frame,
 * so waiting through the original's redraw would be a freeze with nothing to
 * show for it; REPAINT_WAIT below keeps the pass at its ordinary length and the
 * zone change is smooth (decided 2026-09-07, ZADANI.md). The cadence model
 * itself still knows the cost — tools/matchcadence.js measures it — only the
 * worker does not wait it out.
 */

var query = (typeof self !== 'undefined' && self.location) ? self.location.search : '';
importScripts('vortonPhysics.js'+query);   // M3: the measured Vorton
importScripts('highwayObjects.js'+query);  // M4: the road and what stands on it
importScripts('highwayConvoy.js'+query);   // M5: the convoy and the Lasertron
importScripts('highwayEnemies.js'+query);  // M6: the enemies and the collision matrix
importScripts('highwayEnding.js'+query);   // M7: the end of the game and the pass after it
importScripts('highwayCadence.js'+query);  // M9: how long a pass of the main loop takes

var TICK_MS = 1000*69888/3500000;     // 50.08 Hz, the ULA interrupt rate
var ZONES = 30;                       // the road runs from ZONE 30 to Zone Zero
var FIRST_ZONE = ZONES;
var VORTONS = 5;
// M2: the camera coordinate the original measures visibility from is the start
// of the zone's window plus 128 — measured for all 31 zones (w($8F09), §7/§8)
var CAMERA_OFFSET = 128;

var state = null;
var physics = null;                   // VortonPhysics, built from data/physics.json
var world = null;                     // HighwayWorld, built from data/objects.json
var stepFrames = 0;                   // frames until the next step of the game
var meanStepFrames = 0;               // the fallback: the measured mean (M3)
var cadence = null;                   // HighwayCadence, built from data/cadence.json
var REPAINT_WAIT = false;             // wait through the original's zone redraw? see the note above
var timer = 0;
var enemyData = null;
var ending = null;                    // HighwayEnding, built from data/ending.json
var scoreData = null;                 // data/score.json (M8): what scores what
var projData = null;                  // data/projection.json (M2): the drawing
var killAward = 0;                    // body za zničený záznam rodiny 1 až 6
var killBoundary = 7;                 // hranice rodin, které se dají zničit
var finishAward = 0;                  // body za dohrání
var data = null;                      // the init data, kept for the next pass
var flight = null;                    // M9: the test flight's keys, one per frame
var lastTime = false;
var accumulator = 0;

function reset() {
  clearTimeout(timer);
  timer = 0;
  lastTime = false;
  accumulator = 0;
  state = {
    running: false, paused: false, headless: false,
    frame: 0, score: 0, high: 0, zone: FIRST_ZONE, vortons: VORTONS,
    // POWER and TIME are bars on the panel. M8 measured POWER: it is the
    // gun's magazine, one cell per barrel, and it empties while that barrel's
    // shot is in flight (data/score.json `power`) — not the Vorton's energy,
    // which is what ZADANI chap. 3.7 guessed. TIME is M6's clock.
    power: 1, time: 1,
    input: {left: false, right: false, accelerate: false, decelerate: false,
            fire: false},
    // the controlled Vorton: the state vortonPhysics.js steps — position along
    // the world coordinate, heading 0-7, speed, animation phase and the
    // throttle's shift register
    vorton: physics ? physics.spawn() : {x: 0, y: 0, dir: 0, speed: 0, phase: 0,
                                         cls: 0, kind: 0x0E,
                                         timer: 0, turnPhase: 0},
    // what stands on the road, as the original's own entity table
    objects: [],
    // which of the five icons on the panel are filled in — measured, that is
    // which Vortons have been under control, not how many are left
    vortonMarks: [true, false, false, false, false],
    stepAccumulator: 0,
    convoy: [],
    // M2: the animation byte of each kind — which of the four frames of an
    // enemy is up. The original keeps one per kind at $8F00 + kind and steps
    // it every few passes; the cadence is measured, kind by kind
    // (data/projection.json `sprite.animation`, tools/dumpproj.py).
    anim: {},
    animState: {},
    // M6: the game's clock. $8F1A counts one down every pass of the main loop
    // and, when it reaches nothing, takes a notch off the TIME bar; the game
    // is over when the bar runs out (tools/dumpenemies.py measured 3 notches
    // of 3500 passes, so about eight and a half minutes of play).
    timeCounter: enemyData ? enemyData.time.reload : 0,
    timeNotches: enemyData ? enemyData.time.ticks : 0,
    // M7: how many games have been finished. The original keeps it at $8F89,
    // counts it up when the end sequence is over and stops at two; every count
    // adds one to the speed of every enemy on the road (tools/dumpending.py).
    passCount: state ? state.passCount : 0,
    ending: null,
    // M8: what the passes of this frame asked to be heard. The original's own
    // request byte lives in the world (data/sounds.json); this is only the
    // queue on its way to the main thread.
    sounds: [],
    gameOverPosted: false,
    // M9: what the cadence needs to say how long the pass just taken lasts
    // (highwayCadence.js) — how much was drawn, how much is alive, the sound
    // the previous pass asked for, and whether the play area is repainted
    drawnCount: 0,
    liveCount: 0,
    pendingSound: false,
    playingSound: false,
    repaintPass: false
  };
} // reset

/**
 * One frame of the machine. A **step of the game** is one pass of its main
 * loop, which is slower than a frame and not a whole number of them, so the
 * steps are counted off against how long that pass takes — which M9 measured
 * and which is asked of the cadence after every step (see the note above).
 */
function tick() {
  state.frame++;
  if (!physics || !stepFrames) {
    return;
  }
  // M7: two parts of the end sequence do not run the main loop at all — the
  // ship breaking up and the pause after it are drawn straight to the screen,
  // and the original measures them in frames. So they are ticked here, where
  // the frames are, and not in step(), where the passes are.
  if (ending && ending.running && ending.frame(world)) {
    state.ending = ending.view;
    return;
  }
  state.stepAccumulator++;
  while (state.stepAccumulator >= stepFrames) {
    state.stepAccumulator -= stepFrames;
    step();
    stepFrames = nextStepFrames();
  }
} // tick

/**
 * How many frames the pass just taken lasts — M9's measured cadence.
 *
 * Everything it needs the worker already knows. **Drawn** is the length of the
 * list the original builds at $8D52: the records inside the camera's window
 * that are not standing scenery, counted here exactly the way screenComposer.js
 * builds the same list. **Live** is every record on the road, seen or not,
 * because the whole road is stepped. The **sound** is the one this pass asked
 * for, which the original plays at the end of the *next* pass, so it is kept
 * for one step. And a **repaint** is a zone change (the other case, losing a
 * Vorton, is not in the port yet).
 * @returns {number} Frames of the machine's 50.08 Hz interrupt.
 */
function nextStepFrames() {
  if (!cadence) {
    return meanStepFrames;
  }
  return cadence.passFrames(state.drawnCount, state.liveCount,
                            state.playingSound, REPAINT_WAIT && state.repaintPass);
} // nextStepFrames

/**
 * How many records the pass would have put in the original's draw list.
 *
 * The rule is the original's own ($985A, disasm_notes.md chap. 8): the table
 * is walked from the top, an empty slot is skipped, the records whose +6 byte
 * says they stand still are skipped — those are painted into the zone's
 * picture once — and so is anything further than 255 from the camera.
 * @returns {number} The length of the list.
 */
function countDrawn() {
  if (!world) { return 0; }
  var skip = (projData && projData.depth && projData.depth.skip
              && projData.depth.skip.field6) || ['$16', '$19'];
  var stands = [];
  for (var k = 0; k < skip.length; k++) {
    stands.push(parseInt(String(skip[k]).replace('$', ''), 16));
  }
  var cam = world.windowStart + CAMERA_OFFSET;
  var drawn = 0;
  for (var i = 0; i < world.entities.length; i++) {
    var e = world.entities[i];
    if (!e) { continue; }
    if (stands.indexOf((e.cls >> 8) & 0xFF) >= 0) { continue; }
    if (((e.y - cam) & 0xFFFF) > 0xFF) { continue; }
    drawn++;
  }
  return drawn;
} // countDrawn

/** How many records are alive on the road, whether the camera sees them or not. */
function countLive() {
  if (!world) { return 0; }
  var live = 0;
  for (var i = 0; i < world.entities.length; i++) {
    if (world.entities[i]) { live++; }
  }
  return live;
} // countLive

/**
 * One pass of the original's main loop, for the whole road.
 *
 * highwayObjects.js owns it: it steps the Vorton through vortonPhysics, decides
 * what stopped him and what that costs him, shoves what can be shoved, flies
 * the shots and moves the camera to the zone he is standing in. What it cannot
 * do yet is put anything **into** a zone: the road's own data has not been
 * found (M2), so a game started here drives an empty road.
 */
/**
 * Steps the animation byte of every kind, the way the original steps its own.
 *
 * Measured over the whole road (tools/dumpproj.py): four frames two apart, held
 * three or four passes each, some kinds going round in a circle and some
 * swinging back and forth — and the shot's, which flips every single pass.
 */
function stepAnimation() {
  var rules = projData && projData.sprite && projData.sprite.animation;
  if (!rules) { return; }
  for (var key in rules) {
    var rule = rules[key];
    if (!rule.holdPasses || !rule.top) { continue; }
    var at = state.animState[key];
    if (!at) { at = state.animState[key] = {value: 0, held: 0, up: true}; }
    if (++at.held < rule.holdPasses) { continue; }
    at.held = 0;
    var step = rule.step || 2;
    if (rule.pattern === 'pingpong') {
      if (at.up && at.value + step > rule.top) { at.up = false; }
      if (!at.up && at.value - step < 0) { at.up = true; }
      at.value += at.up ? step : -step;
    } else {
      at.value = (at.value + step > rule.top) ? 0 : at.value + step;
    }
    // the byte the renderer reads is keyed by the kind, as a number
    state.anim[String(parseInt(key.replace('$', ''), 16))] = at.value;
  }
} // stepAnimation

function step() {
  stepAnimation();
  // M9: what this pass costs is worked out at the end of it; a pass that
  // leaves early (the end sequence drawing rather than running) is an
  // ordinary one, so the surcharge does not carry over
  state.repaintPass = false;
  // The world's window and the generator's seed are the two things the
  // original keeps outside the entity table; here nothing else moves them, so
  // the window follows the zone the camera is in and the seed simply runs on.
  if (world.enemies) {
    world.windowStart = (world.zone - 1) * world.zoneLength;
    // M2: with the road's own data the end of the table is where the zone's
    // load left it (the original's $FF), not the end of the array
    if (!world.roadTable) { world.endSlot = HighwayWorld.SLOTS; }
  }
  // M7: once the Lasertron reaches the end of the road the game stops taking
  // the player's input and starts scripting its own — the end sequence is the
  // same main loop with the keys written into it, so it is stepped here, not
  // played back somewhere else (tools/dumpending.py, data/ending.json).
  var keys = VortonPhysics.keysOf(state.input);
  // M9: a test flight drives the game instead of the player — the keys a real
  // player's recording had the original read, one entry per frame of the
  // machine (testFlightPage.php, tools/dumpflight.py). It runs out silently.
  if (flight) {
    keys = state.frame < flight.length ? flight[state.frame] : 0;
  }
  var running = ending && ending.running;
  if (running) {
    var beat = ending.step(world);
    keys = beat.keys;
    state.ending = beat.view;
    if (beat.done) {
      // finishing the game is worth a thousand, and the original pays it in
      // the sequence itself, right where it asks for the explosion ($A632)
      state.score += finishAward;
      startNextPass();
      return;
    }
    if (!beat.loop) {
      return;                           // the sequence is drawing, not running
    }
  } else if (ending && ending.triggered(world.zone, lasertronY())) {
    state.ending = ending.start(world);
    running = true;
    keys = 0;
  }
  var out = world.step(keys);
  // M8: what the pass asked to be heard. The original plays it synchronously
  // at the end of the pass and clears its request byte; here the name and the
  // seed the explosion drew from travel to the main thread, which synthesises
  // the pulses (app/soundEffects.js, data/sounds.json).
  if (out.play) { state.sounds.push({name: out.play, seed: out.playSeed}); }
  // M8: the score. The original adds 250 for a record of family 1 to 6 sent
  // into the dying animation, and 1000 for finishing (tools/dumpscore.py); the
  // ten points it pays for escorting the Lasertron are read from its code but
  // not measured into a rule yet, so they are not invented here.
  if (scoreData && out.destroyed && out.destroyed.length) {
    for (var d = 0; d < out.destroyed.length; d++) {
      if (out.destroyed[d] >= 1 && out.destroyed[d] < killBoundary) {
        state.score += killAward;
      }
    }
  }
  // the game's own clock does not tick while the sequence runs: the passes it
  // spends go through $A8C5, which is the loop without the countdown
  if (enemyData && state.timeNotches > 0 && !running) {
    if (--state.timeCounter <= 0) {
      state.timeCounter = enemyData.time.reload;
      state.timeNotches--;
    }
    // what the panel's bar shows: how much of the game's clock is left
    state.time = (state.timeNotches
                  + state.timeCounter/enemyData.time.reload)/enemyData.time.ticks;
    if (state.timeNotches <= 0) { state.gameOverPosted = true; }
  }
  // M7: the end sequence sends the whole convoy into the dying animation and
  // then takes the records out of the table, so from that point there is no
  // controlled Vorton at all. The last one he stood at is kept, because the
  // panel and the renderer are fed from here and the sequence has its own
  // thing to show by then.
  // M8: POWER is the gun's magazine — one cell per barrel, empty while that
  // barrel's shot is in flight. The original counts it with a pointer into the
  // attributes ($8F18); here it is the same count, taken off the table
  // (data/score.json `power`, tools/dumpscore.py).
  if (scoreData && scoreData.power) {
    var flying = 0;
    for (var f = 0; f < world.entities.length; f++) {
      if (world.entities[f] && world.isShot(world.entities[f])) { flying++; }
    }
    state.power = Math.max(0, scoreData.power.cells.length-flying)
                  / scoreData.power.cells.length;
  }
  state.vorton = world.player() || state.vorton;
  state.objects = world.entities;
  // M9: what this pass cost. The original repaints the whole play area when
  // the camera enters another zone, and that pass takes thirteen frames
  // instead of three (data/cadence.json `repaint`). Noted here for the record
  // and for the cadence model; whether the worker waits it out is REPAINT_WAIT.
  state.repaintPass = state.zone !== ZONES + 1 - out.zone;
  state.zone = ZONES + 1 - out.zone;
  state.drawnCount = countDrawn();
  state.liveCount = countLive();
  // The effect a pass asks for is played at the end of the **next** one, and
  // it is that next one the loop waits through — the effect is played inside
  // it (tools/dumpcadence.py). So the pass that just ran is the one that plays
  // what the pass before it asked for.
  state.playingSound = state.pendingSound;
  state.pendingSound = out.play || false;
  if (world.convoy) {
    // the panel's row of Vortons: an icon fills in when the player starts
    // driving that Vorton and stays filled (tools/dumppanelfields.py)
    for (var i = 0; i < VORTONS; i++) {
      state.vortonMarks[i] = world.controlledSlots.indexOf(i) >= 0;
    }
  }
} // step

/**
 * Builds the road and puts the convoy on it, exactly where the original starts
 * a game — and, from the second game on, one step faster.
 *
 * M5: without data/convoy.json the road runs without a convoy; M6: without
 * data/enemies.json the enemies are not stepped. Neither is guessed at.
 * @param {number} passes - How many games have been finished already.
 */
function buildWorld(passes) {
  world = new HighwayWorld(data.objects, physics, data.convoy, data.enemies,
                           data.sounds, data.projection);
  reset();
  state.passCount = passes;
  // his kind word and kind byte come with the measured spawn (data/physics.json)
  world.put(HighwayWorld.PLAYER, state.vorton);
  if (data.convoy) {
    // where the original's convoy stands when a game begins, measured off the
    // entity table of the running original (tools/dumpconvoy.py)
    data.convoy.start.convoy.forEach(function (c) {
      world.put(c.slot, c);
    });
  }
  // M2: the road's own data and the rule that loads a zone out of it
  // (data/highway.json, data/zones.json). Without either the world stays as
  // M4 left it — a road with a convoy on it and nothing else.
  world.setRoad(data.highway, data.zones);
  // M7: every finished game adds one to the speed of everything on the road
  // whose family is below five — the enemies, and not the mines. The original
  // does it to its own table of the road's data ($7B00), and as of M2 so does
  // this: to the table itself, before the first zone is loaded out of it.
  if (ending && passes) {
    ending.harden(world.roadTable || world.entities, passes,
                  data.enemies ? data.enemies.familyMask : undefined);
  }
  world.zone = world.zoneOf(state.vorton.y);
  // ...and the first zone is loaded the same way every other one is
  world.enterZone(world.zone);
  state.vorton = world.player();
  state.zone = ZONES + 1 - world.zone;
} // buildWorld

/**
 * The Lasertron's place on the road — what the end sequence watches for.
 * @returns {number} Its `y`, or -1 while there is no convoy.
 */
function lasertronY() {
  if (!world || !world.convoy) { return -1; }
  for (var i = 0; i < world.entities.length; i++) {
    var e = world.entities[i];
    if (e && e.cls === world.convoy.lasertronClass) { return e.y; }
  }
  return -1;
} // lasertronY

/**
 * What the original does when the sequence is over: count the finished game
 * (to a ceiling of two), start again from the first zone, and make every
 * enemy on the road one step faster for each game finished.
 */
function startNextPass() {
  var passes = ending.nextPassCount(state.passCount);
  var kept = {score: state.score, high: state.high, headless: state.headless,
              vortons: state.vortons};
  buildWorld(passes);
  state.score = kept.score;
  state.high = kept.high;
  state.headless = kept.headless;
  state.vortons = kept.vortons;
  state.running = true;
  ending.running = false;
  ending.finished = false;
} // startNextPass

function postFrame() {
  var s = state;
  postMessage({
    id: 'frame',
    frame: s.frame,
    score: s.score,
    high: s.high,
    zone: s.zone,
    vortons: s.vortons,
    vortonMarks: s.vortonMarks.slice(),
    power: s.power,
    time: s.time,
    // cls and kind go with him: the renderer picks his eight rotations by the
    // kind byte ($0E) and would draw him facing one way without it
    vorton: {x: s.vorton.x, y: s.vorton.y, dir: s.vorton.dir,
             speed: s.vorton.speed, phase: s.vorton.phase,
             cls: s.vorton.cls, kind: s.vorton.kind},
    // everything the road holds, in the original's own table order; the
    // renderer has nothing to draw them with until M2 has the sprites
    objects: s.objects.map(function (e) {
      return e && {x: e.x, y: e.y, dir: e.dir, speed: e.speed, phase: e.phase,
                   cls: e.cls, kind: e.kind};
    }),
    convoy: s.convoy.slice(),
    // M2: what the renderer needs to place them. The camera is the coordinate
    // the original measures visibility from — the zone's window plus 128
    // (disasm_notes.md chap. 7 and 8) — and `anim` says which frame each kind
    // is showing.
    cam: world ? world.windowStart + CAMERA_OFFSET : 0,
    anim: s.anim,
    // M7: what the end sequence is showing, if it runs — the phase it is in,
    // the panel's LASERTRON ACTIVATED, the attribute the play area is flooded
    // with and the text it sets with the game's own character set
    ending: s.ending,
    passCount: s.passCount,
    sounds: state.sounds.splice(0, state.sounds.length),
    state: s.gameOverPosted ? 'gameOver' : 'game'
  });
  if (s.gameOverPosted && s.running) {
    postMessage({id: 'gameOver', score: s.score});
    s.running = false;
    clearTimeout(timer);
  }
} // postFrame

/**
 * Expands the test flight's run-length script into one key mask per frame.
 * @param {string} script - Runs of `NNc`, the count optional.
 * @returns {Array<number>} The key mask of every frame of the flight.
 */
function expandFlight(script) {
  var alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUV';
  var out = [];
  for (var i = 0; i < script.length; ) {
    var count = 1;
    if (script[i] >= '0' && script[i] <= '9' && i+2 < script.length) {
      count = parseInt(script.substr(i, 2), 10);
      i += 2;
    }
    var mask = alphabet.indexOf(script[i]);
    i++;
    if (mask < 0) { continue; }
    for (var n = 0; n < count; n++) { out.push(mask); }
  }
  return out;
} // expandFlight

function loop() {
  var now = (typeof performance !== 'undefined') ? performance.now() : Date.now();
  if (lastTime === false) {
    lastTime = now;
  }
  accumulator = Math.min(250, accumulator+now-lastTime);
  lastTime = now;
  var ticked = false;
  while (accumulator >= TICK_MS) {
    tick();
    accumulator -= TICK_MS;
    ticked = true;
  }
  if (ticked) {
    postFrame();
  }
  if (state.running && !state.paused) {
    timer = setTimeout(loop, Math.max(1, TICK_MS-accumulator));
  }
} // loop

reset();

onmessage = function (event) {
  var msg = event.data;
  switch (msg.id) {
    case 'init':
      var initData = msg.initData || {};
      if (!initData.physics) {
        postMessage({id: 'error',
                     message: 'chybi data/physics.json (tools/dumpphysics.py)'});
        break;
      }
      physics = new VortonPhysics(initData.physics);
      meanStepFrames = initData.physics.stepLength.framesPerStepMean;
      stepFrames = meanStepFrames;
      // M9: how long a pass of the main loop takes, measured
      // (tools/dumpcadence.py). Without it the worker keeps stepping on the
      // measured mean, which is what it did before M9.
      cadence = initData.cadence ? new HighwayCadence(initData.cadence) : null;
      if (!initData.objects) {
        postMessage({id: 'error',
                     message: 'chybi data/objects.json (tools/dumpobjects.py)'});
        break;
      }
      data = initData;
      enemyData = initData.enemies || null;
      // M7: the end of the game and the pass after it. Like every milestone
      // before it, it is only there when its measured data is
      // (tools/dumpending.py).
      ending = initData.ending
               ? new HighwayEnding(initData.ending, meanStepFrames) : null;
      // M8: what scores what, measured off the original (tools/dumpscore.py).
      // Without it the game keeps no score at all rather than inventing one.
      scoreData = initData.score || null;
      if (scoreData) {
        for (var a = 0; a < scoreData.awards.length; a++) {
          if (scoreData.awards[a].what === 'zánik') {
            killAward = scoreData.awards[a].points;
          }
          if (scoreData.awards[a].what === 'dohráno') {
            finishAward = scoreData.awards[a].points;
          }
        }
      }
      if (initData.sounds && initData.sounds.dying) {
        killBoundary = initData.sounds.dying.boundary;
      }
      projData = initData.projection || null;
      buildWorld(0);
      state.headless = !!initData.headless;
      state.zone = (initData.zone === undefined) ? FIRST_ZONE : initData.zone;
      state.vortons = (initData.vortons === undefined) ? VORTONS : initData.vortons;
      state.running = true;
      if (!state.headless) {
        loop();
      }
      postFrame();
      break;
    // M9: the test flight. `script` is the run-length string tools/dumpflight.py
    // writes out of the RZX recording: runs of `NNc`, `c` a base32 digit of the
    // original's own key mask ($8F14). Sending it without a script stops it.
    case 'testFlight':
      flight = msg.script ? expandFlight(msg.script) : null;
      break;
    case 'controls':
      var input = state.input;
      input.left = !!msg.left;
      input.right = !!msg.right;
      input.accelerate = !!msg.accelerate;
      input.decelerate = !!msg.decelerate;
      input.fire = !!msg.fire;
      break;
    case 'pause':
      state.paused = true;
      clearTimeout(timer);
      break;
    case 'continue':
      if (state.running) {
        state.paused = false;
        lastTime = false;
        clearTimeout(timer);
        if (!state.headless) {
          loop();
        }
      }
      break;
    case 'tick':
      if (state.running) {
        tick();
        postFrame();
      }
      break;
    case 'reset':
      reset();
      break;
  }
};
