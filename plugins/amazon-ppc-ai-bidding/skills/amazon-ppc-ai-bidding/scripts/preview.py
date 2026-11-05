#!/usr/bin/env python3
"""Build the approval page (self-contained HTML) from one or more plan.json files.

Usage:
  python preview.py --out <run>/preview.html <run>/plan.json [<other run>/plan.json ...]
                    [--title "Scenery PPC Plan"] [--eyebrow "..."] [--date 2026-10-24]

Publish the result with the Artifact tool (private by default) and wait for the user's approval.
Nothing in the page writes to Amazon. The page shows what would go out (C9): a bid the auto lane caps shows the cap it
writes, and a row the planner or a person's decision holds (payloads/held/) says it is not in this apply. Every row ends
its Why with its lane (E9): "Lane: applies automatically", "waits for a person" or "held", and " · past Kim's $600
level" on a promotion (and its bundle) past his monthly level. A business invest (and a business new exact keyword) says
its campaign's top of search and budget from and to (tos_change, budget_change), and a business re-rank row carries the
label "B2B" (rulebook 9). The review section shows decisions only (decision 97). The For Growth item is not a
decision: it gets one line in a For Growth part of its own, "For Growth: <pass> block produced (see the For Growth
tab)" when this run raised it, else "open (<status>) since <date>", instead of a tile.
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
from human_review import ACTIVE, for_people, validate as validate_human_review
from placement_review import preview_html as placement_preview_html

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(os.path.dirname(HERE), 'assets', 'preview_template.html')

RULES = [
    dict(role='Invest', which='Relevant searches that beat the market (index 1.1+ on 10+ of our SQP clicks, or the search-term report) with 150+ searches in 12 weeks and 3+ purchases',
         bid="Amazon's suggested median, or the search's breakeven if higher, never above Amazon's suggested high",
         rule="Its own exact campaign, $10 a day ($15 on the product's biggest invest search), top of search +50% (standing policy, Kim 2026-10-20; other placements reviewed separately). No Scale Insights bid rules; Optimum Hours dayparting",
         exit='Judged at months 3, 6, 9 and 12 on organic rank (Rank Radar) and organic purchases only: keep investing while either rises, otherwise back to Hold'),
    dict(role='Prove first', which='Searches that beat the market on fewer than 3 purchases', bid="Amazon's suggested median (or breakeven if higher)",
         rule='Its own exact campaign, $5 a day, top of search +30% (standing policy, Kim 2026-10-20)', exit='3 orders at index 1.1+ moves it to Invest; about 30 clicks with no order moves it to Trim'),
    dict(role='Hold', which='Searches converting at the market (index 0.8 to 1.1)', bid="Breakeven click: profit per order x the keyword's conversion; with 2+ orders on its search, Amazon's suggested mid instead (decision 177)",
         rule='Bid set weekly through Marketplace Ad Pros', exit='Re-scored every week'),
    dict(role='Trim', which='Searches trailing the market (index under 0.8) on 15+ clicks', bid='70% of breakeven; pause below index 0.5 on 30+ clicks',
         rule='Bid set weekly', exit='Back to Hold if the index recovers above 0.8'),
    dict(role='Test', which='Relevant searches with insufficient evidence or no same-query market benchmark', bid="Amazon's suggested mid in its launch test (until 2 expected orders at the product's ad conversion, 15 to 60 clicks; 3 with one order; decision 178) and once validated (2+ orders at index 0.8 or more; decision 177); otherwise an economic starting bid: market-CVR breakeven with the existing $0.35 floor",
         rule='Delivery review after 7 eligible days; separately bounded visibility test if justified', exit='Evidence, spend/loss limit or dated deadline; no automatic weekly restart'),
    dict(role='Discovery', which='Broad, phrase and auto keywords that find new searches',
         bid='Breakeven at the keyword\'s own conversion, capped at the product average until it has 3 orders, or 2 orders at a keyword index of 1.1+ against the ad conversion of the product', rule='Bid set weekly',
         exit='Searches that convert move into Invest or Hold'),
    dict(role='Harvest', which='Search terms with 1+ order at or above the product\'s breakeven conversion',
         bid="Starts at the harvest ad group's default bid: the median of Amazon's suggested medians for the product, floored at its breakeven click",
         rule='Scale Insights imports them as unique exact keywords into the harvest campaign ($5 a day)', exit='Priced by its role from the next weekly run'),
    dict(role='Negate', which='Irrelevant searches', bid='Negative phrase or exact', rule='Scale Insights blacklist, after you approve the list (negative-keyword audit)', exit='-'),
]


EVIDENCE_TYPES = ('New exact campaign', 'Reuse exact campaign', 'Business invest', 'New SB video campaign')  # their tables show no Why
HELD_TEXT = 'held: not in this apply'


def lane_text(change, shadow=True, kim_level=None):
    """E9 (M1): the row's lane in plain words, for the page Kim says his whole-run yes on: 'Lane: held' (a lock or the
    monitor lane: payloads/held/), 'Lane: applies automatically' (an enabled run's auto row; in shadow 'would apply
    automatically (shadow run)', since only this yes sends it), else 'Lane: waits for a person' (a row with no lane
    counts as one). A row past Kim's monthly level (past_kim_level) adds " · past Kim's $600 level" (his level
    from the plan's summary, or "his monthly level" when an older plan doesn't record it)."""
    if change.get('locked_until') or change.get('lane') == 'monitor':
        text = 'Lane: held'
    elif change.get('lane') == 'auto':
        text = 'Lane: would apply automatically (shadow run)' if shadow else 'Lane: applies automatically'
    else:
        text = 'Lane: waits for a person'
    if change.get('past_kim_level') is True:
        known = isinstance(kim_level, (int, float)) and not isinstance(kim_level, bool)
        text += f" · past Kim's ${kim_level:g} level" if known else " · past Kim's monthly level"
    return text


def is_business_invest(change):
    """A row that writes its B2B campaign's update (rulebook 9.5): a Business invest, or a business New exact keyword."""
    return change.get('type') == 'Business invest' or (change.get('type') == 'New exact keyword'
                                                      and change.get('owner_kind') == 'business')


