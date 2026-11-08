const { ZXVideoRAMEntity } = await import('./svision/js/platform/canvas2D/zx/zxVideoRAMEntity.js?ver='+window.srcVersion);
const { ScreenLayout } = await import('./screenLayout.js?ver='+window.srcVersion);
// begin code

/**
 * A whole 256x192 Spectrum screen stored as one block — the loading screen
 * from the original tape (data/loading.json, tools/mkscreen.py). The data file
 * holds the bitmap and the attributes as linear blocks, so they are put into
 * the video memory with `setLinear`.
 *
 * `revealed` paints only the first n character rows, so TapeLoadingModel can
 * let the picture appear the way it does while a tape loads.
 */
export class ScreenEntity extends ZXVideoRAMEntity {

  /**
   * @param {AbstractEntity} parentEntity - The parent entity.
   * @param {number} x - X position relative to the parent.
   * @param {number} y - Y position relative to the parent.
   * @param {Object} screen - The parsed screen data file.
   */
  constructor(parentEntity, x, y, screen) {
    super(parentEntity, x, y);
    this.id = 'ScreenEntity';

    this.revealed = ScreenLayout.ROWS;
    this.setScreen(screen);
  } // constructor

  /**
   * Shows the first `rows` character rows of the picture.
   * @param {number} rows - Number of character rows to paint (0-24).
   */
  setRevealed(rows) {
    rows = Math.max(0, Math.min(ScreenLayout.ROWS, Math.round(rows)));
    if (rows !== this.revealed) {
      this.revealed = rows;
      this.invalidate();
    }
  } // setRevealed

  /**
   * Puts another picture up — the title screen after the tape has finished.
   * @param {Object} screen - The parsed screen data file.
   */
  setScreen(screen) {
    this.videoRAM.setLinear({}, screen.bitmap, screen.attributes);
    this.revealed = ScreenLayout.ROWS;
    this.invalidate();
  } // setScreen

  /**
   * Paints the memory and blacks out the rows not revealed yet.
   * @param {Uint8ClampedArray} data - The RGBA bytes of the frame.
   */
  paintRaster(data) {
    super.paintRaster(data);
    if (this.revealed < ScreenLayout.ROWS) {
      var from = this.revealed*ScreenLayout.CELL*this.width*4;
      data.fill(0, from);
      for (var i = from+3; i < data.length; i += 4) {
        data[i] = 255;
      }
    }
  } // paintRaster

} // ScreenEntity
