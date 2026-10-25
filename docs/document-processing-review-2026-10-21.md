# Document processing and review repair

Found: review fetched details once, so status could stay stale. It also offered blank name inputs and Save corrections while queued/processing. Worker logs showed 180-second extraction timeouts and queue socket resets while blocking inside a model call. Windows had approximately 500 MB free RAM when checked; that is a resource-pressure observation, not proof of the sole timeout cause.

Changes: poll review details every three seconds until terminal status; hide editing until completed; disable saving while processing; cancel stale initial fetches. Failed documents expose Retry reading without reuploading. The authenticated retry endpoint accepts failed files only and restores failed state if enqueueing fails. Queue worker runs the blocking job in a worker thread while servicing Pika I/O on the connection-owning thread.

Verification: 36 worker tests passed, including a new heartbeat progress check. Three retry endpoint checks plus code standards passed. Completed pay-slip review was checked in the browser. Frontend build checked separately. No fields were manually populated or fabricated to hide an extraction failure. Model throughput and extraction timeout under severe memory pressure remain limitations.
