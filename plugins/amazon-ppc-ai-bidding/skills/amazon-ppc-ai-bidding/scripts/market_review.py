"""Evidence gate for AI research before listing/price decisions reach humans."""
import copy
import datetime as dt
import math
import statistics
from urllib.parse import urlparse

import evidence

RELEVANCE = ('direct', 'adjacent', 'broad', 'mismatch', 'unknown')


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def amazon_url(value):
    parsed = urlparse(str(value or ''))
    return parsed.scheme == 'https' and parsed.hostname in ('amazon.com', 'www.amazon.com')


def sufficiently_sampled(term, thresholds):
    if term.get('index_basis') not in ('SQP', 'Search terms') or term.get('role') in ('Negate', 'Leave', 'Test'):
        return False
    if (term.get('sqp_total_clicks') or 0) < thresholds['trusted_min_clicks'] or not number(term.get('market_cvr')) or term['market_cvr'] <= 0:
        return False
    sqp = term['index_basis'] == 'SQP'
    clicks = term.get('sqp_our_clicks', 0) if sqp else term.get('ad_clicks', 0)
    orders = term.get('sqp_our_purchases', 0) if sqp else term.get('ad_orders', 0)
    return clicks >= thresholds['trusted_min_clicks'] or (not sqp and orders >= thresholds['trusted_min_ad_orders'])


def opportunities(plan, research, thresholds):
    judgments = {}
    for row in research.get('queries', []):
        query = row['query']
        if query in judgments or row.get('relevance') not in RELEVANCE:
            raise ValueError('Duplicate query or invalid relevance in market_review.json')
        if not row.get('reason') or not row.get('source'):
            raise ValueError('Relevance requires a product-fit reason and source')
        judgments[query] = row
    rows = []
    for term in plan.get('terms', []):
        if not sufficiently_sampled(term, thresholds):
            continue
        query = term['term']
        judgment = judgments.get(query, {})
        volume, days, index = term.get('sqp_volume'), term.get('observed_days'), term.get('index')
        monthly = evidence.monthly_searches(volume, days)
        score = evidence.opportunity(index, volume, days)
        relevance = judgment.get('relevance', 'unknown')
        rows.append(dict(query=query, relevance=relevance, relevance_reason=judgment.get('reason', 'AI product-fit assessment pending'),
                         relevance_source=judgment.get('source'), index=index, basis=term['index_basis'],
                         our_cvr=term.get('cvr_est'), market_cvr=term.get('market_cvr'),
                         clicks=term.get('sqp_our_clicks') if term['index_basis'] == 'SQP' else term.get('ad_clicks'),
                         purchases=term.get('sqp_our_purchases') if term['index_basis'] == 'SQP' else term.get('ad_orders'),
                         volume=volume, observed_days=days, monthly_searches=monthly,
                         opportunity=score if relevance in ('direct', 'adjacent') else None,
                         window=plan.get('terms_window', 'See dated run sources'),
                         source='Scale Insights SQP search volume; existing smoothed same-query conversion index'))
    return sorted(rows, key=lambda row: (RELEVANCE.index(row['relevance']), -(row['opportunity'] or 0), row['query']))


def normalize_offer(offer, date):
    row = copy.deepcopy(offer)
    price, count = row.get('effective_price'), row.get('pack_count')
    required = ('asin', 'title', 'unit', 'comparison', 'availability', 'discount_terms', 'rating_context')
    complete = (all(row.get(field) for field in required) and amazon_url(row.get('url')) and
                row.get('observed_on') == date and number(price) and price > 0 and number(count) and count > 0)
    row['complete'] = bool(complete)
    row['unit_price'] = price / count if complete else None
    return row


