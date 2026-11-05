"""The suggested mid bid for validated and still-launching ordinary keywords (Kim, 2026-10-31, decision 177: "stop
cutting validated or still-launching keywords to breakeven just because they convert at about the market rate. Bid them at
the suggested middle bid so they keep real visibility"; rulebook section 2, "The suggested mid").

Which keywords (state()):
  validated  a Hold keyword (its search converts at index 0.8 to under 1.1) whose search has 2+ orders, counted as
             max(SQP purchases, ad orders) like the ladder (lanes._ladder_orders); a Test or Discovery keyword with 2+
             orders at index 0.8 or more (on the ladder a Test search at 1.1+ goes to Prove first, under 0.8 to Trim;
             decision 178);
  testing    the launch test: a Test or Discovery keyword with 0 or 1 orders on fewer clicks than 2 expected orders at the
             product's ad conversion (launch.test_orders), at least launch.min_clicks (15) and at most launch.max_clicks (60)
             (Kim, 2026-10-31, decision 178: the test sized to each product's conversion; 20 clicks at 10%, 40 at 5%);
  extended   1 order past that: more clicks at the mid until 3 expected orders (launch.extend_orders; 30 at 10%, 60 at 5%,
             at most 1.5 x max_clicks), then judged again;
  failed     0 orders at 2 expected orders: the test is over, its role's own price (breakeven, Trim) and the leak check decide;
  judged     1 order at 3 expected orders: the test is over, its role's own price.
A keyword in its test (testing, extended) is not paused by the leak check until its test ends.
Only validated, testing and extended bid the mid (MID_STATES). The bid is the mid itself, above or below breakeven, never
Amazon's low or high and with no top-of-search boost; 75% of it on a search the product already ranks top 10 for. Only the
owning copy of a duplicated keyword (the most clicks) bids the mid; the other copies keep their role's price.

Where the mid comes from (pick(); Kim, 2026-10-31: "take the Amazon mid suggested bid by default. If it is rate-limited or
unavailable, then take Soldscope. If both are not available, then derive it using the next best possible calculation that
is close to it"):
  1. Amazon: the keyword's own recommendation (the live keyword read), else the suggested median of suggested_bids.json
     (exact) or suggested_bids_match.json (broad and phrase, {"broad": {"text": [low, median, high]}, "phrase": {...}});
  2. SoldScope's middle cost per click for the search (soldscope_bids.json), once Amazon was tried (bid_sources_tried.json);
  3. an estimate (estimate()): the higher of the keyword's own cost per click on bid_fallback.own_cpc_min_clicks (10)
     clicks and the median of Amazon's mids on the product's other searches this run (bid_fallback.peer_min_searches, 3,
     or more), the invest searches' estimate (bid_fallback.py); with neither, the same two on any clicks or any one search;
  4. none of those: no mid, and the keyword keeps its role's price.
"""
import json
import math
import os
import statistics

MID_STATES = ('validated', 'testing', 'extended')
MATCH_FILE = 'suggested_bids_match.json'


def settings(shared):
    """The rule's numbers from config.json (mid_bid, launch, the index bars), or None when mid_bid.enabled is off."""
    mb = shared.get('mid_bid') or {}
    if not mb.get('enabled'):
        return None
    th, lc, auto = shared.get('thresholds') or {}, shared.get('launch') or {}, shared.get('auto') or {}
    fb = shared.get('bid_fallback') or {}
    return dict(validated_orders=mb.get('validated_orders', 2), index_from=th.get('index_hold', 0.8),
                index_to=auto.get('prove_index', 1.1), test_orders=lc.get('test_orders', 2),
                extend_orders=lc.get('extend_orders', 3), min_clicks=lc.get('min_clicks', 15),
                max_clicks=lc.get('max_clicks', 60), cpc_min_clicks=fb.get('own_cpc_min_clicks', 10),
                min_peers=fb.get('peer_min_searches', 3),
                # decision 183 (Kim, 2026-11-04, the visibility test made the rule): the mid on Sponsored Products exact
                # keywords only; broad and phrase keywords and Sponsored Brands keywords keep their role's price (breakeven)
                match_types=tuple(m.lower() for m in mb.get('match_types', ('exact', 'broad', 'phrase'))),
                sponsored_brands=mb.get('sponsored_brands', True))


def test_ends(s, cvr):
    """The launch test's two ends in clicks for a product converting at cvr (its ad conversion): (0-order end, 1-order end).
    2 and 3 expected orders, between min_clicks and max_clicks (1.5 x max_clicks for the second); 20 and 30 at 10%."""
    first = min(s['max_clicks'], max(s['min_clicks'], math.ceil(s['test_orders'] / cvr - 1e-9))) if cvr and cvr > 0 else s['max_clicks']
    second = (min(1.5 * s['max_clicks'], max(first, math.ceil(s['extend_orders'] / cvr - 1e-9))) if cvr and cvr > 0
              else 1.5 * s['max_clicks'])
    return first, second


