"""Autonomous runs (Kim, 2026-10-22, decision 98; docs/superpowers/specs/2026-10-22-autonomous-runs-design.md): the run
applies its own Auto rows. These tests cover what the design added: the guards in autonomy.py (switch_off, day1, readback,
program_month, the stock item), the program total on the run summary (information only since decision 99), the stop-loss
step-downs and the 8-week re-investment cool-off after one, the manifest's per-folder approval flags and the Scale Insights
checklist, the Bids item carrying only the rows parked for a person, and `dashboard.py applied --folder auto` refusing a
product whose Auto is off."""
import argparse
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

import autonomy
import dashboard
import human_review
import lanes
import plan as planner
import plan_lanes
import test_dashboard_approvals as D
import test_plan_lanes as T

ASIN = T.ASIN


def read_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1)


SHARED = T.shared_config()


class Folder(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.data = os.path.join(self.tmp, 'data')
        self.run_dir = os.path.join(self.tmp, 'run')
        self.product_file = os.path.join(self.data, 'asins', f'{ASIN}.json')

    def write_product(self, **over):
        write_json(self.product_file, T.product(**over))
        return self.product_file

    def product(self):
        return read_json(self.product_file)

    def plan(self, cfg=None, inputs=None, write_out=True, **run):
        """build() without the lanes, then the lanes with `inputs` added to the run's own (the program, say)."""
        T.make_run(self.run_dir, **run)
        cfg = cfg or T.product()
        out = planner.build(ASIN, cfg, SHARED, self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW, with_lanes=False)
        lane_inputs = planner.load_lane_inputs(self.run_dir)
        lane_inputs.update(inputs or {})
        plan_lanes.assign(out, cfg, SHARED, 'weekly', lane_inputs, T.TODAY, T.NOW)
        if write_out:
            planner.write_outputs(self.run_dir, out, SHARED, ASIN)
        return out


# ----------------------------------------------------------------------------- the guards
class SwitchOffTest(Folder):
    def test_switch_off_sets_the_kill_switch_and_raises_one_decision_for_the_book_owner(self):
        path = self.write_product()
        self.assertTrue(plan_lanes.auto_enabled(SHARED, self.product()))
        out = autonomy.switch_off(path, 'Read-back mismatch after the apply of payloads/auto/ (1 of 4 rows not as written)',
                                  '2026-10-23', SHARED)
        self.assertEqual((out['was_on'], out['entry_added']), (True, True))
        product = self.product()
        self.assertIs(product['auto']['enabled'], False)
        self.assertEqual(product['auto']['switched_off']['on'], '2026-10-23')
        self.assertEqual(product['auto']['prove_index'], T.AUTO['prove_index'])  # the rest of the block is kept
        self.assertFalse(plan_lanes.auto_enabled(SHARED, product))
        [entry] = [o for o in product['open_items'] if o['status'] == 'decision']
        self.assertTrue(entry['short'].startswith('Auto off: Read-back mismatch'), entry['short'])
        self.assertEqual((entry['opened'], entry['workflow']['lane'], entry['workflow']['kind']), ('2026-10-23', 'human', 'auto_off'))
        self.assertIn('Kim turns Auto back on', entry['text'])
        # the next plan is a shadow plan: every row a proposal, auto/ empty
        plan = self.plan(cfg=product)
        self.assertIs(plan['summary'][0]['shadow'], True)
        self.assertEqual(os.listdir(os.path.join(self.run_dir, 'payloads', 'auto')), [])
        # running it twice the same day adds no second decision
        autonomy.switch_off(path, 'Read-back mismatch after the apply of payloads/auto/ (1 of 4 rows not as written)',
                            '2026-10-23', SHARED)
        self.assertEqual(len([o for o in self.product()['open_items'] if o['status'] == 'decision']), 1)

    def test_a_dry_run_writes_nothing(self):
        path = self.write_product()
        before = open(path, encoding='utf-8').read()
        autonomy.switch_off(path, 'test', '2026-10-23', SHARED, dry_run=True)
        self.assertEqual(open(path, encoding='utf-8').read(), before)

    def test_the_owner_on_the_decision_is_the_book_owner(self):
        path = self.write_product(registry=dict(bid_owner='AI', stage='ai', owner_since='2026-09-01', book_owner='Alex'))
        autonomy.switch_off(path, 'test', '2026-10-23', SHARED)
        [entry] = [o for o in self.product()['open_items'] if o['status'] == 'decision']
        self.assertEqual(entry['workflow']['owner'], 'Alex')


SWITCH_OFF = dict(SHARED, guards=dict(day1_switch_off=True, readback_switch_off=True))   # the rule before decision 163


class Day1Test(Folder):
    def test_a_spend_jump_opens_an_alert_and_auto_stays_on(self):
        # decision 163 (2026-10-29): the Day-1 check no longer switches Auto off
        path = self.write_product()
        out = autonomy.day1(path, 31.0, [10, 12, 8, 10, 10], '2026-10-23', applied_on='2026-10-21', shared=SHARED)
        self.assertEqual((out['tripped'], out['average'], out['ratio'], out['switched_off']), (True, 10.0, 3.1, None))
        self.assertTrue(plan_lanes.auto_enabled(SHARED, self.product()))
        [entry] = [o for o in self.product()['open_items'] if o['status'] == 'decision']
        self.assertEqual(entry['workflow']['kind'], 'day1_spend')
        self.assertIn('Day-1 spend check after the apply of 2026-10-21: $31.00 on the first US weekday against a $10.00 '
                      'weekday average', entry['text'])
        self.assertIn('Auto stays on (decision 163)', entry['text'])

    def test_a_spend_jump_switches_auto_off_when_the_guard_is_set_to(self):
        path = self.write_product()
        out = autonomy.day1(path, 31.0, [10, 12, 8, 10, 10], '2026-10-23', applied_on='2026-10-21', shared=SWITCH_OFF)
        self.assertTrue(out['tripped'])
        self.assertIs(self.product()['auto']['enabled'], False)
        [entry] = [o for o in self.product()['open_items'] if o['status'] == 'decision']
        self.assertEqual(entry['workflow']['kind'], 'auto_off')

    def test_spend_inside_one_and_a_half_times_the_average_changes_nothing(self):
        path = self.write_product()
        before = open(path, encoding='utf-8').read()
        for spend, history in ((15.0, [10, 10]), (40.0, [])):  # exactly 1.5x does not trip; no history has nothing to compare
            with self.subTest(spend=spend, history=history):
                out = autonomy.day1(path, spend, history, '2026-10-23', shared=SHARED)
                self.assertEqual((out['tripped'], out['switched_off']), (False, None))
        self.assertEqual(open(path, encoding='utf-8').read(), before)

    def test_the_cli_reads_the_history_and_prints_the_result(self):
        self.write_product()
        skill = os.path.join(self.tmp, 'skill')
        write_json(os.path.join(skill, 'config.json'), SHARED)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            autonomy.main(['--skill', skill, 'day1', '--asin', ASIN, '--data', self.data, '--spend', '30',
                           '--history', '10,10,10', '--date', '2026-10-23'])
        self.assertIs(json.loads(out.getvalue())['tripped'], True)
        self.assertTrue(plan_lanes.auto_enabled(SHARED, self.product()))


class ReadbackTest(Folder):
    def test_a_mismatch_switches_auto_off_and_a_match_does_not(self):
        path = self.write_product()
        self.plan()
        written = autonomy.folder_rows(self.run_dir, 'auto')
        self.assertTrue(written)
        live = [dict(r, bid=r.get('bid')) for r in written]
        out = autonomy.readback(path, self.run_dir, 'auto', live, '2026-10-20', SHARED)
        self.assertEqual((out['mismatches'], out['switched_off']), ([], None))
        self.assertTrue(plan_lanes.auto_enabled(SHARED, self.product()))
        wrong = copy.deepcopy(live)
        first_bid = next(r for r in wrong if r.get('bid') is not None)
        first_bid['bid'] = round(first_bid['bid'] + 0.10, 2)
        out = autonomy.readback(path, self.run_dir, 'auto', wrong, '2026-10-20', SHARED)
        self.assertEqual(len(out['mismatches']), 1)
        self.assertTrue(out['stop'])
        # decision 163: a real mismatch stops the folder and opens an alert; Auto stays on
        self.assertTrue(plan_lanes.auto_enabled(SHARED, self.product()))
        [entry] = [o for o in self.product()['open_items'] if o['status'] == 'decision']
        self.assertEqual(entry['workflow']['kind'], 'readback')
        autonomy.readback(path, self.run_dir, 'auto', wrong, '2026-10-20', SWITCH_OFF)
        self.assertIs(self.product()['auto']['enabled'], False)

    def test_a_file_that_does_not_cover_the_folder_is_an_input_error_not_a_trip(self):
        # the 2026-10-28 B0SAMP0026 trip: a shape the read missed, so every row read as missing
        path = self.write_product()
        self.plan()
        before = open(path, encoding='utf-8').read()
        with self.assertRaises(autonomy.ReadbackInputError):
            autonomy.readback(path, self.run_dir, 'auto', [], '2026-10-20', SWITCH_OFF)
        with open(path, encoding='utf-8') as fh:
            self.assertEqual(fh.read(), before)

    def test_every_saved_shape_reads_the_same_rows(self):
        self.write_product()
        self.plan()
        live = [dict(r) for r in autonomy.folder_rows(self.run_dir, 'auto')]
        text = json.dumps(dict(items=live, total_count=len(live)))
        shapes = dict(plain=live, items=dict(items=live), data=dict(data=live), results=dict(results=live),
                      wrapper=[dict(type='text', text=text)], content=dict(content=[dict(type='text', text=text)]),
                      structured=dict(structuredContent=dict(items=live)), several=[dict(items=live[:1]), dict(items=live[1:])])
        for name, data in shapes.items():
            with self.subTest(shape=name):
                f = os.path.join(self.tmp, f'live_{name}.json')
                write_json(f, data)
                self.assertEqual([lanes._row_id(r) for r in autonomy.read_live(f)], [lanes._row_id(r) for r in live])

    def test_rows_held_by_hand_are_skipped(self):
        path = self.write_product()
        self.plan()
        written = autonomy.folder_rows(self.run_dir, 'auto')
        held = next(r for r in written if r.get('bid') is not None)
        live = [dict(r) for r in written if r is not held]
        out = autonomy.readback(path, self.run_dir, 'auto', live, '2026-10-20', SWITCH_OFF, skip=[lanes._row_id(held)])
        self.assertEqual((out['mismatches'], out['skipped'], out['switched_off']), ([], [lanes._row_id(held)], None))
        self.assertTrue(plan_lanes.auto_enabled(SHARED, self.product()))

    def test_the_scale_insights_checklist_is_not_read_back_as_a_payload(self):
        self.plan(cfg=T.product(), extra={'si_blacklist.json': dict(NegativeExactList=['blank card'], NegativePhraseList=[],
                                                                    ExactWhiteList=[])})
        self.assertTrue(os.path.exists(os.path.join(self.run_dir, 'payloads', 'auto', autonomy.SI_STEPS)))
        self.assertFalse([r for r in autonomy.folder_rows(self.run_dir, 'auto') if r.get('type') is None])


# ----------------------------------------------------------------------------- the $3,000 program level
class ProgramTotalTest(Folder):
    def test_program_month_adds_up_every_other_product_file(self):
        write_json(os.path.join(self.data, 'asins', 'B0OTHER001.json'),
                   dict(asin='B0OTHER001', planned_invest=dict(month=1200.0, as_of='2026-10-20', run='r', basis='plan')))
        write_json(os.path.join(self.data, 'asins', 'B0OTHER002.json'),   # no record yet: its logged searches at their budgets
                   dict(asin='B0OTHER002', invest_log={'a': dict(role='Invest'), 'b': dict(role='Prove first')}))
        write_json(os.path.join(self.data, 'asins', 'B0OTHER003.json'), dict(asin='B0OTHER003'))   # invests in nothing
        self.write_product(planned_invest=dict(month=999.0))   # the product being planned is left out
        out = autonomy.program_month(self.data, ASIN, SHARED)
        self.assertEqual(out['other_month'], 1200.0 + (10 + 5) * 30)
        self.assertEqual(out['products'], [dict(asin='B0OTHER001', month=1200.0, basis='record'),
                                           dict(asin='B0OTHER002', month=450.0, basis='invest log estimate')])

    def test_the_program_total_is_information_only(self):
        # Kim, 2026-10-22, decision 99: no program-wide cap. The total is on the run summary for a person to see; it never
        # parks a promotion (until then a promotion that took the program past $3,000 a month was his)
        plain = self.plan(write_out=False)
        promo = T.one(plain, 'New exact campaign', keyword='blank cards')
        self.assertEqual(promo['lane'], 'auto')
        self.assertIsNone(plain['summary'][0]['program'])   # no other products' total passed: nothing to show
        start = plain['summary'][0]['planned_invest_month_start']
        out = self.plan(inputs=dict(program=dict(other_month=50000, products=[dict(asin='B0OTHER001', month=50000.0,
                                                                                    basis='record')])), write_out=False)
        row = T.one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual(row['lane'], 'auto')
        self.assertNotIn('past_program_level', row)
        self.assertEqual([x['lane'] for x in out['changes']], [x['lane'] for x in plain['changes']])
        self.assertEqual(out['summary'][0]['program'],
                         dict(other_month=50000, start_month=round(50000 + start, 2),
                              after_month=round(50000 + out['summary'][0]['planned_invest_month'], 2),
                              products=[dict(asin='B0OTHER001', month=50000.0, basis='record')]))
        self.assertNotIn('level', out['summary'][0]['program'])
        self.assertFalse(hasattr(lanes, 'past_program_level_text'))
        self.assertNotIn('kim_program_month', SHARED.get('auto') or {})

    def test_an_unreadable_total_shows_as_unknown_and_holds_nothing(self):
        out = self.plan(inputs=dict(program=dict(other_month=None, products=[])), write_out=False)
        self.assertEqual(T.one(out, 'New exact campaign', keyword='blank cards')['lane'], 'auto')
        self.assertEqual(out['summary'][0]['program'],
                         dict(other_month=None, start_month=None, after_month=None, products=[]))

    def test_main_puts_the_other_products_on_the_summary(self):
        T.make_run(self.run_dir)
        self.write_product()
        write_json(os.path.join(self.data, 'asins', 'B0OTHER001.json'), dict(asin='B0OTHER001', planned_invest=dict(month=5000)))
        argv = ['plan.py', '--asin', ASIN, '--run', self.run_dir, '--data', self.data, '--today', T.TODAY]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), T.planned_at(), T.without_mid():
            planner.main()
        plan = read_json(os.path.join(self.run_dir, 'plan.json'))
        self.assertEqual(plan['summary'][0]['program']['other_month'], 5000)
        promo = T.one(plan, 'New exact campaign', keyword='blank cards')
        self.assertEqual(promo['lane'], 'auto')
        self.assertNotIn('past_program_level', promo)

    def test_the_program_cli_prints_the_total_without_a_level(self):
        write_json(os.path.join(self.data, 'asins', 'B0OTHER001.json'), dict(asin='B0OTHER001', planned_invest=dict(month=700.0)))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            autonomy.main(['program', '--asin', ASIN, '--data', self.data])
        out = json.loads(buf.getvalue())
        self.assertEqual(out['other_month'], 700.0)
        self.assertNotIn('level', out)

    def test_planned_invest_record_counts_only_the_promotions_that_went_out(self):
        out = self.plan(write_out=False)
        promo = T.one(out, 'New exact campaign', keyword='blank cards')
        start = out['summary'][0]['planned_invest_month_start']
        self.assertEqual(autonomy.planned_invest_record(out, {}, '2026-10-20')['month'], start)
        rec = autonomy.planned_invest_record(out, {promo['row_id']: '2026-10-20'}, '2026-10-20')
        self.assertEqual(rec, dict(month=round(start + promo['modelled_spend_month'], 2), as_of='2026-10-20',
                                   run=out['summary'][0]['run'], basis='plan'))
        self.assertIsNone(autonomy.planned_invest_record(dict(summary=[{}], changes=[]), {}, '2026-10-20'))


