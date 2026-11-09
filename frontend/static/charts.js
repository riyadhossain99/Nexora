(function () {
  const NS = "http://www.w3.org/2000/svg";
  const FALLBACK_PALETTE = ["#e1f3fe", "#fbf3db", "#edf3ec", "#f0eef9", "#fdebec", "#e8e7e3"];
  function palette() {
    const css = getComputedStyle(document.documentElement);
    return FALLBACK_PALETTE.map((fb, i) => css.getPropertyValue("--chart-" + (i + 1)).trim() || fb);
  }
  const esc = (v) =>
    String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));

  function el(tag, attrs, text) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value));
    if (text != null) node.textContent = text;
    return node;
  }

  function empty(host, message) {
    host.innerHTML = `<p class="muted">${esc(message)}</p>`;
  }

  function donut(host, data) {
    if (!host) return;
    host.innerHTML = "";
    data = (data || []).filter((d) => Number(d.value) > 0);
    const total = data.reduce((sum, d) => sum + Number(d.value), 0);
    if (!total) return empty(host, "No sales yet.");
    const size = 156;
    const r = 56;
    const cx = size / 2;
    const cy = size / 2;
    const width = 24;
    const C = 2 * Math.PI * r;
    const P = palette();
    const svg = el("svg", { viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: "img" });
    svg.appendChild(el("title", {}, `Units sold by product, ${total} total`));
    let offset = 0;
    data.forEach((d, i) => {
      const len = (Number(d.value) / total) * C;
      svg.appendChild(
        el("circle", {
          cx,
          cy,
          r,
          fill: "none",
          stroke: P[i % P.length],
          "stroke-width": width,
          "stroke-dasharray": `${len} ${C - len}`,
          "stroke-dashoffset": -offset,
          transform: `rotate(-90 ${cx} ${cy})`,
        }),
      );
      offset += len;
    });
    svg.appendChild(el("circle", { cx, cy, r: r - width / 2, style: "fill: var(--surface)" }));
    svg.appendChild(
      el(
        "text",
        { x: cx, y: cy + 1, "text-anchor": "middle", "font-size": "22", style: "fill: var(--ink); font-family: var(--font-serif)" },
        total,
      ),
    );
    svg.appendChild(
      el(
        "text",
        { x: cx, y: cy + 18, "text-anchor": "middle", "font-size": "9", "letter-spacing": "0.08em", style: "fill: var(--muted)" },
        "UNITS",
      ),
    );
    const wrap = document.createElement("div");
    wrap.className = "donut-wrap";
    wrap.appendChild(svg);
    const legend = document.createElement("ul");
    legend.className = "legend";
    data.forEach((d, i) => {
      const li = document.createElement("li");
      li.innerHTML = `<i style="background:${P[i % P.length]}"></i><span>${esc(d.label)}</span><b>${esc(d.value)}</b>`;
      legend.appendChild(li);
    });
    wrap.appendChild(legend);
    host.appendChild(wrap);
  }

  function bars(host, data, format) {
    if (!host) return;
    host.innerHTML = "";
    data = (data || []).filter((d) => Number(d.value) > 0);
    if (!data.length) return empty(host, "Nothing to chart yet.");
    const max = Math.max(...data.map((d) => Number(d.value)));
    const P = palette();
    const wrap = document.createElement("div");
    wrap.className = "bars";
    data.forEach((d, i) => {
      const row = document.createElement("div");
      row.className = "bar-row";
      const pct = Math.max(2, Math.round((Number(d.value) / max) * 100));
      row.innerHTML =
        `<span class="bar-label">${esc(d.label)}</span>` +
        `<span class="bar-track"><i style="width:${pct}%;background:${P[i % P.length]}"></i></span>` +
        `<b>${esc(format ? format(d.value) : d.value)}</b>`;
      wrap.appendChild(row);
    });
    host.appendChild(wrap);
  }

  window.NexoraCharts = { donut, bars };
})();
