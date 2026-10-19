// Map page (SPEC §5).
// - One style object built once from OpenFreeMap "liberty": Polish labels, no voivodeship labels, towns and
//   villages from lower zooms; the satellite style reuses its boundary and label layers on top of EOX imagery.
//   Switching layers uses these prepared objects, so the labels never fall back to English.
// - The verification grid (0.1° cells touching Poland, /dane/komorki.json) is drawn as squares from zoom 7.
//   A click while the whole country is visible only zooms in; with the squares visible it selects a square.
// - The search field opens the forecast ("trafna"); a point outside the Polish cells is refused.
(function () {
  "use strict";

  var PHOTON = "https://photon.komoot.io";
  var LANG = "default"; // local names ("Warszawa"); without it Photon follows the browser language ("Warsaw")
  var STEP = 0.1;
  var GRID_ZOOM = 7; // squares appear
  var SELECT_ZOOM = 8; // below this a click zooms in instead of selecting
  var POLAND = [[13.9, 48.9], [24.2, 55.0]];
  var LIBERTY = "https://tiles.openfreemap.org/styles/liberty";
  var EOX = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg";
  var LABEL = ["coalesce", ["get", "name:pl"], ["get", "name"]];
  var PLACES_URL = document.getElementById("map").dataset.places;

  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) { /* storage blocked: fine */ }
    return null;
  }

  // ---------- styles ----------
  function adaptLiberty(s) {
    s.layers = s.layers.filter(function (l) { return l.id !== "label_state"; });
    s.layers.forEach(function (l) {
      var tf = l.layout && l.layout["text-field"];
      if (l.type === "symbol" && tf && JSON.stringify(tf).indexOf("name") !== -1) l.layout["text-field"] = LABEL;
      if (l.id === "label_town") l.minzoom = 5;
      if (l.id === "label_village") l.minzoom = 8;
    });
    return s;
  }

  function satelliteFrom(base) {
    var keep = /^(boundary|label_|highway-name|water_name|road_shield)/;
    var s = JSON.parse(JSON.stringify(base));
    s.sources.eox = {
      type: "raster", tiles: [EOX], tileSize: 256, maxzoom: 15,
      attribution: "Sentinel-2 cloudless by EOX: contains modified Copernicus Sentinel data (CC BY-NC-SA 4.0)",
    };
    s.layers = [{ id: "eox", type: "raster", source: "eox" }].concat(
      base.layers.filter(function (l) { return keep.test(l.id); })
    );
    return s;
  }

  var styles = null;
  var stylesReady = fetch(LIBERTY)
    .then(function (r) { return r.json(); })
    .then(function (s) {
      var map = adaptLiberty(s);
      styles = { map: map, sat: satelliteFrom(map) };
      return styles;
    });

  // ---------- grid ----------
  var cells = null; // {cell_id: feature index}
  var cellsGeo = null;
  var cellsReady = fetch("/dane/komorki.json")
    .then(function (r) { return r.json(); })
    .then(function (j) {
      cells = {};
      var feats = j.cells.map(function (id, i) {
        cells[id] = i;
        var lat = parseInt(id.slice(0, 3), 10) / 10, lon = parseInt(id.slice(4), 10) / 10;
        return {
          type: "Feature", id: i, properties: { cell: id },
          geometry: { type: "Polygon", coordinates: [[[lon, lat], [lon + STEP, lat], [lon + STEP, lat + STEP], [lon, lat + STEP], [lon, lat]]] },
        };
      });
      cellsGeo = { type: "FeatureCollection", features: feats };
    });

  // ---------- Polish towns (OpenFreeMap low-zoom tiles carry only a few metropolises) ----------
  var placesGeo = null;
  var placesReady = fetch(PLACES_URL)
    .then(function (r) { return r.json(); })
    .then(function (j) {
      placesGeo = {
        type: "FeatureCollection",
        features: j.places.map(function (p) {
          return { type: "Feature", properties: { n: p.n, p: p.p }, geometry: { type: "Point", coordinates: [p.lon, p.lat] } };
        }),
      };
    })
    .catch(function () { /* map works without them */ });

  // population bands: [min, max, minzoom, font, size]
  var TOWN_BANDS = [
    [100000, 1e9, 4, "Noto Sans Bold", 13],
    [40000, 100000, 6, "Noto Sans Regular", 12],
    [15000, 40000, 7, "Noto Sans Regular", 11],
    [0, 15000, 8, "Noto Sans Regular", 11],
  ];

  function addTowns() {
    if (!placesGeo || map.getSource("towns")) return;
    map.addSource("towns", { type: "geojson", data: placesGeo });
    var sat = layer === "sat";
    TOWN_BANDS.forEach(function (b, i) {
      map.addLayer({
        id: "towns-" + i, type: "symbol", source: "towns", minzoom: b[2],
        filter: ["all", [">=", ["get", "p"], b[0]], ["<", ["get", "p"], b[1]]],
        layout: {
          "text-field": ["get", "n"], "text-font": [b[3]], "text-size": b[4],
          "symbol-sort-key": ["-", 0, ["get", "p"]], "text-padding": 4,
        },
        paint: {
          "text-color": sat ? "#ffffff" : "#26303b",
          "text-halo-color": sat ? "rgba(0,0,0,.75)" : "rgba(255,255,255,.95)", "text-halo-width": 1.4,
        },
      });
    });
  }

  function cellIdFor(lat, lon) {
    var a = Math.floor(lat * 10 + 1e-9), o = Math.floor(lon * 10 + 1e-9);
    return ("00" + a).slice(-3) + "_" + ("00" + o).slice(-3);
  }

  function inPoland(lat, lon) {
    return cells !== null && Object.prototype.hasOwnProperty.call(cells, cellIdFor(lat, lon));
  }

  function addGrid() {
    if (!cellsGeo || map.getSource("cells")) return;
    map.addSource("cells", { type: "geojson", data: cellsGeo });
    map.addLayer({ id: "cells-fill", type: "fill", source: "cells", minzoom: GRID_ZOOM, paint: {
      "fill-color": "#1f6feb",
      "fill-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 0.28,
        ["boolean", ["feature-state", "hover"], false], 0.14, 0],
    } });
    map.addLayer({ id: "cells-line", type: "line", source: "cells", minzoom: GRID_ZOOM, paint: {
      "line-color": layer === "sat" ? "#ffffff" : "#1f6feb",
      "line-opacity": ["interpolate", ["linear"], ["zoom"], GRID_ZOOM, 0, GRID_ZOOM + 1, 0.35, 11, 0.5],
      "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 2.5, 0.6],
    } });
    if (selected !== null) map.setFeatureState({ source: "cells", id: selected }, { selected: true });
  }

  // ---------- map ----------
  var layer = store("lp-layer") === "sat" ? "sat" : "map";
  var map = new maplibregl.Map({
    container: "map",
    style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#f2efe9" } }] },
    bounds: POLAND,
    fitBoundsOptions: { padding: { top: 90, bottom: 30, left: 20, right: 20 } },
    attributionControl: { compact: true },
  });
  window.lpMap = map; // handle for debugging in the browser console
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
  var geolocate = new maplibregl.GeolocateControl({ positionOptions: { timeout: 10000 }, showUserLocation: false });
  map.addControl(geolocate, "bottom-right");
  map.on("style.load", function () { addGrid(); addTowns(); });

  Promise.all([stylesReady, cellsReady, placesReady]).then(function () { map.setStyle(styles[layer], { diff: false }); });

  document.querySelectorAll(".layer-switch button").forEach(function (b) {
    b.classList.toggle("active", b.dataset.layer === layer);
    b.addEventListener("click", function () {
      if (!styles || b.dataset.layer === layer) return;
      layer = b.dataset.layer;
      map.setStyle(styles[layer], { diff: false });
      store("lp-layer", layer);
      document.querySelectorAll(".layer-switch button").forEach(function (x) { x.classList.toggle("active", x === b); });
    });
  });

  // ---------- selection ----------
  var marker = null, point = null, selected = null, hovered = null;
  var form = document.getElementById("search");
  var input = document.getElementById("place");
  var go = document.getElementById("go");
  var list = document.getElementById("suggestions");
  var placeholder = input.placeholder;

  function refreshArrow() { go.hidden = input.value.trim().length === 0; }

  function selectCell(id) {
    if (selected !== null && map.getSource("cells")) map.setFeatureState({ source: "cells", id: selected }, { selected: false });
    selected = id;
    if (id !== null && map.getSource("cells")) map.setFeatureState({ source: "cells", id: id }, { selected: true });
  }

  function refuse() {
    point = null;
    selectCell(null);
    if (marker) marker.remove();
    input.value = "";
    input.placeholder = "Prognozy są dostępne tylko dla miejsc w Polsce.";
    input.setAttribute("aria-invalid", "true");
    refreshArrow();
  }

  function setPoint(lat, lon, name, fly) {
    if (!inPoland(lat, lon)) { refuse(); return; }
    input.removeAttribute("aria-invalid");
    input.placeholder = placeholder;
    if (!marker) marker = new maplibregl.Marker({ color: "#1f6feb" });
    marker.setLngLat([lon, lat]).addTo(map);
    selectCell(cells[cellIdFor(lat, lon)]);
    if (fly) map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 10) });
    point = { lat: lat, lon: lon, name: name || "" };
    input.value = name || "…";
    refreshArrow();
    if (!name) reverse(lat, lon);
  }

  function placeName(p) {
    return p.name || p.city || p.town || p.village || p.county || "";
  }

  // nearest town or village, not the nearest shop or bank (layer=city covers towns and villages)
  function reverse(lat, lon) {
    fetch(PHOTON + "/reverse?lat=" + lat + "&lon=" + lon + "&limit=1&layer=city&radius=15&lang=" + LANG)
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!point || point.lat !== lat || point.lon !== lon) return;
        var f = j.features && j.features[0];
        point.name = f ? placeName(f.properties) : "";
        input.value = point.name || lat.toFixed(3) + ", " + lon.toFixed(3);
      })
      .catch(function () {
        if (point && point.lat === lat) input.value = lat.toFixed(3) + ", " + lon.toFixed(3);
      });
  }

  map.on("click", function (e) {
    if (map.getZoom() < SELECT_ZOOM) {
      // country view: a click only brings the place closer, the squares become visible
      map.flyTo({ center: e.lngLat, zoom: 9.5 });
      return;
    }
    setPoint(e.lngLat.lat, e.lngLat.lng, null, false);
  });

  map.on("mousemove", function (e) {
    var id = null;
    if (map.getZoom() >= SELECT_ZOOM && map.getLayer("cells-fill")) {
      var f = map.queryRenderedFeatures(e.point, { layers: ["cells-fill"] })[0];
      id = f ? f.id : null;
    }
    if (id === hovered) return;
    if (hovered !== null && map.getSource("cells")) map.setFeatureState({ source: "cells", id: hovered }, { hover: false });
    hovered = id;
    if (id !== null) map.setFeatureState({ source: "cells", id: id }, { hover: true });
    map.getCanvas().style.cursor = id !== null || map.getZoom() < SELECT_ZOOM ? "pointer" : "";
  });

  geolocate.on("geolocate", function (pos) { setPoint(pos.coords.latitude, pos.coords.longitude, null, true); });

  // "zmień" link from the forecast page: /#lat,lon
  var m = location.hash.match(/^#(-?\d+\.\d+),(-?\d+\.\d+)$/);
  if (m) cellsReady.then(function () { setPoint(parseFloat(m[1]), parseFloat(m[2]), null, true); });

  // ---------- navigation ----------
  var PL = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", AS = "acelnoszzacelnoszz";
  function slugify(name) {
    var s = (name || "").split("").map(function (c) {
      var i = PL.indexOf(c);
      return i >= 0 ? AS[i] : c;
    }).join("").toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    return s.slice(0, 80).replace(/-+$/, "") || "punkt";
  }

  function open(p) {
    var href = "/prognoza/" + slugify(p.name || "punkt") + "/" + p.lat.toFixed(3) + "," + p.lon.toFixed(3) + "/trafna";
    if (p.name) href += "?n=" + encodeURIComponent(p.name);
    location.href = href;
  }

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
    var url = PHOTON + "/api/?q=" + encodeURIComponent(q) + "&limit=8&lang=" + LANG + "&bbox=" + POLAND[0].concat(POLAND[1]).join(",");
    return Promise.all([fetch(url).then(function (r) { return r.json(); }), cellsReady]).then(function (res) {
      // OSM has the same place as a city, a commune and a county: keep one entry per visible label
      var seen = {};
      var found = (res[0].features || []).filter(function (f) {
        var p = f.properties, c = f.geometry.coordinates;
        var key = [placeName(p), p.county, p.state].join("|");
        if (p.countrycode !== "PL" || seen[key] || !inPoland(c[1], c[0])) return false;
        seen[key] = true;
        return true;
      }).slice(0, 6);
      store("lp-q3:" + q, JSON.stringify({ t: Date.now(), v: found }));
      return found;
    });
  }

  input.addEventListener("input", function () {
    point = null; // typed text no longer matches the chosen point
    input.removeAttribute("aria-invalid");
    input.placeholder = placeholder;
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

  // Arrow or Enter: the forecast for the chosen point, or for the best match of the typed text
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (items.length && active >= 0) choose(active);
    if (point) { open(point); return; }
    var q = input.value.trim();
    if (q.length < 2) return;
    search(q).then(function (found) {
      if (!found.length) { input.setAttribute("aria-invalid", "true"); return; }
      var c = found[0].geometry.coordinates;
      open({ lat: c[1], lon: c[0], name: placeName(found[0].properties) });
    });
  });

  input.addEventListener("blur", function () { setTimeout(function () { items = []; render(); }, 150); });
})();