# ----------------------------------------------------------------------------- the re-investment cool-off
class CooloffTest(Folder):
    """Kim, 2026-10-22: a search the stop-loss stepped down is not promoted again by the Auto lane for 8 weeks
    (auto.repromote_cooloff_days 56) after the step-down; inside the window it is held (Monitor), not parked for a person."""
    REASON = 'stepped down at stop-loss on 2026-10-01; held from re-investment until 2026-11-26'

    def history(self, ended, **extra):
        return [dict(dict(search='blank cards', role='Invest', started='2026-08-20', ended=ended, stop_loss=True), **extra)]

    def test_inside_the_window_the_promotion_is_held_with_the_reason(self):
        out = self.plan(cfg=T.product(invest_history=self.history('2026-10-01')), write_out=False)
        row = T.one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual((row['lane'], row['lane_reason']), ('monitor', self.REASON))
        self.assertEqual(out['summary'][0]['repromote_cooloff'], {'blank cards': '2026-11-26'})
        # held, so nothing for a person: the Bids card has no row for it and its bundle stays with it
        item = human_review.propose_bids(out, T.TODAY)
        self.assertNotIn(row['row_id'], [r['row_id'] for r in (item or {}).get('rows') or []])

    def test_after_the_window_it_is_judged_on_the_ladder_again(self):
        # 60 days before TODAY (2026-10-19): the 56 days are over
        out = self.plan(cfg=T.product(invest_history=self.history('2026-08-20')), write_out=False)
        row = T.one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual(row['lane'], 'auto')
        self.assertNotIn('stop-loss', row['lane_reason'])
        self.assertEqual(out['summary'][0]['repromote_cooloff'], {})
        # the last day of the window still holds it; the day it ends does not
        held = self.plan(cfg=T.product(invest_history=self.history('2026-08-25')), write_out=False)
        self.assertEqual(T.one(held, 'New exact campaign', keyword='blank cards')['lane'], 'monitor')
        free = self.plan(cfg=T.product(invest_history=self.history('2026-08-24')), write_out=False)
        self.assertEqual(T.one(free, 'New exact campaign', keyword='blank cards')['lane'], 'auto')

    def test_an_entry_from_before_the_flag_counts_by_its_words(self):
        old = [dict(search='blank cards', role='Invest', started='2026-08-20', ended='2026-10-01',
                    stepped_down='the stop-loss review was approved on 2026-10-01')]
        out = self.plan(cfg=T.product(invest_history=old), write_out=False)
        self.assertEqual(T.one(out, 'New exact campaign', keyword='blank cards')['lane_reason'], self.REASON)
        # an invest a person ended (not the stop-loss) holds nothing
        cut = [dict(search='blank cards', role='Invest', started='2026-08-20', ended='2026-10-01',
                    stepped_down='a person cut it on 2026-10-01')]
        out = self.plan(cfg=T.product(invest_history=cut), write_out=False)
        self.assertEqual(T.one(out, 'New exact campaign', keyword='blank cards')['lane'], 'auto')

    def test_a_shorter_cooloff_in_the_config_is_used(self):
        out = self.plan(cfg=T.product(invest_history=self.history('2026-10-01'),
                                      auto=dict(T.AUTO, repromote_cooloff_days=14)), write_out=False)
        self.assertEqual(T.one(out, 'New exact campaign', keyword='blank cards')['lane'], 'auto')


