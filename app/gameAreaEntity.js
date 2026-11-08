const { ZXVideoRAMEntity } = await import('./svision/js/platform/canvas2D/zx/zxVideoRAMEntity.js?ver='+window.srcVersion);
const { ScreenLayout } = await import('./screenLayout.js?ver='+window.srcVersion);
// begin code

/**
 * The highway: 256x152 pixels above the panel, character rows 0-18
 * (sources/docs/screen_layout.md). ScreenComposer composes the frame into the
 * entity's video memory — the same DOM-free module an offline tool uses — and
 * the library turns the bytes into pixels once per game frame (R-003).
 *
 * Feed it with setFrame() from the worker 'frame' message (WORKER-PROTOCOL.md).
 */
export class GameAreaEntity extends ZXVideoRAMEntity {

  /**
   * @param {AbstractEntity} parentEntity - The parent entity.
   * @param {number} x - X position relative to the parent.
   * @param {number} y - Y position relative to the parent.
   * @param {ScreenComposer} render - The shared renderer.
   */
  constructor(parentEntity, x, y, render) {
    super(parentEntity, x, y, {row: 0, rows: ScreenLayout.PLAY_ROWS});
    this.id = 'GameAreaEntity';

    this.render = render;
    this.frameState = {};
  } // constructor

  /**
   * Stores the state of the newest frame and invalidates the cache.
   * @param {Object} state - The frame state as sent by the worker.
   */
  setFrame(state) {
    this.frameState = state;
    this.invalidate();
  } // setFrame

  /**
   * Composes the highway with the frame's objects into the video memory;
   * ZXVideoRAMEntity calls it only when the cache is dirty.
   */
  compose() {
    this.render.composeInto(this.videoRAM, this.frameState);
  } // compose

} // GameAreaEntity
