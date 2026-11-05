#!/usr/bin/env python3
"""For Growth: when a listing pass is due, and the hand-over block Growth's listing optimizer reads.

Pure functions, standard library only (plus evidence.py, searchtext.py and plan.make_irrelevant): no files, no network,
nothing written. plan.py (the run), dashboard.py (the product file) and the dashboard's For Growth tab call them.

Specs: docs/superpowers/specs/2026-10-22-for-growth-tab-design.md (the addendum: the anchor and the dates, section 2;
the triggers, section 3; the item's growth block, section 1), docs/superpowers/specs/2026-10-20-launch-process-ai-growth-
design.md 4b and 4c (the rows), and Growth's block contract
.claude/skills/listing-build/skills/growth-listing-optimizer/references/ppc-handover-block.md, which render_block and
block_json follow exactly (the tests read both forms with Growth's own parser).

Arguments: `plan` is plan.json's dict (`summary[0]` with `stage` and `sqp_data_through`, `terms`, `changes`); `product`
is the product file (data/asins/<ASIN>.json: `relevance`, `launch`, `invest_log`, `launch_date`, `title`, `growth`);
`cfg` (or `shared`) is config.json (`growth`, `thresholds`, `launch`); `listing` is <run>/listing.json
({asin, read_at, source, title, highlight, bullets, backend}) or None when the run read no listing.

The rules, in the planner's words:
- Funded: role Rank with sub_role Invest or Prove first in this plan, plus every invest_log search (a search leaves the
  log only by a person's step-down). A funded search is never Out: an invested search's exit is the stop-loss review.
- Carried: every content token of the search (lowercase, stop words dropped, a plural folded) in one surface, read in
  the order title, highlight, bullet 1..5, backend. A backend of None is not readable, never "absent".
- Out (the swap table's rotate-out rows): carried, not a head noun (relevance.roots or launch.roots), and either
  irrelevant (the Negate role or the product's relevance lists: removed from every surface) or below market (SQP basis,
  not thin, judge_clicks SQP clicks, index under below_market_index) and not shielded (sqp_shield_purchases SQP purchases
  or an SQP index of sqp_shield_index or more): moved down a level. The Trim lane has no confidence bar of its own (a
  cut is never held back, rulebook 7.3), so the bar is the basis, the click floor and the index; the probability
  (evidence.p_below, as the lanes compute it for a cut) is written into the row's words as the lanes word it. Without
  roots there are no Out rows at all, since the head-noun exemption cannot be applied.
- The rotate-out flag (an unscheduled item): a carried, non-funded, non-head-noun term with rotate_out_min_clicks SQP
  clicks and 0 purchases or an index under rotate_out_index, outside quiet_days after the last listing change.
- Proven SKC keywords (Kim, 2026-10-25): the plan's Rank rows at sub_role Invest earned on SQP's own same-query
  index (3+ purchases at index 1.1 or more, 150+ searches; rulebook 2 and 7.1). Not Prove first, not the product-market
  fallback, not a season's rank searches, not a business search, and not an invest_log search the plan does not rate
  Invest (the launch list's onboarding campaigns): those are funded, not proven.
- The first pass (first_pass_mode 'evidence', Kim 2026-10-25: "hand the listing to Growth when our AI bidding audit has
  enough information and confidence to come up with the SKC keywords"): no date. It fires on the first run where the
  data floor holds (stage not launch and first_pass_min_trusted_queries trusted queries) and skc_min_proven proven SKC
  keywords sit uncarried by the copy on pass_persist_runs runs in a row; else, with first_pass_ceiling, at the later
  of the anchor and growth.enabled_on + pass_ceiling_weeks (a ceiling_pass tagged first listing optimization). Mode
  'date' keeps the old rule (anchor + first_pass_days).
- Dates: the anchor is the later of the Monday launch date and the first ad click (or the one known; a hand-set anchor
  wins); in date mode the first pass is due at the anchor + first_pass_days; after a resolved pass the window is the
  last listing change + pass_floor_weeks to + pass_ceiling_weeks, and its evidence gate counts proven SKC keywords too.
"""
import datetime as dt
import re

import evidence
from searchtext import norm

GROWTH_ID = 'for-growth'
SURFACES = ('title', 'highlight', 'bullet', 'backend')
PASS_FIRST = 'first listing optimization'
PASS_SECOND = 'second optimization onward'
TRIGGERS = ('first_pass', 'evidence_pass', 'ceiling_pass', 'rotate_out_flag', 'new_skc', 'manual')
CLOSED_STATUSES = ('resolved', 'dismissed')   # human_review.STATUSES' terminal ones: a new pass opens a fresh item
ANCHOR_SOURCES = ('monday_launch_date', 'first_ad_click', 'hand')
FUNDED_ROLES = ('Invest', 'Prove first')
STOP_WORDS = frozenset('for the a an of and with to in on'.split())
# a funded search holding one of these words is a modifier or a secondary occasion ("for women", "with envelopes",
# "bulk"): the highlight's, after the title (launch design 4c)
MODIFIER_WORDS = frozenset(('for', 'with', 'bulk', 'pack', 'set', 'kit', 'gift', 'assorted', 'variety'))
BRAND_TOKENS = frozenset(('yourbrand',))   # a search holding the brand is near-brand: the backend's
SQP_DAYS = 90
SGT = dt.timezone(dt.timedelta(hours=8))
COMMAND = '/growth-listing-optimizer'
SEEDS_FLAG = '--seed-keywords'
MOVE_DOWN_TO = {'title': 'bullet', 'highlight': 'bullet', 'bullet': 'backend'}   # the backend has no lower slot

SWAP_HEADING, ROTATE_HEADING, OFFER_HEADING, NOTES_HEADING = (
    '### Swap table', '### Rotate out (watch list)', '### Offer problems', '### Notes')
SWAP_COLUMNS = ('Slot', 'Term', 'Action', 'Role', 'SQP volume', 'Index', 'Our clicks', 'Our purchases', 'Basis', 'Why')
ROTATE_COLUMNS = ('Term', 'Slot today', 'Our clicks', 'Our purchases', 'Index', 'Bar')
OFFER_COLUMNS = ('Search', 'SQP volume', 'Our CVR', 'Market CVR', 'Our clicks', 'Bid action')
OFFER_LABEL = 'image, price or reviews work, not copy'


# ----------------------------------------------------------------------------- small readers
def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _n(v):
    """A count as a number, 0 when missing."""
    return v if _number(v) else 0


def _int(v):
    return int(round(v)) if _number(v) else None


def _date(value):
    """A YYYY-MM-DD date, or None when it is missing or not a date."""
    try:
        return dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _plus(iso, days):
    d = _date(iso)
    return (d + dt.timedelta(days=days)).isoformat() if d else None


def _growth(product):
    return (product or {}).get('growth') or {}


def _summary(plan):
    return ((plan or {}).get('summary') or [{}])[0] or {}


def _stage_name(plan):
    return (_summary(plan).get('stage') or {}).get('stage')


def _terms(plan):
    """plan.json's consumer term rows by normalised search."""
    return {norm(r['term']): r for r in (plan or {}).get('terms') or [] if isinstance(r, dict) and r.get('term')}


def _roots(product):
    return list(((product or {}).get('relevance') or {}).get('roots') or []) + \
        list(((product or {}).get('launch') or {}).get('roots') or [])


def _qualifiers(product):
    return list(((product or {}).get('relevance') or {}).get('qualifiers') or []) + \
        list(((product or {}).get('launch') or {}).get('qualifiers') or [])


def _text(v):
    """A table cell's text: None stays None; a `|` becomes `/` (the reader splits rows on `|`); one line."""
    if v is None:
        return None
    return ' '.join(str(v).replace('|', '/').split())


# ----------------------------------------------------------------------------- tokens and where a search sits
def _fold(word):
    return word[:-1] if len(word) > 3 and word.endswith('s') and not word.endswith('ss') else word


def tokens(text):
    """Lowercase, apostrophes dropped, hyphens and punctuation to spaces, stop words dropped, a trailing s folded
    (`bookmarks` -> `bookmark`; `bulk` and `glass` stay)."""
    text = re.sub(r"['‘’]", '', str(text or '').lower())
    return [_fold(w) for w in re.sub(r'[^a-z0-9áéíóúñü]+', ' ', text).split() if w not in STOP_WORDS]


def surfaces(listing):
    """The listing's readable surfaces in reading order: (name, text), bullets numbered from 1."""
    listing = listing or {}
    named = [('title', listing.get('title')), ('highlight', listing.get('highlight'))]
    named += [(f'bullet {i}', b) for i, b in enumerate(listing.get('bullets') or [], 1)]
    named.append(('backend', listing.get('backend')))
    return [(name, text) for name, text in named if isinstance(text, str) and text.strip()]


def carried(search, listing):
    """The first surface (title, highlight, bullet 1..5, backend) whose tokens hold every token of the search; None
    when none does (a backend of None is not readable, so a search only there reads None); 'unknown' with no listing."""
    if listing is None:
        return 'unknown'
    want = set(tokens(search))
    if not want:
        return None
    for name, text in surfaces(listing):
        if want <= set(tokens(text)):
            return name
    return None