# ----------------------------------------------------------------------------- stale data and low stock
class StockTest(Folder):
    def test_low_stock_parks_increases_and_raises_one_inventory_item(self):
        # Kim, 2026-10-31 (decision 174): under 14 days of cover the increases wait For human; cuts still go out
        path = self.write_product()
        out = self.plan(extra={'inventory_cover.json': {'cover_days': 9}})
        self.assertIsNone(out['summary'][0]['stale_reason'])
        rs = out['summary'][0]['stock_reorder']
        self.assertEqual((rs['cover_days'], rs['cleared']), (9, None))
        self.assertTrue(rs['held'])
        for x in out['changes']:
            if x['row_id'] in rs['held']:
                self.assertEqual(x['lane'], 'human')
                self.assertIn('low stock: 9 days of cover', x['lane_reason'])
        res = autonomy.stock(path, out, '2026-10-19', SHARED)
        self.assertEqual((res['cover_days'], res['entry_added']), (9, True))
        [entry] = [o for o in self.product()['open_items'] if o['status'] == 'decision']
        self.assertEqual((entry['short'], entry['workflow']['action'], entry['workflow']['kind']),
                         ('Reorder stock: 9 days of cover', 'Reorder stock', 'reorder_stock'))
        self.assertIn("increases", entry['text'])
        self.assertIn('wait For human', entry['text'])
        self.assertIsNot(self.product().get('auto', {}).get('enabled'), False)
        self.assertFalse(autonomy.stock(path, out, '2026-10-19', SHARED)['entry_added'])   # once a day

    def test_other_stale_data_stops_the_run_and_opens_no_item(self):
        # decision 168: a missing inventory file stops an Auto product's run up front, so there is no plan to raise a stock
        # item from (old SQP no longer stops it: decision 172)
        path = self.write_product()
        with self.assertRaises(SystemExit):
            self.plan(lane_files=False)
        self.assertFalse([o for o in self.product().get('open_items') or [] if (o.get('workflow') or {}).get('kind') == 'reorder_stock'])
        self.assertTrue(os.path.exists(path))


