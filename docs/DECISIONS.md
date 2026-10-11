# Rejestr decyzji

Format: data · kontekst · wybór · alternatywy.

## 2026-10-11 · Etap 0a

- **Przed Etapem 0 dodany Etap 0a.** Kontekst: Etap 0 wymaga kont (GEE, R2, EUMETSAT) i hostingu, zanim wiadomo, czy ranking ma sens. Wybór: lokalny test na stacjach IMGW i Open-Meteo, bez kont. Alternatywa: od razu Etap 0 wg §13.
- **Previous Runs API zamiast Historical Forecast API.** Kontekst: Historical Forecast skleja pierwsze godziny przebiegów, więc nie ma wyprzedzeń 24–72 h. Wybór: `*_previous_dayN`. Alternatywa: Single Runs API (pełne przebiegi, dużo więcej zapytań).
- **Lista modeli:** `ecmwf_ifs025, ecmwf_aifs025_single, icon_seamless, gfs_seamless, meteofrance_seamless`. Kontekst: `icon_d2` nie obejmuje wschodniej Polski, a `meteofrance_arome_france_hd` obejmuje tylko okolice Szczecina (sprawdzone zapytaniami, próbki w `docs/api-samples/`). Alternatywa: modele regionalne tylko w komórkach, które pokrywają. Odrzucone, bo ranking na różnych zbiorach modeli w różnych komórkach jest nieporównywalny.
- **Okno opadu IMGW:** `SMDB` dnia D = 06 UTC D → 06 UTC D+1. Wyznaczone empirycznie: korelacja 0,66 przy tym oknie, 0,10 przy oknie przesuniętym o dobę.
- **Usłonecznienie wyłączone z rankingu.** Kontekst: bias +2…+4 h/dobę u wszystkich modeli, a MAE ≈ bias, więc zmienna mierzy definicję, nie trafność. Wybór: nie używać jako zastępstwa zachmurzenia; w metrykach zachmurzenia stosować miary odporne na bias (§8.3).
- **Dalszy kierunek produktu:** rozstrzygnięty niżej.

## 2026-10-11 · Decyzja człowieka i Etap 0b

- **„Najbardziej trafna” = średnia modeli ważona trafnością** (decyzja człowieka, wariant a z §17). Alternatywy: jeden zwycięzca z dłuższego okna (b), bez zmian (c). Test w Etapie 0b: wybór jednego zwycięzcy był gorszy od średniej o 10–15 % prawie wszędzie.
- **Wagi:** 1/MSE z 30 dni tylko dla temperatury, osobno dla grup wyprzedzeń; równe wagi dla opadu, zachmurzenia i wiatru. Kontekst: ważenie dało ok. 5 % w Tmin, a w opadzie nic. Alternatywa: wagi dla wszystkich zmiennych (ryzyko nadmiernego dopasowania przy szumie bez zysku).
- **Wagi lokalne zamiast regionalnych (≤ 150 km)** na stacjach. Na siatce z obserwacjami satelitarnymi do ponownej oceny w Etapie 3.
- **`ecmwf_ifs` (HRES 9 km) dodany do modeli.** Lepszy od IFS 0,25° na 1.–3. dzień.
- **Dni 5–7 jako „mniej pewne”, opad jako szansa w %, podsumowanie „Ten tydzień”** (decyzje domyślne agenta, do weta człowieka). Kontekst: od 5. dnia prognoza ilości opadu wypada gorzej niż klimatologia, a prognoza tygodnia jako całości jest trafniejsza od pojedynczych dni pod jego koniec.
- **Siatka 0,1° z pobieraniem rotacyjnym 14-dniowym** (decyzja człowieka, §17 pkt 2). Alternatywa: 0,25° bez problemów z limitem.
- **Obszary, ranking burzowy i „Chmury teraz” przeniesione do v1.1** (decyzja człowieka, §17 pkt 4). Warunek: składniki metryk w Parquet od MVP.
- **`ecmwf_ifs025` usunięty.** Kontekst: to ten sam IFS co `ecmwf_ifs` (korelacja błędów 0,90–0,94, dla innych par 0,6–0,8). Średnia bez niego jest równa lub lepsza, a budżet API mniejszy o 1/6. Alternatywa: zostawić z wagą połówkową dla „rodziny ECMWF IFS”.
- **Modele krótsze niż 7 dni:** jest tylko Météo-France (103 h, Forecast API sprawdzony 2026-10-11). W średniej wagi się renormalizują, w trybach jednomodelowych prognoza jest obcięta z adnotacją.
- **„Optymistyczna” liczona w locie** zamiast crona. Kontekst: cron dla 6 300 komórek × 5 modeli co 6 h ≈ 126 tys. wywołań na dobę. Widok 2 i tak pobiera wszystkie modele do średniej.
- **Open-Meteo ma limit godzinowy 5 000 ważonych wywołań.** Przekroczony w Etapie 0b, więc potok potrzebuje dławika (§7.3).

