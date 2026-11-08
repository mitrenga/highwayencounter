const { Version } = await import('./version.js?ver='+window.srcVersion);
const { AbstractApp } = await import('./svision/js/abstractApp.js?ver='+window.srcVersion);
const { AudioManager } = await import('./audioManager.js?ver='+window.srcVersion);
const { ZXFonts8x8 } = await import('./svision/js/platform/canvas2D/zx/zxFonts8x8.js?ver='+window.srcVersion);
const { Fonts5x5 } = await import('./svision/js/platform/canvas2D/fonts5x5.js?ver='+window.srcVersion);
const { Fonts3x3 } = await import('./svision/js/platform/canvas2D/fonts3x3.js?ver='+window.srcVersion);
const { ZXResetModel } = await import('./svision/js/platform/canvas2D/zx/zxResetModel.js?ver='+window.srcVersion);
const { MenuModel } = await import('./menuModel.js?ver='+window.srcVersion);
const { MainModel } = await import('./mainModel.js?ver='+window.srcVersion);
const { HighwayModel } = await import('./highwayModel.js?ver='+window.srcVersion);
const { GameOverModel } = await import('./gameOverModel.js?ver='+window.srcVersion);
const { TapeLoadingModel } = await import('./tapeLoadingModel.js?ver='+window.srcVersion);
const { ZXErrorEntity } = await import('./svision/js/platform/canvas2D/zx/zxErrorEntity.js?ver='+window.srcVersion);
const { ScreenLayout } = await import('./screenLayout.js?ver='+window.srcVersion);
const { Tool } = await import('./svision/js/tool.js?ver='+window.srcVersion);
const { ZXColor } = await import('./svision/js/platform/canvas2D/zx/zxColor.js?ver='+window.srcVersion);
// begin code

/**
 * Highway Encounter application shell (M1), built on the Underwurlde one — the
 * closest sibling: a ZX game on ZXPlatform with the game logic in a
 * worker. LoadingModel -> MenuModel -> MainModel (title) -> HighwayModel (the
 * game) -> GameOverModel, plus TapeLoadingModel off the menu.
 *
 * The game state kept here is the state of the road: ZONE 30 down to Zone Zero
 * and five Vortons (the instructions and Crash 20; Your Spectrum 19 counts four
 * plus the one you drive, and Sinclair User 41 says 32 zones instead of 30 —
 * the authority will be the game's own data in M2, ZADANI chap. 7).
 */
export class GameApp extends AbstractApp {

