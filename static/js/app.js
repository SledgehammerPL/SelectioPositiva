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
      const input = item.querySelector('input[name="ranked_user_ids"]');
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
      const form = opts.form;
      const statusEl = opts.statusEl;
      const firstEl = opts.firstEl;
      const secondEl = opts.secondEl;
      const lastEl = opts.lastEl;
      const birthEl = opts.birthEl;
      const searchUrl = opts.searchUrl || "";
      const byId = {};
      const MIN_CHARS = 3;
      let debounceTimer = null;
      let requestSeq = 0;
      let activeIndex = -1;

      const tooltipEl = document.getElementById("candidate-tooltip");
      let hoverTooltipId = null;
      const tooltipNameEl = tooltipEl
        ? tooltipEl.querySelector(".candidate-tooltip-name")
        : null;
      const tooltipMetaEl = tooltipEl
        ? tooltipEl.querySelector(".candidate-tooltip-meta")
        : null;

      function hideTooltip() {
        if (!tooltipEl) return;
        hoverTooltipId = null;
        tooltipEl.hidden = true;
        tooltipEl.setAttribute("aria-hidden", "true");
      }

      function renderTooltipContent(c) {
        if (!tooltipEl || !tooltipNameEl || !tooltipMetaEl || !c) return;
        tooltipNameEl.textContent = c.name || "";

        const parts = [];
        if (c.birth_date) parts.push("ur. " + c.birth_date);
        if (c.municipality) parts.push("zam. " + c.municipality);
        if (c.second_name) parts.push("2. imię: " + c.second_name);
        tooltipMetaEl.textContent =
          parts.length ? parts.join(" · ") : "Szczegóły chwilowo niedostępne";
      }

      function moveTooltip(clientX, clientY) {
        if (!tooltipEl) return;
        // tooltipEl musi być widoczny, żeby w ogóle mieć sensowny width/height
        if (tooltipEl.hidden) return;
        const rect = tooltipEl.getBoundingClientRect();
        const pad = 14;
        const maxLeft = window.innerWidth - rect.width - pad;
        const maxTop = window.innerHeight - rect.height - pad;
        const left = Math.max(pad, Math.min(clientX + pad, maxLeft));
        const top = Math.max(pad, Math.min(clientY + pad, maxTop));
        tooltipEl.style.left = left + "px";
        tooltipEl.style.top = top + "px";
      }

      function showTooltipForId(id, clientX, clientY) {
        if (!tooltipEl) return;
        const c = byId[id];
        if (!c) return;
        hoverTooltipId = id;
        renderTooltipContent(c);
        tooltipEl.hidden = false;
        tooltipEl.setAttribute("aria-hidden", "false");
        moveTooltip(clientX, clientY);
      }

      (opts.ranked || []).forEach((c) => {
        byId[String(c.id)] = c;
      });

      const emptyRank = document.querySelector(".rank-empty-msg");
      const focusEl = lastEl || firstEl;

      function rankedIds() {
        return Array.from(rankList.querySelectorAll(".candidate-item")).map(
          (el) => el.dataset.id
        );
      }

      function syncEmpty() {
        if (emptyRank) {
          emptyRank.hidden =
            rankList.querySelectorAll(".candidate-item").length > 0;
        }
      }

      function setStatus(text) {
        if (statusEl) statusEl.textContent = text;
      }

      function fieldValue(el) {
        return (el && el.value ? el.value : "").trim();
      }

      function firstValue() {
        return fieldValue(firstEl);
      }
      function secondValue() {
        return fieldValue(secondEl);
      }
      function lastValue() {
        return fieldValue(lastEl);
      }
      function birthValue() {
        return birthEl && birthEl.value ? birthEl.value : "";
      }

      function filterActive() {
        return (
          firstValue().length >= MIN_CHARS ||
          secondValue().length >= MIN_CHARS ||
          lastValue().length >= MIN_CHARS ||
          !!birthValue()
        );
      }

      function setExpanded(open) {
        if (focusEl) focusEl.setAttribute("aria-expanded", open ? "true" : "false");
      }

      function makeRankItem(c) {
        const li = document.createElement("li");
        li.className = "candidate-item";
        li.dataset.id = String(c.id);
        li.innerHTML =
          '<span class="rank-num" aria-hidden="true"></span>' +
          '<span class="drag-handle" title="Przeciągnij" aria-hidden="true">⋮⋮</span>' +
          '<div class="candidate-body"><strong></strong></div>' +
          '<button type="button" class="btn btn-ghost btn-sm js-remove-rank" title="Usuń z rankingu">Usuń</button>' +
          '<input type="hidden" name="ranked_user_ids" value="">';
        li.querySelector("strong").textContent = c.name;
        const body = li.querySelector(".candidate-body");
        const metaBits = [];
        if (c.birth_date) metaBits.push("ur. " + c.birth_date);
        if (c.municipality) metaBits.push("zam. " + c.municipality);
        if (c.committee) metaBits.push(c.committee);
        if (metaBits.length) {
          const span = document.createElement("span");
          span.className = "candidate-committee";
          span.textContent = metaBits.join(" · ");
          body.appendChild(span);
        }
        li.querySelector('input[name="ranked_user_ids"]').value = String(
          c.id
        );
        return li;
      }

      function makePoolItem(c, index) {
        const li = document.createElement("li");
        li.className = "ac-option";
        li.dataset.id = String(c.id);
        li.dataset.index = String(index);
        li.setAttribute("role", "option");
        li.id = "ac-opt-" + c.id;
        const metaBits = [];
        if (c.birth_date) metaBits.push("ur. " + c.birth_date);
        if (c.municipality) metaBits.push("zam. " + c.municipality);
        if (c.parties) metaBits.push(c.parties);
        if (c.committee) metaBits.push(c.committee);
        li.innerHTML =
          '<span class="ac-option-name"></span>' +
          (metaBits.length
            ? '<span class="ac-option-meta"></span>'
            : "") +
          '<span class="ac-option-add" aria-hidden="true">Dodaj</span>';
        li.querySelector(".ac-option-name").textContent = c.name;
        const meta = li.querySelector(".ac-option-meta");
        if (meta) meta.textContent = metaBits.join(" · ");
        return li;
      }

      function highlightActive() {
        const items = pool.querySelectorAll(".ac-option");
        items.forEach((el, i) => {
          el.classList.toggle("is-active", i === activeIndex);
          if (i === activeIndex) {
            el.scrollIntoView({ block: "nearest" });
            if (focusEl) focusEl.setAttribute("aria-activedescendant", el.id);
          }
        });
        if (activeIndex < 0 && focusEl) {
          focusEl.removeAttribute("aria-activedescendant");
        }
      }

      function renderResults(results) {
        pool.innerHTML = "";
        activeIndex = -1;
        const taken = new Set(rankedIds());
        let visible = 0;
        (results || []).forEach((c) => {
          const id = String(c.id);
          byId[id] = c;
          if (taken.has(id)) return;
          pool.appendChild(makePoolItem(c, visible));
          visible += 1;
        });
        const open = visible > 0;
        pool.hidden = !open;
        setExpanded(open);
        if (!filterActive()) {
          setStatus("Wpisz min. 3 znaki w dowolnym polu (albo datę) — kolejne pola zawężają.");
          return;
        }
        if (visible === 0) {
          setStatus("Brak kandydatów spełniających kryteria.");
        } else {
          setStatus("Podpowiedzi: " + visible + " — kliknij lub Enter, aby dodać.");
        }
      }

      function addCandidate(c) {
        if (!c) return;
        const id = String(c.id);
        if (rankedIds().includes(id)) {
          setStatus("Ta osoba jest już w rankingu.");
          return;
        }
        byId[id] = c;
        rankList.appendChild(makeRankItem(c));
        renumber(rankList);
        syncEmpty();
        [firstEl, secondEl, lastEl].forEach((el) => {
          if (el) el.value = "";
        });
        if (focusEl) focusEl.focus();
        scheduleSearch();
        setStatus("Dodano do rankingu.");
      }

      function runSearch() {
        if (!searchUrl) {
          setStatus("Brak adresu wyszukiwania.");
          return;
        }
        if (!filterActive()) {
          pool.innerHTML = "";
          pool.hidden = true;
          setExpanded(false);
          activeIndex = -1;
          setStatus("Wpisz min. 3 znaki w dowolnym polu (albo datę) — kolejne pola zawężają.");
          return;
        }

        const params = new URLSearchParams();
        params.set("first_name", firstValue());
        params.set("second_name", secondValue());
        params.set("last_name", lastValue());
        params.set("birth_date", birthValue());
        const exclude = rankedIds();
        if (exclude.length) params.set("exclude", exclude.join(","));

        const seq = ++requestSeq;
        setStatus("Szukam…");
        fetch(searchUrl + "?" + params.toString(), {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        })
          .then((res) => {
            if (!res.ok) throw new Error("HTTP " + res.status);
            return res.json();
          })
          .then((data) => {
            if (seq !== requestSeq) return;
            if (!data.active) {
              pool.innerHTML = "";
              pool.hidden = true;
              setExpanded(false);
              setStatus("Wpisz min. 3 znaki w dowolnym polu (albo datę) — kolejne pola zawężają.");
              return;
            }
            renderResults(data.results || []);
          })
          .catch(() => {
            if (seq !== requestSeq) return;
            pool.innerHTML = "";
            pool.hidden = true;
            setExpanded(false);
            setStatus("Nie udało się pobrać podpowiedzi.");
          });
      }

      function scheduleSearch() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(runSearch, 200);
      }

      pool.addEventListener("mousedown", (e) => {
        const item = e.target.closest(".ac-option");
        if (!item) return;
        e.preventDefault();
        const c = byId[item.dataset.id];
        addCandidate(c);
      });

      if (tooltipEl) {
        pool.addEventListener("mouseover", (e) => {
          const item = e.target.closest(".ac-option");
          if (!item) return;
          const id = item.dataset.id;
          if (!id) return;
          if (hoverTooltipId !== id && byId[id]) {
            showTooltipForId(id, e.clientX, e.clientY);
            return;
          }
          if (hoverTooltipId === id) moveTooltip(e.clientX, e.clientY);
        });
        pool.addEventListener("mousemove", (e) => {
          if (hoverTooltipId) moveTooltip(e.clientX, e.clientY);
        });
        pool.addEventListener("mouseleave", () => hideTooltip());
      }

      rankList.addEventListener("click", (e) => {
        const btn = e.target.closest(".js-remove-rank");
        if (!btn) return;
        const item = btn.closest(".candidate-item");
        if (!item) return;
        item.remove();
        renumber(rankList);
        syncEmpty();
        scheduleSearch();
      });

      if (tooltipEl) {
        rankList.addEventListener("mouseover", (e) => {
          const item = e.target.closest(".candidate-item");
          if (!item) return;
          const id = item.dataset.id;
          if (!id) return;
          if (hoverTooltipId !== id && byId[id]) {
            showTooltipForId(id, e.clientX, e.clientY);
            return;
          }
          if (hoverTooltipId === id) moveTooltip(e.clientX, e.clientY);
        });
        rankList.addEventListener("mousemove", (e) => {
          if (hoverTooltipId) moveTooltip(e.clientX, e.clientY);
        });
        rankList.addEventListener("mouseleave", () => hideTooltip());
      }

      function onFilterKeydown(e) {
        const items = pool.querySelectorAll(".ac-option");
        if (e.key === "ArrowDown") {
          if (!items.length) return;
          e.preventDefault();
          activeIndex = Math.min(activeIndex + 1, items.length - 1);
          highlightActive();
        } else if (e.key === "ArrowUp") {
          if (!items.length) return;
          e.preventDefault();
          activeIndex = Math.max(activeIndex - 1, 0);
          highlightActive();
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (activeIndex >= 0 && items[activeIndex]) {
            addCandidate(byId[items[activeIndex].dataset.id]);
          } else if (items.length === 1) {
            addCandidate(byId[items[0].dataset.id]);
          }
        } else if (e.key === "Escape") {
          pool.hidden = true;
          setExpanded(false);
          activeIndex = -1;
        }
      }

      [firstEl, secondEl, lastEl].forEach((el) => {
        if (!el) return;
        el.addEventListener("input", scheduleSearch);
        el.addEventListener("keydown", onFilterKeydown);
      });
      if (birthEl) {
        birthEl.addEventListener("change", scheduleSearch);
        birthEl.addEventListener("input", scheduleSearch);
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
      pool.hidden = true;
      setExpanded(false);
      setStatus("Wpisz min. 3 znaki w dowolnym polu (albo datę) — kolejne pola zawężają.");
      return { addCandidate };
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
