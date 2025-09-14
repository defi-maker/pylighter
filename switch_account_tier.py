#!/usr/bin/env python3
"""
Switch Lighter Protocol account between Premium and Standard tiers
Using direct HTTP API call method
"""

import argparse
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

async def get_current_tier():
    """Get current account tier from API using accountLimits endpoint"""

    # Get credentials from environment
    api_key = os.getenv("LIGHTER_KEY")
    api_secret = os.getenv("LIGHTER_SECRET")

    if not api_key or not api_secret:
        logger.error("Please set LIGHTER_KEY and LIGHTER_SECRET environment variables")
        return None

    try:
        # Create temporary lighter client to get account index and auth token
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
            return None

        # Use accountLimits API to get current tier information
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(
                f"{BASE_URL}/api/v1/accountLimits?account_index={account_index}",
                headers={
                    "Authorization": auth_token,
                    "Accept": "*/*",
                    "PreferAuthServer": "true",
                }
            )

        await temp_client.cleanup()

        if response.status_code != 200:
            logger.error(f"Failed to get account limits: {response.status_code} - {response.text}")
            return None

        account_limits = response.json()
        logger.debug(f"Account limits response: {account_limits}")

        # Extract tier from account limits response
        # The API returns: {"code": 200, "user_tier": "premium", ...}
        if 'user_tier' in account_limits:
            current_tier = account_limits['user_tier'].lower()
            logger.info(f"📊 Current account tier: {current_tier.title()}")
            return current_tier
        else:
            logger.error(f"Could not find user_tier in response: {account_limits}")
            return None

    except Exception as e:
        logger.error(f"Failed to get current tier: {e}")
        return None

async def switch_account_tier(target_tier: str):
    """Switch account tier between Premium and Standard"""
    
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

        logger.info(f"🔄 Switching to {target_tier.title()} account...")
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                f"{BASE_URL}/api/v1/changeAccountTier",
                data={"account_index": account_index, "new_tier": target_tier.lower()},
                headers={"Authorization": auth_token},
            )

        if response.status_code != 200:
            logger.error(f"❌ Error switching to {target_tier.title()}: {response.text}")
            await temp_client.cleanup()
            return False

        result = response.json()
        logger.info(f"✅ Successfully switched to {target_tier.title()} account!")
        logger.info(f"Response: {result}")
        
        await temp_client.cleanup()
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to switch to {target_tier.title()}: {e}")
        return False

def get_tier_info(tier: str) -> dict:
    """Get tier-specific information"""
    if tier.lower() == "premium":
        return {
            "fees": "0.002% Maker / 0.02% Taker",
            "latency": "0ms maker/cancel / 150ms taker",
            "benefits": [
                "Lowest latency on Lighter",
                "Perfect for high-frequency trading",
                "Part of volume quota program",
                "Small fees but fastest execution"
            ]
        }
    else:  # standard
        return {
            "fees": "0% Maker / 0% Taker",
            "latency": "200ms maker/cancel / 300ms taker",
            "benefits": [
                "Zero trading fees",
                "Perfect for grid trading strategies",
                "Suitable for retail traders",
                "Higher latency but no fees"
            ]
        }

async def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Switch Lighter Protocol account between Premium and Standard tiers"
    )
    parser.add_argument(
        "--tier",
        choices=["premium", "standard"],
        help="Target account tier (if not specified, switches to opposite of current tier)"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt"
    )

    args = parser.parse_args()

    logger.info("🚀 Lighter Protocol - Account Tier Switch")

    # Determine target tier
    if args.tier:
        target_tier = args.tier
        logger.info(f"Target tier specified: {target_tier.title()}")
    else:
        # Auto-detect current tier and switch to opposite
        logger.info("🔍 Detecting current account tier...")
        current_tier = await get_current_tier()

        if current_tier is None:
            logger.error("❌ Could not detect current tier. Please specify --tier manually.")
            return

        # Switch to opposite tier
        if current_tier == "premium":
            target_tier = "standard"
        else:
            target_tier = "premium"

        logger.info(f"🔄 Auto-switching from {current_tier.title()} to {target_tier.title()}")

    # Show tier comparison
    if not args.tier:  # Only show comparison when auto-switching
        current_info = get_tier_info(current_tier)
        target_info = get_tier_info(target_tier)
        logger.info(f"\n📈 Tier Switch Summary:")
        logger.info(f"  From: {current_tier.title()} ({current_info['fees']})")
        logger.info(f"  To:   {target_tier.title()} ({target_info['fees']})")
    else:
        target_info = get_tier_info(target_tier)
        logger.info(f"\n🎯 Target tier: {target_tier.title()}")
        logger.info(f"  Fees: {target_info['fees']}")
        logger.info(f"  Latency: {target_info['latency']}")

    # Confirmation prompt (unless --confirm is used)
    if not args.confirm:
        logger.info("\n⚠️  IMPORTANT REQUIREMENTS:")
        logger.info("  - You must have no open positions")
        logger.info("  - You must have no open orders")
        logger.info("  - At least 3 hours must have passed since last tier change")

        confirm = input(f"\nConfirm switch to {target_tier.title()} tier? (yes/no): ")
        if confirm.lower() not in ['yes', 'y']:
            logger.info("❌ Operation cancelled by user")
            return

    success = await switch_account_tier(target_tier)

    if success:
        logger.info(f"✅ Account successfully switched to {target_tier.title()}!")
        logger.info("Benefits:")
        # Use the already defined target_info, or get it if not defined
        if 'target_info' not in locals():
            target_info = get_tier_info(target_tier)
        for benefit in target_info['benefits']:
            logger.info(f"  - {benefit}")
    else:
        logger.error("❌ Failed to switch account tier")

if __name__ == "__main__":
    asyncio.run(main())