NO_AD_GROUP = 'no payload: ad group unknown'


def campaign_change(change):
    """(top of search, budget) from and to, in words, for a business invest row (spec 4b: the first one on a B2B campaign
    cuts top of search for every keyword in it, so the approver sees the cut). The campaign-wide values plan.py stamps on
    every row of the campaign (campaign_tos, campaign_budget) against the live ones (tos_now, budget_now): '+100% → +50%',
    '$7 → $10/day'. A held placement and a campaign not read live say so, as the payload writes neither. A New exact
    keyword whose ad group is unknown writes nothing at all (plan.payload_entries), so it says that (final review M1)."""
    if change.get('type') == 'New exact keyword' and not change.get('ad_group_id'):
        return (NO_AD_GROUP,) * 2
    now, to = change.get('tos_now'), change.get('campaign_tos', change.get('tos'))
    live = f'+{now:g}%' if isinstance(now, (int, float)) else 'not read'
    if change.get('placement_hold') or not isinstance(to, (int, float)):
        tos = f'held as live ({live})'
    else:
        tos = f'{live} → +{to:g}%'
    b_now = change.get('budget_now')
    b_to = change['campaign_budget'] if 'campaign_budget' in change else change.get('budget')
    if isinstance(b_now, (int, float)) and isinstance(b_to, (int, float)):
        budget = f'${b_now:g} → ${b_to:g}/day'
    else:
        budget = 'not read live: left as it is'
    return tos, budget


