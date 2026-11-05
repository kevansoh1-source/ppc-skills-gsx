#!/usr/bin/env python3
"""When a bid write is safe from Scale Insights' dayparting switches (Kim, 2026-10-26, decision 151).

Rule 203 (dayparting 21246) still runs on every AI ad group. At each ON switch Scale Insights sets every bid on Amazon
again from its own saved copy times the hour's modifier, and its saved copy takes a bid written through MarketplaceAdPros
only about 2 hours after the write (2026-10-25 B0SAMP0010; 2026-10-26 B0SAMP0015, 240 of 241). So a bid written in the
2 hours before an ON switch is put back to the old bid at the switch (2026-10-26, B0SAMP0005's 20:28 SGT chunk before the
21:00 SGT Monday switch). Kim chose to have the skill handle the timing itself, so nobody works around the clock:

  check        before the live read and before an apply: `ok`, or `hold` when a switch in `hold_at` is under
               `hold_hours` away or under `settle_minutes` past (Scale Insights takes a while to re-send every bid at a
               switch: SP first, SB later; decision 152), with `safe_from`. On hold, wait and go on from `safe_from`
               (re-reading live state first), or park the folder.
  prewrite     right before the MAP apply, against a fresh live read: each payload row's plan `current` against its
               live bid. `apply` when all still fit; `replan` when the only moves are dayparting switches (live =
               current x m or current = live x m, m read from the bids: 0.8 for today's -20% (since 2026-10-31, decision
               174; 0.6 for the -40% before it), 0.75 for a -25%; expected,
               never a stop or a question; plan again from a fresh read,
               in a new run folder if anything of this one went out); `stop` on any other change (say so before
               applying, AGENTS.md rule 1).
  park         adds a dated open item "Apply held <folder> rows after <time> SGT" for the routine to pick up.
  after-apply  after an apply: when a switch in `recheck_at` comes within `recheck_hours`, adds a dated open item to
               re-read the written bids after it.
  recheck      after that switch: lists the written bids Amazon no longer shows (neither the written bid nor the written
               bid times the hour's modifier) and writes `<run>/recheck/<folder>-<stamp>.json`, the same payload rows,
               grouped by their payload file, for the run to send again through MAP and read back.

The schedule is config.json `write_window` (Los Angeles hours; weekday Mon-Fri, weekend Sat-Sun). Nothing here writes to
Amazon or Scale Insights.

  python scripts/write_window.py check [--now <ISO time>]
  python scripts/write_window.py park --asin <ASIN> --run <run> --folder auto|review|approved [--now ...] [--data <dir>]
  python scripts/write_window.py after-apply --asin <ASIN> --run <run> --folder ... [--now ...] [--data <dir>]
  python scripts/write_window.py recheck --run <run> --folder ... --live <readback.json> [--now ...]
  python scripts/write_window.py prewrite --run <run> --folder ... --live <live.json>
`check` exits 3 on hold; `prewrite` exits 4 on replan and 5 on stop. Each prints a JSON summary.
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import autonomy  # noqa: E402
import daypart_base  # noqa: E402
import lanes  # noqa: E402

SGT = dt.timezone(dt.timedelta(hours=8))
TOL = 0.011  # a cent of rounding on either side (Scale Insights rounds the modified bid)
HOUR = dt.timedelta(hours=1)


def settings(cfg):
    ww = dict(cfg.get('write_window') or {})
    ww.setdefault('on_hours', {'weekday': [6, 21], 'weekend': [5, 21]})
    ww.setdefault('modifier', {'weekday': 1.0, 'weekend': 0.8})
    ww.setdefault('hold_hours', 2)
    ww.setdefault('settle_minutes', 60)
    ww.setdefault('recheck_hours', 4)
    ww.setdefault('hold_at', ['on'])
    ww.setdefault('recheck_at', ['on', 'off'])
    return ww


def _market(moment):
    """The Los Angeles wall-clock time of an aware moment."""
    utc = moment.astimezone(dt.timezone.utc)
    return utc + dt.timedelta(hours=lanes._la_offset_hours(utc))


def _part(local):
    return 'weekend' if local.weekday() >= 5 else 'weekday'


def is_on(moment, ww):
    local = _market(moment)
    first, last = ww['on_hours'][_part(local)]
    return first <= local.hour <= last


def modifier_at(moment, ww):
    """The modifier on the live bids at `moment`: the one of the latest ON hour at or before it (Scale Insights leaves the
    modified bid in place through the OFF hours after it)."""
    t = moment
    for _ in range(169):
        if is_on(t, ww):
            return float(ww['modifier'][_part(_market(t))])
        t -= HOUR
    return 1.0


def upcoming(now, ww, horizon=168):
    """The switches after `now`, in order: {utc, kind} with kind 'on' (ads on, or a new modifier between ON hours) or
    'off'. Switches fall on the hour."""
    t = now.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    for _ in range(horizon):
        t += HOUR
        before, after = t - HOUR, t
        was, on = is_on(before, ww), is_on(after, ww)
        if on and (not was or modifier_at(before, ww) != modifier_at(after, ww)):
            yield dict(utc=t, kind='on')
        elif was and not on:
            yield dict(utc=t, kind='off')


def sgt(moment):
    return moment.astimezone(SGT).strftime('%a %Y-%m-%d %H:%M SGT')


def last_on(now, ww, horizon=168):
    """The latest switch in `hold_at` at or before `now` (None within `horizon` hours)."""
    t = now.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    for _ in range(horizon):
        edge = next(iter(upcoming(t - HOUR, ww, horizon=1)), None)
        if edge and edge['kind'] in ww['hold_at'] and edge['utc'] <= now:
            return edge
        t -= HOUR
    return None


def check(now, ww):
    """`status` 'ok' or 'hold'. On hold, `safe_from` is `settle_minutes` after the switch. `recheck_after` (15 minutes
    after the next switch in `recheck_at`) is set when that switch comes within `recheck_hours`: a write now needs the
    re-check."""
    settle = dt.timedelta(minutes=ww['settle_minutes'])
    past = last_on(now, ww)
    if past and now - past['utc'] < settle:
        safe = past['utc'] + settle
        return dict(now=sgt(now), on=is_on(now, ww), modifier=modifier_at(now, ww), status='hold',
                    safe_from=sgt(safe), safe_from_utc=safe.isoformat(),
                    last_switch=dict(kind=past['kind'], at=sgt(past['utc']), utc=past['utc'].isoformat()),
                    why=f"Scale Insights is still re-sending bids after its {sgt(past['utc'])} switch (it takes up to "
                        f"{ww['settle_minutes']} minutes, SB after SP): a live read now can catch bids on either side")
    edges = list(upcoming(now, ww))
    hold = next((e for e in edges if e['kind'] in ww['hold_at']), None)
    again = next((e for e in edges if e['kind'] in ww['recheck_at']), None)
    out = dict(now=sgt(now), on=is_on(now, ww), modifier=modifier_at(now, ww), status='ok')
    if hold:
        out['next_switch'] = dict(kind=hold['kind'], at=sgt(hold['utc']), utc=hold['utc'].isoformat())
        if hold['utc'] - now < dt.timedelta(hours=ww['hold_hours']):
            safe = hold['utc'] + settle
            out.update(status='hold', safe_from=sgt(safe), safe_from_utc=safe.isoformat(),
                       why=f"Scale Insights resets the bids from its saved copy at {sgt(hold['utc'])}, and it takes a "
                           f"written bid into that copy only about 2 hours later: a write now would be put back")
    if out['status'] == 'ok' and again and again['utc'] - now < dt.timedelta(hours=ww['recheck_hours']):
        after = again['utc'] + dt.timedelta(minutes=15)
        out.update(recheck_after=sgt(after), recheck_after_utc=after.isoformat(), recheck_switch=again['kind'],
                   recheck_switch_at=sgt(again['utc']))
    return out


def written_rows(run, folder):
    """{payload file name: [rows with keywordId or targetId]} of a payload folder, as the read-back reads them."""
    out = {}
    for path in sorted(glob.glob(os.path.join(run, 'payloads', folder, '*.json'))):
        name = os.path.basename(path)
        if name in ('rows.json', 'scale_insights_steps.json'):
            continue
        rows = autonomy.read_json(path, [])
        rows = [r for r in rows if isinstance(r, dict) and lanes._row_id(r)] if isinstance(rows, list) else []
        if rows:
            out[name] = rows
    return out


def reverted(written, live, m):
    """The written bids Amazon no longer shows: live is neither the written bid nor round(written x m, 2). A row missing
    from `live` is listed with live None. State-only rows are not dayparting's and are left to the read-back."""
    by_id = {lanes._row_id(r): r for r in live if lanes._row_id(r)}
    out = []
    for row in written:
        if row.get('bid') is None:
            continue
        rid, bid = lanes._row_id(row), float(row['bid'])
        got = (by_id.get(rid) or {}).get('bid')
        try:
            got = float(got) if got is not None else None
        except (TypeError, ValueError):
            got = None
        if got is None or (abs(got - bid) > TOL and abs(got - round(bid * m, 2)) > TOL):
            out.append(dict(id=rid, written=bid, expected=round(bid * m, 2), live=got))
    return out


