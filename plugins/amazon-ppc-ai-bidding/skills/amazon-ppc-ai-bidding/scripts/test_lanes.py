import copy
import json
import pathlib
import unittest
from datetime import date, datetime, timedelta, timezone

import evidence
import lanes

UTC = timezone.utc
SKILL = pathlib.Path(__file__).resolve().parents[1]
CONFIG = json.loads((SKILL / 'config.json').read_text(encoding='utf-8'))
# The behaviour tests run on these settings, not on the live config, so retuning config.json doesn't break them.
# prove_index 1.25 since 2026-10-22 (was 1.4): Kim's bar for 2 orders is 1.25 everywhere (data-stage design 4.4)
A = {'enabled': False, 'prove_orders': 2, 'prove_index': 1.25, 'invest_orders': 3, 'invest_index': 1.1,
     'raise_orders': 3, 'raise_index': 1.4, 'max_raise_pct': 25, 'min_opportunity': 300,
     'monitor_spend_cap': 15, 'max_raises': 20, 'max_loss_month': 60,
     'invest_guide_month': 2000,  # a guide, not a gate (Kim, 2026-10-22, decision 99; was kim_product_month 600)
     'lock_weeks': 4, 'big_cut_pct': 50, 'big_cut_orders': 3,
     'repromote_cooloff_days': 56}  # the re-investment cool-off after a stop-loss step-down (2026-10-22)


def term(**over):
    """A search at index 1.5 on 3 SQP purchases and 840 searches in 84 days: opportunity 450."""
    t = dict(term='blank cards', role='Hold', sub_role='Hold', index=1.5, index_basis='SQP', market_cvr=0.10,
             cvr_est=0.15, sqp_volume=840, observed_days=84, sqp_our_clicks=20, sqp_our_purchases=3,
             ad_clicks=18, ad_orders=3, be_cpc=0.55)
    t.update(over)
    return t


def change(**over):
    c = dict(type='Bid change', keyword='blank cards', match='exact', role='Hold', current=0.50, new=0.60, change=0.2,
             clicks90=40, orders90=4, spend90=30.0, cvr=0.12, breakeven=0.60, sug_low=None, sug_median=None,
             sug_high=None, keyword_id='111', campaign_id='900')
    c.update(over)
    return c


INFO = ' (information only: no cap, decision 100)'  # how a reason ends that names a band (decision 100)


def promotion(**over):
    c = dict(type='New exact campaign', keyword='blank cards', role='Invest', current=None, new=0.70,
             modelled_spend_month=150.0, own_band_month=150.0, modelled_net_month=-20.0,  # within the $60 loss limit
             sug_low=0.55, sug_median=0.70, sug_high=0.90)
    c.update(over)
    return c


def target(**over):
    c = dict(type='Target bid change', keyword='b0samp0031', match='product', role='Hold', current=0.50, new=0.40,
             clicks90=20, orders90=3, spend90=12.0, cvr=0.10, breakeven=0.40, baseline_cvr=0.08, target_id='777',
             campaign_id='900')
    c.update(over)
    return c


def ctx(**over):
    base = dict(auto=copy.deepcopy(A), profit_per_unit=5.0, stale=None, onboarding=False, locks={},
                today='2026-10-19', band_left_month=500.0, raises_left=20)
    base.update(over)
    return lanes.Ctx(**base)


class ConfigTest(unittest.TestCase):
    def test_auto_block_is_in_config_and_on_for_every_ai_product(self):
        # the keys must match what the tests and lanes.py read; the values are free to be retuned. Autonomous runs (Kim,
        # 2026-10-22, decision 98): "turn it on for all AI products"; a product file's own auto block is its kill switch
        self.assertEqual(set(CONFIG['auto']), set(A))
        self.assertIs(CONFIG['auto']['enabled'], True)
        # decision 99: the investment guide is $2,000 a month a product, information only; no money level in the lanes
        self.assertEqual(CONFIG['auto']['invest_guide_month'], 2000)
        self.assertNotIn('kim_product_month', CONFIG['auto'])
        self.assertNotIn('kim_program_month', CONFIG['auto'])
        self.assertEqual(CONFIG['auto']['repromote_cooloff_days'], 56)


class LadderTest(unittest.TestCase):
    def test_ladder(self):
        self.assertEqual(lanes.ladder(2, 1.45, A), 'Prove first')
        self.assertEqual(lanes.ladder(3, 1.12, A), 'Invest')
        self.assertIsNone(lanes.ladder(2, 1.2, A))
        self.assertIsNone(lanes.ladder(1, 3.0, A))

    def test_ladder_edges_are_inclusive_and_invest_wins_when_both_fit(self):
        self.assertEqual(lanes.ladder(3, 1.1, A), 'Invest')
        self.assertEqual(lanes.ladder(2, 1.4, A), 'Prove first')
        self.assertEqual(lanes.ladder(5, 2.0, A), 'Invest')
        self.assertIsNone(lanes.ladder(3, 1.09, A))
        # the 2-order bar is 1.25 since 2026-10-22 (was 1.4, checked at 1.39): Kim, data-stage design 4.4
        self.assertEqual(lanes.ladder(2, 1.25, A), 'Prove first')
        self.assertIsNone(lanes.ladder(2, 1.24, A))


class SearchBandTest(unittest.TestCase):
    def test_search_band_loss_cap(self):
        self.assertEqual(lanes.search_band({'spend': 300, 'net': -120}, 5.0, 60), 150.0)
        self.assertEqual(lanes.search_band({'spend': 300, 'net': -20}, 5.0, 60), 300)

    def test_search_band_at_exactly_the_loss_cap_is_not_shrunk(self):
        self.assertEqual(lanes.search_band({'spend': 300, 'net': -60}, 5.0, 60), 300)

    def test_search_band_models_the_loss_itself_when_the_row_has_no_net(self):
        # 10 orders at $5 profit against $200 spend loses $150, so the band shrinks to 200 x 60/150
        self.assertEqual(lanes.search_band({'spend': 200, 'orders': 10}, 5.0, 60), 80.0)

    def test_search_band_of_a_profitable_search_is_its_spend(self):
        self.assertEqual(lanes.search_band({'spend': 300, 'net': 40}, 5.0, 60), 300)


class FirstRulesTest(unittest.TestCase):
    def test_locked_is_human(self):
        for key, c in [('111', change(current=0.60, new=0.30)),
                       ('777', target(current=0.60, new=0.30)),
                       ('blank cards', change(current=0.60, new=0.30, keyword_id='999'))]:
            with self.subTest(key=key):
                lane, reason, _ = lanes.classify(c, term(), ctx(locks={key: '2026-11-16'}))
                self.assertEqual(lane, 'human')
                self.assertIn('decided by a person until 2026-11-16', reason)

    def test_search_lock_ignores_case_and_spacing(self):
        lane, _, _ = lanes.classify(change(current=0.60, new=0.30, keyword_id='999'), term(),
                                    ctx(locks={'Blank  Cards': '2026-11-16'}))
        self.assertEqual(lane, 'human')

    def test_lock_holds_through_its_last_day_then_expires(self):
        cut = change(current=0.60, new=0.30)
        self.assertEqual(lanes.classify(cut, term(), ctx(locks={'111': '2026-10-19'}))[0], 'human')
        self.assertEqual(lanes.classify(cut, term(), ctx(locks={'111': '2026-10-18'}))[0], 'auto')

    def test_a_lock_date_that_cannot_be_read_still_holds(self):
        lane, _, _ = lanes.classify(change(current=0.60, new=0.30), term(), ctx(locks={'111': 'until further notice'}))
        self.assertEqual(lane, 'human')

    def test_lock_on_another_row_does_not_apply(self):
        cut = change(current=0.60, new=0.30)
        self.assertEqual(lanes.classify(cut, term(), ctx(locks={'222': '2026-11-16', 'other search': '2026-11-16'}))[0], 'auto')

    def test_lock_beats_a_promotion_that_is_on_the_ladder(self):
        lane, reason, _ = lanes.classify(promotion(), term(), ctx(locks={'blank cards': '2026-11-16'}))
        self.assertEqual(lane, 'human')
        self.assertIn('2026-11-16', reason)

    def test_stale_is_held_not_escalated(self):
        # autonomous runs (2026-10-22): data that isn't fresh holds every row (monitor) with the same words; it is not a
        # decision for a person (only low stock is, through summary.stock_reorder)
        for row in (change(current=0.60, new=0.30), promotion(), change(type='Negative exact', current=None, new=None),
                    change(type='Listing price', current=7.99, new=8.99)):
            with self.subTest(type=row['type']):
                lane, reason, _ = lanes.classify(row, term(), ctx(stale='SQP is 12 days old'))
                self.assertEqual((lane, reason), ('monitor', 'the product data is not fresh: SQP is 12 days old'))

    def test_an_onboarding_product_and_a_season_switch_are_judged_like_any_other(self):
        # until 2026-10-22 every row of an onboarding product or a phase switch went to a person (decision 98)
        cut = change(current=0.60, new=0.30)
        for c in (ctx(onboarding=True, onboarding_reason='no owner_since date in the registry'),
                  ctx(season_switch='rank build -> harvest')):
            with self.subTest(onboarding=c.onboarding, switch=c.season_switch):
                self.assertEqual(lanes.classify(cut, term(), c)[:2], lanes.classify(cut, term(), ctx())[:2])
                self.assertEqual(lanes.classify(promotion(), term(), c)[0], 'auto')

    def test_a_row_id_lock_holds_that_row(self):
        # dashboard approvals write locks by row id ('<type>:<id>'), so a row is also locked by its own row_id
        cut = change(current=0.60, new=0.30, keyword_id='999', keyword='other', row_id='Bid change:999')
        self.assertEqual(lanes.locked_until(cut, ctx(locks={'Bid change:999': '2026-11-16'})), '2026-11-16')
        self.assertEqual(lanes.classify(cut, term(), ctx(locks={'Bid change:999': '2026-11-16'}))[0], 'human')
        self.assertIsNone(lanes.locked_until(cut, ctx(locks={'Bid change:111': '2026-11-16'})))

    def test_a_lock_can_say_why_in_its_own_words(self):
        why = 'a person approved a rank experiment on this search until 2026-11-16'
        cut = change(current=0.60, new=0.30)
        lane, reason, _ = lanes.classify(cut, term(), ctx(locks={'blank cards': {'until': '2026-11-16', 'reason': why}}))
        self.assertEqual((lane, reason), ('human', why))
        self.assertEqual(lanes.lock_on(cut, ctx(locks={'blank cards': {'until': '2026-11-16', 'reason': why}})),
                         ('2026-11-16', why))
        expired = ctx(locks={'blank cards': {'until': '2026-10-18', 'reason': why}})
        self.assertEqual(lanes.classify(cut, term(), expired)[0], 'auto')

    def test_lock_dates_and_keys_are_read_one_way(self):
        self.assertEqual(lanes.lock_date('2026-11-16T00:00'), date(2026, 11, 16))
        self.assertIsNone(lanes.lock_date('further notice'))
        self.assertIsNone(lanes.lock_date(None))
        self.assertEqual(lanes.lock_key('  Blank   Cards '), 'blank cards')

    def test_lock_is_reported_before_stale_and_onboarding(self):
        _, reason, _ = lanes.classify(change(current=0.60, new=0.30), term(),
                                      ctx(locks={'111': '2026-11-16'}, stale='old', onboarding=True))
        self.assertIn('decided by a person', reason)

    def test_the_human_types_stay_human_however_clear_the_numbers(self):
        # autonomous runs (Kim, 2026-10-22, decision 98): a price is Kim's whatever the numbers
        lane, reason, _ = lanes.classify(change(type='Listing price', current=0.60, new=0.30, orders90=0), term(), ctx())
        self.assertEqual(lane, 'human')
        self.assertIn("a price change is Kim's call", reason)
        self.assertEqual(lanes.HUMAN_TYPES, ('Listing price',))

    def test_a_stop_loss_with_no_step_down_yet_is_held_for_the_next_run(self):
        # decision 107 (2026-10-23): planned only where no step-down can be written (stop_loss.py); held, not a person's
        lane, reason, _ = lanes.classify(change(type='Stop-loss review', current=0.60, new=0.30, orders90=0), term(), ctx())
        self.assertEqual(lane, 'monitor')
        self.assertIn('no step-down can be written for this search yet', reason)
        self.assertIn('the next run tries again', reason)

    def test_every_formerly_always_human_type_now_applies_on_its_own(self):
        # until 2026-10-22 each of these waited for a person; now each applies on its own inside the guards (decision 98)
        for kind in ['Budget and top of search', 'Negative exact', 'Archive negative', 'Scale Insights rules',
                     'Scale Insights setup', 'Harvest default bid', 'Harvest setup', 'Budget step', 'New SB video campaign',
                     'SB pause keyword']:
            with self.subTest(kind=kind):
                row = change(type=kind, current=0.60, new=0.30, orders90=4, video_asset='amzn1.asset')
                lane, reason, _ = lanes.classify(row, term(), ctx())
                self.assertEqual(lane, 'auto', reason)
                self.assertNotIn('always needs a person', reason)

    def test_a_sponsored_brands_bid_change_is_a_cut_or_a_capped_raise(self):
        cut = change(type='SB bid change', current=0.80, new=0.60, orders90=0)
        self.assertEqual(lanes.classify(cut, term(), ctx())[:2], ('auto', 'cut from $0.80 to $0.60: a cut is never held back'))
        big = change(type='SB bid change', current=1.00, new=0.40, orders90=4)
        lane, _, ev = lanes.classify(big, term(sqp_our_purchases=4), ctx())
        self.assertEqual((lane, ev['new_capped']), ('auto', 0.50))  # the big-cut step reads SB bids too (decision 107)
        up = change(type='SB bid change', role='Invest', current=0.80, new=1.20, orders90=0)
        lane, reason, ev = lanes.classify(up, term(), ctx())
        self.assertEqual((lane, ev['new_capped']), ('auto', 1.00))  # +25% a run, written at the cap
        self.assertIn('Sponsored Brands keyword re-priced to its Invest bid', reason)
        lane, reason, ev = lanes.classify(up, term(), ctx(raises_left=0))
        self.assertEqual((lane, ev.get('raises_used_up')), ('monitor', True))

    def test_the_rows_that_cant_be_written_go_to_a_person(self):
        no_video = change(type='New SB video campaign', current=None, new=0.80, video_asset=None)
        self.assertEqual(lanes.classify(no_video, term(), ctx())[0], 'human')
        beyond = change(type='Scale Insights setup', current=None, new=None, si_beyond_standard='strategy 144 does not exist yet')
        lane, reason, _ = lanes.classify(beyond, term(), ctx())
        self.assertEqual(lane, 'human')
        self.assertIn("beyond the standard AI setup is Kim's call", reason)
        homeless = promotion(type='New exact keyword', owner_kind='business', campaign_id=None, ad_group_id=None)
        self.assertEqual(lanes.classify(homeless, term(), ctx())[0], 'human')

    def test_a_business_new_exact_keyword_is_judged_as_a_promotion(self):
        # until 2026-10-22 always a person's call; since then the ladder decides (decision 98), and its band is
        # information only (decision 100)
        row = promotion(type='New exact keyword', owner_kind='business', campaign_id='108', ad_group_id='208')
        bt = term(index=2.4, index_basis='Search terms (business)', ad_clicks=25, ad_orders=7, owner_kind='business')
        self.assertEqual(lanes.classify(row, bt, ctx())[0], 'auto')
        self.assertEqual(lanes.classify(row, bt, ctx(band_left_month=10.0))[0], 'auto')

    def test_a_pause_with_orders_applies_on_its_own(self):
        # until 2026-10-22 a person's call; the big-cut guard reads bid cuts only, never a pause (decision 98)
        for orders in (1, 2, 5):
            with self.subTest(orders=orders):
                lane, reason, _ = lanes.classify(change(type='Pause keyword', new=None, orders90=orders, clicks90=40),
                                                 term(sqp_our_purchases=orders), ctx())
                self.assertEqual((lane, reason), ('auto', 'pause: a cut is never held back'))

    def test_a_stop_loss_step_down_applies_on_its_own_whatever_the_cut(self):
        why = 'invested 30 days (4 weeks) with no gain in organic rank (40 -> 41), SQP impression share or organic purchases'
        bid = change(role='Hold', current=1.20, new=0.40, orders90=6, stop_loss_step_down=True, stop_loss_reason=why)
        self.assertEqual(lanes.classify(bid, term(sqp_our_purchases=6), ctx())[:2], ('auto', why))
        campaign = change(type='Budget and top of search', role='Hold', current=None, new=None, budget=5, budget_now=10,
                          tos=0, tos_now=50, stop_loss_step_down=True, stop_loss_reason=why)
        self.assertEqual(lanes.classify(campaign, term(), ctx())[:2], ('auto', why))
        # a lock still comes first, and stale data still holds it
        self.assertEqual(lanes.classify(bid, term(), ctx(locks={'111': '2026-11-16'}))[0], 'human')
        self.assertEqual(lanes.classify(bid, term(), ctx(stale='old'))[0], 'monitor')

    def test_pause_without_orders_is_a_cut(self):
        lane, _, _ = lanes.classify(change(type='Pause keyword', new=None, role=None, orders90=0, clicks90=40),
                                    term(sqp_our_purchases=0, index=0.3), ctx())
        self.assertEqual(lane, 'auto')

    def test_a_type_the_lanes_do_not_know_is_human(self):
        lane, reason, _ = lanes.classify(change(type='Mystery change', current=0.60, new=0.30), term(), ctx())
        self.assertEqual(lane, 'human')
        self.assertIn('Mystery change', reason)

    def test_a_row_with_no_type_is_human_and_does_not_print_none(self):
        lane, reason, _ = lanes.classify(change(type=None), term(), ctx())
        self.assertEqual(lane, 'human')
        self.assertNotIn('None', reason)

    def test_a_bid_row_without_a_current_or_new_bid_is_held_for_the_next_run(self):
        for over in [dict(current=None), dict(new=None)]:
            with self.subTest(over=over):
                lane, reason, _ = lanes.classify(change(**over), term(), ctx())
                self.assertEqual(lane, 'monitor')   # decision 107: held and retried, not a person's call
                self.assertIn('the next run tries again', reason)