def as_previewed(change, max_raise_pct=None, shadow=True, kim_level=None):
    """A plan row as the page shows it (C9, N7): what would go out. A copy; the plan row is not changed.

    A row the plan holds (locked_until, or the monitor lane: plan.write_outputs puts it in payloads/held/, never in
    review/) says "held: not in this apply". A bid the auto lane caps (new_capped: a shadow run's automatic raise, or a
    raise held back for the run's cap) shows the cap as its new bid, and says "$0.62 → $0.37 (the +25% cap; approving
    writes $0.37)", which is what review/ and an approval write. The words go first in the row's Why (Evidence for a
    promotion, whose table has no Why). Its lane goes last (lane_text, E9): `shadow` is the plan's (summary.shadow not
    exactly False) and `kim_level` its summary.kim_product_month."""
    c = dict(change)
    if is_business_invest(c):
        c['tos_change'], c['budget_change'] = campaign_change(c)
    notes = []
    if c.get('locked_until') or c.get('lane') == 'monitor':
        notes.append(HELD_TEXT)
    capped, new = c.get('new_capped'), c.get('new')
    if isinstance(capped, (int, float)) and isinstance(new, (int, float)) and capped != new:
        cap = f'the +{max_raise_pct:g}% cap' if isinstance(max_raise_pct, (int, float)) else 'the per-run cap'
        notes.append(f'${new:.2f} → ${capped:.2f} ({cap}; approving writes ${capped:.2f})')
        c['new'] = capped
        if isinstance(c.get('current'), (int, float)) and c['current']:
            c['change'] = round(capped / c['current'] - 1, 3)
    field = 'evidence' if c.get('type') in EVIDENCE_TYPES else 'why'
    if notes:
        c[field] = '. '.join(notes) + '.' + (f' {c[field]}' if c.get(field) else '')
    c[field] = (f'{c[field]} ' if c.get(field) else '') + lane_text(c, shadow, kim_level) + '.'
    return c


GROWTH_STATUS_WORDS = {'open': 'not picked up yet', 'in_progress': 'picked up', 'copy_pushed': 'copy pushed'}


def growth_line(product, item, raised=None):
    """R32: the For Growth item is not a Needs-human item, so the review section shows one line for it (its For Growth
    part) instead of a tile, and only while it is open (a closed one the plan carries says nothing). `raised` is the
    plan's summary[0].growth_trigger: when this run raised the item, "<pass> block produced"; an item it only carries
    says "open (<status>) since <opened_on>"."""
    if item['status'] not in ACTIVE:
        return ''
    if raised:
        said = f"{item['growth']['pass']} block produced"
    else:
        g = item.get('growth') or {}
        status = GROWTH_STATUS_WORDS.get(item['status'], str(item['status']).replace('_', ' '))
        said = f"open ({status}) since {g.get('opened_on') or item.get('first_seen') or 'a day not recorded'}"
    text = f'{product} · For Growth: {said} (see the For Growth tab)'
    return '<p class="note">' + html.escape(text) + '</p>'


