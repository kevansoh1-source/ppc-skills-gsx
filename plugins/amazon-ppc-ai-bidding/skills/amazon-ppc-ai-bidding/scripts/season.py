#!/usr/bin/env python3
"""Seasonal products (docs/seasonal-bidding.md; built 2026-10-20 on Kim's go-ahead).

A product whose demand lives in one season carries a `season` block in data/asins/<ASIN>.json. This module:
- reads SoldScope weekly search volume (`common_search_volume_batch`) and works out one season's curve per search: the
  weeks it passes 20% and 50% of its peak above its summer floor, the peak, the weeks at 20% or more, and the shortest
  run of weeks that holds 80% of its searches (the doc's section 2);
- turns the curve of the product's rank searches into this year's dates (section 3): wake, rank build, harvest, last
  mile, off, review and next year's wake, with the payback test before any rank build;
- tells the planner which phase a product is in on a given day (state), and lists the dated steps as open items for the
  product file's "Coming up".

How the dates are set, from the rank searches' weeks summed, last complete season moved onto this year's holiday:
- the rank build starts when the 80%-of-volume window opens, and ends the day before the week the searches reach half of
  their peak; the wake is two weeks before it;
- harvest runs from the day after the rank build to the day before the last mile; the last mile is the day before the
  holiday (a Christmas block moves it to the delivery cut-off with `overrides`); off is the holiday; the season review
  is due within two weeks of it;
- a rank build happens only if it passes the payback test: at least 3 weeks of season (to the end of the 80% window)
  after it ends, and an index of 0.8 or more, judged by a person from last season's SQP or, for a new listing, its
  search terms. Otherwise the product harvests from its wake.

The weekly run (plan.py) plans the wake, rank build and harvest phases. The last mile, off, review and asleep phases
are dated steps: plan.py stops, and says so. A phase different from the block's `phase_applied` (the phase whose
changes were last applied) is a phase switch: every change of that run goes to a person (rulebook 7.9), the book
owner (Lee's level until 2026-10-22). Record `phase_applied` in the product file when the switch is applied.

Usage:
  python season.py block --asin B0SAMP0010 --volume <soldscope.json> --holiday thanksgiving
                         --rank "thanksgiving stickers|turkey stickers" [--evergreen "fall stickers"] [--year 2026]
                         [--today 2026-10-18] [--index 0.9] [--rank-build yes|no --by "Kim, 2026-10-18"] [--cap 600]
                         [--set last_mile=2026-12-19 ...] [--name "Christmas 2026"] [--out <file>]
  python season.py phase --asin B0SAMP0010 [--today 2026-11-07]
  python season.py items --asin B0SAMP0010 --run-id <id> --approval "<who, when: words>" [--owner "Sam (book owner)"]

`block` prints the proposed block and writes nothing to the product file: the book owner approves the season dates
(Lee did until 2026-10-22) and Kim a rank build (rulebook section 8). Paste the approved block into the product
file as "season". `--volume` is the SoldScope response saved as it came (one batch, or a list of batches), or
{"search": [["YYYY-MM-DD", searches], ...]}.
"""
import argparse
import datetime as dt
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from searchtext import norm  # noqa: E402

PHASES = ('asleep', 'wake', 'rank build', 'harvest', 'last mile', 'off', 'review')
PLANNED = ('wake', 'rank build', 'harvest')  # the weekly run plans these; the others are dated steps (open_items)
DATE_FIELDS = ('wake', 'rank_build_start', 'rank_build_end', 'last_mile', 'pause', 'review_by')
WAKE_WEEKS = 2            # the wake sweep: two weeks before the rank build
REVIEW_DAYS = 14          # the season review: within two weeks after the holiday
PAYBACK_WEEKS = 3         # a rank build needs at least 3 weeks of season after it ends
PAYBACK_INDEX = 0.8       # ... and an index of 0.8 or more (the planner's Hold line)
STOP_LOSS_WEEKS = [2, 4]  # checkpoints after 2 and 4 weeks of investing (evergreen: config.json thresholds.stop_loss_weeks)
INVEST_CAP = 600          # a rank build's invest for its whole window, a product, unless approved higher
MIN_PEAK_TO_FLOOR = 2     # a curve counts as a season only if its peak week is at least twice its summer floor
HARVEST_SWEEP_DAYS = ('Monday', 'Thursday')
DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')


