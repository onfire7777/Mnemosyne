/* Local-only view state. Rows and compatibility are produced by the renderer. */
(() => {
  "use strict";
  const form = document.getElementById("comparison-controls");
  const group = document.getElementById("comparison-group");
  const checks = Array.from(form.querySelectorAll('input[name="system"]'));
  const sections = Array.from(document.querySelectorAll(".comparison-group"));
  const status = document.getElementById("comparison-status");
  function apply() {
    const params = new URLSearchParams(window.location.search);
    const requestedGroup = params.get("group") || "";
    const sameDataset = !params.has("dataset") || params.get("dataset") === form.dataset.source;
    const knownGroup = Array.from(group.options).some(option => option.value === requestedGroup);
    group.value = knownGroup ? requestedGroup : "";
    const selected = new Set(params.getAll("system"));
    checks.forEach(check => { check.checked = !params.has("selection") || selected.has(check.value); });
    const active = new Set(checks.filter(check => check.checked).map(check => check.value));
    let visibleRows = 0;
    let visibleGroups = 0;
    sections.forEach(section => {
      let count = 0;
      section.querySelectorAll("tbody tr[data-system]").forEach(row => {
        row.hidden = !active.has(row.dataset.system);
        if (!row.hidden) count++;
      });
      section.hidden = !sameDataset || !knownGroup || (!!requestedGroup && section.dataset.group !== requestedGroup) || count === 0;
      if (!section.hidden) { visibleRows += count; visibleGroups++; }
    });
    status.textContent = !sameDataset
      ? "This shared view refers to a different dataset version. Reset filters to inspect the current dataset."
      : knownGroup
      ? `${visibleRows} result rows in ${visibleGroups} compatible groups. No cross-group ranking.`
      : "The linked comparison group is unavailable in this dataset. Reset filters to view current groups.";
  }
  function save() {
    const url = new URL(window.location.href);
    url.searchParams.delete("group");
    url.searchParams.delete("system");
    url.searchParams.delete("selection");
    if (group.value) url.searchParams.set("group", group.value);
    url.searchParams.set("dataset", form.dataset.source);
    url.searchParams.set("selection", "custom");
    checks.filter(check => check.checked).forEach(check => url.searchParams.append("system", check.value));
    window.history.pushState(null, "", url);
    apply();
  }
  form.addEventListener("change", save);
  form.addEventListener("submit", event => event.preventDefault());
  document.getElementById("comparison-reset").addEventListener("click", () => {
    const url = new URL(window.location.href);
    ["group", "system", "selection", "dataset"].forEach(key => url.searchParams.delete(key));
    window.history.pushState(null, "", url);
    apply();
  });
  window.addEventListener("popstate", apply);
  form.hidden = false;
  apply();
})();
