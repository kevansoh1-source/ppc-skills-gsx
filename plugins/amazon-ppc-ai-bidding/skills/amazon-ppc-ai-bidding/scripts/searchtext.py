"""How the bid planner writes a search or keyword: one normal form, so the same search matches across reports.

Shared by plan.py and plan_lanes.py (plan.py re-exports it, so `from plan import norm` keeps working).
"""
import re


def norm(t):
    t = (t or '').lower().replace('+', ' ')
    t = re.sub(r'[^a-z0-9áéíóúñ. /-]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()