def state(role, clicks, orders, ladder_orders, index, s, cvr):
    """A keyword's state under decisions 177 and 178 (the module docstring), or None when the rule doesn't reach it.

    role: the keyword's role (Hold, Test, Discovery; any other returns None); clicks, orders: the keyword's own 90 days;
    ladder_orders: its search's orders on the ladder (max of SQP purchases, ad orders and its own), its own orders for a
    broad or phrase keyword; index: its search's index (an exact keyword) or its own conversion against the product's ad
    conversion (broad, phrase), None when unknown; cvr: the product's ad conversion, which sizes the launch test."""
    if role == 'Hold':
        return 'validated' if ladder_orders >= s['validated_orders'] else None
    if role not in ('Test', 'Discovery'):
        return None
    if ladder_orders >= s['validated_orders']:
        # an unknown index (no same-query market) is validated on its orders alone. A Test search at 1.1+ is Prove first on
        # the ladder, so one still a Test here (too few searches) or a broad keyword at 1.1+ keeps the mid, never less
        return 'validated' if index is None or index >= s['index_from'] - 1e-9 else None
    first, second = test_ends(s, cvr)
    if orders <= 0:
        return 'testing' if clicks < first else 'failed'
    if clicks < first:
        return 'testing'
    return 'extended' if clicks < second else 'judged'


def load_match(run):
    """Amazon's suggested bids for broad and phrase keywords (suggested_bids_match.json), {match: {text: [low, median,
    high]}}, keyed by the normal form of each keyword; "_" keys are notes."""
    from searchtext import norm
    path = os.path.join(run, MATCH_FILE)
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as fh:
        raw = json.load(fh)
    return {mt.lower(): {norm(k): v for k, v in (rows or {}).items() if not k.startswith('_')}
            for mt, rows in raw.items() if not mt.startswith('_') and isinstance(rows, dict)}


def estimate(own_cpc, own_clicks, peers, s):
    """The closest figure to Amazon's mid when Amazon and SoldScope have none: (value, words) or (None, None).

    First the invest searches' estimate (bid_fallback): the higher of the keyword's own cost per click on min_clicks clicks
    and the median of Amazon's mids on min_peers other searches; then, with neither, the higher of the two on any clicks or
    any one search."""
    for clicks_needed, peers_needed in ((s['cpc_min_clicks'], s['min_peers']), (1, 1)):
        own = own_cpc if own_cpc and own_clicks >= clicks_needed else None
        peer = statistics.median(peers) if len(peers) >= peers_needed else None
        bits = ([f'its own cost per click ${own:.2f} on {int(own_clicks)} clicks'] if own else []) + \
               ([f"the median of Amazon's mids on {len(peers)} other search{'es' if len(peers) != 1 else ''}, ${peer:.2f}"]
                if peer else [])
        if bits:
            value = round(max(x for x in (own, peer) if x), 2)
            return value, ('an estimate: ' + (bits[0] if len(bits) == 1 else 'the higher of ' + ' and '.join(bits)))
    return None, None


def pick(amazon, soldscope, tried, own_cpc, own_clicks, peers, s):
    """The mid and where it came from: (mid, source, words), source 'amazon', 'soldscope', 'estimate' or 'none'.

    amazon: (low, median, high) from Amazon or None; soldscope: SoldScope's [low, cpc, high] for the search or None, used
    only once Amazon was tried (tried); own_cpc, own_clicks: the keyword's 90 days; peers: Amazon's mids on the product's
    searches this run."""
    if amazon and amazon[1]:
        return round(amazon[1], 2), 'amazon', f"Amazon's suggested mid ${amazon[1]:.2f}"
    if tried and soldscope and soldscope[1]:
        return round(soldscope[1], 2), 'soldscope', f"SoldScope's middle cost per click ${soldscope[1]:.2f} (Amazon gave none)"
    if not tried:
        return None, 'none', 'Amazon not read yet'
    value, words = estimate(own_cpc, own_clicks, peers, s)
    if value:
        return value, 'estimate', words + ' (no Amazon or SoldScope mid)'
    return None, 'none', "no Amazon, SoldScope or estimated mid: its role's own price"


def owners(candidates):
    """The owning copy of each duplicated keyword: {(text, match): keyword id}, the copy with the most clicks (then orders,
    then the lowest id). candidates: (keyword id, text, match, clicks, orders)."""
    best = {}
    for kid, text, mt, clicks, orders in candidates:
        key = (text, mt)
        rank = (clicks, orders, -int(kid) if str(kid).isdigit() else 0)
        if key not in best or rank > best[key][0]:
            best[key] = (rank, kid)
    return {key: kid for key, (_, kid) in best.items()}


def words(st, s, cvr):
    """The state in plain words, for the row's why."""
    first, second = test_ends(s, cvr)
    return {'validated': f"validated ({s['validated_orders']}+ orders, converting at least like the market)",
            'testing': (f"in its launch test ({first:g} clicks, {s['test_orders']} expected orders at the product's "
                        f"{cvr:.1%} ad conversion)"),
            'extended': (f"1 order at {first:g}+ clicks: more clicks at the mid up to {second:g} ({s['extend_orders']} expected "
                         'orders), then judged again')}.get(st, st)
