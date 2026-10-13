# Order cancellation retired

Customer cancellation and owner/staff review routes, controls and services have been removed. Old URLs return 404. Manual order status forms exclude CANCELLED.

Historical CancellationRequest and OrderEvent records, cancelled_at, workflow_version, and CANCELLED database choices remain unchanged. No cleanup migration or data operation is required. Historical status and read-only audit records remain available.

Shared orders.locking protects payment reconciliation, retries, COD collection and fulfillment updates. Payment verification retains signature/provider checks, idempotent stock changes, and late COMPLETE handling for historical cancellations: record verified funds, retain cancelled status and released stock, flag financial review, and append one audit event. No automatic refunds or stock restoration of historical orders occurs. Provider payment failure handling remains part of the existing payment lifecycle.