def human_review_html(groups):
    """The review section: decisions only (decision 97). Items the AI is still researching or only monitors stay in the
    product file and are not shown; a decision is cut to what it needs (human_review.for_people).

    The For Growth item is not a decision (R32): for_people passes it whole, and here it gets no tile, only one line
    while it is open, in a For Growth part of its own after the decisions (growth_line); a closed one says nothing.
    groups: (product label, the plan's human_review, the plan's growth_trigger) per plan; a pair reads as no trigger."""
    buckets = {key: [] for key in ('human_ready', 'bid', 'history')}
    growth_lines = []
    for product, items, *raised in groups:
        for item in for_people(validate_human_review(items)):
            if item['kind'] == 'growth':
                growth_lines.append(growth_line(product, item, raised[0] if raised else None))
                continue
            key = ('history' if item['status'] in ('resolved', 'dismissed') else
                   'bid' if item['kind'] == 'bid' else 'human_ready')
            buckets[key].append((product, item))
    headings = {
        'human_ready': ('needs-human', 'Human decisions', 'Calls the AI cannot make on its own. Any price change requires Kim’s approval.'),
        'bid': ('bid-approvals', 'Bid approvals', 'Advertising changes parked for a person, kept apart from listing and price decisions.'),
        'history': ('review-history', 'Review history', 'Decisions already resolved or dismissed.'),
    }
    growth_part = ''.join(growth_lines)
    if growth_part:
        growth_part = ('<section id="for-growth"><h2>For Growth</h2><p class="note">Growth’s listing-pass work order, not '
                       'a decision: nothing here to approve.</p>' + growth_part + '</section>')
    parts = []
    for key, entries in buckets.items():
        if key == 'history':
            parts.append(growth_part)
        if not entries:
            continue
        section_id, title, note = headings[key]
        parts.append(f'<section id="{section_id}"><h2>{title}</h2><p class="note">{note}</p>')
        for product, item in entries:
            lines = [product, item['kind'].title() + ' review · ' + item['status'],
                     item['reason'], 'Next action: ' + item['action'],
                     'Source: ' + item['source'], 'Window: ' + item['window']]
            review = item['ai_review']
            assessment = review.get('assessment') or {}
            for field in ('conversion_verdict', 'price_verdict', 'rationale', 'counterevidence', 'recommendation', 'confidence'):
                if assessment.get(field):
                    lines.append(field.replace('_', ' ').title() + ': ' + assessment[field])
            for row in review.get('opportunities', []):
                lines.append(f"{row['query']}: {row['relevance']}; IDX {row['index']}; 30-day searches {row['monthly_searches']}; opportunity {row['opportunity']}. {row['relevance_reason']} · {row['source']} · {row['window']}")
            for offer in [review.get('own_offer') or {}, *review.get('competitors', [])]:
                if offer.get('asin'):
                    lines.append(f"Offer {offer['asin']}: USD {offer.get('effective_price')} / {offer.get('pack_count')} {offer.get('unit')}; unit price {offer.get('unit_price')}. {offer.get('comparison')} · {offer.get('observed_on')} · {offer.get('url')}")
            for row in item['evidence']:
                if isinstance(row, str):
                    lines.append(row)
                else:
                    values = {field: ('not available' if row.get(field) is None else format(row[field], '.2f' if field == 'index' else '.2%'))
                              for field in ('our_cvr', 'market_cvr', 'index')}
                    lines.append(f"{row.get('query', row.get('label', 'Evidence'))}: our CVR {values['our_cvr']}, market CVR {values['market_cvr']}, index {values['index']}; {row.get('purchases')} purchases / {row.get('clicks')} clicks. {row.get('basis', '')}. {row.get('note', '')}")
            price = item.get('price') or {}
            if item['kind'] == 'price':
                if price.get('proposed') is None:
                    lines.append('No price amount proposed. Direction to investigate: ' + price.get('direction', 'review'))
                else:
                    lines += [f"Price: USD {price['current']:.2f} to USD {price['proposed']:.2f}; contribution before ads: USD {price['profit_per_unit_current']:.2f} to USD {price['profit_per_unit_proposed']:.2f}.",
                              f"Economics as of {price['economics_as_of']}: {price['economics_source']}",
                              'Comparable packs: ' + price['comparison_source'],
                              f"Review on {price['review_on']}. Rollback: {price['rollback']}"]
            parts.append('<article class="tile"><h3>' + html.escape(item['title']) + '</h3>' +
                         ''.join('<p>' + html.escape(line) + '</p>' for line in lines) + '</article>')
        parts.append('</section>')
    return ''.join(parts)