def assess(items, plan, product, shared, date, research=None):
    research = research or {}
    if any(row.get('asin') != product['asin'] for row in plan.get('summary', [])):
        raise ValueError('Plan and product ASIN mismatch')
    if research and (research.get('asin') != product['asin'] or research.get('as_of') != date):
        raise ValueError('Market research must match this ASIN and sweep date')
    dt.date.fromisoformat(date)
    rows = opportunities(plan, research, shared['thresholds'])
    own = normalize_offer(research.get('own_offer', {}), date)
    competitors = [normalize_offer(row, date) for row in research.get('competitors', [])]
    comparable = {row['asin']: row for row in competitors if row['complete'] and row.get('comparable') is True and
                  row['asin'] != product['asin'] and row.get('unit') == own.get('unit') and row['availability'] == 'in_stock'}
    selected = [row for relevance in ('direct', 'adjacent') for row in
                [entry for entry in rows if entry['relevance'] == relevance and entry['opportunity'] is not None][:3]]
    weak_direct = [row for row in rows if row['relevance'] == 'direct' and number(row['index']) and
                   row['index'] < shared['thresholds']['index_hold'] and
                   (row['clicks'] or 0) >= shared['thresholds']['trim_min_clicks']]
    selected.extend(row for row in weak_direct if row not in selected)
    searches = research.get('searches', [])
    comparable = {asin: row for asin, row in comparable.items() if row.get('query') in [entry['query'] for entry in selected]}
    median_unit = statistics.median(row['unit_price'] for row in comparable.values()) if comparable else None
    missing = []
    if not rows:
        missing.append('Sufficient same-query CVR evidence; thin samples are skipped, not scored.')
    if any(row['relevance'] == 'unknown' for row in rows):
        missing.append('Classify sampled queries by product fit, with reasons and sources.')
    # only a volume or day count we don't have is a gap; a search with SQP volume 0 is a reading, not missing data
    if any(row['relevance'] in ('direct', 'adjacent') and row['monthly_searches'] is None for row in rows):
        missing.append('Dated SQP search volume and observed days for relevant sampled queries.')
    if not selected:
        missing.append('Relevant, sufficiently sampled opportunity keywords to research.')
    for row in selected:
        if not any(search.get('query') == row['query'] and amazon_url(search.get('url')) and
                   search.get('observed_on') == date and search.get('findings') and search.get('result_mix')
                   for search in searches):
            missing.append('Read live Amazon.com results for: ' + row['query'])
    if not own['complete'] or own.get('asin') != product['asin']:
        missing.append('Dated own Amazon offer: effective price, pack, unit, availability, discounts and rating/review context.')
    if len(comparable) < 2:
        missing.append('At least two distinct, in-stock comparable Amazon offers with dated pack-normalized prices and comparison reasons.')
    assessment = research.get('assessment') or {}
    for field in ('rationale', 'counterevidence', 'recommendation', 'confidence'):
        if not assessment.get(field):
            missing.append('AI assessment: ' + field)
    conversion = assessment.get('conversion_verdict', 'insufficient')
    price = assessment.get('price_verdict', 'uncertain')
    if conversion not in ('listing_candidate', 'query_mismatch', 'mixed', 'insufficient'):
        raise ValueError('Unsupported conversion verdict')
    if price not in ('underpriced', 'overpriced', 'fair', 'uncertain'):
        raise ValueError('Unsupported price verdict')
    if assessment.get('confidence') not in (None, 'low', 'medium', 'high'):
        raise ValueError('Unsupported assessment confidence')
    if assessment.get('confidence') == 'low':
        missing.append('Resolve low-confidence evidence before escalating a recommendation.')
    if conversion == 'query_mismatch' and weak_direct:
        missing.append('Explain direct-fit conversion weakness; broad-query mismatch alone cannot dismiss it.')
    output = []
    for original in items:
        item = copy.deepcopy(original)
        if item.get('kind') in ('bid', 'growth'):
            # A run's Bids item holds the planner's own rows, and the For Growth item Growth's hand-over block (its
            # ai_review is human_ready from growth.build_item), not listing or price research, so none of this applies to
            # them. The price branch below would overwrite their ai_review, and main() runs every item of a plan through here.
            output.append(item)
            continue
        gaps = list(missing)
        if item['kind'] == 'listing':
            if conversion in ('listing_candidate', 'mixed') and not weak_direct:
                gaps.append('Direct-fit, sufficiently sampled conversion weakness; broad/adjacent queries alone do not diagnose the listing.')
            if conversion == 'insufficient':
                gaps.append('Complete the relevance-adjusted conversion assessment.')
            phase = 'monitor' if conversion == 'query_mismatch' else 'human_ready'
        else:
            if price == 'uncertain':
                gaps.append('Complete the comparative offer/price judgment; high CVR or ad losses alone do not prove underpricing.')
            phase = 'monitor' if price == 'fair' and item.get('price', {}).get('proposed') is None else 'human_ready'
        if gaps:
            phase = 'research'
        item['ai_review'] = dict(phase=phase, as_of=date, missing=gaps, assessment=assessment,
                                 opportunities=rows, searches=searches, own_offer=own, competitors=competitors,
                                 direct_weak_count=len(weak_direct), selected_queries=[row['query'] for row in selected],
                                 price_context=dict(comparable_count=len(comparable), median_unit_price=median_unit,
                                                    own_vs_median=own['unit_price'] / median_unit - 1 if own['complete'] and median_unit else None),
                                 note='IDX × 30-day-normalized SQP search volume ranks research opportunities within relevance tiers. Not forecast sales, profit or statistical significance. Broad-query weakness is not an ASIN-wide diagnosis.')
        output.append(item)
    return output


def main():
    import argparse
    import json
    import pathlib

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--product', required=True)
    parser.add_argument('--research')
    parser.add_argument('--date', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    read = lambda path: json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    plan, product = read(args.plan), read(args.product)
    shared = read(pathlib.Path(__file__).resolve().parents[1] / 'config.json')
    items = assess(plan.get('human_review', []), plan, product, shared, args.date, read(args.research) if args.research else None)
    from human_review import validate
    pathlib.Path(args.out).write_text(json.dumps(validate(items), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(asin=product['asin'], reviews=len(items), phases=[item['ai_review']['phase'] for item in items], live_writes=0)))


if __name__ == '__main__':
    main()
