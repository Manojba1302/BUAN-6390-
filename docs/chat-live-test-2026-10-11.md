# Live chat evaluation — 2026-10-11

Executed against the running backend services, existing application documents and configured llama3.1:8b. No model mocks; customer records were not edited. This is a service-level live test, not browser interaction or an authentication/history UI test. Sensitive identifiers are omitted.

| Question | Seconds | Result |
|---|---:|---|
| How many documents have I uploaded? | 0.01 | Pass: four attached completed documents. |
| When does the driving license expire? | 0.02 | Returned saved expiry with license source and holder; independent image verification remains. |
| What job title, pay rate, and pay frequency are printed on my pay slip? | 0.01 | Pass against supplied payroll image: Student Assistant, [financial value omitted], semimonthly. |
| Compare the employer information on my W-2 and pay slip. | 0.01 | Pass: both UTD employer values, two sources, capitalization distinction; no ownership inference. |
| Why is my gross pay different from my printed pay rate? | <0.01 | Pass: distinguishes rate [financial value omitted] from period gross [financial value omitted]; does not invent cause. |
| Compare addresses across my documents. | <0.01 | Pass for conflict handling: four separate sources, differing apartments/ZIPs, no automatic current-address choice. Extraction accuracy still needs original-page review. |
| What is my next paycheck amount? | <0.01 | Pass: refuses unsupported future prediction. |
| Summarize my pay slip, separating regular pay, overtime, deductions, and net pay. | <0.01 | Fail: direct-field routing returned only net and regular pay, omitting other requested categories. |
| Summarize my bank statement. | 122.49 | Fail: actual model request exceeded the 120-second generation timeout. |

## Fix
Summary/overview requests now bypass the partial direct-field lookup and go through general document retrieval and generation. Added a regression check for summaries containing field names. Backend checks: 22 run, 18 passed and 4 database-dependent tests skipped.

## Remaining validation
- Broad model generation is not established as reliable; a longer timeout alone did not fix bank summaries.
- Corrected pay-slip summary was retested: failed after 61.97 seconds with the generic model-unavailable/timeout error. This does not establish a timeout specifically; invalid model JSON is also translated to that error. Broad summary generation remains unresolved. An earlier retry was interrupted by backend restart and excluded.
- Independently verify every extracted value against original pages.
- Browser stop/loading behavior, saved conversations, follow-ups, saved correction changes and unfamiliar uploads still need live testing.
- Fast-path success is not proof of broad LLM accuracy.


## Model-failure diagnosis and follow-up

- Raw payroll generation diagnostic: 5,587 prompt characters; 1,611 evaluated prompt tokens; 320 generated tokens in 63.36 seconds (about 5 tokens/second). Total 65.80 seconds. This particular response was valid JSON with accepted source support, so failures are intermittent; the 320-token ceiling was fully consumed but truncation was not proven in this sample.
- Found a separate evidence bug: page deduplication dropped distinct retrieved chunks from the same page. Payroll has two stored chunks (1,200 and 408 characters). Now distinct retrieved text on a shared page is combined and repeated identical chunks are omitted. This preserves retrieved chunks; it does not guarantee retrieval includes every chunk.
- Increased chat output allowance to 512 tokens and capped support quotes at 160 characters. Invalid model JSON now has a different user message from transport/timeouts. Classification/extraction settings are unchanged.
- Retest payroll: completed in 99.45 seconds with one citation. Regular/gross [financial value omitted], federal withholding [financial value omitted] and net [financial value omitted] matched stored text. However it claimed no overtime without explicit zero evidence: **accuracy failure**, not an overall pass.
- Added an explicit rule that absent earnings categories are unknown rather than zero. This rule has a prompt regression check; live effectiveness has not yet been established.
- Retest bank: still timed out at 120.37 seconds. **Unresolved performance failure.**
- Quote presence and valid citations do not prove every semantic claim. Do not mark broad chat production-ready based on these tests.


## Reported employer typo
Confirmed the persisted question `who is my employeer` failed with a model transport/timeout error; direct intent previously returned None. Added conservative employer typo/phrase aliases. Live database verification with model calls forbidden returned the correct UTD values and two citations: typo 0.024 seconds, `who do I work for` 0.004 seconds, `where do I work` 0.004 seconds. These were service-level checks, not browser clicks. Targeted checks: 25 run, 21 passed, four isolated-database checks skipped. Broad summary limitations above remain.


## Reliable saved-field summary path
Added a complete saved-field summary path for explicitly requested pay slips and bank statements. This is an optimization, not a fix for general LLM generation. The exact payroll request now returned in 0.014 seconds with one source; the bank summary returned in 0.011 seconds with one source. Verified against actual application records with model calls forbidden. Missing regular pay, overtime and bonus values remain explicitly unknown; itemized deductions are not in the saved schema and are not invented. No customer extractions were changed. Unfamiliar document summaries and broad cross-document reasoning remain on the general pipeline. Sixteen focused regression checks passed. Original-page category extraction remains separate work.


## Payroll refinements and persistence regression round
Optional payroll fields now include explicitly printed current-period total deductions and federal withholding. No database columns/migrations were added. Deterministic recovery supports unambiguous single-amount labelled rows for regular earnings, overtime, bonuses and these deduction fields. Explicit zero is retained; YTD rows, ambiguous multi-amount rows and conflicting values remain unknown. Existing fields, including saved blanks, are preserved. Saved-field summaries now include these deduction fields and explain that the breakdown is incomplete.

Validation: 33 worker tests passed; 67 backend tests passed on a fresh isolated PostgreSQL database, including conversation persistence, follow-up clarification, source changes, ownership and correction priority. Disposable database removed. Backend and worker restarted. No customer uploads were reprocessed or corrected, and no Git push occurred. Real multi-column payroll layout extraction, browser interaction/mobile checks and general model generation remain outstanding.


## Original PDF and browser validation
Original payroll PDF coordinate inspection confirmed distinct Current/YTD columns and separate Hours/Earnings subheadings. Added conservative aligned recovery for supported labelled rows. Recovered and saved only missing regular_pay [financial value omitted] and federal_withholding [financial value omitted] on page 1; existing corrections were preserved. No overtime zero or total deductions were inferred. Regression tests include a synthetic multi-column PDF with hours and different YTD amounts.

In the authenticated in-app browser, submitted the exact payroll summary and visibly verified both recovered values, missing overtime/bonus and source reference. Closed and reopened chat; the new answer remained. Historical answers showed changed-source warnings after extraction updates. Inspected the chat at 390x844: header controls, scrolling content, source card and composer were visible; reset the viewport afterward. This is a chat-layout check, not complete application/mobile certification.

Browser history revealed deposits/withdrawals without the word total were omitted from a multi-field bank question. Fixed both aliases and added a completeness regression check. Latest worker suite: 35 tests passed; updated payroll subset: 10 passed. Backend targeted checks: 25 passed, four isolated-DB checks skipped (previous full isolated 67-test run passed before these changes). General model speed/accuracy is still unresolved and has not been represented as fixed by deterministic summaries.


## Final pre-publication checks
Full backend suite: 126 tests run, 125 passed, one skipped. Worker suite: 35 passed. Frontend production build passed. Git whitespace checks passed. Actual payroll values are omitted from this published evaluation report.