# ----------------------------------------------------------------------------- holidays (US marketplace days)
def _nth_weekday(year, month, weekday, n):
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(weekday - first.weekday()) % 7, weeks=n - 1)


def _easter(year):
    """Western Easter Sunday (the anonymous Gregorian computus)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return dt.date(year, month, day + 1)


HOLIDAYS = {
    'valentines': ("Valentine's Day", lambda y: dt.date(y, 2, 14)),
    'st_patricks': ("St. Patrick's Day", lambda y: dt.date(y, 3, 17)),
    'easter': ('Easter', _easter),
    'mothers_day': ("Mother's Day", lambda y: _nth_weekday(y, 5, 6, 2)),
    'fathers_day': ("Father's Day", lambda y: _nth_weekday(y, 6, 6, 3)),
    'halloween': ('Halloween', lambda y: dt.date(y, 10, 31)),
    'thanksgiving': ('Thanksgiving', lambda y: _nth_weekday(y, 11, 3, 4)),
    'christmas': ('Christmas', lambda y: dt.date(y, 12, 25)),
}


def holiday(key, year):
    if key not in HOLIDAYS:
        raise ValueError(f'unknown holiday {key!r}: one of {", ".join(HOLIDAYS)}')
    return HOLIDAYS[key][1](year)


# ----------------------------------------------------------------------------- SoldScope weekly volume
def read_volume(data):
    """{search: [(week-ending date, searches)]}, oldest first, from SoldScope's common_search_volume_batch response
    ({"data": [{keyword, svHistory: [{event_date, search_volume}]}]}, or a list of such responses), or from a compact
    {search: [["YYYY-MM-DD", searches]]}. Keys starting with "_" are notes."""
    out = {}
    for page in data if isinstance(data, list) else [data]:
        if not isinstance(page, dict):
            continue
        if isinstance(page.get('data'), list):
            for row in page['data']:
                out[norm(row.get('keyword'))] = sorted((dt.date.fromisoformat(str(h['event_date'])[:10]), int(h.get('search_volume') or 0))
                                                       for h in row.get('svHistory') or [] if h.get('event_date'))
            continue
        for key, weeks in page.items():
            if not str(key).startswith('_'):
                out[norm(key)] = sorted((dt.date.fromisoformat(str(d)[:10]), int(n or 0)) for d, n in weeks)
    return out


def combine(volume, searches):
    """The searches' weeks summed: [(week-ending date, searches)]."""
    total = {}
    for s in searches:
        for d, n in volume.get(norm(s)) or []:
            total[d] = total.get(d, 0) + n
    return sorted(total.items())


def curve(series, holiday_date):
    """One season of a search (or of several, combine()) around `holiday_date`, the holiday in the series' own year; None
    when there is no season in it. Weeks are SoldScope's, ending on Saturdays.

    - The window runs from 30 weeks before the holiday to 6 after. The peak is its biggest week from 20 weeks before to 1
      after; the summer floor is the median week from 20 to 12 weeks before the peak. No season without a floor in the
      weeks, or with a peak under twice the floor.
    - up20 / up50: the first week of the unbroken run up to the peak at 20% / 50% of the peak, above the floor.
    - weeks_20: that unbroken run at 20% or more, around the peak.
    - window80: the shortest run of weeks holding 80% of the window's searches, from the Sunday its first week starts to
      the Saturday its last week ends (the doc's "80% of volume")."""
    win = [(d, n) for d, n in series if holiday_date - dt.timedelta(weeks=30) <= d <= holiday_date + dt.timedelta(weeks=6)]
    cand = [i for i, (d, _) in enumerate(win) if holiday_date - dt.timedelta(weeks=20) <= d <= holiday_date + dt.timedelta(weeks=1)]
    if not cand:
        return None
    top = max(cand, key=lambda i: (win[i][1], -i))
    peak_day, peak = win[top]
    pre = [n for d, n in win if peak_day - dt.timedelta(weeks=20) <= d <= peak_day - dt.timedelta(weeks=12)]
    if not pre:
        return None  # the weeks don't reach back to the summer floor
    floor = statistics.median(pre)
    if peak <= 0 or peak < MIN_PEAK_TO_FLOOR * floor:
        return None  # no season: the peak is not clearly above the rest of the year

    def level(frac):
        return floor + frac * (peak - floor)

    def run_start(frac):
        i = top
        while i > 0 and win[i - 1][1] >= level(frac):
            i -= 1
        return i
    first20 = run_start(0.2)
    last20 = top
    while last20 + 1 < len(win) and win[last20 + 1][1] >= level(0.2):
        last20 += 1
    total = sum(n for _, n in win)
    best = None
    for x in range(len(win)):
        held = 0
        for y in range(x, len(win)):
            held += win[y][1]
            if held >= 0.8 * total:
                if best is None or y - x < best[1] - best[0]:
                    best = (x, y)
                break
    return dict(floor=floor, peak=peak_day, peak_searches=peak, up20=win[first20][0], up50=win[run_start(0.5)][0],
                weeks_20=last20 - first20 + 1, window80=(win[best[0]][0] - dt.timedelta(days=6), win[best[1]][0]),
                season_searches=total)


