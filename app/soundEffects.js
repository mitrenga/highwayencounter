// begin code

/**
 * The game's own sounds, as of M8.
 *
 * The machine has a one-bit beeper on bit 4 of port $FE and no AY
 * (ZADANI chap. 1), so a sound is nothing but a list of pulse lengths: the
 * svision audio handlers take {fragments, pulses} where `fragments` are pulse
 * lengths in samples and `pulses` indexes into them. That is the same shape
 * the real machine produces, which is why the remake synthesizes rather than
 * plays samples.
 *
 * The sounds of the **machine** — the tape loading show and the ROM's key
 * click and rising scale — are not here: they are not this game's, and the
 * library holds them in svision ZXMachineSounds.
 *
 * The game has no music: in the whole 48K image there are exactly three
 * `OUT ($FE),A` instructions and all three sit inside sound routines, so
 * between effects there is silence (measured, tools/dumpsound.py). There are
 * five effects in the game and one generator in the menu, and each of them is
 * a short program rather than a waveform:
 *
 * * **noise** ($9B2C) — nine to twelve segments; a segment flips the speaker
 *   `L` times and waits `B` turns of an `OUT` loop between flips, and at the
 *   end of every segment it draws a new `L` and `B` from the game's own
 *   generator. That is the explosion.
 * * **tone** ($9B5B) — `E` notes of `L` flips each, the delay `D` shrinking by
 *   a byte-wide step after every note, so the pitch runs.
 * * **click** ($B203) — the menu: two counters flipping the same speaker, one
 *   turn of period apart, which is what makes it buzz.
 *
 * The three are written out here instruction for instruction, the same way
 * tools/dumpsound.py writes them in Python — and that Python is replayed
 * against the original in the simulator, where every flip has to land on the
 * same T state. What comes out is a list of pulse lengths, which is exactly
 * what the svision audio handlers take.
 */

/**
 * The game's own generator at $A270, instruction for instruction. The value it
 * returns is the `(254·seed + 253) mod 65537` of data/enemies.json, but the
 * explosion needs one thing more than the value: whether the routine's last
 * `SBC HL,DE` left a carry, because the `INC HL` that follows costs a T state
 * — and M8 measures T states.
 * @param {number} seed - The seed to advance.
 * @returns {Object} {seed, extra} — the new seed and the cost of that branch.
 */
export function drawRandom(seed) {
  var d = (seed >> 8) & 0xFF, e = seed & 0xFF;
  var hl = ((e << 8)|0xFD) & 0xFFFF;
  var a = d, c = 0, v, r;
  v = hl-seed-c; c = v < 0 ? 1 : 0; hl = v & 0xFFFF;
  r = a-c;       c = r < 0 ? 1 : 0; a = r & 0xFF;
  v = hl-seed-c; c = v < 0 ? 1 : 0; hl = v & 0xFFFF;
  r = a-c;       c = r < 0 ? 1 : 0; a = r & 0xFF;
  v = hl-a-c;    c = v < 0 ? 1 : 0; hl = v & 0xFFFF;
  return c ? {seed: (hl+1) & 0xFFFF, extra: 13} : {seed: hl, extra: 12};
} // drawRandom

/** DJNZ with B = 0 goes round 256 times, not none. */
function loops(b) {
  return b === 0 ? 256 : b;
} // loops

/**
 * The noise generator at $9B2C, instruction for instruction.
 * @param {Object} data - The parsed data/sounds.json.
 * @param {Object} effect - One entry of its `sounds`.
 * @param {number} seed - The generator's seed when the effect starts.
 * @returns {Object} {times, values, end} in T states.
 */
export function noiseFlips(data, effect, seed) {
  var t = data.generators.noise;
  var b = t.initB, l = t.initL, now = 0, level = 0;
  var times = [], values = [];
  for (var note = 0; note < effect.notes; note++) {
    level = 0;
    var count = loops(l);
    for (var j = 0; j < count; j++) {
      level ^= data.speakerBit|0x08;
      times.push(now); values.push(level);
      if (j < count-1) {
        now += t.tPerOut*loops(b)+t.tStep;
      } else {
        var drawn = drawRandom(seed);
        seed = drawn.seed;
        now += t.tPerOut*loops(b)+t.tDraw+drawn.extra;
        l = ((seed & 0xFF) & effect.maskToggles)+1 & 0xFF;
        var hi = (seed >> 8) & 0xFF;
        b = ((effect.maskOp === 'or' ? (hi|effect.maskDelay)
                                     : (hi & effect.maskDelay))+1) & 0xFF;
      }
    }
  }
  return {times: times, values: values, end: now, seed: seed};
} // noiseFlips

/**
 * The tone generator at $9B5B, instruction for instruction.
 * @param {Object} data - The parsed data/sounds.json.
 * @param {Object} effect - One entry of its `sounds`.
 * @returns {Object} {times, values, end} in T states.
 */
export function toneFlips(data, effect) {
  var t = data.generators.tone;
  var delay = effect.delay, now = 0, times = [], values = [];
  for (var note = 0; note < effect.notes; note++) {
    var level = 0;
    for (var j = 0; j < effect.toggles; j++) {
      level ^= data.speakerBit|0x08;
      times.push(now); values.push(level);
      now += t.tPerOut*loops(delay)+(j < effect.toggles-1 ? t.tStep : t.tNote);
    }
    delay = (delay-effect.subtract) & 0xFF;
  }
  return {times: times, values: values, end: now};
} // toneFlips

