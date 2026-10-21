# Do zrobienia przez człowieka

Szczegóły w SPEC §9 i §16.

## Zrobione

- [x] Git zainstalowany, repozytorium https://github.com/gawroon-netizen/lepszapogoda (publiczne).
- [x] Earth Engine: projekt Cloud zarejestrowany, logowanie lokalne (`earthengine authenticate`) działa.
- [x] Cloudflare R2: bucket i klucze w sekretach. `setup-check` przeszedł zapis, odczyt, usunięcie i listowanie (2026-10-12).
- [x] Konto serwisowe GEE `lepszapogoda-pipeline` (Earth Engine Resource Admin, Service Usage Consumer), sekret `GEE_SERVICE_ACCOUNT_JSON`. `setup-check` w pełni zielony, pierwszy przebieg dzienny pobrał IMERG i MODIS (2026-10-13).

## Teraz

- [ ] *(opcjonalnie)* *Settings → General:* wyłączyć Wiki i Projects, włączyć „Automatically delete head branches” (§16 pkt 1).
- [ ] *(opcjonalnie)* *Settings → Branches:* reguła dla `main` z wymaganym statusem `ci` (§16 pkt 1). Pushe agenta idą bezpośrednio na `main`, więc reguła musi na to pozwalać albo przechodzimy na pull requesty.
- [ ] *(opcjonalnie)* Osobny projekt Cloud „lepszapogoda” zamiast automatycznego `gen-lang-client-…` z AI Studio.
- [ ] **WeatherNext 3: wniosek o dostęp** (formularz „WeatherNext Data Request”). Konto Google z Earth Engine, w miarę możliwości także konto serwisowe `lepszapogoda-pipeline@gen-lang-client-0589028343.iam.gserviceaccount.com`. Szczegóły i link: `docs/reports/rozpoznanie-weathernext-3.md`.

## Potrzebne do Etapu 2 (strona)

- [x] **mydevil:** domena `lepszapogoda.pl` typu Python (DNS mydevil, wskazuje na web37), klucz SSH agenta dodany (2026-10-13).
- [x] **Token R2 tylko do odczytu** w `~/.bash_profile` na serwerze. `python -m tools.check_setup r2-ro`: odczyt OK, zapis odrzucony (2026-10-14).
- [x] ~~Plik wykonywalny Python w panelu~~: niepotrzebne. mydevil pozwala go ustawić tylko przy dodawaniu strony (`devil www add … python <plik> <konfiguracja>`), więc `passenger_wsgi.py` sam przełącza się na `venv/bin/python` (`os.execl`, standardowy wzorzec Passengera).
- [x] **HTTPS** dla lepszapogoda.pl (Let's Encrypt, włączony w panelu, 2026-10-14), http → https działa.
- [ ] **Sprawdź mapę na https://lepszapogoda.pl** w zwykłej przeglądarce (komputer i telefon): czy widać mapę Polski, czy działa wyszukiwarka, kliknięcie i przyciski. Automatyczny podgląd agenta nie renderował mapy w karcie w tle.
- [ ] **Klucz SSH do deployu z GitHub Actions** (§16 pkt 3): osobny klucz jako sekret `DEPLOY_SSH_KEY`. Przygotuje go agent, gdy będzie gotowy `deploy.yml`.
- [ ] Klucz licencyjny MaxMind GeoLite2.

## v1.1

- [ ] Konto EUMETSAT (wyładowania MTG LI, §8.9).
