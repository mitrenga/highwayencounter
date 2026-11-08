# tools/ – nástroje remaku

Všechno, co dělá data v `data/`, je tady. Pravidlo projektu: **žádný datový soubor
se nepíše ručně** – vždycky ho vyrobí nástroj z originálu, a nástroj v repu zůstane,
aby se dal výsledek kdykoli zopakovat.

Python 3, bez balíčků z pipu. SkoolKit je vendorovaný v `tools/vendor/` (mimo git,
rozbalený wheel, spouští se přes `PYTHONPATH=tools/vendor`) – do systému se
nezasahuje. `tools/vendor` a `build/` v gitu nejsou.

## Řetěz od kazety k datům

```sh
./tools/mksnapshot.sh                                     # kazeta → build/*.z80, build/*.bin
PYTHONPATH=tools/vendor ./tools/mkruntime.py --screen build/ingame.scr
PYTHONPATH=tools/vendor ./tools/dumppanel.py              # → data/panel.json
./tools/mkscreen.py sources/media/screens/loading_screen.scr data/loading.json
./tools/mkimages.py                                       # → images/, favicon.ico
PYTHONPATH=tools/vendor ./tools/probeview.py              # měření obrazu + build/zones/
PYTHONPATH=tools/vendor ./tools/dumpphysics.py            # → data/physics.json
PYTHONPATH=tools/vendor ./tools/tracephysics.py           # → build/traces/
./tools/matchphysics.js                                   # port proti originálu
PYTHONPATH=tools/vendor ./tools/dumpobjects.py            # → data/objects.json
PYTHONPATH=tools/vendor ./tools/traceobjects.py           # → build/otraces/
./tools/matchobjects.js                                   # svět proti originálu
PYTHONPATH=tools/vendor ./tools/dumpconvoy.py             # → data/convoy.json
PYTHONPATH=tools/vendor ./tools/dumppanelfields.py        # → data/panelfields.json
PYTHONPATH=tools/vendor ./tools/traceconvoy.py            # → build/ctraces/
./tools/matchconvoy.js                                    # konvoj proti originálu
PYTHONPATH=tools/vendor ./tools/dumphighway.py            # → data/highway.json
PYTHONPATH=tools/vendor ./tools/dumpzones.py             # → data/zones.json
PYTHONPATH=tools/vendor ./tools/tracezones.py            # → build/ztraces/
./tools/matchzones.js                                     # plnění zón proti originálu
PYTHONPATH=tools/vendor ./tools/dumpenemies.py            # → data/enemies.json
PYTHONPATH=tools/vendor ./tools/traceenemies.py           # → build/etraces/
./tools/matchenemies.js                                   # nepřátelé proti originálu
PYTHONPATH=tools/vendor ./tools/playrzx.py --timeline     # RZX záznam dohrání
PYTHONPATH=tools/vendor ./tools/dumpfont.py               # → data/font.json
PYTHONPATH=tools/vendor ./tools/dumpending.py             # → data/ending.json
PYTHONPATH=tools/vendor ./tools/dumpintro.py              # → data/intro.json
PYTHONPATH=tools/vendor ./tools/traceending.py            # → build/gtraces/
./tools/matchending.js                                    # konec hry proti originálu
PYTHONPATH=tools/vendor ./tools/dumpsound.py              # → data/sounds.json
PYTHONPATH=tools/vendor ./tools/dumpscore.py              # → data/score.json
PYTHONPATH=tools/vendor ./tools/dumpattrs.py              # → data/attrs.json
PYTHONPATH=tools/vendor ./tools/tracesound.py             # → build/straces/
./tools/matchsound.js                                     # žádanka zvuku proti originálu
PYTHONPATH=tools/vendor ./tools/matchpanel.py             # panel do posledního pixelu
```

