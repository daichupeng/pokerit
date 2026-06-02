from collections import Counter
from functools import reduce
from itertools import combinations, groupby

from pypokerengine.engine.hand_evaluator import HandEvaluator
from pypokerengine.engine.pay_info import PayInfo


# --- PokerTrainer: correct best-5-of-7 hand ranking (see __find_winners_from) ---
# Returns a tuple that orders hands exactly per poker rules, including kickers
# and the A-2-3-4-5 wheel. Larger tuple == stronger hand. Works on engine Card
# objects (which have integer .rank 2..14 and .suit).

def _straight_high(rank_set):
  rs = set(rank_set)
  if 14 in rs:
    rs = rs | {1}  # ace plays low for A-2-3-4-5
  for high in range(14, 4, -1):
    if all(r in rs for r in range(high, high - 5, -1)):
      return high
  return None

def _rank5(cards):
  ranks = sorted((c.rank for c in cards), reverse=True)
  suits = [c.suit for c in cards]
  counts = Counter(ranks)
  groups = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
  is_flush = len(set(suits)) == 1
  sh = _straight_high(set(ranks))
  if is_flush and sh: return (8, sh)
  if groups[0][1] == 4:
    return (7, groups[0][0], max(r for r in ranks if r != groups[0][0]))
  if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
    return (6, groups[0][0], groups[1][0])
  if is_flush: return (5, tuple(ranks))
  if sh: return (4, sh)
  if groups[0][1] == 3:
    return (3, groups[0][0], tuple(sorted((r for r in ranks if r != groups[0][0]), reverse=True)))
  if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
    hi, lo = sorted([groups[0][0], groups[1][0]], reverse=True)
    return (2, hi, lo, max(r for r in ranks if r != hi and r != lo))
  if groups[0][1] == 2:
    return (1, groups[0][0], tuple(sorted((r for r in ranks if r != groups[0][0]), reverse=True)))
  return (0, tuple(ranks))

def _best5_strength(hole, community):
  cards = list(hole) + list(community)
  if len(cards) < 5:
    return (0, tuple(sorted((c.rank for c in cards), reverse=True)))
  return max((_rank5(combo) for combo in combinations(cards, 5)))

class GameEvaluator:

  @classmethod
  def judge(self, table):
    winners = self.__find_winners_from(table.get_community_card(), table.seats.players)
    hand_info = self.__gen_hand_info_if_needed(table.seats.players, table.get_community_card())
    prize_map = self.__calc_prize_distribution(table.get_community_card(), table.seats.players)
    return winners, hand_info, prize_map

  @classmethod
  def create_pot(self, players):
    side_pots = self.__get_side_pots(players)
    main_pot = self.__get_main_pot(players, side_pots)
    return side_pots + [main_pot]

  @classmethod
  def gen_pots_with_winners(self, community_card, players):
    """PokerTrainer addition: per-pot breakdown with the winning uuids.

    Returns a list (main pot last, side pots before it) of
    ``{"amount": int, "eligibles": [uuid], "winners": [uuid]}`` so callers can
    animate each pot moving to its winner(s). Mirrors the per-pot logic used in
    __calc_prize_distribution, but exposes who won each pot.
    """
    result = []
    for pot in self.create_pot(players):
      winners = self.__find_winners_from(community_card, pot["eligibles"])
      result.append({
          "amount": pot["amount"],
          "eligibles": [p.uuid for p in pot["eligibles"]],
          "winners": [p.uuid for p in winners],
      })
    return result


  @classmethod
  def __calc_prize_distribution(self, community_card, players):
    prize_map = self.__create_prize_map(len(players))
    pots = self.create_pot(players)
    for pot in pots:
      winners = self.__find_winners_from(community_card, pot["eligibles"])
      prize = int(pot["amount"] / len(winners))
      for winner in winners:
        prize_map[players.index(winner)] += prize
    return prize_map

  @classmethod
  def __create_prize_map(self, player_num):
    def update(d, other): d.update(other); return d
    return reduce(update, [{i:0} for i in range(player_num)], {})

  @classmethod
  def __find_winners_from(self, community_card, players):
    # PokerTrainer fix: rank by a CORRECT best-5-of-7 comparison rather than
    # HandEvaluator.eval_hand. The latter packs the player's two hole-card ranks
    # into the score even when they are not part of the made hand, which mis-ranks
    # kickers and produces wrong winners/ties when players share the board (e.g.
    # both playing a straight on the board). This decides actual payouts too.
    active_players = [player for player in players if player.is_active()]
    scores = [_best5_strength(player.hole_card, community_card) for player in active_players]
    best_score = max(scores)
    return [p for p, s in zip(active_players, scores) if s == best_score]

  @classmethod
  def __gen_hand_info_if_needed(self, players, community):
    active_players = [player for player in players if player.is_active()]
    # PokerTrainer patch: expose exact hole-card strings for showdown
    # participants so records can show the actual cards revealed. This is only
    # generated when a showdown happens (>1 active player), so folded/unrevealed
    # hands are never included — preserving the hidden-information rule.
    gen_hand_info = lambda player: {
        "uuid": player.uuid,
        "hand": HandEvaluator.gen_hand_rank_info(player.hole_card, community),
        "hole_card": [str(card) for card in player.hole_card],
    }
    return [] if len(active_players) == 1 else [gen_hand_info(player) for player in active_players]

  @classmethod
  def __get_main_pot(self, players, sidepots):
    max_pay = max([pay.amount for pay in self.__get_payinfo(players)])
    return {
        "amount": self.__get_players_pay_sum(players) - self.__get_sidepots_sum(sidepots),
        "eligibles": [player for player in players if player.pay_info.amount == max_pay]
    }

  @classmethod
  def __get_players_pay_sum(self, players):
    return sum([pay.amount for pay in self.__get_payinfo(players)])

  @classmethod
  def __get_side_pots(self, players):
    pay_amounts = [payinfo.amount for payinfo in self.__fetch_allin_payinfo(players)]
    gen_sidepots = lambda sidepots, allin_amount: sidepots + [self.__create_sidepot(players, sidepots, allin_amount)]
    return reduce(gen_sidepots, pay_amounts, [])

  @classmethod
  def __create_sidepot(self, players, smaller_side_pots, allin_amount):
    return {
        "amount": self.__calc_sidepot_size(players, smaller_side_pots, allin_amount),
        "eligibles" : self.__select_eligibles(players, allin_amount)
    }

  @classmethod
  def __calc_sidepot_size(self, players, smaller_side_pots, allin_amount):
    add_chip_for_pot = lambda pot, player: pot + min(allin_amount, player.pay_info.amount)
    target_pot_size = reduce(add_chip_for_pot, players, 0)
    return target_pot_size - self.__get_sidepots_sum(smaller_side_pots)

  @classmethod
  def __get_sidepots_sum(self, sidepots):
    return reduce(lambda sum_, sidepot: sum_ + sidepot["amount"], sidepots, 0)

  @classmethod
  def __select_eligibles(self, players, allin_amount):
    return [player for player in players if self.__is_eligible(player, allin_amount)]

  @classmethod
  def __is_eligible(self, player, allin_amount):
    return player.pay_info.amount >= allin_amount and \
        player.pay_info.status != PayInfo.FOLDED

  @classmethod
  def __fetch_allin_payinfo(self, players):
    payinfo = self.__get_payinfo(players)
    allin_info = [info for info in payinfo if info.status == PayInfo.ALLIN]
    return sorted(allin_info, key=lambda info: info.amount)

  @classmethod
  def __get_payinfo(self, players):
    return [player.pay_info for player in players]