def surface_of(slot):
    """'bullet 2' -> 'bullet'; the other slots as they are."""
    slot = str(slot or '')
    return 'bullet' if slot.startswith('bullet') else slot


# ----------------------------------------------------------------------------- the rows
def _basis(row):
    """The block's Basis column: `SQP`, `Search terms` (the ad report, the fallback included) or `DataDive` (no
    index the block can stand on: a launch-list search, or a logged search with no plan row)."""
    if not row:
        return 'DataDive'
    ib = str(row.get('index_basis') or '')
    if row.get('index_status') == 'product_market_fallback' or ib.startswith('Search terms'):
        return 'Search terms'
    if ib.startswith('SQP') and row.get('index') is not None:
        return 'SQP'
    return 'DataDive'


def _traffic(row, basis):
    """Our clicks and purchases on the row's basis: SQP's, the ad report's, or unknown."""
    if not row:
        return None, None
    if basis == 'SQP':
        return _int(row.get('sqp_our_clicks')), _int(row.get('sqp_our_purchases'))
    if basis == 'Search terms':
        return _int(row.get('ad_clicks')), _int(row.get('ad_orders'))
    return None, None


def _volume(row):
    v = (row or {}).get('sqp_volume')
    return v if _number(v) and v > 0 else None


def _opportunity(volume, index):
    return (volume or 0) * (index or 0)


def sales_potential(volume, market_cvr, index):
    """Kim, 2026-10-26: searches x market CVR x index, the purchases we would expect in the SQP window at a full
    share of the search. None when one of the three is unknown (no SQP row, no market CVR, no index)."""
    if not (_number(volume) and _number(market_cvr) and _number(index)):
        return None
    return volume * market_cvr * index


def _opp_key(x):
    """Highest sales potential first; a row without one after every row with one, by volume x index (the launch
    list's DataDive rows carry their volume as `opportunity`); then the term."""
    potential = x.get('sales_potential')
    second = (x.get('opportunity') if x.get('opportunity') is not None
              else _opportunity(x.get('sqp_volume'), x.get('index')))
    return (potential is None, -(potential or 0), -second, str(x.get('term') or x.get('search') or ''))


def _role(row):
    if not row:
        return None
    return row.get('sub_role') if row.get('role') == 'Rank' else row.get('role')


def _funded_row(term, role, row, source, log=None):
    basis = _basis(row)
    clicks, purchases = _traffic(row, basis)
    index = row.get('index') if row and basis != 'DataDive' else None
    volume = _volume(row)
    rank_index = index if index is not None else (row or {}).get('fallback_index')
    return dict(term=term, role=role, source=source, sqp_volume=volume, index=index,
                index_basis=(row or {}).get('index_basis'), index_status=(row or {}).get('index_status'),
                sqp_our_clicks=(row or {}).get('sqp_our_clicks'), sqp_our_purchases=(row or {}).get('sqp_our_purchases'),
                our_clicks=clicks, our_purchases=purchases, market_cvr=(row or {}).get('market_cvr'),
                our_cvr=(purchases / clicks) if clicks else None, basis=basis,
                relevance_flag=(row or {}).get('relevance_flag'), volume_basis=(row or {}).get('volume_basis'),
                plan_why=(row or {}).get('why'), since=(log or {}).get('since') if isinstance(log, dict) else None,
                opportunity=_opportunity(volume, rank_index),
                sales_potential=sales_potential(volume, (row or {}).get('market_cvr'), index))


def branded(term):
    """A search holding the brand word ("yourbrand birthday cards"). The brand stays organic only (Kim, Oct 20; the
    B0SAMP0014 slip of 2026-10-26), so a branded search is never handed to Growth: not a seed, not a proven SKC
    keyword."""
    return bool(set(tokens(term)) & BRAND_TOKENS)


def funded(plan, product):
    """One dict per funded search: Rank rows with sub_role Invest or Prove first, then every invest_log search not
    already among them (role from the log). Numbers are the plan row's when it has one: `sqp_volume`, `index`,
    `index_basis`, `sqp_our_clicks`, `sqp_our_purchases`, `market_cvr`, and `our_clicks`, `our_purchases`, `our_cvr`
    (purchases / clicks, None on 0 clicks) on the row's basis, with `basis` the block's word for it."""
    rows = _terms(plan)
    out, seen = [], set()
    for key, r in rows.items():
        if branded(key):
            continue
        if r.get('role') == 'Rank' and r.get('sub_role') in FUNDED_ROLES:
            out.append(_funded_row(key, r['sub_role'], r, 'plan'))
            seen.add(key)
    for t, log in ((product or {}).get('invest_log') or {}).items():
        key = norm(t)
        if not key or key in seen or branded(key):
            continue
        role = log.get('role') if isinstance(log, dict) and log.get('role') in FUNDED_ROLES else 'Invest'
        out.append(_funded_row(key, role, rows.get(key), 'invest_log', log))
        seen.add(key)
    return out


def proven(plan, product=None):
    """The proven SKC keywords this plan holds (module notes): [term], in the plan's order. A row qualifies when the
    planner rated it Rank / Invest on SQP's own same-query index; a season rank search, a business search, a retained
    log entry and the product-market fallback do not."""
    out = []
    for key, r in _terms(plan).items():
        if (r.get('role') == 'Rank' and r.get('sub_role') == 'Invest'
                and r.get('index_status') == 'same_query_smoothed' and str(r.get('index_basis') or '').startswith('SQP')
                and not r.get('season_rank') and not r.get('retained_log') and r.get('owner_kind') != 'business'
                and not branded(key)):
            out.append(key)
    return out


def below_market(row, cfg):
    """SQP basis (not thin), judge_clicks SQP clicks or more, and an index under below_market_index (the Trim line,
    never 1.0). The lanes hold no confidence bar for a cut, so this is the whole bar (see the module notes)."""
    g = cfg['growth']
    basis = str(row.get('index_basis') or '')
    index = row.get('index')
    return (basis.startswith('SQP') and 'thin' not in basis and _n(row.get('sqp_our_clicks')) >= g['judge_clicks']
            and _number(index) and index < g['below_market_index'])


def shielded(row, cfg):
    """SQP shows we win the search: sqp_shield_purchases SQP purchases, or an SQP index of sqp_shield_index or more."""
    g = cfg['growth']
    index = row.get('index')
    return (_n(row.get('sqp_our_purchases')) >= g['sqp_shield_purchases']
            or (str(row.get('index_basis') or '').startswith('SQP') and _number(index) and index >= g['sqp_shield_index']))


def exempt(term, product):
    """A head noun: every token of the search is a token of the product's roots (relevance.roots, launch.roots)."""
    root_tokens = {t for r in _roots(product) for t in tokens(r)}
    want = set(tokens(term))
    return bool(root_tokens) and bool(want) and want <= root_tokens


def _irrelevance(plan, product):
    """A function search -> why it is irrelevant (the Negate role, or the product's relevance lists matched the way
    plan.make_irrelevant matches them), else None."""
    from plan import dimension_pairs, make_irrelevant   # imported here: plan.py imports this module
    rows = _terms(plan)
    sizes = (_summary(plan).get('size_check') or {}).get('sizes') or dimension_pairs((product or {}).get('size'))
    listed = make_irrelevant((product or {}).get('asin'), (product or {}).get('relevance') or {}, sizes)

    def why(term):
        key = norm(term)
        row = rows.get(key)
        if row and row.get('role') == 'Negate':
            return row.get('why') or 'the planner negates it'
        return listed(key)
    return why


def irrelevant(term, plan, product):
    """Role Negate in the plan, or matched by the product's relevance.negate_phrase / negate_exact lists."""
    return bool(_irrelevance(plan, product)(term))


def _sure_below(row, cfg):
    """The lanes' words for a cut's evidence: 'about 85% sure it converts under 0.8x the market', or None."""
    m, clicks = row.get('market_cvr'), _n(row.get('sqp_our_clicks'))
    if not (_number(m) and 0 < m < 1) or clicks <= 0:
        return None
    p = evidence.p_below(_n(row.get('sqp_our_purchases')), clicks, m,
                         (cfg.get('thresholds') or {}).get('prior_clicks', 10), cfg['growth']['below_market_index'])
    return evidence.sure_text(p, f"converts under {cfg['growth']['below_market_index']:g}x the market")


def _out_row(term, row, slot_now, why, action, to, cfg, reason=None):
    basis = _basis(row)
    clicks, purchases = _traffic(row, basis)
    volume, index = _volume(row), row.get('index')
    where = slot_now if slot_now.startswith('bullet') else f'the {slot_now}'   # 'bullet 2', 'the title'
    if why == 'irrelevant':
        detail = f'carried in {where}; irrelevant ({reason}): remove from every surface'
    else:
        sure = _sure_below(row, cfg)
        detail = (f"carried in {where}; under {cfg['growth']['below_market_index']:g} on {clicks} clicks, "
                  f"not shielded{f' ({sure})' if sure else ''}: to {'the backend' if to == 'backend' else 'a ' + to}")
    return dict(term=term, slot_now=slot_now, why=why, action=action, to=to, role=_role(row), sqp_volume=volume,
                index=index, our_clicks=clicks, our_purchases=purchases, sqp_our_clicks=row.get('sqp_our_clicks'),
                sqp_our_purchases=row.get('sqp_our_purchases'), market_cvr=row.get('market_cvr'),
                our_cvr=row.get('cvr_est'), basis=basis, reason=reason, detail=_text(detail),
                opportunity=_opportunity(volume, index))


