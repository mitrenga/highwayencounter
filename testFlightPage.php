<?php

require_once 'app/svision/php/appPage.php';

/**
 * The /testFlight page: the game, driven by a recording instead of a player.
 *
 * The sibling remakes write their test flight by hand. This one does not have
 * to: `sources/tape/highway.rzx` is twenty-six minutes of a real player
 * finishing the original, and `tools/dumpflight.py` reads out of it what the
 * game itself saw on the keyboard ($8F14) in every frame. What is embedded
 * below is the first hundred seconds of that run, run-length coded, and the
 * worker replays it frame by frame (gameWorker.js, message `testFlight`).
 *
 * The original's own DEMONSTRATION mode would have been the obvious source and
 * it is not usable: measured, it leaves $8F14 at $14 for its whole length —
 * the attract mode drives its Vorton itself and never goes through the
 * keyboard byte.
 *
 * The flight is not a matcher and is not expected to end where the player's
 * run ended: until M2 knows the contents of the zones the port drives an empty
 * road. It is a check that a deployed build starts, draws, sounds and does not
 * fall over.
 */
class TestFlightPage extends AppPage {
  
  public function createPage() {
    $srcVersion = $this->srcVersion();

    $this->data[] = '<!-- free source code on https://github.com/mitrenga -->';
    $this->data[] = '<!DOCTYPE html>';
    $this->data[] = '<html lang="en">';
    $this->data[] = '  <head>';
    $this->data[] = '    <title>'.$GLOBALS['appName'].'</title>';
    $this->data[] = '    <meta name="description" lang="cs" content="'.$GLOBALS['appName'].'">';
    $this->data[] = '    <meta name="viewport" content="width=device-width, initial-scale=1.0, minimum-scale=1.0, maximum-scale=1.0, user-scalable=0, viewport-fit=cover">';
    $this->data[] = '    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">';
    $this->data[] = '    <meta name="robots" content="noindex, nofollow">';
    $this->data[] = '    <meta name="mobile-web-app-capable" content="yes">';
    $this->data[] = '    <link rel="shortcut icon" sizes="256x256" href="images/app-icon-256x256.png" id="app-icon">';
    $this->data[] = '    <link rel="apple-touch-icon" sizes="192x192" href="images/app-icon-192x192.png">';
    $this->data[] = '    <meta name="theme-color" content="#000000">';
    $this->data[] = '    <link rel="manifest" href="'.$GLOBALS['webURL'].'manifest.webmanifest">';
    $this->data[] = '    <meta http-equiv="X-UA-Compatible" content="IE=Edge; IE=11;" />';
    $this->data[] = '    <link rel="stylesheet" type="text/css" href="app/svision/css/main.css?ver='.$srcVersion.'">';
    $this->data[] = '  </head>';
    $this->data[] = '  <body id="bodyApp">';
    $this->data[] = '    <script>window.appName = "'.$GLOBALS['appName'].'";</script>';
    $this->data[] = '    <script>window.clientIP = "'.$GLOBALS['clientIP'].'";</script>';
    $this->data[] = '    <script>window.appPrefix = "'.$GLOBALS['appPrefix'].'";</script>';
    $this->data[] = '    <script>window.wsURL = "'.$GLOBALS['wsURL'].'";</script>';     
    $this->data[] = '    <script>window.srcVersion = "'.$srcVersion.'";</script>';
    $this->data[] = '    <script>window.devMode = '.json_encode($GLOBALS['devMode'] ?? false).';</script>';
    $this->data[] = '    <script>window.devModeName = ".{\"penColor\":\"#ffffff\",\"bkColor\":\"#107d10\",\"width\":130}  TEST FLIGHT MODE   ← ↑ →";</script>';
    $this->data[] = '    <script>window.appIconSprite = "'.$this->spriteEncode().'";</script>';

    $bundle = $this->bundleFile();

    $this->data[] = '    <script>window.importPath = "'.$this->importPath().'";</script>';

    if ($bundle !== false) {
      $this->data[] = '    <script type="module" src="'.$bundle.'?ver='.$srcVersion.'"></script>';
    } elseif (!empty($GLOBALS['devMode'])) {
      $this->data[] = '    <script type="module" src="app/main.js?ver='.$srcVersion.'"></script>';
    } else {
      $this->data[] = '    <script type="module" src="app/maintenance.js?ver='.$srcVersion.'"></script>';
    }    
    $this->data[] = '  </body>';
    $this->data[] = '</html>';
  } // createPage

