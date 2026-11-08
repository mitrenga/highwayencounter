// begin code

/**
 * The convoy — four automatic Vortons and the Lasertron, measured off the
 * original (M5).
 *
 * This is the heart of the game and the one part with no model in any sibling
 * project: five records the player does not steer, which have to keep moving
 * whether or not the camera is looking at them (ZADANI chap. 3.3). M4 left
 * them alone on purpose — tools/matchobjects.js took their position out of the
 * recording every pass rather than lend them the objects' physics, which would
 * have made them shove the barrels the original's convoy stops in front of.
 *
 * What tools/dumpconvoy.py measured on 75 778 passes of the running original,
 * and what this file is:
 *
 * 1. **The convoy does not steer and does not accelerate.** Every member heads
 *    straight down the road (direction 0) at speed 1 — two units a pass — and
 *    its animation phase turns by 4 on every pass it manages to move, exactly
 *    like the controlled Vorton's (data/physics.json). In 75 778 passes not one
 *    of them ever turned or changed speed.
 * 2. **Pushing the Lasertron is not a rule.** The Lasertron drives itself, at
 *    the same speed as the Vortons; the Vortons behind it simply have nowhere
 *    to go. That is why the convoy closes up into a queue eight units apart
 *    the moment its head is stopped — eight, because seven is as close as the
 *    collision box lets anything get.
 * 3. **It stops on the same box everything else does.** Measured again and
 *    independently of M4, the same 7 x 7 came out — and it is read **in table
 *    order**: a record sees the ones above it already moved and the ones below
 *    it not yet. Reading the state as it was at the start of the pass explains
 *    fewer passes, which is how the order was measured rather than assumed.
 * 4. **It shoves nothing.** Whatever it runs into, it stands in front of until
 *    the way clears. Not one shoveable barrel moved under the convoy.
 * 5. **The speed byte is a display state, not a speed.** A blocked member
 *    keeps a 1 in its record when another member of the convoy stopped it and
 *    gets a 0 when anything else did — the Vorton you drive, or a barrel you
 *    failed to clear. It moves two units a pass either way.
 * 6. **The Lasertron never leaves the centre line.** Its x is 36 in every pass
 *    measured, and so is every automatic Vorton's — which is what YS 19 means
 *    by lining the centre line up with the groove on the Vorton's back. The
 *    gap the convoy needs is therefore fixed by the box: nothing within 7 of
 *    the centre, a clear lane 15 wide out of the road's 73.
 * 7. **Losing the Vorton you drive hands you the next one.** The record goes
 *    through its dying animation (M6), vanishes, and one pass later the
 *    **lowest-numbered record that is still an automatic Vorton** becomes the
 *    controlled one — where it stands, at its own position and phase. You do
 *    not restart; you take over the convoy from the inside, and it is one
 *    Vorton shorter.
 *
 * What is **not** here: 3.17 % of the measured passes, in which the head of
 * the convoy stands still with an empty road in front of it, always far ahead
 * of the camera. Whatever stops it is not in the entity table — the zone it
 * has driven into has not been loaded yet (M2) — so it is written down in
 * data/convoy.json and sources/docs/disasm_notes.md chap. 15 as an open
 * question, and tools/matchconvoy.js counts every one of them rather than this
 * file guessing at it.
 */

var HighwayConvoy = (function () {
  'use strict';

  /**
   * @param {object} data - data/convoy.json (tools/dumpconvoy.py).
   */
  function HighwayConvoy(data) {
    this.data = data;
    this.vortonClass = data.classes.vorton;
    this.lasertronClass = data.classes.lasertron;
    // measured: heading 0, speed 1, and never anything else
    this.dir = data.motion.dir[0];
    this.speed = data.motion.speed;
    // what the record's speed byte holds afterwards — a display state, not a
    // speed: the convoy moves two units a pass whatever is in it
    this.speedMoved = data.speedByte.moved;
    this.speedBlockedByConvoy = data.speedByte.blockedByConvoy;
    this.speedBlockedByOther = data.speedByte.blockedByOther;
    // how many passes the world goes without a controlled Vorton before the
    // next automatic one takes over (the dying animation itself is M6)
    this.blankSteps = data.takeover.blankSteps.length
      ? data.takeover.blankSteps[0] : 1;
  } // HighwayConvoy

  /** Is this one of ours — an automatic Vorton or the Lasertron? */
  HighwayConvoy.prototype.owns = function (cls) {
    return cls === this.vortonClass || cls === this.lasertronClass;
  }; // owns

  HighwayConvoy.prototype.isVorton = function (cls) {
    return cls === this.vortonClass;
  }; // isVorton

  /**
   * One member's pass: straight on at speed 1, refused by the same box that
   * refuses everything else, and read in table order — which is what the
   * `world.at` call does, because the records above this one have already
   * moved by the time it is asked.
   *
   * @param {object} world - the HighwayWorld this convoy lives in.
   * @param {number} slot - the record's slot in the original's table.
   * @param {object} e - the record.
   * @returns {boolean} Whether it moved.
   */
  HighwayConvoy.prototype.stepEntity = function (world, slot, e) {
    var d = world.dirs[this.dir];
    var nx = e.x + d.dx*this.speed, ny = e.y + d.dy*this.speed;
    e.dir = this.dir;
    var blocker = world.at(nx, ny, slot);
    if (blocker) {
      // Measured: stopped by another member of the convoy it keeps its 1,
      // stopped by anything else — you, a barrel — it gets a 0. It shoves
      // neither: whatever is in the way stays exactly where it is.
      e.speed = this.owns(blocker.entity.cls)
        ? this.speedBlockedByConvoy : this.speedBlockedByOther;
      return false;
    }
    e.x = nx;
    e.y = ny;
    e.speed = this.speedMoved;
    e.phase = (e.phase + d.spin*this.speed) & world.physics.phaseMask;
    return true;
  }; // stepEntity

  HighwayConvoy.PLAYER_CLASS = 0;

  return HighwayConvoy;
})();

if (typeof self !== 'undefined') { self.HighwayConvoy = HighwayConvoy; }
if (typeof module !== 'undefined' && module.exports) {
  module.exports = HighwayConvoy;
}
