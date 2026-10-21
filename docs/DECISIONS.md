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
- **Temperatura w czasie rzeczywistym: odpytywanie API IMGW co godzinę** (`pipeline/ingest/imgw.py poll`). Kontekst: miesięczne paczki IMGW przychodzą z opóźnieniem do ~5 tygodni, czyli po upływie 30-dniowego okna. API podaje tylko ostatni pomiar, a NOAA GHCN-Daily i ISD urywają się dla Polski w sierpniu 2025. Paczki archiwalne nadal są pobierane i zastępują wartości z API. Alternatywy: OGIMET (niejasne warunki), DWD BUFR (ciężkie dekodowanie).
- **Tmax/Tmin z wartości godzinowych**, i po stronie obserwacji, i modelu (06–18 i 18–06 UTC, min. 10 z 13 godzin). Kontekst: porównanie „jak z jak”. Prawdziwe ekstrema stacji są o kilka dziesiątych stopnia wyższe/niższe, ale jednakowo dla wszystkich modeli.
- **Współrzędne stacji z NOAA ISD** (`lepszapogoda/data/imgw_stations.json`, 62 stacje). Kontekst: API IMGW nie podaje współrzędnych. Platforma Petrobaltic (12001) leży poza siatką i jest pomijana.
- **Pierwsze tygodnie bez rankingu temperatury.** Kontekst: dla 1–11 października 2026 nie ma ani paczki, ani historii z API. Zgodnie z §8.4 temperatura wypada z rankingu, a wagi w średniej są równe, dopóki nie zbierze się ≥ 20 dni.
- **MODIS: `valid_frac` w praktyce zawsze 1.** MOD09GA to dzienna kompozycja, która nad Polską nie ma dziur w pasie przelotu. Jedna wartość może jednak pochodzić z różnych przelotów, więc godzina przelotu jest przybliżona (±45 min).
- **Potok w GitHub Actions od 2026-10-12, stan w R2** (prefiks `pipeline/`). Każdy przebieg robi `pull` → praca na plikach lokalnych → `push` plików zmienionych (wykrywane po rozmiarze i mtime). Przebieg godzinowy kończy się, gdy limit godzinowy jest pełny (`--max-wait 120`), zamiast czekać, więc nie marnuje minut Actions. Rejestr limitu Open-Meteo leży w R2 i jest wspólny dla przebiegów.
- **Odpytywanie IMGW przez Cloudflare Worker, nie przez harmonogram Actions** (2026-10-13, decyzja człowieka). Kontekst: w pierwszej dobie `schedule` co godzinę dał 3 przebiegi zamiast 24, a API IMGW podaje tylko ostatni pomiar, więc pominięta godzina przepada. Worker `workers/imgw-poller` (cron `5,35 * * * *`) zapisuje surowe odpowiedzi do `pipeline/obs/imgw_raw/{data}/{HHMM}.json` w R2, a potok zamienia je na Parquet (`imgw ingest-raw`). Odpytywanie w Actions zostaje jako zapas. Alternatywy: samowywołujący się job w Actions (szara strefa regulaminu), cron na mydevil (jeszcze go nie ma).
- **Prognozy archiwalne nadal w Actions mimo zawodnego harmonogramu.** Dwa przebiegi na dobę i tak wyczerpują dzienny limit Open-Meteo (8 000), więc opóźnienia nie zmniejszają przepustowości.
- **Publikacja: `tar.gz` zamiast `tar.zst`** (`lepszapogoda/publication.py`). Kontekst: gzip jest w bibliotece standardowej, a `zstandard` wymaga kompilacji, co na FreeBSD (mydevil) jest ryzykiem (§14). Rozmiar dla 4 313 komórek to ~1 MB, więc różnica bez znaczenia.
- **Archiwa wersjonowane** (`publish/archives/rankings-{czas}.tar.gz`, 7 ostatnich), a `publish/meta.json` wskazuje bieżące i jest zapisywany jako ostatni. Kontekst: hosting nigdy nie pobierze archiwum podmienionego w trakcie. SPEC mówił o jednym `rankings.tar.zst`.
- **Bramka jakości (§12):** zero komórek albo spadek o ponad 20 % względem opublikowanego `meta.json` (ta sama `grid_version`) daje brak publikacji, błąd w Actions, a hosting zostaje przy poprzednich danych. Wyjątek: przed pierwszą publikacją zero komórek to tylko pominięcie, bo w czasie rozruchu nie ma czego chronić. `--force` omija bramkę przy zamierzonych zmianach.
- **Hosting:** `web/cron/pull_rankings.py`, klucze R2 tylko do odczytu w `R2_KEY_RO`/`R2_SECRET_RO`. Weryfikuje SHA-256, liczbę plików, JSON, wersję siatki i nazwy członków archiwum (ochrona przed `../`). Podmiana katalogu: rename `rankings` → `rankings.old`, `rankings.tmp` → `rankings`. Między tymi dwoma krokami przez ułamek sekundy katalogu nie ma i strona pokazuje wtedy „zbieramy dane”.
- **Hosting (sonda 2026-10-13, `docs/hosting-capabilities.md`):** Python 3.11.13 na FreeBSD 14.3, wszystkie biblioteki strony instalują się, a numpy, pandas i pyarrow nie mają gotowych pakietów, więc zostają poza hostingiem (§14). **Cache prognoz plikowy zamiast Redis**, bo Redisa nie ma w panelu i wymagałby własnego procesu na zarezerwowanym porcie (§15 zmienione). **Limit 40 procesów na całe konto** z innymi stronami: Passenger z małą liczbą workerów, crony krótkie i z `nice`.
- **Dostęp agenta do hostingu:** osobny klucz SSH `~/.ssh/lepszapogoda_mydevil` (ed25519, bez hasła) w `authorized_keys` konta. Zmiany wyłącznie w `~/domains/lepszapogoda.pl`, bo na koncie są inne strony człowieka.
- **Virtualenv na mydevil wybierany w `passenger_wsgi.py`, nie w panelu.** Kontekst: plik wykonywalny strony typu Python ustawia się tylko przy `devil www add`; zmiana wymagałaby usunięcia i ponownego dodania domeny (ryzyko utraty ustawień, np. SSL). `passenger_wsgi.py` robi `os.execl` na `~/domains/lepszapogoda.pl/venv/bin/python`, gdy uruchomiono go innym interpreterem.
- **Etap 2, strona (2026-10-14).** Odstępstwa od SPEC w MVP:
  - **bez geolokalizacji po IP:** wymaga licencji MaxMind, a ip-api oznaczałoby wysyłanie IP odwiedzających do zewnętrznej usługi. Start na środku Polski, przycisk „Użyj mojej lokalizacji”, link „zmień” wraca z pinezką;
  - **bez podsumowania „Ten tydzień”:** wymaga norm IMGW na hostingu, do zrobienia jako osobny plik danych z potoku;
  - **Photon bez `lang=pl`** (Photon zwraca 400 dla `pl`; bez parametru i tak daje polskie nazwy);
  - **warstwa „Satelita” bez etykiet OpenFreeMap na wierzchu** (do dopracowania);
  - **nazwa miejscowości w URL jako `?n=`** (slug traci polskie znaki), ograniczona do 80 znaków i escapowana przez Jinja.
