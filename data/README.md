# data/ – co si remake nese z originálu

Každý soubor tady **vyrobil nástroj z `tools/`** z originální kazety nebo z běžící hry.
Nic se nepíše ručně a nic se nedokresluje: co se z originálu vytáhnout nedá, je otevřená
otázka v `../ZADANI.md` §7, ne odhad v datech.

Soubory se posílají do prohlížeče najednou při startu aplikace (`db/appData.php`)
a ukládají se do `localStorage` pod `he.<jméno>`. Výjimka je `attrs.json`: je
změřený, ale do prohlížeče se zatím neposílá, protože obarvit se s ním dá až
bitmapa zóny, a ta je M2 – posílat ho dřív by znamenalo nést 55 kB, které nemá
co obarvit.

| soubor | odkud | čím |
|---|---|---|
| `loading.json` | loading screen z originální kazety (6912 B `.scr`, ověřený bajt po bajtu proti bloku, který kazeta nahraje do videopaměti) | `tools/mkscreen.py` |
| `panel.json` | panel dole na obrazovce **běžící hry** – bitmapa 256 × 40 a atributy; hra si ho drží jako hotový obrázek na `$6000` | `tools/dumppanel.py` |
| `global.json` | jen změřené hodnoty: snímková frekvence, geometrie obrazovky, rozsah zón a počet Vortonů, plus seznam otevřených otázek | ručně z `sources/docs/screen_layout.md` |
| `menu.json` | zatím prázdné | – |
| `physics.json` | fyzika řízeného Vortona **odměřená na běžící hře**: osm směrů, tři rychlosti, časovač plynu, otáčení, okraje silnice, chování při nárazu, startovní pozice a délka jednoho průchodu hlavní smyčkou | `tools/dumpphysics.py` |
| `objects.json` | **pravidla silnice** odměřená na běžící hře: srážková krabice, druhy objektů a co z nich se dá strkat, co strčení udělá a jak dojíždí, kde vzniká a jak daleko doletí výstřel, a jak dlouhá je zóna (tedy kdy skočí kamera) | `tools/dumpobjects.py` |
| `convoy.json` | **konvoj** odměřený na běžící hře: sestava na startu, to, že nezatáčí ani nezrychluje a Lasertron netlačí, srážková krabice čtená v pořadí tabulky, co znamená bajt rychlosti, že konvoj nestrká, šířka průjezdu středem a co se stane, když je řízený Vorton zničen | `tools/dumpconvoy.py` |
| `enemies.json` | **nepřátelé a matice srážek** odměřené na běžící hře: jedenáct rodin objektů a čtyři rodiny nepřátel, tabulka kroku, matice srážek 11 × 11 (kdo do koho narazil rozhoduje o všem), masky směru, generátor náhody hry, animace zániku, hodiny `TIME` a sečtené rozmístění po zónách | `tools/dumpenemies.py` |
| `panelfields.json` | **živá pole panelu** sejmutá z běžící hry: obrázek pole `ZONE` pro každou z 31 hodnot a ikony řady `1 2 3 4 5` ve stavu „řídím ho" a „čeká". Číslice se nesázejí, fotí se – velké segmentové písmo pole `ZONE` není znaková sada hry, je to samostatná grafika | `tools/dumppanelfields.py` |
| `font.json` | **znaková sada hry** – 64 glyfů po pěti bajtech od `$5B00`, skladba buňky (`00`, `$7F`, glyf, `$7F`), barvy z bitů 6 a 7 kódu a mapa glyf → písmeno, ověřená rozebráním obrazovek originálu zpátky na znaky (36 glyfů, nula sporů) | `tools/dumpfont.py` |
| `ending.json` | **koncová sekvence a druhý průchod**: kdy se spustí (Lasertron na 5484), scénář bod po bodu s počty průchodů čtenými z kódu, panel tak, jak ho sekvence nechá, obrázek hlášky `LASERTRON ACTIVATED`, všechny texty hry a pravidlo druhého průchodu (rychlost o 1 výš rodinám pod 5) | `tools/dumpending.py` |
| `sounds.json` | **zvuk** originálu, přečtený z jeho rutin a ověřený měřením: pět efektů hry (bity žádanky `$8F15`), dva generátory (`$9B2C` šum, `$9B5B` tón) a třetí v menu (`$B203`), jejich parametry i časování na T-stav, kolik tahů z generátoru náhody spotřebuje šum, kde si hra o který efekt řekne, **že hudba není** a **že border je černý** | `tools/dumpsound.py` |
| `score.json` | **bodování a živá pole panelu**: šest číslic `SCORE` na `$A481` s vlastním pětibajtovým písmem na `$A490` (sedmá číslice je nakreslená v panelu, takže je skóre vždycky násobek deseti), čtyři místa, kde se přičítá (`+10`, `+250`, `+1000`), pravidlo `HIGH`, tři dílky `POWER` (zásobník výstřelů) a lampa doprovodu Lasertronu | `tools/dumpscore.py` |
| `attrs.json` | **atributy hrací plochy** zónu po zóně, sejmuté z režimu `6 DEMONSTRATION`: co v zóně stojí, maska buněk, které se během ní hýbaly, a sečtený přehled – 13 010 z 17 856 neprázdných buněk je bílá na černé a barva sedí u obou krajů obrazovky, přesně jak psal Crash 20 | `tools/dumpattrs.py` |
| `spriteframes.json` | **sprity originálu**: souvislý blok 56 rámců po 144 B z `$B980`–`$D8FF`, každý 24 × 24 px po pixelových řádkách zdola nahoru (3 B masky přes `AND`, 3 B obrázku přes `OR`), a k nim tabulka 128 ukazatelů z `$7A00`, kterou si hra rámec vybírá. Nic se nedokresluje – je to obsah paměti | `tools/dumpsprites.py` |
| `projection.json` | **izometrická projekce, řazení do hloubky a volba spritu**, odměřené na běžícím originálu a ověřené proti tomu, co má hra sama v paměti: řádek, sloupec i posun v buňce, klíč hloubky a pořadí kreslení, animační bajt každého druhu a druh výstřelu podle hlavně. Nula rozdílů na 1217 průchodech, 31 zónách a 8960 záznamech | `tools/dumpproj.py` |
| `scenery.json` | **obraz hrací plochy zónu po zóně** (31 zón, bitmapa 19 znakových řádek + 608 atributů), sejmutý v okamžiku přechodu do zóny, kdy je na obrazovce celý a ještě bez jediného objektu. K tomu tabulka pásů: který parallelogram originál z bufferu vůbec kopíruje – jen v něm se objeví objekty | `tools/dumpgfx.py` |
| `cadence.json` | **kadence hlavní smyčky**: regulátor na `$9AD8`, kterým si originál dopolstruje průchod s méně než osmi kreslenými záznamy (2618 T na otáčku, spočítané z instrukcí), model práce průchodu (T na kreslený a na živý záznam), délky zvukových efektů z `sounds.json` a příplatek za překreslení plochy. 6473 změřených průchodů, 99,6 % modelovaných do půl snímku | `tools/dumpcadence.py` |
| `highway.json` | **tabulka dat silnice**: 240 záznamů po 16 bajtech z `$7B00`–`$89FF`, ze kterých hra plní zóny – pozice `x`, `y`, druh, rodina, směr, rychlost a sprit každého objektu na celé silnici, plus celý blok v base64. Je to obsah paměti, ověřený proti obrazu RAM běžící hry a proti živé tabulce; **jak se z něj zóna načte, tady není** – to je `zones.json` | `tools/dumphighway.py` |
| `zones.json` | **jak se zóna plní z tabulky dat silnice**: pořadí a pravidlo scanu, pás `(y − okno) < 512`, 14 kopírovaných bajtů, strop 44 záznamů na zónu a devátý slot jako začátek, plus dvě rutiny kolem – zápis živých záznamů zpátky do tabulky (silnice si pamatuje, co jste strčili a zničili) a úklid zaniklých. Konstanty jsou přečtené z bajtů rutiny, pravidlo ověřené na celé silnici | `tools/dumpzones.py` |
| `intro.json` | **intro, titulní obrazovka a attract mode**: časy fází intra po snímcích, titulní obrazovka jako obrázek i rozebraná na text, blikající oddělovač u vybrané volby a to, jak se chová `6 DEMONSTRATION` (40 průchodů na zónu, stojící hodiny, závěrečná obrazovka) | `tools/dumpintro.py` |