  function testFlightData() {
    // Written by tools/dumpflight.py out of sources/tape/highway.rzx: runs of
    // NNc, where c is a base32 digit of the original's own key mask ($8F14)
    // and NN an optional repeat count. Rows break only between runs, so they
    // are simply glued together; the padding character '.' is skipped by the
    // worker's decoder.
    return [
      "99099099099069024C31009813C99018007K70006K31035259010413012169010215040407K",
      "04G21007804008111009104008104005121013228011810003821012G070252720125044055",
      "04408546408012204012408512418003833007133006806006807118005G111030071070078",
      "03021803010103008G06H03108008102008109009803A12203002404509K10404K104035071",
      "08006817007111006G10006108007105003127016G53022209A15217I17205A652050514200",
      "29284076499054003822018G25010G13005810061210A04213A122120168130088050188120",
      "16G23004G19404015G02015205010822005G15005855005G17005815010299069051403010G",
      "21009809007115007103006G03013803009203009412015206010812203003G12K09403K03G",
      "15006803013209003G09K06406K15403003809007114006819005110004107003119012G130",
      "03203003G03017239007G03025407K03406007G06029G09016233007G990230038990210098",
      "18009G12009G12007G03006812009816009G18008820019299018008852007G140142030284",
      "59034438003G07003G31007207007G14010210804049405G",
    ];
  } // testFlightData

  function codeHack() {
    return [
      "{",
      "this.sendWorkerMessage({id:'testFlight',script:arg1.sprite[1].grid.join('')});",
      "}"
    ];
  } // codeHack

  function spriteData() {
    $codeHack = $this->codeHack();
    $flight = $this->testFlightData();
    $width = max(array_map('strlen', array_merge($codeHack, $flight)));
    $height = max(count($codeHack), count($flight));
    return [
      'width' => $width,
      'height' => $height,
      'frames' => 2,
      'directions' => 1,
      'colors' => false,
      'sprite' => [
        [
          'colors' => $this->collectChars($codeHack),
          'grid' => array_map(fn($s) => str_pad($s, $width, ' '), array_pad($codeHack, $height, ''))
        ],
        [
          'colors' => $this->collectChars(array_merge($flight, ['.'])),
          'grid' => array_map(fn($s) => str_pad($s, $width, '.'), array_pad($flight, $height, ''))
        ],
      ],
    ];
  } // spriteData

  function spriteWidth() {
    return $this->spriteData()['width'];
  } // spriteWidth

  function spriteHeight() {
    return $this->spriteData()['height'];
  } // spriteHeight

  function collectChars($rows) {
      $all = implode('', $rows);
      $chars = array_unique(mb_str_split($all));
      $colors = [];
      foreach ($chars as $ch) {
        $colors[$ch] = false;
        if ($ch != ' ') {
          $colors[$ch] = $ch;
        }
      }
      return $colors;
  } // collectChars
  

  function intToBraille($num, $len) {
    $res = '';
    while ($len > 0) {
      $res = mb_chr(0x2801+($num%255), 'UTF-8').$res;
      $num = (int)floor($num/255);
      $len--;
    }
    return $res;
  } // intToBraille

  function objLenToBraille($obj, $len) {
    $cnt = 254;
    if ($obj !== false) {
      $cnt = count($obj);
    }
    return $this->intToBraille($cnt, $len);
  } // objLenToBraille

  function strLenToBraille($str, $len) {
    $cnt = 254;
    if ($str !== false) {
      $cnt = mb_strlen($str, 'UTF-8');
    }
    return $this->intToBraille($cnt, $len);
  } // strLenToBraille

  function encodePaletteBlock($palette) {
    $result = '';
    foreach ($palette as $ch => $color) {
      $result .= $this->intToBraille(mb_ord($ch, 'UTF-8'), 1);
      $result .= $this->strLenToBraille($color, 1);
      if ($color !== false) {
        foreach (mb_str_split($color, 1, 'UTF-8') as $c) {
          $result .= $this->intToBraille(mb_ord($c, 'UTF-8'), 1);
        }
      }
    }
    return $result;
  } // encodePaletteBlock

  function findTransparentChar($palette) {
    if ($palette === false) return null;
    foreach ($palette as $ch => $v) {
      if ($v === false) return $ch;
    }
    return null;
  } // findTransparentChar

