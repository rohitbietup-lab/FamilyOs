# Gmail sync recovery

Gmail read requests and refresh-token grants retry transient network failures,
HTTP 429 and HTTP 500/502/503/504 at most three times, with one- and two-second
backoff. Authorization-code exchange is not retried. Permanent 400/401/403/404
errors are returned immediately so reconnect or operator action is not hidden.
A deleted attachment is counted as skipped, like a message removed after listing,
rather than blocking the entire durable page.

When a sync page stops, the worker logs only exception class and HTTP status.
It never logs exception prose, provider bodies, authorization headers, filenames,
message IDs, page tokens or credentials. The encrypted checkpoint is retained,
and normal replay continues to use content-hash deduplication and disconnect
fencing. Exhausted retries still leave a visible error and do not loop forever.

During local diagnosis, ten resumed pages completed successfully; the previous
generic error was not reproduced, so its precise cause remains unconfirmed.
The worker was restarted under the existing supervisor with the new diagnostics.
The initial full sync remains incomplete; completion and a subsequent live
incremental refresh are outstanding.

A specifically requested property draft was located with a narrow Gmail search,
downloaded, malware-scanned, validated and imported into Property with a clear
draft title and note. Other registered-copy emails contained HTML wrappers, not
PDF attachments; these were not executed, imported or automatically followed.
The registered final document has not been verified. Private message metadata,
document bytes and local operator scripts are not stored in GitHub.

Validation: all 94 Django tests pass, including bounded retries, immediate
permanent failures, deleted attachment recovery and log sanitization. Ruff passes.
The draft's presence and label were verified in the live Property group.
