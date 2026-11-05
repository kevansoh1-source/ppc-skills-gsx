import copy
import json
import re
import pathlib
import tempfile
import unittest

import dashboard
import growth
import human_review
import lanes
import preview

SKILL = pathlib.Path(__file__).resolve().parents[1]
SHARED = json.loads((SKILL / 'config.json').read_text(encoding='utf-8'))


def sample(index=0.6, clicks=30):
    return dict(term='blank cards', role='Trim', index_basis='SQP', sqp_total_clicks=400,
                sqp_our_clicks=clicks, sqp_our_purchases=2, ad_clicks=20, ad_orders=2,
                cvr_est=index * 0.12, market_cvr=0.12, index=index)


def proposal():
    return human_review.propose({'terms':[sample()]}, {'price':7.99}, SHARED, '2026-10-18')[0]


class HumanReviewTests(unittest.TestCase):
    def test_only_sufficient_same_query_data(self):
        thin = sample(clicks=4)
        fallback = dict(sample(), sqp_total_clicks=0)
        irrelevant = dict(sample(), role='Negate')
        result = human_review.propose({'terms':[thin, fallback, irrelevant]}, {}, SHARED, '2026-10-18')
        self.assertEqual(result, [])

    def test_gap_is_review_not_listing_diagnosis(self):
        result = human_review.propose({'terms':[sample()]}, {'price':7.99}, SHARED, '2026-10-18')
        self.assertEqual([item['kind'] for item in result], ['listing', 'price'])
        self.assertIn('not proof', result[0]['reason'])
        self.assertIsNone(result[1]['price']['proposed'])
        self.assertEqual(result[1]['approval_required'], 'Kim')

    def test_strong_loss_prompts_increase_review_not_amount(self):
        term = dict(sample(1.4), role='Rank', sqp_our_purchases=5)
        result = human_review.propose({'terms':[term]}, {'price':7.99, 'monitor':{'profit':-10, 'start':'2026-09-18', 'end':'2026-10-17'}}, SHARED, '2026-10-18')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['price']['direction'], 'review')
        self.assertIsNone(result[0]['price']['proposed'])

    def test_dedup_preserves_assignment_and_history(self):
        item = proposal()
        existing = human_review.transition([item], item['id'], 'in_progress', 'Lee', 'Review gallery', '2026-10-18')
        result = human_review.merge(existing, [proposal()], '2026-10-19')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['status'], 'in_progress')
        self.assertEqual(result[0]['owner'], 'Lee')
        self.assertEqual(len(result[0]['history']), 1)
        self.assertEqual(result[0]['first_seen'], '2026-10-18')

    def test_resolved_reopens_only_on_later_sweep(self):
        item = proposal()
        existing = human_review.transition([item], item['id'], 'resolved', None, 'Image test complete', '2026-10-18')
        self.assertEqual(human_review.merge(existing, [proposal()], '2026-10-18')[0]['status'], 'resolved')
        self.assertEqual(human_review.merge(existing, [proposal()], '2026-10-19')[0]['status'], 'open')
        existing[0]['resolved_on'] = '2026-10-20'
        self.assertEqual(human_review.merge(existing, [proposal()], '2026-10-20')[0]['status'], 'resolved')
        existing[0]['status'] = 'dismissed'
        self.assertEqual(human_review.merge(existing, [proposal()], '2026-10-19')[0]['status'], 'dismissed')

    def test_no_silent_closure_or_deletion(self):
        result = human_review.merge([proposal()], [], '2026-10-19')
        self.assertEqual(result[0]['status'], 'open')
        self.assertFalse(result[0]['detected_latest_sweep'])

    def test_price_amount_requires_economics_and_rollback(self):
        item = dict(proposal(), id='price-test', kind='price', price={'current':7.99, 'proposed':8.49})
        with self.assertRaises(ValueError):
            human_review.validate([item])
        item['price'].update(profit_per_unit_current=2, profit_per_unit_proposed=2.42,
                             economics_as_of='2026-10-18', economics_source='Test fee snapshot',
                             comparison_source='Test comparable packs', rollback='Return to baseline if CVR falls', review_on='2026-11-08')
        result = human_review.validate([item])[0]
        self.assertEqual(result['price']['change'], 0.5)
        self.assertEqual(result['price']['profit_change'], 0.42)
        self.assertAlmostEqual(result['price']['margin_proposed'], 2.42 / 8.49)
        pending = copy.deepcopy(result)
        pending['price']['proposed'] = None
        retained = human_review.merge([result], [pending], '2026-10-19')[0]
        self.assertTrue(retained['price_recheck_required'])
        self.assertEqual(retained['price']['proposed'], 8.49)
        self.assertFalse(human_review.merge([retained], [result], '2026-10-20')[0]['price_recheck_required'])

    def test_approval_preview_includes_queue_and_escapes_data(self):
        item = dict(proposal(), title='<script>alert(1)</script>', ai_review={'phase': 'human_ready'})
        page = preview.human_review_html([('Test product', [item])])
        self.assertIn('<h2>Human decisions</h2>', page)
        self.assertIn('our CVR 7.20%', page)
        self.assertIn('market CVR 12.00%', page)
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertEqual(preview.human_review_html([]), '')

    def test_preview_shows_decisions_only(self):
        items = [dict(proposal(), id=phase, title=phase + ' item', ai_review={'phase': phase})
                 for phase in ('research', 'monitor', 'human_ready')]
        items.append(dict(proposal(), id='closed', title='closed item', status='resolved',
                          ai_review={'phase': 'human_ready'}))
        original = copy.deepcopy(items)
        page = preview.human_review_html([('Product', items)])
        sections = dict(re.findall(r'<section id="([^"]+)">(.*?)</section>', page))
        self.assertEqual(set(sections), {'needs-human', 'review-history'})
        self.assertIn('human_ready item', sections['needs-human'])
        self.assertIn('closed item', sections['review-history'])
        self.assertNotIn('closed item', sections['needs-human'])
        for hidden in ('research item', 'monitor item', 'Research needed', 'AI review stage', 'queue publication'):
            self.assertNotIn(hidden, page)
        self.assertEqual(items, original)

    def test_preview_of_research_only_is_empty(self):
        item = dict(proposal(), ai_review={'phase': 'research'})
        self.assertEqual(preview.human_review_html([('Product', [item])]), '')

    def test_build_doc_merges_without_saving_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            data = pathlib.Path(directory)
            (data / 'asins').mkdir()
            product = dict(asin='B0SAMP0025', sku='test', product='Test', price=7.99)
            path = data / 'asins/B0SAMP0025.json'
            path.write_text(json.dumps(product), encoding='utf-8')
            (data / 'plan.json').write_text(json.dumps({'human_review':[proposal()]}), encoding='utf-8')
            doc, state = dashboard.build_doc('B0SAMP0025', str(data), 'proposed', 'Test', '2026-10-18', 'Test', str(data))
            self.assertEqual(doc['card']['human_review_count'], 0)
            self.assertEqual(doc['card']['ai_research_count'], 1)
            self.assertEqual(state['human_review'][0]['id'], 'listing-conversion-gap')
            self.assertNotIn('human_review', json.loads(path.read_text(encoding='utf-8')))

    def test_legacy_and_queued_dashboard_compatible(self):
        doc = {'card':{}}
        human_review.attach(doc, {})
        self.assertEqual(doc['card']['human_review_count'], 0)
        with tempfile.TemporaryDirectory() as directory:
            data = pathlib.Path(directory)
            (data / 'asins').mkdir()
            product = dict(asin='B0SAMP0025', sku='test', product='Test product', price=7.99,
                           registry={'stage':'queued','bid_owner':'SI'}, human_review=[proposal()])
            (data / 'asins/B0SAMP0025.json').write_text(json.dumps(product), encoding='utf-8')
            doc, state = dashboard.build_lineup_doc('B0SAMP0025', '2026-10-18', 'Test', str(data))
            self.assertEqual(doc['card']['human_review_count'], 0)
            self.assertEqual(doc['card']['ai_research_count'], 1)
            self.assertEqual(doc['human_review'], human_review.for_people(state['human_review']))  # decision 97: decisions only
            self.assertEqual(doc['human_review'], [])

    def test_refresh_carries_queue(self):
        product = dict(asin='B0SAMP0025', sku='test', product='Test', human_review=[proposal()])
        doc = dashboard.refresh_doc({'asin':'B0SAMP0025','card':{},'run':{}}, product, SHARED, 'Test')
        self.assertEqual(doc['card']['human_review_count'], 0)
        self.assertEqual(doc['card']['ai_research_count'], 1)

    def test_duplicate_ids_and_statuses_rejected(self):
        with self.assertRaises(ValueError):
            human_review.validate([proposal(), proposal()])
        invalid = dict(proposal(), status='approved')
        with self.assertRaises(ValueError):
            human_review.validate([invalid])


# --- Needs human "Bids" items (propose_bids, validate for kind 'bid', the merge supersede) -------------------------
DATE = '2026-10-19'
SERIAL = iter(range(1, 10 ** 6))


