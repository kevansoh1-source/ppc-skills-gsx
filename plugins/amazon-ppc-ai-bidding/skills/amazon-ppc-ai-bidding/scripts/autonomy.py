#!/usr/bin/env python3
"""The guards of an autonomous run (Kim, 2026-10-22, decision 98; docs/superpowers/specs/2026-10-22-autonomous-runs-design.md).

Since 2026-10-22 the run applies its own Auto rows (config.json auto.enabled is true for every AI product). The manual
guards of the 2026-10-19 design become commands the agent runs:
  switch_off   a guard tripped: the product file's auto.enabled becomes false (its kill switch: the next plan is a shadow
               plan, every row a proposal) and its open_items gets a "decision" entry for the book owner. Kim turns it
               back on (rulebook 7.12).
  day1         the Day-1 check of the previous apply, at the start of the next run (or on a schedule): lanes.spend_check
               (the first US weekday's spend over 1.5x the average weekday spend of the 14 days before the apply). Since
               2026-10-29 (decision 163) a trip opens a "Day-1 spend" alert for the book owner and Auto stays on;
               config.json guards.day1_switch_off true restores the switch-off.
  readback     the read-back of an applied folder: lanes.readback_mismatches between the folder's keyword and target
               payload rows (less --skip, rows held by hand) and the live rows read back, in any saved shape. A file that
               doesn't cover the folder is an input error, never a trip. A real mismatch stops the folder's remaining
               writes and opens a "Read-back" alert, Auto staying on (decision 163; guards.readback_switch_off true
               restores the switch-off).
  program      the AI program's planned invest: every product file but this one (program_month), which plan.py puts on
               the run summary for information (summary.program). Never a gate: Kim, 2026-10-22, decision 99, took the
               $3,000-a-month program check out the evening it was built.
  stock        the one "For human" item of a product with 14 days of stock cover or less (summary.stock_reorder): a
               "decision" entry in the product file's open_items, for the book owner's manual inventory management.
               Since 2026-10-31 (Kim, decision 174) the plan parks the run's increases For human while cover is that low
               and no person has cleared the product (stock_clearance); cuts still go out. It never switches Auto off.
Every write goes to the product file only (never Amazon, Scale Insights, Slack or the dashboard); commit and push it with
the run log. planned_invest_record is what log_invest.py writes as the product's `planned_invest` after an apply.

Usage (from the skill folder):
  python scripts/autonomy.py switch-off --asin <ASIN> --reason "<why>" --date <day> [--data <dir>] [--dry-run]
  python scripts/autonomy.py day1 --asin <ASIN> --spend <first US weekday's spend> --history <s1,s2,...> --date <day>
                                  [--applied-on <day>] [--data <dir>] [--dry-run]
  python scripts/autonomy.py readback --asin <ASIN> --run <run> --folder auto --live <readback.json> --date <day>
                                      [--data <dir>] [--dry-run]
  python scripts/autonomy.py program --asin <ASIN> [--data <dir>]
  python scripts/autonomy.py stock --asin <ASIN> --run <run> --date <day> [--data <dir>] [--dry-run]
Each prints a JSON summary. Standard library only (plus lanes, notify and plan_lanes).
"""
import argparse
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import daypart_base  # noqa: E402
import lanes  # noqa: E402
import notify  # noqa: E402
import plan_lanes  # noqa: E402

STANDARD_DAY = {'Invest': 'invest_per_day', 'Prove first': 'prove_per_day'}  # the estimate of a logged search's budget


# ----------------------------------------------------------------------------- the product file
def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def json_indent(path, default=1):
    """The indent a product file is written with (its first indented line), as dashboard.py keeps it."""
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            body = line.lstrip(' ')
            if body.startswith('"') and body != line:
                return len(line) - len(body)
    return default


def write_product(path, product):
    indent = json_indent(path)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(product, fh, indent=indent, ensure_ascii=False)
        fh.write('\n')


def config(skill=SKILL):
    return read_json(os.path.join(skill, 'config.json'), {})


def data_dir(shared, override=None, skill=SKILL):
    return override or shared.get('data_dir') or os.path.join(skill, 'data')