def _carried_rows(plan, product, listing):
    """(search, row, slot today) for every plan search the listing carries that is neither funded nor a head noun.
    Nothing without a listing or without roots (the exemption can't be applied)."""
    if listing is None or not _roots(product):
        return []
    funded_terms = {f['term'] for f in funded(plan, product)}
    out = []
    for key, row in sorted(_terms(plan).items()):
        if key in funded_terms or exempt(key, product):
            continue
        slot_now = carried(key, listing)
        if slot_now and slot_now != 'unknown':
            out.append((key, row, slot_now))
    return out


def rotate_candidates(plan, product, listing, cfg):
    """The swap table's Out rows: {term, slot_now, why: 'irrelevant' | 'below market', action: 'remove' | 'move
    down', to: 'bullet' | 'backend' | None, numbers...}. Irrelevant terms are removed whatever SQP says (a competitor's
    brand never belongs in the copy); a below-market term moves down unless shielded, and one already in the backend has
    nowhere lower (the watch list still shows it). Empty without relevance.roots or without a listing."""
    why_irrelevant = _irrelevance(plan, product)
    out = []
    for key, row, slot_now in _carried_rows(plan, product, listing):
        reason = why_irrelevant(key)
        if reason:
            out.append(_out_row(key, row, slot_now, 'irrelevant', 'remove', None, cfg, reason))
        elif below_market(row, cfg) and not shielded(row, cfg):
            to = MOVE_DOWN_TO.get(surface_of(slot_now))
            if to:
                out.append(_out_row(key, row, slot_now, 'below market', 'move down', to, cfg))
    return sorted(out, key=_opp_key)


def _at_flag_bar(row, cfg):
    g = cfg['growth']
    index = row.get('index')
    return (_n(row.get('sqp_our_clicks')) >= g['rotate_out_min_clicks']
            and (_n(row.get('sqp_our_purchases')) == 0 or (_number(index) and index < g['rotate_out_index'])))


def flag_candidates(plan, listing, product, cfg):
    """Carried terms at the flag bar (rotate_out_min_clicks SQP clicks and 0 purchases, or an index under
    rotate_out_index), not funded, not head nouns: {term, slot_now, our_clicks, our_purchases, index}, most clicks
    first. The quiet window is the caller's to apply (trigger_for, gate_candidates). A term the block's own shield keeps
    (sqp_shield_purchases SQP purchases or an SQP index of sqp_shield_index or more) raises no flag: the block would
    only ask Growth to keep it (open item 49, Kim 2026-10-25); the watch list still shows it at the flag bar."""
    out = [dict(term=key, slot_now=slot_now, our_clicks=_int(row.get('sqp_our_clicks')),
                our_purchases=_int(row.get('sqp_our_purchases')), index=row.get('index'))
           for key, row, slot_now in _carried_rows(plan, product, listing)
           if _at_flag_bar(row, cfg) and not shielded(row, cfg)]
    return sorted(out, key=lambda f: (-(f['our_clicks'] or 0), f['term']))


def _under_bar(plan, product, listing, cfg):
    """The evidence gate's second reason (R28): the carried terms the swap table moves down this run, by the same
    predicate as rotate_candidates (relevant, under the pass bar, not shielded, and sitting on a surface with a lower
    slot). A term only in the backend, which the block cannot act on, is not one."""
    return [o['term'] for o in rotate_candidates(plan, product, listing, cfg) if o['action'] == 'move down']


def _shield_reasons(row, cfg):
    """The shields that apply, in words: '3+ SQP purchases', 'SQP index 0.85, 0.8 or more'."""
    g = cfg['growth']
    index = row.get('index')
    out = []
    if _n(row.get('sqp_our_purchases')) >= g['sqp_shield_purchases']:
        out.append(f"{g['sqp_shield_purchases']}+ SQP purchases")
    if str(row.get('index_basis') or '').startswith('SQP') and _number(index) and index >= g['sqp_shield_index']:
        out.append(f"SQP index {index:.2f}, {g['sqp_shield_index']:g} or more")
    return out


def _pass_bar_missed(row, cfg):
    """Which conditions of the pass bar a row misses, in words (basis, click floor, index)."""
    g = cfg['growth']
    basis, index, clicks = str(row.get('index_basis') or ''), row.get('index'), _int(row.get('sqp_our_clicks')) or 0
    out = []
    if not basis.startswith('SQP'):
        out.append(f"basis {basis or 'unknown'}, not SQP")
    elif 'thin' in basis:
        out.append('thin SQP')
    if clicks < g['judge_clicks']:
        out.append(f"{clicks} SQP clicks, under the {g['judge_clicks']}-click floor")
    if not _number(index):
        out.append('no index')
    elif index >= g['below_market_index']:
        out.append(f"index {index:.2f}, not under {g['below_market_index']:g}")
    return out


def watch_list(plan, product, listing, cfg):
    """The block's rotate-out table: every carried, non-funded, non-head-noun term at the pass bar (SQP, judge_clicks
    clicks, index under below_market_index) or the flag bar, whether or not the swap table acts on it, with the bar in
    words: which pass-bar condition was missed, if any, the shield that applied, and the flag bar: {term, slot_now,
    our_clicks, our_purchases, index, bar}."""
    g = cfg['growth']
    pass_bar = f"pass bar met ({g['judge_clicks']} clicks, under {g['below_market_index']:g})"
    flag_bar = f"flag bar ({g['rotate_out_min_clicks']} clicks, 0 purchases or under {g['rotate_out_index']:g})"
    why_irrelevant = _irrelevance(plan, product)
    out = []
    for key, row, slot_now in _carried_rows(plan, product, listing):
        at_pass, at_flag = below_market(row, cfg), _at_flag_bar(row, cfg)
        if not (at_pass or at_flag):
            continue
        shields = _shield_reasons(row, cfg)
        if why_irrelevant(key):
            act = 'the swap table removes it as irrelevant'
        elif shields:
            act = f"shielded ({' and '.join(shields)}): kept"
        elif not at_pass:
            act = 'kept: the swap table moves only a term under the pass bar'
        elif not MOVE_DOWN_TO.get(surface_of(slot_now)):
            act = 'in the backend already, nothing lower to move it to'
        else:
            act = 'the swap table moves it down'
        head = pass_bar if at_pass else f"pass bar missed ({'; '.join(_pass_bar_missed(row, cfg))})"
        tail = f"the planner's {flag_bar} met too" if at_flag else f"not the planner's {flag_bar}"
        out.append(dict(term=key, slot_now=slot_now, our_clicks=_int(row.get('sqp_our_clicks')),
                        our_purchases=_int(row.get('sqp_our_purchases')), index=row.get('index'),
                        bar=_text(f'{head}: {act}; {tail}')))
    return sorted(out, key=lambda r: (-(r['our_clicks'] or 0), r['term']))


def _niche_qualified(row, product):
    """Holds one of the product's qualifiers (relevance.qualifiers, launch.qualifiers) when it has any; otherwise
    passes the planner's head-term check (no relevance_flag: not one word, and listed or holding a root)."""
    want = set(tokens(row.get('term')))
    quals = [set(tokens(q)) for q in _qualifiers(product) if tokens(q)]
    if quals:
        return any(q <= want for q in quals)
    return len(want) >= 2 and not row.get('relevance_flag')


def _spacing_variant(term, listing):
    """`book marks` against a carried `bookmarks` (or the reverse): the search's tokens, joined, equal a run of a
    surface's tokens joined, though the tokens themselves differ."""
    want = tokens(term)
    joined = ''.join(want)
    if not joined:
        return False
    for _, text in surfaces(listing):
        have = tokens(text)
        for size in range(1, len(want) + 2):
            for i in range(0, len(have) - size + 1):
                run = have[i:i + size]
                if ''.join(run) == joined and run != want:
                    return True
    return False


def seasonal(term, product, cfg):
    """True when the search names a season or a dated event (growth.seasonal_words: "back to school", "christmas",
    "valentines") that is not part of the product itself (its name, title, roots or qualifiers): an accent for a
    bullet, never the title or the highlight (Kim, 2026-10-26: "optimise the listing according to more evergreen
    keywords rather than seasonal ones"). A Christmas card's "christmas" is its product, so it is not seasonal there."""
    want = tokens(term)
    own = set()
    for k in ('product', 'name', 'title'):
        own |= set(tokens((product or {}).get(k)))
    own |= {t for r in _roots(product) for t in tokens(r)} | {t for q in _qualifiers(product) for t in tokens(q)}
    for phrase in (cfg.get('growth') or {}).get('seasonal_words') or ():
        words = tokens(phrase)
        if not words or set(words) <= own:
            continue
        if any(want[i:i + len(words)] == words for i in range(len(want) - len(words) + 1)):
            return True
    return False


