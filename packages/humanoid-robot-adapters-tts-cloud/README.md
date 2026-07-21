# humanoid-robot-adapters-tts-cloud

`TtsPort` over an OpenAI-compatible `POST /v1/audio/speech` endpoint, with a
**voice per language** map — the reason it exists is Kazakh: the on-device
Piper stack has no Kazakh voice, cloud providers do (plan stage 5).

Select in `voice.yaml` with the local Piper as offline fallback:

```yaml
stack:
  tts:
    name: cloud
    config:
      base_url: https://api.openai.com   # or a Yandex/Azure OpenAI-compatible proxy
      api_key_env: HR_TTS_CLOUD_API_KEY  # key comes from the env, never from git
      model: tts-1
      voices: { ru: alloy, kk: alloy, en: alloy }
  tts_fallback:
    name: piper
    config: { ... }                      # spoken when the cloud is unreachable
```

The final Kazakh voice is chosen with the customer on-site (plan §9 risk).
