# Etap 2 — strona (stan na 2026-10-14)

Strona działa pod **https://lepszapogoda.pl** (mydevil, Passenger, Flask). Kod: `web/`, `lepszapogoda/{blend,forecast,optimistic,ranking}.py`.

## Co zrobiono

- **Widok 1 (`/`):**
  - pełnoekranowa mapa MapLibre (OpenFreeMap; warstwa „Satelita” EOX Sentinel-2);
  - wyszukiwarka Photon z podpowiedziami (debounce, klawiatura, cache 7 dni), kliknięcie na mapie z nazwą miejsca z odwrotnego geokodowania, „Użyj mojej lokalizacji”;
  - trzy przyciski aktywne dopiero po wybraniu miejsca w Polsce.
- **Widok 2 (`/prognoza/{slug}/{lat},{lon}/{tryb}`):**
  - **renderowany na serwerze:** 7 kafelków dni z 12 własnymi ikonami SVG, temperatura max/min, opad, porywy, informacyjne ryzyko burzy;
  - **dni 5–7 jako „mniej pewne”:** przygaszone, ze „szansą opadu” zamiast mm (Etap 0b);
  - **wykresy uPlot dla wybranego dnia:** temperatura z pasem rozrzutu między modelami, opad z zachmurzeniem, wiatr;
  - **zwijany ranking trafności z przełącznikiem trybów.**
- **Tryby:**
  - **trafna:** średnia modeli, dla temperatury wagi z rankingu (§8.10), bez rankingu wagi równe i komunikat „zbieramy dane”;
  - **optymistyczna:** liczona w locie (§8.5);
  - **najmniej trafna:** ostatni model z rankingu.

  Modele kończące horyzont (Météo-France po ~4 dniach) wypadają ze średniej, a w trybie jednego modelu pojawia się adnotacja.
- **`/o-projekcie`** (metoda, zastrzeżenia §8.6, licencje), **`/healthz`** (wiek publikacji rankingu), **`/api/forecast`**.
- **Bezpieczeństwo (§0 pkt 8):**
  - walidacja współrzędnych (bbox ± 0,5°), sluga i trybu, przekierowanie 301 na postać kanoniczną;
  - autoescape;
  - nagłówki CSP, `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`.
- **Hosting:**
  - virtualenv wybierany przez `passenger_wsgi.py`;
  - statyczne pliki serwowane przez nginx;
  - cache plikowy prognoz z własnym budżetem Open-Meteo;
  - crony `pull_rankings` (30 min) i `cleanup` (codziennie);
  - HTTPS (Let's Encrypt, włączony przez człowieka) z przekierowaniem z http.

## Pomiary

- **Czas odpowiedzi:** `/` 0,09 s, prognoza przy pustym cache 0,37 s (łącznie z Open-Meteo z serwera), przy pełnym cache ~0,1 s. Cel z §13: < 1,5 s.
- **Testy:** 138 (w tym 35 dla strony), ruff czysty, CI na Pythonie 3.11.

## Co nie działa lub czeka

- **Ranking:** strona pokazuje „zbieramy dane”, dopóki potok nie opublikuje pierwszego rankingu (pobieranie wstecz do ok. 24.10).
- **Odłożone:** geolokalizacja po IP, podsumowanie „Ten tydzień” i etykiety na warstwie satelitarnej (szczegóły w `docs/DECISIONS.md`).
- **Mapa w tle:** w automatycznym podglądzie (karta w tle, `document.hidden`) MapLibre nie kończy ładowania stylu. W widocznej karcie powinno działać. **Do potwierdzenia przez człowieka w zwykłej przeglądarce.**
- **Wdrożenie:** `deploy.yml` (deploy z Actions po zielonym CI) wymaga osobnego klucza SSH jako sekretu.
- **Do zrobienia:** `docs/QA.md`, czyli ręczne scenariusze: telefon 360 px, brak JS, brak geolokalizacji.
