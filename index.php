<?php
  $appName = 'HIGHWAY ENCOUNTER';
  $appDescription = 'Play HIGHWAY ENCOUNTER online for free in your browser. Faithful remake of the 1985 Vortex Software ZX Spectrum classic, no download required.';
  $appPrefix = 'he';
  $appNoscript =
    '<h1>HIGHWAY ENCOUNTER</h1>'.
    '<p>Highway Encounter is the 1985 ZX Spectrum game by Costa Panayi, published by Vortex '.
    'Software. Five Vortons have to push the Lasertron down the last road left on Earth, from '.
    'Zone 30 to Zone Zero, and destroy the alien stronghold at the end of it. You drive one of '.
    'them; the other four push the bomb on their own, and can be destroyed while you are looking '.
    'the other way, because the road keeps running off-screen.</p>'.
    '<p>This is a faithful remake that runs directly in your web browser. '.
    'There is nothing to install and nothing to download — just open the page and play. '.
    'Please enable JavaScript to start the game.</p>'.
    '<p><a href="about">More about Highway Encounter and this remake</a></p>';
  $appOpenGraph = [
    'image' => 'images/poster.png',
  ];
  $appJsonLd = [
    'genre' => 'Action game',
    'isBasedOn' => [
      '@type' => 'VideoGame',
      'name' => 'Highway Encounter',
      'publisher' => [
        ['@type' => 'Organization', 'name' => 'Vortex Software'],
      ],
      'datePublished' => '1985',
      'gamePlatform' => 'ZX Spectrum',
    ],
  ];
  require_once 'config/config.php';
  require_once 'app/svision/php/main.php';