def decided(what, direction=None, until='2026-11-16', by='Lee', on='2026-10-19'):
    """A person's decision as plan_lanes.lock_table reads it from the product file's decisions."""
    return dict(until=until, what=what, by=by, on=on, direction=direction, reason=f'decided by {by} on {on}')


class LockDirectionTest(unittest.TestCase):
    """A3 (I3): a lock keeps the auto lane off a person's decision; it doesn't hide a new, different call from people."""
    MOVES = ('up', 'down', 'pause', 'other')

    def test_which_way_a_row_moves(self):
        self.assertEqual(lanes.direction(change(current=0.50, new=0.60)), 'up')
        self.assertEqual(lanes.direction(change(current=0.60, new=0.30)), 'down')
        self.assertEqual(lanes.direction(target(current=0.30, new=0.40)), 'up')
        self.assertEqual(lanes.direction(change(type='SB bid change', current=0.80, new=0.50)), 'down')
        for ctype in ('Pause keyword', 'Pause target', 'SB pause keyword'):
            self.assertEqual(lanes.direction(change(type=ctype, new=None)), 'pause', ctype)
        for c in (promotion(), change(type='Negative exact', current=None, new=None), change(current=0.50, new=0.50),
                  change(current=None, new=0.60), change(type='Budget and top of search'), change(type=None)):
            self.assertEqual(lanes.direction(c), 'other', c.get('type'))

    def test_a_declined_move_is_held_and_a_different_one_is_not(self):
        held = {('up', 'up'), ('down', 'down'), ('pause', 'pause'), ('other', 'other'),
                ('down', 'pause'), ('pause', 'down')}  # a cut and a pause both cut: refusing one refuses the other
        for way in self.MOVES:
            for move in self.MOVES:
                with self.subTest(declined=way, proposed=move):
                    self.assertEqual(lanes.lock_blocks(decided('decline', way), move), (way, move) in held)

    def test_an_approved_move_holds_only_the_way_back(self):
        held = {('up', 'down'), ('up', 'pause'), ('down', 'up')} | {(w, m) for w in ('pause', 'other') for m in self.MOVES}
        for way in self.MOVES:
            for move in self.MOVES:
                with self.subTest(approved=way, proposed=move):
                    self.assertEqual(lanes.lock_blocks(decided('approve', way), move), (way, move) in held)

    def test_a_lock_that_does_not_say_which_way_holds_every_move(self):
        for lock in ('2026-11-16', decided('decline'), decided('approve'), decided('decline', 'sideways'),
                     decided('experiment'), decided(None, 'up'), decided('maybe', 'down'),
                     dict(until='2026-11-16', reason='a rank experiment is proposed on this search')):
            for move in self.MOVES:
                with self.subTest(lock=lock, move=move):
                    self.assertTrue(lanes.lock_blocks(lock, move))

    def test_a_row_the_lock_does_not_hold_is_planned_as_usual(self):
        locks = {'111': decided('approve', 'up')}
        raise_ = change(current=0.50, new=0.60, breakeven=0.60)
        self.assertEqual(lanes.classify(raise_, term(), ctx(locks=locks))[:2], lanes.classify(raise_, term(), ctx())[:2])
        self.assertIsNone(lanes.lock_on(raise_, ctx(locks=locks)))
        self.assertIsNone(lanes.locked_until(raise_, ctx(locks=locks)))
        cut = change(current=0.60, new=0.30)
        lane, reason, _ = lanes.classify(cut, term(), ctx(locks=locks))
        self.assertEqual((lane, reason), ('human', 'decided by Lee on 2026-10-19'))

    def test_the_blocking_lock_comes_back_whole(self):
        lock = decided('decline', 'down', by='Kim')
        cut = change(current=0.60, new=0.30)
        self.assertEqual(lanes.blocking_lock(cut, {'Bid change:111': lock, '111': lock}, '2026-10-19'), lock)
        self.assertEqual(lanes.blocking_lock(cut, {'111': '2026-11-16'}, '2026-10-19'),
                         dict(until='2026-11-16', reason='decided by a person until 2026-11-16', what=None, by=None, on=None,
                              direction=None))
        self.assertIsNone(lanes.blocking_lock(cut, {'111': decided('decline', 'up')}, '2026-10-19'))
        self.assertIsNone(lanes.blocking_lock(cut, {'111': decided('decline', 'down', until='2026-10-18')}, '2026-10-19'))
        # the row's own lock doesn't hold the move, but a rank experiment on its search does
        experiment = dict(until='further notice', reason='a rank experiment is proposed on this search; a person decides it first')
        hit = lanes.blocking_lock(cut, {'111': decided('decline', 'up'), 'blank cards': experiment}, '2026-10-19')
        self.assertEqual(hit['reason'], experiment['reason'])


class CutTest(unittest.TestCase):
    def test_a_plain_cut_is_auto(self):
        lane, reason, _ = lanes.classify(change(role='Trim', current=0.60, new=0.42, orders90=1), term(index=0.7), ctx())
        self.assertEqual(lane, 'auto')
        self.assertIn('cut', reason)

    def test_a_cut_on_an_invest_search_applies_on_its_own(self):
        # until 2026-10-22 a person's call ("risks its rank"); since autonomous runs a cut is never held back (decision 98)
        for role in ['Invest', 'Prove first']:
            with self.subTest(role=role):
                lane, reason, _ = lanes.classify(change(role=role, current=0.90, new=0.70), term(), ctx())
                self.assertEqual((lane, reason), ('auto', 'cut from $0.90 to $0.70: a cut is never held back'))

    def test_big_cut_on_proven_steps_down_half(self):
        # decision 107 (2026-10-23): a cut of more than 50% on 3+ orders steps down 50% this run, and the next run takes the
        # rest; until then it went to a person
        lane, reason, ev = lanes.classify(change(role='Trim', current=1.00, new=0.40, orders90=3), term(), ctx())
        self.assertEqual((lane, ev['new_capped']), ('auto', 0.50))
        self.assertIn('a 60% cut on a search that already has 3 orders: it steps down 50% this run, from $1.00 to $0.50', reason)
        self.assertIn('the next run takes the rest to $0.40', reason)

    def test_with_no_big_cut_step_a_big_cut_goes_straight_to_its_price(self):
        # decision 168 (Kim, 2026-10-29, "the full package"): big_cut_pct null in config.json
        lane, reason, ev = lanes.classify(change(role='Trim', current=1.00, new=0.40, orders90=3), term(),
                                          ctx(auto=dict(A, big_cut_pct=None)))
        self.assertEqual(lane, 'auto')
        self.assertNotIn('new_capped', ev)
        self.assertEqual(reason, 'cut from $1.00 to $0.40: a cut is never held back')
        self.assertIsNone(json.loads((SKILL / 'config.json').read_text())['auto']['big_cut_pct'])

    def test_a_cut_of_exactly_half_is_not_a_big_cut(self):
        lane, _, _ = lanes.classify(change(role='Trim', current=1.00, new=0.50, orders90=3), term(), ctx())
        self.assertEqual(lane, 'auto')

    def test_a_big_cut_on_fewer_than_three_orders_is_auto(self):
        lane, _, _ = lanes.classify(change(role='Trim', current=1.00, new=0.30, orders90=2),
                                    term(index_basis='SQP', sqp_our_purchases=2, sqp_our_clicks=40, index=0.5), ctx())
        self.assertEqual(lane, 'auto')

    def test_big_cut_counts_the_orders_the_evidence_uses(self):
        # SQP shows 3 purchases, the keyword's own row only 1 order: the search has 3+ orders
        lane, _, ev = lanes.classify(change(role='Trim', current=1.00, new=0.30, orders90=1), term(sqp_our_purchases=3), ctx())
        self.assertEqual((lane, ev['new_capped']), ('auto', 0.50))

    def test_cut_without_sqp_is_auto(self):
        lane, _, ev = lanes.classify(change(role='Trim', current=0.60, new=0.30, orders90=0), None, ctx())
        self.assertEqual(lane, 'auto')
        self.assertIsNone(ev['opportunity'])

    def test_pause_target_at_no_orders_is_auto(self):
        lane, _, _ = lanes.classify(target(type='Pause target', role='Pause', new=None, orders90=0, clicks90=25), None, ctx())
        self.assertEqual(lane, 'auto')

    def test_a_pause_on_proven_orders_is_not_a_big_cut(self):
        # the big-cut guard reads bid cuts only since 2026-10-22: a pause, with orders or not, applies on its own
        lane, _, _ = lanes.classify(target(type='Pause target', role='Pause', new=None, orders90=3, clicks90=25), None, ctx())
        self.assertEqual(lane, 'auto')

    def test_target_cut_is_auto(self):
        lane, _, _ = lanes.classify(target(current=0.50, new=0.40, orders90=1), None, ctx())
        self.assertEqual(lane, 'auto')

    # fix E, E1 (I1): a search the team invests in (the product's invest log, plus this run's rank searches). Since
    # autonomous runs (2026-10-22, decision 98) its cuts apply on their own like any cut; the flag stays for log_invest
    def test_a_cut_or_pause_on_an_invested_search_applies_on_its_own_and_is_flagged(self):
        invested = ctx(invested=frozenset({'blank cards'}))
        cut = change(role='Hold', current=0.80, new=0.50, orders90=1)
        for row in (cut, change(type='Pause keyword', role='Trim', current=0.80, new=None, orders90=0),
                    change(keyword='Blank  Cards', role='Hold', current=0.80, new=0.50, orders90=1)):  # read as the planner writes it
            with self.subTest(row=row['type'], keyword=row['keyword']):
                self.assertEqual(lanes.classify(row, term(index=1.0), invested)[0], 'auto')
                self.assertEqual(lanes.classify(row, term(index=1.0), invested)[:2],
                                 lanes.classify(row, term(index=1.0), ctx())[:2])
                self.assertIs(lanes.invested_cut(row, invested.invested), True)

    def test_an_invested_search_still_raises_and_other_searches_still_cut(self):
        invested = ctx(invested=frozenset({'blank cards'}))
        self.assertEqual(lanes.classify(change(current=0.50, new=0.60), term(), invested)[0], 'auto')  # a raise to breakeven
        other = change(keyword='gold cards', role='Trim', current=0.60, new=0.42, orders90=1)
        self.assertEqual(lanes.classify(other, term(term='gold cards', index=0.7), invested)[0], 'auto')
        self.assertIs(lanes.invested_cut(other, invested.invested), False)
        self.assertIs(lanes.invested_cut(change(current=0.50, new=0.60), invested.invested), False)  # not a cut
        self.assertIs(lanes.invested_cut(change(current=0.80, new=0.50), frozenset()), False)