def suggest_slot(row, listing, product, cfg, title_taken, highlight_taken=0):
    """Where a funded search the copy does not carry should go (data only; Growth's optimizer has the last word).
    build_item calls it in sales-potential order (Kim, 2026-10-26: "keywords with the most opportunity go into the
    title first, followed by highlights and then bullet points"), so the first rule that holds decides:
    - backend: a near-brand search (it carries the brand token);
    - backend: a spacing variant of a carried word, or a low-volume proven harvest (volume known and under
      offer_min_volume, with a purchase);
    - bullet: a seasonal search (seasonal(): evergreen searches take the title and the highlight);
    - title: a niche-qualified search, while fewer than title_slots are taken;
    - highlight: while fewer than highlight_slots are taken, a niche-qualified search, a search made only of the
      product's own name words (R27), or a modifier or secondary occasion (MODIFIER_WORDS or one of its qualifiers);
    - else bullet.
    The highlight is one 125-character field, so at most highlight_slots (config, default 2) rows point at it
    (2026-10-25, after the 32 hand blocks pointed up to 24 rows at one highlight). Until 2026-10-26 only an Invest
    search could take the title and rows were placed by volume x index."""
    g = cfg['growth']
    term = row.get('term') or ''
    want = set(tokens(term))
    if want & BRAND_TOKENS:
        return 'backend'
    volume = _volume(row)
    if ((listing is not None and _spacing_variant(term, listing))
            or (volume is not None and volume < g['offer_min_volume'] and _n(row.get('our_purchases')) > 0)):
        return 'backend'
    if seasonal(term, product, cfg):
        return 'bullet'
    qualified = _niche_qualified(row, product)
    if qualified and title_taken < g['title_slots']:
        return 'title'
    if highlight_taken < g.get('highlight_slots', 2):
        own_name = {t for k in ('product', 'name', 'title') for t in tokens((product or {}).get(k))}
        raw = set(re.sub(r'[^a-z0-9]+', ' ', term.lower()).split())
        if (qualified or (want and want <= own_name) or raw & MODIFIER_WORDS
                or any(q <= want for q in (set(tokens(q)) for q in _qualifiers(product)) if q)):
            return 'highlight'
    return 'bullet'


def swaps(outs, ins):
    """The swap table as rows {slot, out, in}: title first, then highlight, bullet, backend. Inside a slot the ins and
    the outs (by the surface they sit on) are each ordered by sales potential (then volume x index), highest first,
    and paired in that order; the rows then run highest first. An In without an Out, or an Out without an In, is a row
    of its own."""
    def opp(x):
        k = _opp_key(x) if x else (True, 0, 0, '')
        return (not k[0], -k[1], -k[2])
    rows = []
    for slot in SURFACES:
        o = sorted((x for x in outs if surface_of(x.get('slot_now')) == slot), key=_opp_key)
        i = sorted((x for x in ins if x.get('slot') == slot), key=_opp_key)
        pairs = [{'slot': slot, 'out': o[k] if k < len(o) else None, 'in': i[k] if k < len(i) else None}
                 for k in range(max(len(o), len(i)))]
        rows += sorted(pairs, key=lambda r: max(opp(r['in']), opp(r['out'])), reverse=True)
    return rows


def _bid_action(term, row, plan):
    """What the planner does with the bid: its role, the evidence, and this run's bid change when there is one."""
    text = f"{_role(row)}, index {row['index']:.2f} on {_int(row.get('sqp_our_clicks'))} SQP clicks"
    for x in (plan or {}).get('changes') or []:
        if norm(x.get('keyword') or '') != term:
            continue
        if x.get('type') == 'Bid change' and _number(x.get('current')) and _number(x.get('new')):
            text += f"; bid {x['current']:.2f} to {x['new']:.2f}"
            break
        if x.get('type') == 'Pause keyword':
            text += '; keyword paused'
            break
    return _text(text)


def offer_problems(plan, product, cfg):
    """Relevant searches with offer_min_volume or more searches that convert below market on the move-down bar (SQP,
    judge_clicks clicks, index under below_market_index): {search, sqp_volume, our_cvr, market_cvr, our_clicks,
    our_purchases, index, role, bid_action, label}, biggest opportunity first. The CVRs are the planner's smoothed ones
    (fractions), the two numbers behind the index. Labelled image, price or reviews work, not copy. At most offer_max_rows (config, default 12) rows, the
    biggest opportunities (open item 50b: the gold notebooks' hand block of 2026-10-25 carried 34, each needing a verdict
    from Growth)."""
    g = cfg['growth']
    why_irrelevant = _irrelevance(plan, product)
    out = []
    for key, row in sorted(_terms(plan).items()):
        volume = _volume(row)
        if (row.get('role') == 'Negate' or why_irrelevant(key) or volume is None or volume < g['offer_min_volume']
                or not below_market(row, cfg)):
            continue
        out.append(dict(search=key, sqp_volume=volume, our_cvr=row.get('cvr_est'), market_cvr=row.get('market_cvr'),
                        our_clicks=_int(row.get('sqp_our_clicks')), our_purchases=_int(row.get('sqp_our_purchases')),
                        index=row.get('index'), role=_role(row), bid_action=_bid_action(key, row, plan),
                        label=OFFER_LABEL, opportunity=_opportunity(volume, row.get('index')),
                        sales_potential=sales_potential(volume, row.get('market_cvr'), row.get('index'))))
    return sorted(out, key=_opp_key)[:g.get('offer_max_rows', 12)]


def seed_string(asin, ins):
    """`/growth-listing-optimizer <ASIN> --seed-keywords "a; b; c"`, the In searches in the order given (the swap
    table's), each once; the command alone when there is none. Out searches are never passed in."""
    seeds, seen = [], set()
    for x in ins:
        t = re.sub(r'["“”;]', ' ', str((x or {}).get('term') or ''))
        t = ' '.join(t.split())
        if t and t not in seen:
            seeds.append(t)
            seen.add(t)
    if not seeds:
        return f'{COMMAND} {asin}'
    return f'{COMMAND} {asin} {SEEDS_FLAG} "{"; ".join(seeds)}"'


# ----------------------------------------------------------------------------- the anchor and the dates
def anchor(product, clicks_daily, since=None):
    """{"date", "source"}: a hand-set anchor (growth.anchor with source 'hand') wins; else the later of the Monday
    launch date (`launch_date`, or the launch block's `date`; source monday_launch_date, which also wins a tie) and the
    first day with an ad click (clicks_daily rows {"date", "clicks"}; source first_ad_click); else the one known; else
    None. `since` is the first date the click series covers (the pull's start): a first click falling on it lies at or
    before the window, so it is unknown. Without `since`, the first day with clicks counts."""
    stored = _growth(product).get('anchor') or {}
    if stored.get('source') == 'hand' and _date(stored.get('date')):
        return {'date': _date(stored['date']).isoformat(), 'source': 'hand'}
    launch = _date((product or {}).get('launch_date')) or _date(((product or {}).get('launch') or {}).get('date'))
    days = sorted((_date(r.get('date')) for r in clicks_daily or []
                   if isinstance(r, dict) and _date(r.get('date')) and _n(r.get('clicks')) >= 1))
    first = days[0] if days else None
    start = _date(since)
    if first and start and first <= start:
        first = None
    if launch and (not first or launch >= first):
        return {'date': launch.isoformat(), 'source': 'monday_launch_date'}
    if first:
        return {'date': first.isoformat(), 'source': 'first_ad_click'}
    return None


def resolved_passes(product):
    return [p for p in _growth(product).get('passes') or [] if isinstance(p, dict) and p.get('resolved_on')]


def last_listing_change(product):
    """growth.last_listing_change, else the latest resolved pass's resolved_on, else None."""
    g = _growth(product)
    if _date(g.get('last_listing_change')):
        return _date(g['last_listing_change']).isoformat()
    ends = sorted(_date(p['resolved_on']) for p in resolved_passes(product) if _date(p['resolved_on']))
    return ends[-1].isoformat() if ends else None


def quiet_until(product, cfg):
    """The first day after the quiet window (last listing change + quiet_days), or None with no listing change."""
    return _plus(last_listing_change(product), cfg['growth']['quiet_days'])


def evidence_mode(cfg):
    """True when the first pass waits for proven SKC keywords (config growth.first_pass_mode 'evidence', the default since
    2026-10-25); False for the old date rule ('date')."""
    return (cfg.get('growth') or {}).get('first_pass_mode', 'evidence') != 'date'


def first_ceiling(product, cfg):
    """The evidence mode's latest first pass: the later of the anchor and growth.enabled_on, + pass_ceiling_weeks. None
    when growth.first_pass_ceiling is off or neither date is known. Counting from the day the switch went on keeps a
    product enabled long after its launch from firing at once."""
    g = cfg['growth']
    if not g.get('first_pass_ceiling', True):
        return None
    own = _growth(product)
    dates = [d for d in (_date((own.get('anchor') or {}).get('date')), _date(own.get('enabled_on'))) if d]
    return _plus(max(dates).isoformat(), g['pass_ceiling_weeks'] * 7) if dates else None


