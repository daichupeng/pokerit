"""Shape engine state into JSON for the browser, enforcing the hidden-info rule.

With PokerKit, view building happens in GameSession._build_view() which has
direct access to the State object.  This module is kept for any helpers that
remain useful outside the session (e.g. tests).

The browser must only ever see:
  - public table info (names, stacks, states, bets, board, pot, positions),
  - the hero's own hole cards,
  - opponents' hole cards ONLY at a real showdown.
"""

from __future__ import annotations
