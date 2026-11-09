# Findings & Decisions

## Requirements
- User wants to ask about an image during the current WhatsApp conversation, including a separate follow-up question. No long-term photo memory.
- Fix the diagnosed API-format bug without changing launchers, providers, credentials, inventory/order rules, or database schema.
- Current-chat default chosen by implementer: latest photo only, 10-minute inactivity expiry, bounded in-process memory; restart forgets it.

## Research Findings
- Current Agentrouter configuration uses `/v1/responses`; saved errors on 2026-11-08 are HTTP 400 and image-marked chats immediately receive the fallback reply.
- Offline replay of actual `run_agent`: Responses text passes, Responses image fails, Chat Completions image passes. Wrong types are `text` and `image_url`; Responses requires `input_text` and `input_image`, with a direct URL string.
- Chat history currently stores only `[image attached]`; separately sent questions cannot see earlier pixels.
- Installed Django is 6.1.2. Its LocMemCache is process-local and thread-safe, supports timeout/touch and MAX_ENTRIES, and can be instantiated as a dedicated named store.
- This directory is not a Git repository. Use explicit file backups and diffs; do not initialize Git or overwrite unrelated planning work.
- Final review reproduced concurrent replacement/read races because cache operations were individually thread-safe but not atomic as a group. Added a single lock around the bounded helper; no lock surrounds the external AI request.
- Final verification: image suite 17/17, existing smoke suite 142/142, WhatsApp lifecycle suite 8/8, Django system check clean. The overlap test failed before the lock and passed after it.
- Read-only post-fix verification matched the earlier provider/model/error-log snapshot and the two inspected image conversations. All 12 protected files remain byte-identical.
- New user screenshot after restart: a photo followed by “Aita ache?” gets one reply saying the earlier photo is unavailable to the assistant, then another reply mentioning a bag and human stock verification. This is not the previous generic HTTP-error fallback.
- Live backend on port 8000 is running `manage.py` from `D:\final nexora`; Node listens on 3001. A relative `node index.js` command does not itself prove its working folder, so do not infer a wrong folder from absence of that path in arguments.
- The bridge registers an async `messages.upsert` handler without per-chat serialization; prior tests only covered lifecycle and sequential Python image requests. Need an actual delayed-media event replay rather than assuming model capability.
- Deterministic bridge replay: delayed image download plus a separate text event produces webhook order `question -> photo` and replies `cannot see earlier photo -> can see current photo`. Expected order is `photo -> question`.
- Live saved conversation 370 at 14:05 contains the new `[image attached]` and bag reply, but neither the screenshot's “Aita ache?” nor its first cannot-see reply. This matches overlapping `run_agent` snapshots overwriting the conversation record.
- No new provider HTTP errors were logged after the prior request-format fix; the image itself reached the agent. Active catalogue includes a Structured Shoulder Bag, but its exact visual match is not proven merely by recognising a bag.
- Do not use metadata substring `ache` on `[image attached]`: it falsely flags the word `attached` as an availability question. Direct relevant transcript inspection corrected that diagnostic ambiguity.

## Bridge Follow-up Fix
- Reuse existing promise queue logic; optionally supply a per-session chat queue rather than global connection controls. A new session has a fresh inbox, so old queued work cannot block its replacement.
- Serialize download, webhook request, and reply for the same customer. Other customers and connect/remove/reset operations must remain independent.
- Check session identity/stopped state inside queued processing and again after a delayed download before forwarding. Tests must demonstrate no stale queued sends after removal.
- No new dependencies, no persistent photo archive, and no provider/credential/database changes.
- Independent review found two Important issues: awaiting inside the batch loop delays enqueueing later messages and can reorder them against a subsequent event; a stalled media download has no default timeout and can retain unlimited waiting messages.
- Verified installed Baileys: download options must be nested as `{options: AxiosRequestConfig}`; `downloadMediaMessage(..., "stream", ...)` exposes the decrypted stream. Axios supports `AbortController`, while the Baileys pipe does not forward source-stream errors to its decrypted output; destroy that output explicitly on abort.
- Review-fix defaults chosen by implementer: 30-second cancellable media deadline; 4 MiB decoded incoming-photo bound; at most 16 pending operations per customer and 32 per connected session. Overflow is not sent to Django and gets a wait/resend notice, at most once per customer per minute.
- Apply timeouts only to cancellable media reads, not to Django requests whose server-side saves could outlive a client timeout. Enqueue every eligible batch member synchronously before awaiting all settled operations.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Cache keyed by tenant ID and conversation ID | Prevent cross-shop/customer leaks and forget context when a conversation is recreated. |
| Cache only MIME and validated bounded base64 | Avoid retaining unrelated payload fields, malformed photo context, or unbounded memory. |
| 16 cache entries, 4 MiB base64 per image, 600-second timeout | Bounded temporary context for the current single-process local application. |
| Dedicated in-memory cache, irrespective of default cache settings | No possibility of silently saving customer images to a configured disk/database cache. |

