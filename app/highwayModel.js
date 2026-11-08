const { AbstractModel } = await import('./svision/js/abstractModel.js?ver='+window.srcVersion);
const { BorderEntity } = await import('./borderEntity.js?ver='+window.srcVersion);
const { TextEntity } = await import('./svision/js/platform/canvas2D/textEntity.js?ver='+window.srcVersion);
const { PauseGameEntity } = await import('./pauseGameEntity.js?ver='+window.srcVersion);
const { ZXColor } = await import('./svision/js/platform/canvas2D/zx/zxColor.js?ver='+window.srcVersion);
const { ScreenLayout } = await import('./screenLayout.js?ver='+window.srcVersion);
const { ScreenComposer } = await import('./screenComposer.js?ver='+window.srcVersion);
const { GameAreaEntity } = await import('./gameAreaEntity.js?ver='+window.srcVersion);
const { GameInfoEntity } = await import('./gameInfoEntity.js?ver='+window.srcVersion);
const { SpriteTool } = await import('./svision/js/spriteTool.js?ver='+window.srcVersion);
// begin code

// How far a thumb has to travel before a touch joystick's axis fires, in
// pixels of the Spectrum screen — the value the sibling projects use.
const TOUCH_DEAD_ZONE = 10;

/**
 * The game screen: the highway on character rows 0-18 and the panel below it on
 * rows 19-23 — the layout of the original, which puts its panel at the bottom
 * (sources/docs/screen_layout.md).
 *
 * The panel is the original's own picture (data/panel.json). The play area is
 * still empty, and on purpose: the projection, the depth ordering and the
 * sprites are M2, and the discipline of the project is to leave what has not
 * been measured open rather than to draw an approximation of it (ZADANI
 * chap. 6 and 7).
 *
 * What the model does already carry is the road itself. The worker
 * (gameWorker.js, WORKER-PROTOCOL.md) ticks at the original's 50.08 Hz, runs
 * the measured physics (M3) and the measured rules of the road (M4) and sends
 * back the whole entity table plus the zone the camera is on; this model routes
 * the controls to it and hands what comes back to the renderer, which will have
 * something to draw with as soon as M2 has the sprites. What it does already
 * draw there is the **end of the game** (M7): when the Lasertron reaches the
 * end of the road the worker takes the sequence over, and the message it
 * writes is set with the game's own character set, which M7 found.
 */
export class HighwayModel extends AbstractModel {

  constructor(app) {
    super(app);
    this.id = 'HighwayModel';

    this.gameOver = false;
    this.controlsState = {left: false, right: false, accelerate: false,
                          decelerate: false, fire: false};
    this.worker = null;
    this.render = null;
    this.gameAreaEntity = null;
    this.gameInfoEntity = null;
    this.fpsEntity = null;
    this.fps = {frames: 0, workerFrames: 0, ticks: 0, since: false, lastFrame: false};
  } // constructor

  newBorderEntity() {
    return new BorderEntity(true, this.app.controls.touchscreen.supported);
  } // newBorderEntity

  init() {
    super.init();

    // M8 measured the border: the only writes to port $FE the game makes are
    // the two sound generators, and both send bits 0-2 as zero — so the border
    // is black, for the whole game, all 185 322 writes of it
    // (data/sounds.json `border`, tools/dumpsound.py).
    this.borderEntity.bkColor = ZXColor.black;
    this.desktopEntity.bkColor = ZXColor.black;

    // the data files: at once from localStorage, or from the server when
    // they are missing there (R-062)
    this.loadDataFiles(['projection', 'panel', 'panelfields', 'font', 'ending', 'score', 'scenery', 'spriteframes', 'sounds', 'physics', 'objects', 'convoy', 'enemies', 'cadence', 'highway', 'zones'], (files, error) => this.initData(files, error));
  } // init

