/* TideStock charts — every ECharts instance is themed from the design tokens
   so nothing ships with library-default styling. */
(function () {
  "use strict";

  const css = getComputedStyle(document.documentElement);
  const T = {
    ink:      css.getPropertyValue("--ink").trim(),
    ink2:     css.getPropertyValue("--ink-2").trim(),
    ink3:     css.getPropertyValue("--ink-3").trim(),
    hairline: css.getPropertyValue("--hairline").trim(),
    hairline2: css.getPropertyValue("--hairline-2").trim(),
    accent:   css.getPropertyValue("--accent").trim(),
    harbor:   css.getPropertyValue("--harbor").trim(),
    sea:      css.getPropertyValue("--sea").trim(),
    amber:    css.getPropertyValue("--amber").trim(),
    olive:    css.getPropertyValue("--olive").trim(),
    paper:    css.getPropertyValue("--paper-raised").trim(),
    mono:     css.getPropertyValue("--font-mono").trim(),
    ui:       css.getPropertyValue("--font-ui").trim(),
  };

  const AXIS = {
    axisLine: { lineStyle: { color: T.hairline2 } },
    axisTick: { show: false },
    axisLabel: { color: T.ink3, fontFamily: T.mono, fontSize: 9.5 },
    splitLine: { lineStyle: { color: T.hairline, type: [2, 3] } },
  };

  const TIP = {
    backgroundColor: T.ink,
    borderWidth: 0,
    textStyle: { color: "#F4F1E9", fontFamily: T.mono, fontSize: 11 },
    padding: [8, 12],
  };

  const instances = new Map();

  function mount(elId, option) {
    const el = document.getElementById(elId);
    if (!el) return null;
    let chart = instances.get(elId);
    if (!chart || chart.isDisposed()) {
      chart = echarts.init(el, null, { renderer: "canvas" });
      instances.set(elId, chart);
    }
    chart.setOption(option, true);
    return chart;
  }

  window.addEventListener("resize", () => {
    instances.forEach((c) => { if (!c.isDisposed()) c.resize(); });
  });

  const STATUS_COLOR = {
    "Critical": T.accent, "Reorder Soon": T.amber, "Watch": T.olive, "Healthy": T.sea,
  };

  /* ── tide: 7-day prediction curve ─────────────────────────────────────── */
  function tideChart(rows) {
    if (!rows.length) return;
    mount("tideChart", {
      grid: { left: 44, right: 16, top: 18, bottom: 28 },
      tooltip: { ...TIP, trigger: "axis",
        formatter: (p) => `${p[0].axisValueLabel}<br/>${Number(p[0].value[1]).toFixed(1)} ft` },
      xAxis: { ...AXIS, type: "time", splitLine: { show: false },
        axisLabel: { ...AXIS.axisLabel, hideOverlap: true, formatter: "{MMM} {d}" } },
      yAxis: { ...AXIS, type: "value", name: "ft", nameTextStyle: { color: T.ink3, fontFamily: T.mono, fontSize: 9 } },
      series: [{
        type: "line",
        smooth: 0.55,
        symbol: "none",
        data: rows.map((r) => [r.time, r.height]),
        lineStyle: { color: T.harbor, width: 1.6 },
        areaStyle: { color: T.harbor, opacity: 0.10 },
      }],
    });
  }

  /* ── barometric pressure with condition bands ─────────────────────────── */
  function pressureChart(rows, trend) {
    if (!rows.length) return;
    const vals = rows.map((r) => r.pressure);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    mount("pressureChart", {
      grid: { left: 52, right: 74, top: 18, bottom: 28 },
      tooltip: { ...TIP, trigger: "axis",
        formatter: (p) => `${p[0].axisValueLabel}<br/>${Number(p[0].value[1]).toFixed(1)} hPa` },
      xAxis: { ...AXIS, type: "time", splitLine: { show: false },
        axisLabel: { ...AXIS.axisLabel, hideOverlap: true, formatter: "{MMM} {d}" } },
      yAxis: { ...AXIS, type: "value", min: Math.floor(Math.min(lo, 1005) - 2), max: Math.ceil(Math.max(hi, 1025) + 2) },
      series: [{
        type: "line",
        symbol: "none",
        data: rows.map((r) => [r.time, r.pressure]),
        lineStyle: { color: T.ink, width: 1.6 },
        markArea: {
          silent: true,
          data: [
            [{ yAxis: 1020, itemStyle: { color: T.sea, opacity: 0.06 },
               label: { show: true, position: "insideRight", formatter: "HIGH — SLOW BITE", color: T.sea, fontFamily: T.mono, fontSize: 8.5 } },
             { yAxis: 1060 }],
            [{ yAxis: 1010, itemStyle: { color: T.olive, opacity: 0.05 },
               label: { show: true, position: "insideRight", formatter: "STABLE", color: T.olive, fontFamily: T.mono, fontSize: 8.5 } },
             { yAxis: 1020 }],
            [{ yAxis: 960, itemStyle: { color: T.accent, opacity: 0.06 },
               label: { show: true, position: "insideRight", formatter: "FALLING — HOT BITE", color: T.accent, fontFamily: T.mono, fontSize: 8.5 } },
             { yAxis: 1010 }],
          ],
        },
      }],
      graphic: [{
        type: "text", right: 8, top: 2,
        style: { text: (trend || "").toUpperCase() + " ▸", fill: T.accent, fontSize: 10, fontWeight: 600, fontFamily: T.mono },
      }],
    });
  }

  /* ── days of supply vs lead time (horizontal bars) ─────────────────────── */
  function dosChart(recs) {
    const rows = recs.filter((r) => r.dos < 999).slice(0, 18).reverse();
    mount("dosChart", {
      grid: { left: 168, right: 42, top: 8, bottom: 26 },
      tooltip: { ...TIP,
        formatter: (p) => {
          const r = rows[p.dataIndex];
          return `${r.product_name}<br/>${r.dos.toFixed(1)}d supply · ${r.lead_time}d lead time`;
        } },
      xAxis: { ...AXIS, type: "value", name: "days" , nameTextStyle: { color: T.ink3, fontFamily: T.mono, fontSize: 9 }},
      yAxis: { ...AXIS, type: "category", splitLine: { show: false },
        data: rows.map((r) => r.product_name.length > 24 ? r.product_name.slice(0, 23) + "…" : r.product_name),
        axisLabel: { color: T.ink2, fontFamily: T.ui, fontSize: 10.5 } },
      series: [{
        type: "bar",
        barWidth: 9,
        data: rows.map((r) => ({
          value: Math.round(r.dos * 10) / 10,
          itemStyle: { color: STATUS_COLOR[r.status] || T.ink3, borderRadius: [0, 1, 1, 0] },
        })),
        markLine: {
          symbol: "none",
          lineStyle: { color: T.ink, type: "solid", width: 1 },
          label: { formatter: "{b}", color: T.ink2, fontFamily: T.mono, fontSize: 8.5, position: "end" },
          data: [
            { xAxis: 5,  name: "LEAD 5d" },
            { xAxis: 10, name: "2× LEAD", lineStyle: { type: [3, 3], color: T.ink3 } },
          ],
        },
      }],
    });
  }

  /* ── revenue at risk ──────────────────────────────────────────────────── */
  function rarChart(recs) {
    const rows = recs.filter((r) => r.rev_risk > 0)
      .sort((a, b) => b.rev_risk - a.rev_risk).slice(0, 10).reverse();
    mount("rarChart", {
      grid: { left: 168, right: 48, top: 8, bottom: 26 },
      tooltip: { ...TIP, formatter: (p) => `${rows[p.dataIndex].product_name}<br/>$${Number(p.value).toFixed(0)} at risk` },
      xAxis: { ...AXIS, type: "value", axisLabel: { ...AXIS.axisLabel, formatter: "${value}" } },
      yAxis: { ...AXIS, type: "category", splitLine: { show: false },
        data: rows.map((r) => r.product_name.length > 24 ? r.product_name.slice(0, 23) + "…" : r.product_name),
        axisLabel: { color: T.ink2, fontFamily: T.ui, fontSize: 10.5 } },
      series: [{
        type: "bar",
        barWidth: 9,
        data: rows.map((r) => ({ value: Math.round(r.rev_risk), itemStyle: { color: T.accent, opacity: 0.85, borderRadius: [0, 1, 1, 0] } })),
        label: { show: true, position: "right", formatter: "${c}", color: T.ink2, fontFamily: T.mono, fontSize: 9.5 },
      }],
    });
  }

  /* ── scenario comparison (base vs adjusted, grouped bars) ─────────────── */
  function scenarioChart(elId, categories, subtitle) {
    mount(elId, {
      grid: { left: 44, right: 16, top: 34, bottom: 46 },
      legend: {
        top: 0, right: 0, itemWidth: 10, itemHeight: 10, icon: "rect",
        textStyle: { color: T.ink2, fontFamily: T.mono, fontSize: 10 },
      },
      tooltip: { ...TIP, trigger: "axis" },
      xAxis: { ...AXIS, type: "category", splitLine: { show: false },
        data: categories.map((c) => c.label),
        axisLabel: { ...AXIS.axisLabel, interval: 0, rotate: 28, fontSize: 9 } },
      yAxis: { ...AXIS, type: "value", name: "units / wk", nameTextStyle: { color: T.ink3, fontFamily: T.mono, fontSize: 9 } },
      series: [
        { name: "BASELINE", type: "bar", barWidth: 12,
          data: categories.map((c) => c.base),
          itemStyle: { color: T.ink3, opacity: 0.45 } },
        { name: (subtitle || "ADJUSTED").toUpperCase(), type: "bar", barWidth: 12,
          data: categories.map((c) => ({
            value: c.adjusted,
            itemStyle: { color: c.adjusted >= c.base ? T.harbor : T.accent },
          })) },
      ],
    });
  }

  /* ── MAPE sparkline bars ──────────────────────────────────────────────── */
  function mapeSpark(elId, perSku) {
    const worst = [...perSku].sort((a, b) => b.mape - a.mape).slice(0, 8).reverse();
    mount(elId, {
      grid: { left: 120, right: 40, top: 4, bottom: 4 },
      tooltip: { ...TIP, formatter: (p) => `${worst[p.dataIndex].sku_key}<br/>MAPE ${p.value}%` },
      xAxis: { ...AXIS, type: "value", show: false },
      yAxis: { type: "category", axisLine: { show: false }, axisTick: { show: false },
        data: worst.map((s) => s.sku_key.replace(/_/g, " ").slice(0, 18)),
        axisLabel: { color: T.ink3, fontFamily: T.mono, fontSize: 8.5 } },
      series: [{
        type: "bar", barWidth: 5,
        data: worst.map((s) => ({ value: s.mape, itemStyle: { color: s.mape > 25 ? T.amber : T.harbor } })),
        label: { show: true, position: "right", formatter: "{c}%", color: T.ink3, fontFamily: T.mono, fontSize: 8.5 },
      }],
    });
  }

  window.TSCharts = { tideChart, pressureChart, dosChart, rarChart, scenarioChart, mapeSpark, tokens: T };
})();
