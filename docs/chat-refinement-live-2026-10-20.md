# Chat refinement round - October 20, 2026 (America/Chicago)

Live browser checks against the existing application. No customer field values are copied into this report.

| Question | Result | Verification |
| --- | --- | --- |
| What information could you not find in my documents? | Pass | Returned missing saved extraction fields and document links without model timeout. Explained that missing extraction does not establish absence from the original document. |
| Which documents show different names or addresses? | Pass | Included names and full address components from all four attached documents, with page references. |
| What is the difference between the pay rate and gross pay on my pay slip? | Pass | Exact difference plus explanation that it does not establish overtime, extra hours or adjustments. |
| What address is printed on that same document? | Pass | After license focus, returned that document's address without comparison boilerplate. |

A stale browser conversation reference initially produced Conversation not found. Added frontend recovery for an unavailable saved conversation during loading. Fresh-session live tests then passed.

Automated verification: five new regression tests cover routing, combined comparison, blank corrections, explicit zero, schema-less documents and pay-difference limits. Backend discovery: 159 tests, 95 passed, 64 skipped (database-dependent checks were not enabled in this round). Code standards included. The earlier isolated database suite was not rerun here.

Scope: these checks validate routing and saved-field behavior, not the accuracy of the original document extraction or general LLM reasoning. Missing-field reporting uses configured extraction schemas; it cannot enumerate every fact an unfamiliar document might contain. End-to-end unread notification, conversation deletion and broader mobile checks remain separate validation items.
