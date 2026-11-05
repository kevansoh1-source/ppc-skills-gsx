import copy
import unittest

from dayparting import scheduled_pause
from test_visibility_integration import ASIN, TODAY, build, inputs, inventory


def scheduled_item():
    item = inventory()
    item['gates'].update(ad_group_enabled=False, schedule_open=False)
    item['dayparting'] = dict(asin=ASIN, campaign_id='456', ad_group_id='789',
        rule_id=21246, timezone='America/Los_Angeles', observed_at=TODAY+'T07:30:00+08:00',
        assignment_verified=True, resume_managed=True, manual_pause=False,
        pause_reason='scheduled_dayparting', assignment_source='exact ID SI readback',
        schedule_source='saved weekly rule grid', pause_source='verified SI status history',
        weekly_hours=[[6 <= h < 22 for h in range(24)] for _ in range(7)])
    # 07:30 SGT is 16:30 PDT on the prior day. Use 14:30 SGT = 23:30 PDT instead.
    item['dayparting']['observed_at'] = TODAY+'T14:30:00+08:00'
    return item


class DaypartingTests(unittest.TestCase):
    def assertNoLiveBid(self, result):
        # a held (paused) keyword is never written as a live bid; since decision 155 (2026-10-27) its price may go out as a
        # cut only, marked paused, and it stays paused
        for r in result['changes']:
            if r['type'] == 'Bid change':
                self.assertTrue(r.get('paused'), r)
                self.assertLess(r['new'], r['current'])

    def test_verified_off_period_keeps_real_gates_and_prices_bid(self):
        item = scheduled_item()
        before = copy.deepcopy(item)
        result = build(inputs(5), dict(asin=ASIN, inventory_complete=True, inventory=[item]))
        bids = [r for r in result['changes'] if r['type']=='Bid change' and r.get('keyword_id')=='123']
        self.assertTrue(bids)
        self.assertNotEqual(bids[0]['new'], item['current_bid'])
        self.assertEqual(item, before)
        self.assertEqual(result['visibility_review']['rows'][0]['status'], 'scheduled_off')

    def test_manual_unknown_wrong_id_and_during_on_hours_stay_held(self):
        for field, value in [('manual_pause',True),('pause_reason','unknown'),('pause_source',''),
                             ('ad_group_id','other'),('timezone','Asia/Singapore'),
                             ('observed_at',TODAY+'T07:30:00+08:00'),
                             ('observed_at','2026-10-10T14:30:00+08:00')]:
            with self.subTest(field=field,value=value):
                item=scheduled_item();item['dayparting'][field]=value
                self.assertIsNone(scheduled_pause(item,TODAY))
                result=build(inputs(5),dict(asin=ASIN,inventory_complete=True,inventory=[item]))
                self.assertNoLiveBid(result)

    def test_schedule_never_overrides_real_blockers(self):
        for gate in ['campaign_enabled','target_enabled','in_stock','ownership_clear','negatives_clear','ad_eligible']:
            with self.subTest(gate=gate):
                item=scheduled_item();item['gates'][gate]=False
                result=build(inputs(5),dict(asin=ASIN,inventory_complete=True,inventory=[item]))
                self.assertNoLiveBid(result)

    def test_parent_only_ad_delivery_reason_is_distinguished_from_moderation(self):
        item=scheduled_item();item.update(ad_state='ENABLED',ad_delivery_reasons=['AD_GROUP_PAUSED'])
        item['gates']['ad_eligible']=False
        result=build(inputs(5),dict(asin=ASIN,inventory_complete=True,inventory=[item]))
        self.assertTrue(any(r['type']=='Bid change' for r in result['changes']))
        item['ad_delivery_reasons'].append('PENDING_MODERATION_REVIEW')
        result=build(inputs(5),dict(asin=ASIN,inventory_complete=True,inventory=[item]))
        self.assertFalse(any(r['type']=='Bid change' for r in result['changes']))

    def test_scheduled_rank_owner_does_not_authorize_routing_or_new_visibility_test(self):
        item=scheduled_item()
        result=build(inputs(20),dict(asin=ASIN,inventory_complete=True,inventory=[item]))
        self.assertTrue(any(r['type']=='Bid change' for r in result['changes']))
        self.assertFalse(any(r['type'] in ('Negative exact','Pause keyword','New exact campaign','Reuse exact campaign','Budget and top of search') for r in result['changes']))
        self.assertIsNone(result['visibility_review']['rows'][0]['proposal'])

    def test_us_dst_and_closed_week_are_not_guessed(self):
        item=scheduled_item()
        self.assertIsNotNone(scheduled_pause(item,TODAY))
        item['dayparting']['weekly_hours']=[[False]*24 for _ in range(7)]
        self.assertIsNone(scheduled_pause(item,TODAY))
        item=scheduled_item();item['observed_on']='2026-11-02'
        item['dayparting']['observed_at']='2026-11-02T15:30:00+08:00'
        result=scheduled_pause(item,'2026-11-02')
        self.assertEqual(result['next_on_utc'],'2026-11-02T14:00:00+00:00')

    def test_incomplete_inventory_still_records_schedule_and_blocks_routing(self):
        item=scheduled_item()
        result=build(inputs(20),dict(asin=ASIN,inventory_complete=False,inventory=[item]))
        self.assertEqual(result['visibility_review']['rows'][0]['status'],'scheduled_off')
        self.assertTrue(any(r['type']=='Bid change' for r in result['changes']))
        self.assertFalse(any(r['type'] in ('Negative exact','Pause keyword','New exact campaign','Reuse exact campaign','Budget and top of search') for r in result['changes']))

    def test_incomplete_inventory_never_hides_known_blocker_during_scheduled_pause(self):
        item=scheduled_item();item['gates']['negatives_clear']=False
        result=build(inputs(5),dict(asin=ASIN,inventory_complete=False,inventory=[item]))
        self.assertEqual(result['visibility_review']['rows'][0]['status'],'blocked')
        self.assertFalse(any(r['type']=='Bid change' for r in result['changes']))


if __name__=='__main__':
    unittest.main()
