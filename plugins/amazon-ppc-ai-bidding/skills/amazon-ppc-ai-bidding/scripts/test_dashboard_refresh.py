"""dashboard.py refresh --run: the product file remembers the run's SQP totals (`sqp_history`) and data stage (`data_stage`).

record_run_history is tested on a product dict and temp run folders (the files plan.py writes: sqp_totals.json, and the
stage on plan.json's summary[0]); cmd_refresh is tested with the server patched out, so nothing touches the network.
"""
import argparse
import contextlib
import datetime
import io
import json
import os
import tempfile
import unittest
import unittest.mock

import dashboard

ASIN = 'B0TEST0004'


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
        fh.write('\n')


def read_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def entry(data_through, clicks=40, purchases=4, queries=12):
    return dict(data_through=data_through, our_clicks=clicks, our_purchases=purchases, queries=queries)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.data = os.path.join(self.tmp, 'data')
        self.product_file = os.path.join(self.data, 'asins', f'{ASIN}.json')
        self.n = 0

    def run_folder(self, data_through='2026-10-18', stage='early', clicks=40, purchases=4, queries=12,
                   totals=True, with_stage=True, asin=ASIN):
        """A run folder as plan.py leaves it. `totals=False` leaves sqp_totals.json out; `with_stage=False` gives the
        plan no stage; `asin` is the product the plan is for (None leaves it out)."""
        self.n += 1
        run = os.path.join(self.tmp, f'run{self.n}')
        os.makedirs(run)
        if totals:
            write_json(os.path.join(run, 'sqp_totals.json'),
                       dict(our_clicks=clicks, our_purchases=purchases, queries=queries, data_through=data_through))
        summary = dict(asin=asin) if asin else {}
        if with_stage:
            summary['stage'] = dict(stage=stage, sqp_queries=queries, observed_days=84, trusted_queries=3, reason='test',
                                    left_launch_this_run=False)
        write_json(os.path.join(run, 'plan.json'), dict(summary=[summary], changes=[]))
        return run


