# cortex-robot-adapter

Standalone process that owns exactly **one** robot adapter, publishes its
`RobotAdapterReady` manifest on the event bus, and keeps the adapter alive.

## Commands

```bash
cortex-robot-adapter list                            # discovered adapters
cortex-robot-adapter run unitree_g1_edu \
    --interface eth10 --mic-source g1 \
    --nats nats://127.0.0.1:4222
```

`run` blocks until SIGTERM. On shutdown it publishes `SystemShuttingDown`
and calls `adapter.stop()`.

## Config sources (highest priority first)

1. Command-line flags
2. Environment variables (`HR_ROBOT_ADAPTER__*`)
3. YAML config file `--config /etc/humanoid-robot/robot-adapter.yaml`
4. Package defaults