/**
 * The menu generator at $B203, instruction for instruction. `count` is how
 * many outer rounds of 256 turns it runs, `period` the reload of both counters.
 * @param {Object} data - The parsed data/sounds.json.
 * @param {number} count - The H half of the original's HL.
 * @param {number} period - The L half.
 * @returns {Object} {times, values, end} in T states.
 */
export function clickFlips(data, count, period) {
  var t = data.generators.click;
  var b = 0, level = 0, d = period, e = (period-1) & 0xFF, now = 0;
  var times = [], values = [];
  for (;;) {
    times.push(now); values.push(level);
    now += t.out+t.inc;
    d = (d+1) & 0xFF;
    if (d) { now += t.jrTaken; }
    else { now += t.jrNot+t.reloadD; d = period; level ^= data.speakerBit|0x08; }
    now += t.inc;
    e = (e+1) & 0xFF;
    if (e) { now += t.jrTaken; }
    else {
      now += t.jrNot+t.reloadE; e = (period-1) & 0xFF;
      level ^= data.speakerBit|0x08;
    }
    b = (b-1) & 0xFF;
    if (b) { now += t.djnz; }
    else {
      now += t.djnzEnd+t.decC;
      count = (count-1) & 0xFF;
      if (count) { now += t.jrTaken; }
      else { now += t.jrNot; break; }
    }
  }
  return {times: times, values: values, end: now};
} // clickFlips

/**
 * Turns the flips of a generator into what is actually heard: the speaker only
 * moves when the value written to the port **changes**, and the same value
 * written twice — which happens whenever a segment ends on an odd count — is
 * no edge at all.
 * @param {Object} flips - The output of one of the generators above.
 * @returns {number[]} Pulse lengths in T states.
 */
function pulseLengths(flips) {
  var edges = [], previous = -1;
  for (var i = 0; i < flips.times.length; i++) {
    if (flips.values[i] !== previous) {
      edges.push(flips.times[i]);
      previous = flips.values[i];
    }
  }
  var out = [];
  for (i = 0; i < edges.length; i++) {
    out.push((i+1 < edges.length ? edges[i+1] : flips.end)-edges[i]);
  }
  return out;
} // pulseLengths

/**
 * Packs pulse lengths into what the svision audio handlers take: the distinct
 * lengths in samples, and the sequence as indexes into them.
 * @param {number[]} tStates - Pulse lengths in T states.
 * @param {number} cpuHz - The machine's clock (data/sounds.json).
 * @param {number} sampleRate - The audio context sample rate.
 * @param {number} volume - Bus volume level.
 * @returns {Object} svision pulse data.
 */
function packPulses(tStates, cpuHz, sampleRate, volume) {
  var fragments = [], index = {}, pulses = [];
  for (var i = 0; i < tStates.length; i++) {
    var samples = Math.max(1, Math.round(tStates[i]*sampleRate/cpuHz));
    if (!(samples in index)) {
      index[samples] = fragments.length;
      fragments.push(samples);
    }
    pulses.push(index[samples]);
  }
  return {fragments: fragments, pulses: pulses, volume: volume};
} // packPulses

/**
 * One of the game's five effects, as pulses.
 * @param {Object} data - The parsed data/sounds.json (tools/dumpsound.py).
 * @param {string} name - fire, destroy, blast, crash or bump.
 * @param {number} seed - The generator's seed, for the ones that are noise.
 * @param {number} sampleRate - The audio context sample rate.
 * @param {number} volume - Bus volume level.
 * @returns {Object|false} svision pulse data, or false when there is no such
 *   effect (which is what a missing data/sounds.json looks like).
 */
export function gameSound(data, name, seed, sampleRate, volume) {
  if (!data || !data.sounds) { return false; }
  for (var i = 0; i < data.sounds.length; i++) {
    var effect = data.sounds[i];
    if (effect.name !== name) { continue; }
    var flips = effect.generator === 'noise'
      ? noiseFlips(data, effect, seed >>> 0) : toneFlips(data, effect);
    return packPulses(pulseLengths(flips), data.cpuHz, sampleRate, volume);
  }
  return false;
} // gameSound

/**
 * One of the menu's beeps, as pulses. The original has six call sites with
 * five different pitches — opening the menu, each of the four control choices,
 * starting the game, the demonstration and the beep the game returns with
 * (data/sounds.json `menu`).
 * @param {Object} data - The parsed data/sounds.json.
 * @param {string} at - The call site, e.g. '$B189'.
 * @param {number} sampleRate - The audio context sample rate.
 * @param {number} volume - Bus volume level.
 * @returns {Object|false} svision pulse data, or false.
 */
export function menuSound(data, at, sampleRate, volume) {
  if (!data || !data.menu) { return false; }
  for (var i = 0; i < data.menu.length; i++) {
    if (data.menu[i].at !== at) { continue; }
    var flips = clickFlips(data, data.menu[i].count, data.menu[i].period);
    return packPulses(pulseLengths(flips), data.cpuHz, sampleRate, volume);
  }
  return false;
} // menuSound
