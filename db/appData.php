<?php

class DataCommand {

  var $files = ['global', 'menu', 'loading', 'panel', 'panelfields', 'physics', 'objects', 'convoy', 'enemies', 'font', 'ending', 'intro', 'sounds', 'score',
                  // M2: silnice – obraz zón, sprity, projekce, tabulka dat
                  // silnice a pravidlo, kterým se z ní zóna plní
                  'scenery', 'spriteframes', 'projection', 'highway', 'zones',
                  // M9: kadence hlavní smyčky – jak dlouho trvá průchod
                  'cadence'];

  public function execute($postData) {
    $result = [];
    foreach ($this->files as $file) {
      $fileName = 'data/'.$file.'.json';
      if (!is_file($fileName)) {
        // optional data files (those a later milestone adds) arrive as null
        $result[$file] = null;
        continue;
      }
      $dataJSON = file_get_contents($fileName);
      try {
        $result[$file] = json_decode($dataJSON, false, 512, JSON_THROW_ON_ERROR);
      }
      catch (\JsonException $exception) {
        $result[$file] = ['error' => ['message' => $exception->getMessage()]];
      }
    }

    $mysqli = new mysqli($GLOBALS['dbHostname'], $GLOBALS['dbUser'], $GLOBALS['dbPassword'], $GLOBALS['dbName']);
    $data = $mysqli->query('SELECT `score` FROM `rg_he_hallOfFame` ORDER BY `score` DESC LIMIT 1');
    $mysqli->close();
    $result['hiScore'] = 0;
    if ($row = $data->fetch_object()) {
      $result['hiScore'] = $row->score;
    }

    return $result;
  } // execute

} // class DataCommand