# ----------------------------------------------------------------------------- stop-loss step-downs
class StopLossStepDownTest(Folder):
    # 96 days (the month 3 checkpoint), no Rank Radar, organic purchases 0 then and now: no organic gain (decision 142)
    LOGGED = {'thank you cards': dict(since='2026-07-15', role='Invest', organic_then=0)}
    HIGH = [k for k in T.KEYWORDS if k['KeywordId'] != '1'] + [T.keyword('1', 'thank you cards', 'exact', T.SKC, 2.00, 40, 8, 30)]

    def test_the_step_down_rows_apply_on_their_own(self):
        out = self.plan(cfg=T.product(invest_log=self.LOGGED), keywords=self.HIGH)
        rows = [x for x in out['changes'] if x.get('stop_loss_step_down')]
        self.assertEqual(sorted(x['type'] for x in rows), ['Bid change', 'Budget and top of search'])
        bid = next(x for x in rows if x['type'] == 'Bid change')
        camp = next(x for x in rows if x['type'] == 'Budget and top of search')
        self.assertEqual((bid['keyword_id'], bid['role'], bid['current']), ('1', 'Hold', 2.0))
        self.assertLess(bid['new'], bid['current'])
        self.assertEqual(bid['new'], bid['breakeven'])
        self.assertEqual((camp['campaign_id'], camp['tos_now'], camp['tos'], camp['budget_now'], camp['budget']),
                         (T.IDS[T.SKC][0], 50, 0, 10, 5))
        for x in rows:
            self.assertEqual(x['lane'], 'auto', x['lane_reason'])
            self.assertTrue(x['lane_reason'].startswith('invested 96 days (the month 3 checkpoint) with no gain since its start'),
                            x['lane_reason'])
        self.assertFalse(T.by_type(out, 'Stop-loss review'))
        self.assertEqual(out['summary'][0]['stop_loss_step_downs'], 1)
        self.assertEqual(out['stop_loss'][0]['step_down'], 'written')
        auto = [rid for ids in T.read_rows(self.run_dir, 'auto').values() for rid in ids]
        self.assertIn(bid['row_id'], auto)
        self.assertIn(camp['row_id'], auto)
        written = next(r for r in read_json(os.path.join(self.run_dir, 'payloads', 'auto', '5_campaign_updates.json'))
                       if r['campaignId'] == T.IDS[T.SKC][0])
        self.assertEqual(written['budget'], dict(budget=5, budgetType='DAILY'))
        self.assertEqual(written['dynamicBidding']['placementBidding'][0], dict(placement='PLACEMENT_TOP', percentage=0))

    def test_a_search_with_a_gain_is_not_stepped_down(self):
        rank = {'thank you cards': dict(since='2026-07-15', rank_then=40, rank_now=20)}
        out = self.plan(cfg=T.product(invest_log=self.LOGGED), keywords=self.HIGH, extra={'rank_check.json': rank})
        self.assertFalse([x for x in out['changes'] if x.get('stop_loss_step_down')])
        self.assertEqual(out['stop_loss'][0]['gains'], ['organic rank 40 -> 20'])

    def test_a_budget_step_on_the_campaign_is_dropped(self):
        import stop_loss
        changes = [dict(type='Budget step', campaign_id='105', budget=15, budget_now=10)]

        def add(**kw):
            changes.append(kw)
        owner = dict(keyword_id='1', campaign_id='105', breakeven_cpc=0.5, bid=0.9, campaign='SKC', family='SKC')
        done = stop_loss.step_down(changes, add, 'thank you cards', owner, 'why', lambda cid: (10, 50, []), budget_to=5)
        self.assertEqual(done, 'written')
        self.assertEqual(sorted(x['type'] for x in changes), ['Bid change', 'Budget and top of search'])
        self.assertIsNone(stop_loss.step_down([], add, 'x', None, 'why', lambda cid: (None, None, [])))
        nothing = dict(owner, bid=0.5)
        self.assertEqual(stop_loss.step_down([], add, 'x', nothing, 'why', lambda cid: (5, 0, [])), 'nothing to write')

    def test_a_step_down_on_a_keyword_paused_live_stays_paused_and_passes_the_prewrite_check(self):
        # B0SAMP0006, 2026-11-04: the step-down row of a paused owner keyword lacked the paused flag, so the pre-write check
        # read the paused live keyword as drift and stopped the row
        import stop_loss
        import dashboard
        changes = []

        def add(**kw):
            changes.append(kw)
        owner = dict(keyword_id='90000000000013', campaign_id='105', breakeven_cpc=0.06, bid=0.53, campaign='SKC',
                     family='SKC', paused_live=True)
        stop_loss.step_down(changes, add, 'pink planner', owner, 'why', lambda cid: (None, None, []))
        row = next(x for x in changes if x['type'] == 'Bid change')
        self.assertTrue(row['paused'])
        self.assertIn('stays paused', row['how'])
        live = {'90000000000013': dict(state='PAUSED', bid=0.53)}
        self.assertIsNone(dashboard.drift_reason(row, live))
        # an owner keyword that isn't live at all (archived) gets no bid row
        changes.clear()
        stop_loss.step_down(changes, add, 'pink planner', dict(owner, paused_live=False, not_live=True), 'why',
                            lambda cid: (None, None, []))
        self.assertFalse([x for x in changes if x['type'] == 'Bid change'])


