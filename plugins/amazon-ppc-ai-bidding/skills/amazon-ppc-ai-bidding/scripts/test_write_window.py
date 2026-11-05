"""Decision 151 (Kim, 2026-10-26): the skill keeps bid writes clear of Scale Insights' dayparting switches itself.
Rule 203's schedule (config.json write_window), the hold before an ON switch, the re-check after one, and the dated
open items the morning routine picks up."""
import contextlib
import datetime as dt
import io
import json
import os
import tempfile
import unittest

import autonomy
import dashboard
import daypart_base as D
import lanes
import routine
import write_window as W

WW = W.settings(autonomy.config())


def at(text):
    return dt.datetime.fromisoformat(text)


class ScheduleTest(unittest.TestCase):
    def test_the_schedule_is_rule_203(self):
        self.assertEqual(WW['on_hours'], {'weekday': [6, 21], 'weekend': [5, 21]})
        # weekends -20% since Kim changed rule 203 on 2026-10-31 (decision 174); -40% (0.6) from 2026-10-26
        self.assertEqual(WW['modifier'], {'weekday': 1.0, 'weekend': 0.8})

    def test_the_weekend_modifier_stays_on_the_live_bids_until_monday_06_pt(self):
        self.assertEqual(W.modifier_at(at('2026-10-26T20:40+08:00'), WW), 0.8)   # Mon 05:40 PDT, OFF since Sunday
        self.assertEqual(W.modifier_at(at('2026-10-26T21:05+08:00'), WW), 1.0)
        self.assertEqual(W.modifier_at(at('2026-10-31T20:30+08:00'), WW), 0.8)   # Sat 05:30 PDT

    def test_the_switches_in_singapore_time(self):
        edges = [(e['kind'], W.sgt(e['utc'])) for e in W.upcoming(at('2026-10-30T12:00+08:00'), WW, horizon=36)]
        self.assertEqual(edges, [('off', 'Fri 2026-10-30 13:00 SGT'), ('on', 'Fri 2026-10-30 21:00 SGT'),
                                 ('off', 'Sat 2026-10-31 13:00 SGT'), ('on', 'Sat 2026-10-31 20:00 SGT')])

    def test_switches_move_an_hour_later_after_us_clocks_go_back(self):
        edges = [W.sgt(e['utc']) for e in W.upcoming(at('2026-11-03T12:00+08:00'), WW, horizon=12) if e['kind'] == 'on']
        self.assertEqual(edges, ['Tue 2026-11-03 22:00 SGT'])


class CheckTest(unittest.TestCase):
    def test_a_write_in_the_two_hours_before_an_on_switch_is_held(self):
        res = W.check(at('2026-10-26T20:40+08:00'), WW)
        self.assertEqual((res['status'], res['safe_from']), ('hold', 'Mon 2026-10-26 22:00 SGT'))
        self.assertIn('2 hours', res['why'])
        self.assertEqual(W.check(at('2026-10-31T18:30+08:00'), WW)['safe_from'], 'Sat 2026-10-31 21:00 SGT')

    def test_the_hour_after_an_on_switch_is_held_while_scale_insights_re_sends_the_bids(self):
        # decision 152: at 21:05 SGT on Oct 26 SP bids were back at base but SB bids still read base x 0.6
        res = W.check(at('2026-10-26T21:05+08:00'), WW)
        self.assertEqual((res['status'], res['safe_from'], res['last_switch']['at']),
                         ('hold', 'Mon 2026-10-26 22:00 SGT', 'Mon 2026-10-26 21:00 SGT'))
        self.assertIn('SB after SP', res['why'])

    def test_after_the_settle_hour_the_window_is_open(self):
        res = W.check(at('2026-10-26T22:00+08:00'), WW)
        self.assertEqual(res['status'], 'ok')
        self.assertNotIn('recheck_after', res)

    def test_the_team_day_is_open_and_flags_a_recheck_near_a_switch(self):
        for t in ('10:00', '12:30', '14:00', '18:30'):
            self.assertEqual(W.check(at(f'2026-10-27T{t}+08:00'), WW)['status'], 'ok', t)
        self.assertEqual(W.check(at('2026-10-27T12:00+08:00'), WW)['recheck_after'], 'Tue 2026-10-27 13:15 SGT')
        self.assertEqual(W.check(at('2026-10-27T18:00+08:00'), WW)['recheck_after'], 'Tue 2026-10-27 21:15 SGT')
        self.assertNotIn('recheck_after', W.check(at('2026-10-27T15:00+08:00'), WW))


