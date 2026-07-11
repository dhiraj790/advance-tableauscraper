"""Entry point – runs as an Apify Actor or locally."""
from __future__ import annotations

import asyncio
import sys
import os

from apify import Actor
from scraper import run


async def main() -> None:
    async with Actor:
        print("Starting Tableau Public scraper (Apify Actor context)…\n")
        
        # Handle input
        actor_input = await Actor.get_input() or {}
        url = actor_input.get("url")
        
        if not url:
            from config import URL
            url = URL

        # Configure proxy using Apify's Residential Proxies
        proxy_configuration = await Actor.create_proxy_configuration(groups=['RESIDENTIAL'])
        proxy_url = await proxy_configuration.new_url() if proxy_configuration else None
        
        if proxy_url:
            print("Successfully acquired Apify Proxy URL.")
        else:
            print("No Apify proxy configured or available. Running without it.")

        try:
            # Run the synchronous scraper function in a thread to avoid blocking the event loop
            best_df, worksheets = await asyncio.to_thread(run, url, proxy_url)
            
            print(f"\n{'='*60}")
            print(f"Done.  Best worksheet shape: {best_df.shape}")
            print(f"{'='*60}")
            
            # Save the primary dataframe to the default dataset (for table view)
            if not best_df.empty:
                await Actor.push_data(best_df.to_dict(orient="records"))
                print("Pushed primary extracted data to Apify Dataset.")
                
            # Optionally, we can save all worksheets to the Key-Value store
            store = await Actor.open_key_value_store()
            for name, df in worksheets.items():
                safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
                csv_data = df.to_csv(index=False, encoding="utf-8-sig")
                await store.set_value(
                    f"{safe}.csv",
                    csv_data,
                    content_type="text/csv"
                )
            print("Saved raw CSVs to Apify Key-Value Store.")
                
        except Exception as exc:
            print(f"\n✘ Scraper failed: {exc}", file=sys.stderr)
            await Actor.fail(status_message=f"Scraper failed: {exc}")


if __name__ == "__main__":
    # Ensure asyncio uses the correct selector on Windows if running locally
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())