# ----------------------------------------------------------------------------- outputs
class OutputsTest(Folder):
    def test_the_manifest_says_which_folder_needs_a_person(self):
        self.plan(**T.HEAD_TERM)   # a one-word search's promotion: rows for a person too (decision 107)
        manifest = read_json(os.path.join(self.run_dir, 'payload_manifest.json'))
        self.assertEqual(manifest['approval_required'], dict(auto=False, review=True, held=None))
        folders = {e['folder'] for e in manifest['files']}
        self.assertEqual(folders, {'auto', 'review'})
        for e in manifest['files']:
            self.assertIs(e['approval_required'], e['folder'] == 'review', e['file'])
        for e in manifest['held_files']:
            self.assertIsNone(e['approval_required'])

    def test_scale_insights_rows_are_a_checklist_recorded_like_any_row(self):
        lists = dict(NegativeExactList=['blank card'], NegativePhraseList=['blank'], ExactWhiteList=[])
        out = self.plan(extra={'si_blacklist.json': lists})
        row = T.one(out, 'Scale Insights setup', step=95)
        self.assertEqual(row['lane'], 'auto')
        steps = read_json(os.path.join(self.run_dir, 'payloads', 'auto', autonomy.SI_STEPS))
        self.assertEqual([s['row_id'] for s in steps], [row['row_id']])
        self.assertEqual((steps[0]['exact_remove'], steps[0]['phrase_remove']), (['blank card'], ['blank']))
        self.assertIn('BlacklistRule/Edit', steps[0]['how'])
        self.assertEqual(T.read_rows(self.run_dir, 'auto')[autonomy.SI_STEPS], [row['row_id']])
        entry = next(e for e in read_json(os.path.join(self.run_dir, 'payload_manifest.json'))['files']
                     if e['file'] == f'auto/{autonomy.SI_STEPS}')
        self.assertEqual((entry['approval_required'], entry['apply_via'][:21]), (False, 'Scale Insights web ap'))

    def test_the_bids_item_carries_only_the_rows_parked_for_a_person(self):
        out = self.plan(write_out=False)
        self.assertIs(out['summary'][0]['shadow'], False)
        self.assertFalse([x for x in out['changes'] if x['lane'] == 'human'])
        self.assertIsNone(human_review.propose_bids(out, T.TODAY))   # nothing parked: no Bids item
        out = self.plan(write_out=False, **T.HEAD_TERM)   # a one-word search's promotion waits for a person
        item = human_review.propose_bids(out, T.TODAY)
        human = {x['row_id'] for x in out['changes'] if x['lane'] == 'human'}
        self.assertTrue(human)
        self.assertEqual({r['row_id'] for r in item['rows']}, human)
        self.assertEqual({r['lane'] for r in item['rows']}, {'human'})
        # Auto switched off (shadow): every row is on the item again, for the team to agree or refuse
        out = self.plan(cfg=T.product(auto=dict(T.AUTO, enabled=False)), write_out=False)
        self.assertEqual(len(human_review.propose_bids(out, T.TODAY)['rows']), len(out['changes']))