- **Budżet Open-Meteo strony:** osobny rejestr w `web/var/openmeteo_ledger.json`, 90 % limitów (inne IP niż potok w Actions), czekanie maks. 5 s. Jedno wyświetlenie = 5 modeli × waga zmiennych, cache 1 h na punkt zaokrąglony do 0,01°.
- **Wdrożenie na mydevil:**
  - `deploy/deploy.sh` (git reset do `origin/main`, pip, linki, restart, `/healthz`);
  - `public_python/passenger_wsgi.py` i `public_python/public/static` to dowiązania do repozytorium;
  - zastępcza strona mydevil `public/index.html` przeniesiona do `mydevil-placeholder-index.html`, bo przesłaniała `/`.

  Deploy na razie ręcznie przez SSH. `deploy.yml` w Actions dojdzie z osobnym kluczem (§16 pkt 3).
- **Cron na hostingu (za zgodą człowieka):** dwie linie oznaczone `# lepszapogoda` dopisane na końcu crontaba konta (`pull_rankings` co 30 min, `cleanup` 4:20), kopia poprzedniego crontaba w `~/domains/lepszapogoda.pl/crontab-backup-*.txt`. 10 zadań innych stron bez zmian.
- **Ekran główny minimalny (decyzja człowieka, 2026-10-19).** Zamiast panelu z nagłówkiem i trzema przyciskami: jedno półprzezroczyste pole ze strzałką, która prowadzi do trybu „trafna”. Tryby wybiera się na stronie prognozy. „Użyj mojej lokalizacji” jako ikona w kontrolkach mapy.
- **Polskie etykiety na mapie i w wyszukiwarce.** Styl OpenFreeMap używa `name_en`, więc w JS podmieniamy na `coalesce(name:pl, name)`. Photon dostaje `lang=default`, a duplikaty (miasto, gmina, powiat o tej samej nazwie) są scalane. Klucz cache podpowiedzi w przeglądarce zmieniony na `lp-q3:`, żeby wyrzucić stare angielskie wyniki.
- **Adresy plików statycznych z hashem treści (`?v=`)**, bo pliki mają cache na dobę; bez tego odwiedzający widzieliby stary JS po wdrożeniu.
- **Mapa (2026-10-20, uwagi człowieka):**
  - **Styl przerabiany raz i podawany jako obiekt:** wcześniej po powrocie z „Satelity” MapLibre ładował oryginalny styl, z angielskimi nazwami.
  - **Własna warstwa miast z OSM:** kafelki OpenFreeMap przy małym zoomie nie zawierają Poznania czy Wrocławia.
  - **Filtr miast po `teryt:simc`:** wycina zagraniczne miasta z komórek przygranicznych (Brześć, Frankfurt, Görlitz). Koszt: brak Zgorzelca, który w OSM nie ma węzła miejscowości z TERYT; jego nazwa pojawia się przy większym zoomie z kafelków.
  - **Siatka 0,1° rysowana na mapie i kliknięcie dwustopniowe:** najpierw przybliżenie, potem wybór kwadratu.
  - **Prognozy tylko dla kwadratów z `pl_frac > 0`:** zamiast prostokąta z marginesem 0,5°, także w walidacji URL.
