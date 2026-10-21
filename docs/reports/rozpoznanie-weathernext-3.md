# Rozpoznanie: WeatherNext 3 (Google DeepMind)

Stan: 2026-10-21. Cel: czy i jak dodać WeatherNext 3 (WN3) do porównania.

## Co to jest

- Globalny model AI Google DeepMind, udostępniony 2026-09-03.
- Ensemble 64 członków.
- Przebiegi co godzinę: o 00/06/12/18 UTC na 15 dni, pozostałe na 48 h.
- Krok 1 h, rozdzielczość 0,1° (temperatura i punkt rosy także 0,05° „stacyjnie”).
- Na wejściu bezpośrednio obserwacje: zdjęcia satelitów geostacjonarnych i stacje naziemne.
- Opad kalibrowany do IMERG, temperatura do stacji.

## Dostęp w Earth Engine (sprawdzone na projekcie `gen-lang-client-0589028343`)

| Kolekcja | Zawartość | Stan |
|---|---|---|
| `projects/gcp-public-data-weathernext/assets/weathernext_3_0_0_0p1deg` | 19 zmiennych powierzchniowych × statystyki ensemble (mean, p10, p25, p50, p75, p90): temperatura 2 m, opad 1 h (trzy warianty), zachmurzenie całkowite i piętrowe, wiatr 10/100 m, ciśnienie, promieniowanie | metadane widoczne, **piksele: „Permission denied”** |
| `..._0p05deg` | tylko temperatura i punkt rosy 2 m („station head”) | niewidoczna |

- **Archiwum od 2026-01-01.** Rozruchu 30 dni wstecz nie trzeba czekać, a z danych od stycznia da się nawet ocenić zimę.
- **Opóźnienie w GEE ok. 8 h od startu przebiegu** (00Z dostępny ok. 08 UTC). Dla weryfikacji to bez znaczenia.
- **Pełny przebieg 00Z** to 360 obrazów (godzina po godzinie). Każdy obraz obejmuje cały glob.
- **Dostęp daje wniosek** „WeatherNext Data Request” (Google Form). Rozpatrywany zwykle w 5–7 dni roboczych. Jedna zgoda obejmuje GEE, BigQuery i Cloud Storage. Bez opłat.

## Warunki użycia (moje odczytanie, nie porada prawna)

Dwie licencje, rozdzielone czasem, którego dotyczą dane:

- **Dane dla czasu ≥ 1 h temu: CC BY 4.0.** Dotyczy to też prognoz wydanych w przeszłości na przeszły czas, więc weryfikacja, ranking i publikacja wyników są dozwolone. Wymagane jest podanie źródła: „© 2026 DeepMind Technologies Limited's machine learning models used to create the experimental data”, link do zbioru i CC BY 4.0.
- **Dane dla czasu < 1 h temu i przyszłości: „GDM Real-Time Weather Forecasting Experimental Data Terms of Use”** (`https://storage.googleapis.com/weathernext-public/terms-of-use.pdf`, wersja z 2026-09-03):
  - wolno: użytek wewnętrzny oraz publikacja „Value Added Service”, z której danych nie da się odtworzyć bez znacznego wysiłku;
  - **nie jest** „Value Added Service” to, co tylko koloruje, formatuje, wycina obszar albo zestawia kroki czasowe i parametry (§3). Wykres lub tabela prognozy WN3 to więc „niezmodyfikowane dane”, a tych nie wolno publikować otwarcie: tylko kontrolowane przekazanie znanym odbiorcom;
  - zastrzeżenie „not intended for consumer use”;
  - zakaz udostępniania w krajach z listy (Japonia, Korea Płd., Indonezja i inne), a strona publiczna nie ma blokady geograficznej;
  - Google może w każdej chwili cofnąć zgodę i wprowadzić opłaty (z miesięcznym wyprzedzeniem).

**Wniosek:**
- **ranking z WN3: tak;**
- **prognoza WN3 na stronie: nie, bez pisemnej zgody** (weathernext@google.com);
- **WN3 w średniej „Najbardziej trafna”: niepewne.** Średnia to „wartość dodana”, ale przy publicznych prognozach pozostałych modeli i jawnych wagach wkład WN3 da się odtworzyć prostym rachunkiem. Bez zgody Google nie włączać.

