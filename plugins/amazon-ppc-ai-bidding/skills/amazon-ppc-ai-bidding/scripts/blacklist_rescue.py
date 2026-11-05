#!/usr/bin/env python3
"""Blacklist rescue: no Invest or Prove-first search may sit on the product's Scale Insights blacklist.

Kim, 2026-10-21: "be sure to do the blacklist removals for the keywords that are on invest/prove first. make sure the
skill has this provisioned in it as well."

Scale Insights pushes the product's blacklist into every ad group the blacklist is assigned to, and Amazon applies close
variants to negatives. So an exact entry that is the search itself or a variant of it ("magnetic bookmark",
"magnetic book marks"), or a phrase entry whose words appear in the search in order ("turkey" in "turkey stickers",
"mini" in "mini scripture cards"), switches the invested search off wherever the blacklist reaches. The first sweep
(2026-10-21) found 34 such entries on 11 of 24 products, 13 of them on the magnetic bookmarks.

The rescue removes those entries and puts every invested search on the product's exact whitelist. Searches the team
keeps blacklisted on purpose (config.json scale_insights.blacklist_keep: the brand search "yourbrand", organic only,
Kim 2026-10-20) are never rescued.

Input: the product's lists as Scale Insights shows them on /Automation/Algo/BlacklistRule/Edit?asin=<ASIN>, saved as
<run>/si_blacklist.json: {"NegativeExactList": [...], "NegativePhraseList": [...], "ExactWhiteList": [...],
"PhraseWhiteList": [...], "_read": "<when and how>"} (references/scale-insights-playbook.md, "Blacklist rescue").

Usage:
  python blacklist_rescue.py --asin <ASIN> --lists <run>/si_blacklist.json [--run <run>] [--skill <skill dir>]
prints the entries to remove, the searches to whitelist and the new list contents, and writes <run>/blacklist_rescue.json
when --run is given. plan.py runs the same check when si_blacklist.json is in the run folder and adds a
"Scale Insights setup" row (a person's call) when there is anything to rescue.
"""
import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from close_variants import is_close_variant, phrase_blocks  # noqa: E402

INVEST_ROLES = ('Invest', 'Prove first')
LIST_KEYS = ('NegativeExactList', 'NegativePhraseList', 'ExactWhiteList', 'PhraseWhiteList')


def lines(value):
    """A Scale Insights textarea's entries: one per line, blank lines dropped."""
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [s for s in str(value or '').splitlines() if s.strip()]


def whitelist_text(search):
    """A search as Scale Insights' whitelist accepts it: letters, digits and single spaces ("w/ pockets" was refused as
    "Invalid characters" on 2026-10-21; Amazon matches "w pockets" the same). Accented letters stay as they are: the
    whitelist saved "tarjetas de cumpleaños" on 2026-10-26, after the a-z-only version had proposed "tarjetas de
    cumplea os" for B0SAMP0027. They are not folded either, so "español" and "espanol" are different entries."""
    s = unicodedata.normalize('NFC', search or '').lower()  # a decomposed "n" + tilde is the one letter "ñ"
    return re.sub(r'\s+', ' ', re.sub(r'[^\w ]|_', ' ', s)).strip()


def invested_searches(cfg, rank_terms=(), business_log=None, business_rank_terms=(), sizes=None):
    """The searches the team invests in: the product file's invest log rows on Invest or Prove first, plus this run's
    rank searches (plan.py's terms with role Rank). The business invests count the same (design
    2026-10-21-b2b-lane-and-roles 4h): the business invest log's Invest or Prove first rows (the product file's
    business_invest_log, same shape) and this run's business rank searches, since the blacklist reaches the B2B ad groups
    as it does the consumer ones."""
    out = set()
    for log in (cfg.get('invest_log') or {}, business_log or {}):
        out |= {str(k).strip().lower() for k, v in log.items() if (v or {}).get('role') in INVEST_ROLES}
    out |= {str(t).strip().lower() for t in list(rank_terms) + list(business_rank_terms)}
    from plan import product_sizes, wrong_size  # lazy import: plan.py also uses this module
    sizes = product_sizes(cfg.get('asin'), cfg) if sizes is None else sizes
    return sorted(s for s in out if s and not wrong_size(s, sizes))


def brand_search(search, keep=()):
    """The `keep` entry (config.json scale_insights.blacklist_keep: the brand, "yourbrand") that `search` contains as a
    word or words in order, close variants applied, or None. Such a search is the brand's, organic only (Kim,
    2026-10-20): "yourbrand birthday cards" as much as "yourbrand" itself. plan.py never invests in or raises one."""
    for k in keep:
        k = str(k).strip().lower()
        if k and (str(search or '').strip().lower() == k or phrase_blocks(k, search or '')):
            return k
    return None


