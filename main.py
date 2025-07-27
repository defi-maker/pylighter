import os
import asyncio 
from dotenv import load_dotenv
load_dotenv()

key = os.getenv("LIGHTER_KEY")
secret = os.getenv("LIGHTER_SECRET")

from pylighter.client import Lighter

async def main():
    lighter = Lighter(
        key=key,
        secret=secret,
    )
    await lighter.init_client()
    print(await lighter.status())
    print(await lighter.info())
    print(await lighter.account())
    #print(await lighter.accounts())
    print(await lighter.accounts_by_l1_address())
    print(await lighter.apikeys())
    #print(await lighter.fee_bucket())
    #print(await lighter.pnl())
    print(await lighter.public_pools())
    print(await lighter.exchange_stats())

    await lighter.cleanup()

    

if __name__ == "__main__":
    asyncio.run(main())
