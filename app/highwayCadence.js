// begin code

/**
 * How long a pass of the original's main loop takes — measured (M9).
 *
 * Everything else in this port steps in passes of the original's main loop
 * (disasm_notes.md chap. 11), and until M9 the worker simply ran a pass every
 * 2.586 frames, the measured mean, and said in a comment that it was a
 * placeholder. It was: the loop is not tied to the interrupt and a pass takes
 * anywhere from 1.4 to 13 frames.
 *
 * The rule turned out to be in the code, and it is a **governor**. At the end
 * of every pass, at $9AD8, sits an empty delay loop that runs only when there
 * was little to draw, and waits the more the less there was:
 *
 *     LD A,($8F0B)    the end of the draw list ($8D52 + 3 x records)
 *     CP $6A          = $8D52 + 3 x 8, so eight records
 *     JP NC,$9B72     eight or more: no wait at all
 *     ...             k = 2 x ($6A - end) = 48 - 6 x records
 *     LD B,$C8
 *     DJNZ $          200 x nothing, k times over
 *
 * So a pass is three things added up, and two of them are exact:
 *
 * 1. **work** — the drawing and the logic. It grows with the number of records
 *    drawn and with the number of live records in the table, whether the
 *    camera can see them or not, because the whole road is stepped. This is
 *    the one fitted part of the model.
 * 2. **the governor** — 2618 T per turn of that delay loop, counted off the
 *    instructions and checked against the running game.
 * 3. **the sound** — an effect is played *synchronously inside the loop*, so
 *    its whole length is added; and M8 measured every effect to the T state
 *    (data/sounds.json `measuredT`). The pass that *asks* for a sound is still
 *    short — it is the next one that plays it.
 *
 * A **repaint** is the fourth case: the original wipes the play area and
 * builds it again out of the background block, and that pass takes about
 * 915 000 T, thirteen frames. It does that in two places, both of which can be
 * seen from outside — entering the next zone, and the pass after the
 * controlled Vorton is lost. The pass still does its usual work as well, so
 * what is added is the measured surcharge, not a flat number.
 *
 * Measured by tools/dumpcadence.py into data/cadence.json and replayed against
 * recorded passes of the original by tools/matchcadence.js: the median pass is
 * predicted to 2.2 %, and 96 % of passes land within a quarter of a frame of
 * where the original put them.
 */

var HighwayCadence = (function () {
  'use strict';

  /**
   * @param {Object} data - The parsed data/cadence.json.
   */
  function HighwayCadence(data) {
    var d = data || {};
    var gov = d.governor || {};
    var work = d.work || {};

    this.frameTstates = d.frameTstates || 69888;
    this.cpuHz = d.cpuHz || 3500000;

    // the governor, as a table indexed by the number of records drawn — the
    // tool writes it out so that nothing has to be recomputed here
    this.governor = [];
    var table = gov.tstates || {};
    var n;
    for (n = 0; n < 64; n++) {
      this.governor[n] = (table[String(n)] !== undefined)
        ? table[String(n)]
        : (gov.skipT || 30);
    }

    this.base = work.base || 0;
    this.perDrawn = work.perDrawn || 0;
    this.perLive = work.perLive || 0;

    // sound: name -> T states, straight out of data/sounds.json via the tool
    this.sound = (d.sound && d.sound.tstates) || {};

    // a full repaint of the play area: the pass still does its usual work, so
    // what is measured is the surcharge on top of it
    this.repaintExtra = (d.repaint && d.repaint.extraMedian) || 0;
  } // HighwayCadence

  /**
   * How many T states a pass takes.
   * @param {number} drawn - Records the pass put in the draw list ($8D52):
   *        those inside the camera's window that are not standing scenery.
   * @param {number} live - Live records in the entity table, seen or not.
   * @param {string|false} sound - The effect this pass plays, by name — that
   *        is the effect the *previous* pass asked for, because the original
   *        clears its request byte at the end of the pass that plays it.
   * @param {boolean} repaint - Whether the original repaints the whole play
   *        area this pass: it does that on a zone change and on the pass after
   *        the controlled Vorton is lost.
   * @returns {number} T states.
   */
  HighwayCadence.prototype.passTstates = function (drawn, live, sound,
                                                   repaint) {
    var n = drawn < 0 ? 0 : (drawn > 63 ? 63 : drawn);
    var t = this.base + this.perDrawn * drawn + this.perLive * live
          + this.governor[n];
    if (sound && this.sound[sound]) {
      t += this.sound[sound];
    }
    if (repaint) {
      t += this.repaintExtra;
    }
    return t > 0 ? t : this.frameTstates;
  }; // passTstates

  /** The same thing in frames of the machine's 50.08 Hz interrupt. */
  HighwayCadence.prototype.passFrames = function (drawn, live, sound,
                                                  repaint) {
    return this.passTstates(drawn, live, sound, repaint)
           / this.frameTstates;
  }; // passFrames

  /** And in milliseconds of wall clock, which is what a timer wants. */
  HighwayCadence.prototype.passMs = function (drawn, live, sound, repaint) {
    return 1000 * this.passTstates(drawn, live, sound, repaint) / this.cpuHz;
  }; // passMs

  return HighwayCadence;
})();

if (typeof self !== 'undefined') { self.HighwayCadence = HighwayCadence; }
if (typeof module !== 'undefined' && module.exports) {
  module.exports = HighwayCadence;
}
