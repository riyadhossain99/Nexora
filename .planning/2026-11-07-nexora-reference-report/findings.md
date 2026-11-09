# Findings & Decisions

## Requirements
- Explain every project-owned source/configuration/migration/template/static asset and folder: purpose, reason, behavior, dependencies and downstream integration.
- Include data schemas, wire contracts, lifecycle diagrams, frontend design details, setup sequence, failure behavior, test catalog and an implementation blueprint.
- Keep credentials, token strings, customer records, private session data and machine-specific environment contents out of the deliverable.

## Research Findings
- Runtime: Django/PyMySQL to XAMPP MySQL database nexora_app; Node/Baileys bridge on loopback 3001; Django serves server-rendered HTML, vanilla JavaScript/CSS and static/media paths on 8000.
- Six core business modules, seven sequential migrations, five HTML templates, app.js/charts.js/style.css/favicon and three font binaries with OFL license.
- Orders: PENDING -> ACCEPTED -> SHIPPED -> COMPLETED, with cancellation only from pending/accepted; conditional transition claim and after-commit WhatsApp notification.
- Products store SKU arrays in JSON; conversation/order/settings/usage/shipment fields are JSON. Photos are files with database URLs; reference-aware cleanup is deferred to commits.
- WhatsApp status/send do not create connections. Explicit connect/reset/remove controls are serialized per tenant, with idempotent stops and stale event/retry guards.
- Email is Stytch B2B; DEBUG-only explicit dev mode is supported. Codes expire in ten minutes, permit five wrong attempts, and are consumed on success.
- Current AI runner has five advertised tools, Chat Completions and Responses branches, five-request tool loop, last-40 prompt history and last-60 persisted conversation history.
- AgentRouter diagnosis established that the tested key works at https://agentrouter.org/v1 with gpt-6.1-sol and Responses; co.agentrouter.org rejected that key. The report must explain credential/hostname specificity, not claim every AgentRouter account uses the same host.
- Source inventory intentionally avoids private .env/email note contents, live database rows, WhatsApp key values, dependency internals and cached bytecode.
- Source-level distinctions to preserve: Pathao token authentication can succeed even if the store-list lookup fails; upload checks MIME/size/non-empty but does not decode image integrity; SKU uniqueness is enforced in application scans, not SQL constraints.
- Security/research limits: webhook is CSRF-exempt without a shared-secret signature; Node controls rely on loopback, not API authentication; admin AI HTTP errors conflate 401/403; stock helpers and rate-limit JSON updates are not fully concurrency-safe; multiple SystemConfig rows are not prevented by a database singleton constraint.
- Auth behavior: OTP is sent before creating a pending signup account; unknown reset emails receive a generic success screen; administrative business creation does not send email OTP. Password policy is enforced by application helpers while AUTH_PASSWORD_VALIDATORS is empty.
- Financial/statistical semantics: revenue and converted counts include all non-cancelled statuses, not only completed orders; currency is not stored, dashboard money is formatted numerically and generated photo captions use a dollar sign.
- The source sends order WhatsApp notifications after the order transaction completes, but remote courier booking itself happens inside that transaction and cannot be rolled back remotely after a network timeout.
- Frontend reconstruction: independent complete templates, not template inheritance; CSRF meta on dashboards; one IIFE app.js and window.NexoraCharts; DOM data-widget/data-action/data-tab conventions; no bundler/npm frontend.
- Client contains seven tabs and three drawers. Admin contains three tabs plus account/tenant drawers. Landing animations are inline, with IntersectionObserver reveals, randomized headline typing and a scripted chat loop.
- CSS declares three local WOFF2 faces and a light/dark token palette; system color preference controls theme. Dashboard grid switches at 820px; product editor at 760px; landing grids at 900px. Reduced-motion CSS does not disable inline JavaScript timers.
- Product editor generates size/color Cartesian combinations, auto SKU initials and abbreviations, supports bulk price/stock and live in-memory catalog filters. Saved product forms carry original_image_url to reject stale photo replacements.
- Dashboard widget data is fetched once at initial load and refreshed after actions; WhatsApp alone polls every five seconds when the document is visible. There is no live dashboard WebSocket.
- Seed data is two optional synthetic shops, 12 products (10 active/2 archived), four orders and four chats, plus a staff admin. Seed functions skip any existing username entirely and run under one transaction when executed as main; they do not reserve stock through the normal order tool or create live courier bookings.
- Node tests execute the real index.js inside a VM with fake Express, QR encoder and Baileys sockets. Eight cases cover status/send purity, startup restoration, connect, queued reconnect cancellation, pending-start removal, stale events, and overlapping reset/removal. Middleware and actual WhatsApp wire behavior are not exercised by those fakes.
- Every dashboard/landing/auth template loads the same CSS/fonts/favicon; admin does not need charts.js. Current asset version parameters are CSS v12 (404 v5), app.js v14 and charts.js v5; these are cache-busters, not versions of separate build outputs.
- Launchers do not start XAMPP, seed records, generate migrations or reinstall dependencies during ordinary startup. Setup mode installs dependencies, creates .env only if absent, migrates, then exits. Node does not automatically parse backend/.env; its PORT and DJANGO_URL must be process environment variables.
- Installed versions inspected for this report: Python 3.14.7, Node v24.20.0, Django 6.1.2, PyMySQL 1.2.3, Requests 2.34.2. Node lockfile v3 has 205 package entries; direct resolved versions are Baileys 6.7.24, Express 4.22.3, qrcode 1.5.4.
- At the runtime inventory snapshot there were three uploaded photo files and 45 WhatsApp JSON files grouped as one credentials file, 27 pre-key files, 12 session files, four app-state files and one sender-key file. These counts change with normal WhatsApp activity; no contents were read.
- Migrations are schema changes only. 0001 creates initial config/tenant/product/order/conversation models; 0002 plan; 0003 shipment/settings/SHIPPED; 0004 plan_status; 0005 EmailOTP; 0006 product is_active; 0007 request_options. Bootstrap files are tiny standard Django setup, with empty package initializers and no ASGI application.
- The complete reference now has all 19 planned chapters; final fact checks use current models, settings, routes and provider adapters without importing the live Django application or making external service calls.
- Initial automated documentation checks found all 48 inventoried file mentions, all 90 top-level Python function mentions and all 33 Django routes; 43 local links/anchors and 17 JSON examples validated. No unexpected source hash changes or high-confidence credential-format hits were found.
- Corrected exact chat_threads field names to customer_phone/customer_name, documented archived-product summary counting, and changed the disable-Pathao example to omit fields that should be retained.
- Final source review identified an escalation persistence caveat: _request_human uses a queryset update, followed by run_agent saving a stale in-memory Conversation. The report records the possible needs_human overwrite; application code was not changed or live-tested.
- Added exact Django wiring and clarified stock truncation/empty-list validation and environment-base normalization differences for faithful reconstruction.
- Final report validation passed after corrections: 21,145 words in 19 chapters; all 48 inventoried files/90 top-level Python functions/33 Django routes covered, 43 local links and 17 JSON examples valid, 41 table layouts consistent, and 47 non-README source hashes unchanged. The dependency manifest and documented design colors matched source; no high-confidence credential patterns were found.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Evidence-linked reference rather than copied source archive | A future LLM needs contracts, rationale, UI vocabulary and sequencing; private data cannot be inferred or reproduced. |

## Issues Encountered
| Issue | Resolution |
|-------|------------|

## Resources
- Current source tree D:/final nexora; existing README and session's verified cleanup/migration notes.
- Official Django/Requests/Baileys/Stytch/Pathao/OpenAI/AgentRouter references will be listed in the report.
