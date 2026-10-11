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

W CI zamiast `EE_PROJECT` używany jest sekret `GEE_SERVICE_ACCOUNT_JSON` (SPEC §9).

Docelowa wersja Pythona: 3.11 (mydevil, GitHub Actions). Kod nie używa składni nowszej niż 3.11.
