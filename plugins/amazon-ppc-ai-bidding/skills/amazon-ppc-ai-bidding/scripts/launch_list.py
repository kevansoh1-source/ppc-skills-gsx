#!/usr/bin/env python3
"""The launch list: the `launch` block of a product file, built from the product's DataDive niche (docs/superpowers/
specs/2026-10-21-keyword-selection-by-data-stage-design.md, section 4.3; built 2026-10-22).

Pulls, each saved in the run folder as the tool returned it (references/data-pull.md, "Launch list"):
- niche_keywords.json: DataDive `get_niche_keywords` on the niche the Monday "1st Datadive" link names;
- keyword_recs.json (optional): MarketplaceAdPros `get_amazon_ads_ad_group_keyword_recs` on the product's harvest ad group;
- the research sheet's extra searches (optional), typed on the command line.

What it works out:
- the order: volume x relevancy, highest first (a sheet search has no DataDive relevancy: its volume alone);
- the left-out: a search whose relevancy is under `launch.min_relevancy`;
- the fold: close variants (plurals, spacing and word order) collapse into the spelling with the higher score, so
  "gel pens colored" and "colored gel pens" do not both take a median slot;
- the median set: the first `launch.rank_count` of the list with two or more tokens. One-word heads ("pens") stay in
  the list at `shared` and never take a median slot; so does everything else that is listed;
- Amazon's additions: a recommendation Amazon ranks within `launch.amazon_top_rank` by impression rank, with two or more
  tokens, not already in the list, not a search the niche left out and not negated by the product's relevance lists, joins
  at `amazon`, after the niche rows;
- the roots: the words every listed search at relevancy 0.9 or more shares, proposed for the onboarding person to confirm.

Usage:
  python launch_list.py --asin B0SAMP0012 --niche <run>/niche_keywords.json [--niche-id PCAEwf4c8H]
                        [--recs <run>/keyword_recs.json] [--roots "pens|colored"] [--extra "gel pens for school:20000|..."]
                        --today 2026-10-22 --out <run>/launch_block.json [--data <folder>]

It prints the table (search, volume, relevancy, score, set, note) and the left-out list with the reasons, and writes the
block to --out. It never writes the product file: once the onboarding person has set `date` (the launch date from the
Monday board) and confirmed `roots`, the block is pasted into data/asins/<ASIN>.json as "launch". The negation comes from
that product file's `relevance` block when the file exists (--data is the folder holding asins/, as plan.py reads it);
without it, Amazon's additions are not checked against any relevance list, and the output says so.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from close_variants import norm_cv  # noqa: E402
from human_review import sgt_today  # noqa: E402
from plan import load_raw, make_irrelevant, product_sizes, read_json, write_json  # noqa: E402
from searchtext import norm  # noqa: E402
from stage import relevance_flag  # noqa: E402

ROOTS_MIN_RELEVANCY = 0.9   # the roots are the words every listed search at this relevancy or more shares
STOP_WORDS = frozenset('a an and for of the to with in on'.split())
ONE_TOKEN_WHY = 'one token: never in the median set'


def load_niche(path):
    """The saved get_niche_keywords response ({keywords, latestResearchDate}), raw or in the tool-result wrapper."""
    niche = load_raw(path)
    if not (isinstance(niche, dict) and isinstance(niche.get('keywords'), list) and niche.get('latestResearchDate')):
        sys.exit(f'{path} is not a saved get_niche_keywords response (it needs "keywords" and "latestResearchDate"). '
                 'Nothing built.')
    return niche


def variant_key(search):
    """Searches with the same key are close variants of each other. close_variants.norm_cv reads plurals, spacing and
    "book marks"; the key also ignores word order, as the spec's rule names it (section 4.3: "plurals, word order,
    spacing"). close_variants.is_close_variant keeps word order, so on its own it would let "gel pens colored" and
    "colored gel pens" both take a median slot."""
    return tuple(sorted(norm_cv(search).split()))


def one_token(search):
    return relevance_flag(search, None, set(), []) == 'one token'


def tokens(text):
    """The words of a search: lower case, punctuation and hyphens read as spaces, stop words dropped. There is no
    growth module yet; this is the rule it will carry, copied here (the launch design's roots rule)."""
    return [w for w in re.sub(r'[\W_]+', ' ', (text or '').lower()).split() if w not in STOP_WORDS]


def order_rows(niche, extra):
    """Every candidate as {search, volume, relevancy, score, source}, best first. A niche row's score is
    int(volume x relevancy); a research-sheet row has no DataDive relevancy, so relevancy is None and its score is its
    volume. Ties go to the higher volume, then the search, so the order is the same on every run."""
    rows = []
    for k in niche['keywords']:
        volume = int(k.get('searchVolume') or 0)
        relevancy = k.get('relevancy') or 0
        rows.append({'search': k['keyword'].strip(), 'volume': volume, 'relevancy': relevancy,
                     'score': int(volume * relevancy), 'source': 'datadive'})
    for e in extra:
        volume = int(e['volume'])
        rows.append({'search': e['search'].strip(), 'volume': volume, 'relevancy': None, 'score': volume,
                     'source': 'sheet'})
    return sorted(rows, key=lambda r: (-r['score'], -r['volume'], r['search']))


def split_left_out(rows, min_relevancy):
    """(kept, left_out): a row with a DataDive relevancy under `min_relevancy` is left out, with the reason."""
    kept, left_out = [], []
    for r in rows:
        if r['relevancy'] is not None and r['relevancy'] < min_relevancy:
            left_out.append({'search': r['search'], 'why_out': f"relevancy {r['relevancy']:.3f} under {min_relevancy:g}"})
        else:
            kept.append(r)
    return kept, left_out


def fold_variants(rows):
    """One row per group of close variants, in the order of `rows` (best first, so the keeper is the spelling with the
    higher score), each with the variants it absorbed in `folded`."""
    keepers, by_key = [], {}
    for r in rows:
        key = variant_key(r['search'])
        if key in by_key:
            by_key[key]['folded'].append(r['search'])
        else:
            by_key[key] = dict(r, folded=[])
            keepers.append(by_key[key])
    return keepers


def median_set(keepers, rank_count):
    """The list entries: the first `rank_count` keepers with two or more tokens are 'median', every other keeper is
    'shared'. A one-word search is 'shared' whatever its score, and says why."""
    entries, taken = [], 0
    for k in keepers:
        why = None
        if one_token(k['search']):
            set_, why = 'shared', ONE_TOKEN_WHY
        elif taken < rank_count:
            set_, taken = 'median', taken + 1
        else:
            set_ = 'shared'
        entry = {'search': k['search'], 'volume': k['volume'], 'relevancy': k['relevancy'], 'score': k['score'],
                 'set': set_, 'source': k['source'], 'folded': k['folded']}
        if why:
            entry['why'] = why
        entries.append(entry)
    return entries


def amazon_additions(recs, listed, left_out, top_rank, negate=None):
    """The recommendations that join the list at 'amazon': ranked within `top_rank` by impression rank (a null rank never
    qualifies), two or more tokens, not already listed (neither the same search nor a close variant of a listed one, or
    of one already added), not one the niche left out for low relevancy or a close variant of one (the niche list ranks
    above Amazon's, spec 4.2), and not negated. Best rank first. They carry no volume, relevancy or score."""
    taken = {variant_key(e['search']) for e in listed} | {variant_key(e['search']) for e in left_out}
    ranked = sorted((r for r in recs if isinstance(r.get('searchTermImpressionRank'), int)
                     and r['searchTermImpressionRank'] <= top_rank), key=lambda r: r['searchTermImpressionRank'])
    added = []
    for r in ranked:
        search = r['keyword'].strip()
        key = variant_key(search)
        if one_token(search) or key in taken or (negate and negate(norm(search))):
            continue
        taken.add(key)
        added.append({'search': search, 'volume': None, 'relevancy': None, 'score': None, 'set': 'amazon',
                      'source': 'amazon', 'folded': []})
    return added


def propose_roots(rows):
    """The words every row with relevancy >= 0.9 shares ('pens' and 'pen' read alike), as the first row to carry each
    spells it, the most carried first, then alphabetically. [] when no row reaches 0.9. `rows` are list entries."""
    spelling, carried, shared = {}, {}, None
    for r in rows:
        words = {}
        for w in tokens(r['search']):
            words.setdefault(norm_cv(w), w)
        for key, w in words.items():
            spelling.setdefault(key, w)
            carried[key] = carried.get(key, 0) + 1
        if (r.get('relevancy') or 0) >= ROOTS_MIN_RELEVANCY:
            shared = set(words) if shared is None else shared & set(words)
    return [spelling[k] for k in sorted(shared or (), key=lambda k: (-carried[k], spelling[k]))]


def source_sentence(niche_id, dive_date, today_iso, extra):
    who = f'DataDive niche {niche_id}' if niche_id else 'DataDive niche (niche id not given)'
    sheet = ''
    if extra:
        notes = sorted({e['source'] for e in extra if e.get('source')})
        sheet = f", plus {len(extra)} research-sheet search{'es' if len(extra) != 1 else ''}" + (
            f" ({'; '.join(notes)})" if notes else '')
    return f'{who}, dive of {dive_date}{sheet}, read {today_iso}.'


def build_block(niche, cfg, today_iso, roots=None, extra=(), recs=None, negate=None, niche_id=None):
    """The `launch` block. `niche` is the saved get_niche_keywords response, `cfg` the shared config.json, `extra` the
    research sheet's {search, volume, source} rows, `recs` the saved keyword recommendations (a list), `negate` the
    plan.make_irrelevant callable (a normalised search in, a reason or None out). `date` stays None for the onboarding
    person to set; `roots` is the proposal unless given."""
    launch = cfg['launch']
    kept, left_out = split_left_out(order_rows(niche, extra), launch['min_relevancy'])
    searches = median_set(fold_variants(kept), launch['rank_count'])
    searches += amazon_additions(recs or [], searches, left_out, launch['amazon_top_rank'], negate)
    dive_date = str(niche['latestResearchDate'])[:10]
    return {'date': None,
            'source': source_sentence(niche_id, dive_date, today_iso, extra),
            'niche_id': niche_id,
            'dive_date': dive_date,
            'searches': searches,
            'left_out': left_out,
            'roots': list(roots) if roots is not None else propose_roots(searches),
            'qualifiers': []}


def print_table(block):
    """The list as a table (search, volume, relevancy, score, set, and a note for a fold or a one-word head), then the
    left-out searches with their reasons and the roots."""
    def cell(v):
        return '-' if v is None else str(v)
    table = [('search', 'volume', 'relevancy', 'score', 'set', 'note')]
    for s in block['searches']:
        note = '; '.join(filter(None, [s.get('why'), 'folds: ' + ', '.join(s['folded']) if s['folded'] else '']))
        table.append((s['search'], cell(s['volume']), '-' if s['relevancy'] is None else f"{s['relevancy']:.3f}",
                      cell(s['score']), s['set'], note))
    width = [max(len(row[i]) for row in table) for i in range(5)]
    print(f"Source: {block['source']}")
    for row in table:
        print('  '.join([row[0].ljust(width[0])] + [row[i].rjust(width[i]) for i in (1, 2, 3)]
                        + [row[4].ljust(width[4]), row[5]]).rstrip())
    print(f"\nLeft out ({len(block['left_out'])}):")
    for r in block['left_out']:
        print(f"  {r['search']}: {r['why_out']}")
    print(f"\nRoots (the onboarding person confirms): {', '.join(block['roots']) or 'none'}")
    print('Date: not set. The onboarding person sets it from the Monday board before the block is pasted.')


def parse_extra(text):
    """'search:volume|search:volume' to [{search, volume, source}]."""
    rows = []
    for part in filter(None, (p.strip() for p in (text or '').split('|'))):
        search, _, volume = part.rpartition(':')
        if not search.strip() or not volume.strip().isdigit():
            sys.exit(f'--extra wants "search:volume|search:volume"; "{part}" is not one. Nothing built.')
        rows.append({'search': search.strip(), 'volume': int(volume), 'source': 'research sheet'})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--asin', required=True)
    ap.add_argument('--niche', required=True, help='the saved get_niche_keywords response')
    ap.add_argument('--niche-id', help="the DataDive niche id, for the block's source note")
    ap.add_argument('--recs', help='the saved get_amazon_ads_ad_group_keyword_recs response')
    ap.add_argument('--roots', help='"a|b": the roots, in place of the proposal')
    ap.add_argument('--extra', help='"search:volume|search:volume": the research sheet\'s extra searches')
    ap.add_argument('--today', help='YYYY-MM-DD; defaults to today (the read date in the source note)')
    ap.add_argument('--out', required=True, help='where the block is written (<run>/launch_block.json)')
    ap.add_argument('--skill', default=os.path.dirname(HERE))
    ap.add_argument('--data', help='shared data folder holding asins/<ASIN>.json (default: config.json data_dir, else <skill>/data)')
    a = ap.parse_args()
    shared = read_json(os.path.join(a.skill, 'config.json'))
    data_dir = a.data or shared.get('data_dir') or os.path.join(a.skill, 'data')
    product_path = os.path.join(data_dir, 'asins', f'{a.asin}.json')
    negate = None
    if os.path.exists(product_path):
        product = read_json(product_path)
        negate = make_irrelevant(a.asin, product.get('relevance') or {}, product_sizes(a.asin, product))
    roots = [r.strip() for r in a.roots.split('|') if r.strip()] if a.roots is not None else None
    recs = load_raw(a.recs) if a.recs else None
    if recs is not None and not isinstance(recs, list):
        sys.exit(f'{a.recs} is not a saved get_amazon_ads_ad_group_keyword_recs response (a list of keywords). '
                 'Nothing built.')
    block = build_block(load_niche(a.niche), shared, a.today or sgt_today(), roots=roots, extra=parse_extra(a.extra),
                        recs=recs, negate=negate, niche_id=a.niche_id)
    if os.path.dirname(a.out):
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
    write_json(a.out, block, indent=2)
    print_table(block)
    if negate:
        print(f'Amazon additions checked against the relevance lists in {product_path}.')
    else:
        print(f'No product file at {product_path}: Amazon additions were not checked against any relevance list.')
    print(f'Block written to {a.out}. Nothing was written to the product file.')


if __name__ == '__main__':
    main()
