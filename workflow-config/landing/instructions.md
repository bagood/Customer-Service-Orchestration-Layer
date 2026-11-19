# Landing workflow

Use `classify_intent` for a new customer's request and clarification replies while
the session remains in the landing workflow. Submit the original customer message,
a stable `session_ref`, and a unique `message_id`. Reuse the same identifier and
unchanged message for retries. These references are demo correlation identifiers,
not proof of customer identity.

The tool asks the configured external decision model to distinguish between
`buy_package` and `send_credit`. The server validates the model's JSON decision
before updating its Pydantic state. Do not submit a desired intent or state.

- `needs_clarification`: ask the returned `customer_reply`, then classify the next
  customer message using the same session and a new message identifier.
- `classified`: the intent is recorded and `next_workflow` identifies the intended
  destination. `next_step` is `handoff_pending`: destination workflows have not yet
  been implemented. No purchase or credit transfer has been executed.
- Tool error: classification failed; do not assume that state changed. Retry the
  unchanged message with the same identifiers after resolving the failure.

Once classified, the session cannot be reclassified by this landing tool. A retry
of its original message returns its original result. Do not use a new session to
bypass an active workflow. Session state and retry history are in memory in a
single server process and are cleared on restart.
