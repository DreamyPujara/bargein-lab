# Bargein Lab

Bargein Lab is a small, offline Python CLI for voice-agent product teams who want a deterministic sandbox for interruption behavior before touching telephony, audio, or live users.

It uses synthetic start/stop events and reports how long the agent continues after a user starts speaking.

## User and problem

**User:** a product engineer or QA engineer working on barge-in / interruption behavior for a voice-agent prototype.

**Problem:** before running expensive or flaky audio tests, the team needs a repeatable check that a candidate event stream cancels agent speech quickly enough after user interruption and does not regress versus a known baseline.

## Event format

Input is JSON, either a list or an object with an `events` list:

```json
[
  {"time_ms": 0, "type": "agent_start"},
  {"time_ms": 900, "type": "user_start"},
  {"time_ms": 1040, "type": "agent_stop"}
]
```

Supported event types:

- `agent_start`
- `agent_stop`
- `user_start`
- `user_stop`

A measured interruption is a `user_start` that occurs while the agent is speaking. Cancellation delay is:

```text
next agent_stop time_ms - user_start time_ms
```

If no later `agent_stop` exists, it is counted as a missed cancellation.

## Quick start

Run the built-in synthetic demo:

```bash
python tool.py demo
```

Measure one stream:

```bash
python tool.py measure examples/candidate.json
```

Compare baseline and candidate with gates:

```bash
python tool.py compare examples/baseline.json examples/candidate.json --max-p95-ms 180 --max-regression-ms 0
```

Exit codes:

- `0`: command succeeded; for `compare`, gates passed
- `1`: `compare` ran but gates failed
- `2`: input or file error

## Metrics

The CLI prints JSON with:

- `interruptions`: user interruptions while the agent was speaking
- `completed_cancellations`: interruptions with a later `agent_stop`
- `missed_cancellations`: interruptions without a later `agent_stop`
- `delays_ms`: individual cancellation delays
- `avg_delay_ms`: arithmetic mean of completed delays
- `p95_delay_ms`: nearest-rank p95 of completed delays
- `max_delay_ms`: maximum completed delay

Comparison gates currently check:

- candidate p95 is not above `--max-p95-ms`
- candidate p95 regression versus baseline is not above `--max-regression-ms`
- candidate does not add missed cancellations, unless `--allow-more-missed` is set

## Tests

Run:

```bash
python -m unittest discover -s tests
```

## Tradeoffs

- Uses event timestamps only; there is no audio analysis.
- Sorts events by timestamp for deterministic behavior, so it is tolerant of unsorted JSON.
- Uses nearest-rank percentile because it is easy to explain and stable for small synthetic samples.
- Counts multiple `user_start` events during the same agent turn as multiple interruption attempts.

## Non-goals

- No telephony, streaming, microphone, audio, ASR, or TTS integration.
- No network calls.
- No personal, customer, employer, or production data.
- No attempt to model conversational quality or user satisfaction.

## AI assistance and limitations

This first version was generated with AI assistance. It should be reviewed like any other code. The tool is intended for deterministic offline sandboxing only; passing these checks does not prove that a real voice system handles barge-in correctly under network, device, acoustic, or model-latency conditions.
