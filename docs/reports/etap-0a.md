# Etap 0a — szybki test głównego pomysłu

Data: 2026-10-11
Kod: `spike/probe_openmeteo.py`, `spike/station_ranking.py`
Wyniki surowe: `spike/station_ranking_results_full.json`, `spike/station_ranking_results_nosun.json`, próbki API w `docs/api-samples/`

## Pytanie

Czy „model, który ostatnio trafiał tu najlepiej” to dobra rada na kolejne dni? Od tego zależy sens całego produktu (§1 SPEC).

## Co zrobiono

- **Obserwacje:** dane dobowe IMGW synop (`s_d`) za lipiec–wrzesień 2026, 57 stacji z współrzędnymi (NOAA ISD). Zmienne: Tmax, Tmin, suma opadu, usłonecznienie.
- **Prognozy:** Open-Meteo **Previous Runs API**, wyprzedzenie 24/48/72 h (`*_previous_day1..3`), `elevation=nan`, `cell_selection=nearest`, korekta temperatury 0,65 °C/100 m względem wysokości komórki modelu.
- **Modele:** `ecmwf_ifs025`, `ecmwf_aifs025_single`, `icon_seamless`, `gfs_seamless`, `meteofrance_seamless`.
- **Ranking** jak w §8.4, z usłonecznieniem jako zastępstwem zachmurzenia (waga 0,4). Liczony w dwóch wariantach: z usłonecznieniem i bez niego (opady 0,6, temperatura 0,4). Okno 1 miesiąc, wynik uśredniony po trzech wyprzedzeniach.
- **Zużycie API:** 285 zapytań. Każde obejmuje 94 dni i 9 zmiennych, więc liczy się wielokrotnie: łącznie ok. 1 900 „wywołań” z darmowej puli.

## Wyniki

### 1. Specyfikacja używa złego API do wyprzedzeń (potwierdzone)

Historical Forecast API skleja pierwsze godziny kolejnych przebiegów, więc nie daje prognoz na 24/48/72 h. Do tego służy **Previous Runs API**: wartości `*_previous_dayN` to prognoza wydana N×24 h przed czasem ważności. Archiwum sięga stycznia 2024, a dla AIFS lutego 2025.

### 2. Zasięg i horyzonty modeli nad Polską

| Model | Pokrycie PL | Wyprzedzenia w Previous Runs | `weather_code` | `cape` |
|---|---|---|---|---|
| ecmwf_ifs025 | cała | 1–7 dni | **brak** | **brak** |
| ecmwf_aifs025_single | cała | 1–7 | **brak** | **brak** |
| icon_eu | cała | 1–3 | jest | brak |
| icon_d2 | **tylko zachód (do ok. 20,3°E): Szczecin tak; Warszawa, Białystok, Zakopane nie** | 1 | jest | brak |
| icon_seamless | cała | 1–5 | jest | brak |
| gfs_global / gfs_seamless | cała | 1–7 | jest | jest |
| meteofrance_arome_france_hd | **tylko skrawek przy Szczecinie** | 1 | brak | jest |
| meteofrance_seamless | cała | 1–3 | jest | jest |

Wnioski:
- `meteofrance_arome_france_hd` trzeba usunąć z listy.
- `icon_d2` ma sens tylko jako część `icon_seamless`.
- Ranking burzowy oparty na kodzie pogody i CAPE (§8.9) **nie zadziała dla ECMWF**, bo Open-Meteo nie udostępnia tych zmiennych w archiwum dla IFS/AIFS. Potrzebna inna definicja prognozy burzy, np. intensywność opadu.
- Wysokość komórki modelu różni się od stacji nawet o 600 m (Zakopane: stacja 857 m, IFS 1 464 m). Korekta wysokościowa jest konieczna.

### 3. Konwencje IMGW (sprawdzone empirycznie)

- Suma opadu `SMDB` dla dnia D dotyczy okresu **06 UTC D → 06 UTC D+1**. Korelacja z prognozą przy tym oknie wynosi 0,66, przy oknie o dobę wcześniejszym 0,10.
- Plik `s_d` zawiera też godziny burzy (`BRZA`) i występowanie błyskawic (`DZBL`). To darmowe, naziemne źródło do weryfikacji burz, przynajmniej punktowo na ~60 stacjach.
- Średnie dobowe zachmurzenie (`NOS`, w oktantach) jest w osobnym pliku `s_d_t`. Dla 2026 r. nie ma go w miesięcznych paczkach, do sprawdzenia.

### 4. Usłonecznienie wypacza ranking

Wszystkie modele zawyżają usłonecznienie o 2–4 h dziennie, a MAE jest prawie równe biasowi. Wartość mierzy więc różnicę między sposobem, w jaki Open-Meteo wylicza usłonecznienie dla danego modelu, a heliografem IMGW, a nie trafność modelu. Z usłonecznieniem ICON wygrywa na 30–45 z 57 stacji w każdym miesiącu. Bez niego zwycięzcy są rozproszeni.

