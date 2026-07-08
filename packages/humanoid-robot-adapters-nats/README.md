# humanoid-robot-adapters-nats

NATS + JetStream adapter for `EventBusPort`.

- Publish: subject from `event.subject`, body is `event.model_dump_json()`,
  headers carry `hr-schema-version` and `hr-type-name` for consumer
  routing / compatibility checks.
- Subscribe: without `durable_name` uses a **core NATS ephemeral**
  subscription (fan-out, at-most-once). With `durable_name` opens a
  **JetStream pull consumer** (at-least-once, persistent).
- Deserialisation uses an event-class registry built at import time from
  `humanoid_robot.events.__all__`. Adding a new event type in the events
  package is enough — no adapter change required.

Configuration (all optional):

```python
NatsEventBus(
    servers=("nats://localhost:4222",),
    name="cortex-core",           # client name shown in monitoring
    connect_timeout_s=5.0,
    reconnect_time_wait_s=1.0,
    max_reconnect_attempts=-1,    # infinite
    user_credentials=None,        # path to .creds for NGS/JWT auth
    tls_ca=None,                  # path to CA cert
    tls_cert=None,
    tls_key=None,
)
```

Contract tests live under `tests/` and reuse the fake fixtures from
`humanoid-robot-testing`.
