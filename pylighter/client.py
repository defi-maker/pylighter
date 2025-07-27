import time
import asyncio 
import logging

from datetime import datetime
from lighter import SignerClient
from pylighter.httpx import HTTPClient

logging.basicConfig(level=logging.INFO)

BASE_URL = "https://mainnet.zklighter.elliot.ai"
CHAIN_ID_MAINNET = 304
API_KEY_INDEX = 1

endpoints = {
    #https://apidocs.lighter.xyz/reference/status (root)
    'status':{
        "endpoint":"/",
        "method":"GET",
    },
    'info':{
        "endpoint":"/info",
        "method":"GET",
    },

    #https://apidocs.lighter.xyz/reference/account-1 (account)
    'account':{
        "endpoint": "/api/v1/account",
        "method": "GET",
    },
    'accounts':{
        "endpoint": "/api/v1/accounts",
        "method": "GET",
    },
    'accounts_by_l1_address':{
        "endpoint":"/api/v1/accountsByL1Address",
        "method":"GET",
    },
    'apikeys':{
        "endpoint": "/api/v1/apikeys",
        "method": "GET",
    },
    'fee_bucket':{
        "endpoint": "/api/v1/feeBucket",
        "method": "GET",
    },
    'pnl':{
        "endpoint": "/api/v1/pnl",
        "method": "GET",
    },
    'public_pools':{
        "endpoint": "/api/v1/publicPools",
        "method": "GET",
    },

    #(order)
    'account_active_orders':{
        "endpoint": "/api/v1/accountActiveOrders",
        "method": "GET",
    },
    'account_inactive_orders':{
        "endpoint": "/api/v1/accountInactiveOrders",
        "method": "GET",
    }, #TODO
    'account_orders':{
        "endpoint": "/api/v1/accountOrders",
        "method": "GET",
    },
    "limit_order":{}, #see implementation
    "cancel_order":{}, #see implementation

    'exchange_stats':{
        "endpoint": "/api/v1/exchangeStats",
        "method": "GET",
    },
    'orderbook_details':{
        "endpoint": "/api/v1/orderBookDetails",
        "method": "GET",
    },
    'orderbook_orders':{
        "endpoint": "/api/v1/orderBookOrders",
        "method": "GET",
    },
    'orderbooks':{
        'endpoint': "/api/v1/orderBooks",
        'method': "GET",
    },
    'recent_trades':{
        'endpoint': "/api/v1/recentTrades",
        'method': "GET",
    },
    'trades':{
        'endpoint': "/api/v1/trades",
        'method': "GET",
    },

    
    #https://apidocs.lighter.xyz/reference/accounttxs (transaction)
    
    #https://mainnet.zklighter.elliot.ai/api/v1/accountTxs
    'accounttxs':{
        "endpoint": "/api/v1/accountTxs",
        "method": "GET",
    },
    'blocktxs':{
        "endpoint": "/api/v1/blockTxs",
        "method": "GET",
    },
    'next_nonce': {
        "endpoint": "/api/v1/nextNonce",
        "method": "GET",
    },
    'send_tx': {
        "endpoint": "/api/v1/sendTx",
        "method": "POST",
    }, #see limit order, cancel order etc (order actions)
    'send_tx_batch': {
        "endpoint": "/api/v1/sendTxBatch",
        "method": "POST",
    }, #TODO

    'tx':{
        "endpoint": "/api/v1/tx",
        "method": "GET",
    },
    'tx_from_l1_txhash':{
        "endpoint": "/api/v1/txFromL1TxHash",
        "method": "GET",
    },
    'txs':{
        "endpoint": "/api/v1/txs",
        "method": "GET",
    },
    'withdraw_history':{
        "endpoint": "/api/v1/withdraw/history",
        "method": "GET",
    },
    'deposit_history': {
        "endpoint": "/api/v1/deposit/history",
        "method": "GET",
    },

    #https://apidocs.lighter.xyz/reference/announcement-1 (announcement)
    'announcement':{
        "endpoint": "/api/v1/announcement",
        "method": "GET",
    },
    
    #missing endpoint from OpenAPI
    'layer2_basic_info': {
        "endpoint": "/api/v1/layer2BasicInfo",
        "method": "GET",
    },

    #https://apidocs.lighter.xyz/reference/blocks (block)
    'block': {
        "endpoint": "/api/v1/block",
        "method": "GET",
    },
    'blocks':{
        "endpoint": "/api/v1/blocks",
        "method": "GET",
    },
    'current_height':{
        "endpoint": "/api/v1/currentHeight",
        "method": "GET",
    },

    #https://apidocs.lighter.xyz/reference/candlesticks (candlestick)
    'fundings':{
        "endpoint": "/api/v1/fundings",
        "method": "GET",
    },
    'candlesticks':{
        "endpoint": "/api/v1/candlesticks",
        "method": "GET",
    },

    #https://apidocs.lighter.xyz/reference/layer2basicinfo (info)
    'layer2BasicInfo':{
        "endpoint": "/api/v1/layer2BasicInfo",
        "method": "GET",
    },
}