def change(**over):
    """One plan change row as plan_lanes.assign leaves it: a human-lane bid change with every field the item copies."""
    n = next(SERIAL)
    row = dict(type='Bid change', keyword=f'search {n}', match='exact', role='Hold', current=0.5, new=0.6, orders90=3,
               clicks90=40, confidence_text='70% sure it beats the market', opportunity=10.0, lane='human',
               lane_reason='not enough proof to bid above breakeven; a person decides', row_id=f'Bid change:{n}',
               keyword_id=str(n), campaign='Cards - Exact', why='Converts at the market: its breakeven click.')
    row.update(over)
    return row


def bid_plan(*changes, shadow=False, onboarding=None, run='run-2026-10-19'):
    return dict(summary=[dict(run=run, shadow=shadow, onboarding_reason=onboarding)], changes=list(changes))


def promotion(keyword='blank cards', **over):
    """A promotion with its bundle: the new campaign, a duplicate exact pause, a funnel negative and a budget row.
    Until 2026-10-22 the planner flagged every promotion against Kim's $600 monthly level (past_kim_level); decision
    99 took the level out, so a plan no longer carries the flag and an old plan's flag decides nothing."""
    rows = [change(type='New exact campaign', keyword=keyword, role='Invest', current=None, new=0.8, orders90=None,
                   clicks90=None, row_id=f'New exact campaign:::{keyword}'),
            change(type='Pause keyword', keyword=keyword, match='exact', role=None, current=0.5, new=None,
                   row_id=f'Pause keyword:{keyword}'),
            change(type='Negative exact', keyword=keyword, role=None, current=None, new=None,
                   row_id=f'Negative exact:1:2:{keyword}'),
            change(type='Budget and top of search', keyword=keyword, role='Invest', current=None, new=None,
                   row_id=f'Budget and top of search:{keyword}')]
    for row in rows:
        row.update(over)
    return rows


