import streamlit as st
import asyncio
import sys
from playwright.async_api import async_playwright
from tqdm.asyncio import tqdm
import nest_asyncio
import subprocess

# Ensure Playwright is installed and necessary browsers are available
try:
    import playwright
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])

# Install the necessary browser binaries
subprocess.check_call([sys.executable, "-m", "playwright", "install"])


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
nest_asyncio.apply()


# Define constants
bge = "9C!C"
tower_type = 501


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
            browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
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
        modified_deck = defense_deck_hash.replace(card_hash, "",1)
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


    return avg_winrate, avg_winrates, removed_cards


async def run_optimization(attack_decks, defense_deck_hash):
    return await optimize_defense(attack_decks, defense_deck_hash)


st.set_page_config(layout="wide")  # Ensure full-width layout



def main():
    st.title("Family Simulation Tool")
    # Create two columns for layout
    col1, col2 = st.columns(2)  # Left (narrower) | Right (wider)


    # Input fields and Run button (Left side)
    with col1:
        st.header("Inputs")
        defense_deck_hash = st.text_input("Your deck")
        attack_decks_input = st.text_area("Opponents decks (one per line per hash)")
        st.radio("What deck do you want to optimze?",["Offence", "Defence"])
        c1, c2 = st.columns(2)
        with c1:
            run_button_cards = st.button("Run Card Optimization")
        with c2:
            run_button_hero = st.button("Run Hero Optimization")

    # Results (Right side)
    with col2:
        st.header("Results")

        if run_button_cards:
            if not attack_decks_input or not defense_deck_hash:
                st.error("Please enter both attack deck hashes and a defense deck hash.")
            else:
                attack_decks = [line.strip() for line in attack_decks_input.split("\n") if line.strip()]

                with st.spinner("Running simulations... this may take a while."):
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    avg_winrate, avg_winrates, removed_cards = loop.run_until_complete(
                        run_optimization(attack_decks, defense_deck_hash)
                    )

                    # Store results in session state
                    st.session_state["avg_winrate"] = avg_winrate
                    st.session_state["avg_winrates"] = avg_winrates
                    st.session_state["removed_cards"] = removed_cards

        # Display results if available
        if "avg_winrate" in st.session_state:
            st.write(f"**Winrate of Current Deck:** {st.session_state['avg_winrate']:.2f}%")

            st.subheader("Winrates After Removing Each Card")
            winrate_text = " | ".join(
                f"`{card}` → **{winrate:.2f}%**" for card, winrate in zip(
                    st.session_state["removed_cards"], st.session_state["avg_winrates"].values()
                )
            )
            st.markdown(winrate_text, unsafe_allow_html=True)


if __name__ == "__main__":
    main()