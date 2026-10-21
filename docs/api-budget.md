# Budżet Open-Meteo

Stan: 2026-10-11. Kod: `lepszapogoda/openmeteo.py` (klasy `Budget`, `call_cost`) i `pipeline/ingest/forecasts.py`.

## Limity darmowego planu

600 wywołań/min, 5 000/h, 10 000/dobę, 300 000/mies.

**Wagi zapytań.** Zapytanie z więcej niż 10 zmiennymi lub dłuższe niż 2 tygodnie liczy się proporcjonalnie więcej. Wzór: `lokalizacje × max(1, zmienne/10) × max(1, dni/14)`.
- Zakładamy ostrożnie, że każda lokalizacja w zapytaniu wielopunktowym to osobne wywołanie. Dokumentacja tego nie precyzuje.
- Zapytania odrzucone (HTTP 400) też liczymy, bo nie wiadomo, czy Open-Meteo je odlicza.

**Bezpieczeństwo.** Potok zużywa najwyżej **80 %** każdego limitu (`--safety 0.8`), a resztę zostawia stronie.
- Limit minutowy i godzinowy: zadanie czeka, aż okno się zwolni.
- Limit dobowy i miesięczny: zadanie kończy się czysto. Co pobrano, jest zapisane, reszta idzie następnego dnia.

**Rejestr zużycia** jest w `data/openmeteo_ledger.json` (kroczące okna, 30 dni historii).

## Koszt weryfikacji (potok)

Pobierane: 3 zmienne (temperatura, opad, zachmurzenie) × wyprzedzenia do horyzontu modelu w archiwum.

| Model | Wyprzedzenia | Zmienne | Mnożnik |
|---|---|---|---|
| ecmwf_ifs, ecmwf_aifs025_single, gfs_seamless | 1–7 | 21 | 2,1 |
| icon_seamless | 1–6 | 18 | 1,8 |
| meteofrance_seamless | 1–3 | 9 | 1,0 |
| knmi_harmonie_arome_europe (od 2026-10-20) | 1 | 3 | 1,0 |
| ncep_aigfs025 (od 2026-10-21) | 1–7 | 21 | 2,1 |

Komórki: 4 313 dotykających Polski.

| Faza | Koszt (wywołania ważone) | Czas przy 8 000/dobę |
|---|---|---|
| Rozruch: 30 dni wstecz, wszystkie komórki i modele | **84 104** (plan z 2026-10-11, 5 modeli); KNMI +9 tys., AIGFS +19 tys. | ~11 dni + ~3,5 dnia |
| Stan ustalony: 1/14 komórek dziennie, okna 14-dniowe | ok. **3 700/dobę** (≈ 4 313/14 × suma mnożników 12,2 dla 7 modeli) | — |
| Miesięcznie w stanie ustalonym | ok. 113 000 | 38 % limitu miesięcznego |

Pierwszy prawdziwy przebieg (2026-10-11): 2 zapytania po 50 komórek, AIFS, 30 dni, koszt 450, 504 000 wierszy, 0 braków, 0,93 MB Parquet.

## Koszt strony (Widok 2)

Jedno wyświetlenie prognozy dla punktu = zapytanie Forecast API o 7 modeli. Przy ok. 9 zmiennych na 8 dni to **7 wywołań**. Cache 1 h na komórkę (SPEC §7.4).

Po odjęciu weryfikacji zostaje ok. 215 tys. wywołań na miesiąc, czyli ok. **1 400 nowych komórek dziennie** bez trafienia w cache. Przy większym ruchu: dłuższy TTL (SPEC §7.4) albo płatny plan.

## Do obserwacji

- Faktyczne liczenie zapytań wielopunktowych. Jeśli Open-Meteo liczy je łagodniej, rozruch będzie szybszy.
- Gdy rejestr i Open-Meteo się rozjadą (429 mimo zapasu), klient czeka do następnej godziny albo kończy zadanie.