class BidItemTests(unittest.TestCase):
    ROW_FIELDS = {'row_id', 'keyword', 'type', 'role', 'current', 'new', 'orders90', 'clicks90', 'confidence_text',
                  'opportunity', 'lane_reason', 'approval_required', 'lane', 'lane_unlocked'}
    LOCK_FIELDS = {'locked_until', 'lock_by', 'lock_on', 'lock_decision'}  # the item row's names for a plan change's lock

    def test_propose_bids_sorted_by_opportunity(self):
        a, b, c, d, e = (change(opportunity=o) for o in (5.0, None, 50.0, 20.0, 20.0))
        auto = change(opportunity=99.0, lane='auto')
        monitor = change(opportunity=80.0, lane='monitor')
        item = human_review.propose_bids(bid_plan(a, b, c, auto, d, e, monitor), DATE)
        self.assertEqual([r['row_id'] for r in item['rows']],
                         [c['row_id'], d['row_id'], e['row_id'], a['row_id'], b['row_id']])  # None last, plan order breaks the tie
        self.assertEqual(item['id'], 'bids-2026-10-19')
        self.assertEqual((item['kind'], item['status'], item['origin']), ('bid', 'open', 'sweep'))
        self.assertEqual(item['title'], '5 bid changes to decide')
        self.assertEqual(item['ai_review']['phase'], 'human_ready')
        self.assertEqual((item['first_seen'], item['last_seen']), (DATE, DATE))
        top = item['rows'][0]
        self.assertEqual(top, dict(row_id=c['row_id'], keyword=c['keyword'], type='Bid change', role='Hold', current=0.5,
                                   new=0.6, orders90=3, clicks90=40, confidence_text='70% sure it beats the market',
                                   opportunity=50.0, lane_reason=c['lane_reason'], approval_required='owner', lane='human',
                                   lane_unlocked='human'))

    def test_propose_bids_leaves_the_plan_as_it_was(self):
        plan = bid_plan(*promotion(), change(opportunity=3.0), change(lane='auto'), shadow=True)
        before = copy.deepcopy(plan)
        item = human_review.propose_bids(plan, DATE)
        self.assertEqual(plan, before)
        item['rows'][0]['keyword'] = 'edited'
        self.assertEqual(plan, before)  # the item's rows are copies

    def test_item_text_and_source(self):
        plan = bid_plan(change(), change(lane='auto'), change(lane='monitor'), run='B0TEST0001-2026-10-19')
        item = human_review.propose_bids(plan, DATE)
        self.assertEqual(item['title'], '1 bid change to decide')
        # since 2026-10-24 (Kim: execute whenever the audit runs, weekends included); it read "on the next US weekday"
        self.assertEqual(item['action'], 'Approve or decline each row. Approved rows are applied during the audit through '
                                         'MarketplaceAdPros.')
        self.assertEqual(item['source'], 'AI bid planner (plan.json), B0TEST0001-2026-10-19')
        self.assertEqual(item['reason'], 'Of 3 planned changes: 1 to apply automatically, 1 waiting for a person, '
                                         '1 held until the next run.')
        self.assertIn('SQP', item['window'])
        self.assertIn('B0TEST0001-2026-10-19', item['window'])
        self.assertIs(item['shadow'], False)
        self.assertEqual(item['locked_rows'], 0)
        self.assertNotIn('locked_count', item)

    def test_window_uses_the_plans_terms_window(self):
        plan = dict(bid_plan(change()), terms_window='SQP to 2026-10-12 / ads 90 days')
        self.assertEqual(human_review.propose_bids(plan, DATE)['window'], 'SQP to 2026-10-12 / ads 90 days')

    def test_shadow_lists_every_lane(self):
        rows = [change(opportunity=1.0), change(opportunity=3.0, lane='auto', new_capped=0.55),
                change(opportunity=2.0, lane='monitor')]
        item = human_review.propose_bids(bid_plan(*rows, shadow=True), DATE)
        self.assertIs(item['shadow'], True)
        self.assertEqual(item['title'], '3 changes to agree or refuse (shadow run)')
        self.assertEqual([r['lane'] for r in item['rows']], ['auto', 'monitor', 'human'])
        self.assertIn('Shadow run', item['reason'])
        self.assertIn('Each row below can be marked agree or refuse', item['reason'])
        self.assertIn('Of 3 planned changes: 1 the planner would have applied on its own', item['reason'])
        one = human_review.propose_bids(bid_plan(change(), shadow=True), DATE)
        self.assertEqual(one['title'], '1 change to agree or refuse (shadow run)')

    def test_enabled_lists_human_rows_only(self):
        rows = [change(lane='auto'), change(lane='monitor'), change(lane='human')]
        item = human_review.propose_bids(bid_plan(*rows, shadow=False), DATE)
        self.assertEqual([r['lane'] for r in item['rows']], ['human'])
        self.assertIs(item['shadow'], False)

    def test_a_plan_without_a_shadow_flag_counts_as_shadow(self):
        # the same rule write_outputs uses: only an explicit False turns the auto lane on
        plan = dict(summary=[dict(run='r')], changes=[change(lane='auto'), change()])
        self.assertEqual(len(human_review.propose_bids(plan, DATE)['rows']), 2)

    def test_locked_rows_stay_on_the_item_with_who_decided(self):
        """A4 (I3): a row a lock holds is still shown, marked with who decided it, when, what they decided and the lane
        the planner would have given it, so a new call on it reaches a person and the shadow gate can count it."""
        for shadow in (False, True):
            with self.subTest(shadow=shadow):
                declined = change(opportunity=30.0, locked_until='2026-11-16', decided_by='Lee', decided_on='2026-10-19',
                                  decision='decline', lane_unlocked='auto')
                experiment = change(opportunity=20.0, locked_until='further notice', decided_by=None, decided_on=None,
                                    decision='experiment', lane_unlocked='human')
                free = change(opportunity=10.0, lane_unlocked='human')
                item = human_review.propose_bids(bid_plan(declined, experiment, free, shadow=shadow), DATE)
                rows = {r['row_id']: r for r in item['rows']}
                self.assertEqual(list(rows), [declined['row_id'], experiment['row_id'], free['row_id']])
                self.assertEqual({k: rows[declined['row_id']][k] for k in self.LOCK_FIELDS | {'lane', 'lane_unlocked'}},
                                 dict(locked_until='2026-11-16', lock_by='Lee', lock_on='2026-10-19',
                                      lock_decision='decline', lane='human', lane_unlocked='auto'))
                self.assertEqual({k: rows[experiment['row_id']][k] for k in self.LOCK_FIELDS},
                                 dict(locked_until='further notice', lock_by=None, lock_on=None, lock_decision='experiment'))
                self.assertFalse(self.LOCK_FIELDS & set(rows[free['row_id']]))
                # the plan change's own names never reach the item row: the server writes decision and decided_by there
                for row in rows.values():
                    self.assertFalse({'decision', 'decided_by', 'decided_on'} & set(row))
                self.assertEqual(item['locked_rows'], 2)
                self.assertNotIn('locked_count', item)
                self.assertIn('2 rows are held by an earlier decision (a person\'s, or a planned rank experiment) and are '
                              'shown with it', item['reason'])
        one = human_review.propose_bids(bid_plan(change(locked_until='2026-11-16', decision='approve'), change()), DATE)
        self.assertIn('1 row is held by an earlier decision (a person\'s, or a planned rank experiment) and is shown with it',
                      one['reason'])
        self.assertEqual(human_review.propose_bids(bid_plan(change()), DATE)['locked_rows'], 0)

    def test_none_when_there_is_nothing_to_decide(self):
        self.assertIsNone(human_review.propose_bids(bid_plan(), DATE))
        self.assertIsNone(human_review.propose_bids(dict(summary=[{}], changes=[]), DATE))
        self.assertIsNone(human_review.propose_bids({}, DATE))
        self.assertIsNone(human_review.propose_bids(bid_plan(change(lane='auto'), change(lane='monitor')), DATE))
        # a row a lock holds is still a row to show (A4): only an item with no rows at all is None
        for shadow in (False, True):
            only_locked = human_review.propose_bids(bid_plan(change(locked_until='2026-11-16'), shadow=shadow), DATE)
            self.assertEqual((len(only_locked['rows']), only_locked['locked_rows']), (1, 1))

    def test_missing_values_are_none_and_new_capped_only_when_carried(self):
        bare = dict(type='Stop-loss review', row_id='Stop-loss review:::blank cards', lane='human')
        item = human_review.propose_bids(bid_plan(bare), DATE)
        row = item['rows'][0]
        self.assertEqual(set(row), self.ROW_FIELDS)
        self.assertEqual([k for k, v in row.items() if v is None],
                         ['keyword', 'role', 'current', 'new', 'orders90', 'clicks90', 'confidence_text', 'opportunity',
                          'lane_reason'])
        capped = change(lane='auto', new_capped=0.55)
        shown = human_review.propose_bids(bid_plan(capped, change(), shadow=True), DATE)['rows']
        self.assertEqual(sorted(set(shown[0]) - self.ROW_FIELDS), ['new_capped'])
        self.assertEqual(shown[0]['new_capped'], 0.55)
        self.assertEqual(set(shown[1]), self.ROW_FIELDS)

    def test_rows_carry_the_budgets_and_boosts_they_change(self):
        """E2 (I2): what a row commits beyond its bid is on the item row, so the card can show it and `seen` can cover it.
        A budget row carries budget_now, budget, tos_now and tos; a promotion its budget and modelled_spend_month (None
        when the plan has none), and the boost fields it has; a plain bid row none of them."""
        budget = change(type='Budget and top of search', keyword='thank you cards', role='Invest', current=None, new=None,
                        budget_now=10, budget=15, tos_now=50, tos=50, row_id='Budget and top of search:105:205:thank you cards')
        promo = change(type='New exact campaign', keyword='blank cards', role='Invest', current=None, new=0.88, budget=10,
                       tos=0, tos_now=None, modelled_spend_month=300, row_id='New exact campaign:::blank cards')
        reuse = change(type='Reuse exact campaign', keyword='note cards', role='Invest', current=None, new=0.7, budget=10,
                       budget_now=5, tos=20, tos_now=20, row_id='Reuse exact campaign:107:none:note cards')
        bare_promo = change(type='New exact campaign', keyword='gold cards', role='Invest', current=None, new=0.5,
                            row_id='New exact campaign:::gold cards')
        plain = change()
        rows = {r['row_id']: r for r in human_review.propose_bids(bid_plan(budget, promo, reuse, bare_promo, plain), DATE)['rows']}
        money = ('budget_now', 'budget', 'tos_now', 'tos', 'modelled_spend_month')

        def pick(rid):
            return {k: rows[rid][k] for k in money if k in rows[rid]}
        self.assertEqual(pick(budget['row_id']), dict(budget_now=10, budget=15, tos_now=50, tos=50))
        self.assertEqual(pick(promo['row_id']), dict(budget=10, tos_now=None, tos=0, modelled_spend_month=300))
        self.assertEqual(pick(reuse['row_id']), dict(budget_now=5, budget=10, tos_now=20, tos=20, modelled_spend_month=None))
        self.assertEqual(pick(bare_promo['row_id']), dict(budget=None, modelled_spend_month=None))
        self.assertEqual(pick(plain['row_id']), {})

    def test_a_declined_row_needs_at_least_the_decliners_level(self):
        """E3 (I3): approving a row a decline holds needs a signer at the row's own level and at the decliner's: Kim when
        Kim declined, Lee when Lee did, a book owner otherwise. The item row says so, so the card shows it. Since
        2026-10-22 no bid row starts at Lee's level, so a decline is the only way a row asks for her."""
        held = dict(locked_until='2026-11-16', decision='decline', decided_on='2026-10-20')
        rows = dict(by_lee=change(decided_by='Lee', **held),
                    by_kim=change(decided_by=' kim ', **held),  # named as approvals reads names: trimmed, any case
                    by_owner=change(decided_by='Sam', **held),
                    by_nobody=change(decided_by=None, **held),
                    stop_loss_by_owner=change(type='Stop-loss review', role='Invest', current=None, new=None,
                                              decided_by='Sam', **held),
                    stop_loss_by_lee=change(type='Stop-loss review', role='Invest', current=None, new=None,
                                                decided_by='Lee', **held),
                    price_by_lee=change(type='Listing price', keyword=None, role=None, current=7.99, new=8.49,
                                            decided_by='Lee', **held),  # a Kim row stays Kim's
                    approve_lock=change(locked_until='2026-11-16', decision='approve', decided_by='Kim'),
                    approve_lock_by_lee=change(locked_until='2026-11-16', decision='approve', decided_by='Lee'),
                    experiment=change(locked_until='further notice', decision='experiment', decided_by=None))
        item = human_review.propose_bids(bid_plan(*rows.values()), DATE)
        level = {r['row_id']: r['approval_required'] for r in item['rows']}
        self.assertEqual({name: level[c['row_id']] for name, c in rows.items()},
                         dict(by_lee='Lee', by_kim='Kim', by_owner='owner', by_nobody='owner',
                              stop_loss_by_owner='owner', stop_loss_by_lee='Lee', price_by_lee='Kim',
                              approve_lock='owner', approve_lock_by_lee='owner', experiment='owner'))
        self.assertEqual(item['approval_required'], 'Kim')
        self.assertEqual([human_review.signer_level(n) for n in ('Kim', ' LEE ', 'Sam', '', None)],
                         ['Kim', 'Lee', 'owner', 'owner', 'owner'])

    def test_a_row_without_a_keyword_shows_its_item_text(self):
        price = dict(type='Listing price', item='Price, SKU TEST-SKU', current=7.99, new=8.49, row_id='Listing price:::',
                     lane='human')
        self.assertEqual(human_review.propose_bids(bid_plan(price), DATE)['rows'][0]['keyword'], 'Price, SKU TEST-SKU')

    def test_every_approval_level_and_the_item_maximum(self):
        """Kim, 2026-10-22: the book owner approves every bid call on their own products. Kim keeps the listing price
        (and a Scale Insights rule set beyond the standard setup). Decision 99, the same evening: no promotion is his for
        money, so a promotion and its bundle are the owner's whatever they spend, and an old plan's past_kim_level flag
        changes nothing. No bid row starts at Lee's level."""
        promo_k = promotion('gold cards', past_kim_level=True)   # an old plan's flag
        promo_o = promotion('blank cards')
        owner_rows = [change(role='Hold', current=0.4, new=0.5),                       # a raise inside the rulebook
                      change(type='Bid change', role='Invest', current=0.4, new=0.5),  # an invest raise
                      change(type='Target bid change', role='Trim', current=0.5, new=0.3),
                      change(type='SB bid change', role='Invest', current=0.5, new=0.8),
                      change(type='Pause keyword', role=None, current=0.5, new=None, orders90=4),  # a pause with orders
                      change(type='Harvest default bid', keyword='(harvest ad group)', role='Harvest'),
                      change(type='Negative exact', keyword='lonely search', role=None),  # no promotion for it
                      # Lee's until 2026-10-22, the book owner's since
                      change(type='Bid change', role='Invest', current=0.8, new=0.5),  # a cut of an Invest search
                      change(type='Bid change', role='Prove first', current=0.8, new=0.5),
                      change(type='SB pause keyword', role='Invest', current=0.8, new=None),
                      change(type='SB pause keyword', role='Negate', current=0.8, new=None),  # an irrelevant search
                      change(type='New SB video campaign', role='Invest', current=None, new=0.9),
                      change(type='SB bid change', role='Prove first', current=0.8, new=0.5),
                      change(type='Stop-loss review', role='Invest', current=None, new=None),
                      change(type='Budget and top of search', keyword='no promotion', role='Invest'),
                      change(type='Budget step', keyword=None, role=None, budget_now=10, budget=15),  # +$150 a month
                      change(type='Scale Insights rules', keyword=None, role=None),
                      change(type='Scale Insights setup', keyword=None, role=None),
                      # E1: a cut or pause on a search the team invests in, whatever its role this week
                      change(type='Bid change', role='Hold', current=0.8, new=0.5, invested_search=True),
                      change(type='Pause keyword', role='Trim', current=0.8, new=None, orders90=0, invested_search=True)]
        kim_rows = [change(type='Listing price', keyword=None, role=None, current=7.99, new=8.49)]
        plan = bid_plan(*owner_rows, *promo_o, *promo_k, *kim_rows)
        item = human_review.propose_bids(plan, DATE)
        level = {r['row_id']: r['approval_required'] for r in item['rows']}
        self.assertEqual({level[r['row_id']] for r in owner_rows}, {'owner'})
        self.assertEqual({level[r['row_id']] for r in promo_o}, {'owner'})     # a promotion and its bundle
        self.assertEqual({level[r['row_id']] for r in promo_k}, {'owner'})     # the old $600 flag is ignored
        self.assertEqual({level[r['row_id']] for r in kim_rows}, {'Kim'})
        self.assertNotIn('Lee', human_review.row_levels(plan))
        self.assertEqual(item['approval_required'], 'Kim')
        with_promotion = human_review.propose_bids(bid_plan(*owner_rows, *promo_o), DATE)
        self.assertEqual(with_promotion['approval_required'], 'owner')
        only_owner = human_review.propose_bids(bid_plan(*owner_rows), DATE)
        self.assertEqual(only_owner['approval_required'], 'owner')

    def test_the_book_owner_approves_every_bid_call(self):
        """Pins Kim's 2026-10-22 split row by row: a promotion is the owner's whatever it spends (decision 99 took the
        $600 level out, so an old plan's flag or a missing one changes nothing); a stop-loss review, a cut of an Invest
        search, a 'Budget and top of search' row and a big budget step are the owner's, and so is every row of an
        onboarding product or of a season phase switch. The listing price stays Kim's. A listing item is still Lee's
        (the team leader's harder product calls)."""
        def level_of(row, **summary):
            plan = dict(summary=[dict(run='r', shadow=False, **summary)], changes=[row])
            return human_review.row_levels(plan)[0]
        cases = dict(
            promotion_inside=(promotion('blank cards')[0], 'owner'),
            promotion_past=(promotion('gold cards', past_kim_level=True)[0], 'owner'),   # an old plan's flag
            promotion_unflagged=(promotion('red cards')[0], 'owner'),
            stop_loss=(change(type='Stop-loss review', role='Invest', current=None, new=None), 'owner'),
            invest_cut=(change(type='Bid change', role='Invest', current=0.9, new=0.4), 'owner'),
            invest_pause=(change(type='Pause keyword', role='Invest', current=0.9, new=None, invested_search=True), 'owner'),
            budget_and_tos=(change(type='Budget and top of search', role='Invest', budget_now=10, budget=40, tos_now=0, tos=50),
                            'owner'),
            big_budget_step=(change(type='Budget step', keyword=None, role=None, budget_now=10, budget=50), 'owner'),  # +$1,200 a month
            policy_tos_inside=(change(type='Budget and top of search', role='Invest', policy_tos_only=True, budget_now=10,
                                      budget=10, tos_now=0, tos=50), 'owner'),
            policy_tos_past=(change(type='Budget and top of search', role='Invest', policy_tos_only=True, budget_now=10,
                                    budget=10, tos_now=0, tos=50, past_kim_level=True), 'owner'))   # an old plan's flag
        for name, (row, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(level_of(row), expected)
        onboarding = dict(onboarding_reason='the AI took over on 2026-10-20')
        switch = dict(season=dict(phase='harvest', switch='rank build -> harvest'))
        for summary in (onboarding, switch):
            with self.subTest(summary=summary):
                for name in ('stop_loss', 'invest_cut', 'budget_and_tos', 'big_budget_step', 'promotion_inside'):
                    self.assertEqual(level_of(cases[name][0], **summary), 'owner')
                self.assertEqual(level_of(cases['promotion_past'][0], **summary), 'owner')
                self.assertEqual(level_of(change(type='Listing price', keyword=None, role=None, current=7.99, new=8.49),
                                          **summary), 'Kim')
        self.assertEqual(proposal()['kind'], 'listing')
        self.assertEqual(proposal()['approval_required'], 'Lee')

    def test_a_promotion_row_that_is_not_in_the_human_lane_still_has_its_level(self):
        # shadow mode lists auto promotions too: they are the book owner's calls (Kim's past his $600 level until
        # 2026-10-22, decision 99)
        item = human_review.propose_bids(bid_plan(*promotion(lane='auto'), shadow=True), DATE)
        self.assertEqual({r['approval_required'] for r in item['rows']}, {'owner'})
        past = human_review.propose_bids(bid_plan(*promotion(lane='auto', past_kim_level=True), shadow=True), DATE)
        self.assertEqual({r['approval_required'] for r in past['rows']}, {'owner'})

    def test_onboarding_rows_keep_their_own_level(self):
        # Lee's until 2026-10-22; since then an onboarding product's rows are the book owner's, Kim's rows still Kim's
        owner = change(role='Hold', current=0.4, new=0.5)
        price = change(type='Listing price', keyword=None, role=None, current=7.99, new=8.49)
        item = human_review.propose_bids(bid_plan(owner, price, onboarding='the AI took over on 2026-10-14'), DATE)
        level = {r['row_id']: r['approval_required'] for r in item['rows']}
        self.assertEqual(level[owner['row_id']], 'owner')
        self.assertEqual(level[price['row_id']], 'Kim')
        later = human_review.propose_bids(bid_plan(owner, onboarding=None), DATE)
        self.assertEqual(later['rows'][0]['approval_required'], 'owner')

    def test_no_promotion_is_kims_for_money(self):
        """A2 (C2) sent a promotion, with its bundle, to Kim from the planner's past_kim_level flag, and a promotion
        without the flag to him as a fail-safe. Kim, 2026-10-22, decision 99: "we don't want to put a cap and hamper the
        autonomous engine". A promotion and its bundle are the book owner's whatever the flag, the reason or its absence."""
        old_text = 'it would take the product past $600 a month of invest spend'
        for flag, reason in ((False, old_text), (True, 'the product is onboarding'),
                             (True, "the product's monthly invest band is short"), (False, None)):
            with self.subTest(flag=flag, reason=reason):
                rows = promotion(lane_reason=reason, past_kim_level=flag)
                level = {r['row_id']: r['approval_required'] for r in human_review.propose_bids(bid_plan(*rows), DATE)['rows']}
                self.assertEqual(set(level.values()), {'owner'})  # the promotion and its whole bundle
        self.assertEqual(human_review.propose_bids(bid_plan(promotion()[0]), DATE)['rows'][0]['approval_required'], 'owner')
        self.assertFalse(hasattr(lanes, 'past_kim_level_text'))

    def test_a_bundle_member_alone_is_the_owners(self):
        # a member with no promotion in the plan has no bundle; neither an old flag nor the reason text makes it Kim's
        member = change(type='Negative exact', keyword='gold cards', role=None,
                        lane_reason='it would take the product past $600 a month of invest spend')
        self.assertEqual(human_review.propose_bids(bid_plan(member), DATE)['rows'][0]['approval_required'], 'owner')
        flagged = dict(member, past_kim_level=True)
        self.assertEqual(human_review.propose_bids(bid_plan(flagged), DATE)['rows'][0]['approval_required'], 'owner')

    # --- validate -------------------------------------------------------------------------------------------------
    def bid_item(self, **over):
        item = human_review.propose_bids(bid_plan(change(), change()), DATE)
        item.update(over)
        return item

    def test_validate_rejects_bid_without_rows(self):
        item = self.bid_item()
        for rows in (None, [], 'rows', {'row_id': 'x'}):
            with self.subTest(rows=rows):
                broken = dict(item, rows=rows)
                with self.assertRaises(ValueError):
                    human_review.validate([broken])
        del item['rows']
        with self.assertRaises(ValueError):
            human_review.validate([item])

    def test_validate_rejects_a_bad_row(self):
        good = self.bid_item()['rows'][0]
        bad_rows = [dict(good, row_id=None), dict(good, row_id=''), dict(good, row_id=7), dict(good, row_id='  '),
                    {k: v for k, v in good.items() if k != 'row_id'}, dict(good, type=None), dict(good, type=''),
                    {k: v for k, v in good.items() if k != 'type'}, dict(good, approval_required='admin'),
                    dict(good, approval_required=None), {k: v for k, v in good.items() if k != 'approval_required'},
                    'not a row']
        for bad in bad_rows:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    human_review.validate([self.bid_item(rows=[good, bad])])

    def test_validate_keeps_a_bid_items_own_approval_level(self):
        item = self.bid_item()
        self.assertEqual(item['approval_required'], 'owner')
        self.assertEqual(human_review.validate([item])[0]['approval_required'], 'owner')  # not today's Lee default
        kept = human_review.validate([dict(item, approval_required='Kim')])[0]
        self.assertEqual(kept['approval_required'], 'Kim')
        without = {k: v for k, v in item.items() if k != 'approval_required'}
        self.assertEqual(human_review.validate([without])[0]['approval_required'], 'owner')  # the rows' highest level
        mixed = dict(without, rows=[dict(r, approval_required=l) for r, l in zip(item['rows'], ('owner', 'Lee'))])
        self.assertEqual(human_review.validate([mixed])[0]['approval_required'], 'Lee')
        weird = dict(mixed, approval_required='admin')  # an unreadable level falls back to the safe, highest one
        self.assertEqual(human_review.validate([weird])[0]['approval_required'], 'Lee')

    def test_validate_round_trips_a_bid_item_and_keeps_listing_and_price_rules(self):
        item = self.bid_item()
        self.assertEqual(human_review.validate([item])[0], item)
        listing = dict(proposal(), approval_required='owner')
        self.assertEqual(human_review.validate([listing])[0]['approval_required'], 'Lee')
        price = dict(proposal(), id='price-test', kind='price', price={'direction': 'review', 'current': 7.99, 'proposed': None},
                     approval_required='owner')
        self.assertEqual(human_review.validate([price])[0]['approval_required'], 'Kim')
        with self.assertRaises(ValueError):
            human_review.validate([dict(proposal(), kind='mystery')])

    def test_a_bids_item_counts_as_waiting_for_a_person(self):
        doc = {'card': {}}
        human_review.attach(doc, dict(human_review=[self.bid_item()]))
        self.assertEqual(doc['card']['human_review_count'], 1)
        self.assertEqual(doc['card']['ai_research_count'], 0)

    # --- merge ----------------------------------------------------------------------------------------------------
    def stored(self, date, status='open', plan=None):
        item = human_review.propose_bids(plan or bid_plan(change(), change()), date)
        if status != 'open':
            item = human_review.transition([item], item['id'], status, 'Lee', 'earlier note', date)[0]
        return item

    def test_bids_item_supersedes_older(self):
        old_open = self.stored('2026-10-12')
        old_busy = self.stored('2026-10-05', 'in_progress')
        old_wait = self.stored('2026-09-28', 'waiting_approval')
        old_done = self.stored('2026-09-21', 'resolved')
        old_gone = self.stored('2026-09-14', 'dismissed')
        listing = proposal()
        new = self.stored('2026-10-19')
        result = {i['id']: i for i in human_review.merge([old_open, old_busy, old_wait, old_done, old_gone, listing],
                                                        [new], '2026-10-19')}
        for old in (old_open, old_busy, old_wait):
            item = result[old['id']]
            self.assertEqual(item['status'], 'dismissed', old['id'])
            self.assertEqual(item['resolution'], 'Superseded by bids-2026-10-19')
            self.assertEqual(item['resolved_on'], '2026-10-19')
            self.assertEqual(item['history'][-1], dict(date='2026-10-19', status='dismissed', owner=old.get('owner'),
                                                       note='Superseded by bids-2026-10-19'))
        self.assertEqual(result[old_busy['id']]['owner'], 'Lee')  # who held it stays on the record
        self.assertEqual(result[old_done['id']]['status'], 'resolved')
        self.assertEqual(result[old_done['id']]['resolution'], 'earlier note')  # left alone, not re-dismissed
        self.assertEqual(result[old_gone['id']]['history'], old_gone['history'])
        self.assertEqual(result[listing['id']]['status'], 'open')
        self.assertEqual(result['bids-2026-10-19']['status'], 'open')
        self.assertEqual(len(result), 7)

    def test_a_merge_with_no_bids_item_leaves_older_ones_open(self):
        old = self.stored('2026-10-12')
        result = human_review.merge([old], [proposal()], '2026-10-19')
        self.assertEqual({i['id']: i['status'] for i in result}, {old['id']: 'open', 'listing-conversion-gap': 'open'})

    def test_a_run_with_nothing_to_decide_still_supersedes_older_items(self):
        """A6 (I4): a run whose plan has no Bids item left the older item open and approvable, so a stale approval could
        write over what the auto lane had since applied."""
        older, busy, waiting = self.stored('2026-10-12'), self.stored('2026-10-05', 'in_progress'), self.stored('2026-09-28', 'waiting_approval')
        same_day, newer = self.stored('2026-10-19'), self.stored('2026-10-26')
        done, gone, listing = self.stored('2026-09-21', 'resolved'), self.stored('2026-09-14', 'dismissed'), proposal()
        result = {i['id']: i for i in human_review.merge([older, busy, waiting, same_day, newer, done, gone, listing],
                                                        [proposal()], '2026-10-20', run_date='2026-10-19')}
        note = 'Superseded by the run of 2026-10-19, which had nothing to decide'
        for old in (older, busy, waiting):
            item = result[old['id']]
            self.assertEqual((item['status'], item['resolution'], item['resolved_on']), ('dismissed', note, '2026-10-20'), old['id'])
            self.assertEqual(item['history'][-1], dict(date='2026-10-20', status='dismissed', owner=old.get('owner'), note=note))
            self.assertNotIn('rows', item)  # compacted, like any closed bid item
            self.assertEqual(item['rows_count'], len(old['rows']))
        self.assertEqual(result[busy['id']]['owner'], 'Lee')
        for kept, status in ((same_day, 'open'), (newer, 'open'), (done, 'resolved'), (gone, 'dismissed'), (listing, 'open')):
            self.assertEqual(result[kept['id']]['status'], status, kept['id'])
        self.assertEqual(result[done['id']]['resolution'], 'earlier note')
        self.assertEqual(result[gone['id']]['history'], gone['history'])
        # an unreadable run date supersedes nothing
        kept = human_review.merge([older], [], '2026-10-20', run_date='last monday')
        self.assertEqual(kept[0]['status'], 'open')
        # a run that has its own Bids item supersedes as before, by its item id
        result = {i['id']: i for i in human_review.merge([older], [self.stored('2026-10-19')], '2026-10-20', run_date='2026-10-19')}
        self.assertEqual(result[older['id']]['resolution'], 'Superseded by bids-2026-10-19')

    def test_the_dashboard_build_passes_the_runs_own_date(self):
        """A6: build_doc passes the plan's review_date (the date the bids item id uses), not the publish date, and only for a
        plan made with lanes; an older plan supersedes nothing."""
        with tempfile.TemporaryDirectory() as directory:
            data = pathlib.Path(directory)
            (data / 'asins').mkdir()
            product = dict(asin='B0SAMP0025', sku='test', product='Test', price=7.99,
                           human_review=[self.stored('2026-10-12'), self.stored('2026-10-26')])
            (data / 'asins/B0SAMP0025.json').write_text(json.dumps(product), encoding='utf-8')
            summary = dict(lanes=dict(auto=3, human=0, monitor=1), review_date='2026-10-19')
            for plan_summary, expected in ((summary, 'dismissed'), (dict(summary, lanes=None), 'open'),
                                           ({k: v for k, v in summary.items() if k != 'review_date'}, 'open')):
                with self.subTest(summary=plan_summary):
                    (data / 'plan.json').write_text(json.dumps({'summary': [plan_summary], 'human_review': []}), encoding='utf-8')
                    doc, state = dashboard.build_doc('B0SAMP0025', str(data), 'proposed', 'Test', '2026-10-27', 'Test', str(data))
                    status = {i['id']: i['status'] for i in state['human_review']}
                    self.assertEqual(status, {'bids-2026-10-12': expected, 'bids-2026-10-26': 'open'})  # never the newer run's
                    if expected == 'dismissed':
                        self.assertEqual(state['human_review'][0]['resolution'],
                                         'Superseded by the run of 2026-10-19, which had nothing to decide')

    def test_a_same_day_rerun_replaces_the_rows_and_keeps_the_decision_state(self):
        first = self.stored('2026-10-19', plan=bid_plan(change(), change()))
        held = human_review.transition([first], first['id'], 'in_progress', 'Lee', 'Looking at it', '2026-10-19')
        rerun = self.stored('2026-10-19', plan=bid_plan(change(), change(), change()))
        result = human_review.merge(held, [rerun], '2026-10-19')
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]['rows']), 3)
        self.assertEqual([r['row_id'] for r in result[0]['rows']], [r['row_id'] for r in rerun['rows']])
        self.assertEqual((result[0]['status'], result[0]['owner']), ('in_progress', 'Lee'))
        self.assertEqual(len(result[0]['history']), 1)  # nothing was superseded

    def test_only_the_newest_bids_item_stays_active(self):
        # two incoming items, or an old state with two open ones: one active bids item at a time, the newest run's
        a, b = self.stored('2026-10-19'), self.stored('2026-10-20')
        result = human_review.merge([], [a, b], '2026-10-20')
        self.assertEqual({i['id']: i['status'] for i in result}, {'bids-2026-10-19': 'dismissed', 'bids-2026-10-20': 'open'})
        older, newer = self.stored('2026-10-12'), self.stored('2026-10-26')
        result = {i['id']: i for i in human_review.merge([older, newer], [self.stored('2026-10-19')], '2026-10-27')}
        self.assertEqual({k: v['status'] for k, v in result.items()},
                         {'bids-2026-10-12': 'dismissed', 'bids-2026-10-19': 'dismissed', 'bids-2026-10-26': 'open'})
        self.assertEqual(result['bids-2026-10-12']['resolution'], 'Superseded by bids-2026-10-26')

    def test_an_older_run_published_again_is_the_one_superseded(self):
        # re-publishing an old run folder must not dismiss the newer run's open item
        newer = self.stored('2026-10-26')
        old_run = self.stored('2026-10-12')
        result = {i['id']: i for i in human_review.merge([newer], [old_run], '2026-10-27')}
        self.assertEqual({k: v['status'] for k, v in result.items()}, {'bids-2026-10-12': 'dismissed', 'bids-2026-10-26': 'open'})
        stale = result['bids-2026-10-12']
        self.assertEqual(stale['resolution'], 'Superseded by bids-2026-10-26')
        self.assertEqual(stale['history'][-1], dict(date='2026-10-27', status='dismissed', owner=None,
                                                    note='Superseded by bids-2026-10-26'))
        self.assertNotIn('rows', stale)  # closed the moment it arrives, so it is stored compact
        self.assertEqual((stale['rows_count'], stale['rows_dropped_on']), (len(old_run['rows']), '2026-10-27'))
        self.assertEqual([r['row_id'] for r in result['bids-2026-10-26']['rows']], [r['row_id'] for r in newer['rows']])
        self.assertEqual(result['bids-2026-10-26']['status'], 'open')
        # and a closed newer item does not stop the older run from opening
        closed = human_review.transition([newer], newer['id'], 'resolved', 'Lee', 'Done', '2026-10-27')
        again = {i['id']: i['status'] for i in human_review.merge(closed, [old_run], '2026-10-28')}
        self.assertEqual(again, {'bids-2026-10-12': 'open', 'bids-2026-10-26': 'resolved'})

    # --- a closed bid item keeps a summary, not its rows -----------------------------------------------------------
    def test_superseding_compacts_the_old_item(self):
        plan = bid_plan(*[change() for _ in range(60)], change(lane='auto'), change(lane='monitor'), shadow=True)
        old = self.stored('2026-10-12', plan=plan)
        self.assertEqual(len(old['rows']), 62)
        result = {i['id']: i for i in human_review.merge([old], [self.stored('2026-10-19')], '2026-10-19')}
        closed = result['bids-2026-10-12']
        self.assertEqual(closed['status'], 'dismissed')
        self.assertNotIn('rows', closed)
        self.assertEqual((closed['rows_count'], closed['rows_by_lane'], closed['rows_dropped_on']),
                         (62, {'human': 60, 'auto': 1, 'monitor': 1}, '2026-10-19'))
        for key in ('id', 'title', 'reason', 'action', 'source', 'window', 'approval_required', 'shadow', 'locked_rows'):
            self.assertEqual(closed[key], old[key], key)
        self.assertEqual(closed['history'][-1]['note'], 'Superseded by bids-2026-10-19')
        self.assertLess(len(json.dumps(closed)) * 10, len(json.dumps(old)))  # the rows were nearly all of it
        self.assertEqual(len(result['bids-2026-10-19']['rows']), 2)  # the newest keeps its rows

    def test_transition_to_a_closed_status_compacts_and_an_open_one_does_not(self):
        for status in ('dismissed', 'resolved'):
            with self.subTest(status=status):
                item = self.stored('2026-10-12', plan=bid_plan(change(), change(lane='auto'), change(), shadow=True))
                done = human_review.transition([item], item['id'], status, 'Lee', 'Handled', '2026-10-13')[0]
                self.assertEqual(done['status'], status)
                self.assertNotIn('rows', done)
                self.assertEqual((done['rows_count'], done['rows_by_lane'], done['rows_dropped_on']),
                                 (3, {'human': 2, 'auto': 1}, '2026-10-13'))
                self.assertEqual((done['resolution'], done['resolved_on']), ('Handled', '2026-10-13'))
        for status in ('in_progress', 'waiting_approval'):
            with self.subTest(status=status):
                item = self.stored('2026-10-12')
                held = human_review.transition([item], item['id'], status, 'Lee', 'Looking', '2026-10-13')[0]
                self.assertEqual(len(held['rows']), 2)
                self.assertFalse(set(held) & set(human_review.SUMMARY_KEYS))

    def test_an_active_bid_item_needs_its_rows_and_a_closed_one_without_rows_needs_its_count(self):
        item = self.stored('2026-10-12')
        closed = human_review.transition([item], item['id'], 'dismissed', 'Lee', 'Handled', '2026-10-13')[0]
        for status in human_review.ACTIVE:
            with self.subTest(status=status):
                with self.assertRaises(ValueError):
                    human_review.validate([dict(closed, status=status)])  # rows were dropped: not active any more
        for bad in (None, -1, True, '2'):
            with self.subTest(rows_count=bad):
                with self.assertRaises(ValueError):
                    human_review.validate([dict(closed, rows_count=bad)])
        with self.assertRaises(ValueError):
            human_review.validate([{k: v for k, v in closed.items() if k != 'rows_count'}])
        self.assertEqual(human_review.validate([closed])[0], closed)
        self.assertEqual(human_review.validate([dict(item, status='resolved')])[0]['status'], 'resolved')  # rows kept: fine
        with self.assertRaises(ValueError):
            human_review.validate([dict(item, rows=[])])  # an active item with an empty list

    def test_a_compacted_item_round_trips_through_validate_merge_and_attach(self):
        item = self.stored('2026-10-12')
        closed = human_review.transition([item], item['id'], 'dismissed', 'Lee', 'Not needed', '2026-10-13')[0]
        self.assertEqual(human_review.validate([closed])[0], closed)
        newest = self.stored('2026-10-19')
        merged = human_review.merge([closed], [newest], '2026-10-20')
        kept = next(i for i in merged if i['id'] == closed['id'])
        for key in ('status', 'rows_count', 'rows_by_lane', 'rows_dropped_on', 'resolution', 'resolved_on', 'approval_required'):
            self.assertEqual(kept[key], closed[key], key)
        self.assertNotIn('rows', kept)
        self.assertEqual(len(human_review.merge([], [closed], '2026-10-20')), 1)  # as an incoming item too
        doc = {'card': {}}
        human_review.attach(doc, dict(human_review=merged))
        self.assertEqual(doc['card']['human_review_count'], 1)  # the newest only
        self.assertEqual([i['id'] for i in doc['human_review']], [closed['id'], newest['id']])
        self.assertNotIn('rows', doc['human_review'][0])
        self.assertEqual(len(doc['human_review'][1]['rows']), 2)
        again = human_review.transition(merged, closed['id'], 'resolved', 'Kim', 'Checked', '2026-10-21')  # still compact
        self.assertNotIn('rows', again[0])

    def test_a_closed_item_that_dropped_its_rows_cannot_be_reopened(self):
        item = self.stored('2026-10-12')
        closed = human_review.transition([item], item['id'], 'dismissed', 'Lee', 'Handled', '2026-10-13')
        for status in human_review.ACTIVE:
            with self.subTest(status=status):
                with self.assertRaises(ValueError):
                    human_review.transition(closed, item['id'], status, None, 'Again', '2026-10-14')

    def test_a_same_day_rerun_of_a_closed_item_stays_compact(self):
        closed = self.stored('2026-10-19', 'resolved')
        rerun = self.stored('2026-10-19', plan=bid_plan(change(), change(), change()))
        result = human_review.merge([closed], [rerun], '2026-10-19')[0]
        self.assertEqual(result['status'], 'resolved')
        self.assertNotIn('rows', result)
        self.assertEqual((result['rows_count'], result['rows_dropped_on']), (3, '2026-10-19'))

    def test_a_later_sweep_that_reopens_a_closed_item_gives_it_rows_again(self):
        closed = self.stored('2026-10-19', 'resolved')
        rerun = self.stored('2026-10-19', plan=bid_plan(change(), change(), change()))
        result = human_review.merge([closed], [rerun], '2026-10-20')[0]
        self.assertEqual(result['status'], 'open')
        self.assertEqual(len(result['rows']), 3)
        self.assertFalse(set(result) & set(human_review.SUMMARY_KEYS))

    def test_listing_and_price_items_keep_their_fields_when_closed(self):
        item = proposal()
        done = human_review.transition([item], item['id'], 'dismissed', None, 'Fine', '2026-10-19')[0]
        self.assertEqual(done['evidence'], item['evidence'])
        self.assertFalse(set(done) & set(human_review.SUMMARY_KEYS))

    def test_validate_takes_the_higher_of_the_declared_and_the_rows_level(self):
        base = self.bid_item()

        def level(declared, *row_levels):
            rows = [dict(r, approval_required=l) for r, l in zip(base['rows'], row_levels)]
            return human_review.validate([dict(base, approval_required=declared, rows=rows)])[0]['approval_required']

        self.assertEqual(level('owner', 'owner', 'Kim'), 'Kim')      # a row the declared level doesn't cover
        self.assertEqual(level('Lee', 'Kim', 'owner'), 'Kim')
        self.assertEqual(level('Kim', 'owner', 'owner'), 'Kim')      # a declared level above every row is kept
        self.assertEqual(level('Kim', 'Lee', 'owner'), 'Kim')
        self.assertEqual(level('Lee', 'owner', 'Lee'), 'Lee')
        self.assertEqual(level('owner', 'owner', 'owner'), 'owner')
        self.assertEqual(level('owner', 'owner', 'Lee'), 'Lee')

    def test_the_dashboard_build_supersedes_through_its_merge_call(self):
        # dashboard.build_doc merges plan.json's human_review into the product's, and never saves it back
        with tempfile.TemporaryDirectory() as directory:
            data = pathlib.Path(directory)
            (data / 'asins').mkdir()
            product = dict(asin='B0SAMP0025', sku='test', product='Test', price=7.99, human_review=[self.stored('2026-10-12')])
            path = data / 'asins/B0SAMP0025.json'
            path.write_text(json.dumps(product), encoding='utf-8')
            (data / 'plan.json').write_text(json.dumps({'human_review': [self.stored('2026-10-19')]}), encoding='utf-8')
            doc, state = dashboard.build_doc('B0SAMP0025', str(data), 'proposed', 'Test', '2026-10-19', 'Test', str(data))
            self.assertEqual({i['id']: i['status'] for i in state['human_review']},
                             {'bids-2026-10-12': 'dismissed', 'bids-2026-10-19': 'open'})
            self.assertEqual(doc['card']['human_review_count'], 1)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['human_review'][0]['status'], 'open')

    def test_the_preview_still_renders_a_bids_item(self):
        page = preview.human_review_html([('Test product', [self.bid_item(title='<b>x</b>')])])
        self.assertIn('<h2>Bid approvals</h2>', page)
        self.assertNotIn('id="needs-human"', page)
        self.assertIn('Bid review', page)
        self.assertIn('Approve or decline each row.', page)
        self.assertNotIn('<b>x</b>', page)


