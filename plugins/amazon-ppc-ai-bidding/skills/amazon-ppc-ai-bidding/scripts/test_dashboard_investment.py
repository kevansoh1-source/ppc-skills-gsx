"""The applied dashboard must not turn a partial onboarding plan into live investment settings."""
import json
import os
import tempfile
import unittest

import dashboard


class AppliedInvestmentProjection(unittest.TestCase):
    def build(self, changes, applied=(), clock=None, state='applied', lanes=True):
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, 'data')
            run = os.path.join(tmp, 'run')
            os.makedirs(os.path.join(data, 'asins'))
            os.makedirs(os.path.join(run, 'payloads'))
            product = {'asin': 'B0TEST0004', 'product': 'Cards', 'price': 10, 'profit_per_unit': 3,
                       'invest_log': {'thank you cards': clock} if clock else {}}
            summary = {'lanes': {}, 'shadow': False} if lanes else {}
            plan = {'summary': [summary], 'changes': changes, 'rerank': [
                {'keyword': 'thank you cards', 'role': 'Invest', 'bid': .63, 'tos': 50, 'budget': 10}],
                'terms': [], 'human_review': []}
            for path, value in [(os.path.join(data, 'asins', 'B0TEST0004.json'), product),
                                (os.path.join(run, 'plan.json'), plan)]:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(value, f)
            if lanes:
                with open(os.path.join(run, 'payloads', 'applied_rows.json'), 'w', encoding='utf-8') as f:
                    json.dump({rid: {'date': '2026-10-23', 'folder': 'auto'} for rid in applied}, f)
            return dashboard.build_doc('B0TEST0004', run, state, 'Test', '2026-10-23', 'Test', data)[0]

    def row(self, kind, rid, **values):
        return dict(type=kind, row_id=rid, keyword='thank you cards', role='Invest', lane='auto', **values)

    def test_partial_si_and_sb_do_not_activate_human_head(self):
        changes = [self.row('Scale Insights rules', 'si'), self.row('New SB video campaign', 'sb'),
                   self.row('New exact campaign', 'sp')]
        changes[-1]['lane'] = 'human'
        doc = self.build(changes, ['si', 'sb'])
        self.assertEqual(doc['invest']['rows'], [])
        self.assertEqual(doc['card']['invest_count'], 0)
        self.assertIsNone(doc['card']['invest_budget_day'])
        self.assertIn('No verified consumer', doc['invest']['note'])
        self.assertEqual(doc['run']['changes'][-1]['status'], 'waiting for a person')

    def test_sb_only_does_not_start_sp_investment(self):
        doc = self.build([self.row('New SB video campaign', 'sb')], ['sb'])
        self.assertEqual(doc['invest']['rows'], [])

    def test_applied_sp_promotion_is_shown(self):
        doc = self.build([self.row('New exact campaign', 'sp')], ['sp'])
        self.assertEqual(doc['invest']['rows'][0]['bid'], .63)
        self.assertEqual(doc['card']['invest_count'], 1)

    def test_proposed_preview_keeps_unapplied_promotion(self):
        doc = self.build([self.row('New exact campaign', 'sp')], state='proposed')
        self.assertEqual(len(doc['invest']['rows']), 1)
        self.assertIn('waiting for approval', doc['invest']['note'])

    def test_existing_clock_without_pending_settings_remains(self):
        doc = self.build([], clock={'since': '2026-10-01', 'role': 'Invest'})
        self.assertEqual(doc['invest']['rows'][0]['since'], '2026-10-01')

    def test_the_review_date_is_the_next_stop_loss_checkpoint(self):
        # decision 142: months 3, 6, 9 and 12 of investing (day 91, 182, ...), the next one after the last passed
        doc = self.build([], clock={'since': '2026-10-17', 'role': 'Invest'})
        self.assertEqual(doc['invest']['rows'][0]['review_on'], '2027-01-16')
        doc = self.build([], clock={'since': '2026-10-17', 'role': 'Invest', 'checkpoint': 3})
        self.assertEqual(doc['invest']['rows'][0]['review_on'], '2027-04-17')
        doc = self.build([], clock={'since': '2026-10-17', 'role': 'Invest', 'checkpoint': 12})
        self.assertNotIn('review_on', doc['invest']['rows'][0])
        self.assertIn('months 3, 6, 9, 12 of investing', doc['invest']['note'])

    def test_existing_clock_with_held_price_is_not_mislabeled_live(self):
        doc = self.build([self.row('Bid change', 'bid', current=.40, new=.63)],
                         clock={'since': '2026-10-01', 'role': 'Invest'})
        self.assertEqual(doc['invest']['rows'], [])

    def test_applied_bid_with_held_placement_is_not_all_applied(self):
        doc = self.build([self.row('Bid change', 'bid', current=.40, new=.63),
                          self.row('Budget and top of search', 'budget')], ['bid'],
                         clock={'since': '2026-10-01', 'role': 'Invest'})
        self.assertEqual(doc['invest']['rows'], [])

    def test_applied_pause_does_not_show_old_clock_as_serving(self):
        doc = self.build([self.row('Pause keyword', 'pause')], ['pause'],
                         clock={'since': '2026-10-01', 'role': 'Invest'})
        self.assertEqual(doc['invest']['rows'], [])

    def test_generic_hold_cut_does_not_activate_new_investment(self):
        change = self.row('Bid change', 'cut', current=.80, new=.40)
        change['role'] = 'Hold'
        doc = self.build([change], ['cut'])
        self.assertEqual(doc['invest']['rows'], [])

    def test_rank_creation_without_redundant_change_role_still_appears(self):
        change = self.row('New exact campaign', 'sp')
        change.pop('role')
        doc = self.build([change], ['sp'])
        self.assertEqual(len(doc['invest']['rows']), 1)

    def test_legacy_run_without_applied_record_preserves_rendering(self):
        doc = self.build([self.row('New exact campaign', 'sp')], lanes=False)
        self.assertEqual(len(doc['invest']['rows']), 1)


if __name__ == '__main__':
    unittest.main()
