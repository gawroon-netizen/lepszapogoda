# lepszapogoda.pl — specyfikacja projektu dla agenta AI

Wersja: 0.9, 2026-10-11
Status: dokument wykonawczy. Realizację w całości prowadzi agent AI (np. Claude Code). Człowiek dostarcza konta, klucze i decyzje z §15; wszystko inne agent robi sam.
Zmiany 0.4: hosting mydevil.net (Python/Passenger zamiast PHP), Flask jako frontend, deploy przez git, instrukcja GitHub w §16.
Zmiany 0.5: decyzja o siatce (§8.1, §15), obszary wielokomórkowe — prognoza i ranking dla całego miasta/gminy (§8.7).
Zmiany 0.6: czwarty tryb „najlepsza na burze” — ranking trafności prognoz burz weryfikowany wyładowaniami (§8.9).
Zmiany 0.7 (po Etapie 0a, `docs/reports/etap-0a.md`): Previous Runs API zamiast Historical Forecast API (§7.3); lista modeli poprawiona wg realnego pokrycia Polski (§4); budżet Open-Meteo i pobieranie paczkami 14-dniowymi (§7.3); konwencje IMGW i miary odporne na bias (§8.2–8.3); brak CAPE/kodu pogody dla ECMWF w archiwum (§8.9); otwarte decyzje produktowe (§17).
Zmiany 0.8 (decyzja człowieka + `docs/reports/etap-0b.md`): „Najbardziej trafna” = średnia ważona modeli (§1, §5, §6, §8.10); `ecmwf_ifs` dodany (§4); podsumowanie „Ten tydzień” i prezentacja dni 5–7 jako mniej pewnych (§6); limit godzinowy Open-Meteo (§7.3).
Zmiany 0.9 (decyzje człowieka §17 pkt 2–4): siatka 0,1° z pobieraniem rotacyjnym; obszary, burze i „Chmury teraz” przeniesione do v1.1; `ecmwf_ifs025` usunięty jako duplikat IFS; horyzonty modeli; „optymistyczna” liczona w locie zamiast crona (budżet API).

---

## 0. Instrukcje dla agenta

Ten dokument jest jedynym źródłem wymagań. Zasady pracy:

1. **Nie zgaduj, sprawdzaj.** Każde zewnętrzne API (Open-Meteo, EUMETView, GEE, OpenFreeMap, EOX, Photon, ip-api) przed użyciem przetestuj realnym wywołaniem i zapisz przykładową odpowiedź w `docs/api-samples/`. Parametry, limity i formaty pobieraj z bieżącej dokumentacji, nie z pamięci.
2. **Decyzje domyślne są w §15.** Gdy wymagania są niejednoznaczne, przyjmij domyślne rozwiązanie z §15, zapisz je w `docs/DECISIONS.md` (data, kontekst, wybór, alternatywy) i idź dalej. Pytaj człowieka tylko, gdy potrzebujesz konta, klucza, płatności lub gdy decyzja jest nieodwracalna (schemat plików wynikowych, licencje).
3. **Możliwości hostingu sprawdź, nie zakładaj** (§7.1). Zanim napiszesz cokolwiek pod hosting, uruchom przez SSH `tools/hosting_probe.py` i zapisz wynik w `docs/hosting-capabilities.md`. Jeśli coś z §7.1 nie działa (np. `pyarrow` nie instaluje się na FreeBSD), dostosuj architekturę i opisz to w DECISIONS.
4. **Kolejność:** etapy z §13 realizuj po kolei. Etap uznaje się za zakończony, gdy spełnione są jego kryteria akceptacji i wszystkie testy przechodzą. Nie zaczynaj frontendu, zanim potok danych nie wyprodukuje pierwszego prawdziwego `rankings/*.json`.
5. **Każdy etap kończy się** aktualizacją `README.md`, `docs/DECISIONS.md` i krótkim raportem `docs/reports/etap-N.md` (co zrobiono, co nie działa, co wymaga człowieka).
6. **Nie dodawaj zależności bez potrzeby.** Frontend JS: zero build stepu, zero frameworków. Python 3.11 wszędzie (wersja domyślna na mydevil), tylko biblioteki z `requirements*.txt` zatwierdzone w §7.3–7.4.
7. **Sekrety** wyłącznie przez zmienne środowiskowe / GitHub Secrets (§9). Nigdy w repozytorium. `.env.example` musi być zawsze aktualny.
8. **Bezpieczeństwo aplikacji WWW:** każdy parametr trasy walidowany (lat/lon jako float w bbox Polski z marginesem 0,5°, slug `[a-z0-9-]{1,80}`), Jinja2 z autoescape, nagłówki CSP i `X-Content-Type-Options`, brak wykonywania czegokolwiek z danych wejściowych. Testy w `web/tests/`.
9. **Weryfikacja poprawności danych jest ważniejsza niż szybkość.** Potok ma testy na znanych przypadkach (§12). Ranking, którego nie da się odtworzyć z plików wejściowych, jest błędem.
10. **Język:** kod i komentarze po angielsku, interfejs użytkownika po polsku, dokumentacja w `docs/` po polsku.
11. **Współdzielony kod.** Wszystko, czego używa i runner, i strona WWW (siatka, `cell_id`, obszary, klient Open-Meteo, schematy JSON), żyje w pakiecie `lepszapogoda/` w korzeniu repozytorium. Nie duplikuj tej logiki.
12. **Siatka jest abstrakcją.** Poza `lepszapogoda/grid.py` żaden moduł nie może zakładać, że komórka jest prostokątem 0,1° w lat-lon. Kod dostaje `cell_id`, centroid i geometrię z tego modułu i niczego więcej o kształcie komórki nie wie. To warunek późniejszej zmiany siatki (np. na HEALPix) bez przepisywania projektu.

## 1. Cel

Porównywarka modeli pogodowych, która dla dowolnej lokalizacji w Polsce odpowiada: **jak trafnie prognozowały tu ostatnio poszczególne modele** — i pokazuje prognozę złożoną z nich tak, żeby była możliwie najtrafniejsza (średnia ważona trafnością, §8.10). Użytkownik nie musi wiedzieć, czym jest ICON ani ECMWF.

Decyzja z 2026-10-11 (§17 pkt 1, wariant a): w Etapie 0a średnia modeli była trafniejsza niż model wybrany jako „zwycięzca” poprzedniego miesiąca, a zwycięzca zmieniał się z miesiąca na miesiąc. Ranking pojedynczych modeli zostaje jako informacja i podstawa wag, nie jako wybór jednego modelu.

## 2. Zasady nadrzędne

1. **Pierwszy ekran = zero decyzji poza jedną.** Mapa, pole, trzy przyciski.
2. **Trafność liczymy, nie deklarujemy.** Każdy ranking ma w tle liczby, które można pokazać i odtworzyć.
3. **Uczciwość wobec danych.** Jeśli zmiennej nie da się rzetelnie zweryfikować, mówimy to w UI.
4. **Hosting nic nie liczy.** Obliczenia dzieją się poza serwerem WWW.

## 3. Użytkownicy

Osoby szukające „po prostu pogody”; rolnicy, ogrodnicy, rowerzyści, żeglarze, organizatorzy imprez; entuzjaści pogody.

## 4. Zakres MVP

**Obszar:** Polska, bbox 48.9–55.0 N, 13.9–24.2 E. Siatka 0,1° → 6 283 komórki w prostokącie, z czego **4 324 dotyka Polski** — tylko te są weryfikowane i rankingowane (decyzja o siatce: §8.1; liczby z `docs/reports/etap-0-gee.md`).

**MVP a v1.1 (decyzja człowieka 2026-10-11):** MVP = ranking i prognoza dla **punktu**, mapa z warstwami „Mapa” i „Satelita”, trzy przyciski. Do **v1.1** przechodzą: obszary wielokomórkowe (§8.7), ranking burzowy i czwarty przycisk (§8.9), nakładka „Chmury teraz”. Sekcje te zostają w dokumencie jako projekt v1.1 i są oznaczone „[v1.1]”. **Warunek dla MVP:** dane weryfikacji przechowują składniki metryk (§8.8), a `grid.py` jest jedyną wiedzą o kształcie komórki (§0 pkt 12) — tak, żeby v1.1 nie wymagała przeliczania ani przepisywania potoku.

**Jednostki prognozy:** (a) **punkt** — jedna komórka siatki (MVP); (b) **[v1.1] obszar** — zbiór komórek z wagami, np. całe miasto lub gmina (§8.7); obszary rysowane przez użytkownika — v2.

