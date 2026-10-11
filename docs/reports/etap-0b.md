# Etap 0b — prognozy tygodniowe i sposób łączenia modeli

Data: 2026-10-11
Kod: `spike/weekly_skill.py`. Wyniki surowe: `spike/weekly_skill_results.json`.

## Pytania

1. Jak bardzo mylą się prognozy na 4–7 dni i który model jest w tym najlepszy?
2. Czy prognoza tygodniowa ma sens? Za punkt odniesienia przyjęto klimatologię, czyli „typową pogodę dla tej daty”, oraz persystencję, czyli „będzie jak dziś”.
3. Decyzja a): jak ważyć modele w średniej?

## Dane

- 57 stacji IMGW synop, lipiec–wrzesień 2026.
- Prognozy z Open-Meteo Previous Runs API, wyprzedzenia 1–7 dni.
- Modele: `ecmwf_ifs025`, `ecmwf_aifs025_single`, `ecmwf_ifs` (HRES 9 km, nowy w teście), `gfs_seamless`, `icon_seamless` (do 6 dni), `meteofrance_seamless` (do 3 dni).
- Klimatologia: dane IMGW z lat 2016–2025 dla tej samej stacji, mediana z okna ±7 dni wokół daty. Mediana daje najmniejszy możliwy MAE dla prognozy stałej.

## 1. Spadek trafności z wyprzedzeniem

Wyniki zsumowane po wszystkich stacjach i dniach. MAE w °C lub mm. ETS: 1 = ideał, 0 = nie lepiej niż losowo.

| Wyprzedzenie | Tmax MAE (średnia modeli) | Tmin MAE | ETS opad ≥ 1 mm | ETS opad ≥ 10 mm | MAE opadu [mm] |
|---|---|---|---|---|---|
| 1 dzień | 1,09 | 1,47 | 0,48 | 0,31 | 1,68 |
| 2 | 1,19 | 1,56 | 0,43 | 0,26 | 1,92 |
| 3 | 1,26 | 1,62 | 0,37 | 0,16 | 2,17 |
| 4 | 1,38 | 1,64 | 0,34 | 0,15 | 2,23 |
| 5 | 1,54 | 1,77 | 0,29 | 0,11 | 2,39 |
| 6 | 1,80 | 2,02 | 0,23 | 0,03 | 2,56 |
| 7 | 1,98 | 2,21 | 0,18 | 0,05 | 2,63 |
| *klimatologia* | *3,11* | *2,33* | *0,00* | *0,00* | *2,37* |
| *persystencja, 7 dni* | *4,70* | *3,74* | *−0,04* | *−0,01* | *4,06* |

Co z tego wynika:

- **Temperatura maksymalna** jest wyraźnie lepsza od klimatologii przez cały tydzień. Na 7. dzień błąd jest o 36 % mniejszy (2,0 wobec 3,1 °C).
- **Temperatura minimalna** od 6. dnia jest już niemal równa klimatologii (2,2 wobec 2,3 °C). Letnie noce są mało zmienne, więc „typowa noc” to mocny konkurent.
- **„Czy będzie padać”** (próg 1 mm) ma wartość do 7. dnia, ale słabnącą: ETS spada z 0,48 do 0,18.
- **„Ile spadnie”**: od 5. dnia prognoza ilości opadu w mm myli się bardziej niż założenie „typowy dzień” (MAE 2,39 wobec 2,37 mm). Pokazywanie konkretnych milimetrów na 5–7 dni udaje precyzję, której nie ma.
- **Ulewy** (≥ 10 mm): od 6. dnia ETS jest bliski zera, czyli brak trafności.
- Persystencja przegrywa ze wszystkim już od 1. dnia.

## 2. Tydzień jako całość

Prognoza wydana dnia D na dni D+1…D+7, porównana z tym, co rzeczywiście spadło i jaka była temperatura w tym tygodniu:

| | Suma opadu w tygodniu, MAE | Średnia Tmax w tygodniu, MAE |
|---|---|---|
| średnia modeli | **9,0 mm** | **0,88 °C** |
| ECMWF IFS HRES | 10,3 | 0,92 |
| ECMWF IFS 0,25° | 10,2 | 1,08 |
| GFS | 10,3 | 1,15 |
| ECMWF AIFS | 10,0 | 1,48 |
| klimatologia | 11,1 | 1,69 |

