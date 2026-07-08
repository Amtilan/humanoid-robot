# humanoid-robot-testing

Reusable test doubles. Every port has a fake here so that other packages can
depend on this instead of building their own mocks.

- `InMemoryEventBus` — pub/sub with recording for assertions
- `MockRobotAdapter` — programmable manifest + capability spies
- `MockAsr` / `MockLlm` / `MockTts` — deterministic AI stubs

Nothing here talks to real hardware or the network.