class BusinessLaneTest(unittest.TestCase):
    """A business (Amazon Business) row takes the same lane rules as a consumer one, judged on the B2B keyword's own
    record (design 2026-10-21-b2b-lane-and-roles, section 4d)."""

    def test_a_business_promotion_is_judged_on_the_business_record(self):
        c = promotion(type='Business invest', owner_kind='business', role='Invest')
        bt = term(index=2.4, index_basis='Search terms (business)', ad_clicks=25, ad_orders=7, owner_kind='business')
        self.assertEqual(lanes.classify(c, bt, ctx())[0], 'auto')
        self.assertEqual(lanes.classify(c, term(index=2.4, index_basis='Search terms (business)', ad_clicks=5, ad_orders=1, owner_kind='business'), ctx())[0], 'monitor')

    def test_a_business_promotion_never_counts_the_products_sqp_purchases(self):
        # SQP counts every shopper, so a business record reads its own B2B orders only (decision 174 counts ads or SQP for
        # consumer searches)
        c = promotion(type='Business invest', owner_kind='business', role='Invest')
        bt = term(index=2.4, index_basis='Search terms (business)', sqp_our_purchases=9, ad_clicks=5, ad_orders=1,
                  owner_kind='business')
        self.assertEqual(lanes.classify(c, bt, ctx())[0], 'monitor')

    def test_a_business_cut_is_never_held_back(self):
        self.assertEqual(lanes.classify(change(owner_kind='business', new=0.40), None, ctx())[0], 'auto')


class PromotionTest(unittest.TestCase):
    def test_no_money_level_parks_a_promotion(self):
        # Kim, 2026-10-22, decision 99: "don't cap the promotion"; the $600 level (and the $3,000 program level) are gone
        c = ctx(band_left_month=1000.0)
        self.assertEqual(lanes.classify(promotion(modelled_spend_month=150.0), term(), c)[0], 'auto')
        self.assertFalse(hasattr(lanes, 'past_kim_level_text'))
        self.assertFalse(hasattr(lanes, 'past_program_level_text'))
        self.assertNotIn('planned_invest_month', lanes.Ctx.__dataclass_fields__)

    def test_is_cut_is_public_and_covers_pauses_and_lower_bids(self):
        self.assertTrue(lanes.is_cut(change(current=0.60, new=0.30)))
        self.assertTrue(lanes.is_cut(change(type='Pause keyword', new=None)))
        self.assertTrue(lanes.is_cut(target(type='Pause target', new=None)))
        self.assertFalse(lanes.is_cut(change(current=0.30, new=0.60)))
        self.assertFalse(lanes.is_cut(change(current=None, new=0.60)))

    def test_lock_hit_needs_only_the_locks_and_the_date(self):
        locks = {'111': '2026-11-16', 'old search': '2026-10-18', 'blank cards': {'until': 'further notice', 'reason': 'why'}}
        self.assertEqual(lanes.lock_hit(change(keyword_id='111'), locks, '2026-10-19'),
                         ('2026-11-16', 'decided by a person until 2026-11-16'))
        self.assertIsNone(lanes.lock_hit(change(keyword_id='222', keyword='old search'), locks, '2026-10-19'))  # expired
        self.assertEqual(lanes.lock_hit(change(keyword_id='222'), locks, '2026-10-19'), ('further notice', 'why'))
        self.assertIsNone(lanes.lock_hit(change(keyword_id='222'), {}, '2026-10-19'))
        # classify's own reading is the same one
        self.assertEqual(lanes.lock_on(change(keyword_id='111'), ctx(locks=locks)),
                         lanes.lock_hit(change(keyword_id='111'), locks, '2026-10-19'))

    def test_promotion_on_ladder_is_auto(self):
        lane, reason, _ = lanes.classify(promotion(), term(), ctx(band_left_month=200.0))
        self.assertEqual(lane, 'auto')
        self.assertIn('enough proof for Invest: 3 orders at index 1.50 (converts 1.5x the market)', reason)
        self.assertIn('$150.00 of $200.00 left', reason)

    def test_a_promotion_without_a_role_reads_plainly_and_is_never_auto(self):
        for role in [None, '']:
            with self.subTest(role=role):
                lane, reason, _ = lanes.classify(promotion(role=role), term(), ctx())
                self.assertNotEqual(lane, 'auto')
                self.assertIn('promotion without a role', reason)
                self.assertNotIn('None', reason)

    def test_a_promotion_with_some_other_role_is_not_auto(self):
        lane, reason, _ = lanes.classify(promotion(role='Hold'), term(), ctx())
        self.assertNotEqual(lane, 'auto')
        self.assertIn('a Hold promotion', reason)

    def test_prove_first_on_two_orders_is_auto(self):
        lane, _, _ = lanes.classify(promotion(role='Prove first'),
                                    term(sqp_our_purchases=2, ad_orders=2, index=1.45), ctx())
        self.assertEqual(lane, 'auto')

    def test_ad_orders_count_when_sqp_has_fewer(self):
        # Kim, 2026-10-30: "ad data counts too" (decision 174): 1 SQP purchase and 2 ad orders is 2 orders, never 3
        lane, reason, _ = lanes.classify(promotion(role='Prove first'),
                                         term(sqp_our_purchases=1, ad_orders=2, index=1.45), ctx())
        self.assertEqual(lane, 'auto')
        self.assertIn('2 orders', reason)
        lane, _, _ = lanes.classify(promotion(role='Prove first'), term(sqp_our_purchases=1, ad_orders=1, index=1.45), ctx())
        self.assertEqual(lane, 'monitor')
        # SQP purchases already hold the ad ones: 2 and 2 is 2 orders, so not Invest's 3
        lane, _, _ = lanes.classify(promotion(role='Invest'), term(sqp_our_purchases=2, ad_orders=2, index=1.45), ctx())
        self.assertEqual(lane, 'monitor')
        # SQP ahead of the ads counts as before, on an ads-based index too
        lane, _, _ = lanes.classify(promotion(role='Prove first'),
                                    term(index_basis='Search terms', sqp_our_purchases=2, ad_orders=0, index=1.45), ctx())
        self.assertEqual(lane, 'auto')

    def test_reuse_follows_the_same_rule(self):
        self.assertEqual(lanes.classify(promotion(type='Reuse exact campaign'), term(), ctx())[0], 'auto')
        self.assertEqual(lanes.classify(promotion(type='Reuse exact campaign'), term(), ctx(band_left_month=10.0))[0], 'auto')

    def test_a_promotion_over_its_own_band_goes_out_and_says_so(self):
        # A1 (C1): a search modelled to lose $112.50 a month has its own band shrunk to $80 (search_band). Until
        # 2026-10-22 it went to a person; decision 100 ("don't cap the promotion"): it goes out and its reason names the
        # $60 loss line, whatever the product's pooled band
        capped = promotion(modelled_spend_month=150.0, own_band_month=80.0, modelled_net_month=-112.5)
        line = 'modelled to lose $112.50 a month, over the $60 loss line for one search'
        for c in (ctx(band_left_month=1000.0), ctx(band_left_month=10.0)):
            with self.subTest(band_left=c.band_left_month):
                lane, reason, _ = lanes.classify(capped, term(), c)
                self.assertEqual(lane, 'auto')
                self.assertIn(line, reason)
                self.assertTrue(reason.endswith(INFO), reason)
        _, reason, _ = lanes.classify(capped, term(), ctx(auto=dict(A, max_loss_month=75)))
        self.assertIn('over the $75 loss line for one search', reason)
        no_net = promotion(modelled_spend_month=150.0, own_band_month=80.0, modelled_net_month=None)
        self.assertIn('modelled to lose more than the $60 a month loss line for one search',
                      lanes.classify(no_net, term(), ctx())[1])
        self.assertEqual(lanes.loss_line_text(promotion(), A), None)  # spend right at its own band
        self.assertEqual(lanes.loss_line_text(capped, A), line)

    def test_a_promotion_with_no_band_of_its_own_goes_out(self):
        # until 2026-10-22: "the search has no band of its own, so its modelled loss can't be checked", for a person
        for c in (promotion(own_band_month=None), {k: v for k, v in promotion().items() if k != 'own_band_month'}):
            with self.subTest(c=c):
                lane, reason, _ = lanes.classify(c, term(), ctx())
                self.assertEqual(lane, 'auto')
                self.assertNotIn('loss line', reason)

    def test_a_promotion_past_the_products_band_goes_out_and_says_so(self):
        # until 2026-10-22 "the product's monthly invest band is short" sent it to a person (decision 100)
        lane, reason, _ = lanes.classify(promotion(), term(), ctx(band_left_month=100.0))
        self.assertEqual(lane, 'auto')
        self.assertIn("it goes past the product's monthly invest band ($150.00, with $100.00 left)" + INFO, reason)
        self.assertTrue(lanes.over_invest_band(promotion(), ctx(band_left_month=100.0)))
        self.assertFalse(lanes.over_invest_band(promotion(), ctx(band_left_month=150.0)))
        self.assertFalse(lanes.over_invest_band(promotion(modelled_spend_month=None), ctx(band_left_month=0.0)))

    def test_a_campaigns_business_invests_past_the_band_go_out_together_and_say_so(self):
        # ruling 6: the head carries the group's spend; until decision 100 a short band sent the group to a person
        head = promotion(type='Business invest', owner_kind='business', group_spend_month=300.0)
        lane, reason, _ = lanes.classify(head, term(), ctx(band_left_month=200.0))
        self.assertEqual(lane, 'auto')
        self.assertIn("with the other business invests of its campaign it goes past the product's monthly invest band "
                      '($300.00, with $200.00 left)' + INFO, reason)
        self.assertTrue(lanes.over_invest_band(head, ctx(band_left_month=200.0)))
        unsized = promotion(type='Business invest', owner_kind='business', group_spend_month=None)
        lane, reason, _ = lanes.classify(unsized, term(), ctx())
        self.assertEqual(lane, 'auto')
        self.assertIn("a business invest of its campaign has no modelled monthly spend, so the campaign isn't sized against "
                      'the band', reason)

    def test_a_promotion_inside_its_band_is_auto_whatever_the_product_already_invests(self):
        # until 2026-10-22 one that took the product past Kim's $600 a month went to him (decision 99 took it out)
        lane, reason, _ = lanes.classify(promotion(), term(), ctx(band_left_month=1000.0))
        self.assertEqual(lane, 'auto')
        self.assertNotIn('$600', reason)

    def test_promotion_with_no_modelled_spend_goes_out_unsized(self):
        # until 2026-10-22 a person's call ("no modelled monthly spend, so the band can't be checked"); decision 100
        missing = promotion()
        del missing['modelled_spend_month']
        for c in [missing, promotion(modelled_spend_month=None)]:
            with self.subTest(c=c):
                lane, reason, _ = lanes.classify(c, term(), ctx())
                self.assertEqual(lane, 'auto')
                self.assertTrue(reason.endswith("its monthly spend isn't modelled, so it isn't sized against a band"), reason)

    def test_an_explicit_zero_modelled_spend_passes_the_band_check(self):
        lane, _, _ = lanes.classify(promotion(modelled_spend_month=0.0), term(), ctx(band_left_month=0.0))
        self.assertEqual(lane, 'auto')

    def test_off_the_ladder_a_missing_modelled_spend_does_not_matter(self):
        # nothing is applied for a close call, so there is no band to check
        c = promotion(role='Prove first')
        del c['modelled_spend_month']
        lane, _, _ = lanes.classify(c, term(sqp_our_purchases=2, index=1.2, sqp_volume=200), ctx())
        self.assertEqual(lane, 'monitor')

    def test_the_ladder_must_return_the_changes_own_role(self):
        # 2 orders at 1.5 is a Prove first ladder; a plan row that calls it Invest is not on the ladder for Invest
        lane, _, _ = lanes.classify(promotion(role='Invest'), term(sqp_our_purchases=2, ad_orders=2, index=1.5, sqp_volume=200), ctx())
        self.assertEqual(lane, 'monitor')

    def test_ladder_not_met_and_small_goes_to_monitor(self):
        lane, reason, ev = lanes.classify(promotion(role='Prove first'),
                                          term(sqp_our_purchases=2, ad_orders=2, index=1.2, sqp_volume=200), ctx())
        self.assertEqual(lane, 'monitor')
        self.assertLess(ev['opportunity'], A['min_opportunity'])
        # the bar reads 1.25x since 2026-10-22 (was 1.4x): A['prove_index'], data-stage design 4.4
        self.assertIn('not enough proof yet for Prove first (needs 2+ orders at 1.25x the market)', reason)
        self.assertIn('it has 2 orders at index 1.20 (converts 1.2x the market)', reason)
        self.assertIn('opportunity 86 (conversion index x monthly searches): not yet, the next run judges it again', reason)

    def test_ladder_not_met_but_big_is_still_the_ais_not_yet(self):
        # decision 107 (2026-10-23): a close call is held whatever its size; until then a big one went to a person
        lane, reason, ev = lanes.classify(promotion(role='Prove first'),
                                          term(sqp_our_purchases=2, ad_orders=2, index=1.2, sqp_volume=2000), ctx())
        self.assertEqual(lane, 'monitor')
        self.assertGreaterEqual(ev['opportunity'], A['min_opportunity'])
        self.assertIn('not yet, the next run judges it again', reason)

    def test_ladder_not_met_with_no_volume_is_held_whatever_it_spent(self):
        for spend in (30.0, 90.0):
            with self.subTest(spend=spend):
                thin = term(sqp_our_purchases=2, index=1.2, sqp_volume=0, ad_spend=spend)
                self.assertEqual(lanes.classify(promotion(role='Prove first'), thin, ctx())[0], 'monitor')

    def test_promotion_without_a_term_is_never_auto(self):
        lane, _, _ = lanes.classify(promotion(), None, ctx())
        self.assertNotEqual(lane, 'auto')


