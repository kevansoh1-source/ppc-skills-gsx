#!/usr/bin/env python3
"""The data stage of a product, and the small checks the planner makes on the strength of it (docs/superpowers/specs/
2026-10-21-keyword-selection-by-data-stage-design.md; built 2026-10-22).

Pure functions, no files and no network: plan.py calls them once per run and stamps the answers on the summary and
every term row. In every function here `product` is the product file's dict (data/asins/<ASIN>.json: `launch`,
`data_stage`, `sqp_history`) and `cfg` is the shared config.json dict (`thresholds`, `launch`, `stage`). plan.py calls
them the other way round (its `cfg` is the product file, its `shared` is config.json).

What each one decides:
- data_stage (section 4.1): launch, early or mature. Launch: a `launch` block dated within 90 days and fewer than
  `launch.sqp_min_queries` SQP queries with impressions. Mature: the product file records `data_stage: "mature"` (a
  stock-out thins SQP, it does not make a product new again), or SQP holds the full window: the longest observed-day
  count reaches `stage.full_window_days` (77 in config since 2026-10-22: a 90-day Scale Insights pull holds at most 11
  complete SQP weeks, so the design's 84 never fired; FULL_WINDOW_DAYS, 84, when the config has no such key). Early:
  otherwise, while the longest observed-day count is under `stage.early_max_observed_days` or fewer than
  `stage.early_min_trusted_queries` queries carry `thresholds.trusted_min_clicks` of our clicks. A product with SQP but
  no `launch` block is early, never launch.
- sqp_totals, volatile_week (section 4.6): the run's SQP totals, and whether the SQP since the baseline (the last
  `sqp_history` entry) adds more of our clicks than `stage.volatile_week_ratio` x all the weeks before it.
- volume_of (section 4.4.3): a search's volume from the best source that has one (SQP, the launch list, SoldScope),
  in the units of the product's SQP window.
- fallback_index (section 4.4.2): the search-term conversion over the product's market conversion, shrunk toward the
  market with a 10-click prior. It supports Prove first only.
- relevance_flag (section 4.4.4): 'one token' or 'unlisted' for a head term a person should decide. A root matches its
  plural and singular (close_variants.norm_cv folds each word), and a launch-list entry matches its folded variants too.
"""
import datetime as dt

from close_variants import norm_cv
from searchtext import norm

STAGES = ('launch', 'early', 'mature')

FULL_WINDOW_DAYS = 84   # the planner's own full window: a row with no observed-day count is read as this, and so is a
                        # product without SQP; the mature-by-window line is config `stage.full_window_days` (77), with
                        # this as its default when the key is missing
LAUNCH_DAYS = 90        # a launch block this old or younger puts the product in launch while SQP is thin


def sqp_totals(queries):
    """Our clicks and purchases summed over the SQP rows, and how many rows there are (every row, with or without
    impressions): what the product file's `sqp_history` keeps for the next run's volatile-week check."""
    return {'our_clicks': sum(q.get('AsinClicks') or 0 for q in queries),
            'our_purchases': sum(q.get('AsinPurchase') or 0 for q in queries),
            'queries': len(queries)}


