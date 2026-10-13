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

## Potrzebne do Etapu 2 (strona)

- [x] **mydevil:** domena `lepszapogoda.pl` typu Python (DNS mydevil, wskazuje na web37), klucz SSH agenta dodany (2026-10-13).
- [ ] **Token R2 tylko do odczytu** dla hostingu: Cloudflare → R2 → *Manage API tokens* → uprawnienie **Object Read only**, ograniczone do bucketu `lepszapogoda-data`. Wartości wpisujesz sam na serwerze do `~/.bash_profile` (nie do czatu):
  `export R2_ENDPOINT=…`, `export R2_BUCKET=lepszapogoda-data`, `export R2_KEY_RO=…`, `export R2_SECRET_RO=…`
- [ ] **Klucz SSH do deployu z GitHub Actions** (§16 pkt 3): osobny klucz jako sekret `DEPLOY_SSH_KEY`. Przygotuje go agent, gdy będzie gotowy `deploy.yml`.
- [ ] Klucz licencyjny MaxMind GeoLite2.

## v1.1

- [ ] Konto EUMETSAT (wyładowania MTG LI, §8.9).