  /**
   * The part of init() that needs the data files: the screen and the start
   * of the worker. Runs inside init() when they are in localStorage, later
   * when they had to come from the server.
   * @param {Object|null} files - The data files, or null.
   * @param {Error} [error] - Why they are missing.
   */
  initData(files, error) {
    if (this.app.model !== this) {
      return;
    }
    if (!files) {
      this.app.showErrorMessage(error ? error.message : 'Game data could not be loaded.', 'restart');
    }
    if (!this.initScreen()) {
      this.desktopEntity.addEntity(new TextEntity(this.desktopEntity, this.app.fonts.zxFonts8x8, 0, 8*8, this.desktopWidth, 8, 'HIGHWAY ENCOUNTER', ZXColor.brightWhite, false, {align: 'center'}));
      this.desktopEntity.addEntity(new TextEntity(this.desktopEntity, this.app.fonts.fonts5x5, 8, 8*8+16, this.desktopWidth-16, 40,
        'PANEL DATA MISSING (data/panel.json). RUN tools/dumppanel.py.', ZXColor.brightGreen, false, {align: 'center', textWrap: true}));
      return;
    }

    if (this.app.devModeName !== false) {
      this.fpsEntity = new TextEntity(this.desktopEntity, this.app.fonts.fonts3x3, 16*8, 2, 10*8, 4, '', ZXColor.brightGreen, false, {align: 'right'});
      this.desktopEntity.addEntity(this.fpsEntity);
    }

    // The menu keeps the audio closed; the game opens its bus here. There is
    // only the one, and M8 measured why that is right: the original has no
    // music at all, only five effects and a menu beep (data/sounds.json).
    this.soundData = this.loadDataFile('sounds');
    if (this.app.audioManager) {
      this.app.audioManager.setGameSounds(this.soundData);
    }
    this.sendEvent(0, {id: 'openAudioBus', bus: 'sounds', options: {muted: this.app.muted.sounds}});

    this.worker = this.app.worker;
    this.app.inputEventsManager.sendEventsActiveKeys('Press');
    this.sendWorkerMessage({
      id: 'init',
      initData: {
        headless: false,
        zone: this.app.zone,
        vortons: this.app.vortons,
        // M3: the Vorton's physics, measured on the original by
        // tools/dumpphysics.py
        physics: this.loadDataFile('physics'),
        // M4: the rules of the road — the collision box, the shoving, the
        // shots and the length of a zone (tools/dumpobjects.py)
        objects: this.loadDataFile('objects'),
        // M5: the convoy — four automatic Vortons and the Lasertron, where
        // they start and how they drive (tools/dumpconvoy.py)
        convoy: this.loadDataFile('convoy'),
        // M6: the enemies, the collision matrix, the dying animation and the
        // game's clock (tools/dumpenemies.py)
        enemies: this.loadDataFile('enemies'),
        // M7: the end of the game in Zone Zero and the harder pass that
        // follows it (tools/dumpending.py)
        ending: this.loadDataFile('ending'),
        // M8: the sound routines of the original — which effect the pass asks
        // for and how many draws of the game's generator it takes
        // (tools/dumpsound.py)
        sounds: this.soundData,
        // M8: what scores what — 250 for a destroyed object, 1000 for
        // finishing (tools/dumpscore.py)
        score: this.loadDataFile('score'),
        // M2: the projection, the depth sort and which frame a record draws;
        // the worker needs it for the animation bytes and the shots' kinds
        // (tools/dumpproj.py)
        projection: this.projectionData,
        // M9: how long a pass of the original's main loop takes — the
        // governor in its own code, the work it does and the sound it plays
        // (tools/dumpcadence.py). Without it the worker steps on the mean.
        cadence: this.loadDataFile('cadence'),
        // M2: what stands on the road — the original's own table of 240
        // records (tools/dumphighway.py) and the rule by which a zone is
        // filled from it (tools/dumpzones.py)
        highway: this.loadDataFile('highway'),
        zones: this.loadDataFile('zones')
      }
    });

    // M9: the test flight. The /testFlight page hands the app a script instead
    // of an icon — the keys a real player's recording had the original read,
    // frame by frame (testFlightPage.php, tools/dumpflight.py) — and this is
    // where it is unpacked and sent on to the worker. On the ordinary page
    // there is nothing to unpack and nothing happens.
    SpriteTool.scriptedSprite(this, this.app.appIconSprite);

    this.app.stack.flashState = false;
    this.sendEvent(330, {id: 'changeFlashState'});
  } // initData

  shutdown() {
    super.shutdown();
    this.sendWorkerMessage({id: 'reset'});
    this.sendEvent(0, {id: 'stopAllAudioBuses'});
  } // shutdown


