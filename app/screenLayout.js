// begin code

/**
 * Geometry of the Highway Encounter screen, measured on the running original —
 * sources/docs/screen_layout.md (read out of the video RAM of a captured frame,
 * not off a photograph).
 *
 * The screen is the plain ZX Spectrum one: 256x192 pixels, attributes in 8x8
 * cells. Unlike the sibling remakes the panel is at the **bottom**: character
 * rows 19-23, and the highway is the 19 rows above it.
 */
export const ScreenLayout = {

  WIDTH: 256,
  HEIGHT: 192,

  CELL: 8,
  COLS: 32,
  ROWS: 24,

  // panel: character rows 19-23, pixels y = 152..191. The picture the game
  // actually draws ends at y = 185; the last six pixel rows stay black.
  PANEL_ROW: 19,
  PANEL_Y: 152,
  PANEL_ROWS: 5,
  PANEL_HEIGHT: 40,
  PANEL_DRAWN_HEIGHT: 34,

  // highway: character rows 0-18, pixels y = 0..151
  PLAY_Y: 0,
  PLAY_ROWS: 19,
  PLAY_WIDTH: 256,
  PLAY_HEIGHT: 152,

  // The road is numbered downwards, ZONE 30 to Zone Zero (instructions;
  // Sinclair User 41 says 32 screens and contradicts everything else — the
  // authority will be the zone table in the game data, M2, ZADANI chap. 3.4).
  FIRST_ZONE: 30,
  LAST_ZONE: 0,

  // Five Vortons: the one under your control and the four pushing the
  // Lasertron. The panel shows them as the row 1 2 3 4 5 (ZADANI chap. 3.2;
  // how the original counts them is still open, chap. 7).
  VORTONS: 5,

  // 50.08 Hz — 69888 T states per frame on a 3.5 MHz Z80 (hw_notes.md).
  // The game logic hangs off the ULA interrupt, so this is the simulation step.
  FRAME_RATE: 3500000/69888

}; // ScreenLayout