class RecordRunHistory(Base):
    def test_refresh_appends_sqp_history_once_per_data_through(self):
        product = {}
        run = self.run_folder('2026-10-18', clicks=40, purchases=4, queries=12)
        first = dashboard.record_run_history(product, run)
        self.assertTrue(first['sqp_history_appended'])
        self.assertEqual(product['sqp_history'], [entry('2026-10-18')])
        # the same run again: the same data_through never appends twice
        second = dashboard.record_run_history(product, run)
        self.assertFalse(second['sqp_history_appended'])
        self.assertEqual(product['sqp_history'], [entry('2026-10-18')])
        # a newer week appends, an older one does not
        newer = self.run_folder('2026-10-25', clicks=55, purchases=6, queries=15)
        self.assertTrue(dashboard.record_run_history(product, newer)['sqp_history_appended'])
        older = self.run_folder('2026-10-11')
        self.assertFalse(dashboard.record_run_history(product, older)['sqp_history_appended'])
        self.assertEqual(product['sqp_history'], [entry('2026-10-18'), entry('2026-10-25', 55, 6, 15)])

    def test_an_empty_or_missing_history_always_appends(self):
        for product in ({}, {'sqp_history': []}, {'sqp_history': None}):
            self.assertTrue(dashboard.record_run_history(product, self.run_folder())['sqp_history_appended'])
            self.assertEqual(product['sqp_history'], [entry('2026-10-18')])

    def test_the_baseline_is_the_newest_entry_wherever_it_sits(self):
        """stage.volatile_week takes the newest dated entry, so a hand-edited history out of order must not let an older
        week in, and an entry with no date does not make the next run append."""
        product = {'sqp_history': [entry('2026-10-25'), entry('2026-10-18')]}
        res = dashboard.record_run_history(product, self.run_folder('2026-10-22'))
        self.assertFalse(res['sqp_history_appended'])
        self.assertEqual(product['sqp_history'], [entry('2026-10-25'), entry('2026-10-18')])
        product = {'sqp_history': [entry('2026-10-25'), entry(None)]}
        self.assertFalse(dashboard.record_run_history(product, self.run_folder('2026-10-22'))['sqp_history_appended'])
        self.assertTrue(dashboard.record_run_history(product, self.run_folder('2026-11-01'))['sqp_history_appended'])

    def test_the_entry_keeps_only_the_four_fields_volatile_week_reads(self):
        run = self.run_folder()
        totals = read_json(os.path.join(run, 'sqp_totals.json'))
        write_json(os.path.join(run, 'sqp_totals.json'), dict(totals, extra='not recorded'))
        product = {}
        dashboard.record_run_history(product, run)
        self.assertEqual(sorted(product['sqp_history'][0]), ['data_through', 'our_clicks', 'our_purchases', 'queries'])

    def test_refresh_records_stage_and_mature_sticks(self):
        product = {}
        early = dashboard.record_run_history(product, self.run_folder(stage='early'))
        self.assertEqual((product['data_stage'], early['data_stage'], early['data_stage_changed']), ('early', 'early', True))
        # the run says the same again: nothing changed
        again = dashboard.record_run_history(product, self.run_folder('2026-10-25', stage='early'))
        self.assertEqual((product['data_stage'], again['data_stage_changed']), ('early', False))
        # early then mature: mature
        mature = dashboard.record_run_history(product, self.run_folder('2026-11-01', stage='mature'))
        self.assertEqual((product['data_stage'], mature['data_stage'], mature['data_stage_changed']), ('mature', 'mature', True))
        # mature then early or launch: still mature
        for stage in ('early', 'launch'):
            res = dashboard.record_run_history(product, self.run_folder('2026-11-08', stage=stage))
            self.assertEqual((product['data_stage'], res['data_stage'], res['data_stage_changed']), ('mature', 'mature', False))

    def test_a_launch_product_moves_on_to_early(self):
        product = {'data_stage': 'launch'}
        res = dashboard.record_run_history(product, self.run_folder(stage='early'))
        self.assertEqual((product['data_stage'], res['data_stage_changed']), ('early', True))

    def test_the_history_keeps_the_last_26(self):
        weeks = [(datetime.date(2025, 12, 7) + datetime.timedelta(days=7 * i)).isoformat() for i in range(26)]   # Dec 7 to Jun 7
        product = {'sqp_history': [entry(w, clicks=i) for i, w in enumerate(weeks)]}
        oldest = product['sqp_history'][0]
        res = dashboard.record_run_history(product, self.run_folder('2026-10-18', clicks=999))
        self.assertTrue(res['sqp_history_appended'])
        self.assertEqual([e['data_through'] for e in product['sqp_history']], weeks[1:] + ['2026-10-18'])
        self.assertNotIn(oldest, product['sqp_history'])
        self.assertEqual(product['sqp_history'][-1], entry('2026-10-18', clicks=999))
        # keep= is the size it trims to
        dashboard.record_run_history(product, self.run_folder('2026-10-25'), keep=3)
        self.assertEqual([e['data_through'] for e in product['sqp_history']], [weeks[-1], '2026-10-18', '2026-10-25'])

    def test_a_run_without_totals_leaves_the_history_and_says_so_but_still_records_the_stage(self):
        product = {'sqp_history': [entry('2026-10-11')]}
        res = dashboard.record_run_history(product, self.run_folder(totals=False, stage='mature'))
        self.assertFalse(res['sqp_history_appended'])
        self.assertEqual(product['sqp_history'], [entry('2026-10-11')])
        self.assertEqual(product['data_stage'], 'mature')
        self.assertTrue(any('sqp_totals.json' in n for n in res['notes']), res['notes'])

    def test_a_run_without_a_stage_leaves_the_stage_and_says_so_but_still_records_the_totals(self):
        product = {'data_stage': 'early'}
        res = dashboard.record_run_history(product, self.run_folder(with_stage=False))
        self.assertEqual(product['data_stage'], 'early')
        self.assertFalse(res['data_stage_changed'])
        self.assertEqual(res['data_stage'], 'early')
        self.assertTrue(res['sqp_history_appended'])
        self.assertTrue(any('stage' in n for n in res['notes']), res['notes'])
        # no plan.json at all is the same as no stage
        run = self.run_folder()
        os.remove(os.path.join(run, 'plan.json'))
        product = {}
        res = dashboard.record_run_history(product, run)
        self.assertNotIn('data_stage', product)
        self.assertIsNone(res['data_stage'])
        self.assertTrue(any('stage' in n for n in res['notes']), res['notes'])

    def test_totals_without_a_date_are_not_recorded(self):
        product = {}
        res = dashboard.record_run_history(product, self.run_folder(data_through=None))
        self.assertFalse(res['sqp_history_appended'])
        self.assertNotIn('sqp_history', product)
        self.assertTrue(any('data_through' in n for n in res['notes']), res['notes'])


