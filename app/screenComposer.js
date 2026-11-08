const { ZXVideoRAM } = await import('./svision/js/platform/canvas2D/zx/zxVideoRAM.js?ver='+window.srcVersion);
// begin code

/**
 * Composes the Highway Encounter screen in the video memory of the machine.
 *
 * Everything it draws comes out of the original: the panel is the video memory
 * of a running original (data/panel.json, tools/dumppanel.py — the game keeps
 * it as a finished picture at $6000 rather than setting it in a character set,
 * see sources/docs/disasm_notes.md chap. 3), the loading screen is the block
 * off the original tape (data/loading.json, tools/mkscreen.py), and the type is
 * the game's own — M7 found the character set that had been open since M1
 * (data/font.json, tools/dumpfont.py, chap. 2). Nothing here is drawn by hand.
 *
 * It writes into a {@link ZXVideoRAM} — the 6912 bytes in the ULA's own
 * interleaved order — so the attribute clash is reproduced rather than removed
 * (ZADANI chap. 1). GameAreaEntity calls {@link ScreenComposer#composeInto} and
 * GameInfoEntity {@link ScreenComposer#composePanelInto}, each into its own
 * memory, and the library turns the bytes into pixels (R-003). What is here is
 * only what the original does and this remake measured: the projection, the
 * depth sort, the mask-and-image blit with its four shifts, the panel. The
 * offline tools (tools/matchscreen.js, tools/renderframe.js) compose into a
 * memory of their own.
 *
 * The highway is drawn as of M2, and drawn the way the original draws it: the
 * picture of the zone first (data/scenery.json — photographed at the one moment
 * the original has it on the screen whole and objectless), then the objects on
 * top of it, depth-sorted, placed by the measured projection and blitted mask
 * first through `AND` and image through `OR` (data/spriteframes.json,
 * data/projection.json), and the whole thing clipped to the parallelogram the
 * original copies out of its own buffer. See sources/docs/disasm_notes.md
 * chap. 8 for how that was found and what is still open.
 *
 * Free of DOM dependencies, so an offline tool loads it under Node behind the
 * `nodeEnv.mjs` shim (R-001).
 */

// the panel sits on character rows 19 to 23 (sources/docs/screen_layout.md)
const PANEL_ROW_FIRST = 19;


export class ScreenComposer {

  static get WIDTH() { return 256; }
  static get COLS() { return 32; }
  static get CELL() { return 8; }
  /** the panel sits on the last five character rows, y = 152..191 */
  static get PANEL_ROWS() { return 5; }
  /** the play area in character cells: rows 0-18 of the screen */
  static get PLAY_AREA() { return {col: 0, row: 0, cols: 32, rows: 19}; }
  /** the panel in character cells: rows 19-23 of the screen */
  static get PANEL_AREA() { return {col: 0, row: PANEL_ROW_FIRST, cols: 32, rows: 5}; }