def policy_row(**over):
    """A 'Budget and top of search' row that only sets a live rank campaign's top of search to the standing policy
    (placement_review.hold_defaults marks it policy_tos_only): the budget is unchanged."""
    c = dict(type='Budget and top of search', keyword='blank cards', role='Invest', budget_now=10, budget=10, tos_now=0, tos=50,
             policy_tos_only=True, modelled_spend_month=150.0, own_band_month=150.0, modelled_net_month=-20.0)
    c.update(over)
    return c


class PolicyTosOnlyTest(unittest.TestCase):
    """Kim, 2026-10-20: "Every new or existing exact campaign for an Invest search gets top of search +50%... don't file it
    under Needs Human." A budget row that changes nothing but top of search, to the policy, is judged like a promotion on the
    evidence; any other budget row is still always a person's call."""

    def test_the_marker_is_read_with_the_budget_and_the_role(self):
        self.assertTrue(lanes.policy_tos_only(policy_row()))
        self.assertTrue(lanes.policy_tos_only(policy_row(role='Prove first', tos=30)))
        for label, over in (('no marker', dict(policy_tos_only=None)), ('marker false', dict(policy_tos_only=False)),
                            ('marker not exactly true', dict(policy_tos_only='yes')),
                            ('budget raised', dict(budget=15)), ('budget cut', dict(budget=5)), ('no budget', dict(budget=None, budget_now=None)),
                            ('no live budget', dict(budget_now=None)), ('role Hold', dict(role='Hold')), ('no role', dict(role=None)),
                            ('held by the planner', dict(placement_hold=True)), ('another type', dict(type='Negative exact'))):
            with self.subTest(label):
                self.assertFalse(lanes.policy_tos_only(policy_row(**over)))

    def test_on_the_ladder_inside_the_band_and_the_level_it_is_auto(self):
        lane, reason, ev = lanes.classify(policy_row(), term(), ctx())
        self.assertEqual(lane, 'auto')
        self.assertIn('enough proof for Invest: 3 orders at index 1.50 (converts 1.5x the market)', reason)
        self.assertIn('top of search', reason)
        self.assertEqual(ev['opportunity'], 450.0)
        self.assertIsNotNone(ev['confidence'])  # judged like a promotion, so the card can say how sure
        prove = term(sqp_our_purchases=2, ad_orders=2, index=1.5)
        self.assertEqual(lanes.classify(policy_row(role='Prove first', tos=30, budget=5, budget_now=5), prove, ctx())[0], 'auto')

    def test_any_budget_change_or_a_missing_marker_applies_at_its_standard_settings(self):
        # autonomous runs (2026-10-22): no longer always a person's call. classify lets it through as the role's standard
        # budget and top of search; plan_lanes sends a non-standard one to a person (promotion_odd, test_plan_lanes)
        for over in (dict(budget=15), dict(budget=5), dict(policy_tos_only=False), dict(policy_tos_only=None)):
            with self.subTest(over):
                lane, reason, _ = lanes.classify(policy_row(**over), term(), ctx())
                self.assertEqual((lane, reason), ('auto', "its role's standard budget and top of search (rulebook 7.5)"))

    def test_without_ladder_proof_it_is_a_close_call_like_a_promotion(self):
        thin = term(sqp_our_purchases=1, ad_orders=1, index=1.2)  # under Invest's 3 orders
        lane, reason, _ = lanes.classify(policy_row(), thin, ctx())
        self.assertEqual(lane, 'monitor')  # opportunity 450: held all the same (decision 107)
        self.assertIn('not enough proof yet for Invest', reason)
        self.assertEqual(lanes.classify(policy_row(), term(sqp_our_purchases=1, ad_orders=1, index=1.2, sqp_volume=0, ad_spend=30.0), ctx())[0], 'monitor')
        self.assertNotEqual(lanes.classify(policy_row(), None, ctx())[0], 'auto')

    def test_its_own_search_band_is_information_and_no_money_level_parks_it(self):
        # until 2026-10-22 a policy-only row over its search's loss line, or with no modelled spend, went to a person;
        # decision 100: the reason names the line, the row goes out
        lane, reason, _ = lanes.classify(policy_row(own_band_month=100.0, modelled_net_month=-90.0), term(), ctx())
        self.assertEqual(lane, 'auto')
        self.assertTrue(reason.endswith('; modelled to lose $90.00 a month, over the $60 loss line for one search' + INFO),
                        reason)
        self.assertEqual(lanes.classify(policy_row(modelled_spend_month=None), term(), ctx())[0], 'auto')
        self.assertNotIn('loss line', lanes.classify(policy_row(), term(), ctx())[1])
        # decision 99 (2026-10-22): a level flag on the row (an older plan's past_kim_level) parks nothing any more
        for flag in (True, None):
            with self.subTest(flag=flag):
                self.assertEqual(lanes.classify(policy_row(past_kim_level=flag), term(), ctx())[0], 'auto')

    def test_locks_and_stale_data_come_first(self):
        locked = ctx(locks={'blank cards': '2026-11-16'})
        self.assertIn('decided by a person', lanes.classify(policy_row(), term(), locked)[1])
        self.assertEqual(lanes.classify(policy_row(), term(), ctx(stale='old'))[0], 'monitor')
        # an onboarding product is judged like any other since 2026-10-22
        self.assertEqual(lanes.classify(policy_row(), term(), ctx(onboarding=True))[:2], lanes.classify(policy_row(), term(), ctx())[:2])

    def test_the_other_types_are_untouched_by_the_marker(self):
        for kind in ('Negative exact', 'Archive negative', 'Stop-loss review', 'Listing price', 'Harvest default bid'):
            with self.subTest(kind):
                self.assertEqual(lanes.classify(policy_row(type=kind), term(), ctx())[:2],
                                 lanes.classify(policy_row(type=kind, policy_tos_only=False), term(), ctx())[:2])
        self.assertEqual(lanes.classify(policy_row(type='Listing price'), term(), ctx())[0], 'human')


