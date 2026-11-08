<?php

require_once 'app/svision/php/abstractAboutPage.php';

/**
 * The /about page: the story of the original Highway Encounter and of this
 * remake, the controls, and links to the archives.
 */
class AboutPage extends AbstractAboutPage {

  protected function aboutData() {
    return [
      'image' => 'images/cover.png',
      'sections' => [
        [
          'heading' => 'The original game (1985)',
          'html' =>
            '<p>Highway Encounter was written by Costa Panayi and released by Vortex Software in '.
            'August 1985 for the 48K ZX Spectrum, with cover art by Wil Rowlands. Aliens have taken '.
            'the Earth and one road is left. Five Vortons — droids that look a little like Daleks — '.
            'have to push the Lasertron, a pyramid-shaped weapon, all the way down it, from Zone 30 '.
            'to Zone Zero, and destroy the alien stronghold at the end.</p>'.
            '<p>Its defining idea is an inversion of the usual arcade contract: your spare lives are '.
            'not waiting safely at the bottom of the screen, they are out on the road with you, '.
            'pushing the bomb forward by themselves — and they can all be destroyed before you ever '.
            'get to play them. The game keeps running off-screen, so clearing the way ahead and then '.
            'coming back for the convoy is the whole game. You drive one Vorton at a time, turning it '.
            'left and right and working a throttle rather than pushing it in eight directions, and it '.
            'takes a while to get going and longer to stop. Crash gave it 95% and a Crash Smash.</p>',
        ],
        [
          'heading' => 'This remake',
          'html' =>
            '<p>This is a faithful remake, rewritten for the web browser rather than emulated. The '.
            'graphics and the world are taken out of the original program, not redrawn, and the rules '.
            'come from the original instructions and from a disassembly of the game — no public '.
            'disassembly of this one exists, so it is being written from scratch. Where a rule cannot '.
            'be shown, it is left as an open question rather than guessed. Even the frame rate is the '.
            'Spectrum\'s own 50.08 Hz, and the attribute clash of the hardware is reproduced instead '.
            'of cleaned up — the road and everything standing on it in black and white, the colour '.
            'kept for the strips along the roadside, exactly as the original does it.</p>'.
            '<p>It runs directly in your browser — nothing to install, nothing to download, and '.
            'free of charge.</p>',
        ],
        [
          'heading' => 'Controls',
          'html' =>
            '<p>The original\'s own keys: <b>1</b> to speed up, <b>Q</b> to slow down, <b>O</b> and '.
            '<b>P</b> to turn left and right, <b>SPACE</b> to fire, <b>H</b> to hold and <b>A</b> to '.
            'abort the game. The arrow keys work as well, and every key can be changed under '.
            'SETTINGS.</p>'.
            '<p>Gamepads are supported and the whole game can be played on one. On a phone or a '.
            'tablet, one half of the screen border fires and the other is a joystick: slide across '.
            'it to turn, slide up and down to work the throttle. Which half is which is up to you '.
            '— it is in SETTINGS too.</p>'.$this->installNote().
            '<p>Remember that the Vorton is driven, not pushed around: he turns rather than walking '.
            'in eight directions, he takes a while to get going and much longer to stop.</p>',
        ],
        [
          'heading' => 'Other games',
          'html' =>
            '<p>This remake is one of a growing collection of classic games from the 8-bit and 16-bit era '.
            '— ZX Spectrum, Commodore 64, arcade and more — rebuilt faithfully on the same library and '.
            'playable in your browser, free of charge. Browse the whole collection at '.
            '<a href="https://retrogames.free/" target="_blank" rel="noopener">retrogames.free</a>.</p>',
        ],
      ],
      'links' => [
        ['label' => 'Highway Encounter at Spectrum Computing', 'url' => 'https://spectrumcomputing.co.uk/entry/2323/ZX-Spectrum/Highway_Encounter'],
        ['label' => 'Highway Encounter at World of Spectrum', 'url' => 'https://worldofspectrum.org/archive/software/games/highway-encounter-vortex-software'],
      ],
      'footer' =>
        '<p>An unofficial fan remake. The original game and its artwork belong to their authors '.
        '(Costa Panayi and Vortex Software). '.
        'The remake\'s source code is licensed under <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank" rel="noopener">CC BY-NC-SA 4.0</a>.</p>',
    ];
  } // aboutData

} // AboutPage
