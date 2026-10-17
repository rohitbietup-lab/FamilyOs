# Gmail sync recovery

Gmail read requests and refresh-token grants retry transient network failures,
HTTP 429, allowlisted quota-related HTTP 403 errors and HTTP 500/502/503/504 at most three times, with one- and two-second
backoff. Authorization-code exchange is not retried. Permanent 400/401/403/404
errors are returned immediately so reconnect or operator action is not hidden.
A deleted attachment is counted as skipped, like a message removed after listing,
rather than blocking the entire durable page.

When a sync page stops, the worker logs only exception class, HTTP status and
an allowlisted provider error code (when present).
It never logs exception prose, provider bodies, authorization headers, filenames,
message IDs, page tokens or credentials. The encrypted checkpoint is retained,
and normal replay continues to use content-hash deduplication and disconnect
fencing. Exhausted retries still leave a visible error and do not loop forever.

During local diagnosis, ten resumed pages completed successfully; the previous
generic error was not reproduced, so its precise cause remains unconfirmed.
The worker was restarted under the existing supervisor with the new diagnostics.
It subsequently imported more matching documents and stopped on HTTP 403; a
repeat read of that checkpoint page succeeded. Earlier logging did not include
the provider reason, so quota versus access denial could not be distinguished.
Bounded API error parsing now retains only known reason codes, never error prose.
Quota-related 403 responses retry; permission denials do not.
The initial full sync remains incomplete; completion and a subsequent live
incremental refresh are outstanding.

A specifically requested property draft was located with a narrow Gmail search,
downloaded, malware-scanned, validated and imported into Property with a clear
draft title and note. Other registered-copy emails contained HTML wrappers, not
PDF attachments; these were not executed, imported or automatically followed.
One owner-matching wrapper was inspected as data and its HTTPS download URL on
the builder's Salesforce file domain was requested without redirects or browser
credentials. The server returned HTTP 500 with HTML, so no document was imported.
The registered final document has not been verified. Private message metadata,
document bytes and local operator scripts are not stored in GitHub.

Validation: the full Django suite and Ruff pass, including bounded retries,
immediate permanent failures, quota versus access-denied 403 responses, sanitized
provider reasons, deleted attachment recovery and log sanitization.
The draft's presence and label were verified in the live Property group.