# --- the For Growth item (kind growth; for-growth design 2026-10-22, launch design 4a and 4e) -------------------------
GROWTH_PLAN = {'summary': [{'product': 'Test cards', 'asin': 'B0TEST0001', 'sqp_data_through': '2026-11-14',
                            'stage': {'stage': 'mature', 'observed_days': 84, 'trusted_queries': 3}}],
               'terms': [dict(term='blank cards', role='Rank', sub_role='Invest', sqp_volume=2000, index=1.75,
                              index_basis='SQP', sqp_our_clicks=30, sqp_our_purchases=6, market_cvr=0.1,
                              why='beats the market (1.75) on 30 of our clicks')],
               'changes': []}
GROWTH_PRODUCT = {'asin': 'B0TEST0001', 'product': 'Test cards',
                  'growth': {'enabled': True, 'anchor': {'date': '2026-09-25', 'source': 'monday_launch_date'}}}
AI = {'registry': {'bid_owner': 'AI'}}
GAP_NOTE = 'Superseded by the For Growth item (design 2026-10-20)'


def growth_item(date='2026-11-20', trigger='first_pass', **over):
    """A For Growth item as growth.build_item makes it (no listing read), produced on `date`."""
    item = growth.build_item('B0TEST0001', GROWTH_PLAN, GROWTH_PRODUCT, SHARED, None, date, trigger,
                             produced=f'{date} 10:00 SGT')
    item.update(over)
    return item


