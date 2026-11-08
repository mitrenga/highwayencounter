// begin code

/**
 * The controlled Vorton's physics — measured off the original (M3).
 *
 * Nothing here is tuned by feel. Every number comes out of data/physics.json,
 * which tools/dumpphysics.py measures by driving the original in a simulator
 * and reading what happens in its memory (sources/docs/disasm_notes.md
 * chap. 12); tools/matchphysics.js then replays this code against recorded runs
 * of the original (tools/tracephysics.py) and wants zero differences.
 *
 * Three things about the model are worth saying out loud, because they are the
 * measurement and not a guess:
 *
 * 1. **A step is one pass of the original's main loop, not one frame.** That
 *    loop is not tied to the interrupt: a pass takes 165 000-245 000 T states,
 *    2.4 to 3.5 frames, and its length moves with how much there is to draw
 *    (disasm_notes.md chap. 11). The Vorton's state changes once per pass, so
 *    that is the unit this code steps in. How fast the remake should run those
 *    passes is an open question and belongs to M9; data/physics.json carries
 *    the measured distribution.
 * 2. **The coordinate is the world's own.** The road is one continuous
 *    coordinate, a zone is 176 of it, and speed 1 moves the Vorton 2 per step
 *    along the road, so a diagonal can move 1 and stay exact. (M3 read this as
 *    "half units" of a 352-long zone; M4 measured the zone against the
 *    player's position and it is 176 — disasm_notes.md chap. 14.)
 * 3. **Nothing decelerates on its own.** Release the throttle and the Vorton
 *    keeps its speed for good; only Q slows it down, and only a collision stops
 *    it. That is what Crash 20 means by "seemingly even longer to come to a
 *    halt" — measured, tools/dumpphysics.py `speed.coastsForever`.
 *
 * What the world outside the Vorton is, this file does not know: it asks a
 * `blocked(x, y)` callback whether a position can be entered. The road's own
 * edges it does know (data/physics.json `collision.road`, measured by driving
 * into them); everything else is answered by highwayObjects.js, which as of M4
 * knows what stands on the road and which of the three answers below each of
 * those things gives.
 */

