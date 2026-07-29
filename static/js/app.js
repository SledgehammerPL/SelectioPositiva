(function () {
  "use strict";

  function renumber(listEl) {
    listEl.querySelectorAll(".candidate-item").forEach((item, idx) => {
      const num = item.querySelector(".rank-num");
      if (num) num.textContent = String(idx + 1);
      const input = item.querySelector('input[name="ranked_user_ids"]');
      if (input) input.value = item.dataset.id;
    });
  }

  window.SelectioCandidateTooltip = {
    init(opts) {
      const tooltipEl =
        opts.tooltipEl || document.getElementById("candidate-tooltip");
      if (!tooltipEl) return null;

      const nameEl = tooltipEl.querySelector(".candidate-tooltip-name");
      const metaEl = tooltipEl.querySelector(".candidate-tooltip-meta");
      const byId = opts.byId || {};
      const gap = opts.gap != null ? opts.gap : 22;
      const pad = 8;
      let hoverId = null;

      function hide() {
        hoverId = null;
        tooltipEl.hidden = true;
        tooltipEl.setAttribute("aria-hidden", "true");
      }

      function render(c) {
        if (!nameEl || !metaEl || !c) return;
        nameEl.textContent = c.name || "";
        const parts = [];
        if (c.birth_date) parts.push("ur. " + c.birth_date);
        if (c.municipality) parts.push("zam. " + c.municipality);
        metaEl.textContent = parts.length
          ? parts.join(" · ")
          : "Szczegóły chwilowo niedostępne";
      }

      function move(clientX, clientY) {
        if (tooltipEl.hidden) return;
        const rect = tooltipEl.getBoundingClientRect();
        // Odstęp od kursora — nie nachodzi na uchwyt przeciągania.
        let left = clientX - rect.width - gap;
        let top = clientY + gap;
        if (left < pad) left = clientX + gap;
        if (top + rect.height > window.innerHeight - pad) {
          top = clientY - rect.height - gap;
        }
        left = Math.max(
          pad,
          Math.min(left, window.innerWidth - rect.width - pad)
        );
        top = Math.max(
          pad,
          Math.min(top, window.innerHeight - rect.height - pad)
        );
        tooltipEl.style.left = left + "px";
        tooltipEl.style.top = top + "px";
      }

      function show(id, clientX, clientY) {
        const c = byId[String(id)];
        if (!c) return;
        hoverId = String(id);
        render(c);
        tooltipEl.hidden = false;
        tooltipEl.setAttribute("aria-hidden", "false");
        move(clientX, clientY);
      }

      function bindRoot(root, itemSelector, skipSelector) {
        if (!root) return;
        root.addEventListener("mouseover", (e) => {
          if (skipSelector && e.target.closest(skipSelector)) {
            hide();
            return;
          }
          const item = e.target.closest(itemSelector);
          if (!item || !root.contains(item)) return;
          const id = item.dataset.id;
          if (!id) return;
          if (hoverId !== String(id)) show(id, e.clientX, e.clientY);
          else move(e.clientX, e.clientY);
        });
        root.addEventListener("mousemove", (e) => {
          if (skipSelector && e.target.closest(skipSelector)) {
            hide();
            return;
          }
          if (hoverId) move(e.clientX, e.clientY);
        });
        root.addEventListener("mouseleave", () => hide());
        root.addEventListener("mousedown", (e) => {
          if (skipSelector && e.target.closest(skipSelector)) hide();
        });
      }

      (opts.roots || []).forEach((cfg) => {
        bindRoot(cfg.root, cfg.itemSelector, cfg.skipSelector);
      });

      return { hide, show, byId };
    },
  };

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

      (opts.ranked || []).forEach((c) => {
        byId[String(c.id)] = c;
      });

      const tipApi = window.SelectioCandidateTooltip
        ? window.SelectioCandidateTooltip.init({
            byId,
            gap: 22,
            roots: [
              { root: pool, itemSelector: ".ac-option" },
              {
                root: rankList,
                itemSelector: ".candidate-item",
                skipSelector: ".drag-handle, .js-remove-rank",
              },
            ],
          })
        : null;

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
        li.querySelector('input[name="ranked_user_ids"]').value = String(c.id);
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
          (metaBits.length ? '<span class="ac-option-meta"></span>' : "") +
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
          setStatus(
            "Wpisz min. 3 znaki w dowolnym polu (albo datę) — kolejne pola zawężają."
          );
          return;
        }
        if (visible === 0) {
          setStatus("Brak kandydatów spełniających kryteria.");
        } else {
          setStatus(
            "Podpowiedzi: " + visible + " — kliknij lub Enter, aby dodać."
          );
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
          setStatus(
            "Wpisz min. 3 znaki w dowolnym polu (albo datę) — kolejne pola zawężają."
          );
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
              setStatus(
                "Wpisz min. 3 znaki w dowolnym polu (albo datę) — kolejne pola zawężają."
              );
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
        addCandidate(byId[item.dataset.id]);
        if (tipApi) tipApi.hide();
      });

      rankList.addEventListener("click", (e) => {
        const btn = e.target.closest(".js-remove-rank");
        if (!btn) return;
        const item = btn.closest(".candidate-item");
        if (!item) return;
        item.remove();
        renumber(rankList);
        syncEmpty();
        scheduleSearch();
        if (tipApi) tipApi.hide();
      });

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
          if (tipApi) tipApi.hide();
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
          onStart() {
            if (tipApi) tipApi.hide();
          },
          onSort() {
            renumber(rankList);
          },
        });
      }
      renumber(rankList);
      syncEmpty();
      pool.hidden = true;
      setExpanded(false);
      setStatus(
        "Wpisz min. 3 znaki w dowolnym polu (albo datę) — kolejne pola zawężają."
      );
      return { addCandidate };
    },
  };
})();
