"""Open a Browser Use cloud browser for manual login.

Run this to log into LinkedIn, Twitter, Instagram, etc. in the cloud browser.
The authenticated sessions persist and are reused by all agent runs.

Usage:
    python scripts/login_browser_use.py

This opens a cloud browser session. Log into your accounts, then close the script.
Sessions are saved automatically to your Browser Use profile.
"""

import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings


async def main():
    settings = get_settings()
    if not settings.browser_use_api_key:
        print("ERROR: BROWSER_USE_API_KEY not set in .env")
        sys.exit(1)

    # Make sure the SDK picks up the key
    os.environ["BROWSER_USE_API_KEY"] = settings.browser_use_api_key

    try:
        from browser_use import Browser
    except ImportError:
        print("ERROR: browser-use not installed. Run: pip install browser-use")
        sys.exit(1)

    print("Opening Browser Use cloud browser for login...")
    print("Log into your accounts (LinkedIn, Twitter/X, Instagram)")
    print("Sessions will persist automatically.")
    print()
    print("Press Ctrl+C when done logging in.")
    print()

    browser = Browser(use_cloud=True)

    try:
        context = await browser.new_context()
        page = await context.get_current_page()

        sites = [
            ("LinkedIn", "https://www.linkedin.com/login"),
            ("Twitter/X", "https://x.com/i/flow/login"),
            ("Instagram", "https://www.instagram.com/accounts/login/"),
        ]

        for name, url in sites:
            print(f"\nNavigating to {name}: {url}")
            await page.goto(url)
            input(f"  Press Enter when done logging into {name} (or skip)...")

        print("\nAll logins complete! Sessions saved to Browser Use cloud.")

    except KeyboardInterrupt:
        print("\n\nSessions saved. Closing browser.")
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
