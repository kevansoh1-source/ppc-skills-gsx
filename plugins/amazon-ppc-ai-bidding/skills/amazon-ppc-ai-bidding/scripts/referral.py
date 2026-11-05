"""The referral fee Amazon actually charges, read from the settlement report on every run (Kim, 2026-10-29, decision 169:
"yes, auto-read the referral fee").

Amazon's list rate for these products is 15% (Office Products, the Fee Preview report), but the settlement report has shown
10% and 5% on real orders: a reduction that can end. The product's profit follows what Amazon deducts, so each run reads the
last `referral.window_days` (14) of settled Order rows for the SKU on Amazon.com (MAP run_report_sql over sp_settlement,
references/data-pull.md "Referral fee") and takes commission / principal. With at least `referral.min_units` (10) units
settled it becomes the product's rate: profit_per_unit moves by (old rate - new rate) x price and the product file's
referral_override block records the rate, its window and its unit count. Fewer units keep the stored rate (the block's,
else the one Scale Insights' UnitProfit carries). A missing read stops the run with need_settlement.json naming it.

Every rate here is in percentage points (15 = 15%). Scale Insights' ReferralPercent comes as a fraction (0.15 = 15%), and
until 2026-10-31 it was taken as 0.15%: a product's first settled read moved its profit by (0.15 - 15)/100 x price
(B0SAMP0029 USD 2.37 -> 1.19, B0SAMP0030 USD 3.28 -> 1.94 on 2026-10-30). as_pct reads any rate of 1 or under as a
fraction (Kim, 2026-10-31); no referral fee is 1% or under."""
import datetime as dt
import json
import os

FILE = 'settlement.json'
NEED = 'need_settlement.json'
METADATA = 'product_metadata.json'
DECISION = 169


def settings(shared):
    r = (shared or {}).get('referral') or {}
    return dict(enabled=bool(r.get('auto')), window_days=int(r.get('window_days') or 14),
                min_units=float(r.get('min_units') or 10), marketplace=r.get('marketplace') or 'Amazon.com')


def window_start(today_iso, days):
    return (dt.date.fromisoformat(today_iso) - dt.timedelta(days=days)).isoformat()


def sql(sku, since, marketplace='Amazon.com'):
    """The read data-pull.md names: one row for the SKU, its settled Order rows posted on or after `since` (SGT midnight)."""
    # MAP's sp_settlement is one row per amount (amount-type / amount-description / amount) since Amazon retired the old
    # settlement file (Nov 2026); posted-date is now a plain date and posted-date-time the timestamp. Checked 2026-11-04:
    # YourBrand_436 from 2026-10-21, 61 units, commission 80.33 on principal 536.97 = 14.96%.
    return ("WITH items AS (SELECT sku, \"order-item-code\" AS order_item, MIN(\"posted-date-time\") AS posted, "
            "SUM(CASE WHEN \"amount-type\"='ItemPrice' AND \"amount-description\"='Principal' "
            "THEN TRY_CAST(\"amount\" AS DOUBLE) ELSE 0 END) AS principal, "
            "SUM(CASE WHEN \"amount-type\"='ItemFees' AND \"amount-description\"='Commission' "
            "THEN TRY_CAST(\"amount\" AS DOUBLE) ELSE 0 END) AS commission, "
            "MAX(TRY_CAST(\"quantity-purchased\" AS DOUBLE)) AS units FROM sp_settlement "
            f"WHERE \"transaction-type\"='Order' AND \"marketplace-name\"='{marketplace}' AND sku='{sku}' "
            f"AND CAST(\"posted-date-time\" AS TIMESTAMPTZ) >= TIMESTAMPTZ '{since} 00:00:00+08' GROUP BY 1, 2) "
            f"SELECT sku, '{since}' AS window_from, COUNT(*) AS order_items, SUM(units) AS units, SUM(principal) AS principal, "
            "SUM(commission) AS commission, MIN(posted) AS first_posted, MAX(posted) AS last_posted FROM items "
            "WHERE principal > 0 GROUP BY sku")