def recheck(run, folder, live, now, ww):
    """The schedule's modifier for the hour, or the one the bids show when Scale Insights' cut was changed (decision 152)."""
    m = modifier_at(now, ww)
    files = written_rows(run, folder)
    by_id = {lanes._row_id(r): r for r in live if lanes._row_id(r)}
    pairs = []
    for rows in files.values():
        for r in rows:
            got = (by_id.get(lanes._row_id(r)) or {}).get('bid')
            if r.get('bid') is not None and isinstance(got, (int, float)) and got < float(r['bid']):
                pairs.append((float(r['bid']), float(got)))
    if m != 1.0:
        seen = [f for f in daypart_base.common_factor(pairs) if abs(f - m) > 0.02]
        m = seen[0] if seen else m
    bad = {}
    for name, rows in files.items():
        ids = {r['id'] for r in reverted(rows, live, m)}
        if ids:
            bad[name] = [r for r in rows if lanes._row_id(r) in ids]
    out = dict(now=sgt(now), modifier=m, checked=sum(len(r) for r in files.values()),
               reverted=sum(len(r) for r in bad.values()), resend=None)
    if bad:
        path = os.path.join(run, 'recheck', f"{folder}-{now.astimezone(SGT).strftime('%Y%m%d-%H%M')}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(bad, fh, indent=1, ensure_ascii=False)
            fh.write('\n')
        out.update(resend=path, files={k: len(v) for k, v in bad.items()})
    return out


def prewrite(run, folder, live, mods):
    """Each payload row of `folder` against `live` (dashboard.read_live rows), by its plan row's `current`, with
    dashboard.drift_reason: {verdict, same, switch, changed, not_checked, rows}. verdict 'apply', 'replan' (only
    dayparting switches) or 'stop'."""
    import dashboard
    plan = autonomy.read_json(os.path.join(run, 'plan.json'), {}) or {}
    by_id = {c.get('row_id'): c for c in plan.get('changes') or []}
    names = autonomy.read_json(os.path.join(run, 'payloads', folder, 'rows.json'), {}) or {}
    live_ids = dashboard.live_by_id(live)
    rids = list(dict.fromkeys(rid for ids in names.values() if isinstance(ids, list) for rid in ids if rid in by_id))
    pairs = []
    for rid in rids:
        change = by_id[rid]
        field = dashboard.bid_row_field(change)
        row = live_ids.get(str(change.get(field))) if field else None
        if row is not None:
            before, after = dashboard._number(change.get('current')), dashboard._number(row.get('bid'))
            if before is not None and after is not None:
                pairs.append((before, after))
    mods = daypart_base.common_factor(pairs, mods)
    factor = dashboard.plan_factor(plan)
    out = dict(modifiers=mods, plan_factor=factor, same=0, switch=[], changed=[], not_checked=0)
    for rid in rids:
        why = dashboard.drift_reason(by_id[rid], live_ids, mods, factor)
        if why is dashboard.NOT_CHECKED:
            out['not_checked'] += 1
        elif why is None:
            out['same'] += 1
        else:
            out['switch' if why.startswith(dashboard.DAYPART_SWITCH) else 'changed'].append(dict(row_id=rid, why=why))
    out['verdict'] = 'stop' if out['changed'] else 'replan' if out['switch'] else 'apply'
    out['next'] = {
        'apply': 'every row still fits its plan: apply',
        'replan': "only Scale Insights' dayparting switch moved bids since the plan (expected, not a mismatch, not a "
                  'question for a person): wait for write_window.py check to say ok, then plan again from a fresh read '
                  '(in a new run folder if anything of this one went out); rows already written read live as written '
                  'and are not sent again',
        'stop': 'a bid changed since the plan in a way dayparting does not explain: say so before applying (AGENTS.md '
                'rule 1)'}[out['verdict']]
    return out


def item(product, today, due, short, text, run, folder, kind):
    """A dated open item the morning routine lists under `checks` (routine.py); added once per short text and due day."""
    items = product.setdefault('open_items', [])
    if any(o.get('status') == 'open' and o.get('short') == short and o.get('due') == due for o in items):
        return False
    items.append(dict(opened=today, status='open', short=short, text=text, due=due,
                      workflow=dict(lane='ai', kind=kind, action=short, run=run, folder=folder, date=today, due=due,
                                    source='write_window.py')))
    return True


def _now(value):
    if not value:
        return dt.datetime.now(dt.timezone.utc)
    moment = dt.datetime.fromisoformat(value)
    if moment.utcoffset() is None:
        raise SystemExit('--now needs a timezone, e.g. 2026-10-26T20:40+08:00')
    return moment


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('command', choices=('check', 'park', 'after-apply', 'recheck', 'prewrite'))
    ap.add_argument('--now')
    ap.add_argument('--asin')
    ap.add_argument('--run')
    ap.add_argument('--folder', default='auto', choices=('auto', 'review', 'approved'))
    ap.add_argument('--live')
    ap.add_argument('--data')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    cfg = autonomy.config()
    ww, now = settings(cfg), _now(a.now)
    res = check(now, ww)
    if a.command == 'check':
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 3 if res['status'] == 'hold' else 0
    if not a.run:
        raise SystemExit(f'{a.command} needs --run')
    run_name = os.path.basename(os.path.normpath(a.run))
    if a.command == 'prewrite':
        if not a.live:
            raise SystemExit('prewrite needs --live (a fresh MAP list_resources read of the rows)')
        import dashboard
        res = prewrite(a.run, a.folder, dashboard.read_live(a.live), daypart_base.modifiers(cfg))
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return {'apply': 0, 'replan': 4, 'stop': 5}[res['verdict']]
    if a.command == 'recheck':
        if not a.live:
            raise SystemExit('recheck needs --live (the bids read back with MAP list_resources)')
        import dashboard
        print(json.dumps(recheck(a.run, a.folder, dashboard.read_live(a.live), now, ww), indent=1, ensure_ascii=False))
        return 0
    if not a.asin:
        raise SystemExit(f'{a.command} needs --asin')
    path = os.path.join(autonomy.data_dir(cfg, a.data), 'asins', f'{a.asin}.json')
    product = autonomy.read_json(path)
    if product is None:
        raise SystemExit(f'no product file {path}')
    today = now.astimezone(SGT).date().isoformat()
    if a.command == 'park':
        if res['status'] != 'hold':
            raise SystemExit(f"nothing to park: the window is open ({res['now']}); apply now")
        safe = dt.datetime.fromisoformat(res['safe_from_utc'])
        added = item(product, today, safe.astimezone(SGT).date().isoformat(),
                     f"Apply held {a.folder} rows after {safe.astimezone(SGT).strftime('%H:%M')} SGT",
                     f"{run_name}: the {a.folder}/ folder was held at {res['now']} because {res['why']}. From "
                     f"{res['safe_from']}, re-read live state, check (`applied --folder {a.folder} --dry-run`), apply, "
                     f"read back and record (weekly-run.md step 12).", run_name, a.folder, 'write_window_hold')
    else:
        if 'recheck_after_utc' not in res:
            print(json.dumps(dict(res, added=False, note='no switch within recheck_hours: no re-check needed'),
                             indent=1, ensure_ascii=False))
            return 0
        after = dt.datetime.fromisoformat(res['recheck_after_utc'])
        added = item(product, today, after.astimezone(SGT).date().isoformat(),
                     f"Re-check {a.folder} bids after the {res['recheck_switch_at'][-9:-4]} SGT switch",
                     f"{run_name}: {a.folder}/ was written at {res['now']}, under {ww['recheck_hours']} hours before a "
                     f"Scale Insights switch. From {res['recheck_after']}, read the bids back with MAP list_resources, "
                     f"run `write_window.py recheck --run <run> --folder {a.folder} --live <readback.json>`, send any "
                     f"rows it lists again through MAP, read them back, and log it.", run_name, a.folder,
                     'write_window_recheck')
    if added and not a.dry_run:
        autonomy.write_product(path, product)
    print(json.dumps(dict(res, added=added, dry_run=a.dry_run), indent=1, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
