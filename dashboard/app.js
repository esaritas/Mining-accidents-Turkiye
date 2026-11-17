(function () {
  "use strict";
  const D = window.MINING_DATA;

  // ---- i18n -----------------------------------------------------------------
  // The two-language strings live in strings.js (window.MINING_I18N).
  const I18N = window.MINING_I18N;

  // Source fields are plain text, never trusted HTML or executable URLs.
  const html = value => String(value ?? "").replace(/[&<>"']/g,
    ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
  const sourceLink = (url, label) => {
    try {
      const parsed = new URL(url);
      if (["https:", "http:"].includes(parsed.protocol)) {
        return `<a href="${html(parsed.href)}" target="_blank" rel="noopener noreferrer">${html(label)}</a>`;
      }
    } catch (e) { /* Invalid or unsupported source URLs remain plain text. */ }
    return html(label);
  };
  let savedLanguage;
  try { savedLanguage = localStorage.getItem("ma_lang"); } catch (e) { /* optional storage */ }
  let LANG = savedLanguage
    || ((navigator.language || "").toLowerCase().startsWith("tr") ? "tr" : "en");
  if (!I18N[LANG]) LANG = "en";
  let fmt = new Intl.NumberFormat(I18N[LANG].locale);
  const t = key => I18N[LANG][key] ?? I18N.en[key] ?? key;
  const tf = (key, params) => Object.entries(params || {}).reduce(
    (s, [k, v]) => s.replaceAll(`{${k}}`, v), String(t(key)));

  const incidents = D.incidents.slice().sort((a, b) =>
    (a.incident_start_datetime || "").localeCompare(b.incident_start_datetime || ""));
  const sites = (D.sites || []).slice().sort((a, b) => a.name.localeCompare(b.name, "tr"));
  const totalDeaths = incidents.reduce((s, i) => s + (i.fatalities_current || 0), 0);
  const mechanismsOf = id => (D.classifications[id] || [])
    .filter(c => c.system === "project_event_mechanism");
  const mechLabel = c => LANG === "tr" ? (c.label_tr || c.label_en) : (c.label_en || c.label_tr);
  const provinceName = code =>
    (D.province_names || {})[code] ||
    (D.province_centroids[code] || {}).label_tr || code || "";
  const yearOf = i => +(i.incident_start_datetime || "").slice(0, 4) || null;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Dates render at their recorded precision: a date known only to the month must read
  // "April 2005", never "2005-04-01" (audit rule, 2026-07-17).
  function fmtDate(i) {
    const d = i.incident_start_datetime || "";
    if (!d) return "";
    const month = t("months")[+d.slice(5, 7) - 1];
    if (i.date_precision === "month") return `${month} ${d.slice(0, 4)}`;
    if (i.date_precision === "year" || i.date_precision === "approximate") return d.slice(0, 4);
    return `${+d.slice(8, 10)} ${month} ${d.slice(0, 4)}`;
  }
  function sentence(i) {
    const n = i.fatalities_current;
    const who = n === 1 ? t("sent_one") : tf("sent_many", { n: fmt.format(n) });
    const d = i.incident_start_datetime || "";
    const month = t("months")[+d.slice(5, 7) - 1] || "";
    const when = i.date_precision === "exact_date" || i.date_precision === "exact_datetime"
      ? tf("sent_on", { date: `${+d.slice(8, 10)} ${month} ${d.slice(0, 4)}` })
      : i.date_precision === "month"
        ? tf("sent_in_month", { month, year: d.slice(0, 4) })
        : tf("sent_in_year", { year: d.slice(0, 4) });
    const mech = mechanismsOf(i.public_incident_id).map(mechLabel).join(", ");
    return tf("sent_body", { when, who, prov: provinceName(i.province_code) }) +
      (mech ? ` (${mech}).` : ".") +
      (i.casualty_status === "disputed" ? t("sent_disputed") : "");
  }

  // ---- static labels + language plumbing -----------------------------------
  function applyStatic() {
    document.documentElement.lang = LANG;
    document.title = t("title");
    document.querySelectorAll("[data-i18n]").forEach(el => {
      el.innerHTML = t(el.dataset.i18n);
    });
    // aria-labels are content too: localize them rather than pinning English.
    document.querySelectorAll("[data-aria]").forEach(el => {
      el.setAttribute("aria-label", t(el.dataset.aria));
    });
    document.querySelector("#f-province option[value='']").textContent = t("f_all_prov");
    document.querySelector("#f-mechanism option[value='']").textContent = t("f_all_mech");
    document.querySelector("#f-commodity option[value='']").textContent = t("f_all_comm");
    document.getElementById("sites-head").innerHTML =
      `<th data-sort="site">${t("sh_site")}</th><th data-sort="type">${t("sh_type")}</th>` +
      `<th data-sort="comm">${t("sh_comm")}</th><th data-sort="prov">${t("sh_prov")}</th>` +
      `<th data-sort="op">${t("sh_op")}</th><th data-sort="country">${t("sh_country")}</th>` +
      `<th>${t("sh_source")}</th>`;
    markSorted("sites-head", sortState.sites);
    document.getElementById("records-head").innerHTML =
      `<th data-sort="what">${t("rh_what")}</th><th data-sort="date">${t("rh_date")}</th>` +
      `<th data-sort="prov">${t("rh_prov")}</th>` +
      `<th class="num" data-sort="people">${t("rh_people")}</th>` +
      `<th data-sort="mech">${t("rh_mech")}</th>` +
      `<th data-sort="org">${t("rh_org")}</th><th>${t("rh_sources")}</th>` +
      `<th data-sort="id">${t("rh_id")}</th>`;
    markSorted("records-head", sortState.records);
    renderHazardHeads();
    document.getElementById("chart-legend").innerHTML =
      `<span><span class="swatch bar-swatch"></span> ${t("lgc_bars")}</span>` +
      `<span><span class="swatch line-swatch"></span> ${t("timeline_policy")}</span>`;
    document.querySelectorAll(".lang-toggle button").forEach(b =>
      b.setAttribute("aria-pressed", String(b.dataset.lang === LANG)));
  }

  // ---- Long captions on small screens --------------------------------------
  function setupCaptions() {
    const small = window.matchMedia("(max-width: 640px)").matches;
    // On a wide screen the limits and the milestones are open; on a phone
    // they are headings that open, so the page is not twenty screens long.
    document.querySelectorAll(".about-grid details, #timeline-fold, details.phone-fold").forEach(el => {
      if (!el.dataset.touched) el.open = !small;
      el.onclick = ev => { if (ev.target.closest("summary")) el.dataset.touched = "1"; };
    });
    document.querySelectorAll("section.panel p.caption").forEach(cap => {
      const sib = cap.nextElementSibling;
      if (sib && sib.classList.contains("cap-toggle")) sib.remove();
      cap.classList.remove("clamped");
      if (!small || cap.textContent.trim().length < 260) return;
      cap.classList.add("clamped");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cap-toggle";
      btn.textContent = t("more");
      btn.setAttribute("aria-expanded", "false");
      btn.addEventListener("click", () => {
        const open = !cap.classList.toggle("clamped");
        btn.textContent = open ? t("less") : t("more");
        btn.setAttribute("aria-expanded", String(open));
      });
      cap.insertAdjacentElement("afterend", btn);
    });
  }

  // ---- On this day ----------------------------------------------------------
  function renderOnThisDay() {
    const today = new Date();
    const todayKey = `${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    const anniversaries = incidents.filter(i =>
      (i.date_precision === "exact_date" || i.date_precision === "exact_datetime") &&
      (i.incident_start_datetime || "").slice(5, 10) === todayKey);
    const el = document.getElementById("onthisday");
    el.hidden = !anniversaries.length;
    if (anniversaries.length) {
      el.innerHTML = `<b>${t("onthisday")}</b> ` + anniversaries.map(i =>
        `${html(sentence(i))} (${html(i.public_incident_id)}, ${(i.incident_start_datetime || "").slice(0, 4)}) ${evidenceBadge(i.public_incident_id)}`).join(" ");
    }
  }

  // ---- Research narrative: counts come directly from the displayed snapshot.
  const ERAS = [{ until: 2000 }, { until: 2010 }, { until: 2020 }, { until: 9999 }];
  const eraOf = i => ERAS.findIndex(e => (yearOf(i) || 0) < e.until);
  const hasFacilityLocation = i => Number.isFinite(i.latitude) && Number.isFinite(i.longitude)
    && ["exact_verified", "facility_approximate"].includes(i.coordinate_precision);
  // A status is shown where the register records one (initial, revised,
  // final, disputed). A toll with no recorded status carries no label: the
  // limits box says once what a published toll is, instead of every row
  // repeating that nothing more is known.
  const casualtyLabel = i => i.casualty_status === "disputed" ? t("pill_disputed")
    : ({initial:t("casualty_initial"),revised:t("casualty_revised"),final:t("casualty_final")})[i.casualty_status] || "";
  const casualtyPill = i => casualtyLabel(i)
    ? `<span class="pill ${i.casualty_status === "disputed" ? "pill-dispute" : "pill-unknown"}">${casualtyLabel(i)}</span>` : "";
  const displayTitle = i => {
    const title = LANG === "en" && i.canonical_title_en ? i.canonical_title_en : i.canonical_title_tr || "";
    return ["month", "year", "approximate"].includes(i.date_precision)
      ? title.replace(/\(\d{4}-\d{2}-\d{2}\)/g, `(${fmtDate(i)})`) : title;
  };
  function buildStory() {
    const years = incidents.map(yearOf).filter(Boolean);
    const located = incidents.filter(hasFacilityLocation).length;
    const disputed = incidents.filter(i => i.casualty_status === "disputed").length;
    const revised = incidents.filter(i => i.casualty_status === "revised").length;
    const share = totalDeaths ? Math.round(100 * incidents.map(i => i.fatalities_current || 0).sort((a,b)=>b-a).slice(0,2).reduce((a,b)=>a+b,0) / totalDeaths) : 0;
    const params = { n: incidents.length, located, disputed, revised, share,
      injuries: incidents.filter(i => i.injuries_current != null).length,
      from: years.length ? Math.min(...years) : "—", to: years.length ? Math.max(...years) : "—" };
    document.getElementById("snapshot-date").textContent = tf("snapshot", {
      date:(D.export_timestamp || "").slice(0,10), year:params.to });
    document.getElementById("story-intro").innerHTML = `<strong>${fmt.format(totalDeaths)}</strong><p>${tf("hero_total",params)}</p>`;
    document.getElementById("story-cards").innerHTML = [
      ["story_one","story_one_body","years","go_years"],
      ["story_two","story_two_body","map-panel","go_map"],
      ["story_three","story_three_body","records-panel","go_records"],
    ].map(([h,b,id,link],k)=>`<article class="story-card"><span class="index">0${k+1}</span><h3>${t(h)}</h3><p>${tf(b,params)}</p><a href="#${id}">${t(link)}</a></article>`).join("");
    document.getElementById("evidence-strip").innerHTML = tf("quality",{...params,
      precise:incidents.filter(i=>["exact_date","exact_datetime"].includes(i.date_precision)).length});
  }
  function renderTiles() {
    const tiles = [
      { v:incidents.length, l:t("tile2l"), s:t("tile2s") },
      { v:new Set(incidents.map(i=>i.province_code).filter(Boolean)).size,
        l:t("tile_prov_l"),s:t("tile_prov_s") },
      { v:sites.length,l:t("tile4l"),s:t("tile4s") },
      { v:D.pipeline.records_in_review ?? "—",l:t("review_records"),
        s:tf("review_queue", {claims:D.pipeline.claims_awaiting_review ?? "—", candidates:D.monitoring?.candidates_waiting ?? "—"}) },
    ];
    document.getElementById("tiles").innerHTML = tiles.map(x=>`<div class="tile" role="listitem"><div class="value">${typeof x.v === "number" ? fmt.format(x.v) : html(x.v)}</div><div class="label">${x.l}</div><div class="sub">${x.s}</div></div>`).join("");
  }

  // ---- Filters ------------------------------------------------------------------
  const CONTEXT_TYPES = new Set(["archaeological_quarry", "mining_field",
    "operating_directorate", "regional_group", "deposit", "proposed_project"]);
  const typeLabel = s => t("types")[s.type] || s.type || "";
  const statusLabel = s => t("statuses")[s.status] || t("pill_not_stated");
  const roleLabel = role => t("roles")[role] || role || t("roles").unknown;
  // One order wherever companies are listed, so the company that was working
  // the pit is read first and a contractor is never mistaken for it.
  const ROLE_ORDER = ["operator", "licence_holder", "owner", "subcontractor",
    "employer", "public_authority", "rescue_organization", "other", "unknown"];
  const byRole = (a, b) =>
    (ROLE_ORDER.indexOf(a.role) + 1 || 99) - (ROLE_ORDER.indexOf(b.role) + 1 || 99);
  // Who the sources say held or ran the mine when the accident happened.
  // Organizations only: this register names no individual.
  // Only roles the source places at the mine on the day. The payload has carried
  // at_incident_date from the start and every reader of it ignored the flag, so a
  // company that postdates an accident could be shown beside it: both 1983 records
  // named TTK, founded in October 1983, as operator and owner on the day.
  const orgsOf = id => ((D.incident_organizations || {})[id] || [])
    .filter(o => o.at_incident_date).sort(byRole);
  // Commodity groups (validated palette; gray = not stated in source).
  const COMM_GROUPS = {
    coal: "coal", lignite: "coal",
    chromium: "metal", iron: "metal", copper: "metal", gold: "metal",
    silver: "metal", zinc: "metal", lead: "metal",
    cobalt: "metal", manganese: "metal", nickel: "metal", bauxite: "metal",
    platinum_group: "metal",
    boron: "mineral", phosphate: "mineral", marble: "mineral", salt: "mineral",
  };
  const GROUP_HEX = { coal: "#4a5fc1", metal: "#a08000", mineral: "#0f8a5f", other: "#8a8f96" };
  const groupOf = site => COMM_GROUPS[site.commodity_code] || "other";
  // A code is never printed. Labels come from the project vocabularies, which
  // carry both languages, so the reader sees one language throughout.
  const vocab = (name, code) => {
    if (!code) return "";
    const entry = ((D.vocabulary_labels || {})[name] || {})[code];
    return entry ? (entry[LANG] || entry.en || code) : String(code).replace(/_/g, " ");
  };
  const statusLabelOf = code => vocab("assertion_statuses", code);
  // Unified display labels per language; the source's own wording stays in the
  // tooltip (labels arrive in mixed languages: kömür / coal / altın).
  const commodityText = site => site.commodity_code
    ? (t("comms")[site.commodity_code] || vocab("commodities", site.commodity_code) ||
       t("comm_other"))
    : null;
  const state = { province: "", mechanism: "", from: null, to: null, commodity: "", siteType: "",
                  layer: "both", view: "marks" };

  const provSel = document.getElementById("f-province");
  const mechSel = document.getElementById("f-mechanism");
  const fromSel = document.getElementById("f-from");
  const toSel = document.getElementById("f-to");
  const commSel = document.getElementById("f-commodity");
  const typeSel = document.getElementById("f-site-type");

  const yearsAll = incidents.map(yearOf).filter(Boolean);
  const minY = yearsAll.length ? Math.min(...yearsAll) : new Date().getFullYear();
  const maxY = yearsAll.length ? Math.max(...yearsAll) : minY;
  state.from = minY; state.to = maxY;

  function fillSelects() {
    const provCodes = [...new Set([
      ...incidents.map(i => i.province_code).filter(Boolean),
      ...sites.map(s => s.province_code).filter(Boolean),
    ])].sort((a, b) => provinceName(a).localeCompare(provinceName(b), "tr"));
    provSel.innerHTML = `<option value="">${t("f_all_prov")}</option>` + provCodes.map(c =>
      `<option value="${html(c)}">${html(provinceName(c))}</option>`).join("");
    provSel.value = state.province;

    const mechs = new Map();
    for (const i of incidents) for (const c of mechanismsOf(i.public_incident_id)) {
      mechs.set(c.code, mechLabel(c));
    }
    mechSel.innerHTML = `<option value="">${t("f_all_mech")}</option>` +
      [...mechs.entries()].sort((a, b) => a[1].localeCompare(b[1]))
      .map(([code, label]) => `<option value="${html(code)}">${html(label)}</option>`).join("");
    mechSel.value = state.mechanism;

    let yearOpts = "";
    for (let y = minY; y <= maxY; y++) yearOpts += `<option value="${y}">${y}</option>`;
    fromSel.innerHTML = yearOpts; toSel.innerHTML = yearOpts;
    fromSel.value = String(state.from); toSel.value = String(state.to);
    fromSel.disabled = toSel.disabled = !yearsAll.length;

    const comms = new Map();
    for (const s of sites) {
      if (s.commodity_code) comms.set(s.commodity_code, commodityText(s));
    }
    commSel.innerHTML = `<option value="">${t("f_all_comm")}</option>` +
      [...comms.entries()].sort((a, b) => String(a[1]).localeCompare(String(b[1])))
      .map(([code, label]) => `<option value="${html(code)}">${html(label)}</option>`).join("");
    commSel.value = state.commodity;
    typeSel.innerHTML = `<option value="">${t("all_site_types")}</option>` +
      [...new Set(sites.map(s => s.type || "unknown"))].sort().map(type =>
        `<option value="${html(type)}">${html(typeLabel({type}))}</option>`).join("");
    typeSel.value = state.siteType;
  }

  const incidentMatches = i =>
    (!state.province || i.province_code === state.province) &&
    (!state.mechanism || mechanismsOf(i.public_incident_id).some(c => c.code === state.mechanism)) &&
    (yearOf(i) == null || (yearOf(i) >= state.from && yearOf(i) <= state.to));
  const siteMatches = s =>
    (!state.province || s.province_code === state.province) &&
    (!state.siteType || (s.type || "unknown") === state.siteType) &&
    (!state.commodity || s.commodity_code === state.commodity);

  function applyFilters() {
    const fi = incidents.filter(incidentMatches);
    const fs = sites.filter(siteMatches);
    renderRecords(fi);
    renderSites(fs);
    renderMap(fi, fs);
    renderSmallMultiples();
    const people = fi.reduce((s, i) => s + (i.fatalities_current || 0), 0);
    document.getElementById("filter-result").innerHTML = tf("result",
      { r: fmt.format(fi.length), p: fmt.format(people), s: fmt.format(fs.length) });
  }

  provSel.addEventListener("change", () => { state.province = provSel.value; syncUrl(); applyFilters(); });
  mechSel.addEventListener("change", () => { state.mechanism = mechSel.value; syncUrl(); applyFilters(); });
  fromSel.addEventListener("change", () => {
    state.from = +fromSel.value;
    if (state.from > state.to) { state.to = state.from; toSel.value = fromSel.value; }
    syncUrl();
    applyFilters();
  });
  toSel.addEventListener("change", () => {
    state.to = +toSel.value;
    if (state.to < state.from) { state.from = state.to; fromSel.value = toSel.value; }
    syncUrl();
    applyFilters();
  });
  commSel.addEventListener("change", () => { state.commodity = commSel.value; syncUrl(); applyFilters(); });
  typeSel.addEventListener("change", () => { state.siteType = typeSel.value; syncUrl(); applyFilters(); });
  document.getElementById("f-clear").addEventListener("click", () => {
    state.province = ""; state.mechanism = ""; state.commodity = ""; state.siteType = "";
    state.from = minY; state.to = maxY;
    provSel.value = ""; mechSel.value = ""; commSel.value = ""; typeSel.value = "";
    fromSel.value = String(minY); toSel.value = String(maxY);
    syncUrl();
    applyFilters();
  });
  document.querySelectorAll(".layer-toggle button[data-layer]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.layer = btn.dataset.layer;
      syncToggles();
      syncUrl();
      applyFilters();
    });
  });
  document.querySelectorAll(".layer-toggle button[data-view]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.view = btn.dataset.view;
      syncToggles();
      syncUrl();
      applyFilters();
    });
  });
  function syncToggles() {
    document.querySelectorAll(".layer-toggle button[data-layer]").forEach(b =>
      b.setAttribute("aria-pressed", String(b.dataset.layer === state.layer)));
    document.querySelectorAll(".layer-toggle button[data-view]").forEach(b =>
      b.setAttribute("aria-pressed", String(b.dataset.view === state.view)));
  }

  // ---- Shareable view state -------------------------------------------------
  // The whole filter surface is reflected in the query string so a reader can
  // send someone "Zonguldak, 1983 to 1992" as a link. Nothing else owns the
  // URL, so this is purely additive.
  const URL_KEYS = ["province", "mechanism", "from", "to", "commodity", "siteType", "layer", "view"];
  function syncUrl() {
    const q = new URLSearchParams();
    for (const k of URL_KEYS) {
      const v = state[k];
      if (v === "" || v == null) continue;
      if (k === "from" && +v === minY) continue;
      if (k === "to" && +v === maxY) continue;
      if (k === "layer" && v === "both") continue;
      if (k === "view" && v === "marks") continue;
      q.set(k, String(v));
    }
    const qs = q.toString();
    try {
      history.replaceState(null, "", qs ? "?" + qs + location.hash : location.pathname + location.hash);
    } catch (e) { /* file:// or sandboxed: state still works in-memory */ }
  }
  function hydrateFromUrl() {
    let q;
    try { q = new URLSearchParams(location.search); } catch (e) { return; }
    const provCodes = new Set(incidents.map(i => i.province_code).concat(sites.map(s => s.province_code)));
    if (q.has("province") && provCodes.has(q.get("province"))) state.province = q.get("province");
    if (q.has("mechanism")) state.mechanism = q.get("mechanism");
    if (q.has("commodity")) state.commodity = q.get("commodity");
    if (sites.some(s => (s.type || "unknown") === q.get("siteType"))) state.siteType = q.get("siteType");
    const f = +q.get("from"), tt = +q.get("to");
    if (Number.isFinite(f) && f >= minY && f <= maxY) state.from = f;
    if (Number.isFinite(tt) && tt >= minY && tt <= maxY) state.to = tt;
    if (state.from > state.to) { const a = state.from; state.from = state.to; state.to = a; }
    if (["accidents", "sites", "both"].includes(q.get("layer"))) state.layer = q.get("layer");
    if (["marks", "locations"].includes(q.get("view"))) state.view = q.get("view");
  }

  // ---- Language switch --------------------------------------------------------
  document.querySelectorAll(".lang-toggle button").forEach(btn => {
    btn.addEventListener("click", () => {
      if (btn.dataset.lang === LANG) return;
      LANG = btn.dataset.lang;
      try { localStorage.setItem("ma_lang", LANG); } catch (e) { /* optional storage */ }
      fmt = new Intl.NumberFormat(I18N[LANG].locale);
      renderAll();
    });
  });

  // ---- Map ----------------------------------------------------------------
  // Cartography: province rings are projected in the browser with an Albers
  // Equal Area Conic fitted to Türkiye (standard parallels 37.5N/41.5N).
  // Equal-area is the correct family for any map that fills areas with colour;
  // the previous equirectangular projection sheared the country ~10% from
  // north to south. Geometry is display-only, never evidence.
  const CARN_D = "M12 1.5 L14.4 5.2 L17.8 3.4 L18.4 7.3 L22.3 8 L20.5 11.6 C18.8 15 15.6 16.8 12 16.8 C8.4 16.8 5.2 15 3.5 11.6 L1.7 8 L5.6 7.3 L6.2 3.4 L9.6 5.2 Z M9 16.3 L15 16.3 L13.3 22.3 L10.7 22.3 Z M11.2 21.8 L12.8 21.8 L12.8 34.5 L11.2 34.5 Z M12.8 27.5 C15.4 26.8 17 24.8 17.5 22.6 C14.9 23.3 13.3 25.3 12.8 27.5 Z";
  const RAD = Math.PI / 180;
  const _p1 = 37.5 * RAD, _p2 = 41.5 * RAD, _p0 = 39.0 * RAD, _l0 = 35.2 * RAD;
  const _n = (Math.sin(_p1) + Math.sin(_p2)) / 2;
  const _C = Math.cos(_p1) ** 2 + 2 * _n * Math.sin(_p1);
  const _rho0 = Math.sqrt(_C - 2 * _n * Math.sin(_p0)) / _n;
  function albers(lat, lon) {
    const th = _n * (lon * RAD - _l0);
    const rho = Math.sqrt(_C - 2 * _n * Math.sin(lat * RAD)) / _n;
    return [rho * Math.sin(th), _rho0 - rho * Math.cos(th)];
  }

  // --- ring helpers (also used to place province-level marks) ---------------
  function ringArea(r) {
    let a = 0;
    for (let i = 0, j = r.length - 1; i < r.length; j = i++)
      a += r[j][0] * r[i][1] - r[i][0] * r[j][1];
    return a / 2;
  }
  function ringCentroid(r) {
    let a = 0, cx = 0, cy = 0;
    for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
      const f = r[j][0] * r[i][1] - r[i][0] * r[j][1];
      a += f; cx += (r[j][0] + r[i][0]) * f; cy += (r[j][1] + r[i][1]) * f;
    }
    a *= 0.5;
    return Math.abs(a) < 1e-9 ? r[0].slice() : [cx / (6 * a), cy / (6 * a)];
  }
  function inRing(r, x, y) {
    let inside = false;
    for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
      const xi = r[i][0], yi = r[i][1], xj = r[j][0], yj = r[j][1];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  // An interior point, never the province seat: `province_centroids.csv` holds
  // Wikidata P625 seats (the capital city), and anchoring a province-level mark
  // there would imply the accident happened in that city.
  function interiorAnchor(rings) {
    const big = rings.reduce((m, r) =>
      Math.abs(ringArea(r)) > Math.abs(ringArea(m)) ? r : m, rings[0]);
    const c = ringCentroid(big);
    if (inRing(big, c[0], c[1])) return c;
    const xs = big.map(p => p[0]);
    const lo = Math.min(...xs), hi = Math.max(...xs);
    let best = c, bestLen = -1, start = null;
    for (let s = 0; s <= 140; s++) {
      const x = lo + ((hi - lo) * s) / 140;
      if (inRing(big, x, c[1])) { if (start === null) start = x; }
      else if (start !== null) {
        if (x - start > bestLen) { bestLen = x - start; best = [(start + x) / 2, c[1]]; }
        start = null;
      }
    }
    if (start !== null && hi - start > bestLen) best = [(start + hi) / 2, c[1]];
    return best;
  }

  // Projected geometry, computed once from the payload's lat/lon rings.
  const GEO = (() => {
    const provs = (D.provinces_geo || []).map(p => ({
      code: p.code,
      rings: p.rings.map(r => r.map(pt => albers(pt[0], pt[1]))),
    }));
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const p of provs) for (const r of p.rings) for (const q of r) {
      if (q[0] < minX) minX = q[0];
      if (q[0] > maxX) maxX = q[0];
      if (q[1] < minY) minY = q[1];
      if (q[1] > maxY) maxY = q[1];
    }
    const W = 1000, k = W / (maxX - minX);
    const H = Math.round((maxY - minY) * k);
    const toPx = q => [(q[0] - minX) * k, (maxY - q[1]) * k];
    const paths = {}, pathsSimple = {}, anchors = {};
    const toD = rings => rings.map(r =>
      "M" + r.map(q => q[0].toFixed(1) + "," + q[1].toFixed(1)).join(" L") + " Z").join(" ");
    for (const p of provs) {
      const px = p.rings.map(r => r.map(toPx));
      paths[p.code] = toD(px);
      // The small multiples draw the country four times; thin the rings so the
      // DOM stays light at a size where the detail cannot be seen anyway.
      pathsSimple[p.code] = toD(px.map(r => (r.length > 24 ? r.filter((_, k) => k % 3 === 0) : r)));
      anchors[p.code] = interiorAnchor(px);
    }
    return { W, H, paths, pathsSimple, anchors, project: (lat, lon) => toPx(albers(lat, lon)) };
  })();

  // --- classification -------------------------------------------------------
  // Fixed breaks (comparable while filtering), re-cut to the real distribution:
  // the old 100-299 class was empty and 427 vs 304 shared one shade.
  const BREAKS = [1, 5, 20, 50, 300];
  const RAMP = ["#f6ddda", "#eab5b0", "#d97f77", "#c24a42", "#99231d"];
  const rampColor = d => {
    if (!d || d <= 0) return null;
    let k = 0;
    for (let i = 0; i < BREAKS.length; i++) if (d >= BREAKS[i]) k = i;
    return RAMP[k];
  };
  const breakLabels = () => BREAKS.map((b, i) =>
    i === BREAKS.length - 1 ? fmt.format(b) + "+" : fmt.format(b)).join(" · ");

  // Proportional symbols: area scales with the number of people, so the linear
  // size scales with the square root. The reference maximum is fixed over the
  // whole register (not the filtered subset) so marks stay comparable while
  // filtering. A small floor keeps single-death marks visible; the size legend
  // shows what each step means.
  const MARK_MIN = 7, MARK_MAX = 46;
  const PROV_MAX = (() => {
    const m = new Map();
    for (const i of incidents)
      if (i.province_code)
        m.set(i.province_code, (m.get(i.province_code) || 0) + (i.fatalities_current || 0));
    return Math.max(1, ...m.values());
  })();
  const markSize = d =>
    !d || d <= 0 ? MARK_MIN : Math.max(MARK_MIN, MARK_MAX * Math.sqrt(d / PROV_MAX));

  function carnationMark(x, y, h, cls, attrs) {
    const s = h / 36;
    return `<g class="${cls}" ${attrs} transform="translate(${x.toFixed(1)},${y.toFixed(1)}) scale(${s.toFixed(3)}) translate(-12,-18)">` +
      `<path d="${CARN_D}"></path></g>`;
  }

  // Who the sources say held or ran the mine, written the same way wherever it
  // appears: the map tip, the records table and the record detail. The
  // assertion status rides along, so an attribution a source only alleges is
  // never shown as a settled one.
  function orgLine(o) {
    return `${html(roleLabel(o.role))}: <span lang="tr">${html(o.name)}</span>` +
      (o.country_label ? ` (${html(o.country_label)})` : "") +
      (o.assertion_status && o.assertion_status !== "reported"
        ? ` <span class="t-meta">[${html(statusLabelOf(o.assertion_status))}]</span>` : "");
  }

  function siteTip(s) {
    const orgLines = (s.organizations || []).map(o =>
      `${html(roleLabel(o.role))}: ${html(o.name)}` +
      (o.country_label ? ` (${html(o.country_label)})` : "") +
      ` <span class="t-meta">[${html(statusLabelOf(o.assertion_status))}]</span>`);
    return `<div class="t-title" lang="tr">${html(s.name)}</div>` +
      `<div>${html(typeLabel(s))}` +
      (commodityText(s) ? ` · ${html(commodityText(s))}` : "") +
      (s.province_code ? ` · ${html(provinceName(s.province_code))}` : "") + `</div>` +
      (orgLines.length ? `<div>${orgLines.join("<br>")}</div>` : "") +
      `<div class="t-meta">${t("status_label")}: ${statusLabel(s)}` +
      `${s.province_code ? "" : " · " + t("site_unknown")}</div>` +
      sourceLink(s.source_url,t("wikidata_src"));
  }

  function provinceStats(fi, fs) {
    const stats = new Map();
    const get = code => {
      if (!stats.has(code)) stats.set(code, { deaths: 0, records: 0, all: [], unlocated: [],
                                              unlocatedDeaths: 0, sites: 0, sitesUnlocated: 0 });
      return stats.get(code);
    };
    for (const i of fi) {
      if (!i.province_code) continue;
      const e = get(i.province_code);
      e.deaths += i.fatalities_current || 0; e.records += 1; e.all.push(i);
      if (!hasFacilityLocation(i)) { e.unlocated.push(i); e.unlocatedDeaths += i.fatalities_current || 0; }
    }
    for (const st of fs) {
      if (!st.province_code) continue;
      const e = get(st.province_code);
      e.sites += 1;
      if (!hasFacilityLocation(st)) e.sitesUnlocated += 1;
    }
    return stats;
  }

  function provinceTipHtml(code, e) {
    if (!e) return `<div class="t-title">${html(provinceName(code))}</div>` +
      `<div class="t-meta">${t("prov_none")}</div>`;
    // Six rows rather than eight, because each now carries the company too,
    // with its role spelled out: a name on its own would leave the reader
    // guessing whether that company was working the pit or merely held it.
    const rows = e.unlocated.slice(0, 6).map(i => {
      const who = orgsOf(i.public_incident_id).map(o =>
        `<span lang="tr">${html(o.name)}</span> <span class="t-meta">${html(roleLabel(o.role))}` +
        `${o.assertion_status && o.assertion_status !== "reported"
          ? ", " + html(statusLabelOf(o.assertion_status)) : ""}</span>`).join("<br>");
      return `${html(i.public_incident_id)} · ${html(fmtDate(i))} · ` +
        `${fmt.format(i.fatalities_current)}` + (who ? `<br>${who}` : "");
    }).join("<br>");
    // One line per company, with everything that company was in this
    // province's records. Grouping by role instead would print the same
    // company twice under two headings wherever two sources worded it
    // differently, which reads as two different companies.
    const seen = new Map();
    for (const i of (e.all || e.unlocated)) {
      for (const o of orgsOf(i.public_incident_id)) {
        if (!seen.has(o.name)) seen.set(o.name, new Set());
        seen.get(o.name).add(o.role);
      }
    }
    const companies = [...seen.entries()].map(([name, roles]) => ({
      name, roles: [...roles].sort((a, b) => byRole({ role: a }, { role: b })),
    })).sort((a, b) => byRole({ role: a.roles[0] }, { role: b.roles[0] }))
      .map(c => `<span lang="tr">${html(c.name)}</span> ` +
        `${c.roles.map(r => html(roleLabel(r))).join(", ")}`);
    return `<div class="t-title">${html(provinceName(code))}</div>` +
      (e.records
        ? `<div>${tf("prov_lost", { d: fmt.format(e.deaths), n: e.records })}</div>`
        : `<div class="t-meta">${t("prov_none")}</div>`) +
      (e.unlocated.length ? `<div class="t-meta">${tf("prov_unlocated", { n: e.unlocated.length })}<br>${rows}${e.unlocated.length > 6 ? "<br>…" : ""}</div>` : "") +
      (companies.length
        ? `<div class="t-meta">${t("prov_orgs")}<br>${companies.join("<br>")}</div>`
        : "") +
      (e.sites ? `<div class="t-meta">${tf("prov_sites", { n: e.sites })}` +
        (e.sitesUnlocated ? tf("prov_sites_unloc", { n: e.sitesUnlocated }) : "") +
        `</div>` : "") +
      `<div class="t-meta">${t("prov_click")}</div>`;
  }

  function renderMap(fi, fs) {
    try { renderSvgMap(fi, fs); } catch (err) {
      console.error("map failed:", err);
      document.getElementById("map").innerHTML =
        `<p style="padding:16px;color:var(--ink-2)">${t("map_failed")}</p>`;
    }
  }

  function renderSvgMap(fi, fs) {
    const el = document.getElementById("map");
    const stats = provinceStats(fi, fs);
    const byId = new Map(fi.map(i=>[i.public_incident_id,i]));
    const showAcc = state.layer !== "sites", showSites = state.layer !== "accidents";
    const precisionView = state.view === "locations";
    const radius = d => 42 * Math.sqrt(Math.max(d,0) / PROV_MAX);
    let parts = Object.keys(GEO.paths).map(code=>{
      const e=stats.get(code);
      return `<path class="tr-prov${e?.records ? " has-data" : ""}${state.province===code ? " is-selected" : ""}" data-prov="${html(code)}" tabindex="0" role="button" aria-label="${html(provinceName(code))}" d="${GEO.paths[code]}"><title>${html(provinceName(code))}</title></path>`;
    });
    const circle = (x,y,d,attr,label,cls) => `<g class="mark-wrap" ${attr} tabindex="0" role="button" aria-label="${html(label)}"><circle class="hit" cx="${x}" cy="${y}" r="${Math.max(radius(d),18)}" fill="transparent"></circle><circle class="research-circle ${cls}" cx="${x}" cy="${y}" r="${radius(d)}"></circle><title>${html(label)}</title></g>`;
    // Site groupings are needed before the province labels are placed, so a
    // label is never printed over a marker it would make unreadable.
    // Sites are shown per province, one mark each, whether or not the source
    // published coordinates (project owner, 2026-10-22). Plotting some sites
    // at a facility and others on a province anchor made the reader decode a
    // distinction they do not need, and put two kinds of mark on one layer.
    const coarse = new Map();
    if (showSites) for (const site of fs) {
      if (!GEO.anchors[site.province_code]) continue;
      if (!coarse.has(site.province_code)) coarse.set(site.province_code, []);
      coarse.get(site.province_code).push(site);
    }
    if(showAcc) {
      for(const [code,e] of [...stats].sort((a,b)=>b[1].deaths-a[1].deaths)) {
        const d=precisionView ? e.unlocatedDeaths : e.deaths;
        const anchor=GEO.anchors[code];
        if(!anchor || !d) continue;
        const label=`${provinceName(code)}: ${fmt.format(d)} · ${precisionView ? t("key_coarse") : t("key_province")}`;
        parts.push(circle(...anchor,d,`data-prov-mark="${html(code)}"`,label,precisionView ? "province-level" : "province-total"));
      }
      if(precisionView) for(const i of fi.filter(hasFacilityLocation)) {
        parts.push(circle(...GEO.project(i.latitude,i.longitude),i.fatalities_current || 0,
          `data-id="${html(i.public_incident_id)}"`,`${displayTitle(i)}: ${i.fatalities_current}${casualtyLabel(i) ? " · " + casualtyLabel(i) : ""}`,"located"));
      }
      // A few labels orient the reader. A label is dropped when it would touch
      // another label or any marker: fewer legible names beat more unreadable
      // ones. The selected province is placed first so it always keeps its name.
      const hit=(a,b)=>a[0]<b[2]&&a[2]>b[0]&&a[1]<b[3]&&a[3]>b[1];
      const boxes=[];
      for(const [code,e] of stats) {
        const a=GEO.anchors[code], d=precisionView ? e.unlocatedDeaths : e.deaths;
        if(!a || !d) continue;
        const r=radius(d); boxes.push([a[0]-r,a[1]-r,a[0]+r,a[1]+r,code]);
      }
      for(const [code,list] of coarse) {
        const [x,y]=GEO.anchors[code], r=siteRadius(list.length)+2;
        boxes.push([x-r,y-r,x+r,y+r]);
      }
      const ordered=[...stats].sort((a,b)=>
        (b[0]===state.province)-(a[0]===state.province) || b[1].deaths-a[1].deaths);
      for(const [code,e] of ordered) {
        const a=GEO.anchors[code];
        if(!a || !e.records || (e.deaths<10 && code!==state.province)) continue;
        // Below, above, right, left of the circle: the first place that
        // touches nothing. The provinces with the most recorded deaths are
        // placed first, so they are the last to lose their name.
        const label=provinceName(code),r=radius(e.deaths),half=label.length*3.7+7;
        const spots=[
          [a[0], a[1]+r+17, "middle"], [a[0], a[1]-r-8, "middle"],
          [a[0]+r+6+half, a[1]+5, "middle"], [a[0]-r-6-half, a[1]+5, "middle"],
          [a[0]+r*.75+half, a[1]+r*.75+14, "middle"], [a[0]-r*.75-half, a[1]+r*.75+14, "middle"],
          [a[0]+r*.75+half, a[1]-r*.75-4, "middle"], [a[0]-r*.75-half, a[1]-r*.75-4, "middle"],
        ];
        // A circle is tested as its bounding square, whose corners are empty.
        // The four diagonal places sit in those corners, so they are not
        // tested against the province's own circle.
        const spot=spots.find(([x,y],k)=>!boxes.some(b=>
          !(k>=4 && b[4]===code) && hit([x-half,y-14,x+half,y+6],b)));
        if(!spot) continue;
        const [x,y]=spot;
        boxes.push([x-half,y-14,x+half,y+6]);
        parts.push(`<text class="map-label" x="${x}" y="${y}" text-anchor="middle">${html(label)}</text>`);
      }
    }
    // Draw sites last so province death circles cannot obscure them. Exact
    // coordinate duplicates share one marker; no geographic jitter is invented.
    if (showSites) {
      for (const [code, list] of coarse) {
        const [x,y] = GEO.anchors[code];
        const label = `${provinceName(code)}: ${tf("site_n", { n: list.length })}`;
        parts.push(`<g class="svg-site" data-sitekey="${html(list.map(s=>s.ref).join("|"))}" tabindex="0" role="button" aria-label="${html(label)}">` +
          `<circle class="hit" cx="${x}" cy="${y}" r="${Math.max(siteRadius(list.length) + 6, 13)}" fill="transparent"></circle>` +
          `${siteSymbol(x, y, list)}<title>${html(label)}</title></g>`);
      }
    }
    // Environmental records, drawn last and never in red: on this map red
    // means a person died, and these records count no deaths. A record with
    // no coordinates is anchored on its province, like an unlocated accident.
    for (const e of ENV()) {
      const point = (e.latitude != null && e.longitude != null)
        ? GEO.project(e.latitude, e.longitude)
        : GEO.anchors[e.province_code];
      if (!point) continue;
      const [x, y] = point;
      const exact = e.latitude != null;
      const label = `${e.public_incident_id} · ${LANG === "tr"
        ? (e.canonical_title_tr || "") : (e.canonical_title_en || e.canonical_title_tr || "")}`;
      parts.push(`<g class="svg-env" data-envid="${html(e.public_incident_id)}" tabindex="0" ` +
        `role="button" aria-label="${html(label)}">` +
        `<circle class="hit" cx="${x}" cy="${y}" r="13" fill="transparent"></circle>` +
        `<path class="env-symbol" d="M${x},${y-7} L${x+7},${y+5} L${x-7},${y+5} Z" ` +
        `fill="${exact ? "var(--c-mineral)" : "none"}" stroke="var(--c-mineral)" ` +
        `stroke-width="2.4" stroke-linejoin="round"></path>` +
        `<title>${html(label)}</title></g>`);
    }
    el.innerHTML=`<svg viewBox="-20 -20 ${GEO.W+40} ${GEO.H+60}" role="group" aria-label="${t("aria_map")}">${parts.join("")}</svg>`;
    bindMapInteraction(el,stats,byId,fs);
    renderMapLegend(fs);
    renderMapSummary(fi, fs);
  }
  // One symbol for every site, sized by how many sites it stands for and
  // coloured by what they produce. Four shapes for mine, quarry and context
  // type, plus a dashed box carrying a printed number for province groups,
  // put five visual vocabularies on one map; the type and the names now live
  // in the tooltip, where there is room to say them properly.
  const siteRadius = n => 7 + Math.min(n - 1, 6) * 1.8;
  function siteSymbol(x, y, list) {
    const sites = Array.isArray(list) ? list : [list];
    // A province can hold more than one kind of mine. The mark takes the
    // colour of whatever most of its sites produce, and the tooltip lists
    // every one of them: a separate "mixed" colour made a third of the map a
    // category that means nothing on its own.
    const tally = new Map();
    for (const site of sites) {
      const g = groupOf(site);
      tally.set(g, (tally.get(g) || 0) + 1);
    }
    const ranked = [...tally.entries()].sort((a, b) => b[1] - a[1]);
    const colour = ranked.length && (ranked.length === 1 || ranked[0][1] > ranked[1][1])
      ? GROUP_HEX[ranked[0][0]] : GROUP_HEX.other;
    const r = siteRadius(sites.length);
    // A diamond, not a circle: a circle on this map is an accident, and the
    // two layers should never be read as one. Size carries how many sites
    // the province holds; the names are in the tooltip.
    return `<path class="site-symbol" d="M${x},${y - r} L${x + r},${y} ` +
      `L${x},${y + r} L${x - r},${y} Z" fill="${colour}"></path>`;
  }
  function renderMapSummary(fi, fs) {
    const count=fi.reduce((sum,i)=>sum+(i.fatalities_current || 0),0);
    const located=fi.filter(hasFacilityLocation).length;
    const disputed=fi.filter(i=>i.casualty_status==="disputed").length;
    const named=fi.filter(i=>orgsOf(i.public_incident_id).length).length;
    const host=document.getElementById("map-summary");
    host.innerHTML=`<h3>${html(state.province ? provinceName(state.province) : t("overview"))}</h3><div class="summary-count">${fmt.format(count)}</div><div>${t("sum_deaths")}</div><p>${tf("sum_records",{n:fi.length})}</p><p>${tf("sum_geo",{n:located,coarse:fi.length-located})}</p>`+
      (named ? `<p>${tf("sum_orgs",{n:named,total:fi.length})}</p>` : "")+
      (disputed ? `<p>${tf("sum_disputed",{n:disputed})}</p>` : "")+
      `<p>${t("sum_action")}</p>`+fi.slice().sort((a,b)=>(b.incident_start_datetime || "").localeCompare(a.incident_start_datetime || "")).slice(0,4).map(i=>`<button type="button" data-open="${html(i.public_incident_id)}">${html(displayTitle(i))}<br>${html(fmtDate(i))} · ${fmt.format(i.fatalities_current)}</button>`).join("");
    host.querySelectorAll("[data-open]").forEach(b=>b.addEventListener("click",()=>openDetail(b.dataset.open)));
    if (state.layer === "sites") host.innerHTML = "";
    const breakdown = document.getElementById("site-breakdown");
    if (breakdown) {
      const counts = new Map();
      for (const s of fs) counts.set(typeLabel(s),(counts.get(typeLabel(s)) || 0)+1);
      breakdown.innerHTML = `<p class="row"><strong>${fs.length} ${t("layer_sites")}</strong>`+
        [...counts].sort((a,b)=>b[1]-a[1]).map(([type,n])=>`<span>${html(type)}: ${n}</span>`).join("")+
        `</p><p class="note">${t("site_caveat")}</p>`;
    }
    const mapped = fs.filter(s=>GEO.anchors[s.province_code]).length;
    const provinces = new Set(fs.filter(s=>GEO.anchors[s.province_code])
      .map(s=>s.province_code)).size;
    document.getElementById("site-coverage").textContent = (state.layer === "accidents" ? t("site_hidden")+" " : "") +
      tf("site_coverage", {n:fs.length,mapped,provinces,unmapped:fs.length-mapped});
  }

  // --- interaction: pointer, touch and keyboard ------------------------------
  let tipPinned = false;
  function bindMapInteraction(el, stats, byId, fs) {
    const tip = document.getElementById("map-tip");
    const wrapEl = document.getElementById("map-wrap");
    const svgEl = el.querySelector("svg");
    const bySiteRef = new Map(sites.map(s => [s.ref, s]));

    const contentFor = hit => {
      if (hit.dataset.sitekey) {
        const refs = hit.dataset.sitekey.split("|");
        return refs.map(r => siteTip(bySiteRef.get(r))).join('<hr style="border:none;border-top:1px solid var(--grid)">');
      }
      if (hit.dataset.envid) {
        const e = ENV().find(x => x.public_incident_id === hit.dataset.envid);
        if (!e) return "";
        const title = LANG === "tr" ? (e.canonical_title_tr || e.canonical_title_en)
                                    : (e.canonical_title_en || e.canonical_title_tr);
        const rows = (e.effects || []).map(x => {
          const measure = x.value != null ? `${fmt.format(x.value)}${unitLabel(x.unit)}` : "";
          const est = effectStatusLabel(x);
          return `${html(effectLabel(x.type))}: ` +
            [measure, html(effectText(x))].filter(Boolean).join(" · ") +
            (est ? ` <span class="t-meta">[${html(est)}]</span>` : "") +
            (x.assertion_status && x.assertion_status !== "reported"
              ? ` <span class="t-meta">[${html(statusLabelOf(x.assertion_status))}]</span>` : "");
        }).join("<br>");
        return `<div class="t-title" lang="tr">${html(title)}</div>` +
          `<div class="t-meta">${html(e.public_incident_id)} · ${html(fmtDate(e))} · ` +
          `${html(e.province_name || provinceName(e.province_code))}</div>` +
          (rows ? `<div>${rows}</div>` : "") +
          (e.related_public_incident_id
            ? `<div class="t-meta">${t("env_related")} ${html(e.related_public_incident_id)}</div>`
            : "");
      }
      if (hit.dataset.id) {
        const i = byId.get(hit.dataset.id);
        const orgs = orgsOf(i.public_incident_id);
        return `<div class="t-title" lang="tr">${html(displayTitle(i))}</div>` +
          `<div>${html(sentence(i))}</div>` +
          (orgs.length
            ? `<div><span class="t-meta">${t("rh_org")}</span><br>` +
              orgs.map(orgLine).join("<br>") + `</div>`
            : "") +
          `<div class="t-meta">${html(i.public_incident_id)} · ${t("loc_approx")}</div>`;
      }
      const code = hit.dataset.provMark || hit.dataset.prov;
      const e = stats.get(code);
      return provinceTipHtml(code, e) +
        (hit.dataset.provMark ? `<div class="t-meta">${t(state.view === "locations" ? "key_coarse" : "key_province")}</div>` : "");
    };

    const place = (cx, cy) => {
      const box = wrapEl.getBoundingClientRect();
      let tx = cx - box.left + 14, ty = cy - box.top + 14;
      if (tx + tip.offsetWidth > box.width) tx = Math.max(4, tx - tip.offsetWidth - 26);
      if (ty + tip.offsetHeight > box.height) ty = Math.max(4, ty - tip.offsetHeight - 26);
      tip.style.left = tx + "px"; tip.style.top = ty + "px";
    };
    const show = (hit, cx, cy) => {
      svgEl.querySelectorAll(".is-hover").forEach(n => n.classList.remove("is-hover"));
      hit.classList.add("is-hover");
      tip.innerHTML = contentFor(hit);
      tip.style.display = "block";
      place(cx, cy);
    };
    const hide = () => {
      tipPinned = false;
      tip.style.display = "none";
      svgEl.querySelectorAll(".is-hover").forEach(n => n.classList.remove("is-hover"));
    };
    const SEL = ".mark-wrap, .svg-site, .svg-env, .tr-prov";

    svgEl.addEventListener("mousemove", ev => {
      if (tipPinned) return;
      const hit = ev.target.closest(SEL);
      if (!hit) { hide(); return; }
      show(hit, ev.clientX, ev.clientY);
    });
    svgEl.addEventListener("mouseleave", () => { if (!tipPinned) hide(); });

    // Tap / click: pin the tooltip open, and select a province.
    svgEl.addEventListener("click", ev => {
      // Selecting a province re-renders the SVG, which detaches ev.target; the
      // document-level close handler would then fail its containment test and
      // shut the tooltip we just opened. Keep the event to ourselves.
      ev.stopPropagation();
      const hit = ev.target.closest(SEL);
      if (!hit) { hide(); return; }
      const box = hit.getBoundingClientRect();
      tipPinned = true;
      show(hit, ev.clientX || box.left + box.width / 2, ev.clientY || box.top + box.height / 2);
      const code = hit.dataset.prov || hit.dataset.provMark;
      if (code) selectProvince(code);
    });
    svgEl.addEventListener("keydown", ev => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      const hit = ev.target.closest(SEL);
      if (!hit) return;
      ev.preventDefault();
      const box = hit.getBoundingClientRect();
      tipPinned = true;
      show(hit, box.left + box.width / 2, box.top + box.height / 2);
      const code = hit.dataset.prov || hit.dataset.provMark;
      if (code) selectProvince(code);
    });
    svgEl.addEventListener("focusin", ev => {
      const hit = ev.target.closest(SEL);
      if (!hit || tipPinned) return;
      const box = hit.getBoundingClientRect();
      show(hit, box.left + box.width / 2, box.top + box.height / 2);
    });
  }
  document.addEventListener("keydown", ev => {
    if (ev.key === "Escape") {
      tipPinned = false;
      const tip = document.getElementById("map-tip");
      if (tip) tip.style.display = "none";
    }
  });
  document.addEventListener("click", ev => {
    if (!ev.target.closest("#map-wrap")) {
      tipPinned = false;
      const tip = document.getElementById("map-tip");
      if (tip) tip.style.display = "none";
    }
  });

  // Clicking a province filters the whole page; clicking it again clears.
  function selectProvince(code) {
    state.province = state.province === code ? "" : code;
    const sel = document.getElementById("f-province");
    if (sel) sel.value = state.province;
    syncUrl();
    applyFilters();
  }

  // --- legend ---------------------------------------------------------------
  // Nested circles sharing a baseline: the standard proportional-symbol key.
  // It costs the height of the largest circle once, instead of three circles
  // side by side stretching every other legend item to match.
  function sizeKey() {
    const levels=[1,50,200].filter(d=>d<=PROV_MAX);
    if(!levels.length) return "";
    const k=matchMedia("(max-width: 640px)").matches ? .62 : 1;
    const r=d=>42*k*Math.sqrt(d/PROV_MAX), R=r(levels.at(-1)), pad=7;
    const body=levels.map(d=>{
      const rr=r(d),cy=pad+2*R-rr,cx=pad+R,ty=cy-rr;
      return `<circle cx="${cx}" cy="${cy}" r="${rr}" fill="var(--loss)" fill-opacity=".14" stroke="var(--loss)" stroke-opacity=".75"></circle>`+
        `<line x1="${cx}" y1="${ty}" x2="${pad+2*R+7}" y2="${ty}" stroke="var(--grid)"></line>`+
        `<text x="${pad+2*R+11}" y="${ty+4}" fill="var(--ink-muted)" style="font:11px system-ui,sans-serif">${fmt.format(d)}</text>`;
    }).join("");
    return `<span class="lg-size"><svg width="${Math.ceil(2*R+56)}" height="${Math.ceil(2*R+pad+3)}" aria-hidden="true">${body}</svg></span>`;
  }
  const coarseCounts = fs => {
    const counts = new Map();
    for (const s of fs) {
      if (!s.province_code) continue;
      counts.set(s.province_code, (counts.get(s.province_code) || 0) + 1);
    }
    return counts;
  };
  function renderMapLegend(fs) {
    // A phone gets the same key in fewer words: the legend was taller than the
    // map it explains. What is dropped is the size key, which a tap answers
    // better than a swatch can.
    const tight = matchMedia("(max-width: 640px)").matches;
    const accLegend = `<div class="lg-row"><span>${t("lg_size")}</span>${sizeKey()}`+
      `<span>${t(state.view==="locations" ? "key_located" : "key_province")}</span>`+
      (state.view==="locations" ? `<span><i class="key-circle hollow"></i> ${t("key_coarse")}</span>` : "")+
      `</div>`;
    const colorKey = ["coal","metal","mineral","other"].map(group =>
      `<span><i class="comm-chip round" style="background:${GROUP_HEX[group]}"></i>` +
      `${t(tight ? "lg_" + group + "_s" : "lg_" + group)} ` +
      `(${fs.filter(s=>groupOf(s)===group).length})</span>`).join("");
    // How many sites a circle stands for, read from its size rather than from
    // a printed number. Counts are small, so two steps are the whole scale.
    const biggest = Math.max(1, ...[...coarseCounts(fs).values()]);
    const sizeSteps = biggest > 1 ? [1, biggest] : [1];
    // The key is drawn with the mark's own shape, at the mark's own sizes.
    const rMax = siteRadius(sizeSteps.at(-1)), step = 2 * rMax + 8;
    const siteSizeKey = `<span class="lg-sitesize">` +
      `<svg viewBox="0 ${-rMax - 2} ${sizeSteps.length * step} ${2 * rMax + 18}" ` +
      `aria-hidden="true">` +
      sizeSteps.map((n, k) => {
        const cx = k * step + step / 2, r = siteRadius(n);
        return `<path d="M${cx},${-r} L${cx + r},0 L${cx},${r} L${cx - r},0 Z" ` +
          `fill="var(--site)"></path>` +
          `<text x="${cx}" y="${rMax + 13}" text-anchor="middle" fill="var(--ink-muted)" ` +
          `style="font:10px system-ui,sans-serif">${n}</text>`;
      }).join("") +
      `</svg>${t("lg_site_size")}</span>`;
    const typeKey = `<span><svg class="lg-sym" viewBox="-9 -9 18 18" aria-hidden="true">` +
      `<path d="M0,-7 L7,0 L0,7 L-7,0 Z" fill="var(--site)"></path></svg>` +
      `${t(tight ? "site_group_key_s" : "site_group_key")}</span>`;
    // The environmental key sits apart from the carnations and the site
    // symbols, because it counts a different thing.
    const envKey = ENV().length
      ? `<span><svg class="lg-sym" viewBox="-11 -11 22 22" aria-hidden="true">` +
        `<path d="M0,-7 L7,5 L-7,5 Z" fill="var(--c-mineral)" stroke="var(--c-mineral)" ` +
        `stroke-width="2" stroke-linejoin="round"></path></svg>` +
        `${tf("lg_env", { n: ENV().length })}</span>`
      : "";
    document.getElementById("maplegend").innerHTML = (state.layer!=="sites" ? accLegend : "")+
      (state.layer!=="accidents"
        ? `<div class="lg-sites"><div class="site-key">${colorKey}</div>` +
          `<div class="site-key">${tight ? "" : siteSizeKey}${typeKey}${envKey}</div></div>`
        : (envKey ? `<div class="lg-sites"><div class="site-key">${envKey}</div></div>` : ""));
  }

  // ---- Small multiples: where the loss sat, era by era ----------------------
  // Filtered counts only, no new metric. Static, so it needs no animation and
  // reads the same under prefers-reduced-motion.
  const ERA_RANGE = k => [
    k === 0 ? minY : [0, 2000, 2010, 2020][k],
    k === 3 ? maxY : [1999, 2009, 2019, 9999][k],
  ];
  function renderSmallMultiples() {
    const host = document.getElementById("smallmults");
    if (!host) return;
    const eraMax = (() => {
      let m = 1;
      for (let k = 0; k < 4; k++) {
        const per = new Map();
        for (const i of incidents) {
          if (eraOf(i) !== k || !i.province_code) continue;
          per.set(i.province_code, (per.get(i.province_code) || 0) + (i.fatalities_current || 0));
        }
        for (const v of per.values()) if (v > m) m = v;
      }
      return m;
    })();
    host.innerHTML = [0, 1, 2, 3].map(k => {
      const list = incidents.filter(i => eraOf(i) === k && (!state.province || i.province_code===state.province) && (!state.mechanism || mechanismsOf(i.public_incident_id).some(c=>c.code===state.mechanism)));
      const deaths = list.reduce((a, i) => a + (i.fatalities_current || 0), 0);
      const per = new Map();
      for (const i of list) {
        if (!i.province_code) continue;
        per.set(i.province_code, (per.get(i.province_code) || 0) + (i.fatalities_current || 0));
      }
      const provs = Object.keys(GEO.pathsSimple).map(code =>
        `<path class="sm-prov${per.has(code) ? " on" : ""}" d="${GEO.pathsSimple[code]}"></path>`).join("");
      const marks = [...per.entries()].map(([code, d]) => {
        const a = GEO.anchors[code];
        if (!a) return "";
        const r = 55 * Math.sqrt(d / eraMax);
        return `<circle cx="${a[0]}" cy="${a[1]}" r="${r}" fill="var(--loss)" fill-opacity=".65"><title>${html(provinceName(code))}: ${d}</title></circle>`;
      }).join("");
      const [y0, y1] = ERA_RANGE(k);
      const sel = state.from === y0 && state.to === y1 ? " is-sel" : "";
      return `<button type="button" class="sm-item${sel}" data-era="${k}">` +
        `<svg viewBox="0 0 ${GEO.W} ${GEO.H}" aria-hidden="true">${provs}${marks}</svg>` +
        `<span class="sm-label">${t("eras")[k]}</span>` +
        `<span class="sm-kind">${t("timeline_chapter_titles")[k]}</span>` +
        `<span class="sm-n">${tf("sm_people", { n: fmt.format(deaths) })}</span></button>`;
    }).join("");
    host.querySelectorAll(".sm-item").forEach(btn => {
      btn.addEventListener("click", () => {
        const [y0, y1] = ERA_RANGE(+btn.dataset.era);
        const already = state.from === y0 && state.to === y1;
        state.from = already ? minY : y0;
        state.to = already ? maxY : y1;
        document.getElementById("f-from").value = String(state.from);
        document.getElementById("f-to").value = String(state.to);
        syncUrl();
        applyFilters();
      });
    });
  }

  // ---- Chart (always the full register) --------------------------------------
  const tally = keep => {
    const map = new Map();
    for (const i of incidents) {
      const y = yearOf(i);
      if (!y || !keep(i)) continue;
      const e = map.get(y) || { deaths: 0, incidents: 0 };
      e.deaths += i.fatalities_current || 0; e.incidents += 1;
      map.set(y, e);
    }
    return map;
  };
  const byYear = tally(() => true);
  // Events of three or more deaths: the only series that means the same
  // thing before and after 2010 (see BREAK_YEAR below).
  const byYearMulti = tally(i => (i.fatalities_current || 0) >= 3);
  const isigByYear = new Map(D.aggregates.map(a => [a.year, a.deaths]));
  const chartYears = [];
  const contextYears=[...byYear.keys(),...isigByYear.keys()];
  const cy0 = contextYears.length ? Math.min(...contextYears) : new Date().getFullYear();
  const cy1 = contextYears.length ? Math.max(...contextYears) : cy0;
  for (let y = cy0; y <= cy1; y++) chartYears.push(y);
  const maxDeaths = Math.max(
    ...chartYears.map(y => (byYear.get(y) || { deaths: 0 }).deaths),
    ...isigByYear.values(), 1);
  // Round the axis up to a "nice" step so the ticks read 100/200/300/400
  // rather than 97/193/290/386. The bars scale to this same top.
  const GRID_STEPS = 4;
  const axisMax = (() => {
    const raw = maxDeaths / GRID_STEPS;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
    return step * GRID_STEPS;
  })();

  // Narrative selection is presentation only: all records remain in year detail.
  // Include source-linked milestones, 20+ death records, and the first/latest
  // dated record. Current tolls and their uncertainty always come from incidents.
  const timelineState = { chapter: null, year: null, series: "all" };
  // One period scheme for the whole page: the timeline chapters are the same
  // four periods as the maps, and the boundary at 2010 is where the sources
  // change from recording only multi-death events to recording single deaths.
  const timelineRanges = () => [0, 1, 2, 3].map(ERA_RANGE);
  const BREAK_YEAR = 2010, MULTI_MIN = 3;
  function timelineEvents() {
    const dated = incidents.filter(i => yearOf(i) != null);
    const ids = new Set([dated[0]?.public_incident_id, dated.at(-1)?.public_incident_id]);
    for (const e of D.policy_events || []) {
      for (const i of dated) if ((e.notes || "").includes(i.public_incident_id)) ids.add(i.public_incident_id);
    }
    const events = dated.filter(i => ids.has(i.public_incident_id) || i.fatalities_current >= 20)
      .map(i => ({date:i.incident_start_datetime.slice(0,10), kind:"disaster", incident:i}));
    events.push(...(D.policy_events || []).filter(e=>e.kind !== "disaster"));
    return events.sort((a,b)=>a.date.localeCompare(b.date)).map((e,k)=>({...e,number:k+1}));
  }
  function eventTitle(e) {
    return e.incident ? displayTitle(e.incident) : (LANG==="tr" ? e.label_tr : e.label_en);
  }
  function renderTimelineNarrative() {
    const ranges = timelineRanges();
    const host = document.getElementById("timeline-chapters");
    host.innerHTML = ranges.map(([from,to],k) => {
      if (to < minY || from > maxY || to < from) return "";
      const start=Math.max(from,minY), end=Math.min(to,maxY);
      const list=incidents.filter(i=>yearOf(i)>=start && yearOf(i)<=end);
      const deaths=list.reduce((sum,i)=>sum+(i.fatalities_current || 0),0);
      return `<button type="button" data-chapter="${k}" aria-pressed="${timelineState.chapter===k}"><span>${start}-${end}</span><strong>${t("timeline_chapter_titles")[k]}</strong><small>${tf("timeline_chapter_counts",{n:list.length,d:fmt.format(deaths)})}</small></button>`;
    }).join("");
    host.querySelectorAll("[data-chapter]").forEach(b=>b.addEventListener("click",()=>{
      timelineState.chapter=+b.dataset.chapter; timelineState.year=null; renderChart();
    }));
    document.getElementById("timeline-reset").onclick=()=>{
      timelineState.chapter=null; timelineState.year=null; renderChart();
    };
    const range=timelineState.chapter===null ? null : ranges[timelineState.chapter];
    const list=range ? incidents.filter(i=>yearOf(i)>=range[0] && yearOf(i)<=range[1]) : incidents;
    document.getElementById("timeline-overview").textContent=range ? tf("timeline_selected",{
      from:Math.max(minY,range[0]),to:Math.min(maxY,range[1]),n:list.length,
      d:fmt.format(list.reduce((sum,i)=>sum+(i.fatalities_current || 0),0))
    }) : t("timeline_full");
    const events=timelineEvents().filter(e=>!range || (+e.date.slice(0,4)>=range[0] && +e.date.slice(0,4)<=range[1]));
    document.getElementById("timeline-events").innerHTML=events.map(e=>{
      const i=e.incident;
      const mechanisms=i ? [...new Set(mechanismsOf(i.public_incident_id).map(mechLabel))].join(" · ") : "";
      return `<li class="timeline-event ${i ? "" : "policy"}" id="timeline-event-${e.number}">
        <div class="event-date"><span class="event-number">${String(e.number).padStart(2,"0")}</span>${html(i ? fmtDate(i) : fmtDate({incident_start_datetime:e.date,date_precision:"exact_date"}))} · ${t(i ? "timeline_event" : "timeline_policy")}</div>
        <h3>${html(eventTitle(e))}</h3>
        ${i ? `<p><strong class="event-count">${fmt.format(i.fatalities_current)}</strong> ${t("timeline_recorded")}${evidenceBadge(i.public_incident_id)}${casualtyPill(i) ? " · " + casualtyPill(i) : ""}</p>
          <p>${html(provinceName(i.province_code))}${mechanisms ? " · "+html(mechanisms) : ""}</p>
          <button type="button" data-event-record="${html(i.public_incident_id)}">${t("timeline_open")}</button>`
          : `<p>${t("timeline_policy_note")}</p>${sourceLink(e.source_url,t("rh_sources"))}`}
        </li>`;
    }).join("") || `<li>${t("timeline_empty")}</li>`;
    document.querySelectorAll("[data-event-record]").forEach(b=>b.addEventListener("click",()=>openDetail(b.dataset.eventRecord)));
    document.getElementById("events-caption").textContent=t("timeline_selection_note");
    document.getElementById("timeline-fold-summary").textContent=tf("milestones_fold",{n:events.length});
    renderYearDetail();
  }
  function renderYearDetail() {
    const host=document.getElementById("year-detail"),year=timelineState.year;
    if(year===null) { host.innerHTML=`<p>${t("timeline_year_prompt")}</p>`; return; }
    const list=incidents.filter(i=>yearOf(i)===year);
    const events=(D.policy_events || []).filter(e=>e.kind!=="disaster" && +e.date.slice(0,4)===year);
    host.innerHTML=`<h3>${year} · ${list.length} ${t("tt_records")}</h3><ul>`+
      list.map(i=>`<li>${html(fmtDate(i))} · <button type="button" data-year-record="${html(i.public_incident_id)}">${html(displayTitle(i))}</button> · ${fmt.format(i.fatalities_current)} ${t("timeline_recorded")} ${casualtyPill(i)}</li>`).join("")+
      events.map(e=>`<li>${t("timeline_policy")}: ${sourceLink(e.source_url,eventTitle(e))}</li>`).join("")+
      `</ul>${!list.length ? `<p>${t("tt_none")}</p>` : ""}<p>${t("timeline_year_help")}</p>`+
      (year>=minY && year<=maxY ? `<button type="button" id="timeline-focus-map">${t("timeline_focus")}</button>` : "");
    host.querySelectorAll("[data-year-record]").forEach(b=>b.addEventListener("click",()=>openDetail(b.dataset.yearRecord)));
    const focus=document.getElementById("timeline-focus-map");
    if(focus) focus.onclick=()=>{
      state.from=state.to=year; state.province=""; state.mechanism="";
      fromSel.value=toSel.value=String(year); provSel.value=mechSel.value="";
      syncUrl(); applyFilters();
      const map=document.getElementById("map-panel"); map.tabIndex=-1; map.focus();
      map.scrollIntoView?.({behavior:"smooth",block:"start"});
    };
  }
  // Event callouts are placed before anything is drawn, because the label
  // stack decides how tall the chart has to be. Rows are assigned by testing
  // the interval each label actually occupies (text width, anchor direction,
  // marker disc) instead of a fixed horizontal clearance, which let labels
  // 145 to 200 units apart print on top of each other.
  const LBL_CH = 7.3, LBL_GAP = 10, MARK_R = 12;
  function placeEvents(events, years, x, W) {
    const taken=[], placed=[];
    for(const e of events) {
      const k=years.indexOf(+e.date.slice(0,4)); if(k<0) continue;
      const xx=x(k), policy=!e.incident;
      const label=eventTitle(e);
      const limit=policy ? 64 : 46;
      const short=label.length>limit ? label.slice(0,limit-1)+"…" : label;
      const wide=short.length*LBL_CH;
      const anchor=xx+13+wide>W-6 ? "end" : "start", labelX=anchor==="end" ? xx-13 : xx+13;
      const span=anchor==="end" ? [labelX-wide, xx+MARK_R] : [xx-MARK_R, labelX+wide];
      // A leader runs from its marker toward the bars, through every row
      // nearer the bars. A label may not sit across another marker's leader,
      // and a new leader may not cut through a label already placed. Incident
      // rows stack away from the bars upward (row 0 is farthest), policy rows
      // downward (row 0 is nearest).
      const nearer=(a,b)=>policy ? a<b : a>b;
      const crosses=(s,px)=>px > s[0]-4 && px < s[1]+4;
      const clash=(row,strict)=>taken.some(p=>p.policy===policy && (
            (p.row===row && span[0] < p.span[1]+LBL_GAP && span[1] > p.span[0]-LBL_GAP) ||
            (strict && nearer(row,p.row) && crosses(span,p.xx)) ||
            (strict && nearer(p.row,row) && crosses(p.span,xx))));
      // Some layouts have no row that also keeps every leader clear (a label
      // anchored at the right edge runs back over earlier markers). Then the
      // labels still must not overlap, and the leader rule gives way.
      let row=0;
      while(row<12 && clash(row,true)) row++;
      if(row===12) { row=0; while(clash(row,false)) row++; }
      taken.push({row, span, policy, xx});
      placed.push({e, xx, policy, row, label, short, anchor, labelX});
    }
    const rows=k=>Math.max(0, ...placed.filter(p=>p.policy===k).map(p=>p.row+1));
    return { placed, eventRows: rows(false), policyRows: rows(true) };
  }

  function renderChart() {
    const years=chartYears,W=1000,left=54,right=18,iw=W-left-right;
    const step=iw/years.length,bw=Math.min(20,step*.72),ph=205;
    const x=k=>left+step*(k+.5);
    const layout=placeEvents(timelineEvents(), years, x, W);
    const top=Math.max(64, 44+layout.eventRows*27+14), base=top+ph;
    const H=base+46+Math.max(1,layout.policyRows)*27+8;
    const scale=v=>ph*v/axisMax;
    const parts=[];
    const series=timelineState.series==="multi" ? byYearMulti : byYear;
    const range=timelineState.chapter===null ? null : timelineRanges()[timelineState.chapter];
    if(range) {
      const first=years.findIndex(y=>y>=range[0]),last=years.findLastIndex(y=>y<=range[1]);
      if(first>=0 && last>=first) parts.push(`<rect x="${left+step*first}" y="${top}" width="${step*(last-first+1)}" height="${ph}" fill="#f8ecec"></rect>`);
    }
    for(let n=0;n<=4;n++) {
      const value=axisMax*n/4,yy=base-scale(value);
      parts.push(`<line class="gridline" x1="${left}" x2="${W-right}" y1="${yy}" y2="${yy}"></line><text class="ticklabel" x="${left-8}" y="${yy+4}" text-anchor="end">${fmt.format(value)}</text>`);
    }
    parts.push(`<text class="chart-label" x="${left}" y="22">${t(timelineState.series==="multi" ? "series_multi" : "lgc_bars")} · ${t("timeline_recorded")}</text>`);
    // Where the record changes kind. Drawn between 2009 and 2010 and named,
    // so nobody reads the denser years to its right as a rise.
    const breakAt=years.indexOf(BREAK_YEAR);
    if(breakAt>0) {
      const bx=left+step*breakAt;
      parts.push(`<line class="break-line" x1="${bx}" x2="${bx}" y1="${top}" y2="${base}"></line><text class="break-label" x="${bx-6}" y="${top+12}" text-anchor="end">${html(t("chart_break_label"))}</text>`);
    }
    years.forEach((year,k)=>{
      const rec=series.get(year),xx=x(k);
      if(rec) parts.push(`<rect class="bar" x="${xx-bw/2}" y="${base-scale(rec.deaths)}" width="${bw}" height="${scale(rec.deaths)}"></rect>`);
      else parts.push(`<text class="ticklabel" x="${xx}" y="${base-4}" text-anchor="middle">·</text>`);
      const edge=k===0 || k===years.length-1;
      if(edge || (year%5===0 && k>=3 && k<=years.length-4)) parts.push(`<text class="ticklabel" x="${xx}" y="${base+22}" text-anchor="middle">${year}</text>`);
      const label=`${year}: ${rec ? rec.deaths+" "+t("timeline_recorded")+", "+rec.incidents+" "+t("tt_records") : t("tt_none")}`;
      parts.push(`<rect class="year-hit${timelineState.year===year ? " is-active" : ""}" data-year="${year}" x="${xx-step/2}" y="${top}" width="${step}" height="${ph+26}" fill="transparent" tabindex="0" role="button" aria-pressed="${timelineState.year===year}" aria-label="${html(label)}"><title>${html(label)}</title></rect>`);
    });
    for(const {e,xx,policy,row,label,short,anchor,labelX} of layout.placed) {
      const yy=policy ? base+46+row*27 : 44+row*27;
      if(!policy) parts.push(`<line class="event-leader" x1="${xx}" x2="${xx}" y1="${yy+7}" y2="${base-scale(series.get(+e.date.slice(0,4))?.deaths || 0)-3}"></line>`);
      else parts.push(`<line class="event-leader" x1="${xx}" x2="${xx}" y1="${base+27}" y2="${yy-10}" style="stroke:#315c78"></line>`);
      parts.push(`<a href="#timeline-event-${e.number}" data-marker="${e.number}" aria-label="${html(label)}">
        <rect x="${xx-12}" y="${yy-13}" width="24" height="24" fill="transparent"></rect>
        ${policy ? `<rect x="${xx-8}" y="${yy-9}" width="16" height="16" fill="#315c78"></rect>` : `<circle cx="${xx}" cy="${yy-1}" r="11" fill="white" stroke="var(--loss)"></circle>`}
        <text x="${xx}" y="${yy+3}" text-anchor="middle" style="font:600 11px system-ui;fill:${policy ? "white" : "var(--loss)"}">${e.number}</text>
        <text class="event-marker" x="${labelX}" y="${yy+4}" text-anchor="${anchor}">${html(short)}</text><title>${html(label)}</title></a>`);
    }
    const svg=document.getElementById("chart"); svg.setAttribute("viewBox",`0 0 ${W} ${H}`);svg.innerHTML=parts.join("");
    document.querySelectorAll("#series-toggle [data-series]").forEach(b=>{
      b.setAttribute("aria-pressed",String(b.dataset.series===timelineState.series));
      b.onclick=()=>{ timelineState.series=b.dataset.series; renderChart(); };
    });
    // On a narrow screen the chart scrolls sideways. Open it on the recent
    // years, where most records are, rather than on 1983.
    const wrap=document.getElementById("chart-wrap");
    if(wrap && !wrap.dataset.opened && wrap.scrollWidth>wrap.clientWidth) {
      wrap.scrollLeft=wrap.scrollWidth; wrap.dataset.opened="1";
    }
    const selectYear=hit=>{
      timelineState.year=+hit.dataset.year;
      svg.querySelectorAll(".year-hit").forEach(n=>{
        const active=n===hit;n.classList.toggle("is-active",active);n.setAttribute("aria-pressed",String(active));
      });
      renderYearDetail();
    };
    svg.onclick=e=>{const hit=e.target.closest(".year-hit");if(hit)selectYear(hit);};
    svg.onkeydown=e=>{
      const hit=e.target.closest(".year-hit");if(!hit)return;
      if(e.key==="Enter" || e.key===" ") {e.preventDefault();selectYear(hit);}
      if(e.key==="ArrowLeft" || e.key==="ArrowRight") {
        e.preventDefault();const hits=[...svg.querySelectorAll(".year-hit")],k=hits.indexOf(hit)+(e.key==="ArrowRight" ? 1 : -1);
        hits[Math.max(0,Math.min(hits.length-1,k))].focus();
      }
    };
    svg.querySelectorAll("[data-marker]").forEach(a=>a.addEventListener("click",e=>{
      e.preventDefault();
      const number=+a.dataset.marker;
      if(timelineState.chapter!==null) {timelineState.chapter=null;renderChart();}
      const card=document.getElementById("timeline-event-"+number);
      document.getElementById("timeline-fold").open=true;
      if(card) {card.tabIndex=-1;card.focus();card.scrollIntoView?.({behavior:"smooth",block:"nearest"});}
    }));
    const sectorParts=[];
    for(let n=0;n<=4;n++) {
      const value=axisMax*n/4,yy=230-180*value/axisMax;
      sectorParts.push(`<line class="gridline" x1="${left}" x2="${W-right}" y1="${yy}" y2="${yy}"></line><text class="ticklabel" x="${left-8}" y="${yy+4}" text-anchor="end">${fmt.format(value)}</text>`);
    }
    const sectorYears=[...isigByYear.keys()].sort((a,b)=>a-b);
    const sy0=sectorYears[0],sy1=sectorYears.at(-1);
    const sectorSpan=sy0==null ? [] : Array.from({length:sy1-sy0+1},(_,k)=>sy0+k);
    sectorSpan.forEach((year,k)=>{
      const value=isigByYear.get(year),ss=iw/sectorSpan.length,xx=left+ss*(k+.5);
      if(value!=null) sectorParts.push(`<rect x="${xx-Math.min(22,ss*.7)/2}" y="${230-180*value/axisMax}" width="${Math.min(22,ss*.7)}" height="${180*value/axisMax}" fill="#627985"><title>${year}: ${value}</title></rect>`);
      sectorParts.push(`<text class="ticklabel" x="${xx}" y="255" text-anchor="middle">${year}</text>`);
    });
    const sector=document.getElementById("sector-chart");sector.setAttribute("viewBox","0 0 1000 280");sector.innerHTML=sectorParts.join("");
    document.getElementById("annual-table").innerHTML=`<table><thead><tr><th>${t("rate_year")}</th><th>${t("lgc_bars")}</th><th>${t("lgc_line")}</th></tr></thead><tbody>`+
      years.map(y=>`<tr><td>${y}</td><td>${series.has(y) ? fmt.format(series.get(y).deaths) : "—"}</td><td>${isigByYear.has(y) ? fmt.format(isigByYear.get(y)) : "—"}</td></tr>`).join("")+`</tbody></table>`;
    renderTimelineNarrative();
  }

  // ---- Mechanisms --------------------------------------------------------------
  // ---- Documented-hazard matrix ---------------------------------------------
  // Built at export time by analysis.hazard_matrix() from the public files, so
  // the table can be rebuilt by anyone holding the export. It describes the
  // whole register and deliberately ignores the filters: a severity profile
  // computed from a filtered subset would read as a finding about that subset.
  const HZ = () => D.hazard_matrix || null;
  const mechShort = code => (t("hz_short") || {})[code] ||
    (HZ()?.mechanisms || []).filter(m => m.code === code)
      .map(m => LANG === "tr" ? m.label_tr : m.label_en)[0] || code;
  const mechFull = code => (HZ()?.mechanisms || []).filter(m => m.code === code)
      .map(m => LANG === "tr" ? m.label_tr : m.label_en)[0] || code;

  function renderHazardHeads() {
    const M = HZ();
    if (!M) return;
    const head = document.getElementById("hz-head");
    if (head) head.innerHTML =
      `<th>${t("hz_col_mech")}</th>` +
      M.bands.map(b => `<th class="hz">${html(LANG === "tr" ? b.label_tr : b.label_en)}</th>`).join("") +
      `<th class="num">${t("hz_col_records")}</th><th class="num">${t("hz_col_deaths")}</th>` +
      `<th class="num">${t("hz_col_worst")}</th><th>${t("hz_col_span")}</th>`;
    const phead = document.getElementById("hzp-head");
    if (phead) phead.innerHTML =
      `<th>${t("hzp_col_prov")}</th>` +
      M.mechanism_order.map(c =>
        `<th class="hz" title="${html(mechFull(c))}">${html(mechShort(c))}</th>`).join("") +
      `<th class="num">${t("hzp_col_records")}</th><th class="num">${t("hzp_col_deaths")}</th>` +
      `<th>${t("hzp_col_latest")}</th><th class="num">${t("hzp_col_sites")}</th>`;
  }

  function renderHazards() {
    const M = HZ();
    if (!M) return;
    // Shade is a reading aid over the printed number, never the value itself.
    const shade = (n, max) => n === 0 ? "" :
      ` style="background:rgba(194,47,47,${(0.07 + 0.33 * (n / max)).toFixed(3)})"`;
    const cell = (n, max) =>
      `<td class="hz hz-${n === 0 ? "0" : "n"}"${shade(n, max)}>${n === 0 ? "·" : fmt.format(n)}</td>`;

    const maxCell = Math.max(1, ...M.mechanisms.flatMap(r => r.cells));
    document.querySelector("#hazard-matrix tbody").innerHTML = M.mechanisms.map(r => {
      const main = LANG === "tr" ? r.label_tr : r.label_en;
      const span = r.first_year === r.latest_year ? String(r.first_year ?? "")
        : `${r.first_year ?? ""}-${r.latest_year ?? ""}`;
      return `<tr><th scope="row">${html(main)}</th>` +
        r.cells.map(n => cell(n, maxCell)).join("") +
        `<td class="num">${fmt.format(r.records)}</td>` +
        `<td class="num">${fmt.format(r.deaths)}</td>` +
        `<td class="num">${fmt.format(r.worst)}</td>` +
        `<td class="hz-span">${html(span)}</td></tr>`;
    }).join("");

    const maxProv = Math.max(1, ...M.provinces.flatMap(p =>
      M.mechanism_order.map(c => p.mechanisms[c] || 0)));
    // Alphabetical. Ordering provinces by deaths would make the table a
    // ranking, which is the one thing this page says it is not.
    const provRows = M.provinces.slice().sort((a, b) =>
      provinceName(a.province_code || "").localeCompare(provinceName(b.province_code || ""), "tr"));
    document.querySelector("#hazard-provinces tbody").innerHTML = provRows.map(p => {
      const name = p.province_code ? provinceName(p.province_code) : t("pill_not_stated");
      return `<tr><th scope="row">${html(name)}</th>` +
        M.mechanism_order.map(c => cell(p.mechanisms[c] || 0, maxProv)).join("") +
        `<td class="num">${fmt.format(p.records)}</td>` +
        `<td class="num">${fmt.format(p.deaths)}</td>` +
        `<td class="hz-span">${p.latest_year ?? ""}</td>` +
        `<td class="num">${p.documented_sites ? fmt.format(p.documented_sites)
          : `<span class="pill">${t("pill_not_stated")}</span>`}</td></tr>`;
    }).join("");

    const outside = M.sites_outside_recorded_provinces || { sites: 0, provinces: 0 };
    const note = document.getElementById("hz-sites-note");
    if (note) note.innerHTML = tf("hz_sites_note",
      { sites: fmt.format(outside.sites), provinces: fmt.format(outside.provinces) });
    const caption = document.querySelector('#hazards [data-i18n="hz_caption"]');
    if (caption) caption.innerHTML = tf("hz_caption", { n: fmt.format(M.totals.records) });
  }

  // ---- Environmental records -----------------------------------------------
  // A different kind of record with a different unit of harm, so it is drawn
  // as cards rather than as rows beside the death counts, and never in red.
  const ENV = () => D.environmental || [];
  const effectLabel = type => t("eff_" + type) || type;
  const unitLabel = unit => unit ? " " + html((t("units") || {})[unit] || unit) : "";
  // Descriptions carry both languages; the place names inside them do not
  // change, because they are names.
  const effectText = x => (LANG === "tr" ? x.qualitative : (x.qualitative_en || x.qualitative))
    || "";
  // Whether the effect was observed, reported, threatened or modelled. Shown on
  // every row, because leaving the common case unlabelled is what let one label,
  // "Reached", stand for a measured arrival and a reported threat alike.
  const effectStatusLabel = x => x.effect_status ? t("est_" + x.effect_status) : "";

  function renderEnvironmental() {
    // Counts that appear in prose are filled from the payload, never written
    // into the sentence, so they cannot go stale (quality audit 2026-10-20, A5).
    const named = incidents.filter(i => orgsOf(i.public_incident_id).length).length;
    const charge = document.querySelector('[data-i18n="ab8_d"]');
    if (charge) charge.innerHTML = tf("ab8_d", { n: named, total: incidents.length });
    const scope = document.querySelector('[data-i18n="env_scope"]');
    if (scope) scope.innerHTML = tf("env_scope", { n: (D.environmental || []).length });
    const host = document.getElementById("env-list");
    if (!host) return;
    const records = ENV();
    if (!records.length) { host.innerHTML = `<p class="caption">${t("env_none")}</p>`; return; }
    host.innerHTML = records.slice().sort((a, b) =>
      (b.incident_start_datetime || "").localeCompare(a.incident_start_datetime || "")
    ).map(e => {
      const title = LANG === "tr"
        ? (e.canonical_title_tr || e.canonical_title_en)
        : (e.canonical_title_en || e.canonical_title_tr);
      const mech = (e.mechanisms || []).map(m =>
        html(LANG === "tr" ? (m.label_tr || m.label_en) : (m.label_en || m.label_tr))).join(", ");
      const rows = (e.effects || []).map(x => {
        const measure = x.value != null ? `${fmt.format(x.value)}${unitLabel(x.unit)}` : "";
        const text = [measure, html(effectText(x))].filter(Boolean).join(" · ");
        const est = effectStatusLabel(x);
        const flag = (est ? ` <span class="pill">${html(est)}</span>` : "") +
          (x.assertion_status && x.assertion_status !== "reported"
            ? ` <span class="pill">${html(statusLabelOf(x.assertion_status))}</span>` : "");
        return `<dt>${html(effectLabel(x.type))}</dt><dd lang="tr">${text}${flag}</dd>`;
      }).join("");
      const cites = (e.citations || []).map(c => sourceLink(c.url, c.organization))
        .filter((v, k, arr) => arr.indexOf(v) === k).join(", ");
      return `<article class="env-card">` +
        `<h3><span class="env-chip"></span><span lang="tr">${html(title)}</span></h3>` +
        `<div class="env-meta">${html(e.public_incident_id)} · ${html(fmtDate(e))} · ` +
        `${html(e.province_name || provinceName(e.province_code))}` +
        (mech ? ` · ${t("env_mech")}: ${mech}` : "") +
        (e.related_public_incident_id
          ? ` · ${t("env_related")} ${html(e.related_public_incident_id)}` : "") +
        `</div>` +
        `<details class="phone-fold"><summary><span class="fold-h">${t("env_fold")}</span></summary>` +
        evidenceNoticesHtml(e.public_incident_id) +
        (rows ? `<dl>${rows}</dl>` : "") + `</details>` +
        (cites ? `<div class="env-src">${t("env_sources")}: ${cites}</div>` : "") +
        `</article>`;
    }).join("");
    setupCaptions();
  }

  function renderMechanisms() {
    const mechCounts = new Map();
    for (const i of incidents) {
      const counted = new Set();
      for (const c of mechanismsOf(i.public_incident_id)) {
        if (counted.has(c.code)) continue;
        counted.add(c.code);
        const key = `${c.label_en}|${c.label_tr}`;
        mechCounts.set(key, (mechCounts.get(key) || 0) + 1);
      }
    }
    const mechRows = [...mechCounts.entries()].sort((a, b) => b[1] - a[1]);
    const mechMax = Math.max(...mechRows.map(r => r[1]), 1);
    document.getElementById("mechanisms").innerHTML = mechRows.map(([key, n]) => {
      const [en, tr] = key.split("|");
      const main = LANG === "tr" ? tr : en, second = LANG === "tr" ? en : tr;
      return `<div class="mrow">` +
        `<div class="mlabel">${html(main)} <span class="tr">${html(second)}</span></div>` +
        `<div><div class="mfill" style="width:${(n / mechMax) * 100}%"></div></div>` +
        `<div class="mcount">${n}</div></div>`;
    }).join("") || `<p class="caption">${t("mech_none")}</p>`;
  }

  // ---- Table sorting -----------------------------------------------------------
  const sortState = { records: { key: "date", dir: 1 }, sites: { key: "site", dir: 1 } };
  const RECORD_SORTERS = {
    id: i => i.public_incident_id,
    date: i => i.incident_start_datetime || "",
    prov: i => provinceName(i.province_code),
    what: i => i.canonical_title_tr || "",
    people: i => i.fatalities_current || 0,
    mech: i => mechanismsOf(i.public_incident_id).map(mechLabel).join(", "),
    org: i => orgsOf(i.public_incident_id).map(o => o.name).join(", "),
  };
  const SITE_SORTERS = {
    site: s => s.name || "",
    type: s => typeLabel(s),
    comm: s => commodityText(s) || "",
    prov: s => (s.province_code ? provinceName(s.province_code) : ""),
    op: s => (s.organizations || []).map(o => o.name).join(", "),
    country: s => (s.organizations || []).map(o => o.country_label).filter(Boolean).join(", "),
  };
  function sortRows(rows, sorters, st) {
    const f = sorters[st.key];
    if (!f) return rows;
    const loc = LANG === "tr" ? "tr" : "en";
    return rows.slice().sort((a, b) => {
      const va = f(a), vb = f(b);
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * st.dir;
      return String(va).localeCompare(String(vb), loc) * st.dir;
    });
  }
  function markSorted(headRowId, st) {
    document.querySelectorAll(`#${headRowId} th[data-sort]`).forEach(th => {
      if (th.dataset.sort === st.key) {
        th.setAttribute("aria-sort", st.dir === 1 ? "ascending" : "descending");
        th.insertAdjacentHTML("beforeend", `<span class="arr">${st.dir === 1 ? "\u25b2" : "\u25bc"}</span>`);
      } else {
        th.removeAttribute("aria-sort");
      }
    });
  }
  // Delegated from the stable <table>, because applyStatic() rewrites the
  // header row's innerHTML on every render.
  function bindSort(tableId, which) {
    document.getElementById(tableId).addEventListener("click", ev => {
      const th = ev.target.closest("th[data-sort]");
      if (!th) return;
      const st = sortState[which];
      if (st.key === th.dataset.sort) st.dir *= -1;
      else { st.key = th.dataset.sort; st.dir = 1; }
      applyStatic();   // rebuilds both header rows and their sort markers
      syncToggles();
      applyFilters();  // re-renders the rows in the new order
    });
  }
  bindSort("records", "records");
  bindSort("sites-table", "sites");

  // ---- Sites table -----------------------------------------------------------
  function renderSites(fs) {
    document.querySelector("#sites-table tbody").innerHTML = sortRows(fs, SITE_SORTERS, sortState.sites).map(s => {
      const orgs = (s.organizations || []);
      const orgNames = orgs.map(o =>
        `<span lang="tr">${html(o.name)}</span> <span class="pill">${html(roleLabel(o.role))} · ${html(statusLabelOf(o.assertion_status))}</span>`).join("<br>") ||
        `<span class="pill">${t("pill_not_stated_src")}</span>`;
      const countries = [...new Set(orgs.map(o => o.country_label).filter(Boolean))].map(html).join(", ") ||
        `<span class="pill">${t("pill_not_stated")}</span>`;
      return `<tr>
        <td data-label="${t("sh_site")}" lang="tr"><strong>${html(s.name)}</strong></td>
        <td data-label="${t("sh_type")}">${html(typeLabel(s))}</td>
        <td data-label="${t("sh_comm")}" title="${html(s.commodity_label || "")}"><span class="comm-chip" style="background:${GROUP_HEX[groupOf(s)]}"></span>${html(commodityText(s)) || `<span class="pill">${t("pill_not_stated")}</span>`}</td>
        <td data-label="${t("sh_prov")}">${s.province_code ? html(provinceName(s.province_code)) : `<span class="pill">${t("pill_not_stated")}</span>`}</td>
        <td data-label="${t("sh_op")}">${orgNames}</td>
        <td data-label="${t("sh_country")}">${countries}</td>
        <td data-label="${t("sh_source")}">${s.source_url ? sourceLink(s.source_url, "Wikidata") : ""}</td>
      </tr>`;
    }).join("") || `<tr><td colspan="7">${t("no_sites")}</td></tr>`;
  }

  // ---- Records table -------------------------------------------------------------
  function orgCell(id) {
    const orgs = orgsOf(id);
    if (!orgs.length) return `<span class="pill">${t("pill_not_stated_src")}</span>`;
    return orgs.map(o => {
      const country = o.country_label ? ` · ${html(o.country_label)}` : "";
      return `<span lang="tr">${html(o.name)}</span> ` +
        `<span class="pill">${html(roleLabel(o.role))}${country} · ${html(statusLabelOf(o.assertion_status))}</span>`;
    }).join("<br>");
  }

  function renderRecords(fi) {
    document.querySelector("#records tbody").innerHTML = sortRows(fi, RECORD_SORTERS, sortState.records).map(i => {
      const cites = (D.citations[i.public_incident_id] || [])
        .map(c => sourceLink(c.url, c.organization))
        .filter((v, k, arr) => arr.indexOf(v) === k).join(", ");
      const mech = mechanismsOf(i.public_incident_id).map(mechLabel).join(", ");
      return `<tr class="rec-row" data-id="${html(i.public_incident_id)}" tabindex="0">
        <td data-label="${t("rh_what")}" lang="${LANG}"><strong>${html(displayTitle(i))}</strong>${evidenceBadge(i.public_incident_id)}</td>
        <td data-label="${t("rh_date")}">${html(fmtDate(i))}</td>
        <td data-label="${t("rh_prov")}">${html(provinceName(i.province_code))}</td>
        <td data-label="${t("rh_people")}" class="num">${fmt.format(i.fatalities_current)}${casualtyPill(i) ? "<br>" + casualtyPill(i) : ""}${i.injuries_current != null ? `<br><span class="pill">${tf("pill_injured", { n: fmt.format(i.injuries_current) })}</span>` : ""}</td>
        <td data-label="${t("rh_mech")}">${mech ? `<span class="pill">${html(mech)}</span>` : `<span class="pill">${t("pill_no_mech")}</span>`}</td>
        <td data-label="${t("rh_org")}">${orgCell(i.public_incident_id)}</td>
        <td data-label="${t("rh_sources")}">${cites}</td>
        <td data-label="${t("rh_id")}" class="rec-id">${html(i.public_incident_id)}</td>
      </tr>`;
    }).join("") || `<tr><td colspan="8">${t("no_records")}</td></tr>`;
  }

  // ---- Downloads (filter-aware, built from the same payload) -----------------
  function toCsv(rows, columns) {
    const esc = v => {
      let s = v == null ? "" : String(v);
      if (typeof v === "string" && /^[\s]*[=+@-]/.test(s)) s = "'" + s;
      return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    return [columns.join(",")]
      .concat(rows.map(r => columns.map(c => esc(r[c])).join(",")))
      .join("\n") + "\n";
  }
  function download(name, text, type) {
    const blob = new Blob([text], { type });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }
  const RECORD_COLUMNS = ["public_incident_id", "date", "date_display", "date_precision",
    "province", "title_tr", "deaths", "casualty_status", "injuries", "mechanisms",
    "organizations_at_incident_date", "organization_countries",
    "latitude", "longitude", "coordinate_precision", "sources", "evidence_notices", "evidence_notice_sources"];
  const SITE_COLUMNS = ["site", "type", "commodity", "commodity_group", "province",
    "operators", "operator_countries", "status", "latitude", "longitude",
    "coordinate_precision", "source_url"];
  const stamp = () => (D.export_timestamp || "").slice(0, 10) || "export";
  document.getElementById("dl-records").addEventListener("click", () => {
    const rows = incidents.filter(incidentMatches).map(i => ({
      public_incident_id: i.public_incident_id,
      date: (i.incident_start_datetime || "").slice(0, 10),
      date_display: fmtDate(i),
      date_precision: i.date_precision,
      province: provinceName(i.province_code),
      title_tr: i.canonical_title_tr,
      deaths: i.fatalities_current,
      casualty_status: i.casualty_status,
      injuries: i.injuries_current,
      mechanisms: mechanismsOf(i.public_incident_id).map(mechLabel).join("; "),
      organizations_at_incident_date: orgsOf(i.public_incident_id)
        .map(o => `${o.name} (${roleLabel(o.role)})`).join("; "),
      organization_countries: [...new Set(orgsOf(i.public_incident_id)
        .map(o => o.country_label).filter(Boolean))].join("; "),
      latitude: i.latitude, longitude: i.longitude,
      coordinate_precision: i.coordinate_precision,
      evidence_notices: noticesOf(i.public_incident_id).map(n => `[${n.checked_at}; ${n.status}] ${noticeText(n)}`).join(" | "),
      evidence_notice_sources: noticesOf(i.public_incident_id).flatMap(n => n.sources.map(c => c.url)).join("; "),
      sources: (D.citations[i.public_incident_id] || []).map(c => c.url)
        .filter((v, k, arr) => arr.indexOf(v) === k).join("; "),
    }));
    download(`mining-accident-records-${stamp()}.csv`, toCsv(rows, RECORD_COLUMNS), "text/csv;charset=utf-8");
  });
  document.getElementById("dl-sites").addEventListener("click", () => {
    const rows = sites.filter(siteMatches).map(st => ({
      site: st.name,
      type: typeLabel(st),
      commodity: st.commodity_label || st.commodity_code,
      commodity_group: groupOf(st),
      province: st.province_name || provinceName(st.province_code),
      operators: (st.organizations || []).map(o => `${o.name} (${o.role})`).join("; "),
      operator_countries: (st.organizations || []).map(o => o.country_label).filter(Boolean).join("; "),
      status: statusLabel(st),
      latitude: st.latitude, longitude: st.longitude,
      coordinate_precision: st.coordinate_precision,
      source_url: st.source_url,
    }));
    download(`mining-sites-${stamp()}.csv`, toCsv(rows, SITE_COLUMNS), "text/csv;charset=utf-8");
  });
  document.getElementById("dl-json").addEventListener("click", () => {
    const selectedIncidents = incidents.filter(incidentMatches);
    const selectedIds = new Set(selectedIncidents.map(i => i.public_incident_id));
    const selectedEntries = entries => Object.fromEntries(
      Object.entries(entries || {}).filter(([id]) => selectedIds.has(id)));
    const payload = {
      note: t("dl_note"),
      filters: { province: state.province, mechanism: state.mechanism,
        from: state.from, to: state.to, commodity: state.commodity },
      export_timestamp: D.export_timestamp,
      schema_version: D.schema_version,
      incidents: selectedIncidents, sites: sites.filter(siteMatches),
      evidence_notices: (D.evidence_notices || []).filter(n => selectedIds.has(n.public_incident_id)),
      incident_organizations: selectedEntries(D.incident_organizations),
      citations: selectedEntries(D.citations),
      classifications: selectedEntries(D.classifications),
      // These series describe the full register/sector, independent of filters.
      context: { scope: "full_register_and_sector", aggregates: D.aggregates,
        annual_context: D.annual_context, rate_context: D.rate_context },
    };
    download(`mining-accidents-${stamp()}.json`, JSON.stringify(payload, null, 2), "application/json");
  });

  // Evidence notices never replace a field or participate in an aggregate.
  const noticesOf = id => (D.evidence_notices || []).filter(n => n.public_incident_id === id);
  const noticeText = n => LANG === "tr" ? n.text_tr : n.text_en;
  const evidenceBadge = id => noticesOf(id).length
    ? ` <span class="pill pill-dispute">${t("evidence_pending")}</span>` : "";
  // Folded by default: the note is one click away on its record, and the
  // record itself is what the reader meets first.
  const evidenceNoticesHtml = id => noticesOf(id).map(n =>
    `<details class="d-sec evidence-notice"><summary>${t("evidence_pending")} · ${html(n.checked_at)}</summary>` +
    `<p>${html(noticeText(n))}</p><small>${t("evidence_checked")}: ${html(n.checked_at)}</small> · ` +
    n.sources.map(c => sourceLink(c.url, c.label)).join(" · ") + `</details>`).join("");
  function missingCitationHtml(i) {
    const fields = ["fatalities_current", "incident_start_datetime", "province_code", "injuries_current"]
      .filter(field => i[field] != null && !(D.citations[i.public_incident_id] || []).some(c => c.field_name === field));
    return fields.length ? `<p class="d-sec evidence-notice"><b>${t("evidence_missing")}:</b> ` +
      fields.map(field => html(fieldLabel(field))).join(", ") + `</p>` : "";
  }
  function renderEvidenceNotices() {
    const notes = D.evidence_notices || [];
    const host = document.getElementById("evidence-notices");
    host.hidden = !notes.length;
    if (!notes.length) return;
    host.innerHTML = `<summary>${t("evidence_title")} (${notes.length})</summary>` +
      `<p>${tf("evidence_intro", {n:new Set(notes.map(n => n.public_incident_id)).size})}</p>` +
      notes.map(n => `<article><b>${html(n.public_incident_id)}</b><p>${html(noticeText(n))}</p>` +
        `<small>${t("evidence_checked")}: ${html(n.checked_at)}</small> · ` +
        n.sources.map(c => sourceLink(c.url,c.label)).join(" · ") + `</article>`).join("");
  }

  // ---- Record detail -------------------------------------------------------
  // Sources travel with the values: the panel shows every citation and the
  // assertion status of each classification, per the evidence-flow rule.
  const fieldLabel = field => ({incident_start_datetime:t("rh_date"),province_code:t("rh_prov"),
    fatalities_current:t("rh_people"), latitude:t("d_location"),longitude:t("d_location"),
    injuries_current:t("d_injured"),event_mechanism:t("rh_mech")})[field] || field || t("field_unknown");
  let detailOpener = null;
  function openDetail(id) {
    const i = incidents.find(x => x.public_incident_id === id);
    if (!i) return;
    const cites = (D.citations[id] || []);
    const cls = (D.classifications[id] || []);
    const row = (label, value) => value
      ? `<div class="d-sec"><b>${label}:</b> ${value}</div>` : "";
    const body = document.getElementById("detail-body");
    body.innerHTML =
      `<h3 lang="tr">${html(displayTitle(i))}</h3>` +
      `<p class="d-meta">${html(sentence(i))}</p>` +
      evidenceNoticesHtml(id) + missingCitationHtml(i) +
      row(t("rh_id"), html(i.public_incident_id)) +
      row(t("rh_date"), html(fmtDate(i)) + (i.date_precision
        ? ` <span class="pill">${html(vocab("date_precisions", i.date_precision))}</span>` : "")) +
      row(t("rh_prov"), html(provinceName(i.province_code))) +
      row(t("rh_people"), fmt.format(i.fatalities_current) +
        ` ${casualtyPill(i)}`) +
      row(t("d_injured"), i.injuries_current != null ? fmt.format(i.injuries_current) : t("unknown_value")) +
      row(t("d_location"), i.latitude != null
        ? `${i.latitude.toFixed(4)}, ${i.longitude.toFixed(4)} <span class="pill">` +
          `${html(vocab("coordinate_precisions", i.coordinate_precision))}</span>`
        : t("d_no_coords")) +
      (orgsOf(i.public_incident_id).length
        ? row(t("rh_org"), orgCell(i.public_incident_id) +
            `<br><span class="pill">${t("org_at_date")}</span>`)
        : "") +
      (cls.length ? `<div class="d-sec"><b>${t("d_class")}:</b><ul>` + cls.map(c =>
        `<li>${html(LANG === "tr" ? (c.label_tr || c.label_en) : (c.label_en || c.label_tr))} ` +
        `<span class="pill">${html(statusLabelOf(c.assertion_status))}</span></li>`).join("") + `</ul></div>` : "") +
      (cites.length ? `<div class="d-sec"><b>${t("fields_sources")}</b><ul class="field-citations">` + cites.map(c =>
        `<li><b>${html(fieldLabel(c.field_name))}</b> · ${sourceLink(c.url, `${c.organization}: ${c.title}`)}` +
        `<small>${t("source_tier")}: ${html(c.source_tier || "—")} · ${t("retrieved")}: ${html((c.retrieved_at || "").slice(0,10) || "—")}</small>` +
        (c.short_evidence_excerpt ? `<blockquote lang="tr">${html(c.short_evidence_excerpt)}</blockquote>` : "") + `</li>`
      ).join("") + `</ul></div>` : "") +
      `<div class="d-sec t-meta">${t("d_traceable")}</div>`;
    const el = document.getElementById("detail");
    detailOpener = document.activeElement;
    el.hidden = false;
    el.querySelector("#detail-close").focus();
  }
  function closeDetail() {
    const el = document.getElementById("detail");
    if (el) el.hidden = true;
    if (detailOpener?.isConnected) detailOpener.focus();
  }
  document.getElementById("detail-close").addEventListener("click", closeDetail);
  document.addEventListener("keydown", ev => { if (ev.key === "Escape") closeDetail(); });
  // Delegated from the stable <table>: row bodies are re-rendered constantly.
  document.getElementById("records").addEventListener("click", ev => {
    const tr = ev.target.closest("tr.rec-row");
    if (!tr || ev.target.closest("a")) return;   // let source links work
    openDetail(tr.dataset.id);
  });
  document.getElementById("records").addEventListener("keydown", ev => {
    const tr = ev.target.closest("tr.rec-row");
    if (!tr || ev.target.closest("a") || !["Enter"," "].includes(ev.key)) return;
    ev.preventDefault();
    openDetail(tr.dataset.id);
  });

  // ---- How current the register is --------------------------------------------------
  // The check's own facts, read from the payload so the page cannot claim a
  // freshness it does not have. The source names are names: only Wikipedia has
  // a Turkish title of its own.
  const sourceLabel = key => key === "wikipedia"
    ? (LANG === "tr" ? "Vikipedi" : "Wikipedia")
    : key === "wikidata" ? "Wikidata" : "İSİG Meclisi";

  function freshness() {
    const m = D.monitoring || {};
    const unknown = t("mon_never");
    const failed = (m.failed_sources || []).map(sourceLabel).join(", ");
    return {
      checked: m.last_checked ? String(m.last_checked).slice(0, 10) : unknown,
      attempted: m.last_attempted ? String(m.last_attempted).slice(0, 10) : unknown,
      waiting: m.candidates_waiting == null ? unknown : fmt.format(m.candidates_waiting),
      sources: (m.swept_sources || []).map(sourceLabel).join(", "),
      // Said only when true: a failed attempt, or a sweep that is overdue.
      state: [failed ? tf("mon_failed", { failed }) : "", m.overdue ? t("mon_overdue") : ""]
        .filter(Boolean).join(" "),
      isig: m.isig_latest_month || null,
    };
  }

  function renderFreshness() {
    // applyStatic() has just written the template, placeholders and all.
    const box = document.querySelector('[data-i18n="ab9_d"]');
    if (!box) return;
    const f = freshness();
    box.innerHTML = tf("ab9_d", { checked: f.checked, attempted: f.attempted,
      waiting: f.waiting, state: f.state });
    // What the tolls rest on, and what "reviewed" covers: counted from the
    // payload each time, so the sentences cannot drift from the data.
    const tier = { 1: 0, 2: 0, 3: 0 }, dead = { 1: 0, 2: 0, 3: 0 };
    let passages = 0;
    for (const i of incidents) {
      const c = (D.citations[i.public_incident_id] || []).find(x => x.field_name === "fatalities_current");
      const k = c && tier[c.source_tier] != null ? c.source_tier : 3;
      tier[k] += 1; dead[k] += i.fatalities_current || 0;
      if (c && c.short_evidence_excerpt) passages += 1;
    }
    const src = document.querySelector('[data-i18n="ab2_d"]');
    if (src) src.innerHTML = tf("ab2_d", { n: incidents.length, t1: tier[1], t2: tier[2], t3: tier[3],
      d12: fmt.format(dead[1] + dead[2]), d3: fmt.format(dead[3]),
      deaths: fmt.format(totalDeaths), passages });
    const rev = document.querySelector('[data-i18n="ab10_d"]');
    if (rev) rev.innerHTML = tf("ab10_d", {
      dec: fmt.format(D.pipeline.decisions_total || 0),
      restored: fmt.format(D.pipeline.decisions_restored || 0),
      delegated: fmt.format(D.pipeline.decisions_delegated || 0) });
  }

  // ---- Footer ----------------------------------------------------------------------
  function renderFooter() {
    const f = freshness();
    let stamp = tf("foot3", { checked: f.checked, attempted: f.attempted, sources: f.sources,
      waiting: f.waiting, state: f.state });
    if (f.isig && f.isig.isig_mining_deaths != null) {
      stamp += " " + tf("foot3_isig", {
        isig: fmt.format(f.isig.isig_mining_deaths),
        period: f.isig.period,
        reg: fmt.format(f.isig.register_deaths_published || 0),
      });
    }
    document.getElementById("foot").innerHTML =
      tf("foot1", {
        ts: D.export_timestamp, v: D.schema_version,
        rev: fmt.format(D.pipeline.records_in_review || 0),
        wd: fmt.format(D.pipeline.withdrawn_records || 0),
        docs: fmt.format(D.pipeline.source_documents),
        claims: fmt.format(D.pipeline.claims_total),
        dec: fmt.format(D.pipeline.decisions_total),
      }) + "<br>" + t("foot2") + "<br>" + stamp;
  }

  // ---- boot / re-render -------------------------------------------------------
  function renderAll() {
    applyStatic();
    syncToggles();
    setupCaptions();
    renderOnThisDay();
    buildStory();
    renderTiles();
    renderEvidenceNotices();
    fillSelects();
    renderChart();
    renderMechanisms();
    renderHazards();
    renderEnvironmental();
    renderFreshness();
    renderFooter();
    applyFilters();
  }
  hydrateFromUrl();
  renderAll();
})();
