// begin code

/**
 * The road and the things standing on it — measured off the original (M4).
 *
 * M3 gave the controlled Vorton his physics but left him alone in an empty
 * world: vortonPhysics.js knows where the road ends and nothing else, and asks
 * a `blocked(x, y)` callback about everything beyond that. This file is what
 * answers. It keeps the original's own entity table — 24 records of 16 bytes at
 * $8A00 (sources/docs/disasm_notes.md chap. 12) — and runs the rules that
 * table obeys: what stops the Vorton, what a shove does to what was shoved,
 * where a shot goes and what it does when it arrives. (The table turned out to
 * be longer than 24 records — M6 measured 42 of them going by, and what the
 * unused slots hold; see disasm_notes.md chap. 16.)
 *
 * Every constant comes from data/objects.json, which tools/dumpobjects.py
 * measures by driving the original in a simulator and reading its memory after
 * every pass of the main loop; tools/matchobjects.js then replays this code
 * against recorded runs (tools/traceobjects.py) and wants zero differences.
 *
 * The four rules the measurement found, none of them guessed:
 *
 * 1. **Collision is one box, 7 each way.** A step is refused when something
 *    stands within |dx| <= 7 and |dy| <= 7 of where it would land. One pair of
 *    numbers explains every refused and every allowed step of the thousands
 *    measured — no false alarm, no miss.
 * 2. **Shots are transparent.** They stop nobody; the Vorton drives straight
 *    through his own fire. An enemy does stop things, but it is not something
 *    to lean on: an object shoved into one gives up its speed for good instead
 *    of waiting. (What touching an enemy does to the *Vorton* is M6.)
 * 3. **A shove hands over direction and speed.** Whatever is run into takes the
 *    heading and the speed of whatever ran into it, moves off in the same pass,
 *    and then halves its speed every pass it manages to move: 4, 2, 1, stop.
 *    A shot pushes exactly as hard as a Vorton at speed 4, which is harder than
 *    a Vorton can drive. Wedged against another object it keeps a 1 and leans;
 *    wedged against the edge of the road it loses everything.
 * 4. **The camera is the player's zone.** The world is one continuous
 *    coordinate; a zone is 176 of it, and the view is the zone the controlled
 *    Vorton is standing in — it does not scroll, it jumps (disasm_notes.md
 *    chap. 6), and it jumps back if he drives back.
 *
 * Where the objects of a zone come from is **measured** as of M2, and it is
 * `enterZone()` below: the original keeps a second table of the same format at
 * $7B00 (240 records, data/highway.json), and on every zone change it writes
 * the live records back into it, then refills the live table from it — every
 * record whose `y` is inside a 512-long band past the window, in the table's
 * own order, at most 44 of them (data/zones.json, tools/dumpzones.py, and
 * disasm_notes.md chap. 17). That write-back is why the road remembers: a
 * barrel you shoved stays shoved and a wall you shot stays gone.
 *
 * Nor is it finished: tools/matchobjects.js still counts 68 differences in
 * 7862 passes (16 of its 24 recorded runs match to the last byte). What is
 * still wrong is written down in disasm_notes.md chap. 14 rather than papered
 * over here.
 */

