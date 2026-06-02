/* Poker table rendering, bet controls, and the WebSocket play client.
 * Cards are drawn with CSS (no external assets) so the app works fully offline.
 * Exposes window.PokerTable.mount(gameId, wsUrl) used by the router in app.js.
 */
(function () {
  "use strict";

  const SUIT = { S: { g: "♠", c: "black" }, H: { g: "♥", c: "red" },
                 D: { g: "♦", c: "red" }, C: { g: "♣", c: "black" } };

  function cardEl(code, opts) {
    opts = opts || {};
    const el = document.createElement("div");
    el.className = "pcard" + (opts.hero ? " hero" : opts.lg ? " lg" : "") + (opts.dimmed ? " dimmed" : "");
    if (!code) { el.classList.add("placeholder"); return el; }
    if (code === "back") { el.classList.add("back"); return el; }
    // code like "SK", "HТ"(T=10), "D2"
    const suit = code[0], rank = code.slice(1).replace("T", "10");
    const s = SUIT[suit] || { g: "?", c: "black" };
    el.classList.add(s.c);
    // Rank in the top-left corner; a single suit symbol in the center.
    const corner = document.createElement("div");
    corner.className = "corner";
    corner.textContent = rank;
    const center = document.createElement("div");
    center.className = "center-suit";
    center.textContent = s.g;
    el.appendChild(corner); el.appendChild(center);
    return el;
  }

  // Seat positions around the oval (percent of felt). Index 0 = hero (bottom).
  function seatPositions(n) {
    // Hero (index 0) sits at the bottom rail; bots are spread around the rim so
    // the felt is used fully. Cards render above each plate, so rim seats sit a
    // little inside the very edge to keep their (now large) cards on the felt.
    // Seats are spread to the rim. Top-row seats sit a bit lower (larger y) so
    // their cards — which render above the plate, same size as the hero's —
    // stay on the felt rather than clipping over the top rail.
    // Hero (index 0) sits at the bottom-center; the other seats are spread
    // roughly evenly around the rest of the oval, with only a slightly larger
    // gap reserved for the hero at the bottom. Every seat shows cards on top of
    // its plate, so the top rows sit low enough that those upward-facing cards
    // stay on the felt (don't clip over the top rail).
    const layouts = {
      2: [[50, 90], [50, 26]],
      3: [[50, 90], [12, 40], [88, 40]],
      4: [[50, 90], [8, 56], [50, 26], [92, 56]],
      6: [[50, 90], [12, 74], [7, 34], [30, 12], [70, 12], [93, 34], [88, 74]],
      9: [[50, 90], [20, 83], [3, 52], [11, 22], [33, 8], [67, 8], [89, 22], [97, 52], [80, 83]],
    };
    if (layouts[n]) return layouts[n];
    // fallback: evenly distribute the bots around the ring, hero at bottom.
    // Leave a slightly wider gap at the bottom for the hero by spanning the
    // bots across ~290° of the ellipse rather than the full circle, and keep
    // the top of the ring low enough for the upward cards.
    const pos = [[50, 90]];
    const span = 2 * Math.PI * (290 / 360);
    const start = -Math.PI / 2 - span / 2; // centered opposite the hero
    for (let i = 1; i < n; i++) {
      const t = start + (span * (i - 1)) / (n - 2);
      pos.push([50 + 44 * Math.cos(t), 42 - 34 * Math.sin(t)]);
    }
    return pos;
  }

  class TableUI {
    constructor(gameId, wsUrl) {
      this.gameId = gameId;
      this.wsUrl = wsUrl;
      this.seatPos = null;
      this.heroUuid = null;
      this.lastView = null;
      this.validActions = null;
      this.bigBlind = 0;
      this.preflopQuick = [];   // [N, ...] big-blind multiples
      this.postflopQuick = [];  // [N, ...] pot percentages
      this.street = "preflop";  // current street, drives which presets show
      this.myTurn = false;      // true only between a hero ask and the hero acting
      this.stats = {};         // uuid -> {name, played, won, net}
      this.hands = [];         // completed hand summaries
      this.bind();
    }

    bind() {
      this.$seats = document.getElementById("seats");
      this.$community = document.getElementById("community");
      this.$pot = document.getElementById("pot");
      this.$message = document.getElementById("message");
      this.$controls = document.getElementById("controls");
      this.$slider = document.getElementById("bet-slider");
      this.$input = document.getElementById("bet-input");
      this.$fold = document.getElementById("btn-fold");
      this.$call = document.getElementById("btn-call");
      this.$raise = document.getElementById("btn-raise");
      this.$quickRow = document.getElementById("quick-row");
      this.$blinds = document.getElementById("table-blinds");
      this.$hand = document.getElementById("table-hand");

      this.$slider.addEventListener("input", () => { this.$input.value = this.$slider.value; });
      this.$input.addEventListener("input", () => {
        let v = clampInt(this.$input.value, +this.$input.min, +this.$input.max);
        this.$slider.value = v;
      });
      this.$fold.addEventListener("click", () => this.send("fold", 0));
      this.$call.addEventListener("click", () => this.send("call", this._callAmount));
      this.$raise.addEventListener("click", () => {
        const v = clampInt(this.$input.value, +this.$input.min, +this.$input.max);
        this.send("raise", v);
      });
      document.querySelectorAll("[data-quick]").forEach((b) =>
        b.addEventListener("click", () => this.quick(b.dataset.quick)));

      document.getElementById("toggle-panel").addEventListener("click", () => {
        const p = document.getElementById("side-panel");
        p.classList.toggle("hidden");
      });
      document.querySelectorAll(".tab").forEach((t) =>
        t.addEventListener("click", () => this.switchTab(t.dataset.tab)));
    }

    connect() {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      this.ws = new WebSocket(`${proto}://${location.host}${this.wsUrl}`);
      this.ws.onmessage = (e) => this.onMessage(JSON.parse(e.data));
      this.ws.onclose = () => this.setMessage("Disconnected.");
    }

    onMessage(msg) {
      if (msg.type === "init") {
        if (msg.config) {
          this.bigBlind = msg.config.big_blind || 0;
          this.preflopQuick = msg.config.preflop_quick || [];
          this.postflopQuick = msg.config.postflop_quick || [];
        }
        if (msg.view) this.render(msg.view);
        if (msg.pending_ask) this.onAsk(msg.pending_ask);
        return;
      }
      if (msg.type === "event") return this.onEvent(msg.event);
      if (msg.type === "saved") {
        this.setMessage("Game over. Result saved" + (msg.db_game_id ? "." : " (not persisted)."));
        this.disableControls();
        return;
      }
      if (msg.type === "error") this.setMessage(msg.message);
    }

    onEvent(ev) {
      switch (ev.type) {
        case "to_act":
          this.disableControls();  // someone else is acting — lock the buttons
          if (ev.view) this.render(ev.view, ev.uuid);
          break;
        case "new_street":
          this.showdown = null; this.winnerUuids = null;  // clear prior showdown
          // Collect the final bets that are currently shown in front of players,
          // slide them into the pot, then reveal the new street's view/card.
          this.collectBetsThenRender(ev);
          break;
        case "round_finish":
          // Stash showdown info so render() can show hand labels and dim the
          // winner's unused cards. Cleared by the next non-showdown render.
          this.showdown = {};
          (ev.showdown || []).forEach((s) => (this.showdown[s.uuid] = s));
          this.winnerUuids = new Set((ev.winners || []).map((w) => w.uuid));
          if (ev.view) this.render(ev.view);
          this.revealShowdown(ev.revealed);
          this.recordHand(ev);
          this.announceWinners(ev.winners, ev.view);
          this.animatePotAward(ev.pot_winners, ev.view);
          break;
        case "ask":
          this.onAsk(ev);
          break;
        case "game_finish":
          this.setMessage("Game finished.");
          this.disableControls();
          this.renderStats();
          break;
      }
    }

    onAsk(ask) {
      this.showdown = null; this.winnerUuids = null;  // new betting view, no showdown
      this.validActions = ask.valid_actions;
      this.myTurn = true;  // only now may the player act
      if (ask.view) this.render(ask.view, this.heroUuid);
      this.enableControls(ask.valid_actions);
      // The glowing seat highlight already signals the hero's turn; no banner.
    }

    // ---- rendering ----
    render(view, actingUuid) {
      this.lastView = view;
      if (view.street) this.street = view.street;
      if (!this.seatPos) this.seatPos = seatPositions(view.seats.length);
      // identify hero
      const hero = view.seats.find((s) => s.is_hero);
      if (hero) this.heroUuid = hero.uuid;

      this.$blinds.textContent = `Blinds ${view.small_blind_amount}/${view.small_blind_amount * 2}`;
      this.$hand.textContent = view.round_count ? `Hand #${view.round_count}` : "";

      // At showdown, the union of the winners' best-5 cards is kept bright;
      // every other card (board kicker / loser's hole) is dimmed.
      const sd = this.showdown || {};
      const winners = this.winnerUuids || new Set();
      const brightBoard = new Set();
      Object.values(sd).forEach((s) => {
        if (winners.has(s.uuid)) (s.best_cards || []).forEach((c) => brightBoard.add(c));
      });
      const showdownActive = Object.keys(sd).length > 0 && winners.size > 0;

      // community — five fixed slots so the board has a stable position; each
      // slot is a grey-outlined placeholder until its card is dealt.
      const board = view.community_card || [];
      this.$community.innerHTML = "";
      for (let i = 0; i < 5; i++) {
        const c = board[i];
        let cardNode;
        if (c) {
          const dim = showdownActive && !brightBoard.has(c);
          cardNode = cardEl(c, { lg: true, dimmed: dim });
        } else {
          cardNode = document.createElement("div");
          cardNode.className = "pcard lg slot";
        }
        // Extra gap before the 4th card (turn) to separate the flop from the
        // turn and river.
        if (i === 3) cardNode.classList.add("gap-before");
        this.$community.appendChild(cardNode);
      }

      // pot — show the main pot and each side pot separately.
      const mainAmt = (view.pot && view.pot.main && view.pot.main.amount) || 0;
      const sidePots = (view.pot && view.pot.side) || [];
      const lines = [];
      if (sidePots.length) {
        lines.push(`Main Pot: ${mainAmt}`);
        sidePots.forEach((s, i) => lines.push(`Side Pot ${i + 1}: ${s.amount || 0}`));
      } else {
        lines.push(`Pot: ${mainAmt}`);
      }
      this.$pot.innerHTML = lines.map((l) => `<div class="pot-line">${l}</div>`).join("");

      // seats
      this.$seats.innerHTML = "";
      this.seatEls = {};  // uuid -> {el, x, y} for the pot-award animation
      view.seats.forEach((seat, i) => {
        const [x, y] = this.seatPos[i] || [50, 50];
        const el = document.createElement("div");
        el.className = "seat" + (seat.state === "folded" ? " folded" : "") + (seat.is_hero ? " hero-seat" : "");
        if (actingUuid && seat.uuid === actingUuid) el.classList.add("acting");
        else if (!actingUuid && seat.pos === view.next_player) el.classList.add("acting");
        el.style.left = x + "%"; el.style.top = y + "%";
        this.seatEls[seat.uuid] = { el, x, y };

        // All players' cards are the same (large) size. At showdown:
        //  - a winner keeps their best-5 bright and dims their 2 unused cards;
        //  - a non-winner has both cards dimmed (they lost the pot).
        const sdEntry = sd[seat.uuid];
        const isWinner = showdownActive && winners.has(seat.uuid);
        const bestSet = (isWinner && sdEntry) ? new Set(sdEntry.best_cards || []) : null;
        const dimCard = (c) => {
          if (!showdownActive) return false;
          if (isWinner) return bestSet ? !bestSet.has(c) : false;  // winner: dim kickers
          return true;  // non-winner at showdown: dim both cards
        };
        const hole = document.createElement("div");
        hole.className = "hole";
        if (seat.hole_cards) {
          seat.hole_cards.forEach((c) =>
            hole.appendChild(cardEl(c, { hero: true, dimmed: dimCard(c) })));
        } else if (seat.state !== "folded") {
          hole.appendChild(cardEl("back", { hero: true }));
          hole.appendChild(cardEl("back", { hero: true }));
        }

        const plate = document.createElement("div");
        plate.className = "plate";
        const styleTag = seat.style ? `<div class="style-tag">${seat.style}</div>` : "";
        const stateTag = seat.state === "allin" ? `<div class="state-tag">ALL-IN</div>`
          : seat.state === "folded" ? `<div class="state-tag">FOLD</div>` : "";
        const labelTag = sdEntry ? `<div class="hand-label">${esc(sdEntry.hand_label)}</div>` : "";
        plate.innerHTML =
          `<div class="name">${esc(seat.name)}${seat.is_hero ? " (you)" : ""}</div>` +
          `<div class="stack">${seat.stack}</div>` + styleTag + stateTag + labelTag;

        const badges = document.createElement("div");
        badges.className = "badges";
        if (seat.is_button) badges.innerHTML += `<span class="badge btn-d">D</span>`;
        if (seat.is_sb) badges.innerHTML += `<span class="badge sb">SB</span>`;
        if (seat.is_bb) badges.innerHTML += `<span class="badge bb">BB</span>`;

        // Every seat: cards on top, name plate on the bottom.
        el.appendChild(hole); el.appendChild(plate); el.appendChild(badges);
        this.$seats.appendChild(el);

        // The current bet sits between the seat and the table center, so it
        // reads as chips pushed toward the pot. Positioned absolutely on the
        // felt (not inside the seat) so it can overlap the green.
        if (seat.bet > 0) {
          const bet = document.createElement("div");
          bet.className = "bet-chip";
          bet.innerHTML = `<span class="chip"></span>${seat.bet}`;
          // 28% of the way from the seat toward the center of the table.
          const bx = x + (50 - x) * 0.3;
          const by = y + (50 - y) * 0.3;
          bet.style.left = bx + "%"; bet.style.top = by + "%";
          this.$seats.appendChild(bet);
        }
      });
    }

    // End of a street: the bet chips currently shown in front of the players
    // slide into the pot, then the new street's view (with its new card) renders.
    collectBetsThenRender(ev) {
      const chips = Array.from(this.$seats.querySelectorAll(".bet-chip"));
      if (!chips.length) {
        if (ev.view) this.render(ev.view);
        this.setMessage(cap(ev.street));
        return;
      }
      const SLIDE_MS = 500;
      // Slide every bet chip to the pot location (40% down, centered).
      chips.forEach((chip) => {
        chip.style.transition = `left ${SLIDE_MS}ms ease-in, top ${SLIDE_MS}ms ease-in, opacity ${SLIDE_MS}ms`;
        requestAnimationFrame(() => {
          chip.style.left = "50%";
          chip.style.top = "40%";
          chip.style.opacity = "0.2";
        });
      });
      // After they land, render the new street (clears the chips, adds the card).
      setTimeout(() => {
        if (ev.view) this.render(ev.view);
        this.setMessage(cap(ev.street));
      }, SLIDE_MS + 60);
    }

    revealShowdown(revealed) {
      if (!revealed) return;
      // update lastView seats with revealed cards then re-render (keeps positions)
      if (!this.lastView) return;
      this.lastView.seats.forEach((s) => { if (revealed[s.uuid]) s.hole_cards = revealed[s.uuid]; });
      this.render(this.lastView);
    }

    announceWinners(winners, view) {
      if (!winners || !view) return;
      const names = winners.map((w) => {
        const s = view.seats.find((x) => x.uuid === w.uuid);
        return s ? s.name : "?";
      });
      this.setMessage(`Winner: ${names.join(", ")}`);
    }

    // Award the pots one at a time: each pot's chips slide from the center to
    // its winner(s) in series (main pot first, then each side pot), then the
    // winning seats blink. Split pots send a chip to each tied winner.
    animatePotAward(potWinners, view) {
      if (!potWinners || !potWinners.length || !this.seatEls) return;

      const MOVE_MS = 900;    // chip travel time (matches the CSS transition)
      const GAP_MS = 450;     // pause between consecutive pots
      const BLINK_MS = 2000;  // winners blink after all pots land

      // The engine orders side pots first, main pot last. Award the main pot
      // first, then side pots in order, for a clearer narrative.
      const ordered = potWinners
        .filter((p) => (p.winners || []).length && p.amount > 0)
        .reverse();
      if (!ordered.length) return;

      const labelFor = (idx) => (idx === 0 ? "Main pot" : `Side pot ${idx}`);
      const POT_X = 50, POT_Y = 40;
      const allWinnerEls = new Set();

      const awardPot = (pot, idx) => {
        this.setMessage(`${labelFor(idx)}: ${pot.amount}`);
        const winners = pot.winners;
        const share = Math.floor(pot.amount / winners.length);
        winners.forEach((uuid) => {
          const ref = this.seatEls[uuid];
          if (!ref) return;
          ref.el.classList.add("winner");
          allWinnerEls.add(ref.el);
          const chip = document.createElement("div");
          chip.className = "pot-fly";
          chip.innerHTML = `<span class="chip"></span>${share}`;
          chip.style.left = POT_X + "%"; chip.style.top = POT_Y + "%";
          this.$seats.appendChild(chip);
          requestAnimationFrame(() => {
            chip.style.left = ref.x + "%";
            chip.style.top = ref.y + "%";
            chip.style.opacity = "0.15";
          });
          setTimeout(() => chip.remove(), MOVE_MS);
        });
      };

      // Chain the pots in series.
      let delay = 0;
      ordered.forEach((pot, idx) => {
        setTimeout(() => awardPot(pot, idx), delay);
        delay += MOVE_MS + GAP_MS;
      });

      // After the last pot lands, blink all winners, then clear.
      setTimeout(() => {
        allWinnerEls.forEach((el) => el.classList.add("winner-blink"));
      }, delay);
      setTimeout(() => {
        allWinnerEls.forEach((el) => el.classList.remove("winner", "winner-blink"));
      }, delay + BLINK_MS);
    }

    // ---- bet controls ----
    // Build the quick-bet buttons for the current street: preflop uses
    // big-blind multiples, later streets use pot percentages. All-in is always
    // appended.
    buildQuickButtons(enabled) {
      const preflop = this.street === "preflop";
      const presets = (preflop ? this.preflopQuick : this.postflopQuick).slice(0, 5);
      this.$quickRow.innerHTML = "";
      presets.forEach((value) => {
        const b = document.createElement("button");
        b.className = "btn tiny";
        b.textContent = preflop ? `${trim(value)}× BB` : `${trim(value)}% Pot`;
        b.disabled = !enabled;
        b.addEventListener("click", () => this.quickPreset(preflop ? "bb" : "pot", value));
        this.$quickRow.appendChild(b);
      });
      const allin = document.createElement("button");
      allin.className = "btn tiny";
      allin.textContent = "All-in";
      allin.disabled = !enabled;
      allin.addEventListener("click", () => this.quickAllin());
      this.$quickRow.appendChild(allin);
    }

    enableControls(valid) {
      this.$controls.classList.remove("hidden");
      const by = {}; valid.forEach((a) => (by[a.action] = a));
      const callAmt = by.call ? by.call.amount : 0;
      this._callAmount = callAmt;
      const raise = by.raise ? by.raise.amount : { min: -1, max: -1 };
      const canRaise = raise.min !== -1 && raise.max !== -1;

      // Fold always; Check/Bet vs Call/Raise depending on call amount
      this.$fold.disabled = false;
      this.$call.disabled = false;
      this.$call.textContent = callAmt === 0 ? "Check" : `Call ${callAmt}`;

      if (canRaise) {
        this.$raise.disabled = false;
        this.$raise.textContent = callAmt === 0 ? "Bet" : "Raise";
        this.setBetBounds(raise.min, raise.max);
      } else {
        this.$raise.disabled = true;
        this.setBetBounds(0, 0, true);
      }
      // Rebuild for the current street (preset set + labels depend on it).
      this.buildQuickButtons(canRaise);
    }

    setBetBounds(min, max, disabled) {
      [this.$slider, this.$input].forEach((el) => {
        el.min = min; el.max = max; el.value = min;
        el.disabled = !!disabled;
      });
    }

    // A preset maps to a raise-TO amount: a BB-multiple (preflop), or a fraction
    // of the pot added on top of the call (postflop). Clamped to the legal range.
    quickPreset(type, value) {
      const pot = this.lastView ? potTotal(this.lastView.pot) : 0;
      let v;
      if (type === "bb") v = Math.round(value * this.bigBlind);
      else v = Math.round((this._callAmount || 0) + (pot * value) / 100);
      this.setBetValue(v);
    }

    quickAllin() { this.setBetValue(+this.$input.max); }

    setBetValue(v) {
      v = clampInt(v, +this.$input.min, +this.$input.max);
      this.$input.value = v; this.$slider.value = v;
    }

    disableControls() {
      this.myTurn = false;
      [this.$fold, this.$call, this.$raise, this.$slider, this.$input].forEach((e) => (e.disabled = true));
      this.$quickRow.querySelectorAll("button").forEach((b) => (b.disabled = true));
    }

    send(action, amount) {
      // Guard: ignore any action unless it is actually the player's turn.
      if (!this.myTurn) return;
      if (!this.ws || this.ws.readyState !== 1) return;
      this.disableControls();
      this.ws.send(JSON.stringify({ type: "action", action, amount: amount || 0 }));
    }

    // ---- stats & hand history ----
    recordHand(ev) {
      const v = ev.view;
      const board = (v.community_card || []).slice();
      const hero = v.seats.find((s) => s.is_hero);
      const winnerNames = (ev.winners || []).map((w) => {
        const s = v.seats.find((x) => x.uuid === w.uuid); return s ? s.name : "?";
      });
      this.hands.push({
        n: v.round_count, board,
        heroCards: hero ? hero.hole_cards : null,
        revealed: ev.revealed || {},
        winners: winnerNames,
        seats: v.seats.map((s) => ({ uuid: s.uuid, name: s.name })),
      });
      // tally stats from winners + presence
      v.seats.forEach((s) => {
        const st = (this.stats[s.uuid] = this.stats[s.uuid] || { name: s.name, played: 0, won: 0 });
        st.played += 1;
        if ((ev.winners || []).some((w) => w.uuid === s.uuid)) st.won += 1;
      });
      this.renderStats(); this.renderHands();
    }

    renderStats() {
      const el = document.getElementById("tab-stats");
      const rows = Object.values(this.stats)
        .map((s) => `<tr><td>${esc(s.name)}</td><td>${s.played}</td><td>${s.won}</td></tr>`)
        .join("");
      el.innerHTML = `<table class="stat-table"><thead><tr><th>Player</th><th>Hands</th><th>Won</th></tr></thead>` +
        `<tbody>${rows || '<tr><td colspan=3 class="muted">No hands yet</td></tr>'}</tbody></table>`;
    }

    renderHands() {
      const el = document.getElementById("tab-hands");
      el.innerHTML = this.hands.slice().reverse().map((h) => {
        const board = h.board.map((c) => `<span class="pcard">${suitGlyph(c)}</span>`).join("");
        const heroC = (h.heroCards || []).join(" ") || "—";
        const reveals = Object.entries(h.revealed).map(([u, c]) => {
          const nm = (h.seats.find((s) => s.uuid === u) || {}).name || "?";
          return `${esc(nm)}: ${c.join(" ")}`;
        }).join(" · ");
        return `<div class="hand-entry"><b>Hand #${h.n}</b>` +
          `<div class="board">${board || '<span class="muted tiny">no board</span>'}</div>` +
          `<div class="tiny">You: ${heroC}</div>` +
          (reveals ? `<div class="tiny muted">Shown — ${reveals}</div>` : "") +
          `<div class="tiny win">Winner: ${h.winners.join(", ")}</div></div>`;
      }).join("") || '<p class="muted">No completed hands yet.</p>';
    }

    switchTab(name) {
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
      document.getElementById("tab-stats").classList.toggle("hidden", name !== "stats");
      document.getElementById("tab-hands").classList.toggle("hidden", name !== "hands");
    }

    setMessage(text) { this.$message.textContent = text; }
  }

  // ---- helpers ----
  function clampInt(v, lo, hi) { v = parseInt(v, 10); if (isNaN(v)) v = lo; return Math.max(lo, Math.min(v, hi)); }
  function potTotal(pot) {
    if (!pot) return 0;
    const m = (pot.main && pot.main.amount) || 0;
    const s = (pot.side || []).reduce((a, x) => a + (x.amount || 0), 0);
    return m + s;
  }
  function suitGlyph(code) {
    const s = SUIT[code[0]] || { g: "?" }; const r = code.slice(1).replace("T", "10");
    return `${r}${s.g}`;
  }
  function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }
  function trim(n) { return Number.isInteger(n) ? String(n) : String(+(+n).toFixed(2)); }
  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  window.PokerTable = {
    mount(gameId, wsUrl) {
      const ui = new TableUI(gameId, wsUrl);
      ui.connect();
      window.__ptui = ui;  // exposed for debugging/testing
      return ui;
    },
  };
})();