## Co tu ještě není

Podle `../MILNIKY.md`. Dokud data nejsou, remake to nekreslí – ani „zhruba":

- ~~`font.json`~~ – **našla se v M7** (§2). Číslice `SCORE` a `HIGH` se s ní
  ale nesázejí: M8 našla, že skóre má **vlastní pětibajtové písmo** na `$A490`
  (`score.json`), a s ním se zavřelo i to, **kde se skóre počítá** (ZADANI §4).
- ~~`spriteframes.json`~~ – **hotové**: sprity se našly tím, že `tools/tracedraw.py`
  přestal hledat bajty a našel **kreslicí rutinu** (`sources/docs/disasm_notes.md` §8).
- ~~`scenery.json`, `projection.json`~~ – **hotové v M2**; hrací plocha se z nich
  složí do posledního pixelu (`tools/matchscreen.js`).
- ~~`highway.json`~~ – **hotové**: tabulka dat silnice je vyjmutá
  (`tools/dumphighway.py`, 240 záznamů z `$7B00`–`$89FF`), takže **kde na
  silnici co stojí, se ví**. Vypadlo z toho i to, jak vypadá načtený záznam:
  živý záznam v `$8A00` je **kopie** svého vzoru v bajtech `+0`–`+13` a na
  `+14/+15` nese jeho adresu – tím se zavřela „pevná dvojice (x, y)", kterou
  `disasm_notes.md` §12 nechala otevřenou.
- ~~`zones.json`~~ – **hotové**: pravidlo, kterým si hra zónu z tabulky plní,
  je změřené z její vlastní rutiny (`tools/dumpzones.py`) a ověřené jak proti
  originálu (31 zón, 663 záznamů, nula rozdílů), tak proti portu
  (`tools/matchzones.js`: 30 přechodů, nula rozdílů). Tím **M2 nemá otevřený
  obsah zón** a na silnici stojí, co v originálu.
- ~~`sounds.json`~~ – **hotové v M8**, a s ním i poslední otevřená věc M6:
  zvuk výbuchu tahá z generátoru náhody **právě jednou za segment**, tedy 8, 9
  nebo 12 tahů podle druhu (`sources/docs/disasm_notes.md` §18). Kolikrát tahá
  **kreslení** (`$AAE4`), otevřené zůstává – to je M2.
- grafika konce hry a intra (M8/M2): rozpad lodi, zóny za Zone Zero a
  izometrický nápis intra. Změřený je scénář a časování (`ending.json`,
  `intro.json`), ne pixely – ty stojí na spritech, a ty jsou M2.