## 2026-10-11 · Etap 0, część GEE (`docs/reports/etap-0-gee.md`)

- **Zachmurzenie z MODIS Terra i Aqua, nie z Meteosatu.** Kontekst: Meteosatu nie ma w katalogu GEE (sprawdzone 1 162 zbiory). VIIRS ma ~7 dni opóźnienia i inną maskę chmur. Alternatywa: EUMETSAT Data Store poza GEE (v1.1).
- **Chmury weryfikowane dla D-4, opady dla D-2.** Kontekst: opóźnienie MODIS w GEE ~3 dni, IMERG ~21 h.
- **Weryfikacja tylko komórek z `pl_frac > 0`** (4 324 z 6 283). Kontekst: o 31 % mniej wywołań Open-Meteo.
- **IMERG zostaje sędzią opadu.** Jesienią ETS 0,58 wobec deszczomierzy IMGW, czyli lepiej niż najlepsza prognoza. Zimą do ponownego sprawdzenia.
- **Granice Polski: `USDOS/LSIB_SIMPLE/2017`** w GEE (precyzyjnie: `pipeline/grid/build_cells.py`, maska 100 m, ułamki < 0,001 zerowane). Wynik: 4 313 komórek z `pl_frac > 0`, łączne pole Polski 310 718 km², o 0,6 % mniej niż według GUS (312 696 km²) przez uproszczone granice. Wcześniejsze 4 324 z testu GEE pochodziło z maski 1 km. Wystarczy do flagi `pl_frac`; do obszarów v1.1 zostaje OSM/PRG wg §15.

## 2026-10-11 · Pakiet `lepszapogoda/` i siatka

- **`grid.py` jest jedynym modułem, który zna kształt komórki** (§0 pkt 12). API: `cell_id_for`, `get_cell`, `all_cells`, `poland_cells`, `neighbours`, `pl_frac`, `GRID_VERSION`.
- **Punkt na krawędzi należy do komórki na północ/wschód** (krawędź dolna i lewa są włączne). Punkt na północnej lub wschodniej krawędzi bboxa (55,0°N, 24,2°E) jest poza siatką i dostaje `None`. Siatka obejmuje [48,9; 55,0) × [13,9; 24,2).
- **`pl_frac` w pakiecie jako JSON** (`lepszapogoda/data/poland_cells.json`), a nie tylko w Parquet. Kontekst: hosting może nie mieć pyarrow (§14). Pełna tabela komórek jest w `pipeline/grid/poland_cells.parquet`, a test pilnuje zgodności obu plików.
- **Klient Open-Meteo z własnym budżetem** (`lepszapogoda/openmeteo.py`). Rejestr wywołań ważonych, kroczące okna minuta/godzina/doba/miesiąc, potok używa 80 % limitów. Okno kroczące nigdy nie jest łagodniejsze od kalendarzowego, więc jest bezpieczne niezależnie od tego, jak liczy Open-Meteo.
- **Zapytania wielopunktowe liczone jako 1 wywołanie na punkt**, także odrzucone (400). Ostrożnie, bo dokumentacja tego nie precyzuje.
- **Prognozy dla użytkownika z korektą wysokości Open-Meteo i `cell_selection=land`.** Weryfikacja: `elevation=nan` i `nearest` (SPEC §7.3). Kontekst: użytkownik chce temperatury w swoim punkcie, a weryfikacja potrzebuje surowej komórki modelu. Alternatywa: wszędzie `nan` (gorsze prognozy w górach).
- **Pobieranie z manifestem i uzupełnianiem luk zamiast sztywnej rotacji.** Komórka jest pobierana, gdy luka ≥ 14 dni albo gdy jest jej dzień rotacji (hash `cell_id` mod 14). Ta sama reguła robi rozruch, rotację i nadrabianie po awarii. W manifeście są tylko daty, które naprawdę przyszły z danymi.
- **Format prognoz archiwalnych:** wiersz = (komórka, godzina, `lead_day`) z kolumnami zmiennych, `float32`, plus metadane komórki modelu. SPEC §8.8 mówił `lead_h` i `init_time`; Previous Runs API daje stałe wyprzedzenia dobowe, więc `lead_day`, a `init_time` ≈ `valid_time − lead_day × 24 h`.
- **API wymaga `elevation` powtórzonego dla każdej współrzędnej** w zapytaniu wielopunktowym (HTTP 400). Wykryte przy pierwszym prawdziwym przebiegu.
- **Testy pakietu współdzielonego w `tests/`** (SPEC §10 przewidywał tylko `pipeline/tests` i `web/tests`).