def decision_entry(product, asin, shared, date, short, text, action, kind):
    """An open_items "decision" entry for the book owner (the dashboard's "Needs a decision" list), tagged with what raised it
    (workflow.kind: 'auto_off' or 'reorder_stock'), so notify.py can name it in the run's message."""
    owner = notify.book_owner(asin, product, shared, notify.read_tiers(os.path.join(notify.REPO, (shared.get('notify') or {})
                                                                                    .get('tiers_csv', 'docs/sweep-tiers.csv'))))
    return dict(opened=date, status='decision', short=short, text=text,
                workflow=dict(lane='human', action=action, owner=owner, date=date, kind=kind, source='autonomy.py'))


def add_decision(product, entry):
    """Adds `entry` to the product's open_items unless an open decision of the same kind and short text was opened the same
    day (running a guard twice adds nothing). Returns True when it added one."""
    items = product.setdefault('open_items', [])
    for o in items:
        flow = o.get('workflow') or {}
        if (o.get('status') == 'decision' and o.get('opened') == entry['opened'] and o.get('short') == entry['short']
                and flow.get('kind') == entry['workflow']['kind']):
            return False
    items.append(entry)
    return True


# ----------------------------------------------------------------------------- the guards
def switch_off(product_path, reason, date, shared=None, dry_run=False):
    """Switch a product's Auto lane off: its product file's auto.enabled becomes false (the kill switch plan_lanes reads:
    the next plan is a shadow plan) with switched_off {on, reason}, and its open_items gets a "decision" entry for the book
    owner ("Auto off: ..."). Returns {asin, was_on, entry_added}. Nothing else is written; `dry_run` writes nothing.
    Turning Auto back on is Kim's (rulebook 7.12): set the product file's auto.enabled to true, or remove the block."""
    shared = shared if shared is not None else config()
    product = read_json(product_path)
    if product is None:
        raise SystemExit(f'No product file at {product_path}')
    asin = product.get('asin') or os.path.splitext(os.path.basename(product_path))[0]
    was_on = plan_lanes.auto_enabled(shared, product)
    block = dict(product.get('auto') or {})
    block.update(enabled=False, switched_off=dict(on=date, reason=reason))
    product['auto'] = block
    entry = decision_entry(product, asin, shared, date, short=f'Auto off: {short_text(reason)}',
                           text=(f'{reason}. The AI switched Auto off for this product on {date}: its runs now plan and '
                                 'propose only, and nothing applies on its own. Look at what tripped it; Kim turns Auto '
                                 'back on (rulebook 7.12).'),
                           action='Look at what tripped it; Kim turns Auto back on', kind='auto_off')
    added = add_decision(product, entry)
    if not dry_run:
        write_product(product_path, product)
    return dict(asin=asin, was_on=was_on, entry_added=added, dry_run=dry_run)


def short_text(reason, n=60):
    text = str(reason).strip().rstrip('.')
    return text if len(text) <= n else text[:n].rsplit(' ', 1)[0] + '...'


def guard_switches_off(shared, name):
    """Whether guard `name` ('day1' or 'readback') switches a product's Auto off when it trips. Since 2026-10-29 (Kim,
    decision 163: 'the auto tripping confuses my team members.. how do we not make the auto trips?') neither does by
    default: a trip opens an alert for the book owner and Auto stays on; the stop-loss and the weekly leak check
    (decision 175) are the brakes. config.json guards.<name>_switch_off true restores the kill switch."""
    return bool((shared.get('guards') or {}).get(f'{name}_switch_off', False))


def alert(product_path, reason, date, kind, action, shared=None, dry_run=False):
    """A guard's alert with Auto left on (decision 163): an open_items "decision" entry for the book owner, once a day.
    Returns {asin, entry_added}."""
    shared = shared if shared is not None else config()
    product = read_json(product_path)
    asin = product.get('asin') or os.path.splitext(os.path.basename(product_path))[0]
    entry = decision_entry(product, asin, shared, date, short=short_text(reason),
                           text=f'{reason}. Auto stays on (decision 163); {action[0].lower() + action[1:]}.',
                           action=action, kind=kind)
    added = add_decision(product, entry)
    if added and not dry_run:
        write_product(product_path, product)
    return dict(asin=asin, entry_added=added, dry_run=dry_run)


