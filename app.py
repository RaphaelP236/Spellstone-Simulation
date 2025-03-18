import streamlit as st
import asyncio
import sys
from playwright.async_api import async_playwright
from tqdm.asyncio import tqdm
import nest_asyncio
import subprocess

# Ensure Playwright browser binaries are installed
subprocess.run(["python", "-m", "playwright", "install"])

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
nest_asyncio.apply()


# Define constants
bge = "9C!C"
tower_type = 506


async def load_page_with_retry(page, url, retries=3):
    attempt = 0
    while attempt < retries:
        try:
            await page.goto(url, timeout=100000)
            return True
        except Exception:
            attempt += 1
    return False


async def run_simulation(attack_deck, defense_deck, context):
    url = f"https://vuzaldo.github.io/SIMSpellstone/Titans.html?deck1={attack_deck}&deck2={defense_deck}&mission_level=7&raid_level=25&siege&tower_level=18&tower_type={tower_type}&bges={bge}&sims=100000&autostart"

    page = await context.new_page()
    try:
        success = await load_page_with_retry(page, url)
        if not success:
            return None
        if await page.query_selector("#winrate"):
            winrate = await page.inner_text("#winrate")
            return winrate.strip()
        return None
    except Exception:
        return None
    finally:
        await page.close()


async def simulate_pair(pair, context, semaphore, pbar):
    async with semaphore:
        attack_deck, defense_deck = pair
        result = await run_simulation(attack_deck, defense_deck, context)
        pbar.update(1)
        return (attack_deck, defense_deck, result)


async def run_simulations_parallel(attack_decks, defense_decks):
    deck_pairs = [(attack_deck, defense_deck) for attack_deck in attack_decks for defense_deck in defense_decks]
    total_simulations = len(deck_pairs)
    semaphore = asyncio.Semaphore(10)

    with tqdm(total=total_simulations, desc="Simulations Progress", unit="sim") as pbar:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)  # No --no-sandbox argument
            context = await browser.new_context()
            tasks = [simulate_pair(pair, context, semaphore, pbar) for pair in deck_pairs]
            results = await asyncio.gather(*tasks)
            await browser.close()

    return results


async def optimize_defense(attack_decks, defense_deck_hash):
    prev_winrate = 100
    card_hashes = [defense_deck_hash[i:i + 5] for i in range(5, 80, 5)]  # Assuming 5-char card hashes
    seen_card_hashes = set()
    modified_decks = []
    removed_cards = []

    for card_hash in card_hashes:
        if card_hash in seen_card_hashes:
            continue
        seen_card_hashes.add(card_hash)
        modified_deck = defense_deck_hash.replace(card_hash, "")
        modified_decks.append(modified_deck)
        removed_cards.append(card_hash)

    initial_results = await run_simulations_parallel(attack_decks, [defense_deck_hash])
    winrates = [float(result[2].strip('%')) for result in initial_results if result[2]]

    avg_winrate = sum(winrates) / len(winrates) if winrates else 0
    results = await run_simulations_parallel(attack_decks, modified_decks)

    avg_winrates = {}
    for i, modified_deck in enumerate(modified_decks):
        total_winrate = sum(
            float(winrate.strip('%')) for attack, defense, winrate in results if defense == modified_deck and winrate)
        avg_winrates[removed_cards[i]] = total_winrate / len(attack_decks)

    weakest_card = min(avg_winrates, key=avg_winrates.get)
    weakest_card_index = removed_cards.index(weakest_card)

    return avg_winrate, weakest_card, avg_winrates[weakest_card], modified_decks[weakest_card_index]


async def run_optimization(attack_decks, defense_deck_hash):
    return await optimize_defense(attack_decks, defense_deck_hash)


def main():
    st.title("Defense Deck Optimizer")
    st.write("Optimize your defense deck by identifying the weakest card.")

    attack_decks_input = st.text_area("Enter Attack Deck Hashes (one per line)")
    defense_deck_hash = st.text_input("Enter Defense Deck Hash")

    if st.button("Run Optimization"):
        if not attack_decks_input or not defense_deck_hash:
            st.error("Please enter both attack deck hashes and a defense deck hash.")
            return

        attack_decks = [line.strip() for line in attack_decks_input.split("\n") if line.strip()]

        with st.spinner("Running simulations... this may take a while."):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            avg_winrate, weakest_card, new_winrate, new_deck_hash = loop.run_until_complete(
                run_optimization(attack_decks, defense_deck_hash)
            )

        st.write(f"**Average Winrate Before:** {avg_winrate:.2f}%")
        st.write(f"**Weakest Card:** {weakest_card} (Winrate: {new_winrate:.2f}%)")
        st.write(f"**New Optimized Deck Hash:** `{new_deck_hash}`")


if __name__ == "__main__":
    main()