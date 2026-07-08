# humanoid-robot-plugins-sdk

Runtime discovery of robot adapters (and, later, generic plugins).

Adapter authors register a **factory callable** under the entry-point group
`humanoid_robot.robot_adapters`:

```toml
# pyproject.toml of an adapter package
[project.entry-points."humanoid_robot.robot_adapters"]
unitree_g1_edu = "humanoid_robot.adapters.unitree_g1.adapter:UnitreeG1Adapter"
```

The factory can be a class (constructed with `**kwargs`) or a plain callable
returning a `RobotAdapterPort`. Kwargs are provided by the runner from
runtime config (e.g. `network_interface`, `mic_source`).

`AdapterRegistry.discover()` scans the current interpreter for all
registered entries and lets the caller instantiate by name:

```python
registry = AdapterRegistry.discover()
adapter = registry.build("unitree_g1_edu", network_interface="eth10")
```

Registration is **explicit** (`[project.entry-points]`) — the SDK never
scans directories or auto-loads Python modules.