def day1(product_path, next_weekday_spend, last14_weekday_spends, date, applied_on=None, shared=None, dry_run=False):
    """The Day-1 check of the previous apply (weekly-run.md, "Day-1 check"): lanes.spend_check on the first full US weekday's
    ad spend after the apply against the product's US weekdays of the 14 days before it. A trip opens a "Day-1 spend" alert
    for the book owner and leaves Auto on (decision 163), unless guards.day1_switch_off is true, when it switches Auto off
    (switch_off) as before. Returns {tripped, spend, average, ratio, switched_off, alert}."""
    shared = shared if shared is not None else config()
    history = [float(v) for v in last14_weekday_spends]
    spend = float(next_weekday_spend)
    tripped = lanes.spend_check(spend, history)
    average = sum(history) / len(history) if history else None
    ratio = (spend / average) if average else None
    out = dict(tripped=tripped, spend=spend, average=None if average is None else round(average, 2),
               ratio=None if ratio is None or not math.isfinite(ratio) else round(ratio, 2), switched_off=None, alert=None)
    if tripped:
        when = f' after the apply of {applied_on}' if applied_on else ''
        avg = 'no spend' if not average else f'a ${average:,.2f} weekday average'
        reason = (f'Day-1 spend check{when}: ${spend:,.2f} on the first US weekday against {avg} over the 14 days before '
                  f'(over {lanes.SPEND_TRIP_RATIO:g}x)')
        if guard_switches_off(shared, 'day1'):
            out['switched_off'] = switch_off(product_path, reason, date, shared, dry_run)
        else:
            out['alert'] = alert(product_path, reason, date, 'day1_spend', 'Check the spend is what the run meant to add '
                                 '(new rank campaigns, raises, opened hours); the stop-loss and the leak check brake a loss', shared, dry_run)
    return out


def folder_rows(run, folder):
    """The keyword, target and Sponsored Brands theme payload rows of a payload folder (what readback_mismatches compares),
    in file order; the Scale Insights checklist and rows.json are left out."""
    rows = []
    for path in sorted(glob.glob(os.path.join(glob.escape(os.path.join(run, 'payloads', folder)), '*.json'))):
        if os.path.basename(path) in ('rows.json', SI_STEPS):
            continue
        data = read_json(path, [])
        rows += [r for r in data if isinstance(r, dict) and (r.get('keywordId') or r.get('targetId') or r.get('themeId'))]
    return rows


SI_STEPS = 'scale_insights_steps.json'  # plan.write_outputs' Scale Insights checklist in a lane folder (not a MAP payload)


class ReadbackInputError(SystemExit):
    """The read-back file does not cover the folder (wrong shape, or the wrong reads): an input error, never a guard trip
    (decision 163; the 2026-10-28 B0SAMP0026 trip was an {"items": [...]} file read as 96 missing rows)."""


def readback(product_path, run, folder, live, date, shared=None, dry_run=False, skip=()):
    """The read-back of `folder` (auto/, review/ or approved/) after its MAP apply: lanes.readback_mismatches between the
    folder's keyword and target rows and `live` (the rows read back, read_live's shapes). `skip`: keyword, target or theme
    ids of rows held by hand and never sent; they are not compared.

    When half or more of the compared rows are missing from `live`, the file does not cover the folder: ReadbackInputError,
    and nothing is written (read the rows again). A real mismatch stops the folder's remaining writes (`stop`) and opens a
    "Read-back" alert for the book owner with Auto left on (decision 163), unless guards.readback_switch_off is true, when it
    switches Auto off (switch_off) as before. Returns {rows, skipped, mismatches, stop, switched_off, alert}."""
    shared = shared if shared is not None else config()
    skip = {str(s) for s in (skip or ()) if str(s).strip()}
    written = [r for r in folder_rows(run, folder) if str(lanes._row_id(r)) not in skip]
    mods = daypart_base.common_factor(_lower_pairs(written, live), daypart_base.modifiers(shared))
    mismatches = lanes.readback_mismatches(written, live, mods)
    found = {str(lanes._row_id(r)) for r in live if lanes._row_id(r)}
    missing = [r for r in written if str(lanes._row_id(r)) not in found]
    if written and len(missing) * 2 >= len(written):
        raise ReadbackInputError(
            f'{len(missing)} of {len(written)} rows of payloads/{folder}/ are not in the read-back file: it does not cover the '
            'folder (check its shape and that every resource type and campaign was read). Nothing was recorded or switched off.')
    out = dict(rows=len(written), skipped=sorted(skip), mismatches=mismatches, stop=bool(mismatches), switched_off=None,
               alert=None)
    if mismatches:
        reason = (f"Read-back mismatch after the apply of payloads/{folder}/ ({len(mismatches)} of {len(written)} rows "
                  'not as written)')
        if guard_switches_off(shared, 'readback'):
            out['switched_off'] = switch_off(product_path, reason, date, shared, dry_run)
        else:
            out['alert'] = alert(product_path, reason, date, 'readback', 'Send those rows again through MAP and read them '
                                 'back; record only what reads back', shared, dry_run)
    return out


