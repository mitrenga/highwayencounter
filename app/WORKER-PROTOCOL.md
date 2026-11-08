# Protokol mezi `highwayModel.js` a `gameWorker.js`

Worker drží herní stav a tiká na **50,08 Hz** – snímkové frekvenci originálu
(3,5 MHz / 69 888 T-stavů na snímek, viz `sources/docs/hw_notes.md` a ZADANI §1).
Model do něj jen posílá vstupy a kreslí to, co dostane zpátky. Kreslí se
v hlavním vlákně, počítá ve workeru – totéž rozdělení jako v Underwurlde.

### Tik není krok

V M1 tady stálo, že jeden tik je jeden krok hlavní smyčky originálu. **Změřeno
v M3, že to není pravda**: hlavní smyčka na přerušení z ULA nevisí, jeden
průchod trvá 1,4 až 13 snímků (medián 2,41) a délka se mění podle toho, kolik je
co kreslit (`sources/docs/disasm_notes.md` §11). Stav hry se mění jednou za
průchod, ne jednou za snímek.

Worker proto tiká dál na snímky, ale **krok hry** trvá tolik tiků, kolik ten
konkrétní průchod trvá originálu – a to je od M9 změřené pravidlo, ne průměr.
Po každém kroku se worker zeptá `app/highwayCadence.js` (`data/cadence.json`,
`tools/dumpcadence.py`), jak dlouho ten průchod trval: podle toho, kolik
záznamů se kreslilo, kolik jich je na silnici živých, jaký zvuk se hraje a
jestli se překresluje celá plocha. Za tím vším stojí **regulátor v kódu
originálu** – prázdná čekací smyčka na `$9AD8`, která průchod s méně než osmi
kreslenými záznamy dopolstruje 2618 T-stavy za každou svou otáčku. Bez
`data/cadence.json` worker krokuje po staru, na `stepLength.framesPerStepMean`
z `data/physics.json`.

**Stav M7: hra má i konec** – když Lasertron dojede na konec silnice, převezme
worker scénář koncové sekvence, odehraje ho na snímek přesně jako originál
a začne novou, tvrdší hru. Chybí pořád obsah zón (M2), aby bylo koho a kde
potkat – a nic si nevymýšlí. Co přijde:

| milník | co do workeru přibude |
|---|---|
| ~~M3~~ | ~~fyzika řízeného Vortona~~ – **hotovo**: `app/vortonPhysics.js`, konstanty z `data/physics.json`, ověřeno `tools/matchphysics.js` (10 260 kroků, nula rozdílů) |
| ~~M4~~ | ~~silnice, předměty a strkání~~ – **hotovo**: `app/highwayObjects.js`, `data/objects.json`, `tools/matchobjects.js` (7862 kroků, 68 rozdílů) |
| ~~M5~~ | ~~konvoj: čtyři automatické Vortony a Lasertron, simulované **i mimo obraz**~~ – **hotovo**: `app/highwayConvoy.js`, `data/convoy.json`, `tools/matchconvoy.js` |
| ~~M6~~ | ~~nepřátelé, střelba po trojicích, časový limit~~ – **hotovo**: `app/highwayEnemies.js`, `data/enemies.json`, `tools/matchenemies.js` (17 124 průchodů nepřátel, nula rozdílů). Zbývá **bodování**, které se v originálu průběžně nepřičítá a nenašlo se, kde se počítá (`disasm_notes.md` §16) |
| ~~M7~~ | ~~koncová sekvence v Zone Zero, druhý průchod, intro~~ – **hotovo**: `app/highwayEnding.js`, `data/ending.json`, `data/font.json`, `data/intro.json`, `tools/matchending.js` (802 průchodů, nula rozdílů) |
| ~~M9~~ | ~~kadence hlavní smyčky~~ – **hotovo**: `app/highwayCadence.js`, `data/cadence.json`, `tools/matchcadence.js` (3764 průchodů, 99,6 % do půl snímku) |

Každý z nich se ověřuje stejně jako u sourozeneckých projektů: přehrát port
proti nahranému běhu originálu s **nulou rozdílů** (`tools/match*.js`), a u téhle
hry navíc proti RZX záznamu kompletního dohrání (`sources/tape/highway.rzx`).

**Svět není mřížka místností.** Silnice je jeden souvislý pás od `ZONE 30`
k `Zone Zero` a hra ho simuluje celý, i to, co zrovna není na obrazovce
(ZADANI §3.3) – stav ve workeru je proto stav silnice, ne viditelného výřezu.
Jestli se obraz roluje plynule, nebo skáče po zónách, je otevřená otázka M0b
a rozhodne o tom, co bude worker o kameře posílat.

## Model → worker