| nástroj | co dělá |
|---|---|
| `mksnapshot.sh` | Z kazety (Speedlock 1) udělá snapshot a surový obraz RAM. Zároveň **ověří, že loading screen z kazety je bajt po bajtu tentýž jako `.scr`** v `sources/media/screens/`. |
| `mkruntime.py` | Spustí hru v simulátoru, projde menu `OPTIONS` (`1` KEYBOARD, `7` START GAME) a uloží RAM `$4000–$FFFF` **za běhu hry**. Změří, jestli se blok po nahrání v paměti neposunul (u Highway Encounter neposunul – u Underwurlde ano, a bez toho by byla disassembly rozsypaná). `--screen` uloží i obrazovku rozehrané hry. |
| `playtrace.py` | Odsimuluje hru se skriptem stisků kláves a ukládá snímky obrazovky do PNG + `.scr`, volitelně mapu pokrytí (adresy provedených instrukcí). Základ pro trasování. |
| `dumppanel.py` | Vytáhne **panel** z běžící hry do `data/panel.json` (bitmapa + atributy). Hra si panel drží jako hotový obrázek na `$6000`, viz `sources/docs/disasm_notes.md` §3. |
| `mkscreen.py` | Převede ZX `.scr` (6912 B) na datový soubor remaku – loading screen do `data/loading.json`. |
| `mkimages.py` | Z loading screenu udělá `images/cover.png`, `poster.png`, ikony aplikace a `favicon.ico`. Nic dokresleného, jen celočíselné škálování a výřez. |
| `scr2png.py` | Převod `.scr` → PNG, používají ho ostatní nástroje. |
| `highwaylib.py` | **Krokovatelný běh originálu** – obdoba `roomlib.py` z Underwurlde: nabootuje hru (a stav rozehrané hry si uloží do `build/gameplay.z80`, takže boot se dělá jednou), pak ji krokuje po snímcích, mezi snímky drží klávesy a dává obrazovku, hrací plochu a RAM. `step()` navíc krokuje **po krocích herní
smyčky** (adresa `$985A`), protože ta na snímek vázaná není – bez toho se fyzika
změřit nedá, viz `disasm_notes.md` §11. Základ všech extrakčních nástrojů. `demo()` nabootuje do `6 DEMONSTRATION`, kde si hra projede celou silnici sama. Krokuje se **doprostřed snímku**, ne na jeho hranici – jinak se hra přestane kreslit, viz `disasm_notes.md` §9. |
| `probeview.py` | Změří, **jak originál mění obraz**: změna bitmapy za snímek, vynulované atributy při přechodu zóny a korelace posunu. Tím je zavřená hlavní otázka M0b (neroluje se) a vypadnou z toho **referenční obrazovky všech 30 zón** do `build/zones/` – podklad pro `matchscreen.py`. `--mode player` totéž v rozehrané hře. |
| `dumpphysics.py` | Odměří na běžící hře **konstanty fyziky řízeného Vortona** → `data/physics.json`: osm směrů, tři rychlosti, posuvný registr plynu, otáčení po dvou krocích, okraje silnice, co udělá náraz, startovní pozice a délka jednoho průchodu hlavní smyčkou. Bez disassembly – každá konstanta vznikne naskriptovanými klávesami a měřením paměti (`disasm_notes.md` §13). |
| `tracephysics.py` | Zaznamená **originál krok po kroku** (ne po snímcích) při skriptovaných klávesách → `build/traces/*.json`. 30 scénářů včetně pseudonáhodných; do záznamu jde vstup tak, jak ho přečetla hra. |
| `matchphysics.js` | Přehraje `app/vortonPhysics.js` proti těm záznamům a hlásí každý rozdíl. Dnes **10 260 kroků, nula rozdílů**; u 1 % kroků si bere ze záznamu odpověď o předmětu v cestě (M2/M4) a počítá ji. |
| `dumpobjects.py` | Odměří na běžící hře **pravidla silnice** → `data/objects.json`: srážkovou krabici (hledá jedinou dvojici mezí, která na tisících kroků nedělá ani falešný poplach, ani přehlédnutí), druhy objektů a to, které se dají strčit, co strčení udělá a jak dojíždí, kde vzniká a jak daleko doletí výstřel, a délku zóny (kdy skočí kamera). Bez disassembly, viz `disasm_notes.md` §14. |
| `traceobjects.py` | Zaznamená **celý svět originálu krok po kroku** – ne jen Vortona jako `tracephysics.py`, ale celou tabulku objektů `$8A00` → `build/otraces/*.json`. 24 scénářů: strkání do všech stran, střelba do předmětů, přechod zóny, pseudonáhodné běhy. |
| `matchobjects.js` | Přehraje `app/highwayObjects.js` proti těm záznamům. Dnes **7862 kroků, 68 rozdílů**, 16 z 24 scénářů sedí do posledního bajtu (včetně všech na strkání a přechod zóny); konvoj, nepřátelé a obsah nové zóny se berou ze záznamu (M5/M6, M2) a každé takové vzetí se počítá a hlásí. |
| `dumpconvoy.py` | Odměří **konvoj** → `data/convoy.json` (M5): sestavu na startu, to, že konvoj nezatáčí ani nezrychluje a Lasertron netlačí (jede sám), srážkovou krabici – měřenou znovu a nezávisle na M4, a vyšla stejná – i to, že se čte **v pořadí tabulky**, co znamená bajt rychlosti v záznamu, že konvoj nestrká, jak široký průjezd potřebuje středem a co se stane, když je řízený Vorton zničen. Viz `disasm_notes.md` §15. |
| `dumppanelfields.py` | Sejme **živá pole panelu** → `data/panelfields.json` (M5): obrázek pole `ZONE` pro každou z 31 hodnot (z režimu `6 DEMONSTRATION`, který si projede celou silnici sám) a ikony řady `1 2 3 4 5`. Číslice se nesázejí, fotí se – v M5 proto, že znaková sada nebyla nalezená, a od M7 (kdy nalezená je, §2) proto, že velké segmentové písmo pole `ZONE` **není** ta znaková sada; je to samostatná grafika. Měření přitom opravilo předpoklad ZADANI §7: řada neukazuje, kolik Vortonů zbývá. |
| `traceconvoy.py` | Zaznamená běh originálu se scénáři psanými **na konvoj**: stát mu v cestě, uhnout a nechat ho dojet do neuklizených předmětů, uklízet mu průjezd střelbou, projet s ním hranici zóny a dlouhé běhy, ve kterých řízený Vorton zahyne a řízení se předá → `build/ctraces/`. Scénáře jsou schválně jiné než ty, na kterých `dumpconvoy.py` pravidla naměřil. |
| `matchconvoy.js` | Přehraje `app/highwayConvoy.js` proti těm záznamům – **obráceně než `matchobjects.js`**: počítá se konvoj a hráč, výstřely, předměty a nepřátelé se berou ze záznamu, aby čísla M5 nenesla 68 rozdílů M4. Dnes **18 scénářů, 10 500 kroků, 2224 rozdílů**, z toho 2223 jeden jediný jev (§15); 15 scénářů sedí do posledního bajtu, včetně dvou předání řízení. |
| `dumpenemies.py` | Odměří **nepřátele a pravidla srážek** → `data/enemies.json` (M6). Jinak než M3–M5: hra si pravidla drží v tabulkách, a ty se z běžící hry přečtou – rodiny objektů (horní bajt druhu bez bitu 4), tabulka kroku na `$8E00`, **matice srážek 11 × 11 na `$9000`**, masky směru rodiny 4, generátor náhody na `$5C76`, animace zániku a hodiny `TIME`. Přečtené se pak **ověří měřením**: referenční model se přehraje na každém naměřeném průchodu každého nepřítele (dnes 20 796 průchodů, 1 rozdíl). Dva scénáře jsou psané uzavřenou smyčkou (`hunt()`), protože slepým mačkáním se srážka s nepřítelem nepotká. Viz `disasm_notes.md` §16. |
| `traceenemies.py` | Zaznamená běh originálu se scénáři psanými **na nepřátele** → `build/etraces/`: koukat se, jet do zón, kde jsou, střílet do nich, dotknout se jich, projet celou silnici demem, a pseudonáhodné běhy. Ukládá se navíc **celá tabulka včetně konce** (`$FE`/`$FF`), **semínko generátoru** a **okno světa** – bez nich se nepřátelé přehrát nedají. |
| `matchenemies.js` | Přehraje `app/highwayEnemies.js` proti těm záznamům: počítají se **jen nepřátelé a animace zániku**, všechno ostatní se bere ze záznamu na své řadě v tabulce. Dnes **10 scénářů, 5716 kroků, 17 124 průchodů nepřátel, nula rozdílů**; navíc 4 rozdíly v průchodech, ve kterých si originál tahal z generátoru i jinde než u nepřátel (zvuk a kreslení, §16), a to se hlásí zvlášť. |
| `disasm.py` | Vypíše disassembly kusu paměti z `build/gameplay.z80` (`./tools/disasm.py 9D40 9E60`). Pomůcka, kterou si vyžádala M6: směr nepřítele se zvenčí odměřit nedá, takže se poprvé čte kód. Krokování po instrukcích, kterým se našla rutina zapisující směr, je v §16. |
| `playrzx.py` | Přehraje **RZX záznam** kompletního dohrání (`sources/tape/highway.rzx`) v simulátoru, s krokováním a snímáním paměti. RZX je záznam **vstupů**, takže běží tentýž kód a čte tytéž hodnoty z portů – výsledek je bit po bitu tentýž běh, jaký hráč odehrál. Celých 80 385 snímků trvá sedm sekund. `--timeline` vypíše každou změnu počítadla zón, `--scr` ukládá obrazovky a `--dump` uloží snapshot z libovolného snímku, ze kterého pak krokuje `highwaylib.Session`. Bez něj se konec hry změřit nedá: začíná až tehdy, když Lasertron dojede na konec silnice (M7). |
| `dumpfont.py` | Vytáhne **znakovou sadu** → `data/font.json` (M7). Zavírá největší otevřenou věc projektu (`disasm_notes.md` §2): glyf má **pět bajtů** na `$5B00 + 5 × (kód AND $3F)`, buňku kolem něj hra teprve skládá (`00`, `$7F`, glyf, `$7F`) a bity 6 a 7 kódu vybírají barvu, ne písmeno – proto ji osmibajtové hledání nemohlo najít. Přiřazení glyf → písmeno se **nehádá**: rozebere se jím titulní obrazovka, obrazovka `INFORMATION` a dva hotové řetězce z paměti, zkusí se všechna posunutí a vezme se to, ve kterém si žádný glyf neodporuje (dnes 36 glyfů, **nula sporů**). |
| `dumpending.py` | Odměří **koncovou sekvenci a druhý průchod** → `data/ending.json` (M7). Stojí na `playrzx.py`: záznam se přehraje těsně před sekvenci, uloží se `build/ending.z80` a od něj se krokuje – sekvence si hru řídí sama, takže je od spuštění deterministická. Konstanty scénáře se čtou **z kódu** (a u každé se kontroluje, že na adrese stojí očekávaná instrukce) a ověřují měřením. Vypadl z toho i **panel, jak ho sekvence nechá** (prázdné `ZONE`), obrázek hlášky `LASERTRON ACTIVATED` a všechny texty hry. |
| `dumpintro.py` | Odměří **intro, titulní obrazovku a attract mode** → `data/intro.json` (M7). Snímek po snímku počítá, kolik bajtů obrazu se změnilo, a z toho vypadnou hranice fází; titulní obrazovka se uloží jako obrázek **a zároveň se rozebere zpátky na znaky** sadou z `data/font.json`. Demo se změří v průchodech hlavní smyčky (40 na zónu, hodiny stojí) i s obrazovkou, kterou končí. |
| `traceending.py` | Zaznamená **koncovou sekvenci originálu** → `build/gtraces/`. Scénář se nepíše – píše si ho hra sama. Nahrává se dvakrát od téhož snapshotu: jednou po **hranicích částí** scénáře, jednou po **průchodech** hlavní smyčky, protože zastavit se dá vždycky jen na jedné adrese. Kus scénáře hlavní smyčkou neběží (rozpad lodi) a je to v záznamu vidět. Navíc se ukládá tabulka dat silnice před druhým průchodem a po něm. |
| `matchending.js` | Přehraje `app/highwayEnding.js` proti tomu záznamu: počítá se **jen to, co přidala M7** – scénář a druhý průchod – a kde Lasertron je, se bere ze záznamu (to je M5). Dnes **802 průchodů, nula rozdílů**; kamera dojede na zónu 36 jako v originálu a druhý průchod zrychlí přesně těch 65 záznamů tabulky silnice, které zrychlil originál. |
| `dumpsound.py` | Odměří **zvuk a barvu borderu** → `data/sounds.json` (M8). Najde v obrazu paměti všechny tři `OUT ($FE),A` (a tím dokáže, že hra **nemá hudbu**), přečte rozskok `$9AEF` a oba herní generátory (`$9B2C` šum, `$9B5B` tón) i ten z menu (`$B203`) a **napíše je po instrukcích v Pythonu**; pak je přehraje proti originálu v simulátoru a porovná **každé překlopení bitu 4 portu `$FE` na T-stav**, u šumu i semínko, které po efektu zůstalo. Dnes **120 spuštění, 3220 překlopení, nula rozdílů** a 2142 překlopení menu bez rozdílu. Vypadl z toho i **border** (černý, na 185 322 zápisech), počet tahů z generátoru náhody (zavírá §16) a **`POWER` jako zásobník výstřelů**. |
| `tracesound.py` | Zaznamená běh originálu se zaměřením na **žádanku zvuku** → `build/straces/`. Zastavuje se v každém průchodu na `$9AEF`, tedy v jediném místě, kde je bajt `$8F15` celý vidět, a ukládá k němu celou tabulku objektů, stav hráče, semínko a šest číslic skóre. `--report` z toho spočítá, co se v tabulce dělo v průchodech, které si o který zvuk řekly – tím se **pojmenují spouštěče**, které `dumpsound.py` umí najít v kódu, ale ne pojmenovat. |
| `matchsound.js` | Přehraje **žádanku zvuku** portu proti tomu záznamu a porovná **celou masku**, ne jen vítězný efekt. Počítá se jen to, co přidala M8 – který efekt si o sebe řekne zanikající záznam; bity výstřelu a nárazu jsou M3/M4 a hlásí se zvlášť, protože jejich rozdíly jsou §14, ne §18. Dnes **9 scénářů, 5900 průchodů, 7 rozdílů**, 7 scénářů sedí do posledního bitu. Kontroluje i **body**. |
| `dumpscore.py` | Odměří **bodování a živá pole panelu** → `data/score.json` (M8). Zavírá ZADANI §4: `$A414`, o které M7 psala jako o blikání barvy, je počítadlo bodů. Číslice se zapíšou do paměti, nechá je nakreslit originál a porovná se to s tabulkou glyfů (72 číslic, nula rozdílů); přičítání se změří tak, že se rutina pustí se známým `B`. Vypadl z toho i **`POWER`** (tři dílky, zásobník výstřelů, pravidlo ověřené na každém snímku) a **lampa doprovodu Lasertronu**. |
| `dumpattrs.py` | Odměří **atributy hrací plochy** → `data/attrs.json` (M8). Projede silnici demem a pro každou z 31 zón sejme atributy tolikrát, aby se poznalo, které buňky stojí (kulisa) a které se hýbou (kreslí se v nich). Ověřuje tím Crash 20: **13 010 ze 17 856** neprázdných buněk je bílá na černé a sloupcový profil barevných buněk je miska s vrcholy u obou krajů obrazovky. `FLASH` se nepoužívá, `BRIGHT` ano. |
| `matchpanel.py` | Panel **do posledního pixelu**: složí ho z `data/panel.json`, `data/panelfields.json` a `data/score.json` a porovná s tím, co má originál na obrazovce. Dnes **48 z 60 panelů sedí bajt po bajtu**, zbylých 12 se liší jen ve dvou buňkách – lampa doprovodu Lasertronu, jejíž pravidlo změřené není. |
| `tracedraw.py` | Najde v originálu **kreslicí rutinu** (M0/M2). Pustí hru v pythonovém simulátoru s podstrčenou pamětí, která loguje zápisy, a u každého zápisu do zvoleného rozsahu si zapíše, která instrukce ho udělala a co bylo na vrcholu zásobníku. Tím se zavřela §8, otevřená od M0: **do videopaměti hrací plochy zapisuje jediná instrukce v celé hře** (`$9ABC`), a odtud vypadl buffer na `$E900`, počítadla buněk na `$FD00`, pozadí na `$D905` i sprity samy. |
| `dumpsprites.py` | Vytáhne **sprity** → `data/spriteframes.json` (M2). 56 rámců po 144 B z `$B980`–`$D8FF`, 24 × 24 px, řádka = 3 B masky a 3 B obrázku, zdola nahoru, plus tabulka 128 ukazatelů z `$7A00`. `--sheet` uloží kontaktní list všech rámců do PNG, `--ascii N` je vypíše do terminálu – kontrola očima, že rámcování po 144 B sedí na celém bloku. |
| `dumpproj.py` | Odměří **projekci, řazení do hloubky a volbu spritu** → `data/projection.json` (M0b/M2). Adresu, kam se sprit kreslí, si záznam nese v `+3/+4`, takže se dá pro každý viditelný záznam dopředu spočítat a **porovnat s tím, co má hra v paměti**: řádek, sloupec, posun v buňce, fáze i klíč hloubky. Dnes **1217 průchodů, 31 zón, 8960 záznamů, nula rozdílů**. Vypadla z toho i animace každého druhu a to, že u řízeného Vortona je ten bajt `2 × směr`. |
| `dumphighway.py` | Vyjme **tabulku dat silnice** → `data/highway.json` (M2). 240 záznamů po 16 B z `$7B00`–`$89FF`, týž formát jako živá tabulka objektů (§12, §17) – obsah paměti, nic dopočítaného. Ověřuje si to ze čtyř stran: proti obrazu RAM běžící hry (3840 z 3840 B), formátem (`+11` = `22 × rodina` a `+13/+14/+15` = kopie `x`, `y` u všech 240), neměnností za běhu (0 změněných bajtů po 200 průchodech) a proti živé tabulce. **Z toho posledního vypadlo, jak vypadá načtený záznam**: živý je kopie svého vzoru v bajtech `+0`–`+13` a na `+14/+15` nese jeho adresu (`$7B00 + 16 × index`) – 12 z 12 nalezených. `--zone N` vypíše, co v zóně `N` podle `y` leží. |
| `dumpzones.py` | Odměří, **jak se zóna plní z tabulky dat silnice** → `data/zones.json` (M2). Rutinu našel `tracedraw.py` nad rozsahem živé tabulky (`LDIR` na `$93E3`) a tenhle nástroj z ní čte konstanty **z bajtů hry**: scan celé tabulky od `$7B00` v jejím pořadí, bere se záznam, jehož `(y − okno) & $FFFF` je pod 512, kopíruje se 14 bajtů od devátého místa živé tabulky, nejvýš 44 záznamů, za poslední značka `$FF`. K tomu dvě rutiny kolem: `$92CE` **ukládá živé záznamy zpátky** do tabulky (proto si silnice pamatuje, co jste strčili nebo zničili) a `$9400` uklidí zaniklé. Ověřeno demem přes celou silnici: **31 zón, 663 záznamů, nula rozdílů**. |
| `tracezones.py` | Zaznamená **přechody zón originálu** → `build/ztraces/`: stav před přechodem (tabulka dat silnice a živá tabulka) a stav po něm (tabulka po zápisu zpět a úklidu, a pořadí načtených záznamů podle ukazatele `+14/+15`). Přehrává `matchzones.js`. |
| `matchzones.js` | Přehraje `HighwayWorld.enterZone()` portu proti těm záznamům. Porovnává **tabulku dat silnice bajt po bajtu** (tím se ověří zápis zpět i úklid) a **pořadí načtených záznamů**. Dnes **30 přechodů, 7200 záznamů, 64 800 hodnot, nula rozdílů**. |
| `dumpgfx.py` | Sejme **obraz hrací plochy zónu po zóně** → `data/scenery.json` (M2). Čte v jediném okamžiku, kdy je plocha na obrazovce celá a ještě bez objektu: při přechodu do zóny, hned za `$97A6` (blok pozadí `$D905` → obrazovka) a `$97DD` (atributy). Demo si přes plochu píše `DEMO MODE`, ale ten je v bufferu, ne v bloku pozadí, takže do dat nezasahuje. `--png` uloží všech 31 zón k prohlédnutí. |
| `tracescreen.py` | Zaznamená **hrací plochu originálu** i stav, ze kterého vznikla → `build/vtraces/`. Zastavuje se na `$9AD8`, tedy hned za blitem bufferu na obrazovku, a ukládá bitmapu, atributy, celou tabulku objektů, kameru a animační bajty. Začíná se na hranici zóny – kdo se přidá uprostřed, nemůže vědět, které stojící objekty do ní originál nakreslil při vstupu. |
| `matchscreen.js` | Porovná **hrací plochu remaku s originálem pixel po pixelu, včetně atributů**. Ze záznamu jde jen tabulka objektů a kamera; co je vidět, v jakém pořadí se to kreslí a který rámec to má, si `app/screenComposer.js` počítá sám, takže se testuje i culling, řazení a animace. Dnes **rozehraná hra 120 průchodů, nula rozdílných pixelů**; demo 1200 průchodů přes všech 31 zón s rozdíly jen v nápisu `DEMO MODE` a v Zone Zero (grafika konce, otevřená od M7). |
| `dumpcadence.py` | Odměří **kadenci hlavní smyčky** → `data/cadence.json` (M9). Zavírá poslední otevřené místo §11: délka průchodu není konstanta ani rozdělení, je to **regulátor v kódu** – prázdná čekací smyčka na `$9AD8`, která se pustí, jen když se ten průchod kreslilo míň než osm záznamů, a čeká 2618 T za každou svou otáčku (`48 − 6 × kreslených` otáček). Konstanty se spočítají z instrukcí, jejich bajty se zkontrolují proti obrazu hry a délka se ověří měřením. Zbytek průchodu je práce (fit: T na kreslený a na živý záznam), zvuk (délky z M8, hraje se **synchronně uvnitř smyčky**) a příplatek za překreslení plochy. Dnes **6473 průchodů**, medián chyby 2,2 %. |
| `tracecadence.py` | Zaznamená **délku každého průchodu** originálu → `build/ktraces/`: T-stavy, počet kreslených a živých záznamů, žádanku o zvuk a to, jestli se překresluje plocha. 13 scénářů včetně celé demonstrace. |
| `matchcadence.js` | Přehraje `app/highwayCadence.js` proti těm záznamům. Jediný matcher projektu, kde se **nula rozdílů čekat nedá** a je to napsané rovnou: regulátor a zvuk jsou přesné, práce je fit. Měří se chyba – dnes **3764 průchodů, 99,6 % do půl snímku**, 93,4 % do čtvrt snímku. Přidat počet přenášených buněk by odchylku srazilo o pětinu, a to za vedení počítadel originálu v portu nestojí. |
| `dumpflight.py` | Vytáhne z `sources/tape/highway.rzx` **scénář zkušebního letu** pro `testFlightPage.php` (M9): co si hra přečetla z klávesnice (`$8F14`) v každém snímku záznamu skutečného hráče, běhově kódované. Demonstrace originálu se na to nehodí – změřeno, že v ní `$8F14` zůstane celou dobu na `$14`, attract mode si Vortona vede sám. |
| `renderframe.js` | Vykreslí snímek remaku do PNG **bez prohlížeče**: pustí `app/gameWorker.js` a `app/screenComposer.js` v node. Kontrola, že se celý řetěz složí a že sedí geometrie. `--keys accelerate,right` k tomu drží ovládání, takže se dá vykreslit i jízda a přechod zóny. |

