Receive status and notification refresh

- Separate imported FILE history from live RX packets and current connection counts.
- Show waiting for the first packet until an actual notification arrives, along with active channel count and last-received age.
- Add manual notification subscription refresh using standard CCCD disable/enable operations.
- Discover fresh Windows GATT services and clean up active subscriptions before intentionally closing the connection.

This update improves receive diagnostics and subscription lifecycle. It does not
claim that a connected but silent R1 has begun emitting gestures. No application
initialization commands, health queries or firmware operations are added.