| zpráva | pole | význam |
|---|---|---|
| `init` | `initData: {headless, zone, vortons, physics, objects, convoy, enemies, ending, sounds, score, projection, cadence}` | start nové hry. `physics` je `data/physics.json`, `objects` `data/objects.json`; bez nich worker odpoví `error`. `convoy` je `data/convoy.json` – s ním worker konvoj postaví a simuluje, bez něj jede silnice bez něj (M5 se nedokresluje). `enemies` je `data/enemies.json` – s ním se simulují nepřátelé, animace zániku a hodiny hry (M6). `ending` je `data/ending.json` – s ním hra **má konec**: koncová sekvence i druhý průchod (M7); bez něj jede silnice donekonečna. `cadence` je `data/cadence.json` – s ní worker krokuje v kadenci originálu (M9), bez ní na naměřený průměr. `headless: true` tiká jen na vyžádání zprávou `tick` (pro testy). |
| `controls` | `left`, `right`, `accelerate`, `decelerate`, `fire` (boolean) | úplný stav ovládání; posílá se při každé změně. |
| `pause` | – | zastaví tikání. |
| `continue` | – | pokračuje. |
| `tick` | – | jeden krok v režimu `headless`. |
| `reset` | – | zahodí stav (volá se při opuštění herní obrazovky). |

### Ovládání není osmisměrný joystick

`left`/`right` Vortonem **otáčí** (originál `O` a `P`), `accelerate`/`decelerate`
**přidává a ubírá plyn** (`1` a `Q`). Změřené je i to, co dělají stisknuté
naráz: dvě otáčky se ruší, u plynu **vyhraje brzda**. Stav řízeného Vortona je proto
**(pozice, směr 0–7, rychlost)** a pohyb má setrvačnost – změřeno, že hra sama
nezpomaluje **vůbec**: rychlost se drží, dokud ji nesebere `Q` nebo náraz
(`disasm_notes.md` §13). Crash 20: „it takes some time to accelerate to full
speed and seemingly even longer to come to a halt" (ZADANI §3.6). `H` (HOLD) a `A` (ABORT GAME) originálu se v remaku
mapují na pauzu, takže se do workeru neposílají.

## Worker → model

| zpráva | pole | význam |
|---|---|---|
| `frame` | `frame`, `score`, `high`, `zone`, `vortons`, `vortonMarks`, `power`, `time`, `vorton`, `objects`, `ending`, `passCount`, `sounds`, `state` | jeden odtikaný krok. |
| `gameOver` | `score` | konec hry; model přepne na `GameOverModel`. |
| `error` | `message` | chybí data. |

### `vorton` a konvoj