class RaiseTest(unittest.TestCase):
    def test_raise_to_breakeven_is_auto(self):
        lane, reason, ev = lanes.classify(change(current=0.50, new=0.60, breakeven=0.60), term(index=1.0, sqp_our_purchases=1), ctx())
        self.assertEqual(lane, 'auto')
        self.assertIn('breakeven', reason)
        self.assertNotIn('new_capped', ev)

    def test_raise_capped_25pct(self):
        lane, _, ev = lanes.classify(change(current=0.40, new=0.80, breakeven=0.90), term(), ctx())
        self.assertEqual(lane, 'auto')
        self.assertEqual(ev['new_capped'], 0.50)

    def test_the_cap_rounds_down_to_stay_within_25_percent(self):
        # 0.39 x 1.25 = 0.4875: rounding to the nearest cent would pass the cap, so it goes down to 0.48
        _, _, ev = lanes.classify(change(current=0.39, new=0.80, breakeven=0.90), term(), ctx())
        self.assertEqual(ev['new_capped'], 0.48)

    def test_a_raise_of_exactly_the_cap_is_not_capped(self):
        _, _, ev = lanes.classify(change(current=0.40, new=0.50, breakeven=0.90), term(), ctx())
        self.assertNotIn('new_capped', ev)

    def test_a_tiny_bid_still_moves_by_at_least_a_cent(self):
        # 0.02 x 1.25 rounds down to 0.02, which would make the "raise" a no-op: the cap is one cent over the bid
        lane, _, ev = lanes.classify(change(current=0.02, new=0.05, breakeven=0.10), term(), ctx())
        self.assertEqual(lane, 'auto')
        self.assertEqual(ev['new_capped'], 0.03)
        _, _, ev = lanes.classify(change(current=0.03, new=0.08, breakeven=0.10), term(), ctx())
        self.assertEqual(ev['new_capped'], 0.04)

    def test_the_one_cent_minimum_is_not_used_when_the_percentage_cap_is_already_bigger(self):
        _, _, ev = lanes.classify(change(current=0.08, new=0.30, breakeven=0.40), term(), ctx())
        self.assertEqual(ev['new_capped'], 0.10)

    def test_a_raise_the_cap_cannot_move_goes_to_monitor_with_a_plain_reason(self):
        # at breakeven already: even one more cent would pass it, and 25% of 0.02 is nothing
        for over in [dict(), dict(spend90=500.0)]:
            with self.subTest(over=over):
                c = change(current=0.02, new=0.05, breakeven=0.02, **over)
                lane, reason, ev = lanes.classify(c, term(index=2.0, sqp_our_purchases=5, sqp_volume=5000), ctx())
                self.assertEqual(lane, 'monitor')
                self.assertEqual(reason, "it can't rise this run: one more cent would pass its breakeven click ($0.02), "
                                         'so it waits for the next run')
                self.assertNotIn('new_capped', ev)

    def test_the_one_cent_minimum_stops_at_breakeven(self):
        # breakeven $0.03: the raise may go one cent up to it, but not past it
        lane, _, ev = lanes.classify(change(current=0.02, new=0.03, breakeven=0.03), term(), ctx())
        self.assertEqual(lane, 'auto')
        self.assertNotIn('new_capped', ev)
        lane, _, ev = lanes.classify(change(current=0.02, new=0.05, breakeven=0.03), term(index=1.0, sqp_our_purchases=1), ctx())
        self.assertEqual(ev['new_capped'], 0.03)
        self.assertNotEqual(lane, 'auto')

    def test_the_cap_reads_the_configured_percentage(self):
        a = dict(A, max_raise_pct=10)
        _, _, ev = lanes.classify(change(current=0.40, new=0.80, breakeven=0.90), term(), ctx(auto=a))
        self.assertEqual(ev['new_capped'], 0.44)

    def test_a_capped_raise_still_reports_the_cap_when_it_is_held(self):
        lane, _, ev = lanes.classify(change(current=0.40, new=0.80, breakeven=0.50), term(index=1.2, sqp_our_purchases=2), ctx())
        self.assertEqual(lane, 'monitor')
        self.assertEqual(ev['new_capped'], 0.50)

    def test_raise_above_breakeven_on_the_ladder_is_auto(self):
        lane, reason, ev = lanes.classify(change(current=0.50, new=0.70, breakeven=0.60), term(index=1.4, sqp_our_purchases=3), ctx())
        self.assertEqual(lane, 'auto')
        self.assertIn('enough proof to bid above breakeven: 3 orders at index 1.40 (converts 1.4x the market)', reason)
        self.assertIn('the bar is 3+ orders at 1.4x the market', reason)
        self.assertEqual(ev['new_capped'], 0.62)

    def test_raise_above_breakeven_needs_both_orders_and_index(self):
        for over in [dict(index=1.39, sqp_our_purchases=3), dict(index=2.0, sqp_our_purchases=2, ad_orders=2)]:
            with self.subTest(over=over):
                self.assertNotEqual(lanes.classify(change(current=0.50, new=0.70, breakeven=0.60), term(**over), ctx())[0], 'auto')

    def test_raise_above_breakeven_off_the_ladder_and_small_goes_to_monitor(self):
        lane, _, ev = lanes.classify(change(current=0.50, new=0.70, breakeven=0.60),
                                     term(index=1.2, sqp_our_purchases=2, sqp_volume=200), ctx())
        self.assertEqual(lane, 'monitor')
        self.assertLess(ev['opportunity'], A['min_opportunity'])

    def test_raise_above_breakeven_off_the_ladder_and_big_is_held(self):
        lane, _, ev = lanes.classify(change(current=0.50, new=0.70, breakeven=0.60),
                                     term(index=1.2, sqp_our_purchases=2, sqp_volume=2000), ctx())
        self.assertEqual(lane, 'monitor')   # decision 107: the AI's "not yet", whatever the size
        self.assertGreaterEqual(ev['opportunity'], A['min_opportunity'])

    def test_raise_without_sqp_goes_monitor(self):
        lane, _, ev = lanes.classify(change(current=0.40, new=0.60, breakeven=0.50, spend90=5.0, orders90=1), None, ctx())
        self.assertEqual(lane, 'monitor')
        self.assertIsNone(ev['opportunity'])

    def test_raise_without_sqp_that_spent_over_the_cap_is_held_too(self):
        # $60 over 90 days is $20 over 30 days, above the $15 cap that sent it to a person until 2026-10-23 (decision 107)
        lane, reason, _ = lanes.classify(change(current=0.40, new=0.60, breakeven=0.50, spend90=60.0, orders90=1), None, ctx())
        self.assertEqual(lane, 'monitor')
        self.assertIn('($20.00 spent in 30 days)', reason)

    def test_a_hold_uplift_raise_to_breakeven_plus_its_percent_is_auto(self):
        # decision 108 (2026-10-23): a Hold search at index 1.0-1.1 bids breakeven +15%, its role's own price
        row = change(role='Hold', current=0.50, new=0.69, breakeven=0.60, hold_uplift=15)
        lane, reason, _ = lanes.classify(row, term(index=1.05), ctx())
        self.assertEqual(lane, 'auto')
        self.assertIn('the raise stops at breakeven +15% ($0.69)', reason)
        # past breakeven +15% it is judged like any raise; without the flag, a raise past breakeven needs the ladder
        self.assertNotEqual(lanes.classify(dict(row, new=0.75), term(index=1.05), ctx())[0], 'auto')
        self.assertNotEqual(lanes.classify(dict(row, hold_uplift=None), term(index=1.05), ctx())[0], 'auto')

    def test_raise_to_breakeven_without_sqp_is_still_auto(self):
        lane, _, _ = lanes.classify(change(current=0.40, new=0.50, breakeven=0.50, spend90=5.0), None, ctx())
        self.assertEqual(lane, 'auto')

    def test_breakeven_falls_back_to_the_terms_be_cpc(self):
        lane, _, _ = lanes.classify(change(current=0.50, new=0.55, breakeven=None), term(be_cpc=0.55, index=1.0), ctx())
        self.assertEqual(lane, 'auto')

    def test_no_breakeven_anywhere_cannot_be_auto_without_the_ladder(self):
        lane, _, _ = lanes.classify(change(current=0.50, new=0.55, breakeven=None, spend90=5.0), None, ctx())
        self.assertEqual(lane, 'monitor')

    def test_no_raises_left_holds_it_for_the_next_run_even_at_breakeven(self):
        lane, reason, _ = lanes.classify(change(current=0.50, new=0.60, breakeven=0.60), term(), ctx(raises_left=0))
        self.assertEqual(lane, 'monitor')   # decision 107: the next run raises it
        self.assertIn('raises, so it goes out on the next run', reason)

    def test_no_raises_left_only_stops_raises_that_would_have_applied(self):
        # a small close call is still held in monitor, so an used-up cap doesn't ping a person about it
        small = change(current=0.40, new=0.60, breakeven=0.50, spend90=5.0, orders90=1)
        self.assertEqual(lanes.classify(small, None, ctx(raises_left=0))[0], 'monitor')
        self.assertEqual(lanes.classify(small, None, ctx(raises_left=3))[0], 'monitor')
        # a big close call is held too, whether or not the cap is used up (decision 107)
        big = change(current=0.50, new=0.70, breakeven=0.60)
        self.assertEqual(lanes.classify(big, term(index=1.2, sqp_our_purchases=2, sqp_volume=2000), ctx(raises_left=0))[0], 'monitor')
        # the last raise left still applies
        self.assertEqual(lanes.classify(change(current=0.50, new=0.60, breakeven=0.60), term(), ctx(raises_left=1))[0], 'auto')

    def test_a_raise_held_back_only_for_the_run_cap_keeps_its_capped_bid(self):
        # A5 (M6): the held row keeps what the auto lane would have written (+25%); the next run raises it (decision 107)
        lane, reason, ev = lanes.classify(change(current=0.40, new=0.80, breakeven=0.80), term(), ctx(raises_left=0))
        self.assertEqual(lane, 'monitor')
        self.assertEqual((ev['new_capped'], ev['raises_used_up']), (0.50, True))
        self.assertEqual(reason, 'this run has used up its 20 automatic raises, so it goes out on the next run')
        lane, reason, ev = lanes.classify(change(current=0.50, new=0.60, breakeven=0.60), term(), ctx(raises_left=0))
        self.assertEqual((reason, ev['raises_used_up']), ('this run has used up its 20 automatic raises, so it goes out on the next run', True))
        self.assertNotIn('new_capped', ev)  # within +25%: nothing to cap
        # a raise that is a person's call for its own reason is not flagged
        _, _, ev = lanes.classify(change(current=0.40, new=0.80, breakeven=0.50), term(index=1.2, sqp_our_purchases=2), ctx())
        self.assertNotIn('raises_used_up', ev)

    def test_raises_left_does_not_touch_cuts(self):
        lane, _, _ = lanes.classify(change(role='Trim', current=0.60, new=0.30, orders90=0), term(), ctx(raises_left=0))
        self.assertEqual(lane, 'auto')

    def test_invest_reprice_inside_amazons_range_is_auto(self):
        c = change(role='Invest', current=0.60, new=0.75, breakeven=0.70, sug_low=0.55, sug_median=0.70, sug_high=0.90)
        lane, reason, _ = lanes.classify(c, term(index=1.1), ctx())
        self.assertEqual(lane, 'auto')
        self.assertIn('range', reason)

    def test_invest_reprice_far_below_the_range_is_still_judged_on_where_it_lands(self):
        c = change(role='Prove first', current=0.40, new=0.70, breakeven=0.55, sug_low=0.55, sug_high=0.90)
        lane, _, ev = lanes.classify(c, term(index=1.1), ctx())
        self.assertEqual(lane, 'auto')
        self.assertEqual(ev['new_capped'], 0.50)

    def test_invest_reprice_above_amazons_high_is_not_auto(self):
        c = change(role='Invest', current=0.80, new=0.95, breakeven=0.70, sug_low=0.55, sug_high=0.90)
        self.assertNotEqual(lanes.classify(c, term(index=1.1), ctx())[0], 'auto')

    def test_invest_reprice_without_suggested_bids_is_not_auto(self):
        c = change(role='Invest', current=0.60, new=0.75, breakeven=0.70)
        self.assertNotEqual(lanes.classify(c, term(index=1.1), ctx())[0], 'auto')

    def test_range_exception_is_only_for_invest_roles(self):
        c = change(role='Hold', current=0.60, new=0.75, breakeven=0.70, sug_low=0.55, sug_high=0.90)
        self.assertNotEqual(lanes.classify(c, term(index=1.1), ctx())[0], 'auto')

    def test_target_raise_above_breakeven_uses_the_product_baseline_for_its_index(self):
        # 3 orders and a conversion of 0.12 against the product's 0.08 is index 1.5
        c = target(current=0.35, new=0.45, breakeven=0.40, cvr=0.12, orders90=3)
        lane, _, _ = lanes.classify(c, None, ctx())
        self.assertEqual(lane, 'auto')
        weak = target(current=0.35, new=0.45, breakeven=0.40, cvr=0.09, orders90=3)
        self.assertNotEqual(lanes.classify(weak, None, ctx())[0], 'auto')

    def test_target_raise_to_breakeven_is_auto(self):
        lane, _, _ = lanes.classify(target(current=0.30, new=0.38, breakeven=0.40, orders90=1), None, ctx())
        self.assertEqual(lane, 'auto')


class ReasonTextTest(unittest.TestCase):
    def test_reasons_are_plain_words_whatever_the_row_looks_like(self):
        rows = [
            (change(current=0.60, new=0.30, role=None), term()),
            (change(type='Pause keyword', new=None, role=None, orders90=0), term(sqp_our_purchases=0)),
            (change(type='Pause keyword', new=None, orders90=1), term()),
            (change(role='Trim', current=1.00, new=0.30, orders90=1), term(sqp_our_purchases=3, sqp_our_clicks=40)),
            (change(current=0.40, new=0.60, breakeven=None), None),
            (change(current=0.40, new=0.60, breakeven=0.50, spend90=60.0), None),
            (change(current=0.02, new=0.05, breakeven=0.02), term()),
            (change(role='Invest', current=0.60, new=0.75, breakeven=0.70, sug_low=0.55, sug_high=0.90), term(index=1.1)),
            (promotion(), term()),
            (promotion(role=None), term()),
            (promotion(modelled_spend_month=None), term()),
            (promotion(own_band_month=80.0, modelled_net_month=-112.5), term()),
            (promotion(own_band_month=None), term()),
            (promotion(), None),
            (promotion(), term(sqp_our_purchases=1, index=1.0 / 3, sqp_volume=0, ad_spend=0.0)),
            (target(current=0.35, new=0.45, breakeven=0.40, cvr=0.12, orders90=1), None),
            (target(type='Pause target', role='Pause', new=None, orders90=0, clicks90=25), None),
            (change(type=None), None),
        ]
        for c, t in rows:
            for over in [dict(), dict(raises_left=0), dict(band_left_month=0.0), dict(band_left_month=-5.0)]:
                with self.subTest(type=c.get('type'), role=c.get('role'), over=over):
                    _, reason, _ = lanes.classify(c, t, ctx(**over))
                    self.assertNotIn('None', reason)
                    self.assertNotRegex(reason, r'\b1 orders\b')
                    self.assertNotRegex(reason, r'\d\.\d{4,}')
                    self.assertNotRegex(reason, r'\$-')

    def test_internal_terms_come_with_a_gloss(self):
        _, reason, _ = lanes.classify(promotion(role='Invest'), term(sqp_our_purchases=2, ad_orders=2, index=1.2, sqp_volume=2000), ctx())
        self.assertIn('not enough proof yet for Invest (needs 3+ orders at 1.1x the market)', reason)
        self.assertIn('index 1.20 (converts 1.2x the market)', reason)
        self.assertIn('opportunity 857 (conversion index x monthly searches)', reason)
        _, reason, _ = lanes.classify(change(current=0.50, new=0.55, breakeven=0.55), term(), ctx())
        self.assertIn('breakeven click ($0.55, the most a click can cost and still pay for itself)', reason)

    def test_a_target_is_measured_against_the_products_ad_average_not_the_market(self):
        weak = target(current=0.35, new=0.45, breakeven=0.40, cvr=0.088, orders90=3)
        _, reason, _ = lanes.classify(weak, None, ctx())
        self.assertIn("needs 3+ orders at 1.4x the product's ad average", reason)
        self.assertIn("index 1.10 (converts 1.1x the product's ad average)", reason)
        self.assertNotIn('the market', reason)

    def test_a_search_with_no_volume_says_so_and_how_much_it_spent(self):
        c = change(current=0.40, new=0.60, breakeven=0.50, spend90=6.0)
        _, reason, _ = lanes.classify(c, None, ctx())
        self.assertIn('no search volume to size it ($2.00 spent in 30 days)', reason)

    def test_a_band_that_is_already_overspent_reads_zero_left_not_a_negative(self):
        lane, reason, _ = lanes.classify(promotion(), term(), ctx(band_left_month=-5.0))
        self.assertEqual(lane, 'auto')
        self.assertIn('($150.00, with $0.00 left)', reason)
        self.assertNotIn('$-', reason)

    def test_a_negative_zero_band_does_not_print_a_minus_sign(self):
        _, reason, _ = lanes.classify(promotion(), term(), ctx(band_left_month=-0.0))
        self.assertIn('($150.00, with $0.00 left)', reason)

    def test_the_used_up_raises_reason_pluralises(self):
        for limit, said in [(1, 'its 1 automatic raise'), (2, 'its 2 automatic raises'), (20, 'its 20 automatic raises')]:
            with self.subTest(limit=limit):
                _, reason, _ = lanes.classify(change(current=0.50, new=0.60, breakeven=0.60), term(),
                                              ctx(auto=dict(A, max_raises=limit), raises_left=0))
                self.assertIn(said, reason)
                if limit == 1:
                    self.assertNotIn('raises', reason)