  /**
   * Builds the renderer and adds the highway and the panel.
   * @returns {boolean} True when the screen was created.
   */
  initScreen() {
    this.projectionData = this.loadDataFile('projection');
    var panel = this.loadDataFile('panel');
    if (!panel) {
      return false;
    }
    // ...and the panel's live fields, photographed off the original for every
    // value it shows (data/panelfields.json, tools/dumppanelfields.py)
    // ...and, as of M7, the game's own character set (data/font.json,
    // tools/dumpfont.py) with the end sequence's own pictures and strings, so
    // that what the original writes in words can be written here too
    // ...and, as of M8, the digits of SCORE and HIGH with the five-byte font
    // the original keeps for them alone (data/score.json, tools/dumpscore.py)
    // ...and, as of M2, the road itself: the picture of every zone
    // (data/scenery.json), the 56 sprites (data/spriteframes.json) and the
    // projection that places them (data/projection.json)
    this.render = new ScreenComposer(panel, this.loadDataFile('panelfields'),
                                   this.loadDataFile('font'),
                                   this.loadDataFile('ending'),
                                   this.loadDataFile('score'),
                                   this.loadDataFile('scenery'),
                                   this.loadDataFile('spriteframes'),
                                   this.projectionData);
    this.gameAreaEntity = new GameAreaEntity(this.desktopEntity, 0, ScreenLayout.PLAY_Y, this.render);
    this.desktopEntity.addEntity(this.gameAreaEntity);
    this.gameInfoEntity = new GameInfoEntity(this.desktopEntity, 0, ScreenLayout.PANEL_Y, this.render);
    this.desktopEntity.addEntity(this.gameInfoEntity);
    this.gameInfoEntity.setPanel({zone: this.app.zone, score: this.app.score,
                                  high: this.app.hiScore || 0,
                                  vortons: this.app.vortons,
                                  vortonMarks: [true, false, false, false, false]});
    return true;
  } // initScreen

  sendWorkerMessage(event) {
    if (this.worker) {
      this.worker.postMessage(event);
    }
  } // sendWorkerMessage

  /**
   * Sets one control and sends the whole state to the worker when it changed.
   * @param {string} action - The control action.
   * @param {boolean} value - Pressed or released.
   */
  setControl(action, value) {
    if (!(action in this.controlsState) || this.controlsState[action] === value) {
      return;
    }
    this.controlsState[action] = value;
    this.sendWorkerMessage(Object.assign({id: 'controls'}, this.controlsState));
  } // setControl

  handleWorkerMessage(event) {
    var data = event.data;
    switch (data.id) {
      case 'frame':
        this.fps.workerFrames++;
        // ★ R-045: a tiky světa zvlášť, odečtené z čítače ve zprávě
        if (this.fps.lastFrame !== false) { this.fps.ticks += data.frame-this.fps.lastFrame; }
        this.fps.lastFrame = data.frame;
        this.app.score = data.score;
        this.app.zone = data.zone;
        this.app.vortons = data.vortons;
        if (this.gameAreaEntity) {
          this.gameAreaEntity.setFrame({vorton: data.vorton, convoy: data.convoy,
                                        objects: data.objects,
                                        // M2: which zone's picture goes down,
                                        // where the camera is and which frame
                                        // each kind is showing
                                        zone: data.zone, cam: data.cam,
                                        anim: data.anim,
                                        // M7: the end sequence, when it runs
                                        ending: data.ending});
        }
        if (this.gameInfoEntity) {
          this.gameInfoEntity.setPanel({zone: data.zone, score: data.score,
                                        high: data.high, power: data.power,
                                        time: data.time, vortons: data.vortons,
                                        vortonMarks: data.vortonMarks,
                                        // LASERTRON ACTIVATED takes the place
                                        // of ZONE while the sequence runs
                                        endingMessage: !!(data.ending
                                          && data.ending.panelMessage),
                                        endingPanel: !!(data.ending
                                          && data.ending.panelBlank)});
        }
        if (data.sounds && data.sounds.length && this.app.audioManager) {
          this.app.audioManager.playFrame(data);
        }
        break;
      case 'gameOver':
        if (!this.gameOver) {
          this.gameOver = true;
          this.app.score = data.score;
          this.app.setModel('GameOverModel');
        }
        break;
    }
  } // handleWorkerMessage

