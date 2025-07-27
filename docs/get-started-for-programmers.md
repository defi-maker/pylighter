# Get Started For Programmers
Lighter provides SDKs for two languages: Python and Go. You can choose one of the SDK and start trading.

Install the pip package

`pip install lighter-sdk`

Start with a basic status call

```
import zklighter
import asyncio


async def main():
    client = zklighter.ApiClient()
    root_api = zklighter.RootApi(client)
    status = await root_api.status()
    print(status)


if __name__ == "__main__":
    asyncio.run(main())

```


Let's get the available exchange details

```
import json
import zklighter
import asyncio


async def main():
    client = zklighter.ApiClient()
    order_api = zklighter.OrderApi(client)
    order_books = await order_api.order_book_details(filter="all")
    print(json.dumps(order_books.model_dump(), indent=4))


if __name__ == "__main__":
    asyncio.run(main())

```


Output:

```
{
  "code": 100,
  "message": null,
  "order_book_details": [
    {
        "symbol": "ETH",
        "market_id": 0,
        "status": "active",
        "taker_fee": "0.0300",
        "maker_fee": "0.0000",
        "liquidation_fee": "",
        "min_base_amount": "0.0050",
        "min_quote_amount": "10.000000",
        "supported_size_decimals": 4,
        "supported_price_decimals": 2,
        "supported_quote_decimals": 6,
        "size_decimals": 4,
        "price_decimals": 2,
        "quote_multiplier": 1,
        "initial_margin_fraction": 200,
        "maintenance_margin_fraction": 120,
        "closeout_margin_fraction": 80,
        "last_trade_price": 2374.89,
        "daily_trades_count": 2147140,
        "daily_base_token_volume": 43541.61250000002,
        "daily_quote_token_volume": 102412113.18653099,
        "daily_price_low": 2308.64,
        "daily_price_high": 2392.39,
        "daily_price_change": 1.0014373070479152,
        "open_position_base": 89493.3278,
        "open_position_quote": 190252681.480512,
        "daily_chart": {
          "1728032400": 2375.17,
          .
          .
          .
        }
    }
		.
    .
    .
  ]
}

```


We can get the current order book state

```
async def get_order_book(market_id: int) -> zklighter.OrderBookOrders:
    client = zklighter.ApiClient()
    order_api = zklighter.OrderApi(client)
    order_book_orders = await order_api.order_book_orders(market_id=0, limit=10)
    return order_book_orders


```


Output:

```
{
  "code": 100,
  "total_asks": 10,
  "asks": [
        {
            "order_index": 281474992718570,
            "owner_account_index": 3,
            "initial_base_amount": "1.2001",
            "remaining_base_amount": "0.4810",
            "price": "2310.53",
            "order_expiry": 1728833297023
        },
    .
    .
    .
  ],
  "total_bids": 10,
  "bids": [
        {
            "order_index": 562949938784145,
            "owner_account_index": 3,
            "initial_base_amount": "1.4737",
            "remaining_base_amount": "1.4737",
            "price": "2485.87",
            "order_expiry": 1728722474677
        },
    .
    .
  ]
}

```


Get the best bid and best ask

```
best_bid = order_book_orders.bids[0].price
best_ask = order_book_orders.asks[0].price

```


These were some example info endpoints to get the live data and insights from Lighter.

Now we'll try to create and cancel orders

Orders are managed by `SignedClient` in the Python SDK.

```
import time
import logging
import zklighter
import asyncio

logging.basicConfig(level=logging.DEBUG)

BASE_URL = "https://staging.zklighter.elliot.ai"
PRIVATE_KEY = "5de4111afa1a4b94908f83103eb1f1706367c2168ca870fc3fb9a804cdab365c"


async def get_best_bid(market_id: int) -> zklighter.OrderBookOrders:
    client = zklighter.ApiClient()
    order_api = zklighter.OrderApi(client)
    order_book_orders = await order_api.order_book_orders(market_id=market_id, limit=10)

    best_bid = float(order_book_orders.bids[0].price)
    return best_bid


async def main():
    client = zklighter.SignerClient(BASE_URL, PRIVATE_KEY)

    best_bid = await get_best_bid(0)
    best_bid_int = int(best_bid * 100)
    order = await client.create_order(
        market_index=0,
        client_order_index=0,
        base_amount=100,
        price=best_bid_int,
        is_ask=0,
        order_type=zklighter.SignerClient.ORDER_TYPE_LIMIT,
        time_in_force=zklighter.SignerClient.ORDER_TIME_IN_FORCE_POST_ONLY,
        order_expiry=int((time.time() + 60 * 60 * 24) * 1000),
    )

    print(order)

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())

```


Available order types:

```
ORDER_TYPE_LIMIT = 0
ORDER_TYPE_MARKET = 1

ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL = 0
ORDER_TIME_IN_FORCE_GOOD_TILL_TIME = 1
ORDER_TIME_IN_FORCE_POST_ONLY = 2

```


To cancel your order, you need to get your `order_nonce` which you can gather by `get_account_active_orders` method.

```
import logging
from eth_account import Account
import zklighter
import asyncio

logging.basicConfig(level=logging.DEBUG)

BASE_URL = "https://staging.zklighter.elliot.ai"
PRIVATE_KEY = "5de4111afa1a4b94908f83103eb1f1706367c2168ca870fc3fb9a804cdab365c"


async def main():
    client = zklighter.SignerClient(BASE_URL, PRIVATE_KEY)

    l1_address = Account.from_key(PRIVATE_KEY).address
    api_client = zklighter.ApiClient()
    account = await zklighter.AccountApi(api_client).accounts_by_l1_address(
        l1_address=l1_address
    )
    master_account_index = min(account.sub_accounts, key=lambda x: x.index).index

    active_orders = await zklighter.OrderApi(api_client).account_active_orders(
        account_index=master_account_index, market_id=0
    )
    last_order_index = active_orders.orders[0].order_index

    tx, response = await client.cancel_order(order_index=last_order_index)
    logging.info(
        f"code: {response.code} msg: {response.message} l2Hash: {response.tx_hash} tx: {tx.to_json()}"
    )

    await client.close()
    await api_client.close()


if __name__ == "__main__":
    asyncio.run(main())

```
