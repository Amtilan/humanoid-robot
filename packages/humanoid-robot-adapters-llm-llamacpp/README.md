# humanoid-robot-adapters-llm-llamacpp

`LlmPort` implemented against a `llama.cpp` HTTP server (the `llama-server`
binary shipped with llama.cpp). Uses the OpenAI-compatible `/completions`
route so the same adapter also works against any llama-server-compat server
(vLLM, mlc-serve, etc.) with minor config changes.

## Configuration

```python
LlamaCppLlm(
    config=LlamaCppConfig(
        base_url="http://127.0.0.1:8080",
        model="qwen3-8b-instruct-q4_k_m",
        request_timeout_s=60.0,
        max_retries=1,
    )
)
```

Per ADR-0005 the reference model is `Qwen 3 8B Instruct Q4_K_M`, but the
adapter is model-agnostic; the operator supplies the model tag to send to
the server.

## Runtime dependency

`httpx` is a runtime dependency and installed unconditionally — it is small
(~1 MB) and required by other subsystems too. No model weights or CUDA
runtime are pulled by this package; you point it at an already-running
`llama-server` process (managed by systemd on the robot).

## Streaming

`stream(request)` uses the server's SSE (`text/event-stream`) response
mode. `generate(request)` uses the single-shot `/completions` route.
