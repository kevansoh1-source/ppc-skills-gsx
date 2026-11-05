"""The base bid behind a live bid that a Scale Insights dayparting modifier has lowered (Kim, 2026-10-26, decision 150).

Scale Insights runs a dayparting bid modifier by changing Amazon's own bid, and leaves the modified bid in place through
the OFF hours after it: rule 203's weekend cut (-20% since 2026-10-31, decision 174; -40% from 2026-10-26) is in
Amazon's live bids from Sat 05:00 PT until the weekday hours open on
Mon 06:00 PT (Sat 20:00 SGT to Mon 21:00 SGT). Read then, a live bid is the base times the modifier (2026-10-26, the
B0SAMP0028 sweep: 282 of 282 rows at exactly Scale Insights' stored bid x 0.60). The plan prices against the base, so a
raise is capped from the base and a cut-only row cuts from the base, never from the modified bid.

The modifier is read from the data, never from the calendar (weekly-run.md, "Dayparting bid consistency"): a run compares
each enabled live keyword with its Scale Insights row. When most read the stored bid, there is no modifier. When at least
half read the stored bid times one common factor, that factor is the modifier: a row that matches takes its stored bid, and
a live-only row (or one written since Scale Insights last synced) takes its live bid divided by the factor. Anything else
is mixed: the live bids stay as read, and the run says so."""

TOL = 0.011  # a cent of rounding on either side


def detect(pairs, min_rows=10, same_share=0.8, modifier_share=0.5):
    """pairs: [(stored bid, live bid)] of enabled rows on both sides. Returns (factor, status): (1.0, 'none') when the live
    bids are the stored ones, (m, 'modifier') when at least modifier_share of the rows read stored x m for one m away from
    1, (1.0, 'mixed') otherwise, and (1.0, 'too_few') under min_rows."""
    rows = [(s, l) for s, l in pairs if s and l and s > 0 and l > 0]
    if len(rows) < min_rows:
        return 1.0, 'too_few'
    if sum(abs(l - s) <= TOL for s, l in rows) >= same_share * len(rows):
        return 1.0, 'none'
    ratios = sorted(l / s for s, l in rows if abs(l - s) > TOL)
    m = round(ratios[len(ratios) // 2], 2)
    if abs(m - 1) > 0.02 and sum(matches(s, l, m) for s, l in rows) >= modifier_share * len(rows):
        return m, 'modifier'
    return 1.0, 'mixed'


def matches(stored, live, m):
    """The live bid is the stored bid under modifier m (Amazon rounds to the cent)."""
    return abs(live - round(stored * m, 2)) <= TOL


CUT_RANGE = (0.5, 0.95)  # a dayparting modifier the data may show: a cut of 5% to 50%


def modifiers(cfg):
    """The dayparting modifiers other than 1.0 in config.json `write_window` (rule 203: the weekend 0.8 since 2026-10-31; 0.6 before). Only a starting
    point: common_factor reads the modifier actually on the bids, so a weekend cut changed in Scale Insights (Kim,
    2026-10-26: "I might tweak it to -20% or -25%") is recognised before anyone edits config.json."""
    mods = ((cfg or {}).get('write_window') or {}).get('modifier') or {'weekend': 0.8}
    return sorted({float(v) for v in mods.values() if abs(float(v) - 1) > 0.02})


def common_factor(pairs, mods=(), min_rows=3, share=0.8):
    """The modifiers that explain the moved bids in `pairs` [(before, after)]: `mods` plus the factor the rows themselves
    show. Each moved row (before and after a cent or more apart) gives min(after/before, before/after), so a modifier
    coming on and one coming off read the same; the median, to the cent, is the factor when at least `min_rows` and
    `share` of the moved rows fit it and it is a cut of 5% to 50% (CUT_RANGE). So a -25% weekend reads 0.75 from the
    bids, and its base is the live bid / 0.75, never / 0.6 (no "double minus")."""
    moved = [(b, a) for b, a in pairs if b and a and b > 0 and a > 0 and abs(a - b) > TOL]
    out = sorted(set(mods))
    if len(moved) < min_rows:
        return out
    ratios = sorted(min(a / b, b / a) for b, a in moved)
    m = round(ratios[len(ratios) // 2], 2)
    fit = sum(matches(b, a, m) or matches(a, b, m) for b, a in moved)
    if CUT_RANGE[0] <= m <= CUT_RANGE[1] and fit >= share * len(moved) and m not in out:
        out = sorted(out + [m])
    return out


def switch_moved(before, after, mods):
    """True when a bid moved from `before` to `after` by a Scale Insights dayparting switch, not by a person or a rule:
    `after` is `before` x m (the modifier came on) or `before` is `after` x m (it came off: the weekend $0.96 back to the
    $1.60 base at Mon 21:00 SGT), for a modifier m of the schedule (decision 152). Such a move is expected."""
    if before is None or after is None or before <= 0 or after <= 0:
        return False
    return any(matches(before, after, m) or matches(after, before, m) for m in mods)


def base(stored, live, m):
    """The base bid behind a live bid under modifier m: the stored bid when the live one is the stored bid (a bid written
    under the modifier that Scale Insights took as its base before re-applying the modifier on top: B0SAMP0015, 2026-10-26,
    240 of 241 written rows) or the stored bid x m, else live / m."""
    if m == 1.0 or live is None:
        return live
    if stored and (abs(live - stored) <= TOL or matches(stored, live, m)):
        return stored
    return max(0.02, round(live / m, 2))
