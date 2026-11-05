"""Evidence for automatic wrong-size positive-keyword pauses; no connector or write operations."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re

SGT = dt.timezone(dt.timedelta(hours=8))
SOURCE = 'MAP get_selling_partner_listings'
FILE = 'listing_size_verification.json'
MARKER = 'listing_size_verified_pause'
PAUSES = ('Pause keyword', 'SB pause keyword')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _unsupported_units(text):
    return re.search(r'(?:\d|\s)(?:cm|mm|centimet(?:er|re)s?|millimet(?:er|re)s?|feet|ft)\b', text, re.I)


def confirm(raw, review, cfg, own_sizes, parse, today, now=None):
    """Validate dated review against actual raw MAP title/bullets, including all alternate dimensions.

    Only explicit product-size claims qualify. Catalog/package dimensions, unanchored assertions, an incomplete
    review, unsupported units and conflicting listing/config sizes retain the hold. The returned proof authorizes
    no action by itself: the normal lane, ownership, human decision and apply/readback controls still run.
    """
    def fail(reason): return None, reason
    if not isinstance(review, dict) or not isinstance(raw, dict):
        return fail('Live listing size evidence is missing or malformed.')
    if raw.get('isError') is True:
        return fail('The raw listing read failed; it cannot confirm an automatic pause.')
    if (review.get('asin') != cfg.get('asin') or review.get('sku') != cfg.get('sku')
            or not cfg.get('sku') or review.get('marketplace') != 'US' or review.get('source') != SOURCE):
        return fail('Live listing evidence identity, US marketplace or source does not match this product.')
    if review.get('complete') is not True or review.get('ambiguous') is not False:
        return fail('Actual product dimensions have not been completely and unambiguously reviewed.')
    try:
        observed = dt.datetime.fromisoformat(review['observed_at'].replace('Z', '+00:00'))
        now = now or dt.datetime.now(dt.timezone.utc)
        if (observed.tzinfo is None or now.tzinfo is None or observed > now
                or now - observed > dt.timedelta(hours=24) or observed.astimezone(SGT).date().isoformat() != today):
            return fail('The live listing size read must be from this SGT day, within24hours and not in the future.')
        payload = json.loads(raw['content'][0]['text']) if 'content' in raw else raw
        items = payload['listings']
        matches = [r for r in items if r.get('asin') == cfg.get('asin') and r.get('sku') == cfg.get('sku')]
        if len(matches) != 1:
            return fail('The raw live listing does not uniquely identify this ASIN and SKU.')
        item = matches[0]; attrs = item.get('attributes') or {}
        if 'BUYABLE' not in (item.get('status') or []):
            return fail('Live listing buyability is not verified; keep its independent hold.')
        for field in ('item_name', 'bullet_point'):
            if any(v.get('marketplace_id') not in (None, 'ATVPDKIKX0DER') for v in attrs.get(field, [])):
                return fail('The raw size-bearing listing fields are from another marketplace.')
        title = item.get('title') or next((v['value'] for v in attrs.get('item_name', []) if v.get('value')), '')
        bullets = [v['value'] for v in attrs.get('bullet_point', [])]
        claims = review.get('claims')
        if not isinstance(claims, list) or not claims:
            return fail('Verbatim product-size claims from the live title/bullets are required.')
        actual = set()
        for claim in claims:
            field = claim['field']; quote = claim['quote']
            if field == 'title': text = title
            elif field == 'bullets' and type(claim.get('index')) is int and 0 <= claim['index'] < len(bullets):
                text = bullets[claim['index']]
            else: return fail('Size claims must point to the actual title or a numbered bullet.')
            if not isinstance(quote, str) or not quote or quote not in text or not parse(quote):
                return fail('A size claim is not a verbatim dimensional statement in the live listing.')
            if (not re.search(r'\d\s*(?:inches|inch|in)\b|["″]', quote, re.I) or _unsupported_units(text)
                    or re.search(r'\b(?:packag\w*|frame\w*|fits|compatible|not|maximum|up to)\b'
                                 r'|\benvelopes?\s+(?:size|dimensions?|measures?)\b', text, re.I)
                    or re.search(r'\d(?:\.\d+)?\s*[x×]\s*\d(?:\.\d+)?\s*[x×]', quote, re.I)):
                return fail('The size claim has ambiguous units, packaging/accessory context or three dimensions.')
            actual.update(parse(quote))
        seen = parse(' '.join([title] + bullets))
        allowed = set(own_sizes) | parse(' | '.join((cfg.get('relevance') or {}).get('protect') or []))
        if not own_sizes or not set(own_sizes) <= actual or not actual <= allowed or seen != actual:
            return fail('Live size claims conflict with configured product sizes or omit an alternate listing size.')
    except (KeyError, ValueError, TypeError, IndexError, AttributeError):
        return fail('Live listing size evidence is unreadable or incomplete.')
    return dict(asin=cfg['asin'], sku=cfg['sku'], observed_at=review['observed_at'], source=SOURCE,
                marketplace='US', sizes_inches=[list(s) for s in sorted(actual)], claims=claims,
                raw_listing_file=review.get('raw_listing_file'), snapshot_sha256=_digest(raw),
                review_sha256=_digest(review)), None


def read_confirmation(run, cfg, own_sizes, parse, today, now=None):
    """Load the review and its saved raw connector response from this run only; failure holds just size pauses."""
    try:
        root = Path(run).resolve(); review = json.loads((root / FILE).read_text(encoding='utf-8-sig'))
        name = review.get('raw_listing_file')
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            return None, 'The raw live listing must be a relative file inside this run.'
        source = (root / name).resolve()
        if not source.is_relative_to(root) or source == root / FILE:
            return None, 'The raw live listing must stay inside this run.'
        raw = json.loads(source.read_text(encoding='utf-8-sig'))
        return confirm(raw, review, cfg, own_sizes, parse, today, now)
    except (OSError, ValueError, TypeError, AttributeError):
        return None, 'No readable live listing size verification in this run.'


def pause_proof(row, allowed_sizes, proof, parse):
    """Only a wholly wrong-size, identified positive keyword relevance pause can use this evidence."""
    if (not proof or row.get('type') not in PAUSES or row.get('role') != 'Negate' or row.get('new') is not None
            or row.get('asin') != proof.get('asin') or not all(row.get(k) for k in ('campaign_id', 'ad_group_id', 'keyword_id'))):
        return None
    text = str(row.get('keyword') or ''); requested = parse(text)
    if not requested or requested & set(allowed_sizes) or _unsupported_units(text):
        return None
    return dict(proof, requested_sizes_inches=[list(s) for s in sorted(requested)])


def preapply_problem(rows, run, cfg, own_sizes, allowed_sizes, parse, today, now=None):
    """Revalidate marked planned pauses before execution; a saved marker never substitutes for fresh evidence."""
    marked = [r for r in rows if r.get(MARKER)]
    if not marked: return None
    proof, problem = read_confirmation(run, cfg, own_sizes, parse, today, now)
    if problem: return problem
    for row in marked:
        if pause_proof(row, allowed_sizes, proof, parse) != row[MARKER]:
            return f"Live size evidence changed or no longer supports {row.get('row_id')}; re-plan before applying."
    return None