def due_dates(product, cfg):
    """{"first_due", "next_pass": {"no_earlier_than", "by"}, "pass"} from growth.anchor, growth.enabled_on,
    growth.last_listing_change, growth.passes and the config. After a resolved pass: the last listing change +
    pass_floor_weeks and + pass_ceiling_weeks. Before one, in evidence mode: first_due None and the window
    {no_earlier_than: None, by: first_ceiling, on_evidence: True} (the pass comes when the SKC keywords are proven, by
    the ceiling at the latest); in date mode both window dates are anchor + first_pass_days (None without an anchor:
    never a due date of today). The anchor is read as stored; a caller holding a fresh one passes a product copy
    carrying it."""
    g = cfg['growth']
    stored = _growth(product).get('anchor') or {}
    if resolved_passes(product):
        first_due = None if evidence_mode(cfg) else _plus(stored.get('date'), g['first_pass_days'])
        last = last_listing_change(product)
        window = {'no_earlier_than': _plus(last, g['pass_floor_weeks'] * 7), 'by': _plus(last, g['pass_ceiling_weeks'] * 7)}
        return {'first_due': first_due, 'next_pass': window, 'pass': PASS_SECOND}
    if evidence_mode(cfg):
        return {'first_due': None, 'next_pass': {'no_earlier_than': None, 'by': first_ceiling(product, cfg),
                                                 'on_evidence': True}, 'pass': PASS_FIRST}
    first_due = _plus(stored.get('date'), g['first_pass_days'])
    return {'first_due': first_due, 'next_pass': {'no_earlier_than': first_due, 'by': first_due}, 'pass': PASS_FIRST}


def data_floor(plan, cfg):
    """None when the data is enough to judge the copy (rule 1: stage not launch and first_pass_min_trusted_queries
    queries with trusted_min_clicks of our clicks), else what is missing, in words."""
    stage = _summary(plan).get('stage') or {}
    name = stage.get('stage') if isinstance(stage, dict) else stage
    need = cfg['growth'].get('first_pass_min_trusted_queries', 5)
    trusted = stage.get('trusted_queries') if isinstance(stage, dict) else None
    if name == 'launch' or not name:
        return f"stage {name or 'unknown'}: no SQP market to judge the copy by"
    if _number(trusted) and trusted < need:
        return f'{int(trusted)} trusted queries, under {need}'
    return None


# ----------------------------------------------------------------------------- the evidence gate
def gate_candidates(plan, listing, product, cfg, today_iso=None):
    """This run's gate bookkeeping: {"uncarried_funded": [terms], "uncarried_proven": [the proven SKC keywords the copy
    misses], "under_bar": [terms], "stage": name, "flag_bar":
    [terms]}. With today_iso it adds "date" and "flags_in_quiet" ([{term, seen, until}] for flag-bar terms found inside
    the quiet window: they raise nothing now and are remembered, R10), and always "listing_read". No listing: the lists
    are empty and listing_read is false, which advance_candidates reads as unknown, never as absent."""
    uncarried = sorted(f['term'] for f in funded(plan, product)
                       if listing is not None and carried(f['term'], listing) is None)
    proven_out = sorted(t for t in proven(plan, product) if listing is not None and carried(t, listing) is None)
    flags = flag_candidates(plan, listing, product, cfg)
    now = {'uncarried_funded': uncarried, 'uncarried_proven': proven_out,
           'under_bar': sorted(_under_bar(plan, product, listing, cfg)),
           'stage': _stage_name(plan), 'flag_bar': [f['term'] for f in flags], 'listing_read': listing is not None}
    if today_iso:
        until = quiet_until(product, cfg)
        now['date'] = today_iso
        now['flags_in_quiet'] = ([{'term': f['term'], 'seen': today_iso, 'until': until} for f in flags]
                                 if until and today_iso < until else [])
    return now


def _counts(value):
    """A candidates entry as {term: runs}: a dict as it is, a list as one run each."""
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if _number(v) and v > 0}
    return {t: 1 for t in value or []}


def advance_candidates(previous, now):
    """The candidates to store after this run: per term, the count of consecutive runs it has been seen (a term absent
    this run drops out, so it restarts at 1 when seen again), this run's stage, the date of the last run counted, and
    flags_waiting: the flags found in the quiet window (R10), each keeping its first sighting, dropped once the window
    ends (that run raises it) or when the term leaves the flag bar.

    A re-run on the date already counted (`now.date` equal to `previous.date`) is not a new run: a term still present
    keeps its stored count (at least 1) and a term now absent drops. A run that read no listing (`now.listing_read`
    false) knows nothing about the copy: every count, the date and flags_waiting carry forward unchanged."""
    prev = previous or {}
    out = {}
    unread = now.get('listing_read') is False
    same_run = bool(now.get('date')) and prev.get('date') == now.get('date')
    for key in ('uncarried_funded', 'uncarried_proven', 'under_bar'):
        before = _counts(prev.get(key))
        if unread:
            out[key] = dict(before)
        elif same_run:
            out[key] = {t: max(before.get(t, 0), 1) for t in now.get(key) or []}
        else:
            out[key] = {t: before.get(t, 0) + 1 for t in now.get(key) or []}
    out['stage'] = now.get('stage')
    waiting_before = {e['term']: e for e in prev.get('flags_waiting') or [] if isinstance(e, dict) and e.get('term')}
    if unread:
        out['flags_waiting'] = [dict(e) for e in waiting_before.values()]
    elif 'flags_in_quiet' in now:
        out['flags_waiting'] = [dict(e, seen=waiting_before.get(e['term'], e)['seen']) for e in now['flags_in_quiet']]
    else:
        bar = set(now.get('flag_bar') or [])
        out['flags_waiting'] = [dict(e) for t, e in waiting_before.items() if t in bar]
    date = prev.get('date') if unread else now.get('date')
    if date:
        out['date'] = date
    return out


def proven_ready(candidates, cfg, offered=()):
    """The proven SKC keywords uncarried on pass_persist_runs runs in a row and not offered by the last block, sorted,
    when there are skc_min_proven of them; else []."""
    g = cfg['growth']
    need = g['pass_persist_runs']
    old = {norm(t) for t in offered or ()}
    new = sorted(t for t, n in _counts((candidates or {}).get('uncarried_proven')).items()
                 if n >= need and norm(t) not in old)
    return new if len(new) >= g.get('skc_min_proven', 2) else []


def gate_open(candidates, previous_stage, cfg, offered=(), offered_out=()):
    """Why the evidence gate is open, or None: skc_min_proven proven SKC keywords uncarried for pass_persist_runs
    runs ('2 proven SKC keywords uncarried for 2 runs: a, b'; a search the last block already offered as an In is not
    new and does not count; Kim 2026-10-25, was any funded search), a carried term under the pass bar for as many runs ('<term> under the bar for 2 runs'; one the last
    block already offered as a move down or remove does not count, R28), or a stage change since the last pass
    ('stage early -> mature')."""
    g = cfg['growth']
    need = g['pass_persist_runs']
    c = candidates or {}
    new = proven_ready(c, cfg, offered)
    if new:
        return f'{len(new)} proven SKC keywords uncarried for {need} runs: {", ".join(new)}'
    old_out = {norm(t) for t in offered_out or ()}
    under = sorted(t for t, n in _counts(c.get('under_bar')).items() if n >= need and norm(t) not in old_out)
    if under:
        return f'{under[0]} under the bar for {need} runs'
    now = c.get('stage')
    if previous_stage and now and previous_stage != now:
        return f'stage {previous_stage} -> {now}'
    return None


def previous_stage(product, previous):
    """The stage at the last pass (R5): the last passes entry's `stage`, else the previous item's growth.stage.name."""
    passes = [p for p in _growth(product).get('passes') or [] if isinstance(p, dict)]
    if passes and passes[-1].get('stage'):
        return passes[-1]['stage']
    return (((previous or {}).get('growth') or {}).get('stage') or {}).get('name')


def closed(item):
    """An item whose status is terminal (R11, amended): resolved or dismissed."""
    return bool(item) and item.get('status') in CLOSED_STATUSES


def dismissal_hold_until(previous, cfg):
    """R30: the first day the scheduled triggers may fire again after Growth dismissed the previous item: its
    `resolved_on` (human_review._set_status stamps it on dismissal; else the latest dismissed history line) +
    pass_floor_weeks. None when the item is not dismissed or carries no date. A dismissal adds no passes entry and moves
    neither the quiet clock nor the pass tag; its own flags stay quiet until this day (R43, held_flags)."""
    if not previous or previous.get('status') != 'dismissed':
        return None
    on = _date(previous.get('resolved_on'))
    if not on:
        dated = [_date(h.get('date')) for h in previous.get('history') or []
                 if isinstance(h, dict) and h.get('status') == 'dismissed' and _date(h.get('date'))]
        on = max(dated) if dated else None
    return _plus(on.isoformat(), cfg['growth']['pass_floor_weeks'] * 7) if on else None


