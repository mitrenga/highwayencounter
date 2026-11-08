const { AbstractAudioManager } = await import('./svision/js/audio/abstractAudioManager.js?ver='+window.srcVersion);
const { AudioWorkletHandler } = await import('./svision/js/audio/audioWorkletHandler.js?ver='+window.srcVersion);
const { AudioScriptProcessorHandler } = await import('./svision/js/audio/audioScriptProcessorHandler.js?ver='+window.srcVersion);
const { AudioSilentHandler } = await import('./svision/js/audio/audioSilentHandler.js?ver='+window.srcVersion);
const { Tool } = await import('./svision/js/tool.js?ver='+window.srcVersion);
const { ZXMachineSounds } = await import('./svision/js/platform/canvas2D/zx/zxMachineSounds.js?ver='+window.srcVersion);
const { gameSound, menuSound } = await import('./soundEffects.js?ver='+window.srcVersion);
// begin code

/**
 * Audio manager. The original has a one-bit beeper on bit 4 of port $FE and no
 * sound chip (ZADANI chap. 1), so every sound is a stream of pulse lengths
 * (app/soundEffects.js for the game's own, svision ZXMachineSounds for the
 * machine's) played by the svision pulse handlers — the same way the
 * machine makes sound, not sampled.
 *
 * M1 had only the sounds of the **machine**: the tape load and the ROM's key
 * click. M8 added the game's own, straight out of its routines
 * (tools/dumpsound.py -> data/sounds.json, app/soundEffects.js): five effects
 * and a menu beep, each a program that flips the speaker rather than a
 * waveform, and each replayed against the original T state for T state.
 *
 * There is still deliberately no MUSIC bus, and now that is measured rather
 * than assumed: the original has no music. All three of its `OUT ($FE),A`
 * instructions sit inside sound routines, and in every pass of the main loop
 * that asked for no effect it does not touch the port at all.
 */
export class AudioManager extends AbstractAudioManager {

  constructor(app) {
    super(app);
    this.id = 'AudioManager';
    this.volume = {};
    // the measured sound routines of the original, handed over by HighwayModel
    // once data/sounds.json is loaded (M8)
    this.gameSounds = null;
    this.volume.sounds = Math.min(10, Math.max(0, Math.round(Number(Tool.readCookie('audioBusSoundsLevel', 5)))));
  } // constructor

  createAudioHandler(bus, options) {
    var audioHandler = false;

    var volume = 0.0;
    switch (bus) {
      case 'sounds':
      case 'extra':
        volume = this.volumeLevel(this.volume.sounds);
        break;
    }

    if (options.audioSilentHandler != 'disable' && volume == 0.0) {
      return new AudioSilentHandler(this.app);
    }

    if (this.unsupportedAudioBus == false) {
      this.unsupportedAudioBus = Tool.readCookie('unsupportedAudioBus', false);
    }

    switch (this.unsupportedAudioBus) {
      case false:
        audioHandler = new AudioWorkletHandler(this.app);
        break;
      case 'AudioWorkletHandler':
        Tool.writeCookie('unsupportedAudioBus', 'AudioWorkletHandler');
        audioHandler = new AudioScriptProcessorHandler(this.app);
        break;
      case 'AudioScriptProcessorHandler':
        Tool.writeCookie('unsupportedAudioBus', 'AudioScriptProcessorHandler');
        audioHandler = new AudioSilentHandler(this.app);
        break;
    }

    if (bus in this.restartSounds) {
      this.app.model.sendEvent(1, {id: 'playSound', bus: bus, sound: this.restartSounds[bus].sound, options: this.restartSounds[bus].options});
    }

    return audioHandler;
  } // createAudioHandler

  audioData(bus, sound, options) {
    var data = super.audioData(bus, sound, options);
    if (data !== false) {
      return data;
    }

    var sampleRate = this.getSampleRate();
    var sounds = this.volumeLevel(this.volume.sounds);
    switch (sound) {
      case 'tapePilotToneSound': return ZXMachineSounds.tapePilotTone(sampleRate, sounds);
      case 'tapeRndDataSound': return ZXMachineSounds.tapeRndData(sampleRate, sounds);
      case 'basicBeepsSound': return ZXMachineSounds.basicBeeps(sampleRate, sounds);
      case 'keyboardSound': return ZXMachineSounds.keyClick(sampleRate, sounds);
    }
    // M8: the game's own effects. They are not cached — an explosion draws its
    // pitch and its length from the game's generator, so every one of them is
    // a different list of pulses and the seed comes with the request.
    if (this.gameSounds) {
      if (sound.charAt(0) === '$') {
        return menuSound(this.gameSounds, sound, sampleRate, sounds);
      }
      var made = gameSound(this.gameSounds, sound,
                           (options && options.seed) || 0, sampleRate, sounds);
      if (made !== false) { return made; }
    }
    return false;
  } // audioData

  /**
   * Hands over the measured sound routines (data/sounds.json). Without them
   * nothing of the game is played — the same rule every other milestone
   * follows here.
   * @param {Object|null} data - The parsed data/sounds.json.
   */
  setGameSounds(data) {
    this.gameSounds = data || null;
  } // setGameSounds

  volumeLevel(volume) {
    var levels = [0, 0.005, 0.01, 0.02, 0.04, 0.07, 0.1, 0.14, 0.18, 0.23, 0.29];
    return levels[volume];
  } // volumeLevel

  /**
   * One worker frame: what the passes in it asked to be heard.
   *
   * The original plays at most one effect per pass of the main loop, and it
   * plays it **synchronously** — the loop waits for it. A frame here can carry
   * more than one pass, so only the last request is played: piling them up
   * would run the beeper behind the game, which is the one thing the original
   * never does.
   * @param {Object} frame - The 'frame' message from the worker.
   */
  playFrame(frame) {
    if (!this.gameSounds || !frame.sounds || !frame.sounds.length) { return; }
    var last = frame.sounds[frame.sounds.length-1];
    this.playSound('sounds', last.name, {seed: last.seed|0});
  } // playFrame

} // AudioManager