def close(items, status, note, date):
    """A growth item closed the way it really closes: `resolved` by the AI's listing-change close (dashboard.py
    close_on_listing_change sets the same fields), `dismissed` by a person through `transition`, which refuses
    `resolved` on a growth item (the final review's M1, 2026-10-22)."""
    if status != 'resolved':
        return human_review.transition(items, 'for-growth', status, None, note, date)
    out = human_review.validate(items)
    human_review._set_status(out[0], 'resolved', None, note, date)
    return out


class GrowthItemTests(unittest.TestCase):
    def test_growth_kind_validates(self):
        self.assertEqual(human_review.KINDS, ('listing', 'price', 'bid', 'growth'))
        item = human_review.validate([growth_item()])[0]
        self.assertEqual((item['id'], item['kind'], item['status'], item['owner']), ('for-growth', 'growth', 'open', 'Growth'))
        self.assertEqual(item['ai_review'], {'phase': 'human_ready'})
        self.assertEqual(item['growth'], growth_item()['growth'])
        with self.assertRaisesRegex(ValueError, 'kind must be listing, price, bid or growth'):
            human_review.validate([dict(growth_item(), kind='copy')])
        # Growth's "Copy pushed" step is an active status of the growth item only (launch design 4e)
        self.assertIn('copy_pushed', human_review.ACTIVE)
        self.assertEqual(human_review.validate([dict(growth_item(), status='copy_pushed')])[0]['status'], 'copy_pushed')
        with self.assertRaisesRegex(ValueError, "status copy_pushed is the For Growth item's only"):
            human_review.validate([dict(proposal(), status='copy_pushed')])

    def test_growth_item_validates_block_fields(self):
        for field in ('pass', 'block_md', 'block'):
            with self.subTest(missing=field):
                item = growth_item()
                del item['growth'][field]
                with self.assertRaisesRegex(ValueError, f'for-growth: growth.{field}'):
                    human_review.validate([item])
        for field, bad in (('pass', 'third pass'), ('pass', ''), ('block_md', '  '), ('block', 'a string'),
                           ('block', None)):
            with self.subTest(field=field, bad=bad):
                item = growth_item()
                item['growth'][field] = bad
                with self.assertRaises(ValueError):
                    human_review.validate([item])
        with self.assertRaisesRegex(ValueError, 'for-growth: a growth item needs its growth block'):
            human_review.validate([dict(growth_item(), growth=None)])
        second = growth_item()
        second['growth']['pass'] = growth.PASS_SECOND
        self.assertEqual(human_review.validate([second])[0]['growth']['pass'], 'second optimization onward')

    def test_growth_merge_keeps_status_fields(self):
        # Growth picked the item up; a later run's flag refreshes its block in place (R7, R22)
        old = dict(growth_item('2026-11-20'), status='in_progress', status_by='Robin', status_at='2026-11-21T02:00:00Z',
                   owner='Robin', first_seen='2026-11-20',
                   history=[dict(date='2026-11-21', status='in_progress', owner='Robin', note='Picked up')])
        flag_line = dict(date='2026-11-27', status='in_progress', owner='Robin', note='rotate-out flag: gold cards')
        incoming = dict(growth_item('2026-11-27', 'rotate_out_flag'), status='in_progress', status_by='Robin',
                        status_at='2026-11-21T02:00:00Z', owner='Robin', first_seen='2026-11-20',
                        history=old['history'] + [flag_line])
        # the product file moved on after the plan was made: Growth marked the copy pushed
        stored = dict(old, status='copy_pushed', status_at='2026-11-26T02:00:00Z',
                      history=old['history'] + [dict(date='2026-11-26', status='copy_pushed', owner='Robin',
                                                     note='Copy pushed')])
        merged = human_review.merge([stored], [incoming], '2026-11-27', product=AI)[0]
        self.assertEqual((merged['status'], merged['status_by'], merged['status_at'], merged['owner'],
                          merged['first_seen']), ('copy_pushed', 'Robin', '2026-11-26T02:00:00Z', 'Robin', '2026-11-20'))
        self.assertEqual(merged['history'], stored['history'] + [flag_line])   # the stored lines, then the run's
        self.assertEqual(merged['growth']['produced'], '2026-11-27 10:00 SGT')   # the new block
        self.assertEqual(merged['growth']['trigger'], 'rotate_out_flag')
        self.assertEqual(merged['last_seen'], '2026-11-27')

    def test_new_growth_pass_over_closed_item_is_born_open(self):
        # R11 (amended): a new pass arriving over a resolved or dismissed item opens a fresh one, history kept
        for status in ('resolved', 'dismissed'):
            with self.subTest(status=status):
                old = close([dict(growth_item('2026-11-20'), status='in_progress', status_by='Robin',
                                  status_at='2026-11-21T02:00:00Z', owner='Robin')],
                            status, 'Listing changed', '2026-12-01')[0]
                line = dict(date='2027-01-20', status='open', owner='Growth', note='second optimization onward raised')
                incoming = dict(growth_item('2027-01-20', 'evidence_pass'), history=old['history'] + [line])
                merged = human_review.merge([old], [incoming], '2027-01-20', product=AI)[0]
                self.assertEqual(merged['status'], 'open')
                self.assertEqual((merged['owner'], merged['first_seen']), ('Growth', '2027-01-20'))
                for gone in ('status_by', 'status_at', 'resolved_on', 'resolution'):
                    self.assertNotIn(gone, merged)
                self.assertEqual(merged['history'], old['history'] + [line])
                self.assertEqual(merged['growth']['trigger'], 'evidence_pass')
                # without the run's own line the stored history is still kept
                bare = human_review.merge([old], [growth_item('2027-01-20', 'evidence_pass')], '2027-01-20')[0]
                self.assertEqual((bare['status'], bare['history']), ('open', old['history']))

    def test_growth_item_carried_unchanged_changes_nothing(self):
        # a run with no trigger carries the stored item; the copy it carries (same produced) never reopens or
        # overwrites the stored one, whatever happened to it after the plan
        old = close([growth_item('2026-11-20')], 'resolved', 'Listing changed', '2026-12-01')[0]
        old['growth']['proof'] = {'title': ['old', 'new']}
        carried = growth_item('2026-11-20')                                       # the plan's copy: still open
        merged = human_review.merge([old], [carried], '2026-12-08', product=AI)[0]
        self.assertEqual(merged['status'], 'resolved')
        self.assertEqual({k: v for k, v in merged.items() if k not in ('last_seen', 'detected_latest_sweep')},
                         {k: v for k, v in old.items() if k not in ('last_seen', 'detected_latest_sweep')})
        self.assertEqual((merged['last_seen'], merged['detected_latest_sweep']), ('2026-12-08', True))
        picked = dict(growth_item('2026-11-20'), status='in_progress', status_by='Kat')
        self.assertEqual(human_review.merge([picked], [growth_item('2026-11-20')], '2026-11-27')[0]['status_by'], 'Kat')
        # another block stamped in the same minute can't be ordered against the stored one: the stored item stands
        same_minute = human_review.merge([old], [growth_item('2026-11-20', 'manual')], '2026-12-08', product=AI)[0]
        self.assertEqual((same_minute['status'], same_minute['growth']), ('resolved', old['growth']))

    def test_a_refresh_planned_before_the_close_does_not_reopen_it(self):
        # fix round 1, probe (a): a flag refresh planned while Robin had the item in progress is published after the
        # listing change resolved it. The resolved item stands (R11: only a new item is born open; growth.passes agrees)
        picked = human_review.transition([growth_item('2026-11-20')], 'for-growth', 'in_progress', 'Robin', 'Picked up',
                                         '2026-11-21')[0]
        picked.update(status_by='Robin', status_at='2026-11-21T02:00:00Z')
        refresh = dict(growth_item('2026-11-27', 'rotate_out_flag'), status='in_progress', status_by='Robin',
                       status_at='2026-11-21T02:00:00Z', owner='Robin', first_seen='2026-11-20',
                       history=picked['history'] + [dict(date='2026-11-27', status='in_progress', owner='Robin',
                                                         note='rotate-out flag: gold cards')])
        resolved = close([picked], 'resolved', 'Listing changed: title', '2026-12-01')[0]
        merged = human_review.merge([resolved], [refresh], '2026-12-01', product=AI)[0]
        self.assertEqual((merged['status'], merged['resolved_on'], merged['resolution']),
                         ('resolved', '2026-12-01', 'Listing changed: title'))
        self.assertEqual((merged['growth'], merged['history']), (resolved['growth'], resolved['history']))
        # a refresh of an item someone had picked up never reads as a new item, whatever its status
        stale = dict(refresh, status='open')
        self.assertEqual(human_review.merge([resolved], [stale], '2026-12-01')[0]['status'], 'resolved')
        # while a new pass built over the closed item (open, nobody's yet) is born open
        fresh = human_review.merge([resolved], [growth_item('2027-01-20', 'evidence_pass')], '2027-01-20')[0]
        self.assertEqual((fresh['status'], fresh['growth']['trigger']), ('open', 'evidence_pass'))

    def test_an_older_block_published_again_does_not_replace_the_newer(self):
        # fix round 1, probe (b): the stored block of 2026-12-04 is the one Growth picked up; the 2026-11-27 plan published
        # again must not put its older block back under "Picked up" (for-growth design 7)
        newer = dict(growth_item('2026-12-04', 'rotate_out_flag'), status='in_progress', status_by='Kat',
                     status_at='2026-12-05T02:00:00Z', first_seen='2026-11-20')
        older = growth_item('2026-11-27', 'rotate_out_flag')
        for stored in (dict(growth_item('2026-12-04', 'rotate_out_flag'), first_seen='2026-11-20'), newer):
            with self.subTest(status=stored['status']):
                merged = human_review.merge([stored], [older], '2026-12-06', product=AI)[0]
                self.assertEqual(merged['growth']['produced'], '2026-12-04 10:00 SGT')
                self.assertEqual(merged['growth'], stored['growth'])
                self.assertEqual((merged['status'], merged.get('status_by')), (stored['status'], stored.get('status_by')))
        # over a closed item too: an older block, even one built as a new item, does not reopen it
        closed = close([newer], 'resolved', 'Listing changed', '2026-12-10')[0]
        self.assertEqual(human_review.merge([closed], [older], '2026-12-11')[0]['status'], 'resolved')

    def test_growth_item_has_no_approval_level(self):
        # R32: the For Growth item is not an approval; validate gives it no level and drops one stored before
        item = human_review.validate([growth_item()])[0]
        self.assertNotIn('approval_required', item)
        self.assertNotIn('approval_required', human_review.validate([dict(growth_item(), approval_required='Lee')])[0])
        merged = human_review.merge([dict(growth_item('2026-11-20'), approval_required='Lee')],
                                    [growth_item('2026-11-27', 'rotate_out_flag'), proposal()], '2026-11-27')
        self.assertEqual({i['id']: i.get('approval_required') for i in merged},
                         {'for-growth': None, 'listing-conversion-gap': 'Lee'})
        self.assertNotIn('approval_required', merged[0])
        self.assertEqual(human_review.validate([dict(proposal(), id='price-x', kind='price')])[0]['approval_required'],
                         'Kim')

    def test_growth_item_is_published_whole_and_left_out_of_the_count(self):
        # decision 97 publishes decisions only (for_people), each cut to what the decision needs. The For Growth item is
        # not a listing or price decision but Growth's work order: it is published as it is (the For Growth tab and the
        # product page read it from the published doc), its growth block, status fields and history whole, its action its
        # own and no approval level; attach leaves it out of "N decisions need you" (R32)
        picked = dict(growth_item(), status='in_progress', status_by='Robin', status_at='2026-11-21T02:00:00Z',
                      history=[dict(date='2026-11-21', status='in_progress', owner='Growth', note='Picked up')])
        ready = dict(proposal(), id='listing-ready',
                     ai_review=dict(phase='human_ready', assessment=dict(recommendation='Refresh image 2.', rationale='Long.')))
        stored = human_review.validate([picked, ready, proposal()])   # proposal(): still in AI research
        before = copy.deepcopy(stored)
        shown = {i['id']: i for i in human_review.for_people(stored)}
        self.assertEqual(stored, before)
        self.assertEqual(sorted(shown), ['for-growth', 'listing-ready'])
        self.assertEqual(shown['for-growth'], stored[0])
        mine = shown['for-growth']
        self.assertEqual(mine['growth'], picked['growth'])
        self.assertEqual((mine['status'], mine['status_by'], mine['status_at'], mine['history']),
                         ('in_progress', 'Robin', '2026-11-21T02:00:00Z', picked['history']))
        self.assertEqual((mine['action'], mine['ai_review']), (picked['action'], {'phase': 'human_ready'}))
        self.assertNotIn('approval_required', mine)
        self.assertEqual(shown['listing-ready']['action'], 'Refresh image 2.')   # a decision is still cut (decision 97)
        for status in ('open', 'in_progress', 'copy_pushed', 'resolved'):
            with self.subTest(status=status):
                doc = {'card': {}}
                human_review.attach(doc, dict(human_review=[dict(picked, status=status), ready, proposal()]))
                self.assertEqual([i['id'] for i in doc['human_review']], ['for-growth', 'listing-ready'])
                self.assertEqual(doc['card']['human_review'], doc['human_review'])
                self.assertEqual(doc['human_review'][0]['growth'], picked['growth'])
                self.assertEqual(doc['human_review'][0]['status'], status)
                self.assertNotIn('approval_required', doc['human_review'][0])
                self.assertEqual(doc['card']['human_review_count'], 1)   # the listing decision only
                self.assertEqual(doc['card']['ai_research_count'], 1)

    def test_growth_supersedes_listing_conversion_gap_on_ai_product(self):
        gap = proposal()
        self.assertEqual(gap['id'], 'listing-conversion-gap')
        merged = {i['id']: i for i in human_review.merge([gap], [proposal(), growth_item()], '2026-11-20', product=AI)}
        done = merged['listing-conversion-gap']
        self.assertEqual((done['status'], done['resolution'], done['resolved_on']), ('resolved', GAP_NOTE, '2026-11-20'))
        self.assertEqual(done['history'][-1]['note'], GAP_NOTE)
        self.assertEqual(merged['for-growth']['status'], 'open')
        # the next week's publish: the gap is proposed again but stays superseded, without a new history line
        again = {i['id']: i for i in human_review.merge(list(merged.values()), [proposal(), growth_item()],
                                                        '2026-11-27', product=AI)}
        self.assertEqual(again['listing-conversion-gap']['status'], 'resolved')
        self.assertEqual(again['listing-conversion-gap']['history'], done['history'])
        # a product whose bids Scale Insights owns, or no product given, or no growth item: the gap stays open
        for product, incoming in (({'registry': {'bid_owner': 'SI'}}, [proposal(), growth_item()]),
                                  (None, [proposal(), growth_item()]), (AI, [proposal()])):
            with self.subTest(product=product, kinds=[i['kind'] for i in incoming]):
                kept = {i['id']: i for i in human_review.merge([gap], incoming, '2026-11-20', product=product)}
                self.assertEqual(kept['listing-conversion-gap']['status'], 'open')
                self.assertNotIn('history', kept['listing-conversion-gap'])


if __name__ == '__main__':
    unittest.main()