var VortonPhysics = (function () {
  'use strict';

  // offsets in the game's own 16-byte entity record ($8A00, entry 0 is the
  // controlled Vorton — disasm_notes.md chap. 12). The port keeps its state in
  // a plain object, but the names are the record's so the two can be compared.
  var REC_X = 0, REC_Y = 1, REC_DIR = 7, REC_SPEED = 8, REC_PHASE = 9;

  // the keyboard bitmask the original builds each step ($8F14)
  var KEY_FIRE = 1, KEY_ACCEL = 2, KEY_DECEL = 4, KEY_RIGHT = 8, KEY_LEFT = 16;

  // $8F13 alternates 0/2 every step and turning is only allowed on the 2
  var TURN_PHASE_ON = 2;

  // What blocked(x, y) may answer. The Vorton's own physics is the same in all
  // three; what differs is what the thing he ran into does to him, and that is
  // the object layer's business (M2 data, M4 rules), not his.
  var BLOCK_HOLD = 2,   // the move is refused and costs nothing
      BLOCK_HIT = 1,    // ...and costs a step of speed; the original raises its
                        //    own hit flag ($8F15 bit 4) and reloads the
                        //    throttle's shift register
      BLOCK_SLOW = 3;   // ...costs a step of speed, but no flag and the shift
                        //    register is left running (measured on a row of
                        //    objects across the road)

  // the animation phase wraps at 16; how far it turns per unit of speed is a
  // measured table per heading, not a single constant — see the constructor

  /**
   * @param {object} data - data/physics.json (tools/dumpphysics.py).
   */
  function VortonPhysics(data) {
    this.data = data;
    this.dirs = [];
    for (var i = 0; i < 8; i++) {
      var v = data.directions[i] || data.directions[String(i)];
      var spin = data.phase.perDirectionPerSpeed;
      this.dirs.push({dx: v[0], dy: v[1],
                      spin: spin[i] === undefined ? spin[String(i)] : spin[i]});
    }
    this.maxSpeed = data.speed.max;
    this.minSpeed = data.speed.min;
    this.reload = data.thrustTimer.reload;
    this.road = data.collision.road;
    this.hitReload = data.collision.timerReload;
    this.hitDrop = data.collision.speedDropOnHit[0];
    this.phaseMask = data.phase.mask;
  } // VortonPhysics

  /**
   * A Vorton in the state the original's record has him at the start of a game
   * (data/physics.json `spawn`, read out of the running game), or wherever the
   * caller says.
   */
  VortonPhysics.prototype.spawn = function (x, y, dir) {
    var at = this.data.spawn || {x: 0, y: 0, dir: 0, phase: 0, cls: 0, kind: 14};
    return {
      x: x === undefined ? at.x : x,
      y: y === undefined ? at.y : y,
      dir: dir === undefined ? at.dir : dir,
      speed: 0,
      phase: at.phase,
      // the record's own two identities, straight out of the measured spawn:
      // the kind word ($8A00+5, zero for whoever is being driven) and the kind
      // byte ($8A00+10, $0E), which is what picks his eight rotations out of
      // the sprite table — see screenComposer.frameOf
      cls: at.cls|0,
      kind: at.kind|0,
      // the throttle's shift register ($8F1D): loaded with $FF when the speed
      // changes and shifted right once every step, moving or not; the next
      // change comes when it reaches zero, which is eight steps later
      timer: 0,
      // $8F13 — the global alternating flag that lets the Vorton turn on every
      // other step. It belongs to the engine, not to the Vorton, but until M5
      // has the rest of the entities there is nowhere else to keep it.
      turnPhase: 0
    };
  }; // spawn

  /** Is x still on the road? The edges are measured, not assumed. */
  VortonPhysics.prototype.onRoad = function (x) {
    return x >= this.road.minX && x <= this.road.maxX;
  }; // onRoad

  /**
   * One pass of the original's main loop.
   *
   * @param {object} v - the Vorton's state, changed in place.
   * @param {number} keys - the keyboard bitmask ($8F14): FIRE 1, ACCELERATE 2,
   *   DECELERATE 4, RIGHT 8, LEFT 16.
   * @param {function} [blocked] - blocked(x, y) tells what stands there:
   *   0 nothing, BLOCK_HIT a collision (the original raises its own hit flag,
   *   $8F15 bit 4, and that is what costs the speed), BLOCK_HOLD something
   *   that only refuses the move — measured: pressing into the convoy stops
   *   the Vorton for several steps before the collision is ever reported.
   *   Without the callback only the road's edges stop him.
   * @returns {object} what the step did: {turned, throttled, moved, hit}.
   */
  VortonPhysics.prototype.step = function (v, keys, blocked) {
    var out = {turned: false, throttled: 0, moved: false, hit: false,
               held: false};

    // 1. the turn — every other step, and only when exactly one of the two
    //    keys is down: pressed together they cancel (measured, `bothKeysTurns`)
    v.turnPhase ^= TURN_PHASE_ON;
    var left = !!(keys & KEY_LEFT), right = !!(keys & KEY_RIGHT);
    if (v.turnPhase === TURN_PHASE_ON && left !== right) {
      v.dir = (v.dir + (right ? 1 : -1)) & 7;
      out.turned = true;
    }

    // 2. the throttle. The shift register runs every step, whether the Vorton
    //    moves or not; a change of speed loads it with $FF and the next one
    //    can only come when it has shifted its way back to zero, eight steps
    //    later. At a standstill it is normally zero already, which is why the
    //    first press takes effect at once.
    v.timer >>= 1;
    // pressed together the brake wins — measured: at speed 2 the pair 1+Q
    // slows down, and only from a standstill does it look like nothing happens
    var decel = !!(keys & KEY_DECEL), accel = !decel && !!(keys & KEY_ACCEL);
    if (v.timer === 0) {
      if (accel && v.speed < this.maxSpeed) {
        v.speed++;
        out.throttled = 1;
      } else if (decel && v.speed > this.minSpeed) {
        v.speed--;
        out.throttled = -1;
      }
      if (out.throttled) {
        // reloaded only while there is another step left to make: reaching top
        // speed or a standstill leaves it at zero (measured)
        v.timer = (v.speed > this.minSpeed && v.speed < this.maxSpeed)
                  ? this.reload : 0;
      }
    }

    // 3. the move. A step that cannot be made is dropped whole — x and y both
    //    stay, the animation does not advance and the speed drops by one, so
    //    running into a wall at full speed costs two steps to stop.
    if (v.speed > 0) {
      var d = this.dirs[v.dir];
      var nx = v.x + d.dx*v.speed, ny = v.y + d.dy*v.speed;
      var stop = this.onRoad(nx) ? (blocked ? blocked(nx, ny) : 0) : BLOCK_HIT;
      if (stop === BLOCK_HIT) {
        v.speed -= this.hitDrop;
        if (v.speed < this.minSpeed) { v.speed = this.minSpeed; }
        // the same shape as the throttle's reload, with the collision's own
        // shorter constant: loaded only while there is still speed to lose
        v.timer = v.speed > this.minSpeed ? this.hitReload : 0;
        out.hit = true;
      } else if (stop === BLOCK_SLOW) {
        v.speed -= this.hitDrop;
        if (v.speed < this.minSpeed) { v.speed = this.minSpeed; }
        out.held = true;
      } else if (stop) {
        out.held = true;        // BLOCK_HOLD — leaning on it costs nothing
      } else {
        v.x = nx;
        v.y = ny;
        // the Vorton is a ball: which way it looks to be rolling depends on
        // the heading, and on two of the eight it does not turn at all
        v.phase = (v.phase + d.spin*v.speed) & this.phaseMask;
        out.moved = true;
      }
    }
    return out;
  }; // step

  VortonPhysics.KEYS = {FIRE: KEY_FIRE, ACCEL: KEY_ACCEL, DECEL: KEY_DECEL,
                        RIGHT: KEY_RIGHT, LEFT: KEY_LEFT};
  VortonPhysics.FIELDS = {X: REC_X, Y: REC_Y, DIR: REC_DIR, SPEED: REC_SPEED,
                          PHASE: REC_PHASE};
  VortonPhysics.TURN_PHASE_ON = TURN_PHASE_ON;
  VortonPhysics.BLOCK_HIT = BLOCK_HIT;
  VortonPhysics.BLOCK_HOLD = BLOCK_HOLD;
  VortonPhysics.BLOCK_SLOW = BLOCK_SLOW;

  /** The bitmask the original would have built out of a set of controls. */
  VortonPhysics.keysOf = function (input) {
    return (input.fire ? KEY_FIRE : 0)
         | (input.accelerate ? KEY_ACCEL : 0)
         | (input.decelerate ? KEY_DECEL : 0)
         | (input.right ? KEY_RIGHT : 0)
         | (input.left ? KEY_LEFT : 0);
  }; // keysOf

  return VortonPhysics;
})();

if (typeof self !== 'undefined') { self.VortonPhysics = VortonPhysics; }
if (typeof module !== 'undefined' && module.exports) { module.exports = VortonPhysics; }
