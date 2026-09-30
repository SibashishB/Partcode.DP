(function () {
  const root = document.getElementById("root");
  const ME = JSON.parse(root.dataset.user);
  const MODULES = JSON.parse(root.dataset.modules);
  const CODE_MIN = Number(root.dataset.codeMin);
  const CODE_MAX = Number(root.dataset.codeMax);

  let CATEGORIES = {};
  let ALL_CODES = [];
  let SELECTED_IDS = new Set();

  // ---------------------------------------------------------------- utils
  async function api(url, options) {
    const res = await fetch(url, Object.assign({
      headers: { "Content-Type": "application/json" },
    }, options || {}));
    let data = null;
    try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) {
      const msg = (data && data.error) ? data.error : "Request failed.";
      throw new Error(msg);
    }
    return data;
  }

  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "text") e.textContent = v;
      else e.setAttribute(k, v);
    });
    (children || []).forEach(c => e.appendChild(c));
    return e;
  }

  // ---------------------------------------------------------------- tabs
  function applyNavAccess() {
    document.querySelectorAll(".nav-link").forEach(btn => {
      const tab = btn.dataset.tab;
      if (!MODULES.includes(tab)) return;
      if (!ME.access.includes(tab)) {
        btn.style.display = "none";
      }
    });
  }

  function switchTab(tab) {
    document.querySelectorAll(".nav-link").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
    document.querySelectorAll(".tab-panel").forEach(p => p.hidden = (p.id !== "tab-" + tab));
    if (tab === "history") loadHistory();
    if (tab === "user_management") loadUsers();
    if (tab === "categories") loadCategoriesTable();
  }

  document.querySelectorAll(".nav-link").forEach(btn => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  // ------------------------------------------------------------- account
  const accountBtn = document.getElementById("accountBtn");
  const accountMenu = document.getElementById("accountMenu");
  accountBtn.addEventListener("click", () => { accountMenu.hidden = !accountMenu.hidden; });
  document.addEventListener("click", (e) => {
    if (!accountBtn.contains(e.target) && !accountMenu.contains(e.target)) accountMenu.hidden = true;
  });

  // ==================================================================
  // HOME: category selector + dynamic form
  // ==================================================================
  const categorySelect = document.getElementById("categorySelect");
  const dynamicFields = document.getElementById("dynamicFields");
  const createBtn = document.getElementById("createBtn");
  const createError = document.getElementById("createError");
  const resultBox = document.getElementById("resultBox");
  const resultCode = document.getElementById("resultCode");

  function renderCategoryOptions() {
    categorySelect.innerHTML = "";
    Object.entries(CATEGORIES).forEach(([key, cat]) => {
      categorySelect.appendChild(el("option", { value: key, text: cat.label + "  (" + cat.code_format + ")" }));
    });
    renderDynamicFields();
  }

  function renderDynamicFields() {
    const cat = CATEGORIES[categorySelect.value];
    dynamicFields.innerHTML = "";
    if (!cat) return;
    cat.fields.forEach(f => {
      if (f.kind === "auto") return; // assigned server-side
      const label = el("label", { for: "f_" + f.key, text: f.label });
      dynamicFields.appendChild(label);
      if (f.kind === "choice") {
        const select = el("select", { id: "f_" + f.key, "data-field": f.key });
        select.appendChild(el("option", { value: "", text: "-- select --" }));
        f.choices.forEach(([code, lbl]) => select.appendChild(el("option", { value: code, text: lbl })));
        dynamicFields.appendChild(select);
      } else {
        const input = el("input", { type: "text", id: "f_" + f.key, "data-field": f.key });
        dynamicFields.appendChild(input);
      }
    });
  }

  categorySelect.addEventListener("change", renderDynamicFields);

  createBtn.addEventListener("click", async () => {
    createError.hidden = true;
    resultBox.hidden = true;
    const cat = CATEGORIES[categorySelect.value];
    const values = {};
    dynamicFields.querySelectorAll("[data-field]").forEach(inp => { values[inp.dataset.field] = inp.value; });
    try {
      const data = await api("/api/codes", {
        method: "POST",
        body: JSON.stringify({ category: categorySelect.value, values }),
      });
      resultCode.textContent = data.code;
      resultBox.hidden = false;
      resultBox.dataset.code = data.code;
      resultBox.dataset.id = data.id;
      loadRecent();
      loadChart(currentRange);
    } catch (e) {
      createError.textContent = e.message;
      createError.hidden = false;
    }
  });

  document.getElementById("copyBtn").addEventListener("click", () => {
    const code = resultBox.dataset.code || "";
    navigator.clipboard.writeText(code);
  });
  document.getElementById("downloadBtn").addEventListener("click", () => {
    const code = resultBox.dataset.code || "";
    downloadTxt(code + ".txt", code);
  });
  document.getElementById("downloadXlsxBtn").addEventListener("click", () => {
    const id = resultBox.dataset.id;
    if (id) downloadExport([Number(id)], "xlsx");
  });

  function downloadTxt(filename, content) {
    const blob = new Blob([content], { type: "text/plain" });
    const a = el("a", { href: URL.createObjectURL(blob), download: filename });
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function downloadExport(ids, format) {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, format }),
    });
    if (!res.ok) {
      let message = "Export failed.";
      try {
        const data = await res.json();
        if (data && data.error) message = data.error;
      } catch (e) { /* response wasn't JSON, keep generic message */ }
      alert(message);
      return;
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : ("export." + format);
    const a = el("a", { href: URL.createObjectURL(blob), download: filename });
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  // ---------------------------------------------------------- recent list
  async function loadRecent() {
    const codes = await api("/api/codes");
    ALL_CODES = codes;
    const tbody = document.querySelector("#recentTable tbody");
    tbody.innerHTML = "";
    codes.slice(0, 8).forEach(c => {
      tbody.appendChild(el("tr", {}, [
        el("td", {}, [el("code", { text: c.code })]),
        el("td", { text: (CATEGORIES[c.category] || {}).label || c.category }),
        el("td", { text: c.created_by }),
      ]));
    });
  }

  // ----------------------------------------------------------------chart
  let currentRange = "day";
  document.querySelectorAll("#chartFilters .pill").forEach(p => {
    p.addEventListener("click", () => {
      document.querySelectorAll("#chartFilters .pill").forEach(x => x.classList.remove("active"));
      p.classList.add("active");
      currentRange = p.dataset.range;
      loadChart(currentRange);
    });
  });

  async function loadChart(range) {
    const data = await api("/api/stats?granularity=" + range);
    drawBarChart(document.getElementById("chartSvg"), data.labels, data.values);
  }

  function drawBarChart(svg, labels, values) {
    svg.innerHTML = "";
    const W = 480, H = 220, padL = 30, padB = 30, padT = 10, padR = 10;
    const max = Math.max(1, ...values);
    const n = Math.max(1, labels.length);
    const chartW = W - padL - padR;
    const chartH = H - padT - padB;
    const barW = Math.min(36, chartW / n * 0.6);
    const gap = chartW / n;

    // axis line
    const axis = document.createElementNS("http://www.w3.org/2000/svg", "line");
    axis.setAttribute("x1", padL); axis.setAttribute("y1", H - padB);
    axis.setAttribute("x2", W - padR); axis.setAttribute("y2", H - padB);
    axis.setAttribute("stroke", "#dde3ec");
    svg.appendChild(axis);

    labels.forEach((label, i) => {
      const v = values[i];
      const barH = (v / max) * chartH;
      const x = padL + i * gap + (gap - barW) / 2;
      const y = H - padB - barH;

      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", x); rect.setAttribute("y", y);
      rect.setAttribute("width", barW); rect.setAttribute("height", Math.max(barH, 1));
      rect.setAttribute("rx", 3);
      rect.setAttribute("fill", "#1282a2");
      svg.appendChild(rect);

      const valText = document.createElementNS("http://www.w3.org/2000/svg", "text");
      valText.setAttribute("x", x + barW / 2); valText.setAttribute("y", y - 4);
      valText.setAttribute("text-anchor", "middle");
      valText.setAttribute("font-size", "10"); valText.setAttribute("fill", "#5c6a82");
      valText.textContent = v;
      svg.appendChild(valText);

      const labText = document.createElementNS("http://www.w3.org/2000/svg", "text");
      labText.setAttribute("x", x + barW / 2); labText.setAttribute("y", H - padB + 14);
      labText.setAttribute("text-anchor", "middle");
      labText.setAttribute("font-size", "9"); labText.setAttribute("fill", "#5c6a82");
      labText.textContent = label.length > 10 ? label.slice(5) : label;
      svg.appendChild(labText);
    });

    if (labels.length === 0) {
      const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
      t.setAttribute("x", W / 2); t.setAttribute("y", H / 2);
      t.setAttribute("text-anchor", "middle"); t.setAttribute("fill", "#5c6a82"); t.setAttribute("font-size", "13");
      t.textContent = "No codes created yet.";
      svg.appendChild(t);
    }
  }

  // ==================================================================
  // HISTORY
  // ==================================================================
  const historyFilter = document.getElementById("historyFilter");
  const selectAllBox = document.getElementById("selectAllBox");
  const historyCount = document.getElementById("historyCount");

  async function loadHistory() {
    const cat = historyFilter.value || "all";
    const codes = await api("/api/codes" + (cat !== "all" ? "?category=" + cat : ""));
    ALL_CODES = codes;
    SELECTED_IDS = new Set();
    selectAllBox.checked = false;
    renderHistoryTable(codes);
  }

  function renderHistoryTable(codes) {
    const tbody = document.querySelector("#historyTable tbody");
    tbody.innerHTML = "";
    codes.forEach(c => {
      const cb = el("input", { type: "checkbox", "data-id": c.id });
      cb.addEventListener("change", () => {
        if (cb.checked) SELECTED_IDS.add(c.id); else SELECTED_IDS.delete(c.id);
        updateHistoryCount();
      });
      tbody.appendChild(el("tr", {}, [
        el("td", {}, [cb]),
        el("td", {}, [el("code", { text: c.code })]),
        el("td", { text: (CATEGORIES[c.category] || {}).label || c.category }),
        el("td", { text: c.created_by }),
        el("td", { text: c.created_at }),
      ]));
    });
    updateHistoryCount();
  }

  function updateHistoryCount() {
    historyCount.textContent = SELECTED_IDS.size + " selected of " + ALL_CODES.length;
  }

  selectAllBox.addEventListener("change", () => {
    SELECTED_IDS = new Set();
    document.querySelectorAll("#historyTable [data-id]").forEach(cb => {
      cb.checked = selectAllBox.checked;
      if (selectAllBox.checked) SELECTED_IDS.add(Number(cb.dataset.id));
    });
    updateHistoryCount();
  });

  historyFilter.addEventListener("change", loadHistory);

  document.getElementById("downloadSelectedBtn").addEventListener("click", () => {
    if (SELECTED_IDS.size === 0) { alert("Select at least one code to download."); return; }
    downloadExport(Array.from(SELECTED_IDS), "txt");
  });
  document.getElementById("downloadSelectedXlsxBtn").addEventListener("click", () => {
    if (SELECTED_IDS.size === 0) { alert("Select at least one code to download."); return; }
    downloadExport(Array.from(SELECTED_IDS), "xlsx");
  });

  function populateHistoryFilterOptions() {
    Object.entries(CATEGORIES).forEach(([key, cat]) => {
      historyFilter.appendChild(el("option", { value: key, text: cat.label }));
    });
  }

  // ==================================================================
  // USER MANAGEMENT
  // ==================================================================
  async function loadUsers() {
    const users = await api("/api/users");
    const tbody = document.querySelector("#usersTable tbody");
    tbody.innerHTML = "";
    users.forEach(u => {
      const modulesText = u.access.map(a => a.replace("_", " ")).join(", ") || "none";
      const editBtn = el("button", { class: "icon-btn", text: "Edit access" });
      editBtn.addEventListener("click", () => openEditAccess(u));
      const resetBtn = el("button", { class: "icon-btn", text: "Reset password" });
      resetBtn.addEventListener("click", () => resetPassword(u));
      const delBtn = el("button", { class: "icon-btn danger", text: "Delete" });
      delBtn.addEventListener("click", () => deleteUser(u));

      const actionsCell = el("td", {}, [editBtn, resetBtn]);
      if (u.username !== "Master") actionsCell.appendChild(delBtn);

      tbody.appendChild(el("tr", {}, [
        el("td", { text: u.username }),
        el("td", {}, [el("span", { class: "badge-role " + u.role, text: u.role })]),
        el("td", { text: modulesText }),
        actionsCell,
      ]));
    });
  }

  function openEditAccess(u) {
    let role = u.role;
    if (ME.role === "Admin") {
      const newRole = prompt("Role for " + u.username + " (Admin/User):", u.role);
      if (newRole === null) return;
      role = (newRole.trim() === "Admin") ? "Admin" : "User";
    } else if (u.role === "Admin") {
      alert("Only an Admin can change another Admin's role or access.");
      return;
    }
    let access = u.access;
    if (role === "User") {
      const mods = prompt("Modules (comma-separated: home,history,user_management):", u.access.join(","));
      if (mods === null) return;
      access = mods.split(",").map(s => s.trim()).filter(Boolean);
    }
    api("/api/users/" + u.id, { method: "PUT", body: JSON.stringify({ role, access }) })
      .then(loadUsers)
      .catch(e => alert(e.message));
  }

  function resetPassword(u) {
    const pw = prompt("New password for " + u.username + ":");
    if (!pw) return;
    api("/api/users/" + u.id + "/reset_password", { method: "POST", body: JSON.stringify({ password: pw }) })
      .then(() => alert("Password updated."))
      .catch(e => alert(e.message));
  }

  function deleteUser(u) {
    if (!confirm("Delete user '" + u.username + "'? This can't be undone.")) return;
    api("/api/users/" + u.id, { method: "DELETE" })
      .then(loadUsers)
      .catch(e => alert(e.message));
  }

  document.getElementById("addUserBtn").addEventListener("click", async () => {
    const umError = document.getElementById("umError");
    umError.hidden = true;
    const username = document.getElementById("newUsername").value.trim();
    const password = document.getElementById("newPassword").value;
    const role = document.getElementById("newRole").value;
    const access = Array.from(document.querySelectorAll(".new-access:checked")).map(cb => cb.value);
    try {
      await api("/api/users", { method: "POST", body: JSON.stringify({ username, password, role, access }) });
      document.getElementById("newUsername").value = "";
      document.getElementById("newPassword").value = "";
      loadUsers();
    } catch (e) {
      umError.textContent = e.message;
      umError.hidden = false;
    }
  });

  document.getElementById("newRole").addEventListener("change", (e) => {
    document.getElementById("newAccessGroup").style.display = (e.target.value === "Admin") ? "none" : "block";
  });

  function setupRoleDropdown() {
    const roleSelect = document.getElementById("newRole");
    roleSelect.innerHTML = "";
    roleSelect.appendChild(el("option", { value: "User", text: "User" }));
    if (ME.role === "Admin") {
      roleSelect.appendChild(el("option", { value: "Admin", text: "Admin" }));
    }
    // Only an Admin can decide who else gets to manage users.
    const umCheckbox = document.querySelector('.new-access[value="user_management"]');
    if (umCheckbox && ME.role !== "Admin") {
      umCheckbox.checked = false;
      umCheckbox.disabled = true;
      umCheckbox.parentElement.title = "Only an Admin can grant User Management access.";
    }
  }

  // ==================================================================
  // MANAGE CATEGORIES (Admin only — not part of the delegable module list)
  // ==================================================================
  const fieldRowTemplate = document.getElementById("fieldRowTemplate");
  const newCatFields = document.getElementById("newCatFields");

  function addFieldRow() {
    const node = fieldRowTemplate.content.cloneNode(true);
    const row = node.querySelector(".field-row");
    const kindSelect = row.querySelector(".fr-kind");
    const choicesInput = row.querySelector(".fr-choices");
    kindSelect.addEventListener("change", () => {
      choicesInput.style.display = (kindSelect.value === "choice") ? "block" : "none";
      if (kindSelect.value !== "choice") choicesInput.value = "";
    });
    row.querySelector(".fr-remove").addEventListener("click", () => row.remove());
    newCatFields.appendChild(row);
  }
  document.getElementById("addFieldRowBtn").addEventListener("click", addFieldRow);

  document.getElementById("saveCategoryBtn").addEventListener("click", async () => {
    const catError = document.getElementById("catError");
    const catSuccess = document.getElementById("catSuccess");
    catError.hidden = true; catSuccess.hidden = true;

    const label = document.getElementById("newCatLabel").value.trim();
    const prefix = document.getElementById("newCatPrefix").value.trim() || "JEVBP";
    const includeAuto = document.getElementById("includeAutoSeq").checked;

    const fields = [];
    newCatFields.querySelectorAll(".field-row").forEach(row => {
      const flabel = row.querySelector(".fr-label").value.trim();
      const kind = row.querySelector(".fr-kind").value;
      const choicesRaw = row.querySelector(".fr-choices").value.trim();
      if (!flabel) return;
      fields.push({ label: flabel, kind, choices_raw: choicesRaw });
    });
    if (includeAuto) fields.push({ label: "Sequence", kind: "auto" });

    try {
      const res = await api("/api/categories", {
        method: "POST",
        body: JSON.stringify({ label, prefix, fields }),
      });
      catSuccess.textContent = "Category saved: format " + res.code_format;
      catSuccess.hidden = false;
      document.getElementById("newCatLabel").value = "";
      newCatFields.innerHTML = "";
      document.getElementById("includeAutoSeq").checked = false;
      CATEGORIES = await api("/api/categories");
      renderCategoryOptions();
      populateHistoryFilterOptions();
      loadCategoriesTable();
    } catch (e) {
      catError.textContent = e.message;
      catError.hidden = false;
    }
  });

  function lengthText(range) {
    if (!range) return "checked per code";
    return range[0] === range[1] ? String(range[0]) : range[0] + "\u2013" + range[1];
  }

  async function loadCategoriesTable() {
    const cats = await api("/api/categories");
    const tbody = document.querySelector("#categoriesTable tbody");
    tbody.innerHTML = "";
    Object.entries(cats).forEach(([key, cat]) => {
      const hasChoiceFields = cat.fields.some(f => f.kind === "choice");

      const actionsCell = el("td", {}, []);
      if (hasChoiceFields) {
        const manageBtn = el("button", { class: "icon-btn", text: "Manage options" });
        actionsCell.appendChild(manageBtn);
        manageBtn.addEventListener("click", () => {
          panelRow.hidden = !panelRow.hidden;
          if (!panelRow.hidden) renderOptionsPanel(panelTd, key, cat);
        });
      }
      if (cat.custom) {
        const delBtn = el("button", { class: "icon-btn danger", text: "Delete" });
        delBtn.addEventListener("click", async () => {
          if (!confirm("Delete category '" + cat.label + "'?")) return;
          try {
            await api("/api/categories/" + key, { method: "DELETE" });
            CATEGORIES = await api("/api/categories");
            renderCategoryOptions();
            populateHistoryFilterOptions();
            loadCategoriesTable();
          } catch (e) { alert(e.message); }
        });
        actionsCell.appendChild(delBtn);
      } else if (!hasChoiceFields) {
        actionsCell.appendChild(el("span", { class: "muted", text: "built-in" }));
      }

      tbody.appendChild(el("tr", {}, [
        el("td", { text: cat.label }),
        el("td", {}, [el("code", { text: cat.code_format })]),
        el("td", { text: lengthText(cat.length_range) }),
        el("td", { text: cat.custom ? "Custom" : "Built-in" }),
        actionsCell,
      ]));

      const panelTd = el("td", { colspan: "5" }, []);
      const panelRow = el("tr", { class: "option-panel-row" }, [panelTd]);
      panelRow.hidden = true;
      tbody.appendChild(panelRow);
    });
  }

  function renderOptionsPanel(container, key, cat) {
    container.innerHTML = "";
    const choiceFields = cat.fields.filter(f => f.kind === "choice");
    if (choiceFields.length === 0) {
      container.appendChild(el("p", { class: "muted", text: "This category has no dropdown fields." }));
      return;
    }
    choiceFields.forEach(f => {
      const block = el("div", { class: "option-field-block" });
      block.appendChild(el("h4", { text: f.label }));

      const tagsWrap = el("div", { class: "option-tags" });
      f.choices.forEach(choice => {
        const code = choice[0], label = choice[1], isCustom = choice[2];
        const tag = el("span", { class: "option-tag" + (isCustom ? " custom" : "") });
        tag.appendChild(document.createTextNode(label));
        if (isCustom) {
          const rm = el("button", { class: "tag-remove", type: "button", title: "Remove", text: "\u00d7" });
          rm.addEventListener("click", async () => {
            try {
              await api("/api/categories/" + key + "/fields/" + f.key + "/options/" + encodeURIComponent(code), { method: "DELETE" });
              CATEGORIES = await api("/api/categories");
              renderCategoryOptions();
              loadCategoriesTable();
            } catch (e) { alert(e.message); }
          });
          tag.appendChild(rm);
        }
        tagsWrap.appendChild(tag);
      });
      block.appendChild(tagsWrap);

      const addRow = el("div", { class: "option-add-row" });
      const codeInput = el("input", { type: "text", class: "code-input", placeholder: "Code, e.g. NEWSUP" });
      const labelInput = el("input", { type: "text", class: "label-input", placeholder: "Label, e.g. NewSupplier Inc" });
      const addBtn = el("button", { class: "btn-secondary", type: "button", text: "Add option" });
      addBtn.addEventListener("click", async () => {
        if (!codeInput.value.trim()) return;
        try {
          await api("/api/categories/" + key + "/fields/" + f.key + "/options", {
            method: "POST",
            body: JSON.stringify({ code: codeInput.value.trim(), label: labelInput.value.trim() }),
          });
          CATEGORIES = await api("/api/categories");
          renderCategoryOptions();
          loadCategoriesTable();
        } catch (e) { alert(e.message); }
      });
      addRow.appendChild(codeInput);
      addRow.appendChild(labelInput);
      addRow.appendChild(addBtn);
      block.appendChild(addRow);

      container.appendChild(block);
    });
  }

  // ==================================================================
  // IMPORT HISTORICAL CODES (Admin only)
  // ==================================================================
  document.getElementById("importBtn").addEventListener("click", async () => {
    const fileInput = document.getElementById("importFile");
    const importError = document.getElementById("importError");
    const importResult = document.getElementById("importResult");
    importError.hidden = true; importResult.hidden = true;

    if (!fileInput.files.length) {
      importError.textContent = "Choose a .csv or .xlsx file first.";
      importError.hidden = false;
      return;
    }
    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    try {
      const res = await fetch("/api/import", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Import failed.");
      importResult.textContent =
        "Imported " + data.inserted + " new code(s). Skipped " + data.skipped_duplicate +
        " already-known duplicate(s) and " + data.skipped_invalid + " row(s) with no code, out of " +
        data.total_rows + " row(s) read." +
        (data.off_standard
          ? " Note: " + data.off_standard + " imported code(s) are outside the " + CODE_MIN + "\u2013" + CODE_MAX +
            " character standard \u2014 they're kept for duplicate checking but worth reviewing."
          : "");
      importResult.hidden = false;
      fileInput.value = "";
      CATEGORIES = await api("/api/categories");
      renderCategoryOptions();
      populateHistoryFilterOptions();
      loadCategoriesTable();
      loadRecent();
      loadChart(currentRange);
    } catch (e) {
      importError.textContent = e.message;
      importError.hidden = false;
    }
  });

  // ==================================================================
  // INIT
  // ==================================================================
  async function init() {
    applyNavAccess();
    document.getElementById("lengthRule").textContent =
      "Every code is " + CODE_MIN + "\u2013" + CODE_MAX + " characters (hyphens included).";
    if (!ME.access.includes("user_management")) {
      document.getElementById("umNavLink").style.display = "none";
    }
    if (ME.role !== "Admin") {
      document.getElementById("catNavLink").style.display = "none";
    }
    setupRoleDropdown();
    CATEGORIES = await api("/api/categories");
    renderCategoryOptions();
    populateHistoryFilterOptions();
    await loadRecent();
    await loadChart(currentRange);
  }

  init();
})();
