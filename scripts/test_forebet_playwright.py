import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        print("Navigating to Forebet...")
        try:
            response = await page.goto("https://www.forebet.com/en/football-tips-and-predictions-for-today/over-under-2-5-goals", wait_until="domcontentloaded", timeout=15000)
            print("Status:", response.status)
            await page.wait_for_timeout(3000)
            content = await page.content()
            print("Title:", await page.title())
            soup = BeautifulSoup(content, "html.parser")
            rows = soup.find_all("div", class_="rcnt") or soup.find_all("tr", class_="tr_short") or soup.find_all("div", class_="schema_row")
            print("Rows found:", len(rows))
            for r in rows[:5]:
                print(" ->", r.get_text(" ", strip=True)[:120])
        except Exception as e:
            print("Error:", e)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
