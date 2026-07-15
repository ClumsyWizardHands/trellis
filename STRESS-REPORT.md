# STRESS REPORT

run: 2026-07-15T20:02:09+00:00 · python 3.11.15 · seed 20260715 (deterministic chaos)
result: **10/10 attacks defeated**

The suite's stance is the verifier's stance: each scenario ATTACKS one of
the harness's refusals. A pass means the attack failed. Evidence below is
recorded, not narrated.

## ✅ scale: 5k ledger entries — append, supersede, search, as_of
took 9.281s
```json
{
  "entries": 5000,
  "corrections": 100,
  "append_s": 0.14,
  "correct_s": 9.02,
  "search_s": 0.056,
  "current_s": 0.029,
  "file_mb": 1.0
}
```

## ✅ session death: 200 chaotic runs — zero silent failures possible
took 0.023s
```json
{
  "runs": 200,
  "fates_injected": {
    "ok": 49,
    "crash": 30,
    "wander": 38,
    "block": 44,
    "budget": 39
  },
  "outcomes_recorded": {
    "blocked": 44,
    "budget_exceeded": 39,
    "protocol_violation": 68,
    "ok": 49
  },
  "silent_failures": 0
}
```

## ✅ time attack: skewed, future, and ancient events never read as current
took 0.01s
```json
{
  "annotations_checked": 2000,
  "naive_stamps_refused": 50
}
```

## ✅ pass fuzz: 3000 random transitions — illegal ones always refused, none lost
took 0.017s
```json
{
  "transitions_attempted": 3000,
  "legal_accepted": 321,
  "illegal_refused": 2679,
  "passes_persisted": 60,
  "turd_drops_refused": 4
}
```

## ✅ privacy fuzz: 5000 random flows — DM->public always blocked without a token
took 0.018s
```json
{
  "flows": 5000,
  "allowed": 2666,
  "blocked": 2334
}
```

## ✅ self-certification: 100 disguise attempts all refused
took 0.004s
```json
{
  "disguise_attempts": 400,
  "refused": 400
}
```

## ✅ sycophancy pressure: T-shaped maybes refused; hidden nos surface
took 0.003s
```json
{
  "fake_Ts_refused": 200,
  "hidden_nos_surfaced": 10
}
```

## ✅ witness under a garbage model: 30 cycles of fluff produce zero fake decisions
took 0.047s
```json
{
  "cycles": 30,
  "outcomes": {
    "failed": 30
  },
  "fake_decisions_recorded": 0
}
```

## ✅ concurrency: 8 threads x 500 appends — ledger stays readable, nothing lost
took 0.286s
```json
{
  "threads": 8,
  "appends": 4000,
  "readable": true,
  "lost": 0
}
```

## ✅ synthesis gate under pressure: 500 lazy writes refused, store stays sparse
took 0.001s
```json
{
  "lazy_writes_attempted": 500,
  "refused": 500,
  "files_created": 0
}
```
