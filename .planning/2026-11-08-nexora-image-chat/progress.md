# Progress Log

## Session: 2026-11-08

### Current Status
- **Phase:** 7 - Ordered WhatsApp Photo Conversations (tests first)
- **Started:** 2026-11-08

### Actions Taken
- Kept prior read-only diagnosis intact; user now requested implementation of current-conversation image reading.
- Inspected current source and identified only one production module needs changing.
- Created a separate named plan without overwriting the earlier reference-report plan.
- Verified installed Django version and official local-memory cache contracts.
- Defined temporary image bounds and recorded no-schema/no-dependency constraints.
- Saved original agent/README and untouched-file fingerprints in `C:\Users\Sazzad Hossain\AppData\Local\Temp\opencode\nexora-image-chat-437a2c46d7734c18b41d47f44a07b27f`.
- Added 16 offline regression tests through real `run_agent`, with network/database access blocked.
- Initial RED: 8 failures / 16 tests, reproducing both malformed Responses image requests and absent follow-up photo context.
- Applied only the provider-specific image-format correction as the first slice.
- First GREEN slice: all six focused request-format/text/tool-photo tests pass.
- Added bounded process-local latest-photo context; raw photos remain absent from saved conversation messages.
- Full image-suite GREEN: 16/16 tests pass after format and temporary-context fixes.
- Updated README with short-lived image behavior, bounds and the focused regression command.
- Ruling: Git-specific execution scripts/commits are unavailable because this is not a Git repository; use the named plan ledger and saved file backups/diffs instead, without initializing a repository.
- Existing offline smoke suite: 142/142 checks passed; Django system check reports no issues.
- Existing WhatsApp lifecycle suite: 8/8 tests passed using disposable sessions and fake sockets.
- Verified all 12 protected source/configuration/dependency files, including `.env` and all launchers, are unchanged.
- In-memory-only mutation test reversed the new size guard; the follow-up image regression failed as expected. No source edits were needed for the mutation.
- Generated a complete diff against backups and requested one independent read-only review. No live AI/WhatsApp calls made.
- Independent review found no critical issues but reproduced a race between delete/validate/set operations on overlapping photos and questions.
- Added a gated, overlapping-thread regression before implementing its fix.
- Ruling: serialize only the bounded photo-cache helper with one shared lock, not AI/network calls; a per-chat lock registry is unnecessary complexity for this small in-process store.
- Review-fix RED: the overlap test reproduced both the missing-context gap and older-photo overwrite before the lock was added.
- Applied a shared helper-only lock; reads, validation, replacement and expiry refresh are now one atomic operation relative to other chat-image requests.
- Review fix GREEN: all 17 image tests pass, including the overlapping photo/question regression. Final existing suites rerun after that fix: smoke 142/142, Node 8/8, Django check clean.
- Read-only verification confirmed earlier provider/model/error logs and both inspected image conversations were unchanged. Protected-file fingerprints again matched all 12 files.
- Final review important finding fixed via RED-to-GREEN regression; no critical/minor findings remained. No second review dispatch was needed.
- Final scope rulings: live provider/WhatsApp interpretation not exercised; upstream bridge ordering unchanged; process-local multi-worker limit documented; pre-existing unrelated auth/security not audited. Those do not change the isolated fix's verified protocol/context behavior.
- User reported the live follow-up still fails; reopened diagnosis without changing production code.
- Verified running backend uses the requested folder, not a stale Python copy; inspected current bridge event handler.
- Read-only live inspection: API config is unchanged and there are no new HTTP-error entries; the photo/bag reply is saved, but the separate question and first reply from the screenshot were overwritten.
- Exact offline real-bridge replay failed with webhook order `question -> photo` and the same cannot-see-then-image reply pattern. No files/services/records were changed by that replay.
- Found missing coverage in the earlier fix: Python tests did not simulate concurrent WhatsApp event callbacks and media download latency.
- Ruling: fix the remaining active image feature in the WhatsApp message dispatcher, reusing existing serialization logic. This necessarily expands production scope to the bridge but leaves settings, photo retention and stock rules untouched.
- Backed up the bridge/test/README and fingerprinted 13 files including the Python image fix and all configuration.
- Added four real-handler regressions for delayed downloads, webhook completion ordering, failure recovery, and removed/replaced sessions. RED: three new tests failed; all original lifecycle tests passed.
- Applied per-session/per-customer ordering through the existing serialization helper, with stop/identity checks before queued work and after media download.
- Expanded bridge suite GREEN: 12/12 tests pass, including the three previously failing cases. Node syntax check passes; all 17 Python image tests still pass unchanged.
- Documented per-chat ordering and the distinction between seeing an object and verifying its exact catalogue stock.
- Independent bridge review: no critical findings; two Important findings reproduce batched enqueue reorder/customer blocking and unbounded backlog behind a stalled media download.
- Verified the installed media API and cancellation path; options belong under `options`, and decrypted output must also be destroyed on abort.
- Ruling: bound pending work (16/customer, 32/session), abort incoming media at 30 seconds and cap it at 4 MiB, with explicit wait/resend or photo-retry notices. Do not abort/race a Django save to advance its queue.
- Review-fix RED: two batch tests failed and all five deadline/body-size/backpressure tests failed before their implementation.
- One fix pass: enqueue every batch member before awaiting settled work; add bounded pending counts with explicit overflow notices; collect/deadline/cancel the decrypted media stream and its underlying Axios request; stop aborts active downloads.

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| `python -B backend/test_agent_images.py` before fix | Format/context tests fail | 8 failures / 16 tests | RED confirmed |
| Six focused request-format/text/tool-photo tests after format patch | All pass | 6/6 pass | GREEN |
| Complete image suite after temporary-context patch | All pass | 16/16 pass | GREEN |
| Existing offline smoke suite | All pass | 142/142 pass | PASS |
| Django `manage.py check` | No issues | 0 issues, 0 silenced | PASS |
| Existing Node WhatsApp lifecycle suite | All pass | 8/8 pass | PASS |
| In-memory size-guard mutation | Follow-up regression catches it | 1 expected assertion failure, no errors | PASS |
| Protected file fingerprints | Unchanged | All 12 unchanged | PASS |
| Overlapping photo/question regression before review fix | Reproduce race | Two expected assertion failures | RED confirmed |
| Final image suite after concurrency fix | All pass | 17/17 pass | GREEN |
| Final existing smoke suite | All pass | 142/142 pass | PASS |
| Final existing Node suite | All pass | 8/8 pass | PASS |
| Final Django system check | No issues | 0 issues | PASS |
| Read-only runtime snapshot comparison | No changes to inspected state | Provider/model/errors and both image conversations unchanged | PASS |
| Delayed-media real bridge replay | Photo before follow-up | Question before photo; same reply pattern reproduced | RED confirmed |
| Expanded bridge tests before ordering fix | New ordering/cancellation tests fail | 3 failures / 12 tests; original tests pass | RED confirmed |
| Expanded bridge tests after ordering fix | All pass | 12/12 pass | GREEN |
| Node syntax check after ordering fix | Valid JavaScript | Exit 0 | PASS |
| Python image suite after bridge change | Unchanged regression behavior | 17/17 pass | PASS |

