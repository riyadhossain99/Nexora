(function () {
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (v) =>
    String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  const money = (v) => Number(v || 0).toFixed(2);
  const csrf = () => ($('meta[name="csrf-token"]') || {}).content || "";

  const toasts = document.createElement("div");
  toasts.className = "toasts";
  toasts.setAttribute("aria-live", "polite");
  document.body.appendChild(toasts);

  function toast(message, kind) {
    if (!message) return;
    const el = document.createElement("div");
    el.className = "toast" + (kind ? " " + kind : "");
    el.textContent = message;
    toasts.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  const emptyState = (title, hint) =>
    `<div class="empty"><b>${esc(title)}</b><span>${esc(hint)}</span></div>`;

  async function api(url, body) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify(body || {}),
      });
      if (res.redirected && res.url.includes("/login/")) {
        return { error: "Your session expired. Please sign in again." };
      }
      const data = await res.json();
      return res.ok ? data : { error: data.error || `Request failed (${res.status}).` };
    } catch (e) {
      return { error: "Could not complete the request. Check the connection and try again." };
    }
  }

  const loadedOnce = new Set();
  const skeleton = () => '<div class="skel"><i></i><i></i><i></i></div>';

  async function loadWidgets() {
    const els = $$("[data-widget]");
    const keys = [...new Set(els.map((el) => el.dataset.widget))];
    if (!keys.length) return;
    els.forEach((el) => {
      if (!loadedOnce.has(el)) el.innerHTML = skeleton();
    });
    let data = {};
    try {
      const res = await fetch("/api/dashboard/?widgets=" + keys.join(","));
      if (!res.ok || res.redirected) throw new Error("Dashboard unavailable");
      data = (await res.json()).widgets || {};
    } catch (e) {
      els.forEach((el) => {
        el.innerHTML = emptyState("Could not load data", "Check that the server is running, then refresh.");
      });
      toast("Could not refresh the dashboard. Try refreshing the page.", "err");
      return;
    }
    els.forEach((el) => {
      loadedOnce.add(el);
      const fn = RENDERERS[el.dataset.widget];
      if (fn) fn(el, data[el.dataset.widget]);
    });
  }

  const productsById = new Map();
  let threadsCache = [];

  function ordersTable(rows, mode) {
    return (
      '<div class="table-wrap"><table><thead><tr>' +
      '<th>#</th>' +
      '<th>Customer</th>' +
      '<th>Product &amp; SKU</th>' +
      '<th>Total</th>' +
      '<th>Status</th>' +
      '<th>Created</th>' +
      '<th></th>' +
      '</tr></thead><tbody>' +
      rows
        .map((o) => {
          const items = (o.items || [])
            .map((i) => {
              const pName = esc(i.product || "Product");
              const skuCode = i.sku ? `<span class="sku-badge">${esc(i.sku)}</span>` : "";
              const noteHtml = i.notes ? `<div class="order-item-note">${esc(i.notes)}</div>` : "";
              return `<div class="order-item-row"><span class="order-item-name">${esc(i.qty || 1)}x ${pName}</span> ${skuCode}${noteHtml}</div>`;
            })
            .join("");

          const custHtml =
            '<div class="order-cust">' +
            `<strong class="order-cust-name">${esc(o.customer_name || "Customer")}</strong>` +
            `<div class="order-cust-phone">${esc(o.customer_phone || "-")}</div>` +
            (o.address ? `<div class="order-cust-addr" title="${esc(o.address)}">${esc(o.address)}</div>` : "") +
            '</div>';

          let actions = "";
          if (o.status === "PENDING" && (mode === "pending" || mode === "all")) {
            actions =
              `<button class="btn sm ok" data-action="order" data-id="${o.id}" data-status="ACCEPTED" type="button">Accept</button>` +
              `<button class="btn sm danger" data-action="order" data-id="${o.id}" data-status="CANCELLED" type="button">Cancel</button>`;
          } else if (o.status === "ACCEPTED" && (mode === "active" || mode === "all")) {
            actions =
              `<button class="btn sm" data-action="order" data-id="${o.id}" data-status="SHIPPED" type="button">Ship</button>` +
              `<button class="btn sm danger" data-action="order" data-id="${o.id}" data-status="CANCELLED" type="button">Cancel</button>`;
          } else if (o.status === "SHIPPED" && (mode === "all" || mode === "history")) {
            actions = `<button class="btn sm ok" data-action="order" data-id="${o.id}" data-status="COMPLETED" type="button">Complete</button>`;
          }
          actions += `<button class="btn sm ghost" data-action="view-order" data-id="${o.id}" type="button">Details</button>`;

          const shipping = o.shipment || {};
          let shippingLabel = [shipping.courier, shipping.consignment].filter(Boolean).join(" ");
          if (shipping.courier === "MANUAL") shippingLabel = "Manual delivery";
          if (shipping.status === "simulated") shippingLabel = "Demo tracking — no verified courier booking";
          const shipment = shippingLabel ? `<br><span class="muted">${esc(shippingLabel)}</span>` : "";

          return (
            `<tr class="order-row-clickable" data-action="view-order" data-id="${o.id}">` +
            `<td><b>#${o.id}</b></td>` +
            `<td>${custHtml}</td>` +
            `<td>${items || '<span class="muted">No items</span>'}</td>` +
            `<td><b>${money(o.total)}</b></td>` +
            `<td><span class="badge ${esc(o.status)}">${esc(o.status)}</span>${shipment}</td>` +
            `<td>${esc((o.created_at || "").slice(0, 16).replace("T", " "))}</td>` +
            `<td class="order-actions-cell">${actions}</td>` +
            `</tr>`
          );
        })
        .join("") +
      "</tbody></table></div>"
    );
  }

  const RENDERERS = {
    summary_cards(el, d) {
      d = d || {};
      el.innerHTML = [
        ["Products", d.products],
        ["Pending orders", d.pending_orders],
        ["Active orders", d.active_orders],
        ["Shipped", d.shipped_orders],
        ["Human alerts", d.human_alerts],
      ]
        .map(([label, value]) => `<div class="stat"><b>${esc(value ?? 0)}</b><span>${label}</span></div>`)
        .join("");
    },

    sales_stats(el, d) {
      d = d || {};
      const charts = window.NexoraCharts;
      el.innerHTML =
        '<div class="stats-row">' +
        [["Revenue", money(d.total_revenue)], ["Units sold", d.total_units], ["Orders", d.orders]]
          .map(([label, value]) => `<div class="stat"><b>${esc(value ?? 0)}</b><span>${label}</span></div>`)
          .join("") +
        "</div>" +
        '<div class="chart-mini">' +
        '<div><p class="chart-title">Units by product</p><div class="donut-slot"></div></div>' +
        '<div><p class="chart-title">Revenue by product</p><div class="bars-slot"></div></div>' +
        "</div>";
      if (charts) {
        charts.donut(el.querySelector(".donut-slot"), d.donut || []);
        charts.bars(
          el.querySelector(".bars-slot"),
          (d.top_sellers || []).map((t) => ({ label: t.label, value: t.revenue })),
          money,
        );
      }
    },

    inventory_stats(el, d) {
      d = d || {};
      const rows = d.rows || [];
      if (!rows.length)
        return (el.innerHTML = emptyState("No products yet", "Add products to see stock levels here."));
      el.innerHTML =
        '<p class="chart-title">Remaining stock</p><div class="bars-slot"></div>' +
        '<div class="inventory-table table-wrap"><table><thead><tr><th>Product</th><th>Stock</th><th>Sold</th></tr></thead><tbody>' +
        rows
          .map((r) => `<tr><td>${esc(r.name)}</td><td>${esc(r.stock)}</td><td>${esc(r.sold)}</td></tr>`)
          .join("") +
        "</tbody></table></div>";
      const charts = window.NexoraCharts;
      if (charts)
        charts.bars(
          el.querySelector(".bars-slot"),
          rows.map((r) => ({ label: r.name, value: r.stock })),
        );
    },

    tenant_settings(el, d) {
      d = d || {};
      const assistantForm = $("#assistant-form");
      if (assistantForm && !loadedOnce.has(assistantForm)) {
        assistantForm.greeting.value = d.greeting || "";
        assistantForm.commands.value = commandLines(d.commands);
        loadedOnce.add(assistantForm);
      }
      const profileForm = $("#profile-form");
      if (profileForm && !loadedOnce.has(profileForm) && d.business_name) {
        profileForm.business_name.value = d.business_name;
        loadedOnce.add(profileForm);
      }
    },

    pending_orders(el, rows) {
      rows = rows || [];
      if (!rows.length)
        return (el.innerHTML = emptyState("No pending orders", "New orders from the agent wait here for your approval."));
      el.innerHTML = ordersTable(rows, "pending");
    },

    active_orders(el, rows) {
      rows = rows || [];
      if (!rows.length)
        return (el.innerHTML = emptyState("No active orders", "Accepted orders move here until they are shipped."));
      el.innerHTML = ordersTable(rows, "active");
    },

    order_history(el, rows) {
      rows = rows || [];
      if (!rows.length)
        return (el.innerHTML = emptyState("No orders yet", "Accepted, shipped and completed orders are listed here."));
      el.innerHTML = ordersTable(rows, "history");
    },

    recent_orders(el, rows) {
      rows = rows || [];
      if (!rows.length)
        return (el.innerHTML = emptyState("No orders yet", "Orders the AI agent creates will land here for your approval."));
      el.innerHTML = ordersTable(rows, "all");
    },

    catalog_skus(el, rows) {
      catalogCache = rows || [];
      productsById.clear();
      catalogCache.forEach((p) => productsById.set(String(p.id), p));
      renderCatalog();
    },

    chat_threads(el, rows) {
      rows = rows || [];
      threadsCache = rows;
      if (!rows.length)
        return (el.innerHTML =
          "<h3>Conversations</h3>" +
          emptyState("No conversations yet", "Incoming WhatsApp chats will appear here."));
      el.innerHTML =
        "<h3>Conversations</h3>" +
        rows
          .map((t) => {
            const last = (t.messages || [])[(t.messages || []).length - 1] || {};
            return `<div class="thread" data-action="thread" data-id="${t.id}">
              <b>${esc(t.customer_name || t.customer_phone)}</b>
              ${t.needs_human ? ' <span class="badge human">needs human</span>' : ""}
              <p>${esc(last.content || "")}</p>
            </div>`;
          })
          .join("");
    },

    system_overview(el, d) {
      d = d || {};
      el.innerHTML = [
        ["Tenants", d.total_tenants],
        ["Active tenants", d.active_tenants],
        ["WA connected", d.active_wa_sessions],
        ["Total orders", d.total_orders],
      ]
        .map(([label, value]) => `<div class="stat"><b>${esc(value ?? 0)}</b><span>${label}</span></div>`)
        .join("");
    },

    tenant_usage(el, rows) {
      rows = rows || [];
      if (!rows.length)
        return (el.innerHTML = emptyState("No tenants yet", "Create the first business account below."));
      const statusCls = (s) =>
        s === "CONNECTED" ? "connected" : s === "QR_READY" ? "qr" : s === "CONNECTING" ? "connecting" : "disconnected";
      el.innerHTML =
        '<div class="table-wrap"><table><thead><tr><th>Business</th><th>Plan</th><th>WA</th><th>Messages</th><th>Orders</th><th>Conversion</th><th>Account</th></tr></thead><tbody>' +
        rows
          .map(
            (t) => `<tr class="row-click" data-action="tenant-detail" data-id="${t.id}">
              <td>${esc(t.business_name)}</td>
              <td><span class="badge">${esc(t.plan || "BASIC")}</span></td>
              <td><span class="badge ${statusCls(t.wa_status)}">${esc(t.wa_status)}</span></td>
              <td>${esc(t.messages ?? 0)}</td><td>${esc(t.orders ?? 0)}</td><td>${esc(t.conversion ?? "-")}</td>
              <td>${t.plan_status === "CANCELLED" ? '<span class="log-error">plan cancelled</span>' : t.is_active ? "active" : '<span class="log-error">suspended</span>'}</td>
            </tr>`,
          )
          .join("") +
        "</tbody></table></div>";
    },

    config_and_logs(el, d) {
      d = d || {};
      const form = $("#config-form");
      if (form) {
        if (!form.llm_base_url.value) form.llm_base_url.value = d.llm_base_url || "";
        form.dataset.currentModel = d.model_name || "";
        const modelSelect = form.querySelector("#model-select");
        if (modelSelect && d.model_name) {
          if (!modelSelect.options.length || modelSelect.options.length <= 1) {
            modelSelect.innerHTML = `
              <option value="${esc(d.model_name)}">${esc(d.model_name)}</option>
              <option value="__custom__">Custom model…</option>
            `;
          }
          modelSelect.value = d.model_name;
        }
        if (!form.system_prompt.value) form.system_prompt.value = d.system_prompt || "";
        if (!form.request_options.value) form.request_options.value = d.request_options || "{}";
        document.dispatchEvent(new CustomEvent("nexora:config"));
      }
      const logs = d.error_logs || [];
      el.innerHTML =
        `<h3>Error and audit log</h3><p class="muted">Current model: ${esc(d.model_name || "not set")}</p>` +
        (logs.length
          ? '<div class="table-wrap"><table><thead><tr><th>Time</th><th>Message</th></tr></thead><tbody>' +
            logs
              .slice()
              .reverse()
              .map((l) => `<tr><td>${esc((l.at || "").slice(0, 19).replace("T", " "))}</td><td class="log-error">${esc(l.message)}</td></tr>`)
              .join("") +
            "</tbody></table></div>"
          : emptyState("No errors logged", "System and AI errors will be listed here."));
    },
  };

  const catalogState = { filter: "all", search: "" };
  let catalogCache = [];

  function skuChips(p) {
    if (!(p.skus || []).length) return '<span class="muted">No variants</span>';
    return (p.skus || [])
      .map((s) => {
        const stock = Number(s.stock || 0);
        const cls = stock === 0 ? " out" : stock <= 3 ? " low" : "";
        const step = (delta, label, disabled) =>
          `<button type="button" class="chip-step" data-action="stock-delta" data-id="${p.id}" ` +
          `data-sku="${esc(s.sku)}" data-delta="${delta}" title="${label}"${disabled ? " disabled" : ""}>${delta > 0 ? "+" : "−"}</button>`;
        return (
          `<span class="chip${cls}">` +
          step(-1, "Remove one", stock === 0) +
          `<span class="chip-txt">${esc(s.sku)} · ${esc(s.size || "-")}/${esc(s.color || "-")} · ${money(s.price)} · <b>${stock}</b></span>` +
          step(1, "Add one", false) +
          `</span>`
        );
      })
      .join(" ");
  }

  function catalogVisible() {
    const q = catalogState.search.trim().toLowerCase();
    return catalogCache.filter((p) => {
      if (catalogState.filter === "active" && !p.is_active) return false;
      if (catalogState.filter === "archived" && p.is_active) return false;
      if (catalogState.filter === "low" && !(p.is_active && p.low_stock > 0)) return false;
      if (catalogState.filter === "out" && !(p.is_active && p.out_of_stock > 0)) return false;
      if (!q) return true;
      const hay = [p.name, p.description]
        .concat((p.skus || []).flatMap((s) => [s.sku, s.size, s.color]))
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }

  function updateCatalogCounts() {
    const el = $("#catalog-count");
    if (!el) return;
    const total = catalogCache.length;
    const active = catalogCache.filter((p) => p.is_active).length;
    const counts = {
      all: total,
      active,
      archived: total - active,
      low: catalogCache.filter((p) => p.is_active && p.low_stock > 0).length,
      out: catalogCache.filter((p) => p.is_active && p.out_of_stock > 0).length,
    };
    $$("#catalog-filters .chip-btn").forEach((b) => {
      const n = counts[b.dataset.filter] || 0;
      b.textContent = b.dataset.filter.charAt(0).toUpperCase() + b.dataset.filter.slice(1) + " · " + n;
    });
    const visible = catalogVisible().length;
    el.textContent = visible === total ? `${total} product${total === 1 ? "" : "s"}` : `${visible} of ${total} shown`;
  }

  function renderCatalog() {
    const el = $('[data-widget="catalog_skus"]');
    if (!el) return;
    updateCatalogCounts();
    if (!catalogCache.length)
      return (el.innerHTML = emptyState("No products yet", "Add your first product above so the agent can quote prices and stock."));
    const rows = catalogVisible();
    if (!rows.length)
      return (el.innerHTML = emptyState("Nothing matches", "Try another search or filter."));
    el.innerHTML =
      '<div class="table-wrap"><table class="catalog-table"><thead><tr><th></th><th>Product</th><th>Variants</th><th>Stock</th><th></th></tr></thead><tbody>' +
      rows
        .map((p) => {
          const badges = [];
          if (!p.is_active) badges.push('<span class="badge archived">archived</span>');
          if (p.is_active && p.low_stock) badges.push('<span class="badge warn">low stock</span>');
          if (p.is_active && p.out_of_stock) badges.push(`<span class="badge out">${p.out_of_stock} out</span>`);
          const priceRange =
            p.max_price > p.min_price ? `${money(p.min_price)}–${money(p.max_price)}` : money(p.min_price);
          return (
            `<tr${p.is_active ? "" : ' class="row-archived"'}>` +
            `<td>${p.image_url ? `<img class="thumb" src="${esc(p.image_url)}" alt="">` : '<span class="thumb"></span>'}</td>` +
            `<td><div class="p-name"><b>${esc(p.name)}</b> ${badges.join(" ")}</div>` +
            `<div class="muted small">${p.variants} variant${p.variants === 1 ? "" : "s"} · ${priceRange}` +
            `${p.description ? " · " + esc(p.description.slice(0, 60)) : ""}</div></td>` +
            `<td class="chips-cell">${skuChips(p)}</td>` +
            `<td><b>${p.total_stock}</b><div class="muted small">units</div></td>` +
            `<td class="actions-cell">` +
            `<button class="btn sm ghost" data-action="edit-product" data-id="${p.id}">Edit</button>` +
            `<button class="btn sm ghost" data-action="duplicate-product" data-id="${p.id}">Duplicate</button>` +
            `<button class="btn sm ghost" data-action="${p.is_active ? "archive-product" : "restore-product"}" data-id="${p.id}">${p.is_active ? "Archive" : "Restore"}</button>` +
            `</td></tr>`
          );
        })
        .join("") +
      "</tbody></table></div>";
  }

  function autoSku(name, color, size) {
    const initials =
      String(name || "ITEM")
        .split(/\s+/)
        .map((w) => w[0])
        .filter(Boolean)
        .join("")
        .slice(0, 3)
        .toUpperCase() || "ITM";
    const c = String(color || "").replace(/[^a-z0-9]/gi, "").slice(0, 3).toUpperCase() || "STD";
    const s = String(size || "").replace(/[^a-z0-9]/gi, "").slice(0, 3).toUpperCase();
    return [initials, c, s].filter(Boolean).join("-");
  }

  function addVariantRow(variant) {
    const host = $("#variant-rows");
    if (!host) return;
    variant = variant || {};
    const row = document.createElement("div");
    row.className = "variant-row";
    row.innerHTML =
      `<input class="v-sku" placeholder="SKU code" value="${esc(variant.sku || "")}">` +
      `<input class="v-size" placeholder="Size" value="${esc(variant.size || "")}">` +
      `<input class="v-color" placeholder="Color" value="${esc(variant.color || "")}">` +
      `<input class="v-price" type="number" step="0.01" min="0" placeholder="0.00" value="${variant.price != null ? esc(variant.price) : ""}">` +
      `<input class="v-stock" type="number" min="0" placeholder="0" value="${variant.stock != null ? esc(variant.stock) : ""}">` +
      `<button type="button" class="v-remove" title="Remove variant">×</button>`;
    host.appendChild(row);
    updateVariantSummary();
    return row;
  }

  function renderVariantRows(list) {
    const host = $("#variant-rows");
    if (!host) return;
    host.innerHTML = "";
    (list || []).forEach((v) => addVariantRow(v));
    updateVariantSummary();
  }

  function readVariants() {
    return $$("#variant-rows .variant-row").map((row) => ({
      sku: $(".v-sku", row).value.trim(),
      size: $(".v-size", row).value.trim(),
      color: $(".v-color", row).value.trim(),
      price: Number($(".v-price", row).value || 0),
      stock: Number($(".v-stock", row).value || 0),
    }));
  }

  function updateVariantSummary() {
    const el = $("#variant-summary");
    if (!el) return;
    const rows = readVariants();
    if (!rows.length) {
      el.textContent = "No variants yet";
      return;
    }
    const stocks = rows.map((r) => r.stock || 0);
    const prices = rows.map((r) => r.price || 0).filter((p) => p > 0);
    const total = stocks.reduce((a, b) => a + b, 0);
    const range = prices.length
      ? ` · ${money(Math.min.apply(null, prices))}–${money(Math.max.apply(null, prices))}`
      : "";
    el.textContent = `${rows.length} variant${rows.length === 1 ? "" : "s"} · ${total} units in stock${range}`;
  }

  function splitList(value) {
    return String(value || "")
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean);
  }

  function bindProductTools() {
    const addBtn = $("#variant-add");
    if (addBtn)
      addBtn.addEventListener("click", () => {
        addVariantRow();
        const rows = $$("#variant-rows .variant-row");
        const last = rows[rows.length - 1];
        if (last) $(".v-sku", last).focus();
      });

    const genBtn = $("#variant-generate");
    if (genBtn)
      genBtn.addEventListener("click", () => {
        const sizes = splitList(($("#gen-sizes") || {}).value);
        const colors = splitList(($("#gen-colors") || {}).value);
        if (!sizes.length && !colors.length) return toast("Enter sizes and/or colors first.", "err");
        const form = $("#product-form");
        const name = form ? form.name.value : "";
        const basePrice = form && Number(form.base_price.value) ? Number(form.base_price.value) : null;
        const existing = new Set(
          readVariants()
            .map((v) => `${v.size}|${v.color}`.toLowerCase())
            .filter((k) => k !== "|"),
        );
        const sizeList = sizes.length ? sizes : [""];
        const colorList = colors.length ? colors : [""];
        let added = 0;
        for (const color of colorList)
          for (const size of sizeList) {
            const key = `${size}|${color}`.toLowerCase();
            if (existing.has(key)) continue;
            existing.add(key);
            addVariantRow({ sku: autoSku(name, color, size), size, color, price: basePrice, stock: 0 });
            added += 1;
          }
        toast(added ? `Generated ${added} variant${added === 1 ? "" : "s"}.` : "All combinations already exist.", added ? "ok" : "err");
      });

    const bulkPrice = $("#bulk-price-apply");
    if (bulkPrice)
      bulkPrice.addEventListener("click", () => {
        const value = Number(($("#bulk-price") || {}).value || 0);
        if (!value) return toast("Enter a price to apply.", "err");
        $$("#variant-rows .v-price").forEach((input) => (input.value = value));
        updateVariantSummary();
        toast("Price applied to all variants.", "ok");
      });

    const bulkStock = $("#bulk-stock-apply");
    if (bulkStock)
      bulkStock.addEventListener("click", () => {
        const input = $("#bulk-stock") || {};
        if (input.value === "" || input.value == null) return toast("Enter a stock amount to apply.", "err");
        $$("#variant-rows .v-stock").forEach((field) => (field.value = Math.max(0, Number(input.value || 0))));
        updateVariantSummary();
        toast("Stock applied to all variants.", "ok");
      });

    const host = $("#variant-rows");
    if (host) {
      host.addEventListener("input", (e) => {
        const row = e.target.closest(".variant-row");
        if (row) row.classList.remove("invalid");
        updateVariantSummary();
      });
      host.addEventListener("click", (e) => {
        const btn = e.target.closest(".v-remove");
        if (!btn) return;
        const row = btn.closest(".variant-row");
        if (row) row.remove();
        updateVariantSummary();
      });
    }

    const search = $("#catalog-search");
    if (search)
      search.addEventListener("input", () => {
        catalogState.search = search.value;
        renderCatalog();
      });
    const filters = $("#catalog-filters");
    if (filters)
      filters.addEventListener("click", (e) => {
        const btn = e.target.closest(".chip-btn");
        if (!btn) return;
        catalogState.filter = btn.dataset.filter;
        $$("#catalog-filters .chip-btn").forEach((b) => b.classList.toggle("active", b === btn));
        renderCatalog();
      });
  }

  function parseCommandLines(text) {
    return String(text || "")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const idx = line.indexOf("|");
        if (idx === -1) return { trigger: line, reply: "" };
        return { trigger: line.slice(0, idx).trim(), reply: line.slice(idx + 1).trim() };
      })
      .filter((c) => c.trigger && c.reply);
  }

  function commandLines(commands) {
    return (commands || []).map((c) => `${c.trigger} | ${c.reply}`).join("\n");
  }

  function setImagePreview(url) {
    const box = $("#image-preview");
    if (!box) return;
    if (url) {
      box.innerHTML = `<img src="${esc(url)}" alt="Product photo preview">`;
      box.hidden = false;
    } else {
      box.innerHTML = "";
      box.hidden = true;
    }
  }

  function showThread(id) {
    const view = $("#chat-view");
    const t = threadsCache.find((x) => String(x.id) === String(id));
    if (!view || !t) return;
    $$(".thread").forEach((el) => el.classList.toggle("active", el.dataset.id === String(id)));
    view.innerHTML =
      `<h3>${esc(t.customer_name || t.customer_phone)} <span class="muted">${esc(t.customer_phone)}</span></h3>` +
      (t.needs_human
        ? `<button class="btn sm ok" data-action="resolve" data-id="${t.id}">Mark resolved</button>`
        : "") +
      '<div class="msgs">' +
      (t.messages || [])
        .map((m) => {
          let mediaHtml = "";
          if (m.media && Array.isArray(m.media)) {
            mediaHtml = m.media
              .map(
                (med) =>
                  `<div class="msg-media"><img src="${esc(med.url || med)}" alt="${esc(med.caption || "Product photo")}" style="max-width:200px;border-radius:8px;margin-top:6px;display:block;">${med.caption ? `<small class="muted" style="display:block;margin-top:2px;">${esc(med.caption)}</small>` : ""}</div>`,
              )
              .join("");
          }
          return `<div class="msg ${m.role === "assistant" ? "assistant" : "user"}"><span class="who">${esc(m.role)}</span>${esc(m.content)}${mediaHtml}</div>`;
        })
        .join("") +
      "</div>";
  }

  async function pollWa() {
    const el = $("#wa-status");
    if (!el) return;
    const button = $("#wa-connect");
    try {
      const res = await fetch("/api/wa/status/");
      if (!res.ok) throw new Error("Bridge unavailable");
      const j = await res.json();
      const cls =
        { CONNECTED: "connected", QR_READY: "qr", CONNECTING: "connecting" }[j.status] || "disconnected";
      el.innerHTML = `<span class="badge ${cls}">${esc(j.status)}</span>`;
      $("#wa-qr").innerHTML = j.qr ? `<img src="${esc(j.qr)}" alt="WhatsApp linking QR code">` : "";
      if (j.qr) el.innerHTML += '<p class="muted">Scan with WhatsApp &gt; Linked devices.</p>';
      button.disabled = j.status !== "DISCONNECTED";
      button.textContent = j.status === "CONNECTED" ? "Connected" : button.disabled ? "Connecting…" : "Connect WhatsApp";
    } catch (e) {
      el.innerHTML = '<span class="badge disconnected">BRIDGE OFFLINE</span>';
      $("#wa-qr").innerHTML = "";
      button.disabled = false;
      button.textContent = "Connect WhatsApp";
    }
  }

  let cancelOrderId = null;
  let lastFocus = null;

  function openCancelDrawer(orderId) {
    cancelOrderId = orderId;
    lastFocus = document.activeElement;
    $("#cancel-order-id").textContent = "#" + orderId;
    $("#drawer-backdrop").classList.add("open");
    const drawer = $("#cancel-drawer");
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    $("#cancel-note").value = "";
    setTimeout(() => $("#cancel-note").focus(), 140);
  }

  function closeCancelDrawer() {
    $("#drawer-backdrop").classList.remove("open");
    const drawer = $("#cancel-drawer");
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    cancelOrderId = null;
    if (lastFocus) lastFocus.focus();
  }

  let activeDetailOrderId = null;

  async function openOrderDrawer(orderId) {
    activeDetailOrderId = orderId;
    lastFocus = document.activeElement;
    const titleId = $("#order-detail-id");
    if (titleId) titleId.textContent = orderId;
    const body = $("#order-drawer-body");
    if (body) body.innerHTML = '<div class="muted">Loading order details...</div>';
    $("#drawer-backdrop").classList.add("open");
    const drawer = $("#order-drawer");
    if (drawer) {
      drawer.classList.add("open");
      drawer.setAttribute("aria-hidden", "false");
    }

    try {
      const res = await fetch(`/api/order/${orderId}/`);
      const data = await res.json();
      if (!data.ok || !data.order) {
        if (body) body.innerHTML = `<div class="empty"><b>Error</b><span>${esc(data.error || "Could not load order")}</span></div>`;
        return;
      }
      renderOrderDrawer(data.order);
    } catch (e) {
      if (body) body.innerHTML = '<div class="empty"><b>Error</b><span>Network error fetching order details.</span></div>';
    }
  }

  function closeOrderDrawer() {
    const drawer = $("#order-drawer");
    if (drawer) {
      drawer.classList.remove("open");
      drawer.setAttribute("aria-hidden", "true");
    }
    if (!$("#cancel-drawer.open") && !$("#tenant-drawer.open") && !$("#account-drawer.open")) {
      const backdrop = $("#drawer-backdrop");
      if (backdrop) backdrop.classList.remove("open");
    }
    activeDetailOrderId = null;
    if (lastFocus) lastFocus.focus();
  }

  function renderOrderDrawer(o) {
    const body = $("#order-drawer-body");
    if (!body) return;

    const cleanPhone = String(o.customer_phone || "").replace(/[^\d+]/g, "").replace(/^\+/, "");
    const dateFormatted = esc((o.created_at || "").slice(0, 19).replace("T", " "));

    const itemsHtml = (o.items || [])
      .map((i) => {
        const itemTotal = Number(i.price || 0) * Number(i.qty || 1);
        const skuBadge = i.sku ? `<span class="sku-badge">${esc(i.sku)}</span>` : "";
        const noteHtml = i.notes
          ? `<div class="order-item-detail-note"><strong>Note:</strong> ${esc(i.notes)}</div>`
          : "";
        return (
          '<div class="order-item-detail-entry">' +
          '<div class="order-item-detail-header">' +
          `<span class="order-item-detail-name">${esc(i.product || "Product")}</span>` +
          `<span class="order-item-detail-price">${money(itemTotal)}</span>` +
          '</div>' +
          '<div class="order-item-detail-sub">' +
          `<span>Qty: <b>${esc(i.qty || 1)}</b> &times; ${money(i.price)}</span>` +
          skuBadge +
          '</div>' +
          noteHtml +
          '</div>'
        );
      })
      .join("");

    let notesBlock = "";
    const allNotes = [];
    if (o.latest_customer_note) allNotes.push(o.latest_customer_note);
    if (o.item_notes && Array.isArray(o.item_notes)) {
      o.item_notes.forEach((n) => {
        if (n && !allNotes.includes(n)) allNotes.push(n);
      });
    }

    if (allNotes.length) {
      notesBlock =
        '<div class="order-detail-card">' +
        '<h4>Specific Note from Customer</h4>' +
        allNotes.map((n) => `<div class="order-note-callout">${esc(n)}</div>`).join("") +
        '</div>';
    } else {
      notesBlock =
        '<div class="order-detail-card">' +
        '<h4>Customer Notes</h4>' +
        '<div class="muted small">No specific notes recorded for this order.</div>' +
        '</div>';
    }

    let shipmentBlock = "";
    if (o.shipment && (o.shipment.courier || o.shipment.consignment)) {
      shipmentBlock =
        '<div class="order-detail-card">' +
        '<h4>Shipment &amp; Tracking</h4>' +
        (o.shipment.status === "simulated" ? '<p class="muted">Demo tracking — this is not a verified courier booking.</p>' : "") +
        '<div class="order-info-list">' +
        `<div class="order-info-row"><span class="order-info-label">Courier</span><span class="order-info-val"><b>${esc(o.shipment.courier || "-")}</b></span></div>` +
        (o.shipment.courier === "MANUAL"
          ? '<p class="muted">Delivery is arranged directly by the store.</p>'
          : `<div class="order-info-row"><span class="order-info-label">Consignment / Tracking</span><span class="order-info-val"><code>${esc(o.shipment.consignment || "-")}</code></span></div>`) +
        (o.shipment.shipped_at
          ? `<div class="order-info-row"><span class="order-info-label">Shipped at</span><span class="order-info-val">${esc(o.shipment.shipped_at)}</span></div>`
          : "") +
        '</div>' +
        '</div>';
    }

    let actionsHtml = "";
    if (o.status === "PENDING") {
      actionsHtml =
        `<button class="btn ok" data-action="drawer-order" data-id="${o.id}" data-status="ACCEPTED" type="button">Accept order</button>` +
        `<button class="btn danger" data-action="drawer-order" data-id="${o.id}" data-status="CANCELLED" type="button">Cancel order</button>`;
    } else if (o.status === "ACCEPTED") {
      actionsHtml =
        `<button class="btn" data-action="drawer-order" data-id="${o.id}" data-status="SHIPPED" type="button">Ship order</button>` +
        `<button class="btn danger" data-action="drawer-order" data-id="${o.id}" data-status="CANCELLED" type="button">Cancel order</button>`;
    } else if (o.status === "SHIPPED") {
      actionsHtml = `<button class="btn ok" data-action="drawer-order" data-id="${o.id}" data-status="COMPLETED" type="button">Mark complete</button>`;
    }

    body.innerHTML =
      '<div class="order-detail-card">' +
      '<div style="display:flex; justify-content:space-between; align-items:center;">' +
      `<span class="badge ${esc(o.status)}">${esc(o.status)}</span>` +
      `<span class="muted small">${dateFormatted}</span>` +
      '</div>' +
      '</div>' +
      '<div class="order-detail-card">' +
      '<h4>Customer Information</h4>' +
      '<div class="order-info-list">' +
      `<div class="order-info-row"><span class="order-info-label">Full Name</span><span class="order-info-val"><b>${esc(o.customer_name || "Customer")}</b></span></div>` +
      `<div class="order-info-row"><span class="order-info-label">Phone</span><span class="order-info-val"><a href="tel:${esc(o.customer_phone)}" class="order-phone-link">${esc(o.customer_phone)}</a>` +
      (cleanPhone ? `<a href="https://wa.me/${esc(cleanPhone)}" target="_blank" rel="noopener" class="order-wa-link">WhatsApp</a>` : "") +
      `</span></div>` +
      `<div class="order-info-row"><span class="order-info-label">Delivery Address</span><span class="order-info-val">${esc(o.address || "No address provided")}</span></div>` +
      '</div>' +
      '</div>' +
      notesBlock +
      '<div class="order-detail-card">' +
      '<h4>Ordered Products &amp; SKUs</h4>' +
      `<div class="order-items-detail-list">${itemsHtml || '<span class="muted">No items</span>'}</div>` +
      '<div class="order-total-bar">' +
      '<span>Total Amount</span>' +
      `<b>${money(o.total)}</b>` +
      '</div>' +
      '</div>' +
      shipmentBlock +
      (actionsHtml ? `<div class="order-drawer-actions">${actionsHtml}</div>` : "");
  }

  let currentTenant = null;

  async function openTenantDrawer(id) {
    const res = await fetch(`/api/admin/tenant/${id}/`);
    const j = await res.json();
    if (j.error) return toast(j.error, "err");
    const t = j.tenant;
    currentTenant = t;
    $("#tenant-name").textContent = t.business_name;
    $("#tenant-plan-badge").textContent = t.plan + (t.plan_status === "CANCELLED" ? " (cancelled)" : "");
    $("#plan-select").value = t.plan;
    $("#plan-cancel-btn").textContent = t.plan_status === "CANCELLED" ? "Reactivate plan" : "Cancel plan";
    $("#tenant-suspend-btn").textContent = t.is_active ? "Suspend" : "Activate";
    $("#tenant-detail").innerHTML = [
      ["Username", esc(t.username)],
      ["Email", esc(t.email || "-")],
      ["WhatsApp", esc(t.wa_status)],
      ["Messages", esc(t.messages)],
      ["Orders", esc(t.orders_count)],
      ["Converted orders", esc(t.converted_orders)],
      ["Conversion rate", esc(t.conversion_rate)],
      ["Tokens used", esc((t.usage_stats || {}).tokens_used || 0)],
    ]
      .map(([label, value]) => `<div class="detail-row"><span>${label}</span><b>${value}</b></div>`)
      .join("");
    $("#tenant-delete-confirm").hidden = true;
    $("#tenant-danger").hidden = false;
    lastFocus = document.activeElement;
    $("#drawer-backdrop").classList.add("open");
    const drawer = $("#tenant-drawer");
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
  }

  function closeTenantDrawer() {
    const drawer = $("#tenant-drawer");
    if (!drawer || !drawer.classList.contains("open")) return;
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    if (!$(".drawer.open")) $("#drawer-backdrop").classList.remove("open");
    if (lastFocus) lastFocus.focus();
  }

  function openAccountDrawer() {
    const drawer = $("#account-drawer");
    if (!drawer) return;
    lastFocus = document.activeElement;
    $("#drawer-backdrop").classList.add("open");
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    setTimeout(() => $("#account-form").username.focus(), 140);
  }

  function closeAccountDrawer() {
    const drawer = $("#account-drawer");
    if (!drawer || !drawer.classList.contains("open")) return;
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    if (!$(".drawer.open")) $("#drawer-backdrop").classList.remove("open");
    if (lastFocus) lastFocus.focus();
  }

  function bindTabs() {
    const buttons = $$(".tab");
    const activate = (name) => {
      buttons.forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
      $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
      document.dispatchEvent(new CustomEvent("nexora:tab", { detail: { tab: name } }));
    };
    buttons.forEach((btn) =>
      btn.addEventListener("click", () => {
        activate(btn.dataset.tab);
        history.replaceState(null, "", "#" + btn.dataset.tab);
      }),
    );
    const initial = location.hash.slice(1);
    if (initial && buttons.some((b) => b.dataset.tab === initial)) activate(initial);
  }

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;

    if (action === "order" || action === "drawer-order") {
      const status = btn.dataset.status;
      if (status === "CANCELLED") {
        if (action === "drawer-order") closeOrderDrawer();
        return openCancelDrawer(id);
      }
      btn.disabled = true;
      const r = await api(`/api/order/${id}/action/`, { action: status });
      btn.disabled = false;
      if (r.error) return toast(r.error, "err");
      toast(`Order #${id} ${status.toLowerCase()}`, "ok");
      if (r.warning) toast(r.warning, "err");
      if (action === "drawer-order") closeOrderDrawer();
      await loadWidgets();
      if (status === "ACCEPTED") $("[data-tab=active]")?.click();
    } else if (action === "view-order") {
      openOrderDrawer(id);
    } else if (action === "edit-product") {
      const p = productsById.get(String(id));
      if (!p) return;
      const form = $("#product-form");
      form.id.value = p.id;
      form.name.value = p.name || "";
      form.base_price.value = p.base_price || "";
      form.description.value = p.description || "";
      form.image_url.value = p.image_url || "";
      form.dataset.originalImage = p.image_url || "";
      renderVariantRows(p.skus);
      setImagePreview(p.image_url || "");
      $("#product-form-title").textContent = "Editing: " + p.name;
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else if (action === "stock-delta") {
      btn.disabled = true;
      const r = await api("/api/product/stock/", {
        id: Number(id),
        sku: btn.dataset.sku,
        delta: Number(btn.dataset.delta),
      });
      if (r.error) {
        btn.disabled = false;
        return toast(r.error, "err");
      }
      const p = productsById.get(String(id));
      if (p) {
        const sku = (p.skus || []).find((s) => s.sku === r.sku);
        if (sku) sku.stock = r.stock;
        const stocks = (p.skus || []).map((s) => Number(s.stock || 0));
        p.total_stock = stocks.reduce((a, b) => a + b, 0);
        p.low_stock = stocks.filter((v) => v > 0 && v <= 3).length;
        p.out_of_stock = stocks.filter((v) => v === 0).length;
        renderCatalog();
      }
    } else if (action === "duplicate-product") {
      btn.disabled = true;
      const r = await api("/api/product/duplicate/", { id: Number(id) });
      if (r.error) {
        btn.disabled = false;
        return toast(r.error, "err");
      }
      toast("Product duplicated — edit the copy to change its SKUs.", "ok");
      loadWidgets();
    } else if (action === "archive-product" || action === "restore-product") {
      btn.disabled = true;
      const archived = action === "archive-product";
      const r = await api("/api/product/archive/", { id: Number(id), archived });
      if (r.error) {
        btn.disabled = false;
        return toast(r.error, "err");
      }
      toast(archived ? "Archived — the agent will no longer sell it." : "Restored to the active catalog.", "ok");
      loadWidgets();
    } else if (action === "thread") {
      showThread(id);
    } else if (action === "resolve") {
      const r = await api(`/api/conversation/${id}/resolve/`, {});
      if (r.error) return toast(r.error, "err");
      toast("Marked resolved.", "ok");
      loadWidgets();
    } else if (action === "account-open") {
      openAccountDrawer();
    } else if (action === "tenant-detail") {
      openTenantDrawer(id);
    } else if (action === "toggle-tenant") {
      const r = await api("/api/admin/config/", { tenant_id: Number(id), is_active: btn.dataset.active !== "true" });
      if (r.error) return toast(r.error, "err");
      loadWidgets();
    } else if (action === "reset-tenant") {
      btn.disabled = true;
      const r = await api("/api/admin/config/", { reset_tenant: Number(id) });
      btn.disabled = false;
      if (r.error) return toast(r.error, "err");
      toast("WhatsApp session reset requested.", "ok");
      loadWidgets();
    }
  });

  function bindForms() {
    const tenantDrawer = $("#tenant-drawer");
    if (tenantDrawer) {
      $("#tenant-drawer-close").addEventListener("click", closeTenantDrawer);
      $("#drawer-backdrop").addEventListener("click", closeTenantDrawer);
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeTenantDrawer();
      });
      $("#plan-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!currentTenant) return;
        const plan = $("#plan-select").value;
        const r = await api("/api/admin/plan/", { tenant_id: currentTenant.id, plan });
        if (r.error) return toast(r.error, "err");
        toast(`Plan set to ${plan}.`, "ok");
        await openTenantDrawer(currentTenant.id);
        loadWidgets();
      });
      $("#plan-cancel-btn").addEventListener("click", async () => {
        if (!currentTenant) return;
        const next = currentTenant.plan_status === "CANCELLED" ? "ACTIVE" : "CANCELLED";
        const r = await api("/api/admin/plan/", { tenant_id: currentTenant.id, plan_status: next });
        if (r.error) return toast(r.error, "err");
        toast(next === "CANCELLED" ? "Plan cancelled. Messages are ignored." : "Plan reactivated.", "ok");
        await openTenantDrawer(currentTenant.id);
        loadWidgets();
      });
      $("#tenant-suspend-btn").addEventListener("click", async () => {
        if (!currentTenant) return;
        const r = await api("/api/admin/config/", { tenant_id: currentTenant.id, is_active: !currentTenant.is_active });
        if (r.error) return toast(r.error, "err");
        toast(currentTenant.is_active ? "Business suspended." : "Business activated.", "ok");
        await openTenantDrawer(currentTenant.id);
        loadWidgets();
      });
      $("#tenant-reset-btn").addEventListener("click", async () => {
        if (!currentTenant) return;
        const r = await api("/api/admin/config/", { reset_tenant: currentTenant.id });
        toast(r.error || "WhatsApp session reset requested.", r.error ? "err" : "ok");
      });
      $("#tenant-delete-start").addEventListener("click", () => {
        $("#tenant-danger").hidden = true;
        $("#tenant-delete-confirm").hidden = false;
      });
      $("#tenant-delete-no").addEventListener("click", () => {
        $("#tenant-delete-confirm").hidden = true;
        $("#tenant-danger").hidden = false;
      });
      $("#tenant-delete-yes").addEventListener("click", async () => {
        if (!currentTenant) return;
        const r = await api(`/api/admin/tenant/${currentTenant.id}/delete/`, {});
        if (r.error) return toast(r.error, "err");
        toast("Tenant deleted.", "ok");
        currentTenant = null;
        closeTenantDrawer();
        loadWidgets();
      });
    }

    const productForm = $("#product-form");
    if (productForm) {
      const imageInput = $("#product-image");
      if (imageInput) {
        imageInput.addEventListener("change", async () => {
          const file = imageInput.files && imageInput.files[0];
          if (!file) return;
          const status = $("#upload-status");
          status.textContent = "Uploading…";
          const body = new FormData();
          body.append("file", file);
          try {
            const res = await fetch("/api/product/upload/", {
              method: "POST",
              headers: { "X-CSRFToken": csrf() },
              body,
            });
            const r = await res.json();
            if (r.error) {
              status.textContent = "";
              return toast(r.error, "err");
            }
            productForm.image_url.value = r.url;
            setImagePreview(r.url);
            status.textContent = "Photo attached.";
            toast("Photo uploaded.", "ok");
          } catch (err) {
            status.textContent = "";
            toast("Upload failed. Check the server.", "err");
          }
          imageInput.value = "";
        });
        productForm.image_url.addEventListener("change", () => setImagePreview(productForm.image_url.value));
      }
      productForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = productForm;
        const variants = readVariants();
        if (!variants.length) return toast("Add at least one variant (SKU) before saving.", "err");
        const missing = variants.findIndex((v) => !v.sku);
        if (missing !== -1) {
          const row = $$("#variant-rows .variant-row")[missing];
          if (row) {
            row.classList.add("invalid");
            $(".v-sku", row).focus();
          }
          return toast("Every variant needs a SKU code.", "err");
        }
        const seen = new Set();
        const dupe = variants.findIndex((v) => {
          const key = v.sku.toLowerCase();
          if (seen.has(key)) return true;
          seen.add(key);
          return false;
        });
        if (dupe !== -1) {
          const row = $$("#variant-rows .variant-row")[dupe];
          if (row) {
            row.classList.add("invalid");
            $(".v-sku", row).focus();
          }
          return toast(`Duplicate SKU code: ${variants[dupe].sku}`, "err");
        }
        const r = await api("/api/product/save/", {
          id: f.id.value || null,
          name: f.name.value,
          base_price: f.base_price.value,
          image_url: f.image_url.value,
          original_image_url: f.dataset.originalImage || "",
          description: f.description.value,
          skus: variants,
        });
        if (r.error) return toast(r.error, "err");
        f.reset();
        f.id.value = "";
        f.dataset.originalImage = "";
        renderVariantRows([]);
        setImagePreview("");
        $("#upload-status").textContent = "";
        $("#product-form-title").textContent = "Add product";
        toast("Product saved.", "ok");
        loadWidgets();
      });
      $("#product-reset").addEventListener("click", () => {
        productForm.reset();
        productForm.id.value = "";
        productForm.dataset.originalImage = "";
        renderVariantRows([]);
        setImagePreview("");
        $("#upload-status").textContent = "";
        $("#product-form-title").textContent = "Add product";
      });
      bindProductTools();
    }

    const configForm = $("#config-form");
    if (configForm) {
      const f = configForm;
      const modelSelect = $("#model-select");
      const modelCustom = $("#model-custom");
      const modelStatus = $("#config-status");
      let modelsLoaded = false;

      const selectedModel = () => {
        if (modelSelect.value === "__custom__") {
          return modelCustom.value.trim();
        }
        return modelSelect.value.trim() || modelCustom.value.trim() || f.dataset.currentModel || "";
      };

      function syncModelCustom() {
        const custom = modelSelect.value === "__custom__";
        modelCustom.hidden = !custom;
        if (custom) modelCustom.focus();
      }

      function renderModels(models, current, keepMissing) {
        const list = models.slice();
        if (current && !list.includes(current)) list.unshift(current);
        modelSelect.innerHTML =
          (list.length ? "" : '<option value="">Select a model…</option>') +
          list.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("") +
          '<option value="__custom__">Custom model…</option>';
        modelSelect.value = current || (list.length ? list[0] : "");
        syncModelCustom();
      }

      const hostOf = (url) => {
        try {
          return new URL(url).host;
        } catch (e) {
          return url;
        }
      };

      function cleanBaseUrl(val) {
        let base = String(val || "").trim();
        if (base && !base.startsWith("http://") && !base.startsWith("https://")) {
          base = (base.startsWith("localhost") || base.startsWith("127.0.0.1") ? "http://" : "https://") + base;
        }
        return base;
      }

      async function loadModels() {
        let base = cleanBaseUrl(f.llm_base_url.value);
        if (base && f.llm_base_url.value.trim() !== base) {
          f.llm_base_url.value = base;
        }
        if (!base) {
          modelStatus.innerHTML = '<span style="color:var(--muted)">Enter a base URL first, then load models.</span>';
          return;
        }
        const current =
          selectedModel() || modelSelect.dataset.current || f.dataset.currentModel || "";
        const host = hostOf(base);
        const refreshBtn = $("#model-refresh");
        if (refreshBtn) {
          refreshBtn.disabled = true;
          refreshBtn.textContent = "Loading…";
        }
        modelStatus.innerHTML = `<span style="color:var(--muted)">Connecting to ${esc(host)}…</span>`;
        try {
          const r = await api("/api/admin/models/", {
            llm_base_url: base,
            api_key: f.api_key.value,
          });
          if (r.normalized_url && f.llm_base_url.value !== r.normalized_url) {
            f.llm_base_url.value = r.normalized_url;
            base = r.normalized_url;
          }
          if (r.models && r.models.length) {
            renderModels(r.models, current);
            modelSelect.dataset.current = modelSelect.value || "";
            modelSelect.dataset.host = host;
            modelStatus.innerHTML = `<span style="color:var(--green-ink); font-weight:500;">Loaded ${r.models.length} models from ${esc(host)}.</span>`;
            toast(`${r.models.length} models loaded.`, "ok");
          } else {
            renderModels([], current, true);
            modelSelect.dataset.host = "";
            const err = r.error || "Could not load models.";
            modelStatus.innerHTML = `<span style="color:var(--red-ink);">${esc(err)}</span>`;
            toast(err, "err");
            if (!current) {
              modelSelect.value = "__custom__";
              syncModelCustom();
            }
          }
        } catch (e) {
          modelStatus.innerHTML = '<span style="color:var(--red-ink);">Network error loading models.</span>';
          toast("Network error loading models.", "err");
        } finally {
          modelsLoaded = true;
          if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.textContent = "Load models";
          }
        }
      }

      let loadTimer = null;
      const scheduleLoad = () => {
        clearTimeout(loadTimer);
        loadTimer = setTimeout(loadModels, 600);
      };

      modelSelect.addEventListener("change", syncModelCustom);
      const refreshBtn = $("#model-refresh");
      if (refreshBtn) {
        refreshBtn.addEventListener("click", () => {
          clearTimeout(loadTimer);
          loadModels();
        });
      }

      const testBtn = $("#model-test");
      const testResultBox = $("#test-result-box");
      if (testBtn) {
        testBtn.addEventListener("click", async () => {
          let base = cleanBaseUrl(f.llm_base_url.value);
          if (!base) {
            toast("Please enter a base URL first.", "err");
            f.llm_base_url.focus();
            return;
          }
          if (f.llm_base_url.value.trim() !== base) f.llm_base_url.value = base;
          const model = selectedModel();
          const host = hostOf(base);
          testBtn.disabled = true;
          testBtn.textContent = "Testing…";
          if (testResultBox) {
            testResultBox.hidden = false;
            testResultBox.innerHTML = `
              <div class="test-box loading">
                <b>Testing connection to ${esc(host)}…</b>
                <div class="test-meta">Sending completion request with model: <code>${esc(model || "auto-detect")}</code></div>
              </div>
            `;
          }
          try {
            const r = await api("/api/admin/test-llm/", {
              llm_base_url: base,
              api_key: f.api_key.value,
              model_name: model,
              request_options: f.request_options.value.trim() || "{}",
            });
            if (testResultBox) {
              if (r.ok && r.live) {
                testResultBox.innerHTML = `
                  <div class="test-box success">
                    <b>Live (${r.latency_ms}ms)</b>
                    <div class="test-meta">Successfully connected to <strong>${esc(r.model)}</strong> at ${esc(host)}.</div>
                    ${r.reply ? `<div class="test-reply">Response: "${esc(r.reply)}"</div>` : ""}
                  </div>
                `;
                toast(`API is live (${r.latency_ms}ms).`, "ok");
              } else {
                testResultBox.innerHTML = `
                  <div class="test-box error">
                    <b>Connection failed</b>
                    <div class="test-meta">${esc(r.error || "The provider did not respond.")}</div>
                  </div>
                `;
                toast(r.error || "API connection failed.", "err");
              }
            }
          } catch (err) {
            if (testResultBox) {
              testResultBox.innerHTML = `
                <div class="test-box error">
                  <b>Network error</b>
                  <div class="test-meta">Failed to communicate with local server: ${esc(err.message || String(err))}</div>
                </div>
              `;
            }
            toast("Network error during test.", "err");
          } finally {
            testBtn.disabled = false;
            testBtn.textContent = "Test API connection";
          }
        });
      }

      f.llm_base_url.addEventListener("change", () => {
        const host = hostOf(f.llm_base_url.value.trim());
        if (modelSelect.dataset.host && modelSelect.dataset.host !== host) {
          modelSelect.innerHTML = '<option value="">Loading models…</option>';
          modelStatus.innerHTML = '<span style="color:var(--muted)">Provider changed — loading its models…</span>';
        }
        scheduleLoad();
      });
      document.addEventListener("nexora:config", () => {
        if (modelsLoaded || !f.llm_base_url.value) return;
        loadModels();
      });
      document.addEventListener("nexora:tab", (e) => {
        if (e.detail && e.detail.tab === "ai" && !modelsLoaded && f.llm_base_url.value) {
          loadModels();
        }
      });

      f.addEventListener("submit", async (e) => {
        e.preventDefault();
        const modelName = selectedModel();
        if (!modelName) return toast("Select or enter a model name.", "err");
        let requestOptions = f.request_options.value.trim() || "{}";
        try {
          const parsed = JSON.parse(requestOptions);
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
          requestOptions = JSON.stringify(parsed);
        } catch (err) {
          return toast("Advanced options must be a valid JSON object.", "err");
        }
        const body = {
          llm_base_url: f.llm_base_url.value,
          model_name: modelName,
          system_prompt: f.system_prompt.value,
          request_options: requestOptions,
        };
        if (f.api_key.value) body.api_key = f.api_key.value;
        const r = await api("/api/admin/config/", body);
        toast(r.error ? r.error : "Configuration saved.", r.error ? "err" : "ok");
        if (!r.error) {
          modelSelect.dataset.current = modelName;
          f.request_options.value = requestOptions;
          f.api_key.value = "";
        }
        loadWidgets();
      });
    }

    const tenantForm = $("#tenant-form");
    if (tenantForm) {
      tenantForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = tenantForm;
        const r = await api("/api/admin/tenant/", {
          business_name: f.business_name.value,
          username: f.username.value,
          password: f.password.value,
        });
        if (r.error) return toast(r.error, "err");
        f.reset();
        toast("Business account created.", "ok");
        loadWidgets();
      });
    }

    const assistantForm = $("#assistant-form");
    if (assistantForm) {
      assistantForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const r = await api("/api/tenant/settings/", {
          greeting: assistantForm.greeting.value,
          commands: parseCommandLines(assistantForm.commands.value),
        });
        toast(r.error ? r.error : "Assistant settings saved.", r.error ? "err" : "ok");
      });
    }

    const profileForm = $("#profile-form");
    if (profileForm) {
      profileForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const r = await api("/api/tenant/settings/", {
          business_name: profileForm.business_name.value,
        });
        if (r.error) return toast(r.error, "err");
        toast("Profile saved. Refresh to update the header.", "ok");
      });
    }

    const accountForm = $("#account-form");
    if (accountForm) {
      accountForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const f = accountForm;
        const r = await api("/api/account/update/", {
          username: f.username.value,
          current_password: f.current_password.value,
          new_password: f.new_password.value,
        });
        if (r.error) return toast(r.error, "err");
        toast(r.changed ? "Account updated." : "No changes to save.", "ok");
        f.current_password.value = "";
        f.new_password.value = "";
        closeAccountDrawer();
      });
      $("#account-close").addEventListener("click", closeAccountDrawer);
      const backdrop = $("#drawer-backdrop");
      if (backdrop) backdrop.addEventListener("click", closeAccountDrawer);
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeAccountDrawer();
      });
    }

    const confirmBtn = $("#cancel-confirm");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", async () => {
        const id = cancelOrderId;
        if (!id) return;
        confirmBtn.disabled = true;
        const r = await api(`/api/order/${id}/action/`, {
          action: "CANCELLED",
          note: $("#cancel-note").value,
        });
        confirmBtn.disabled = false;
        if (r.error) return toast(r.error, "err");
        closeCancelDrawer();
        toast(`Order #${id} cancelled. Reserved stock restored.`, "ok");
        if (r.warning) toast(r.warning, "err");
        loadWidgets();
      });
      $("#cancel-close").addEventListener("click", closeCancelDrawer);
      $("#drawer-backdrop").addEventListener("click", closeCancelDrawer);
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && cancelOrderId) closeCancelDrawer();
      });
    }

    const orderDrawerClose = $("#order-drawer-close");
    if (orderDrawerClose) {
      orderDrawerClose.addEventListener("click", closeOrderDrawer);
      const backdrop = $("#drawer-backdrop");
      if (backdrop) backdrop.addEventListener("click", closeOrderDrawer);
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && activeDetailOrderId) closeOrderDrawer();
      });
    }
  }

  async function loadCouriers() {
    const form = $("#couriers-form");
    if (!form) return;
    try {
      const res = await fetch("/api/tenant/couriers/");
      const data = await res.json();
      if (!data.ok || !data.couriers) return;
      const pt = data.couriers.pathao || {};

      if (form.pathao_enabled) form.pathao_enabled.checked = !!pt.enabled;
      if (form.pathao_environment) form.pathao_environment.value = pt.environment || "sandbox";
      if (form.pathao_store_id) form.pathao_store_id.value = pt.store_id || "";
      if (form.pathao_client_id) form.pathao_client_id.value = pt.client_id || "";
      if (form.pathao_client_secret) {
        form.pathao_client_secret.value = "";
        form.pathao_client_secret.placeholder = pt.has_client_secret ? "•••••• (saved)" : "Pathao Client Secret";
      }
      if (form.pathao_username) form.pathao_username.value = pt.username || "";
      if (form.pathao_password) {
        form.pathao_password.value = "";
        form.pathao_password.placeholder = pt.has_password ? "•••••• (saved)" : "Pathao account password";
      }

      const ptBadge = $("#pathao-status-badge");
      if (ptBadge) {
        if (pt.enabled && pt.client_id && pt.has_client_secret && pt.username && pt.has_password && Number(pt.store_id) > 0) {
          ptBadge.className = "badge connected";
          ptBadge.textContent = pt.environment === "production" ? "Pathao: Live" : "Pathao: Sandbox";
        } else if (pt.enabled) {
          ptBadge.className = "badge";
          ptBadge.textContent = "Pathao: Complete your settings";
        } else {
          ptBadge.className = "badge";
          ptBadge.textContent = "Manual delivery";
        }
      }
    } catch (e) {
      // ignore
    }
  }

  function bindCouriers() {
    const form = $("#couriers-form");
    if (!form) return;

    loadCouriers();

    document.addEventListener("nexora:tab", (e) => {
      if (e.detail && e.detail.tab === "settings") {
        loadCouriers();
      }
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const saveBtn = $("#btn-save-couriers");
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = "Saving…";
      }
      const payload = {
        pathao: {
          enabled: form.pathao_enabled.checked,
          environment: form.pathao_environment.value,
          store_id: form.pathao_store_id.value,
          client_id: form.pathao_client_id.value,
          client_secret: form.pathao_client_secret.value,
          username: form.pathao_username.value,
          password: form.pathao_password.value,
        },
      };

      const res = await api("/api/tenant/couriers/", payload);
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = "Save shipping settings";
      }
      if (res.error) return toast(res.error, "err");
      toast("Shipping settings saved.", "ok");
      loadCouriers();
    });

    const testPtBtn = $("#btn-test-pathao");
    if (testPtBtn) {
      testPtBtn.addEventListener("click", async () => {
        const statusEl = $("#pt-test-status");
        testPtBtn.disabled = true;
        testPtBtn.textContent = "Testing…";
        if (statusEl) {
          statusEl.className = "courier-test-status muted small";
          statusEl.textContent = "Connecting to Pathao…";
        }
        const res = await api("/api/courier/test/", {
          environment: form.pathao_environment.value,
          store_id: form.pathao_store_id.value,
          client_id: form.pathao_client_id.value,
          client_secret: form.pathao_client_secret.value,
          username: form.pathao_username.value,
          password: form.pathao_password.value,
        });
        testPtBtn.disabled = false;
        testPtBtn.textContent = "Test connection";
        if (res.ok) {
          if (statusEl) {
            statusEl.className = "courier-test-status ok small";
            statusEl.textContent = res.message || "Connected successfully.";
            if (res.stores?.length) {
              statusEl.textContent += " " + res.stores.map(store => `${store.store_name} (ID: ${store.store_id})`).join(", ");
            }
          }
          toast(res.message || "Pathao connected successfully.", "ok");
        } else {
          const err = res.error || "Could not connect to Pathao.";
          if (statusEl) {
            statusEl.className = "courier-test-status err small";
            statusEl.textContent = err;
          }
          toast(err, "err");
        }
      });
    }

    const accountShippingBtn = $("#account-open-shipping");
    if (accountShippingBtn) {
      accountShippingBtn.addEventListener("click", () => {
        closeAccountDrawer();
        const settingsTabBtn = $('[data-tab="settings"]');
        if (settingsTabBtn) settingsTabBtn.click();
        setTimeout(() => {
          const card = $("#shipping-settings-card");
          if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 120);
      });
    }
  }

  bindTabs();
  bindForms();
  bindCouriers();
  loadWidgets();
  if ($("#wa-status")) {
    $("#wa-connect").addEventListener("click", async () => {
      $("#wa-connect").disabled = true;
      const result = await api("/api/wa/connect/", {});
      if (result.error) toast(result.error, "err");
      await pollWa();
    });
    pollWa();
    setInterval(() => { if (!document.hidden) pollWa(); }, 5000);
  }
})();
