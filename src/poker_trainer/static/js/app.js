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
    wireCoachBtns(null);
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
  // Card format: rank+suit lowercase, e.g. "As", "Tc", "2h"
  const SUIT = { s: { g: "♠", c: "black" }, h: { g: "♥", c: "red" },
                 d: { g: "♦", c: "red" }, c: { g: "♣", c: "black" } };

  // Render a card code ("As", "Tc") as an inline colored glyph, e.g. A♠.
  function cardHTML(code) {
    if (!code) return "";
    const rank = code[0].replace("T", "10"), suit = code[1];
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
  const _dismissedUnviewed = new Set(); // in-memory only — dismiss never marks viewed

  async function loadUnviewedBanner() {
    const el = document.getElementById("unviewed-banner");
    if (!el) return;
    let unviewed;
    try { unviewed = await api("/api/evaluations/unviewed"); }
    catch { return; }
    const visible = unviewed.filter((e) => !_dismissedUnviewed.has(e.evaluation_id));
    if (!visible.length) { el.innerHTML = ""; return; }

    const rows = visible.map((e) =>
      `<button class="unviewed-banner-row" data-game="${e.game_id}" data-eval="${e.evaluation_id}">
        New coaching report ready — game from ${fmtDate(e.completed_at)}
      </button>`
    ).join("");
    el.innerHTML = `<div class="unviewed-banner">
      <div class="unviewed-banner-head">
        <strong>${visible.length} new coaching report${visible.length === 1 ? "" : "s"}</strong>
        <button class="unviewed-banner-dismiss">Dismiss</button>
      </div>
      <div class="unviewed-banner-list">${rows}</div>
    </div>`;
    el.querySelectorAll(".unviewed-banner-row").forEach((row) => {
      row.onclick = () => (location.hash = `#/history/${row.dataset.game}/eval/${row.dataset.eval}`);
    });
    el.querySelector(".unviewed-banner-dismiss").onclick = () => {
      visible.forEach((e) => _dismissedUnviewed.add(e.evaluation_id));
      el.innerHTML = "";
    };
  }

  async function showHistory() {
    if (!state.user) { location.hash = "#/login"; return; }
    screen("history");
    document.getElementById("history-back").onclick = () => (location.hash = "#/");
    document.getElementById("history-go-coaching").onclick = () => (location.hash = "#/profile/coaching");
    wireCoachBtns(null);
    loadUnviewedBanner();
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

  // Hero's stats for this game, plus a comparison line against the hero's
  // rolling stats across every game they've played. Hero-only — no opponent
  // stats — and every stat shown as a percentage plus its raw count, never
  // hidden for sample size.
  async function loadGameStats(gameId) {
    const el = document.getElementById("hands-stats");
    if (!el) return;
    el.innerHTML = `<p class="muted tiny">Loading stats…</p>`;
    let game, career;
    try {
      [game, career] = await Promise.all([
        api(`/api/games/${gameId}/stats`),
        api("/api/profile/stats"),
      ]);
    } catch (e) {
      el.innerHTML = `<p class="error tiny">Could not load stats: ${e.message}</p>`;
      return;
    }
    const gameHTML = window.heroStatsHTML ? window.heroStatsHTML(game, { title: "This game" }) : "";
    const careerHTML = window.heroStatsHTML ? window.heroStatsHTML(career, { title: "All games" }) : "";
    el.innerHTML = `<div class="hands-stats-row">${gameHTML}${careerHTML}</div>`;
  }

  // ---------- game evaluation (coach agent) ----------
  function evalStatusBadgeHTML(status) {
    return `<span class="eval-status ${status}">${status}</span>`;
  }

  async function loadEvalHistory(gameId) {
    const el = document.getElementById("eval-history-list");
    if (!el) return;
    try {
      const evaluations = await api(`/api/games/${gameId}/evaluations`);
      el.innerHTML = "";
      evaluations.forEach((e) => {
        const row = document.createElement("button");
        row.className = "eval-history-row";
        row.innerHTML = `<span>${fmtDate(e.created_at)}</span>${evalStatusBadgeHTML(e.status)}`;
        row.onclick = () => (location.hash = `#/history/${gameId}/eval/${e.evaluation_id}`);
        el.appendChild(row);
      });
    } catch (e) {
      el.innerHTML = "";
    }
  }

  function wireEvaluateButton(gameId, handCount) {
    const btn = document.getElementById("evaluate-game-btn");
    if (!btn) return;
    btn.onclick = async () => {
      if (handCount < 10) {
        const proceed = confirm(
          `This game only has ${handCount} hand${handCount === 1 ? "" : "s"} — evaluate anyway?`
        );
        if (!proceed) return;
      }
      btn.disabled = true;
      try {
        const res = await api(`/api/games/${gameId}/evaluate`, { method: "POST" });
        location.hash = `#/history/${gameId}/eval/${res.evaluation_id}`;
      } catch (e) {
        alert("Could not start evaluation: " + e.message);
      } finally {
        btn.disabled = false;
      }
    };
    loadEvalHistory(gameId);
  }

  let _evalPollTimer = null;

  function stopEvalPolling() {
    if (_evalPollTimer) { clearInterval(_evalPollTimer); _evalPollTimer = null; }
  }

  const PROFILE_STATUS_LABEL = { new: "New", returning: "Returning", regressing: "Regressing" };

  function renderEvalReport(full, gameId, evalId) {
    const box = document.getElementById("eval-report");
    box.classList.remove("hidden");

    const toolbar = document.getElementById("eval-toolbar");
    const discardBtn = document.getElementById("eval-discard-btn");
    toolbar.classList.remove("hidden");
    const isDiscarded = !!full.discarded_at;
    discardBtn.textContent = isDiscarded ? "Restore" : "Discard";
    discardBtn.onclick = async () => {
      discardBtn.disabled = true;
      try {
        const action = isDiscarded ? "restore" : "discard";
        if (!isDiscarded && !confirm("Discard this evaluation? It will stop counting toward your coaching profile.")) {
          discardBtn.disabled = false;
          return;
        }
        await api(`/api/games/${gameId}/evaluations/${evalId}/${action}`, { method: "POST" });
        // The rebuild can take a few seconds (it regenerates the playstyle
        // summary via an LLM call) — the user may have navigated away from
        // this report by the time it resolves, in which case these elements
        // no longer exist and there's nothing to update.
        if (!document.body.contains(discardBtn)) return;
        full.discarded_at = isDiscarded ? null : new Date().toISOString();
        renderEvalReport(full, gameId, evalId);
      } catch (e) {
        if (document.body.contains(discardBtn)) alert("Could not update evaluation: " + e.message);
      } finally {
        if (document.body.contains(discardBtn)) discardBtn.disabled = false;
      }
    };

    const disputedTags = new Set(full.disputed_tags || []);
    const sections = (full.report && full.report.sections) || [];
    let html = "";
    if (isDiscarded) {
      html += `<div class="eval-discarded-banner"><span>This evaluation is discarded and excluded from your coaching profile.</span></div>`;
    }
    html += `<div class="eval-summary">${(full.report && full.report.summary) || ""}</div>`;
    sections.forEach((s) => {
      const citations = (s.citations || []).map((c) => {
        const round = typeof c === "object" ? c.round_count : c;
        return `<button class="eval-citation-chip" data-round="${round}">Hand #${round}</button>`;
      }).join("");
      const profileBadge = s.profile_status
        ? `<span class="eval-profile-status ${s.profile_status}">${PROFILE_STATUS_LABEL[s.profile_status] || s.profile_status}</span>`
        : "";
      const isDisputed = disputedTags.has(s.tag);
      html += `<div class="eval-section-card">
        <div class="eval-section-head">
          <span class="eval-tag">${titleCase((s.tag || "").replace(/_/g, " "))}</span>
          <span class="eval-severity sev-${s.severity}">severity ${s.severity}</span>
          ${profileBadge}
        </div>
        <p>${s.narrative || ""}</p>
        <div class="eval-citations">${citations}</div>
        <div class="eval-section-foot">
          <button class="eval-dispute-btn${isDisputed ? " disputed" : ""}" data-tag="${s.tag}">
            ${isDisputed ? "Disputed ✓" : "Dispute this finding"}
          </button>
        </div>
      </div>`;
    });
    box.innerHTML = html;
    box.querySelectorAll(".eval-citation-chip").forEach((chip) => {
      chip.onclick = () => (location.hash = `#/history/${full.game_id_for_link}/${chip.dataset.round}`);
    });
    box.querySelectorAll(".eval-dispute-btn").forEach((btn) => {
      btn.onclick = async () => {
        const tag = btn.dataset.tag;
        const nowDisputed = !disputedTags.has(tag);
        if (nowDisputed && !confirm("Dispute this finding? It will be excluded from your coaching profile.")) return;
        btn.disabled = true;
        try {
          const res = await api(`/api/games/${gameId}/evaluations/${evalId}/dispute`, {
            method: "POST",
            body: JSON.stringify({ tags: [tag], disputed: nowDisputed }),
          });
          // Same staleness guard as discard/restore above — the rebuild
          // triggers an LLM call and can outlive this report view.
          if (!document.body.contains(btn)) return;
          full.disputed_tags = res.disputed_tags;
          renderEvalReport(full, gameId, evalId);
        } catch (e) {
          if (document.body.contains(btn)) alert("Could not update dispute: " + e.message);
        } finally {
          if (document.body.contains(btn)) btn.disabled = false;
        }
      };
    });
  }

  async function showEvaluation(gameId, evalId) {
    if (!state.user) { location.hash = "#/login"; return; }
    screen("evaluation");
    document.getElementById("eval-back").onclick = () => (location.hash = `#/history/${gameId}`);
    stopEvalPolling();

    const progressBox = document.getElementById("eval-progress");
    const progressLabel = document.getElementById("eval-progress-label");
    const progressFill = document.getElementById("eval-progress-fill");
    const errorBox = document.getElementById("eval-error");

    async function poll() {
      let status;
      try {
        status = await api(`/api/games/${gameId}/evaluations/${evalId}/status`);
      } catch (e) {
        stopEvalPolling();
        errorBox.textContent = "Could not load evaluation status: " + e.message;
        errorBox.classList.remove("hidden");
        return;
      }

      if (status.status === "PENDING" || status.status === "RUNNING") {
        progressBox.classList.remove("hidden");
        const pct = status.progress_total
          ? Math.round((100 * status.progress_current) / status.progress_total) : 0;
        progressLabel.textContent =
          `${titleCase(status.current_stage || "starting")}… (${status.progress_current}/${status.progress_total})`;
        progressFill.style.width = pct + "%";
        return;
      }

      stopEvalPolling();
      progressBox.classList.add("hidden");

      if (status.status === "FAILED") {
        errorBox.textContent = "Evaluation failed: " + (status.error || "unknown error");
        errorBox.classList.remove("hidden");
        return;
      }

      // Completed — fetch the full record and render the report.
      let full;
      try { full = await api(`/api/games/${gameId}/evaluations/${evalId}`); }
      catch (e) {
        errorBox.textContent = "Could not load report: " + e.message;
        errorBox.classList.remove("hidden");
        return;
      }
      full.game_id_for_link = gameId;
      renderEvalReport(full, gameId, evalId);
      // Mark viewed on first render — a no-op if it's already viewed.
      api(`/api/games/${gameId}/evaluations/${evalId}/viewed`, { method: "POST" }).catch(() => {});
    }

    await poll();
    _evalPollTimer = setInterval(poll, 2000);
  }

  async function showGameHands(gameId, autoRound) {
    if (!state.user) { location.hash = "#/login"; return; }
    screen("game-hands");
    document.getElementById("hands-back").onclick = () => (location.hash = "#/");
    const list = document.getElementById("hands-list");
    loadGameStats(gameId);
    let data;
    try { data = await api("/api/games/" + gameId + "/hands"); }
    catch (e) {
      list.innerHTML = `<p class="error">Could not load game: ${e.message}</p>`;
      return;
    }
    wireEvaluateButton(gameId, data.hands.length);
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
        // Fetch hand context for coach and load it into the global coach panel.
        api(`/api/games/${gameId}/hands/${h.round_count}/context`)
          .then((ctx) => {
            if (_globalCoach && ctx && ctx.context) {
              _globalCoach.setHandContext(gameId, h.round_count, ctx.context, ctx.hand_id);
            }
          })
          .catch(() => {});
      };
      list.appendChild(row);
    });

    // Auto-select first hand (or a specific round passed in).
    const targetRound = autoRound || data.hands[0].round_count;
    const target = list.querySelector(`[data-round="${targetRound}"]`);
    if (target) target.click();

    wireCoachBtns(gameId);
  }

  // Render a player name with optional position badge.
  function pnameHTML(name, isHero, pos) {
    const label = isHero ? "you" : name;
    const posTag = pos ? ` <span class="pos-badge">${pos}</span>` : "";
    return `<span class="pname${isHero ? " hero" : ""}">${label}</span>${posTag}`;
  }

  // Render a small context tag showing current-street bet and remaining stack.
  function actionContextHTML(a) {
    if (a.street_bet == null || a.stack_before == null) return "";
    return ` <span class="action-context">Current Bet: ${a.street_bet.toLocaleString()} · Stack: ${a.stack_before.toLocaleString()}</span>`;
  }

  // Phrase one action as "name action amount" (hero shown as "you").
  function actionLine(a) {
    const who = pnameHTML(a.name, a.is_hero, a.position);
    const ctx = actionContextHTML(a);
    const amt = a.amount || 0;
    const allin = a.is_allin ? ` <span class="tag-allin">ALL IN</span>` : "";
    switch (a.action) {
      case "fold": return `${who} folds${ctx}`;
      case "raise": return `${who} raises to ${amt.toLocaleString()}${allin}${ctx}`;
      case "call": return amt > 0 ? `${who} calls ${amt.toLocaleString()}${allin}${ctx}` : `${who} checks${ctx}`;
      case "smallblind": return `${who} posts small blind ${amt.toLocaleString()}${ctx}`;
      case "bigblind": return `${who} posts big blind ${amt.toLocaleString()}${ctx}`;
      case "ante": return `${who} posts ante ${amt.toLocaleString()}${ctx}`;
      default: return `${who} ${a.action}${amt ? " " + amt.toLocaleString() : ""}${ctx}`;
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
      const cards = p.hole_cards ? cardsHTML(p.hole_cards) : `<span class="muted">Unknown</span>`;
      return `<li>${pnameHTML(p.name, p.is_hero, p.position)}: ${cards}</li>`;
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
        const winTag = sh.is_winner
          ? ` <span class="win">wins ${sh.amount_won.toLocaleString()}</span>` : "";
        return `<li>
          ${pnameHTML(sh.name, sh.is_hero, sh.position)}:
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
    wireCoachBtns(null);

    const sb = $("cfg-sb"), bb = $("cfg-bb");
    sb.addEventListener("input", () => { bb.value = (+sb.value || 0) * 2; }); // keep BB = 2*SB

    const random = $("cfg-random"), picker = $("styles-picker"), rows = $("styles-rows"), bots = $("cfg-bots");
    let STYLES = [];
    fetch("/api/bot-styles").then(r => r.json()).then(data => {
      STYLES = data;
      rebuildPicker();
    });
    function rebuildPicker() {
      picker.classList.toggle("hidden", random.checked);
      if (random.checked) return;
      const n = clamp(+bots.value, 1, 8);
      rows.innerHTML = "";
      for (let i = 0; i < n; i++) {
        const row = document.createElement("div");
        row.className = "styles-row";
        row.innerHTML = `<span class="tiny muted">Bot ${i + 1}</span>` +
          `<select data-bot="${i}">${STYLES.map((s) => `<option value="${s.value}">${s.label}</option>`).join("")}</select>`;
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
    [2, 2.5, 3.5, 4.5].forEach((v) => addChip(preflopRows, v, "× BB"));
    [33, 50, 65, 100].forEach((v) => addChip(postflopRows, v, "% Pot"));
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
    const wsUrl = sessionStorage.getItem("pt_ws_" + gameId) || `/ws/games/${gameId}`;
    window.PokerTable.mount(gameId, wsUrl);
  }

  async function showProfile() {
    if (!state.user) { location.hash = "#/login"; return; }
    screen("profile");
    const $ = (id) => document.getElementById(id);
    $("profile-back").onclick = () => (location.hash = "#/");
    $("pf-go-coaching").onclick = () => (location.hash = "#/profile/coaching");
    wireCoachBtns(null);

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

  // ---------- coaching profile (Phase 5+6) ----------
  function leakCardHTML(leak) {
    const regressedBadge = leak.regressed ? `<span class="coaching-regressed-pill">Regressing</span>` : "";
    const lastSeenDate = leak.last_seen ? fmtDate(leak.last_seen.date) : "—";
    return `<div class="coaching-leak-card">
      <div class="coaching-leak-head">
        <span class="eval-tag">${titleCase((leak.tag || "").replace(/_/g, " "))}</span>
        <span class="coaching-status-pill ${leak.status}">${titleCase(leak.status || "")}</span>
        ${regressedBadge}
      </div>
      <div class="coaching-leak-meta muted">
        Seen ${leak.occurrences} time${leak.occurrences === 1 ? "" : "s"} · last: ${lastSeenDate}
      </div>
    </div>`;
  }

  function trendRowHTML(name, trend) {
    const dirGlyph = trend.direction === "up" ? "▲" : trend.direction === "down" ? "▼" : "―";
    const series = trend.series || [];
    const latest = series.length ? series[series.length - 1] : null;
    const latestText = latest ? `${latest.value}${typeof latest.value === "number" && latest.value <= 100 && name !== "aggression_factor" ? "%" : ""}` : "—";
    return `<div class="coaching-trend-row">
      <span>${titleCase(name.replace(/_/g, " "))}</span>
      <span><span class="coaching-trend-dir ${trend.direction}">${dirGlyph}</span> ${latestText}</span>
    </div>`;
  }

  async function showProfileCoaching() {
    if (!state.user) { location.hash = "#/login"; return; }
    screen("coaching-profile");
    const $ = (id) => document.getElementById(id);
    $("coaching-back").onclick = () => (location.hash = "#/history");

    let profile;
    try { profile = await api("/api/profile/coaching"); }
    catch (e) {
      $("coaching-count").textContent = "Could not load coaching profile: " + e.message;
      return;
    }

    $("coaching-count").textContent = `${profile.evaluations_folded} evaluation${profile.evaluations_folded === 1 ? "" : "s"} folded in`;
    $("coaching-summary").innerHTML = profile.playstyle_summary
      ? `<div class="coaching-summary">${profile.playstyle_summary}</div>`
      : `<p class="muted tiny">No playstyle summary yet — evaluate a few games to build your profile.</p>`;

    const trends = profile.trends || {};
    const trendNames = Object.keys(trends);
    $("coaching-trends").innerHTML = trendNames.length
      ? trendNames.map((name) => trendRowHTML(name, trends[name])).join("")
      : `<p class="muted tiny">No trend data yet.</p>`;

    const active = [...(profile.leaks_by_status.flagged || []), ...(profile.leaks_by_status.confirmed || [])];
    $("coaching-active-leaks").innerHTML = active.length
      ? active.map(leakCardHTML).join("")
      : `<p class="muted tiny">No active leaks right now.</p>`;

    const resolved = profile.leaks_by_status.resolved || [];
    $("coaching-resolved-leaks").innerHTML = resolved.length
      ? resolved.map(leakCardHTML).join("")
      : `<p class="muted tiny">Nothing resolved yet.</p>`;

    $("coaching-reset-btn").onclick = async () => {
      if (!confirm("Reset your coaching profile? Active leaks and trends will be cleared — future evaluations start fresh. Past game reports are unaffected.")) return;
      try {
        await api("/api/profile/reset", { method: "POST" });
        showProfileCoaching();
      } catch (e) {
        alert("Could not reset profile: " + e.message);
      }
    };
  }

  // ---------- global coach panel ----------
  let _globalCoach = null;

  function initGlobalCoach() {
    const panel = document.getElementById("global-coach-panel");
    document.getElementById("global-coach-close").onclick = () => panel.classList.add("hidden");
    _globalCoach = new CoachBox(
      document.getElementById("global-coach-messages"),
      document.getElementById("global-coach-form"),
      document.getElementById("global-coach-input"),
      null,
    );
  }

  function toggleGlobalCoach() {
    document.getElementById("global-coach-panel").classList.toggle("hidden");
  }

  // Wire the AI Coach button on the game-hands screen.
  function wireCoachBtns(gameId) {
    if (_globalCoach) {
      _globalCoach.gameId = gameId || null;
    }
    const btn = document.getElementById("history-toggle-coach");
    if (btn) btn.onclick = toggleGlobalCoach;
  }

  // ---------- markdown helper ----------
  function markdownToHTML(text) {
    let html = text
      // Bold: **text** → <strong>text</strong>
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      // Italic: *text* → <em>text</em>
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      // Code: `text` → <code>text</code>
      .replace(/`(.+?)`/g, "<code>$1</code>")
      // Headers: # text → <h3>text</h3>, ## text → <h4>text</h4>
      .replace(/^### (.+?)$/gm, "<h5>$1</h5>")
      .replace(/^## (.+?)$/gm, "<h4>$1</h4>")
      .replace(/^# (.+?)$/gm, "<h3>$1</h3>")
      // Line breaks: \n → <br/>
      .replace(/\n/g, "<br/>");
    // Sanitize: remove any potentially dangerous HTML
    const div = document.createElement("div");
    div.innerHTML = html;
    // Remove any script tags and event handlers
    div.querySelectorAll("script").forEach(s => s.remove());
    return div.innerHTML;
  }

  // ---------- coach chat (shared SSE helper) ----------
  class CoachBox {
    constructor(messagesEl, formEl, inputEl, gameId) {
      this.messagesEl = messagesEl;
      this.gameId = gameId;
      this.conversationId = null;
      this._formEl = formEl;
      this._inputEl = inputEl;
      this._submitBtn = formEl.querySelector("button[type=submit]");
      formEl.addEventListener("submit", (e) => {
        e.preventDefault();
        const text = (inputEl.value || "").trim();
        if (!text) return;
        inputEl.value = "";
        this.send(text);
      });
      inputEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          formEl.dispatchEvent(new Event("submit"));
        }
      });
    }

    // Load context for a hand: resumes an existing hand_history conversation if
    // one exists, otherwise creates a new one with the hand text pinned server-side.
    async setHandContext(gameId, roundCount, contextText, handId) {
      this.gameId = gameId;
      this.conversationId = null;
      this.messagesEl.innerHTML = "";
      const banner = document.createElement("div");
      banner.className = "coach-hand-banner";
      this.messagesEl.appendChild(banner);

      // Try to resume an existing conversation for this hand.
      if (handId) {
        try {
          const existing = await api(`/api/coach/conversations/by-hand/${handId}`);
          if (existing && existing.conversation_id) {
            this.conversationId = existing.conversation_id;
            banner.textContent = `Hand #${roundCount} — continuing previous conversation.`;
            // Replay stored messages into the UI.
            (existing.messages || []).forEach((m) => this.append(m.role, m.content, false));
            return;
          }
        } catch (_) {
          // 404 = no prior conversation; fall through to create one.
        }
      }

      banner.textContent = `Hand #${roundCount} loaded — ask the coach anything about this hand.`;
      try {
        const res = await api("/api/coach/conversations", {
          method: "POST",
          body: JSON.stringify({
            game_id: gameId,
            pinned_context: contextText,
            entry_point: "hand_history",
            hand_id: handId || null,
          }),
        });
        this.conversationId = res.conversation_id;
      } catch (e) {
        banner.textContent += " (context unavailable)";
      }
    }

    append(role, text, streaming) {
      const el = document.createElement("div");
      el.className = "coach-msg " + (role === "user" ? "coach-user" : "coach-assistant");
      if (streaming) el.classList.add("coach-streaming");
      if (role === "user") {
        el.textContent = text;
      } else {
        el.innerHTML = markdownToHTML(text);
      }
      this.messagesEl.appendChild(el);
      this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
      return el;
    }

    _setWaiting(waiting) {
      if (this._submitBtn) this._submitBtn.disabled = waiting;
      if (this._inputEl) this._inputEl.disabled = waiting;
    }

    async send(text) {
      this.append("user", text, false);
      const bubbleEl = this.append("assistant", "Thinking…", true);
      this._setWaiting(true);
      const body = {
        message: text,
        game_id: this.gameId || null,
        conversation_id: this.conversationId || null,
      };
      try {
        const res = await fetch("/api/coach/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(await res.text());
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "", fullText = "";
        bubbleEl.innerHTML = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop();
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const payload = JSON.parse(line.slice(6));
            if (payload.type === "chunk") {
              fullText += payload.text;
              bubbleEl.innerHTML = markdownToHTML(fullText);
              this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
            } else if (payload.type === "done") {
              this.conversationId = payload.conversation_id;
              bubbleEl.classList.remove("coach-streaming");
              this._setWaiting(false);
            } else if (payload.type === "error") {
              bubbleEl.textContent = "Error: " + payload.message;
              bubbleEl.classList.remove("coach-streaming");
              bubbleEl.classList.add("coach-error");
              this._setWaiting(false);
            }
          }
        }
      } catch (err) {
        bubbleEl.textContent = "Error: " + err.message;
        bubbleEl.classList.remove("coach-streaming");
        bubbleEl.classList.add("coach-error");
        this._setWaiting(false);
      }
    }
  }

  function clamp(v, lo, hi) { v = parseInt(v, 10); if (isNaN(v)) v = lo; return Math.max(lo, Math.min(v, hi)); }

  // ---------- router ----------
  async function route() {
    if (!state.bootstrapped) await bootstrap();
    const hash = location.hash || (state.user ? "#/" : "#/login");
    if (hash.startsWith("#/table/")) return showTable(hash.slice("#/table/".length));
    if (hash === "#/create") return showCreate();
    if (hash === "#/profile") return showProfile();
    if (hash === "#/profile/coaching") return showProfileCoaching();
    if (hash === "#/history") return showHistory();
    if (hash.startsWith("#/history/")) {
      const parts = hash.slice("#/history/".length).split("/");
      // parts[0] = gameId, then either "eval/<evalId>" or an optional round to auto-select.
      if (parts[1] === "eval" && parts[2]) return showEvaluation(parts[0], parts[2]);
      return showGameHands(parts[0], parts[1] ? parseInt(parts[1], 10) : null);
    }
    if (hash.startsWith("#/login")) return showLogin();
    return showMain();
  }

  window.addEventListener("hashchange", route);
  initGlobalCoach();
  route();
})();