class RecheckTest(unittest.TestCase):
    WRITTEN = [{'keywordId': 1, 'bid': 0.40}, {'keywordId': 2, 'bid': 0.57}, {'keywordId': 3, 'bid': 0.80},
               {'targetId': 4, 'bid': 0.30}, {'keywordId': 5, 'state': 'paused'}]

    def test_written_or_written_times_the_modifier_holds_else_it_was_put_back(self):
        live = [{'keywordId': '1', 'bid': 0.24}, {'keywordId': '2', 'bid': 0.57}, {'keywordId': '3', 'bid': 0.5},
                {'keywordId': '5', 'state': 'PAUSED'}]
        out = W.reverted(self.WRITTEN, live, 0.6)
        self.assertEqual([(r['id'], r['live']) for r in out], [('3', 0.5), ('4', None)])

    def test_recheck_writes_the_rows_to_send_again_by_payload_file(self):
        with tempfile.TemporaryDirectory() as run:
            os.makedirs(os.path.join(run, 'payloads', 'auto'))
            for name, rows in (('1_sp_keyword_updates.json', self.WRITTEN[:3]), ('2_sp_target_updates.json', self.WRITTEN[3:4]),
                               ('rows.json', [{'keywordId': 3, 'bid': 9}])):
                with open(os.path.join(run, 'payloads', 'auto', name), 'w') as fh:
                    json.dump(rows, fh)
            live = [{'keywordId': '1', 'bid': 0.4}, {'keywordId': '2', 'bid': 0.57}, {'keywordId': '3', 'bid': 0.5},
                    {'targetId': '4', 'bid': 0.3}]
            out = W.recheck(run, 'auto', live, at('2026-10-27T10:30+08:00'), WW)
            self.assertEqual((out['checked'], out['reverted'], out['modifier']), (4, 1, 1.0))
            with open(out['resend']) as fh:
                self.assertEqual(json.load(fh), {'1_sp_keyword_updates.json': [{'keywordId': 3, 'bid': 0.8}]})


class OpenItemTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, 'asins'))
        self.path = os.path.join(self.tmp.name, 'asins', 'B0TEST0001.json')
        with open(self.path, 'w') as fh:
            json.dump({'asin': 'B0TEST0001', 'open_items': []}, fh, indent=1)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = W.main(list(args) + ['--asin', 'B0TEST0001', '--run', 'runs/B0TEST0001-2026-10-26',
                                        '--data', self.tmp.name])
        return code, json.loads(out.getvalue())

    def items(self):
        with open(self.path) as fh:
            return json.load(fh)['open_items']

    def test_park_adds_one_dated_item_the_routine_lists(self):
        code, res = self.run_cli('park', '--now', '2026-10-26T20:40+08:00')
        self.assertEqual((code, res['added']), (0, True))
        self.run_cli('park', '--now', '2026-10-26T20:45+08:00')
        items = self.items()
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]['short'], items[0]['due']), ('Apply held auto rows after 22:00 SGT', '2026-10-26'))
        with open(self.path) as fh:
            listed = routine.work_list([json.load(fh)], '2026-10-27')
        self.assertEqual(listed['checks'][0]['items'][0]['what'], 'Apply held auto rows after 22:00 SGT')

    def test_park_refuses_when_the_window_is_open(self):
        with self.assertRaises(SystemExit):
            self.run_cli('park', '--now', '2026-10-27T15:00+08:00')
        self.assertEqual(self.items(), [])

    def test_after_apply_adds_a_recheck_only_near_a_switch(self):
        self.assertFalse(self.run_cli('after-apply', '--now', '2026-10-27T15:00+08:00')[1]['added'])
        self.assertTrue(self.run_cli('after-apply', '--now', '2026-10-27T18:00+08:00')[1]['added'])
        self.assertEqual([(i['short'], i['due']) for i in self.items()],
                         [('Re-check auto bids after the 21:00 SGT switch', '2026-10-27')])

    def test_check_exits_3_on_hold(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(W.main(['check', '--now', '2026-10-26T20:40+08:00']), 3)
            self.assertEqual(W.main(['check', '--now', '2026-10-26T22:05+08:00']), 0)



class DaypartSwitchTest(unittest.TestCase):
    """Decision 152 (Kim, 2026-10-26): a live bid that moved between base and base x the weekend modifier at a Scale
    Insights switch is expected. Codex's B0SAMP0032 run stopped on 22 SB rows that went from USD 0.96 back to their USD 1.60
    base under the -40% weekend (0.6); since 2026-10-31 (decision 174) the weekend is -20%, so the same row reads USD 1.28."""
    MODS = D.modifiers(autonomy.config())

    def test_the_schedule_modifiers(self):
        self.assertEqual(self.MODS, [0.8])

    def test_a_move_by_the_modifier_either_way_is_a_switch(self):
        for before, after in ((1.28, 1.60), (1.60, 1.28), (0.74, 0.92), (0.92, 0.74)):
            self.assertTrue(D.switch_moved(before, after, self.MODS), (before, after))
        for before, after in ((1.28, 1.45), (1.28, 1.28), (None, 1.6), (1.28, 0)):
            self.assertFalse(D.switch_moved(before, after, self.MODS), (before, after))
        # the old -40% weekend is no longer the schedule's, but the code still knows it when given it
        self.assertTrue(D.switch_moved(0.96, 1.60, [0.6]))

    def test_the_read_back_takes_the_written_bid_under_the_modifier_as_written(self):
        written = [{'keywordId': 1, 'bid': 1.60}, {'keywordId': 2, 'bid': 1.60}]
        live = [{'keywordId': '1', 'bid': 1.28}, {'keywordId': '2', 'bid': 1.20}]
        self.assertEqual([m['id'] for m in lanes.readback_mismatches(written, live, self.MODS)], ['2'])
        self.assertEqual(len(lanes.readback_mismatches(written, live)), 2)

    def test_the_drift_check_names_a_switch_as_expected(self):
        change = {'type': 'SB bid change', 'keyword_id': '7', 'current': 1.28}
        why = dashboard.drift_reason(change, {'7': {'keywordId': '7', 'bid': 1.60, 'state': 'ENABLED'}}, self.MODS)
        self.assertTrue(why.startswith(dashboard.DAYPART_SWITCH), why)
        why = dashboard.drift_reason(change, {'7': {'keywordId': '7', 'bid': 1.30, 'state': 'ENABLED'}}, self.MODS)
        self.assertTrue(why.startswith('changed since the plan'), why)


    def test_a_changed_weekend_cut_is_read_from_the_bids(self):
        # Kim, 2026-10-26: the weekend cut may become -20% or -25%; the rows show it before config.json is updated
        pairs = [(1.60, 1.20), (0.80, 0.60), (0.40, 0.30), (1.00, 0.75), (0.52, 0.39)]
        self.assertEqual(D.common_factor(pairs, self.MODS), [0.75, 0.8])
        self.assertEqual(D.common_factor([(b, round(b * 0.8, 2)) for b, _ in pairs]), [0.8])
        self.assertEqual(D.common_factor([(1.20, 1.60), (0.60, 0.80), (0.30, 0.40)]), [0.75])   # coming off: the same
        # scattered moves are not a modifier, and too few rows say nothing
        self.assertEqual(D.common_factor([(1.0, 0.5), (1.0, 0.9), (1.0, 0.7), (1.0, 0.62)], self.MODS), [0.8])
        self.assertEqual(D.common_factor([(1.6, 1.2)], self.MODS), [0.8])

    def test_the_read_back_takes_a_changed_weekend_cut_as_written(self):
        written = [{'keywordId': i, 'bid': b} for i, b in enumerate((1.60, 0.80, 0.40, 1.00))]
        live = [{'keywordId': str(i), 'bid': round(b * 0.75, 2)} for i, b in enumerate((1.60, 0.80, 0.40, 1.00))]
        with tempfile.TemporaryDirectory() as run:
            os.makedirs(os.path.join(run, 'payloads', 'auto'))
            with open(os.path.join(run, 'payloads', 'auto', '1_sp_keyword_updates.json'), 'w') as fh:
                json.dump(written, fh)
            path = os.path.join(run, 'B0TEST0001.json')
            with open(path, 'w') as fh:
                json.dump({'asin': 'B0TEST0001'}, fh)
            res = autonomy.readback(path, run, 'auto', live, '2026-10-31', shared=autonomy.config(), dry_run=True)
        self.assertEqual(res['mismatches'], [])

class PrewriteTest(unittest.TestCase):
    def run_prewrite(self, live_bids):
        with tempfile.TemporaryDirectory() as run:
            os.makedirs(os.path.join(run, 'payloads', 'auto'))
            changes = [{'row_id': 'r1', 'type': 'SB bid change', 'keyword_id': '1', 'current': 1.28, 'new': 1.40},
                       {'row_id': 'r2', 'type': 'Bid change', 'keyword_id': '2', 'current': 0.50, 'new': 0.45},
                       {'row_id': 'r3', 'type': 'Negative exact', 'keyword': 'x'}]
            for name, data in (('plan.json', {'changes': changes}),
                               (os.path.join('payloads', 'auto', 'rows.json'),
                                {'8_sb_keyword_updates.json': ['r1'], '1_sp_keyword_updates.json': ['r2'],
                                 '3_negatives.json': ['r3']})):
                with open(os.path.join(run, name), 'w') as fh:
                    json.dump(data, fh)
            live = os.path.join(run, 'live.json')
            with open(live, 'w') as fh:
                json.dump([{'keywordId': k, 'bid': b, 'state': 'ENABLED'} for k, b in live_bids.items()], fh)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = W.main(['prewrite', '--run', run, '--live', live])
            return code, json.loads(out.getvalue())

    def test_unchanged_bids_apply(self):
        code, res = self.run_prewrite({'1': 1.28, '2': 0.50})
        self.assertEqual((code, res['verdict'], res['same'], res['not_checked']), (0, 'apply', 2, 1))

    def test_only_a_dayparting_switch_means_plan_again_not_stop(self):
        code, res = self.run_prewrite({'1': 1.60, '2': 0.50})
        self.assertEqual((code, res['verdict'], [r['row_id'] for r in res['switch']]), (4, 'replan', ['r1']))
        self.assertIn('not a question for a person', res['next'])

    def test_any_other_change_stops(self):
        code, res = self.run_prewrite({'1': 1.60, '2': 0.70})
        self.assertEqual((code, res['verdict'], [r['row_id'] for r in res['changed']]), (5, 'stop', ['r2']))

    def test_a_changed_weekend_cut_coming_off_is_still_a_switch(self):
        # the planned bids at x0.75 (a -25% weekend), live back at base after the Monday switch
        with tempfile.TemporaryDirectory() as run:
            os.makedirs(os.path.join(run, 'payloads', 'auto'))
            changes = [{'row_id': f'r{i}', 'type': 'SB bid change', 'keyword_id': str(i), 'current': c, 'new': c}
                       for i, c in enumerate((1.20, 0.60, 0.30, 0.75))]
            with open(os.path.join(run, 'plan.json'), 'w') as fh:
                json.dump({'changes': changes}, fh)
            with open(os.path.join(run, 'payloads', 'auto', 'rows.json'), 'w') as fh:
                json.dump({'8_sb_keyword_updates.json': [c['row_id'] for c in changes]}, fh)
            live = [{'keywordId': str(i), 'bid': b, 'state': 'ENABLED'} for i, b in enumerate((1.60, 0.80, 0.40, 1.00))]
            res = W.prewrite(run, 'auto', live, D.modifiers(autonomy.config()))
        self.assertEqual((res['verdict'], len(res['switch']), res['modifiers']), ('replan', 4, [0.75, 0.8]))

    def test_a_weekend_live_bid_at_current_x_0_8_is_a_switch_not_a_stop(self):
        # Kim, 2026-10-31 (decision 174): rule 203's weekend is -20%, so at the Saturday ON switch a live bid reads the
        # plan's current x 0.8. That is dayparting: replan (exit 4), never stop (exit 5)
        bases = (1.60, 0.80, 0.45, 1.00, 0.52)
        with tempfile.TemporaryDirectory() as run:
            os.makedirs(os.path.join(run, 'payloads', 'auto'))
            changes = [{'row_id': f'r{i}', 'type': 'Bid change', 'keyword_id': str(i), 'current': b, 'new': b}
                       for i, b in enumerate(bases)]
            with open(os.path.join(run, 'plan.json'), 'w') as fh:
                json.dump({'changes': changes}, fh)
            with open(os.path.join(run, 'payloads', 'auto', 'rows.json'), 'w') as fh:
                json.dump({'1_sp_keyword_updates.json': [c['row_id'] for c in changes]}, fh)
            live = os.path.join(run, 'live.json')
            with open(live, 'w') as fh:
                json.dump([{'keywordId': str(i), 'bid': round(b * 0.8, 2), 'state': 'ENABLED'} for i, b in enumerate(bases)], fh)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = W.main(['prewrite', '--run', run, '--live', live])
        res = json.loads(out.getvalue())
        self.assertEqual((code, res['verdict'], len(res['switch']), res['changed']), (4, 'replan', 5, []))
        self.assertIn(0.8, res['modifiers'])
        # one row alone (too few for the bids to show a factor) is still a switch: 0.8 is the schedule's own modifier
        self.assertTrue(D.switch_moved(1.60, 1.28, D.modifiers(autonomy.config())))


class ModifierToModifierTest(unittest.TestCase):
    """Kim, 2026-10-26: "if it is 0.75 moving to 0.6, it can also be 0.6 moving to 0.75". Under a modifier the plan's
    current is the base (decision 150), so a live bid at base x the plan's factor has not moved, and one at base x another
    modifier is a dayparting switch, in either direction."""
    BASES = (1.60, 0.80, 0.40, 1.00)

    def run_prewrite(self, plan_factor, live_factor):
        with tempfile.TemporaryDirectory() as run:
            os.makedirs(os.path.join(run, 'payloads', 'auto'))
            changes = [{'row_id': f'r{i}', 'type': 'Bid change', 'keyword_id': str(i), 'current': b, 'new': b}
                       for i, b in enumerate(self.BASES)]
            plan = {'changes': changes,
                    'summary': [{'inventory': {'daypart': {'status': 'modifier', 'factor': plan_factor}}}]}
            with open(os.path.join(run, 'plan.json'), 'w') as fh:
                json.dump(plan, fh)
            with open(os.path.join(run, 'payloads', 'auto', 'rows.json'), 'w') as fh:
                json.dump({'1_sp_keyword_updates.json': [c['row_id'] for c in changes]}, fh)
            live = [{'keywordId': str(i), 'bid': round(b * live_factor, 2), 'state': 'ENABLED'}
                    for i, b in enumerate(self.BASES)]
            return W.prewrite(run, 'auto', live, D.modifiers(autonomy.config()))

    def test_still_under_the_plans_own_modifier_is_unchanged(self):
        for factor in (0.6, 0.75, 0.8):
            res = self.run_prewrite(factor, factor)
            self.assertEqual((res['verdict'], res['same']), ('apply', 4), factor)

    def test_a_move_between_two_modifiers_either_way_is_a_switch(self):
        for before, after in ((0.75, 0.6), (0.6, 0.75), (0.8, 0.6), (0.6, 0.8), (1.0, 0.75)):
            res = self.run_prewrite(before, after)
            self.assertEqual((res['verdict'], len(res['switch'])), ('replan', 4), (before, after))
        # the modifier coming off after a plan made under it: live is back at the base the plan priced from
        self.assertEqual(self.run_prewrite(0.6, 1.0)['verdict'], 'apply')

    def test_the_drift_check_takes_the_plans_factor(self):
        change = {'type': 'Bid change', 'keyword_id': '7', 'current': 1.60}
        live = lambda bid: {'7': {'keywordId': '7', 'bid': bid, 'state': 'ENABLED'}}  # noqa: E731
        self.assertIsNone(dashboard.drift_reason(change, live(1.20), [0.6], 0.75))
        self.assertTrue(dashboard.drift_reason(change, live(0.96), [0.6], 0.75).startswith(dashboard.DAYPART_SWITCH))
        self.assertTrue(dashboard.drift_reason(change, live(1.20), [0.6, 0.75], 0.6).startswith(dashboard.DAYPART_SWITCH))
        self.assertTrue(dashboard.drift_reason(change, live(1.05), [0.6, 0.75], 0.6).startswith('changed since the plan'))

    def test_an_unrebased_bid_moving_between_modifiers_reads_as_the_ratio(self):
        # an SB bid planned at 0.96 (base 1.60 x 0.6) that now reads 1.20 (base x 0.75): the rows share 0.8
        pairs = [(round(b * 0.6, 2), round(b * 0.75, 2)) for b in self.BASES]
        mods = D.common_factor(pairs, [0.6])
        self.assertIn(0.8, mods)
        self.assertTrue(all(D.switch_moved(b, a, mods) for b, a in pairs))

    def test_the_read_back_takes_a_written_bid_under_any_modifier(self):
        for factor in (0.6, 0.75, 0.8):
            written = [{'keywordId': i, 'bid': b} for i, b in enumerate(self.BASES)]
            live = [{'keywordId': str(i), 'bid': round(b * factor, 2)} for i, b in enumerate(self.BASES)]
            mods = D.common_factor(autonomy._lower_pairs(written, live), [0.6])
            self.assertEqual(lanes.readback_mismatches(written, live, mods), [], factor)

if __name__ == '__main__':
    unittest.main()