  function encodeGridBlock($grid, $palette, $width, $height, $posLen, $cellBytes) {
    $codeChars   = array_keys($palette);
    $codeIndex   = array_flip($codeChars);
    $numCodes    = count($codeChars);
    // 1-byte cell: intdiv(255,n), 2-byte cell: intdiv(65025,n)
    $maxReps     = intdiv(255 ** $cellBytes, $numCodes);
    $transparent = $this->findTransparentChar($palette);

    $rows = [];
    for ($y = 0; $y < $height; $y++) {
      $rows[$y] = isset($grid[$y]) ? mb_str_split($grid[$y], 1, 'UTF-8') : [];
    }

    $startY = -1; $endY = -1;
    for ($y = 0; $y < $height; $y++) {
      foreach ($rows[$y] as $ch) {
        if ($ch !== $transparent) {
          if ($startY === -1) $startY = $y;
          $endY = $y;
          break;
        }
      }
    }

    if ($startY === -1) {
      return $this->intToBraille($height, $posLen).$this->intToBraille($height, $posLen);
    }

    $result  = $this->intToBraille($startY, $posLen);
    $result .= $this->intToBraille($endY, $posLen);

    for ($y = $startY; $y <= $endY; $y++) {
      $rowArr = $rows[$y];
      $rowLen = count($rowArr);
      $firstX = -1; $lastX = -1;
      for ($x = 0; $x < $rowLen; $x++) {
        if ($rowArr[$x] !== $transparent) {
          if ($firstX === -1) $firstX = $x;
          $lastX = $x;
        }
      }
      if ($firstX === -1) {
        $result .= $this->intToBraille($width, $posLen);
        continue;
      }
      $result .= $this->intToBraille($firstX, $posLen);
      $result .= $this->intToBraille($lastX, $posLen);

      $x = $firstX;
      while ($x <= $lastX) {
        $ch = $rowArr[$x];
        $runEnd = $x + 1;
        while ($runEnd <= $lastX && $rowArr[$runEnd] === $ch) $runEnd++;
        $runLen = $runEnd - $x;
        $colorIdx = $codeIndex[$ch] ?? 0;
        while ($runLen > 0) {
          $part = min($runLen, $maxReps);
          $result .= $this->intToBraille(($part - 1)*$numCodes + $colorIdx, $cellBytes);
          $runLen -= $part;
        }
        $x = $runEnd;
      }
    }
    return $result;
  } // encodeGridBlock

  function encodeBrailleBody($spriteData, $posLen, $cellBytes)
  {
    $width         = $spriteData['width'];
    $height        = $spriteData['height'];
    $frames        = $spriteData['frames'];
    $directions    = $spriteData['directions'];
    $sharedPalette = $spriteData['colors'];

    $body = $this->objLenToBraille($sharedPalette, 1);
    if ($sharedPalette !== false) {
      $body .= $this->encodePaletteBlock($sharedPalette);
    }

    for ($d = 0; $d < $directions; $d++) {
      for ($f = 0; $f < $frames; $f++) {
        $entry   = $spriteData['sprite'][$f + $d*$frames];
        $palette = $sharedPalette !== false ? $sharedPalette : $entry['colors'];

        if ($sharedPalette === false) {
          $body .= $this->intToBraille(count($palette), 1);
          $body .= $this->encodePaletteBlock($palette);
        }

        $body .= $this->encodeGridBlock($entry['grid'], $palette, $width, $height, $posLen, $cellBytes);
      }
    }

    return $body;
  } // encodeBrailleBody

  function spriteEncode()
  {
    $spriteData = $this->spriteData();
    $width      = $spriteData['width'];
    $height     = $spriteData['height'];
    $frames     = $spriteData['frames'];
    $directions = $spriteData['directions'];
    // Position byte width derived from dimensions (one braille char holds 0..254).
    $posLen     = ($width > 254 || $height > 254) ? 2 : 1;

    // Variant A: encode the grid both ways, keep the shorter. Tie -> 1-byte.
    $body1 = $this->encodeBrailleBody($spriteData, $posLen, 1);
    $body2 = $this->encodeBrailleBody($spriteData, $posLen, 2);
    $useDouble = mb_strlen($body2, 'UTF-8') < mb_strlen($body1, 'UTF-8');
    $body = $useDouble ? $body2 : $body1;

    $result  = $this->intToBraille(0xFE, 1);
    $result .= $this->intToBraille(0xFE, 1);
    $result .= $this->intToBraille(0xFE, 1);
    $result .= $this->intToBraille(1, 1);
    $result .= $this->intToBraille($useDouble ? 2 : 0, 1);
    $result .= $this->intToBraille($width, 2);
    $result .= $this->intToBraille($height, 2);
    $result .= $this->intToBraille($frames, 1);
    $result .= $this->intToBraille($directions, 1);
    $result .= $body;

    return $result;
  } // spriteEncode

} // TestFlightPage