  /**
   * @param {Object} [panel] - The parsed data/panel.json (bitmap + attributes
   *        of the panel, base64). Without it the panel stays black.
   * @param {Object} [fields] - The parsed data/panelfields.json: the pictures
   *        of the panel's live fields, one per value, photographed off the
   *        running original (tools/dumppanelfields.py). Without it the panel
   *        shows the values the original starts a game with.
   * @param {Object} [font] - The parsed data/font.json: the game's own
   *        character set (M7, tools/dumpfont.py). Without it nothing is set in
   *        type — which is where M1 to M6 stood, because the character set had
   *        not been found.
   * @param {Object} [ending] - The parsed data/ending.json: the end sequence,
   *        with the picture of the panel's LASERTRON ACTIVATED and the bytes
   *        of the text it prints (tools/dumpending.py).
   * @param {Object} [score] - The parsed data/score.json: the digits of SCORE
   *        and HIGH and where they go (M8, tools/dumpscore.py). Without it the
   *        two fields stay as the panel's picture drew them.
   * @param {Object} [scenery] - The parsed data/scenery.json (M2): the picture
   *        of the road, zone by zone, photographed at the moment the original
   *        paints it and before it draws a single object (tools/dumpgfx.py).
   *        Without it the play area stays black, which is where M1 to M8 stood.
   * @param {Object} [sprites] - The parsed data/spriteframes.json (M2): the 56
   *        frames of 24x24 pixels the original keeps at $B980, mask and image
   *        three bytes at a time (tools/dumpsprites.py).
   * @param {Object} [projection] - The parsed data/projection.json (M2): how a
   *        world coordinate becomes a place on the screen, how deep the sprites
   *        sort and which frame a record picks (tools/dumpproj.py).
   */
  constructor(panel, fields, font, ending, score, scenery, sprites, projection) {
    this.panel = null;
    if (panel && panel.bitmap && panel.attributes) {
      this.panel = {
        rows: panel.rows || ScreenComposer.PANEL_ROWS,
        bitmap: ZXVideoRAM.decode(panel.bitmap),
        attributes: ZXVideoRAM.decode(panel.attributes)
      };
    }
    this.fields = null;
    if (fields && fields.zone && fields.vortons) {
      const zone = {};
      Object.keys(fields.zone.values).forEach((key) => {
        zone[key] = ZXVideoRAM.decode(fields.zone.values[key]);
      });
      this.fields = {
        panelRow: fields.panelRow,
        zone: Object.assign({}, fields.zone, {
          values: zone,
          attributes: ZXVideoRAM.decode(fields.zone.attributes)
        }),
        vortons: Object.assign({}, fields.vortons, {
          icons: fields.vortons.icons.map((icon) => ({
            controlled: icon.controlled ? ZXVideoRAM.decode(icon.controlled) : null,
            waiting: icon.waiting ? ZXVideoRAM.decode(icon.waiting) : null
          }))
        })
      };
    }
    this.font = null;
    if (font && font.bitmaps) {
      this.font = {
        glyphs: font.bitmaps.map((glyph) => ZXVideoRAM.decode(glyph)),
        attributes: font.attributes || {'00': '$46', '10': '$03',
                                        '01': '$07', '11': '$47'}
      };
    }
    // M8: SCORE and HIGH. The digits are not the character set of data/font.json
    // — the score has a five-byte font of its own at $A490 — and the seventh
    // digit is never drawn: the trailing zero belongs to the panel's picture,
    // which is why every score in this game is a multiple of ten.
    this.score = null;
    if (score && score.glyphs) {
      const glyphs = ZXVideoRAM.decode(score.glyphs.bytes);
      this.score = {
        digits: score.digits, unit: score.unit, rows: score.glyphs.rows,
        glyphs: glyphs, cells: score.cells,
        // POWER turned out to be the gun's magazine, one cell per barrel:
        // full while the barrel's shot is not in flight (data/score.json)
        power: score.power || null
      };
    }
    // M2: the road itself. Everything the play area needs comes in these
    // three, and each of them is a measurement: the picture of the zone, the
    // frames of the sprites and the arithmetic that places them.
    this.scenery = null;
    if (scenery && scenery.zones) {
      const zones = {};
      Object.keys(scenery.zones).forEach((key) => {
        zones[key] = {
          bitmap: ZXVideoRAM.decode(scenery.zones[key].bitmap),
          attributes: ZXVideoRAM.decode(scenery.zones[key].attributes)
        };
      });
      // the parallelogram: the only part of the play area the original ever
      // copies out of its buffer, so the only part an object can appear in
      const bands = {};
      const rows = (scenery.bands && scenery.bands.rows) || {};
      Object.keys(rows).forEach((row) => { bands[row|0] = rows[row]; });
      this.scenery = {zones: zones, bands: bands,
                      rowBytes: scenery.rowBytes || ScreenComposer.COLS};
    }
    this.sprites = null;
    if (sprites && sprites.frames) {
      this.sprites = {
        frames: sprites.frames.map((frame) => ZXVideoRAM.decode(frame)),
        // the table at $7A00, as frame numbers: the byte offset the record
        // computes, halved, indexes it
        pointers: (sprites.pointers && sprites.pointers.frames) || [],
        rows: (sprites.frame && sprites.frame.rows) || 24,
        rowBytes: (sprites.frame && sprites.frame.rowBytes) || 6
      };
    }
    // the zone's picture with its standing objects composited in, kept for as
    // long as the camera is on that zone — see drawObjects()
    this.composite = {zone: null, memory: null};
    this.projection = (projection && projection.projection)
      ? {rowConst: projection.projection.rowConst,
         colConst: projection.projection.colConst,
         skip: (projection.depth && projection.depth.skip
                && projection.depth.skip.field6 || ['$16', '$19'])
                 .map((value) => parseInt(String(value).replace('$', ''), 16))}
      : null;
    this.ending = null;
    if (ending && ending.panelMessage) {
      const message = ending.panelMessage;
      this.ending = {
        // the panel as the sequence leaves it: the ZONE field empty and the
        // row of Vortons gone, photographed off the original (the picture the
        // panel normally shows still has the number of the zone in it)
        panel: ending.panel && {
          bitmap: ZXVideoRAM.decode(ending.panel.bitmap),
          attributes: ZXVideoRAM.decode(ending.panel.attributes)
        },
        message: ZXVideoRAM.decode(message.bitmap),
        rows: message.rows,
        cols: message.cols,
        glyphRows: message.glyphRows,
        at: message.screen.map((address) => ScreenComposer.at(address)),
        attribute: parseInt(message.attribute.replace('$', ''), 16)
      };
    }
  } // constructor

