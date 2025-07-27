# Rate Limits
We enforce rate limits on both REST API and WebSocket usage. These limits are based on IP address, not L1 wallet address.

Below is an overview of our rate limiting rules.

* * *

_Premium Account_ users have limit of 2400 weighted REST API requests per minute, while _Standard Account_ users 60 per minute.

**The `sendTx` and `sendTxBatch` transaction types are the only types of transactions that can increase in quota (see Volume Quota)**, which are used to create and modify orders. All other endpoints are have a set limit of tx per minute and do not increase with volume.

Weights per endpoint can be listed as below:

*   **Per User**: 1

* * *

*   **Per User**: 5

* * *

*   **Per User**: 10

* * *

*   **Per User**: 15

* * *

Other endpoints not listed above are limited to:

*   **Per User**: 30

* * *

Requests from a single IP address are capped at:

*   **60 requests per minute** under the Standard Account
*   **2400 requests per minute** under the Premium Account

* * *

To prevent resource exhaustion, we enforce the following usage limits **per IP**:

*   **Sessions**: 5
*   **Subscriptions**: 100
*   **Unique Accounts**: 5
*   **Session Burst**: 100 messages

* * *

These limits applied for only standard accounts.


|Transaction Type  |Limit                  |
|------------------|-----------------------|
|Default           |60 requests / minute   |
|L2Withdraw        |2 requests / minute    |
|L2UpdateLeverage  |1 request / minute     |
|L2CreateSubAccount|2 requests / minute    |
|L2CreatePublicPool|2 requests / minute    |
|L2ChangePubKey    |2 requests / 10 seconds|
|L2Transfer        |1 request / minute     |


* * *

If you exceed any rate limit:

*   You will receive an HTTP `429 Too Many Requests` error.
*   For WebSocket connections, excessive messages may result in disconnection.

To avoid this, please ensure your clients are implementing proper backoff and retry strategies.
