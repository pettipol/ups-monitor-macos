# Alert Delivery

`UPSAlertController` owns session-only opt-in, policy, evaluator continuity, and
delivery lifecycle. It starts disabled. Only `setEnabled(true)` requests
authorization; `observe` never prompts and is ignored when disabled, stopped, or
busy. Observations arriving during an admitted asynchronous delivery are
skipped rather than accumulated. A later polling observation can reevaluate
conditions. Policy changes reset evaluator observations but preserve cooldowns.

Authorization, submissions, and cleanup are generation-fenced. Disabling,
suspending, or stopping invalidates pending authorization and observation
completions. An already admitted submission cannot be cancelled, so lifecycle
transitions await it before clearing the four identifiers owned by this
feature. `suspend()` resets observations and preserves opt-in and cooldowns; `stop()` disables
permanently. Before the first explicit enable, suspend/stop do not call the
delivery dependency. Delivery failures produce a generic UI message and are
not retried on each poll.

`SystemUPSAlertDelivery` accesses `UNUserNotificationCenter` lazily. It requests
only alert authorization, verifies current authorization before each submit,
and uses four fixed IDs. A pure request factory is tested without touching the
notification center. Requests have no trigger, user info, attachments, sound,
badge, category, or actions. Titles and bodies are generic; bodies
contain only a formatted event capture time, with monitoring loss labeled as
the last observation. Its retained delegate is installed only after opt-in and
asks macOS to present this feature's alerts as foreground banners and in the
notification list. Other notification identifiers receive no foreground
presentation override. The user and System Settings still determine actual
presentation; request acceptance is not proof that a banner was shown.

Tests inject a synthetic delivery and use continuations to hold authorization
and submission operations across disable, suspend, and stop. No permission
prompt, app notification center, hardware, or live UPS source is exercised.
Clearing these fixed IDs does not remove other app notifications and is not a
claim of secure physical erasure of Notification Center history.
