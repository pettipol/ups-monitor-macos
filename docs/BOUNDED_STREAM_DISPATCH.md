# Bounded stream dispatch

`BoundedStreamDispatch` is a small, opt-in foundation for consuming streamed
stdout in order. It stores at most two queued chunks of up to 65,536 bytes and
dispatches one additional chunk at a time to a single daemon worker. The
consumer runs outside the state lock; producers never call it directly.

The producer closes input separately from the data queue. After queued chunks
drain, the worker calls the consumer once with `b""` to signal EOF. Either
valid boolean return marks that EOF call delivered, and EOF never counts as
progress. Only `True` for a nonempty chunk advances the bounded progress
counter and records a monotonic timestamp. Invalid clock values, clock
regression, counter overflow, oversized chunks, queue backpressure, consumer
errors, and worker start failures latch fixed error codes. Failure or Stop
drops queued chunks and accepts no new input; it does not retry or replace the
worker.

Stop cannot interrupt a consumer callback already in progress. `join` accepts
a finite budget of up to two seconds and reports whether the worker quiesced.
If it remains blocked, the owner must retain the dispatcher and its state;
returning from `join` does not mean the worker was terminated.

This component is isolated and is not connected to the process runner or app.
Its unit tests passed (21 tests; receipt covers this component only). The full
CI script has not been run. These results do not qualify a session longer than
120 seconds, the GUI, or real hardware.