  /**
   * Character row and column of a screen address, the way the original's
   * strings carry it — `$40E8` is the bitmap of a cell, `$58E8` the attribute
   * of the same one, and the low byte they share is its row and column.
   * @param {string|number} address - `"$40E8"` or 0x40E8.
   * @returns {{row: number, col: number}} Where on the screen it lands.
   */
  static at(address) {
    const value = (typeof address === 'string')
                  ? parseInt(String(address).replace('$', ''), 16) : address;
    const low = value & 0xFF;
    return {row: ((value >> 11) & 3)*8 + ((low >> 5) & 7), col: low & 31};
  } // at

  /**
   * Sets one line of one of the original's own strings into the memory — the
   * game's own type, with the game's own glyphs.
   *
   * How the original does it, measured in tools/dumpfont.py: the glyph is
   * **five bytes** at $5B00 + 5*(code AND $3F), and the cell it builds around
   * it is `00`, `$7F`, those five bytes, `$7F` — which is why searching video
   * memory for eight-byte glyphs never found the character set
   * (sources/docs/disasm_notes.md chap. 2). Bits 6 and 7 of the code do not
   * pick a letter, they pick one of four colours.
   * @param {ZXVideoRAM} videoRAM - Target memory.
   * @param {Object} line - {screen, codes} out of data/ending.json; `screen`
   *        is the address of the first cell, so it says where the line goes.
   * @param {Object} area - {row, rows} the character rows the line may touch.
   */
  setLine(videoRAM, line, area) {
    if (!this.font || !line || !line.codes) {
      return;
    }
    const at = ScreenComposer.at(line.screen);
    const row = at.row;
    if (row < area.row || row >= area.row+area.rows) {
      return;
    }
    for (let i = 0; i < line.codes.length; i++) {
      const code = line.codes[i];
      const col = at.col + i;
      if (col >= ScreenComposer.COLS) {
        break;
      }
      const key = ((code & 0x80) ? '1' : '0')+((code & 0x40) ? '1' : '0');
      const attribute = this.font.attributes[key];
      videoRAM.pokeAttribute(row, col, (typeof attribute === 'string')
        ? parseInt(attribute.replace('$', ''), 16) : attribute);
      const glyph = this.font.glyphs[code & 0x3F];
      videoRAM.pokeOffset(ZXVideoRAM.lineOffset(row*8)+col, 0);
      videoRAM.pokeOffset(ZXVideoRAM.lineOffset(row*8+1)+col, 0x7F);
      for (let r = 0; r < 5; r++) {
        videoRAM.pokeOffset(ZXVideoRAM.lineOffset(row*8+2+r)+col, glyph ? glyph[r] : 0);
      }
      videoRAM.pokeOffset(ZXVideoRAM.lineOffset(row*8+7)+col, 0x7F);
    }
  } // setLine

