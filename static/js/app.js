(function () {
  "use strict";

  const UNIT_STYLES = {
    country: { color: "#1f6f4a", fillOpacity: 0.08, weight: 2 },
    voivodeship: { color: "#2a7f9e", fillOpacity: 0.14, weight: 2 },
    district: { color: "#b36b1b", fillOpacity: 0.2, weight: 2 },
    municipality: { color: "#6b3fa0", fillOpacity: 0.28, weight: 2.5 },
  };

  function renumber(listEl) {
    listEl.querySelectorAll(".candidate-item").forEach((item, idx) => {
      const num = item.querySelector(".rank-num");
      if (num) num.textContent = String(idx + 1);
      const input = item.querySelector('input[name="ranked_candidate_ids"]');
      if (input) input.value = item.dataset.id;
    });
  }

  window.SelectioRanking = {
    init(listEl) {
      if (!listEl || typeof Sortable === "undefined") return;
      renumber(listEl);
      Sortable.create(listEl, {
        animation: 160,
        handle: ".drag-handle",
        draggable: ".candidate-item",
        ghostClass: "sortable-ghost",
        chosenClass: "sortable-chosen",
        onSort() {
          renumber(listEl);
        },
      });
    },
  };

  window.SelectioBallot = {
    init(opts) {
      const pool = opts.pool;
      const rankList = opts.rankList;
      const search = opts.search;
      const form = opts.form;
      const byId = {};
      (opts.candidates || []).forEach((c) => {
        byId[String(c.id)] = c;
      });

      const emptyRank = document.querySelector(".rank-empty-msg");
      const noMatch = document.querySelector(".pool-no-match");

      function syncEmpty() {
        if (emptyRank) {
          emptyRank.hidden = rankList.querySelectorAll(".candidate-item").length > 0;
        }
      }

      function makeRankItem(c) {
        const li = document.createElement("li");
        li.className = "candidate-item";
        li.dataset.id = String(c.id);
        li.innerHTML =
          '<span class="rank-num" aria-hidden="true"></span>' +
          '<span class="drag-handle" title="Przeciągnij" aria-hidden="true">⋮⋮</span>' +
          '<div class="candidate-body"><strong></strong>' +
          (c.committee ? '<span class="candidate-committee"></span>' : "") +
          "</div>" +
          '<button type="button" class="btn btn-ghost btn-sm js-remove-rank" title="Usuń z rankingu">Usuń</button>' +
          '<input type="hidden" name="ranked_candidate_ids" value="">';
        li.querySelector("strong").textContent = c.name;
        const committeeEl = li.querySelector(".candidate-committee");
        if (committeeEl) committeeEl.textContent = c.committee;
        li.querySelector('input[name="ranked_candidate_ids"]').value = String(c.id);
        return li;
      }

      function makePoolItem(c) {
        const li = document.createElement("li");
        li.className = "pool-item";
        li.dataset.id = String(c.id);
        li.dataset.name = (c.name || "").toLowerCase();
        li.dataset.committee = (c.committee || "").toLowerCase();
        li.innerHTML =
          '<div class="candidate-body"><strong></strong>' +
          (c.committee ? '<span class="candidate-committee"></span>' : "") +
          (c.bio ? '<span class="candidate-bio"></span>' : "") +
          "</div>" +
          '<button type="button" class="btn btn-secondary btn-sm js-add-rank">+ Dodaj do mojego rankingu</button>';
        li.querySelector("strong").textContent = c.name;
        const committeeEl = li.querySelector(".candidate-committee");
        if (committeeEl) committeeEl.textContent = c.committee;
        const bioEl = li.querySelector(".candidate-bio");
        if (bioEl) bioEl.textContent = c.bio;
        return li;
      }

      function filterPool() {
        const q = (search.value || "").trim().toLowerCase();
        let visible = 0;
        pool.querySelectorAll(".pool-item").forEach((item) => {
          const hay =
            (item.dataset.name || "") + " " + (item.dataset.committee || "");
          const show = !q || hay.includes(q);
          item.hidden = !show;
          if (show) visible += 1;
        });
        if (noMatch) noMatch.hidden = visible > 0 || !q;
      }

      pool.addEventListener("click", (e) => {
        const btn = e.target.closest(".js-add-rank");
        if (!btn) return;
        const item = btn.closest(".pool-item");
        if (!item) return;
        const c = byId[item.dataset.id];
        if (!c) return;
        item.remove();
        rankList.appendChild(makeRankItem(c));
        renumber(rankList);
        syncEmpty();
        filterPool();
      });

      rankList.addEventListener("click", (e) => {
        const btn = e.target.closest(".js-remove-rank");
        if (!btn) return;
        const item = btn.closest(".candidate-item");
        if (!item) return;
        const c = byId[item.dataset.id];
        if (!c) return;
        item.remove();
        pool.appendChild(makePoolItem(c));
        renumber(rankList);
        syncEmpty();
        filterPool();
      });

      if (search) {
        search.addEventListener("input", filterPool);
      }

      if (form) {
        form.addEventListener("submit", (e) => {
          if (!rankList.querySelector(".candidate-item")) {
            e.preventDefault();
            alert("Dodaj co najmniej jednego kandydata do swojego rankingu.");
          }
        });
      }

      if (typeof Sortable !== "undefined") {
        Sortable.create(rankList, {
          animation: 160,
          handle: ".drag-handle",
          draggable: ".candidate-item",
          ghostClass: "sortable-ghost",
          chosenClass: "sortable-chosen",
          onSort() {
            renumber(rankList);
          },
        });
      }
      renumber(rankList);
      syncEmpty();
    },
  };

  window.SelectioMap = {
    init(mapEl) {
      if (!mapEl || typeof L === "undefined") return;

      let payload;
      try {
        const node = document.getElementById("map-payload");
        payload = node ? JSON.parse(node.textContent) : {};
      } catch (e) {
        console.error("Map payload parse error", e);
        return;
      }

      const map = L.map(mapEl, {
        scrollWheelZoom: false,
        zoomControl: true,
      });

      L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: "abcd",
        maxZoom: 19,
      }).addTo(map);

      const bounds = L.latLngBounds([]);
      const legend = document.getElementById("map-legend");

      (payload.units || []).forEach((unit) => {
        const style = UNIT_STYLES[unit.kind] || UNIT_STYLES.district;
        if (unit.boundary && unit.boundary.coordinates) {
          const layer = L.geoJSON(
            { type: "Feature", properties: unit, geometry: unit.boundary },
            {
              style: () => ({
                color: style.color,
                weight: style.weight,
                fillColor: style.color,
                fillOpacity: style.fillOpacity,
              }),
              onEachFeature(feature, lyr) {
                lyr.bindPopup(
                  `<strong>${unit.kind_label}</strong><br>${unit.name}`
                );
              },
            }
          ).addTo(map);
          bounds.extend(layer.getBounds());
        } else if (unit.center_lat != null && unit.center_lng != null) {
          bounds.extend([unit.center_lat, unit.center_lng]);
        }

        if (legend) {
          const chip = document.createElement("span");
          chip.className = "legend-chip";
          chip.innerHTML = `<span class="legend-swatch" style="background:${style.color}"></span>${unit.kind_label}: ${unit.name}`;
          legend.appendChild(chip);
        }
      });

      const station = payload.station;
      if (station && station.lat != null && station.lng != null) {
        const marker = L.marker([station.lat, station.lng]).addTo(map);
        marker.bindPopup(
          `<strong>${station.name}</strong><br>${station.code}<br>${station.address}`
        );
        bounds.extend([station.lat, station.lng]);
        marker.openPopup();
      }

      if (bounds.isValid()) {
        map.fitBounds(bounds.pad(0.12));
      } else {
        map.setView([50.2649, 19.0238], 11);
      }

      setTimeout(() => map.invalidateSize(), 80);
    },
  };
  window.SelectioResultsMap = {
    init(mapEl) {
      if (!mapEl || typeof L === "undefined") return;

      let payload;
      try {
        const node = document.getElementById("results-map-payload");
        payload = node ? JSON.parse(node.textContent) : {};
      } catch (e) {
        console.error("Results map payload parse error", e);
        return;
      }

      const map = L.map(mapEl, {
        scrollWheelZoom: false,
        zoomControl: true,
      });

      L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: "abcd",
        maxZoom: 19,
      }).addTo(map);

      const bounds = L.latLngBounds([]);
      const legend = document.getElementById("map-legend");
      const selectedId = payload.selected_unit_id;
      const base = payload.results_base || "/results/";

      (payload.units || []).forEach((unit) => {
        const style = UNIT_STYLES[unit.kind] || UNIT_STYLES.district;
        const isSelected = selectedId != null && unit.id === selectedId;
        const drawStyle = {
          color: style.color,
          weight: isSelected ? style.weight + 1.5 : style.weight,
          fillColor: style.color,
          fillOpacity: isSelected ? Math.min(style.fillOpacity + 0.18, 0.55) : style.fillOpacity,
        };

        const onClick = () => {
          const url = new URL(base, window.location.origin);
          url.searchParams.set("kind", unit.kind);
          url.searchParams.set("unit", String(unit.id));
          window.location.href = url.toString();
        };

        if (unit.boundary && unit.boundary.coordinates) {
          const layer = L.geoJSON(
            { type: "Feature", properties: unit, geometry: unit.boundary },
            {
              style: () => drawStyle,
              onEachFeature(feature, lyr) {
                lyr.on("click", onClick);
                lyr.bindTooltip(
                  `${unit.kind_label}: ${unit.name} (${unit.offices_count || 0} urz.)`,
                  { sticky: true }
                );
              },
            }
          ).addTo(map);
          bounds.extend(layer.getBounds());
        } else if (unit.center_lat != null && unit.center_lng != null) {
          const marker = L.circleMarker([unit.center_lat, unit.center_lng], {
            radius: isSelected ? 10 : 7,
            color: style.color,
            fillColor: style.color,
            fillOpacity: 0.7,
          }).addTo(map);
          marker.on("click", onClick);
          bounds.extend([unit.center_lat, unit.center_lng]);
        }

        if (legend) {
          const chip = document.createElement("button");
          chip.type = "button";
          chip.className = "legend-chip legend-chip-btn" + (isSelected ? " is-active" : "");
          chip.innerHTML = `<span class="legend-swatch" style="background:${style.color}"></span>${unit.name}`;
          chip.addEventListener("click", onClick);
          legend.appendChild(chip);
        }
      });

      if (bounds.isValid()) {
        map.fitBounds(bounds.pad(0.15));
      } else {
        map.setView([52.1, 19.4], 6);
      }
      setTimeout(() => map.invalidateSize(), 80);
    },
  };
})();