**Modele (identyfikatory zgodne z Open-Meteo), 5 niezależnych:**
`ecmwf_ifs` (ECMWF IFS HRES 9 km), `ecmwf_aifs025_single` (ECMWF AIFS — model AI, inny niż IFS), `icon_seamless` (DWD: ICON-D2 → ICON-EU → ICON global), `gfs_seamless` (NOAA GFS), `meteofrance_seamless` (Météo-France: AROME → ARPEGE). WeatherNext 3 — v2.
- `ecmwf_ifs025` **usunięty** (Etap 0b, `spike/model_families.py`): to ten sam model IFS co `ecmwf_ifs`, tylko w grubszej siatce wyjściowej — korelacja błędów 0,90–0,94 (inne pary modeli: 0,6–0,8). W średniej liczyłby IFS podwójnie; bez niego średnia jest tak samo dobra lub lepsza, a budżet API mniejszy o 1/6.
- „Seamless” to nie warianty, tylko sklejka różnych modeli jednego ośrodka: najdokładniejszy regionalny tak długo, jak sięga, potem coraz grubszy. `icon_d2` pokrywa tylko zachód Polski (do ok. 20,3°E), `meteofrance_arome_france_hd` tylko okolice Szczecina — dlatego wchodzą wyłącznie przez „seamless”.
- **Horyzonty (Forecast API, sprawdzone 2026-10-11):** ECMWF IFS/AIFS i GFS ≥ 15 dni, ICON ~7,5 dnia, **Météo-France ~4 dni (103 h)**. Jedyny model krótszy niż 7 dni to Météo-France: w średniej (§8.10) od 5. dnia wagi renormalizują się na pozostałe 4 modele; w trybach jednomodelowych (optymistyczny, najmniej trafny) prognoza kończy się na horyzoncie modelu z adnotacją „ten model liczy prognozę tylko na 4 dni”.

**Zmienne w prognozie:** zachmurzenie, opady, temperatura 2 m, wiatr 10 m (prędkość, porywy, kierunek), ryzyko burzy (kod pogody, CAPE).
**Zmienne w rankingu:** zachmurzenie, opady (satelita), temperatura (stacje IMGW — decyzja domyślna §15). Wiatr poza rankingiem.
**[v1.1] Osobny ranking burzowy:** trafność prognoz burz, weryfikowana wyładowaniami atmosferycznymi (§8.9). Sezonowy: kwiecień–wrzesień. W MVP Widok 2 pokazuje tylko informacyjne ryzyko burzy z prognozy (bez rankingu).
**Horyzont:** 7 dni; krok 1 h do 5 dni, dalej 3 h.
**Poza zakresem:** konta, powiadomienia, aplikacja mobilna, prognozy probabilistyczne, API publiczne.

## 5. Widok 1 — ekran główny

### Układ
Pełnoekranowa mapa. Na niej, u góry na środku: pole lokalizacji; pod nim nagłówek „Jaką pogodę chcesz oglądać?” i trzy przyciski w rzędzie (na < 640 px w kolumnie). [v1.1] Czwarty, „Najlepsza na burze”, pod nimi jako mniejszy, wyróżniony ikoną błyskawicy; poza sezonem burzowym szary z podpisem „ranking burzowy od kwietnia”. Logo w lewym górnym rogu, „O projekcie” w prawym dolnym. Panel z polem i przyciskami ma półprzezroczyste tło i cień (czytelność na zdjęciu satelitarnym).

### Warstwy mapy (MapLibre GL JS, self-host pliku JS)
- **Bazowa „Mapa”** (domyślna): OpenFreeMap, styl `liberty` lub `bright`, kolory lekko wyciszone własnym nadpisaniem stylu.
- **Bazowa „Satelita”**: EOX Sentinel-2 cloudless, WMTS, bez klucza; na wierzchu warstwa OpenFreeMap tylko z granicami, drogami i nazwami. Fallback: Esri World Imagery z kluczem ArcGIS Location Platform (darmowy plan).
- **[v1.1] Nakładka „Chmury teraz”**: EUMETView (WMS/WMTS, Meteosat, co 15 min). RGB w dzień, IR 10.8 w nocy, przełączenie automatyczne. Krycie 60 %, suwak. Widoczna tylko przy zoomie ≤ 9. Znacznik czasu obrazu w rogu. Animacja 6 ostatnich klatek po „▶”. Fallback: RainViewer IR.
- Wybór warstw zapamiętany w localStorage. Kafelki zawsze prosto z przeglądarki, nigdy przez hosting.
- Atrybucje wszystkich źródeł w kontrolce mapy (§11).

### Zachowanie
- Start: przybliżenie do lokalizacji z IP (zoom 9); przy błędzie środek Polski, zoom 6. Nie ustawia pinezki.
- Przycisk „Użyj mojej lokalizacji” → HTML5 Geolocation.
- Kliknięcie na mapie stawia pinezkę i wypełnia pole wynikiem reverse geocodingu (Photon).
- Przyciski nieaktywne do wyboru lokalizacji.

### Geolokalizacja po IP (Flask)
MaxMind GeoLite2-City z pliku `.mmdb` (biblioteka `geoip2`), plik odświeżany co miesiąc przez cron na hostingu (`tools/update_geoip.py`, klucz licencyjny w env). Fallback: ip-api.com (limit 45/min, cache 24 h w Redis pod kluczem SHA-256 z IP, bez zapisu samego IP).

### Autocomplete
Photon (publiczna instancja Komoot) wywoływany z przeglądarki, `lang=pl`, bbox Polski, `limit=6`, debounce 250 ms, od 2 znaków, cache odpowiedzi w localStorage 7 dni. Fallback offline: `public/data/places-pl.json` (miejscowości z OSM, nazwa + gmina + województwo + lat/lon, ~40 tys. rekordów, indeks prefiksowy budowany w JS przy pierwszym użyciu). Wyświetlanie: nazwa, gmina/powiat, województwo. W MVP wybór podpowiedzi zawsze ustawia punkt. [v1.1] Jeśli podpowiedź odpowiada miastu lub gminie z `regions.json` (§8.7), pokazuje się z ikoną obszaru i wybór ustawia tryb **obszar** (na mapie rysowany jest kontur, nie pinezka). Mały przełącznik pod polem: „punkt / cały obszar” — widoczny tylko wtedy, gdy oba są dostępne. Kliknięcie na mapie zawsze daje punkt.

### Trzy przyciski

| Przycisk | Logika |
|---|---|
| **Najbardziej trafna** | średnia ważona modeli z wagami `blend` z JSON komórki lub obszaru (§8.10) |
| **Najbardziej optymistyczna** | model wybrany w locie z bieżących prognoz (§8.5) |
| **Najmniej trafna** | ostatni model z `accurate[]` |
| **[v1.1] Najlepsza na burze** | pierwszy model z `storm[]` w JSON komórki lub obszaru; brak pola → przycisk nieaktywny z wyjaśnieniem |

## 6. Widok 2 — prognoza

**URL punktu:** `/prognoza/{slug}/{lat},{lon}/{tryb}`; **[v1.1] URL obszaru:** `/prognoza/obszar/{region_id}/{tryb}` (np. `/prognoza/obszar/m-warszawa/trafna`). Tryb ∈ `trafna|optymistyczna|najmniej-trafna` (+ `burze` w v1.1). Lat/lon z 3 miejscami po przecinku.

### Nagłówek
- Nazwa lokalizacji, link „zmień” (powrót na mapę z zachowaną pinezką lub konturem). Dla obszaru: dopisek „prognoza uśredniona dla całego obszaru ({n} komórek, {km²})” i link „pokaż dla punktu”.
- Zdanie wyjaśniające, generowane z szablonu. Tryb trafny: *„Prognoza łączy {n} modeli. Większą wagę mają te, które w okolicy {nazwa} trafiały ostatnio lepiej: {model1} {w1} %, {model2} {w2} %…”* Pod spodem jedno zdanie, dlaczego tak: *„Średnia z kilku modeli myli się zwykle rzadziej niż którykolwiek z nich osobno.”* Tryby optymistyczny i najmniej trafny pokazują pojedynczy model. Dla trybu optymistycznego: *„{model} obiecuje na najbliższe 3 dni najcieplej i najsuszej (w rankingu trafności jest {n}. z {m}).”*
- Zwijany pasek rankingu: pozycja, nazwa modelu, wynik 0–100, MAE zachmurzenia, ETS opadów, MAE temperatury (jeśli jest). W trybie burzowym pasek pokazuje ranking burzowy: ETS burz, liczbę dni burzowych w oknie, odsetek fałszywych alarmów. Zdanie wyjaśniające: *„W tym sezonie burze w okolicy {nazwa} najtrafniej przewidywał {model} (trafił {k} z {n} dni burzowych, {f} fałszywych alarmów).”*
- Przełącznik trybu bez powrotu na mapę.
- Jeśli `temp_source` = null: adnotacja „temperatura poza rankingiem dla tej okolicy (brak stacji w 60 km)”.

