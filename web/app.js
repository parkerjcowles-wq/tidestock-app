/* TideStock app — fetch, render, interactions.
   Untrusted feed content (Reddit, Exa, LLM output) is ALWAYS rendered via
   textContent / createElement. No innerHTML is ever given external data. */
(function () {
  "use strict";

  const C = window.TSCharts;

  /* ── tiny DOM helpers ─────────────────────────────────────────────────── */
  const $ = (id) => document.getElementById(id);

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  function safeLink(href, text, cls) {
    const a = el("a", cls, text);
    try {
      const u = new URL(href, location.origin);
      if (u.protocol === "http:" || u.protocol === "https:") {
        a.href = u.href; a.target = "_blank"; a.rel = "noopener noreferrer";
      }
    } catch (e) { /* leave as plain text */ }
    return a;
  }

  function replace(node, ...children) {
    node.replaceChildren(...children);
  }

  const money = (v) => "$" + Math.round(v).toLocaleString("en-US");
  const STATUS_CLS = { "Critical": "critical", "Reorder Soon": "reorder", "Watch": "watch", "Healthy": "healthy" };

  function statusBadge(status) {
    return el("span", "badge " + (STATUS_CLS[status] || "neutral"), status);
  }
  function abcBadge(cls) { return el("span", "abc " + cls, cls); }

  async function fetchJSON(url, opts) {
    const r = await fetch(url, opts ? {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(opts),
    } : undefined);
    if (!r.ok) throw new Error(url + " → " + r.status);
    return r.json();
  }

  function errCard(container, label, retryFn) {
    const box = el("div", "err-card");
    box.append(el("span", null, label + " unavailable — upstream feed did not respond."));
    const btn = el("button", "chip", "RETRY");
    btn.addEventListener("click", retryFn);
    box.append(btn);
    replace(container, box);
  }

  /* ── SVG glyphs: moon phases + weather (no emoji anywhere) ───────────── */
  function moonSVG(phase, size) {
    const s = size || 26, r = s / 2 - 1.5, cx = s / 2, cy = s / 2;
    const ink = C.tokens.ink, paper = C.tokens.paper;
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", s); svg.setAttribute("height", s);
    svg.setAttribute("viewBox", `0 0 ${s} ${s}`);
    const base = document.createElementNS(NS, "circle");
    base.setAttribute("cx", cx); base.setAttribute("cy", cy); base.setAttribute("r", r);
    base.setAttribute("fill", paper); base.setAttribute("stroke", ink); base.setAttribute("stroke-width", "1.2");
    svg.append(base);
    // illuminated overlay: two arcs — outer half-circle + terminator ellipse
    const F = { new: 0, waxing_crescent: 0.25, first_quarter: 0.5, waxing_gibbous: 0.75,
                full: 1, waning_gibbous: 0.75, last_quarter: 0.5, waning_crescent: 0.25 };
    const f = F[phase] !== undefined ? F[phase] : 0.5;
    const waxing = phase.startsWith("waxing") || phase === "first_quarter";
    if (f === 1) { base.setAttribute("fill", ink); }
    else if (f > 0) {
      const rx = Math.abs(2 * f - 1) * r;                 // terminator ellipse x-radius
      const sweepOuter = waxing ? 1 : 0;
      const sweepInner = (f > 0.5 ? (waxing ? 1 : 0) : (waxing ? 0 : 1));
      const d = `M ${cx} ${cy - r} A ${r} ${r} 0 0 ${sweepOuter} ${cx} ${cy + r}` +
                ` A ${rx} ${r} 0 0 ${sweepInner} ${cx} ${cy - r} Z`;
      const lit = document.createElementNS(NS, "path");
      lit.setAttribute("d", d); lit.setAttribute("fill", ink);
      svg.append(lit);
    }
    return svg;
  }

  function weatherSVG(emoji, size) {
    const s = size || 22;
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", s); svg.setAttribute("height", s);
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", C.tokens.ink2);
    svg.setAttribute("stroke-width", "1.5");
    svg.setAttribute("stroke-linecap", "round");
    const put = (d) => { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); svg.append(p); };
    const sun = () => {
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", 12); c.setAttribute("cy", 12); c.setAttribute("r", 4);
      c.setAttribute("stroke", C.tokens.amber); svg.append(c);
      put("M12 3v2 M12 19v2 M3 12h2 M19 12h2 M5.6 5.6l1.4 1.4 M17 17l1.4 1.4 M18.4 5.6L17 7 M7 17l-1.4 1.4");
      svg.querySelectorAll("path").forEach((p) => p.setAttribute("stroke", C.tokens.amber));
    };
    const cloud = () => put("M6 15a4 4 0 0 1 .5-7.9A5 5 0 0 1 16 6.5 4 4 0 0 1 17.5 15Z");
    const e = emoji || "";
    if (/[☀🌞]/.test(e)) sun();
    else if (/[🌤⛅🌥]/.test(e)) { sun(); cloud(); }
    else if (/[🌧🌦]/.test(e)) { cloud(); put("M8 18l-1 3 M12 18l-1 3 M16 18l-1 3"); }
    else if (/[⛈🌩]/.test(e)) { cloud(); put("M12 16l-2 4h3l-2 4"); }
    else if (/[🌨❄]/.test(e)) { cloud(); put("M8 19v2 M12 19v2 M16 19v2"); }
    else if (/[🌫]/.test(e)) { put("M4 10h16 M4 14h16 M6 18h12"); }
    else cloud();
    return svg;
  }

  /* ── router ───────────────────────────────────────────────────────────── */
  const TITLES = { command: "Command Center", inventory: "Inventory", signals: "Demand Signals",
                   scenario: "Scenario Simulator", brief: "Dave’s Brief" };
  let briefLoaded = false;

  function route() {
    const view = (location.hash || "#command").slice(1);
    const v = TITLES[view] ? view : "command";
    document.querySelectorAll("section[data-view]").forEach((s) =>
      s.classList.toggle("active", s.dataset.view === v));
    document.querySelectorAll("#nav a").forEach((a) =>
      a.classList.toggle("active", a.dataset.nav === v));
    $("viewTitle").textContent = TITLES[v];
    if (v === "brief" && !briefLoaded) { briefLoaded = true; loadBrief(false); }
    window.dispatchEvent(new Event("resize"));   // charts in newly shown section
  }
  window.addEventListener("hashchange", route);

  /* ── state ────────────────────────────────────────────────────────────── */
  const state = { dash: null, signals: null, feeds: null, abc: "ALL" };

  /* ══ 01 Command Center ═══════════════════════════════════════════════── */
  function renderKPIs(d) {
    const k = d.kpis;
    const row = $("kpiRow");
    const mk = (label, value, sub, opts) => {
      const cell = el("div", "kpi" + (opts && opts.mod ? " " + opts.mod : ""));
      cell.append(el("div", "k-label", label));
      const v = el("div", "k-value" + (opts && opts.tone ? " " + opts.tone : ""), value);
      cell.append(v);
      if (sub) cell.append(el("div", "k-sub", sub));
      return cell;
    };
    replace(row,
      mk("Critical — order today", k.n_critical,
         k.n_critical ? "SKUs below reorder point" : "all above reorder point",
         { tone: k.n_critical ? "k-red" : "k-green", mod: k.n_critical ? "alert" : "" }),
      mk("Revenue at risk", money(k.total_rev_risk), "critical + reorder SKUs",
         { tone: k.total_rev_risk > 200 ? "k-red" : k.total_rev_risk > 0 ? "k-amber" : "k-green",
           mod: k.total_rev_risk > 200 ? "alert" : "" }),
      mk("Reorder soon", k.n_reorder, "this week", { tone: k.n_reorder ? "k-amber" : "", mod: k.n_reorder ? "warn" : "" }),
      mk("Avg days of supply", k.avg_dos.toFixed(0) + "d", "vs " + k.avg_lead_time.toFixed(0) + "d avg lead time"),
      mk("Fishing score", k.fishing_score + "/100",
         d.month + " · env + social", { tone: k.fishing_score >= 80 ? "k-green" : k.fishing_score >= 60 ? "k-amber" : "" }),
      mk("SKUs tracked", k.n_total, k.n_categories + " categories"));
    $("metaTimes").textContent = `env ${d.as_of} · social ${d.social_as_of}`;
    $("metaDate").textContent = d.today.toUpperCase();
    $("railSkus").textContent = k.n_total;
  }

  function renderBuyer(d) {
    replace($("buyerSummary"), el("div", null, d.buyer_summary));
  }

  function renderMape(d) {
    const fa = d.forecast_accuracy;
    const wrap = $("mapeCard");
    const head = el("div");
    head.style.display = "flex"; head.style.alignItems = "baseline"; head.style.gap = "14px";
    const big = el("span", null, fa.portfolio_mape + "%");
    big.style.cssText = "font-family:var(--font-display);font-size:34px;font-weight:800;letter-spacing:-0.03em";
    head.append(big, el("span", "dim", "portfolio WAPE · " + fa.weeks + "-week window"));
    head.lastChild.style.cssText = "font-family:var(--font-mono);font-size:10px;color:var(--ink-3)";
    const method = el("div", null, fa.method);
    method.style.cssText = "font-family:var(--font-mono);font-size:9.5px;color:var(--ink-3);margin:4px 0 10px";
    const spark = el("div"); spark.id = "mapeSpark"; spark.className = "chart"; spark.style.height = "150px";
    replace(wrap, head, method, spark);
    C.mapeSpark("mapeSpark", fa.per_sku);
  }

  function renderCatchIntel(feeds) {
    const posts = (feeds.reddit_regional || []).filter((p) => p.sentiment === "catching" && (p.bait_mentions || []).length).slice(0, 3);
    const box = $("catchIntel");
    if (!posts.length) { replace(box, el("div", "err-card", "No catch reports with bait mentions in the current window.")); return; }
    replace(box, ...posts.map(feedCard));
  }

  function renderInvTable(d) {
    const tbl = el("table", "tbl");
    const thead = el("thead"); const hr = el("tr");
    ["Product", "Category", "ABC", "Status", "On hand", "DoS", "Stockout", "Urgency"].forEach((h, i) => {
      const th = el("th", i >= 4 ? "right" : null, h); hr.append(th);
    });
    thead.append(hr); tbl.append(thead);
    const tb = el("tbody");
    d.recs.forEach((r) => {
      const tr = el("tr");
      tr.append(el("td", "prod", r.product_name));
      tr.append(el("td", "dim", r.category_label));
      const abcTd = el("td"); abcTd.append(abcBadge(r.abc_class)); tr.append(abcTd);
      const st = el("td"); st.append(statusBadge(r.status)); tr.append(st);
      tr.append(el("td", "num right", r.on_hand + " " + r.unit));
      tr.append(el("td", "num right", r.dos >= 999 ? "—" : r.dos.toFixed(0) + "d"));
      tr.append(el("td", "num right", Math.round(r.stockout_prob * 100) + "%"));
      tr.append(el("td", "num right", r.urgency));
      tb.append(tr);
    });
    tbl.append(tb);
    const pad = el("div", "panel-pad"); pad.style.padding = "6px 8px"; pad.append(tbl);
    replace($("invTableWrap"), pad);
  }

  /* ══ 02 Inventory ═══════════════════════════════════════════════════── */
  function renderPolicy(d) {
    const pct = Math.round(d.service_pct * 100);
    const z = d.recs[0] ? d.recs[0].service_z : 1.645;
    $("policyNote").textContent = pct + "% service level · z = " + z;
    const tbl = el("table", "tbl");
    const hr = el("tr");
    ["Product", "Safety stock", "ROP", "Lead time"].forEach((h, i) => hr.append(el("th", i ? "right" : null, h)));
    const thead = el("thead"); thead.append(hr); tbl.append(thead);
    const tb = el("tbody");
    [...d.recs].sort((a, b) => b.safety_stock - a.safety_stock).slice(0, 9).forEach((r) => {
      const tr = el("tr");
      tr.append(el("td", "prod", r.product_name));
      tr.append(el("td", "num right", r.safety_stock.toFixed(1)));
      tr.append(el("td", "num right", r.rop.toFixed(0)));
      tr.append(el("td", "num right", r.lead_time + "d"));
      tb.append(tr);
    });
    tbl.append(tb);
    const pad = el("div", "panel-pad"); pad.style.padding = "6px 8px"; pad.append(tbl);
    replace($("policyPanel"), pad);
  }

  function renderReorderCards(d) {
    const flagged = d.recs.filter((r) =>
      (r.status === "Critical" || r.status === "Reorder Soon") &&
      (state.abc === "ALL" || r.abc_class === state.abc));
    const grid = $("reorderCards");
    if (!flagged.length) {
      replace(grid, el("div", "err-card", state.abc === "ALL"
        ? "Nothing flagged — every SKU is above its reorder threshold."
        : "No flagged SKUs in class " + state.abc + "."));
      return;
    }
    replace(grid, ...flagged.map((r) => {
      const card = el("div", "rcard " + (STATUS_CLS[r.status] || ""));
      const top = el("div", "r-top");
      const left = el("div");
      left.append(el("div", "r-name", r.product_name));
      left.append(el("div", "r-brand", r.brand + " · " + r.category_label.toUpperCase()));
      const right = el("div"); right.style.cssText = "display:flex;gap:6px;align-items:center";
      right.append(abcBadge(r.abc_class), statusBadge(r.status));
      top.append(left, right); card.append(top);
      const nums = el("div", "r-nums");
      [["ORDER", r.order_qty + " " + r.unit], ["ON HAND", r.on_hand], ["DOS", r.dos >= 999 ? "—" : r.dos.toFixed(0) + "d"],
       ["MODEL", r.order_model.toUpperCase()], ["CONF", r.confidence.toUpperCase()]].forEach(([k, v]) => {
        const cell = el("div", null, k); cell.append(el("b", null, v)); nums.append(cell);
      });
      card.append(nums);
      const why = el("div", "r-why");
      why.append(el("span", "lede", "Math"), el("span", null, r.reasons.calc));
      why.append(el("span", "lede", "Demand"), el("span", null, r.reasons.demand));
      why.append(el("span", "lede", "Business"), el("span", null, r.reasons.business));
      card.append(why);
      return card;
    }));
  }

  function wireABC() {
    $("abcFilter").addEventListener("click", (e) => {
      const btn = e.target.closest(".chip"); if (!btn) return;
      state.abc = btn.dataset.abc;
      document.querySelectorAll("#abcFilter .chip").forEach((c) => c.classList.toggle("on", c === btn));
      if (state.dash) renderReorderCards(state.dash);
    });
  }

  function wirePO() {
    $("poBtn").addEventListener("click", async () => {
      const btn = $("poBtn");
      btn.disabled = true; btn.textContent = "Building…";
      try {
        const po = await fetchJSON("/api/po-draft");
        renderPO(po);
      } catch (e) {
        errCard($("poSheet"), "PO draft", () => $("poBtn").click());
      }
      btn.disabled = false; btn.textContent = "Build draft PO";
    });
  }

  function renderPO(po) {
    const wrap = $("poSheet");
    if (!po.groups.length) {
      replace(wrap, el("div", "err-card", "Nothing to order — no Critical or Reorder Soon SKUs right now."));
      return;
    }
    const sheet = el("div", "po-sheet");
    const head = el("div", "po-head");
    const t = el("div");
    t.append(el("div", "po-title", "DRAFT PO — DAVE’S BAIT & TACKLE"));
    t.append(el("div", "po-meta", po.generated_at + " · " + po.line_count + " lines · draft only, nothing is sent"));
    head.append(t);
    const copyBtn = el("button", "btn ghost", "Copy as text");
    head.append(copyBtn);
    sheet.append(head);

    const lines = [];
    lines.push("DRAFT PURCHASE ORDER — Dave's Bait & Tackle — " + po.generated_at);
    po.groups.forEach((g) => {
      sheet.append(el("div", "po-cat", g.category));
      lines.push("", g.category.toUpperCase());
      const tbl = el("table", "tbl");
      const hr = el("tr");
      ["Product", "Supplier", "Model", "Qty", "Unit cost", "Line"].forEach((h, i) => hr.append(el("th", i >= 3 ? "right" : null, h)));
      const thead = el("thead"); thead.append(hr); tbl.append(thead);
      const tb = el("tbody");
      g.lines.forEach((l) => {
        const tr = el("tr");
        tr.append(el("td", "prod", l.product_name));
        tr.append(el("td", "dim", l.supplier));
        tr.append(el("td", "dim", l.order_model.toUpperCase()));
        tr.append(el("td", "num right", l.order_qty + " " + l.unit));
        tr.append(el("td", "num right", "$" + l.unit_cost.toFixed(2)));
        tr.append(el("td", "num right", "$" + l.line_cost.toFixed(2)));
        tb.append(tr);
        lines.push(`  ${l.product_name} — ${l.order_qty} ${l.unit} @ $${l.unit_cost.toFixed(2)} = $${l.line_cost.toFixed(2)} (${l.supplier})`);
      });
      tbl.append(tb);
      const pad = el("div"); pad.style.padding = "2px 8px 10px"; pad.append(tbl);
      sheet.append(pad);
      lines.push(`  Subtotal: $${g.subtotal.toFixed(2)}`);
    });
    const foot = el("div", "po-foot");
    foot.append(el("span", null, po.total_units + " units across " + po.groups.length + " categories"));
    foot.append(el("span", "total", "$" + po.total_cost.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })));
    sheet.append(foot);
    lines.push("", `TOTAL: $${po.total_cost.toFixed(2)} — ${po.total_units} units`);

    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(lines.join("\n"));
        copyBtn.textContent = "Copied ✓";
        setTimeout(() => { copyBtn.textContent = "Copy as text"; }, 1800);
      } catch (e) { copyBtn.textContent = "Copy failed"; }
    });
    replace(wrap, sheet);
  }

  /* ══ 03 Demand Signals ══════════════════════════════════════════════── */
  function renderSignals(s) {
    // strip
    const mk = (label, value, sub, tone) => {
      const cell = el("div", "sig");
      cell.append(el("div", "s-label", label));
      const v = el("div", "s-value", value);
      if (tone) v.style.color = tone;
      cell.append(v);
      if (sub) cell.append(el("div", "s-sub", sub));
      return cell;
    };
    const moonCell = el("div", "sig");
    moonCell.append(el("div", "s-label", "Moon phase"));
    const mv = el("div", "s-value");
    mv.append(moonSVG(s.moon_phase, 18), el("span", null, s.moon_phase.replace(/_/g, " ")));
    moonCell.append(mv);
    const tideTone = { prime: C.tokens.sea, moderate: C.tokens.amber, poor: C.tokens.accent }[s.tide_quality];
    const presTone = { rising: C.tokens.sea, stable: C.tokens.amber, falling: C.tokens.accent }[s.pressure_trend];
    replace($("signalStrip"),
      moonCell,
      mk("Tide quality", s.tide_quality, null, tideTone),
      mk("Water temp", s.water_temp.toFixed(1) + "°F", null,
         s.water_temp >= 55 && s.water_temp <= 68 ? C.tokens.sea : null),
      mk("Pressure", s.pressure_trend, null, presTone),
      mk("Air / wind", Math.round(s.current_temp_f) + "°F · " + Math.round(s.current_wind_mph) + " mph"),
      mk("Fishing score", s.fishing_score + "/100",
         s.social_boost > 0 ? "+" + s.social_boost + " social" : null,
         s.fishing_score >= 80 ? C.tokens.sea : s.fishing_score >= 60 ? C.tokens.amber : null));

    C.tideChart(s.tide);
    C.pressureChart(s.pressure, s.pressure_trend);

    // moon strip
    replace($("moonStrip"), ...s.moon.map((m) => {
      const day = el("div", "moon-day");
      day.append(el("div", "m-dow", m.dow));
      day.append(moonSVG(m.phase, 26));
      day.append(el("div", "m-phase", m.phase.replace(/_/g, " ") + " · " + m.score));
      return day;
    }));

    // species
    $("speciesTitle").textContent = "Species Activity";
    replace($("speciesRow"), ...Object.entries(s.species).map(([name, level]) => {
      const card = el("div", "sp-card");
      card.append(el("div", "sp-name", name));
      const lv = el("div", "sp-level", level);
      lv.style.color = s.species_colors[level] || C.tokens.ink3;
      // remap the original dark-theme greens onto ledger tones
      const remap = { Peak: C.tokens.sea, Good: C.tokens.harbor, Fair: C.tokens.amber, Low: C.tokens.accent, Inactive: C.tokens.ink3 };
      if (remap[level]) lv.style.color = remap[level];
      card.append(lv);
      return card;
    }));

    // forecast strip
    if (s.forecast && s.forecast.length) {
      replace($("fcStrip"), ...s.forecast.map((d) => {
        const day = el("div", "fc-day" + (d.is_weekend ? " weekend" : ""));
        day.append(el("div", "fc-dow", d.dow));
        day.append(weatherSVG(d.emoji, 20));
        day.append(el("div", "fc-temp", Math.round(d.temp_max) + "°"));
        day.append(el("div", "fc-precip", Math.round(d.precip_pct) + "%"));
        return day;
      }));
      const pct = (s.weather_mult - 1) * 100;
      $("weatherImpact").textContent =
        "WEATHER DEMAND IMPACT: " + (pct >= 0 ? "+" : "") + pct.toFixed(0) + "% ACROSS SEASONAL SKUS";
    } else {
      replace($("fcStrip"), el("div", "err-card", "Forecast unavailable."));
    }

    // tournaments
    const tWrap = $("tournaments");
    if (s.tournaments && s.tournaments.length) {
      const list = el("div", "panel-pad");
      s.tournaments.forEach((t) => {
        const row = el("div");
        row.style.cssText = "display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px dashed var(--hairline)";
        row.append(safeLink(t.url, t.title));
        row.append(el("span", "dim", (t.proximity || "").replace(/_/g, " ")));
        row.lastChild.style.cssText = "font-family:var(--font-mono);font-size:10px;flex-shrink:0";
        list.append(row);
      });
      list.lastChild.style.borderBottom = "none";
      replace(tWrap, list);
    } else {
      replace(tWrap, el("div", "err-card", "No tournaments found within 30 days."));
    }
  }

  /* feeds */
  function feedCard(p) {
    const card = el("div", "feed-card");
    const src = el("div", "f-src");
    const av = el("span", "avatar", p.initials || "?");
    av.style.background = p.avatar_color || C.tokens.ink3;
    src.append(av, el("span", "src-tag", "r/" + (p.subreddit || "fishing")), el("span", null, p.time_ago || ""));
    card.append(src);
    const title = el("div", "f-title"); title.append(safeLink(p.url, p.title)); card.append(title);
    if (p.body) card.append(el("div", "f-snippet", p.body));
    const meta = el("div", "f-meta");
    meta.append(el("span", null, "▲ " + p.upvotes), el("span", null, p.comments + " comments"));
    if (p.sentiment === "catching") meta.append(el("span", "catching", "CATCHING"));
    (p.bait_mentions || []).slice(0, 3).forEach((b) => meta.append(el("span", "bait", b.toUpperCase())));
    card.append(meta);
    return card;
  }

  function webCard(r) {
    const card = el("div", "feed-card");
    const src = el("div", "f-src");
    const tag = el("span", "src-tag", r.source_label || r.domain || "web");
    src.append(tag, el("span", null, r.time_ago || ""));
    card.append(src);
    const title = el("div", "f-title"); title.append(safeLink(r.url, r.title)); card.append(title);
    if (r.snippet) card.append(el("div", "f-snippet", r.snippet));
    return card;
  }

  function renderFeeds(f) {
    const wr = $("webReports");
    replace(wr, ...(f.web_reports.length ? f.web_reports.slice(0, 6).map(webCard)
      : [el("div", "err-card", "No web reports in the last 14 days.")]));
    const loc = $("redditLocal");
    const localCards = f.reddit_local.slice(0, 5).map(feedCard);
    replace(loc, ...(localCards.length ? localCards : [el("div", "err-card", "No local posts this month.")]));
    localCards.forEach((c) => { c.style.marginBottom = "10px"; });
    $("redditRegTitle").textContent = "Regional Chatter — " + f.velocity.toUpperCase() + " velocity";
    const reg = $("redditRegional");
    const regCards = f.reddit_regional.slice(0, 5).map(feedCard);
    replace(reg, ...(regCards.length ? regCards : [el("div", "err-card", "No regional posts.")]));
    regCards.forEach((c) => { c.style.marginBottom = "10px"; });
  }

  /* ══ 04 Scenario ════════════════════════════════════════════════════── */
  const PRESETS = [
    ["tournament_weekend", "Tournament This Weekend", "Local tournament drives finesse tackle and soft plastic demand up sharply."],
    ["viral_bait_moment", "Viral Bait Moment", "A bait goes viral — soft plastic demand 3× baseline."],
    ["cold_front", "Cold Front Incoming", "Cold front suppresses activity — bait and soft plastics drop 30–40%."],
    ["striper_run_peak", "Striper Run Peak", "Striper migration peak — paddle tails and bucktails in high demand."],
    ["tourist_season", "Tourist Season", "Summer tourists — accessories and hard baits spike 40–60%."],
    ["supplier_delay", "Supplier Delay", "Key supplier running 3+ days late — models urgency under extended lead times."],
  ];

  let weightsTimer = null;
  function currentWeights() {
    const w = {};
    document.querySelectorAll("#sliderBox input[type=range]").forEach((r) => { w[r.dataset.w] = parseFloat(r.value); });
    return w;
  }

  async function runWeights() {
    try {
      const body = { mode: "weights", weights: currentWeights(), weekend_boost: $("weekendBoost").checked };
      const res = await fetchJSON("/api/scenario", body);
      const s = res.summary;
      const banner = $("weightsBanner");
      const dirWord = s.demand_index > 1.1 ? "above" : s.demand_index < 0.9 ? "below" : "near";
      replace(banner, el("b", null, "Demand Index " + s.demand_index.toFixed(2) + "×"),
        el("span", null, " baseline — " + dirWord + " normal · "),
        el("span", s.total_shift_pct >= 0 ? "up" : "down",
           (s.total_shift_pct >= 0 ? "+" : "") + s.total_shift_pct.toFixed(0) + "% total"));
      C.scenarioChart("weightsChart", res.categories, "weighted");
    } catch (e) {
      replace($("weightsBanner"), el("span", null, "Scenario engine unavailable — retrying on next change."));
    }
  }

  function wireScenario() {
    document.querySelectorAll("#sliderBox input[type=range]").forEach((r) => {
      r.addEventListener("input", () => {
        r.closest(".slider-row").querySelector(".sval").textContent = parseFloat(r.value).toFixed(1);
        clearTimeout(weightsTimer); weightsTimer = setTimeout(runWeights, 280);
      });
    });
    $("weekendBoost").addEventListener("change", runWeights);

    const grid = $("presetGrid");
    PRESETS.forEach(([key, name, desc]) => {
      const b = el("button", "preset");
      b.dataset.key = key;
      b.append(el("div", "p-name", name), el("div", "p-desc", desc));
      b.addEventListener("click", () => runPreset(key, b));
      grid.append(b);
    });
  }

  async function runPreset(key, btn) {
    document.querySelectorAll(".preset").forEach((p) => p.classList.toggle("on", p === btn));
    const out = $("presetResult");
    const load = el("div", "err-card"); load.append(el("span", "spin"), el("span", null, " running scenario…"));
    replace(out, load);
    try {
      const res = await fetchJSON("/api/scenario", { mode: "preset", preset: key });
      const s = res.summary;
      const banner = el("div", "scen-banner");
      banner.append(el("b", null, s.label), el("span", null, " · "));
      banner.append(el("span", s.total_shift_pct >= 0 ? "up" : "down",
        (s.total_shift_pct >= 0 ? "+" : "") + s.total_shift_pct.toFixed(0) + "% total demand shift"));
      banner.append(el("span", null, " · " + s.description));
      if (s.lead_time_extra) {
        banner.append(el("div", "dim", "Demand unchanged — the risk is cover time. Status below reflects a +" +
          s.lead_time_extra + "d lead-time extension. " + s.n_changed + " SKUs flip status."));
        banner.lastChild.style.cssText = "font-size:11px;margin-top:4px;color:var(--amber)";
      }
      const pieces = [banner];

      if (!s.lead_time_extra) {
        const panel = el("div", "panel");
        const pad = el("div", "panel-pad");
        const chartDiv = el("div"); chartDiv.id = "presetChart"; chartDiv.className = "chart h300";
        pad.append(chartDiv); panel.append(pad); pieces.push(panel);
      }

      const head = el("div", "sec-head");
      head.append(el("div", "overline", "IMPACT"), el("h3", null, "SKU Status Under This Scenario"));
      pieces.push(head);
      const tbl = el("table", "tbl");
      const hr = el("tr");
      ["Product", "Category", "Baseline", "Scenario", s.lead_time_extra ? "Lead time" : "Δ demand/wk", "Changed"].forEach((h) => hr.append(el("th", null, h)));
      const thead = el("thead"); thead.append(hr); tbl.append(thead);
      const tb = el("tbody");
      const rows = [...res.sku_table].sort((a, b) => Number(b.changed) - Number(a.changed));
      rows.forEach((r) => {
        const tr = el("tr");
        if (r.changed) tr.style.background = "var(--accent-soft)";
        tr.append(el("td", "prod", r.product_name));
        tr.append(el("td", "dim", r.category_label));
        const b1 = el("td"); b1.append(statusBadge(r.baseline_status)); tr.append(b1);
        const b2 = el("td"); b2.append(statusBadge(r.scenario_status)); tr.append(b2);
        tr.append(el("td", "num", s.lead_time_extra ? "+" + s.lead_time_extra + "d"
          : (r.demand_delta >= 0 ? "+" : "") + r.demand_delta.toFixed(0)));
        tr.append(el("td", "num", r.changed ? "YES" : ""));
        tb.append(tr);
      });
      tbl.append(tb);
      const panel2 = el("div", "panel"); const pad2 = el("div"); pad2.style.padding = "6px 8px";
      pad2.append(tbl); panel2.append(pad2); pieces.push(panel2);

      replace(out, ...pieces);
      if (!s.lead_time_extra) C.scenarioChart("presetChart", res.categories, s.label);
    } catch (e) {
      errCard(out, "Scenario", () => runPreset(key, btn));
    }
  }

  /* ══ 05 Dave ════════════════════════════════════════════════════════── */
  function renderBriefText(text) {
    const body = $("briefBody");
    const nodes = [];
    text.split("\n").forEach((line) => {
      line = line.replace(/\r/g, "");
      if (line.startsWith("## ")) { nodes.push(el("h4", null, line.slice(3).trim())); return; }
      if (line.trim() === "" || line.trim() === "---") return;
      const isBullet = line.startsWith("• ") || line.startsWith("- ") || line.startsWith("* ");
      const content = isBullet ? line.slice(2).trim() : line.trim();
      const holder = isBullet ? el("div", "bullet") : el("p");
      if (isBullet) holder.append(el("span", "tick", "—"));
      const span = el("span");
      // **bold** → <strong>, built via text nodes only (no HTML injection possible)
      content.split(/(\*\*[^*]+\*\*)/).forEach((part) => {
        if (part.startsWith("**") && part.endsWith("**")) span.append(el("strong", null, part.slice(2, -2)));
        else if (part) span.append(document.createTextNode(part));
      });
      holder.append(span);
      nodes.push(holder);
    });
    replace(body, ...nodes);
  }

  async function loadBrief(refresh) {
    const body = $("briefBody");
    const sk = el("div", "skeleton"); sk.style.height = "180px";
    replace(body, sk);
    $("briefTime").textContent = "GENERATING…";
    try {
      const b = await fetchJSON("/api/brief", { refresh: !!refresh });
      renderBriefText(b.text);
      $("briefTime").textContent = "GENERATED " + b.generated_at.toUpperCase();
      $("briefSource").textContent = b.source === "groq" ? "POWERED BY GROQ · LLAMA 3" : "RULE-BASED FALLBACK — AI OFFLINE";
      const badges = $("daveBadges");
      replace(badges,
        el("span", "badge neutral", b.badges.moon),
        el("span", "badge neutral", b.badges.water_temp + "°F water"),
        el("span", "badge neutral", b.badges.pressure + " pressure"),
        el("span", "badge " + (b.badges.fishing_score >= 70 ? "healthy" : "watch"), "Fishing " + b.badges.fishing_score + "/100"),
        el("span", "badge neutral", "Social: " + b.badges.social));
    } catch (e) {
      errCard(body, "Dave's brief", () => loadBrief(true));
      $("briefTime").textContent = "FAILED";
    }
  }

  function wireDave() {
    $("briefRefresh").addEventListener("click", () => loadBrief(true));
    const send = async () => {
      const q = $("askInput").value.trim();
      if (!q) return;
      $("askInput").value = "";
      const item = el("div", "ask-item");
      item.append(el("div", "q", q));
      const a = el("div", "a");
      a.append(el("span", "spin"));
      item.append(a);
      $("askThread").prepend(item);
      try {
        const res = await fetchJSON("/api/ask", { question: q });
        replace(a, el("span", null, res.text));
        if (res.source !== "groq") a.append(el("div", "dim", "rule-based fallback — AI offline"));
      } catch (e) {
        replace(a, el("span", "dim", "Dave couldn't answer — request failed."));
      }
    };
    $("askBtn").addEventListener("click", send);
    $("askInput").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  }

  /* ── boot ─────────────────────────────────────────────────────────────── */
  async function loadDashboard() {
    try {
      const d = await fetchJSON("/api/dashboard");
      state.dash = d;
      renderKPIs(d); renderBuyer(d); renderMape(d); renderInvTable(d);
      renderPolicy(d); renderReorderCards(d);
      C.dosChart(d.recs); C.rarChart(d.recs);
    } catch (e) {
      errCard($("kpiRow"), "Dashboard", loadDashboard);
    }
  }

  async function loadSignals() {
    try {
      const s = await fetchJSON("/api/signals");
      state.signals = s;
      renderSignals(s);
    } catch (e) {
      errCard($("signalStrip"), "Signals", loadSignals);
    }
  }

  async function loadFeeds() {
    try {
      const f = await fetchJSON("/api/feeds");
      state.feeds = f;
      renderFeeds(f); renderCatchIntel(f);
    } catch (e) {
      errCard($("webReports"), "Feeds", loadFeeds);
    }
  }

  wireABC(); wirePO(); wireScenario(); wireDave();
  route();
  loadDashboard(); loadSignals(); loadFeeds(); runWeights();
})();
