"""Build a run's placement_inputs.json (references/placements.md, "Planner input") from three MarketplaceAdPros reads.

Since 2026-10-26 (decision 140) every run needs it: the product-page base bid (placement_shape.py) shapes a campaign only
from it, and a down-only row (placement_review.strategy_rows) goes to a person for any campaign whose product ads it does
not show. Two steps, from the skill folder:

    python scripts/placement_inputs.py sql --asin <ASIN> --as-of <SGT date>
        Prints the SQL for MAP run_report_sql (integration_ids [<amazon_ads.integration_id>], limit 1000) and the windows.
        Save the whole response to <run>/placement_report.json.
    python scripts/placement_inputs.py build --asin <ASIN> --run <run> --as-of <SGT date>
        Reads <run>/placement_report.json, <run>/campaigns.json (the run's usual read) and <run>/live_product_ads_p*.json
        (MAP list_resources sp_product_ads, filters {"campaign_id": "<id,id,...>", "max_results": 1000}, once per 100 ids
        of campaigns.json's enabled campaigns, every page), and writes <run>/placement_inputs.json.

It stops, writing nothing, when the report was truncated or is another product's, or when an enabled campaign of
campaigns.json has no product ad in the reads (`missing` lists them: read those and build again).
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys

import plan as planner

SGT = dt.timezone(dt.timedelta(hours=8))
SQL = """WITH own AS (
  SELECT campaignId FROM sponsored_products_product_ads
  WHERE date BETWEEN DATE '{start}' AND DATE '{end}' AND __amazon_profile_id = '{profile}'
  GROUP BY campaignId
  HAVING COUNT(DISTINCT advertisedAsin) = 1 AND MAX(advertisedAsin) = '{asin}'
)
SELECT CAST(p.campaignId AS VARCHAR) AS campaignId, MAX(p.campaignName) AS campaign_name,
  p.placementClassification AS placement,
{sums}
FROM sponsored_products_campaign_placements p JOIN own ON own.campaignId = p.campaignId
WHERE p.date BETWEEN DATE '{start}' AND DATE '{end}' AND p.__amazon_profile_id = '{profile}'
GROUP BY p.campaignId, p.placementClassification
ORDER BY campaignId, placement"""
FIELDS = (('clicks', 'p.clicks', False), ('orders', 'p.purchases14d', False), ('spend', 'p.cost', True),
          ('sales', 'p.sales14d', True))
SUFFIX = {'30d': '30', '90d': '90', 'recent': '_recent'}


def windows(as_of, lag):
    """{'30d', '90d', 'recent': [start, end]}: the mature windows end `lag` days before the SGT pull date, and the recent
    30 days end the day before it (placements.md, "Evidence and scope"; placement_review.recommend checks the same)."""
    day = dt.date.fromisoformat(as_of)
    end = day - dt.timedelta(days=lag)
    recent_end = day - dt.timedelta(days=1)
    return {'30d': [(end - dt.timedelta(days=29)).isoformat(), end.isoformat()],
            '90d': [(end - dt.timedelta(days=89)).isoformat(), end.isoformat()],
            'recent': [(recent_end - dt.timedelta(days=29)).isoformat(), recent_end.isoformat()]}


def sql(asin, as_of, cfg):
    w = windows(as_of, cfg['placement']['recommendations']['attribution_lag_days'])
    sums = []
    for window, suffix in SUFFIX.items():
        start, end = w[window]
        for name, column, money in FIELDS:
            expr = f"SUM(CASE WHEN p.date BETWEEN DATE '{start}' AND DATE '{end}' THEN {column} ELSE 0 END)"
            sums.append(f"  {f'ROUND({expr}, 2)' if money else expr} AS {name}{suffix}")
    return SQL.format(start=w['90d'][0], end=w['recent'][1], profile=cfg['amazon_ads']['profile'].split()[-1], asin=asin,
                      sums=',\n'.join(sums)), w


def report_rows(path):
    raw = planner.load_raw(path)
    if isinstance(raw, dict):
        if raw.get('truncated'):
            raise SystemExit(f'{path}: the report was truncated; run it again with limit 1000')
        if raw.get('status') not in (None, 'success'):
            raise SystemExit(f"{path}: the report did not succeed ({raw.get('status')})")
        return raw.get('data') or raw.get('rows') or []
    return raw if isinstance(raw, list) else []


def build(asin, run, as_of, cfg, now=None):
    """placement_inputs.json's content, or SystemExit with what is wrong."""
    _, w = sql(asin, as_of, cfg)
    report = os.path.join(run, 'placement_report.json')
    if not os.path.exists(report):
        raise SystemExit(f'{report} is missing: run the SQL from `placement_inputs.py sql` and save the response there')
    rows, seen = [], set()
    for r in report_rows(report):
        cid = str(r['campaignId'])   # exclusive to this product by the SQL's advertised-ASIN filter, not by name
        key = (cid, r['placement'])
        if key in seen:
            raise SystemExit(f'{report}: duplicate row for campaign {cid}, {r["placement"]}')
        seen.add(key)
        row = dict(asin=asin, campaignId=cid, campaign_name=r.get('campaign_name'), placement=r['placement'])
        for suffix in SUFFIX.values():
            for name, _, money in FIELDS:
                value = r.get(name + suffix) or 0
                row[name + suffix] = round(float(value), 2) if money else int(value)
        rows.append(row)
    camp_path = os.path.join(run, 'campaigns.json')
    if not os.path.exists(camp_path):
        raise SystemExit(f'{camp_path} is missing (data-pull.md, the campaigns read)')
    campaigns = [c for c in planner.load_items(camp_path) if asin in (c.get('name') or '')]
    live = {}
    ad_files = sorted(glob.glob(os.path.join(glob.escape(run), 'live_product_ads_p*.json')))
    for path in ad_files:
        for ad in planner.load_items(path):
            if (ad.get('state') or '').upper() == 'ARCHIVED' or not ad.get('asin'):
                continue
            live.setdefault(str(ad['campaignId']), set()).add(ad['asin'])
    enabled = [str(c['campaignId']) for c in campaigns if (c.get('state') or '').upper() == 'ENABLED']
    missing = [cid for cid in enabled if cid not in live]
    if missing:
        groups = [','.join(missing[i:i + 100]) for i in range(0, len(missing), 100)]
        raise SystemExit(json.dumps(dict(error='enabled campaigns with no product ad read', missing=missing,
                                         read_with='MAP list_resources sp_product_ads, filters {"campaign_id": "<group>", '
                                                   '"max_results": 1000}, every page; save as live_product_ads_pN.json',
                                         groups=groups), indent=1))
    now = now or dt.datetime.now(SGT)
    return dict(asin=asin, as_of=as_of, retrieved_at=now.isoformat(timespec='seconds'), complete=True, windows=w,
                campaigns=campaigns, live_asins={cid: sorted(asins) for cid, asins in sorted(live.items())}, rows=rows,
                source_files=['placement_report.json', 'campaigns.json'] + [os.path.basename(p) for p in ad_files],
                built_by='scripts/placement_inputs.py')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('sql', 'build'):
        p = sub.add_parser(name)
        p.add_argument('--asin', required=True)
        p.add_argument('--as-of', required=True, help='the SGT date of the pull, YYYY-MM-DD')
        if name == 'build':
            p.add_argument('--run', required=True)
    a = ap.parse_args(argv)
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json'), encoding='utf-8') as f:
        cfg = json.load(f)
    if a.cmd == 'sql':
        text, w = sql(a.asin, a.as_of, cfg)
        print(f"-- windows: 30d {w['30d'][0]}..{w['30d'][1]}, 90d {w['90d'][0]}..{w['90d'][1]}, "
              f"recent {w['recent'][0]}..{w['recent'][1]}")
        print(f"-- MAP run_report_sql, integration_ids [\"{cfg['amazon_ads']['integration_id']}\"], limit 1000")
        print(text)
        return 0
    data = build(a.asin, a.run, a.as_of, cfg)
    out = os.path.join(a.run, 'placement_inputs.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    print(f"{out}: {len(data['rows'])} placement rows, {len(data['campaigns'])} campaigns, "
          f"{len(data['live_asins'])} with product ads read")
    return 0


if __name__ == '__main__':
    sys.exit(main())
