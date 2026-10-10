# Rejestr decyzji

Format: data · kontekst · wybór · alternatywy.

## 2026-10-11 · Etap 0a

- **Przed Etapem 0 dodany Etap 0a.** Kontekst: Etap 0 wymaga kont (GEE, R2, EUMETSAT) i hostingu, zanim wiadomo, czy ranking ma sens. Wybór: lokalny test na stacjach IMGW i Open-Meteo, bez kont. Alternatywa: od razu Etap 0 wg §13.
- **Previous Runs API zamiast Historical Forecast API.** Kontekst: Historical Forecast skleja pierwsze godziny przebiegów, więc nie ma wyprzedzeń 24–72 h. Wybór: `*_previous_dayN`. Alternatywa: Single Runs API (pełne przebiegi, dużo więcej zapytań).
- **Lista modeli:** `ecmwf_ifs025, ecmwf_aifs025_single, icon_seamless, gfs_seamless, meteofrance_seamless`. Kontekst: `icon_d2` nie obejmuje wschodniej Polski, a `meteofrance_arome_france_hd` obejmuje tylko okolice Szczecina (sprawdzone zapytaniami, próbki w `docs/api-samples/`). Alternatywa: modele regionalne tylko w komórkach, które pokrywają. Odrzucone, bo ranking na różnych zbiorach modeli w różnych komórkach jest nieporównywalny.
- **Okno opadu IMGW:** `SMDB` dnia D = 06 UTC D → 06 UTC D+1. Wyznaczone empirycznie: korelacja 0,66 przy tym oknie, 0,10 przy oknie przesuniętym o dobę.
- **Usłonecznienie wyłączone z rankingu.** Kontekst: bias +2…+4 h/dobę u wszystkich modeli, a MAE ≈ bias, więc zmienna mierzy definicję, nie trafność. Wybór: nie używać jako zastępstwa zachmurzenia; w metrykach zachmurzenia stosować miary odporne na bias (§8.3).
- **Dalszy kierunek produktu:** otwarte, czeka na człowieka (§17 SPEC).
