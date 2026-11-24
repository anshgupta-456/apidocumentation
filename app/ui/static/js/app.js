/* API Contract Validator - dashboard behaviour (vanilla JS, no dependencies) */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  // ================================================================ API + feedback
  async function api(method, url, body) {
    const options = { method, headers: { Accept: "application/json" }, credentials: "same-origin" };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const res = await fetch(url, options);
    if (res.status === 401) {
      window.location.href = `/ui/login?next=${encodeURIComponent(location.pathname + location.search)}`;
      throw new Error("Session expired - please sign in again.");
    }
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
    const box = $("#toasts");
    if (!box) return;
    const el = document.createElement("div");
    el.className = `toast ${type || ""}`;
    el.setAttribute("role", type === "error" ? "alert" : "status");
    const b = document.createElement("b");
    b.textContent = title;
    el.appendChild(b);
    if (message) el.appendChild(document.createTextNode(message));
    box.appendChild(el);
    setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s"; }, 4500);
    setTimeout(() => el.remove(), 4900);
  }
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

  // Styled confirmation dialog (replaces window.confirm).
  function confirmDialog({ title, message, confirmLabel = "Confirm", danger = false }) {
    return new Promise((resolve) => {
      const dlg = document.createElement("dialog");
      dlg.className = "modal";
      dlg.innerHTML = `<div class="modal-body"><h3></h3><p></p></div>
        <div class="modal-actions"><button class="btn" value="cancel">Cancel</button><button class="btn" value="ok"></button></div>`;
      $("h3", dlg).textContent = title;
      $("p", dlg).textContent = message;
      const ok = $('button[value="ok"]', dlg);
      ok.textContent = confirmLabel;
      ok.classList.add(danger ? "btn-danger-solid" : "btn-primary");
      document.body.appendChild(dlg);
      const done = (value) => { dlg.close(); dlg.remove(); resolve(value); };
      ok.addEventListener("click", () => done(true));
      $('button[value="cancel"]', dlg).addEventListener("click", () => done(false));
      dlg.addEventListener("cancel", (e) => { e.preventDefault(); done(false); });
      dlg.showModal();
      ok.focus();
    });
  }

  // ================================================================ formatting
  const nf = new Intl.NumberFormat();
  function compact(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const a = Math.abs(v);
    if (a >= 1e6) return `${+(v / 1e6).toFixed(1)}M`;
    if (a >= 1e4) return `${+(v / 1e3).toFixed(1)}K`;
    return Number.isInteger(v) ? nf.format(v) : nf.format(+v.toFixed(1));
  }
  function fmtTime(iso, bucket, long) {
    const d = new Date(iso);
    if (bucket === "hour") {
      const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      return long ? `${d.toLocaleDateString([], { month: "short", day: "numeric" })}, ${time}` : time;
    }
    return d.toLocaleDateString([], long ? { weekday: "short", month: "short", day: "numeric" } : { month: "short", day: "numeric" });
  }

  // ================================================================ tooltip
  const tip = document.createElement("div");
  tip.className = "tooltip";
  tip.hidden = true;
  document.body.appendChild(tip);

  function showTip(x, y, title, rows) {
    tip.replaceChildren();
    const t = document.createElement("div");
    t.className = "t-title";
    t.textContent = title;
    tip.appendChild(t);
    rows.forEach((r) => {
      const row = document.createElement("div");
      row.className = "t-row";
      const key = document.createElement("span");
      key.className = "t-key";
      if (r.color) {
        const i = document.createElement("i");
        i.style.background = r.color;
        key.appendChild(i);
      }
      key.appendChild(document.createTextNode(r.name));
      const val = document.createElement("b");
      val.textContent = r.value;
      row.append(val, key);
      row.style.flexDirection = "row-reverse";
      tip.appendChild(row);
    });
    tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let left = x + 14, top = y - h - 10;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (top < 8) top = y + 14;
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  }
  function hideTip() { tip.hidden = true; }

  // Generic hover tooltip for marks with data-tip-title / data-tip-value (e.g. segmented bars).
  document.addEventListener("pointerover", (e) => {
    const el = e.target.closest("[data-tip-title]");
    if (!el) return;
    const r = el.getBoundingClientRect();
    showTip(r.left + r.width / 2, r.top, el.dataset.tipTitle, [{ name: el.dataset.tipLabel || "", value: el.dataset.tipValue || "" }]);
  });
  document.addEventListener("pointerout", (e) => {
    if (e.target.closest("[data-tip-title]")) hideTip();
  });

  // ================================================================ charts
  const SVG = "http://www.w3.org/2000/svg";
  function svgEl(tag, attrs, parent) {
    const el = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
    if (parent) parent.appendChild(el);
    return el;
  }
  function niceStep(raw, integer) {
    if (raw <= 0) return 1;
    const exp = Math.pow(10, Math.floor(Math.log10(raw)));
    const f = raw / exp;
    let step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * exp;
    if (integer) step = Math.max(1, Math.ceil(step));
    return step;
  }

  function lineChart(container, cfg) {
    const width = container.clientWidth;
    const height = container.clientHeight || 220;
    if (!width) return;
    container.replaceChildren();
    const n = cfg.x.length;
    const series = cfg.series;
    const all = series.flatMap((s) => s.values).filter((v) => v !== null && v !== undefined);
    const maxVal = all.length ? Math.max(...all) : 0;
    const integer = cfg.unit !== "ms";
    const step = niceStep(maxVal / 4 || 1, integer);
    const yMax = Math.max(step, Math.ceil(maxVal / step) * step);
    const ticks = [];
    for (let v = 0; v <= yMax + 1e-9; v += step) ticks.push(v);

    const tickLabel = (v) => compact(v) + (cfg.unit === "ms" ? " ms" : "");
    const left = Math.max(...ticks.map((t) => tickLabel(t).length)) * 6.4 + 12;
    const m = { top: 10, right: 14, bottom: 26, left };
    const pw = width - m.left - m.right;
    const ph = height - m.top - m.bottom;
    const xAt = (i) => m.left + (n <= 1 ? pw / 2 : (i * pw) / (n - 1));
    const yAt = (v) => m.top + ph - (v / yMax) * ph;

    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", tabindex: "0", "aria-label": cfg.label || "Chart" });
    ticks.forEach((t) => {
      svgEl("line", { x1: m.left, x2: width - m.right, y1: yAt(t), y2: yAt(t), class: t === 0 ? "baseline" : "grid-line" }, svg);
      const label = svgEl("text", { x: m.left - 8, y: yAt(t) + 4, "text-anchor": "end", class: "tick" }, svg);
      label.textContent = tickLabel(t);
    });
    const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(pw / 74))));
    for (let i = 0; i < n; i += every) {
      const label = svgEl("text", { x: xAt(i), y: height - 6, "text-anchor": i === 0 ? "start" : "middle", class: "tick" }, svg);
      label.textContent = fmtTime(cfg.x[i], cfg.bucket, false);
    }

    series.forEach((s) => {
      const color = `var(${s.color})`;
      const segments = [];
      let current = [];
      s.values.forEach((v, i) => {
        if (v === null || v === undefined) { if (current.length) segments.push(current); current = []; }
        else current.push([xAt(i), yAt(v)]);
      });
      if (current.length) segments.push(current);
      segments.forEach((pts) => {
        if (s.area && pts.length > 1) {
          const d = `M${pts[0][0]},${yAt(0)} ` + pts.map((p) => `L${p[0]},${p[1]}`).join(" ") + ` L${pts[pts.length - 1][0]},${yAt(0)} Z`;
          const area = svgEl("path", { d, class: "area" }, svg);
          area.style.fill = color;
        }
        if (pts.length === 1) {
          const dot = svgEl("circle", { cx: pts[0][0], cy: pts[0][1], r: 4, class: "marker" }, svg);
          dot.style.fill = color;
        } else {
          const line = svgEl("path", { d: pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join(" "), class: "line" }, svg);
          line.style.stroke = color;
        }
      });
    });

    // hover layer: crosshair snaps to the nearest bucket, one tooltip lists every series
    const hover = svgEl("g", { visibility: "hidden" }, svg);
    const cross = svgEl("line", { y1: m.top, y2: m.top + ph, class: "crosshair" }, hover);
    const dots = series.map((s) => {
      const c = svgEl("circle", { r: 4, class: "marker" }, hover);
      c.style.fill = `var(${s.color})`;
      return c;
    });
    let active = null;
    function focusIndex(i, clientX, clientY) {
      active = Math.max(0, Math.min(n - 1, i));
      const x = xAt(active);
      cross.setAttribute("x1", x);
      cross.setAttribute("x2", x);
      series.forEach((s, k) => {
        const v = s.values[active];
        dots[k].setAttribute("visibility", v === null || v === undefined ? "hidden" : "visible");
        if (v !== null && v !== undefined) { dots[k].setAttribute("cx", x); dots[k].setAttribute("cy", yAt(v)); }
      });
      hover.setAttribute("visibility", "visible");
      const rect = svg.getBoundingClientRect();
      const px = clientX !== undefined ? clientX : rect.left + (x / width) * rect.width;
      const py = clientY !== undefined ? clientY : rect.top + m.top;
      showTip(px, py, fmtTime(cfg.x[active], cfg.bucket, true), series.map((s) => ({
        name: s.name,
        color: getComputedStyle(document.documentElement).getPropertyValue(s.color),
        value: s.values[active] === null || s.values[active] === undefined ? "—" : tickLabel(s.values[active]),
      })));
    }
    const hit = svgEl("rect", { x: m.left - 10, y: m.top, width: pw + 20, height: ph, fill: "transparent" }, svg);
    hit.addEventListener("pointermove", (e) => {
      const rect = svg.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * width;
      focusIndex(n <= 1 ? 0 : Math.round(((x - m.left) / pw) * (n - 1)), e.clientX, e.clientY);
    });
    hit.addEventListener("pointerleave", () => { hover.setAttribute("visibility", "hidden"); hideTip(); });
    svg.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        focusIndex((active === null ? n - 1 : active) + (e.key === "ArrowRight" ? 1 : -1));
      }
    });
    svg.addEventListener("focus", () => focusIndex(active === null ? n - 1 : active));
    svg.addEventListener("blur", () => { hover.setAttribute("visibility", "hidden"); hideTip(); });

    container.appendChild(svg);
    if (!all.some((v) => v > 0)) {
      const empty = document.createElement("div");
      empty.className = "chart-empty";
      empty.textContent = cfg.empty || "No data in this range";
      container.appendChild(empty);
    }
  }

  function sparkline(container, values) {
    const w = container.clientWidth || 90, h = container.clientHeight || 30;
    const max = Math.max(...values, 1);
    const pts = values.map((v, i) => [(i * (w - 4)) / Math.max(1, values.length - 1) + 2, h - 3 - (v / max) * (h - 6)]);
    const svg = svgEl("svg", { viewBox: `0 0 ${w} ${h}`, "aria-hidden": "true" });
    const line = svgEl("path", { d: pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join(" "), fill: "none", "stroke-width": 1.5, "stroke-linejoin": "round" }, svg);
    line.style.stroke = "var(--axis)";
    const last = pts[pts.length - 1];
    const dot = svgEl("circle", { cx: last[0], cy: last[1], r: 3 }, svg);
    dot.style.fill = "var(--series-1)";
    container.replaceChildren(svg);
  }

  const resizeObserver = "ResizeObserver" in window ? new ResizeObserver((entries) => {
    entries.forEach((entry) => {
      const el = entry.target;
      clearTimeout(el._t);
      el._t = setTimeout(() => drawChart(el), 60);
    });
  }) : null;

  function drawChart(el) {
    try {
      const cfg = JSON.parse(el.dataset.chart);
      if (cfg.type === "spark") sparkline(el, cfg.values);
      else lineChart(el, cfg);
    } catch (err) { console.error("chart failed", err); }
  }

  // ================================================================ content initialisers
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
  function escapeHtml(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  const PY_KEYWORDS = new Set(["from", "import", "class", "def", "return", "None", "True", "False"]);
  const PY_TOKENS = /("[^"\n]*"|#.*$|\b(?:from|import|class|def|return|None|True|False|Optional|List|Dict|Union|Any|BaseModel|Field|str|int|float|bool)\b)/gm;
  function highlightPython(text) {
    return escapeHtml(text).replace(PY_TOKENS, (m) => {
      let cls = "py-type";
      if (m.startsWith('"')) cls = "py-str";
      else if (m.startsWith("#")) cls = "py-com";
      else if (PY_KEYWORDS.has(m)) cls = "py-kw";
      return `<span class="${cls}">${m}</span>`;
    });
  }
  function highlight(pre) {
    const text = pre.textContent;
    if (pre.dataset.lang === "json") pre.innerHTML = highlightJson(text);
    else if (pre.dataset.lang === "python") pre.innerHTML = highlightPython(text);
  }

  function initContent(root) {
    $$("pre[data-lang]", root).forEach(highlight);
    $$("[data-chart]", root).forEach((el) => { drawChart(el); if (resizeObserver) resizeObserver.observe(el); });
    $$("[data-tabs]", root).forEach((box) => {
      const tabs = $$(".tab", box).filter((t) => t.closest("[data-tabs]") === box);
      const panels = $$(".tab-panel", box).filter((p) => p.closest("[data-tabs]") === box);
      tabs.forEach((tab) => tab.addEventListener("click", () => {
        tabs.forEach((t) => t.classList.toggle("active", t === tab));
        panels.forEach((p) => p.classList.toggle("active", p.dataset.panel === tab.dataset.tab));
      }));
    });
    $$("input[data-filter-table]", root).forEach((input) => {
      const table = document.getElementById(input.dataset.filterTable);
      input.addEventListener("input", () => {
        const q = input.value.trim().toLowerCase();
        $$("tbody tr", table).forEach((tr) => { tr.hidden = q && !tr.textContent.toLowerCase().includes(q); });
      });
    });
    initBulk(root);
    initLive(root);
    if ($("#pg-ops", root)) initPlayground();
    if ($("#login-form", root)) initLogin();
  }

  // ================================================================ live refresh
  let liveTimer = null;
  async function softRefresh() {
    const content = $(".content");
    if (!content || document.hidden) return;
    content.classList.add("refreshing");
    try {
      const res = await fetch(location.href, { credentials: "same-origin" });
      if (res.redirected && res.url.includes("/ui/login")) { location.href = res.url; return; }
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      const next = $(".content", doc);
      if (next) {
        if (resizeObserver) $$("[data-chart]", content).forEach((el) => resizeObserver.unobserve(el));
        content.innerHTML = next.innerHTML;
        initContent(content);
      }
    } catch (_) { /* keep the previous frame */ } finally {
      content.classList.remove("refreshing");
    }
  }
  function initLive(root) {
    const toggle = $("input[data-live]", root);
    if (!toggle) return;
    const key = `live:${location.pathname}`;
    toggle.checked = localStorage.getItem(key) === "1";
    const apply = () => {
      clearInterval(liveTimer);
      liveTimer = toggle.checked ? setInterval(softRefresh, 10000) : null;
      const ind = $("[data-live-indicator]", root);
      if (ind) ind.hidden = !toggle.checked;
    };
    toggle.addEventListener("change", () => { localStorage.setItem(key, toggle.checked ? "1" : "0"); apply(); });
    apply();
  }

  // ================================================================ bulk selection
  function initBulk(root) {
    const bar = $("[data-bulk-bar]", root);
    if (!bar) return;
    const boxes = () => $$("input[data-select-row]", root);
    const all = $("input[data-select-all]", root);
    const update = () => {
      const selected = boxes().filter((b) => b.checked);
      bar.hidden = selected.length === 0;
      $("[data-bulk-count]", bar).textContent = `${selected.length} selected`;
      boxes().forEach((b) => b.closest("tr").classList.toggle("selected", b.checked));
      if (all) all.checked = selected.length && selected.length === boxes().length;
    };
    boxes().forEach((b) => b.addEventListener("change", update));
    if (all) all.addEventListener("change", () => { boxes().forEach((b) => { b.checked = all.checked; }); update(); });
    update();
  }
  const selectedIds = () => $$("input[data-select-row]:checked").map((b) => b.value);

  // ================================================================ actions
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
        msg += ` · +${s.added_endpoints} / -${s.removed_endpoints} operations, ${s.breaking_changes} breaking`;
      }
      reloadWith(r.changed ? "New spec version stored" : "Spec unchanged", msg);
    },
    async "scan-all"() {
      const r = await api("POST", "/drift/scan", { save: true, use_ai: true });
      if (!r.scanned) {
        toast("Nothing to scan", "No traffic captured yet. Generate demo traffic or call your /api endpoints.", "error");
        return;
      }
      reloadWith("Scan complete", `${r.scanned} endpoint(s) scanned · ${r.with_drift} with drift · ${r.new_events} new event(s).`);
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
      await api("PATCH", `/drift-events/${btn.dataset.id}`, { notes: $("#notes").value });
      toast("Notes saved", "", "success");
    },
    async "delete-event"(btn) {
      const ok = await confirmDialog({ title: "Delete drift event?", message: "The event, its explanation and patches are removed permanently.", confirmLabel: "Delete", danger: true });
      if (!ok) return;
      await api("DELETE", `/drift-events/${btn.dataset.id}`);
      flash("Event deleted", "", "success");
      window.location.href = "/ui/drifts";
    },
    async bulk(btn) {
      const ids = selectedIds();
      if (!ids.length) return;
      const del = btn.dataset.delete === "true";
      if (del) {
        const ok = await confirmDialog({ title: `Delete ${ids.length} event(s)?`, message: "This cannot be undone.", confirmLabel: "Delete", danger: true });
        if (!ok) return;
      }
      const r = await api("POST", "/drift-events/bulk", del ? { ids, delete: true } : { ids, status: btn.dataset.status });
      reloadWith("Done", r.message);
    },
    async "apply-patch"(btn) {
      const r = await api("POST", `/patch/apply?event_id=${btn.dataset.id}`);
      const o = r.results.openapi;
      if (o.generated_spec_path) {
        toast("Patch applied", `Updated ${o.changed_operations.join(", ")}.`, "success");
        const link = $("#generated-link");
        if (link) link.hidden = false;
      } else {
        toast("Nothing to apply", o.message, "error");
      }
    },
    async "clear-logs"(btn) {
      const { endpoint, method } = btn.dataset;
      const scope = endpoint ? `${method || ""} ${endpoint}`.trim() : "ALL endpoints";
      const ok = await confirmDialog({ title: "Clear captured traffic?", message: `All captured requests for ${scope} will be deleted. Drift events are kept.`, confirmLabel: "Clear logs", danger: true });
      if (!ok) return;
      const params = new URLSearchParams();
      if (endpoint) params.set("endpoint", endpoint);
      if (method) params.set("method", method);
      const r = await api("DELETE", `/api-logs?${params}`);
      reloadWith("Logs cleared", r.message);
    },
    async "test-alert"() {
      const r = await api("POST", "/alerts/test");
      toast("Alert delivered", `Webhook answered ${r.status_code}.`, "success");
    },
    async "run-cleanup"() {
      const r = await api("POST", "/system/cleanup");
      reloadWith("Retention cleanup", r.message);
    },
    async "run-scan-job"() {
      const r = await api("POST", "/system/scan");
      reloadWith("Scan complete", `${r.scanned} scanned · ${r.with_drift} with drift · ${r.new_events} new event(s).`);
    },
    async logout() {
      await api("POST", "/auth/logout");
      window.location.href = "/ui/login";
    },
    replay(btn) {
      sessionStorage.setItem("replay", JSON.stringify({ method: btn.dataset.method, path: btn.dataset.path, route: btn.dataset.route, body: btn.dataset.body || "" }));
      window.location.href = "/ui/playground?replay=1";
    },
    async copy(btn) {
      const target = document.getElementById(btn.dataset.target);
      if (!target) return;
      await navigator.clipboard.writeText(target.value !== undefined ? target.value : target.innerText);
      const old = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = old; }, 1400);
    },
    "toggle-theme"() {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      localStorage.setItem("theme", next);
    },
    "open-palette"() { openPalette(); },
    "toggle-nav"() { document.body.classList.toggle("nav-open"); },
  };

  async function runAction(name, btn) {
    const handler = actions[name];
    if (!handler) return;
    btn.classList.add("loading");
    try {
      await handler(btn);
    } catch (err) {
      toast("Something went wrong", err.message, "error");
    } finally {
      btn.classList.remove("loading");
    }
  }

  document.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-action]");
    if (btn) {
      event.preventDefault();
      await runAction(btn.dataset.action, btn);
      return;
    }
    if (event.target.closest(".scrim")) document.body.classList.remove("nav-open");
    const row = event.target.closest("tr[data-href]");
    if (row && !event.target.closest("a, button, summary, input, label")) {
      startProgress();
      window.location.href = row.dataset.href;
    }
  });

  document.addEventListener("change", (event) => {
    if (event.target.matches("form[data-autosubmit] select")) event.target.form.submit();
  });

  // ================================================================ navigation progress
  function startProgress() { const p = $("#progress"); if (p) p.classList.add("active"); }
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (!a || a.target === "_blank" || e.ctrlKey || e.metaKey || e.shiftKey || a.hasAttribute("download")) return;
    const href = a.getAttribute("href");
    if (href.startsWith("#") || href.startsWith("javascript")) return;
    if (a.origin === location.origin && !/\/(export|download|generated-spec)/.test(a.pathname)) startProgress();
  });
  document.addEventListener("submit", () => startProgress());
  window.addEventListener("pageshow", () => { const p = $("#progress"); if (p) p.classList.remove("active"); });

  // ================================================================ command palette
  const PAGES = [
    ["Dashboard", "/ui", "g d"], ["Endpoints", "/ui/endpoints", "g e"], ["Drift events", "/ui/drifts", "g x"],
    ["Traffic logs", "/ui/logs", "g l"], ["API playground", "/ui/playground", "g p"], ["OpenAPI versions", "/ui/openapi", "g o"],
    ["Settings", "/ui/settings", "g s"], ["API reference (Swagger)", "/docs", ""],
  ];
  const PALETTE_ACTIONS = [
    ["Scan all endpoints for drift", "scan-all"], ["Snapshot the live OpenAPI spec", "extract-spec"],
    ["Generate demo traffic", "demo-traffic"], ["Toggle dark mode", "toggle-theme"],
  ];
  let paletteEndpoints = null;
  let paletteDlg = null;

  function buildPalette() {
    paletteDlg = document.createElement("dialog");
    paletteDlg.className = "palette";
    paletteDlg.innerHTML = `<div class="palette-input">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
        <input type="text" placeholder="Search pages, endpoints and actions…" aria-label="Command search" autocomplete="off">
        <span class="kbd">Esc</span></div>
      <div class="palette-list" role="listbox"></div>
      <div class="palette-foot"><span><span class="kbd">↑</span> <span class="kbd">↓</span> navigate</span><span><span class="kbd">Enter</span> open</span></div>`;
    document.body.appendChild(paletteDlg);
    const input = $("input", paletteDlg);
    input.addEventListener("input", () => renderPalette(input.value));
    input.addEventListener("keydown", (e) => {
      const items = $$(".palette-item", paletteDlg);
      let idx = items.findIndex((i) => i.classList.contains("active"));
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        idx = e.key === "ArrowDown" ? Math.min(items.length - 1, idx + 1) : Math.max(0, idx - 1);
        items.forEach((i, k) => i.classList.toggle("active", k === idx));
        if (items[idx]) items[idx].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter" && items[idx]) {
        e.preventDefault();
        items[idx].click();
      }
    });
    paletteDlg.addEventListener("click", (e) => { if (e.target === paletteDlg) paletteDlg.close(); });
  }

  function paletteEntries() {
    const entries = PAGES.map(([label, href, hint]) => ({ group: "Pages", label, hint, run: () => { startProgress(); location.href = href; } }));
    PALETTE_ACTIONS.forEach(([label, action]) => entries.push({
      group: "Actions", label, hint: "", run: () => { paletteDlg.close(); runAction(action, document.createElement("button")); },
    }));
    (paletteEndpoints || []).forEach((ep) => entries.push({
      group: "Endpoints", label: `${ep.method} ${ep.endpoint}`, hint: ep.open_drifts ? `${ep.open_drifts} open drift` : `${ep.requests} req`,
      run: () => { startProgress(); location.href = `/ui/endpoint?method=${ep.method}&path=${encodeURIComponent(ep.endpoint)}`; },
    }));
    return entries;
  }

  function renderPalette(query) {
    const list = $(".palette-list", paletteDlg);
    list.replaceChildren();
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    const matches = paletteEntries().filter((e) => words.every((w) => e.label.toLowerCase().includes(w)));
    let lastGroup = null;
    matches.slice(0, 40).forEach((entry, i) => {
      if (entry.group !== lastGroup) {
        const g = document.createElement("div");
        g.className = "palette-group";
        g.textContent = entry.group;
        list.appendChild(g);
        lastGroup = entry.group;
      }
      const item = document.createElement("div");
      item.className = "palette-item" + (i === 0 ? " active" : "");
      item.setAttribute("role", "option");
      const label = document.createElement("span");
      label.textContent = entry.label;
      label.className = entry.group === "Endpoints" ? "path" : "";
      const hint = document.createElement("span");
      hint.className = "hint";
      hint.textContent = entry.hint;
      item.append(label, hint);
      item.addEventListener("click", () => entry.run());
      item.addEventListener("mousemove", () => $$(".palette-item", list).forEach((x) => x.classList.toggle("active", x === item)));
      list.appendChild(item);
    });
    if (!matches.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.style.padding = "24px";
      empty.textContent = "No matches";
      list.appendChild(empty);
    }
  }

  async function openPalette() {
    if (!paletteDlg) buildPalette();
    const input = $("input", paletteDlg);
    input.value = "";
    renderPalette("");
    if (!paletteDlg.open) paletteDlg.showModal();
    input.focus();
    if (paletteEndpoints === null) {
      paletteEndpoints = [];
      try { paletteEndpoints = await api("GET", "/endpoints"); renderPalette(input.value); } catch (_) { /* optional */ }
    }
  }

  // ================================================================ keyboard shortcuts
  let gPressed = 0;
  document.addEventListener("keydown", (e) => {
    const typing = /input|textarea|select/i.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "/") {
      const search = $("[data-search]");
      e.preventDefault();
      if (search) search.focus(); else openPalette();
      return;
    }
    if (e.key === "g") { gPressed = Date.now(); return; }
    if (Date.now() - gPressed < 900) {
      const page = PAGES.find(([, , hint]) => hint === `g ${e.key}`);
      if (page) { startProgress(); location.href = page[1]; }
      gPressed = 0;
    }
  });

  // ================================================================ playground
  function initPlayground() {
    const ops = JSON.parse($("#pg-ops").textContent);
    const list = $("#op-list");
    const builder = $("#pg-builder");
    let current = null;

    function select(index, prefill) {
      current = ops[index];
      $$(".op-item", list).forEach((b) => b.classList.toggle("active", Number(b.dataset.index) === index));
      builder.hidden = false;
      $("#pg-empty").hidden = true;
      $("#pg-method").className = `method m-${current.method}`;
      $("#pg-method").textContent = current.method;
      $("#pg-summary").textContent = current.summary || "";

      const renderParams = (box, params, kind) => {
        box.replaceChildren();
        params.forEach((p) => {
          const field = document.createElement("div");
          field.className = "field";
          const label = document.createElement("label");
          label.textContent = `${p.name}${p.required ? " *" : ""}`;
          const input = document.createElement("input");
          input.className = "input full";
          input.dataset.param = kind;
          input.dataset.name = p.name;
          const pre = prefill && prefill[kind] && prefill[kind][p.name];
          input.value = pre !== undefined ? pre : (kind === "path" && p.example !== null && p.example !== undefined ? p.example : "");
          input.placeholder = `${p.type}${p.example !== null && p.example !== undefined && kind === "query" ? ` · e.g. ${p.example}` : ""}`;
          input.addEventListener("input", updateUrl);
          const hint = document.createElement("span");
          hint.className = "hint";
          hint.textContent = p.description || p.type;
          field.append(label, input, hint);
          box.appendChild(field);
        });
        box.closest("[data-section]").hidden = params.length === 0;
      };
      renderParams($("#pg-path-params"), current.path_params, "path");
      renderParams($("#pg-query-params"), current.query_params, "query");

      const bodySection = $("#pg-body-section");
      bodySection.hidden = !current.has_body;
      $("#pg-body").value = prefill && prefill.body !== undefined ? prefill.body : (current.has_body ? JSON.stringify(current.body_example, null, 2) : "");
      $("#pg-response").hidden = true;
      $("#pg-scan").dataset.endpoint = current.path;
      $("#pg-scan").dataset.method = current.method;
      $("#pg-endpoint-link").href = `/ui/endpoint?method=${current.method}&path=${encodeURIComponent(current.path)}`;
      updateUrl();
      history.replaceState(null, "", `/ui/playground?op=${encodeURIComponent(current.id)}${location.search.includes("all=true") ? "&all=true" : ""}`);
    }

    function buildUrl() {
      let path = current.path;
      $$('input[data-param="path"]', builder).forEach((i) => { path = path.replace(`{${i.dataset.name}}`, encodeURIComponent(i.value)); });
      const qs = new URLSearchParams();
      $$('input[data-param="query"]', builder).forEach((i) => { if (i.value !== "") qs.set(i.dataset.name, i.value); });
      const q = qs.toString();
      return path + (q ? `?${q}` : "");
    }
    function updateUrl() { $("#pg-url").textContent = buildUrl(); }

    $$(".op-item", list).forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.index))));
    $("#op-search").addEventListener("input", (e) => {
      const q = e.target.value.toLowerCase();
      $$(".op-item", list).forEach((b) => { b.hidden = q && !b.textContent.toLowerCase().includes(q); });
    });

    $("#pg-format").addEventListener("click", () => {
      try { $("#pg-body").value = JSON.stringify(JSON.parse($("#pg-body").value), null, 2); }
      catch (err) { toast("Invalid JSON", err.message, "error"); }
    });
    $("#pg-curl").addEventListener("click", async () => {
      let cmd = `curl -X ${current.method} "${location.origin}${buildUrl()}"`;
      if (current.has_body && $("#pg-body").value.trim()) {
        cmd += ` -H "Content-Type: application/json" -d '${$("#pg-body").value.replace(/\s*\n\s*/g, " ").replace(/'/g, "'\\''")}'`;
      }
      await navigator.clipboard.writeText(cmd);
      toast("Copied", "curl command copied to the clipboard.", "success");
    });

    $("#pg-send").addEventListener("click", async () => {
      const btn = $("#pg-send");
      const options = { method: current.method, headers: { Accept: "application/json" }, credentials: "same-origin" };
      if (current.has_body) {
        const raw = $("#pg-body").value.trim();
        if (raw) {
          try { JSON.parse(raw); } catch (err) { toast("Invalid JSON body", err.message, "error"); return; }
          options.headers["Content-Type"] = "application/json";
          options.body = raw;
        }
      }
      btn.classList.add("loading");
      const started = performance.now();
      try {
        const res = await fetch(buildUrl(), options);
        const ms = Math.round(performance.now() - started);
        const text = await res.text();
        let pretty = text;
        try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch (_) { /* not JSON */ }
        const status = $("#pg-status");
        status.textContent = `${res.status} ${res.statusText}`;
        status.className = res.status < 300 ? "status-ok" : res.status < 500 ? "status-warn" : "status-err";
        $("#pg-time").textContent = `${ms} ms`;
        $("#pg-size").textContent = `${new Blob([text]).size} bytes`;
        const out = $("#pg-output");
        out.textContent = pretty || "(empty body)";
        out.dataset.lang = "json";
        highlight(out);
        $("#pg-response").hidden = false;
        $("#pg-captured").hidden = !current.monitored;
      } catch (err) {
        toast("Request failed", err.message, "error");
      } finally {
        btn.classList.remove("loading");
      }
    });

    // initial selection: replayed request, ?op=, or the first operation
    const params = new URLSearchParams(location.search);
    const replay = params.get("replay") && sessionStorage.getItem("replay");
    if (replay) {
      sessionStorage.removeItem("replay");
      const r = JSON.parse(replay);
      const idx = ops.findIndex((o) => o.method === r.method && o.path === (r.route || r.path));
      if (idx >= 0) {
        const prefill = { path: {}, query: {}, body: r.body };
        const names = [...ops[idx].path.matchAll(/\{([^}]+)\}/g)].map((m) => m[1]);
        const statics = ops[idx].path.split(/\{[^}]+\}/).map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
        const regex = new RegExp(`^${statics.join("([^/]+)")}/?$`);
        const match = r.path.split("?")[0].match(regex);
        if (match) names.forEach((n, i) => { prefill.path[n] = decodeURIComponent(match[i + 1]); });
        select(idx, prefill);
        return;
      }
      toast("Cannot replay", `${r.method} ${r.path} is not a documented operation.`, "error");
    }
    const wanted = params.get("op");
    const start = wanted ? ops.findIndex((o) => o.id === wanted) : -1;
    if (ops.length) select(start >= 0 ? start : 0);
  }

  // ================================================================ login
  function initLogin() {
    const form = $("#login-form");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const err = $("#login-error");
      err.hidden = true;
      const btn = $("button[type=submit]", form);
      btn.classList.add("loading");
      try {
        const res = await fetch("/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: form.username.value, password: form.password.value }),
          credentials: "same-origin",
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Sign-in failed");
        }
        location.href = form.dataset.next || "/ui";
      } catch (ex) {
        err.textContent = ex.message;
        err.hidden = false;
        form.password.select();
      } finally {
        btn.classList.remove("loading");
      }
    });
  }

  // ================================================================ boot
  initContent(document);
  showFlash();
})();