  constructor(platform, importPath, wsURL, devModeName, appIconSprite) {
    super(platform, 'bodyApp', importPath, wsURL);

    this.worker = new Worker(this.importPath+'/gameWorker.js?ver='+window.srcVersion);
    this.worker.onmessage = (event) => {
      if (this.model) {
        this.model.handleWorkerMessage(event);
      }
    };

    this.version = Version;
    this.copyright = '©␣2026␣Libor␣Mitrenga, CC␣BY⋅NC⋅SA';
    this.devModeName = devModeName;
    this.appIconSprite = appIconSprite;

    this.audioManager = new AudioManager(this);
    this.muted = {sounds: false};

    this.fonts = {
      zxFonts8x8Mono: new ZXFonts8x8(this, false),
      zxFonts8x8: new ZXFonts8x8(this, true),
      zxFonts8x8Keys: new ZXFonts8x8(this, false),
      fonts5x5: new Fonts5x5(this),
      fonts3x3: new Fonts3x3(this)
    };
    // ZX key-cap glyphs for the key-remap screen (ZXRemapKeysEntity)
    this.fonts.zxFonts8x8Keys.setFontsData('00000000000000000010101010001000002424000000000014147E28FC505000107C507C14547C1042A44810244A8400001028102A443A00000810000000000000182020202018000030080808083000000014083E081400000008083E0808000000000000080810000000003E00000000000000001818000204081020408000007C4C5454647C000018280808083E00007C440438407C00007C441804447C00001828487E081C00007C407C04447C00007C407C44447C00007C440810101000007C443844447C00007C44447C047C000000001000001000000010000010102000000408100804000000003E003E00000000100804081000007C441C100010003C42BD85BDA5BE78003C42427E42E70000FC427C4242FC00007E424040427E0000FE42424242FE0000FE42784042FE0000FE42784040E000007E42404E427E0000E7427E4242E700007C101010107C00007E08080848780000E648705844E60000E040404242FE0000C3665A4242E70000C762524A46E700007E424242427E0000FE42427E40E000007E424242527E0800FE42427E44E700007E407E02427E0000FE92101010380000CE444444447E0000E742424224180000D7929292926C0000EE44382844EE0000EE442810103800007E440810227E001C10101010101C0000004020100804003808080808083800001038541010100000000000000000FF003C247020207C0000007C047C447E00C0407C4444447C0000007C4440407C000C047C4444447E0000007C447C407C003C2470202020700000007C44447C047CC0407C444444E6001000701010107C000800380808084878C0404C506058CC007010101010107C000000FC545454D6000000FC444444E60000007C4444447C0000007E22223E207000007C44447C040600007C242020700000007C407C04FC0000207820202038000000CC4444447E000000CE44442838000000D65454547E000000C6281028C6000000CC44447C047C00007E4418227E00000E083008080E0000080808080808000070100C1010700000142800000000003C4299A1A199423C');
    // Extra glyphs + hard/short spaces live in the game (svision core fonts are ASCII + normal space).
    this.fonts.fonts5x5.addGlyphs({
      'Ⓥ': {width: 3, data: [[0,2,1,1], [0,3,1,1], [1,4,1,1], [2,3,1,1], [2,2,1,1]]},
      '←': {width: 6, data: [[0,2,6,1], [1,1,1,3], [2,0,1,5]]},
      '↓': {width: 5, data: [[2,0,1,5], [1,3,3,1], [0,2,5,1]]},
      '↑': {width: 5, data: [[2,0,1,5], [1,1,3,1], [0,2,5,1]]},
      '→': {width: 6, data: [[0,2,6,1], [4,1,1,3], [3,0,1,5]]},
      // blinking cursor for the key-remap screen
      '█': {width: 4, data: [[0,0,4,5]]},
      // devModeName banner decoration
      '◢': {width: 4, data: [[4,0,1,1], [3,1,2,1], [2,2,3,1], [1,3,4,1], [0,4,5,1]]},
      '◤': {width: 4, data: [[0,0,5,1], [0,1,4,1], [0,2,3,1], [0,3,2,1], [0,4,1,1]]}
    });
    this.fonts.fonts5x5.addSpace('␣', {width: 2, breaking: false, stretch: true});

    this.fonts.zxFonts8x8.addGlyphs('‗⋅', '000000000000F8F80000000030000000');
    this.fonts.zxFonts8x8.addSpace('␣', {width: 3, breaking: false, stretch: false});

    // The original is played on 1 (FAST), Q (SLOW), O (LEFT), P (RIGHT),
    // SPACE (FIRE), H (HOLD) and A (ABORT GAME) — its own INFORMATION screen
    // (sources/docs/instructions_transcript.md, ZADANI chap. 1). O and P turn
    // the Vorton, 1 and Q are the throttle: eight headings and inertia, not an
    // eight-way joystick (ZADANI chap. 3.6). Those letters are the defaults
    // here; the arrow keys always work as well and everything can be remapped.
    this.controlsOptions = {
      keyboard: {
        device: 'keyboard',
        keys: [
          {action: 'left', label: 'TURN LEFT'},
          {action: 'right', label: 'TURN RIGHT'},
          {action: 'accelerate', label: 'ACCELERATE'},
          {action: 'decelerate', label: 'DECELERATE'},
          {action: 'fire', label: 'FIRE'},
          {action: 'hold', label: 'HOLD / PAUSE'},
          {action: 'abort', label: 'ABORT GAME'},
          {action: 'sounds', label: 'MUTE SOUNDS'}
        ]
      },
      mouse: {
        device: 'mouse',
        keys: [
          {action: 'left', label: 'TURN LEFT'},
          {action: 'right', label: 'TURN RIGHT'},
          {action: 'accelerate', label: 'ACCELERATE'}
        ]
      },
      // The gamepad drives the same five controls, and the two the menus need
      // on top of them. Up and down do double duty: they are the throttle on
      // the road and the menu's own up and down (menuEntity), so only OK and
      // EXIT have to be bound for the whole game to be playable without a
      // keyboard — which is what M9 asks for.
      gamepads: {
        device: 'gamepads',
        keys: [
          {action: 'left', label: 'TURN LEFT', eventKey: 'GamepadLeft'},
          {action: 'right', label: 'TURN RIGHT', eventKey: 'GamepadRight'},
          {action: 'accelerate', label: 'ACCELERATE', eventKey: 'GamepadUp'},
          {action: 'decelerate', label: 'DECELERATE', eventKey: 'GamepadDown'},
          {action: 'fire', label: 'FIRE', eventKey: 'GamepadFire'},
          {action: 'ok', label: 'MENU OK', eventKey: 'GamepadOK'},
          {action: 'exit', label: 'EXIT', eventKey: 'GamepadExit'}
        ]
      },
      // The two halves of the border are the touch controls: one carries the
      // gun, the other the Vorton. M1 put only the turn on it and left the
      // throttle for M9; M9 puts it there, on the other axis of the same
      // thumb, because that is what the original's controls are — O and P
      // turn, 1 and Q are the throttle (ZADANI chap. 3.6), and a driver needs
      // both at once. Which half is which is the one thing to choose.
      touchscreen: {
        device: 'touchscreen',
        types: {
          keys: [
            'leftFire',
            'rightFire'
          ],
          leftFire: {
            left: {
              type: 'button',
              control: false,
              action: 'fire',
              actions: false,
              sprite: 'fire'
            },
            right: {
              type: 'joystick',
              control: 'both',
              action: false,
              actions: {horizontal: ['left', 'right'],
                        vertical: ['accelerate', 'decelerate']},
              sprite: 'drive'
            }
          },
          rightFire: {
            left: {
              type: 'joystick',
              control: 'both',
              action: false,
              actions: {horizontal: ['left', 'right'],
                        vertical: ['accelerate', 'decelerate']},
              sprite: 'drive'
            },
            right: {
              type: 'button',
              control: false,
              action: 'fire',
              actions: false,
              sprite: 'fire'
            }
          }
        },
        icons: {
          fire: {
            compressedSpriteData: 'lP101300N0A970111030Z0510122382012345617171859'
          },
          // turn and throttle on one thumb: the left-right icon of the
          // sibling projects with the other axis added
          drive: {
            compressedSpriteData: 'hR200270017AF012503230524012601260120010501050119020501050217060201020617020501050219010501050120012601260124052303250161'
          }
        }
      }
    };

    this.controls = {
      keyboard: this.getControls('keyboard'),
      mouse: this.getControls('mouse'),
      touchscreen: this.getControls('touchscreen'),
      gamepads: this.getControls('gamepads')
    };

    this.zone = ScreenLayout.FIRST_ZONE;
    this.vortons = ScreenLayout.VORTONS;
    this.score = 0;
    this.hiScore = false;
    this.playerName = Tool.readCookie('playerName', '');
    this.globalData = false;
    this.id = 'GameApp';
    this.fetchDataId = '';
    this.setModel('LoadingModel');
    this.loadAppData();
  } // constructor

