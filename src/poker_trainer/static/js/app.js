/* SPA router + login/main/create screens. Gameplay lives in table.js. */
(function () {
  "use strict";

  const app = document.getElementById("app");
  // The session cookie is the source of truth for identity; we cache the
  // fetched profile object for instant header rendering.
  const state = { user: null, bootstrapped: false };

  function screen(id) {
    const tpl = document.getElementById("screen-" + id);
    app.innerHTML = "";
    app.appendChild(tpl.content.cloneNode(true));
  }

  async function api(path, opts) {
    const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
    if (res.status === 204) return null;
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch {}
      const err = new Error(detail); err.status = res.status; throw err;
    }
    return res.json();
  }

  // Load the logged-in user from the session, once per page load.
  async function bootstrap() {
    try { state.user = await api("/api/auth/me"); }
    catch { state.user = null; }
    state.bootstrapped = true;
  }

  // ---------- screens ----------
  async function showLogin() {
    screen("login");
    const btn = document.getElementById("login-google");
    const err = document.getElementById("login-error");
    // Surface an OAuth error if Google bounced us back with one.
    const m = location.hash.match(/error=oauth/);
    if (m) { err.textContent = "Google sign-in failed. Please try again."; err.classList.remove("hidden"); }
    try {
      const cfg = await api("/api/auth/config");
      if (!cfg.google_enabled) {
        btn.disabled = true;
        document.getElementById("login-disabled").classList.remove("hidden");
      }
    } catch {}
    btn.onclick = () => { window.location.href = "/api/auth/google/login"; };
  }

  function renderProfileChip() {
    const av = document.getElementById("profile-avatar");
    if (state.user && state.user.avatar_url) { av.src = state.user.avatar_url; av.classList.remove("hidden"); }
    else if (av) av.classList.add("hidden");
    document.getElementById("profile-name").textContent =
      state.user ? (state.user.username || state.user.display_name) : "Guest";
  }

  async function showMain() {
    if (!state.user) { location.hash = "#/login"; return; }
    screen("main");
    renderProfileChip();
    document.getElementById("go-profile").onclick = () => (location.hash = "#/profile");
    document.getElementById("logout-btn").onclick = async () => {
      await api("/api/auth/logout", { method: "POST" });
      state.user = null; location.hash = "#/login";
    };
    document.getElementById("go-create").onclick = () => (location.hash = "#/create");
    const list = document.getElementById("games-list");
    try {
      const games = await api("/api/games");
      list.innerHTML = games.length
        ? games.map((g) => `<div class="muted">${g.game_id}</div>`).join("")
        : `<p class="muted">No games yet — your finished games will appear here (coming soon).</p>`;
    } catch (e) {
      list.innerHTML = `<p class="error">Could not load games: ${e.message}</p>`;
    }
  }

  function showCreate() {
    if (!state.user) { location.hash = "#/login"; return; }
    screen("create");
    const $ = (id) => document.getElementById(id);
    $("create-back").onclick = () => (location.hash = "#/");

    const sb = $("cfg-sb"), bb = $("cfg-bb");
    sb.addEventListener("input", () => { bb.value = (+sb.value || 0) * 2; }); // keep BB = 2*SB

    const random = $("cfg-random"), picker = $("styles-picker"), rows = $("styles-rows"), bots = $("cfg-bots");
    const STYLES = ["tag", "lag", "station", "rock"];
    function rebuildPicker() {
      picker.classList.toggle("hidden", random.checked);
      if (random.checked) return;
      const n = clamp(+bots.value, 1, 8);
      rows.innerHTML = "";
      for (let i = 0; i < n; i++) {
        const row = document.createElement("div");
        row.className = "styles-row";
        row.innerHTML = `<span class="tiny muted">Bot ${i + 1}</span>` +
          `<select data-bot="${i}">${STYLES.map((s) => `<option value="${s}">${s.toUpperCase()}</option>`).join("")}</select>`;
        rows.appendChild(row);
      }
    }
    random.addEventListener("change", rebuildPicker);
    bots.addEventListener("input", rebuildPicker);
    rebuildPicker();

    // --- quick-bet preset editors (separate preflop / postflop, up to 5 each) ---
    const preflopRows = $("preflop-rows"), postflopRows = $("postflop-rows");
    function addChip(container, value, suffix) {
      if (container.children.length >= 5) return;
      const chip = document.createElement("span");
      chip.className = "quick-chip";
      chip.innerHTML =
        `<input type="number" class="qv" min="0.1" step="0.5" value="${value}" />` +
        `<span class="qsfx">${suffix}</span>` +
        `<button type="button" class="qx" title="remove">✕</button>`;
      chip.querySelector(".qx").onclick = () => chip.remove();
      container.appendChild(chip);
    }
    [2, 2.5, 3, 4].forEach((v) => addChip(preflopRows, v, "× BB"));
    [33, 50, 75, 100].forEach((v) => addChip(postflopRows, v, "% Pot"));
    $("preflop-add").onclick = () => addChip(preflopRows, 3, "× BB");
    $("postflop-add").onclick = () => addChip(postflopRows, 50, "% Pot");
    const readChips = (c) => Array.from(c.querySelectorAll(".qv"))
      .map((i) => +i.value).filter((v) => v > 0);

    $("create-start").onclick = async () => {
      const err = $("create-error"); err.classList.add("hidden");
      const styles = random.checked ? null
        : Array.from(rows.querySelectorAll("select")).map((s) => s.value);
      const body = {
        num_bots: clamp(+bots.value, 1, 8),
        small_blind: +sb.value,
        big_blind: +bb.value,
        buy_in: +$("cfg-buyin").value,
        max_round: clamp(+$("cfg-rounds").value, 1, 500),
        randomize_styles: random.checked,
        hide_styles: $("cfg-hide").checked,
        styles,
        preflop_quick: readChips(preflopRows),
        postflop_quick: readChips(postflopRows),
        // Hero identity comes from the session on the server, not the client.
      };
      try {
        const res = await api("/api/games", { method: "POST", body: JSON.stringify(body) });
        sessionStorage.setItem("pt_ws_" + res.game_id, res.ws_url);
        location.hash = "#/table/" + res.game_id;
      } catch (e) {
        err.textContent = e.message; err.classList.remove("hidden");
      }
    };
  }

  function showTable(gameId) {
    if (!state.user) { location.hash = "#/login"; return; }
    screen("table");
    document.getElementById("leave-game").onclick = () => (location.hash = "#/");
    const wsUrl = sessionStorage.getItem("pt_ws_" + gameId) || `/ws/games/${gameId}`;
    window.PokerTable.mount(gameId, wsUrl);
  }

  async function showProfile() {
    if (!state.user) { location.hash = "#/login"; return; }
    screen("profile");
    const $ = (id) => document.getElementById(id);
    $("profile-back").onclick = () => (location.hash = "#/");

    let p;
    try { p = await api("/api/profile"); }
    catch (e) { if (e.status === 401) { location.hash = "#/login"; return; } throw e; }
    state.user = p;

    if (p.avatar_url) { $("pf-avatar").src = p.avatar_url; }
    $("pf-email").textContent = p.email + (p.email_verified ? " ✓" : "");
    $("pf-meta").textContent =
      `${p.status} · member since ${(p.created_at || "").slice(0, 10)}`;
    $("pf-display").value = p.display_name || "";
    $("pf-username").value = p.username || "";
    $("pf-bio").value = p.bio || "";
    $("pf-country").value = p.country || "";
    $("pf-timezone").value = p.timezone || "";
    $("pf-language").value = p.language || "";
    $("pf-avatar-url").value = p.avatar_url || "";

    $("pf-save").onclick = async () => {
      const err = $("pf-error"), ok = $("pf-saved");
      err.classList.add("hidden"); ok.classList.add("hidden");
      const body = {
        display_name: $("pf-display").value,
        username: $("pf-username").value.trim() || null,
        bio: $("pf-bio").value,
        country: $("pf-country").value.trim() || null,
        timezone: $("pf-timezone").value.trim() || null,
        language: $("pf-language").value.trim() || null,
        avatar_url: $("pf-avatar-url").value.trim() || null,
      };
      try {
        state.user = await api("/api/profile", { method: "PATCH", body: JSON.stringify(body) });
        ok.classList.remove("hidden");
      } catch (e) { err.textContent = e.message; err.classList.remove("hidden"); }
    };

    $("pf-delete").onclick = async () => {
      if (!confirm("Delete your account? Your games are kept but you'll be logged out.")) return;
      await api("/api/profile", { method: "DELETE" });
      state.user = null; location.hash = "#/login";
    };
  }

  function clamp(v, lo, hi) { v = parseInt(v, 10); if (isNaN(v)) v = lo; return Math.max(lo, Math.min(v, hi)); }

  // ---------- router ----------
  async function route() {
    if (!state.bootstrapped) await bootstrap();
    const hash = location.hash || (state.user ? "#/" : "#/login");
    if (hash.startsWith("#/table/")) return showTable(hash.slice("#/table/".length));
    if (hash === "#/create") return showCreate();
    if (hash === "#/profile") return showProfile();
    if (hash.startsWith("#/login")) return showLogin();
    return showMain();
  }

  window.addEventListener("hashchange", route);
  route();
})();
