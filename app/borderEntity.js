const { AbstractEntity } = await import('./svision/js/abstractEntity.js?ver='+window.srcVersion);
const { ButtonEntity } = await import('./svision/js/platform/canvas2D/buttonEntity.js?ver='+window.srcVersion);
const { TextEntity } = await import('./svision/js/platform/canvas2D/textEntity.js?ver='+window.srcVersion);
const { Tool } = await import('./svision/js/tool.js?ver='+window.srcVersion);
const { ZXColor } = await import('./svision/js/platform/canvas2D/zx/zxColor.js?ver='+window.srcVersion);
// begin code

/**
 * The ZX Spectrum border: the optional exit (X) button, the two halves used by
 * the touch controls, the developer-mode banner — and the loading stripes.
 *
 * The stripe animation is the tape one (pilot tone, data, and the screech of
 * a broken load), driven by TapeLoadingModel. What the border does during the
 * game itself — its colour, and whether the game changes it — is still open
 * (ZADANI chap. 7); M8 measures it and adds it here.
 */
export class BorderEntity extends AbstractEntity {

  constructor(enableExit, enableGameControls) {
    super(null, 0, 0, 0, 0, false, false);
    this.id = 'BorderEntity';

    this.enableExit = enableExit;
    this.enableGameControls = enableGameControls;

    this.diff = 0;
    this.animation = false;
    this.stripes = [];
    this.style = {
      pilotTone: {colors: ['cyan', 'red'], stripeHeight: 10},
      dataTone: {colors: ['blue', 'yellow'], stripeHeight: 3},
      screech: {colors: ['white', 'yellow', 'cyan', 'green', 'magenta', 'red', 'blue', 'black'], stripeHeight: 1}
    };

    this.escapeEntity = null;
    this.escapeScale = 2;

    this.leftControlEntity = null;
    this.rightControlEntity = null;
    this.devModeNameEntity = null;
  } // constructor

  init() {
    super.init();

    if (this.enableExit) {
      if (this.app.layout.ratio > 2) {
        this.escapeScale = 1;
      }
      this.escapeEntity = new ButtonEntity(this, this.app.fonts.zxFonts8x8Mono, 0, 0, this.escapeScale*8, this.escapeScale*8, 'X', {id: 'keyPress', key: 'Escape'}, [], false, false, {scale: this.escapeScale, clickColor: '#7a7a7aff'});
      this.addEntity(this.escapeEntity);
    }

    if (this.enableGameControls) {
      this.leftControlEntity = new AbstractEntity(this, 0, 0, 0, 0, false, false);
      this.addEntity(this.leftControlEntity);
      this.rightControlEntity = new AbstractEntity(this, 0, 0, 0, 0, false, false);
      this.addEntity(this.rightControlEntity);
    }

    if (this.app.devModeName !== false) {
      this.devModeNameEntity = new TextEntity(this, this.app.fonts.fonts5x5, 0, -7, 100, 7, '', false, false, {margin: 1});
      var cfgLen = this.app.devModeName.indexOf('}');
      this.devModeNameEntity.setText(this.app.devModeName.substring(cfgLen+1));
      var cfg = null;
      try {
        cfg = JSON.parse(this.app.devModeName.substring(1, cfgLen+1));
        Object.keys(cfg).forEach((item) => {
          this.devModeNameEntity[item] = cfg[item];
        });
      } catch (error) {
        console.error(error.message);
      }
      // no width in the configuration: the banner is as wide as its text (R-025)
      if (!cfg || !('width' in cfg)) {
        this.devModeNameEntity.width = this.devModeNameEntity.lineWidth(this.devModeNameEntity.text)+2;
      }
      this.addEntity(this.devModeNameEntity);
    }
  } // init

