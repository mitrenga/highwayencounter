// begin code

/**
 * The end of the game, and the pass after it (M7).
 *
 * Everything up to M6 could be measured by playing the first zone with
 * scripted keys. This could not: the sequence starts only when the
 * **Lasertron** reaches the end of the road, which is a whole game away. It is
 * measured off the RZX recording of somebody finishing the original
 * (tools/playrzx.py, tools/dumpending.py, data/ending.json), and what came out
 * of it is worth writing down, because none of it is what the reviews assumed:
 *
 * 1. **The Lasertron ends the game, not the player.** Every pass, the main
 *    loop asks whether the zone counter is at least 30 and the Lasertron's `y`
 *    is inside a window at 5484 — 204 units past the start of Zone Zero. The
 *    player does not have to be anywhere near.
 * 2. **The sequence drives the game itself.** It writes what the game "pressed"
 *    that pass ($8F14) and then lets an exact number of **passes of the main
 *    loop** go by. So it is not animation on a timer: it is the game still
 *    running, with the input coming from a script. That is why it can be
 *    replayed here at all.
 * 3. **The five Vortons are consumed, not paraded.** The first thing it does
 *    is send the first five records into the dying animation M6 already
 *    measured — the same $80 in the kind word, the same top bit of the speed —
 *    and then move the table pointer past them, which promotes the Lasertron
 *    to the first record. The "guard of honour" Your Sinclair 19 describes is
 *    the convoy dying, one after another.
 * 4. **Zone Zero is not the last zone.** The Lasertron is given speed 1 and
 *    left to drive, and the sequence waits until the zone copy reaches **36** —
 *    five zones past Zone Zero that a normal game never shows.
 * 5. **The second pass is one counter and one walk of a table.** $8F89 counts
 *    finished games (to a ceiling of two) and the game walks the road's own
 *    data table, adding **1 to the speed** of every record whose family is
 *    below 5. That is the whole of the "harder highway encounter": faster
 *    enemies — and **not** faster mines, which are family 5, just above the
 *    line. Starting a new game walks the table back down again.
 *
 * What this file does not do is draw. The break-up of the alien ship and the
 * scenery of the end zones are graphics, and the projection and the sprites
 * are M2 and M8; the sequence carries them as named states so the renderer can
 * fill them in when there is something to fill them with. The text it does
 * carry: M7 found the character set (data/font.json, tools/dumpfont.py), so
 * PREPARE YOURSELF FOR THE NEXT HIGHWAY ENCOUNTER! is set by
 * app/screenComposer.js with the original's own glyphs from the original's own
 * bytes.
 */

