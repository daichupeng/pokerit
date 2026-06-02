/* SPA router + login/main/create screens. Gameplay lives in table.js. */
(function () {
  "use strict";

  const app = document.getElementById("app");
  const state = { user: loadUser() };

  function loadUser() {
    try { return JSON.parse(localStorage.getItem("pt_user") || "null"); } catch { return null; }
  }
  function saveUser(u) { state.user = u; localStorage.setItem("pt_user", JSON.stringify(u)); }

  function screen(id) {
    const tpl = document.getElementById("screen-" + id);
    app.innerHTML = "";
    app.appendChild(tpl.content.cloneNode(true));
  }

  async function api(path, opts) {
    const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch {}
      throw new Error(detail);
    }
    return res.json();
  }

  // ---------- screens ----------
  function showLogin() {
    screen("login");
    const go = async (asGuest) => {
      const name = document.getElementById("login-name").value;
      const email = document.getElementById("login-email").value;
      const body = asGuest ? {} : { display_name: name, email };
      try {
        const user = await api("/api/login", { method: "POST", body: JSON.stringify(body) });
        saveUser(user);
        location.hash = "#/";
      } catch (e) { alert("Login failed: " + e.message); }
    };
    document.getElementById("login-continue").onclick = () => go(false);
    document.getElementById("login-skip").onclick = () => go(true);
  }

  async function showMain() {
    if (!state.user) { location.hash = "#/login"; return; }
    screen("main");
    document.getElementById("profile-name").textContent = state.user.display_name;
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
        hero_name: state.user.display_name,
        hero_email: state.user.email,
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
    screen("table");
    document.getElementById("leave-game").onclick = () => (location.hash = "#/");
    const wsUrl = sessionStorage.getItem("pt_ws_" + gameId) || `/ws/games/${gameId}`;
    window.PokerTable.mount(gameId, wsUrl);
  }

  function clamp(v, lo, hi) { v = parseInt(v, 10); if (isNaN(v)) v = lo; return Math.max(lo, Math.min(v, hi)); }

  // ---------- router ----------
  function route() {
    const hash = location.hash || (state.user ? "#/" : "#/login");
    if (hash.startsWith("#/table/")) return showTable(hash.slice("#/table/".length));
    if (hash === "#/create") return showCreate();
    if (hash === "#/login") return showLogin();
    return showMain();
  }

  window.addEventListener("hashchange", route);
  route();
})();
