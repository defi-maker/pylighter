# Account Types
Lighter API users can operate under a Standard or Premium account.

*   Fees: 0.002% Maker, 0.02% Taker
*   maker/cancel latency: 0ms
*   taker latency: 150ms

  

*   fees: 0 maker / 0 taker
*   taker latency: 300ms
*   maker/cancel latency: 200ms

You can change your Account Type (tied to your L1 address) using the `/changeAccountTier` endpoint.

You may call that endpoint if:

*   You have no open positions
*   You have no open orders
*   At least 3 hours have passed since the last call

_Python snippet to switch tiers_:

```switch to Premium
import asyncio
import logging
import lighter
import requests

logging.basicConfig(level=logging.DEBUG)

BASE_URL = "https://mainnet.zklighter.elliot.ai"

# You can get the values from the system_setup.py script
# API_KEY_PRIVATE_KEY =
# ACCOUNT_INDEX =
# API_KEY_INDEX =


async def main():
    client = lighter.SignerClient(
        url=BASE_URL,
        private_key=API_KEY_PRIVATE_KEY,
        account_index=ACCOUNT_INDEX,
        api_key_index=API_KEY_INDEX,
    )

    err = client.check_client()
    if err is not None:
        print(f"CheckClient error: {err}")
        return

    auth, err = client.create_auth_token_with_expiry(
        lighter.SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY
    )

    response = requests.post(
        f"{BASE_URL}/api/v1/changeAccountTier",
        data={"account_index": ACCOUNT_INDEX, "new_tier": "premium"},
        headers={"Authorization": auth},
    )
    if response.status_code != 200:
        print(f"Error: {response.text}")
        return
    print(response.json())


if __name__ == "__main__":
    asyncio.run(main())

```


```switch to standard
import asyncio
import logging
import lighter
import requests

logging.basicConfig(level=logging.DEBUG)

BASE_URL = "https://mainnet.zklighter.elliot.ai"

# You can get the values from the system_setup.py script
# API_KEY_PRIVATE_KEY =
# ACCOUNT_INDEX =
# API_KEY_INDEX =


async def main():
    client = lighter.SignerClient(
        url=BASE_URL,
        private_key=API_KEY_PRIVATE_KEY,
        account_index=ACCOUNT_INDEX,
        api_key_index=API_KEY_INDEX,
    )

    err = client.check_client()
    if err is not None:
        print(f"CheckClient error: {err}")
        return

    auth, err = client.create_auth_token_with_expiry(
        lighter.SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY
    )

    response = requests.post(
        f"{BASE_URL}/api/v1/changeAccountTier",
        data={"account_index": ACCOUNT_INDEX, "new_tier": "standard"},
        headers={"Authorization": auth},
    )
    if response.status_code != 200:
        print(f"Error: {response.text}")
        return
    print(response.json())


if __name__ == "__main__":
    asyncio.run(main())

```


In isolated margin, fees are taken from the isolated position itself, but if needed, we automatically transfer from cross margin to keep the position healthy. In cross margin, fees are always deducted directly from the available cross balance.

Sub-accounts share the same tier as the main L1 address on the account. You’ll be able to switch to a Premium Account now. Let us know if you have any questions.
