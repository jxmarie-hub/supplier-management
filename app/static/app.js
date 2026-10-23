/* Client UX helpers: conditional fields, tag autocomplete, similarity, clickable rows */
function initConditionalFields() {
  const country = document.getElementById("field-country");
  const province = document.getElementById("field-cn-province");
  const nature = document.getElementById("field-nature");
  const method = document.getElementById("field-method");
  if (!country || !province || !nature || !method) return;

  function syncCountry() {
    if (country.value === "China") {
      province.disabled = false;
      if (province.value === "N/A") province.value = "";
    } else {
      province.value = "N/A";
    }
  }

  const itemGroup = document.getElementById("field-item-group");
  const hintItem = document.getElementById("hint-item-group");
  const hintMethod = document.getElementById("hint-method");

  const reqItem = document.getElementById("req-item-group");
  const reqMethod = document.getElementById("req-method");

  function syncNature() {
    const isFinish = nature.value === "Finish product";
    const isOem = nature.value === "OEM";
    if (isFinish) {
      method.value = "";
    }
    if (hintItem) hintItem.hidden = !isFinish;
    if (hintMethod) hintMethod.hidden = !isOem;
    if (reqItem) reqItem.hidden = !isFinish;
    if (reqMethod) reqMethod.hidden = !isOem;
    if (itemGroup) {
      if (isFinish) itemGroup.setAttribute("required", "required");
      else itemGroup.removeAttribute("required");
    }
    if (method) {
      if (isOem) method.setAttribute("required", "required");
      else method.removeAttribute("required");
    }
  }

  country.addEventListener("change", syncCountry);
  nature.addEventListener("change", syncNature);
  syncCountry();
  syncNature();
}

function initTagAutocomplete() {
  document.querySelectorAll(".tag-input").forEach((input) => {
    let timer = null;
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const q = input.value.trim();
        if (q.length < 1) return;
        try {
          const res = await fetch("/api/tags?q=" + encodeURIComponent(q));
          if (!res.ok) return;
          const data = await res.json();
          const listId = input.getAttribute("list");
          const dl = listId ? document.getElementById(listId) : null;
          if (!dl) return;
          dl.innerHTML = "";
          (data.tags || []).forEach((t) => {
            const opt = document.createElement("option");
            opt.value = t;
            dl.appendChild(opt);
          });
        } catch (e) {
          /* ignore */
        }
      }, 200);
    });
  });
}

function initTagSimilarityCheck() {
  document.querySelectorAll(".tag-input").forEach((input) => {
    const idx = input.getAttribute("data-tag-index");
    if (!idx) return;
    const resolveInput = document.getElementById("tag-resolve-" + idx);
    const box = document.getElementById("tag-resolve-box-" + idx);

    async function checkSimilar() {
      const q = input.value.trim();
      if (!q) {
        if (resolveInput) resolveInput.value = "";
        if (box && !box.querySelector(".tag-resolve-card")) box.innerHTML = "";
        return;
      }
      // If server already rendered a card, leave it
      if (box && box.querySelector(".tag-resolve-card")) return;
      try {
        const res = await fetch("/api/tags/similar?q=" + encodeURIComponent(q));
        if (!res.ok) return;
        const data = await res.json();
        const similar = data.similar || [];
        if (!similar.length) {
          if (resolveInput) resolveInput.value = "";
          if (box) box.innerHTML = "";
          return;
        }
        if (!box) return;
        const preferred = similar[0];
        const useExisting = window.confirm(
          'Similar tag exists: "' + preferred + '".\n\nOK = Use existing\nCancel = Keep as typed "' + q + '"'
        );
        if (useExisting) {
          input.value = preferred;
          if (resolveInput) resolveInput.value = "use:" + preferred;
          box.innerHTML =
            '<p class="muted">Using existing tag “' + preferred + '”.</p>';
        } else {
          if (resolveInput) resolveInput.value = "keep";
          box.innerHTML =
            '<p class="muted">Keeping typed tag “' + q + '”.</p>';
        }
      } catch (e) {
        /* ignore */
      }
    }

    input.addEventListener("blur", () => {
      setTimeout(checkSimilar, 150);
    });
  });
}

function initClickableRows() {
  document.querySelectorAll("tr.clickable-row[data-href]").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.closest("a, button, input, label")) return;
      const href = row.getAttribute("data-href");
      if (href) window.location.href = href;
    });
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        const href = row.getAttribute("data-href");
        if (href) window.location.href = href;
      }
    });
  });
}