class Lighter():
    
    def __init__(self,key=None,secret=None):
        self.key = key
        self.secret = secret
        self.http_client = HTTPClient(base_url=BASE_URL)

        self.aws_manager = None
        self.state_manager = None

        self.positions = None 
        self.orders = None 
        self.l2_dict = {}
        self.l2_update = {}

        self.shutdown = False
        
        # Initialize attributes that are set during init_client
        self.account_idx = None
        self.client = None
        self.ticker_to_idx = {}
        self.idx_to_ticker = {}
        self.ticker_to_price_precision = {}
        self.ticker_to_lot_precision = {}
        self.ticker_min_base = {}
        self.ticker_min_quote = {}
        
        return

    async def init_client(self):
        main = await self.accounts_by_l1_address()
        self.account_idx = main['sub_accounts'][0]['index']
        self.client = SignerClient(
            url=BASE_URL,
            private_key=self.secret,
            account_index=self.account_idx,
            api_key_index=API_KEY_INDEX
        )

        ticker_meta = await self.orderbooks()
        orderbooks = ticker_meta['order_books']
        
        ticker_to_idx = {}
        ticker_to_price_precision = {}
        ticker_to_lot_precision = {}
        ticker_min_base = {}
        ticker_min_quote = {}

        for ticker in orderbooks:
            ticker_to_idx[ticker['symbol']] = int(ticker['market_id'])
            ticker_to_price_precision[ticker['symbol']] = int(ticker['supported_price_decimals'])
            ticker_to_lot_precision[ticker['symbol']] = int(ticker['supported_size_decimals'])
            ticker_min_base[ticker['symbol']] = float(ticker['min_base_amount'])
            ticker_min_quote[ticker['symbol']] = float(ticker['min_quote_amount'])

        self.idx_to_ticker = {v:k for k,v in ticker_to_idx.items()}
        self.ticker_to_idx = ticker_to_idx
        self.ticker_to_price_precision = ticker_to_price_precision
        self.ticker_to_lot_precision = ticker_to_lot_precision
        self.ticker_min_base = ticker_min_base
        self.ticker_min_quote = ticker_min_quote

    async def cleanup(self):
        await self.http_client.cleanup()
        if self.client:
            await self.client.close()

    async def limit_order(
        self,
        ticker,
        amount,
        price,
        tif='GTC',
        client_order_index=None,
        is_index=False,
        reduce_only=False,
        **kwargs
    ): 
        """Create a limit order.
        
        Args:
            ticker: Market symbol (e.g., 'BTC-USD') or market ID if is_index=True
            amount: Order size (positive for buy, negative for sell)
            price: Order price
            tif: Time in force ('GTC', 'IOC', 'ALO')
            client_order_index: Client order index (optional)
            is_index: Whether ticker is a market ID (default: False)
            reduce_only: Whether this is a reduce-only order (default: False)
        
        Returns:
            Order creation response from the API
        """
        if client_order_index is None:
            client_order_index = SignerClient.ORDER_TYPE_LIMIT
        
        # Validate TIF
        tif_map = {'GTC': 1, 'IOC': 0, 'ALO': 2}
        if tif not in tif_map:
            raise ValueError(f"Invalid TIF: {tif}. Must be one of {list(tif_map.keys())}")
        tif = tif_map[tif]
        
        # Validate amount and price
        if amount == 0:
            raise ValueError("Amount cannot be zero")
        if price <= 0:
            raise ValueError("Price must be positive")
        
        market_id = self.ticker_to_idx[ticker] if not is_index else ticker
        is_ask = amount < 0  # Negative amount = sell/ask
        
        # Validate minimum amounts
        ticker_key = ticker if not is_index else self.idx_to_ticker.get(ticker, ticker)
        if ticker_key in self.ticker_min_base and abs(amount) < self.ticker_min_base[ticker_key]:
            raise ValueError(f"Minimum base amount for {ticker_key} is {self.ticker_min_base[ticker_key]}")
        if ticker_key in self.ticker_min_quote:
            quote = self.ticker_min_quote[ticker_key]
            if abs(amount) * price < quote:
                raise ValueError(f"Minimum quote amount for {ticker_key} is {quote}")
        
        # Apply precision
        price_precision = self.ticker_to_price_precision.get(ticker_key, 0)
        lot_precision = self.ticker_to_lot_precision.get(ticker_key, 0)
        price = round(price * 10**price_precision)
        base_amount = round(abs(amount) * 10**lot_precision)
        
        return await self.client.create_order(
            market_index=market_id,
            client_order_index=client_order_index,
            base_amount=base_amount,
            price=price,
            is_ask=is_ask,
            order_type=0, #ORDER_TYPE_LIMIT
            time_in_force=tif,
            reduce_only=int(reduce_only),
            trigger_price=0
        )

    async def market_order(
        self,
        ticker,
        amount,
        tif='IOC',  # Market orders should typically be IOC
        reduce_only=False,
        slippage_tolerance=0.03,
        is_index=False,
        **kwargs
    ):
        """Create a market order by using a limit order with market price + slippage.
        
        Args:
            ticker: Market symbol (e.g., 'BTC-USD') or market ID if is_index=True
            amount: Order size (positive for buy, negative for sell)
            tif: Time in force (default: 'IOC' for market orders)
            reduce_only: Whether this is a reduce-only order (default: False)
            slippage_tolerance: Slippage tolerance as decimal (default: 0.03 = 3%)
            is_index: Whether ticker is a market ID (default: False)
        
        Returns:
            Order creation response from the API
        """
        if amount == 0:
            raise ValueError("Amount cannot be zero")
        if not 0 <= slippage_tolerance <= 1:
            raise ValueError("Slippage tolerance must be between 0 and 1")
        
        market_id = self.ticker_to_idx[ticker] if not is_index else ticker
        lob = await self.orderbook_orders(market_id, is_index=True)
        
        if not lob.get('bids') or not lob.get('asks'):
            raise ValueError(f"No orderbook data available for {ticker}")
        
        bids = lob['bids']
        asks = lob['asks']
        bb = float(bids[0]['price'])
        aa = float(asks[0]['price'])
        
        # For market orders, use the opposite side of the book with slippage
        if amount > 0:  # Buy order - use ask price with positive slippage
            price = aa * (1 + slippage_tolerance)
        else:  # Sell order - use bid price with negative slippage
            price = bb * (1 - slippage_tolerance)
        
        return await self.limit_order(
            ticker=ticker,
            amount=amount,
            price=price,
            tif=tif,
            reduce_only=reduce_only,
            is_index=is_index,
            **kwargs
        )

    async def cancel_order(self,ticker,order_id,is_index=False):
        market_id = self.ticker_to_idx[ticker] if not is_index else ticker
        return await self.client.cancel_order(
            market_index=market_id,
            order_index=int(order_id)
        )
    
    async def cancel_all_orders(self):
        """Cancel all orders for the account.
        
        Note: This cancels ALL orders across all markets, not just a specific ticker.
        The official Lighter SDK does not support per-ticker bulk cancellation.
        
        Returns:
            Response from the cancel_all_orders endpoint
        """
        # Use immediate cancellation parameters
        time_in_force = 0  # ImmediateCancelAll
        cancel_time = 0  # NilOrderExpiry - MUST be 0 for immediate cancellation
        
        return await self.client.cancel_all_orders(
            time_in_force=time_in_force,
            time=cancel_time
        )
    
    async def send_tx_batch(self, transactions):
        """Send a batch of transactions to the Lighter protocol.
        
        Args:
            transactions: List of transaction objects to send in batch
        
        Returns:
            Response from the send_tx_batch endpoint
        """
        return await self.client.send_tx_batch(transactions)
        
    async def status(self):
        endpoint = dict(endpoints['status'])
        return await self.http_client.request(
            **endpoint,
            params={}
        )

    async def info(self):
        endpoint = dict(endpoints['info'])
        return await self.http_client.request(
            **endpoint,
            params={}
        )

    async def account(self,by='l1_address',value=None):
        endpoint = dict(endpoints['account'])
        account_idx = self.account_idx
        endpoint['params'] = {
            'by':by,
            'value':self.key if by == 'l1_address' else account_idx
        }
        return await self.http_client.request(
            **endpoint,
        )

    async def accounts(self, limit=100, index=None, **kwargs):
        endpoint = dict(endpoints['accounts'])
        endpoint['params'] = {
            'limit': limit,
            **kwargs
        }
        if index is not None:
            endpoint['params']['index'] = index
        return await self.http_client.request(
            **endpoint,
        )

    async def accounts_by_l1_address(self):
        '''
        account index > integer used by lighter to identify wallet
        sub_accounts[0] > your main account, sub_accounts[0]['index'] is your account index.
        '''
        endpoint = dict(endpoints['accounts_by_l1_address'])
        endpoint['params'] = {
            'l1_address':self.key
        }
        return await self.http_client.request(
            **endpoint,
        )   

    async def apikeys(self,account_idx=None,api_key_index=255):
        account_idx = account_idx or self.account_idx
        endpoint = dict(endpoints['apikeys'])
        endpoint['params'] = {
            'account_index':account_idx,
            'api_key_index':api_key_index
        }
        return await self.http_client.request(
            **endpoint,
        )
        
    async def fee_bucket(self,account_idx=None):
        account_idx = account_idx or self.account_idx
        endpoint = dict(endpoints['fee_bucket'])
        endpoint['params'] = {
            'account_index':account_idx
        }
        return await self.http_client.request(
            **endpoint,
        )
    
    async def pnl(self, by="index", account_idx=None, start=None, end=None, resolution='1h', count_back=2, ignore_transfers=False, **kwargs):
        value = account_idx or self.account_idx
        start = start or int(datetime.now().timestamp() - 60 * 60 * 24)
        end = end or int(datetime.now().timestamp())
        endpoint = dict(endpoints['pnl'])
        endpoint['params'] = {
            'by': by,
            'value': str(value),
            'resolution': resolution,
            'start_timestamp': start,
            'end_timestamp': end,
            'count_back': count_back,
            'ignore_transfers': ignore_transfers,
            **kwargs
        }
        # PnL endpoint may require auth based on OpenAPI spec
        auth, err = self.client.create_auth_token_with_expiry(SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY)
        if not err:  # Only add auth if no error
            endpoint['params']['auth'] = auth
        return await self.http_client.request(
            **endpoint,
        )

    async def public_pools(self, index=0, limit=100, filter='all', account_idx=None, **kwargs):
        endpoint = dict(endpoints['public_pools'])
        endpoint['params'] = {
            'index': index,
            'limit': limit,
            **kwargs
        }
        if filter != 'all':
            endpoint['params']['filter'] = filter
        if account_idx is not None:
            endpoint['params']['account_index'] = account_idx
        # Add auth if filtering by account
        if filter == 'account_index' or account_idx is not None:
            auth, err = self.client.create_auth_token_with_expiry(SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY)
            if err:
                raise ValueError(err)
            endpoint['params']['auth'] = auth
        return await self.http_client.request(
            **endpoint,
        )
    
    # DEPRECATED - Use account_orders instead
    async def account_active_orders(self,ticker,account_idx=None,is_index=False,**kwargs):
        """
        DEPRECATED: This endpoint returns 403 errors. Use account_orders instead.
        """
        logger.warning("account_active_orders is deprecated and returns 403 errors. Use account_orders instead.")
        # Fallback to account_orders
        return await self.account_orders(ticker, account_idx, is_index=is_index, **kwargs)

    async def account_inactive_orders(self, ticker=None, account_idx=None, ask_filter=-1, between_timestamps=None, cursor=None, limit=100, is_index=False):
        account_idx = account_idx or self.account_idx
        auth, err = self.client.create_auth_token_with_expiry(SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY)
        if err:
            raise ValueError(err)
        endpoint = dict(endpoints['account_inactive_orders'])
        endpoint['params'] = {
            'auth': auth,
            'account_index': account_idx,
            'limit': limit
        }
        if ticker is not None:
            market_id = self.ticker_to_idx[ticker] if not is_index else ticker
            endpoint['params']['market_id'] = market_id
        else:
            endpoint['params']['market_id'] = 255  # Default for all markets
        if ask_filter != -1:
            endpoint['params']['ask_filter'] = ask_filter
        if between_timestamps:
            endpoint['params']['between_timestamps'] = between_timestamps
        if cursor:
            endpoint['params']['cursor'] = cursor
        return await self.http_client.request(
            **endpoint,
        )

    async def account_orders(self,ticker,account_idx=None,cursor=None,is_index=False,limit=100):
        market_id = self.ticker_to_idx[ticker] if not is_index else ticker 
        account_idx = account_idx or self.account_idx
        auth, err = self.client.create_auth_token_with_expiry(SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY)
        if err:
            raise ValueError(err)
        endpoint = dict(endpoints['account_orders'])
        endpoint['params'] = {
            'auth': auth,
            'account_index':account_idx,
            'market_id':market_id,
            'limit':limit
        }
        if cursor:
            endpoint['params']['cursor'] = cursor
        return await self.http_client.request(
            **endpoint,
        )

    async def exchange_stats(self):
        endpoint = dict(endpoints['exchange_stats'])
        return await self.http_client.request(
            **endpoint,
        )

    async def orderbook_details(self,ticker=None,is_index=False):
        endpoint = dict(endpoints['orderbook_details'])
        if ticker is not None:
            market_id = self.ticker_to_idx[ticker] if not is_index else ticker
            endpoint['params'] = {'market_id':market_id}
        return await self.http_client.request(
            **endpoint,
        )

    async def orderbook_orders(self,ticker,limit=100,is_index=False,**kwargs):
        endpoint = dict(endpoints['orderbook_orders'])
        market_id = self.ticker_to_idx[ticker] if not is_index else ticker
        endpoint['params'] = {
            'market_id':market_id,
            'limit':limit,
            **kwargs
        }
        return await self.http_client.request(
            **endpoint,
        )

    async def orderbooks(self,ticker=None,is_index=False):
        endpoint = dict(endpoints['orderbooks'])
        if ticker is not None:
            market_id = self.ticker_to_idx[ticker] if not is_index else ticker
            endpoint['params'] = {'market_id':market_id}
        return await self.http_client.request(
            **endpoint,
        )

    async def recent_trades(self,ticker,limit=100,is_index=False,**kwargs):
        endpoint = dict(endpoints['recent_trades'])
        market_id = self.ticker_to_idx[ticker] if not is_index else ticker
        endpoint['params'] = {
            'market_id':market_id,
            'limit':limit,
            **kwargs
        }
        return await self.http_client.request(
            **endpoint,
        )
    
    async def trades(self, ticker=None, account_idx=None, order_index=None, limit=100, sort_by='timestamp', sort_dir='asc', cursor=None, from_id=None, ask_filter=-1, is_index=False, **kwargs):
        endpoint = dict(endpoints['trades'])
        endpoint['params'] = {
            'limit': limit,
            'sort_by': sort_by,
            'sort_dir': sort_dir,
            **kwargs
        }
        if ticker is not None:
            market_id = self.ticker_to_idx[ticker] if not is_index else ticker
            endpoint['params']['market_id'] = market_id
        else:
            endpoint['params']['market_id'] = 255  # Default for all markets
        if account_idx is not None:
            endpoint['params']['account_index'] = account_idx
        else:
            endpoint['params']['account_index'] = -1  # Default for all accounts
        if order_index is not None:
            endpoint['params']['order_index'] = order_index
        if cursor:
            endpoint['params']['cursor'] = cursor
        if from_id is not None:
            endpoint['params']['from'] = from_id
        if ask_filter != -1:
            endpoint['params']['ask_filter'] = ask_filter
        # Add auth if filtering by account
        if account_idx is not None:
            auth, err = self.client.create_auth_token_with_expiry(SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY)
            if err:
                raise ValueError(err)
            endpoint['params']['auth'] = auth
        return await self.http_client.request(
            **endpoint,
        )

    async def accounttxs(self, account_idx=None, by='account_index', limit=100, index=None, types=None, **kwargs):
        account_idx = account_idx or self.account_idx
        endpoint = dict(endpoints['accounttxs'])
        endpoint['params'] = {
            'by': by,
            'value': str(account_idx),
            'limit': limit,
            **kwargs
        }
        if index is not None:
            endpoint['params']['index'] = index
        if types is not None:
            endpoint['params']['types'] = types
        return await self.http_client.request(
            **endpoint,
        )

    async def blocktxs(self,commitment=None,height=None):
        endpoint = dict(endpoints['blocktxs'])
        endpoint['params'] = {
            'by':'block_commitment' if commitment else 'block_height',
            'value':commitment or height
        }
        return await self.http_client.request(
            **endpoint,
        )

    async def deposit_history(self, account_idx=None, cursor=None, filter='all'):
        account_idx = account_idx or self.account_idx
        auth, err = self.client.create_auth_token_with_expiry(SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY)
        if err:
            raise ValueError(err)
        endpoint = dict(endpoints['deposit_history'])
        endpoint['params'] = {
            'account_index': account_idx,
            'auth': auth,
            'l1_address': self.key
        }
        if cursor:
            endpoint['params']['cursor'] = cursor
        if filter != 'all':
            endpoint['params']['filter'] = filter
        return await self.http_client.request(
            **endpoint,
        ) 
    
    async def next_nonce(self,account_idx=None,api_key_index=0):
        account_idx = account_idx or self.account_idx
        endpoint = dict(endpoints['next_nonce'])
        endpoint['params'] = {
            'account_index':account_idx,
            'api_key_index':api_key_index
        }
        return await self.http_client.request(
            **endpoint,
        )

    async def tx(self, by='hash', value=None):
        if value is None:
            raise ValueError("Value parameter is required")
        endpoint = dict(endpoints['tx'])
        endpoint['params'] = {
            'by': by,
            'value': value
        }
        return await self.http_client.request(
            **endpoint,
        ) 
    
    async def tx_from_l1_txhash(self, hash):
        endpoint = dict(endpoints['tx_from_l1_txhash'])
        endpoint['params'] = {
            'hash': hash
        }
        return await self.http_client.request(
            **endpoint,
        ) 
    
    async def txs(self, index=None, limit=100):
        endpoint = dict(endpoints['txs'])
        endpoint['params'] = {
            'limit': limit
        }
        if index is not None:
            endpoint['params']['index'] = index
        return await self.http_client.request(
            **endpoint,
        )
    
    async def withdraw_history(self, account_idx=None, cursor=None, filter='all'):
        account_idx = account_idx or self.account_idx
        auth, err = self.client.create_auth_token_with_expiry(SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY)
        if err:
            raise ValueError(err)
        endpoint = dict(endpoints['withdraw_history'])
        endpoint['params'] = {
            'account_index': account_idx,
            'auth': auth
        }
        if cursor:
            endpoint['params']['cursor'] = cursor
        if filter != 'all':
            endpoint['params']['filter'] = filter
        return await self.http_client.request(
            **endpoint,
        )

    async def announcement(self):
        endpoint = dict(endpoints['announcement'])
        return await self.http_client.request(
            **endpoint,
        )

    async def block(self,commitment=None,height=None):
        endpoint = dict(endpoints['block'])
        endpoint['params'] = {
            'by':'commitment' if commitment else 'height',
            'value':commitment or height
        }
        return await self.http_client.request(
            **endpoint,
        )

    async def blocks(self, limit=100, index=None, sort='asc', **kwargs):
        endpoint = dict(endpoints['blocks'])
        endpoint['params'] = {
            'limit': limit,
            'sort': sort,
            **kwargs
        }
        if index is not None:
            endpoint['params']['index'] = index
        return await self.http_client.request(
            **endpoint,
        )

    async def current_height(self):  
        endpoint = dict(endpoints['current_height'])
        return await self.http_client.request(
            **endpoint,
        )

    async def fundings(self,ticker,resolution='1h',start=None,end=None,count_back=2,is_index=False,**kwargs):
        market_id = self.ticker_to_idx[ticker] if not is_index else ticker
        start = start or int(datetime.now().timestamp() - 60 * 60 * 24)
        end = end or int(datetime.now().timestamp())
        endpoint = dict(endpoints['fundings'])
        endpoint['params'] = {
            'market_id':market_id,
            'resolution':resolution,
            'start_timestamp':start,
            'end_timestamp':end,
            'count_back':count_back,
            **kwargs
        }
        return await self.http_client.request(
            **endpoint,
        )

    async def candlesticks(self,ticker,resolution='1h',start=None,end=None,count_back=2,set_timestamp_to_end=False,is_index=False,**kwargs):
        market_id = self.ticker_to_idx[ticker] if not is_index else ticker
        start = start or int(datetime.now().timestamp() - 60 * 60 * 24)
        end = end or int(datetime.now().timestamp())
        endpoint = dict(endpoints['candlesticks'])
        endpoint['params'] = {
            'market_id':market_id,
            'resolution':resolution,
            'start_timestamp':start,
            'end_timestamp':end,
            'count_back':count_back,
            'set_timestamp_to_end':set_timestamp_to_end,
            **kwargs
        }
        return await self.http_client.request(
            **endpoint,
        )

    async def layer2_basic_info(self):
        endpoint = dict(endpoints['layer2_basic_info'])
        return await self.http_client.request(
            **endpoint,
        )
    
    # Keep backward compatibility
    async def layer2BasicInfo(self):
        return await self.layer2_basic_info()
    
    async def update_leverage(self, ticker, leverage, is_index=False):
        """
        Update leverage for a specific market
        
        Args:
            ticker: Symbol like 'TON', 'XRP', 'TRX' (or market_id if is_index=True)
            leverage: Leverage multiplier (e.g., 1 for 1x, 2 for 2x, etc.)
            is_index: If True, ticker is treated as market_id
            
        Returns:
            Tuple of (tx_info, tx_hash, error)
        """
        market_id = ticker if is_index else self.ticker_to_idx[ticker]
        
        # Convert leverage to initial margin fraction
        # Formula: margin_fraction = 10000 / leverage
        # 1x leverage = 10000 basis points (100% margin)
        # 2x leverage = 5000 basis points (50% margin)
        # 5x leverage = 2000 basis points (20% margin)
        margin_fraction = int(10000 / leverage)
        
        # Sign the update leverage transaction with margin fraction
        tx_info, error = self.client.sign_update_leverage(
            market_index=market_id,
            leverage=margin_fraction  # This parameter is actually margin fraction, not direct leverage
        )
        
        if error is not None:
            return None, None, error
            
        # Send the transaction with correct TX_TYPE
        try:
            # From lighter-go constants: TxTypeL2UpdateLeverage = 20
            tx_type = 20
            api_response = await self.client.send_tx(tx_type=tx_type, tx_info=tx_info)
            return tx_info, api_response, None
            
        except Exception as e:
            return None, None, str(e)
    
    # ==================== 通用市场约束和交易工具方法 ====================
    
    async def get_market_constraints(self, ticker, is_index=False):
        """
        获取特定交易对的市场约束信息
        
        Args:
            ticker: 交易对符号 (如 'TON', 'BTC-USD') 或市场ID (如果 is_index=True)
            is_index: 如果为 True，ticker 被视为市场ID
            
        Returns:
            dict: 包含市场约束的字典:
            {
                'min_base_amount': float,
                'min_quote_amount': float,
                'price_precision': int,
                'amount_precision': int,
                'market_id': int
            }
        """
        try:
            market_id = ticker if is_index else self.ticker_to_idx.get(ticker)
            if market_id is None:
                raise ValueError(f"Market not found for ticker: {ticker}")
                
            ticker_key = ticker if not is_index else self.idx_to_ticker.get(ticker, str(ticker))
            
            # 从预加载的数据中获取约束
            constraints = {
                'min_base_amount': self.ticker_min_base.get(ticker_key, 1.0),
                'min_quote_amount': self.ticker_min_quote.get(ticker_key, 10.0),
                'price_precision': self.ticker_to_price_precision.get(ticker_key, 6),
                'amount_precision': self.ticker_to_lot_precision.get(ticker_key, 1),
                'market_id': market_id
            }
            
            # 如果预加载数据不完整，从API获取详细信息
            if constraints['min_quote_amount'] == 10.0:  # 默认值，可能需要更新
                try:
                    details = await self.orderbook_details(ticker_key)
                    if 'order_book_details' in details and details['order_book_details']:
                        market_data = details['order_book_details'][0]
                        constraints.update({
                            'min_base_amount': float(market_data.get('min_base_amount', constraints['min_base_amount'])),
                            'min_quote_amount': float(market_data.get('min_quote_amount', constraints['min_quote_amount'])),
                            'price_precision': int(market_data.get('supported_price_decimals', constraints['price_precision'])),
                            'amount_precision': int(market_data.get('supported_size_decimals', constraints['amount_precision']))
                        })
                except Exception:
                    # 如果API调用失败，使用预加载的数据
                    pass
                    
            return constraints
            
        except Exception as e:
            raise ValueError(f"Failed to get market constraints for {ticker}: {e}")
    
    def format_price(self, price, ticker, is_index=False):
        """
        根据市场精度格式化价格
        
        Args:
            price: 原始价格
            ticker: 交易对符号或市场ID
            is_index: 如果为 True，ticker 被视为市场ID
            
        Returns:
            float: 格式化后的价格
        """
        ticker_key = ticker if not is_index else self.idx_to_ticker.get(ticker, str(ticker))
        precision = self.ticker_to_price_precision.get(ticker_key, 6)
        return round(float(price), precision)
    
    def format_quantity(self, quantity, ticker, is_index=False):
        """
        根据市场精度格式化数量
        
        Args:
            quantity: 原始数量
            ticker: 交易对符号或市场ID
            is_index: 如果为 True，ticker 被视为市场ID
            
        Returns:
            float: 格式化后的数量
        """
        ticker_key = ticker if not is_index else self.idx_to_ticker.get(ticker, str(ticker))
        precision = self.ticker_to_lot_precision.get(ticker_key, 1)
        
        if precision > 0:
            precision_factor = 10 ** precision
            return int(float(quantity) * precision_factor + 0.999) / precision_factor
        else:
            return round(float(quantity))
    
    def calculate_min_quantity_for_quote_amount(self, price, min_quote_amount, ticker, is_index=False):
        """
        计算满足最小报价金额要求的数量
        
        Args:
            price: 当前价格
            min_quote_amount: 最小报价金额
            ticker: 交易对符号或市场ID
            is_index: 如果为 True，ticker 被视为市场ID
            
        Returns:
            float: 满足最小报价金额的数量
        """
        if price <= 0:
            raise ValueError("Price must be positive")
            
        base_quantity = min_quote_amount / price
        return self.format_quantity(base_quantity, ticker, is_index)
    
    def validate_order_amount(self, price, quantity, ticker, is_index=False):
        """
        验证订单金额是否满足最小要求
        
        Args:
            price: 订单价格
            quantity: 订单数量
            ticker: 交易对符号或市场ID
            is_index: 如果为 True，ticker 被视为市场ID
            
        Returns:
            tuple: (is_valid: bool, adjusted_quantity: float, error_message: str)
        """
        try:
            ticker_key = ticker if not is_index else self.idx_to_ticker.get(ticker, str(ticker))
            
            # 检查最小基础数量
            min_base = self.ticker_min_base.get(ticker_key, 0)
            if abs(quantity) < min_base:
                adjusted_quantity = min_base if quantity > 0 else -min_base
                return False, adjusted_quantity, f"Quantity {abs(quantity)} below minimum {min_base}"
            
            # 检查最小报价金额
            min_quote = self.ticker_min_quote.get(ticker_key, 0)
            quote_amount = abs(quantity) * price
            if quote_amount < min_quote:
                adjusted_quantity = self.calculate_min_quantity_for_quote_amount(price, min_quote, ticker, is_index)
                if quantity < 0:
                    adjusted_quantity = -adjusted_quantity
                return False, adjusted_quantity, f"Quote amount ${quote_amount:.2f} below minimum ${min_quote}"
            
            # 格式化数量以符合精度要求
            formatted_quantity = self.format_quantity(quantity, ticker, is_index)
            
            return True, formatted_quantity, ""
            
        except Exception as e:
            return False, quantity, f"Validation error: {e}"
