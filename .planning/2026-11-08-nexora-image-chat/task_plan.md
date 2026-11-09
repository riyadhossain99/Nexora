# WhatsApp Image Conversation Implementation Plan

> **For agentic workers:** Use executing-plans and implement in this session; no delegated work is needed.

**Goal:** Let customers ask about the latest image in their active WhatsApp chat without permanent photo storage.
**Architecture:** Correct provider-specific image content in the existing Python agent. Use a dedicated, thread-safe process-local Django cache for the latest image per tenant/conversation, expiring after 600 seconds of inactivity. Keep image bytes out of saved chat messages.
**Tech Stack:** Python 3.14, installed Django 6.1.2, Requests, standard-library unittest.
**Spec:** Requirements and bounded-context decisions in `findings.md`.

## Global Constraints
- No new dependencies, database migrations, launcher changes, or changes to business settings/WhatsApp credentials. A bounded Django request-size adjustment is allowed for the reproduced photo/base64 boundary failure.
- Retain at most one image per chat; replace on a new photo, expire after 600 seconds of inactivity, clear on process restart.
- Dedicated cache: at most 16 chats; at most 4 MiB of base64 per cached image. Larger current images may still be processed but are not retained.
- Partition context by tenant and conversation identifiers; never persist incoming base64 in chat history or logs.
- All automated AI requests and model writes are isolated/faked; no real API calls or production database writes.

## Review Focus
- Text-only and Chat Completions requests retain their existing formats.
- Image followed by a separate question includes the latest photo, but not any superseded photo.
- Tenant/chat isolation, expired context, and a recreated conversation cannot reuse another chat's photo.
- Oversized/invalid cache inputs cannot retain unbounded data or revive an older photo.
- Tool-call continuation and outgoing catalogue-photo collection work with image inputs.

## Goal
Fix the Responses image request and support short-lived current-chat photo questions safely.

## Next Step
Inspect the actual bag catalogue entry, saved matching replies, and provider configuration read-only; reproduce the catalogue and latency causes before fixing.

## Current Phase
Phase 7

## Phases

### Phase 1: Requirements & Discovery
- [x] Understand user intent
- [x] Identify constraints
- [x] Document in findings.md
- **Status:** complete

### Phase 2: Planning & Structure
- [x] Define approach
- [x] Keep existing module structure
- **Status:** complete

### Phase 3: Implementation
- [x] Write `backend/test_agent_images.py` using the real `run_agent(...)` with isolated model/session fakes; run it and confirm request-shape and follow-up failures.
- [x] Correct only the Responses image branch in `backend/core/agent.py`; preserve Chat Completions and rerun focused format tests.
- [x] Add `_chat_image(tenant, conv, image)` in that same module using bounded local memory; run the complete image suite.
- [x] Document temporary context and the focused test command in `README.md`.
- **Status:** complete

### Phase 4: Testing & Verification
- [x] Run focused image tests, existing offline smoke checks, Django system check, and Node lifecycle tests.
- [x] Verify live configuration/records and untouched files are unchanged; inspect the complete diff against backups.
- [x] Document test results and live-service verification limits.
- **Status:** complete

### Phase 5: Delivery
- [x] Review outputs and address the independently reproduced replacement race.
- [x] Prepare verified result, restart/resend instructions, and live-service limitations for the user.
- **Status:** complete

### Phase 6: Live Photo Follow-up Diagnosis
- [x] Read the new screenshot and verify which backend is running.
- [x] Read the relevant saved chat sequence/configuration without exposing private data.
- [x] Reproduce the exact photo-then-question symptom through the real WhatsApp event handler with fake media/network.
- [x] Distinguish download/order/context failures from visual inventory-match limitations before changing product code.
- **Status:** complete

### Phase 7: Ordered WhatsApp Photo Conversations
- [x] Back up `backend/whatsapp/index.js`, `backend/whatsapp/test.js`, and the current README.
- [x] Extend the existing fake bridge tests with delayed media, parallel customers, failed earlier requests, and cancelled queued work; confirm ordering failure first.
- [x] Reuse the bridge's existing promise-serialization helper with a per-session/per-chat queue; keep session controls independent.
- [x] Recheck stopped/replaced sessions before queued work and before forwarding downloaded photos.
- [ ] Run all Node/Python checks; obtain one read-only review of this bridge change; preserve business settings, credentials, schemas, Python photo context and launchers.
- [ ] Address review findings: enqueue complete batches before awaiting; bound queued work; cancel stalled media reads without racing Django saves.
- [x] Explain that image recognition and exact catalogue/SKU verification are different capabilities; do not force invented availability.
- **Status:** in_progress

### Phase 8: Catalogue Photo Matching and Response Latency
- [ ] Inspect catalogue/chat/provider evidence without changing records or credentials.
- [ ] Add regressions for the reproduced photo request-size, matching, and latency issues.
- [ ] Apply the smallest verified fixes without inventing stock or weakening ordering/isolation.
- [ ] Run the complete offline suites and record live-service verification limits.
- **Status:** in_progress

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Implement directly in the existing agent | User asked to proceed with current-conversation image reading; avoid another requirements interview and a rewrite. |
| Process-local context, not saved image history | Meets temporary image use without new durable personal-data storage or database schema changes. |
| Use the existing Django cache implementation | Thread safety, timeout and capacity bounds without another dependency. |
| Backups/diffs instead of Git execution helpers | No Git repository exists; avoid initializing or altering version control beyond the request. |
| Lock the bounded helper only | Prevent overlapping photo replacement/read races without serializing slow AI requests. |
| Live vision/WhatsApp verification left to the user | No external AI calls or production chat writes were authorized in the offline verification plan. |

## Errors Encountered
| Error | Resolution |
|-------|------------|
| Smoke-test read at offset 1070 exceeded its current 1060 lines | Read the current tail at offset 990; do not assume old file lengths. |
| Initial 8/16 image regressions failed | Corrected request format and added bounded context; full suite passed. |
| Review overlap regression exposed two cache races | Added helper-wide shared lock; overlap regression and full suites passed. |
| Live photo/follow-up still failed despite Python tests | Offline actual-bridge replay forwards question before photo; fix per-chat dispatch, not model/provider settings. |
| Bridge review found batched-message reorder and stalled-download backlog | Add deterministic coverage and a single fix pass: synchronous enqueue, cancellable media deadline and bounded admission. |
| Session recovery found multiple named plans | Explicitly selected `2026-11-08-nexora-image-chat`; use its paths for this resumed task. |
| `git diff --stat` unavailable on recovery | Confirmed this directory has no Git repository; retain existing backups and compare files directly. |
| 2 MiB photo fails before reaching agent | Its 2,796,317-byte JSON exceeds Django's 2,621,440-byte default body cap; add bounded support for the bridge's existing photo limit. |
| Live candidate probe hit provider connection reset | Baseline completed and proves the description mismatch/max-effort delay; candidate result is unverified, so inspect faster supported models and do not retry blindly. |
