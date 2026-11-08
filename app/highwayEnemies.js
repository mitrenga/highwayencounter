// begin code

/**
 * The enemies, and the matrix that decides what a collision does (M6).
 *
 * M4 and M5 both stopped at the same fence: they took the enemies out of the
 * recording every pass, because nothing was known about them
 * (sources/docs/disasm_notes.md chap. 14 and 15). This file is what closes
 * that, and it closes it differently from the milestones before it — the
 * original does not hide these rules in code, it keeps them in **tables**, and
 * tools/dumpenemies.py reads them straight out of the running game:
 *
 * 1. **A record's family is the high byte of its kind word without bit 4.**
 *    That is why $0330 and $1378 behave identically, and why $0A60 and $1A68
 *    do not — the bit that separates them is read by the handlers, not by the
 *    dispatch. There are eleven families: the Vortons, the shot, four kinds of
 *    enemy, four kinds of object and the Lasertron.
 * 2. **The step comes out of a table** at $8E00, indexed by direction and
 *    speed: how far across, how far along, how far the animation phase turns
 *    and how the drawing depth moves.
 * 3. **A collision is an 11 x 11 matrix** at $9000 — who ran into whom decides
 *    what happens, and byte +11 of every record is that record's row (22 per
 *    row, two bytes per entry). The edge of the road and a target outside the
 *    world's window both use column 7. This one table explains what M4
 *    measured about shoving from the outside: a shot melts one kind of box,
 *    shoves another, passes clean through a third, and the row of objects that
 *    costs speed without raising the hit flag is simply the column that lands
 *    on "halve speed".
 * 4. **The enemies are random, but not unpredictable.** The game has its own
 *    generator over the Spectrum's own seed at $5C76:
 *    `SEED' = (254 * SEED + 253) mod 65537`. Family 2 draws a fresh 90-degree
 *    heading when it is blocked, family 3 wanders a step left or right on
 *    about one pass in twelve, family 4 draws its heading from a mask table
 *    every pass it moves, and family 5 — the mines — simply turn around.
 * 5. **Mines cannot be killed.** A shot into family 5 is eaten and the mine
 *    drives on, which is exactly what the instructions say and what the
 *    matrix says: the mine's column-1 handler removes the shot, and the
 *    shot's column-5 handler removes the shot too. Families 2, 3 and 4 do die
 *    to a shot; and touching any of them destroys the Vorton you drive — the
 *    enemy goes with him unless it is a mine.
 * 6. **Dying is a table walk too.** A destroyed record keeps the top bit in
 *    its speed and its kind word's low byte walks $80, $88, $90… until $DC,
 *    when the record leaves the table. That is the twelve passes M5 measured
 *    at the hand-over without knowing what they were.
 *
 * What this file does **not** own: the generator's sequence. The game draws
 * from the same seed in its explosion sound and in its drawing
 * (disasm_notes.md chap. 16), so a port that only steps the enemies drifts out
 * of step with it. Until the sound is measured (M8) the seed is taken from the
 * recording at the start of every pass, and tools/matchenemies.js counts every
 * time it does that rather than this file pretending to know.
 */