def data_stage(product, queries, cfg, today_iso):
    """The product's data stage from the run's SQP rows (`queries`, as plan.load_inputs returns them) and the product
    file. Returns {stage, sqp_queries, observed_days, trusted_queries, reason, left_launch_this_run}.

    observed_days is the longest QueryObservedDayCount (a row without one counts as a full 84-day window, as the planner
    reads it; 0 with no rows). The product is mature by window when that count reaches `stage.full_window_days` (77: the
    most a 90-day pull holds; FULL_WINDOW_DAYS when the config has no such key). left_launch_this_run: the file still
    records `data_stage: "launch"` and has a dated launch block, but this run's stage is not launch. A `launch.date`
    that is not a YYYY-MM-DD date stops the run (SystemExit) rather than planning on a guess."""
    sqp_queries = sum(1 for q in queries if (q.get('AsinImpressions') or 0) > 0)
    observed_days = max((q.get('QueryObservedDayCount') or FULL_WINDOW_DAYS for q in queries), default=0)
    trusted = sum(1 for q in queries if (q.get('AsinClicks') or 0) >= cfg['thresholds']['trusted_min_clicks'])
    full_window = cfg['stage'].get('full_window_days', FULL_WINDOW_DAYS)

    launch_date = (product.get('launch') or {}).get('date')
    age = None
    if launch_date:
        try:
            age = (dt.date.fromisoformat(today_iso) - dt.date.fromisoformat(str(launch_date)[:10])).days
        except ValueError:
            raise SystemExit(f"the product file's launch.date '{launch_date}' is not a date (YYYY-MM-DD)") from None
    in_launch = age is not None and 0 <= age <= LAUNCH_DAYS and sqp_queries < cfg['launch']['sqp_min_queries']

    if product.get('data_stage') == 'mature':
        stage = 'mature'
    elif in_launch:
        stage = 'launch'
    elif observed_days >= full_window:
        stage = 'mature'
    elif (observed_days < cfg['stage']['early_max_observed_days']
          or trusted < cfg['stage']['early_min_trusted_queries']):
        stage = 'early'
    else:
        stage = 'mature'

    return {'stage': stage, 'sqp_queries': sqp_queries, 'observed_days': observed_days, 'trusted_queries': trusted,
            'reason': f'{stage}: {observed_days} observed days, {trusted} trusted queries, '
                      f'{sqp_queries} SQP queries with impressions',
            'left_launch_this_run': bool(launch_date) and product.get('data_stage') == 'launch' and stage != 'launch'}


def volatile_week(product, queries, data_through, cfg):
    """The reason text when the SQP since the baseline (normally this run's newest SQP week) adds more of our clicks
    than `stage.volatile_week_ratio` x the weeks before it, else None.

    The baseline is the newest `sqp_history` entry ({data_through, our_clicks, our_purchases, queries}); there is none
    when the history is empty, when `data_through` is unknown, when it has not moved past every entry (the same pull
    again) or when the baseline's clicks are 0. The text names the span it measured, from the baseline's data_through to
    this run's: a history that missed a week compares two weeks against the baseline, and the text says so."""
    dated = [e for e in product.get('sqp_history') or [] if e.get('data_through')]
    if not data_through or not dated:
        return None
    baseline = max(dated, key=lambda e: e['data_through'])
    before = baseline.get('our_clicks') or 0
    if data_through <= baseline['data_through'] or before <= 0:
        return None
    added = sqp_totals(queries)['our_clicks'] - before
    ratio = cfg['stage']['volatile_week_ratio']
    if added <= ratio * before:
        return None
    bar = f'the {before}' if ratio == 1 else f'{ratio:g} x the {before}'
    return (f"volatile SQP week: the SQP since {baseline['data_through']} (through {data_through}) added {added} "
            f'of our clicks, more than {bar} of all earlier weeks')


def volume_of(term, sq_row, launch, soldscope, window_days=FULL_WINDOW_DAYS):
    """(volume, basis) for a search, from the first source that has a positive figure: the SQP row's QueryVolume as it
    is ('SQP'); the launch list's monthly volume ('launch list'); SoldScope's monthly volume ('SoldScope'); else (0,
    'none'). A monthly figure is scaled to the product's SQP window (`window_days`, the longest observed day count, 84
    without SQP) so it sits beside SQP volumes counted over the same days. `soldscope` is {normalised search: monthly}.
    A launch-list entry matches by its own spelling or any of its `folded` variants (launch_list.fold_variants puts
    "gel pens colored" under "colored gel pens"), so a reordered spelling of a listed search still has the list's
    volume."""
    if sq_row and (sq_row.get('QueryVolume') or 0) > 0:
        return sq_row['QueryVolume'], 'SQP'
    key = norm(term)
    for s in (launch or {}).get('searches') or []:
        if key in _spellings(s) and (s.get('volume') or 0) > 0:
            return round(s['volume'] * window_days / 30), 'launch list'
    monthly = (soldscope or {}).get(key) or 0
    if monthly > 0:
        return round(monthly * window_days / 30), 'SoldScope'
    return 0, 'none'