- **Ranking tylko przy komplecie 5 modeli** (2026-10-20). Pierwsza publikacja (2 513 komórek) porównywała tylko AIFS z IFS (i GFS w 250 komórkach), bo pobieranie wstecz idzie model po modelu. Niepełny ranking zdjęty wymuszoną publikacją pustego (`force_publish`). Pusty po pustym to pominięcie, a pusty po niepustym blokuje bramka.
- **Rozdzielczość siatki rankingu zostaje 0,1°** (2026-10-20, pytanie człowieka o 2–4 km). Powody:
  - sędzia opadu (IMERG) ma 0,1°, więc mniejsza komórka powtórzyłaby ten sam piksel;
  - większość modeli ma 7–28 km (ICON-D2 2 km tylko na zachodzie i na 2 dni);
  - siatka 0,05° to 4 razy więcej zapytań Open-Meteo, ponad darmowy limit;
  - prognoza na stronie i tak jest dla dokładnego punktu, w natywnej rozdzielczości modelu, z korektą wysokości.

  Lepsza droga do szczegółu: kolejne modele wysokiej rozdzielczości. W Open-Meteo całą Polskę obejmują KNMI i DMI HARMONIE-AROME Europe (~3 dni) oraz UKMO 10 km (7 dni). ICM UM 4 km nie jest w Open-Meteo.
- **Nazwa klikniętego miejsca = miejscowość, w której leży punkt** (2026-10-20, błąd zgłoszony przez człowieka: Ursynów pokazywał się jako „Dawidy”). Photon reverse bez filtra zwraca najbliższy obiekt, a z jego adresu bierzemy `city` (+ `district` w dużych miastach: „Warszawa – Ursynów”). Najbliższy punkt miejscowości (`layer=city`) zostaje tylko jako zapas, gdy w pobliżu nie ma adresów (las). Wcześniejsze podejście myliło się na obrzeżach miast, bo punkt środka Warszawy jest dalej niż punkt sąsiedniej wsi.
- **Dodany model KNMI HARMONIE-AROME Europe** (decyzja człowieka, 2026-10-20). Obejmuje całą Polskę, 5,5 km, prognoza ~2,5 dnia. W Previous Runs API ma tylko `previous_day1`, więc w potoku `MAX_LEAD_DAYS = 1`. Koszt pobierania: 3 zmienne × 1 wyprzedzenie, czyli mnożnik 1,0 (rozruch ~9 tys. wywołań, potem ~300 na dobę). Strona: 6 modeli w jednym zapytaniu prognozy. Ranking wymaga kompletu modeli, więc pierwsza pełna publikacja przesuwa się o ~1–2 dni. DMI HARMONIE odłożony na później.
- **Ranking liczony osobno dla każdego wyprzedzenia i uśredniany** (2026-10-20). Przy łączeniu 24/48/72 h model archiwizowany tylko na 24 h miałby fory. Test `test_model_with_only_24h_archive_is_compared_at_24h_only`.
- **Zbieranie danych ze stacji automatycznych IMGW** (decyzja człowieka, 2026-10-21). Endpoint `api/data/meteo` ma 788 stacji. Temperaturę podaje ok. 315, a opad 10-minutowy ok. 700. Stację w promieniu 20 km ma 70% komórek dla temperatury i 90% dla opadu; przy stacjach synop trzeba było promienia 60 km. Na razie dane tylko zbieramy: do rankingu wejdą, gdy uzbiera się ≥ 20 dni i będzie gotowa kontrola jakości deszczomierzy.
  - **Worker odpytuje co 5 minut**, synop dalej o :05 i :35. API podaje tylko ostatnią wartość, a IMGW publikuje ją z opóźnieniem 10–30 min. Przy odpytywaniu co 10 minut opóźnienie mogłoby przeskoczyć interwał, a co 5 minut każdy interwał widzimy co najmniej raz. Surowe pliki są spakowane gzipem (~30 KB zamiast ~520 KB). Pliki w R2 starsze niż 14 dni kasuje codzienny przebieg, bo i tak są już w Parquet.
  - **Opad dnia D = suma 10-minutowych wartości ze znacznikiem w (06:00 D, 06:00 D+1] UTC**, jak w IMGW i IMERG (zakładamy, że znacznik to koniec interwału). Dzień jest ważny przy ≥ 138 ze 144 interwałów, bo pominiętego odczytu nie da się odtworzyć. Tmax i Tmin liczymy z pełnych godzin, w tych samych oknach co dla synop (wspólna funkcja `tmax_tmin`).
  - **Kontrola jakości na razie tylko czasowa:** odrzucamy wartości starsze niż 3 h w chwili odczytu, bo część stacji podaje pomiar sprzed miesięcy. Zacięte deszczomierze (same zera) odfiltrujemy przy weryfikacji, porównując stację z sąsiadami i z IMERG.
  - **Zapis dobowy zachowuje wartość policzoną z większej liczby danych**, więc ponowne liczenie przy brakującym pliku jej nie pogorszy.
