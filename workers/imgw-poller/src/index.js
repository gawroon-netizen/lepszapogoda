// Polls the IMGW synop API on a cron trigger and stores the raw response in R2.
// The API only returns the latest hourly observation per station, so a missed hour is lost for good;
// GitHub Actions schedules proved too unreliable for this (docs/DECISIONS.md, 2026-10-13).
// Raw files are converted to Parquet by `python -m pipeline.ingest.imgw ingest-raw` in the pipeline.

const API_URL = "https://danepubliczne.imgw.pl/api/data/synop";
const PREFIX = "pipeline/obs/imgw_raw";

export default {
  async scheduled(controller, env, ctx) {
    const now = new Date(controller.scheduledTime);
    const day = now.toISOString().slice(0, 10); // UTC date
    const hhmm = now.toISOString().slice(11, 16).replace(":", "");
    const res = await fetch(API_URL, { headers: { "User-Agent": "lepszapogoda.pl imgw-poller" } });
    if (!res.ok) {
      throw new Error(`IMGW API HTTP ${res.status}`);
    }
    const body = await res.text();
    const data = JSON.parse(body); // fail loudly on a non-JSON answer instead of storing it
    if (!Array.isArray(data) || data.length === 0) {
      throw new Error("IMGW API returned no stations");
    }
    await env.DATA.put(`${PREFIX}/${day}/${hhmm}.json`, body, {
      httpMetadata: { contentType: "application/json" },
    });
  },
};