### Prognoza 7 dni
0. **„Ten tydzień”** (nad paskiem dni, jedno–dwa zdania): średnia temperatura tygodnia względem normy IMGW dla tej pory roku („cieplej niż zwykle o ok. 2 °C”) i suma opadu względem typowego tygodnia („mniej deszczu niż zwykle”). Prognoza tygodnia jako całości jest trafniejsza niż pojedyncze dni pod jego koniec (`docs/reports/etap-0b.md`). Normy: mediana 2016–2025 ze stacji przypisanej do komórki, okno ±7 dni.
1. **Wiarygodność wg wyprzedzenia:** dni 1–4 — pełne wartości; dni 5–7 — kafelki wizualnie przygaszone z podpisem „mniej pewne”, temperatura jako zakres między modelami, opad jako „szansa opadu {p} %” zamiast milimetrów (od 5. dnia ilość opadu z modeli myli się bardziej niż założenie „typowy dzień”). Progi w `config.yaml`.
2. **Pasek dni**: 7 kafelków — dzień tygodnia, ikona (własny zestaw SVG, 12 stanów), temp. max/min, suma opadu, max porywy. Kliknięcie rozwija dzień; domyślnie rozwinięty dziś.
3. **Szczegół dnia** (uPlot, self-host): temperatura + odczuwalna; opady mm/h (deszcz/śnieg kolorem); zachmurzenie 0–100 % (warstwy jako odcienie); wiatr — prędkość, porywy, strzałki kierunku pod osią.

### Zasady prezentacji
°C, mm, km/h. Czas `Europe/Warsaw`. Widoczny czas przebiegu każdego użytego modelu. W trybie trafnym widok pokazuje średnią ważoną (§8.10), a na wykresach opadu i temperatury dodatkowo cienki pas min–max między modelami (niepewność prognozy); w pozostałych trybach — jeden model. Dla obszaru wykresy pokazują średnią, a przy opadach i wietrze dodatkowo cienki pas min–max między komórkami (rozrzut wewnątrz obszaru). Adnotacja przy wietrze: „wiatr nie wchodzi do rankingu” z linkiem do „O projekcie”. Widok działa bez JS w wersji podstawowej (SSR pasek dni w Jinja2; wykresy wymagają JS).

## 7. Architektura

### 7.1 Hosting: mydevil.net
Zgodnie z dokumentacją hostingu dostępne są: Python 3.8–3.12 (domyślnie 3.11) z `pip` i virtualenv, aplikacje WWW typu „Python” serwowane przez Passenger (WSGI, plik `passenger_wsgi.py`), SSH, cron z panelu DevilWEB, PostgreSQL, MySQL, Redis, memcached, git. System operacyjny: **FreeBSD** — biblioteki z rozszerzeniami natywnymi mogą wymagać kompilacji.

Agent potwierdza to sondą `tools/hosting_probe.py` uruchomioną przez SSH. Sonda wypisuje: wersje `python3.x`, wynik `pip install -r requirements-web.txt` i `requirements-cron.txt` w świeżym virtualenvie (z czasem i błędami kompilacji), limity z `ulimit -a`, wolne miejsce, dostępność Redis i `git`, oraz czas wykonania testowego skryptu liczącego „optymistyczny” model dla 500 komórek (żeby wiedzieć, czy lekkie zadania mogą działać na hostingu). Wynik w `docs/hosting-capabilities.md`.

Założenie do weryfikacji: hosting współdzielony ma limity CPU i RAM per proces. **Ciężkie przetwarzanie (weryfikacja na pełnej siatce, GEE) zostaje poza hostingiem**; na hostingu działają tylko aplikacja WWW i lekkie crony.

### 7.2 Podział

```
 STRONA OBLICZENIOWA                              HOSTING mydevil.net
 GEE (satelity) ─┐                                Passenger → Flask (web/)
 GitHub Actions ─┴─ verify.yml: prognozy           cron: pull_rankings.py,
                    archiwalne, weryfikacja,             cleanup.py, update_geoip.py
                    ranking → rankings.tar.zst    Redis: cache prognoz, cache geoIP
                    → Cloudflare R2  ────────────► data/rankings/*.json, data/meta.json
 git push ───────────────────────────────────────► git pull + restart Passengera (deploy)
```

Runner nie łączy się z hostingiem bezpośrednio. Publikuje wynik do R2; hosting sam pobiera go cronem (`pull_rankings.py`) i atomowo podmienia katalog. Dzięki temu brak sekretów SFTP w GitHubie, a hosting jest odporny na niedostępność Actions (zostaje przy ostatnich danych).

### 7.3 Strona obliczeniowa (Python 3.11, GitHub Actions)
- **GEE** przez `earthengine-api` z kontem serwisowym. Skrypty w `pipeline/gee/` eksportują dzienne tabele na komórkę: suma IMERG dla doby D-2, frakcja zachmurzenia MODIS dla doby D-4 (opóźnienie MODIS w GEE ~3 dni). Koszt zmierzony w Etapie 0: ~8 EECU-s na dobę danych IMERG dla całej siatki — potok mieści się w < 1 % darmowego limitu Community (150 EECU-h/mies., obowiązuje od 27.04.2026).
- **`verify.yml`**: codziennie 05:30 UTC. Kroki: eksport GEE → pobranie obserwacji IMGW → pobranie prognoz archiwalnych → metryki → ranking → `rankings.tar.zst` + `meta.json` → upload do R2. Dane pośrednie (Parquet) także w R2, żeby job był wznawialny.
- **Prognozy archiwalne: Open-Meteo Previous Runs API** (`previous-runs-api.open-meteo.com/v1/forecast`), zmienne `{var}_previous_day{1,2,3}` (= prognoza wydana 24/48/72 h przed czasem ważności), `models=` po jednym, `timezone=UTC`, `cell_selection=nearest`, `elevation=nan` (odpowiedź podaje wtedy wysokość komórki modelu — potrzebna do korekty temperatury). Zmienne: `cloud_cover,precipitation,temperature_2m` + dla burz `weather_code,cape` tam, gdzie istnieją (§8.9). **Nie** Historical Forecast API — ono skleja pierwsze godziny przebiegów i nie zawiera wyprzedzeń 24–72 h. Archiwum od 01.2024 (AIFS od 02.2025), co pozwala policzyć ranking wstecz od pierwszego dnia.
- **Budżet:** darmowy limit 10 000 wywołań/dobę i 300 000/mies.; zapytanie > 10 zmiennych lub > 2 tygodnie liczy się proporcjonalnie więcej; zapytania wielopunktowe liczymy ostrożnie jako 1 wywołanie na punkt. Pełna siatka dziennie (6 300 × 5 modeli × ~1,8) ≈ 57 tys./dobę — niewykonalne. **Decyzja (człowiek, 2026-10-11): siatka 0,1° z pobieraniem rotacyjnym paczkami 14-dniowymi** — każdego dnia 1/14 komórek za ostatnie 14 dni (dla 4 324 komórek w Polsce ~2,8 tys. ważonych wywołań/dobę); dane weryfikacji są więc opóźnione maks. o 14 dni, co przy oknie 30 dni jest akceptowalne. Rozruch (30 dni wstecz dla wszystkich komórek, ~110 tys. wywołań) rozłożony na ~14 dni przed startem strony. Budżet całkowity (weryfikacja + Widok 2) musi zmieścić się w 300 tys./mies.; licznik zużycia w `meta.json`. **Limit godzinowy (5 000 ważonych wywołań/h) jest realnym ograniczeniem** — w Etapie 0a został przekroczony po ~600 zapytaniach z 3-miesięcznym zakresem dat. Pobieranie musi mieć własny dławik (np. ≤ 4 000 ważonych wywołań/h, licząc wagę z liczby zmiennych i dni) i obsługę HTTP 429 z odczekaniem do następnej godziny.
- Ten sam kod uruchamialny lokalnie: `make verify`.
- `requirements-pipeline.txt`: `pandas`, `pyarrow`, `numpy`, `requests`, `earthengine-api`, `boto3`, `pydantic`, `zstandard`, `pytest`, `ruff`.
- Budżet Open-Meteo policzony i zapisany w `docs/api-budget.md`.

