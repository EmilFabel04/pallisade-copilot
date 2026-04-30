A monitor on `{node_fqn}` just fired with a borderline reading on the `{metric}` metric.

Observed: {observed}
Expected range: {expected_range}
Z-score: {z_score} (sensitivity threshold not yet exceeded)
Sample window: {sample_window}

Speak directly. One short sentence stating the deviation, then one focused question:
"Is this expected, or worth investigating?"

If the user says "expected", call `record_clarification_answer` with
`structured_answer: {{"disposition": "expected"}}` — Pallisade will dampen future
alerts on this node + metric.

If the user says "investigate", call `record_clarification_answer` with
`structured_answer: {{"disposition": "investigate"}}` — the platform will open a
debug session loaded with this failure's context.

Hard rules:
- Do not propose answers; ask, then wait.
- Do not call any tool except `record_clarification_answer`.
- Keep your message under 50 words.
