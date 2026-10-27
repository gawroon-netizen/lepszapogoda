"""Verification and ranking parameters (SPEC §8.3, §8.4, §8.10). Changing any of them changes rankings: note it in
docs/DECISIONS.md."""

WINDOW_DAYS = 30
# The window ends where every cell has its forecasts. Each cell is refreshed once per ROTATION_DAYS (budget, see
# pipeline.ingest.forecasts), so its newest stored day lags today - LAG_DAYS by up to ROTATION_DAYS - 1 days. A window
# ending at D-2 left most cells below MIN_DAYS once the rotation spread out: 29 of 4313 cells ranked (2026-10-27).
from pipeline.ingest.forecasts import LAG_DAYS as _FC_LAG  # noqa: E402
from pipeline.ingest.forecasts import ROTATION_DAYS as _ROT  # noqa: E402

END_LAG_DAYS = _FC_LAG + _ROT - 1  # 15
MIN_DAYS = 20  # days with data per (cell, model) to enter the ranking (§8.4)
RANK_LEADS = (1, 2, 3)  # 24/48/72 h, pooled (§8.3)
from lepszapogoda.blend import LEAD_GROUPS  # noqa: E402, F401 - blend weight groups, shared with the web app (§8.10)

PRECIP_THRESHOLD_MM = 1.0
CLOUD_CLEAR_MAX = 25.0  # %, class "pogodnie" below
CLOUD_CLOUDY_MIN = 75.0  # %, class "pochmurno" above
MODIS_MIN_VALID = 0.5  # minimum valid fraction of a cell for a MODIS observation to count

LAPSE_RATE = 0.0065  # K/m, model temperature corrected to station elevation (§8.2)
STATION_RADIUS_KM = 60.0  # stations assigned to a cell within this distance, weight 1/d (§8.2)
MIN_STATION_DIST_KM = 1.0  # floor for 1/d

# Combined score weights (§8.4); without temperature: cloud and precipitation 0.5 each
WEIGHTS = {"cloud": 0.4, "precip": 0.4, "temp": 0.2}
PRECIP_ETS_WEIGHT = 0.7  # within precipitation: ETS 0.7, MAE 0.3 (§8.3)
CLOUD_CLASS_WEIGHT = 0.5  # within cloud: class accuracy 0.5, error SD 0.5 (bias-robust, Etap 0a)

# A cell is ranked only when all core models have >= MIN_DAYS of data (2026-10-20: the first publication
# compared only the ECMWF models, because the backfill fetches model by model). Extra models join when they
# have enough data, so a newly added model does not block publication (2026-10-21).
from lepszapogoda.openmeteo import CORE_MODELS as REQUIRED_MODELS  # noqa: E402, F401
