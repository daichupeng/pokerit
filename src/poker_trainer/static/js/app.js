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
    document.getElementById("go-history").onclick = () => (location.hash = "#/history");
    document.getElementById("see-all-history").onclick = () => (location.hash = "#/history");
    const list = document.getElementById("games-list");
    try {
      const games = await api("/api/games");
      if (!games.length) {
        list.innerHTML = `<p class="muted">No games yet — finish a game and it will appear here.</p>`;
      } else {
        list.innerHTML = "";
        games.slice(0, 5).forEach((g) => list.appendChild(gameRow(g)));
      }
    } catch (e) {
      list.innerHTML = `<p class="error">Could not load games: ${e.message}</p>`;
    }
  }

  // ---------- history helpers ----------
  const SUIT = { S: { g: "♠", c: "black" }, H: { g: "♥", c: "red" },
                 D: { g: "♦", c: "red" }, C: { g: "♣", c: "black" } };

  // Render a card code ("SK", "HT") as an inline colored glyph, e.g. ♥K.
  function cardHTML(code) {
    if (!code) return "";
    const suit = code[0], rank = code.slice(1).replace("T", "10");
    const s = SUIT[suit] || { g: "?", c: "black" };
    return `<span class="suit-${s.c}">${rank}${s.g}</span>`;
  }
  function cardsHTML(codes) {
    return (codes || []).map(cardHTML).join(" ");
  }

  // Format a stored amount with a sign, for net results.
  function netHTML(n) {
    const cls = n > 0 ? "win" : n < 0 ? "loss" : "muted";
    const sign = n > 0 ? "+" : "";
    return `<span class="${cls}">${sign}${n.toLocaleString()}</span>`;
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return iso.slice(0, 16).replace("T", " ");
    return d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  }

  // A clickable game row used on both the main page and the history list.
  function gameRow(g) {
    const row = document.createElement("button");
    row.className = "list-row";
    row.innerHTML =
      `<span class="lr-main">${fmtDate(g.started_at)}</span>` +
      `<span class="lr-meta muted tiny">${g.small_blind}/${g.big_blind} · ${g.num_hands} hand${g.num_hands === 1 ? "" : "s"}</span>` +
      `<span class="lr-net">${netHTML(g.hero_net)}</span>`;
    row.onclick = () => (location.hash = "#/history/" + g.game_id);
    return row;
  }

  // ---------- history screens ----------
  async function showHistory() {
    if (!state.user) { location.hash = "#/login"; return; }
    screen("history");
    document.getElementById("history-back").onclick = () => (location.hash = "#/");
    const list = document.getElementById("history-list");
    try {
      const games = await api("/api/games");
      if (!games.length) {
        list.innerHTML = `<p class="muted">No games yet — finish a game and it will appear here.</p>`;
      } else {
        list.innerHTML = "";
        games.forEach((g) => list.appendChild(gameRow(g)));
      }
    } catch (e) {
      list.innerHTML = `<p class="error">Could not load games: ${e.message}</p>`;
    }
  }

  function titleCase(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }

  async function showGameHands(gameId, autoRound) {
    if (!state.user) { location.hash = "#/login"; return; }
    screen("game-hands");
    document.getElementById("hands-back").onclick = () => (location.hash = "#/history");
    const list = document.getElementById("hands-list");
    let data;
    try { data = await api("/api/games/" + gameId + "/hands"); }
    catch (e) {
      list.innerHTML = `<p class="error">Could not load game: ${e.message}</p>`;
      return;
    }
    document.getElementById("hands-summary").textContent =
      `${fmtDate(data.started_at)} · ${data.small_blind}/${data.big_blind} · ${data.hands.length} hands`;
    if (!data.hands.length) {
      list.innerHTML = `<p class="muted">This game has no recorded hands.</p>`;
      return;
    }

    let activeRow = null;
    list.innerHTML = "";
    data.hands.forEach((h) => {
      const row = document.createElement("button");
      row.className = "list-row";
      const result = h.hero_amount ? netHTML(h.hero_amount) : `<span class="muted">—</span>`;
      row.innerHTML =
        `<span class="lr-main">Hand #${h.round_count}</span>` +
        `<span class="lr-meta muted tiny">${titleCase(h.street_reached)} · pot ${h.pot_total.toLocaleString()}</span>` +
        `<span class="lr-net">${result}</span>`;
      row.dataset.round = h.round_count;
      row.onclick = () => {
        if (activeRow) activeRow.classList.remove("active");
        row.classList.add("active");
        activeRow = row;
        loadHandDetail(gameId, h.round_count);
      };
      list.appendChild(row);
    });

    // Auto-select first hand (or a specific round passed in).
    const targetRound = autoRound || data.hands[0].round_count;
    const target = list.querySelector(`[data-round="${targetRound}"]`);
    if (target) target.click();
  }

  // Phrase one action as "name action amount" (hero shown as "you").
  function actionLine(a) {
    const who = a.is_hero ? "you" : a.name;
    const amt = a.amount || 0;
    const allin = a.is_allin ? ` <span class="tag-allin">ALL IN</span>` : "";
    switch (a.action) {
      case "fold": return `${who} folds`;
      case "raise": return `${who} raises to ${amt.toLocaleString()}${allin}`;
      case "call": return amt > 0 ? `${who} calls ${amt.toLocaleString()}${allin}` : `${who} checks`;
      case "smallblind": return `${who} posts small blind ${amt.toLocaleString()}`;
      case "bigblind": return `${who} posts big blind ${amt.toLocaleString()}`;
      case "ante": return `${who} posts ante ${amt.toLocaleString()}`;
      default: return `${who} ${a.action}${amt ? " " + amt.toLocaleString() : ""}`;
    }
  }

  function potHTML(pot) {
    if (!pot) return "";
    const main = (pot.main || 0).toLocaleString();
    const sides = (pot.side || []).filter(s => s.amount > 0);
    let s = `<span class="pot-main">Pot: ${main}</span>`;
    sides.forEach((sp, i) => {
      s += ` <span class="pot-side">Side pot ${i + 1}: ${sp.amount.toLocaleString()}</span>`;
    });
    return `<div class="street-pot">${s}</div>`;
  }

  function stacksHTML(playerStacks) {
    if (!playerStacks || !playerStacks.length) return "";
    const items = playerStacks
      .filter(p => p.stack > 0)
      .map(p => `<span class="stack-chip${p.is_hero ? " hero" : ""}">${p.is_hero ? "you" : p.name} ${p.stack.toLocaleString()}</span>`)
      .join("");
    return items ? `<div class="street-stacks">${items}</div>` : "";
  }

  // Build one street block with pot context, board cards, stacks, and actions.
  function streetBlock(label, st) {
    if (!st) return "";
    const acts = st.actions || [];
    const board = st.board || [];
    if (!acts.length && !board.length) return "";
    let html = `<div class="street"><h3>${label}</h3>`;
    if (board.length) html += `<p class="board-line">${cardsHTML(board)}</p>`;
    html += potHTML(st.pot);
    html += stacksHTML(st.player_stacks);
    if (acts.length) {
      html += `<ul class="action-list">${acts.map(a => `<li>${actionLine(a)}</li>`).join("")}</ul>`;
    } else {
      html += `<p class="muted tiny">(cards dealt, no action — all in)</p>`;
    }
    return html + `</div>`;
  }

  async function loadHandDetail(gameId, round) {
    const box = document.getElementById("hand-detail");
    if (!box) return;
    box.innerHTML = `<p class="muted" style="padding:1.5rem">Loading…</p>`;
    let d;
    try { d = await api(`/api/games/${gameId}/hands/${round}`); }
    catch (e) {
      box.innerHTML = `<p class="error" style="padding:1.5rem">Could not load hand: ${e.message}</p>`;
      return;
    }

    // Players' hole cards header.
    const playersHTML = d.players.map((p) => {
      const who = p.is_hero ? "you" : p.name;
      const cards = p.hole_cards ? cardsHTML(p.hole_cards) : `<span class="muted">Unknown</span>`;
      return `<li><span class="pname${p.is_hero ? " hero" : ""}">${who}</span>: ${cards}</li>`;
    }).join("");

    let html = `<div class="hand-detail-header"><h3>Hand #${d.round_count}</h3></div>`;
    html += `<div class="street"><h3>Players' hands</h3><ul class="hand-players">${playersHTML}</ul></div>`;
    html += streetBlock("Preflop", d.streets.preflop);
    html += streetBlock("Flop", d.streets.flop);
    html += streetBlock("Turn", d.streets.turn);
    html += streetBlock("River", d.streets.river);

    // Showdown: revealed cards + hand values.
    if (d.had_showdown && d.showdown_hands && d.showdown_hands.length) {
      const sdRows = d.showdown_hands.map(sh => {
        const who = sh.is_hero ? "you" : sh.name;
        const winTag = sh.is_winner
          ? ` <span class="win">wins ${sh.amount_won.toLocaleString()}</span>` : "";
        return `<li>
          <span class="pname${sh.is_hero ? " hero" : ""}">${who}</span>:
          ${cardsHTML(sh.hole_cards)}
          <span class="hand-label">${sh.hand_label}</span>${winTag}
        </li>`;
      }).join("");
      // Final pot breakdown.
      const fp = d.final_pot || {};
      const mainAmt = (fp.main || {}).amount || d.pot_total;
      let potLine = `Total pot: ${mainAmt.toLocaleString()}`;
      (fp.side || []).filter(s => s.amount > 0).forEach((sp, i) => {
        potLine += ` · Side pot ${i + 1}: ${sp.amount.toLocaleString()}`;
      });
      html += `<div class="street"><h3>Showdown</h3>` +
        `<ul class="hand-players showdown-list">${sdRows}</ul>` +
        `<p class="muted tiny pot-summary">${potLine}</p></div>`;
    }

    // Result: show winner(s) for every hand, including folds (no showdown).
    if (d.winners && d.winners.length) {
      const wLines = d.winners.map(w => {
        const who = w.is_hero ? "you" : w.name;
        return `<span class="pname${w.is_hero ? " hero" : ""}">${who}</span> wins ${w.amount_won.toLocaleString()}`;
      }).join(" · ");
      html += `<div class="street result-line"><span class="win">${wLines}</span></div>`;
    }

    box.innerHTML = html;
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
    if (hash === "#/history") return showHistory();
    if (hash.startsWith("#/history/")) {
      const parts = hash.slice("#/history/".length).split("/");
      // parts[0] = gameId, parts[1] (optional) = round to auto-select
      return showGameHands(parts[0], parts[1] ? parseInt(parts[1], 10) : null);
    }
    if (hash.startsWith("#/login")) return showLogin();
    return showMain();
  }

  window.addEventListener("hashchange", route);
  route();
})();