def rescue(searches, lists, keep=()):
    """What to change so no search in `searches` is blocked: {exact_remove, phrase_remove, whitelist_add, blocks}.

    exact_remove: exact entries that are a search or a close variant of one; phrase_remove: phrase entries whose words
    appear in a search, in order (close variants applied); whitelist_add: searches missing from the exact whitelist, in
    the form the whitelist accepts; blocks: {entry: [the searches it blocks]}. A search that contains a `keep` entry
    (brand_search) is left blacklisted, so is never whitelisted and never frees an entry: "yourbrand birthday cards" kept
    "yourbrand" on the blacklist only by hand until 2026-10-26, when the rollout run took it off for 14 minutes."""
    searches = [s for s in searches if not brand_search(s, keep)]
    exact, phrase = lines(lists.get('NegativeExactList')), lines(lists.get('NegativePhraseList'))
    white = {whitelist_text(w) for w in lines(lists.get('ExactWhiteList'))}
    blocks = {}
    exact_remove = []
    for e in exact:
        hit = [s for s in searches if is_close_variant(e, s)]
        if hit:
            exact_remove.append(e)
            blocks[e] = hit
    phrase_remove = []
    for p in phrase:
        hit = [s for s in searches if phrase_blocks(p, s)]
        if hit:
            phrase_remove.append(p)
            blocks[p] = hit
    whitelist_add = []
    for s in searches:
        w = whitelist_text(s)
        if w and w not in white and w not in whitelist_add:
            whitelist_add.append(w)
    return dict(exact_remove=exact_remove, phrase_remove=phrase_remove, whitelist_add=whitelist_add, blocks=blocks)


def new_lists(lists, result):
    """The lists after the rescue, as the four textareas should read."""
    drop_e, drop_p = set(result['exact_remove']), set(result['phrase_remove'])
    return dict(NegativeExactList=[e for e in lines(lists.get('NegativeExactList')) if e not in drop_e],
                NegativePhraseList=[p for p in lines(lists.get('NegativePhraseList')) if p not in drop_p],
                ExactWhiteList=lines(lists.get('ExactWhiteList')) + result['whitelist_add'],
                PhraseWhiteList=lines(lists.get('PhraseWhiteList')))


def plan_row(asin, result, read_note=None):
    """The planner's change row for a rescue, or None when nothing is blocked and every search is whitelisted."""
    n_rm = len(result['exact_remove']) + len(result['phrase_remove'])
    if not n_rm and not result['whitelist_add']:
        return None
    show = '; '.join(f'"{k}" blocks {", ".join(v[:2])}' + (' ...' if len(v) > 2 else '') for k, v in list(result['blocks'].items())[:6])
    return dict(step=95, type='Scale Insights setup', keyword='blacklist rescue',  # its own row id, apart from step 94's
                item=f"Blacklist rescue: remove {n_rm} blacklist entr{'y' if n_rm == 1 else 'ies'} that block invest searches; "
                     f"whitelist {len(result['whitelist_add'])}",
                current=f"{len(result['exact_remove'])} exact and {len(result['phrase_remove'])} phrase entries block invested searches"
                        + (f": {show}" if show else ''),
                new=f"Removed; {len(result['whitelist_add'])} search(es) added to the exact whitelist",
                exact_remove=result['exact_remove'], phrase_remove=result['phrase_remove'], whitelist_add=result['whitelist_add'],
                why=('An invested search must never be on its own product\'s blacklist (Kim, 2026-10-21): Scale Insights pushes '
                     'the blacklist into every ad group it is assigned to and Amazon applies close variants to negatives, so '
                     'these entries switch the search off.' + (f' Lists read {read_note}.' if read_note else '')),
                how=f'Scale Insights web app, /Automation/Algo/BlacklistRule/Edit?asin={asin}: edit the lists, Update, re-read '
                    f'(references/scale-insights-playbook.md, "Blacklist rescue")')


def load_lists(path):
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    return {k: lines(data.get(k)) for k in LIST_KEYS} | {'_read': data.get('_read')}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--asin', required=True)
    ap.add_argument('--lists', required=True, help='si_blacklist.json')
    ap.add_argument('--run', help='run folder: adds its plan.json rank searches (consumer and business) and writes '
                                  'blacklist_rescue.json')
    ap.add_argument('--skill', default=os.path.dirname(HERE))
    ap.add_argument('--data', help='shared data folder holding asins/<ASIN>.json')
    a = ap.parse_args(argv)
    with open(os.path.join(a.skill, 'config.json'), encoding='utf-8') as fh:
        shared = json.load(fh)
    data = a.data or shared.get('data_dir') or os.path.join(a.skill, 'data')
    with open(os.path.join(data, 'asins', f'{a.asin}.json'), encoding='utf-8') as fh:
        cfg = json.load(fh)
    rank, business_rank = [], []
    if a.run and os.path.exists(os.path.join(a.run, 'plan.json')):
        with open(os.path.join(a.run, 'plan.json'), encoding='utf-8') as fh:
            planned = json.load(fh)
        rank = [t['term'] for t in planned.get('terms', []) if t.get('role') == 'Rank']
        business_rank = [t['term'] for t in planned.get('business_terms', []) if t.get('role') == 'Rank']
    lists = load_lists(a.lists)
    keep = (shared.get('scale_insights') or {}).get('blacklist_keep') or []
    result = rescue(invested_searches(cfg, rank, cfg.get('business_invest_log'), business_rank), lists, keep)
    out = dict(asin=a.asin, read=lists.get('_read'), **result, new_lists=new_lists(lists, result))
    if a.run:
        with open(os.path.join(a.run, 'blacklist_rescue.json'), 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=1, ensure_ascii=False)
    print(json.dumps({k: out[k] for k in ('asin', 'exact_remove', 'phrase_remove', 'whitelist_add', 'blocks')}, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
