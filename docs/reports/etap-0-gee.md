# Etap 0 (część GEE) — obserwacje satelitarne dla siatki 0,1°

Data: 2026-10-11
Kod: `spike/gee_catalog.py`, `spike/gee_test.py`. Wyniki: `spike/gee_test_results.json`; dane per komórka w `spike/data/gee/` (poza repozytorium).
Uruchomione na projekcie Cloud człowieka, z jego logowaniem (`earthengine authenticate`). Konto serwisowe jeszcze nie istnieje.

## Wyniki

### 1. Co jest w katalogu GEE (1 162 zbiory)

- **Brak produktów Meteosat/EUMETSAT** (CLAAS, SEVIRI, MTG). Zachmurzenie co 15 min wymagałoby EUMETSAT Data Store poza GEE.
- **Zachmurzenie:** MODIS Terra `MODIS/061/MOD09GA` i Aqua `MODIS/061/MYD09GA` (1 km, bity `state_1km`) oraz VIIRS `NASA/VIIRS/002/VNP09GA` (`QF1`). Stary `NOAA/VIIRS/001` jest wycofany.
- **Opady:** IMERG V07 `NASA/GPM_L3/IMERG_V07` (co 30 min, 0,1°) oraz JAXA GSMaP v8 `JAXA/GPM_L3/GSMaP/v8/operational` (co 1 h, 0,1°).

### 2. Opóźnienie danych (stan 2026-10-11 ok. 00:30 UTC)

| Źródło | Najnowsze dane | Opóźnienie |
|---|---|---|
| IMERG V07 | 2026-10-10 03:30 UTC | ~21 h |
| GSMaP v8 | 2026-10-10 14:00 UTC | ~10 h |
| MODIS Terra / Aqua | 2026-10-08 | ~3 dni |
| VIIRS | 2026-10-04 | ~7 dni |

Wniosek: opady można weryfikować dla doby D-2, jak w SPEC. **Zachmurzenie z MODIS najwcześniej dla D-4.** VIIRS ma za duże opóźnienie do codziennego potoku; nadaje się tylko jako uzupełnienie przy przeliczeniach wstecz.

### 3. Siatka

- W prostokącie Polski jest **6 283** komórek (SPEC §12 zakładał „6 300 ± 50”, co się zgadza).
- Z tego tylko **4 324** dotyka Polski, a 4 091 leży w Polsce co najmniej w połowie (granice: `USDOS/LSIB_SIMPLE/2017`).
- Ranking i pobieranie prognoz wystarczy robić dla 4 324 komórek, czyli **o 31 % mniej wywołań Open-Meteo**: ok. 2,8 tys. wywołań na dobę przy rotacji 14-dniowej zamiast 4 tys.

### 4. Jak wiarygodny jest IMERG jako „prawda” o opadach

Dobowa suma opadu z IMERG w komórce, porównana z deszczomierzem stacji IMGW w tej komórce (wrzesień 2026, 57 stacji, 1 710 par):

| Miara | IMERG wobec deszczomierza | Dla porównania: średnia modeli, prognoza na 1 dzień (Etap 0b) |
|---|---|---|
| korelacja | 0,79 | — |
| bias | +0,10 mm/dobę | — |
| MAE | 1,06 mm | 1,68 mm |
| ETS ≥ 1 mm | **0,58** | 0,48 |
| POD / FAR ≥ 1 mm | 0,85 / 0,22 | — |

IMERG zgadza się z deszczomierzami wyraźnie lepiej niż najlepsza prognoza, więc nadaje się na sędziego dla opadu. Zastrzeżenia: to jeden jesienny miesiąc. Ze specyfikacji (§8.6) wiadomo, że IMERG słabo radzi sobie ze śniegiem i słabymi opadami, więc zimą trzeba to sprawdzić ponownie. Przy różnicach między modelami rzędu 0,03–0,05 ETS błąd samego IMERG nie jest pomijalny.

### 5. Zachmurzenie: trzy satelity, trzy różne odpowiedzi

Średnie zachmurzenie nad siatką w tych samych dniach:

| Dzień | Terra (~09:30 UTC) | Aqua (~11:30 UTC) | VIIRS (~11:30 UTC) |
|---|---|---|---|
| 05.09 | 0,70 | 0,64 | 0,45 |
| 15.09 | 0,49 | 0,40 | 0,26 |
| 25.09 | 0,93 | 0,97 | 0,95 |

VIIRS daje systematycznie mniej chmur niż MODIS przy podobnej godzinie przelotu. To różnica w definicji maski chmur (MODIS liczy piksele „mieszane”, VIIRS tylko „prawdopodobnie zachmurzone”), a nie w pogodzie. Potwierdza to wniosek z Etapu 0a: w zachmurzeniu potrzebne są miary odporne na bias i **jedno, stałe źródło**. Domyślnie: MODIS Terra i Aqua, porównywane z prognozą modelu w godzinie przelotu. Pokrycie Polski 100 % w każdym z trzech dni.

### 6. Koszt w limicie GEE

- Eksport IMERG dla całej siatki za 30 dni: **242 EECU-sekundy**, czyli ok. 8 s na dobę danych.
- Darmowy poziom Community: 150 EECU-godzin na miesiąc.
- Codzienny potok (IMERG + MODIS) zużyje szacunkowo **poniżej 1 % limitu**. Rozruch wstecz za kilka miesięcy też się mieści.
- Obliczenia interaktywne: 21 s dla IMERG (30 dni) i 18 s dla chmur (9 obrazów).

## Co wymaga człowieka

- **Konto serwisowe** w tym samym projekcie Cloud: role Earth Engine Resource Writer i Service Usage Consumer, klucz JSON do sekretu GitHub `GEE_SERVICE_ACCOUNT_JSON`.
- **Sugestia, bez blokowania:** obecny projekt Cloud został utworzony automatycznie przez Google AI Studio (nazwa `gen-lang-client-…`). Limit GEE liczy się per projekt. Osobny projekt „lepszapogoda” byłby czytelniejszy, ale obecny też działa.
