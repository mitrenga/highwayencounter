const { ZXVideoRAMEntity } = await import('./svision/js/platform/canvas2D/zx/zxVideoRAMEntity.js?ver='+window.srcVersion);
const { ScreenLayout } = await import('./screenLayout.js?ver='+window.srcVersion);
// begin code

/**
 * The panel: character rows 19-23 at the **bottom** of the screen — ZONE and
 * its number, the row of Vortons 1-5, POWER, SCORE, TIME and HIGH — the layout
 * measured on the running original (sources/docs/screen_layout.md).
 *
 * It is not set in a font: the original keeps the panel as a finished picture
 * at $6000 and copies it to the screen, so the picture is what M1 draws
 * (data/panel.json, tools/dumppanel.py). The live fields on it come with the
 * rules that feed them — the ZONE counter and the Vorton row in M5, POWER and
 * SCORE in M6 — and until then the panel shows what the original shows at the
 * start of a game.
 */
export class GameInfoEntity extends ZXVideoRAMEntity {

  /**
   * @param {AbstractEntity} parentEntity - The parent entity.
   * @param {number} x - X position relative to the parent.
   * @param {number} y - Y position relative to the parent.
   * @param {ScreenComposer} render - The shared renderer.
   */
  constructor(parentEntity, x, y, render) {
    super(parentEntity, x, y, {row: ScreenLayout.PANEL_ROW, rows: ScreenLayout.PANEL_ROWS});
    this.id = 'GameInfoEntity';

    this.render = render;
    this.panel = {zone: ScreenLayout.FIRST_ZONE, score: 0, high: 0,
                  power: 0, time: 0, vortons: ScreenLayout.VORTONS,
                  // which of the five icons the panel has filled in; the first
                  // one is, because that is the Vorton a game starts on
                  vortonMarks: [true, false, false, false, false],
                  // M7: whether the end sequence has taken the ZONE field over,
                  // and whether it has emptied it
                  endingMessage: false, endingPanel: false};
  } // constructor

  /**
   * Updates the panel values, repainting only when something changed.
   * @param {Object} panel - {zone, score, high, power, time, vortons,
   *        vortonMarks}.
   */
  setPanel(panel) {
    var changed = false;
    Object.keys(this.panel).forEach((key) => {
      if (!(key in panel)) {
        return;
      }
      // vortonMarks is an array, so it is compared by value — comparing it by
      // reference would repaint the panel on every single frame
      var same = Array.isArray(panel[key])
        ? (Array.isArray(this.panel[key])
           && String(panel[key]) === String(this.panel[key]))
        : panel[key] === this.panel[key];
      if (!same) {
        this.panel[key] = Array.isArray(panel[key]) ? panel[key].slice()
                                                    : panel[key];
        changed = true;
      }
    });
    if (changed) {
      this.invalidate();
    }
  } // setPanel

  /**
   * Composes the panel into the video memory; ZXVideoRAMEntity calls it only
   * when the cache is dirty.
   */
  compose() {
    this.render.composePanelInto(this.videoRAM, this.panel);
  } // compose

} // GameInfoEntity
