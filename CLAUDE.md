# lepszapogoda.pl

Porównywarka trafności modeli pogodowych dla Polski. Projekt realizuje agent AI według specyfikacji.

- **Specyfikacja (jedyne źródło wymagań):** `docs/SPEC.md`. Zacznij od §0 (zasady pracy), §13 (etapy) i §17 (otwarte decyzje).
- **Decyzje:** `docs/DECISIONS.md`. Każdą decyzję podjętą bez człowieka dopisz tutaj.
- **Raporty z etapów:** `docs/reports/etap-N.md`.
- **Geneza projektu** (rozmowa, z której powstała specyfikacja): `docs/history/`. Tylko kontekst, nie wymagania.
- **Spike'i i eksperymenty:** `spike/`. Kod jednorazowy, nie jest częścią produktu. Dane w `spike/data/` są w `.gitignore`.

Aktualny stan: zakończone Etapy 0a i 0b (`docs/reports/`). Wszystkie decyzje z §17 są zamknięte (SPEC v0.9). MVP = punkt + średnia ważona; obszary, burze i „Chmury teraz” to v1.1. Etap 0 w toku: test GEE zrobiony (`docs/reports/etap-0-gee.md`), pakiet `lepszapogoda/` z siatką i testami gotowy. Brakuje kont z `docs/HUMAN_TODO.md` (GitHub, R2, mydevil, konto serwisowe GEE) i sondy hostingu.

Lokalnie: `.\.venv\Scripts\python -m pytest`, `.\.venv\Scripts\ruff check .`. Earth Engine: zmienna `EE_PROJECT` z ID projektu Cloud człowieka (zapytaj, jeśli nie jest ustawiona).

Środowisko lokalne: Windows, Python 3.14 (docelowo 3.11 na mydevil i w Actions). Kod i komentarze po angielsku, UI i dokumentacja po polsku.
