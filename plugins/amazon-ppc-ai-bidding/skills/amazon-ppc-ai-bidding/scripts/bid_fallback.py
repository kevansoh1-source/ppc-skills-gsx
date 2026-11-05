"""Where an invest search's bid comes from when Amazon gives no suggested bid (Kim, 2026-10-23, decision 106; rulebook
section 1).

The planner asks for Amazon's suggested bid first (need_suggested_bids.json, exit 2). Amazon may have none for a search, or
keep rate-limiting the reads. Once the agent has tried Amazon, it records what happened in bid_sources_tried.json and reruns;
the planner then prices every invest search still without an Amazon suggestion itself, and the run goes on:
  1. SoldScope's estimate for that exact query (soldscope_bids.json, {"search": [cpcMin, cpc, cpcMax]}). A zero or missing
     cpc means SoldScope has none, never a free auction; a related query's estimate never stands in;
  2. an estimate: the higher of the search's own ad cost per click over the 90 days (on bid_fallback.own_cpc_min_clicks
     clicks or more) and the median of Amazon's suggested medians on the product's other searches this run (on
     bid_fallback.peer_min_searches searches or more). It has no high, so the bid is the estimate, or breakeven if higher;
  3. none of those: the no-suggestion bid of rulebook section 1, no_suggestion_multiplier x breakeven.
Every row priced this way says so (its bid_source and its why), and plan.json's summary lists them (bid_fallback).
A business (B2B) invest search has no fallback of its own: with Amazon tried, it takes the no-suggestion bid at its B2B
breakeven (business.bid_pull), because a consumer figure never prices a B2B auction (rulebook 9.7)."""
import json
import os
import statistics

TRIED = 'bid_sources_tried.json'
SOLDSCOPE = 'soldscope_bids.json'


def tried(run):
    """What the agent recorded after trying Amazon for the missing suggestions (bid_sources_tried.json), or None while it
    hasn't: {"amazon": "<what happened, SGT time>", "soldscope": "<what happened>"}."""
    path = os.path.join(run, TRIED)
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def load_soldscope(run, load_suggested):
    """SoldScope's estimates, {search: [low, cpc, high]}, keyed like the suggested bids; a search whose cpc is zero or
    missing has none."""
    return {t: v for t, v in load_suggested(run, SOLDSCOPE).items() if isinstance(v, list) and len(v) == 3 and v[1]}


def fill(missing, soldscope, terms, amazon, shared):
    """Prices the invest searches Amazon gave no suggestion for.

    amazon: the run's Amazon suggestions ({search: [low, median, high]}), the estimate's peers; shared: config.json.
    Returns (values, sources):
    values {search: [low, median, high]} for the searches SoldScope or the estimate covers, for the planner to price like an
    Amazon suggestion; sources {search: (kind, note)} for every missing search, kind 'soldscope', 'estimate' or 'none', and
    note what the bid was priced on, in words for the row's why."""
    fb = shared.get('bid_fallback') or {}
    mult = (shared.get('thresholds') or {}).get('no_suggestion_multiplier', 1.5)
    min_clicks = fb.get('own_cpc_min_clicks', 10)
    min_peers = fb.get('peer_min_searches', 3)
    meds = [v[1] for v in amazon.values() if v and v[1]]
    peer = statistics.median(meds) if len(meds) >= min_peers else None
    values, sources = {}, {}
    for t in missing:
        if t in soldscope:
            lo, med, hi = soldscope[t]
            values[t] = [lo or None, med, hi or None]
            sources[t] = ('soldscope', f"SoldScope's estimate ${med:.2f}" + (f' (${lo:.2f}-${hi:.2f})' if lo and hi else ''))
            continue
        r = terms.get(t) or {}
        own = r.get('ad_cpc') if (r.get('ad_clicks') or 0) >= min_clicks else None
        bits = ([f"its own cost per click ${own:.2f} on {r['ad_clicks']} clicks"] if own else []) + \
               ([f"Amazon's median suggestion on {len(meds)} other searches, ${peer:.2f}"] if peer else [])
        if bits:
            est = round(max(x for x in (own, peer) if x), 2)
            values[t] = [None, est, None]
            sources[t] = ('estimate', f'an estimate of ${est:.2f} (' + (' and '.join(bits) if len(bits) == 1
                                                                          else 'the higher of ' + ' and '.join(bits)) + ')')
        else:
            sources[t] = ('none', f'{mult:g}x breakeven, with no SoldScope figure or estimate')
    return values, sources