def held_flags(previous, today_iso, cfg):
    """R43: the flags a dismissal holds quiet on `today_iso`, as [{term, until}] (`until` the first day the term may be
    raised again). A dismissed item's growth.flags terms until dismissal_hold_until(previous); and the growth.flags_held
    entries an item carries from a dismissal it replaced (a new term raised inside the hold opens a new item, on which the
    dismissed terms stay quiet until their date). A resolved item holds nothing (R11: the flags start again after the
    listing change's quiet window)."""
    if not previous or previous.get('status') == 'resolved':
        return []
    g = previous.get('growth') or {}
    out = {}
    for e in g.get('flags_held') or []:
        if isinstance(e, dict) and e.get('term') and _date(e.get('until')) and today_iso < e['until']:
            out[e['term']] = e['until']
    until = dismissal_hold_until(previous, cfg)
    if until and today_iso < until:
        for f in g.get('flags') or []:
            if isinstance(f, dict) and f.get('term'):
                out[f['term']] = max(until, out.get(f['term'], until))
    return [{'term': t, 'until': u} for t, u in out.items()]


def _flagged(previous, today_iso, cfg):
    """Terms not to raise again: those flagged on the previous item while it is not closed (R11), and those a dismissal
    holds quiet (R43, held_flags)."""
    held = {e['term'] for e in held_flags(previous, today_iso, cfg)}
    if not previous or closed(previous):
        return held
    return held | {f.get('term') for f in ((previous.get('growth') or {}).get('flags') or []) if isinstance(f, dict)}


def _offered(previous):
    """The In searches the previous item's block already handed Growth."""
    g = (previous or {}).get('growth') or {}
    terms = [x.get('term') for x in g.get('weave_in') or [] if isinstance(x, dict)]
    terms += [r['in'].get('term') for r in g.get('swaps') or [] if isinstance(r, dict) and isinstance(r.get('in'), dict)]
    return [t for t in terms if t]


def _offered_out(previous):
    """The carried terms the previous item's block already listed as a move down or a remove (R28)."""
    g = (previous or {}).get('growth') or {}
    return [r['out'].get('term') for r in g.get('swaps') or []
            if isinstance(r, dict) and isinstance(r.get('out'), dict) and r['out'].get('term')
            and (r['out'].get('action') or 'move down') in ('move down', 'remove')]


def _enabled(product, cfg):
    g = _growth(product)
    return g.get('enabled', cfg['growth'].get('enabled_default', False)) is True


def _new_flags(product, plan, listing, previous, today_iso, cfg):
    """Flag-bar terms outside the quiet window, not already flagged on the open item and not held by a dismissal."""
    until = quiet_until(product, cfg)
    if until and today_iso < until:
        return []
    flagged = _flagged(previous, today_iso, cfg)
    return [f for f in flag_candidates(plan, listing, product, cfg) if f['term'] not in flagged]


def new_skcs(product, listing, previous):
    """The new SKC searches (Kim, 2026-10-29, decision 167: "be sure to have the 'for growth' tab populated from time to
    time as new SKCs surface"): every search with its own SKC in the invest log that the live copy does not carry and no
    earlier block offered, sorted. [] without a listing read (the copy is unknown)."""
    if listing is None:
        return []
    offered = set(_offered(previous))
    out = set()
    for t in ((product or {}).get('invest_log') or {}):
        key = norm(t)
        if key and not branded(key) and key not in offered and carried(key, listing) is None:
            out.add(key)
    return sorted(out)


def new_skc_hold(product, previous, cfg):
    """The first day a new-SKC item may open (decision 167): new_skc_min_days after the previous item opened, and the
    quiet window after the last listing change; None when nothing holds it. An open item is refreshed, not held."""
    days = cfg['growth'].get('new_skc_min_days', 14)
    opened = ((previous or {}).get('growth') or {}).get('opened_on') or (previous or {}).get('first_seen')
    dates = [d for d in (_plus(opened, days) if opened else None, quiet_until(product, cfg)) if d]
    return max(dates) if dates else None


def _anchor_words(a):
    if not a:
        return 'no anchor'
    return {'monday_launch_date': 'launch', 'first_ad_click': 'first ad click',
            'hand': 'anchor set by hand'}.get(a.get('source'), a.get('source') or 'anchor') + f" {a.get('date')}"


def trigger_for(product, plan, listing, previous, today_iso, cfg):
    """(trigger, reason) for this run, or (None, None). Only a product whose growth.enabled is true fires.
    - rotate_out_flag (reason: the term): any time, before or after the first pass, a flag-bar term outside the quiet
      window, not already flagged on the open item and not held by a dismissal (R43, held_flags);
    - evidence_pass: after a resolved pass, on or after no_earlier_than, with the gate open (candidates advanced from
      growth.candidates by this run);
    - ceiling_pass: after a resolved pass, on or after `by`;
    - first_pass: no resolved pass; in evidence mode, the data floor holds and skc_min_proven proven SKC keywords sit
      uncarried for pass_persist_runs runs (else ceiling_pass at first_ceiling); in date mode, on or after the first due
      date.
    Priority: flag, evidence, ceiling, first. An item not yet closed (resolved or dismissed) holds its window: the scheduled triggers fire once per
    window, and only a flag updates an open item. A dismissed item holds the scheduled triggers until its dismissal +
    pass_floor_weeks (R30, dismissal_hold_until), and its own flags as long (R43); a flag on a new term still fires.
    `manual` is the caller's."""
    if not _enabled(product, cfg):
        return None, None
    flags = _new_flags(product, plan, listing, previous, today_iso, cfg)
    if flags:
        return 'rotate_out_flag', flags[0]['term']
    # decision 167: a search that got its own SKC and is missing from the copy raises an item (or refreshes the open one,
    # which then offers it), at most one new item every growth.new_skc_min_days
    g = cfg['growth']
    skcs = new_skcs(product, listing, previous) if g.get('new_skc_min_days') is not None else []
    if skcs:
        hold = None if previous is not None and not closed(previous) else new_skc_hold(product, previous, cfg)
        if not hold or today_iso >= hold:
            return 'new_skc', f"new SKC search{'es' if len(skcs) != 1 else ''} the copy does not carry: {', '.join(skcs)}"
    if previous is not None and not closed(previous):
        return None, None
    hold = dismissal_hold_until(previous, cfg)
    if hold and today_iso < hold:
        return None, None
    g = cfg['growth']
    dates = due_dates(product, cfg)
    window = dates['next_pass']
    if resolved_passes(product):
        if window['no_earlier_than'] and today_iso >= window['no_earlier_than']:
            candidates = advance_candidates(_growth(product).get('candidates'),
                                            gate_candidates(plan, listing, product, cfg, today_iso))
            reason = gate_open(candidates, previous_stage(product, previous), cfg, _offered(previous),
                               _offered_out(previous))
            if reason:
                return 'evidence_pass', reason
        if window['by'] and today_iso >= window['by']:
            return 'ceiling_pass', (f"{g['pass_ceiling_weeks']} weeks since the last listing change on "
                                    f"{last_listing_change(product)}: due by {window['by']}")
        return None, None
    if evidence_mode(cfg):
        if data_floor(plan, cfg) is None:
            candidates = advance_candidates(_growth(product).get('candidates'),
                                            gate_candidates(plan, listing, product, cfg, today_iso))
            ready = proven_ready(candidates, cfg, _offered(previous))
            if ready:
                return 'first_pass', (f"{len(ready)} proven SKC keywords the copy does not carry, for "
                                      f"{g['pass_persist_runs']} runs: {', '.join(ready)}")
        by = dates['next_pass'].get('by')
        if by and today_iso >= by:
            return 'ceiling_pass', (f"no proven SKC keywords handed over in {g['pass_ceiling_weeks']} weeks "
                                    f"(since {_anchor_words(_growth(product).get('anchor'))} or the switch on "
                                    f"{_growth(product).get('enabled_on') or 'an unknown day'}): due by {by}")
        return None, None
    if dates['first_due'] and today_iso >= dates['first_due']:
        return 'first_pass', (f"day {g['first_pass_days']} from the anchor "
                              f"({_anchor_words(_growth(product).get('anchor'))}): due {dates['first_due']}")
    return None, None


# ----------------------------------------------------------------------------- the item
def _in_row(f, listing):
    sits = 'unknown' if listing is None else 'missing'
    if f['source'] == 'invest_log' and not f.get('plan_why'):
        why = f"in the invest log as {f['role']}{' since ' + f['since'] if f.get('since') else ''}; no plan row this run"
    else:
        why = f.get('plan_why') or f['role']
    why += '; not carried' if listing is not None else '; the listing was not read this run'
    return dict(f, action='in', sits_today=sits, detail=_text(why))