**Odpowiedzi na pytanie „jaki będzie ten tydzień” są wyraźnie trafniejsze niż prognozy na pojedyncze dni pod jego koniec.** Średnia temperatura tygodnia ma błąd o 48 % mniejszy niż klimatologia, suma opadu o 19 % mniejszy. Błędy pojedynczych dni częściowo się znoszą.

## 3. Który model najlepiej przewiduje dalsze dni

- Na 6.–7. dzień prowadzi rodzina ECMWF: AIFS ma najmniejszy błąd Tmax na 6.–7. dzień, a IFS HRES i IFS 0,25° podobne.
- **GFS wyraźnie słabnie po 5. dniu**: Tmax MAE 2,9 °C na 7. dzień, ETS 0,09, czyli połowa wyniku ECMWF.
- Zwycięzca Tmax na 7. dzień na stacjach: w lipcu i sierpniu AIFS (30 i 44 z 57 stacji), we wrześniu IFS HRES (38). Ten sam zwycięzca w kolejnym miesiącu tylko w 35 % przypadków. Wyniki potwierdzają, że trzeba łączyć modele, a nie wybierać jeden.
- **ECMWF IFS HRES 9 km (`ecmwf_ifs`) jest lepszy od IFS 0,25° na krótkich wyprzedzeniach** (Tmax 1,22 wobec 1,34 °C). Warto dodać go do listy modeli.
- **Średnia modeli jest najlepsza na każdym wyprzedzeniu** w Tmax, opadzie (MAE i ETS) i w ujęciu tygodniowym. Przegrywa tylko w Tmin na 1.–3. dzień z ICON i IFS HRES; tu pomaga ważenie (pkt 4).

## 4. Decyzja a): jak ważyć

Wagi wyznaczono z poprzedniego miesiąca, a sprawdzono w sierpniu i wrześniu. Wagi są proporcjonalne do 1/MSE, osobno dla temperatury i opadu, osobno dla każdego wyprzedzenia.

| Strategia | Tmin MAE, 1. dzień | Tmax MAE, 7. dzień | ETS ≥ 1 mm, 1. dzień | ETS ≥ 1 mm, 7. dzień |
|---|---|---|---|---|
| równe wagi | 1,58 | 2,01 | 0,499 | 0,164 |
| wagi lokalne (stacja) | **1,50** | **1,99** | **0,506** | **0,169** |
| wagi regionalne (≤ 150 km) | 1,53 | 1,99 | 0,496 | 0,168 |
| jeden zwycięzca regionu (wariant b) | 1,43 | 2,27 | 0,420 | 0,156 |

Wnioski:

- **Ważenie pomaga w temperaturze**, głównie w Tmin, o ok. 5 %.
- **W opadzie ważenie nie daje nic** ponad równe wagi.
- **Wybór jednego zwycięzcy jest gorszy prawie wszędzie.** Wyjątkiem jest Tmin na 1. dzień, gdzie zwycięzca regionu ma 1,43 °C, najmniej w całej tabeli. Na pozostałych wyprzedzeniach i zmiennych przegrywa ze średnią o 10–15 %. To potwierdza decyzję a).

Przyjęte w SPEC §8.10:
- temperatura: wagi 1/MSE z 30 dni, osobno dla grup wyprzedzeń,
- opad, zachmurzenie i wiatr: równe wagi.

## Zastrzeżenia

Wszystkie wyniki dotyczą lata: 3 miesiące, pojedynczy sezon. Zimą trafność opadu i różnice między modelami mogą wyglądać inaczej. Część przewagi wag w Tmin może wynikać z korekty stałego biasu stacji (np. lotniska). Do sprawdzenia w Etapie 3 na pełnym roku: prosta korekta biasu z ostatnich 30 dni, podobna do MOS, może dać więcej niż samo ważenie.

## Propozycje dla produktu (SPEC §6, decyzje domyślne)

1. **Dni 1–4: pełne liczby.**
2. **Dni 5–7 pokazane jako mniej pewne.** Temperatura jako zakres między modelami. Opad jako „szansa opadu”, czyli odsetek modeli, które dają ≥ 1 mm, zamiast milimetrów.
3. **Podsumowanie „Ten tydzień”** nad paskiem dni: średnia temperatura, czy będzie cieplej lub chłodniej niż zwykle (względem klimatologii IMGW), suma opadu w porównaniu z typowym tygodniem. To najtrafniejsza część prognozy długoterminowej i dobrze pasuje do „zero decyzji” z §2.
4. **Strona „O projekcie” z wykresem spadku trafności z wyprzedzeniem**, liczonym codziennie przez potok. Uczciwie pokazuje, ile warta jest prognoza na 7. dzień.
