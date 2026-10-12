# Do zrobienia przez człowieka

Szczegóły w SPEC §9 i §16.

## Zrobione

- [x] Git zainstalowany, repozytorium https://github.com/gawroon-netizen/lepszapogoda (publiczne).
- [x] Earth Engine: projekt Cloud zarejestrowany, logowanie lokalne (`earthengine authenticate`) działa.
- [x] Cloudflare R2: bucket i klucze w sekretach. `setup-check` przeszedł zapis, odczyt, usunięcie i listowanie (2026-10-12).

## Teraz

- [ ] **Konto serwisowe GEE** w projekcie Cloud używanym do Earth Engine:
  1. role Earth Engine Resource Writer i Service Usage Consumer,
  2. klucz JSON (cała zawartość pliku) jako sekret `GEE_SERVICE_ACCOUNT_JSON`,
  3. potem usuń plik z dysku.

  Do tego czasu przebieg dzienny pomija obserwacje satelitarne. Kontrola: *Actions → setup-check → Run workflow*.
- [ ] *(opcjonalnie)* *Settings → General:* wyłączyć Wiki i Projects, włączyć „Automatically delete head branches” (§16 pkt 1).
- [ ] *(opcjonalnie)* *Settings → Branches:* reguła dla `main` z wymaganym statusem `ci` (§16 pkt 1). Pushe agenta idą bezpośrednio na `main`, więc reguła musi na to pozwalać albo przechodzimy na pull requesty.
- [ ] *(opcjonalnie)* Osobny projekt Cloud „lepszapogoda” zamiast automatycznego `gen-lang-client-…` z AI Studio.

## Potrzebne do Etapu 2 (strona)

- [ ] **mydevil:** domena typu Python 3.11, klucz SSH do deployu, Redis (§16 pkt 3 i 6). Klucze R2 tylko do odczytu na hosting.
- [ ] **Domena** `lepszapogoda.pl`.
- [ ] Klucz licencyjny MaxMind GeoLite2.

## v1.1

- [ ] Konto EUMETSAT (wyładowania MTG LI, §8.9).