function initSupplierFormValidation() {
  const form = document.getElementById("supplier-form");
  if (!form) return;
  form.addEventListener("submit", (e) => {
    const email = (form.querySelector("#field-email") || {}).value || "";
    const tel = (form.querySelector("#field-tel") || {}).value || "";
    if (!String(email).trim() && !String(tel).trim()) {
      e.preventDefault();
      alert("Enter an email or a Tel / WhatsApp / WeChat number (at least one is required).");
      const focusEl = form.querySelector("#field-email") || form.querySelector("#field-tel");
      if (focusEl) focusEl.focus();
      return;
    }
    const natureEarly = (form.querySelector("#field-nature") || {}).value || "";
    if (!String(natureEarly).trim()) {
      e.preventDefault();
      alert("Nature of Product is required.");
      const n = form.querySelector("#field-nature");
      if (n) n.focus();
      return;
    }
    const grouping = (form.querySelector("#field-grouping") || {}).value || "";
    if (!String(grouping).trim()) {
      e.preventDefault();
      alert("Grouping is required.");
      const g = form.querySelector("#field-grouping");
      if (g) g.focus();
      return;
    }
    const t2 = (form.querySelector("#tag-input-2") || {}).value || "";
    const t3 = (form.querySelector("#tag-input-3") || {}).value || "";
    const t4 = (form.querySelector("#tag-input-4") || {}).value || "";
    if (!String(t2).trim() && !String(t3).trim() && !String(t4).trim()) {
      e.preventDefault();
      alert("Enter at least one Tag (Tag 2, 3, or 4).");
      const t = form.querySelector("#tag-input-2");
      if (t) t.focus();
      return;
    }
    const nature = (form.querySelector("#field-nature") || {}).value || "";
    const itemGroup = (form.querySelector("#field-item-group") || {}).value || "";
    const method = (form.querySelector("#field-method") || {}).value || "";
    if (nature === "Finish product" && !String(itemGroup).trim()) {
      e.preventDefault();
      alert("Item Group is required when Nature of Product is Finish product.");
      const ig = form.querySelector("#field-item-group");
      if (ig) ig.focus();
      return;
    }
    if (nature === "OEM" && !String(method).trim()) {
      e.preventDefault();
      alert("Production Method is required when Nature of Product is OEM.");
      const m = form.querySelector("#field-method");
      if (m) m.focus();
      return;
    }
  });
}


function initColumnFilters(tableSelector) {
  const table = document.querySelector(tableSelector || "table.data-table.filterable");
  if (!table) return;
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  if (!thead || !tbody) return;
  if (thead.querySelector("tr.col-filter-row")) return;

  const headerRow = thead.querySelector("tr");
  if (!headerRow) return;
  const headers = Array.from(headerRow.children);
  const filterRow = document.createElement("tr");
  filterRow.className = "col-filter-row";

  headers.forEach((th, colIdx) => {
    const cell = document.createElement("th");
    cell.className = "col-filter-cell";
    // Skip action column (last empty header or no label)
    const label = (th.textContent || "").trim();
    const isAction = !label || th.classList.contains("no-filter");
    if (isAction) {
      filterRow.appendChild(cell);
      return;
    }
    const select = document.createElement("select");
    select.className = "col-filter-select";
    select.setAttribute("aria-label", "Filter " + label);
    select.dataset.col = String(colIdx);
    const optAll = document.createElement("option");
    optAll.value = "";
    optAll.textContent = "All";
    select.appendChild(optAll);

    const values = new Set();
    Array.from(tbody.rows).forEach((row) => {
      const td = row.cells[colIdx];
      if (!td) return;
      const v = (td.textContent || "").replace(/\s+/g, " ").trim();
      if (v) values.add(v);
    });
    Array.from(values)
      .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }))
      .forEach((v) => {
        const opt = document.createElement("option");
        opt.value = v;
        opt.textContent = v.length > 40 ? v.slice(0, 37) + "…" : v;
        select.appendChild(opt);
      });

    select.addEventListener("change", () => applyColumnFilters(table));
    select.addEventListener("click", (e) => e.stopPropagation());
    cell.appendChild(select);
    filterRow.appendChild(cell);
  });

  thead.appendChild(filterRow);
}

function applyColumnFilters(table) {
  const tbody = table.querySelector("tbody");
  if (!tbody) return;
  const filters = Array.from(table.querySelectorAll("select.col-filter-select")).map((sel) => ({
    col: parseInt(sel.dataset.col, 10),
    value: sel.value,
  }));
  let visible = 0;
  Array.from(tbody.rows).forEach((row) => {
    if (row.querySelector("td[colspan]")) {
      row.style.display = "";
      return;
    }
    let show = true;
    for (const f of filters) {
      if (!f.value) continue;
      const td = row.cells[f.col];
      const cellText = td ? (td.textContent || "").replace(/\s+/g, " ").trim() : "";
      if (cellText !== f.value) {
        show = false;
        break;
      }
    }
    row.style.display = show ? "" : "none";
    if (show) visible += 1;
  });
  const counter = document.getElementById("result-filter-count");
  if (counter) {
    const total = Array.from(tbody.rows).filter((r) => !r.querySelector("td[colspan]")).length;
    counter.textContent =
      visible === total ? "" : " · showing " + visible + " of " + total + " (column filters)";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initConditionalFields();
  initTagAutocomplete();
  initTagSimilarityCheck();
  initClickableRows();
  initSupplierFormValidation();
  initColumnFilters("table.data-table.filterable");
});