def _rows(data):
    """The rows of a saved read in any shape: MAP's {"data": [...]}, the [{"type": "text", "text": "<json>"}] wrapper, a list."""
    if isinstance(data, dict):
        for key in ('structuredContent', 'content', 'data', 'rows', 'items'):
            if key in data:
                return _rows(data[key])
        return [data] if 'sku' in data else []
    if isinstance(data, list):
        out = []
        for r in data:
            if isinstance(r, dict) and r.get('type') == 'text' and isinstance(r.get('text'), str):
                try:
                    out += _rows(json.loads(r['text']))
                except ValueError:
                    continue
            elif isinstance(r, (dict, list)):
                out += _rows(r)
        return out
    return []


def as_pct(x):
    """A referral rate in percentage points: a fraction (0 < x <= 1, Scale Insights' 0.15) times 100, a percentage as is."""
    if x is None:
        return None
    x = float(x)
    return round(x * 100, 4) if 0 < x <= 1 else x


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def measure(rows, sku, since):
    """{pct, units, order_items, principal, commission, window_from, last_posted} over the SKU's rows of the window.
    A read of another window (window_from earlier than `since` by more than a day, or later) counts as not read: None."""
    mine = [r for r in rows if str(r.get('sku')) == str(sku)]
    froms = {str(r.get('window_from'))[:10] for r in mine if r.get('window_from')}
    if froms and any(abs((dt.date.fromisoformat(f) - dt.date.fromisoformat(since)).days) > 1 for f in froms):
        return None
    principal = sum(_num(r.get('principal')) for r in mine)
    commission = -sum(_num(r.get('commission')) for r in mine)
    units = sum(_num(r.get('units')) for r in mine)
    items = sum(_num(r.get('order_items') or 1) for r in mine)
    return dict(pct=round(commission / principal * 100, 2) if principal > 0 else None, units=units, order_items=items,
                principal=round(principal, 2), commission=round(commission, 2), window_from=since,
                last_posted=max((str(r.get('last_posted') or r.get('posted') or '') for r in mine), default='') or None)


def si_pct(run, asin):
    """Scale Insights' ReferralPercent for the ASIN from <run>/product_metadata.json (get_product_metadata), or None."""
    path = os.path.join(run, METADATA)
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    stack = [data]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if str(o.get('ASIN') or o.get('asin') or asin) == asin:
                for k, v in o.items():
                    if k.lower().replace('_', '') == 'referralpercent' and isinstance(v, (int, float)):
                        return as_pct(v)
            stack += [v for v in o.values() if isinstance(v, (dict, list, str))]
        elif isinstance(o, list):
            stack += o
        elif isinstance(o, str) and o.lstrip().startswith(('{', '[')):
            try:
                stack.append(json.loads(o))
            except ValueError:
                pass
    return None


def need(run, asin, sku, since, s, what):
    write_json(os.path.join(run, NEED), dict(asin=asin, need=what))
    return (f"the referral fee read isn't in the run yet ({', '.join(what)}): see {NEED}, so the fee Amazon charges can't "
            "be checked")


def write_json(path, data):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)