def yoy(series, last_holiday, this_holiday):
    """This season's latest week against the week the same number of days before last year's holiday (searches, this
    year / last), or None: no week of this season yet, or no such week last year."""
    if not series:
        return None
    weeks = dict(series)
    latest = max(weeks)
    if not this_holiday - dt.timedelta(weeks=30) <= latest <= this_holiday + dt.timedelta(weeks=6):
        return None
    target = last_holiday - (this_holiday - latest)
    near = sorted((abs((d - target).days), d) for d in weeks if abs((d - target).days) <= 3)
    if not near or not weeks[near[0][1]]:
        return None
    return round(weeks[latest] / weeks[near[0][1]], 2)


def reference_year(holiday_key, year, last):
    """The latest season, this year's or before, that ended (holiday + 2 weeks) by `last`, the data's last week."""
    for y in range(year, year - 4, -1):
        if holiday(holiday_key, y) + dt.timedelta(days=REVIEW_DAYS) <= last:
            return y
    return None


# ----------------------------------------------------------------------------- the season block
def season_block(volume, rank_searches, holiday_key, year, today, evergreen_searches=(), index=None, rank_build=None,
                 decided_by=None, invest_cap=INVEST_CAP, overrides=None, source=None, name=None):
    """The proposed season block for a product (see the module doc for how each date is set). `volume` is read_volume's;
    `index` the listing's conversion against the market, judged by a person (None: not judged, so no rank build until
    someone decides); `rank_build` a person's yes/no that overrides the payback test, with `decided_by` naming them;
    `overrides` {date field: "YYYY-MM-DD"} that win over the computed dates."""
    rank = [norm(s) for s in rank_searches]
    have = [s for s in rank if volume.get(s)]
    if not have:
        raise ValueError('none of the rank searches has SoldScope volume: ' + ', '.join(rank))
    last = max(d for s in have for d, _ in volume[s])
    ref = reference_year(holiday_key, year, last)
    if ref is None:
        raise ValueError(f'the SoldScope weeks end {last}: no complete {holiday_key} season in them')
    H, Href = holiday(holiday_key, year), holiday(holiday_key, ref)
    summed = combine(volume, have)
    c = curve(summed, Href)
    if c is None:
        raise ValueError(f'no {holiday_key} season in the rank searches\' {ref} weeks')

    def move(d):
        return H + (d - Href)
    start, season_end = move(c['window80'][0]), move(c['window80'][1])
    dates = dict(wake=start - dt.timedelta(weeks=WAKE_WEEKS), rank_build_start=start,
                 rank_build_end=move(c['up50']) - dt.timedelta(days=1), last_mile=H - dt.timedelta(days=1), pause=H,
                 review_by=H + dt.timedelta(days=REVIEW_DAYS))
    over = {k: str(v)[:10] for k, v in (overrides or {}).items()}
    for k, v in over.items():
        if k not in DATE_FIELDS:
            raise ValueError(f'unknown date {k!r}: one of {", ".join(DATE_FIELDS)}')
        dates[k] = dt.date.fromisoformat(v)
    order = [dates[k] for k in DATE_FIELDS]
    if not (order[0] <= order[1] <= order[2] < order[3] < order[4] <= order[5]):
        raise ValueError('the dates are out of order (wake <= rank build start <= rank build end < last mile < pause <= '
                         'review): ' + ', '.join(f'{k} {dates[k]}' for k in DATE_FIELDS))

    weeks_after = round((season_end - dates['rank_build_end']).days / 7, 1)
    reasons = []
    if max(today, dates['rank_build_start']) > dates['rank_build_end']:
        reasons.append(f"the rank-build window has passed (it ended {dates['rank_build_end']})")
    if weeks_after < PAYBACK_WEEKS:
        reasons.append(f'only {weeks_after:g} weeks of season after the rank build ends (it needs {PAYBACK_WEEKS})')
    if index is not None and index < PAYBACK_INDEX:
        reasons.append(f'the listing converts at {index:g}x the market (it needs {PAYBACK_INDEX:g})')
    passed = False if reasons else (None if index is None else True)
    if passed is None:
        reasons.append("the index is unknown: a person judges it, from last season's SQP or, for a new listing, its search terms")

    prior_ref = holiday(holiday_key, ref - 1)
    prior = curve(summed, prior_ref)
    curves = {}
    for s in have + [norm(e) for e in evergreen_searches if volume.get(norm(e))]:
        one = curve(volume[s], Href)
        if one:
            curves[s] = dict(up20=one['up20'].isoformat(), up50=one['up50'].isoformat(), peak=one['peak'].isoformat(),
                             peak_searches=one['peak_searches'], weeks_20=one['weeks_20'],
                             window80=[d.isoformat() for d in one['window80']], this_year_vs_last=yoy(volume[s], Href, H))
    block = dict(name=name or f'{HOLIDAYS[holiday_key][0]} {year}', holiday_key=holiday_key, holiday=H.isoformat(),
                 **{k: v.isoformat() for k, v in dates.items()},
                 next_wake=(holiday(holiday_key, year + 1) + (dates['wake'] - H)).isoformat(), season_end=season_end.isoformat(),
                 rank_build=bool(rank_build) if rank_build is not None else passed is True,
                 payback=dict(passed=passed, weeks_after_rank_build=weeks_after, index=index, reasons=reasons,
                              decided_by=decided_by),
                 rank_searches=rank, evergreen_searches=[norm(e) for e in evergreen_searches], invest_cap=invest_cap,
                 stop_loss_weeks=list(STOP_LOSS_WEEKS), harvest_sweep_days=list(HARVEST_SWEEP_DAYS), reference_season=ref,
                 prior_season_shift_days=((prior['up50'] - prior_ref) - (c['up50'] - Href)).days if prior else None,
                 curves=curves, missing_volume=[s for s in rank if s not in have],
                 source=source or f'SoldScope common_search_volume_batch, weekly US searches through {last}')
    if over:
        block['overrides'] = over
    return block


