"""Blacklist rescue (blacklist_rescue.py, and plan.py's Scale Insights setup row). The cases are the 2026-10-21 sweep's:
34 blacklist entries on 11 products blocked Invest or Prove-first searches."""
import json
import os
import tempfile
import unittest

import blacklist_rescue as br
import plan as planner
import test_plan_lanes as T


class RescueTest(unittest.TestCase):
    def test_exact_variants_of_an_invested_search_come_off(self):
        lists = dict(NegativeExactList=['magnetic bookmark', 'magnetic book marks', 'magnetic bookmarkers', 'magnetic bookmarks',
                                        'christian book mark', 'bookmark holder'],
                     NegativePhraseList=['holder'], ExactWhiteList=['magnetic bookmarks'])
        r = br.rescue(['magnetic bookmarks', 'christian bookmarks'], lists)
        self.assertEqual(r['exact_remove'], ['magnetic bookmark', 'magnetic book marks', 'magnetic bookmarkers', 'magnetic bookmarks',
                                             'christian book mark'])
        self.assertEqual(r['phrase_remove'], [])
        self.assertEqual(r['whitelist_add'], ['christian bookmarks'])
        self.assertEqual(r['blocks']['magnetic book marks'], ['magnetic bookmarks'])

    def test_a_phrase_whose_words_are_in_the_search_comes_off(self):
        lists = dict(NegativeExactList=['turkey'], NegativePhraseList=['turkey', 'mini', 'turkey baster', 'journal', 'sticker book'],
                     ExactWhiteList=[])
        r = br.rescue(['turkey stickers', 'mini scripture cards', 'junk journal stickers'], lists)
        self.assertEqual(r['phrase_remove'], ['turkey', 'mini', 'journal'])
        self.assertEqual(r['exact_remove'], [])  # an exact "turkey" only blocks the search "turkey"
        self.assertEqual(r['blocks']['mini'], ['mini scripture cards'])

    def test_kept_searches_stay_blacklisted(self):
        lists = dict(NegativeExactList=['yourbrand', 'cute notebook'], NegativePhraseList=['yourbrand'], ExactWhiteList=[])
        r = br.rescue(['yourbrand', 'cute notebooks'], lists, keep=['YourBrand'])
        self.assertEqual((r['exact_remove'], r['phrase_remove'], r['whitelist_add']), (['cute notebook'], [], ['cute notebooks']))

    def test_whitelist_text_drops_characters_scale_insights_refuses(self):
        self.assertEqual(br.whitelist_text('home finance bill organizer w/ pockets monthly budget planner'),
                         'home finance bill organizer w pockets monthly budget planner')
        lists = dict(NegativeExactList=[], NegativePhraseList=[],
                     ExactWhiteList=['home finance bill organizer w pockets monthly budget planner'])
        self.assertEqual(br.rescue(['home finance bill organizer w/ pockets monthly budget planner'], lists)['whitelist_add'], [])

    def test_whitelist_text_keeps_accented_letters(self):
        # B0SAMP0027, 2026-10-26: the a-z-only version proposed "tarjetas de cumplea os"; Scale Insights saves the "ñ"
        self.assertEqual(br.whitelist_text('Tarjetas de Cumpleaños'), 'tarjetas de cumpleaños')
        self.assertEqual(br.whitelist_text('w/ pockets'), 'w pockets')
        self.assertEqual(br.whitelist_text('cumplean\u0303os'), 'cumpleaños')  # a decomposed "ñ" is the same letter
        self.assertEqual(br.whitelist_text('español'), 'español')
        self.assertNotEqual(br.whitelist_text('español'), br.whitelist_text('espanol'))
        lists = dict(NegativeExactList=[], NegativePhraseList=[], ExactWhiteList=['tarjetas de cumpleaños', 'espanol'])
        self.assertEqual(br.rescue(['tarjetas de cumpleaños', 'español'], lists)['whitelist_add'], ['español'])

    def test_lists_read_from_textarea_text_or_lists(self):
        self.assertEqual(br.lines('a\r\n\nb \n'), ['a', 'b '])
        self.assertEqual(br.lines(['a', '', 'b']), ['a', 'b'])

    def test_new_lists_and_the_clean_case(self):
        lists = dict(NegativeExactList=['bible bookmarks', 'bookmark holder'], NegativePhraseList=['holder'], ExactWhiteList=['x'],
                     PhraseWhiteList=['y'])
        r = br.rescue(['bible bookmark'], lists)
        self.assertEqual(br.new_lists(lists, r), dict(NegativeExactList=['bookmark holder'], NegativePhraseList=['holder'],
                                                      ExactWhiteList=['x', 'bible bookmark'], PhraseWhiteList=['y']))
        clean = br.rescue(['bible bookmark'], br.new_lists(lists, r))
        self.assertIsNone(br.plan_row('B0TEST0001', clean))

    def test_invested_searches_are_the_invest_log_and_this_runs_rank_terms(self):
        cfg = dict(invest_log={'A': {'role': 'Invest'}, 'b': {'role': 'Prove first'}, 'c': {'role': 'Hold'}})
        self.assertEqual(br.invested_searches(cfg, ['d']), ['a', 'b', 'd'])

    def test_business_invest_searches_are_rescued_too(self):
        self.assertIn('zebra cards', br.invested_searches({}, (), business_log={'zebra cards': {'role': 'Invest'}}))
        # the business log's Invest / Prove first rows and this run's business rank searches, beside the consumer ones
        cfg = dict(invest_log={'a': {'role': 'Invest'}})
        log = {'B': {'role': 'Prove first'}, 'c': {'role': 'Hold'}, 'a': {'role': 'Invest'}}
        self.assertEqual(br.invested_searches(cfg, ['d'], business_log=log, business_rank_terms=['E ']), ['a', 'b', 'd', 'e'])


class PlannerRescueRowTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = os.path.join(tmp.name, 'run')

    def plan(self, lists=None, cfg=None):
        extra = {'si_blacklist.json': dict(lists, _read='test')} if lists is not None else None
        T.make_run(self.run_dir, extra=extra)
        return planner.build(T.ASIN, cfg or T.product(), T.shared_config(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)

    def test_a_blocked_rank_search_gets_a_rescue_row_that_applies_on_its_own(self):
        # 'blank cards' is this run's rank search, 'thank you cards' is in the invest log. The rescue is the standard Scale
        # Insights setup of an AI product: since autonomous runs (2026-10-22, decision 98) it applies on its own
        cfg = T.product(invest_log={'thank you cards': {'since': '2026-10-01', 'role': 'Invest'}})
        out = self.plan(dict(NegativeExactList=['blank card', 'thank you card', 'other'], NegativePhraseList=['blank'],
                             ExactWhiteList=['blank cards']), cfg)
        row = T.one(out, 'Scale Insights setup', step=95)
        self.assertEqual((row['exact_remove'], row['phrase_remove'], row['whitelist_add']),
                         (['blank card', 'thank you card'], ['blank'], ['thank you cards']))
        self.assertEqual((row['lane'], row['row_id']), ('auto', 'Scale Insights setup:::blacklist rescue'))
        self.assertEqual(out['summary'][0]['blacklist_rescue'], dict(checked=True, exact_remove=2, phrase_remove=1, whitelist_add=1))

    def test_clean_lists_add_no_row_and_no_file_says_so(self):
        out = self.plan(dict(NegativeExactList=['other'], NegativePhraseList=[], ExactWhiteList=['blank cards', 'thank you cards']))
        self.assertEqual([x for x in out['changes'] if x.get('step') == 95], [])
        self.assertEqual(out['summary'][0]['blacklist_rescue']['checked'], True)
        os.remove(os.path.join(self.run_dir, 'si_blacklist.json'))
        missing = self.plan(None)
        self.assertEqual(missing['summary'][0]['blacklist_rescue']['checked'], False)


if __name__ == '__main__':
    unittest.main()