  /**
   * Blits one measured block of character cells into the panel.
   *
   * The blocks come out of data/panelfields.json exactly as they sit in the
   * original's video memory — pixel rows top to bottom, one byte per eight
   * pixels — so putting them back is a copy, not a drawing routine. Nothing
   * here is set in a font, and not because there is none: the digits of ZONE
   * are drawn in a big segmented face of their own, not in the character set
   * M7 found (sources/docs/disasm_notes.md chap. 2), so they stay photographs
   * of the original showing that very number.
   * @param {ZXVideoRAM} videoRAM - Target memory.
   * @param {Uint8Array} block - The measured block.
   * @param {number} col - Character column of the block.
   * @param {number} row - Character row **within the panel**.
   * @param {number} cols - Width of the block in character cells.
   */
  static blit(videoRAM, block, col, row, cols) {
    const lines = block.length/cols;
    for (let line = 0; line < lines; line++) {
      const at = ZXVideoRAM.lineOffset((PANEL_ROW_FIRST+row)*8+line)+col;
      for (let i = 0; i < cols; i++) {
        videoRAM.pokeOffset(at+i, block[line*cols + i]);
      }
    }
  } // blit

  /**
   * Renders the play area — the highway.
   *
   * This is what M2 measured, and it works the way the original works
   * (sources/docs/disasm_notes.md chap. 8):
   *
   * 1. the **picture of the zone** goes down first — road, verges and scenery,
   *    photographed off the original at the one moment it is on the screen
   *    whole and with no object on it, which is the pass that enters the zone
   *    (data/scenery.json, tools/dumpgfx.py). Its attributes come with it;
   * 2. the objects go on top of it, **sorted by depth**: the key is
   *    `(d >> 1) + (x >> 1) + 1`, the same insertion sort into the same order
   *    the original keeps at $8D52, drawn from the far end forward;
   * 3. each object is placed by the **measured projection** — row
   *    `158 - ((d + x) >> 1)`, pixel `d - x + 24` — and drawn as the original
   *    draws it: three bytes of mask through `AND`, three of image through
   *    `OR`, 24 rows from the bottom up, shifted inside the cell by one of
   *    four variants two pixels apart (data/projection.json);
   * 4. and it is all clipped to the **parallelogram** the original copies out
   *    of its buffer — 363 cells of 608 — so nothing can appear where the
   *    original could not have put it.
   *
   * Everything the road holds is drawn from the records the worker sends, and
   * as of M2 those include the zone's own contents: the world fills itself
   * from the original's table of road data (data/highway.json,
   * data/zones.json), so the barrels, the walls and the enemies stand where
   * the original stands them.
   *
   * The whole memory is replaced by the zone's picture, so the panel rows come
   * out empty — the panel is another entity with a memory of its own.
   * @param {ZXVideoRAM} videoRAM - The memory to write.
   * @param {Object} state - The frame state from the worker.
   */
  composeInto(videoRAM, state) {
    var area = ScreenComposer.PLAY_AREA;
    // M2: the zone's own picture, and its attributes with it
    var zone = this.scenery && state
      ? this.scenery.zones[String(state.zone)] : null;
    if (zone) {
      videoRAM.restore(this.zoneBase(state, zone));
    } else {
      videoRAM.clearArea(area, 0);
    }
    // M7: the end of the game. What it does to the play area is measured
    // (tools/dumpending.py): the attributes are flooded — white while the ship
    // breaks up, then plain — and the message that announces the second pass
    // is set with the game's own character set, from the game's own bytes.
    // The break-up itself is not drawn: it is graphics, and the projection and
    // the sprites are M2 and M8.
    var ending = state && state.ending;
    if (ending) {
      if (ending.attribute !== null && ending.attribute !== undefined) {
        videoRAM.fillAttributes(area, ending.attribute);
      }
      (ending.text || []).forEach((line) => {
        this.setLine(videoRAM, line, area);
      });
    } else if (zone) {
      this.drawObjects(videoRAM, state, false);
    }
  } // composeInto

