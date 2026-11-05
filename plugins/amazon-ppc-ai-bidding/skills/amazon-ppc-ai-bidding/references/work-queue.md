# Follow-up ownership — 2026-10-19 SGT

Kim requested one Needs Human destination. **Published Oct 19 at 16:24 SGT:** this page now shows only human decisions; the AI work, scheduled and history tabs were removed at his request. Operational records remain under each ASIN's Context & audit → Follow-ups & history. Internal ownership lanes still exist; hiding their tabs does not delete, execute or complete the work. Source records remain authoritative; routing is not an execution receipt.

At each one-ASIN sweep:

1. Read current approvals, execution receipts and open items before asking again. A confirmed approval becomes AI preflight/execution work, not another general approval request.
2. Do the research that the agent can do: keyword relevance, market opportunity, comparable offers, live configuration, asset availability and economics. Do not make a human investigate an unresearched conversion or price flag.
3. For harvest/SB, reconcile the actual import gate, profit, bids, budget, strategy and video asset. The LLM can prepare and execute these, but unsupported thresholds and unpreviewed financial settings still require their concrete preview and approval. General delegation is not a new bidding policy.
4. Publish a human item only when it has a specific question, options or proposed action, evidence, owner, and an explanation of why AI cannot finish without that input. Physical-product conflicts and new schedule/price decisions are examples. Do not invent a blocker or approver.
5. Routine delivery checks, audits and approved execution keep the internal `ai` lane. Future-dated reviews keep `scheduled`. These are retained operational records, not entries in the human decision inbox. Sam done only after verification. Retain superseded notes in `history` with the newer evidence and the separate unfinished tasks.

## Optional structured routing

`open_items[]` and `human_review[]` may carry a `workflow` object. Current `dashboard.py` preserves these records. The shared queue accepts it only when `run_id` matches the current run and `source_text` matches the source record exactly. This prevents old approval/routing metadata from attaching to a changed task.

- `lane`: `human`, `ai`, `scheduled`, or `history`.
- `action`: concise concrete next action; required.
- `why`: why the task is in this lane and the real blocker.
- `owner`, `date` (SGT), optional `due`.
- `approval`: reference the person, date and exact approved scope. A string here does not itself authorize execution.
- `proof`: source path/receipt; required to supersede into history.
- `run_id`: current dashboard `run.id`.
- `source_text`: for open items, their exact `text`; for human reviews, `title + '\n' + reason + '\n' + action`.

Existing `done`, `resolved` and `dismissed` source statuses take precedence and remain history. `ai_review.phase = human_ready` takes precedence for a completed AI assessment. New/unclassified open items remain visible for triage; missing research on listing/price reviews stays in AI work. Do not mark work complete merely to lower the badge count.

The Oct 19 migration uses reviewed `dashboard/work-queue-triage.json` overlays scoped to ASIN/run/original text. Execution-only additions also match the saved execution state. Do not reuse or silently regenerate this dated migration for future sweeps; use the structured field above.

UI contract and publication boundaries: `docs/dashboard-ui.md` in the repository. No queue control approves or applies live changes. No automatic background worker is implied.
