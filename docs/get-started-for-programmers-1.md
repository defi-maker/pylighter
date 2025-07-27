# Get Started For Programmers
Welcome to the Lighter SDK and API Introduction. Here, we will go through everything from the system setup, to creating and cancelling all types of orders, to fetching exchange data.

In order to get started using the Lighter API, you must first set up an **API\_KEY\_PRIVATE\_KEY**, as you will need it to sign any transaction you want to make. You can find how to do it in the following [example](https://github.com/elliottech/lighter-python/blob/main/examples/system_setup.py). The **BASE\_URL** will reflect if your key is generated on testnet or mainnet (for mainnet, just change the **BASE\_URL** in the example to [https://mainnet.zklighter.elliot.ai](https://mainnet.zklighter.elliot.ai/)). Note that you also need to provide your **ETH\_PRIVATE\_KEY**.

You can setup up to 253 API keys (2 <= **API\_KEY\_INDEX** <= 254). The 0 index is the one reserved for the desktop, while 1 is the one reserved for the mobile. Finally, the 255 index can be used as a value for the _api\_key\_index_ parameter of the **apikeys** method of the **AccountApi** for getting the data about all the API keys.

In case you do not know your **ACCOUNT\_INDEX**, you can find it by querying the **AccountApi** for the data about your account, as shown in this [example](https://github.com/elliottech/lighter-python/blob/main/examples/get_info.py).

Lighter API users can operate under a Standard or Premium account. The Standard account is suitable for latency insensitive traders, providing 0 fees, while the premium one provides a latency suitable for HFTs at 0.2 bps maker and 2 bps taker fees. You can find more information about it in the [Account Types](https://apibetadocs.lighter.xyz/edit/account-types) section.

In order to create a transaction (create/cancel/modify order), you need to use the **SignerClient**. For initializing it, use the following lines of code:

```
 client = lighter.SignerClient(  
        url=BASE_URL,  
        private_key=API_KEY_PRIVATE_KEY,  
        account_index=ACCOUNT_INDEX,  
        api_key_index=API_KEY_INDEX  
    )

```


The code for the signer can be found in the same repo, in the [signer\_client.py](https://github.com/elliottech/lighter-python/blob/main/lighter/signer_client.py) file. You may notice that it uses a binary for the signer: the code for it can be found in the [lighter-go](https://github.com/elliottech/lighter-go) public repo, and you can compile it yourself using the [justfile](https://github.com/elliottech/lighter-go/blob/main/justfile).

When signing a transaction, you may need to provide a nonce (number used once). A nonce needs to be incremented each time you sign something. You can get the next nonce that you need to use using the **TransactionApi’s** _next\_nonce_ method or take care of incrementing it yourself. Note that each nonce is handled per **API\_KEY**.

One can sign a transaction using the **SignerClient’s** _sign\_create\_order_, _sign\_modify\_order_, _sign\_cancel\_order_ and its other similar methods. For actually pushing the transaction, you need to call _send\_tx_ or _send\_tx\_batch_ using the **TransactionApi**. Here’s an [example](https://github.com/elliottech/lighter-python/blob/main/examples/send_tx_batch.py) that includes such an operation.

Note that _base\_amount, price_ are to be passed as integers, and _client\_order\_index_ is an unique (across all markets) identifier you provide for you to be able to reference this order later (e.g. if you want to cancel it).

The following values can be provided for the order\_type parameter:

*   ORDER\_TYPE\_LIMIT
*   ORDER\_TYPE\_MARKET
*   ORDER\_TYPE\_STOP\_LOSS
*   ORDER\_TYPE\_STOP\_LOSS\_LIMIT
*   ORDER\_TYPE\_TAKE\_PROFIT
*   ORDER\_TYPE\_TAKE\_PROFIT\_LIMIT
*   ORDER\_TYPE\_TWAP

The following values can be provided for the time\_in\_force parameter:

*   ORDER\_TIME\_IN\_FORCE\_IMMEDIATE\_OR\_CANCEL
*   ORDER\_TIME\_IN\_FORCE\_GOOD\_TILL\_TIME
*   ORDER\_TIME\_IN\_FORCE\_POST\_ONLY

The SignerClient provides several functions that sign and push a type of transaction. Here’s a list of some of them:

*   _create\_order_ - signs and pushes a create order transaction;
*   [_create\_market\_order_](https://github.com/elliottech/lighter-python/blob/main/examples/create_market_order.py) - signs and pushes a create order transaction for a market order;
*   [_create\_cancel\_order_](create_cancel_order) - signs and pushes a cancel transaction for a certain order. Note that the order\_index needs to equal the client\_order\_index of the order to cancel;
*   _cancel\_all\_orders_ - signs and pushes a cancel all transactions. Note that, depending on the time\_in\_force provided, the transaction has different consequences:
    *   ORDER\_TIME\_IN\_FORCE\_IMMEDIATE\_OR\_CANCEL - ImmediateCancelAll;
    *   ORDER\_TIME\_IN\_FORCE\_GOOD\_TILL\_TIME - ScheduledCancelAll;
    *   ORDER\_TIME\_IN\_FORCE\_POST\_ONLY - AbortScheduledCancelAll.
*   _create\_auth\_token\_with\_expiry_ - creates an auth token (useful for getting data using the Api and Ws methods)

The SDK provides API classes that make calling the Lighter API easier. Here are some of them and the most important of their methods:

*   **AccountApi** - provides account data
    *   _account_ - get account data either by l1\_address or index
    *   _accounts\_by\_l1\_address_ - get data about all the accounts (master account and subaccounts)
    *   _apikeys_ - get data about the api keys of an account (use api\_key\_index = 255 for getting data about all the api keys)
*   **TransactionApi** - provides transaction related data
    *   _next\_nonce_ - get next nonce to be used for signing a transaction using a certain api key
    *   _send\_tx_ - push a transaction
    *   _send\_tx\_batch_ - push several transactions at once
*   **OrderApi** - provides data about orders, trades and the orderbook
    *   _order\_book\_details_ - get data about a specific market’s orderbook
    *   _order\_books_ - get data about all markets’ orderbooks

You can find the rest [here](https://github.com/elliottech/lighter-python/tree/main/lighter/api). We also provide an [example](https://github.com/elliottech/lighter-python/blob/main/examples/get_info.py) showing how to use some of these. For the methods that require an auth token, you can generate one using the _create\_auth\_token\_with\_expiry_ method of the **SignerClient** (the same applies to the websockets auth).

Lighter also provides access to essential info using websockets. A simple version of an **WsClient** for subscribing to account and orderbook updates is implemented [here](https://github.com/elliottech/lighter-python/blob/main/lighter/ws_client.py). You can also take it as an example implementation of such a client.

To get access to more data, you will need to connect to the websockets without the provided WsClient. You can find the streams you can connect to, how to connect, and the data they provide in the [websockets](https://apibetadocs.lighter.xyz/edit/websocket-reference) section.