### 7.4 Strona WWW (Flask, Passenger)
- `web/passenger_wsgi.py`: `from app import create_app; application = create_app()`. Domena w panelu DevilWEB jako typ „Python”, wskazująca na katalog `web/` i interpreter z virtualenva.
- Trasy: `/` (Widok 1), `/prognoza/<slug>/<lat>,<lon>/<tryb>` (Widok 2), `/api/forecast` (JSON dla wykresów), `/o-projekcie`, `/healthz`. Statyczne pliki z `web/static/` (Passenger/nginx serwuje je bezpośrednio, jeśli hosting to wspiera — sprawdzić w sondzie).
- `lepszapogoda/forecast.py`: prognoza z Open-Meteo Forecast API dla `(model, lat, lon)`, cache w Redis pod kluczem `fc:{model}:{lat2}:{lon2}`, TTL 1 h; dla obszaru — jedno zapytanie wielopunktowe na centroidy komórek obszaru (max 50 punktów; większe obszary próbkowane co drugą komórkę, zapisane w DECISIONS), wynik agregowany wg §8.7 i cache'owany pod `fcr:{model}:{region_id}`; licznik dzienny `quota:{date}` w Redis; po 8 000 wywołań TTL rośnie do 3 h. Fallback cache plikowy w `web/var/cache/`, jeśli Redis niedostępny.
- `lepszapogoda/ranking.py`: czyta `web/data/rankings/{cell_id}.json`; brak → średnia z równymi wagami i komunikat „zbieramy dane”.
- `lepszapogoda/blend.py`: łączy prognozy modeli wg §8.10. W trybie trafnym Widok 2 potrzebuje prognoz wszystkich modeli — jedno zapytanie Forecast API z `models=` jako listą (cache per model jak wyżej; przy liczeniu budżetu traktować jako N wywołań).
- `lepszapogoda/grid.py` (lat/lon → cell_id), `web/app/geoip.py`, `web/app/slug.py`.
- Szablony Jinja2 w `web/app/templates/`; teksty UI w `web/app/i18n/pl.py`.
- `requirements-web.txt`: `flask`, `jinja2`, `requests`, `redis`, `geoip2`, `gunicorn` (tylko do testów lokalnych; na hostingu serwuje Passenger).
- Crony na hostingu (panel DevilWEB, wszystkie w virtualenvie, logi do `web/var/log/`):
  - `pull_rankings.py` — co 30 min: sprawdza `meta.json` w R2 (ETag); jeśli nowy, pobiera archiwum do `data/rankings.tmp/`, weryfikuje liczbę plików i podmienia katalog `os.rename`.
  - ~~`optimistic.py`~~ — **usunięty w v0.9**: liczenie dla 6 300 komórek × 5 modeli co 6 h to ~126 tys. wywołań/dobę, ponad limit. „Optymistyczny” liczy się w locie w Widoku 2 z prognoz wszystkich modeli, które i tak są pobierane do średniej (§8.5) — zero dodatkowych wywołań.
  - `cleanup.py` — codziennie: sprząta cache plikowy i logi starsze niż 7 dni.
  - `update_geoip.py` — 1. dnia miesiąca: pobiera nowy `.mmdb`.
- Deploy: `deploy/deploy.sh` wykonywany przez SSH z GitHub Actions (`deploy.yml`, po zielonym CI na `main`): `git pull`, `pip install -r requirements-web.txt` w virtualenvie, `touch web/tmp/restart.txt` (restart Passengera), `curl /healthz`.

### 7.5 Co odpada
PHP w całości; SFTP; PostgreSQL (niepotrzebny w MVP — rankingi w JSON); FastAPI/Django (Passenger = WSGI, dwie trasy nie uzasadniają większego frameworka).

## 8. Weryfikacja przez satelity

### 8.1 Siatka
**Decyzja (MVP):** regularna siatka 0,1° × 0,1° w lat-lon. `cell_id = f"{int(round(lat*10)):03d}_{int(round(lon*10)):03d}"` dla lewego dolnego rogu (np. `509_182`). Lista komórek w `pipeline/grid/poland_cells.parquet` (cell_id, lat_min, lon_min, centroid, geometria, pole [km²], `pl_frac` — ułamek komórki w granicach Polski wg `USDOS/LSIB_SIMPLE/2017`). Komórki z `pl_frac = 0` są w pliku, ale potok ich nie weryfikuje.

**Dlaczego nie HEALPix teraz:** produktem jest ranking per komórka, gdzie równa powierzchnia komórek nic nie zmienia; nad Polską różnica pola między północą a południem to ~13 %, a wszystkie źródła (GEE, Open-Meteo, mapa) pracują w lat-lon. HEALPix wchodzi w v2 przy rozszerzeniu na Europę lub przy statystykach po dużych obszarach.

**Warunki migracji siatki (obowiązują od dziś):**
- cały kod poza `grid.py` używa tylko `cell_id`, centroidu, geometrii i pola z tego modułu (§0 pkt 12);
- `grid.py` wystawia `grid_version` (np. `latlon01`), zapisywany w każdym Parquet i JSON; pliki z inną wersją nie mieszają się;
- obserwacje z GEE liczy się funkcją, która przyjmuje dowolną kolekcję wielokątów, nie zakłada prostokątów;
- migracja = nowa wersja siatki, ponowne pobranie prognoz archiwalnych z Open-Meteo (dostępne od 2022 r.) i przeliczenie obserwacji; stare pliki zostają w R2 pod starą wersją.

### 8.2 Obserwacje

| Zmienna | Źródło | Przetwarzanie |
|---|---|---|
| Zachmurzenie | **MODIS Terra i Aqua w GEE** (`MODIS/061/MOD09GA`, `MYD09GA`, bity `state_1km`: zachmurzone = 1, mieszane = 0,5). Decyzja po Etapie 0: Meteosatu nie ma w GEE; VIIRS ma ~7 dni opóźnienia i inną definicję maski (systematycznie mniej chmur) — nie mieszać źródeł | frakcja na komórkę w chwili przelotu (Terra ~09:30, Aqua ~11:30 UTC; dokładny czas z metadanych granuli), porównywana z `cloud_cover` modelu interpolowanym na tę godzinę; tylko pora dzienna. Zachmurzenie nocne poza rankingiem (oznaczyć w „O projekcie”) |
| Opady | NASA IMERG V07 Late, GEE (`NASA/GPM_L3/IMERG_V07`) | suma dobowa [mm] na komórkę; flaga `snow_possible` gdy T2m stacji < 2 °C |
| Temperatura | IMGW, dane synoptyczne (API publiczne `danepubliczne.imgw.pl`), ok. 60 stacji | dobowa średnia, max, min; przypisanie do komórek w promieniu 60 km z wagą 1/d; korekta 0,65 °C/100 m względem wysokości modelu z odpowiedzi Open-Meteo |

Wiatr: brak obserwacji nad lądem — poza rankingiem.

**Konwencje IMGW (sprawdzone w Etapie 0a):** dane dobowe synop `s_d` w miesięcznych paczkach `danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_meteorologiczne/dobowe/synop/{rok}/`, publikowane z opóźnieniem do ~5 tygodni, kodowanie CP1250; status `8` = brak pomiaru, `9` = zjawisko nie wystąpiło (opad = 0). Suma opadu `SMDB` dnia D obejmuje 06 UTC D → 06 UTC D+1. Tmax liczyć z 06–18 UTC, Tmin z 18 UTC D−1 – 06 UTC D. Współrzędne stacji: identyfikator WMO = `12` + trzy ostatnie cyfry kodu IMGW. Do bieżących danych (bez czekania na paczkę miesięczną) sprawdzić `api/data/synop`.

### 8.3 Metryki (okno 30 dni, wyprzedzenia 24/48/72 h uśrednione)
- Zachmurzenie: trafność klasy (pogodnie < 25 %, pochmurno > 75 %, pośrednie) jako miara główna oraz MAE frakcji [%] **po odjęciu biasu modelu z okna**. Powód (Etap 0a): różne definicje „zachmurzenia/usłonecznienia” w modelu i w obserwacji dają systematyczny bias rzędu dziesiątek procent, który zwykły MAE traktuje jak błąd prognozy i który sam rozstrzygał ranking. Bias raportujemy osobno.
- Opady: ETS dla progu ≥ 1 mm/dobę (waga 0,7) i MAE sumy dobowej (waga 0,3).
- Temperatura: MAE dobowej max i min [°C].

### 8.4 Wskaźnik łączony
Każda metryka normalizowana do 0–1 względem najgorszego i najlepszego modelu w komórce (1 = najlepszy). Wagi: zachmurzenie 0,40 · opady 0,40 · temperatura 0,20; jeśli temperatury brak (brak stacji ≤ 60 km), wagi 0,5/0,5 i `temp_source: null`. Wynik × 100, zaokrąglony do całości. Wagi w `pipeline/config.yaml`.

Warunek minimalny: ≥ 20 dni z danymi dla komórki i modelu; modele poniżej progu wypadają z rankingu tej komórki. Jeśli żaden nie spełnia — brak pliku dla komórki.