### Errors
| Error | Resolution |
|-------|------------|
| Requested smoke-test offset 1070 was out of range | Read its current tail from offset 990. |
| Eight expected image/context regression failures | Implement format first, then bounded temporary context; do not weaken tests. |

## Session: 2026-11-09
- Resumed from the selected image-chat planning files, without accessing previous session transcripts.
- Confirmed the format correction is present and the interrupted task is Phase 7 bridge review-fix verification.
- `git diff --stat` cannot run because the project is not a Git repository; use the existing backup/diff approach.
- Next action: validate the recovered plan, inspect current bridge/test code, and run the already-written regressions.
- Recovered plan validated successfully (7 phases).
- Reviewed the current agent, bridge, and focused test harnesses; Node/Python tests isolate network, WhatsApp sessions, and persisted data.
- Fresh Node result: 19/19 pass, zero failed/cancelled/skipped. This includes batch ordering, stalled transport/body cancellation, size limits, queue bounds, follow-up ordering and session lifecycle.
- Fresh Python results: image suite 17/17 and smoke 142/142; system check and Node syntax pass.
- New size-boundary repro confirmed RequestDataTooBig before DB/agent for a 2 MiB image.
- New user steering: screenshot demonstrates bag-recognition without a catalogue match and roughly minute-spaced replies; investigate catalogue lookup and latency before changing provider/model settings.
- Confirmed the actual catalogue photo exactly matches the user's screenshot, despite misleading catalogue description. No catalogue records were edited.
- Located the provider's incompatible reasoning option; official Responses schema uses nested `reasoning.effort`.
- Obtained explicit permission for a few isolated live provider probes. Catalogue photo downloaded to the recovery backup folder; all production data stays read-only.
- Added two RequestFactory regressions. RED: max bridge photo fails with RequestDataTooBig. GREEN: finite 6 MiB setting accepts it and still rejects oversized JSON.
- Live baseline exactly reproduced description-driven bag rejection and 153.412-second total latency; all responses returned maximum effort.
- Nested-medium candidate still returned max effort; second call ended in a remote connection reset. No production records changed and no WhatsApp messages sent.