def _launch_ins(product, listing, cfg):
    """A launch-stage product's weave-ins: the launch list's median set (else its first launch.rank_count searches
    by score), DataDive basis, no index; the ones the listing carries are left out."""
    searches = [s for s in ((product or {}).get('launch') or {}).get('searches') or []
                if isinstance(s, dict) and s.get('search')]
    picked = [s for s in searches if s.get('set') == 'median']
    if not picked:
        count = (cfg.get('launch') or {}).get('rank_count', 5)
        picked = sorted(searches, key=lambda s: -(s.get('score') or s.get('volume') or 0))[:count]
    out = []
    for s in picked:
        key = norm(s['search'])
        if branded(key):
            continue
        where = carried(key, listing)
        if where not in (None, 'unknown'):
            continue
        volume = s.get('volume') if _number(s.get('volume')) and s.get('volume') > 0 else None
        rel = s.get('relevancy')
        why = f"launch list (DataDive{f', relevancy {rel:.2f}' if _number(rel) else ''})"
        why += '; not carried' if listing is not None else '; the listing was not read this run'
        out.append(dict(term=key, role=None, source='launch', sqp_volume=volume, index=None, our_clicks=None,
                        our_purchases=None, market_cvr=None, our_cvr=None, basis='DataDive', relevance_flag=None,
                        action='in', sits_today='unknown' if listing is None else 'missing', detail=_text(why),
                        opportunity=volume or 0))
    return out


def _stage_block(plan, cfg):
    s = _summary(plan)
    info = s.get('stage') or {}
    name, through = info.get('stage'), s.get('sqp_data_through')
    if name == 'launch':
        window = 'no SQP yet: DataDive weave-ins only'
    else:
        window = f'SQP {SQP_DAYS} days to {through}' if through else f'SQP {SQP_DAYS} days'
    return {'name': name, 'window': window, 'observed_days_max': info.get('observed_days'),
            'trusted_queries': info.get('trusted_queries')}


def _evidence_rows(rows, offer):
    """The item's evidence: the query rows of needs-human.md, one per swap side and per offer problem."""
    ev = []
    for r in rows:
        for s in (r['in'], r['out']):
            if not s:
                continue
            where = s.get('slot_now') if s is r['out'] else r['slot']
            ev.append(dict(query=s['term'], basis=s.get('basis'), clicks=s.get('our_clicks'),
                           purchases=s.get('our_purchases'), our_cvr=s.get('our_cvr'), market_cvr=s.get('market_cvr'),
                           index=s.get('index'), note=f"{s.get('action')} ({where})"))
    for o in offer:
        ev.append(dict(query=o['search'], basis='SQP', clicks=o['our_clicks'], purchases=o.get('our_purchases'),
                       our_cvr=o['our_cvr'], market_cvr=o['market_cvr'], index=o['index'],
                       note=f'offer problem: {OFFER_LABEL}'))
    return ev


def _flag_text(f):
    """'rotate-out flag: colorful pens (35 SQP clicks, 0 purchases, index 0.22)'; a count of 1 in the singular."""
    index = f"{f['index']:.2f}" if _number(f.get('index')) else 'unknown'
    clicks, purchases = f.get('our_clicks'), f.get('our_purchases')
    return (f"rotate-out flag: {f['term']} ({clicks} SQP click{'' if clicks == 1 else 's'}, "
            f"{purchases} purchase{'' if purchases == 1 else 's'}, index {index})")


def _notes(stage, trigger, trigger_reason, dates, the_anchor, new_flags, listing, product, rows, watch, cfg):
    g = cfg['growth']
    notes = []
    if stage['name'] == 'launch':
        notes.append("Launch stage: no SQP yet, so the weave-ins are the launch list's DataDive searches and nothing "
                     'is judged for rotate-out.')
    elif stage['name'] == 'early':
        notes.append(f"Early stage, {stage['observed_days_max']} observed days: title and highlight edits only for the "
                     'paired swap; everything else in bullets and backend.')
    if trigger == 'first_pass' and dates['first_due'] is None:
        notes.append(f"First pass on evidence: {trigger_reason}.")
    elif trigger == 'first_pass':
        notes.append(f"Day-{g['first_pass_days']} pass due {dates['first_due']} ({_anchor_words(the_anchor)}).")
    elif trigger == 'evidence_pass':
        notes.append(f"Evidence pass: {trigger_reason}; the window was no earlier than "
                     f"{dates['next_pass']['no_earlier_than']}, by {dates['next_pass']['by']}.")
    elif trigger == 'ceiling_pass':
        notes.append(f'Ceiling pass: {trigger_reason}.')
    elif trigger == 'manual':
        notes.append('Raised by hand.')
    for f in new_flags:
        text = _flag_text(f)
        slot = str(f.get('slot_now') or '')
        where = slot if slot.startswith('bullet') else f'the {slot}'   # 'bullet 2', 'the title' (as _out_row says it)
        notes.append(f"{text[0].upper()}{text[1:]}, carried in {where}.")
    if listing is None:
        notes.append('No listing read this run: every In row sits today as unknown and there are no Out rows.')
    elif not (isinstance(listing.get('backend'), str) and listing['backend'].strip()):
        notes.append('backend: not readable, so a search carried only in the backend shows as missing.')
    if stage['name'] != 'launch' and not _roots(product):
        notes.append('No rotate-out rows: add relevance.roots (the head nouns) to the product file.')
    if not rows and watch:
        notes.append('Nothing to weave in, move down or remove this pass; the rotate-out table only watches terms '
                     'near the bar.')
    elif not rows:
        notes.append('Nothing to weave in or rotate out this pass.')
    return ' '.join(notes)


def build_item(asin, plan, product, shared, listing, date, trigger, previous=None, trigger_reason=None,
               candidates=None, produced=None):
    """The For Growth human_review item (id for-growth, kind growth, lane growth, owner Growth) for this run.

    `date` is the run's SGT date; `trigger` one of TRIGGERS; `previous` the item already in the product file, if any
    (its status and first_seen are kept unless it was closed, resolved or dismissed: a new pass opens, born open on
    `date`, R11; callers pass a closed item too, so its held flags carry, R43); `candidates` the gate
    bookkeeping to store (advanced from growth.candidates by this run when not given); `produced` the SGT time stamp
    ('YYYY-MM-DD HH:MM SGT'; the run's date and the clock's time when not given). growth.block and growth.block_md
    are the hand-over block in Growth's two forms. A flag item's reason is the flag in words: 'rotate-out flag: <term>
    (<clicks> SQP clicks, <purchases> purchases, index <i>)'. growth.opened_on is the day this pass opened (R33): the
    previous item's when it is not closed, else `date`. growth.flags_held, only when a dismissal holds terms quiet on
    `date` (R43, held_flags): [{term, until}], so a new item raised inside the hold keeps them quiet too."""
    cfg = shared
    g = _growth(product)
    summary = _summary(plan)
    the_anchor = g.get('anchor') or anchor(product, None)
    dated = dict(product, growth=dict(g, anchor=the_anchor))
    dates = due_dates(dated, cfg)
    stage = _stage_block(plan, cfg)
    if stage['name'] == 'launch':
        ins, outs, offer, watch = _launch_ins(product, listing, cfg), [], [], []
    else:
        ins = [_in_row(f, listing) for f in funded(plan, product) if carried(f['term'], listing) in (None, 'unknown')]
        outs = rotate_candidates(plan, product, listing, cfg)
        offer = offer_problems(plan, product, cfg)
        watch = watch_list(plan, product, listing, cfg)
    taken = highlights = 0
    for x in sorted(ins, key=_opp_key):
        x['slot'] = suggest_slot(x, listing, product, cfg, taken, highlights)
        taken += x['slot'] == 'title'
        highlights += x['slot'] == 'highlight'
    rows = swaps(outs, ins)
    weave_in = [r['in'] for r in rows if r['in']]
    command = seed_string(asin, weave_in)
    new_flags = _new_flags(dated, plan, listing, previous, date, cfg) if trigger == 'rotate_out_flag' else []
    new_flags.sort(key=lambda f: f['term'] != trigger_reason)   # the flag the trigger named first
    flags = [dict(f) for f in (((previous or {}).get('growth') or {}).get('flags') or [])
             if isinstance(f, dict)] if previous and not closed(previous) else []
    flags += [dict(f, date=date) for f in new_flags]
    if candidates is None:
        candidates = advance_candidates(g.get('candidates'), gate_candidates(plan, listing, product, cfg, date))
    due = {'first_pass': dates['first_due'], 'ceiling_pass': dates['next_pass']['by']}.get(trigger) or date
    # the product file's name first (the record; a hand emit reads an older plan.json whose name may be stale: "Scenery"
    # for the scenery bookmarks on 2026-10-25), then the plan's
    name = (product or {}).get('product') or summary.get('product') or (product or {}).get('name') or asin
    if trigger == 'rotate_out_flag':
        reason_text = ('; '.join(_flag_text(f) for f in new_flags) if new_flags else
                       f'rotate-out flag: {trigger_reason}' if trigger_reason else
                       'a carried term crossed the rotate-out flag bar')
    else:
        reason_text = trigger_reason or {'first_pass': 'the first listing pass is due',
                                         'evidence_pass': 'the evidence gate opened',
                                         'ceiling_pass': 'the 26-week ceiling arrived',
                                         'new_skc': 'a new SKC search the copy does not carry',
                                         'manual': 'raised by hand'}.get(trigger, 'listing pass')
    pass_tag = dates['pass']
    status = (previous or {}).get('status') or 'open'
    if status in CLOSED_STATUSES:
        status = 'open'
    # R33: the day this pass opened. The item id is for-growth on every pass and the dashboard's status entries carry no
    # pass, so dashboard.apply_statuses counts Growth's clicks from this day only. A previous item not yet closed is the
    # same pass (a flag refresh); one built before opened_on existed gives the day it was first seen.
    if previous and not closed(previous):
        opened_on = ((previous.get('growth') or {}).get('opened_on') or previous.get('first_seen') or date)
    else:
        opened_on = date
    through = summary.get('sqp_data_through')
    action = ('Paste the block into the listing optimizer and run its command; mark Picked up, then Copy pushed once '
              'the new copy is submitted. The seeds are candidates for the optimizer to verify, not an answer.')
    source = ('Scale Insights SQP and search-term reports through the weekly plan (roles, index, volume); the live '
              + (f"listing read {listing.get('read_at')} ({listing.get('source')})" if listing is not None
                 else 'listing was not read this run'))
    item = {
        'id': GROWTH_ID, 'kind': 'growth', 'title': f'For Growth: {pass_tag} for {name}',
        'reason': _text(f'{pass_tag}: {reason_text}'), 'action': action, 'source': source,
        'window': (f'SQP {SQP_DAYS} days to {through}; ads 90 days' if through else
                   f'no SQP window ({stage["name"] or "unknown"} stage); ads 90 days'),
        'evidence': _evidence_rows(rows, offer), 'owner': 'Growth', 'status': status, 'priority': 'normal',
        'first_seen': ((previous.get('first_seen') if previous and not closed(previous) else None) or date),
        'last_seen': date, 'origin': 'sweep',
        'ai_review': {'phase': 'human_ready'},
        'workflow': {'lane': 'growth', 'action': 'Run the listing pass with the block', 'why': _text(reason_text),
                     'owner': 'Growth', 'date': date},
        'growth': {
            'asin': asin, 'product': name,
            'produced': produced or f"{date} {dt.datetime.now(SGT).strftime('%H:%M')} SGT",
            'pass': pass_tag, 'trigger': trigger, 'trigger_reason': trigger_reason, 'opened_on': opened_on, 'stage': stage,
            'trusted_min_clicks': (cfg.get('thresholds') or {}).get('trusted_min_clicks', 10),
            'window': {'sqp_data_through': through, 'days': SQP_DAYS},
            'anchor': the_anchor, 'due': due, 'next_pass': dates['next_pass'], 'candidates': candidates,
            'listing_snapshot': dict(listing) if listing is not None else None,
            'swaps': rows, 'weave_in': weave_in, 'rotate_out': watch, 'offer': offer, 'command': command,
            'flags': flags,
            'note': _notes(stage, trigger, trigger_reason, dates, the_anchor, new_flags, listing, product, rows, watch,
                           cfg),
        },
    }
    held = held_flags(previous, date, cfg)
    if held:
        item['growth']['flags_held'] = held
    item['growth']['block'] = block_json(item)
    item['growth']['block_md'] = render_block(item)
    return item