### 8.5 „Najbardziej optymistyczna”
Liczone **w locie w Widoku 2** (`lepszapogoda/optimistic.py`), z prognoz wszystkich modeli pobranych dla punktu do średniej (§8.10) — bez dodatkowych wywołań API i bez crona. Dni 1–3 od jutra (wszystkie modele, także Météo-France, sięgają tak daleko). `t = mean(tmax)`, `p = sum(precip)`. Normalizacja min–max między modelami; `score = 0.5·t_norm + 0.5·(1−p_norm)`; remis → niższe zachmurzenie. Etykieta UI: „najcieplej i najsuszej”.

### 8.6 Zastrzeżenia (do umieszczenia na stronie „O projekcie”)
IMERG zaniża słabe opady i myli się przy śniegu; skala 0,1° nie widzi pojedynczej burzy; ranking temperatury jest regionalny (stacje), nie lokalny; wiatr nie jest weryfikowany. Prognozy nie zastępują ostrzeżeń IMGW.

### 8.7 [v1.1] Obszary wielokomórkowe (miasto, gmina)
Obszar to zbiór komórek z wagami. Definicja w `web/data/regions.json` i `pipeline/grid/regions.parquet`, generowana raz przez `pipeline/grid/build_regions.py` z granic administracyjnych (OSM `admin_level` 7–8 albo PRG z GUGiK, decyzja w DECISIONS):

```json
{"id":"m-warszawa","name":"Warszawa","type":"miasto","teryt":"1465011",
 "cells":[{"cell":"522_209","w":0.31},{"cell":"522_210","w":0.42}, ...],
 "area_km2":517,"centroid":[52.23,21.01]}
```
`w` = ułamek pola obszaru przypadający na komórkę (przecięcie geometrii), suma = 1. Komórki z `w < 0,02` odrzucane, wagi renormalizowane. Obszar mniejszy niż jedna komórka nie jest obszarem — dostaje tryb punktowy.

**Ranking obszaru** liczy się z danych per komórka bez ponownej weryfikacji, dlatego `verification` (§9) musi przechowywać **składniki**, nie tylko gotowe metryki:
- MAE: ważona średnia MAE komórek (wagi `w`);
- ETS/klasy: sumuje się liczniki (`hits, misses, false_alarms, correct_negatives`) ważone `w`, potem liczy ETS ze zsumowanych liczników — nie średnia ETS-ów;
- temperatura: ważona średnia, z pominięciem komórek bez stacji ≤ 60 km (wagi renormalizowane);
- dalej jak §8.4. Runner liczy rankingi wszystkich obszarów z `regions.parquet` w tym samym jobie i publikuje `rankings/regions/{region_id}.json` w tym samym formacie co komórki.

**Prognoza obszaru** = agregacja prognoz komórek dla wybranego modelu, ważona `w`:
- temperatura, zachmurzenie, prędkość wiatru, porywy: średnia ważona;
- opady: średnia ważona sumy (interpretacja: średni opad na obszarze), plus min i max między komórkami do pasa rozrzutu;
- kierunek wiatru: średnia wektorowa ze składowych u/v, nigdy średnia stopni;
- ikona dnia: z zagregowanych wartości, nie z „najczęstszej ikony”.

**„Optymistyczny” obszaru**: ta sama procedura co §8.5 na zagregowanych prognozach.

**Zastrzeżenie (do „O projekcie”):** uśrednianie po obszarze wygładza ekstrema i faworyzuje modele gładkie; dla miasta wielkości Warszawy prognoza obszaru może pokazać 2 mm, gdy jedna dzielnica dostanie 10 mm, a inna nic. Pas min–max ma to pokazywać.

**Skalowanie w v2:** obszary definiowane przez użytkownika (rysowanie na mapie), powiaty i województwa, statystyki „który model wygrywa w regionie”. Wszystko to działa na tej samej strukturze `cells + w`, więc nie wymaga zmian w potoku; to również jest moment, w którym HEALPix (hierarchiczna agregacja) zaczyna mieć praktyczne zalety.

### 8.8 Formaty danych

**Runner (Parquet w R2, każdy plik z kolumną `grid_version`):**
- `forecasts/{model}/{date}.parquet` — cell_id, init_time, valid_time, lead_h, cloud, precip, temp
- `obs/{source}/{date}.parquet` — cell_id, time, cloud | precip | temp | flashes (liczba wyładowań w oknie 3 h)
- `verification/{date}.parquet` — cell_id, model, var (`cloud|precip|temp|storm`), lead_h, mae, bias, hits, misses, false_alarms, correct_negatives, n, timing_err — **składniki, nie tylko metryki**, żeby obszary (§8.7) i sezonowe okna burzowe (§8.9) dało się policzyć bez ponownej weryfikacji

**Hosting (JSON, `web/data/`):**
- `rankings/{cell_id}.json`:
  ```json
  {"grid_version":"latlon01","cell":"522_209","computed":"2026-09-28T05:10Z","window_days":30,
   "accurate":[{"model":"icon_d2","score":91,"cloud_mae":11.2,"precip_ets":0.58,"temp_mae":1.3}, ...],
   "blend":{"method":"…","temp":{"ecmwf_ifs":0.24, ...},"precip":{...},"cloud":{...}},
   "temp_source":"station:12375:8km",
   "storm":{...}}
  ```
- `rankings/regions/{region_id}.json` — ten sam format, plus `cells_n`, `area_km2`.
- `regions.json` — definicje obszarów (§8.7).
- `meta.json` — lista modeli z opisami, `grid_version`, czas ostatniej aktualizacji, wagi, liczba komórek i obszarów z rankingiem, mediana wyniku.

### 8.9 [v1.1] Ranking burzowy

**Cel:** który model najlepiej przewiduje, czy w danym miejscu będzie burza. To inna umiejętność niż trafność opadów: burza jest zdarzeniem rzadkim, krótkim i lokalnym, więc wymaga własnej weryfikacji, własnego okna i własnych progów.

**Obserwacja: wyładowania atmosferyczne.** Kandydaci, do rozstrzygnięcia testem w Etapie 0 (kolejność preferencji):
1. **Meteosat MTG Lightning Imager (EUMETSAT)** — detekcja wyładowań z orbity geostacjonarnej nad Europą, produkty L2 (flashes/groups) z EUMETSAT Data Store; rozdzielczość rzędu 4–5 km, ciągła obserwacja. Wymaga konta EUMETSAT i przetwarzania na runnerze (nie ma go w GEE). Objętość dobowa produktów L2 jest umiarkowana — sprawdzić.
2. **IMGW PERUN** — naziemna sieć detekcji IMGW; sprawdzić, czy dane są w otwartym dostępie (danepubliczne.imgw.pl) i z jakim opóźnieniem. Jeśli tak — dokładniejsze niż satelita.
3. **Blitzortung** — sieć społecznościowa; dane surowe tylko dla uczestników, więc odpada, chyba że projekt sam postawi odbiornik (wtedy dostęp do danych sieci) — zapisać jako opcję w HUMAN_TODO.
Komercyjne sieci (Vaisala GLD360, ENTLN) poza zakresem.

**Zdarzenie „burza” w komórce:** ≥ 1 wyładowanie w komórce **lub jej 8 sąsiadach** w oknie 3 h. Sąsiedztwo jest celowe: model o siatce 2–25 km nie umie umieścić burzy w konkretnej komórce, a burza 8 km obok dla użytkownika i tak jest burzą. To standardowa weryfikacja sąsiedztwa; promień w `config.yaml` (domyślnie 1 komórka ≈ 10 km).

**Prognoza „burza” w modelu (dla tej samej komórki i okna 3 h):** kod pogody Open-Meteo w zakresie 95–99 **lub** `cape ≥ 800 J/kg` i `precipitation ≥ 0,5 mm` w oknie. Próg CAPE w `config.yaml`; agent kalibruje go w Etapie 3 tak, by częstość alarmów była zbliżona do częstości zdarzeń (bias ≈ 1) i zapisuje w DECISIONS. Modele bez CAPE w Open-Meteo używają tylko kodu pogody — oznaczone w `meta.json`.
**Uwaga z Etapu 0a:** w Previous Runs API `ecmwf_ifs025` i `ecmwf_aifs025_single` nie mają ani `weather_code`, ani `cape`; CAPE mają tylko `gfs_*` i `meteofrance_*`. Potrzebna jest definicja wspólna dla wszystkich modeli — domyślnie: maksymalny opad godzinowy w oknie 3 h ≥ próg (kalibrowany do bias ≈ 1 per model), a kod pogody/CAPE tylko jako dodatkowa informacja. Dodatkowe darmowe źródło obserwacji: kolumny `BRZA` (godziny burzy) i `DZBL` (błyskawice) w danych dobowych IMGW synop — punktowe, ale naziemne; użyć do walidacji detekcji satelitarnej.

