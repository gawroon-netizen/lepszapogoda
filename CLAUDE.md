# lepszapogoda.pl

Porównywarka trafności modeli pogodowych dla Polski. Projekt realizuje agent AI według specyfikacji.

- **Specyfikacja (jedyne źródło wymagań):** `docs/SPEC.md`. Zacznij od §0 (zasady pracy), §13 (etapy) i §17 (otwarte decyzje).
- **Decyzje:** `docs/DECISIONS.md`. Każdą decyzję podjętą bez człowieka dopisz tutaj.
- **Raporty z etapów:** `docs/reports/etap-N.md`.
- **Geneza projektu** (rozmowa, z której powstała specyfikacja): `docs/history/`. Tylko kontekst, nie wymagania.
- **Spike'i i eksperymenty:** `spike/`. Kod jednorazowy, nie jest częścią produktu. Dane w `spike/data/` są w `.gitignore`.

Aktualny stan: zakończone Etapy 0a i 0b (`docs/reports/`). Decyzja o łączeniu modeli zapadła (§8.10). Otwarte pozostają §17 pkt 2–4; następny krok to Etap 0 z §13.

Środowisko lokalne: Windows, Python 3.14 (docelowo 3.11 na mydevil i w Actions). Kod i komentarze po angielsku, UI i dokumentacja po polsku.