class EvidenceTest(unittest.TestCase):
    def test_a_raise_reads_confidence_that_it_beats_the_market(self):
        _, _, ev = lanes.classify(change(), term(sqp_our_purchases=3, sqp_our_clicks=15), ctx())
        self.assertEqual(ev['confidence_kind'], 'beats')
        self.assertEqual(ev['confidence'], evidence.p_beats(3, 15, 0.10))

    def test_a_cut_reads_confidence_that_it_is_below_the_market(self):
        _, _, ev = lanes.classify(change(role='Trim', current=0.60, new=0.30, orders90=0),
                                  term(sqp_our_purchases=0, sqp_our_clicks=30, index=0.25), ctx())
        self.assertEqual(ev['confidence_kind'], 'below')
        self.assertEqual(ev['confidence'], evidence.p_below(0, 30, 0.10))

    def test_a_pause_is_a_cut_for_confidence(self):
        _, _, ev = lanes.classify(change(type='Pause keyword', new=None, role=None, orders90=0, clicks90=40),
                                  term(sqp_our_purchases=0, sqp_our_clicks=30), ctx())
        self.assertEqual(ev['confidence_kind'], 'below')

    def test_promotion_confidence_is_that_it_beats_the_market(self):
        _, _, ev = lanes.classify(promotion(), term(), ctx())
        self.assertEqual(ev['confidence_kind'], 'beats')

    def test_orders_and_clicks_come_from_sqp_when_the_index_is_sqp_based(self):
        _, _, ev = lanes.classify(change(), term(index_basis='SQP (thin)', sqp_our_purchases=4, sqp_our_clicks=20,
                                                 ad_orders=1, ad_clicks=50), ctx())
        self.assertEqual(ev['confidence'], evidence.p_beats(4, 20, 0.10))

    def test_orders_and_clicks_come_from_the_ads_when_the_index_is_not_sqp_based(self):
        _, _, ev = lanes.classify(change(), term(index_basis='Search terms', sqp_our_purchases=4, sqp_our_clicks=20,
                                                 ad_orders=1, ad_clicks=50), ctx())
        self.assertEqual(ev['confidence'], evidence.p_beats(1, 50, 0.10))

    def test_without_a_term_the_changes_own_orders_and_clicks_are_used(self):
        _, _, ev = lanes.classify(change(current=0.60, new=0.30, orders90=2, clicks90=40, role='Trim'), None, ctx())
        # no term means no market conversion, so no confidence
        self.assertIsNone(ev['confidence'])
        self.assertIsNone(ev['confidence_kind'])

    def test_a_target_uses_the_products_ad_conversion_as_its_baseline(self):
        _, _, ev = lanes.classify(target(current=0.50, new=0.40, orders90=3, clicks90=20, baseline_cvr=0.08), None, ctx())
        self.assertEqual(ev['confidence_kind'], 'below')
        self.assertEqual(ev['confidence'], evidence.p_below(3, 20, 0.08))

    def test_a_target_raise_uses_beats_against_the_baseline(self):
        _, _, ev = lanes.classify(target(current=0.30, new=0.38, orders90=3, clicks90=20, baseline_cvr=0.08), None, ctx())
        self.assertEqual(ev['confidence_kind'], 'beats')
        self.assertEqual(ev['confidence'], evidence.p_beats(3, 20, 0.08))

    def test_a_target_without_a_baseline_has_no_confidence_and_is_still_judged(self):
        c = target(current=0.50, new=0.40, orders90=1)
        del c['baseline_cvr']
        lane, _, ev = lanes.classify(c, None, ctx())
        self.assertEqual(lane, 'auto')
        self.assertIsNone(ev['confidence'])

    def test_confidence_is_none_when_there_are_no_clicks_or_the_market_is_unusable(self):
        for over in [dict(sqp_our_clicks=0, sqp_our_purchases=0), dict(market_cvr=None), dict(market_cvr=0.0),
                     dict(market_cvr=1.0)]:
            with self.subTest(over=over):
                _, _, ev = lanes.classify(change(), term(**over), ctx())
                self.assertIsNone(ev['confidence'])
                self.assertIsNone(ev['confidence_kind'])

    def test_purchases_above_clicks_do_not_crash_confidence(self):
        _, _, ev = lanes.classify(change(), term(sqp_our_purchases=5, sqp_our_clicks=3), ctx())
        self.assertEqual(ev['confidence'], evidence.p_beats(5, 3, 0.10))

    def test_opportunity_comes_from_the_terms_index_volume_and_days(self):
        _, _, ev = lanes.classify(change(), term(index=1.5, sqp_volume=840, observed_days=84), ctx())
        self.assertEqual(ev['opportunity'], 450.0)

    def test_opportunity_is_none_without_a_term_or_volume(self):
        self.assertIsNone(lanes.classify(change(), None, ctx())[2]['opportunity'])
        self.assertIsNone(lanes.classify(change(), term(sqp_volume=0), ctx())[2]['opportunity'])

    def test_locked_and_always_human_rows_still_carry_evidence(self):
        _, _, locked = lanes.classify(change(), term(), ctx(locks={'111': '2026-11-16'}))
        self.assertEqual(locked['opportunity'], 450.0)
        _, _, budget = lanes.classify(change(type='Budget and top of search'), term(), ctx())
        self.assertEqual(budget['opportunity'], 450.0)
        self.assertIsNone(budget['confidence'])

    def test_classify_does_not_change_its_inputs(self):
        c, t, x = change(current=0.40, new=0.80), term(), ctx()
        before = copy.deepcopy((c, t, x))
        lanes.classify(c, t, x)
        self.assertEqual((c, t, x), before)


class FirstUsWeekdayTest(unittest.TestCase):
    def test_weekend_run_waits(self):
        # 16:35 UTC on Sunday 18 Oct 2026 is 09:35 Sunday in Los Angeles: the first US weekday is Monday
        self.assertEqual(lanes.first_us_weekday(datetime(2026, 10, 18, 16, 35, tzinfo=UTC)), date(2026, 10, 19))

    def test_weekday_run_now(self):
        self.assertEqual(lanes.first_us_weekday(datetime(2026, 10, 20, 18, 0, tzinfo=UTC)), date(2026, 10, 20))

    def test_the_us_date_decides_not_the_utc_date(self):
        # Saturday in UTC, still Friday evening in Los Angeles: the US weekday is that Friday
        self.assertEqual(lanes.first_us_weekday(datetime(2026, 10, 24, 5, 0, tzinfo=UTC)), date(2026, 10, 23))
        # Monday in UTC, still Sunday evening in Los Angeles: wait for the US Monday
        self.assertEqual(lanes.first_us_weekday(datetime(2026, 10, 19, 3, 0, tzinfo=UTC)), date(2026, 10, 19))

    def test_saturday_and_sunday_both_wait_for_monday(self):
        for day in (17, 18):
            with self.subTest(day=day):
                self.assertEqual(lanes.first_us_weekday(datetime(2026, 10, day, 20, 0, tzinfo=UTC)), date(2026, 10, 19))

    def test_every_weekday_is_its_own_date(self):
        for day in range(19, 24):  # Mon 19 to Fri 23 Oct 2026
            with self.subTest(day=day):
                self.assertEqual(lanes.first_us_weekday(datetime(2026, 10, day, 20, 0, tzinfo=UTC)), date(2026, 10, day))

    def test_after_the_clocks_go_forward_the_offset_is_minus_7(self):
        # Saturday 20 Mar 2027 00:30 PDT, so wait for Monday
        self.assertEqual(lanes.first_us_weekday(datetime(2027, 3, 20, 7, 30, tzinfo=UTC)), date(2027, 3, 22))

    def test_before_the_clocks_go_forward_the_offset_is_minus_8(self):
        # still PST in early March: Friday 5 Mar 2027 23:30, not Saturday
        self.assertEqual(lanes.first_us_weekday(datetime(2027, 3, 6, 7, 30, tzinfo=UTC)), date(2027, 3, 5))

    def test_before_the_clocks_go_back_the_offset_is_minus_7(self):
        # Saturday 31 Oct 2026 00:30 PDT, so wait for Monday
        self.assertEqual(lanes.first_us_weekday(datetime(2026, 10, 31, 7, 30, tzinfo=UTC)), date(2026, 11, 2))

    def test_after_the_clocks_go_back_the_offset_is_minus_8(self):
        # Friday 6 Nov 2026 23:30 PST
        self.assertEqual(lanes.first_us_weekday(datetime(2026, 11, 7, 7, 30, tzinfo=UTC)), date(2026, 11, 6))

    def test_winter_months_use_minus_8(self):
        # 07:30 UTC on Mon 4 Jan 2027 is Sunday 23:30 PST: wait for Monday. At minus 7 it would be Monday 00:30.
        self.assertEqual(lanes.first_us_weekday(datetime(2027, 1, 4, 7, 30, tzinfo=UTC)), date(2027, 1, 4))
        # 07:30 UTC on Sat 9 Jan 2027 is Friday 23:30 PST: that Friday. At minus 7 it would be Saturday 00:30.
        self.assertEqual(lanes.first_us_weekday(datetime(2027, 1, 9, 7, 30, tzinfo=UTC)), date(2027, 1, 8))

    def test_the_new_year_crosses_back_into_the_old_one(self):
        # 03:00 UTC on Fri 1 Jan 2027 is Thursday 19:00 PST, 31 Dec 2026
        self.assertEqual(lanes.first_us_weekday(datetime(2027, 1, 1, 3, 0, tzinfo=UTC)), date(2026, 12, 31))

    def test_the_clocks_change_at_2am_on_the_second_sunday_of_march_and_the_first_of_november(self):
        # forward at 02:00 PST = 10:00 UTC, back at 02:00 PDT = 09:00 UTC
        cases = [(datetime(2027, 3, 14, 9, 59, tzinfo=UTC), -8), (datetime(2027, 3, 14, 10, 0, tzinfo=UTC), -7),
                 (datetime(2026, 11, 1, 8, 59, tzinfo=UTC), -7), (datetime(2026, 11, 1, 9, 0, tzinfo=UTC), -8),
                 (datetime(2026, 3, 8, 9, 59, tzinfo=UTC), -8), (datetime(2026, 3, 8, 10, 0, tzinfo=UTC), -7),
                 (datetime(2027, 11, 7, 8, 59, tzinfo=UTC), -7), (datetime(2027, 11, 7, 9, 0, tzinfo=UTC), -8)]
        for moment, hours in cases:
            with self.subTest(moment=moment):
                self.assertEqual(lanes._la_offset_hours(moment), hours)

    def test_a_time_in_another_zone_is_read_as_the_instant_it_is(self):
        singapore = timezone(timedelta(hours=8))
        # 00:30 Monday 19 Oct in Singapore is 16:30 UTC Sunday: Sunday 09:30 in Los Angeles
        self.assertEqual(lanes.first_us_weekday(datetime(2026, 10, 19, 0, 30, tzinfo=singapore)), date(2026, 10, 19))
        # 07:00 Tuesday 20 Oct in Singapore is Monday 16:00 in Los Angeles
        self.assertEqual(lanes.first_us_weekday(datetime(2026, 10, 20, 7, 0, tzinfo=singapore)), date(2026, 10, 19))

    def test_a_time_with_no_zone_is_refused(self):
        with self.assertRaises(ValueError):
            lanes.first_us_weekday(datetime(2026, 10, 20, 18, 0))


class UsDateTest(unittest.TestCase):
    def test_it_is_the_los_angeles_calendar_date(self):
        self.assertEqual(lanes.us_date(datetime(2026, 10, 18, 16, 35, tzinfo=UTC)), date(2026, 10, 18))
        self.assertEqual(lanes.us_date(datetime(2026, 10, 19, 3, 0, tzinfo=UTC)), date(2026, 10, 18))
        self.assertEqual(lanes.us_date(datetime(2026, 10, 24, 5, 0, tzinfo=UTC)), date(2026, 10, 23))

    def test_it_does_not_skip_the_weekend(self):
        self.assertEqual(lanes.us_date(datetime(2026, 10, 17, 20, 0, tzinfo=UTC)), date(2026, 10, 17))
        self.assertEqual(lanes.us_date(datetime(2026, 10, 18, 20, 0, tzinfo=UTC)), date(2026, 10, 18))

    def test_the_date_turns_over_at_local_midnight_on_both_sides_of_the_clocks_going_forward(self):
        cases = [(datetime(2027, 3, 14, 7, 59, tzinfo=UTC), date(2027, 3, 13)),  # 23:59 PST
                 (datetime(2027, 3, 14, 8, 0, tzinfo=UTC), date(2027, 3, 14)),   # 00:00 PST
                 (datetime(2027, 3, 14, 9, 59, tzinfo=UTC), date(2027, 3, 14)),  # 01:59 PST, the last minute of PST
                 (datetime(2027, 3, 14, 10, 0, tzinfo=UTC), date(2027, 3, 14)),  # 03:00 PDT, the first of PDT
                 (datetime(2027, 3, 15, 6, 59, tzinfo=UTC), date(2027, 3, 14)),  # 23:59 PDT
                 (datetime(2027, 3, 15, 7, 0, tzinfo=UTC), date(2027, 3, 15))]   # 00:00 PDT
        for moment, expected in cases:
            with self.subTest(moment=moment):
                self.assertEqual(lanes.us_date(moment), expected)

    def test_the_date_turns_over_at_local_midnight_on_both_sides_of_the_clocks_going_back(self):
        cases = [(datetime(2026, 11, 1, 6, 59, tzinfo=UTC), date(2026, 10, 31)),  # 23:59 PDT
                 (datetime(2026, 11, 1, 7, 0, tzinfo=UTC), date(2026, 11, 1)),    # 00:00 PDT
                 (datetime(2026, 11, 1, 9, 0, tzinfo=UTC), date(2026, 11, 1)),    # 01:00 PST, the repeated hour
                 (datetime(2026, 11, 2, 7, 59, tzinfo=UTC), date(2026, 11, 1)),   # 23:59 PST
                 (datetime(2026, 11, 2, 8, 0, tzinfo=UTC), date(2026, 11, 2))]    # 00:00 PST
        for moment, expected in cases:
            with self.subTest(moment=moment):
                self.assertEqual(lanes.us_date(moment), expected)

    def test_a_time_in_another_zone_is_read_as_the_instant_it_is(self):
        singapore = timezone(timedelta(hours=8))
        self.assertEqual(lanes.us_date(datetime(2026, 10, 19, 0, 30, tzinfo=singapore)), date(2026, 10, 18))

    def test_a_time_with_no_zone_is_refused(self):
        with self.assertRaises(ValueError):
            lanes.us_date(datetime(2026, 10, 20, 18, 0))


