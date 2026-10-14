// Day detail charts (SPEC §6): temperature (+ spread between models), precipitation + cloud cover, wind.
(function () {
  "use strict";

  var data = JSON.parse(document.getElementById("fc-data").textContent);
  var tzDate = function (ts) { return uPlot.tzDate(new Date(ts * 1000), "Europe/Warsaw"); };
  var dayFmt = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Warsaw" }); // yyyy-mm-dd
  var charts = [];

  function dayIndices(day) {
    var idx = [];
    data.time.forEach(function (t, i) { if (dayFmt.format(new Date(t * 1000)) === day) idx.push(i); });
    return idx;
  }

  function pick(arr, idx) { return idx.map(function (i) { return arr ? arr[i] : null; }); }

  function width() { return Math.max(280, document.querySelector(".charts").clientWidth - 18); }

  function axes(unitLeft, unitRight) {
    var a = [
      { values: "{HH}:{mm}" },
      { label: unitLeft, size: 50 },
    ];
    if (unitRight) a.push({ side: 1, label: unitRight, size: 50, scale: "right", grid: { show: false } });
    return a;
  }

  function draw(day) {
    charts.forEach(function (c) { c.destroy(); });
    charts = [];
    var idx = dayIndices(day);
    if (!idx.length) return;
    var x = pick(data.time, idx);

    // temperature, with the min-max band between models when blended
    var tSeries = [{}, { label: "Temperatura °C", stroke: "#e4572e", width: 2 },
      { label: "Odczuwalna °C", stroke: "#e4572e", dash: [5, 5] }];
    var tData = [x, pick(data.temperature_2m, idx), pick(data.apparent_temperature, idx)];
    var bands;
    if (data.temperature_2m_min) {
      tSeries.push({ label: "min. modeli", stroke: "rgba(228,87,46,.25)" }, { label: "max. modeli", stroke: "rgba(228,87,46,.25)" });
      tData.push(pick(data.temperature_2m_min, idx), pick(data.temperature_2m_max, idx));
      bands = [{ series: [4, 3], fill: "rgba(228,87,46,.10)" }];
    }
    charts.push(new uPlot({ width: width(), height: 220, tzDate: tzDate, series: tSeries, bands: bands, axes: axes("°C") },
      tData, document.getElementById("chart-temp")));

    // precipitation bars + cloud cover on the right axis
    var bars = uPlot.paths && uPlot.paths.bars ? uPlot.paths.bars({ size: [0.7, 40] }) : undefined;
    charts.push(new uPlot({
      width: width(), height: 200, tzDate: tzDate,
      scales: { y: { range: function (u, mn, mx) { return [0, Math.max(1, mx)]; } }, right: { range: [0, 100] } },
      series: [{}, { label: "Opad mm/h", stroke: "#1f6feb", fill: "rgba(31,111,235,.35)", paths: bars },
        { label: "Zachmurzenie %", stroke: "#8492a6", scale: "right" }],
      axes: axes("mm", "%"),
    }, [x, pick(data.precipitation, idx), pick(data.cloud_cover, idx)], document.getElementById("chart-precip")));

    // wind
    charts.push(new uPlot({
      width: width(), height: 180, tzDate: tzDate,
      series: [{}, { label: "Wiatr km/h", stroke: "#2a9d8f", width: 2 }, { label: "Porywy km/h", stroke: "#2a9d8f", dash: [4, 4] }],
      axes: axes("km/h"),
    }, [x, pick(data.wind_speed_10m, idx), pick(data.wind_gusts_10m, idx)], document.getElementById("chart-wind")));
  }

  var days = document.querySelectorAll(".day");
  days.forEach(function (b) {
    b.addEventListener("click", function () {
      days.forEach(function (x) { x.classList.toggle("active", x === b); });
      draw(b.dataset.date);
    });
  });
  var current = document.querySelector(".day.active");
  if (current) draw(current.dataset.date);
  var resizeTimer;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      var a = document.querySelector(".day.active");
      if (a) draw(a.dataset.date);
    }, 200);
  });
})();