# ----------------------------------------------------------------------------- phases
def _day(block, key):
    return dt.date.fromisoformat(str(block[key])[:10])


def phase_of(block, day):
    """(phase, next phase, the day the next phase starts) of a season block on `day`."""
    wake, start, end, last_mile, pause, review = (_day(block, k) for k in DATE_FIELDS)
    one = dt.timedelta(days=1)
    rank = block.get('rank_build') is True
    if day < wake:
        return 'asleep', 'wake', wake
    if day < start:
        return 'wake', 'rank build' if rank else 'harvest', start
    if day <= end and rank:
        return 'rank build', 'harvest', end + one
    if day < last_mile:
        return 'harvest', 'last mile', last_mile
    if day < pause:
        return 'last mile', 'off', pause
    if day == pause:
        return 'off', 'review', pause + one
    if day <= review:
        return 'review', 'asleep', review + one
    return 'asleep', 'wake', _day(block, 'next_wake') if block.get('next_wake') else None


def describe(block):
    """The season's dates in one line."""
    rank = (f"rank build {block['rank_build_start']} to {block['rank_build_end']}" if block.get('rank_build') is True
            else 'no rank build')
    return (f"{block.get('name') or 'season'}: wake {block['wake']}, {rank}, last mile {block['last_mile']}, "
            f"off {block['pause']}, review by {block['review_by']}")


