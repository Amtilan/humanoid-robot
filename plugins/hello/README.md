# humanoid-robot-plugins-hello

Reference first-party plugin. Subscribes to `asr.final` events on the bus
and logs a friendly acknowledgement — a minimal, self-contained example of
how third-party plugins integrate with the platform.

Registered under `humanoid_robot.plugins` as `hello`.

## Usage

Once installed, the plugin appears in `PluginRegistry.discover()`:

```python
from humanoid_robot.plugins_sdk import PluginRegistry

registry = PluginRegistry.discover()
print(registry.names())     # ('hello',)
plugin = registry.build("hello")
```

Plugin lifecycle:

```python
await plugin.activate(PluginContext(bus=bus))
# ... plugin now handles asr.final events ...
await plugin.deactivate()
```