var HighwayEnding = (function () {
  'use strict';

  var DEAD_BIT = 0x80;          // speed bit 7: the record is dying (M6)
  var SHAPE_STEP = 2;           // the Lasertron's kind low byte, +2 a step
  var ZONE_LENGTH = 176;        // measured, disasm_notes.md chap. 7

  /**
   * @param {Object} data - The parsed data/ending.json (tools/dumpending.py).
   * @param {number} [framesPerPass] - How many frames one pass of the main
   *        loop takes (data/physics.json stepLength.framesPerStepMean). Only
   *        the parts of the sequence the original spends **outside** the main
   *        loop are measured in frames, and this turns them into passes.
   */
  function HighwayEnding(data, framesPerPass) {
    this.data = data || null;
    this.framesPerPass = framesPerPass || 2.41;
    this.constants = {};
    var consts = (data && data.script && data.script.constants) || {};
    for (var name in consts) {
      if (Object.prototype.hasOwnProperty.call(consts, name)) {
        this.constants[name] = consts[name].value;
      }
    }
    this.phases = null;
    this.index = 0;
    this.left = 0;
    this.passes = 0;
    this.running = false;
    this.finished = false;
    // what the renderer is shown while the sequence runs
    this.view = HighwayEnding.blankView();
  } // HighwayEnding

  HighwayEnding.blankView = function () {
    return {phase: null, panelMessage: false, panelBlank: false,
            attribute: null, text: null, breakup: false, zone: null};
  };

  /** A constant of the script, straight out of data/ending.json. */
  HighwayEnding.prototype.k = function (name, fallback) {
    var value = this.constants[name];
    return (value === undefined) ? fallback : value;
  }; // k

  /**
   * Has the Lasertron reached the end of the road?
   * @param {number} zoneCounter - The original's own counter, 1 to 31.
   * @param {number} lasertronY - Where the Lasertron stands on the road.
   */
  HighwayEnding.prototype.triggered = function (zoneCounter, lasertronY) {
    if (!this.data || this.running || this.finished) { return false; }
    var trigger = this.data.trigger;
    if (zoneCounter < trigger.zoneCounterAtLeast) { return false; }
    var delta = lasertronY - trigger.lasertronY;
    return delta >= 0 && delta < (trigger.window || 256);
  }; // triggered

  /** Frames the original spends outside the main loop, as passes. */
  HighwayEnding.prototype.framesAsPasses = function (frames) {
    return Math.max(1, Math.round(frames/this.framesPerPass));
  }; // framesAsPasses

  /**
   * The script, built from the measured constants. Every entry is a number of
   * **passes of the main loop** and what the sequence does when it starts.
   */
  HighwayEnding.prototype.script = function () {
    var self = this;
    var frames = {};
    ((this.data && this.data.script && this.data.script.phases) || [])
      .forEach(function (phase) { frames[phase.name] = phase.framesSincePrevious; });
    var salute = this.k('saluteEntities', 5);
    var shapeSteps = this.k('shapeSteps', 3);
    var steps = [
      {name: 'salute', passes: this.k('salutePasses', 24), enter: function (world) {
        // the convoy goes into the dying animation M6 measured: $80 in the
        // kind word's low byte and the top bit of the speed
        var kind = self.k('saluteKind', 0x80);
        for (var i = 0; i < salute; i++) {
          var e = world.entities[i];
          if (e) { e.cls = (e.cls & 0xFF00) | kind; e.speed |= DEAD_BIT; }
        }
        // ...and the record after them — the Lasertron — is stopped, so that
        // it stands still until the sequence sets it going again
        if (world.entities[salute]) { world.entities[salute].speed = 0; }
      }},
      {name: 'lasertronAlone', passes: this.k('afterPointerPasses', 15),
       enter: function (world) {
         // the original moves the table's own pointer past the five; here the
         // records are simply gone, which is what that amounts to
         for (var i = 0; i < salute; i++) { world.entities[i] = null; }
         // the original clears the panel's ZONE field here and never puts a
         // number back: from now on the panel shows the sequence's own message
         // instead, and after it an empty box until the next game
         self.view.panelBlank = true;
         self.view.panelMessage = true;
       }},
      {name: 'lasertronRuns', until: 'endZone', enter: function (world) {
        var lasertron = self.lasertron(world);
        if (lasertron) { lasertron.speed = self.k('lasertronSpeed', 1); }
      }},
      {name: 'clear', passes: this.k('clearPasses', 20)}
    ];
    // the Lasertron changes shape three times, three passes apart: the
    // original runs the passes first and moves the kind word after them, so
    // every step here belongs to the **next** stretch of passes
    for (var i = 0; i < shapeSteps; i++) {
      steps.push({name: 'shape'+(i+1), passes: this.k('shapePasses', 3),
                  enter: i === 0 ? null
                    : function (world) { self.shape(world, SHAPE_STEP); }});
    }
    steps.push(
      {name: 'afterShape', passes: this.k('afterShapePasses', 20),
       enter: function (world) {
         self.shape(world, SHAPE_STEP);
         // three records take a kind of their own — the explosion
         var first = self.k('explosionFirst', 6);
         for (var n = 0; n < self.k('explosionRecords', 3); n++) {
           var e = world.entities[first + n];
           if (e) { e.cls = (e.cls & 0xFF00) | self.k('explosionKind', 0x20); }
         }
       }},
      // the original also patches a byte into its own drawing routine here
      // ($A1CE); what that byte selects is not measured, so nothing is drawn
      // from it — see data/ending.json `open`
      {name: 'explosion', passes: this.k('explosionPasses', 60),
       keys: this.k('explosionKeys', 1)},
      {name: 'afterExplosion', passes: this.k('afterExplosionPasses', 8)},
      // Two parts of the sequence do not run the main loop at all: the ship
      // breaking up and the pause after it are drawn straight to the screen.
      // They are the only parts measured in **frames** rather than in passes,
      // and while they run there is no pass to step the road with.
      {name: 'shipBreakup', frames: frames.afterBreakup || 94,
       enter: function () {
         self.view.attribute = self.k('whiteAttr', 0x47);
         self.view.breakup = true;
       }},
      {name: 'afterBreakup', frames: frames.rewind || 16,
       enter: function (world) {
         self.view.breakup = false;
         self.view.attribute = self.k('plainAttr', 7);
         self.view.panelMessage = false;
         // the table is cut short — everything past that record is gone
         for (var i = self.k('tableEndAt', 9); i < world.entities.length; i++) {
           world.entities[i] = null;
         }
       }});
    // ...and the same three steps backwards
    for (var r = 0; r < this.k('rewindSteps', 3); r++) {
      steps.push({name: 'rewind'+(r+1), passes: this.k('rewindPasses', 3),
                  enter: r === 0 ? null
                    : function (world) { self.shape(world, -SHAPE_STEP); }});
    }
    steps.push(
      {name: 'afterRewind', passes: this.k('afterRewindPasses', 20),
       enter: function (world) { self.shape(world, -SHAPE_STEP); }},
      {name: 'finale', passes: this.k('finalePasses', 190),
       textAt: this.k('finalePasses', 190) - this.k('textAtPass', 135),
       dead: this.k('finaleDeadAt', 5),
       enter: function (world) {
         self.view.attribute = null;
         var e = world.entities[self.k('finaleKindAt', 5)];
         if (e) { e.cls = (e.cls & 0xFF00) | self.k('finaleKind', 0x80); }
       }});
    return steps;
  }; // script

  /** The Lasertron is the record that is left once the convoy has gone. */
  HighwayEnding.prototype.lasertron = function (world) {
    for (var i = 0; i < world.entities.length; i++) {
      var e = world.entities[i];
      if (e && !(e.speed & DEAD_BIT)) { return e; }
    }
    return null;
  }; // lasertron

  /** The Lasertron's shape walks up (and later back down) by two. */
  HighwayEnding.prototype.shape = function (world, step) {
    var e = this.lasertron(world);
    if (e) { e.cls = (e.cls & 0xFF00) | ((e.cls + step) & 0xFF); }
  }; // shape

  /** Start the sequence. */
  HighwayEnding.prototype.start = function (world) {
    this.phases = this.script();
    this.index = -1;
    this.passes = 0;
    this.running = true;
    this.finished = false;
    this.view = HighwayEnding.blankView();
    this.pending = null;
    this.advance(world);
    // ...except the very first part, which the original does the moment the
    // Lasertron crosses the line, before any pass at all
    if (this.pending) { this.pending(world); this.pending = null; }
    return this.view;
  }; // start

  /**
   * Move on to the next part of the script.
   *
   * What that part **does** is not done here but at the top of the next pass,
   * and that is measured, not tidiness: the original changes the state between
   * two passes of its main loop, and the recording is read inside a pass, so a
   * change made here would show up one pass too early.
   */
  HighwayEnding.prototype.advance = function (world) {
    this.index++;
    if (this.index >= this.phases.length) {
      this.running = false;
      this.finished = true;
      this.view.phase = 'done';
      return;
    }
    var phase = this.phases[this.index];
    this.left = phase.passes || phase.frames || 0;
    this.view.phase = phase.name;
    this.pending = phase.enter || null;
  }; // advance

  /**
   * One pass of the main loop while the sequence runs.
   *
   * @param {Object} world - the HighwayWorld.
   * @returns {Object} {keys, done, view} — `keys` is what the sequence
   *   "pressed" this pass, and the caller steps the world with it exactly as
   *   the original's own loop does.
   */
  HighwayEnding.prototype.step = function (world) {
    if (!this.running) { return {keys: 0, done: true, loop: false, view: this.view}; }
    var phase = this.phases[this.index];
    // the parts that draw instead of running the loop are counted in frames,
    // and while they run the road is not stepped at all
    if (phase.frames) {
      return {keys: 0, done: false, loop: false, view: this.view};
    }
    if (this.pending) { this.pending(world); this.pending = null; }
    this.passes++;
    var keys = phase.keys || 0;
    // the closing stretch keeps setting the top bit of the Lasertron's speed
    // every single pass, so that it stays in the dying animation
    if (phase.dead !== undefined && world.entities[phase.dead]) {
      world.entities[phase.dead].speed |= DEAD_BIT;
    }

    if (phase.until === 'endZone') {
      // the camera's own zone, and it is read off where the Lasertron stood
      // when the pass began — the original loads the new zone one pass after
      // it crosses, which M4 measured and which is why this is not read after
      // the step (disasm_notes.md chap. 14)
      var lasertron = this.lasertron(world);
      var zone = lasertron ? Math.floor(lasertron.y/ZONE_LENGTH) : 0;
      this.view.zone = zone;
      if (zone >= this.k('endZoneLast', 36)) { this.advance(world); }
      return {keys: keys, done: false, loop: true, view: this.view};
    }

    if (phase.textAt !== undefined && this.phases[this.index].passes - this.left
        === phase.textAt) {
      this.view.text = (this.data && this.data.text && this.data.text.ending) || null;
    }
    if (--this.left <= 0) { this.advance(world); }
    return {keys: keys, done: !this.running, loop: true, view: this.view};
  }; // step

  /**
   * One frame of the machine, for the parts of the sequence that do not run
   * the main loop — the ship breaking up and the pause after it. Everywhere
   * else it does nothing, because everywhere else the sequence is counted in
   * passes.
   */
  HighwayEnding.prototype.frame = function (world) {
    if (!this.running) { return false; }
    var phase = this.phases[this.index];
    if (!phase.frames) { return false; }
    if (this.pending) { this.pending(world); this.pending = null; }
    if (--this.left <= 0) { this.advance(world); }
    return true;
  }; // frame

  /**
   * The second pass: what one finished game does to the road.
   *
   * The original walks its own table of the road's data — 240 records of
   * sixteen bytes at $7B00, the very format the live table has — and adds one
   * to the speed of every record whose family is below the limit. The port has
   * no road data yet (that table is M2), so this takes whatever records it is
   * given, which is the same walk over the same format.
   *
   * @param {Array} records - Records with `cls` and `speed`.
   * @param {number} passes - How many games have been finished (the counter).
   * @param {number} [familyMask] - data/enemies.json familyMask ($EF).
   * @returns {number} How many records were made faster.
   */
  HighwayEnding.prototype.harden = function (records, passes, familyMask) {
    if (!this.data || !passes) { return 0; }
    var limit = this.data.secondPass.familyBelow;
    var delta = this.data.secondPass.speedDelta*passes;
    var mask = familyMask || 0xEF;
    var count = 0;
    for (var i = 0; i < records.length; i++) {
      var e = records[i];
      if (!e) { continue; }
      var family = ((e.cls || 0) >> 8) & mask;
      if (family < limit) { e.speed += delta; count++; }
    }
    return count;
  }; // harden

  /** The counter the original keeps at $8F89, with its measured ceiling. */
  HighwayEnding.prototype.nextPassCount = function (passes) {
    var cap = this.data ? this.data.secondPass.cap : 2;
    return (passes >= cap) ? passes : passes + 1;
  }; // nextPassCount

  HighwayEnding.DEAD_BIT = DEAD_BIT;
  HighwayEnding.ZONE_LENGTH = ZONE_LENGTH;

  return HighwayEnding;
})();

if (typeof self !== 'undefined') { self.HighwayEnding = HighwayEnding; }
if (typeof module !== 'undefined' && module.exports) {
  module.exports = HighwayEnding;
}
