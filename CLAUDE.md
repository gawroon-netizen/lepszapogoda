# lepszapogoda.pl

Porównywarka trafności modeli pogodowych dla Polski. Projekt realizuje agent AI według specyfikacji.

- **Specyfikacja (jedyne źródło wymagań):** `docs/SPEC.md`. Zacznij od §0 (zasady pracy), §13 (etapy) i §17 (otwarte decyzje).
- **Decyzje:** `docs/DECISIONS.md`. Każdą decyzję podjętą bez człowieka dopisz tutaj.
- **Raporty z etapów:** `docs/reports/etap-N.md`.
- **Geneza projektu** (rozmowa, z której powstała specyfikacja): `docs/history/`. Tylko kontekst, nie wymagania. Plik jest prywatny: tylko lokalnie, w `.gitignore`, nie publikować.
- **Repozytorium:** https://github.com/gawroon-netizen/lepszapogoda (publiczne). Autor commitów: adres noreply GitHuba.
- **Spike'i i eksperymenty:** `spike/`. Kod jednorazowy, nie jest częścią produktu. Dane w `spike/data/` są w `.gitignore`.

Aktualny stan: zakończone Etapy 0a i 0b (`docs/reports/`). Wszystkie decyzje z §17 są zamknięte (SPEC v0.9). MVP = punkt + średnia ważona; obszary, burze i „Chmury teraz” to v1.1. Etap 1 (potok) kompletny w kodzie: Actions + R2 + Cloudflare Worker (IMGW), weryfikacja, ranking, publikacja z bramką jakości. Rozruch prognoz (30 dni wstecz) trwa do ok. 2026-10-24, do tego czasu brak opublikowanego rankingu. Etap 2 (strona) działa na https://lepszapogoda.pl (`docs/reports/etap-2.md`). Wdrożenie ręcznie: `ssh … 'bash -lc "bash ~/domains/lepszapogoda.pl/app/deploy/deploy.sh"'` (dostęp: pamięć agenta, nie repozytorium).

Lokalny podgląd strony: `.claude/launch.json` („web”, port 5057). Pliki statyczne mają cache 1 dzień, więc po zmianie JS/CSS potrzebne twarde przeładowanie.

Logi przebiegów w Actions wymagają uwierzytelnienia. Lokalnie można użyć tokenu z `git credential fill` (Git Credential Manager), nigdy go nie wypisując.

Lokalnie: `.\.venv\Scripts\python -m pytest`, `.\.venv\Scripts\ruff check .`. Earth Engine: zmienna `EE_PROJECT` z ID projektu Cloud człowieka (zapytaj, jeśli nie jest ustawiona).

Środowisko lokalne: Windows, Python 3.14 (docelowo 3.11 na mydevil i w Actions). Kod i komentarze po angielsku, UI i dokumentacja po polsku.
