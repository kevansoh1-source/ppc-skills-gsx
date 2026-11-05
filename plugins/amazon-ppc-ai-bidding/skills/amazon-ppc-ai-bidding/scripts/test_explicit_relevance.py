"""A product owner's explicit format exclusion wins over generic roots and conversions."""
import os
import unittest
from unittest.mock import patch

import plan as planner
import test_plan_lanes as T


class ExplicitRelevanceTest(unittest.TestCase):
    def test_owner_exclusion_precedes_generic_protection_without_substring_overreach(self):
        check = planner.make_irrelevant(T.ASIN, {
            'protect': ['grocery', 'list', 'notepad'],
            'approved_phrase_exclusions': {'notebook': 'Kim: tear-off pad, not a notebook',
                                           'notebooks': 'Kim: no notebook keyword targeting'},
        })
        self.assertIn('Kim', check('grocery list notebook'))
        self.assertIn('Kim', check('grocery notebooks'))
        self.assertIsNone(check('grocery list notepad'))
        self.assertIsNone(check('notebookcase grocery list'))
        legacy = planner.make_irrelevant(T.ASIN, {'protect': ['grocery'], 'negate_phrase': {'notebook': 'legacy'}})
        self.assertIsNone(legacy('grocery notebook'))

    def test_converting_excluded_query_cannot_promote_harvest_or_blacklist_rescue(self):
        bad, good = 'grocery list notebook', 'grocery list notepad'
        cfg = T.product(sb_video={'video_asset_id': 'test-asset', 'campaigns': []},
                        relevance={'protect': ['grocery', 'list'],
                                  'approved_phrase_exclusions': {'notebook': 'Kim: wrong product format'}})
        inputs = ({t: T.query(t, 2000, 800, 80, 30, 6) for t in [bad, good]},
                  [T.search_term(t, T.STW, 20, 3, 12) for t in [bad, good]],
                  [T.keyword(str(i), t, 'exact', T.STW, .5, 20, 3, 12) for i, t in enumerate([bad, good])],
                  {t: [.5, .7, .9] for t in [bad, good]}, [T.campaign(T.STW)], {}, {}, '2026-10-12')
        sb = {'campaigns': {'300': {'campaignId': '300', 'name': 'Cards - Videos - Legacy', 'state': 'ENABLED'}},
              'keywords': [], 'cover': {}, 'pulled': True, 'read_ids': set(), 'perf': {}}
        with patch.object(planner, 'load_inputs', return_value=inputs), \
                patch.object(planner, 'load_sb', return_value=sb), \
                patch.object(planner.os.path, 'exists', side_effect=lambda p: os.path.basename(p) == 'si_blacklist.json'), \
                patch.object(planner, 'load_lane_inputs', return_value=T.FRESH_LANE_INPUTS), \
                patch.object(planner.blacklist_rescue, 'load_lists', return_value={'NegativePhraseList': ['notebook']}):
            out = planner.build(T.ASIN, cfg, T.shared_config(), 'unused-explicit-relevance-run', 'onboard', T.TODAY, T.NOW)
        self.assertEqual(next(t for t in out['terms'] if t['term'] == bad)['role'], 'Negate')
        self.assertNotIn(bad, [x['keyword'] for x in out['rerank']])
        self.assertFalse(any(x.get('keyword') == bad and x['type'] in
                             ('New exact campaign', 'Reuse exact campaign', 'New SB video campaign', 'Archive negative')
                             for x in out['changes']))
        self.assertEqual(out['harvest']['priced_searches'], 1)
        self.assertIn(good, [x['keyword'] for x in T.by_type(out, 'New exact campaign')])
        self.assertIn(good, [x['keyword'] for x in T.by_type(out, 'New SB video campaign')])


if __name__ == '__main__':
    unittest.main()
