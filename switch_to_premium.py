#!/usr/bin/env python3
"""
Switch Lighter Protocol account to Premium tier
Using direct HTTP API call method
"""

import asyncio
import logging
import os
import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://mainnet.zklighter.elliot.ai"

async def switch_to_premium():
    """Switch account to Premium tier for zero fees"""
    
    # Get credentials from environment
    api_key = os.getenv("LIGHTER_KEY")
    api_secret = os.getenv("LIGHTER_SECRET")
    
    if not api_key or not api_secret:
        logger.error("Please set LIGHTER_KEY and LIGHTER_SECRET environment variables")
        return False
    
    try:
        # Create temporary lighter client to get account info and auth token
        from pylighter.client import Lighter
        temp_client = Lighter(key=api_key, secret=api_secret)
        await temp_client.init_client()
        
        account_index = temp_client.account_idx
        logger.info(f"Using account index: {account_index}")
        
        # Get auth token using the internal client
        auth_token, err = temp_client.client.create_auth_token_with_expiry(
            temp_client.client.DEFAULT_10_MIN_AUTH_EXPIRY
        )
        
        if err is not None:
            logger.error(f"Auth token creation error: {err}")
            await temp_client.cleanup()
            return False

        logger.info("🔄 Switching to Premium account...")
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                f"{BASE_URL}/api/v1/changeAccountTier",
                data={"account_index": account_index, "new_tier": "premium"},
                headers={"Authorization": auth_token},
            )
        
        if response.status_code != 200:
            logger.error(f"❌ Error switching to Premium: {response.text}")
            await temp_client.cleanup()
            return False
            
        result = response.json()
        logger.info(f"✅ Successfully switched to Premium account!")
        logger.info(f"Response: {result}")
        
        await temp_client.cleanup()
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to switch to Premium: {e}")
        return False

async def main():
    """Main function"""
    logger.info("🚀 Lighter Protocol - Account Tier Switch")
    logger.info("Switching to Premium account for zero trading fees...")
    
    success = await switch_to_premium()
    
    if success:
        logger.info("✅ Account successfully switched to Premium!")
        logger.info("Benefits:")
        logger.info("  - 0% Maker fees (was 0.002%)")
        logger.info("  - 0% Taker fees (was 0.02%)")
        logger.info("  - Perfect for grid trading strategies!")
        logger.info("  - Note: Latency increased to 200ms (maker) / 300ms (taker)")
    else:
        logger.error("❌ Failed to switch account tier")

if __name__ == "__main__":
    asyncio.run(main())