def _lower_pairs(written, live):
    """(written bid, live bid) of the rows that read back lower than written: where a dayparting modifier shows."""
    by_id = {lanes._row_id(r): r for r in live if lanes._row_id(r)}
    out = []
    for row in written:
        got = (by_id.get(lanes._row_id(row)) or {}).get('bid')
        try:
            w, g = float(row['bid']), float(got)
        except (KeyError, TypeError, ValueError):
            continue
        if g < w:
            out.append((w, g))
    return out


def unwrap_live(data):
    """The rows of a read-back in any shape an agent saves it (decision 163): a plain list; {"items"|"data"|"results":
    [...]}; MAP's saved response [{"type": "text", "text": "<json>"}], {"content": [...]} or {"structuredContent": ...};
    or a list of several such reads concatenated. Rows are the dicts that carry an id."""
    if isinstance(data, dict):
        if 'structuredContent' in data:
            return unwrap_live(data['structuredContent'])
        if isinstance(data.get('content'), list):
            return unwrap_live(data['content'])
        for key in ('items', 'data', 'results'):
            if isinstance(data.get(key), list):
                return unwrap_live(data[key])
        return [data] if lanes._row_id(data) else []
    if isinstance(data, list):
        rows = []
        for r in data:
            if isinstance(r, dict) and r.get('type') == 'text' and isinstance(r.get('text'), str):
                try:
                    rows += unwrap_live(json.loads(r['text']))
                except ValueError:
                    continue
            elif isinstance(r, (dict, list)):
                rows += unwrap_live(r) if (isinstance(r, list) or not lanes._row_id(r)) else [r]
        return rows
    return []


def read_live(path):
    """Rows read back, from a file in any shape unwrap_live reads."""
    data = read_json(path)
    rows = unwrap_live(data)
    if not rows:
        raise ReadbackInputError(f'{path} holds no rows with an id: save the MAP list_resources reads (any shape)')
    return rows


# ----------------------------------------------------------------------------- the program total (information only)
def product_month(product, shared):
    """(the product's planned invest a month, basis): its `planned_invest.month` when log_invest recorded one (basis
    'record'), else an estimate from its invest logs, each logged search at its role's standard daily budget x 30
    (basis 'invest log estimate'; an upper bound: it fails safe), or (0.0, 'nothing invested')."""
    rec = product.get('planned_invest')
    if isinstance(rec, dict) and isinstance(rec.get('month'), (int, float)) and not isinstance(rec.get('month'), bool):
        return float(rec['month']), 'record'
    bud = shared.get('budgets') or {}
    total = 0.0
    for key in ('invest_log', 'business_invest_log'):
        for entry in (product.get(key) or {}).values():
            if isinstance(entry, dict):
                total += float(bud.get(STANDARD_DAY.get(entry.get('role'), 'invest_per_day'), 10)) * 30
    return total, ('invest log estimate' if total else 'nothing invested')


def program_month(data, asin, shared):
    """Every other product file's planned invest a month (product_month), for the run summary's program total: {other_month,
    products: [{asin, month, basis}]} (only the products that invest). The product being planned is left out: its own
    planned invest is the plan's (planned_invest_month_start plus this run's promotions)."""
    products, total = [], 0.0
    for path in sorted(glob.glob(os.path.join(glob.escape(os.path.join(data, 'asins')), '*.json'))):
        other = os.path.splitext(os.path.basename(path))[0]
        if other == asin:
            continue
        try:
            product = read_json(path, {})
        except (OSError, ValueError):
            continue
        month, basis = product_month(product, shared)
        if month:
            products.append(dict(asin=other, month=round(month, 2), basis=basis))
            total += month
    return dict(other_month=round(total, 2), products=products)


def planned_invest_record(plan, applied, date):
    """The product's planned invest after a run, as log_invest.py writes it (`planned_invest`): {month, as_of, run, basis}.
    month = the plan's planned_invest_month_start (its invest searches not promoted this run) plus the modelled monthly
    spend of every promotion recorded as gone out (`applied`: {row_id: date}). None for a plan made before the lanes."""
    s = (plan.get('summary') or [{}])[0]
    start = s.get('planned_invest_month_start')
    if not isinstance(start, (int, float)) or isinstance(start, bool):
        return None
    added = sum(c.get('modelled_spend_month') or 0 for c in plan.get('changes') or []
                if isinstance(c, dict) and plan_lanes.is_promotion(c) and c.get('row_id') in (applied or {}))
    return dict(month=round(start + added, 2), as_of=date, run=s.get('run'), basis='plan')


