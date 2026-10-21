// Polls the IMGW public API on a cron trigger and stores the raw responses in R2.
// The API only returns the latest observation per station, so a missed poll is lost for good;
// GitHub Actions schedules proved too unreliable for this (docs/DECISIONS.md, 2026-10-13).
//
// - synop (62 stations, hourly values): at :05 and :35, raw JSON;
// - meteo (~790 automatic stations, 10-minute values): every 5 minutes, so each 10-minute value is seen
//   at least once even when IMGW publishes late; gzipped (~0.5 MB -> ~30 KB per poll).
// Raw files are converted to Parquet by `python -m pipeline.ingest.imgw ingest-raw` and
// `python -m pipeline.ingest.imgw_meteo ingest-raw` in the pipeline.

const SOURCES = {
  synop: { url: "https://danepubliczne.imgw.pl/api/data/synop", prefix: "pipeline/obs/imgw_raw", gzip: false },
  meteo: { url: "https://danepubliczne.imgw.pl/api/data/meteo", prefix: "pipeline/obs/imgw_meteo_raw", gzip: true },
};

async function fetchAndStore(env, source, now) {
  const day = now.toISOString().slice(0, 10); // UTC date
  const hhmm = now.toISOString().slice(11, 16).replace(":", "");
  const res = await fetch(source.url, { headers: { "User-Agent": "lepszapogoda.pl imgw-poller" } });
  if (!res.ok) {
    throw new Error(`IMGW API ${source.url} HTTP ${res.status}`);
  }
  const body = await res.text();
  const data = JSON.parse(body); // fail loudly on a non-JSON answer instead of storing it
  if (!Array.isArray(data) || data.length === 0) {
    throw new Error(`IMGW API ${source.url} returned no stations`);
  }
  if (!source.gzip) {
    await env.DATA.put(`${source.prefix}/${day}/${hhmm}.json`, body, {
      httpMetadata: { contentType: "application/json" },
    });
    return;
  }
  const gz = await new Response(
    new Blob([body]).stream().pipeThrough(new CompressionStream("gzip")),
  ).arrayBuffer();
  await env.DATA.put(`${source.prefix}/${day}/${hhmm}.json.gz`, gz, {
    httpMetadata: { contentType: "application/gzip" },
  });
}

export default {
  async scheduled(controller, env, ctx) {
    const now = new Date(controller.scheduledTime);
    const jobs = [fetchAndStore(env, SOURCES.meteo, now)];
    if (now.getUTCMinutes() % 30 === 5) {
      jobs.push(fetchAndStore(env, SOURCES.synop, now));
    }
    // one failing source must not stop the other; the run still fails so the error shows in the logs
    const failed = (await Promise.allSettled(jobs)).filter((r) => r.status === "rejected");
    if (failed.length) {
      throw new Error(failed.map((r) => r.reason?.message ?? String(r.reason)).join("; "));
    }
  },
};