def refresh(cfg, shared, run, asin, today_iso):
    """(record, problem). With referral.auto on: reads <run>/settlement.json, and when the window holds min_units units,
    sets cfg's referral_override to the settled rate and moves cfg['profit_per_unit'] by (old - new)/100 x price (in place).
    record is the run summary's `referral` (None when off); problem stops the run (need_settlement.json written)."""
    s = settings(shared)
    if not s['enabled']:
        return None, None
    sku = cfg.get('sku')
    if not sku:
        return dict(status='no_sku', note='the product file has no sku: the referral fee was not read'), None
    since = window_start(today_iso, s['window_days'])
    path = os.path.join(run, FILE)
    how = (f"MAP run_report_sql, platform selling_partner, limit 1000, with the SQL referral.sql(sku, since) prints "
           f"(references/data-pull.md, \"Referral fee\"): settled Order rows for {sku} on {s['marketplace']} posted since "
           f"{since}; saved as {FILE}")
    if not os.path.exists(path):
        return None, need(run, asin, sku, since, s, {FILE: dict(sku=sku, since=since, how=how, sql=sql(sku, since, s['marketplace']))})
    with open(path, encoding='utf-8') as fh:
        m = measure(_rows(json.load(fh)), sku, since)
    if m is None:
        return None, need(run, asin, sku, since, s, {FILE: dict(sku=sku, since=since, how=how + ' (the saved read is of another window)',
                                                         sql=sql(sku, since, s['marketplace']))})
    block = cfg.get('referral_override') if isinstance(cfg.get('referral_override'), dict) else None
    stored = as_pct(block.get('pct')) if block and block.get('pct') is not None else None
    base = dict(window_from=since, window_days=s['window_days'], units=m['units'], order_items=m['order_items'],
                settled_pct=m['pct'], min_units=s['min_units'])
    if m['units'] < s['min_units'] or m['pct'] is None:
        if block is not None:
            block['last_read'] = dict(base, on=today_iso, used=False)
        used = f"{stored:g}% (stored)" if stored is not None else "Scale Insights' rate"
        return dict(base, status='too_few_units', pct=stored, changed=False,
                    note=f"{m['units']:g} units settled since {since}, under {s['min_units']:g}: priced on {used}"), None
    old = stored if stored is not None else si_pct(run, asin)
    if old is None:
        return None, need(run, asin, sku, since, s, {METADATA: dict(
            how=f"Scale Insights get_product_metadata asin_list [{asin}], saved as {METADATA}: the referral rate its "
                "UnitProfit carries, needed once, before the product's first settled-rate block")})
    price = float(cfg.get('price') or 0)
    profit_was = float(cfg['profit_per_unit'])
    profit = round(profit_was + (old - m['pct']) / 100 * price, 2)
    note = (block or {}).get('note')
    cfg['referral_override'] = dict(
        pct=m['pct'], si_pct=as_pct((block or {}).get('si_pct', old if block is None else None)), price=price,
        si_unit_profit=(block or {}).get('si_unit_profit'),
        source=(f"settlement report (MAP sp_settlement), Order rows on {s['marketplace']} posted since {since}: commission / "
                f"principal (${m['commission']:.2f} / ${m['principal']:.2f}), {m['units']:g} units"),
        as_of=today_iso, window_from=since, window_days=s['window_days'], units=m['units'], order_items=m['order_items'],
        decision=DECISION, previous=kept_previous(block, today_iso) or dict(pct=old, profit_per_unit=profit_was),
        **({'note': note} if note else {}))
    changed = abs(profit - profit_was) >= 0.005
    if changed:
        cfg['profit_per_unit'] = profit
        cfg['economics_as_of'] = today_iso
    return dict(base, status='read', pct=m['pct'], was=old, profit_was=profit_was, profit=profit if changed else profit_was,
                changed=changed), None


def kept_previous(block, today_iso):
    """A re-plan the same day keeps the stored block's `previous` (the rate before today's first read): without it a second
    plan.py run overwrote previous with today's own rate (2026-11-04, the top-15 re-runs)."""
    if isinstance(block, dict) and block.get('as_of') == today_iso and isinstance(block.get('previous'), dict):
        return block['previous']
    return None


def line(record):
    """The Slack and log line when the settled rate moved the profit, else None."""
    if not record or not record.get('changed'):
        return None
    return (f"referral fee now {record['pct']:.1f}% (was {record['was']:g}%): profit ${record['profit_was']:.2f} -> "
            f"${record['profit']:.2f}")


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Print the settlement read for a SKU (references/data-pull.md, "Referral fee")')
    ap.add_argument('--sku', required=True)
    ap.add_argument('--today', required=True, help='YYYY-MM-DD, today in Singapore')
    ap.add_argument('--days', type=int, default=14)
    ap.add_argument('--marketplace', default='Amazon.com')
    a = ap.parse_args()
    print(sql(a.sku, window_start(a.today, a.days), a.marketplace))