var HighwayWorld = (function () {
  'use strict';

  // The original's table is longer than chap. 12 measured on the first zones:
  // 42 records went by in the demonstration run that drives the whole road,
  // an empty slot carries $FE in its x and the end of the table $FF
  // (tools/dumpenemies.py, disasm_notes.md chap. 16). M2 measured where the
  // 42 come from and what the ceiling is: the zone's own load fills from the
  // ninth place and copies at most 44 records (`LD A,$2C` at $93BE), so the
  // table cannot hold more than 9 + 44 (data/zones.json, tools/dumpzones.py).
  var SLOTS = 53;
  var PLAYER = 0;           // ...and the controlled Vorton starts in the first
  // a speed with the top bit set is not a speed: the record is destroyed and
  // its kind is walking up the dying animation's table (tools/dumpobjects.py)
  var MAX_SPEED = 4;
  var PLAYER_CLASS = 0;     // the controlled Vorton's kind word (measured)
  // ...and his kind byte, which is not the automatic Vorton's $0D: it is what
  // the drawing takes his heading from (data/physics.json spawn.kind, and the
  // records of build/ctraces/handover*.json, where the Vorton that is taken
  // over gets kind 14 in the same pass as kind word 0)
  var PLAYER_KIND = 0x0E;

  /**
   * @param {object} data - data/objects.json (tools/dumpobjects.py).
   * @param {object} physics - a VortonPhysics built from data/physics.json.
   * @param {object} [convoy] - data/convoy.json (tools/dumpconvoy.py). With it
   *        the four automatic Vortons and the Lasertron are stepped here (M5);
   *        without it they are left to whoever passes an `adopt` callback, the
   *        way M4 left them.
   * @param {object} [enemies] - data/enemies.json (tools/dumpenemies.py). With
   *        it the enemies and the dying animation are stepped here (M6).
   * @param {object} [sounds] - data/sounds.json (tools/dumpsound.py). With it
   *        the pass keeps the original's own sound request (M8): a bit mask
   *        the pass sets and the end of the pass resolves and clears, exactly
   *        as $8F15 works in the original.
   */
  function HighwayWorld(data, physics, convoy, enemies, sounds, projection) {
    this.data = data;
    this.physics = physics;
    this.convoy = convoy ? new (
      (typeof HighwayConvoy !== 'undefined') ? HighwayConvoy
        : require('./highwayConvoy.js'))(convoy) : null;
    this.enemies = enemies ? new (
      (typeof HighwayEnemies !== 'undefined') ? HighwayEnemies
        : require('./highwayEnemies.js'))(enemies) : null;
    // Where the table ends and how far along the road the world's window
    // starts: the enemies need both, because a step that would leave either
    // is refused by the same column of the collision matrix as a wall (M6).
    this.endSlot = SLOTS;
    this.windowStart = 0;
    // M8: the sound request. The original keeps one byte, $8F15: whoever wants
    // a sound sets a bit in it during the pass, and at the end of the pass a
    // chain of BIT tests takes the first bit in priority order, plays that one
    // effect and clears the byte (tools/dumpsound.py). Nothing is played here
    // — the world only says what was asked for.
    this.soundData = sounds || null;
    this.sound = 0;
    // M8: which families were sent into the dying animation in this pass. The
    // original scores off exactly that (tools/dumpscore.py) and whoever keeps
    // the score reads it here rather than guessing from the table.
    this.destroyed = [];
    this.soundBits = {};
    if (sounds) {
      for (var s0 = 0; s0 < sounds.sounds.length; s0++) {
        this.soundBits[sounds.sounds[s0].name] = sounds.sounds[s0].bit;
      }
    }
    // Whether this world computes only its enemies and takes everything else
    // from outside at its turn in the table — what tools/matchenemies.js does,
    // so that M6's numbers carry neither M4's nor M5's differences.
    this.borrowAll = false;
    // Which record the player is actually driving. It is the first one for as
    // long as he lives; lose him and the convoy hands over the lowest-numbered
    // record that is still an automatic Vorton, measured in tools/dumpconvoy.py.
    this.playerSlot = PLAYER;
    this.blankPasses = 0;
    // which of the five Vortons have been under control — that, and not how
    // many are left, is what the row of icons on the panel marks (measured,
    // sources/docs/disasm_notes.md chap. 15)
    this.controlledSlots = [PLAYER];
    this.box = data.collision.box;
    this.shotClass = data.shot['class'];
    // M2: který sprit má výstřel, rozhoduje bajt +10 jeho záznamu, a ten se
    // liší podle hlavně: slot 6 a 8 má $11, slot 7 má $12 – změřeno držením
    // SPACE (data/projection.json `sprite.shotSlots`, tools/dumpproj.py)
    this.shotKinds = {};
    var slots = projection && projection.sprite && projection.sprite.shotSlots;
    if (slots) {
      for (var slot in slots) {
        this.shotKinds[slot|0] = parseInt(String(slots[slot].kind)
                                          .replace('$', ''), 16);
      }
    }
    this.shotSpeed = data.shot.speed[data.shot.speed.length-1];
    this.shotSlots = data.shot.slots.slice();
    this.shotOffset = data.shot.spawnOffsetSteps;
    this.reload = data.shot.slotReloadSteps;
    this.shotLife = data.shot.lifetimeSteps;
    this.gap = data.shot.gapSteps;
    // what can be shoved, measured by whether it ever moved when something ran
    // into it (data/objects.json collision.pushableClasses)
    this.pushable = data.collision.pushableClasses;
    // ...and what answers a collision with a shrug: the rows of objects across
    // the road, which cost the Vorton a step of speed without the original
    // ever raising its hit flag (data/objects.json collision.fixedClasses)
    this.fixed = data.collision.fixedClasses;
    // What is solid enough to lean on: everything that stands on the road, and
    // the convoy. An enemy is not — an object shoved against one stops but
    // loses its speed instead of waiting for the way to clear (measured).
    this.solid = data.collision.blockingClasses.slice();
    for (var c = 0; c < data.push.objectClasses.length; c++) {
      if (this.solid.indexOf(data.push.objectClasses[c]) < 0) {
        this.solid.push(data.push.objectClasses[c]);
      }
    }
    // one reload counter per slot of the original's own three, plus the gap
    // between two shots of the same burst
    this.slotTimer = this.shotSlots.map(function () { return 0; });
    this.gapTimer = 0;
    this.zoneLength = data.zone.length;
    this.road = data.collision.road;
    this.dirs = physics.dirs;
    // measured, not assumed: whoever is driving carries this kind byte
    this.playerKind = (physics.data && physics.data.spawn
                       && physics.data.spawn.kind !== undefined)
                      ? physics.data.spawn.kind|0 : PLAYER_KIND;
    this.entities = new Array(SLOTS);
    for (var i = 0; i < SLOTS; i++) { this.entities[i] = null; }
    this.zone = 1;
    // M2: the road's own data and the rule that loads a zone out of it. Both
    // are measured or nothing happens — without them the world stays as M4
    // left it: a road with a convoy on it and nothing else.
    this.roadTable = null;
    this.rule = null;
  } // HighwayWorld

  /**
   * The road's own table and the rule that fills a zone from it (M2).
   *
   * @param {object} highway - data/highway.json (tools/dumphighway.py): the
   *        240 records of $7B00, in the original's own order.
   * @param {object} zones - data/zones.json (tools/dumpzones.py): the
   *        constants of the loading routine, read out of the game's own bytes.
   */
  HighwayWorld.prototype.setRoad = function (highway, zones) {
    if (!highway || !highway.records || !zones || !zones.load) { return false; }
    this.rule = {
      firstSlot: zones.load.toSlot,
      limit: zones.load.limit,
      span: zones.load.span,
      emptyX: parseInt(String(zones.load.skipEmptyX).replace('$', ''), 16),
      // the dying animation walks the kind word's low byte from $80 by eights,
      // and the clean-up after the load frees every record already in it
      deadFrom: zones.constants.deadFrom.value,
      deadTo: zones.constants.deadTo.value
    };
    this.roadTable = highway.records.map(function (r) {
      return {x: r.x, y: r.y, depth: r.depth,
              cls: parseInt(String(r.cls).replace('$', ''), 16),
              dir: r.dir, speed: r.speed, phase: r.phase, kind: r.kind,
              lane: r.extra};
    });
    return true;
  }; // setRoad

  /**
   * Entering a zone, the way the original does it — three routines in this
   * order, and the order matters (tools/dumpzones.py):
   *
   * 1. **$92CE writes the live records back.** Everything from the ninth place
   *    to the end of the table is copied into the record it was loaded from.
   *    The table at $7B00 is therefore not data, it is the **state of the
   *    world**: what you shoved stays where you left it.
   * 2. **$92F5 works out the zone and the window.** Already measured from the
   *    outside in M4 (data/objects.json): the zone is `y / 176`, and the
   *    window is where it starts.
   * 3. **$93B7 refills the table** from the ninth place: the whole road table
   *    is scanned in its own order and a record is taken when its `y` is less
   *    than 512 past the window — unsigned, so nothing behind the window comes
   *    with it. At most 44, and the rest of the table is empty.
   * 4. **$9400 cleans up.** A record whose kind word is inside the dying
   *    animation is freed for good, which is what keeps a destroyed object
   *    destroyed when you drive back into its zone.
   *
   * @param {number} zone - The zone the controlled Vorton has moved into.
   */
  HighwayWorld.prototype.enterZone = function (zone) {
    this.zone = zone;
    if (!this.roadTable) {
      this.windowStart = (zone-1)*this.zoneLength;
      return 0;
    }
    this.writeBackRoad();
    this.windowStart = (zone-1)*this.zoneLength;
    var taken = this.loadZone();
    this.cleanRoad();
    return taken;
  }; // enterZone

  /** Step 1: the live records go back into the road's table, 14 bytes each. */
  HighwayWorld.prototype.writeBackRoad = function () {
    if (!this.roadTable) { return 0; }
    var saved = 0;
    for (var i = this.rule.firstSlot; i < this.endSlot; i++) {
      var e = this.entities[i];
      if (!e || e.source === undefined) { continue; }
      var r = this.roadTable[e.source];
      if (!r) { continue; }
      r.x = e.x; r.y = e.y; r.depth = e.depth|0; r.cls = e.cls;
      r.dir = e.dir; r.speed = e.speed; r.phase = e.phase; r.kind = e.kind;
      r.lane = e.lane|0;
      saved++;
    }
    return saved;
  }; // writeBackRoad

  /** Step 3: the table refilled from the road's own data. */
  HighwayWorld.prototype.loadZone = function () {
    if (!this.roadTable) { return 0; }
    var slot = this.rule.firstSlot, taken = 0, i;
    for (i = slot; i < this.entities.length; i++) { this.entities[i] = null; }
    for (i = 0; i < this.roadTable.length && taken < this.rule.limit; i++) {
      var r = this.roadTable[i];
      // an empty place is skipped, and so is everything the window does not
      // reach — the original compares the high byte of `y - window` with 2
      if (r.x >= this.rule.emptyX) { continue; }
      if (((r.y - this.windowStart) & 0xFFFF) >= this.rule.span) { continue; }
      this.put(slot + taken, r).source = i;
      taken++;
    }
    // the end of the table is where the original writes its $FF, and that is
    // what the enemies read it as (highwayEnemies.js)
    this.endSlot = slot + taken;
    return taken;
  }; // loadZone

  /** Step 4: whatever is already dying is freed, and stays freed. */
  HighwayWorld.prototype.cleanRoad = function () {
    if (!this.roadTable) { return 0; }
    var freed = 0;
    for (var i = 0; i < this.roadTable.length; i++) {
      var r = this.roadTable[i], low = r.cls & 0xFF;
      if (low >= this.rule.deadFrom && low < this.rule.deadTo) {
        r.x = this.rule.emptyX;
        r.speed &= 0x7F;
        freed++;
      }
    }
    return freed;
  }; // cleanRoad

  /** An entity in the shape the original's record has it. */
  HighwayWorld.prototype.put = function (slot, e) {
    this.entities[slot] = e ? {x: e.x, y: e.y, dir: e.dir|0, speed: e.speed|0,
                               phase: e.phase|0, cls: e.cls|0, kind: e.kind|0,
                               // +12: which lane an enemy of family 4 draws
                               // its heading from; +3/+4: the drawing depth
                               lane: e.lane|0, depth: e.depth|0,
                               life: e.life === undefined ? 0 : e.life} : null;
    return this.entities[slot];
  }; // put

  HighwayWorld.prototype.player = function () {
    return this.entities[this.playerSlot];
  }; // player

  /**
   * Who is driving.
   *
   * The controlled Vorton is simply the record whose kind is 0, and it does
   * not stay in slot 0: when he is destroyed the record goes through its dying
   * animation (M6), vanishes, and **one pass later** the lowest-numbered
   * record that is still an automatic Vorton is given kind 0 and starts
   * listening to the keyboard — where it stands, with its own position and
   * animation phase. Measured on the original in tools/dumpconvoy.py; the
   * player does not restart, he takes over the convoy from the inside and the
   * convoy is one Vorton shorter.
   *
   * @returns {number} The slot now driving, or -1 while nobody is.
   */
  HighwayWorld.prototype.takeOver = function () {
    var i, e;
    for (i = 0; i < SLOTS; i++) {
      e = this.entities[i];
      if (e && e.cls === PLAYER_CLASS && e.speed <= MAX_SPEED) {
        this.playerSlot = i;
        this.blankPasses = 0;
        if (this.controlledSlots.indexOf(i) < 0) { this.controlledSlots.push(i); }
        return i;
      }
    }
    if (!this.convoy) { return -1; }
    // Nobody is driving. If the record he was in is still there but destroyed,
    // his dying animation is still running (M6 owns that) and the convoy waits
    // — measured at twelve passes, after which the record leaves the table and
    // the hand-over happens on the very next pass.
    e = this.entities[this.playerSlot];
    if (e && e.speed > MAX_SPEED) {
      this.blankPasses = 0;
      return -1;
    }
    this.blankPasses++;
    for (i = 0; i < SLOTS; i++) {
      e = this.entities[i];
      if (e && this.convoy.isVorton(e.cls) && e.speed <= MAX_SPEED) {
        e.cls = PLAYER_CLASS;
        e.kind = this.playerKind;
        this.playerSlot = i;
        this.blankPasses = 0;
        if (this.controlledSlots.indexOf(i) < 0) { this.controlledSlots.push(i); }
        return i;
      }
    }
    return -1;
  }; // takeOver

  HighwayWorld.prototype.isShot = function (e) {
    return e.cls === this.shotClass;
  }; // isShot

  /**
   * Can this be shoved? Only one measured kind of thing can: something that
   * never moves by itself and *was* seen to move when something ran into it
   * (data/objects.json `collision.pushableClasses`). The convoy is not one —
   * it moves by itself and never gave way — and neither are the rows across
   * the road, which are what `collision.fixedClasses` holds.
   */
  HighwayWorld.prototype.isPushable = function (e) {
    return this.pushable.indexOf(e.cls) >= 0;
  }; // isPushable

  /**
   * What stands at (x, y), if anything. Shots are transparent (measured), and
   * an entity never blocks itself.
   * @returns {object|null} The record in the way, or null.
   */
  HighwayWorld.prototype.at = function (x, y, exceptSlot, alsoExcept) {
    for (var i = 0; i < SLOTS; i++) {
      var e = this.entities[i];
      if (!e || i === exceptSlot || i === alsoExcept || this.isShot(e)) {
        continue;
      }
      if (Math.abs(e.x-x) <= this.box.x && Math.abs(e.y-y) <= this.box.y) {
        return {slot: i, entity: e};
      }
    }
    return null;
  }; // at

  /**
   * What is left of an object's speed when it could not move.
   *
   * It halves like a move does, but it never reaches nothing: an object wedged
   * against something sits there with a 1 in its record for as long as it is
   * wedged, and moves the moment the way clears. That is measured, and it is
   * what the game looks like — a barrel pressed against a wall is not "at
   * rest", it is still being pushed.
   */
  HighwayWorld.prototype.leaning = function (speed) {
    return speed > 1 ? (speed >> 1) : speed;
  }; // leaning

  /**
   * A shove: whatever was run into takes the heading and speed of whatever ran
   * into it. It moves off in this same pass, because the entity update below
   * runs after the mover — the original does the same, measured step by step.
   */
  HighwayWorld.prototype.shove = function (victim, dir, speed) {
    victim.dir = dir;
    victim.speed = speed;
    // ...and it is marked as shoved **in this pass**, which is what decides
    // whether it passes the shove on when it turns out it cannot move: a
    // barrel the Vorton is pushing shoves the barrel in front of it, a barrel
    // rolling on its own does not. Measured — three barrels in a row move as a
    // train while the Vorton leans on them, and stop dead the moment he lets
    // go.
    victim.shoved = true;
  }; // shove

  /**
   * The zone the controlled Vorton is standing in — that is the camera.
   *
   * A zone is 176 of the world's own coordinate, and the Vorton's position is
   * in that same coordinate: the zone counter and the window at $8F05 both
   * step by 176, and so does the y at which the view changes (measured at
   * 352, 528, 704 driving forward, and back again at 350 driving back). M3
   * read this coordinate as "half units" of a 352-long zone; it is not.
   */
  HighwayWorld.prototype.zoneOf = function (y) {
    var zone = Math.floor(y/this.zoneLength);
    // ...and it never falls below the first: drive back past the start of the
    // road and the view stays where it is, because there is no zone behind it
    return zone < 1 ? 1 : zone;
  }; // zoneOf

  /**
   * One pass of the original's main loop for the whole road.
   *
   * @param {number} keys - the keyboard bitmask the original builds ($8F14).
   * @param {function} [adopt] - adopt(slot, entity) is called at the turn of
   *   every entity this file does not simulate (the enemies, and the convoy
   *   too when no data/convoy.json was given), so whoever does can put it
   *   where it belongs at exactly that point in the table's order.
   * @param {function} [drive] - drive(slot, entity) is called for the
   *   **controlled Vorton** before his turn, which is the first turn of the
   *   pass. Returning `true` means "he is driven from outside this pass" and
   *   this file leaves his step and his trigger alone — that is what
   *   tools/matchconvoy.js uses to hold M4's Vorton still while it measures
   *   M5's convoy, which has to see him where the original left him.
   * @returns {object} what the pass did: {hit, shoved, fired, zone}.
   */
  HighwayWorld.prototype.step = function (keys, adopt, drive) {
    var self = this, out = {hit: false, shoved: null, fired: null,
                            zone: this.zone};
    this.destroyed = [];
    // 0a. who is driving. With a convoy this can change mid-game: lose the
    //     Vorton you are driving and the next one in the table takes over.
    if (this.convoy) { this.takeOver(); }
    var slot = this.playerSlot;
    var player = this.entities[slot];
    // The controlled Vorton's turn comes first in the table, and it comes
    // before everything else here — so whoever wants to drive him from outside
    // has to be asked first, or the convoy behind him would see him where he
    // was rather than where he went.
    var driven = !!(drive && player && drive(slot, player) === true);
    player = this.entities[slot];
    // the Vorton as the pass found him: the shot leaves from there and carries
    // that animation phase, not the one the pass leaves him with (measured —
    // firing while moving puts the shot two short of four steps ahead, and
    // four short at speed 2). Its heading, though, is the one he turned to.
    var from = player ? {x: player.x, y: player.y, phase: player.phase} : null;

    // 0. the camera. The zone is read off where the Vorton **stood** when the
    //    pass began, not where it leaves him: the original loads the new zone
    //    one pass after he crosses, and that pass is measurable — the port
    //    switched a step early until this was moved up here.
    if (player) {
      var zone = this.zoneOf(player.y);
      // M2: and entering a zone is not just a number changing — the road's
      // table is written back and the new zone loaded out of it
      if (zone !== this.zone) { this.enterZone(zone); }
    }
    out.zone = this.zone;

    // 1. the gun's three barrels count down. A barrel is spoken for 22 passes
    //    from the moment it fires and two passes must pass between any two
    //    shots — both measured on held-trigger runs, where the bursts come out
    //    exactly 22 passes apart and the shots inside them exactly two.
    for (var n = 0; n < this.slotTimer.length; n++) {
      if (this.slotTimer[n] > 0) { this.slotTimer[n]--; }
    }
    if (this.gapTimer > 0) { this.gapTimer--; }

    // 2. the Vorton. vortonPhysics.js owns the throttle, the turn and the
    //    step itself; the world only answers what stands in the way, and
    //    remembers what it was so it can be shoved below.
    var victim = null, pushSpeed = 0;
    if (player && !driven) {
      var result = this.physics.step(player, keys, function (nx, ny) {
        var found = self.at(nx, ny, slot);
        if (!found) { return 0; }
        // Which of the three answers M3 measured applies is decided by what
        // is in the way (disasm_notes.md chap. 13, point 5, left open there).
        // Something that can be shoved reports a collision and reloads the
        // throttle's shift register; something that cannot — the rows of
        // objects across the road — costs the same step of speed but raises
        // no flag and leaves the register running, which is why you can grind
        // into such a row over and over.
        if (self.fixed.indexOf(found.entity.cls) >= 0) {
          return VortonPhysics.BLOCK_SLOW;
        }
        if (self.isPushable(found.entity)) {
          victim = found.entity;
          pushSpeed = player.speed;
        }
        return VortonPhysics.BLOCK_HIT;
      });
      out.hit = result.hit;
      // The original's hit flag **is** the request for the bump sound: it is
      // the same byte, $8F15 bit 4 (tools/dumpsound.py, disasm_notes.md
      // chap. 13). M3 already reproduces when it is raised, so the sound
      // follows it for free.
      if (result.hit) { this.requestSound(this.soundBits.bump); }
      if (victim) {
        this.shove(victim, player.dir, pushSpeed);
        out.shoved = victim;
      }
    }

    // 3. the trigger. It comes before the movement below, and that is
    //    measurable: a shot born inside something never appears in the table
    //    at all — it knocks on it and is gone in the same pass, and the thing
    //    it knocked on has already moved by the time the pass ends.
    if (player && !driven) {
      out.fired = this.fire(player, keys, from);
      if (out.fired) { this.requestSound(this.soundBits.fire); }
    }

    // 4. everything of ours that is already moving: the shots, and the objects
    //    coasting off a shove. Slot order is the original's own, which is why
    //    two objects side by side are shoved on alternate passes rather than
    //    both at once — measured, and it is visible in the game.
    //
    //    The convoy and the enemies are **not** stepped here. They move by
    //    rules of their own (M5, M6) that have not been measured yet, and the
    //    honest thing is to leave them alone rather than to lend them the
    //    objects' physics: doing that made the port's automatic Vortons shove
    //    barrels the original's convoy stops in front of.
    for (var i = 0; i < SLOTS; i++) {
      var e = this.entities[i];
      if (!e || i === slot) { continue; }
      if (this.enemies && (this.enemies.owns(e.cls) || (e.speed & 0x80))) {
        // M6: the enemies, and any record walking its dying animation. Their
        // turn is here, in the table's own order, and that order is what the
        // measurement says it must be.
        this.enemies.stepEntity(this, i, e);
        continue;
      }
      if (this.borrowAll) {
        if (adopt) { adopt(i, e); }
        continue;
      }
      if (this.convoy && this.convoy.owns(e.cls)) {
        // M5: the convoy is ours now. Its turn is here, in the table's own
        // order, and that order is what the measurement says it must be —
        // a record sees the ones above it already moved.
        this.convoy.stepEntity(this, i, e);
        continue;
      }
      if (!this.isShot(e) && !this.isPushable(e)) {
        // Not ours to move — the convoy, the Lasertron, the enemies. Their
        // turn in the table still comes here, and it matters: an object one
        // slot below them sees where they were, one slot above sees where
        // they went. Whoever drives them (M5, M6, or the matcher replaying
        // the original) gets to put them in place at exactly this point.
        if (adopt) { adopt(i, e); }
        continue;
      }
      if (!e.speed || e.born) { continue; }
      this.moveEntity(i, e);
    }
    for (i = 0; i < SLOTS; i++) {
      if (this.entities[i]) {
        this.entities[i].shoved = false;
        this.entities[i].born = false;
      }
    }

    // M8: the end of the pass is where the original reads its sound request,
    // plays the winning effect and clears the byte ($9AEF, tools/dumpsound.py).
    out.sound = this.sound;
    out.play = this.takeSound();
    out.playSeed = this.playSeed;
    out.destroyed = this.destroyed;

    return out;
  }; // step

  /**
   * Ask for a sound: one bit in the pass's request, the way the original sets
   * a bit in $8F15. More than one can be asked for in the same pass — the end
   * of the pass decides which of them is heard.
   * @param {number} bit - The bit, from data/sounds.json.
   */
  HighwayWorld.prototype.requestSound = function (bit) {
    if (bit !== undefined) { this.sound |= 1 << bit; }
  }; // requestSound

  /**
   * Which effect a **dying** record asks for. Measured on the original
   * (tools/tracesound.py): a record walking its dying animation asks in every
   * pass of it, not only in the first, and which effect it is comes from its
   * family — the original's own dispatch at $9CF2, read into data/sounds.json.
   * @param {number} family - The record's family (chap. 16).
   */
  HighwayWorld.prototype.noteDestroyed = function (family) {
    this.destroyed.push(family);
  }; // noteDestroyed

  HighwayWorld.prototype.requestDyingSound = function (family) {
    var rule = this.soundData && this.soundData.dying;
    if (!rule) { return; }
    this.requestSound(family === 0 ? rule.familyZero
      : (family < rule.boundary ? rule.familyBelow : rule.familyAbove));
  }; // requestDyingSound

  /**
   * Takes the pass's sound request the way $9AEF does: the first bit in the
   * original's own priority order wins, and the request is cleared.
   * @returns {string|null} The name of the effect to play, or null.
   */
  HighwayWorld.prototype.takeSound = function () {
    var asked = this.sound;
    this.sound = 0;
    this.playSeed = 0;
    if (!asked || !this.soundData) { return null; }
    var order = this.soundData.flag.priority;
    for (var i = 0; i < order.length; i++) {
      if (!(asked & (1 << order[i]))) { continue; }
      for (var j = 0; j < this.soundData.sounds.length; j++) {
        var effect = this.soundData.sounds[j];
        if (effect.bit !== order[i]) { continue; }
        // The explosions draw their pitch and their length from the game's own
        // generator, and M8 measured how many draws each of them takes. That
        // is what M6 had to leave open (chap. 16): with it the port can keep
        // the generator's sequence through a sound instead of borrowing a seed
        // from a recording.
        if (this.enemies) {
          this.playSeed = this.enemies.seed;
          for (var d = 0; d < (effect.draws || 0); d++) { this.enemies.random(); }
        }
        return effect.name;
      }
    }
    return null;
  }; // takeSound

  /**
   * One entity's own move. A shot flies on at its speed and dies where it
   * arrives; anything else is coasting off a shove and halves its speed with
   * every pass it manages to move. Blocked by another object it keeps at least
   * a 1 and leans — that is why an object wedged against something sits there
   * with speed still in its record — but the edge of the road and an enemy
   * both take that last step of speed away.
   */
  HighwayWorld.prototype.moveEntity = function (slot, e) {
    var d = this.dirs[e.dir];
    var shot = this.isShot(e);
    if (shot && e.life >= this.shotLife) {
      // its range is up: it is gone before the move, and knocks on nothing
      this.entities[slot] = null;
      return;
    }
    var nx = e.x + d.dx*e.speed, ny = e.y + d.dy*e.speed;
    var blocker = this.at(nx, ny, slot, shot ? this.playerSlot : -1);
    if (blocker) {
      // Only a shot passes its shove on. An object rolling into another object
      // does not push it along — measured: a barrel shoved into a barrel stops
      // and the second one never stirs. Pushing is something the Vorton and
      // the laser do, not something a rolling object does.
      if (shot) {
        if (this.isPushable(blocker.entity)) {
          this.shove(blocker.entity, e.dir, e.speed);
        }
        this.entities[slot] = null;
      } else if (this.solid.indexOf(blocker.entity.cls) < 0) {
        // an enemy in the way is not something to lean on: the object stops
        // against it and gives up half its speed for good, down to nothing
        e.speed >>= 1;
      } else if (e.shoved) {
        if (this.isPushable(blocker.entity)) {
          this.shove(blocker.entity, e.dir, e.speed);
        }
      } else {
        e.speed = this.leaning(e.speed);
      }
      return;
    }
    if (nx < this.road.minX || nx > this.road.maxX) {
      // The road's edge swallows a shot, and it takes an object's speed away
      // for good rather than leaving it leaning: an object cannot press
      // against the edge of the road the way it presses against another
      // object, and the original writes a zero into its record.
      if (shot) { this.entities[slot] = null; } else { e.speed >>= 1; }
      return;
    }
    e.x = nx;
    e.y = ny;
    e.phase = (e.phase + d.spin*e.speed) & this.physics.phaseMask;
    if (shot) { e.life++; } else { e.speed >>= 1; }
  }; // moveEntity

  /**
   * The trigger.
   *
   * The instructions promise "bursts of three with a recharge", and the shape
   * of that turns out to be per **slot**: the original fires into three slots
   * of its own table, highest first, and a slot is spoken for 22 passes from
   * the moment it fires — whether its shot is still in the air or hit
   * something on the second pass. Two shots of a burst are also always two
   * passes apart. Both numbers are measured off held-trigger runs, where the
   * bursts come out exactly 22 passes apart and the shots inside them exactly
   * two.
   *
   * A shot appears four steps ahead of the Vorton in the heading he faces, and
   * does not move in the pass it is born in.
   */
  HighwayWorld.prototype.fire = function (player, keys, from) {
    if (!(keys & VortonPhysics.KEYS.FIRE) || this.gapTimer > 0) { return null; }
    for (var n = this.shotSlots.length-1; n >= 0; n--) {
      var barrel = this.shotSlots[n];
      // A barrel comes free 22 passes after it fired, and firing it again
      // takes over whatever is still in it: with the trigger held, a shot that
      // has reached nothing is cut off one pass before its range would have
      // run out, and that is exactly what the original does.
      if (this.slotTimer[n] > 0) { continue; }
      this.slotTimer[n] = this.reload;
      this.gapTimer = this.gap;
      var d = this.dirs[player.dir];
      var at = from || player;
      var shot = this.put(barrel, {
        x: at.x + d.dx*this.shotOffset,
        y: at.y + d.dy*this.shotOffset,
        dir: player.dir, speed: this.shotSpeed, phase: at.phase,
        cls: this.shotClass, kind: this.shotKinds[barrel]|0, life: 0
      });
      shot.born = true;
      // Fired off the side of the road: the barrel is spent all the same,
      // which is why firing while pinned against the edge quietly eats a shot
      // of the burst.
      if (shot.x < this.road.minX || shot.x > this.road.maxX) {
        this.entities[barrel] = null;
        return null;
      }
      // Fired point blank: the shot is spent where it appears, and shoves what
      // it appeared in. The Vorton who fired it is not in its way — the muzzle
      // is only four steps ahead of him, well inside the collision box, so a
      // shot that stopped on him could never leave the barrel.
      var into = this.at(shot.x, shot.y, barrel, this.playerSlot);
      if (into) {
        if (this.isPushable(into.entity)) {
          this.shove(into.entity, shot.dir, shot.speed);
        }
        this.entities[barrel] = null;
        return null;
      }
      return shot;
    }
    return null;
  }; // fire

  HighwayWorld.PLAYER = PLAYER;
  HighwayWorld.SLOTS = SLOTS;

  return HighwayWorld;
})();

if (typeof self !== 'undefined') { self.HighwayWorld = HighwayWorld; }
if (typeof module !== 'undefined' && module.exports) { module.exports = HighwayWorld; }