**Metryki (wyprzedzenia 24/48 h, okna 3 h):**
- ETS (główna), POD (trafione burze), FAR (fałszywe alarmy), bias częstości;
- błąd czasu: mediana różnicy między początkiem prognozowanego a obserwowanego okna burzowego w dniach z trafieniem;
- wynik = ETS znormalizowany między modelami × 100.

**Okno i minimum:** burze są rzadkie, więc 30 dni to za mało. Okno = **bieżący sezon od 1 kwietnia**, kroczące co najmniej 60 dni. Ranking tylko przy ≥ 5 dniach burzowych zaobserwowanych w komórce (z sąsiedztwem) w oknie; inaczej `storm: null` i komunikat „za mało burz do oceny”. Od października do marca `storm` w JSON zawiera wynik z ostatniego sezonu z flagą `season: "2026"` i UI mówi „ranking z sezonu 2026”.

**Obszary:** zdarzenie obszaru = wyładowanie w dowolnej komórce obszaru (bez sąsiedztwa, bo obszar sam jest sąsiedztwem); prognoza obszaru = burza w ≥ 20 % komórek (waga `w`). Liczniki sumowane jak w §8.7.

**Wyświetlanie ryzyka w Widoku 2** (w każdym trybie): poziom „możliwa” gdy CAPE ≥ 400 lub kod 95–99; „prawdopodobna” gdy kod 95–99 i CAPE ≥ 800. To komunikacja, nie ostrzeżenie — disclaimer o IMGW obowiązuje.

**JSON komórki, pole `storm`:**
```json
"storm":{"season":"2026","window_from":"2026-04-01","computed":"2026-09-28T05:10Z","storm_days_obs":14,
 "ranking":[{"model":"icon_d2","score":100,"ets":0.41,"pod":0.79,"far":0.35,"timing_h":-1.5}, ...],
 "obs_source":"mtg_li"}
```

**Zastrzeżenia (do „O projekcie”):** satelitarna detekcja wyładowań gubi część słabych burz i bywa mniej czuła w dzień; ranking mówi „czy będzie burza w okolicy”, nie „o której i jak silna”; poza sezonem pokazujemy dane historyczne.

### 8.10 Łączenie modeli („Najbardziej trafna”)

Podstawa: `docs/reports/etap-0b.md` (średnia modeli najlepsza na każdym wyprzedzeniu 1–7 dni; ważenie pomaga tylko w temperaturze; wybór jednego zwycięzcy gorszy).

- **Członkowie:** wszystkie modele z §4 dostępne dla danej godziny prognozy; gdy model kończy horyzont, wagi renormalizuje się na pozostałych.
- **Temperatura:** wagi ∝ 1/MSE z ostatnich 30 dni, osobno dla grup wyprzedzeń 1–2, 3–4, 5–7 dni, liczone z obserwacji stacyjnych przypisanych do komórki (§8.2). Brak danych → równe wagi.
- **Opad, zachmurzenie, wiatr:** równe wagi (ważenie nie poprawiło wyniku; do ponownej oceny w Etapie 3 na pełnym roku). Kierunek wiatru — średnia wektorowa u/v.
- **Ikona dnia** z wartości uśrednionych, nie z najczęstszej ikony.
- **Niepewność:** min–max między członkami, pokazywany jako pas na wykresach; „szansa opadu” = odsetek członków z opadem ≥ 1 mm w danym dniu.
- **Zapis:** pole `blend` w JSON komórki/obszaru (§8.8): metoda, wagi per zmienna i grupa wyprzedzeń, okno, czas obliczenia. Wagi muszą być odtwarzalne z Parquet weryfikacji (§0 pkt 9).
- **Do sprawdzenia w Etapie 3:** korekta biasu per komórka (30 dni) przed uśrednieniem — może dać więcej niż samo ważenie, zwłaszcza dla Tmin.

## 9. Konta, klucze, sekrety (dostarcza człowiek)

