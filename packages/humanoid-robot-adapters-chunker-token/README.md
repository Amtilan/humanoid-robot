# humanoid-robot-adapters-chunker-token

Token-aware fixed-size chunker with paragraph-preserving boundaries. No ML
dependency — token count is estimated as `len(text) / chars_per_token`
(default `4.0`, which is close to BPE english + slightly conservative for
Cyrillic). The estimate stays inside the caller's max-token budget on all
corpora we have seen so far; if you need a true tokenizer, register a
different `chunker_adapters` implementation.

## Behaviour

- Splits on blank-line paragraph boundaries first.
- If a paragraph fits within `target_tokens`, it becomes one chunk.
- Otherwise, splits on sentence-ish boundaries (`. `, `? `, `! `, `\n`).
- Guarantees no chunk exceeds `hard_max_tokens` in the estimated token
  count — falls back to hard slicing when even a sentence is too big.
- Optional `overlap_tokens` glues consecutive chunks so retrieval keeps
  context near paragraph boundaries.

## Registration

Under the `humanoid_robot.chunker_adapters` entry-point group as `token`.
