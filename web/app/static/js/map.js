// Map page (SPEC §5): map, place search (Photon), click / geolocation, three mode buttons.
(function () {
  "use strict";

  var BBOX = [13.9, 48.9, 24.2, 55.0];
  var MARGIN = 0.5;
  var PHOTON = "https://photon.komoot.io";
  var STYLES = {
    map: "https://tiles.openfreemap.org/styles/liberty",
    sat: {
      version: 8,
      sources: {
        eox: {
          type: "raster",
          tiles: ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg"],
          tileSize: 256,
          maxzoom: 15,
          attribution: "Sentinel-2 cloudless by EOX: contains modified Copernicus Sentinel data (CC BY-NC-SA 4.0)",
        },
      },
      layers: [{ id: "eox", type: "raster", source: "eox" }],
    },
  };

  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) { /* storage blocked: fine */ }
    return null;
  }

  var layer = store("lp-layer") === "sat" ? "sat" : "map";
  var map = new maplibregl.Map({
    container: "map",
    style: STYLES[layer],
    center: [19.4, 52.0],
    zoom: 5.6,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
  window.lpMap = map; // handle for debugging in the browser console

  var marker = null;
  var input = document.getElementById("place");
  var list = document.getElementById("suggestions");
  var hint = document.getElementById("hint");
  var modes = document.querySelectorAll(".mode");

  // ---------- layers ----------
  document.querySelectorAll(".layer-switch button").forEach(function (b) {
    b.classList.toggle("active", b.dataset.layer === layer);
    b.addEventListener("click", function () {
      layer = b.dataset.layer;
      map.setStyle(STYLES[layer]);
      store("lp-layer", layer);
      document.querySelectorAll(".layer-switch button").forEach(function (x) {
        x.classList.toggle("active", x === b);
      });
    });
  });

  // ---------- point selection ----------
  var PL = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", AS = "acelnoszzacelnoszz";
  function slugify(name) {
    var s = (name || "").split("").map(function (c) {
      var i = PL.indexOf(c);
      return i >= 0 ? AS[i] : c;
    }).join("").toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    return s.slice(0, 80).replace(/-+$/, "") || "punkt";
  }

  function inside(lat, lon) {
    return lat >= BBOX[1] - MARGIN && lat <= BBOX[3] + MARGIN && lon >= BBOX[0] - MARGIN && lon <= BBOX[2] + MARGIN;
  }

  function setPoint(lat, lon, name, fly) {
    if (!marker) marker = new maplibregl.Marker({ color: "#1f6feb" });
    marker.setLngLat([lon, lat]).addTo(map);
    if (fly) map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 10) });
    var ok = inside(lat, lon);
    var label = name || lat.toFixed(3) + ", " + lon.toFixed(3);
    hint.textContent = ok ? label : "Ten punkt leży poza obszarem prognoz (Polska).";
    modes.forEach(function (a) {
      if (!ok) {
        a.classList.add("disabled");
        a.setAttribute("aria-disabled", "true");
        return;
      }
      var href = "/prognoza/" + slugify(name || "punkt") + "/" + lat.toFixed(3) + "," + lon.toFixed(3) + "/" + a.dataset.mode;
      if (name) href += "?n=" + encodeURIComponent(name);
      a.href = href;
      a.classList.remove("disabled");
      a.removeAttribute("aria-disabled");
    });
    if (!name && ok) reverse(lat, lon);
  }

  function placeName(p) {
    return p.name || p.city || p.town || p.village || p.county || "";
  }

  function reverse(lat, lon) {
    fetch(PHOTON + "/reverse?lat=" + lat + "&lon=" + lon + "&limit=1")
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var f = j.features && j.features[0];
        var n = f ? placeName(f.properties) : "";
        if (n) {
          input.value = n;
          setPoint(lat, lon, n, false);
        }
      })
      .catch(function () { /* keep coordinates */ });
  }

  map.on("click", function (e) {
    input.value = "";
    setPoint(e.lngLat.lat, e.lngLat.lng, null, false);
  });

  document.getElementById("locate").addEventListener("click", function () {
    if (!navigator.geolocation) return;
    hint.textContent = "Ustalam lokalizację…";
    navigator.geolocation.getCurrentPosition(
      function (pos) { setPoint(pos.coords.latitude, pos.coords.longitude, null, true); },
      function () { hint.textContent = "Nie udało się ustalić lokalizacji. Wpisz miejscowość albo kliknij na mapie."; },
      { timeout: 10000 }
    );
  });

  // "zmień" link from the forecast page: /#lat,lon
  var m = location.hash.match(/^#(-?\d+\.\d+),(-?\d+\.\d+)$/);
  if (m) map.once("load", function () { setPoint(parseFloat(m[1]), parseFloat(m[2]), null, true); });

  // ---------- search ----------
  var timer = null, items = [], active = -1;

  function cached(q) {
    try {
      var c = JSON.parse(store("lp-q:" + q) || "null");
      if (c && Date.now() - c.t < 7 * 864e5) return c.v;
    } catch (e) { /* ignore */ }
    return null;
  }

  function render() {
    list.innerHTML = "";
    items.forEach(function (f, i) {
      var p = f.properties;
      var li = document.createElement("li");
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", i === active ? "true" : "false");
      li.textContent = placeName(p);
      var sub = document.createElement("small");
      sub.textContent = [p.county, p.state].filter(Boolean).join(", ");
      li.appendChild(sub);
      li.addEventListener("mousedown", function (e) { e.preventDefault(); choose(i); });
      list.appendChild(li);
    });
    list.hidden = items.length === 0;
    input.setAttribute("aria-expanded", items.length ? "true" : "false");
  }

  function choose(i) {
    var f = items[i];
    if (!f) return;
    var c = f.geometry.coordinates, n = placeName(f.properties);
    input.value = n;
    items = [];
    render();
    setPoint(c[1], c[0], n, true);
  }

  function search(q) {
    var hit = cached(q);
    if (hit) { items = hit; active = -1; render(); return; }
    var url = PHOTON + "/api/?q=" + encodeURIComponent(q) + "&limit=6&bbox=" + BBOX.join(",");
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (j) {
        items = (j.features || []).filter(function (f) { return f.properties.countrycode === "PL"; });
        active = -1;
        store("lp-q:" + q, JSON.stringify({ t: Date.now(), v: items }));
        render();
      })
      .catch(function () { items = []; render(); });
  }

  input.addEventListener("input", function () {
    clearTimeout(timer);
    var q = input.value.trim();
    if (q.length < 2) { items = []; render(); return; }
    timer = setTimeout(function () { search(q); }, 250);
  });
  input.addEventListener("keydown", function (e) {
    if (!items.length) return;
    if (e.key === "ArrowDown") { active = (active + 1) % items.length; render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = (active - 1 + items.length) % items.length; render(); e.preventDefault(); }
    else if (e.key === "Enter") { choose(active >= 0 ? active : 0); e.preventDefault(); }
    else if (e.key === "Escape") { items = []; render(); }
  });
  input.addEventListener("blur", function () { setTimeout(function () { items = []; render(); }, 150); });
})();