## Jak wpasować WN3 w ranking

- **Wyprzedzenie jak w Open-Meteo.** `previous_dayN` to prognoza wydana 24·N h przed czasem ważności, a w modelach globalnych z najnowszego przebiegu 6-godzinnego. Dla WN3: najnowszy przebieg 00/06/12/18 UTC nie późniejszy niż czas ważności − 24·N h (`forecast_hour` 24N…24N+5). Godzinnych przebiegów pośrednich nie używamy, żeby nie dać WN3 przewagi świeższego startu.
- **Zmienne:** `temperature_2m_mean`, `total_cloud_cover_mean`, `total_precipitation_1hr_mean` (m → mm).
  - **Nie** używać `imerg_tp_1hr`: to opad kalibrowany do IMERG, a IMERG jest naszym sędzią opadu. Wynik byłby z góry wygrany.
  - Także `total_precipitation_1hr` model uczył się częściowo na IMERG. To przewaga, której nie ma żaden inny model. Pełna uczciwość dopiero przy deszczomierzach ze stacji automatycznych (zbierane od 2026-10-21). Zaznaczyć w „O projekcie”.
- **Średnia ensemble a modele deterministyczne.** Średnia z 64 członków jest gładsza. Zwykle wygrywa w MAE, a w ETS ≥ 1 mm bywa różnie (rozmyty słaby opad). To nadal najlepsza pojedyncza prognoza WN3, jaką da się porównać. Alternatywą jest mediana (`p50`), do sprawdzenia na danych.
- **Obliczenia w GEE, jak dla IMERG.** Na dobę danych potrzeba ok. 7 wyprzedzeń × ~37 obrazów godzinowych, czyli ~260 obrazów, 3 pasma i `reduceRegions` na 4 313 komórkach. Szacunek: kilkadziesiąt–kilkaset EECU-s na dobę, < 2 EECU-h/mies. z limitu 150. Rozruch 30 dni ok. 1 EECU-h. Open-Meteo nie jest potrzebne. Do sprawdzenia po uzyskaniu dostępu: czy piksele 0,1° WN3 pokrywają się z naszymi komórkami (rogi na wielokrotnościach 0,1°), czy są przesunięte o pół piksela.
- **Model „tylko w rankingu”.** WN3 jest w tabeli rankingu i w liczbie modeli. Strona go nie pobiera i nie pokazuje jego prognozy. Tryb „najmniej trafna” przy WN3 na ostatnim miejscu pokazuje zamiast niego ostatni model, który da się wyświetlić, z adnotacją. Tryb „optymistyczna” i średnia WN3 pomijają. Jako model dodatkowy WN3 nie blokuje publikacji rankingu.

## Do zrobienia przez człowieka

1. Wypełnić **WeatherNext Data Request**: https://docs.google.com/forms/d/e/1FAIpQLSeCf1JY8G78UDWzbm0ly9kJxfSjUIJT5WyMR_HiNqCm-IHIBg/viewform
   - konto Google używane w Earth Engine;
   - jeśli formularz na to pozwala, także konto serwisowe potoku `lepszapogoda-pipeline@gen-lang-client-0589028343.iam.gserviceaccount.com` i ID projektu `gen-lang-client-0589028343`, bo w Actions GEE działa na koncie serwisowym, nie na osobistym;
   - cel: niekomercyjna weryfikacja trafności prognoz dla Polski.
2. (Opcjonalnie) zapytać weathernext@google.com, czy wolno włączyć WN3 do publicznie pokazywanej średniej modeli albo pokazać jego prognozę.

## Źródła

- Katalog GEE 0,1°: https://developers.google.com/earth-engine/datasets/catalog/projects_gcp-public-data-weathernext_assets_weathernext_3_0_0_0p1deg
- WeatherNext w Earth Engine: https://developers.google.com/weathernext/guides/earth-engine
- Opis modelu: https://developers.google.com/weathernext/guides/models
- Dostęp: https://developers.google.com/weathernext/guides/access-forecast
- Warunki dla danych bieżących: https://storage.googleapis.com/weathernext-public/terms-of-use.pdf
- Open-Meteo, definicja `previous_dayN`: https://open-meteo.com/en/docs/previous-runs-api