def visibility_review_html(groups):
    if not groups:
        return ''
    parts = ['<section id="visibility"><h2>Visibility and fair testing</h2>',
             '<p class="note">Policy approved October 19, 2026. These are diagnostics and proposed experiments, not applied bids. '
             'A concrete bid, effective-bid ceiling, spend/loss allowance and end date still need review before execution. '
             'Suggested bids are not paid CPC or a visibility guarantee.</p>']
    for product, review in groups:
        parts.append('<h3>' + html.escape(product) + '</h3>')
        parts.append('<p>' + html.escape('; '.join(f'{key}: {value}' for key, value in review.get('counts', {}).items())) + '</p>')
        if review.get('retained_rank_searches'):
            parts.append('<p>Existing rank investments retained for review under their original controls, excluded from new-investment forecasts: ' +
                         html.escape(', '.join(review['retained_rank_searches'])) + '.</p>')
        parts.append('<details><summary>Per-keyword delivery evidence and proposed next action</summary>')
        parts.append('<table><thead><tr><th>Keyword / role</th><th>Delivery</th><th>Amazon range</th><th>Next action</th></tr></thead><tbody>')
        for row in review.get('rows', []):
            suggestion = row.get('recommendation') or row.get('suggested') or {}
            band = ' / '.join(f'${suggestion[key]:.2f}' for key in ('low', 'median', 'high')) if all(isinstance(suggestion.get(key), (int, float)) for key in ('low', 'median', 'high')) else 'Missing contextual recommendation'
            proposal = row.get('proposal')
            details = '<details><summary>Experiment boundaries</summary><pre>' + html.escape(json.dumps(proposal, indent=2, ensure_ascii=False)) + '</pre></details>' if proposal else ''
            metrics = row.get('metrics') or {}
            sample = '; '.join(f'{metrics[field]:g} {label}' for field, label in (('impressions', 'impressions'), ('clicks', 'clicks'), ('orders', 'orders'), ('eligible_days', 'eligible days')) if isinstance(metrics.get(field), (int, float)))
            evidence = '<br>' + html.escape(sample) if sample else '<br>Delivery sample not verified'
            parts.append('<tr><td>' + html.escape(f'{row.get("keyword", "")} · {row.get("match", "")} · {row.get("role", "")}') +
                         '</td><td>' + html.escape(str(row.get('delivery_state') or row.get('status', 'Unknown'))) + evidence +
                         '</td><td>' + html.escape(band) + '</td><td>' + html.escape(row.get('reason', 'Review saved evidence')) + details + '</td></tr>')
        parts.append('</tbody></table></details>')
    return ''.join(parts) + '</section>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('plans', nargs='+')
    ap.add_argument('--out', required=True)
    ap.add_argument('--title')
    ap.add_argument('--eyebrow', default='YourBrand · Amazon US · AI-managed PPC')
    ap.add_argument('--date', default=dt.date.today().isoformat())
    a = ap.parse_args()
    data = dict(summary=[], changes=[], rerank=[], rules=RULES, notes=[])
    names, reviews, placement_previews, visibility_reviews = [], [], [], []
    for p in a.plans:
        with open(p, encoding='utf-8') as fh:
            d = json.load(fh)
        if d.get('visibility_review'):
            visibility_reviews.append((d['summary'][0]['product'], d['visibility_review']))
        if d.get('placement_review'):
            placement_previews.append('<h2>' + html.escape(d['summary'][0]['product']) + '</h2>' + placement_preview_html(d['placement_review']))
        if d.get('human_review'):
            product = d['summary'][0]
            reviews.append((product['product'] + ' · ' + product['asin'], d['human_review'], product.get('growth_trigger')))
        for s in d['summary']:
            s['harvest_default_bid'] = (d.get('harvest') or {}).get('default_bid')
            names.append(s['product'])
            inp = s.get('inputs', {})
            data['notes'].append(f"{s['product']} ({s['asin']}), {s.get('mode')} run {s.get('run')}: SQP {inp.get('sqp')} searches, "
                                 f"{inp.get('search_terms')} search-term rows and {inp.get('keywords')} keywords (90 days), {inp.get('suggested')} searches priced by Amazon, "
                                 f"{inp.get('campaigns')} live campaigns read, {inp.get('recent')} recent keyword rows swept. Profit per order ${s.get('profit_per_unit')}.")
            sbv = s.get('sb_video') or {}
            if sbv:
                data['notes'].append(f"{s['product']}, Sponsored Brands video: {sbv.get('status')}. {sbv.get('new_keywords', 0)} invest searches get an exact "
                                     f"video keyword in {sbv.get('new_campaigns', 0)} new campaign(s) (next number {sbv.get('next_exact_n')}, ${sbv.get('budget')}/day each); "
                                     f"{sbv.get('pauses', 0)} older copies paused; {sbv.get('bid_changes', 0)} bids repriced. "
                                     f"{sbv.get('legacy_video_campaigns', 0)} older video campaigns are left as they are "
                                     f"({sbv.get('legacy_bid_optimisation_on', 0)} with Amazon's bid optimisation on).")
            if s.get('negatives_skipped'):
                data['notes'].append(f"{s['product']}: {s['negatives_skipped']} funnel negatives skipped because they would sit inside another exact campaign as a close variant of its own keyword.")
            # the data stage when it is not mature (data-stage design 4.1 and 4.6, 2026-10-22): a Rank row's why already carries
            # its basis, volume source and flag (plan.py evidence_of); this says what the stage holds back, and a volatile week
            stage_now = s.get('stage') or {}
            if stage_now and stage_now.get('stage') != 'mature':
                note = (f"{s['product']}: data stage {stage_now.get('stage')} ({stage_now.get('observed_days')} observed days, "
                        f"{stage_now.get('trusted_queries')} trusted queries, {stage_now.get('sqp_queries')} SQP queries with impressions)")
                if s.get('volatile_week'):   # the text already starts with "volatile SQP week" (fix round 1, 2026-10-22)
                    note += f"; {s['volatile_week']}"
                data['notes'].append(note)
        data['summary'] += d['summary']
        first = d['summary'][0] if d.get('summary') else {}
        data['changes'] += [as_previewed(c, first.get('max_raise_pct'), first.get('shadow') is not False,
                                         first.get('kim_product_month')) for c in d['changes']]
        # a business invest's re-rank row sits next to the consumer one of the same search: the label tells them apart
        data['rerank'] += [dict(r, label='B2B') if r.get('owner_kind') == 'business' else r for r in d['rerank']]
    data['notes'] += [
        'Expected spend comes from SQP click volumes and the planned bids. Actual spend depends on the auction; the 24-hour check after applying is where we see it.',
        "Audience (AMC / low-bid) campaigns are left alone. Amazon Business (B2B) campaigns are priced on their own conversion, and business rows follow the same lanes as consumer rows, judged on the B2B keyword's own evidence (rulebook 9). Business invests happen inside the team's B2B campaigns: the keyword's bid and its campaign's budget and top of search change together, and the planner never creates a B2B campaign. Sponsored Products ASIN and category targets are priced by rulebook section 2b; auto-targeting groups and Sponsored Display are not changed by this plan. In Sponsored Brands only video keywords for invest searches change (new, repriced, or older copies paused).",
        'Every change goes through Marketplace Ad Pros in this order, only after approval. Scale Insights assignments are done in its web app.',
    ]
    title = a.title or (' + '.join(dict.fromkeys(names)) + ' PPC Plan')
    lede = (f"Every change the plan would make, in launch order. Bids, budgets, campaigns and negatives go through Marketplace Ad Pros "
            f"after your approval. Data pulled {a.date}.")
    with open(TEMPLATE, encoding='utf-8') as fh:
        page = fh.read()
    page = page.replace('</header>', '</header>' + human_review_html(reviews), 1)
    page = page.replace('</header>', '</header>' + ''.join(placement_previews), 1)
    page = page.replace('</header>', '</header>' + visibility_review_html(visibility_reviews), 1)
    for k, v in (('__TITLE__', title), ('__EYEBROW__', a.eyebrow), ('__H1__', title), ('__LEDE__', lede)):
        assert page.count(k) >= 1, k
        page = page.replace(k, html.escape(v))
    assert page.count('/*__DATA__*/null') == 1
    page = page.replace('/*__DATA__*/null', json.dumps(data, ensure_ascii=False, separators=(',', ':'), default=str).replace('</', '<\\/'))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as fh:
        fh.write(page)
    msg = dict(out=a.out, bytes=len(page.encode('utf-8')), products=names, changes=len(data['changes']))
    node = shutil.which('node')
    if node:
        js = re.findall(r'<script>(.*?)</script>', page, re.S)[0]
        chk = os.path.join(os.path.dirname(os.path.abspath(a.out)), '_preview_check.js')
        with open(chk, 'w', encoding='utf-8') as fh:
            fh.write(js)
        r = subprocess.run([node, '--check', chk], capture_output=True, text=True)
        msg['js_check'] = 'ok' if r.returncode == 0 else r.stderr[:400]
        os.remove(chk)
    print(json.dumps(msg, indent=1))


if __name__ == '__main__':
    sys.exit(main())