  /**
   * The picture the pass starts from: the zone's own, with the objects that
   * **stand still** already on it.
   *
   * The original leaves those out of the list it sorts and draws every pass
   * ($9872 skips the records whose byte +6 is $16 or $19) — it draws them into
   * its buffer once, as the zone is entered, and then lets them stand. That is
   * why they are composited here once per zone and not redrawn: a record that
   * was out of the camera's window when the zone was entered never appears at
   * all, which is exactly what the original shows, and drawing them every pass
   * would put them on the road where the original has bare tarmac.
   * @param {Object} state - The frame state from the worker.
   * @param {Object} zone - The zone's decoded picture.
   * @returns {ZXVideoRAM} The memory to start the pass from; not to be written.
   */
  zoneBase(state, zone) {
    if (this.composite.zone === state.zone && this.composite.memory) {
      return this.composite.memory;
    }
    var area = ScreenComposer.PLAY_AREA;
    var memory = new ZXVideoRAM().setLinear(area,
      zone.bitmap.subarray(0, area.cols*area.rows*8),
      zone.attributes.subarray(0, area.cols*area.rows));
    this.drawObjects(memory, state, true);
    // not kept until there is a frame to keep: without the camera nothing was
    // composited, and caching that would leave the zone without its objects
    if (state.cam !== undefined) {
      this.composite = {zone: state.zone, memory: memory};
    }
    return memory;
  } // zoneBase

  /**
   * Puts the objects on the road, depth-sorted, the way the original does.
   * @param {ZXVideoRAM} videoRAM - Target memory.
   * @param {Object} state - The frame state from the worker.
   * @param {boolean} standing - True to draw the records that stand still,
   *        false to draw the rest.
   */
  drawObjects(videoRAM, state, standing) {
    if (!this.sprites || !this.projection || state.cam === undefined) {
      return;
    }
    var order = [];
    var records = (state.objects || []).slice();
    // the controlled Vorton is the table's own zeroth record; the worker sends
    // him separately, so he is put back where the original has him
    if (state.vorton) { records[0] = state.vorton; }
    for (var i = 0; i < records.length; i++) {
      var e = records[i];
      if (!e) { continue; }
      // the records that stand still go into the zone's picture once (see
      // zoneBase), the rest are drawn every pass
      var stands = this.projection.skip.indexOf((e.cls >> 8) & 0xFF) >= 0;
      if (stands !== !!standing) { continue; }
      var d = (e.y - state.cam) & 0xFFFF;
      if (d > 0xFF) { continue; }        // outside the camera's window
      order.push({key: (d >> 1) + (e.x >> 1) + 1, d: d, e: e, slot: i});
    }
    // Far end first: the original inserts into a list whose key falls and
    // draws it in that order — a painter, nothing more. Where two records
    // share a key the later slot goes first, because the insertion at $989B
    // stops at the first entry whose key is not greater and puts the new one
    // in front of it.
    order.sort(function (a, b) { return b.key - a.key || b.slot - a.slot; });
    for (var n = 0; n < order.length; n++) {
      var item = order[n];
      var frame = this.frameOf(item.e, state.anim);
      if (!frame) { continue; }
      var px = (item.d - item.e.x + this.projection.colConst) | 0;
      this.drawSprite(videoRAM, frame, this.projection.rowConst
                      - ((item.d + item.e.x) >> 1), px >> 3, px & 6);
    }
  } // drawObjects