class UsWriteWindowTest(unittest.TestCase):
    def test_all_days_and_legacy_dates_allow_execution(self):
        for day in range(19,26):
            for legacy in (None, date(2026,10,26), date(2026,9,1)):
                with self.subTest(day=day,legacy=legacy):
                    self.assertTrue(lanes.us_write_window_open(datetime(2026,10,day,18,0,tzinfo=UTC),legacy))

    def test_unzoned_timestamp_is_still_rejected(self):
        with self.assertRaises(ValueError):
            lanes.us_write_window_open(datetime(2026,10,24,18,0),None)



class ReadbackTest(unittest.TestCase):
    def test_readback_flags_drift(self):
        written = [{'keywordId': '111', 'bid': 0.27}]
        live = [{'keywordId': '111', 'bid': 0.32, 'state': 'ENABLED'}]
        self.assertEqual(lanes.readback_mismatches(written, live), [{'id': '111', 'written': 0.27, 'live': 0.32}])

    def test_readback_flags_unpaused(self):
        written = [{'keywordId': '111', 'state': 'PAUSED'}]
        live = [{'keywordId': '111', 'bid': 0.30, 'state': 'ENABLED'}]
        self.assertEqual(lanes.readback_mismatches(written, live),
                         [{'id': '111', 'written': 'PAUSED', 'live': 'ENABLED'}])

    def test_readback_clean(self):
        written = [{'keywordId': '111', 'bid': 0.27}, {'targetId': '777', 'state': 'PAUSED'}]
        live = [{'keywordId': '111', 'bid': 0.27, 'state': 'ENABLED'}, {'targetId': '777', 'bid': 0.40, 'state': 'PAUSED'}]
        self.assertEqual(lanes.readback_mismatches(written, live), [])

    def test_nothing_written_is_clean(self):
        self.assertEqual(lanes.readback_mismatches([], [{'keywordId': '111', 'bid': 0.27, 'state': 'ENABLED'}]), [])
        self.assertEqual(lanes.readback_mismatches([], []), [])

    def test_a_bid_within_half_a_cent_is_clean(self):
        def live(bid):
            return [{'keywordId': '111', 'bid': bid, 'state': 'ENABLED'}]
        written = [{'keywordId': '111', 'bid': 0.27}]
        for bid in (0.27, 0.274, 0.266, 0.275, 0.265):
            with self.subTest(bid=bid):
                self.assertEqual(lanes.readback_mismatches(written, live(bid)), [])
        for bid in (0.276, 0.264, 0.28, 0.0):
            with self.subTest(bid=bid):
                self.assertEqual(len(lanes.readback_mismatches(written, live(bid))), 1)

    def test_ids_are_compared_as_strings(self):
        live = [{'keywordId': 111, 'bid': 0.27, 'state': 'ENABLED'}, {'targetId': '777', 'bid': 0.40, 'state': 'PAUSED'}]
        written = [{'keywordId': '111', 'bid': 0.27}, {'targetId': 777, 'state': 'PAUSED'}]
        self.assertEqual(lanes.readback_mismatches(written, live), [])

    def test_the_result_id_is_a_string_whatever_the_payload_used(self):
        out = lanes.readback_mismatches([{'keywordId': 111, 'bid': 0.27}], [{'keywordId': '111', 'bid': 0.32}])
        self.assertEqual(out[0]['id'], '111')

    def test_state_is_compared_case_insensitively(self):
        written = [{'keywordId': '111', 'state': 'PAUSED'}, {'targetId': '777', 'state': 'enabled'}]
        live = [{'keywordId': '111', 'state': 'paused'}, {'targetId': '777', 'state': 'ENABLED'}]
        self.assertEqual(lanes.readback_mismatches(written, live), [])

    def test_a_written_row_missing_from_live_is_a_mismatch(self):
        live = [{'keywordId': '111', 'bid': 0.27, 'state': 'ENABLED'}]
        self.assertEqual(lanes.readback_mismatches([{'keywordId': '999', 'bid': 0.27}], live),
                         [{'id': '999', 'written': 0.27, 'live': None}])
        self.assertEqual(lanes.readback_mismatches([{'targetId': '888', 'state': 'PAUSED'}], live),
                         [{'id': '888', 'written': 'PAUSED', 'live': None}])
        self.assertEqual(lanes.readback_mismatches([{'keywordId': '999', 'bid': 0.27}], []),
                         [{'id': '999', 'written': 0.27, 'live': None}])

    def test_a_row_with_both_fields_missing_from_live_reports_the_written_pair_and_no_live(self):
        out = lanes.readback_mismatches([{'keywordId': '999', 'bid': 0.27, 'state': 'ENABLED'}], [])
        self.assertEqual(out, [{'id': '999', 'written': {'bid': 0.27, 'state': 'ENABLED'}, 'live': None}])

    def test_a_state_only_row_ignores_the_live_bid(self):
        written = [{'keywordId': '111', 'state': 'PAUSED'}]
        live = [{'keywordId': '111', 'bid': 9.99, 'state': 'PAUSED'}]
        self.assertEqual(lanes.readback_mismatches(written, live), [])

    def test_a_bid_only_row_ignores_the_live_state(self):
        written = [{'keywordId': '111', 'bid': 0.27}]
        live = [{'keywordId': '111', 'bid': 0.27, 'state': 'PAUSED'}]
        self.assertEqual(lanes.readback_mismatches(written, live), [])

    def test_a_row_carrying_both_reports_both_as_dicts(self):
        written = [{'keywordId': '111', 'bid': 0.27, 'state': 'ENABLED'}]
        live = [{'keywordId': '111', 'bid': 0.32, 'state': 'enabled'}]
        self.assertEqual(lanes.readback_mismatches(written, live),
                         [{'id': '111', 'written': {'bid': 0.27, 'state': 'ENABLED'},
                           'live': {'bid': 0.32, 'state': 'enabled'}}])

    def test_a_row_carrying_both_is_flagged_when_only_the_state_differs(self):
        written = [{'keywordId': '111', 'bid': 0.27, 'state': 'ENABLED'}]
        live = [{'keywordId': '111', 'bid': 0.27, 'state': 'PAUSED'}]
        self.assertEqual(len(lanes.readback_mismatches(written, live)), 1)

    def test_a_row_carrying_both_that_matches_is_clean(self):
        written = [{'keywordId': '111', 'bid': 0.27, 'state': 'ENABLED'}]
        live = [{'keywordId': '111', 'bid': 0.27, 'state': 'enabled'}]
        self.assertEqual(lanes.readback_mismatches(written, live), [])

    def test_only_the_bad_rows_come_back_in_the_order_written(self):
        written = [{'keywordId': '1', 'bid': 0.20}, {'keywordId': '2', 'bid': 0.30},
                   {'targetId': '3', 'state': 'PAUSED'}, {'keywordId': '4', 'bid': 0.40}]
        live = [{'keywordId': '1', 'bid': 0.20, 'state': 'ENABLED'}, {'keywordId': '2', 'bid': 0.31, 'state': 'ENABLED'},
                {'targetId': '3', 'bid': 0.5, 'state': 'ENABLED'}, {'keywordId': '4', 'bid': 0.40, 'state': 'ENABLED'}]
        self.assertEqual([m['id'] for m in lanes.readback_mismatches(written, live)], ['2', '3'])

    def test_a_live_bid_that_is_missing_or_unreadable_is_a_mismatch(self):
        written = [{'keywordId': '111', 'bid': 0.27}]
        for live_bid in (None, 'n/a'):
            with self.subTest(live_bid=live_bid):
                out = lanes.readback_mismatches(written, [{'keywordId': '111', 'bid': live_bid, 'state': 'ENABLED'}])
                self.assertEqual(out, [{'id': '111', 'written': 0.27, 'live': live_bid}])
        out = lanes.readback_mismatches(written, [{'keywordId': '111', 'state': 'ENABLED'}])
        self.assertEqual(out, [{'id': '111', 'written': 0.27, 'live': None}])

    def test_a_live_bid_that_is_not_a_number_is_a_mismatch(self):
        written = [{'keywordId': '111', 'bid': 0.27}]
        out = lanes.readback_mismatches(written, [{'keywordId': '111', 'bid': float('nan')}])
        self.assertEqual([m['id'] for m in out], ['111'])

    def test_a_live_state_that_is_missing_is_a_mismatch(self):
        out = lanes.readback_mismatches([{'keywordId': '111', 'state': 'PAUSED'}], [{'keywordId': '111', 'bid': 0.3}])
        self.assertEqual(out, [{'id': '111', 'written': 'PAUSED', 'live': None}])

    def test_a_bid_sent_as_text_still_compares_as_a_number(self):
        written = [{'keywordId': '111', 'bid': '0.27'}]
        self.assertEqual(lanes.readback_mismatches(written, [{'keywordId': '111', 'bid': 0.27}]), [])
        self.assertEqual(len(lanes.readback_mismatches(written, [{'keywordId': '111', 'bid': 0.32}])), 1)

    def test_a_written_row_with_no_id_cannot_be_confirmed_so_it_is_a_mismatch(self):
        out = lanes.readback_mismatches([{'bid': 0.27}], [{'keywordId': '111', 'bid': 0.27, 'state': 'ENABLED'}])
        self.assertEqual(out, [{'id': None, 'written': 0.27, 'live': None}])

    def test_a_written_row_with_nothing_to_check_cannot_be_confirmed_so_it_is_a_mismatch(self):
        live = [{'keywordId': '111', 'bid': 0.27, 'state': 'ENABLED'}, {'keywordId': '222', 'bid': 0.30, 'state': 'ENABLED'}]
        for row in ({'keywordId': '111'}, {'keywordId': '111', 'bid': None, 'state': None}):
            with self.subTest(row=row):
                self.assertEqual(lanes.readback_mismatches([row], live), [{'id': '111', 'written': None, 'live': None}])
        # only that row is flagged; its neighbour is checked as usual
        out = lanes.readback_mismatches([{'keywordId': '111'}, {'keywordId': '222', 'bid': 0.30}], live)
        self.assertEqual(out, [{'id': '111', 'written': None, 'live': None}])

    def test_readback_does_not_change_its_inputs(self):
        written = [{'keywordId': 111, 'bid': 0.27, 'state': 'ENABLED'}]
        live = [{'keywordId': '111', 'bid': 0.32, 'state': 'enabled'}]
        before = copy.deepcopy((written, live))
        lanes.readback_mismatches(written, live)
        self.assertEqual((written, live), before)


class SpendCheckTest(unittest.TestCase):
    """The 24-hour check: a spend over 1.5 times the average of the last 14 weekdays switches the auto lane off."""

    def test_spend_check_trips_at_1_5x(self):
        self.assertIs(lanes.spend_check(31.0, [20.0] * 10), True)

    def test_spend_check_ok(self):
        self.assertIs(lanes.spend_check(29.0, [20.0] * 10), False)

    def test_spend_check_no_history_ok(self):
        self.assertIs(lanes.spend_check(31.0, []), False)

    def test_exactly_1_5x_does_not_trip_but_a_cent_over_does(self):
        self.assertIs(lanes.spend_check(30.0, [20.0] * 10), False)
        self.assertIs(lanes.spend_check(30.01, [20.0] * 10), True)

    def test_a_jump_from_an_average_of_zero_trips(self):
        self.assertIs(lanes.spend_check(0.01, [0.0] * 14), True)
        self.assertIs(lanes.spend_check(0.0, [0.0] * 14), False)

    def test_a_nan_or_infinite_spend_trips_even_with_no_history(self):
        for spend in (float('nan'), float('inf')):
            with self.subTest(spend=spend):
                self.assertIs(lanes.spend_check(spend, [20.0] * 10), True)
                self.assertIs(lanes.spend_check(spend, []), True)

    def test_a_nan_or_infinite_value_in_the_history_trips(self):
        for bad in (float('nan'), float('inf')):
            with self.subTest(bad=bad):
                self.assertIs(lanes.spend_check(20.0, [20.0] * 13 + [bad]), True)

    def test_a_negative_spend_or_history_value_raises(self):
        with self.assertRaises(ValueError):
            lanes.spend_check(-1.0, [20.0] * 10)
        with self.assertRaises(ValueError):
            lanes.spend_check(20.0, [20.0] * 13 + [-0.01])
        with self.assertRaises(ValueError):
            lanes.spend_check(float('-inf'), [20.0] * 10)