def cap_volume(sqp_monthly, datadive_sv=None, soldscope_monthly=None, season_monthly=None):
    """(monthly searches, sources) for the rank volume cap (decision 182, cross-checked on Kim's ask 2026-11-04:
    "aggregate monthly searches using datadive / soldscope as well, cross reference the search volume"): the highest of
    the search's own monthly figure (SQP, else the launch list or SoldScope), DataDive's Rank Radar volume and SoldScope's
    monthly volume, each at its own number (decision 189, 2026-11-05: no 0.8 DataDive conversion), so one low reading
    never lets a big search through. A seasonal product adds `season_monthly`, its season curve's peak week x 52/12
    (decision 185: the cap binds a rank build too). `sources` lists each reading used, highest first. (None, []) when no
    source has a positive figure."""
    seen = [(sqp_monthly, 'own'),
            (datadive_sv, 'DataDive'),
            (soldscope_monthly, 'SoldScope'),
            (season_monthly, 'season peak')]
    seen = sorted([(float(v), k) for v, k in seen if isinstance(v, (int, float)) and v > 0], reverse=True)
    if not seen:
        return (sqp_monthly if sqp_monthly == 0 else None), []
    return seen[0][0], [f'{k} {v:,.0f}' for v, k in seen]


def rank_cap_for(cap, index=None, strong_index=None, strong_max=None):
    """The rank cap one search is held to (decision 189, Kim, 2026-11-05): `cap` (the threshold or the product's own),
    raised to `strong_max` when the search's trusted index is at least `strong_index`, never lowered. None stays None
    (the cap is off)."""
    if cap is None:
        return None
    if strong_index is not None and strong_max is not None and index is not None and index >= strong_index:
        return max(float(cap), float(strong_max))
    return cap


def fallback_index(ad_clicks, ad_orders, product_market_cvr, prior_clicks=10):
    """A search's ad conversion, shrunk toward the product's market conversion with a `prior_clicks` prior, over that
    market conversion. None when the product has no market conversion. For searches with no SQP row of their own: it
    may support Prove first and nothing else (section 4.4.2)."""
    if not product_market_cvr:
        return None
    m = product_market_cvr
    return ((ad_orders + prior_clicks * m) / (ad_clicks + prior_clicks)) / m


def _spellings(entry):
    """The normalised spellings a launch-list entry answers to: its `search` and its `folded` variants."""
    return {norm(x) for x in [entry.get('search')] + list(entry.get('folded') or []) if x}


def relevance_flag(term, launch, niche_terms, roots):
    """'one token' for a one-word search; 'unlisted' for a search that is in neither the product's launch list (by its
    own spelling or a folded variant) nor the niche list (`niche_terms`, normalised) and holds none of the product's
    roots; else None. Either flag sends a Rank candidate to a person (section 4.4.4). A root matches its plural and
    singular: the term's words and the roots are compared after close_variants.norm_cv's per-word fold ("pens" matches
    "pen", "markers" matches "mark"), as launch_list.propose_roots compares them (R41, 2026-10-22)."""
    key = norm(term)
    tokens = key.split()
    if len(tokens) == 1:
        return 'one token'
    listed = set().union(*(_spellings(s) for s in (launch or {}).get('searches') or []))
    if key in listed or key in niche_terms:
        return None
    root_words = {norm_cv(r) for r in roots}
    if any(norm_cv(t) in root_words for t in tokens):
        return None
    return 'unlisted'