## Co přijde

Podle `../MILNIKY.md`:

- **M0** – vlastní disassembly. ~~`playrzx.py`~~ a ~~`mkfont.py`~~ jsou hotové
  (M7: `playrzx.py`, `dumpfont.py`).
- ~~**M2**~~ – **hotová**: `dumpsprites.py`, `dumpproj.py`, `dumpgfx.py`,
  `matchscreen` (§8; rozhodl `tracedraw.py`) a **obsah zón** –
  `dumphighway.py` vyjmul tabulku dat silnice a `dumpzones.py` změřil
  pravidlo, kterým se z ní zóna plní (`matchzones.js`: nula rozdílů).
- ~~**M8** – `dumpsound.py`~~ – **hotové**: `dumpsound.py`, `tracesound.py`,
  `matchsound.js`, `dumpscore.py`, `dumpattrs.py` a `matchpanel.py`. Zvuk
  výbuchu tahá z generátoru **jednou za segment** (§16 zavřená); kolikrát tahá
  **kreslení** (`$AAE4`), zůstává otevřené a je to M2.
- **M8/M2** – grafika konce hry a intra: rozpad lodi, zóny za Zone Zero a
  izometrický nápis intra. Změřený je scénář a časování, ne pixely.
- ~~**M9** – kadence hlavní smyčky~~ – **hotové**: `dumpcadence.py`,
  `tracecadence.py`, `matchcadence.js` a `dumpflight.py`. Kadence je
  **regulátor v kódu originálu** (§19), ne konstanta.

Hotové dvojice `dump*` / `trace*` / `match*`: M3 (`dumpphysics.py`,
`tracephysics.py`, `matchphysics.js`, nula rozdílů), M4 (`dumpobjects.py`,
`traceobjects.py`, `matchobjects.js`, 68 zbylých rozdílů, §14), M5
(`dumpconvoy.py`, `dumppanelfields.py`, `traceconvoy.py`, `matchconvoy.js`,
jeden otevřený jev, §15) M6 (`dumpenemies.py`, `traceenemies.py`,
`matchenemies.js`, nula rozdílů, §16) a M7 (`dumpending.py`, `traceending.py`,
`matchending.js`, nula rozdílů, §17). M9 (`dumpcadence.py`,
`tracecadence.py`, `matchcadence.js`) měří místo rozdílů odchylku, protože
jedna ze tří částí modelu je fit – a je to tam napsané.
