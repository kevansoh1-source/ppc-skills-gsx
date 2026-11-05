"""Saved Claude/Codex response compatibility, 2026-10-23. No connector calls."""
import json
import os
import tempfile
import unittest

import plan


class LoadRaw(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'sqp_p1.json')

    def load(self, value):
        with open(self.path, 'w', encoding='utf-8') as fh:
            json.dump(value, fh)
        return plan.load_raw(self.path)

    def test_four_response_shapes(self):
        payload = {'Queries': [{'ASIN': 'B0TEST0001', 'Query': 'christian bookmarks', 'QueryVolume': 200}]}
        blocks = [{'type': 'text', 'text': json.dumps(payload)}]
        for value in (payload, blocks, {'content': blocks}, {'structuredContent': payload}):
            with self.subTest(value=value):
                self.assertEqual(self.load(value), payload)

    def test_structured_content_takes_precedence_even_when_empty(self):
        blocks = [{'type': 'text', 'text': '{"wrong": true}'}]
        for payload in ({}, [], False, 0):
            with self.subTest(payload=payload):
                self.assertEqual(self.load({'structuredContent': payload, 'content': blocks}), payload)

    def test_null_structured_content_falls_back_to_content(self):
        self.assertEqual(self.load({'structuredContent': None,
                                    'content': [{'type': 'text', 'text': '{"items": []}'}]}), {'items': []})

    def test_plain_json_values_stay_unchanged(self):
        for value in ({'items': []}, [{'text': 'no type field'}], [], 'plain text', 7, None):
            with self.subTest(value=value):
                self.assertEqual(self.load(value), value)

    def test_payload_with_its_own_content_list_is_not_an_envelope(self):
        # a report whose rows sit under 'content' is data, not an MCP envelope: only text blocks are unwrapped
        for value in ({'content': [{'ASIN': 'B0TEST0001', 'Query': 'bookmarks'}], 'total': 1},
                      {'content': ['a', 'b']}, {'content': []}):
            with self.subTest(value=value):
                self.assertEqual(self.load(value), value)

    def test_text_wrapper_keeps_first_block_behavior(self):
        self.assertEqual(self.load([{'type': 'text', 'text': '{"first": 1}'},
                                    {'type': 'text', 'text': '{"second": 2}'}]), {'first': 1})

    def test_non_json_text_is_returned_as_before(self):
        blocks = [{'type': 'text', 'text': 'report unavailable'}]
        self.assertEqual(self.load(blocks), 'report unavailable')
        self.assertEqual(self.load({'content': blocks}), 'report unavailable')

    def test_invalid_outer_json_still_raises(self):
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write('{truncated')
        with self.assertRaises(json.JSONDecodeError):
            plan.load_raw(self.path)


class LiveTargets(unittest.TestCase):
    """2026-11-04: MAP's sp_targets read can return a keyword in Amazon's unified format, under the keyword's own id."""

    def test_a_keyword_mirrored_into_the_targets_read_is_left_to_the_keyword_read(self):
        keywords = [dict(keywordId='11', keywordText='bible cards', matchType='EXACT', bid=0.5, state='ENABLED')]
        targets = [dict(targetId='11', bid=dict(bid=0.5, currencyCode='USD'), state='ENABLED'),
                   dict(keywordId='12', bid=dict(bid=0.4), state='ENABLED'),
                   dict(targetId='21', bid=dict(bid=0.35, currencyCode='USD'), state='ENABLED',
                        expression=[dict(type='ASIN_SAME_AS', value='B0TEST0001')]),
                   dict(targetId='22', bid=0.3, state='PAUSED')]
        live = plan.live_targets(targets, keywords)
        self.assertEqual([(t['targetId'], t['bid']) for t in live], [('21', 0.35), ('22', 0.3)])
        self.assertEqual(live[0]['bid_object'], dict(bid=0.35, currencyCode='USD'))


if __name__ == '__main__':
    unittest.main()