| Co | Gdzie użyte | Zmienna / miejsce |
|---|---|---|
| Google Cloud projekt + GEE (niekomercyjny) + konto serwisowe JSON | GitHub Actions | secret `GEE_SERVICE_ACCOUNT_JSON` |
| EUMETSAT konto (Data Store: Lightning Imager, ew. produkty chmurowe) | GitHub Actions | secrets `EUMETSAT_KEY`, `EUMETSAT_SECRET` — wymagane dopiero w v1.1 (burze); w MVP tylko, jeśli produkt chmurowy z §8.2 tego wymaga |
| Cloudflare R2 bucket + klucze (odczyt/zapis) | GitHub Actions | secrets `R2_ENDPOINT`, `R2_KEY`, `R2_SECRET`, `R2_BUCKET` |
| Cloudflare R2 klucze tylko do odczytu | hosting | `~/.bash_profile` na mydevil: `R2_*_RO` |
| Klucz SSH do mydevil (deploy) | GitHub Actions | secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH` |
| Redis na mydevil (host, port, hasło) | hosting | `~/.bash_profile`: `REDIS_URL` |
| MaxMind licencja (do pobierania `.mmdb`) | hosting | `~/.bash_profile`: `MAXMIND_LICENSE_KEY` |
| ArcGIS Location Platform klucz (fallback satelity) | frontend | `web/static/config.js` (publiczny, ograniczony do domeny) |
| Wniosek o dostęp do WeatherNext (v2) | — | — |

Na mydevil zmienne środowiskowe dla aplikacji Passengera ustawia się w `~/.bash_profile` (`export NAZWA=wartość`). Agent utrzymuje `.env.example` i `docs/HUMAN_TODO.md`.

## 10. Struktura repozytorium

```
lepszapogoda/
├── README.md, LICENSE (AGPL-3.0), .env.example, Makefile, pyproject.toml
├── lepszapogoda/        pakiet współdzielony: grid.py, regions.py, aggregate.py, openmeteo.py, ranking.py, schemas.py
├── pipeline/            gee/, ingest/, verify/, rank/, publish/, grid/ (build_cells.py, build_regions.py), config.yaml, tests/
├── web/
│   ├── passenger_wsgi.py
│   ├── app/             __init__.py (create_app), routes.py, forecast_api.py, geoip.py, slug.py,
│   │                    templates/, i18n/pl.py
│   ├── static/          js/ (map.js, search.js, charts.js), css/, vendor/ (maplibre, uplot),
│   │                    icons/, data/places-pl.json, config.js
│   ├── data/            rankings/ (pobierane cronem, w .gitignore), meta.json
│   ├── cron/            pull_rankings.py, cleanup.py, update_geoip.py
│   ├── var/             cache/, log/, geoip/ (w .gitignore)
│   ├── tmp/             restart.txt (Passenger)
│   └── tests/
├── tools/               hosting_probe.py
├── deploy/              deploy.sh, CHECKLIST.md
├── docs/                DECISIONS.md, HUMAN_TODO.md, hosting-capabilities.md, api-budget.md,
│                        api-samples/, reports/, o-projekcie.md, QA.md
├── requirements-web.txt, requirements-pipeline.txt, requirements-dev.txt
└── .github/workflows/   ci.yml, verify.yml, deploy.yml
```

## 11. Prawne i atrybucje (wszystkie widoczne w kontrolce mapy lub stopce „O projekcie”)

- Projekt niekomercyjny; przy monetyzacji ponownej oceny wymagają: Open-Meteo, GEE, ip-api, Photon, EOX (CC BY-NC-SA), EUMETView, RainViewer.
- Teksty atrybucji: „© OpenStreetMap contributors”, „OpenFreeMap”, „Sentinel-2 cloudless by EOX — contains modified Copernicus Sentinel data”, „© EUMETSAT”, „NASA GPM IMERG”, „Dane pomiarowe: IMGW-PIB”, „Prognozy: Open-Meteo.com (CC BY 4.0) oraz ECMWF, DWD, NOAA, Météo-France”, „GeoLite2 © MaxMind”.
- RODO: IP nie zapisywane; brak analityki w MVP.
- Disclaimer na obu widokach: „Prognozy nie zastępują ostrzeżeń IMGW. Ranking dotyczy zachmurzenia, opadów i temperatury.”
- Licencja kodu: AGPL-3.0, repozytorium publiczne.

## 12. Testy i jakość

- **Potok i pakiet współdzielony:** `pytest` — (a) test siatki: 6 283 komórki w bbox, pełne pokrycie bbox, 4 324 ± 20 z `pl_frac > 0`; (b) test metryk na syntetycznych danych: model idealny → MAE 0, ETS 1; model losowy → ETS ≈ 0; (c) test normalizacji i wag: suma wag = 1, wynik w [0,100]; (d) test „optymistyczny” na 3 modelach z ręcznie policzonym wynikiem; (e) test odtwarzalności: ten sam Parquet → identyczny JSON (hash); (f) test agregacji obszarów: obszar z jednej komórki = wynik komórki; obszar z dwóch komórek o wagach 0,5/0,5 z ręcznie policzonym ETS ze zsumowanych liczników; średnia wektorowa kierunku wiatru (350° i 10° → 0°); (g) test `build_regions.py`: sumy wag = 1 ± 1e-6, każda komórka obszaru istnieje w siatce; (h) test weryfikacji burz: sąsiedztwo (wyładowanie w komórce obok = trafienie), okno 3 h na granicy doby, ETS przy zerowych zdarzeniach zwraca `null` a nie dzielenie przez zero, próg minimum 5 dni burzowych.
- **WWW:** `pytest` z klientem testowym Flask — walidacja tras (błędne lat/lon → 400, slug spoza wzorca → 404), mapowanie lat/lon → cell_id na granicach bbox, brak pliku rankingu → model domyślny, TTL i licznik limitu (Redis podmieniony na `fakeredis`), nagłówki CSP, SSR paska dni bez JS.
- **Frontend:** brak frameworka testowego; lista ręcznych scenariuszy w `docs/QA.md` (mobile 360 px, brak JS, brak geolokalizacji, wolne łącze, pinezka na granicy).
- **CI (`ci.yml`):** `ruff check`, `ruff format --check`, `pytest` (pipeline + web), kontrola, że `.env.example` zawiera wszystkie zmienne z §9. Deploy (`deploy.yml`) startuje tylko po zielonym CI na `main`.
- **Dane produkcyjne:** codzienny job zapisuje w `meta.json` liczbę komórek z rankingiem i medianę wyniku; spadek liczby komórek > 20 % dzień do dnia = błąd jobu (nie publikować, tylko alert w logu Actions).

## 13. Etapy i kryteria akceptacji

**Etap 0 — rozpoznanie (agent + człowiek).**
Agent: `tools/hosting_probe.py` uruchomiony przez SSH na mydevil, raport w `docs/hosting-capabilities.md` (w tym: czas obliczenia średniej ważonej i „optymistycznej” dla jednego punktu w Flasku); realne wywołania wszystkich API z §0 zapisane w `docs/api-samples/`; test w GEE: eksport zachmurzenia i IMERG dla siatki za jeden dzień; [v1.1, nie w MVP] test MTG LI i PERUN; decyzja o produkcie chmurowym w DECISIONS; `HUMAN_TODO.md` z listą kont.
Akceptacja: wszystkie API odpowiadają; wiadomo, co działa na hostingu; siatka istnieje.

**Etap 1 — potok danych.**
Codzienny `verify.yml` produkuje `rankings.tar.zst` i `meta.json` w R2; `pull_rankings.py` na hostingu pobiera je i podmienia katalog; wagi `blend` (§8.10) w JSON komórek; testy z §12 przechodzą; `api-budget.md` pokazuje zużycie < 60 % limitu (dobowego, godzinowego i miesięcznego).
Akceptacja: po rozruchu (≈ 14 dni rotacji wstecz) ≥ 90 % komórek ma ranking i wagi; ranking odtwarzalny z Parquet; Parquet weryfikacji zawiera składniki metryk (warunek v1.1).

**[v1.1] Etap 1.1 — obszary, burze, „Chmury teraz”.** Rankingi obszarów dla wszystkich miast na prawach powiatu i gmin miejskich (§8.7); ranking burzowy policzony wstecznie za ostatni sezon (§8.9; wymaga konta EUMETSAT i testu MTG LI); nakładka „Chmury teraz” (§5).

**Etap 2 — frontend.**
Aplikacja Flask działa pod Passengerem na mydevil, `deploy.yml` wdraża po zielonym CI; Widok 1 i 2 zgodnie z §5–6; działa bez JS w wersji podstawowej; TTFB < 300 ms; Widok 2 < 1,5 s przy zimnym cache Open-Meteo; scenariusze `QA.md` przechodzą; atrybucje kompletne.

**Etap 3 — beta.**
Porównanie rankingu z ręczną kontrolą dla 20 lokalizacji; korekta wag jeśli trzeba (w DECISIONS); strona „O projekcie” z §8.6; monitoring limitu; raport końcowy.

**v2:** radar IMGW dla opadów, warstwa „kto wygrywa” na mapie, WeatherNext 3 (w GEE), wagi użytkownika, oś czasu „Chmury teraz”, Europa.

## 14. Ryzyka i postępowanie

| Ryzyko | Co robi agent |
|---|---|
| Produkt chmurowy Meteosat niedostępny w GEE | **zmaterializowane w Etapie 0** — używamy MODIS Terra/Aqua; Meteosat z EUMETSAT Data Store jako opcja v1.1 (wymaga przetwarzania na runnerze) |
| IMERG jako „prawda” zawodzi zimą (śnieg, słabe opady) | jesienią ETS IMERG vs deszczomierze = 0,58 (Etap 0); powtórzyć test na miesiącach zimowych; w razie słabego wyniku zimą — ważyć mocniej stacje IMGW lub dodać GSMaP v8 jako drugie źródło |
| IMERG słaby zimą | waga ETS > MAE (już w §8.3); w meta.json flaga sezonu; radar w v2 |
| Limit Open-Meteo | TTL adaptacyjny (§7.4); przy > 90 % przez 3 dni — precomputowanie prognoz per komórka co 6 h (dodać do runnera) |
| Cron hostingu zawodny | `pull_rankings.py` jest idempotentny, a strona działa na ostatnich danych; `/healthz` zwraca wiek `meta.json`, monitorowany przez darmowy uptime checker (HUMAN_TODO) |
| `pyarrow`/`numpy` nie instalują się na FreeBSD (mydevil) | na hostingu tylko `requirements-web.txt` bez pandas; JSON zamiast Parquet w kodzie hostingu |
| Passenger nie serwuje statycznych plików wydajnie | ustawić nagłówki cache z Flask (`Cache-Control: max-age=86400` dla `static/`), rozważyć subdomenę statyczną |
| Limity CPU/RAM na hostingu ubijają cron | wszystkie crony z `nice`, przetwarzanie strumieniowe po jednej komórce, timeout 10 min; przy problemach przenieść do Actions |
| GitHub Actions job > 6 h lub brak minut | podział na kroki, cache Parquet w R2; instrukcja uruchomienia na domowym komputerze w README |
| Zmiana warunków EUMETView/EOX | fallbacki z §5; warstwa może być wyłączona flagą w `config.js` bez deployu reszty |
| Brak dostępu do danych o wyładowaniach (LI niedostępny, PERUN zamknięty) | ranking burzowy z opadów konwekcyjnych IMERG (≥ 5 mm/h) jako słabszego proxy, oznaczony w UI; zapisać w DECISIONS |
| Archiwum LI nie sięga kwietnia 2026 | ranking burzowy startuje od dostępnej daty; próg 5 dni burzowych może nie być spełniony przed sezonem 2027 — UI pokazuje „za mało burz do oceny” |

## 15. Decyzje domyślne (agent przyjmuje bez pytania)

| Kwestia | Decyzja domyślna |
|---|---|
| Temperatura w rankingu | stacje IMGW, ≤ 60 km, inaczej poza rankingiem dla komórki |
| Runner ciężkich zadań | GitHub Actions; kod uruchamialny lokalnie przez `make` |
| Framework WWW | Flask + Jinja2, WSGI pod Passengerem; bez FastAPI/Django |
| Cache | Redis na mydevil; fallback plikowy |
| Transfer runner → hosting | Cloudflare R2, hosting pobiera cronem (pull), bez SFTP |
| Produkt chmurowy | MODIS Terra + Aqua (Etap 0: Meteosatu nie ma w GEE) |
| Nazwy modeli w UI | prawdziwe (ICON-D2, ECMWF IFS…) z jednozdaniowym opisem w dymku |
| Język | tylko PL; teksty UI w `web/app/i18n/pl.py`, szablony gotowe na i18n |
| Okno rankingu | 30 dni; sezonowe — v2 |
| Licencja kodu | AGPL-3.0 |
| Prognoza bez rankingu | średnia modeli z równymi wagami |
| „Najbardziej trafna” | średnia ważona trafnością (§8.10), decyzja człowieka 2026-10-11 |
| Siatka | lat-lon 0,1° (`grid_version=latlon01`); HEALPix w v2 przy Europie, migracja wg §8.1 |
| Źródło granic obszarów | OSM `admin_level` 7–8 (miasta, gminy); PRG GUGiK jeśli OSM ma braki |
| Zakres obszarów (v1.1) | miasta na prawach powiatu + gminy miejskie (~300 obszarów); reszta gmin i obszary własne — v2 |
| Zakres MVP | punkt, ranking + średnia ważona, 3 przyciski; obszary, burze, „Chmury teraz” — v1.1 (decyzja człowieka 2026-10-11) |
| Siatka rankingu | 0,1°, pobieranie rotacyjne 14-dniowe (decyzja człowieka 2026-10-11) |
| Źródło wyładowań | MTG Lightning Imager; PERUN jeśli otwarty; IMERG jako proxy w ostateczności |
| Definicja burzy w modelu | kod pogody 95–99 lub CAPE ≥ 800 J/kg z opadem ≥ 0,5 mm w oknie 3 h; kalibracja progu w Etapie 3 |
| Sąsiedztwo weryfikacji burz | 1 komórka (3×3) |
| Sezon burzowy | 1 kwietnia – 30 września |
| Ikony pogodowe | własny zestaw SVG, 12 stanów, w repozytorium |
| Mapa bazowa | OpenFreeMap `liberty` z wyciszonymi kolorami |

**Decyzje wymagające człowieka (nieodwracalne lub kosztowe):** rejestracja kont z §9; ewentualna zmiana na model komercyjny; zakup domeny i hostingu; zgoda na publikację repozytorium.

## 16. Co zrobić na GitHubie (instrukcja dla człowieka)

Kolejność ma znaczenie: agent potrzebuje repozytorium i sekretów, zanim uruchomi pierwszy workflow.

**1. Repozytorium**
- Utwórz repozytorium `lepszapogoda` (publiczne, licencja AGPL-3.0, bez szablonu — agent wygeneruje strukturę z §10). Jeśli wolisz zacząć prywatnie i upublicznić po becie, ustaw prywatne; Actions ma wtedy limit 2 000 min/mies. (publiczne — bez limitu).
- W *Settings → General*: wyłącz Wiki i Projects (szum), włącz „Automatically delete head branches”.
- W *Settings → Branches* dodaj regułę dla `main`: wymagany zielony status `ci`, zakaz force-push. Bez wymogu recenzji (pracuje jeden agent), chyba że chcesz zatwierdzać każdy PR ręcznie — wtedy włącz „Require a pull request before merging” i sam będziesz recenzentem.

**2. Sekrety** (*Settings → Secrets and variables → Actions → New repository secret*). Wklej dokładnie pod tymi nazwami:
- `GEE_SERVICE_ACCOUNT_JSON` — cała zawartość pliku JSON klucza konta serwisowego GEE.
- `R2_ENDPOINT`, `R2_KEY`, `R2_SECRET`, `R2_BUCKET` — z panelu Cloudflare R2 (utwórz bucket `lepszapogoda-data` i token API z uprawnieniem Object Read & Write).
- `DEPLOY_HOST` (np. `s1.mydevil.net`), `DEPLOY_USER` (login mydevil), `DEPLOY_PATH` (np. `/usr/home/LOGIN/domains/lepszapogoda.pl/public_python`), `DEPLOY_SSH_KEY` — klucz **prywatny** wygenerowany specjalnie do deployu (krok 3).
- `EUMETSAT_KEY`, `EUMETSAT_SECRET` — z konta EUMETSAT (Data Store → API keys); potrzebne do wyładowań (§8.9, v1.1), a być może też do produktów chmurowych — w MVP można odłożyć do wyniku Etapu 0.
- Sekrety są niewidoczne po zapisaniu; przy pomyłce nadpisz.

**3. Klucz SSH do deployu**
- Lokalnie: `ssh-keygen -t ed25519 -f ~/.ssh/lepszapogoda_deploy -C "github-deploy"` (bez hasła).
- Klucz publiczny (`.pub`) dodaj na mydevil: przez SSH do `~/.ssh/authorized_keys` albo w panelu DevilWEB, jeśli ma taką opcję.
- Klucz prywatny wklej jako sekret `DEPLOY_SSH_KEY`.
- Sprawdź z terminala: `ssh -i ~/.ssh/lepszapogoda_deploy LOGIN@sX.mydevil.net` musi wejść bez pytania o hasło.

**4. Zmienne nie-tajne** (*Settings → Secrets and variables → Actions → Variables*):
- `OPENMETEO_MODELS` = `ecmwf_ifs,ecmwf_aifs025_single,icon_seamless,gfs_seamless,meteofrance_seamless`
- `RANKING_WINDOW_DAYS` = `30`
Agent może dodać kolejne; ma je opisać w README.

**5. Actions**
- *Settings → Actions → General*: „Allow all actions”, Workflow permissions: „Read repository contents” (workflows nie muszą pisać do repo). Deploy używa własnego klucza SSH, nie `GITHUB_TOKEN`.
- Harmonogramy (`schedule:`) działają tylko na gałęzi domyślnej i mogą się opóźniać o kilkanaście minut — to normalne.
- Po pierwszym uruchomieniu `verify.yml` sprawdź zakładkę Actions: zielony status i artefakt `verify-report`. Czerwony status z logiem to jest to, co przekazujesz agentowi.

**6. Na mydevil (jednorazowo, przed pierwszym deployem)**
- W panelu DevilWEB dodaj domenę `lepszapogoda.pl` typu **Python**, wersja 3.11, katalog aplikacji `.../public_python` (nazwa wg panelu).
- Przez SSH: `git clone https://github.com/TWOJLOGIN/lepszapogoda.git` do tego katalogu, `python3.11 -m venv venv`, `venv/bin/pip install -r requirements-web.txt`.
- Do `~/.bash_profile` dopisz `export REDIS_URL=...`, `export R2_ENDPOINT_RO=...` itd. (lista w `.env.example`), potem `source ~/.bash_profile`.
- Utwórz Redis w panelu (jeśli wymaga osobnego włączenia) i zapisz dane dostępowe.
- Crony z §7.4 dodaj w *Zadania Cron* w DevilWEB, wywołując `venv/bin/python web/cron/NAZWA.py` z pełnymi ścieżkami. Agent wygeneruje dokładne linie w `deploy/CHECKLIST.md`.
- Zrób pierwszy ręczny `deploy/deploy.sh`, wejdź na `/healthz`. Jeśli odpowiada, kolejne deploye idą z Actions.