  /**
   * Which of the 56 frames a record draws: the table at $7A00, indexed by the
   * record's own type byte plus the animation byte of its kind.
   *
   * The animation byte is measured (data/projection.json `sprite.animation`):
   * for the enemies it is a counter of four frames the worker steps, for the
   * controlled Vorton it is **twice his heading**, which is how his eight
   * rotations are chosen.
   * @param {Object} e - The record.
   * @param {Object} [anim] - The animation bytes by kind, from the worker.
   * @returns {Uint8Array|null} The frame, or null when there is none.
   */
  frameOf(e, anim) {
    var kind = e.kind|0;
    var animation = (kind === 0x0E)
      ? ((e.dir|0)*2)
      : ((anim && anim[String(kind)]) || 0);
    var offset = (animation + (e.cls & 0xFF)) & 0xFF;
    var index = this.sprites.pointers[offset >> 1];
    return (index === undefined) ? null : (this.sprites.frames[index] || null);
  } // frameOf

  /**
   * Draws one 24x24 sprite into the play area, as the original's routine does
   * it: from the bottom row up, three bytes of mask through `AND` and three of
   * image through `OR`, and the shift inside the cell done here rather than
   * held as pre-shifted copies — four variants two pixels apart, which is
   * exactly the isometric raster (disasm_notes.md chap. 8).
   *
   * Clipped to the parallelogram the original copies out of its buffer, so a
   * sprite cannot show up in a cell the original never refreshes.
   * @param {ZXVideoRAM} videoRAM - Target memory.
   * @param {Uint8Array} frame - The 144 bytes of the frame.
   * @param {number} row - Pixel row the sprite stands on.
   * @param {number} col - Character column of its three-byte window.
   * @param {number} shift - 0, 2, 4 or 6: which of the four variants.
   */
  drawSprite(videoRAM, frame, row, col, shift) {
    var cols = ScreenComposer.COLS, rows = ScreenComposer.PLAY_AREA.rows;
    var height = this.sprites.rows;
    var stride = this.sprites.rowBytes;
    var bands = this.scenery ? this.scenery.bands : null;
    // The original's four entry points, measured at $9915: shift the triple
    // left by four ($99D1, and then only two bytes are left to write), left by
    // two ($9A26), not at all ($9A70), or right by two ($9933).
    // shift is 0, 2, 4 or 6 pixels of the cell; the four routines shift the
    // triple left by 4, left by 2, not at all and right by 2 respectively
    var left = 4 - shift;
    var bytes = (left === 4) ? 2 : 3;
    for (var r = 0; r < height; r++) {
      var line = row - r;
      if (line < 0 || line >= rows*8) { continue; }
      var band = bands ? bands[line >> 3] : null;
      var at = ZXVideoRAM.lineOffset(line);
      var mask = (frame[r*stride] << 16) | (frame[r*stride+1] << 8)
                 | frame[r*stride+2];
      var image = (frame[r*stride+3] << 16) | (frame[r*stride+4] << 8)
                  | frame[r*stride+5];
      if (left > 0) {
        // rotating left feeds ones into the mask (the original sets the carry)
        // and zeros into the image
        mask = ((mask << left) | ((1 << left) - 1)) & 0xFFFFFF;
        image = (image << left) & 0xFFFFFF;
      } else if (left < 0) {
        // rotating right copies the mask's top bit (`SRA`) and clears the
        // image's (`SRL`)
        var top = (mask & 0x800000) ? (0xFFFFFF << (24+left)) & 0xFFFFFF : 0;
        mask = (mask >>> -left) | top;
        image = image >>> -left;
      }
      for (var i = 0; i < bytes; i++) {
        var column = col + i;
        if (column < 0 || column >= cols) { continue; }
        if (band && (column < band[0] || column > band[1])) { continue; }
        // mask through AND, image through OR, as the original's routine does
        videoRAM.pokeOffset(at+column, (mask >>> (16 - i*8)) & 0xFF, 'and');
        videoRAM.pokeOffset(at+column, (image >>> (16 - i*8)) & 0xFF, 'or');
      }
    }
  } // drawSprite