**To samo ryzyko dotyczy zachmurzenia z satelity (§8.2).** Inna definicja „zachmurzenia” w modelu i w produkcie satelitarnym da systematyczny bias, który MAE potraktuje jak błąd prognozy. W rankingu trzeba używać miar odpornych na bias: trafności klas, korelacji albo MAE po odjęciu biasu.

### 5. Główny wynik: „zwycięzca z zeszłego miesiąca” nie przewiduje dobrze następnego

Wariant bez usłonecznienia, 57 stacji:

- Ten sam zwycięzca w kolejnym miesiącu: **31 %** przypadków. Przy losowym wyborze byłoby 20 %.
- Średnia korelacja rang między miesiącami: **0,38**.

Test wyboru: model wybrany na podstawie poprzedniego miesiąca, oceniony w miesiącu docelowym (wyniki uśrednione po stacjach i wyprzedzeniach 24/48/72 h):

| Strategia | Sierpień: T MAE | Sierpień: ETS opadu | Wrzesień: T MAE | Wrzesień: ETS opadu |
|---|---|---|---|---|
| zawsze ICON | **1,45** | 0,41 | 1,37 | 0,40 |
| zawsze ECMWF IFS | 1,62 | 0,37 | 1,43 | 0,45 |
| lokalny zwycięzca z poprzedniego miesiąca | 1,51 | 0,40 | 1,36 | 0,43 |
| regionalny zwycięzca (stacje ≤ 150 km) | 1,50 | 0,40 | 1,38 | 0,40 |
| lokalny zwycięzca z 2 miesięcy | — | — | 1,37 | 0,41 |
| **średnia z 5 modeli** | 1,52 | **0,45** | **1,31** | **0,46** |
| wyrocznia (najlepszy w miesiącu docelowym, wiedza z przyszłości) | 1,52 | 0,48 | 1,34 | 0,49 |

Wnioski:
- Wybór lokalnego zwycięzcy daje wynik zbliżony do „zawsze jeden dobry model”: w sierpniu trochę gorzej, we wrześniu trochę lepiej. Różnice między modelami są małe (T MAE 1,37–1,54 °C, ETS 0,38–0,45), a 30-dniowe okno na jednej stacji to za mało danych, żeby je wiarygodnie rozróżnić.
- **Średnia z modeli bije każdy pojedynczy model** we wrześniu we wszystkich trzech miarach, a w sierpniu w opadach. We wrześniu jest nawet lepsza od „wyroczni”. To standardowy efekt w meteorologii: błędy różnych modeli częściowo się znoszą.

### Zastrzeżenia

Tylko 3 letnie miesiące, tylko stacje (bez satelity), 5 modeli. Siatka 0,1° z obserwacjami satelitarnymi ma więcej szumu (pojedyncza komórka, IMERG), więc stabilność rankingu per komórka będzie raczej gorsza niż na stacjach. Wynik trzeba powtórzyć na pełnym archiwum od 2024 r. (zima, przejściowe pory roku).

## Co to znaczy dla projektu

Hasło „najtrafniejszy model dla twojej okolicy” w obecnej formie obiecuje więcej, niż dane pozwalają dowieść. Wersje produktu, które dane wspierają:

1. **Najbardziej trafna = średnia modeli ważona trafnością** (wagi z dłuższego okna, np. 90 dni, regionalnie). Najlepsza jakość prognozy. Odchodzi od zasady „cały widok z jednego modelu”.
2. **Ranking jako transparentność, nie wyrocznia.** Pokazujemy tabelę trafności z niepewnością („modele A, B, C w granicach błędu — remis”), dłuższe okno (60–90 dni) i rankingi osobno dla zmiennych.
3. **Zostawić koncept jednego zwycięzcy**, z uczciwym komunikatem, że różnice są małe. To najprostsze, ale najsłabiej uzasadnione.

Decyzja należy do człowieka (zmienia §1, §5, §6).

## Budżet Open-Meteo (§7.3)

- Darmowy limit: 600 wywołań/min, 5 000/h, 10 000/dobę, 300 000/mies. Zapytanie liczy się wielokrotnie powyżej 10 zmiennych (np. 18 zmiennych = 1,8) lub 2 tygodni danych. Sposób liczenia zapytań o wiele lokalizacji nie jest opisany. Zakładamy ostrożnie, że każda lokalizacja to osobne wywołanie.
- Codzienne pobieranie dla pełnej siatki 0,1°: 6 300 komórek × 5 modeli × 1,8 ≈ **57 tys. wywołań na dobę, ok. 6× ponad limit**.
- Wykonalne warianty:
  - **pobieranie paczkami po 14 dni rotacyjnie:** codziennie 1/14 komórek, czyli ok. 4 tys. wywołań na dobę; dane spóźnione maks. 2 tygodnie,
  - **siatka weryfikacji 0,25°:** ok. 1 000 komórek; przy paczkach 14-dniowych ok. 650 wywołań na dobę,
  - płatny plan.

## Do zrobienia przez człowieka

- Zainstalować git: `winget install Git.Git`. Nie ma go w systemie, więc repozytorium nie zostało jeszcze zainicjowane.
- Decyzja produktowa z sekcji „Co to znaczy dla projektu”.