def state(cfg, day):
    """What the planner needs to know about a product's season on `day`, or None for an evergreen product: neither a
    `season` block nor `mode: "harvest"` in its product file.

    phase; plan (False: a dated-step phase, the weekly run plans nothing); harvest (no invest searches: everything bids
    at its breakeven, top of search at 0%); rank_searches (the only invest searches, in a rank build); stop_loss_weeks;
    switch ("<phase applied> -> <phase>" when the phase differs from the block's phase_applied, else None); invest_cap;
    next {phase, on}; text."""
    block, mode = cfg.get('season'), cfg.get('mode')
    if not block and mode != 'harvest':
        return None
    if not block:
        return dict(name=None, phase='harvest', plan=True, harvest=True, rank_searches=[], stop_loss_weeks=None, switch=None,
                    invest_cap=None, next=None,
                    text='harvest mode (the product file says mode "harvest"): no invest searches; every search bids at its breakeven')
    phase, nxt, when = phase_of(block, day)
    # harvest mode (the Christmas cards, onboarded Oct 20 to 31, 2026, before their searches wake in November) harvests
    # from onboarding to the last mile: before the wake, in the wake and in place of a rank build. After the season the
    # product sleeps as any other.
    if mode == 'harvest' and (phase in ('wake', 'rank build') or (phase == 'asleep' and day < _day(block, 'wake'))):
        phase, nxt, when = 'harvest', 'last mile', _day(block, 'last_mile')
    plan = phase in PLANNED
    applied = block.get('phase_applied')
    return dict(name=block.get('name'), phase=phase, plan=plan, harvest=phase in ('wake', 'harvest'),
                rank_searches=[norm(s) for s in block.get('rank_searches') or []] if phase == 'rank build' else [],
                stop_loss_weeks=list(block.get('stop_loss_weeks') or STOP_LOSS_WEEKS),
                switch=None if not plan or applied == phase else f"{applied or 'no phase recorded'} -> {phase}",
                invest_cap=block.get('invest_cap'), rank_build_end=block.get('rank_build_end') if phase == 'rank build' else None,
                next=dict(phase=nxt, on=when.isoformat() if when else None),
                text=f"{phase} on {day} ({describe(block)}); next: {nxt}" + (f' on {when}' if when else ''))


# ----------------------------------------------------------------------------- dated steps
def open_items(block, today, run_id, owner, approval):
    """The season's dated steps from `today` on, as product-file open items routed to the scheduled lane (the shape the
    dashboard's "Coming up" reads: workflow.source_text equal to text, workflow.run_id set)."""
    name = block.get('name') or 'the season'
    wake, start, end, last_mile, pause, review = (_day(block, k) for k in DATE_FIELDS)
    rank = block.get('rank_build') is True
    steps = []

    def step(day, short, text):
        if day and day >= today:
            steps.append((day, short, f'{text} ({name}; docs/seasonal-bidding.md)'))
    step(wake, 'Wake sweep: unpause the seasonal campaigns at breakeven',
         "Wake sweep: unpause the seasonal campaigns at breakeven, and check stock against the season forecast (last "
         "season's units x this year's search ratio), the listing and price, the negative audit on last season's search "
         "terms and the weekend hours")
    if rank:
        step(start, 'Rank build starts: weekly sweeps',
             f"Rank build starts: {', '.join(block.get('rank_searches') or [])} go to Invest at Amazon's suggested median, "
             f"everything else at breakeven; ${block.get('invest_cap') or INVEST_CAP} cap for the window to {end}; weekly sweeps")
        for n in block.get('stop_loss_weeks') or STOP_LOSS_WEEKS:
            if start + dt.timedelta(weeks=n) <= end:
                step(start + dt.timedelta(weeks=n), f'Stop-loss checkpoint (week {n} of the rank build)',
                     f"Stop-loss checkpoint, week {n} of the rank build: stop any rank search that hasn't moved up in organic rank")
    harvest_from = end + dt.timedelta(days=1) if rank else start
    days = [DAY_NAMES.index(d) for d in block.get('harvest_sweep_days') or HARVEST_SWEEP_DAYS]
    step(harvest_from, 'Harvest: every search to breakeven, top of search to 0%',
         'Harvest: the weekly run proposes the switch (every search at its breakeven, no invest, top of search back to '
         '0%) and a person approves it; sweeps on ' + ' and '.join(DAY_NAMES[d] for d in days))
    d = harvest_from + dt.timedelta(days=1)
    while d < last_mile:
        if d.weekday() in days:
            step(d, 'Harvest sweep', 'Harvest sweep: ACOS by search against breakeven, stock cover against the days left')
        d += dt.timedelta(days=1)
    step(last_mile, 'Halve the seasonal bids and budgets', 'Last mile: halve the seasonal bids and budgets')
    keep = block.get('evergreen_searches') or []
    step(pause, 'Pause the seasonal campaigns',
         'Off: pause the seasonal campaigns (pause, never archive)' +
         (f"; the evergreen searches ({', '.join(keep)}) stay on at breakeven only if they hold it" if keep else ''))
    step(review, 'Season review into the product file',
         "Season review: profit after ads against breakeven, leftover units, and next year's wake and rank-build dates "
         '(scripts/season.py block on fresh SoldScope weeks)')
    if block.get('next_wake'):
        step(_day(block, 'next_wake'), 'Wake date for next season', 'Wake date for next season: build next year\'s block first')
    out = []
    for day, short, text in steps:
        out.append(dict(opened=today.isoformat(), status='open', short=short, text=text, due=day.isoformat(),
                        workflow=dict(lane='scheduled', action=short,
                                      why='Dated step of the approved season plan (scripts/season.py).', owner=owner,
                                      date=today.isoformat(), due=day.isoformat(), run_id=run_id, source_text=text,
                                      approval=approval)))
    return out