  /**
   * Renders the panel (256x40) at the bottom of the screen.
   *
   * The panel is not set in a character set: the original keeps it as a
   * finished picture and copies it to the screen, so what is painted here is
   * that picture, read out of the video memory of the running game
   * (data/panel.json). Two of its live fields are measured as of M5 and are
   * blitted over it, again as pictures rather than as type
   * (data/panelfields.json, tools/dumppanelfields.py):
   *
   * * **ZONE**, the big two-digit number, photographed for every value the
   *   game ever shows — all 31 of them, off the original's own demonstration
   *   mode, which drives the whole road by itself;
   * * **the row 1 2 3 4 5**, whose icons turn out not to count down. Losing an
   *   automatic Vorton changes nothing on the panel; an icon fills in when the
   *   player starts driving *that* Vorton, and stays filled afterwards. The
   *   row shows how far through the five you are, not how many are left, which
   *   is the opposite of what ZADANI chap. 7 assumed — and it is measured.
   *
   * * **SCORE and HIGH**, as of M8. They are not set in the character set of
   *   data/font.json: the score has a five-byte font of its own at $A490 and
   *   six digits at $A481, drawn right to left, and the seventh digit is never
   *   drawn at all — the trailing zero is part of the panel's picture, which is
   *   why every score in this game is a multiple of ten (tools/dumpscore.py).
   *
   * POWER and TIME are still the picture's own. What POWER counts came out with
   * the sound in M8 — it is the magazine of the gun, one cell per shot in
   * flight (data/sounds.json `power`) — but the panel's bar for it has not been
   * measured cell by cell yet.
   *
   * Only the five rows of the panel are written; the rest of the memory is
   * left alone.
   * @param {ZXVideoRAM} videoRAM - The memory to write.
   * @param {Object} panel - {zone, score, high, power, time, vortons,
   *        vortonMarks}. `vortonMarks` says which of the five icons are filled.
   */
  composePanelInto(videoRAM, panel) {
    var cols = ScreenComposer.COLS;
    var area = ScreenComposer.PANEL_AREA;
    if (!this.panel) {
      videoRAM.clearArea(area, 0);
      return;
    }
    var fields = this.fields;
    // M7: while the end sequence runs the panel is the sequence's own — it
    // clears the ZONE field and the row of Vortons when the convoy goes and
    // never puts either back
    var picture = (fields && panel.endingPanel && this.ending && this.ending.panel)
      ? this.ending.panel : this.panel;
    videoRAM.setLinear(area, picture.bitmap, picture.attributes);
    if (!fields) {
      return;
    }
    var zone = panel.endingPanel ? null : fields.zone.values[String(panel.zone)];
    if (zone) {
      ScreenComposer.blit(videoRAM, zone, fields.zone.col, fields.zone.rowInPanel,
                        fields.zone.cols);
      for (var r = 0; r < fields.zone.rows; r++) {
        for (var c = 0; c < fields.zone.cols; c++) {
          videoRAM.pokeAttribute(area.row+fields.zone.rowInPanel+r, fields.zone.col+c,
                                 fields.zone.attributes[r*fields.zone.cols + c]);
        }
      }
    }
    // M7: while the end sequence runs, LASERTRON ACTIVATED sits where ZONE
    // was — not set in type but blitted, because the original keeps it as a
    // picture of its own: two character rows of eight cells, five pixel rows
    // of data in each, and one flashing attribute over all of them.
    if (panel.endingMessage && this.ending) {
      var e = this.ending;
      for (var mr = 0; mr < e.rows; mr++) {
        for (var mc = 0; mc < e.cols; mc++) {
          var row = e.at[mr].row;
          var col = e.at[mr].col + mc;
          if (row < area.row || row >= area.row+area.rows || col >= cols) { continue; }
          // the original writes the cell as one blank row, five rows of the
          // picture and two blank rows — so the panel underneath is cleared,
          // not drawn over
          for (var line = 0; line < 8; line++) {
            videoRAM.pokeOffset(ZXVideoRAM.lineOffset(row*8+line)+col,
              (line >= 1 && line <= e.glyphRows)
                ? e.message[(mr*e.cols + mc)*e.glyphRows + line - 1] : 0);
          }
          videoRAM.pokeAttribute(row, col, e.attribute);
        }
      }
    }
    var marks = panel.endingPanel ? [] : (panel.vortonMarks || []);
    for (var i = 0; panel.endingPanel ? false : i < fields.vortons.count; i++) {
      var icon = fields.vortons.icons[i];
      var block = marks[i] ? icon.controlled : icon.waiting;
      if (block) {
        ScreenComposer.blit(videoRAM, block, fields.vortons.col + i*fields.vortons.step,
                          fields.vortons.rowInPanel, fields.vortons.step);
      }
    }
    this.setPower(videoRAM, panel.power);
    this.setNumber(videoRAM, panel.score, this.score && this.score.cells.score);
    this.setNumber(videoRAM, panel.high, this.score && this.score.cells.high);
  } // composePanelInto

