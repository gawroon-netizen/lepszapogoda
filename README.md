# lepszapogoda.pl

Porównywarka trafności modeli pogodowych dla Polski. Wymagania: [docs/SPEC.md](docs/SPEC.md), decyzje: [docs/DECISIONS.md](docs/DECISIONS.md), raporty z etapów: [docs/reports/](docs/reports/).

## Struktura (stan obecny)

- `lepszapogoda/`: pakiet współdzielony przez potok i stronę WWW.
  - `grid.py`: siatka 0,1°, `cell_id`, geometria, pole powierzchni, ułamek komórki w Polsce.
  - `data/poland_cells.json`: `pl_frac` dla komórek dotykających Polski.
  - `openmeteo.py`: klient Open-Meteo (Previous Runs i Forecast) z budżetem limitów, opisanym w `docs/api-budget.md`.
- `pipeline/`: potok danych.
  - `grid/build_cells.py`: buduje listę komórek. Wymaga Earth Engine.
  - `grid/poland_cells.parquet`: lista komórek.
  - `gee/auth.py`: logowanie do Earth Engine.
  - `ingest/forecasts.py`: dzienne pobieranie prognoz archiwalnych (rotacja, uzupełnianie luk, Parquet w `data/`).
  - `ingest/imgw.py`: stacje IMGW. Odpytywanie co godzinę (`poll`), dobowe Tmax/Tmin (`daily`), paczki miesięczne (`archive`).
  - `ingest/satellite.py`: IMERG (opady, D-2) i MODIS Terra/Aqua (chmury, D-4) per komórka z Earth Engine.
  - `grid/build_stations.py`: lista stacji IMGW ze współrzędnymi, zapisywana w `lepszapogoda/data/imgw_stations.json`.
  - `storage.py`: synchronizacja `data/` z R2 (`pull` na starcie, `push` na końcu przebiegu w CI).
  - `verify/`: weryfikacja i ranking. Wartości dobowe z prognoz (`aggregate`), składniki dzienne (`components`), ranking i wagi średniej (`ranking`), zadanie (`run`).
  - `publish.py`: paczka z rankingiem do R2 (`publish/`) z bramką jakości.
- `web/cron/pull_rankings.py`: cron hostingu, pobiera opublikowany ranking i podmienia `web/data/rankings/`.
- `.github/workflows/`:
  - `ci.yml`: ruff i pytest na Pythonie 3.11 przy każdym pushu.
  - `pipeline-hourly.yml`: co godzinę o :07. Odpytanie IMGW, potem pobieranie prognoz w ramach godzinowego limitu Open-Meteo.
  - `pipeline-daily.yml`: codziennie o 05:30 UTC. Dobowe Tmax/Tmin, paczki IMGW, obserwacje satelitarne (gdy jest konto serwisowe GEE).
  - `setup-check.yml`: ręczna kontrola sekretów R2 i GEE (bez wypisywania wartości).
- `tools/check_setup.py`: kod kontroli sekretów.
- `workers/imgw-poller/`: Cloudflare Worker odpytujący API IMGW o :05 i :35 i zapisujący surowe odpowiedzi do R2. Wdrożenie (Node.js; w PowerShellu `npx.cmd`, bo `npx.ps1` blokuje zasada wykonywania skryptów):

  ```powershell
  cd workers\imgw-poller
  npx.cmd --yes wrangler@4 login    # raz, logowanie w przeglądarce
  npx.cmd --yes wrangler@4 deploy
  ```
- `tests/`, `pipeline/tests/`: testy.
- `spike/`: jednorazowe eksperymenty z Etapów 0a i 0b oraz testu GEE. Nie są częścią produktu.

## Uruchomienie lokalne (Windows, PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt -e .
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\ruff check .
```

Przebudowa listy komórek (potrzebne tylko przy zmianie siatki lub granic):

```powershell
$env:EE_PROJECT = "<id projektu Google Cloud>"   # wcześniej: earthengine authenticate
.\.venv\Scripts\python -m pipeline.grid.build_cells
```

Pobieranie prognoz archiwalnych (dane trafiają do `data/`, poza repozytorium):

```powershell
.\.venv\Scripts\python -m pipeline.ingest.forecasts --dry-run          # plan i koszt
.\.venv\Scripts\python -m pipeline.ingest.forecasts --max-requests 10  # ograniczony przebieg
```

Obserwacje:

```powershell
.\.venv\Scripts\python -m pipeline.ingest.imgw poll                       # co godzinę
.\.venv\Scripts\python -m pipeline.ingest.imgw daily                      # raz dziennie, za wczoraj
.\.venv\Scripts\python -m pipeline.ingest.imgw archive --year 2026 --month 9
.\.venv\Scripts\python -m pipeline.ingest.satellite                       # wymaga EE_PROJECT
```

W CI zamiast `EE_PROJECT` używany jest sekret `GEE_SERVICE_ACCOUNT_JSON` (SPEC §9).

Docelowa wersja Pythona: 3.11 (mydevil, GitHub Actions). Kod nie używa składni nowszej niż 3.11.