`vorton` je `{x, y, dir, speed, phase, cls, kind}` řízeného Vortona – `dir` je jeden z osmi
směrů (SU 41: „everything moves faster and in a true eight directions"),
`speed` je 0–2 a `phase` fáze animace 0–15. Souřadnice je **světová souřadnice
silnice**: zóna je 176 dlouhá a při rychlosti 1 se `y` mění o 2 na krok
(`disasm_notes.md` §12 a §14). `cls` je slovo druhu (u řízeného Vortona `0`)
a `kind` bajt druhu `$0E` – **podle něj renderer vybírá jeho osm natočení**
(`data/projection.json` `sprite.controlledVorton`), takže bez nich by se kreslil
pořád jedním směrem. Při předání řízení je dostane ten automatický Vorton,
který řízení převzal (změřeno, `build/ctraces/handover*.json`).

Konvoj **vlastní pole nemá**: od M5 je ve `objects` jako všechno ostatní, ve
slotech 1–5 tabulky originálu, protože tam ho drží i originál. Čtyři automatické
Vortony jsou druh `$1070`, Lasertron `$0910` (`disasm_notes.md` §15). Simulují
se pořád, ať jsou vidět, nebo ne – silnice je jeden souvislý svět, ne mřížka
místností.

**Řízený Vorton nemusí zůstat ve slotu 0.** Když ho něco zničí, jeho záznam
z tabulky zmizí a druh `0` dostane **nejnižší automatický Vorton, který ještě
žije** – hráč tedy nezačíná znovu, přebírá konvoj zevnitř a je o jednoho Vortona
kratší. Změřeno v `tools/dumpconvoy.py`.

### `objects`

Od M4 posílá worker i **celou tabulku silnice** – 24 slotů v pořadí originálu,
`null` tam, kde je prázdno, jinak `{x, y, dir, speed, phase, cls, kind}`. `cls`
je druh objektu ze slova `+5/+6` záznamu (`disasm_notes.md` §14): `0` řízený
Vorton, `$0118` výstřel, `$1A68` předmět, který se dá strkat, `$19F0` a spol.
předmět nepohnutelný. Kreslit se z toho zatím nedá nic – sprity ani projekce
nejsou změřené (M2) – ale simuluje se to celé, i to, co zrovna není vidět.

### `power` a `time`

Obojí je na panelu **sloupcový ukazatel** (Crash 20 o čase: „amount of time
remaining is shown by a bar graph"). Co přesně měří `POWER` – dobíjení laseru po
trojici výstřelů, nebo energii Vortona – je otevřená otázka (ZADANI §3.7), takže
`power` je pořád 1 a panel ho kreslí plný.

`time` je od M6 **změřený**: originál ubere z 16bitového počítadla 1 každý
průchod hlavní smyčky, na nule sundá ukazateli jeden ze tří dílků a nabije se na
3500 (`disasm_notes.md` §16). Celá hra má tedy 10 500 průchodů, asi 8,5 minuty.
Worker posílá `time` jako **zbytek 0–1** (dílky plus rozehraný dílek) a když
dojde, hlásí `gameOver`. Kolik dílků panel doopravdy nakreslí, se rozhodne až
na pixelech (M8) – ukazatel je v originálu ukazatel do videopaměti.

### `vortons`, `vortonMarks` a `zone`

`zone` je číslo zóny, jak ho ukazuje panel (30 → 0), tedy `31 −` počítadlo
originálu (`disasm_notes.md` §7).

`vortonMarks` je pět booleanů: **které z pěti ikon na panelu jsou vyplněné**.
M5 změřila, že řada `1 2 3 4 5` neukazuje, kolik Vortonů zbývá – zánik
automatického Vortona na panelu nezmění nic. Ikona se vyplní u toho Vortona,
kterého hráč začne řídit, a **zůstane vyplněná i potom**, takže řada ukazuje,
kolikátého v pořadí už hráč spotřeboval (`tools/dumppanelfields.py`,
`disasm_notes.md` §15). `vortons` je pořád jen počet z `data/global.json`; panel
ho nekreslí.

### `ending` a `passCount`

`ending` je `null`, dokud hra běží normálně. Když **Lasertron dojede na konec
silnice** (`y` v okně od 5484 a počítadlo zón aspoň 30), převezme worker
scénář koncové sekvence a od té chvíle posílá, co má renderer ukázat:

| pole | význam |
|---|---|
| `phase` | jak se ta část scénáře jmenuje (`salute`, `lasertronRuns`, `explosion`, `shipBreakup`, `finale`…) |
| `panelMessage` | v panelu je hláška `LASERTRON ACTIVATED` (obrázek z `data/ending.json`, ne text) |
| `panelBlank` | panel je ten, který sekvence po sobě nechá: **prázdné pole `ZONE`** a smazaná řada Vortonů |
| `attribute` | atribut, kterým je zaplavená celá hrací plocha (`$47` při rozpadu lodi, pak `$07`) |
| `text` | řádky textu k vysázení znakovou sadou hry – `PREPARE YOURSELF FOR THE NEXT HIGHWAY ENCOUNTER!` |
| `breakup` | běží rozpad lodi. **Nekreslí se** – je to grafika, a ta je M8 |
| `zone` | kam dojela kamera; sekvence ji vede až na zónu 36, tedy pět zón za Zone Zero |

Sekvence **není animace na čase**: originál si do `$8F14` zapisuje, co se ten
průchod „zmáčklo", a nechává si odběhnout přesné počty **průchodů hlavní
smyčky**. Worker to dělá stejně, takže sekvence trvá 2081 snímků jako v
originálu. Dvě její části (rozpad lodi a prodleva po něm) hlavní smyčku
neběží vůbec a měří se ve snímcích – ty se tikají v `tick()`, ne v `step()`.

`passCount` je počítadlo dohraných her (`$8F89` originálu, strop 2). Když
sekvence skončí, worker začne novou hru a **přičte 1 k rychlosti** každému
záznamu, jehož rodina je pod 5 – rychlejší nepřátelé, a miny ne. To je celý
„druhý průchod".

### `sounds`

Co si průchody v tomhle snímku vyžádaly: seznam `{name, seed}`, kde `name` je
jméno efektu z `data/sounds.json` (`fire`, `destroy`, `blast`, `crash`, `bump`)
a `seed` je stav generátoru náhody v okamžiku, kdy efekt začal – šum si z něj
tahá výšku i délku, takže bez semínka nezní stejně jako v originálu.

Originál hraje **nejvýš jeden efekt za průchod** hlavní smyčky a hraje ho
**synchronně**: smyčka na něj čeká. Jeden snímek workeru může být víc průchodů,
takže `AudioManager.playFrame()` pouští jen ten poslední – kdyby se hromadily,
šel by beeper za hrou pozadu, a to originál nikdy nedělá.

Že hra nemá hudbu, je změřené, ne předpokládané: v celém obrazu 48 K jsou tři
instrukce `OUT ($FE),A` a všechny leží uvnitř zvukových rutin
(`tools/dumpsound.py`).