  /**
   * Maps a key, gamepad or mouse event onto a control action.
   *
   * The original is played on 1 (FAST), Q (SLOW), O (LEFT), P (RIGHT),
   * SPACE (FIRE), H (HOLD) and A (ABORT GAME) — read off its own INFORMATION
   * screen (sources/docs/instructions_transcript.md, ZADANI chap. 1). Those
   * are the defaults; the arrow keys are always accepted as well, and
   * everything can be remapped from SETTINGS. O and P **turn** the Vorton
   * rather than moving it, which is why they are 'left' and 'right' here and
   * the throttle is a pair of its own (ZADANI chap. 3.6).
   * @param {string} key - The event key.
   * @returns {string|false} The action, or false.
   */
  controlAction(key) {
    var kb = this.app.controls.keyboard, mouse = this.app.controls.mouse;
    var mouseOk = (k) => mouse.enable && this.app.inputEventsManager.keysMap[k] === false;
    switch (key) {
      case kb.left: case 'ArrowLeft': case 'GamepadLeft': return 'left';
      case kb.right: case 'ArrowRight': case 'GamepadRight': return 'right';
      case kb.accelerate: case 'ArrowUp': case 'GamepadUp': return 'accelerate';
      case kb.decelerate: case 'ArrowDown': case 'GamepadDown': return 'decelerate';
      case kb.fire: case 'GamepadFire': return 'fire';
      case mouse.left: return mouseOk(mouse.left) ? 'left' : false;
      case mouse.right: return mouseOk(mouse.right) ? 'right' : false;
      case mouse.accelerate: return mouseOk(mouse.accelerate) ? 'accelerate' : false;
    }
    return false;
  } // controlAction

  handleEvent(event) {
    if (super.handleEvent(event)) {
      return true;
    }

    switch (event.id) {

      case 'changeFlashState':
        this.app.stack.flashState = !this.app.stack.flashState;
        this.sendEvent(330, {id: 'changeFlashState'});
        return true;

      case 'exitGame':
        this.app.setModel('MenuModel');
        return true;

      case 'blurWindow':
        this.pauseGame();
        return true;

      case 'continueGame':
        this.sendWorkerMessage({id: 'continue'});
        this.sendEvent(0, {id: 'continueAllAudioBuses'});
        return true;

      case 'keyPress':
        var key = event.key;
        if (key.length == 1) {
          key = key.toUpperCase();
        }
        switch (key) {
          // the original pauses on H (HOLD) and leaves on A (ABORT GAME);
          // both open the remake's pause panel, and so does Escape
          case 'Escape':
          case 'GamepadExit':
          case this.app.controls.keyboard.hold:
          case this.app.controls.keyboard.abort:
            this.pauseGame();
            return true;
          case 'Touch':
            if (this.borderEntity.leftControlEntity && this.borderEntity.leftControlEntity.pointOnEntity(event)) {
              this.app.inputEventsManager.touchesMap[event.identifier] = this.borderEntity.leftControlEntity;
              this.touchStart(event, 'left');
              return true;
            }
            if (this.borderEntity.rightControlEntity && this.borderEntity.rightControlEntity.pointOnEntity(event)) {
              this.app.inputEventsManager.touchesMap[event.identifier] = this.borderEntity.rightControlEntity;
              this.touchStart(event, 'right');
              return true;
            }
            break;
          case 'RetryTouch':
            this.setControl(event.action, true);
            return true;
          case this.app.controls.keyboard.sounds:
            this.app.muted.sounds = !this.app.muted.sounds;
            this.sendEvent(0, {id: 'muteAudioBus', bus: 'sounds', muted: this.app.muted.sounds});
            return true;
        }
        var action = this.controlAction(key);
        if (action !== false) {
          this.setControl(action, true);
          return true;
        }
        break;

      case 'keyRelease':
        var releasedKey = event.key;
        if (releasedKey.length == 1) {
          releasedKey = releasedKey.toUpperCase();
        }
        if (releasedKey == 'Touch') {
          this.touchEnd(event);
          return true;
        }
        var releasedAction = this.controlAction(releasedKey);
        if (releasedAction !== false) {
          this.setControl(releasedAction, false);
          return true;
        }
        break;

      case 'keyMove':
        if (event.key == 'Touch') {
          this.touchMove(event);
          return true;
        }
        break;

      case 'errorAudioBus':
        this.app.showErrorMessage(event.error, 'reopen');
        return true;
    }

    return false;
  } // handleEvent

  /** pauses the worker and opens the pause menu */
  pauseGame() {
    if (this.desktopEntity.modalEntity || this.gameOver) {
      return;
    }
    this.sendWorkerMessage({id: 'pause'});
    this.sendEvent(0, {id: 'pauseAllAudioBuses'});
    this.desktopEntity.addModalEntity(new PauseGameEntity(this.desktopEntity, 52, 40, 153, 85, 'PAUSE GAME', 'MenuModel'));
  } // pauseGame

