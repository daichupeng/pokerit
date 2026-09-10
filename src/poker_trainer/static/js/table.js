/* Poker table rendering, bet controls, and the WebSocket play client.
 * Cards are drawn with CSS (no external assets) so the app works fully offline.
 * Exposes window.PokerTable.mount(gameId, wsUrl) used by the router in app.js.
 */
(function () {
  "use strict";

  // Card format: rank+suit lowercase, e.g. "As", "Tc", "2h"
  const SUIT = { s: { g: "♠", c: "black" }, h: { g: "♥", c: "red" },
                 d: { g: "♦", c: "red" }, c: { g: "♣", c: "black" } };

  function cardEl(code, opts) {
    opts = opts || {};
    const el = document.createElement("div");
    el.className = "pcard" + (opts.hero ? " hero" : opts.lg ? " lg" : "") + (opts.dimmed ? " dimmed" : "");
    if (!code) { el.classList.add("placeholder"); return el; }
    if (code === "back") { el.classList.add("back"); return el; }
    // code like "As", "Tc", "2h"
    const rank = code[0].replace("T", "10"), suit = code[1];
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
    // Positions go clockwise from hero (bottom-center): next seat is bottom-right,
    // then right, top-right, top-left, left, bottom-left.
    // All layouts: hero at index 0 (bottom-center), remaining seats clockwise.
    // Clockwise from hero: bottom-right → right → top-right → top → top-left → left → bottom-left.
    const layouts = {
      2: [[50, 96], [50, 8]],
      3: [[50, 96], [88, 40], [12, 40]],
      4: [[50, 96], [92, 56], [50, 8], [8, 56]],
      5: [[50, 96], [92, 65], [80, 16], [20, 16], [8, 65]],
      6: [[50, 96], [93, 56], [88, 22], [50, 10], [12, 22], [7, 56]],
      7: [[50, 96], [88, 74], [93, 34], [70, 12], [30, 12], [7, 34], [12, 74]],
      8: [[50, 96], [82, 78], [97, 46], [84, 14], [50, 8], [16, 14], [3, 46], [18, 78]],
      9: [[50, 98], [80, 83], [97, 52], [94, 22], [65, 8], [35, 8], [6, 22], [3, 52], [20, 83]],
    };
    if (layouts[n]) return layouts[n];
    // fallback: evenly distribute the bots around the ring, hero at bottom.
    // Leave a slightly wider gap at the bottom for the hero by spanning the
    // bots across ~290° of the ellipse rather than the full circle, and keep
    // the top of the ring low enough for the upward cards.
    const pos = [[50, 90]];
    const span = 2 * Math.PI * (290 / 360);
    // Arc spans 290° centered at top of oval. Start at bottom-right (t = π/2 − span/2)
    // and increment t so seats go clockwise: bottom-right → right → top → left → bottom-left.
    const start = Math.PI / 2 - span / 2;
    for (let i = 1; i < n; i++) {
      const t = start + (span * (i - 1)) / Math.max(n - 2, 1);
      pos.push([50 + 44 * Math.cos(t), 42 - 34 * Math.sin(t)]);
    }
    return pos;
  }

  function seatRegion(x, y, isHero) {
    if (isHero) return "bottom";
    if (x <= 25) return "left";
    if (x >= 75) return "right";
    if (y <= 28) return "top";
    return "bottom";
  }

  function betPosition(x, y, region, isHero) {
    if (isHero) return [62, 68];
    if (region === "left" || region === "right") {
      const left = region === "left";
      if (y <= 30) return [left ? 36 : 64, 45];
      if (y >= 70) return [left ? 28 : 72, 59];
      return [left ? 30 : 70, y + (50 - y) * 0.2];
    }
    if (region === "top") {
      const offset = x === 50 ? 10 : x < 50 ? 7 : -7;
      return [x + offset, 32];
    }
    return [x + (50 - x) * 0.25, 70];
  }

  function seatActionBadge(seat, terminal) {
    let action = "";
    let label = "";
    if (terminal) {
      if (terminal.status === "win") {
        action = "win";
        label = "WIN";
      } else if (terminal.status === "showdown") {
        action = "showdown";
        label = terminal.was_allin ? "ALL-IN · SHOWDOWN" : "SHOWDOWN";
      } else if (terminal.status === "mucked") {
        action = "mucked";
        label = "MUCKED";
      } else if (terminal.status === "fold") {
        action = "fold";
        label = "FOLD";
      }
    } else if (seat.state === "folded" && !seat.is_sitting_out) {
      action = "fold";
      label = "FOLD";
    } else if (seat.state === "allin") {
      action = "allin";
      label = "ALL-IN";
    } else if (seat.last_action) {
      const raw = String(seat.last_action.action || "").toUpperCase();
      const amount = Number(seat.last_action.amount || 0);
      if (raw === "CALL" && amount === 0) {
        action = "check";
        label = "CHECK";
      } else if (raw === "CALL") {
        action = "call";
        label = `CALL ${amount}`;
      } else if (raw === "RAISE") {
        action = "raise";
        label = `RAISE TO ${amount}`;
      } else if (raw === "BET") {
        action = "raise";
        label = `BET ${amount}`;
      } else if (raw === "FOLD") {
        action = "fold";
        label = "FOLD";
      }
    }
    if (!label) return null;
    const badge = document.createElement("div");
    badge.className = `seat-action action-${action}`;
    badge.textContent = label;
    badge.title = terminal ? `Hand result: ${label}` : `Last action: ${label}`;
    return badge;
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
      this.raiseAmountReady = false; // R is armed only after the player chooses/edits a size
      this.stats = {};         // uuid -> {name, played, won, net}
      this.hands = [];         // completed hand summaries
      this.showdown = null;
      this.winnerUuids = null;
      this.terminalStatuses = null;
      this.revealedCards = {};
      this.visibleHandNum = null;
      this._coachConversationId = null;
      this._coachHandNum = null;
      this._coachContextVersion = 0;
      this.bind();
    }

    bind() {
      this.$seats = document.getElementById("seats");
      this.$community = document.getElementById("community");
      this.$pot = document.getElementById("pot");
      this.$message = document.getElementById("message");
      this.$controls = document.getElementById("controls");
      this.$actionHint = document.getElementById("action-hint");
      this.$slider = document.getElementById("bet-slider");
      this.$input = document.getElementById("bet-input");
      this.$fold = document.getElementById("btn-fold");
      this.$call = document.getElementById("btn-call");
      this.$raise = document.getElementById("btn-raise");
      this.$quickRow = document.getElementById("quick-row");
      this.$blinds = document.getElementById("table-blinds");
      this.$hand = document.getElementById("table-hand");
      this.$endGame = document.getElementById("end-game-btn");

      this.$slider.addEventListener("input", () => {
        this.$input.value = this.$slider.value;
        this.markRaiseAmountEdited();
      });
      this.$input.addEventListener("input", () => {
        let v = clampInt(this.$input.value, +this.$input.min, +this.$input.max);
        this.$slider.value = v;
        this.markRaiseAmountEdited();
      });
      this.$fold.addEventListener("click", () => this.send("fold", 0));
      this.$call.addEventListener("click", () => this.send("call", this._callAmount));
      this.$raise.addEventListener("click", () => {
        const v = clampInt(this.$input.value, +this.$input.min, +this.$input.max);
        this.send("raise", v);
      });
      this.$endGame.addEventListener("click", () => this.endGame());
      document.querySelectorAll("[data-quick]").forEach((b) =>
        b.addEventListener("click", () => this.quick(b.dataset.quick)));

      this.setShortcutButtonContent(this.$fold, "Fold", "F");
      this.$fold.title = "Keyboard shortcut: F";
      this.$fold.setAttribute("aria-keyshortcuts", "f");
      this.$raise.title = "Keyboard shortcut: R (choose or edit a size first)";
      this.$raise.setAttribute("aria-keyshortcuts", "r");
      this._keyboardHandler = (e) => this.handleKeyboardShortcut(e);
      document.addEventListener("keydown", this._keyboardHandler);

      document.getElementById("topbar-home").addEventListener("click", () => {
        window.location.hash = "#/main";
      });

      document.getElementById("toggle-panel").addEventListener("click", () => {
        const p = document.getElementById("side-panel");
        const isHidden = p.classList.toggle("hidden");
        if (!isHidden) this.switchTab("coach");
      });
      document.querySelectorAll(".tab").forEach((t) =>
        t.addEventListener("click", () => this.switchTab(t.dataset.tab)));
    }

    unbindKeyboardShortcuts() {
      if (this._keyboardHandler) {
        document.removeEventListener("keydown", this._keyboardHandler);
        this._keyboardHandler = null;
      }
    }

    handleKeyboardShortcut(e) {
      if (!this.myTurn || e.defaultPrevented || e.repeat || e.altKey || e.ctrlKey || e.metaKey) return;

      const key = e.key.toLowerCase();

      // Inputs (including the bet amount and coach chat) keep normal typing
      // behaviour and never trigger an action at the table. A hidden input
      // from the previous SPA screen may still have focus. The two bet editors
      // are the sole exception: after changing one, R may submit its value.
      const target = e.target;
      const editable = target && target.closest
        ? target.closest("input, textarea, select, [contenteditable]")
        : null;
      if (editable && editable.getClientRects().length > 0) {
        const isBetEditor = editable === this.$input || editable === this.$slider;
        if (!isBetEditor || key !== "r") return;
      }

      if (key === "f" && !this.$fold.disabled) {
        e.preventDefault();
        this.$fold.click();
        return;
      }
      // The same control is Check when there is nothing to call and Call
      // otherwise, so C safely covers both mutually exclusive actions.
      if (key === "c" && !this.$call.disabled) {
        e.preventDefault();
        this.$call.click();
        return;
      }
      if (key === "r" && !this.$raise.disabled) {
        e.preventDefault();
        if (!this.raiseAmountReady) {
          this.$actionHint.textContent = "Choose a size (1–4) or adjust the amount before pressing R";
          this.$controls.classList.add("needs-raise-size");
          return;
        }
        this.$raise.click();
        return;
      }
      if (/^[1-4]$/.test(key)) {
        const preset = this.$quickRow.querySelector(`[data-preset-index="${Number(key) - 1}"]`);
        if (preset && !preset.disabled) {
          e.preventDefault();
          preset.click();
        }
      }
    }

    setShortcutButtonContent(button, label, shortcut) {
      button.innerHTML = "";
      const key = document.createElement("kbd");
      key.textContent = shortcut;
      const text = document.createElement("span");
      text.textContent = label;
      button.appendChild(key);
      button.appendChild(text);
    }

    markRaiseAmountEdited(selectedButton) {
      this.raiseAmountReady = true;
      this.$controls.classList.remove("needs-raise-size");
      this.$quickRow.querySelectorAll("button").forEach((button) => {
        button.classList.toggle("selected-size", button === selectedButton);
      });
    }

    connect() {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      this.ws = new WebSocket(`${proto}://${location.host}${this.wsUrl}`);
      this.ws.onmessage = (e) => this.onMessage(JSON.parse(e.data));
      this.ws.onclose = () => {
        if (!this.gameFinished) this.setMessage("Disconnected.");
      };
    }

    endGame() {
      if (this.saveFailed) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
          this.setMessage("Reconnecting to retry saving…");
          this.connect();
          return;
        }
        this.$endGame.disabled = true;
        this.setMessage("Retrying save…");
        this.ws.send(JSON.stringify({ type: "retry_save" }));
        return;
      }
      if (this.gameFinished || this.$endGame.disabled) return;
      const confirmed = window.confirm(
        "End this game now? Completed hands will be saved; the current unfinished hand will not count."
      );
      if (!confirmed) return;
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        this.setMessage("Cannot end the game while disconnected.");
        return;
      }
      this.$endGame.disabled = true;
      this.$endGame.textContent = "Ending…";
      this.disableControls();
      this.setMessage("Ending game and saving completed hands…");
      this.ws.send(JSON.stringify({ type: "end_game" }));
    }

    onMessage(msg) {
      if (msg.type === "init") {
        if (msg.config) {
          this.bigBlind = msg.config.big_blind || 0;
          this.startingStackBB = msg.config.starting_stack_bb || 0;
          this.scenario = msg.config.scenario || "custom";
          this.ante = msg.config.ante || 0;
          this.anteType = msg.config.ante_type || "none";
          this.preflopQuick = msg.config.preflop_quick || [];
          this.postflopQuick = msg.config.postflop_quick || [];
        }
        if (msg.view) this.render(msg.view);
        if (msg.pending_ask) this.onAsk(msg.pending_ask);
        return;
      }
      if (msg.type === "event") return this.onEvent(msg.event);
      if (msg.type === "stats_update") {
        this.serverStats = msg.stats;
        this.renderStats();
        return;
      }
      if (msg.type === "saved") {
        this.saveFailed = false;
        this.gameFinished = true;
        this.$endGame.disabled = true;
        this.$endGame.textContent = "Game ended";
        sessionStorage.removeItem("pt_ws_" + this.gameId);
        this.setMessage("Game over. Result saved.");
        this.disableControls();
        return;
      }
      if (msg.type === "persist_error") {
        this.saveFailed = true;
        if (msg.finished) {
          this.gameFinished = true;
          this.disableControls();
        }
        this.$endGame.disabled = false;
        this.$endGame.textContent = "Retry save";
        this.setMessage(msg.message);
        return;
      }
      if (msg.type === "save_status" && msg.saved) {
        const wasRetrying = this.saveFailed;
        this.saveFailed = false;
        this.$endGame.disabled = Boolean(this.gameFinished);
        this.$endGame.textContent = this.gameFinished ? "Game ended" : "End game";
        if (wasRetrying) this.setMessage("Completed hands saved.");
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
        case "showdown_reveal":
          this.rememberRevealed(ev.revealed);
          if (this.lastView) this.render(this.lastView);
          this.setMessage("All-in — live hands shown");
          break;
        case "round_finish":
          // Stash showdown info so render() can show hand labels and dim the
          // winner's unused cards. Cleared by the next non-showdown render.
          this.showdown = {};
          (ev.showdown || []).forEach((s) => (this.showdown[s.uuid] = s));
          this.winnerUuids = new Set((ev.winners || []).map((w) => typeof w === "string" ? w : w.uuid));
          this.terminalStatuses = ev.terminal_statuses || null;
          this.rememberRevealed(ev.revealed);
          if (ev.view) this.render(ev.view);
          this.recordHand(ev);
          this.announceWinners(ev.winners, ev.view);
          this.animatePotAward(ev.pot_winners, ev.view);
          break;
        case "ask":
          this.onAsk(ev);
          break;
        case "game_finish":
          this.gameFinished = true;
          this.$endGame.disabled = true;
          this.$endGame.textContent = "Game ended";
          this.setMessage(ev.reason === "ended_by_player" ? "Game ended. Saving…" : "Game finished.");
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
      if (this.visibleHandNum !== view.round_count) {
        this.visibleHandNum = view.round_count;
        this.revealedCards = {};
        this.terminalStatuses = null;
      }
      (view.seats || []).forEach((seat) => {
        if (this.revealedCards[seat.uuid]) {
          seat.hole_cards = this.revealedCards[seat.uuid];
        }
      });
      this.lastView = view;
      if (view.street) this.street = view.street;
      this.onCoachHand(view.round_count);
      if (!this.seatPos) this.seatPos = seatPositions(view.seats.length);
      // identify hero
      const hero = view.seats.find((s) => s.is_hero);
      if (hero) this.heroUuid = hero.uuid;

      const bb = view.big_blind_amount || view.small_blind_amount * 2;
      const anteText = (view.ante_type === "big_blind" && view.ante)
        ? ` · BB Ante ${view.ante}` : "";
      this.$blinds.textContent = `${this.scenario.replace(/_/g, " ")} · ${this.startingStackBB}BB · Blinds ${view.small_blind_amount}/${bb}${anteText}`;
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

      // seats — rotate so hero is always at position 0 (bottom-center), then
      // proceed clockwise around the table.
      this.$seats.innerHTML = "";
      this.seatEls = {};  // uuid -> {el, x, y} for the pot-award animation
      // Rotate hero to index 0, then reverse the remaining seats so they go
      // left-first on screen (SB to hero's left), matching poker's clockwise action.
      const heroIdx = view.seats.findIndex((s) => s.is_hero);
      const shifted = heroIdx <= 0 ? view.seats
        : [...view.seats.slice(heroIdx), ...view.seats.slice(0, heroIdx)];
      const rotatedSeats = shifted.length <= 1 ? shifted
        : [shifted[0], ...shifted.slice(1).reverse()];
      rotatedSeats.forEach((seat, i) => {
        const terminal = this.terminalStatuses ? this.terminalStatuses[seat.uuid] : null;
        const isMucked = terminal && terminal.status === "mucked";
        const [x, y] = this.seatPos[i] || [50, 50];
        const el = document.createElement("div");
        const region = seatRegion(x, y, seat.is_hero);
        el.className = "seat" + (seat.state === "folded" ? " folded" : "") +
          (seat.is_hero ? " hero-seat" : "") + ` seat-${region}`;
        if (actingUuid && seat.uuid === actingUuid) el.classList.add("acting");
        else if (!actingUuid && seat.pos === view.next_player) el.classList.add("acting");
        el.style.left = x + "%"; el.style.top = y + "%";
        // Anchor rim seats inward so their cards/plates never grow outside the
        // felt and into the action controls. Middle seats remain centered.
        el.style.setProperty("--seat-tx", x <= 22 ? "0%" : x >= 78 ? "-100%" : "-50%");
        el.style.setProperty("--seat-ty", y <= 25 ? "0%" : y >= 70 ? "-100%" : "-50%");
        this.seatEls[seat.uuid] = { el, x, y };

        // Hero cards are deliberately larger; opponent cards stay compact so
        // full-ring layouts remain readable at 100% browser zoom. At showdown:
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
            hole.appendChild(cardEl(c, { hero: seat.is_hero, dimmed: dimCard(c) })));
        } else if (seat.state !== "folded" && !seat.is_sitting_out && !isMucked) {
          hole.appendChild(cardEl("back", { hero: seat.is_hero }));
          hole.appendChild(cardEl("back", { hero: seat.is_hero }));
        }

        const plate = document.createElement("div");
        plate.className = "plate";
        const styleTag = seat.style ? `<div class="style-tag">${seat.style}</div>` : "";
        const labelTag = sdEntry ? `<div class="hand-label">${esc(sdEntry.hand_label)}</div>` : "";
        plate.innerHTML =
          `<div class="name">${esc(seat.name)}${seat.is_hero ? " (you)" : ""}</div>` +
          `<div class="stack">${seat.stack}</div>` + styleTag + labelTag;

        const badges = document.createElement("div");
        badges.className = "badges";
        const pos = seat.position || "";
        if (pos && seat.state !== "folded") {
          const posClass = {
            "BTN": "btn-d", "SB": "sb", "BB": "bb",
            "CO": "co", "UTG": "utg", "HJ": "hj",
            "UTG+1": "utg1", "HJ-1": "hj1", "UTG+2": "utg2",
          }[pos] || "pos-other";
          badges.innerHTML += `<span class="badge ${posClass}">${pos}</span>`;
        }

        const meta = document.createElement("div");
        meta.className = "seat-meta";
        meta.appendChild(plate);
        if (!seat.is_hero) {
          const actionSlot = document.createElement("div");
          actionSlot.className = "seat-action-slot";
          const actionBadge = seatActionBadge(seat, terminal);
          if (actionBadge) actionSlot.appendChild(actionBadge);
          meta.appendChild(actionSlot);
        }
        meta.appendChild(badges);

        // The pod owns cards, information, position, and last action. Side
        // seats switch to a horizontal orientation so neighbouring pods do not
        // grow into each other when the felt becomes narrow.
        el.appendChild(hole); el.appendChild(meta);
        this.$seats.appendChild(el);

        // The current bet sits between the seat and the table center, so it
        // reads as chips pushed toward the pot. Positioned absolutely on the
        // felt (not inside the seat) so it can overlap the green.
        if (seat.bet > 0) {
          const bet = document.createElement("div");
          bet.className = "bet-chip";
          bet.innerHTML = `<span class="chip"></span>${seat.bet}`;
          // Each table region has a dedicated inward chip lane. This keeps a
          // player's bet clear of both their own pod and neighbouring seats.
          const [bx, by] = betPosition(x, y, region, seat.is_hero);
          bet.style.left = bx + "%"; bet.style.top = by + "%";
          this.$seats.appendChild(bet);
        }
      });
    }

    // End of a street: the bet chips currently shown in front of the players
    // slide into the pot, then the new street's view (with its new card) renders.
    collectBetsThenRender(ev) {
      const streetMessage = cap(ev.street) + ((ev.rebuys || []).length
        ? " · " + ev.rebuys.map(r => `${r.name} bought in for ${r.amount}`).join("; ")
        : "");
      const chips = Array.from(this.$seats.querySelectorAll(".bet-chip"));
      if (!chips.length) {
        if (ev.view) this.render(ev.view);
        this.setMessage(streetMessage);
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
        this.setMessage(streetMessage);
      }, SLIDE_MS + 60);
    }

    rememberRevealed(revealed) {
      if (!revealed) return;
      Object.entries(revealed).forEach(([uuid, cards]) => {
        this.revealedCards[uuid] = cards;
      });
    }

    announceWinners(winners, view) {
      if (!winners || !view) return;
      const names = winners.map((w) => {
        const uuid = typeof w === "string" ? w : w.uuid;
        const s = view.seats.find((x) => x.uuid === uuid);
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
      presets.forEach((value, index) => {
        const b = document.createElement("button");
        b.className = "btn tiny";
        const label = preflop ? `${trim(value)}× BB` : `${trim(value)}% Pot`;
        if (index < 4) this.setShortcutButtonContent(b, label, String(index + 1));
        else b.textContent = label;
        b.disabled = !enabled;
        b.dataset.presetIndex = index;
        if (index < 4) {
          b.title = `Keyboard shortcut: ${index + 1}`;
          b.setAttribute("aria-keyshortcuts", String(index + 1));
        }
        b.addEventListener("click", () => this.quickPreset(preflop ? "bb" : "pot", value, b));
        this.$quickRow.appendChild(b);
      });
      const allin = document.createElement("button");
      allin.className = "btn tiny";
      allin.textContent = "All-in";
      allin.disabled = !enabled;
      allin.addEventListener("click", () => this.quickAllin(allin));
      this.$quickRow.appendChild(allin);
    }

    enableControls(valid) {
      this.$controls.classList.remove("hidden");
      const by = {}; valid.forEach((a) => (by[a.action] = a));
      const callAmt = by.call ? by.call.amount : 0;
      this._callAmount = callAmt;
      const raise = by.raise ? by.raise.amount : { min: -1, max: -1 };
      const canRaise = raise.min !== -1 && raise.max !== -1;
      const canCheck = callAmt === 0;

      // Fold always; Check/Bet vs Call/Raise depending on call amount
      this.$fold.disabled = false;
      this.$call.disabled = false;
      this.setShortcutButtonContent(this.$call, canCheck ? "Check — Free" : `Call ${callAmt}`, "C");
      this.$call.title = "Keyboard shortcut: C";
      this.$call.setAttribute("aria-keyshortcuts", "c");
      this.$call.classList.toggle("check-ready", canCheck);
      this.$controls.classList.toggle("can-check", canCheck);
      this.$actionHint.textContent = canCheck
        ? "No bet to call — check for free"
        : `Your turn — ${callAmt} to call`;
      this.$actionHint.classList.toggle("check-ready", canCheck);
      this.setMessage(canCheck ? "Your turn — CHECK is free" : "Your turn", canCheck ? "check" : "turn");

      if (canRaise) {
        this.$raise.disabled = false;
        this.setShortcutButtonContent(this.$raise, callAmt === 0 ? "Bet" : "Raise", "R");
        this.setBetBounds(raise.min, raise.max);
      } else {
        this.$raise.disabled = true;
        this.setBetBounds(0, 0, true);
      }
      // Rebuild for the current street (preset set + labels depend on it).
      this.buildQuickButtons(canRaise);
    }

    setBetBounds(min, max, disabled) {
      this.raiseAmountReady = false;
      this.$controls.classList.remove("needs-raise-size");
      [this.$slider, this.$input].forEach((el) => {
        el.min = min; el.max = max; el.value = min;
        el.disabled = !!disabled;
      });
    }

    // A preset maps to a raise-TO amount: a BB-multiple (preflop), or a fraction
    // of the pot added on top of the call (postflop). Clamped to the legal range.
    quickPreset(type, value, selectedButton) {
      const pot = this.lastView ? potTotal(this.lastView.pot) : 0;
      let v;
      if (type === "bb") v = Math.round(value * this.bigBlind);
      else v = Math.round((this._callAmount || 0) + (pot * value) / 100);
      this.setBetValue(v, selectedButton);
    }

    quickAllin(selectedButton) { this.setBetValue(+this.$input.max, selectedButton); }

    setBetValue(v, selectedButton) {
      v = clampInt(v, +this.$input.min, +this.$input.max);
      this.$input.value = v; this.$slider.value = v;
      this.markRaiseAmountEdited(selectedButton);
    }

    disableControls() {
      this.myTurn = false;
      [this.$fold, this.$call, this.$raise, this.$slider, this.$input].forEach((e) => (e.disabled = true));
      this.$quickRow.querySelectorAll("button").forEach((b) => (b.disabled = true));
      this.$controls.classList.remove("can-check");
      this.$call.classList.remove("check-ready");
      this.$actionHint.classList.remove("check-ready");
      this.$actionHint.textContent = "";
    }

    send(action, amount) {
      // Guard: ignore any action unless it is actually the player's turn.
      if (!this.myTurn) return;
      if (!this.ws || this.ws.readyState !== 1) return;
      this.disableControls();
      this.setMessage("Action submitted…");
      this.ws.send(JSON.stringify({ type: "action", action, amount: amount || 0 }));
    }

    // ---- stats & hand history ----
    recordHand(ev) {
      const v = ev.view;
      const board = (v.community_card || []).slice();
      const hero = v.seats.find((s) => s.is_hero);
      const winnerNames = (ev.winners || []).map((w) => {
        const uuid = typeof w === "string" ? w : w.uuid;
        const s = v.seats.find((x) => x.uuid === uuid); return s ? s.name : "?";
      });
      this.hands.push({
        n: v.round_count, board,
        heroCards: hero ? hero.hole_cards : null,
        revealed: ev.history_revealed || ev.revealed || {},
        terminalStatuses: ev.terminal_statuses || {},
        winners: winnerNames,
        seats: v.seats.map((s) => ({ uuid: s.uuid, name: s.name })),
      });
      // tally stats from winners + presence
      v.seats.forEach((s) => {
        const st = (this.stats[s.uuid] = this.stats[s.uuid] || { name: s.name, played: 0, won: 0 });
        st.played += 1;
        if ((ev.winners || []).some((w) => (typeof w === "string" ? w : w.uuid) === s.uuid)) st.won += 1;
      });
      this.renderStats(); this.renderHands();
    }

    renderStats() {
      const el = document.getElementById("tab-stats");
      if (this.serverStats) {
        el.innerHTML = heroStatsHTML(this.serverStats);
        return;
      }
      const rows = Object.values(this.stats)
        .map((s) => `<tr><td>${esc(s.name)}</td><td>${s.played}</td><td>${s.won}</td></tr>`)
        .join("");
      el.innerHTML = `<table class="stat-table"><thead><tr><th>Player</th><th>Hands</th><th>Won</th></tr></thead>` +
        `<tbody>${rows || '<tr><td colspan=3 class="muted">No hands yet</td></tr>'}</tbody></table>`;
    }

    renderHands() {
      const el = document.getElementById("tab-hands");
      el.innerHTML = this.hands.slice().reverse().map((h) => {
        const board = h.board.map((c) => cardInline(c)).join(" ");
        const heroC = h.heroCards && h.heroCards.length
          ? h.heroCards.map((c) => cardInline(c)).join(" ")
          : "—";
        const reveals = Object.entries(h.revealed).map(([u, c]) => {
          const nm = (h.seats.find((s) => s.uuid === u) || {}).name || "?";
          const cards = c.map((x) => cardInline(x)).join(" ");
          const terminal = h.terminalStatuses[u];
          const suffix = terminal && terminal.status === "mucked" ? " (mucked)" : "";
          return `${esc(nm)}${suffix}: ${cards}`;
        }).join(" · ");
        return `<div class="hand-entry"><b>Hand #${h.n}</b>` +
          `<div class="board">${board || '<span class="muted tiny">no board</span>'}</div>` +
          `<div class="tiny">You: ${heroC}</div>` +
          (reveals ? `<div class="tiny muted">Showdown cards — ${reveals}</div>` : "") +
          `<div class="tiny win">Winner: ${h.winners.join(", ")}</div></div>`;
      }).join("") || '<p class="muted">No completed hands yet.</p>';
    }

    switchTab(name) {
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
      document.getElementById("tab-stats").classList.toggle("hidden", name !== "stats");
      document.getElementById("tab-hands").classList.toggle("hidden", name !== "hands");
      document.getElementById("tab-coach").classList.toggle("hidden", name !== "coach");
    }

    // ---- coach chat ----
    onCoachHand(handNum) {
      if (!handNum || this._coachHandNum === handNum) return;
      const previousHand = this._coachHandNum;
      const hadCoachMessages = Boolean(
        document.querySelector("#coach-messages .coach-msg")
      );
      this._coachHandNum = handNum;
      if (previousHand === null) return;

      // Keep the visible transcript, but start a clean model conversation so
      // cards and strategic conclusions from the previous hand cannot leak in.
      this._coachConversationId = null;
      this._coachContextVersion += 1;
      if (hadCoachMessages) {
        const box = document.getElementById("coach-messages");
        if (box) {
          const banner = document.createElement("div");
          banner.className = "coach-hand-banner";
          banner.textContent = `Hand #${handNum} — new coach context`;
          box.appendChild(banner);
          box.scrollTop = box.scrollHeight;
        }
      }
    }

    initCoach(gameId) {
      this._coachGameId = gameId;
      this._coachConversationId = null;
      const form = document.getElementById("coach-form");
      if (!form) return;
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const input = document.getElementById("coach-input");
        const text = (input.value || "").trim();
        if (!text) return;
        input.value = "";
        this.coachSend(text);
      });
      // Allow Shift+Enter for newline, plain Enter to submit.
      document.getElementById("coach-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          document.getElementById("coach-form").dispatchEvent(new Event("submit"));
        }
      });
    }

    coachAppend(role, text, streaming) {
      const box = document.getElementById("coach-messages");
      if (!box) return null;
      const el = document.createElement("div");
      el.className = "coach-msg " + (role === "user" ? "coach-user" : "coach-assistant");
      if (streaming) el.classList.add("coach-streaming");
      el.textContent = text;
      box.appendChild(el);
      box.scrollTop = box.scrollHeight;
      return el;
    }

    async coachSend(text) {
      this.coachAppend("user", text, false);
      const bubbleEl = this.coachAppend("assistant", "…", true);
      const contextVersion = this._coachContextVersion;
      let conversationId = this._coachConversationId;

      // Pre-create the conversation with the correct entry_point on first message.
      if (!conversationId) {
        try {
          const conv = await fetch("/api/coach/conversations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ game_id: this._coachGameId || null, entry_point: "in_game" }),
          });
          if (conv.ok) {
            const data = await conv.json();
            conversationId = data.conversation_id;
            if (contextVersion === this._coachContextVersion) {
              this._coachConversationId = conversationId;
            }
          }
        } catch (_) {}
      }

      if (contextVersion !== this._coachContextVersion) {
        bubbleEl.textContent = "Hand changed — ask again for the current hand.";
        bubbleEl.classList.remove("coach-streaming");
        return;
      }

      const body = {
        message: text,
        game_id: this._coachGameId || null,
        conversation_id: conversationId || null,
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
        bubbleEl.textContent = "";
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
              bubbleEl.textContent = fullText;
              const box = document.getElementById("coach-messages");
              if (box) box.scrollTop = box.scrollHeight;
            } else if (payload.type === "done") {
              if (contextVersion === this._coachContextVersion) {
                this._coachConversationId = payload.conversation_id;
              }
              bubbleEl.classList.remove("coach-streaming");
            } else if (payload.type === "error") {
              bubbleEl.textContent = "Error: " + payload.message;
              bubbleEl.classList.remove("coach-streaming");
              bubbleEl.classList.add("coach-error");
            }
          }
        }
      } catch (err) {
        if (bubbleEl) {
          bubbleEl.textContent = "Error: " + err.message;
          bubbleEl.classList.remove("coach-streaming");
          bubbleEl.classList.add("coach-error");
        }
      }
    }

    setMessage(text, tone) {
      this.$message.textContent = text;
      this.$message.classList.toggle("check-prompt", tone === "check");
      this.$message.classList.toggle("turn-prompt", tone === "turn");
    }
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
    const r = code[0].replace("T", "10"), s = SUIT[code[1]] || { g: "?" };
    return `${r}${s.g}`;
  }
  function cardInline(code) {
    const s = SUIT[code[1]] || { g: "?", c: "black" };
    return `<span class="suit-${s.c}">${suitGlyph(code)}</span>`;
  }
  function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }
  function trim(n) { return Number.isInteger(n) ? String(n) : String(+(+n).toFixed(2)); }
  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  // ---- shared hero-stats formatting (used by both the live table and game
  // history — reads the {pct,n,d}/{ratio,n,d} shape returned by
  // GET /api/games/{id}/stats, /api/profile/stats, and the stats_update WS event) ----
  function pctLabel(stat) {
    if (!stat) return "—";
    if (stat.pct === null || stat.pct === undefined) return `— (${stat.n}/${stat.d})`;
    return `${stat.pct}% (${stat.n}/${stat.d})`;
  }

  function ratioLabel(stat) {
    if (!stat) return "—";
    if (stat.infinite) return `∞ (${stat.n}/${stat.d})`;
    if (stat.ratio === null || stat.ratio === undefined) return `— (${stat.n}/${stat.d})`;
    return `${stat.ratio} (${stat.n}/${stat.d})`;
  }

  function heroStatsHTML(s, opts) {
    opts = opts || {};
    const title = opts.title ? `<h4 class="stats-title">${esc(opts.title)}</h4>` : "";
    const rows = [
      ["VPIP", pctLabel(s.vpip)],
      ["PFR", pctLabel(s.pfr)],
      ["Total Limp", pctLabel(s.limp)],
      ["Non-SB Open Limp", pctLabel(s.open_limp)],
      ["Over-Limp", pctLabel(s.over_limp)],
      ["SB Complete", pctLabel(s.sb_complete)],
      ["Standard 3-Bet", pctLabel(s.three_bet)],
      ["Squeeze", pctLabel(s.squeeze)],
      ["Limp-Reraise", pctLabel(s.limp_reraise)],
      ["Fold to 3-Bet", pctLabel(s.fold_to_3bet)],
      ["C-Bet Flop", pctLabel(s.cbet && s.cbet.flop)],
      ["C-Bet Turn", pctLabel(s.cbet && s.cbet.turn)],
      ["C-Bet River", pctLabel(s.cbet && s.cbet.river)],
      ["Fold to C-Bet Flop", pctLabel(s.fold_to_cbet && s.fold_to_cbet.flop)],
      ["Fold to C-Bet Turn", pctLabel(s.fold_to_cbet && s.fold_to_cbet.turn)],
      ["Fold to C-Bet River", pctLabel(s.fold_to_cbet && s.fold_to_cbet.river)],
      ["WTSD", pctLabel(s.wtsd)],
      ["W$SD", pctLabel(s.wsd)],
      ["Aggression Factor", ratioLabel(s.aggression_factor)],
    ];
    const body = rows.map(([label, val]) => `<tr><td>${esc(label)}</td><td>${val}</td></tr>`).join("");
    const tableSizeRows = Object.entries(s.by_table_size || {})
      .sort((a, b) => Number(b[0]) - Number(a[0]))
      .map(([size, segment]) =>
        `<tr><td>${esc(size)}-handed</td><td>${pctLabel(segment.vpip)}</td><td>${pctLabel(segment.pfr)}</td></tr>`
      ).join("");
    const tableSizeBreakdown = tableSizeRows
      ? `<details class="table-size-stats"><summary>By players dealt</summary>` +
        `<table class="stat-table"><thead><tr><th>Table</th><th>VPIP</th><th>PFR</th></tr></thead>` +
        `<tbody>${tableSizeRows}</tbody></table></details>`
      : "";
    return `<div class="hero-stats">${title}` +
      `<p class="tiny muted">Hands dealt: ${s.hands_dealt}</p>${tableSizeBreakdown}` +
      `<table class="stat-table"><tbody>${body}</tbody></table></div>`;
  }
  window.heroStatsHTML = heroStatsHTML;

  window.PokerTable = {
    mount(gameId, wsUrl) {
      // SPA navigation can mount the table more than once. Keep only the
      // current table's document-level shortcut handler active.
      if (window.__ptui && window.__ptui.unbindKeyboardShortcuts) {
        window.__ptui.unbindKeyboardShortcuts();
      }
      const ui = new TableUI(gameId, wsUrl);
      ui.connect();
      ui.initCoach(gameId);
      window.__ptui = ui;  // exposed for debugging/testing
      return ui;
    },
  };
})();