var HighwayEnemies = (function () {
  'use strict';

  var EMPTY_X = 0xFE;       // an empty slot in the original's table
  var END_X = 0xFF;         // ...and the end of it
  var SHOVED_BIT = 0x40;    // speed bit 6: shoved in this pass (M4)
  var DEAD_BIT = 0x80;      // speed bit 7: the record is dying
  var PLAYER_KIND = 0x0E;   // +10 of the Vorton the player drives

  /**
   * @param {object} data - data/enemies.json (tools/dumpenemies.py).
   */
  function HighwayEnemies(data) {
    this.data = data;
    this.familyMask = data.familyMask;
    this.enemyFamilies = data.enemyFamilies.slice();
    this.matrix = data.collision.handlers;
    this.wallColumn = data.collision.wallColumn;
    this.range = data.collision.range;          // 15, i.e. the 7-each-way box
    this.steps = data.steps.perSpeed;
    this.masks = data.dirMasks.perLane;
    this.wander = data.wander;
    this.death = data.death;
    this.roadMax = 0x49;                        // measured: x < 73 is the road
    this.windowSpan = 2;                        // ...and y within 512 of the window
    this.seed = 0;
    this.borrowedSeeds = 0;
  } // HighwayEnemies

  /** The family a kind word belongs to — the high byte without bit 4. */
  HighwayEnemies.prototype.familyOf = function (cls) {
    return (cls >> 8) & this.familyMask;
  }; // familyOf

  /** Is this one of ours: one of the four enemy families? */
  HighwayEnemies.prototype.owns = function (cls) {
    return this.enemyFamilies.indexOf(this.familyOf(cls)) >= 0;
  }; // owns

  /** The game's own generator, over the Spectrum's seed at $5C76. */
  HighwayEnemies.prototype.random = function () {
    var r = this.data.random;
    this.seed = (r.mul*this.seed + r.add) % r.mod;
    return this.seed;
  }; // random

  /**
   * The seed the original had when this pass began.
   *
   * The port cannot keep the sequence by itself yet: the explosion sound and
   * the drawing draw from the same generator (chap. 16), and neither is
   * measured before M8. So whoever replays a recording hands the seed over
   * here once per pass, and every one of those is counted.
   */
  HighwayEnemies.prototype.borrowSeed = function (seed) {
    this.seed = seed;
    this.borrowedSeeds++;
  }; // borrowSeed

  HighwayEnemies.prototype.isDead = function (e) {
    return !!(e.speed & DEAD_BIT);
  }; // isDead

  /**
   * One pass of a dying record: the kind word's low byte walks up by eight and
   * the record leaves the table when it reaches the limit. Nothing else about
   * it moves.
   *
   * @returns {boolean} Whether the record is gone.
   */
  HighwayEnemies.prototype.stepDying = function (world, slot, e) {
    // M8: a dying record asks for its explosion in **every** pass of the
    // animation, and which one it is comes from its family (measured,
    // tools/tracesound.py; the dispatch is the original's own at $9CF2).
    if (world.requestDyingSound) {
      world.requestDyingSound(this.familyOf(e.cls));
    }
    var low = (e.cls & 0xFF) + this.death.step;
    if (low >= this.death.limit) {
      world.entities[slot] = null;
      return true;
    }
    e.cls = (e.cls & 0xFF00) | low;
    return false;
  }; // stepDying

  /** Mark a record destroyed: the top bit of the speed, and $80 in the kind. */
  HighwayEnemies.prototype.destroy = function (e) {
    if ((e.cls & 0xFF) >= this.death.clsLow) { return false; }
    e.cls = (e.cls & 0xFF00) | this.death.clsLow;
    e.speed |= DEAD_BIT;
    return true;
  }; // destroy

  /**
   * One enemy's pass, exactly as the original's entity loop runs it.
   *
   * @param {object} world - the HighwayWorld it lives in.
   * @param {number} slot - its slot in the original's table.
   * @param {object} e - the record.
   * @returns {string} what the pass did: 'idle', 'dying', 'gone', 'wall',
   *   'window', 'hit' or 'moved'.
   */
  HighwayEnemies.prototype.stepEntity = function (world, slot, e) {
    e.speed &= ~SHOVED_BIT;
    if (!e.speed) { return 'idle'; }
    if (e.speed & DEAD_BIT) {
      return this.stepDying(world, slot, e) ? 'gone' : 'dying';
    }
    var family = this.familyOf(e.cls);
    var step = this.steps[(e.speed & 0x7F) - 1][e.dir];
    var nx = (e.x + step.dx) & 0xFF;
    var ny = (e.y + step.dy) & 0xFFFF;

    // The edge of the road and a target outside the world's window are both
    // answered by column 7 of this family's row — the same column the rows of
    // objects across the road land in, which is why running into the verge
    // and running into a wall look the same from inside the game.
    if (nx >= this.roadMax
        || (((ny - world.windowStart) & 0xFFFF) >> 8) >= this.windowSpan) {
      this.handle(world, this.matrix[family][this.wallColumn], slot, e, null);
      return nx >= this.roadMax ? 'wall' : 'window';
    }
    // A record that has taken a Vorton with it is written out of the table
    // straight away — and then, if the rest of the table turns out to be
    // clear, the step below writes it back in. The original does exactly
    // that, so the flag rides along rather than the record being dropped.
    e.leaving = false;

    // The table is read from the top every time, in its own order: a record
    // sees the ones above it already moved and the ones below it not yet
    // (measured again here, and it is the same order M5 found for the convoy).
    var left = (nx - 7) & 0xFF, back = (ny - 7) & 0xFFFF;
    for (var j = 0; j < world.endSlot; j++) {
      var o = world.entities[j];
      if (!o || j === slot) { continue; }
      if (((o.x - left) & 0xFF) >= this.range) { continue; }
      var dy = (o.y - back) & 0xFFFF;
      if ((dy >> 8) !== 0 || (dy & 0xFF) >= this.range) { continue; }
      if (this.handle(world, this.matrix[family][this.familyOf(o.cls)],
                      slot, e, o, j) === 'end') {
        if (e.leaving) { world.entities[slot] = null; }
        return 'hit';
      }
    }
    e.leaving = false;

    e.x = (left + 7) & 0xFF;
    e.y = (back + 7) & 0xFFFF;
    // The phase turns by the table's own amount, in eight bits: overflow one
    // way or the other is what picks the second of the two depth steps, which
    // is the only place the drawing depth is not a plain sum.
    var phase = (step.phase + e.phase) & 0xFF;
    var depth = step.depth;
    if (phase >= 0x0D) {
      phase = (phase < 0x80 ? phase - 0x10 : phase + 0x10);
      depth = step.depthWrapped;
    }
    e.phase = phase & 0xFF;
    e.depth = ((e.depth || 0) + depth) & 0xFFFF;
    this.afterMove(e, family);
    return 'moved';
  }; // stepEntity

  /**
   * What the families do with the pass they just completed: family 4 draws a
   * fresh heading out of its lane's mask, family 3 wanders a step to one side
   * on about one pass in twelve, and families 2 and 5 drive straight on.
   */
  HighwayEnemies.prototype.afterMove = function (e, family) {
    if (family === 4) {
      this.pickFromLane(e);
    } else if (family === 3) {
      var low = this.random() & 0xFF;
      if (low >= this.wander.left) { e.dir = (e.dir - 1) & 7; }
      else if (low < this.wander.right) { e.dir = (e.dir + 1) & 7; }
    }
  }; // afterMove

  /** Family 4's heading: the generator's high byte through its lane's mask. */
  HighwayEnemies.prototype.pickFromLane = function (e) {
    var mask = this.masks[e.lane & 7];
    e.dir = ((this.random() >> 8) & mask.and) | mask.or;
  }; // pickFromLane

  /**
   * One entry of the collision matrix.
   *
   * @returns {string} 'end' when the pass is over, 'cont' when the table is to
   *   be read on — which is what makes a shot invisible to an object and a
   *   family-6 object invisible to a mine.
   */
  HighwayEnemies.prototype.handle = function (world, what, slot, e, other, oslot) {
    switch (what) {
      case 'passThrough':
        return 'cont';
      case 'eatShot':
        // The Vorton the player drives lets his own fire through; anybody
        // else — including a mine — swallows it and drives on.
        if (e.kind !== PLAYER_KIND && other) { world.entities[oslot] = null; }
        return 'cont';
      case 'killedByShot':
        if (other) { world.entities[oslot] = null; }
        this.destroy(e);
        e.speed |= DEAD_BIT;
        // M8: the pass a record is destroyed in already asks for its
        // explosion, not only the passes of the animation after it — measured
        // (tools/tracesound.py, tools/matchsound.js).
        if (world.requestDyingSound) { world.requestDyingSound(this.familyOf(e.cls)); }
        if (world.noteDestroyed) { world.noteDestroyed(this.familyOf(e.cls)); }
        return 'end';
      case 'killVorton':
        // Whatever it was that touched him goes with him — unless it is a
        // mine, which stays where it is and waits for the next one.
        if (this.familyOf(e.cls) !== 5) { e.leaving = true; }
        if (other && this.destroy(other)) {
          if (world.requestDyingSound) {
            world.requestDyingSound(this.familyOf(other.cls));
          }
          if (world.noteDestroyed) { world.noteDestroyed(this.familyOf(other.cls)); }
          return 'end';
        }
        return 'cont';
      case 'randomEvenDir':
        e.dir = this.random() & 6;
        return 'end';
      case 'randomDir':
        e.dir = this.random() & 7;
        return 'end';
      case 'randomLane':
        e.lane = this.random() & 7;
        this.pickFromLane(e);
        return 'end';
      case 'reverse':
        e.dir = (e.dir + 4) & 7;
        return 'end';
      case 'halveSpeed':
        e.speed = (e.speed & ~SHOVED_BIT) >> 1;
        return 'end';
      default:
        return 'end';                 // 'stop' and everything else: no step
    }
  }; // handle

  HighwayEnemies.EMPTY_X = EMPTY_X;
  HighwayEnemies.END_X = END_X;
  HighwayEnemies.DEAD_BIT = DEAD_BIT;

  return HighwayEnemies;
})();

if (typeof self !== 'undefined') { self.HighwayEnemies = HighwayEnemies; }
if (typeof module !== 'undefined' && module.exports) {
  module.exports = HighwayEnemies;
}