  /**
   * Touch controls: the border's two halves, one the gun and one the Vorton.
   *
   * The driving half is a joystick on **both** axes, because that is what the
   * original's controls are — O and P turn, 1 and Q are the throttle, and they
   * are pressed at the same time (ZADANI chap. 3.6). Each axis is its own
   * control with its own dead zone, so a thumb can hold a turn and open the
   * throttle without letting either go, and each axis re-centres on the last
   * position it fired at, which is what makes a thumb-sized joystick usable on
   * a phone: it is a relative control, not an absolute one.
   * @param {Object} event - The touch event.
   * @param {string} side - 'left' or 'right'.
   */
  touchStart(event, side) {
    var ts = this.app.controlsOptions.touchscreen.types[this.app.controls.touchscreen.type][side];
    if (ts.type == 'button') {
      this.setControl(ts.action, true);
    }
    this.app.inputEventsManager.touchesGameControls[event.identifier] = {
      center: {x: event.x, y: event.y}, type: ts.type, control: ts.control,
      action: ts.action, actions: ts.actions,
      // what each axis of a two-axis joystick is holding down right now
      axes: {horizontal: false, vertical: false}
    };
  } // touchStart

  touchEnd(event) {
    var controls = this.app.inputEventsManager.touchesGameControls;
    var control = controls[event.identifier];
    if (!control) {
      return;
    }
    if (control.action !== false) {
      this.setControl(control.action, false);
    }
    for (var axis in control.axes) {
      if (control.axes[axis] !== false) {
        this.setControl(control.axes[axis], false);
      }
    }
    delete controls[event.identifier];
  } // touchEnd

  touchMove(event) {
    var control = this.app.inputEventsManager.touchesGameControls[event.identifier];
    if (!control || control.type != 'joystick') {
      return;
    }
    if (control.control == 'both') {
      this.touchAxis(control, 'horizontal', event.x);
      this.touchAxis(control, 'vertical', event.y);
      return;
    }
    // one-axis joystick: the action it holds is the touch's own
    var pair = control.actions;
    var axis = control.control == 'vertical' ? 'vertical' : 'horizontal';
    var position = axis == 'vertical' ? event.y : event.x;
    var wanted = this.touchAxisAction(control, axis, pair, position);
    if (wanted !== null && control.action !== wanted) {
      if (control.action !== false) {
        this.setControl(control.action, false);
      }
      control.action = wanted;
      this.setControl(control.action, true);
    }
  } // touchMove

  /** One axis of the two-axis joystick: press what it moved towards. */
  touchAxis(control, axis, position) {
    var pair = control.actions[axis];
    if (!pair) {
      return;
    }
    var wanted = this.touchAxisAction(control, axis, pair, position);
    if (wanted === null || control.axes[axis] === wanted) {
      return;
    }
    if (control.axes[axis] !== false) {
      this.setControl(control.axes[axis], false);
    }
    control.axes[axis] = wanted;
    this.setControl(wanted, true);
  } // touchAxis

  /**
   * Which of an axis's two actions a movement asks for, or null while the
   * thumb has not left the dead zone.
   */
  touchAxisAction(control, axis, pair, position) {
    var key = axis == 'vertical' ? 'y' : 'x';
    var moved = position-control.center[key];
    if (moved < -TOUCH_DEAD_ZONE) {
      control.center[key] = position;
      return pair[0];
    }
    if (moved > TOUCH_DEAD_ZONE) {
      control.center[key] = position;
      return pair[1];
    }
    return null;
  } // touchAxisAction

  updateFps(timestamp) {
    if (!this.fpsEntity) {
      return;
    }
    this.fps.frames++;
    if (this.fps.since === false) {
      this.fps.since = timestamp;
      return;
    }
    var elapsed = timestamp-this.fps.since;
    if (elapsed >= 1000) {
      this.fpsEntity.setText(Math.round(this.fps.frames*1000/elapsed)+'/'+Math.round(this.fps.workerFrames*1000/elapsed)+'/'+Math.round(this.fps.ticks*1000/elapsed)+' FPS');
      this.fps.frames = 0;
      this.fps.workerFrames = 0;
      this.fps.ticks = 0;
      this.fps.since = timestamp;
    }
  } // updateFps

  loopModel(timestamp) {
    super.loopModel(timestamp);

    if (this.desktopEntity.modalEntity) {
      this.desktopEntity.modalEntity.loopEntity(timestamp);
    }

    this.updateFps(timestamp);
    this.drawModel();
  } // loopModel

} // HighwayModel