class CooloffTest(unittest.TestCase):
    """Kim, 2026-10-22: a search the stop-loss stepped down can't be promoted again by the Auto lane for 8 weeks
    (auto.repromote_cooloff_days, 56). A row that re-invests in it inside the window is held, not sent to a person."""
    HELD = 'stepped down at stop-loss on 2026-10-10; held from re-investment until 2026-12-05'

    def cool(self, **over):
        return ctx(cooloff={'blank cards': ('2026-10-10', '2026-12-05')}, **over)

    def test_a_re_investment_inside_the_window_is_held_with_the_dates(self):
        for row in (promotion(), promotion(type='Reuse exact campaign'), policy_row(),
                    change(role='Invest', current=0.50, new=0.60), change(type='SB bid change', role='Invest', current=0.5, new=0.6),
                    dict(policy_row(), policy_tos_only=False, budget=10, budget_now=5)):
            with self.subTest(type=row['type'], role=row.get('role')):
                self.assertTrue(lanes.reinvests(row))
                self.assertEqual(lanes.classify(row, term(), self.cool())[:2], ('monitor', self.HELD))

    def test_cuts_other_roles_and_other_searches_are_judged_as_usual(self):
        for row in (change(role='Invest', current=0.80, new=0.50), change(type='Pause keyword', role='Invest', new=None),
                    change(role='Hold', current=0.50, new=0.60), promotion(keyword='gold cards')):
            with self.subTest(type=row['type'], role=row.get('role'), keyword=row['keyword']):
                self.assertEqual(lanes.classify(row, term(), self.cool())[:2], lanes.classify(row, term(), ctx())[:2])
        # a business step-down holds the business search only, never the consumer one of the same text
        biz = ctx(cooloff={'business:blank cards': ('2026-10-10', '2026-12-05')})
        self.assertEqual(lanes.classify(promotion(), term(), biz)[0], 'auto')
        self.assertEqual(lanes.classify(promotion(type='Business invest', owner_kind='business'), term(), biz)[0], 'monitor')

    def test_a_lock_still_comes_first_and_stale_data_holds_as_before(self):
        self.assertEqual(lanes.classify(promotion(), term(), self.cool(locks={'blank cards': '2026-11-16'}))[0], 'human')
        self.assertTrue(lanes.classify(promotion(), term(), self.cool(stale='old'))[1].startswith('the product data is not fresh'))


class DataStageTest(unittest.TestCase):
    """The data-stage returns of classify (data-stage design sections 4.4.1, 4.4.2, 4.4.4 and 4.6; built 2026-10-22): a
    fallback Prove first and a head-term flag go to a person at every stage; in stage early a promotion waits for its
    second SQP week, and a volatile SQP week holds every promotion (held, monitor, since autonomous runs 2026-10-22: the
    next week's data settles both, so neither is a person's call). Cuts, raises and business rows are judged as before."""
    EARLY = dict(stage='early', sqp_queries=12, observed_days=21, trusted_queries=2, left_launch_this_run=False,
                 reason='early: 21 observed days, 2 trusted queries, 12 SQP queries with impressions')
    VOLATILE = 'volatile SQP week: the week through 2026-10-17 added 248 of our clicks, more than the 214 of all earlier weeks'

    def room(self, **over):
        """A Ctx with room in the band and under Kim's level, so the ladder alone decides."""
        return ctx(band_left_month=200.0, **over)

    def test_classify_early_stage_promotion_waits_for_its_second_week(self):
        c = self.room(early_stage=self.EARLY)
        lane, reason, _ = lanes.classify(promotion(sqp_observed_days=7), term(sqp_observed_days=7), c)
        self.assertEqual(lane, 'monitor')
        self.assertTrue(reason.startswith('early SQP: '), reason)
        self.assertIn('seen in one SQP week only', reason)
        self.assertIn('so it waits for its second week', reason)
        # no observed-day count at all counts as 0
        self.assertEqual(lanes.classify(promotion(), term(sqp_observed_days=None), c)[0], 'monitor')
        # the row's own count is read; the term's stands in when the row has none
        self.assertEqual(lanes.classify(promotion(), term(sqp_observed_days=7), c)[0], 'monitor')
        self.assertEqual(lanes.classify(promotion(sqp_observed_days=14), term(sqp_observed_days=7), c)[0], 'auto')
        # two SQP weeks: on to the ladder as today
        lane, reason, _ = lanes.classify(promotion(sqp_observed_days=14), term(sqp_observed_days=14), c)
        self.assertEqual(lane, 'auto')
        self.assertIn('enough proof for Invest', reason)
        # the bar is Ctx.auto_min_observed_days (config.json stage.auto_min_observed_days)
        self.assertEqual(lanes.Ctx.__dataclass_fields__['auto_min_observed_days'].default, 14)
        self.assertEqual(lanes.classify(promotion(sqp_observed_days=14), term(sqp_observed_days=14),
                                        self.room(early_stage=self.EARLY, auto_min_observed_days=21))[0], 'monitor')
        # mature (no early stage): since 2026-10-25 (decision 135) a search SQP has seen in 7 days waits at every stage too,
        # and one with no SQP count is judged as before
        self.assertEqual(lanes.classify(promotion(sqp_observed_days=7), term(sqp_observed_days=7), self.room())[0], 'monitor')
        self.assertEqual(lanes.classify(promotion(sqp_observed_days=14), term(sqp_observed_days=14), self.room())[0], 'auto')
        self.assertEqual(lanes.classify(promotion(), term(sqp_observed_days=None), self.room())[0], 'auto')
        # a Reuse exact campaign and a policy-only top-of-search row take the same check
        self.assertEqual(lanes.classify(promotion(type='Reuse exact campaign', sqp_observed_days=7), term(sqp_observed_days=7), c)[0], 'monitor')
        lane, reason, _ = lanes.classify(policy_row(sqp_observed_days=7), term(sqp_observed_days=7), c)
        self.assertEqual(lane, 'monitor')
        self.assertTrue(reason.startswith('early SQP: '), reason)
        self.assertEqual(lanes.classify(policy_row(sqp_observed_days=14), term(sqp_observed_days=14), c)[0], 'auto')

    def test_classify_volatile_week_holds_promotions(self):
        c = self.room(volatile=self.VOLATILE)
        held = '; promotions wait for a steadier week (a person may lift the hold with --allow-volatile)'
        lane, reason, _ = lanes.classify(promotion(sqp_observed_days=21), term(sqp_observed_days=21), c)
        self.assertEqual(lane, 'monitor')
        self.assertEqual(reason, self.VOLATILE + held)   # the text already starts with the prefix: not doubled
        self.assertTrue(reason.startswith('volatile SQP week: '))
        # a reason without the prefix gets it
        lane, reason, _ = lanes.classify(promotion(), term(), self.room(volatile='the week through 2026-10-17 doubled our clicks'))
        self.assertEqual((lane, reason), ('monitor', 'volatile SQP week: the week through 2026-10-17 doubled our clicks' + held))
        self.assertEqual(lanes.classify(promotion(type='Reuse exact campaign'), term(), c)[0], 'monitor')
        self.assertEqual(lanes.classify(policy_row(), term(), c)[0], 'monitor')
        # the volatile week is read before the early check: a one-week row says volatile, not early
        lane, reason, _ = lanes.classify(promotion(sqp_observed_days=7), term(sqp_observed_days=7),
                                         self.room(early_stage=self.EARLY, volatile=self.VOLATILE))
        self.assertEqual(lane, 'monitor')
        self.assertTrue(reason.startswith('volatile SQP week'), reason)
        # without it, the same promotion is automatic
        self.assertEqual(lanes.classify(promotion(sqp_observed_days=21), term(sqp_observed_days=21), self.room())[0], 'auto')

    def test_classify_early_stage_leaves_bid_cuts(self):
        c = ctx(early_stage=self.EARLY, volatile=self.VOLATILE)
        flagged = term(sqp_observed_days=7, relevance_flag='one token', sqp_our_purchases=1)   # 1 purchase: a pause is no big cut
        for row in (change(new=0.40, sqp_observed_days=7, relevance_flag='one token'), change(type='Pause keyword', new=None, orders90=0),
                    target(new=0.40), target(type='Pause target', new=None, orders90=0)):
            with self.subTest(row=row['type']):
                lane, reason, _ = lanes.classify(row, flagged, c)
                self.assertEqual((lane, reason), lanes.classify(row, flagged, ctx())[:2])
                self.assertEqual(lane, 'auto')
        self.assertEqual(lanes.classify(change(new=0.40), term(), c)[1], 'cut from $0.50 to $0.40: a cut is never held back')
        # a raise, a negative and a budget step are judged as before too
        raise_ = change(current=0.40, new=0.50, breakeven=0.60)
        self.assertEqual(lanes.classify(raise_, term(), c)[:2], lanes.classify(raise_, term(), ctx())[:2])
        self.assertEqual(lanes.classify(raise_, term(), c)[0], 'auto')
        negative = dict(type='Negative exact', keyword='blank cards')
        self.assertEqual(lanes.classify(negative, term(), c)[:2], lanes.classify(negative, term(), ctx())[:2])
        self.assertEqual(lanes.classify(negative, term(), c)[0], 'auto')

    def test_classify_early_stage_skips_business_rows(self):
        c = promotion(type='Business invest', owner_kind='business', role='Invest', relevance_flag='one token', sqp_observed_days=7)
        bt = term(index=2.4, index_basis='Search terms (business)', ad_clicks=25, ad_orders=7, owner_kind='business',
                  relevance_flag='one token', sqp_observed_days=7)
        plain = lanes.classify(c, bt, ctx())
        early = lanes.classify(c, bt, ctx(early_stage=self.EARLY, volatile=self.VOLATILE))
        self.assertEqual(early[:2], plain[:2])
        self.assertEqual(plain[0], 'auto')
        # a fallback-looking business record is judged as PR #5 left it too
        fb = term(index=None, index_status='product_market_fallback', index_basis='Search terms (business)', ad_clicks=6, ad_orders=3,
                  owner_kind='business')
        self.assertEqual(lanes.classify(c, fb, ctx(early_stage=self.EARLY))[:2], lanes.classify(c, fb, ctx())[:2])

    def test_classify_fallback_prove_first_goes_out_as_a_test(self):
        # decision 107 (2026-10-23): a fallback Prove first goes out as a small Prove-first test; a person approved it until then
        fallback = term(index=None, index_basis='Search terms vs product market', index_status='product_market_fallback',
                        fallback_index=2.39, ad_clicks=6, ad_orders=3, sqp_our_clicks=0, sqp_our_purchases=0, market_cvr=None)
        for c in (ctx(), self.room(), self.room(early_stage=self.EARLY), self.room(early_stage=self.EARLY, volatile=self.VOLATILE)):
            lane, reason, ev = lanes.classify(promotion(role='Prove first', sqp_observed_days=None), fallback, c)
            self.assertEqual(lane, 'auto')
            self.assertTrue(reason.startswith("Prove first on the search-term fallback (no SQP row yet): its ads convert 2.39x the "
                                              "product's market"), reason)
        self.assertIsNone(ev['opportunity'])   # index None: the fallback index never reaches the opportunity

    def test_classify_fallback_term_raise_is_held(self):
        # R34 (fix round 1, 2026-10-22): the fallback supports Prove first only, never a raise (data-stage design 4.4.2); the
        # suggested-range rule in _raise_lane needs no index, so without this a fallback term's live keyword would raise on its own
        fallback = term(index=None, index_basis='Search terms vs product market', index_status='product_market_fallback',
                        fallback_index=2.39, ad_clicks=6, ad_orders=3, sqp_our_clicks=0, sqp_our_purchases=0, market_cvr=None, be_cpc=1.73)
        raise_ = change(role='Prove first', current=2.0, new=2.5, change=0.25, breakeven=1.73, sug_low=2.0, sug_median=2.5, sug_high=3.0)
        for c in (ctx(), self.room(early_stage=self.EARLY), self.room(early_stage=self.EARLY, volatile=self.VOLATILE)):
            lane, reason, _ = lanes.classify(raise_, fallback, c)
            self.assertEqual(lane, 'monitor')   # decision 107: held, never a raise, never a person's call
            self.assertIn('its live keyword keeps its bid', reason)
        # the same raise on a same-query-indexed search lanes as before: inside Amazon's suggested range
        lane, reason, _ = lanes.classify(raise_, term(index=1.16, be_cpc=1.48), ctx())
        self.assertEqual(lane, 'auto')
        self.assertIn("inside Amazon's suggested range", reason)
        # a cut on the fallback term is judged as before (section 4: since 2026-10-22 a Prove first search's cut applies on
        # its own like any cut)
        cut = change(role='Prove first', current=2.0, new=1.5, change=-0.25)
        self.assertEqual(lanes.classify(cut, fallback, ctx())[:2], lanes.classify(cut, term(index=1.16), ctx())[:2])
        self.assertEqual(lanes.classify(cut, fallback, ctx())[1], 'cut from $2.00 to $1.50: a cut is never held back')
        # a business row never takes the check
        biz = change(role='Prove first', current=2.0, new=2.5, owner_kind='business', breakeven=1.73, sug_low=2.0, sug_median=2.5, sug_high=3.0)
        self.assertEqual(lanes.classify(biz, dict(fallback, owner_kind='business'), ctx())[0], 'auto')

    def test_classify_head_term_flag_is_always_human(self):
        for flag, words in (('one token', 'one-word search'), ('unlisted', "not in the product's niche list")):
            with self.subTest(flag=flag):
                for c in (self.room(), self.room(early_stage=self.EARLY), self.room(early_stage=self.EARLY, volatile=self.VOLATILE)):
                    lane, reason, _ = lanes.classify(promotion(relevance_flag=flag, sqp_observed_days=84), term(relevance_flag=flag), c)
                    self.assertEqual(lane, 'human')
                    self.assertIn(words, reason)
                # the flag on the term alone (a row the planner did not stamp) counts too
                self.assertEqual(lanes.classify(promotion(), term(relevance_flag=flag), self.room())[0], 'human')
                self.assertEqual(lanes.classify(policy_row(relevance_flag=flag), term(relevance_flag=flag), self.room())[0], 'human')
        # no flag: the ladder as today
        self.assertEqual(lanes.classify(promotion(relevance_flag=None), term(relevance_flag=None), self.room())[0], 'auto')


if __name__ == '__main__':
    unittest.main()