  getControls(device) {
    var result = {};

    switch (device) {
      case 'keyboard':
        result = {left: 'O', right: 'P', accelerate: '1', decelerate: 'Q',
                  fire: ' ', hold: 'H', abort: 'A', sounds: 'S'};
        break;
      case 'mouse':
        result = {enable: false, left: 'Mouse1', right: 'Mouse2', accelerate: 'Mouse4'};
        break;
      case 'touchscreen':
        result = {supported: false, type: 'leftFire'};
        break;
      case 'gamepads':
        result = {supported: false, devices: {}};
        break;
    }

    switch (device) {
      case 'keyboard':
      case 'mouse':
      case 'touchscreen':
        var cfgString = Tool.readCookie(device, false);
        if (cfgString !== false) {
          try {
            var cfg = JSON.parse(cfgString);
            Object.keys(cfg).forEach((item) => {
              result[item] = cfg[item];
              if (device == 'touchscreen' && !(result[item] in this.controlsOptions.touchscreen.types)) {
                result[item] = this.controlsOptions.touchscreen.types.keys[0];
              }
            });
          } catch (error) {
            console.error(error.message);
          }
        }
        break;
      case 'gamepads':
        var devicesString = Tool.readCookie('gamepads', false);
        if (devicesString !== false) {
          try {
            var devices = JSON.parse(devicesString);
          } catch (error) {
            console.error(error.message);
          } finally {
            if (Array.isArray(devices)) {
              devices.forEach((id) => {
                var deviceString = Tool.readCookie(id, false);
                if (deviceString !== false) {
                  try {
                    var device = JSON.parse(deviceString);
                  } catch (error) {
                    console.error(error.message);
                  } finally {
                    result.devices[id] = device;
                  }
                }
              });
            }
          }
        }
        break;
    }
    return result;
  } // getControls