**7. Przekazanie agentowi (po decyzjach z §17)**
Agent dostaje: adres repozytorium, dostęp do SSH mydevil (ten sam klucz lub osobny), potwierdzenie, że sekrety z pkt 2 są wpisane, oraz ten dokument. Pierwsze polecenie dla agenta: *„Wykonaj Etap 0 z §13 i zakończ raportem `docs/reports/etap-0.md` oraz listą `docs/HUMAN_TODO.md`.”*

## 17. Otwarte decyzje po Etapie 0a (wymagają człowieka)

Szczegóły i liczby: `docs/reports/etap-0a.md`.

1. ~~**Czym jest „Najbardziej trafna”.**~~ **Rozstrzygnięte 2026-10-11: wariant a** (średnia ważona, §8.10; potwierdzone testem w `docs/reports/etap-0b.md`). Pierwotny opis: na 57 stacjach IMGW (VII–IX 2026) model wybrany jako najlepszy w poprzednim miesiącu trafiał w kolejnym mniej więcej tak samo jak jeden stały model, a **średnia z 5 modeli była lepsza od każdego pojedynczego**. Warianty:
   a. średnia modeli ważona trafnością (rekomendacja: najlepsza jakość; zmienia zasadę „cały widok z jednego modelu”),
   b. pojedynczy zwycięzca, ale okno 60–90 dni, ranking regionalny i komunikat o remisie, gdy różnice mieszczą się w niepewności,
   c. bez zmian (najprostsze, najsłabiej uzasadnione).
2. **Rozstrzygnięte 2026-10-11: 0,1°** z pobieraniem rotacyjnym (§7.3).
3. **Rozstrzygnięte 2026-10-11:** jedynym modelem krótszym niż 7 dni jest Météo-France (~4 dni); w średniej wagi się renormalizują, w trybach jednomodelowych prognoza kończy się na horyzoncie z adnotacją (§4). Przy okazji usunięto `ecmwf_ifs025` jako duplikat IFS.
4. **Rozstrzygnięte 2026-10-11: tak** — obszary, burze i „Chmury teraz” w v1.1 (§4, §13).

Wszystkie decyzje z §17 są zamknięte; następny krok: Etap 0 (§13) po założeniu kont z §16.
