/* UrBG Remover - dashboard */
(function () {
  "use strict";

  const state = {
    csrf: null,
    username: "admin",
    file: null,
    result: null,
    resultMime: "image/png",
    resultName: "result.png",
    overview: null,
    docs: null,
    integrations: null,
  };

  const $ = (id) => document.getElementById(id);
  const $$ = (selector, root) => Array.prototype.slice.call((root || document).querySelectorAll(selector));

  const SECTION_META = {
    overview: ["Overview", "Service health and usage at a glance"],
    remover: ["Background Remover", "Upload an image and remove its background with AI"],
    keys: ["API Keys", "Create and manage keys for the public REST API"],
    docs: ["API Documentation", "Every endpoint, parameter and error code"],
    integrations: ["Integrations", "Drop-in examples for PHP, JavaScript, React, Flutter and Python"],
    stats: ["Usage Statistics", "Request volume, traffic and the raw request log"],
    settings: ["Settings", "Processing defaults, environment and session"],
  };

  // ------------------------------------------------------------ helpers --
  function escapeHtml(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatNumber(value) {
    const number = Number(value || 0);
    if (number >= 1_000_000) return (number / 1_000_000).toFixed(1) + "M";
    if (number >= 1_000) return (number / 1_000).toFixed(1) + "k";
    return number.toLocaleString();
  }

  function formatBytes(bytes) {
    const value = Number(bytes || 0);
    if (value < 1024) return value + " B";
    if (value < 1024 * 1024) return (value / 1024).toFixed(1) + " KB";
    if (value < 1024 * 1024 * 1024) return (value / (1024 * 1024)).toFixed(2) + " MB";
    return (value / (1024 * 1024 * 1024)).toFixed(2) + " GB";
  }

  function formatDate(value) {
    if (!value) return "Never";
    const date = new Date(value);
    if (isNaN(date.getTime())) return "Never";
    return date.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function toast(title, message, type) {
    const stack = $("toast-stack");
    if (!stack) return;
    const node = document.createElement("div");
    node.className = "toast " + (type || "");
    node.innerHTML =
      "<div><strong>" + escapeHtml(title) + "</strong><span>" + escapeHtml(message || "") + "</span></div>";
    stack.appendChild(node);
    setTimeout(function () {
      node.style.opacity = "0";
      node.style.transform = "translateX(16px)";
      node.style.transition = "opacity .2s ease, transform .2s ease";
      setTimeout(function () {
        node.remove();
      }, 220);
    }, 4200);
  }

  async function api(path, options) {
    const settings = Object.assign({ method: "GET", headers: {} }, options || {});
    settings.headers = Object.assign({}, settings.headers);
    if (settings.body && typeof settings.body !== "string") {
      settings.headers["Content-Type"] = "application/json";
      settings.body = JSON.stringify(settings.body);
    }
    const method = settings.method.toUpperCase();
    if (method !== "GET" && method !== "HEAD" && state.csrf) {
      settings.headers["X-CSRF-Token"] = state.csrf;
    }
    settings.credentials = "same-origin";

    let response;
    try {
      response = await fetch(path, settings);
    } catch (err) {
      throw new Error("Network error - the server could not be reached.");
    }

    if (response.status === 401 && !path.endsWith("/login")) {
      window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
      throw new Error("Session expired.");
    }

    let payload = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      payload = await response.json().catch(function () {
        return null;
      });
    }

    if (!response.ok) {
      const message =
        (payload && payload.error && payload.error.message) ||
        (payload && payload.message) ||
        "Request failed (" + response.status + ")";
      const error = new Error(message);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  async function copyToClipboard(text, successMessage) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const helper = document.createElement("textarea");
        helper.value = text;
        helper.style.position = "fixed";
        helper.style.opacity = "0";
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        helper.remove();
      }
      if (successMessage) toast("Copied", successMessage, "success");
      return true;
    } catch (err) {
      toast("Copy failed", "Select the text and copy it manually.", "error");
      return false;
    }
  }

  // ----------------------------------------------------------- routing --
  function showSection(name) {
    if (!SECTION_META[name]) name = "overview";
    $$(".section").forEach(function (node) {
      node.classList.toggle("active", node.id === "section-" + name);
    });
    $$(".nav-item").forEach(function (node) {
      node.classList.toggle("active", node.getAttribute("data-section") === name);
    });
    $("page-title").textContent = SECTION_META[name][0];
    $("page-subtitle").textContent = SECTION_META[name][1];
    if (window.location.hash !== "#" + name) {
      history.replaceState(null, "", "#" + name);
    }
    closeSidebar();
    loadSection(name);
  }

  function closeSidebar() {
    $("sidebar").classList.remove("open");
    $("sidebar-backdrop").classList.remove("show");
  }

  async function loadSection(name) {
    try {
      if (name === "overview") await loadOverview();
      else if (name === "keys") await loadKeys();
      else if (name === "docs") await loadDocs();
      else if (name === "integrations") await loadIntegrations();
      else if (name === "stats") await loadStats();
      else if (name === "settings") await loadSettings();
      else if (name === "remover") await loadRemoverSettings();
    } catch (err) {
      toast("Error", err.message, "error");
    }
  }

  // ---------------------------------------------------------- overview --
  async function loadOverview() {
    const data = await api("/admin/api/overview");
    state.overview = data;
    const stats = data.stats || {};

    $("stat-images").textContent = formatNumber(stats.images_processed);
    $("stat-images-meta").textContent = stats.requests_last_24h
      ? formatNumber(stats.requests_last_24h) + " requests in the last 24 h"
      : "All time";
    $("stat-requests").textContent = formatNumber(stats.total_requests);
    $("stat-requests-meta").textContent =
      formatNumber(stats.successful_requests) + " successful · " + formatNumber(stats.failed_requests) + " failed";
    $("stat-keys").textContent = formatNumber(stats.active_keys);
    $("stat-keys-meta").textContent = formatNumber(stats.total_keys) + " keys created in total";
    $("stat-duration").textContent = stats.avg_duration_ms ? stats.avg_duration_ms + " ms" : "—";

    const server = data.server || {};
    $("server-details").innerHTML =
      "<div class='kv'><span>Service</span><span>" + escapeHtml(server.app_name || "UrBG Remover") + "</span></div>" +
      "<div class='kv'><span>Version</span><span>" + escapeHtml(server.version || "—") + "</span></div>" +
      "<div class='kv'><span>Environment</span><span>" + escapeHtml(server.environment || "—") + "</span></div>" +
      "<div class='kv'><span>Base URL</span><span class='mono'>" + escapeHtml(server.base_url || "—") + "</span></div>" +
      "<div class='kv'><span>Max upload</span><span>" + escapeHtml((data.runtime && data.runtime.max_upload_mb) || "—") + " MB</span></div>" +
      "<div class='kv'><span>Uptime</span><span>Since start of this instance</span></div>";

    renderEngine(data.engine || {});
    renderRequestTable($("overview-requests"), data.recent_requests || [], true);
    updateEnginePill(data.engine || {});
  }

  function renderEngine(engine) {
    const ready = !!engine.ready;
    $("engine-details").innerHTML =
      "<div class='kv'><span>Model</span><span class='mono'>" + escapeHtml(engine.model || "—") + "</span></div>" +
      "<div class='kv'><span>Provider</span><span class='mono'>" + escapeHtml(engine.provider || "—") + "</span></div>" +
      "<div class='kv'><span>Status</span><span>" +
        (ready
          ? "<span class='pill success'><span class='dot'></span> Loaded</span>"
          : "<span class='pill warning'><span class='dot'></span> Not loaded</span>") +
      "</span></div>" +
      "<div class='kv'><span>Load time</span><span>" + (engine.load_ms ? engine.load_ms + " ms" : "—") + "</span></div>" +
      "<div class='kv'><span>Loaded at</span><span>" + escapeHtml(formatDate(engine.loaded_at)) + "</span></div>" +
      "<div class='kv'><span>Images processed</span><span>" + formatNumber(engine.processed || 0) + "</span></div>" +
      (engine.error
        ? "<div class='note warning' style='margin-top:12px'><strong>Engine error:</strong> " + escapeHtml(engine.error) + "</div>"
        : "");
  }

  function updateEnginePill(engine) {
    const pill = $("engine-pill");
    if (engine.ready) {
      pill.className = "pill success";
      pill.innerHTML = "<span class='dot'></span> Engine: " + escapeHtml(engine.model || "ready");
    } else if (engine.error) {
      pill.className = "pill danger";
      pill.innerHTML = "<span class='dot'></span> Engine: error";
    } else {
      pill.className = "pill warning";
      pill.innerHTML = "<span class='dot pulse'></span> Engine: loading";
    }
  }

  // ---------------------------------------------------------- requests --
  function renderRequestTable(container, rows, compact) {
    if (!rows || !rows.length) {
      container.innerHTML = "<div class='empty'>No requests recorded yet.</div>";
      return;
    }
    var html =
      "<div class='table-wrap'><table><thead><tr>" +
      "<th>When</th><th>Key</th><th>Endpoint</th><th>Status</th>" +
      (compact ? "" : "<th>Duration</th><th>Size</th>") +
      "</tr></thead><tbody>";
    rows.forEach(function (row) {
      var ok = Number(row.status_code) < 400;
      html +=
        "<tr><td class='dim'>" + escapeHtml(formatDate(row.created_at)) + "</td>" +
        "<td>" + escapeHtml(row.key_label || "—") + "</td>" +
        "<td class='mono'>" + escapeHtml(row.method + " " + row.endpoint) + "</td>" +
        "<td><span class='pill " + (ok ? "success" : "danger") + "'>" + escapeHtml(row.status_code) + "</span></td>" +
        (compact ? "" : "<td>" + escapeHtml((row.duration_ms || 0) + " ms") + "</td>" +
          "<td>" + escapeHtml(formatBytes(row.bytes_out)) + "</td>") +
        "</tr>";
    });
    html += "</tbody></table></div>";
    container.innerHTML = html;
  }

  // ----------------------------------------------------------- remover --
  async function loadRemoverSettings() {
    try {
      const data = await api("/admin/api/settings");
      $("remover-hint").textContent =
        "JPG, JPEG, PNG or WebP — maximum " + (data.runtime.max_upload_mb || 5) + " MB";
      $("remover-format").value = data.runtime.default_output_format || "png";
      $("remover-matting").checked = !!data.runtime.alpha_matting;
      $("remover-postprocess").checked = !!data.runtime.post_process_mask;
    } catch (err) {
      /* non fatal */
    }
  }

  function selectFile(file) {
    if (!file) return;
    if (!/^image\/(jpeg|png|webp)$/.test(file.type) && !/\.(jpe?g|png|webp)$/i.test(file.name)) {
      toast("Unsupported file", "Use a JPG, PNG or WebP image.", "error");
      return;
    }
    state.file = file;
    state.result = null;

    const reader = new FileReader();
    reader.onload = function (event) {
      $("original-image").src = event.target.result;
      $("original-size").textContent = formatBytes(file.size);
    };
    reader.readAsDataURL(file);

    $("file-meta").hidden = false;
    $("file-name").textContent = file.name;
    $("file-size").textContent = formatBytes(file.size);
    $("file-dimensions").textContent = "Dimensions loaded on preview";
    $("remove-button").disabled = false;
    $("reset-button").disabled = false;
    $("preview-grid").hidden = false;
    $("remover-empty").hidden = true;
    $("result-actions").hidden = true;
    $("result-meta").hidden = true;
    $("result-image").removeAttribute("src");
  }

  async function runRemoval() {
    if (!state.file) return;
    const button = $("remove-button");
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span> Processing…';
    $("remover-progress").hidden = false;

    const params = new URLSearchParams();
    params.set("format", $("remover-format").value);
    params.set("alpha_matting", $("remover-matting").checked ? "true" : "false");
    params.set("post_process_mask", $("remover-postprocess").checked ? "true" : "false");

    const form = new FormData();
    form.append("file", state.file);

    try {
      const response = await fetch("/admin/api/remove?" + params.toString(), {
        method: "POST",
        body: form,
        credentials: "same-origin",
        headers: state.csrf ? { "X-CSRF-Token": state.csrf } : {},
      });

      if (response.status === 401) {
        window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
        return;
      }

      const payload = await response.json().catch(function () {
        return null;
      });
      if (!response.ok || !payload || !payload.image) {
        throw new Error(
          (payload && payload.error && payload.error.message) || "Background removal failed."
        );
      }

      const mime = payload.content_type || "image/png";
      state.resultMime = mime;
      state.result = payload.image;
      const ext = mime === "image/webp" ? "webp" : mime === "image/jpeg" ? "jpg" : "png";
      state.resultName =
        (state.file.name.replace(/\.[^.]+$/, "") || "image") + "-transparent." + ext;

      $("result-image").src = "data:" + mime + ";base64," + payload.image;
      $("result-size").textContent = formatBytes(payload.duration_ms ? payload.duration_ms : 0) + " ms";
      $("result-meta").hidden = false;
      $("result-meta").textContent =
        (payload.input ? payload.input.width + "×" + payload.input.height : "") +
        (payload.duration_ms ? " · " + payload.duration_ms + " ms" : "");
      $("result-actions").hidden = false;
      toast("Background removed", "Processed in " + payload.duration_ms + " ms.", "success");
      await loadOverview();
    } catch (err) {
      toast("Processing failed", err.message, "error");
    } finally {
      button.disabled = false;
      button.textContent = "Remove background";
      $("remover-progress").hidden = true;
    }
  }

  function downloadResult() {
    if (!state.result) return;
    const link = document.createElement("a");
    link.href = "data:" + state.resultMime + ";base64," + state.result;
    link.download = state.resultName;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function copyResult() {
    if (!state.result) return;
    try {
      const response = await fetch("data:" + state.resultMime + ";base64," + state.result);
      const blob = await response.blob();
      if (navigator.clipboard && window.ClipboardItem && window.isSecureContext) {
        await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
        toast("Copied", "The transparent image is on your clipboard.", "success");
        return;
      }
      toast("Not supported", "This browser cannot copy images - use Download instead.", "warning");
    } catch (err) {
      toast("Copy failed", "Use the Download button instead.", "error");
    }
  }

  function resetRemover() {
    state.file = null;
    state.result = null;
    $("file-input").value = "";
    $("file-meta").hidden = true;
    $("preview-grid").hidden = true;
    $("remover-empty").hidden = false;
    $("result-actions").hidden = true;
    $("result-meta").hidden = true;
    $("remove-button").disabled = true;
    $("reset-button").disabled = true;
  }

  // -------------------------------------------------------------- keys --
  async function loadKeys() {
    const data = await api("/admin/api/keys");
    renderKeys(data.keys || []);
  }

  function renderKeys(keys) {
    const container = $("keys-table");
    if (!keys.length) {
      container.innerHTML =
        "<div class='empty'>No API keys yet. Generate one above to start calling the API.</div>";
      return;
    }
    var html =
      "<div class='table-wrap'><table><thead><tr>" +
      "<th>Name</th><th>Key</th><th>Created</th><th>Last used</th><th>Requests</th><th>Images</th><th>Status</th><th></th>" +
      "</tr></thead><tbody>";
    keys.forEach(function (key) {
      html +=
        "<tr>" +
        "<td><strong>" + escapeHtml(key.name) + "</strong></td>" +
        "<td class='mono'>" + escapeHtml(key.key_prefix) + "…" + escapeHtml(key.key_last4) + "</td>" +
        "<td class='dim'>" + escapeHtml(formatDate(key.created_at)) + "</td>" +
        "<td class='dim'>" + escapeHtml(formatDate(key.last_used_at)) + "</td>" +
        "<td>" + formatNumber(key.request_count) + "</td>" +
        "<td>" + formatNumber(key.image_count) + "</td>" +
        "<td>" +
          (key.revoked
            ? "<span class='pill danger'><span class='dot'></span> Revoked</span>"
            : "<span class='pill success'><span class='dot'></span> Active</span>") +
        "</td>" +
        "<td><div class='btn-row'>" +
          (key.revoked
            ? "<button class='btn btn-sm' data-restore='" + key.id + "'>Restore</button>"
            : "<button class='btn btn-sm btn-danger' data-revoke='" + key.id + "'>Revoke</button>") +
          "<button class='btn btn-sm btn-ghost' data-delete='" + key.id + "'>Delete</button>" +
        "</div></td>" +
        "</tr>";
    });
    html += "</tbody></table></div>";
    container.innerHTML = html;

    $$("[data-revoke]", container).forEach(function (button) {
      button.addEventListener("click", async function () {
        if (!window.confirm("Revoke this API key? Requests using it will start failing.")) return;
        try {
          await api("/admin/api/keys/" + button.getAttribute("data-revoke") + "/revoke", { method: "POST" });
          toast("Key revoked", "The key can no longer be used.", "success");
          loadKeys();
        } catch (err) {
          toast("Error", err.message, "error");
        }
      });
    });

    $$("[data-restore]", container).forEach(function (button) {
      button.addEventListener("click", async function () {
        try {
          await api("/admin/api/keys/" + button.getAttribute("data-restore") + "/restore", { method: "POST" });
          toast("Key restored", "The key works again.", "success");
          loadKeys();
        } catch (err) {
          toast("Error", err.message, "error");
        }
      });
    });

    $$("[data-delete]", container).forEach(function (button) {
      button.addEventListener("click", async function () {
        if (!window.confirm("Delete this key permanently?")) return;
        try {
          await api("/admin/api/keys/" + button.getAttribute("data-delete"), { method: "DELETE" });
          toast("Key deleted", "The key was removed.", "success");
          loadKeys();
        } catch (err) {
          toast("Error", err.message, "error");
        }
      });
    });
  }

  async function createKey() {
    const name = $("key-name").value.trim() || "Untitled key";
    try {
      const created = await api("/admin/api/keys", { method: "POST", body: { name: name } });
      $("key-name").value = "";
      $("new-key").hidden = false;
      $("new-key").innerHTML =
        "<div class='key-reveal'><p>Copy this key now — it is never shown again.</p>" +
        "<div class='badge-key' id='revealed-key'>" + escapeHtml(created.key) +
        "<button class='btn btn-sm' id='copy-revealed-key'>Copy</button></div></div>";
      $("copy-revealed-key").addEventListener("click", function () {
        copyToClipboard(created.key, "API key copied to the clipboard.");
      });
      toast("API key created", "Copy it now - it cannot be shown again.", "success");
      loadKeys();
    } catch (err) {
      toast("Error", err.message, "error");
    }
  }

  // -------------------------------------------------------------- docs --
  async function loadDocs() {
    if (!state.docs) state.docs = await api("/admin/api/docs");
    $("docs-base-url").textContent = "Base URL: " + state.docs.base_url;
    const container = $("docs-list");
    container.innerHTML = state.docs.endpoints
      .map(function (endpoint) {
        var query = "";
        if (endpoint.query && endpoint.query.length) {
          query =
            "<table style='margin-top:10px'><thead><tr><th>Query</th><th>Type</th><th>Default</th><th>Description</th></tr></thead><tbody>" +
            endpoint.query
              .map(function (q) {
                return (
                  "<tr><td class='mono'>" + escapeHtml(q.name) + "</td><td class='dim'>" + escapeHtml(q.type) +
                  "</td><td class='dim'>" + escapeHtml(q.default) + "</td><td class='muted'>" + escapeHtml(q.description) + "</td></tr>"
                );
              })
              .join("") +
            "</tbody></table>";
        }
        var body = "";
        if (endpoint.body && typeof endpoint.body === "object") {
          body =
            "<table style='margin-top:10px'><thead><tr><th>Field</th><th>Description</th></tr></thead><tbody>" +
            Object.keys(endpoint.body)
              .map(function (field) {
                return "<tr><td class='mono'>" + escapeHtml(field) + "</td><td class='muted'>" + escapeHtml(endpoint.body[field]) + "</td></tr>";
              })
              .join("") +
            "</tbody></table>";
        } else if (endpoint.body) {
          body = "<p class='muted' style='margin-top:8px'><strong>Body:</strong> " + escapeHtml(endpoint.body) + "</p>";
        }
        return (
          "<div class='card' style='margin-bottom:14px'>" +
          "<div class='card-header' style='margin-bottom:10px'>" +
          "<div style='display:flex;align-items:center;gap:10px;flex-wrap:wrap'>" +
          "<span class='pill neutral mono'>" + escapeHtml(endpoint.method) + "</span>" +
          "<span class='mono' style='font-size:14px'>" + escapeHtml(endpoint.path) + "</span>" +
          "<span class='pill " + (endpoint.auth === "None" ? "neutral" : "success") + "'>" +
          (endpoint.auth === "None" ? "Public" : "API key required") + "</span>" +
          "</div>" +
          "<button class='btn btn-sm' data-copy-endpoint>Copy example</button>" +
          "</div>" +
          "<p style='margin:0 0 6px'><strong>" + escapeHtml(endpoint.summary) + "</strong></p>" +
          "<p class='muted' style='margin:0 0 6px'>" + escapeHtml(endpoint.description) + "</p>" +
          "<p class='dim' style='margin:0'>Response: " + escapeHtml(endpoint.response) + "</p>" +
          query +
          body +
          "<div class='code-block' style='margin-top:12px'><pre><code>" + escapeHtml(endpoint.example) + "</code></pre></div>" +
          "</div>"
        );
      })
      .join("");

    $$("[data-copy-endpoint]", container).forEach(function (button, index) {
      button.addEventListener("click", function () {
        copyToClipboard(state.docs.endpoints[index].example, "Example copied.");
      });
    });

    if (!container.dataset.errors) {
      container.dataset.errors = "1";
    }
  }

  // ------------------------------------------------------ integrations --
  async function loadIntegrations() {
    if (!state.integrations) state.integrations = await api("/admin/api/integrations");
    const items = state.integrations.integrations || [];
    const tabs = $("integration-tabs");
    const panels = $("integration-panels");

    tabs.innerHTML = items
      .map(function (item, index) {
        return "<button class='tab" + (index === 0 ? " active" : "") + "' data-tab='" + index + "'>" + escapeHtml(item.title) + "</button>";
      })
      .join("");

    panels.innerHTML = items
      .map(function (item, index) {
        var notes = "";
        if (item.notes && item.notes.length) {
          notes =
            "<ul class='inline-list'>" + item.notes.map(function (n) { return "<li>" + escapeHtml(n) + "</li>"; }).join("") + "</ul>";
        }
        return (
          "<div class='tab-panel" + (index === 0 ? " active" : "") + "' data-panel='" + index + "'>" +
          "<div class='kv'><span>Endpoint</span><span class='mono'>" + escapeHtml(item.endpoint) + "</span></div>" +
          "<div class='kv'><span>Authentication</span><span class='mono'>" + escapeHtml(item.auth_header) + "</span></div>" +
          notes +
          "<div class='code-block' style='margin-top:14px'>" +
          "<button class='btn btn-sm copy-btn' data-copy-code='" + index + "'>Copy</button>" +
          "<pre><code>" + escapeHtml(item.code) + "</code></pre></div>" +
          "</div>"
        );
      })
      .join("");

    $$("[data-tab]", tabs).forEach(function (tab) {
      tab.addEventListener("click", function () {
        const index = tab.getAttribute("data-tab");
        $$("[data-tab]", tabs).forEach(function (t) { t.classList.toggle("active", t === tab); });
        $$("[data-panel]", panels).forEach(function (p) {
          p.classList.toggle("active", p.getAttribute("data-panel") === index);
        });
      });
    });

    $$("[data-copy-code]", panels).forEach(function (button) {
      button.addEventListener("click", function () {
        const item = items[Number(button.getAttribute("data-copy-code"))];
        copyToClipboard(item.code, item.title + " example copied.");
      });
    });
  }

  // ------------------------------------------------------------- stats --
  async function loadStats() {
    const days = Number($("chart-range").value || 30);
    const data = await api("/admin/api/usage?days=" + days);
    const daily = data.daily || [];

    const requests = daily.reduce(function (sum, d) { return sum + d.requests; }, 0);
    const success = daily.reduce(function (sum, d) { return sum + d.success; }, 0);
    const failed = daily.reduce(function (sum, d) { return sum + d.failed; }, 0);
    const bytes = daily.reduce(function (sum, d) { return sum + d.bytes_out; }, 0);

    $("stat-period-requests").textContent = formatNumber(requests);
    $("stat-period-success").textContent = formatNumber(success);
    $("stat-period-failed").textContent = formatNumber(failed);
    $("stat-period-bytes").textContent = formatBytes(bytes);
    $("chart-period-label").textContent = "Last " + days + " days";

    var max = 0;
    daily.forEach(function (d) { if (d.requests > max) max = d.requests; });
    if (max === 0) max = 1;

    $("usage-chart").innerHTML = daily
      .map(function (d) {
        var height = Math.round((d.requests / max) * 100);
        return (
          "<div class='chart-col' title='" + escapeHtml(d.day) + ": " + d.requests + " requests'>" +
          "<div class='chart-bar' style='height:" + Math.max(height, 1) + "%'></div></div>"
        );
      })
      .join("");

    var labels = daily.map(function (d) {
      var parts = d.day.split("-");
      return "<span>" + escapeHtml(parts[1] + "/" + parts[2]) + "</span>";
    });
    $("chart-labels").innerHTML = labels.join("");

    var endpoints = data.endpoints || [];
    if (!endpoints.length) {
      $("endpoint-breakdown").innerHTML = "<div class='empty'>No endpoint traffic recorded yet.</div>";
    } else {
      var maxEndpoint = endpoints.reduce(function (max, e) { return Math.max(max, e.requests); }, 0) || 1;
      $("endpoint-breakdown").innerHTML = endpoints
        .map(function (endpoint) {
          var pct = Math.round((endpoint.requests / maxEndpoint) * 100);
          return (
            "<div style='margin-bottom:12px'><div class='kv' style='border:none;padding:0 0 4px 0'>" +
            "<span class='mono'>" + escapeHtml(endpoint.endpoint) + "</span>" +
            "<span>" + formatNumber(endpoint.requests) + " req · " + escapeHtml((endpoint.avg_ms || 0) + " ms") + "</span></div>" +
            "<div class='usage-bar'><span style='width:" + pct + "%'></span></div></div>"
          );
        })
        .join("");
    }

    renderRequestTable($("recent-requests"), data.recent || [], false);
  }

  // ---------------------------------------------------------- settings --
  async function loadSettings() {
    const data = await api("/admin/api/settings");

    $("setting-upload").value = data.runtime.max_upload_mb;
    $("setting-matting").checked = !!data.runtime.alpha_matting;
    $("setting-postprocess").checked = !!data.runtime.post_process_mask;
    $("setting-format").value = data.runtime.default_output_format || "png";

    var select = $("setting-model");
    select.innerHTML = (data.available_models || [])
      .map(function (model) {
        return "<option value='" + escapeHtml(model.id) + "'" + (model.id === data.runtime.default_model ? " selected" : "") + ">" + escapeHtml(model.label) + "</option>";
      })
      .join("");

    var env = data.environment || {};
    $("env-details").innerHTML =
      "<div class='kv'><span>Application</span><span>" + escapeHtml(env.app_name || "—") + "</span></div>" +
      "<div class='kv'><span>Version</span><span>" + escapeHtml(env.version || "—") + "</span></div>" +
      "<div class='kv'><span>Environment</span><span>" + escapeHtml(env.environment || "—") + "</span></div>" +
      "<div class='kv'><span>Base URL</span><span class='mono'>" + escapeHtml(env.base_url || "—") + "</span></div>" +
      "<div class='kv'><span>Max upload</span><span>" + escapeHtml(env.max_upload_mb || "—") + " MB</span></div>" +
      "<div class='kv'><span>Max dimension</span><span>" + escapeHtml(env.max_dimension || "—") + " px</span></div>" +
      "<div class='kv'><span>Session lifetime</span><span>" + escapeHtml(env.session_max_age_minutes || "—") + " min</span></div>" +
      "<div class='kv'><span>API rate limit</span><span>" +
        (env.api_rate_limit_per_minute ? env.api_rate_limit_per_minute + " req/min" : "disabled") + "</span></div>";

    renderEngine(data.engine || {});
  }

  async function saveSettings() {
    const model = $("setting-model").value;
    const payload = {
      max_upload_mb: Number($("setting-upload").value),
      default_output_format: $("setting-format").value,
      alpha_matting: $("setting-matting").checked,
      post_process_mask: $("setting-postprocess").checked,
    };
    try {
      await api("/admin/api/settings", { method: "PUT", body: payload });
      toast("Settings saved", "The new defaults are active.", "success");
      if (model !== state.overview?.runtime?.default_model) {
        await api("/admin/api/engine/model", { method: "POST", body: { model: model } });
        toast("Model updated", "The " + model + " model is being loaded.", "success");
      }
      loadSettings();
      loadOverview();
    } catch (err) {
      toast("Error", err.message, "error");
    }
  }

  async function warmup() {
    const button = $("warmup-button");
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span> Loading';
    try {
      const result = await api("/admin/api/engine/warmup", { method: "POST" });
      toast(
        result.success ? "Model ready" : "Model unavailable",
        result.success ? "The AI model is loaded and ready." : "Check the engine details.",
        result.success ? "success" : "error"
      );
      loadOverview();
    } catch (err) {
      toast("Error", err.message, "error");
    } finally {
      button.disabled = false;
      button.textContent = "Pre-load model";
    }
  }

  async function logout() {
    try {
      await api("/admin/api/logout", { method: "POST" });
    } catch (err) {
      /* ignore - redirect anyway */
    }
    window.location.href = "/login";
  }

  // ------------------------------------------------------------- bind ---
  function bindEvents() {
    $$(".nav-item").forEach(function (item) {
      item.addEventListener("click", function () {
        showSection(item.getAttribute("data-section"));
      });
    });

    $$("[data-goto]").forEach(function (item) {
      item.addEventListener("click", function () {
        showSection(item.getAttribute("data-goto"));
      });
    });

    $("menu-toggle").addEventListener("click", function () {
      $("sidebar").classList.toggle("open");
      $("sidebar-backdrop").classList.toggle("show");
    });
    $("sidebar-backdrop").addEventListener("click", closeSidebar);

    $("logout-button").addEventListener("click", logout);
    $("logout-button-2").addEventListener("click", logout);

    $("refresh-button").addEventListener("click", function () {
      loadSection(currentSection());
      toast("Refreshed", "The dashboard data is up to date.", "success");
    });

    $("warmup-button").addEventListener("click", warmup);

    // Remover
    const dropzone = $("dropzone");
    const fileInput = $("file-input");
    dropzone.addEventListener("click", function () { fileInput.click(); });
    dropzone.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        fileInput.click();
      }
    });
    fileInput.addEventListener("change", function () {
      if (fileInput.files && fileInput.files[0]) selectFile(fileInput.files[0]);
    });
    ["dragenter", "dragover"].forEach(function (name) {
      dropzone.addEventListener(name, function (event) {
        event.preventDefault();
        dropzone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (name) {
      dropzone.addEventListener(name, function (event) {
        event.preventDefault();
        dropzone.classList.remove("dragover");
      });
    });
    dropzone.addEventListener("drop", function (event) {
      if (event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0]) {
        selectFile(event.dataTransfer.files[0]);
      }
    });

    $("remove-button").addEventListener("click", runRemoval);
    $("reset-button").addEventListener("click", resetRemover);
    $("new-image-button").addEventListener("click", resetRemover);
    $("download-button").addEventListener("click", downloadResult);
    $("copy-image-button").addEventListener("click", copyResult);

    // Keys
    $("create-key-button").addEventListener("click", createKey);
    $("key-name").addEventListener("keydown", function (event) {
      if (event.key === "Enter") createKey();
    });
    $("copy-curl-button").addEventListener("click", function () {
      copyToClipboard($("key-usage-example").textContent, "curl example copied.");
    });

    // Stats
    $("chart-range").addEventListener("change", loadStats);

    // Settings
    $("save-settings-button").addEventListener("click", saveSettings);
    $("reload-model-button").addEventListener("click", async function () {
      try {
        await api("/admin/api/engine/warmup", { method: "POST" });
        toast("Model reloaded", "The AI model is ready.", "success");
        loadSettings();
      } catch (err) {
        toast("Error", err.message, "error");
      }
    });
  }

  function currentSection() {
    const hash = (window.location.hash || "").replace("#", "");
    return SECTION_META[hash] ? hash : "overview";
  }

  // ------------------------------------------------------------- boot ---
  async function boot() {
    bindEvents();
    try {
      const session = await api("/admin/api/session");
      if (!session.authenticated) {
        window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
        return;
      }
      state.csrf = session.csrf_token;
      state.username = session.username || "admin";
      $("user-name").textContent = state.username;
      $("user-avatar").textContent = state.username.charAt(0).toUpperCase();
      $("session-details").innerHTML =
        "<div class='kv'><span>Signed in as</span><span>" + escapeHtml(state.username) + "</span></div>" +
        "<div class='kv'><span>Signed in at</span><span>" + escapeHtml(formatDate(new Date(session.issued_at * 1000).toISOString())) + "</span></div>" +
        "<div class='kv'><span>Expires at</span><span>" + escapeHtml(formatDate(new Date(session.expires_at * 1000).toISOString())) + "</span></div>";
    } catch (err) {
      window.location.href = "/login";
      return;
    }

    window.addEventListener("hashchange", function () {
      showSection(currentSection());
    });

    showSection(currentSection());
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