class RefreshAppliedRecap(unittest.TestCase):
    def refreshed(self, state='applied', marked=True):
        rows = [dict(type='Bid change', status='applied'),
                dict(type='Negative exact', status='not applied'),
                dict(type='Pause keyword', status='held')]
        if not marked:
            rows = [{k: v for k, v in row.items() if k != 'status'} for row in rows]
        live = dict(asin=ASIN, registry={},
                    run=dict(date='2026-10-24', state=state, label='Test run', changes=rows))
        product = dict(asin=ASIN, product='Test cards', registry=dict(stage='ai', bid_owner='AI'))
        return dashboard.refresh_doc(live, product, dashboard.config(), None), rows

    def test_refresh_counts_only_applied_rows_and_preserves_the_full_table(self):
        doc, rows = self.refreshed()
        self.assertEqual(doc['just_changed']['counts'], [['Bid change', 1]])
        self.assertEqual(doc['run']['changes'], rows)
        self.assertNotIn('negatives', doc['card']['just_changed']['headline'])
        self.assertNotIn('keywords paused', doc['card']['just_changed']['headline'])

    def test_refresh_keeps_legacy_unmarked_counts(self):
        doc, rows = self.refreshed(marked=False)
        self.assertEqual(sum(n for _, n in doc['just_changed']['counts']), len(rows))

    def test_refresh_keeps_proposed_counts(self):
        doc, rows = self.refreshed(state='proposed')
        self.assertEqual(sum(n for _, n in doc['just_changed']['counts']), len(rows))


