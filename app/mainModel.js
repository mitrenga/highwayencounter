const { AbstractModel } = await import('./svision/js/abstractModel.js?ver='+window.srcVersion);
const { AbstractEntity } = await import('./svision/js/abstractEntity.js?ver='+window.srcVersion);
const { BorderEntity } = await import('./borderEntity.js?ver='+window.srcVersion);
const { ScreenEntity } = await import('./screenEntity.js?ver='+window.srcVersion);
const { SlidingTextEntity } = await import('./svision/js/platform/canvas2D/slidingTextEntity.js?ver='+window.srcVersion);
const { TextEntity } = await import('./svision/js/platform/canvas2D/textEntity.js?ver='+window.srcVersion);
const { PauseGameEntity } = await import('./pauseGameEntity.js?ver='+window.srcVersion);
const { ZXColor } = await import('./svision/js/platform/canvas2D/zx/zxColor.js?ver='+window.srcVersion);
// begin code

/**
 * Title screen. The picture is the original's own loading screen off the tape
 * (data/loading.json); ENTER starts.
 *
 * The original has more than this after the tape stops: a title screen with the
 * OPTIONS menu, an INFORMATION page and a DEMONSTRATION — the attract mode
 * Crash 20 praised the introduction of. All three are the original's own
 * screens and belong in the remake, so they are M7 work, taken out of the
 * running game rather than invented here.
 */
export class MainModel extends AbstractModel {

  constructor(app) {
    super(app);
    this.id = 'MainModel';

    this.slidingText =
      '+++++ PRESS ENTER TO START +++++' +
      '  ' +
      'HIGHWAY ENCOUNTER by Costa Panayi, Vortex Software, 1985' +
      ' . . . . . . ' +
      'Five Vortons must push the Lasertron down the last road on Earth, from Zone 30 to Zone Zero - and the four you are not driving push it on their own' +
      ' . . . . . . ';
    this.screenEntity = null;
    this.slidingTextEntity = null;
  } // constructor

  newBorderEntity() {
    return new BorderEntity(true, false);
  } // newBorderEntity

  init() {
    super.init();

    this.borderEntity.bkColor = ZXColor.black;
    this.desktopEntity.bkColor = ZXColor.black;

    // the data files: at once from localStorage, or from the server when
    // they are missing there (R-062)
    this.loadDataFiles(['loading'], (files, error) => this.initData(files, error));
  } // init

  /**
   * The part of init() that needs the data files: the loading screen under
   * the menu. Runs inside init() when it is in localStorage, later when it
   * had to come from the server.
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
    var loading = this.loadDataFile('loading');
    if (loading) {
      this.screenEntity = new ScreenEntity(this.desktopEntity, 0, 0, loading);
      this.desktopEntity.addEntity(this.screenEntity);
    } else {
      this.desktopEntity.addEntity(new TextEntity(this.desktopEntity, this.app.fonts.zxFonts8x8, 0, 8*8, this.desktopWidth, 8, 'HIGHWAY ENCOUNTER', ZXColor.brightWhite, false, {align: 'center'}));
    }

    var bar = new AbstractEntity(this.desktopEntity, 0, 23*8, 32*8, 8, false, ZXColor.black);
    this.desktopEntity.addEntity(bar);
    this.slidingTextEntity = new SlidingTextEntity(bar, this.app.fonts.zxFonts8x8Mono, 0, 0, 32*8, 8, this.slidingText, ZXColor.brightYellow, ZXColor.black, {animation: 'loopLeft', speed: 20, leftMargin: 256, rightMargin: 256});
    bar.addEntity(this.slidingTextEntity);

    this.sendEvent(0, {id: 'openAudioBus', bus: 'sounds', options: {muted: this.app.muted.sounds}});

    this.app.stack.flashState = false;
    this.sendEvent(330, {id: 'changeFlashState'});
  } // initData

  shutdown() {
    super.shutdown();
    this.sendEvent(0, {id: 'stopAllAudioBuses'});
  } // shutdown


  handleEvent(event) {
    if (super.handleEvent(event)) {
      return true;
    }

    switch (event.id) {
      case 'changeFlashState':
        this.app.stack.flashState = !this.app.stack.flashState;
        this.sendEvent(330, {id: 'changeFlashState'});
        return true;

      case 'startHighway':
        this.app.startHighway();
        return true;

      case 'keyPress':
        if (this.desktopEntity.modalEntity != null) {
          break;
        }
        switch (event.key) {
          case 'Enter':
          case ' ':
          case 'GamepadOK':
            this.app.startHighway();
            return true;
          case 'Escape':
          case 'GamepadExit':
            this.desktopEntity.addModalEntity(new PauseGameEntity(this.desktopEntity, 52, 40, 153, 85, 'OPTIONS', 'MenuModel'));
            return true;
          case 'Mouse1':
            this.app.inputEventsManager.keysMap.Mouse1 = this.borderEntity;
            return true;
          case 'Touch':
            this.app.inputEventsManager.touchesMap[event.identifier] = this.borderEntity;
            return true;
        }
        break;

      case 'keyRelease':
        switch (event.key) {
          case 'Mouse1':
            if (this.app.inputEventsManager.keysMap.Mouse1 === this.borderEntity) {
              this.app.startHighway();
              return true;
            }
            break;
          case 'Touch':
            if (this.app.inputEventsManager.touchesMap[event.identifier] === this.borderEntity) {
              this.app.startHighway();
              return true;
            }
            break;
        }
        break;

      case 'continueGame':
        return true;

      case 'errorAudioBus':
        this.app.showErrorMessage(event.error, 'reopen');
        return true;
    }

    return false;
  } // handleEvent

  loopModel(timestamp) {
    super.loopModel(timestamp);

    if (this.desktopEntity.modalEntity) {
      this.desktopEntity.modalEntity.loopEntity(timestamp);
    }
    this.slidingTextEntity.loopEntity(timestamp);

    this.drawModel();
  } // loopModel

} // MainModel
