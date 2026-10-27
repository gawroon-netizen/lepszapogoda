"""Polish UI texts (SPEC §15: Polish only, templates ready for i18n)."""

MODELS = {
    "ecmwf_ifs": (
        "ECMWF IFS",
        "Model Europejskiego Centrum Prognoz Średnioterminowych, uznawany za wzorzec modeli globalnych.",
    ),
    "ecmwf_aifs025_single": ("ECMWF AIFS", "Model oparty na sztucznej inteligencji, rozwijany przez ECMWF."),
    "icon_seamless": ("DWD ICON", "Model niemieckiej służby DWD; na pierwsze dni nad Polską w rozdzielczości do 2 km."),
    "gfs_seamless": ("NOAA GFS", "Amerykański model globalny NOAA."),
    "meteofrance_seamless": (
        "Météo-France",
        "Modele francuskiej służby meteorologicznej (AROME, ARPEGE); prognoza na 4 dni.",
    ),
    "knmi_harmonie_arome_europe": (
        "KNMI HARMONIE-AROME",
        "Model holenderskiej służby KNMI dla Europy w rozdzielczości 5,5 km; prognoza na ok. 2,5 dnia.",
    ),
    "ncep_aigfs025": (
        "NOAA AIGFS",
        "Model amerykańskiej NOAA oparty na sztucznej inteligencji; startuje z tych samych danych co GFS.",
    ),
}

MODES = {
    "trafna": "Najbardziej trafna",
    "optymistyczna": "Najbardziej optymistyczna",
    "najmniej-trafna": "Najmniej trafna",
}

WEEKDAYS = ["pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."]

ICONS = {
    "slonecznie": "słonecznie",
    "malo-chmur": "mało chmur",
    "czesciowe": "częściowe zachmurzenie",
    "pochmurno": "pochmurno",
    "zachmurzenie": "duże zachmurzenie",
    "mzawka": "słaby deszcz",
    "deszcz": "deszcz",
    "ulewa": "ulewa",
    "snieg": "śnieg",
    "deszcz-snieg": "deszcz ze śniegiem",
    "burza": "burza",
    "wietrznie": "wietrznie",
}

T = {
    "title": "lepszapogoda.pl: który model pogody trafia u Ciebie",
    "search_placeholder": "Wpisz miejscowość albo kliknij na mapie",
    "show_forecast": "Pokaż prognozę",
    "outside": "Prognozy są dostępne tylko dla miejsc w Polsce.",
    "about": "O projekcie",
    "change": "zmień",
    "layer_map": "Mapa",
    "layer_sat": "Satelita",
    "blend_intro": (
        "Prognoza łączy {n} modeli. Większą wagę przy temperaturze mają te, "
        "które w tej okolicy trafiały ostatnio lepiej."
    ),
    "blend_why": "Średnia z kilku modeli myli się zwykle rzadziej niż którykolwiek z nich osobno.",
    "blend_equal": (
        "Prognoza łączy {n} modeli z równymi wagami. Ranking trafności dla tej okolicy jeszcze powstaje: zbieramy dane."
    ),
    "optimistic_intro": "{model} obiecuje na najbliższe 3 dni najcieplej i najsuszej.",
    "optimistic_rank": "W rankingu trafności dla tej okolicy jest {n}. z {m}.",
    "least_intro": "{model} przewidywał w tej okolicy najmniej trafnie ({window}).",
    "least_none": "Ranking trafności dla tej okolicy jeszcze powstaje, więc pokazujemy średnią modeli.",
    "ranking_title": "Ranking trafności",
    "ranking_window": "30 dni: {window}",
    "ranking_none": (
        "Ranking dla tej okolicy jeszcze powstaje. "
        "Pierwsze wyniki pojawią się po zebraniu 20 dni porównań prognoz z pomiarami."
    ),
    "unranked": "Bez oceny, bo zbieramy jeszcze dane: {models}. Nie wchodzą do prognozy łączonej.",
    "temp_none": "Temperatura poza rankingiem dla tej okolicy (brak stacji IMGW w promieniu 60 km lub za mało danych).",
    "uncertain": "mniej pewne",
    "precip_chance": "szansa opadu {p}%",
    "night_precip": "w nocy",
    "storm_possible": "możliwa burza",
    "storm_likely": "prawdopodobna burza",
    "model_horizon": "{model} liczy prognozę tylko na {d} dni.",
    "stale": "Nie udało się pobrać najnowszej prognozy; pokazujemy ostatnią zapisaną.",
    "wind_note": "Wiatr nie wchodzi do rankingu trafności.",
    "disclaimer": "Prognozy nie zastępują ostrzeżeń IMGW. Ranking dotyczy zachmurzenia, opadów i temperatury.",
    "unavailable": "Prognoza jest chwilowo niedostępna. Spróbuj ponownie za kilka minut.",
    "run_time": "Prognoza pobrana: {t}",
}

# /stan-danych: pipeline status page
STATUS_SOURCES = {
    "imerg": "Opady: satelity NASA IMERG",
    "modis_terra": "Zachmurzenie: satelita MODIS Terra",
    "modis_aqua": "Zachmurzenie: satelita MODIS Aqua",
    "imgw_daily": "Temperatura: stacje synoptyczne IMGW",
    "imgw_meteo_daily": "Stacje automatyczne IMGW (jeszcze poza rankingiem)",
    "imgw_synop": "Stacje synoptyczne IMGW (co 30 min)",
    "imgw_meteo": "Stacje automatyczne IMGW (co 5 min)",
}
STATUS_WORKFLOWS = {
    "pipeline-hourly": "Pobieranie prognoz (co godzinę)",
    "pipeline-daily": "Obserwacje i ranking (codziennie)",
    "setup-check": "Kontrola konfiguracji",
}
STATUS_INVALID_WORKFLOW = "Błędny plik przebiegu"
STATUS_RESULTS = {
    "success": "OK",
    "failure": "błąd",
    "cancelled": "przerwany",
    "timed_out": "przekroczony czas",
    "skipped": "pominięty",
    "in_progress": "trwa",
    "queued": "w kolejce",
}
