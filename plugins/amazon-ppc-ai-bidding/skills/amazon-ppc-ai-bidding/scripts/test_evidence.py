import unittest

import evidence

TOLERANCE = 0.015


class EvidenceTest(unittest.TestCase):
    def assert_near(self, actual, expected):
        self.assertLessEqual(abs(actual - expected), TOLERANCE, f'{actual} is not within {TOLERANCE} of {expected}')

    def test_p_beats_table(self):
        for orders, clicks, expected in [(3, 15, 0.78), (3, 23, 0.60), (5, 25, 0.88), (8, 40, 0.95),
                                         (13, 100, 0.80), (3, 21, 0.65), (3, 27, 0.51), (2, 14, 0.59)]:
            with self.subTest(orders=orders, clicks=clicks):
                self.assert_near(evidence.p_beats(orders, clicks, 0.10), expected)

    def test_p_below_table(self):
        for orders, clicks, expected in [(0, 30, 0.96), (0, 15, 0.86), (2, 40, 0.76)]:
            with self.subTest(orders=orders, clicks=clicks):
                self.assert_near(evidence.p_below(orders, clicks, 0.10), expected)

    def test_p_below_is_the_complement_of_p_beats_at_the_same_ratio(self):
        self.assertAlmostEqual(evidence.p_below(2, 40, 0.10, ratio=0.8) + evidence.p_beats(2, 40, 0.10, ratio=0.8), 1.0)

    def test_p_beats_with_no_clicks_rests_on_the_prior_alone(self):
        # With no clicks the posterior is just the prior (Beta(1, 9) at a 10% market), so confidence is modest
        # and a lower bar is easier to clear.
        self.assertTrue(0.3 < evidence.p_beats(0, 0, 0.10) < 0.7)
        self.assertGreater(evidence.p_beats(0, 0, 0.10, ratio=0.8), evidence.p_beats(0, 0, 0.10, ratio=1.0))

    def test_p_beats_caps_orders_at_clicks_and_rejects_impossible_input(self):
        self.assertEqual(evidence.p_beats(5, 3, 0.10), evidence.p_beats(3, 3, 0.10))
        for args in [(-1, 5, 0.10), (1, -5, 0.10), (1, 5, 0.0), (1, 5, 1.0)]:
            with self.subTest(args=args):
                self.assertRaises(ValueError, evidence.p_beats, *args)

    def test_p_beats_is_a_probability_and_moves_the_right_way(self):
        for orders, clicks in [(0, 1), (1, 1), (20, 20), (0, 500), (50, 500)]:
            self.assertTrue(0.0 <= evidence.p_beats(orders, clicks, 0.10) <= 1.0)
        self.assertGreater(evidence.p_beats(6, 30, 0.10), evidence.p_beats(3, 30, 0.10))
        self.assertGreater(evidence.p_beats(3, 30, 0.10), evidence.p_beats(3, 30, 0.20))
        self.assertGreater(evidence.p_beats(3, 30, 0.10, ratio=0.8), evidence.p_beats(3, 30, 0.10, ratio=1.2))

    def test_opportunity(self):
        self.assertEqual(evidence.opportunity(1.2, 840, 84), 360.0)
        self.assertIsNone(evidence.opportunity(None, 100, 84))
        self.assertIsNone(evidence.opportunity(1.0, None, 84))
        self.assertIsNone(evidence.opportunity(1.0, 100, None))
        self.assertIsNone(evidence.opportunity(1.0, 100, 0))
        self.assertIsNone(evidence.opportunity(0, 100, 84))
        self.assertIsNone(evidence.opportunity(1.0, -5, 84))
        self.assertIsNone(evidence.opportunity(float('nan'), 100, 84))
        self.assertIsNone(evidence.opportunity(1.0, float('inf'), 84))

    def test_monthly_searches(self):
        self.assertEqual(evidence.monthly_searches(840, 84), 300.0)
        self.assertEqual(evidence.monthly_searches(0, 84), 0.0)  # a search nobody made is zero, not missing
        for volume, days in [(None, 84), (100, None), (100, 0), (-5, 84), (float('nan'), 84), (100, float('inf')),
                             (True, 84)]:
            with self.subTest(volume=volume, days=days):
                self.assertIsNone(evidence.monthly_searches(volume, days))

    def test_opportunity_is_the_index_times_monthly_searches(self):
        self.assertEqual(evidence.opportunity(1.5, 840, 84), 1.5 * evidence.monthly_searches(840, 84))
        self.assertIsNone(evidence.opportunity(1.5, 0, 84))

    def test_sure_text(self):
        self.assertEqual(evidence.sure_text(0.654), 'about 65% sure it beats the market')

    def test_sure_text_names_the_claim_for_a_cut(self):
        self.assertEqual(evidence.sure_text(0.96, claim='converts under 0.8x the market'),
                         'about 96% sure it converts under 0.8x the market')


if __name__ == '__main__':
    unittest.main()