# ----------------------------------------------------------------------------- the two renderers
def _whole(v):
    return int(round(v)) if _number(v) else None


def _pct(v):
    """A fraction as the block's percent number (0.156 -> 15.6)."""
    return round(v * 100, 1) if _number(v) else None


def _swap_row(slot, side, s):
    action = s.get('action') or ('in' if side == 'in' else 'move down')
    return {'slot': (s.get('slot_now') or slot) if side == 'out' else slot, 'term': _text(s.get('term')),
            'action': action, 'role': _text(s.get('role')), 'sqp_volume': _whole(s.get('sqp_volume')),
            'index': round(s['index'], 2) if _number(s.get('index')) else None,
            'our_clicks': _whole(s.get('our_clicks')), 'our_purchases': _whole(s.get('our_purchases')),
            'basis': _text(s.get('basis')),
            'why': _text(s['detail'] if s.get('detail') is not None else s.get('why'))}


def block_json(item):
    """The block's JSON form, the reference's keys: asin, product, produced, pass, stage {name, window,
    observed_days_max, trusted_queries}, command (no backticks), swaps (flat rows, each pair's In before its Out),
    rotate_out, offer_problems (CVRs as percent numbers), notes."""
    g = item.get('growth') or {}
    st = g.get('stage') or {}
    rows = []
    for r in g.get('swaps') or []:
        for side in ('in', 'out'):
            if r.get(side):
                rows.append(_swap_row(r.get('slot'), side, r[side]))
    rotate = [{'term': _text(w.get('term')), 'slot_now': _text(w.get('slot_now')), 'our_clicks': _whole(w.get('our_clicks')),
               'our_purchases': _whole(w.get('our_purchases')),
               'index': round(w['index'], 2) if _number(w.get('index')) else None, 'bar': _text(w.get('bar'))}
              for w in g.get('rotate_out') or []]
    offer = [{'search': _text(o.get('search')), 'sqp_volume': _whole(o.get('sqp_volume')), 'our_cvr': _pct(o.get('our_cvr')),
              'market_cvr': _pct(o.get('market_cvr')), 'our_clicks': _whole(o.get('our_clicks')),
              'bid_action': _text(o.get('bid_action'))}
             for o in g.get('offer') or []]
    return {'asin': g.get('asin'), 'product': g.get('product'), 'produced': g.get('produced'), 'pass': g.get('pass'),
            'stage': {'name': st.get('name'), 'window': _text(st.get('window')),
                      'observed_days_max': st.get('observed_days_max'), 'trusted_queries': st.get('trusted_queries')},
            'command': g.get('command'), 'swaps': rows, 'rotate_out': rotate, 'offer_problems': offer,
            'notes': g.get('note')}


def _cell(v, kind=None):
    if v is None:
        return ''
    if kind == 'volume':
        return f'{int(v):,}'
    if kind == 'index':
        return f'{v:.2f}'
    if kind == 'pct':
        return f'{v:.1f}%'
    return str(v)


def _table_line(cells):
    """`| a | b |`, a blank cell as `| |` (the reference's form)."""
    return '|' + ''.join(f' {c} |' if c != '' else ' |' for c in cells)


def _stage_line(stage, trusted_min_clicks=10):
    details = [stage.get('window'),
               f"longest observed-day count {stage['observed_days_max']}" if stage.get('observed_days_max') is not None else None,
               f"{stage['trusted_queries']} queries with {trusted_min_clicks}+ of our clicks"
               if stage.get('trusted_queries') is not None else None]
    details = [d for d in details if d]
    # an unknown stage name is left out, as block_json leaves it null, so both forms parse to the same null name
    return ' '.join(p for p in (stage.get('name') or '', f"({'; '.join(details)})" if details else '') if p)


def render_block(item):
    """The block's markdown form, exactly the reference's layout: the `## For Growth:` header, the four `- Key:` lines,
    the three tables under their ### headings (a table with no rows is left out: nothing to report) and ### Notes."""
    b = block_json(item)
    trusted_clicks = (item.get('growth') or {}).get('trusted_min_clicks') or 10   # thresholds.trusted_min_clicks
    lines = [f"## For Growth: {b['asin']} {b['product'] or ''}".rstrip(), f"- Produced: {b['produced'] or ''}",
             f"- Pass: {b['pass'] or ''}", f"- Stage: {_stage_line(b['stage'], trusted_clicks)}",
             f"- Command: `{b['command'] or ''}`"]
    tables = (
        (SWAP_HEADING, SWAP_COLUMNS, b['swaps'],
         lambda r: [_cell(r['slot']), _cell(r['term']), _cell(r['action']), _cell(r['role']),
                    _cell(r['sqp_volume'], 'volume'), _cell(r['index'], 'index'), _cell(r['our_clicks']),
                    _cell(r['our_purchases']), _cell(r['basis']), _cell(r['why'])]),
        (ROTATE_HEADING, ROTATE_COLUMNS, b['rotate_out'],
         lambda r: [_cell(r['term']), _cell(r['slot_now']), _cell(r['our_clicks']), _cell(r['our_purchases']),
                    _cell(r['index'], 'index'), _cell(r['bar'])]),
        (OFFER_HEADING, OFFER_COLUMNS, b['offer_problems'],
         lambda r: [_cell(r['search']), _cell(r['sqp_volume'], 'volume'), _cell(r['our_cvr'], 'pct'),
                    _cell(r['market_cvr'], 'pct'), _cell(r['our_clicks']), _cell(r['bid_action'])]),
    )
    for heading, columns, rows, cells in tables:
        if rows:
            lines += ['', heading, _table_line(columns), '|' + '---|' * len(columns)]
            lines += [_table_line(cells(r)) for r in rows]
    lines += ['', NOTES_HEADING, b['notes'] or '']
    return '\n'.join(lines) + '\n'