- **Modele podstawowe i dodatkowe** (decyzja człowieka, 2026-10-21). Reguła „ranking tylko przy komplecie modeli” sprawiała, że każdy nowy model wstrzymywał publikację o ~20 dni zbierania danych. Samo dodanie KNMI przesunęło pierwszy ranking o kilka dni.
  - **Podstawowe** (pięć pierwszych) są wymagane w każdej komórce, tak jak dotąd.
  - **Dodatkowe** (KNMI, potem AIGFS i inne) dołączają do rankingu i do średniej w komórce, gdy mają tam ≥ 20 dni. Wcześniej strona pokazuje je z dopiskiem „bez oceny”.
  - **Bez oceny poza średnią:** „Najbardziej trafna” ma opierać się na sprawdzonych modelach, a model bez historii mógłby ją pogorszyć. W trybie „optymistyczna” model bez oceny bierze udział, bo ten tryb nie opiera się na trafności.
  - **Kolejność pobierania:** zapytania modeli podstawowych idą przed dodatkowymi, żeby rozruch nowego modelu nie zjadał budżetu bieżącej aktualizacji rankingu.
  - **Koszt:** przez kilka dni pobierania wstecz model dodatkowy może być w rankingu części komórek, a w innych jeszcze nie. W każdej komórce porównanie jest uczciwe, bo wynik liczymy osobno dla każdego wyprzedzenia. Zmieniają się tylko liczby zwycięstw w `meta.json`.
- **Dodany NOAA AIGFS (`ncep_aigfs025`) jako model dodatkowy** (decyzja człowieka, 2026-10-21). Drugi model AI obok ECMWF AIFS, z innego ośrodka.
  - **Archiwum** Previous Runs API ma wszystkie 7 wyprzedzeń, więc AIGFS porównujemy na 24/48/72 h jak pozostałe.
  - **Opad** jest 6-godzinny, rozłożony równo na godziny. Bloki kończą się o 00/06/12/18 UTC, więc sumy dobowe 06–06 się zgadzają, ale godzinowy wykres opadu jest „schodkowy”.
  - **Forecast API nie ma** porywów, temperatury odczuwalnej i CAPE. Średnia liczy każdą zmienną z modeli, które ją mają; w widoku pojedynczego modelu karta dnia nie pokazuje porywów.
  - **Koszt:** rozruch ok. 19 tys. ważonych wywołań (~2,5 dnia budżetu, po modelach podstawowych i KNMI), potem ok. 650 na dobę. Strona: 7 wywołań na wyświetlenie zamiast 6.
  - **Do sprawdzenia, gdy będą dane:** korelacja błędów AIGFS z GFS (ten sam start z GDAS). Jeśli będzie tak wysoka jak IFS z IFS 0,25° (0,9+), średnia liczyłaby NOAA podwójnie (por. Etap 0b).
- **Bez migracji lokalnych danych do R2.** Kontekst: klucze R2 są tylko w sekretach GitHuba. Koszt: ~1 dzień budżetu na ponowne pobranie prognoz i kilka godzin pomiarów IMGW z lokalnego odpytywania. Dane lokalne w `data/` zostają jako kopia, nieużywana przez potok.
- **Publiczne repozytorium, autor commitów z adresem noreply GitHuba, prywatna rozmowa (`docs/history/`) poza repozytorium** (decyzje człowieka 2026-10-12). Historia gita przepisana przed pierwszym pushem.
- **Testy pakietu współdzielonego w `tests/`** (SPEC §10 przewidywał tylko `pipeline/tests` i `web/tests`).
