# Do zrobienia przez człowieka

Szczegóły w SPEC §9 i §16.

## Zrobione

- [x] Git zainstalowany, lokalne repozytorium istnieje.
- [x] Earth Engine: projekt Cloud zarejestrowany, logowanie lokalne (`earthengine authenticate`) działa.

## Potrzebne do Etapu 0 i 1 (potok w GitHub Actions)

- [ ] **Repozytorium na GitHubie** `lepszapogoda` (§16 pkt 1). Po utworzeniu agent podepnie lokalne repozytorium (`git remote add origin …`, `git push`).
- [ ] **Konto serwisowe GEE** w tym samym projekcie Cloud, role Earth Engine Resource Writer i Service Usage Consumer, klucz JSON jako sekret `GEE_SERVICE_ACCOUNT_JSON`. Nie wklejać go do czatu ani do repozytorium.
- [ ] **Cloudflare R2:** bucket `lepszapogoda-data`, klucze RW do sekretów GitHub, klucze RO na hosting (§9, §16 pkt 2).
- [ ] *(opcjonalnie)* Osobny projekt Cloud „lepszapogoda” zamiast automatycznego `gen-lang-client-…` z AI Studio. Limit GEE liczy się na projekt.

## Potrzebne do Etapu 2 (strona)

- [ ] **mydevil:** domena typu Python 3.11, klucz SSH do deployu, Redis (§16 pkt 3 i 6).
- [ ] **Domena** `lepszapogoda.pl`.
- [ ] Klucz licencyjny MaxMind GeoLite2.

## v1.1

- [ ] Konto EUMETSAT (wyładowania MTG LI, §8.9).