# ----------------------------------------------------------------------------- low stock
def stock(product_path, plan, date, shared=None, dry_run=False):
    """The "reorder stock" decision for the book owner when the plan's summary.stock_reorder says the product has 14 days of
    cover or less (plan_lanes.stock_cover): an open_items "decision" entry, once a day. Returns {cover_days, entry_added}."""
    shared = shared if shared is not None else config()
    cover = ((plan.get('summary') or [{}])[0].get('stock_reorder') or {}).get('cover_days')
    if cover is None:
        return dict(cover_days=None, entry_added=False)
    product = read_json(product_path)
    asin = product.get('asin') or os.path.splitext(os.path.basename(product_path))[0]
    rs = (plan.get('summary') or [{}])[0].get('stock_reorder') or {}
    held, cleared = len(rs.get('held') or []), rs.get('cleared')
    if cleared:
        hold = (f"{cleared.get('by')} cleared it on {cleared.get('on')} until {cleared.get('until')}, so the run's increases "
                'went out under the normal rules.')
    else:
        hold = (f"The run's increases ({held} row{'s' if held != 1 else ''}) wait For human until a person approves them or "
                'clears the product (stock_clearance in its file, decision 174); cuts went out as usual.')
    entry = decision_entry(product, asin, shared, date, short=f'Reorder stock: {cover:g} days of cover',
                           text=(f'{cover:g} days of stock cover on {date} (14 or fewer). {hold} The team manages '
                                 'inventory and any reorder manually.'),
                           action='Reorder stock', kind='reorder_stock')
    added = add_decision(product, entry)
    if added and not dry_run:
        write_product(product_path, product)
    return dict(cover_days=cover, entry_added=added, dry_run=dry_run)


# ----------------------------------------------------------------------------- the commands
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--skill', default=SKILL)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('switch-off', 'day1', 'readback', 'program', 'stock'):
        p = sub.add_parser(name)
        p.add_argument('--asin', required=True)
        p.add_argument('--data', help='shared data folder holding asins/<ASIN>.json')
        if name != 'program':
            p.add_argument('--date', required=True, help='YYYY-MM-DD, today in Singapore')
            p.add_argument('--dry-run', action='store_true', help='work it out and print it, write nothing')
        if name == 'switch-off':
            p.add_argument('--reason', required=True)
        if name == 'day1':
            p.add_argument('--spend', required=True, type=float, help="the first full US weekday's ad spend after the apply")
            p.add_argument('--history', required=True,
                           help='the ad spend of each US weekday of the 14 days before the apply, comma-separated')
            p.add_argument('--applied-on', help='the day the previous apply went out')
        if name in ('readback', 'stock'):
            p.add_argument('--run', required=True)
        if name == 'readback':
            p.add_argument('--folder', required=True, choices=('auto', 'review', 'approved'))
            p.add_argument('--live', required=True, help='the rows read back (MAP list_resources), saved to a file')
            p.add_argument('--skip', default='', help='keyword/target ids held by hand and never sent, comma-separated')
    a = ap.parse_args(argv)
    shared = config(a.skill)
    path = os.path.join(data_dir(shared, a.data, a.skill), 'asins', f'{a.asin}.json')
    if a.cmd != 'program' and not os.path.exists(path):   # the program total needs no file of its own
        sys.exit(f'No product file at {path}')
    if a.cmd == 'switch-off':
        out = switch_off(path, a.reason, a.date, shared, a.dry_run)
    elif a.cmd == 'day1':
        history = [float(v) for v in str(a.history).replace(';', ',').split(',') if v.strip()]
        out = day1(path, a.spend, history, a.date, a.applied_on, shared, a.dry_run)
    elif a.cmd == 'readback':
        out = readback(path, a.run, a.folder, read_live(a.live), a.date, shared, a.dry_run,
                       skip=[s for s in str(a.skip).split(',') if s.strip()])
    elif a.cmd == 'program':
        out = program_month(data_dir(shared, a.data, a.skill), a.asin, shared)
    else:
        plan = read_json(os.path.join(a.run, 'plan.json'))
        if plan is None:
            sys.exit(f'No plan.json in {a.run}')
        out = stock(path, plan, a.date, shared, a.dry_run)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
