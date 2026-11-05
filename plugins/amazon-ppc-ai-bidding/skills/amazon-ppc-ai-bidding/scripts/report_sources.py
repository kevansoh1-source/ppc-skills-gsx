"""The run's report inputs from SoldScope and MarketplaceAdPros instead of the Scale Insights MCP (Kim, 2026-11-04: "use
soldscope instead of Scaleinsights so we can save the usage").

The planner reads Scale Insights' shapes (sqp_p*.json {Queries, Meta}, st_p*.json, kw_p*.json, pt_p*.json {data: [...]}). This
script writes those same files from:
  SQP            SoldScope search_query_performance_export (weeks, grouped by keyword), the same Amazon Brand Analytics data
  search terms   MAP run_report_sql over sponsored_products_search_terms and sponsored_brands_search_terms
  keywords and   MAP run_report_sql over sponsored_products_keywords (it holds the keywords and, as TARGETING_EXPRESSION rows,
  targets        the product, category and auto targets)
Checked on 2026-11-04: B0SAMP0017's three costliest keywords, Oct 1 to 28, read the same clicks, spend, impressions, orders
and sales from MAP (purchases7d, sales7d) as from Scale Insights' keyword report.

Sponsored Display targets (sd_targets), sales_daily.json and product costs still come from Scale Insights (data-pull.md).

Commands (paths relative to the skill folder):
  python scripts/report_sources.py weeks --through 2026-10-31 [--weeks 13]
      the SoldScope `periods` list: the Saturdays (week ends) of the window, newest last
  python scripts/report_sources.py sql --asin B0... --kind kw|st|sb_st --end 2026-11-03 [--days 90] [--campaign-ids 1,2]
      the MAP SQL to run with run_report_sql, limit 1000; run it again with --offset 1000, 2000 ... while it is truncated
  python scripts/report_sources.py sqp --asin B0... --run <run> <soldscope export file> [--last-season]
      writes sqp_p1.json (or last_season_sqp_p1.json)
  python scripts/report_sources.py ads --asin B0... --run <run> --kw <MAP kw pages...> --st <MAP st pages...> [--sb-st <pages...>]
      writes kw_p1.json, pt_p1.json and st_p1.json
Save every raw response first, under names the planner does not read: soldscope_sqp_raw*.json, map_kw_raw_p*.json,
map_st_raw_p*.json, map_sb_st_raw_p*.json.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

US_PROFILE = '9000000000000003'   # MAP's US profile (AGENTS.md key IDs): the SQL keeps this account's rows only
OBJECT = '￼'                  # SoldScope keys sometimes carry U+FFFC; removing it can leave duplicates, which are merged
AUTO = {'close-match', 'loose-match', 'substitutes', 'complements'}
TARGETING = ('TARGETING_EXPRESSION', 'TARGETING_EXPRESSION_PREDEFINED')
SQP_COUNTS = ('QueryVolume', 'TotalImpressions', 'AsinImpressions', 'TotalClicks', 'AsinClicks', 'TotalPurchase', 'AsinPurchase')
SOLDSCOPE = dict(QueryVolume='queryVolume', TotalImpressions='marketImpressionCount', AsinImpressions='myImpressionCount',
                 TotalClicks='marketClickCount', AsinClicks='myClickCount', TotalPurchase='marketPurchaseCount',
                 AsinPurchase='myPurchaseCount')


def unwrap(raw):
    """A saved response: plain JSON, an MCP text-block list or a content envelope; returns the JSON object inside."""
    if isinstance(raw, dict) and isinstance(raw.get('content'), list):
        raw = raw['content']
    if isinstance(raw, list) and raw and isinstance(raw[0], dict) and 'text' in raw[0]:
        text = ''.join(b.get('text', '') for b in raw if isinstance(b, dict))
        raw = json.JSONDecoder().raw_decode(text.strip())[0]
    return raw


def load(path):
    with open(path, encoding='utf-8') as fh:
        text = fh.read().strip()
    try:
        return unwrap(json.loads(text))
    except json.JSONDecodeError:
        return unwrap(json.JSONDecoder().raw_decode(text)[0])   # a response followed by an account_context object


def rows_of(path):
    t = load(path)
    rows = t.get('data') if isinstance(t, dict) else t
    if not isinstance(rows, list):
        raise SystemExit(f'{path}: no data rows (is it a saved run_report_sql or SoldScope export response?)')
    if isinstance(t, dict) and t.get('truncated'):
        print(f'note: {os.path.basename(path)} says truncated: read the next page (--offset) too', file=sys.stderr)
    return rows


def weeks(through, n=13):
    """The n Saturdays ending at `through` (a Saturday, the last complete SQP week), oldest first."""
    end = dt.date.fromisoformat(through)
    if end.weekday() != 5:
        raise SystemExit(f'{through} is not a Saturday: SoldScope weeks end on Saturdays')
    return [(end - dt.timedelta(weeks=i)).isoformat() for i in range(n - 1, -1, -1)]


def sqp(rows, asin, periods=None):
    """SoldScope rows (grouped by keyword) as Scale Insights' get_search_query_data {Queries, Meta}. QueryObservedDayCount
    is the number of weeks the query showed in x 7; data_through is the newest week end seen."""
    merged, seen = {}, []
    for r in rows:
        key = re.sub(r'\s+', ' ', str(r.get('key') or '').replace(OBJECT, '')).strip().lower()
        if not key:
            continue
        q = merged.setdefault(key, dict(Query=key, ASIN=asin, **{k: 0 for k in SQP_COUNTS}, _periods=set()))
        for ours, theirs in SOLDSCOPE.items():
            q[ours] += r.get(theirs) or 0
        q['_periods'] |= set(r.get('dataPeriods') or [])
        seen += list(r.get('dataPeriods') or [])
    queries = []
    for q in merged.values():
        days = 7 * len(q.pop('_periods')) or None
        q['QueryObservedDayCount'] = days
        q['MarketCVR'] = round(100 * q['TotalPurchase'] / q['TotalClicks'], 2) if q['TotalClicks'] else 0
        q['AsinCVR'] = round(100 * q['AsinPurchase'] / q['AsinClicks'], 2) if q['AsinClicks'] else 0
        queries.append(q)
    queries.sort(key=lambda q: -q['QueryVolume'])
    through = max(seen) if seen else (max(periods) if periods else None)
    return dict(Queries=queries, Meta=dict(data_through=through, total=len(queries), source='SoldScope search_query_performance_export',
                                           periods=sorted(set(seen)) or periods))


def window(end, days=90):
    e = dt.date.fromisoformat(end)
    return (e - dt.timedelta(days=days - 1)).isoformat(), e.isoformat()


def scope(asin, campaign_ids):
    ids = ','.join(str(int(c)) for c in campaign_ids or [] if str(c).strip().isdigit())
    name = f"campaignName LIKE '%{asin}%'"
    return f'({name} OR campaignId IN ({ids}))' if ids else name


def sql(kind, asin, end, days=90, campaign_ids=None, offset=0):
    """The run_report_sql text for one page (limit 1000) of the keyword (kw), Sponsored Products search-term (st) or
    Sponsored Brands search-term (sb_st) report: the product's campaigns (its ASIN in the name, or the ids given), the
    `days` US days to `end` (the marketplace's yesterday), the US profile only."""
    if not re.fullmatch(r'B0[A-Z0-9]{8}', asin):
        raise SystemExit(f'{asin} is not an ASIN')
    start, stop = window(end, days)
    where = (f"WHERE __amazon_profile_id = '{US_PROFILE}' AND date BETWEEN DATE '{start}' AND DATE '{stop}' "
             f"AND {scope(asin, campaign_ids)}")
    page = f'LIMIT 1000 OFFSET {int(offset)}'
    if kind == 'kw':
        return ('SELECT keywordId AS keyword_id, any_value(keyword) AS keyword, any_value(matchType) AS match_type, '
                'any_value(keywordType) AS keyword_type, any_value(targeting) AS targeting, campaignId AS campaign_id, '
                'any_value(campaignName) AS campaign_name, adGroupId AS ad_group_id, any_value(adGroupName) AS ad_group_name, '
                'arg_max(keywordBid, date) AS bid, SUM(clicks) AS clicks, SUM(impressions) AS impressions, SUM(cost) AS spend, '
                'SUM(purchases7d) AS orders, SUM(sales7d) AS sales FROM sponsored_products_keywords '
                f'{where} GROUP BY keywordId, campaignId, adGroupId ORDER BY spend DESC, keyword_id {page}')
    if kind == 'st':
        return ('SELECT searchTerm AS search_term, keywordId AS keyword_id, any_value(keyword) AS keyword, '
                'any_value(matchType) AS match_type, any_value(keywordType) AS keyword_type, any_value(targeting) AS targeting, '
                'campaignId AS campaign_id, any_value(campaignName) AS campaign_name, adGroupId AS ad_group_id, '
                'any_value(adGroupName) AS ad_group_name, SUM(clicks) AS clicks, SUM(impressions) AS impressions, '
                'SUM(cost) AS spend, SUM(purchases7d) AS orders, SUM(sales7d) AS sales FROM sponsored_products_search_terms '
                f'{where} GROUP BY searchTerm, keywordId, campaignId, adGroupId ORDER BY spend DESC, search_term, keyword_id {page}')
    if kind == 'sb_st':
        return ('SELECT searchTerm AS search_term, keywordId AS keyword_id, any_value(keywordText) AS keyword, '
                'any_value(matchType) AS match_type, campaignId AS campaign_id, any_value(campaignName) AS campaign_name, '
                'adGroupId AS ad_group_id, any_value(adGroupName) AS ad_group_name, SUM(clicks) AS clicks, '
                'SUM(impressions) AS impressions, SUM(cost) AS spend, SUM(purchases) AS orders, SUM(sales) AS sales '
                f'FROM sponsored_brands_search_terms {where} GROUP BY searchTerm, keywordId, campaignId, adGroupId '
                f'ORDER BY spend DESC, search_term, keyword_id {page}')
    raise SystemExit(f'unknown kind {kind}: kw, st or sb_st')


def _ids(r):
    return dict(CampaignId=str(r.get('campaign_id') or ''), CampaignName=r.get('campaign_name') or '',
                AdGroupId=str(r.get('ad_group_id') or ''), AdGroupName=r.get('ad_group_name') or '')


def _metrics(r):
    return dict(Clicks=int(r.get('clicks') or 0), Impressions=int(r.get('impressions') or 0),
                Spend=round(float(r.get('spend') or 0), 2), Orders=int(r.get('orders') or 0),
                Sales=round(float(r.get('sales') or 0), 2))


def target_type(text):
    t = (text or '').strip().lower()
    if t in AUTO:
        return 'auto'
    if t.startswith('category='):
        return 'category'
    return 'product'


def keywords_and_targets(rows):
    """MAP keyword-report rows as Scale Insights' keyword rows (kw) and target rows (pt). A TARGETING_EXPRESSION row is a
    target: its keywordId is the target id (the MAP report notes)."""
    kw, pt = [], []
    for r in rows:
        kid = str(r.get('keyword_id') or '')
        if not kid:
            continue
        bid = r.get('bid')
        if (r.get('keyword_type') or '').upper() in TARGETING:
            text = (r.get('targeting') or r.get('keyword') or '').strip()
            pt.append(dict(TargetId=kid, TargetText=text, TargetType=target_type(text), AdType='SP',
                           Bid=None if bid is None else round(float(bid), 2), **_ids(r), **_metrics(r)))
        else:
            kw.append(dict(KeywordId=kid, Keyword=r.get('keyword') or '', MatchType=(r.get('match_type') or '').lower(),
                           AdType='SP', Bid=None if bid is None else round(float(bid), 2), **_ids(r), **_metrics(r)))
    return kw, pt


def search_terms(rows, ad_type='SP'):
    out = []
    for r in rows:
        term = r.get('search_term')
        if not term:
            continue
        row = dict(SearchTerm=term, Keyword=r.get('keyword') or r.get('targeting') or '',
                   MatchType=(r.get('match_type') or '').lower(), AdType=ad_type, **_ids(r), **_metrics(r))
        if ad_type == 'SP' and (r.get('keyword_type') or '').upper() in TARGETING:
            row['TargetId'] = str(r.get('keyword_id') or '')
        else:
            row['KeywordId'] = str(r.get('keyword_id') or '')
        out.append(row)
    return out


def write(path, obj):
    if os.path.exists(path):
        raise SystemExit(f'{path} exists: a Scale Insights page or an earlier conversion. Move it out of the run folder first; '
                         'two sources for one report would be read twice')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    w = sub.add_parser('weeks'); w.add_argument('--through', required=True); w.add_argument('--weeks', type=int, default=13)
    s = sub.add_parser('sql')
    s.add_argument('--asin', required=True); s.add_argument('--kind', required=True, choices=('kw', 'st', 'sb_st'))
    s.add_argument('--end', required=True); s.add_argument('--days', type=int, default=90)
    s.add_argument('--campaign-ids', default=''); s.add_argument('--offset', type=int, default=0)
    q = sub.add_parser('sqp')
    q.add_argument('--asin', required=True); q.add_argument('--run', required=True); q.add_argument('files', nargs='+')
    q.add_argument('--last-season', action='store_true')
    a = sub.add_parser('ads')
    a.add_argument('--asin', required=True); a.add_argument('--run', required=True)
    a.add_argument('--kw', nargs='+', required=True); a.add_argument('--st', nargs='+', required=True)
    a.add_argument('--sb-st', nargs='*', default=[])
    o = ap.parse_args(argv)
    if o.cmd == 'weeks':
        print(json.dumps(weeks(o.through, o.weeks)))
    elif o.cmd == 'sql':
        print(sql(o.kind, o.asin, o.end, o.days, [c for c in o.campaign_ids.split(',') if c], o.offset))
    elif o.cmd == 'sqp':
        out = sqp([r for f in o.files for r in rows_of(f)], o.asin)
        name = 'last_season_sqp_p1.json' if o.last_season else 'sqp_p1.json'
        write(os.path.join(o.run, name), out)
        print(f"{name}: {len(out['Queries'])} queries, data through {out['Meta']['data_through']} (SoldScope)")
    else:
        kw, pt = keywords_and_targets([r for f in o.kw for r in rows_of(f)])
        st = search_terms([r for f in o.st for r in rows_of(f)]) + search_terms([r for f in o.sb_st for r in rows_of(f)], 'SB')
        for name, rows in (('kw_p1.json', kw), ('pt_p1.json', pt), ('st_p1.json', st)):
            write(os.path.join(o.run, name), dict(data=rows, Meta=dict(source='MarketplaceAdPros run_report_sql', rows=len(rows))))
        print(f'kw_p1.json {len(kw)} keywords, pt_p1.json {len(pt)} targets, st_p1.json {len(st)} search-term rows (MAP)')


if __name__ == '__main__':
    main()