# ----------------------------------------------------------------------------- command line
def _product(skill, data, asin):
    with open(os.path.join(skill, 'config.json'), encoding='utf-8') as fh:
        shared = json.load(fh)
    path = os.path.join(data or shared.get('data_dir') or os.path.join(skill, 'data'), 'asins', f'{asin}.json')
    if not os.path.exists(path):
        sys.exit(f'No product file at {path}.')
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _sgt_today():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)).date()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for cmd in ('block', 'phase', 'items'):
        p = sub.add_parser(cmd)
        p.add_argument('--asin', required=True)
        p.add_argument('--today', help='YYYY-MM-DD (default: today in Singapore)')
        p.add_argument('--skill', default=os.path.dirname(HERE))
        p.add_argument('--data', help='shared data folder holding asins/<ASIN>.json')
    b = sub.choices['block']
    b.add_argument('--volume', required=True, help='SoldScope common_search_volume_batch response, saved as it came')
    b.add_argument('--holiday', required=True, choices=sorted(HOLIDAYS))
    b.add_argument('--rank', required=True, help='the rank searches, separated by |')
    b.add_argument('--evergreen', default='', help='searches that stay on outside the season, separated by |')
    b.add_argument('--year', type=int)
    b.add_argument('--index', type=float, help="the listing's conversion against the market, judged by a person")
    b.add_argument('--rank-build', choices=['yes', 'no'], help="a person's call that overrides the payback test (needs --by)")
    b.add_argument('--by', help='who decided --rank-build, and when')
    b.add_argument('--cap', type=float, default=INVEST_CAP)
    b.add_argument('--set', action='append', default=[], metavar='FIELD=YYYY-MM-DD', help='override a date')
    b.add_argument('--name')
    b.add_argument('--out')
    i = sub.choices['items']
    i.add_argument('--run-id', required=True)
    i.add_argument('--approval', required=True)
    i.add_argument('--owner', default='the book owner')
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.today) if a.today else _sgt_today()
    if a.cmd == 'block':
        if a.rank_build and not a.by:
            sys.exit('--rank-build needs --by: who decided it, and when.')
        with open(a.volume, encoding='utf-8') as fh:
            vol = read_volume(json.load(fh))
        block = season_block(vol, [s for s in a.rank.split('|') if s.strip()], a.holiday, a.year or today.year, today,
                             evergreen_searches=[s for s in a.evergreen.split('|') if s.strip()], index=a.index,
                             rank_build=None if a.rank_build is None else a.rank_build == 'yes', decided_by=a.by,
                             invest_cap=a.cap, overrides=dict(s.split('=', 1) for s in a.set), name=a.name)
        text = json.dumps(block, indent=1)
        if a.out:
            with open(a.out, 'w', encoding='utf-8') as fh:
                fh.write(text + '\n')
        print(text)
        print(f"\n{describe(block)}\nPayback test: {block['payback']['passed']} ({'; '.join(block['payback']['reasons']) or 'passes'})",
              file=sys.stderr)
        return
    cfg = _product(a.skill, a.data, a.asin)
    if a.cmd == 'phase':
        s = state(cfg, today)
        print(json.dumps(s, indent=1) if s else f'{a.asin} has no season block and no harvest mode: an evergreen product.')
        return
    if not cfg.get('season'):
        sys.exit(f'{a.asin} has no season block.')
    print(json.dumps(open_items(cfg['season'], today, a.run_id, a.owner, a.approval), indent=1))


if __name__ == '__main__':
    main()
