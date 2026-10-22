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

  function syncNature() {
    if (nature.value === "Finish product") {
      method.value = "N/A";
    } else if (nature.value === "OEM" && method.value === "N/A") {
      method.value = "";
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

document.addEventListener("DOMContentLoaded", () => {
  initConditionalFields();
  initTagAutocomplete();
  initTagSimilarityCheck();
  initClickableRows();
});