## Threat Model
- Boundary: WhatsApp media enters the Django webhook and becomes an external AI image request.
- Assets: customer photos, tenant separation, existing records and API credentials.
- Controls: tenant/conversation-specific keys, latest-image replacement, expiry, size/count limits, no base64 in history/logs, isolated tests with live network and database writes disabled.
- Limitation: process-local cache is appropriate to current `runserver`; a future multi-worker deployment needs a separately approved shared ephemeral store.

## Review Scope Rulings
- Live provider visual interpretation/WhatsApp delivery was not tested: offline protocol/context correctness is verified, not a live image understanding claim. User should restart and resend a photo.
- Bridge download/delivery ordering before the webhook remains unchanged; no ordering metadata was added outside the narrowly scoped Python fix.
- Multi-worker cache sharing remains an explicitly documented deployment limitation, not part of this local single-process task.
- Pre-existing unrelated authentication/security behavior was not audited or changed; this is not a whole-application security approval.

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Prior logs omit provider response body | Do not claim a live provider validation message was captured; use the confirmed format defect and offline reproduction. |

## Session Recovery: 2026-11-09
- User resumed the stopped task in `D:\final nexora` to finish WhatsApp image processing.
- Selected the existing `2026-11-08-nexora-image-chat` plan explicitly because two named plans exist.
- Current Python agent already uses `input_text` / `input_image` for Responses; prior ledger ends immediately after implementing bridge batch/deadline/backpressure review fixes, before their verification.
- No Git history is available in this project. Existing source and previous changes must be preserved and reviewed against the saved backups.
- Current bridge review-fix code is present: synchronous whole-batch enqueue, separate per-customer queues, cancellable stream downloads, and bounded pending counts.
- First resumed Node run passed all 19 tests, including the seven regressions that were still unverified in the previous ledger.
- Located the existing bridge/source backups and protected-file hashes under `C:\Users\Sazzad Hossain\AppData\Local\Temp\opencode\nexora-image-chat-437a2c46d7734c18b41d47f44a07b27f`.
- Fresh Python checks: image suite 17/17, smoke suite 142/142, Django system check clean, bridge syntax valid.
- Reproduced an untested HTTP boundary failure with real RequestFactory/wa_webhook, DB access blocked: a 2 MiB photo becomes 2,796,317 bytes of JSON, exceeding Django's default 2,621,440-byte body cap before catalogue lookup.
- User supplied a new screenshot: photo identified as a red bag but successive replies escalate and then claim no exact catalogue match; user confirms the bag exists and reports much slower responses. Investigate actual catalogue matching and latency in addition to completing the prior task.
- Read-only catalogue inspection confirms active `Structured Shoulder Bag` in Zara Fashion, red SKU `ZF-BAG-RED-STD`, price 2190, stock 10. Catalogue description says gold clasp/chain, but downloading its actual public photo proves it is the same red bag/silver clasp shown in the user screenshot.
- Root matching gap: inventory tools give the AI text and an image URL only; catalogue-photo pixels are never passed as image inputs for comparison. The inaccurate prose can contradict the real photo.
- Read queries took 0.022 seconds and the catalogue-photo download 1.233 seconds. The saved provider uses `gpt-5.6-sol` with top-level `reasoning_effort: medium`. Official Responses API expects `reasoning: {effort: ...}`, not the Chat Completions top-level setting.
- User authorized a few isolated live AI requests for catalogue/latency diagnosis, using API credit but no WhatsApp sends, saved chat/stock changes, or credential changes.
- Latest saved provider error is an HTTP 403 at 13:11 on 2026-11-09; subsequent bag replies are not the generic HTTP-error fallback.
- Authorized live baseline reproduced the real failure: the AI fetched the correct bag SKU but rejected the visual match solely because the description says gold clasp/chain, then escalated. Three calls took 19.079 + 96.540 + 37.790 = 153.412 seconds.
- Provider response reported `reasoning.effort: max` both with the existing top-level medium setting and with the corrected nested medium setting; simply translating the setting does not solve this gateway/model latency.
- Candidate photo-comparison probe's second call failed with a remote connection reset. Do not infer a successful fix or a latency improvement from that incomplete probe; use a different model/call shape next rather than repeating it unchanged.
- Request-boundary tests: maximum 4 MiB decoded photo failed before the bounded 6 MiB Django setting; after the one-line setting change both acceptance and oversized-body rejection tests pass.
- Recovery backups for any new edits: `C:\Users\Sazzad Hossain\AppData\Local\Temp\opencode\nexora-image-finish-59ed5ce05cfb44de9eca11c6487721f2`.

## Resources
- https://raw.githubusercontent.com/openai/openai-python/main/src/openai/types/responses/response_input_image_param.py
- https://raw.githubusercontent.com/openai/openai-python/main/src/openai/types/responses/response_input_text_param.py
- https://docs.djangoproject.com/en/6.1/topics/cache/#local-memory-caching
- https://docs.djangoproject.com/en/6.1/topics/cache/#cache-arguments
- https://axios-http.com/docs/cancellation
- Installed Baileys `lib/Utils/messages-media.d.ts`, `messages.js`, `messages-media.js`, and Axios `lib/adapters/http.js` (nested options, cancellation and stream behavior).
- Installed `django/core/cache/backends/locmem.py` (implementation signatures/expiry behavior).