# ----------------------------------------------------------------------------- dashboard.py applied --folder auto
class AppliedAutoOffTest(D.Base):
    def applied_refused(self, folder, **over):
        with self.assertRaises(SystemExit) as cm:
            self.run_applied(folder, **over)
        self.assertNotIn(cm.exception.code, (0, None))
        return str(cm.exception.code)

    def test_applied_auto_refuses_a_product_whose_auto_is_off(self):
        self.plan_run(shadow=False)
        rows = [rid for ids in read_json(os.path.join(self.run_dir, 'payloads', 'auto', 'rows.json')).values() for rid in ids]
        self.assertTrue(rows)
        self.assertEqual(self.run_applied('auto', dry_run=True)['dry_run'], True)   # on: the check passes
        product = read_json(self.product_file)
        product['auto'] = dict(product['auto'], enabled=False)   # a guard switched it off (autonomy.switch_off)
        write_json(self.product_file, product)
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                message = self.applied_refused('auto', dry_run=dry_run)
                self.assertIn("Auto lane is off", message)
                self.assertIn('--record-anyway', message)
                self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'payloads', 'applied_rows.json')))
        # what already went out is still recorded, with --record-anyway
        out = self.run_applied('auto', record_anyway=True, rows=[rows[0]])
        self.assertEqual(out['recorded'], 1)
        # config.json off for everyone does the same, whatever the product says
        self.shared = dict(self.shared, auto=dict(self.shared['auto'], enabled=False))
        product['auto'] = {k: v for k, v in product['auto'].items() if k != 'enabled'}
        write_json(self.product_file, product)
        self.assertIn('Auto lane is off', self.applied_refused('auto', dry_run=True))
        # other folders are not affected
        self.assertNotIn('Auto lane is off', json.dumps(self.run_applied('review', dry_run=True)))


if __name__ == '__main__':
    unittest.main()