class CmdRefresh(Base):
    LIVE = {'asin': ASIN, 'run': {}, 'registry': {}}
    PUT = {'version': 'v2', 'published_at': '2026-10-22T00:00:00Z', 'published_by': 'test'}

    def test_onboarding_refresh_retains_proposal_but_does_not_claim_ai_ownership(self):
        product = dict(asin=ASIN, product='Test cards', registry=dict(bid_owner='Scale Insights', stage='onboarding'))
        live = dict(self.LIVE, run=dict(id='test-run', state='proposed', changes=[]), card=dict(stage='ai'))
        doc = dashboard.refresh_doc(live, product, dashboard.config(), 'Audit only')
        self.assertEqual(doc['card']['stage'], 'queued')
        self.assertEqual(doc['card']['bid_owner'], 'Scale Insights')
        self.assertEqual(doc['run'], live['run'])
        self.assertFalse(any(row['status'] == 'ai' for row in doc['scope']))

    def test_ai_owned_refresh_keeps_ai_stage(self):
        product = dict(asin=ASIN, product='Test cards', registry=dict(bid_owner='AI', stage='ai'))
        doc = dashboard.refresh_doc(self.LIVE, product, dashboard.config(), 'Refresh')
        self.assertEqual(doc['card']['stage'], 'ai')
        self.assertTrue(any(row['status'] == 'ai' for row in doc['scope']))

    def write_product(self, **over):
        product = dict(asin=ASIN, product='Test cards', sku='TEST-SKU', registry=dict(bid_owner='AI', stage='ai'),
                       dashboard=dict(version='v1'))
        product.update(over)
        write_json(self.product_file, product)
        return product

    def args(self, run=None, dry_run=False, **over):
        a = argparse.Namespace(asin=ASIN, note=None, by='Tester', data=self.data, out=None, dry_run=dry_run, force=False, run=run)
        for k, v in over.items():
            setattr(a, k, v)
        return a

    def refresh(self, a):
        """cmd_refresh with the dashboard patched out; returns (printed JSON, the calls it made)."""
        def fake(method, path, body=None, base_version=None):
            return dict(self.LIVE) if method == 'GET' else dict(self.PUT)
        out = io.StringIO()
        with unittest.mock.patch.object(dashboard, 'call', side_effect=fake) as call, contextlib.redirect_stdout(out):
            dashboard.cmd_refresh(a)
        return json.loads(out.getvalue()), call.call_args_list

    def raw(self):
        with open(self.product_file, 'rb') as fh:
            return fh.read()

    def test_a_live_refresh_with_a_run_writes_the_history_and_stage_to_the_product_file(self):
        self.write_product(sqp_history=[entry('2026-10-11')], data_stage='launch')
        run = self.run_folder('2026-10-18', stage='early', clicks=50, purchases=5, queries=14)
        printed, calls = self.refresh(self.args(run=run))
        product = read_json(self.product_file)
        self.assertEqual(product['sqp_history'], [entry('2026-10-11'), entry('2026-10-18', 50, 5, 14)])
        self.assertEqual(product['data_stage'], 'early')
        self.assertEqual(product['dashboard']['version'], 'v2')   # put_page still records the new page version
        self.assertEqual([c.args[0] for c in calls], ['GET', 'PUT'])
        self.assertTrue(printed['sqp_history_appended'])
        self.assertEqual(printed['data_stage'], 'early')
        self.assertTrue(printed['data_stage_changed'])
        # the same run refreshed again adds nothing
        printed, _ = self.refresh(self.args(run=run))
        self.assertFalse(printed['sqp_history_appended'])
        self.assertEqual(len(read_json(self.product_file)['sqp_history']), 2)

    def test_a_dry_run_prints_what_it_would_record_and_leaves_the_product_file_alone(self):
        self.write_product(data_stage='launch')
        before = self.raw()
        run = self.run_folder('2026-10-18', stage='mature')
        printed, calls = self.refresh(self.args(run=run, dry_run=True))
        self.assertEqual(self.raw(), before)
        self.assertEqual([c.args[0] for c in calls], ['GET'])    # no PUT on a dry run
        self.assertTrue(printed['dry_run'])
        self.assertTrue(printed['sqp_history_appended'])
        self.assertEqual(printed['data_stage'], 'mature')
        self.assertTrue(printed['data_stage_changed'])

    def test_refresh_without_run_leaves_both(self):
        history = [entry('2026-10-04'), entry('2026-10-11')]
        self.write_product(sqp_history=history, data_stage='early')
        printed, _ = self.refresh(self.args())
        product = read_json(self.product_file)
        self.assertEqual(product['sqp_history'], history)
        self.assertEqual(product['data_stage'], 'early')
        self.assertNotIn('sqp_history_appended', printed)
        # a product that records neither still records neither
        self.write_product()
        self.refresh(self.args())
        product = read_json(self.product_file)
        self.assertNotIn('sqp_history', product)
        self.assertNotIn('data_stage', product)

    def test_a_caller_that_passes_no_run_at_all_leaves_both(self):
        """cmd_rank hands cmd_refresh its own arguments, which have no --run."""
        self.write_product(data_stage='early')
        a = self.args()
        del a.run
        self.refresh(a)
        product = read_json(self.product_file)
        self.assertEqual(product['data_stage'], 'early')
        self.assertNotIn('sqp_history', product)

    def test_a_run_folder_for_another_product_is_refused_and_nothing_is_written(self):
        self.write_product(data_stage='early')
        before = self.raw()
        run = self.run_folder('2026-10-18', stage='mature', asin='B0OTHER001')
        for dry_run in (False, True):
            with unittest.mock.patch.object(dashboard, 'call') as call, self.assertRaises(SystemExit) as cm:
                dashboard.cmd_refresh(self.args(run=run, dry_run=dry_run))
            self.assertIn(f'{run} holds the plan for B0OTHER001, not {ASIN}', str(cm.exception))
            self.assertEqual(self.raw(), before)
            call.assert_not_called()

    def test_a_plan_that_names_no_asin_is_not_refused(self):
        self.write_product()
        printed, _ = self.refresh(self.args(run=self.run_folder('2026-10-18', asin=None)))
        self.assertTrue(printed['sqp_history_appended'])
        self.assertEqual(read_json(self.product_file)['sqp_history'], [entry('2026-10-18')])

    def test_a_queued_product_has_no_run_to_record(self):
        self.write_product(registry=dict(bid_owner='Scale Insights', stage='queued'))
        before = self.raw()
        with unittest.mock.patch.object(dashboard, 'call') as call, self.assertRaises(SystemExit) as cm:
            dashboard.cmd_refresh(self.args(run=self.run_folder()))
        self.assertIn('queued', str(cm.exception))
        self.assertEqual(self.raw(), before)
        call.assert_not_called()

    def test_a_run_folder_that_does_not_exist_stops_before_anything_is_published(self):
        self.write_product()
        before = self.raw()
        with unittest.mock.patch.object(dashboard, 'call') as call, self.assertRaises(SystemExit) as cm:
            dashboard.cmd_refresh(self.args(run=os.path.join(self.tmp, 'no-such-run')))
        self.assertIn('no-such-run', str(cm.exception))
        self.assertEqual(self.raw(), before)
        call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
