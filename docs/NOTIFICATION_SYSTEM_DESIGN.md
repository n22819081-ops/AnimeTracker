# Notification System Design

Milestone 6 converts typed domain events into versioned messages and durable outbox rows. It is independent from GUI, production scheduling, live persistence, and media discovery.

Private tracker, shared announcement, and Windows local purposes are distinct. Each Discord purpose has its own enabled state, credential reference, event filters, templates, delivery history, suppression rules, silent setting, and rate limit. Windows delivery is optional, private, non-blocking, and cannot fail Discord delivery.

Stable event keys identify material facts such as AniList ID plus episode and airing-time version, mapping plus coverage snapshot, or week start plus summary purpose. Channel purpose is added at enqueue, allowing one fact to produce separate private and shared rows without duplication within either channel.

The flow is event, privacy check, filter/suppression decision, versioned rendering, atomic enqueue, lease claim, credential lookup, delivery outside the transaction, ownership-checked completion, and delivery-attempt history. Errors retain redacted type/summary only. No webhook is stored in an event, message, outbox row, attempt, log, or diagnostic.

The optional manual Discord integration check requires an explicitly supplied dedicated test webhook. It is disabled by default and never reads production configuration. It was not run for Milestone 6.