  setModel(model) {
    if (model == 'MenuModel' && this.globalData === false) {
      // the fetch may still be pending or has failed: as a last resort try the
      // data cached in localStorage before bothering the user
      if (!this.loadGlobalDataFromStorage()) {
        this.showErrorMessage('Game data could not be loaded.', 'retry');
        return;
      }
    }
    var needResizeApp = false;
    var selectionItem = 0;
    if (this.model) {
      if (this.model.id == 'TapeLoadingModel') {
        selectionItem = 5;
      }
      this.model.shutdown();
      needResizeApp = true;
    }
    switch (model) {
      case 'LoadingModel':
        this.model = new ZXResetModel(this);
        break;
      case 'MenuModel':
        this.model = new MenuModel(this, selectionItem);
        break;
      case 'MainModel':
        this.model = new MainModel(this);
        break;
      case 'HighwayModel':
        this.model = new HighwayModel(this);
        break;
      case 'GameOverModel':
        this.model = new GameOverModel(this, 'MenuModel');
        break;
      case 'TapeLoadingModel':
        this.model = new TapeLoadingModel(this);
        break;
    } // switch
    this.model.init();
    if (needResizeApp) {
      this.resizeApp();
    }
  } // setModel

  /** Starts a new game at the top of the road. */
  startHighway() {
    this.score = 0;
    this.zone = (this.globalData && this.globalData.firstZone) || ScreenLayout.FIRST_ZONE;
    this.vortons = (this.globalData && this.globalData.vortons) || ScreenLayout.VORTONS;
    this.setModel('HighwayModel');
  } // startHighway

  applyGlobalData(global) {
    this.globalData = global;
    this.zone = global.firstZone || this.zone;
    this.vortons = global.vortons || this.vortons;
  } // applyGlobalData

  setGlobalData(data) {
    this.applyGlobalData(data.data.global);

    var files = {};
    Object.keys(data.data).forEach((key) => {
      if (key == 'hiScore') {
        this.hiScore = data.data[key];
      } else if (key != 'global') {
        files[key] = data.data[key];
      }
    });
    // global goes last; a full localStorage is cleared and tried once more
    // (R-062)
    this.saveAppDataToStorage(files, data.data.global);
  } // setGlobalData

  // Load the application data: from the server when online (which also refreshes
  // localStorage), or rehydrate the global data from localStorage when offline.
  loadAppData() {
    if (navigator.onLine) {
      this.fetchDataId = this.fetchData('appData.db', false, {}, this, 2000);
    } else {
      this.loadGlobalDataFromStorage();
    }
  } // loadAppData

  loadGlobalDataFromStorage() {
    var stored = localStorage.getItem(window.appPrefix+'.global');
    if (stored !== null) {
      try {
        this.applyGlobalData(JSON.parse(stored));
        return true;
      } catch (error) {
        console.error(error.message);
      }
    }
    return false;
  } // loadGlobalDataFromStorage

  setData(data) {
    this.setGlobalData(data);
  } // setData

  errorData(error) {
    // The network request failed (offline, unreachable server, or the fetch
    // timeout). Fall back to the data cached in localStorage; if none exists,
    // log it and let the MenuModel guard surface the error to the user.
    if (!this.loadGlobalDataFromStorage()) {
      console.error(error.message ? error.message : error);
      return;
    }
    if (this.model && this.model.id == 'ZXResetModel'
        && !this.model.events.some((queued) => queued.id == 'setMenuModel')
        && !this.model.desktopEntity.modalEntity) {
      this.setModel('MenuModel');
    }
  } // errorData

  showErrorMessage(message, action) {
    var topModalEntity = this.model.desktopEntity.topModalEntity();
    topModalEntity.addModalEntity(
      new ZXErrorEntity(
        topModalEntity,
        -topModalEntity.absoluteX(),
        -topModalEntity.absoluteY(),
        this.fonts.zxFonts8x8,
        message,
        action,
        ZXColor.white,
        ZXColor.red
      )
    );
  } // showErrorMessage

} // GameApp