  drawEntity() {
    super.drawEntity();

    if (this.escapeEntity) {
      var penColor = ZXColor.brightWhite;
      if (this.animation !== false) {
        penColor = ZXColor.black;
      }
      switch (this.bkColor) {
        case ZXColor.white:
        case ZXColor.yellow:
        case ZXColor.cyan:
          penColor = ZXColor.black;
          break;
      }
      if (this.escapeEntity.penColor !== penColor) {
        this.escapeEntity.setPenColor(penColor);
      }
    }

    if (this.animation === false) {
      this.drawSubEntities();
      return;
    }

    var y = 0;
    var color = 0;
    if (this.animation == 'screech') {
      color = Math.floor(Math.random()*this.style[this.animation].colors.length);
    } else {
      color = Math.floor(this.diff/10);
    }
    if (this.stripes.length == 0) {
      while (y < this.height) {
        var stripeHeight = this.style[this.animation].stripeHeight;
        if ((y == 0) && (this.animation == 'pilotTone')) {
          stripeHeight = 10-this.diff%10;
        }
        var extraStripe = 0;
        if (this.animation == 'dataTone') {
          extraStripe = Math.round(Math.random()*stripeHeight);
        }
        if (this.animation == 'screech') {
          if (this.style[this.animation].colors[color] != 'black') {
            extraStripe = Math.round(Math.random()*6);
          }
        }
        if (y+stripeHeight+extraStripe > this.height) {
          stripeHeight = this.height-y-extraStripe;
        }
        this.stripes.push({y: y, height: stripeHeight+extraStripe, color: ZXColor[this.style[this.animation].colors[color]]});
        y += stripeHeight+extraStripe;
        if (this.animation == 'screech') {
          color = Math.floor(Math.random()*this.style[this.animation].colors.length);
        } else {
          color = Tool.cycleInc(color, 0, this.style[this.animation].colors.length-1);
        }
      }
    }
    for (var s = 0; s < this.stripes.length; s++) {
      this.app.layout.paintRect(this.app.stack.ctx, 0, this.stripes[s].y, this.width, this.stripes[s].height, this.stripes[s].color);
    }
    this.drawSubEntities();
  } // drawEntity

  handleEvent(event) {
    if (super.handleEvent(event)) {
      return true;
    }

    switch (event.id) {
      case 'setBorderAnimation':
        this.animation = event.value;
        if (this.animation === 'pilotTone' || this.animation === 'screech') {
          this.sendEvent(0, 50, {id: 'moveStripes'});
        }
        return true;
      case 'moveStripes':
        this.stripes = [];
        if (this.animation !== false) {
          if (this.animation == 'screech') {
            this.diff = Math.floor(Math.random()*this.style[this.animation].colors.length*10);
          } else {
            this.diff = Tool.cycleInc(this.diff, 0, this.style[this.animation].colors.length*10-1);
          }
          this.sendEvent(0, 50, {id: 'moveStripes'});
        }
        return true;
      case 'resizeModel':
        if (this.escapeEntity) {
          if (this.model.borderHeight < this.escapeScale*8) {
            this.escapeEntity.x = this.model.borderWidth+this.model.desktopEntity.width;
            this.escapeEntity.y = this.model.borderHeight;
          } else {
            this.escapeEntity.x = this.model.borderWidth+this.model.desktopEntity.width-this.escapeScale*8;
            this.escapeEntity.y = this.model.borderHeight-this.escapeScale*8;
          }
        }
        
        if (this.enableGameControls) {
          var w = Math.floor(this.width/2);

          this.leftControlEntity.x = 0;
          this.leftControlEntity.y = 0;
          this.leftControlEntity.width = w;
          this.leftControlEntity.height = this.height;

          this.rightControlEntity.x = this.width-w;
          this.rightControlEntity.y = 0;
          this.rightControlEntity.width = w;
          this.rightControlEntity.height = this.height;
        }

        if (this.devModeNameEntity) {
          this.devModeNameEntity.x = Math.floor((this.width-this.devModeNameEntity.width)/2);
          this.devModeNameEntity.y = Math.max(Math.floor((this.app.model.borderHeight-this.devModeNameEntity.height)/2), 0);
        }
        break;
    }

    return false;
  } // handleEvent

} // BorderEntity
