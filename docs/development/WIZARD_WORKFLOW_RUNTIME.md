# Durable Wizard workflow runtime

Immediate actions finish inside one Wizard turn. A workflow can wait for a
canonical task and continue after a reload without asking the LLM to repeat a
mechanical decision.

## Durable record

Each workspace stores `.wizard-workflows-v1.json` through
`GET/PUT /api/v1/wizard/workflows`. Writes use compare-and-swap revisions and
an atomic temporary-file replacement. Every record includes:

- workflow identity, type, workspace and original user request;
- state, current step and per-step input/output checkpoints;
- immutable input snapshot and resolved entity IDs;
- canonical task IDs, pipeline IDs and output references;
- confirmation scope, attempts and processed canonical event IDs;
- timestamps, recoverable error, cancellation and resumption flags.

Credentials in nested inputs are redacted before the backend writes them.

## Runtime behavior

`wizardWorkflowRuntime.ts` registers deterministic workflow definitions. It
persists a step as `running` before invoking it and persists either its output
or its canonical wait ID before continuing. A waiting step advances only when
the task event stream reports its exact `task_id` as terminal.

Processed event IDs and a per-workflow serial queue make duplicate or
concurrent completion events harmless. Reloading a waiting workflow does not
execute its queue step again. An interrupted `running` step becomes a
recoverable failure and requires explicit resume; its stable execution key lets
the underlying action reuse an already-created task.

The state machine is:

```text
prepared -> queued -> waiting -> running -> completed
                                  |-> partial
                                  |-> failed -> retrying
                                  |-> cancelled
```

The Wizard panel subscribes to the canonical task stream while open. Workflow
updates reuse one stable execution-card ID, so a completion edits the existing
card instead of appending a second result.

## Next vertical slice

The runtime intentionally contains no creative workflow definition yet. Phase
5 registers `create_rhythmic_3d_video`, whose steps will generate/resolve audio,
prepare the scene, bake rhythm, save and export using the stored IDs above.
