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
