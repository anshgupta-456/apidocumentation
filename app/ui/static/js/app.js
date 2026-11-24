/* API Contract Validator - small vanilla JS layer for the dashboard */
(function () {
  "use strict";

  // ------------------------------------------------------------- helpers
  async function api(method, url, body) {
    const options = { method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const res = await fetch(url, options);
    if (res.status === 204) return null;
    let data = null;
    try { data = await res.json(); } catch (_) { /* non JSON */ }
    if (!res.ok) {
      const detail = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : res.statusText;
      throw new Error(detail || `Request failed (${res.status})`);
    }
    return data;
  }

  function toast(title, message, type) {
    const box = document.getElementById("toasts");
    if (!box) return;
    const el = document.createElement("div");
    el.className = `toast ${type || ""}`;
    const b = document.createElement("b");
    b.textContent = title;
    el.appendChild(b);
    if (message) el.appendChild(document.createTextNode(message));
    box.appendChild(el);
    setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s"; }, 4200);
    setTimeout(() => el.remove(), 4600);
  }

  // Persist a toast across a reload.
  function flash(title, message, type) {
    sessionStorage.setItem("flash", JSON.stringify({ title, message, type }));
  }
  function showFlash() {
    const raw = sessionStorage.getItem("flash");
    if (!raw) return;
    sessionStorage.removeItem("flash");
    try { const f = JSON.parse(raw); toast(f.title, f.message, f.type); } catch (_) { /* ignore */ }
  }

  function reloadWith(title, message, type) {
    flash(title, message, type || "success");
    window.location.reload();
  }

  // ------------------------------------------------------------- actions
  const actions = {
    async "demo-traffic"() {
      const r = await api("POST", "/demo/traffic?requests=60");
      reloadWith("Demo traffic generated", `${r.sent} requests (${r.client_errors} client errors).`);
    },

    async "extract-spec"() {
      const r = await api("GET", "/extract-openapi?include_spec=false");
      let msg = r.message;
      if (r.diff && r.diff.summary) {
        const s = r.diff.summary;
        msg += ` · +${s.added_endpoints} / -${s.removed_endpoints} endpoints, ${s.breaking_changes} breaking`;
      }
      reloadWith(r.changed ? "New spec version stored" : "Spec unchanged", msg);
    },

    async "scan-all"() {
      const r = await api("POST", "/drift/scan", { save: true, use_ai: true });
      if (!r.scanned) {
        toast("Nothing to scan", "No traffic captured yet. Generate demo traffic or call your /api endpoints.", "error");
        return;
      }
      reloadWith(
        "Scan complete",
        `${r.scanned} endpoint(s) scanned · ${r.with_drift} with drift · ${r.new_events} new event(s).`
      );
    },

    async "scan-endpoint"(btn) {
      const { endpoint, method } = btn.dataset;
      const r = await api("GET", `/detect-drift${endpoint}?method=${encodeURIComponent(method)}`);
      const res = r.results[0];
      if (res.status === "no_traffic") {
        toast("No traffic yet", `${method} ${endpoint} has no captured requests.`, "error");
      } else if (!res.has_drift) {
        toast("No drift", `${method} ${endpoint} matches its contract (${res.sample_size.total} samples).`, "success");
      } else if (res.event_id && btn.dataset.open !== "false") {
        flash("Drift detected", `${res.issue_count} issue(s), severity ${res.severity}.`, "error");
        window.location.href = `/ui/drift/${res.event_id}`;
      } else {
        reloadWith("Drift detected", `${res.issue_count} issue(s), severity ${res.severity}.`, "error");
      }
    },

    async "set-status"(btn) {
      await api("PATCH", `/drift-events/${btn.dataset.id}`, { status: btn.dataset.status });
      reloadWith("Status updated", `Event marked as ${btn.dataset.status}.`);
    },

    async "save-notes"(btn) {
      const notes = document.getElementById("notes").value;
      await api("PATCH", `/drift-events/${btn.dataset.id}`, { notes });
      toast("Notes saved", "", "success");
    },

    async "delete-event"(btn) {
      if (!confirm("Delete this drift event? This cannot be undone.")) return;
      await api("DELETE", `/drift-events/${btn.dataset.id}`);
      flash("Event deleted", "", "success");
      window.location.href = "/ui/drifts";
    },

    async "apply-patch"(btn) {
      const r = await api("POST", `/patch/apply?event_id=${btn.dataset.id}`);
      const o = r.results.openapi;
      if (o.generated_spec_path) {
        toast("Patch applied", `Updated ${o.changed_operations.join(", ")} → ${o.generated_spec_path}`, "success");
        const link = document.getElementById("generated-link");
        if (link) link.hidden = false;
      } else {
        toast("Nothing to apply", o.message, "error");
      }
    },

    async "clear-logs"(btn) {
      const { endpoint, method } = btn.dataset;
      const scope = endpoint ? `${method || ""} ${endpoint}`.trim() : "ALL endpoints";
      if (!confirm(`Delete captured traffic for ${scope}? This cannot be undone.`)) return;
      const params = new URLSearchParams();
      if (endpoint) params.set("endpoint", endpoint);
      if (method) params.set("method", method);
      const r = await api("DELETE", `/api-logs?${params}`);
      reloadWith("Logs cleared", r.message);
    },

    async copy(btn) {
      const target = document.getElementById(btn.dataset.target);
      if (!target) return;
      await navigator.clipboard.writeText(target.innerText);
      const old = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = old; }, 1400);
    },

    "toggle-theme"() {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      localStorage.setItem("theme", next);
    },
  };

  document.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-action]");
    if (btn) {
      event.preventDefault();
      const handler = actions[btn.dataset.action];
      if (!handler) return;
      btn.classList.add("loading");
      try {
        await handler(btn);
      } catch (err) {
        toast("Something went wrong", err.message, "error");
      } finally {
        btn.classList.remove("loading");
      }
      return;
    }
    const row = event.target.closest("tr[data-href]");
    if (row && !event.target.closest("a, button, summary")) {
      window.location.href = row.dataset.href;
    }
  });

  // Auto-submit filter forms when a select changes.
  document.addEventListener("change", (event) => {
    if (event.target.matches("form[data-autosubmit] select")) event.target.form.submit();
  });

  // "/" focuses the search box.
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) {
      const search = document.querySelector("[data-search]");
      if (search) { event.preventDefault(); search.focus(); }
    }
  });

  // ------------------------------------------------------------- tabs
  document.querySelectorAll("[data-tabs]").forEach((root) => {
    const tabs = root.querySelectorAll(".tab");
    const panels = root.querySelectorAll(".tab-panel");
    tabs.forEach((tab) => tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.toggle("active", t === tab));
      panels.forEach((p) => p.classList.toggle("active", p.dataset.panel === tab.dataset.tab));
    }));
  });

  // ------------------------------------------------------------- syntax highlighting
  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function highlightJson(text) {
    return escapeHtml(text).replace(
      /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(?:true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
      (m) => {
        let cls = "j-num";
        if (/^"/.test(m)) cls = /:$/.test(m) ? "j-key" : "j-str";
        else if (/true|false/.test(m)) cls = "j-bool";
        else if (/null/.test(m)) cls = "j-null";
        return `<span class="${cls}">${m}</span>`;
      }
    );
  }
  const PY_KEYWORDS = new Set(["from", "import", "class", "def", "return", "None", "True", "False"]);
  const PY_TOKENS = /("[^"\n]*"|#.*$|\b(?:from|import|class|def|return|None|True|False|Optional|List|Dict|Union|Any|BaseModel|Field|str|int|float|bool)\b)/gm;
  function highlightPython(text) {
    // Single pass so inserted markup is never re-processed.
    return escapeHtml(text).replace(PY_TOKENS, (m) => {
      let cls = "py-type";
      if (m.startsWith('"')) cls = "py-str";
      else if (m.startsWith("#")) cls = "py-com";
      else if (PY_KEYWORDS.has(m)) cls = "py-kw";
      return `<span class="${cls}">${m}</span>`;
    });
  }
  document.querySelectorAll("pre[data-lang]").forEach((pre) => {
    const text = pre.textContent;
    if (pre.dataset.lang === "json") pre.innerHTML = highlightJson(text);
    else if (pre.dataset.lang === "python") pre.innerHTML = highlightPython(text);
  });

  showFlash();
})();
