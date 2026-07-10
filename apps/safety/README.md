# cortex-safety

Fail-closed gate between orchestrators (LLM, behavior tree, plugins)
and the concrete robot adapter.

Subscribes to `robot.command.requested`, evaluates a chain of
`SafetyPolicyPort` policies, and publishes either
`safety.command.forwarded` (which the adapter must ack) or
`safety.command.denied`.  Unknown/unclassified capabilities are denied.

E-stop policies default to engaged-on-boot until an operator releases
it explicitly.
