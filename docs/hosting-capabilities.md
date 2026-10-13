# Możliwości hostingu (mydevil, s37)

Data: 2026-10-13. Źródło: `tools/hosting_probe.py` uruchomiony przez SSH (wynik niżej, bez zmian poza usunięciem kolorów terminala).

## Wnioski

- **Python 3.11.13** jest dostępny (`/usr/local/bin/python3.11`), FreeBSD 14.3. Virtualenv działa.
- **Wszystkie biblioteki strony instalują się w kilka sekund** (flask, jinja2, requests, redis, geoip2, boto3). Drobne rozszerzenia C kompilują się bez problemu (markupsafe, maxminddb, aiohttp), bo dostępne są gcc, clang i rustc.
- **Brak gotowych pakietów numpy, pandas i pyarrow dla FreeBSD.** Kompilacja byłaby długa i obciążałaby współdzielony serwer. Zgodnie z §14 na hostingu nie ma pandas ani Parquet: strona czyta JSON, a cała analiza danych zostaje w GitHub Actions.
- **Limit 40 procesów na konto** (wspólny dla wszystkich stron na koncie). Passenger nie może mieć wielu workerów, a crony muszą być krótkie (`nice`).
- **Pamięć do 3 GB na proces, CPU bez limitu czasu.** Średnia z 5 modeli dla jednego punktu (168 h × 6 zmiennych) liczy się w czystym Pythonie w ~1,5 ms, więc „najbardziej trafna” i „optymistyczna” mogą być liczone w locie.
- **Redis:** jest `redis-server`, ale nie ma go w panelu (`devil redis` nie istnieje). Własny Redis wymagałby rezerwacji portu i stałego procesu. **Decyzja: w MVP cache plikowy** (fallback z §7.4 staje się podstawą), Redis dopiero gdy ruch tego wymaga.
- **Struktura domeny:** `~/domains/lepszapogoda.pl/public_python/`. Passenger szuka tam `passenger_wsgi.py`, `public/` jest serwowany bezpośrednio jako pliki statyczne, a `tmp/restart.txt` restartuje aplikację.
- **Konto ma kilkanaście innych stron.** Wdrożenie dotyka wyłącznie `~/domains/lepszapogoda.pl`.

---

# Surowy wynik sondy

host: s37.mydevil.net, FreeBSD-14.3-RELEASE-p19-amd64-64bit-ELF, probe python 3.11.13

## Python interpreters

- python3.8: /usr/local/bin/python3.8 -> 3.8.20
- python3.9: /usr/local/bin/python3.9 -> 3.9.23
- python3.10: /usr/local/bin/python3.10 -> 3.10.18
- python3.11: /usr/local/bin/python3.11 -> 3.11.13
- python3.12: /usr/local/bin/python3.12 -> 3.12.11

## Limits

- RLIMIT_CPU: soft=9223372036854775807 hard=9223372036854775807
- RLIMIT_AS: soft=9223372036854775807 hard=9223372036854775807
- RLIMIT_DATA: soft=34359738368 hard=34359738368
- RLIMIT_NPROC: soft=40 hard=40
- RLIMIT_NOFILE: soft=2000 hard=2000

```
number of pseudoterminals                (-P) unlimited
socket buffer size           (bytes, -b) unlimited
core file size              (blocks, -c) 1048576
data seg size               (kbytes, -d) 33554432
file size                   (blocks, -f) unlimited
max kqueues                         (-k) unlimited
max locked memory           (kbytes, -l) 3072000
max memory size             (kbytes, -m) 3072000
open files                          (-n) 2000
pipe size                (512 bytes, -p) 1
stack size                  (kbytes, -s) 524288
cpu time                   (seconds, -t) unlimited
max user processes                  (-u) 40
virtual memory              (kbytes, -v) unlimited
swap size                   (kbytes, -w) unlimited
```

- home filesystem free: 2056 GB (account quota: see `devil info account`)

```
Informacje o koncie

        Nazwa użytkownika: mojabramka
                   Pakiet: MD1
           Konto ważne do: 2027-02-15 00:32:17


Serwery

Serwery poczty
              Serwer SMTP: mail37.mydevil.net
              Serwer IMAP: mail37.mydevil.net
              Serwer POP3: mail37.mydevil.net

Serwery bazodanowe
             Serwer MySQL: mysql37.mydevil.net
        Serwer PostgreSQL: pgsql37.mydevil.net
           Serwer MongoDB: mongo37.mydevil.net

Serwery DNS
            Serwer DNS #1: dns1.mydevil.net
            Serwer DNS #2: dns2.mydevil.net


Narzędzia webowe

         DevilWEB (panel): https://panel37.mydevil.net/
          Panel płatności: https://platnosci.admin.net.pl/
      Roundcube (webmail): https://poczta.mydevil.net/
               phpMyAdmin: https://pma.mydevil.net/
               PhpPgAdmin: https://pga.mydevil.net/
      RockMongo (MongoDB): https://moa.mydevil.net/
       Matomo (WWW stats): https://stats37.mydevil.net


Inne

                  Binexec: Włączony
                      2FA: Wyłączony
```

## Tools

- git: /usr/local/bin/git
- redis-cli: /usr/local/bin/redis-cli
- redis-server: /usr/local/bin/redis-server
- memcached: /usr/local/bin/memcached
- cc: /usr/bin/cc
- gcc: /usr/local/bin/gcc
- clang: /usr/bin/clang
- make: /usr/bin/make
- cmake: /usr/local/bin/cmake
- rustc: /usr/local/bin/rustc
- `devil redis`: exit 3: [Błąd] Moduł o podanej nazwie nie istnieje

## pip in a fresh virtualenv (python3.11)

- venv: exit 0 (7 s)
- install flask: OK (7 s)
- install jinja2: OK (1 s)
- install requests: OK (3 s)
- install redis: OK (2 s)
- install geoip2: OK (11 s)
- install boto3: OK (5 s)
- installed: aiohappyeyeballs==2.7.1, aiohttp==3.14.5, aiosignal==1.4.0, attrs==26.1.0, blinker==1.9.0, boto3==1.43.112, botocore==1.43.112, certifi==2026.7.22, charset-normalizer==3.5.2, click==8.5.0, flask==3.1.3, frozenlist==1.8.0, geoip2==5.3.0, idna==3.20, itsdangerous==2.2.0, jinja2==3.1.6, jmespath==1.1.0, markupsafe==3.0.4, maxminddb==3.2.0, multidict==7.1.0, pip==26.2.1, propcache==0.5.4, python-dateutil==2.9.0.post0, redis==8.1.0, requests==2.34.2, s3transfer==0.19.2, setuptools==65.5.0, six==1.17.0, typing_extensions==4.16.0, urllib3==2.8.0, werkzeug==3.1.9, yarl==1.25.1
- markupsafe C speedups: yes

## Binary wheels available (no source builds attempted)

- numpy: no wheel (would compile from source)
- pandas: no wheel (would compile from source)
- pyarrow: no wheel (would compile from source)
- markupsafe: no wheel (would compile from source)
- maxminddb: no wheel (would compile from source)

## CPU timing (blend of 5 models x 168 h x 6 variables, pure Python)

- one blend: 1.47 ms

## Environment

- PATH: /sbin:/bin:/usr/sbin:/usr/bin:/usr/local/sbin:/usr/local/bin
- HOME: /home/mojabramka
