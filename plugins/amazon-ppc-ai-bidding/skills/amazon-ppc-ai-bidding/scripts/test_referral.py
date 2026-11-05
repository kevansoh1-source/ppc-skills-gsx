"""The referral fee read from the settlement report on every run (Kim, 2026-10-29, decision 169: "yes, auto-read the
referral fee"). The settled rate on 10+ units of the last 14 days moves profit_per_unit by (old - new) x price and is kept
in referral_override; fewer units keep the stored rate; a missing read stops the run with need_settlement.json."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

import notify
import plan as planner
import referral
import test_plan_lanes as T

TODAY = '2026-10-29'
SINCE = '2026-10-15'
SHARED = {'referral': {'auto': True, 'window_days': 14, 'min_units': 10, 'marketplace': 'Amazon.com'}}


def product(**over):
    p = dict(asin='B0SAMP0026', sku='YourBrand_860', price=7.99, profit_per_unit=3.01, economics_as_of='2026-10-27',
             referral_override=dict(pct=9.94, si_pct=5, price=7.99, si_unit_profit=None, source='MAP sp_settlement',
                                    as_of='2026-10-27', decision=136, note='kept'))
    p.update(over)
    return p


def settled(pct, units, sku='YourBrand_860', since=SINCE):
    principal = round(7.99 * units, 2)
    return {'status': 'success', 'data': [dict(sku=sku, window_from=since, order_items=units, units=units, principal=principal,
                                               commission=-round(principal * pct / 100, 2), first_posted='2026-10-15T04:33:34+00:00',
                                               last_posted='2026-10-27T11:50:56+00:00')]}


class ReferralTest(unittest.TestCase):
    def setUp(self):
        self.run = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.run, ignore_errors=True)

    def save(self, data, name=referral.FILE):
        with open(os.path.join(self.run, name), 'w', encoding='utf-8') as fh:
            json.dump(data, fh)

    def refresh(self, cfg, shared=SHARED):
        return referral.refresh(cfg, shared, self.run, 'B0SAMP0026', TODAY)

    def test_the_live_config_turns_it_on(self):
        s = referral.settings(T.shared_config())
        self.assertEqual((s['enabled'], s['window_days'], s['min_units'], s['marketplace']), (True, 14, 10, 'Amazon.com'))

    def test_the_fee_back_at_15_percent_cuts_the_profit(self):
        cfg = product()
        self.save(settled(15.0, 40))
        rec, problem = self.refresh(cfg)
        self.assertIsNone(problem)
        self.assertEqual((rec['status'], rec['pct'], rec['was']), ('read', 15.0, 9.94))
        self.assertTrue(rec['changed'])
        self.assertEqual(cfg['profit_per_unit'], round(3.01 + (9.94 - 15.0) / 100 * 7.99, 2))   # $2.61
        self.assertEqual(cfg['economics_as_of'], TODAY)
        block = cfg['referral_override']
        self.assertEqual((block['pct'], block['window_from'], block['window_days'], block['units'], block['decision']),
                         (15.0, SINCE, 14, 40, 169))
        self.assertEqual(block['previous'], dict(pct=9.94, profit_per_unit=3.01))
        self.assertEqual((block['si_pct'], block['note']), (5, 'kept'))
        self.assertEqual(referral.line(rec), 'referral fee now 15.0% (was 9.94%): profit $3.01 -> $2.61')

    def test_a_second_plan_the_same_day_keeps_the_first_previous(self):
        # 2026-11-04: re-running plan.py overwrote previous with today's own rate
        cfg = product()
        self.save(settled(15.0, 40))
        self.refresh(cfg)
        rec, problem = self.refresh(cfg)
        self.assertIsNone(problem)
        self.assertEqual(cfg['referral_override']['previous'], dict(pct=9.94, profit_per_unit=3.01))
        self.assertFalse(rec['changed'])

    def test_the_fee_down_at_5_percent_raises_the_profit(self):
        cfg = product()
        self.save(settled(5.0, 25))
        rec, problem = self.refresh(cfg)
        self.assertIsNone(problem)
        self.assertEqual(cfg['profit_per_unit'], round(3.01 + (9.94 - 5.0) / 100 * 7.99, 2))    # $3.40
        self.assertEqual(rec['profit'], cfg['profit_per_unit'])
        self.assertIn('referral fee now 5.0% (was 9.94%)', referral.line(rec))

    def test_too_few_units_keep_the_stored_rate(self):
        cfg = product()
        self.save(settled(15.0, 9))
        rec, problem = self.refresh(cfg)
        self.assertIsNone(problem)
        self.assertEqual((rec['status'], rec['pct'], rec['changed']), ('too_few_units', 9.94, False))
        self.assertEqual((cfg['profit_per_unit'], cfg['referral_override']['pct']), (3.01, 9.94))
        self.assertEqual(cfg['referral_override']['last_read']['units'], 9)
        self.assertIsNone(referral.line(rec))
        self.assertIn('9.94% (stored)', rec['note'])

    def test_too_few_units_without_a_block_keep_scale_insights(self):
        cfg = product()
        del cfg['referral_override']
        self.save({'data': []})
        rec, problem = self.refresh(cfg)
        self.assertIsNone(problem)
        self.assertEqual((rec['status'], cfg['profit_per_unit']), ('too_few_units', 3.01))
        self.assertNotIn('referral_override', cfg)
        self.assertIn("Scale Insights' rate", rec['note'])

    def test_a_missing_read_stops_the_run(self):
        rec, problem = self.refresh(product())
        self.assertIsNone(rec)
        self.assertIn('need_settlement.json', problem)
        with open(os.path.join(self.run, referral.NEED), encoding='utf-8') as fh:
            need = json.load(fh)
        self.assertEqual(need['need'][referral.FILE]['since'], SINCE)
        self.assertIn("sku='YourBrand_860'", need['need'][referral.FILE]['sql'])

    def test_a_read_of_another_window_stops_the_run(self):
        self.save(settled(15.0, 40, since='2026-09-01'))
        rec, problem = self.refresh(product())
        self.assertIsNone(rec)
        self.assertIn('another window', json.load(open(os.path.join(self.run, referral.NEED)))['need'][referral.FILE]['how'])

    def test_another_skus_rows_do_not_count(self):
        cfg = product()
        self.save(settled(15.0, 40, sku='YourBrand_859'))
        rec, _ = self.refresh(cfg)
        self.assertEqual((rec['status'], cfg['profit_per_unit']), ('too_few_units', 3.01))

    def test_a_first_read_without_a_block_needs_scale_insights_rate_once(self):
        cfg = product()
        del cfg['referral_override']
        self.save(settled(10.0, 30))
        rec, problem = self.refresh(cfg)
        self.assertIsNone(rec)
        self.assertIn(referral.METADATA, problem)
        self.save([{'type': 'text', 'text': json.dumps({'products': [{'ASIN': 'B0SAMP0026', 'ReferralPercent': 15}]})}],
                  name=referral.METADATA)
        rec, problem = self.refresh(cfg)
        self.assertIsNone(problem)
        self.assertEqual(cfg['profit_per_unit'], round(3.01 + (15 - 10.0) / 100 * 7.99, 2))
        self.assertEqual((cfg['referral_override']['pct'], cfg['referral_override']['si_pct']), (10.0, 15))

    def test_commission_over_principal_of_0_15_is_a_15_percent_fee(self):
        # Kim, 2026-10-31: the fee is commission / principal in percentage points, 0.15 -> 15%, never 0.15%
        m = referral.measure([dict(sku='S', window_from=SINCE, units=10, order_items=10, principal=100.0, commission=-15.0)],
                             'S', SINCE)
        self.assertEqual(m['pct'], 15.0)
        cfg = product()
        self.save({'data': [dict(sku='YourBrand_860', window_from=SINCE, order_items=20, units=20, principal=159.80,
                                 commission=-23.97)]})
        rec, _ = self.refresh(cfg)
        self.assertEqual(rec['pct'], 15.0)
        self.assertEqual(cfg['profit_per_unit'], round(3.01 + (9.94 - 15.0) / 100 * 7.99, 2))   # down, never up

    def test_scale_insights_fraction_0_15_is_read_as_15_percent(self):
        # 2026-10-30 B0SAMP0029 and B0SAMP0030: ReferralPercent 0.15 taken as 0.15% halved profit_per_unit
        self.assertEqual([referral.as_pct(x) for x in (0.15, 0.05, 15, 9.94, None)], [15.0, 5.0, 15, 9.94, None])
        cfg = product()
        del cfg['referral_override']
        self.save(settled(15.0, 30))
        self.save([{'type': 'text', 'text': json.dumps({'products': [{'ASIN': 'B0SAMP0026', 'ReferralPercent': 0.15}]})}],
                  name=referral.METADATA)
        rec, problem = self.refresh(cfg)
        self.assertIsNone(problem)
        self.assertEqual((rec['was'], rec['changed'], cfg['profit_per_unit']), (15.0, False, 3.01))
        self.assertEqual(cfg['referral_override']['si_pct'], 15.0)

    def test_a_stored_fraction_is_read_as_a_percentage_too(self):
        cfg = product(referral_override=dict(pct=0.15, si_pct=0.15, price=7.99))
        self.save(settled(15.0, 30))
        rec, _ = self.refresh(cfg)
        self.assertEqual((rec['was'], rec['changed'], cfg['profit_per_unit']), (15.0, False, 3.01))

    def test_off_leaves_everything_alone(self):
        cfg = product()
        rec, problem = self.refresh(cfg, shared={'referral': {'auto': False}})
        self.assertEqual((rec, problem, cfg), (None, None, product()))

    def test_the_slack_message_carries_the_line(self):
        rec = dict(status='read', pct=15.0, was=9.94, profit_was=3.01, profit=2.61, changed=True)
        plan = {'summary': [dict(referral=rec, review_date=TODAY, shadow=False)], 'changes': []}
        text = notify.message(plan, {'product': 'Set'}, T.shared_config(), 'B0SAMP0026', applied={}, date=TODAY)['text']
        self.assertIn('- Referral fee now 15.0% (was 9.94%): profit $3.01 -> $2.61', text)


class PlanMainTest(unittest.TestCase):
    """plan.main() reads the fee before pricing: it stops without the read, and prices on the settled profit with it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.run_dir = os.path.join(self.tmp, 'run')
        self.data = os.path.join(self.tmp, 'data')
        os.makedirs(os.path.join(self.data, 'asins'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def main(self, product, settlement):
        T.make_run(self.run_dir, **T.HEAD_TERM, extra={'settlement.json': settlement})
        path = os.path.join(self.data, 'asins', f'{T.ASIN}.json')
        T.write(path, product)
        argv = ['plan.py', '--asin', T.ASIN, '--run', self.run_dir, '--data', self.data, '--today', T.TODAY]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), T.without_mid():
            planner.main()
        with open(path, encoding='utf-8') as fh:
            saved_product = json.load(fh)
        with open(os.path.join(self.run_dir, 'plan.json'), encoding='utf-8') as fh:
            return json.load(fh), saved_product

    def product(self):
        return dict(T.product(), sku='YourBrand_TEST', price=7.99,
                    referral_override=dict(pct=9.94, si_pct=15, price=7.99, decision=136))

    def test_main_stops_without_the_settlement_read(self):
        with self.assertRaises(SystemExit) as stop:
            self.main(self.product(), None)
        self.assertIn('need_settlement.json', str(stop.exception))
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'plan.json')))

    def test_main_prices_on_the_settled_profit_and_keeps_it(self):
        p = self.product()
        plan, saved = self.main(p, settled(15.0, 40, sku='YourBrand_TEST', since='2026-10-05'))   # T.TODAY less 14 days
        want = round(p['profit_per_unit'] + (9.94 - 15.0) / 100 * 7.99, 2)
        self.assertEqual(saved['profit_per_unit'], want)
        self.assertEqual(saved['referral_override']['pct'], 15.0)
        ref = plan['summary'][0]['referral']
        self.assertEqual((ref['pct'], ref['was'], ref['profit'], ref['units']), (15.0, 9.94, want, 40))
        self.assertEqual(plan['summary'][0]['profit_per_unit'], want)


if __name__ == '__main__':
    unittest.main()
