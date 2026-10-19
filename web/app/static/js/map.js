// Map page (SPEC §5): map with Polish labels, one search field; the arrow opens the forecast ("trafna" mode;
// the other modes are switched on the forecast page). A point comes from a suggestion, a map click or geolocation.
(function () {
  "use strict";

  var BBOX = [13.9, 48.9, 24.2, 55.0];
  var MARGIN = 0.5;
  var PHOTON = "https://photon.komoot.io";
  var LANG = "default"; // local names ("Warszawa"); without it Photon follows the browser language ("Warsaw")
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
  // OpenFreeMap "liberty" labels prefer English (name_en); use Polish, then the local name
  var LABEL = ["coalesce", ["get", "name:pl"], ["get", "name"]];

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
  window.lpMap = map; // handle for debugging in the browser console
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
  var geolocate = new maplibregl.GeolocateControl({ positionOptions: { timeout: 10000 }, showUserLocation: false });
  map.addControl(geolocate, "bottom-right");

  function polishLabels() {
    (map.getStyle().layers || []).forEach(function (l) {
      if (l.type !== "symbol" || !l.layout || !l.layout["text-field"]) return;
      if (JSON.stringify(l.layout["text-field"]).indexOf("name") === -1) return; // road numbers etc.
      map.setLayoutProperty(l.id, "text-field", LABEL);
    });
  }
  map.on("style.load", polishLabels);

  var marker = null;
  var point = null; // {lat, lon, name} chosen for the current text
  var form = document.getElementById("search");
  var input = document.getElementById("place");
  var go = document.getElementById("go");
  var list = document.getElementById("suggestions");

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

  // ---------- point and navigation ----------
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

  function refreshArrow() {
    go.hidden = input.value.trim().length === 0;
  }

  function setPoint(lat, lon, name, fly) {
    if (!marker) marker = new maplibregl.Marker({ color: "#1f6feb" });
    marker.setLngLat([lon, lat]).addTo(map);
    if (fly) map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 10) });
    if (!inside(lat, lon)) {
      point = null;
      input.value = "";
      input.placeholder = "Ten punkt leży poza Polską. Wybierz miejsce w Polsce.";
      input.setAttribute("aria-invalid", "true");
      refreshArrow();
      return;
    }
    input.removeAttribute("aria-invalid");
    point = { lat: lat, lon: lon, name: name || "" };
    input.value = name || lat.toFixed(3) + ", " + lon.toFixed(3);
    refreshArrow();
    if (!name) reverse(lat, lon);
  }

  function open(p) {
    var href = "/prognoza/" + slugify(p.name || "punkt") + "/" + p.lat.toFixed(3) + "," + p.lon.toFixed(3) + "/trafna";
    if (p.name) href += "?n=" + encodeURIComponent(p.name);
    location.href = href;
  }

  function placeName(p) {
    return p.name || p.city || p.town || p.village || p.county || "";
  }

  function reverse(lat, lon) {
    fetch(PHOTON + "/reverse?lat=" + lat + "&lon=" + lon + "&limit=1&lang=" + LANG)
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var f = j.features && j.features[0];
        var n = f ? placeName(f.properties) : "";
        if (n && point && point.lat === lat && point.lon === lon) {
          point.name = n;
          input.value = n;
        }
      })
      .catch(function () { /* keep coordinates */ });
  }

  map.on("click", function (e) { setPoint(e.lngLat.lat, e.lngLat.lng, null, false); });
  geolocate.on("geolocate", function (pos) { setPoint(pos.coords.latitude, pos.coords.longitude, null, true); });

  // "zmień" link from the forecast page: /#lat,lon
  var m = location.hash.match(/^#(-?\d+\.\d+),(-?\d+\.\d+)$/);
  if (m) map.once("load", function () { setPoint(parseFloat(m[1]), parseFloat(m[2]), null, true); });

  // ---------- search ----------
  var timer = null, items = [], active = -1;

  function cached(q) {
    try {
      var c = JSON.parse(store("lp-q3:" + q) || "null");
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
    var c = f.geometry.coordinates;
    items = [];
    render();
    setPoint(c[1], c[0], placeName(f.properties), true);
  }

  function search(q) {
    var hit = cached(q);
    if (hit) return Promise.resolve(hit);
    var url = PHOTON + "/api/?q=" + encodeURIComponent(q) + "&limit=6&lang=" + LANG + "&bbox=" + BBOX.join(",");
    return fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (j) {
        // OSM has the same place as a city, a commune and a county: keep one entry per visible label
        var seen = {};
        var found = (j.features || []).filter(function (f) {
          var p = f.properties;
          var key = [placeName(p), p.county, p.state].join("|");
          if (p.countrycode !== "PL" || seen[key]) return false;
          seen[key] = true;
          return true;
        });
        store("lp-q3:" + q, JSON.stringify({ t: Date.now(), v: found }));
        return found;
      });
  }

  input.addEventListener("input", function () {
    point = null; // typed text no longer matches the chosen point
    input.removeAttribute("aria-invalid");
    refreshArrow();
    clearTimeout(timer);
    var q = input.value.trim();
    if (q.length < 2) { items = []; render(); return; }
    timer = setTimeout(function () {
      search(q).then(function (found) { items = found; active = -1; render(); }).catch(function () { items = []; render(); });
    }, 250);
  });

  input.addEventListener("keydown", function (e) {
    if (!items.length) return;
    if (e.key === "ArrowDown") { active = (active + 1) % items.length; render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = (active - 1 + items.length) % items.length; render(); e.preventDefault(); }
    else if (e.key === "Escape") { items = []; render(); }
  });

  // Arrow or Enter: open the forecast for the chosen point, or for the best match of the typed text
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (items.length && active >= 0) { choose(active); }
    if (point) { open(point); return; }
    var q = input.value.trim();
    if (q.length < 2) return;
    search(q).then(function (found) {
      if (!found.length) {
        input.setAttribute("aria-invalid", "true");
        return;
      }
      var c = found[0].geometry.coordinates;
      open({ lat: c[1], lon: c[0], name: placeName(found[0].properties) });
    });
  });

  input.addEventListener("blur", function () { setTimeout(function () { items = []; render(); }, 150); });
})();
