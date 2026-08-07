# Intent routing (Sprint 2)

Production hot path uses a **regex heuristic** only — no SageMaker / AWS tool call per turn.

## Ingress normalization

Gateway (typed + voice) runs a single-pass `normalize_utterance()` (`_fold_vi`: lowercase + strip Vietnamese diacritics, `đ→d`):

| Field | Use |
|-------|-----|
| `raw_utterance` | Logs, TTS echo, UI transcript |
| `normalized_utterance` | All intent + `get_command_id` pattern matchers |

## Precedence

```
Safety/Emergency (core refuse) > Direct Control (known command_id) > RAG heuristics > Free Talk
```

- **Direct control:** `get_command_id(normalized) != GENERIC_CONTROL` ⇒ `CAR_CONTROL` (single source of truth with `car_controller.COMMAND_CONTRACTS`).
- **Advice hybrid:** `should i` / `bao lau` / `nen` without a trailing imperative ⇒ `RAG_SEARCH`.
- **Compound:** advice clause + later imperative (e.g. `…? Open it now.`) ⇒ **Direct Control wins**.

## Telemetry

When `intent=CAR_CONTROL` but `command_id=GENERIC_CONTROL`, gateway emits a structured **warning** log so unmapped phrases can be harvested into fixtures.

## Latency SLA (documented targets)

| Phase | Mechanism | Target |
|-------|-----------|--------|
| **Phase 1 (now)** | Regex + command contract | **&lt;5ms** p99 local classify |
| **Phase 2 (later)** | Warm SageMaker / AWS tools intent | Soft **&lt;200ms** warm; not on Sprint 2 hot path |

## Fixtures

Ambiguous + clean cases: [`tests/fixtures/ambiguous_intent_cases.json`](../tests/fixtures/ambiguous_intent_cases.json)

```bash
uv run pytest tests/test_intent_router.py -q
```