  /**
   * POWER: three cells, one per barrel of the gun, full while that barrel's
   * shot is not in flight. It is drawn straight into the attributes — the
   * original writes $44 or $00 into the cell rather than touching the bitmap
   * (data/score.json `power`, tools/dumpscore.py).
   * @param {ZXVideoRAM} videoRAM - Target memory.
   * @param {number} power - How full the magazine is, 0 to 1.
   */
  setPower(videoRAM, power) {
    var bar = this.score && this.score.power;
    if (!bar || power === undefined || power === null) { return; }
    var full = Math.round(Math.max(0, Math.min(1, power))*bar.cells.length);
    for (var i = 0; i < bar.cells.length; i++) {
      var addr = parseInt(bar.cells[i].slice(1), 16);
      videoRAM.pokeAddress(addr, parseInt((i < full ? bar.full : bar.empty).slice(1), 16));
    }
  } // setPower

  /**
   * Writes one of the panel's two numbers the way the original writes it:
   * right to left from one cell, five pixel rows of a glyph each, and nothing
   * cleared around them — the rest of the cell is the panel's own picture.
   *
   * Leading zeros are blank, because in the original an untouched digit holds
   * zero and zero is the blank glyph; a digit a carry has reached holds 1 to 10
   * for 0 to 9. The value is divided by the unit first: the digit the panel
   * paints on the end is not stored anywhere.
   * @param {ZXVideoRAM} videoRAM - Target memory.
   * @param {number} value - The score to write.
   * @param {Object} where - {row, col, line} from data/score.json.
   */
  setNumber(videoRAM, value, where) {
    if (!this.score || !where || value === undefined || value === null) { return; }
    var text = String(Math.floor(Math.max(0, value)/this.score.unit));
    if (text === '0') { text = ''; }
    var row = where.row;
    if (row < PANEL_ROW_FIRST || row >= PANEL_ROW_FIRST+(this.panel ? this.panel.rows : 0)) { return; }
    for (var i = 0; i < this.score.digits; i++) {
      var col = where.col - i;
      if (col < 0) { break; }
      var digit = i < text.length
        ? Number(text.charAt(text.length-1-i))+1 : 0;   // 0 is the blank glyph
      for (var line = 0; line < this.score.rows; line++) {
        videoRAM.pokeOffset(ZXVideoRAM.lineOffset(row*8 + where.line + line)+col,
                            this.score.glyphs[digit*this.score.rows + line]);
      }
    }
  } // setNumber

} // ScreenComposer
