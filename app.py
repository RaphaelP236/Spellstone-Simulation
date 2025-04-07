import streamlit as st
import asyncio
import sys
from playwright.async_api import async_playwright
from tqdm.asyncio import tqdm
import nest_asyncio
import subprocess
from collections import defaultdict


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
bge = "!C~C"
BGE = "!C~CJI"
tower_type = 501

heroes = {
    "Samael": "gmQAA",
    "Tarian the Lich Lord": "4!fAA",
    "Groc the Hammer": "QXvAA",
    "Rayne the Wavecrasher": "Yf0AA",
    "Orgoth the Hex Fist": "gn5AA",
    "Ol' Cedric": "ov!AA",
    "Oda the Aegis": "w3DBA",
    "Yuriel the Manashifter": "4~IBA",
    "Aria the Nightwielder": "AIOBA",
    "Decim the Pyrokinetic": "IQTBA",
    "Elyse the Truestriker": "QYYBA",
    "General Ursurio": "YgdBA",
    "Scyer the Fury Mecha": "goiBA"
}

def replace_hero(deck_hash, new_hero_hash):
    """Replace the hero in the deck hash with the new hero hash."""
    return new_hero_hash + deck_hash[5:]

async def load_page_with_retry(page, url, retries=3):
    attempt = 0
    while attempt < retries:
        try:
            await page.goto(url, timeout=100000)
            return True
        except Exception:
            attempt += 1
    return False


async def run_simulation(attack_deck, defense_deck, battle_type, numb_sims, context):
    if battle_type == "Tower Battles":
        url = f"https://vuzaldo.github.io/SIMSpellstone/Titans.html?deck1={attack_deck}&deck2={defense_deck}&mission_level=7&raid_level=25&siege&tower_level=18&tower_type={tower_type}&bges={bge}&sims={numb_sims}&autostart"
    elif battle_type == "Arena":
        url = f"https://vuzaldo.github.io/SIMSpellstone/Titans.html?deck1={attack_deck}&deck2={defense_deck}&mission_level=7&raid_level=25&bges={BGE}&sims={numb_sims}&autostart"
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


async def simulate_pair(pair, battle_type, numb_sims, context, semaphore, pbar):
    async with semaphore:
        attack_deck, defense_deck = pair
        result = await run_simulation(attack_deck, defense_deck, battle_type, numb_sims, context)
        pbar.update(1)
        return (attack_deck, defense_deck, result)


async def run_simulations_parallel(attack_decks, defense_decks, battle_type, numb_sims):
    deck_pairs = [(attack_deck, defense_deck) for attack_deck in attack_decks for defense_deck in defense_decks]
    total_simulations = len(deck_pairs)
    semaphore = asyncio.Semaphore(8)

    with tqdm(total=total_simulations, desc="Simulations Progress", unit="sim") as pbar:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
            context = await browser.new_context()
            tasks = [simulate_pair(pair, battle_type, numb_sims, context, semaphore, pbar) for pair in deck_pairs]
            results = await asyncio.gather(*tasks)
            await browser.close()

    return results


async def get_card_name_from_hash(card_hash, context):
    # This function fetches the card name using the hash on the website
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # Set False if you want to see the browser
        page = await browser.new_page()

        # Open the DeckBuilder website
        await page.goto("https://vuzaldo.github.io/SIMSpellstone/DeckBuilder.html")
        await page.wait_for_load_state("domcontentloaded")

        js_script = f"""
        (() => {{
            // Decode the hash to get deck info
            var d = hash_decode("{card_hash}");

            // Extract the ID from the first card in the deck
            var card_id = d.deck[0].id;
            var rune_id = d.deck[0].runes[0].id;  // FIXED: use 'd' instead of 'c'

            var cardName = "";
            var cardRune = "";

            // Check if CARDS is available and search for the card name
            Object.values(CARDS).forEach(c => {{
                if (c.id == card_id) {{
                    cardName = c.name;
                }}
            }});

            // Check if RUNES is available and search for the rune name
            
            Object.values(RUNES).forEach(c => {{
                if (c.id == rune_id) {{
                    cardRune = c.name;
                }}
            }});

            return [cardName, cardRune];  // FIXED: Return an array instead of tuple
        }})()
        """

        # Get the card name by executing the JavaScript code
        card_name, card_rune = await page.evaluate(js_script)

        # Close the page and return the result
        await page.close()
        return [card_name, card_rune]


async def optimize_deck(your_deck, opponents_decks, deck_type, battle_type, numb_sims, context):

    if deck_type == "Defence":
        attack_decks = opponents_decks
        defence_deck = your_deck
        len_hash = len(defence_deck)
        card_hashes = [defence_deck[i:i + 5] for i in range(5, len_hash, 5)]  # Assuming 5-char card hashes
    elif deck_type == 'Offence':
        defence_decks = opponents_decks
        attack_deck = your_deck
        len_hash = len(attack_deck)
        card_hashes = [attack_deck[i:i + 5] for i in range(5, len_hash, 5)]  # Assuming 5-char card hashes
    seen_card_hashes = set()
    modified_decks = []
    removed_names = []
    removed_runes = []

    # Fetch card names for each hash in `card_hashes`
    card_names = {}
    card_runes = {}
    for card_hash in card_hashes:
        if card_hash in seen_card_hashes:
            continue
        seen_card_hashes.add(card_hash)
        card_name, card_rune = await get_card_name_from_hash(card_hash, context)
        card_names[card_hash] = card_name
        card_runes[card_hash] = card_rune
        if deck_type == "Defence":
            modified_deck = defence_deck.replace(card_hash, "", 1)
        elif deck_type == "Offence":
            modified_deck = attack_deck.replace(card_hash, "", 1)
        modified_decks.append(modified_deck)
        removed_names.append(card_name)  # Store card names
        removed_runes.append(card_rune)



    if deck_type == "Defence":
        initial_results = await run_simulations_parallel(attack_decks, [your_deck], battle_type, numb_sims)
        winrates = [float(result[2].strip('%')) for result in initial_results if result[2]]
        results = await run_simulations_parallel(attack_decks, modified_decks, battle_type, numb_sims)
    elif deck_type == "Offence":
        initial_results = await run_simulations_parallel([your_deck], defence_decks, battle_type, numb_sims)
        winrates = [float(result[2].strip('%')) for result in initial_results if result[2]]
        results = await run_simulations_parallel(modified_decks, defence_decks, battle_type, numb_sims)
    avg_winrate = sum(winrates) / len(winrates) if winrates else 0

    avg_winrates = {}
    for i, modified_deck in enumerate(modified_decks):
        if deck_type == "Defence":
            total_winrate = sum(
                float(winrate.strip('%')) for attack, defense, winrate in results if defense == modified_deck and winrate)
            avg_winrates[removed_names[i]] = total_winrate / len(attack_decks)
        elif deck_type == "Offence":
            total_winrate = sum(
                float(winrate.strip('%')) for attack, defense, winrate in results if attack == modified_deck and winrate)
            avg_winrates[removed_names[i]] = total_winrate / len(defence_decks)

    return avg_winrate, avg_winrates, removed_names, removed_runes


async def run_optimization(attack_decks, defense_deck_hash, deck_type, battle_type, numb_sims, context):
    return await optimize_deck(attack_decks, defense_deck_hash, deck_type, battle_type, numb_sims, context)


st.set_page_config(layout="wide")  # Ensure full-width layout


async def main():
    st.title("Family Simulation Tool")
    # Create two columns for layout
    col1, col2 = st.columns(2)  # Left (narrower) | Right (wider)

    # Input fields and Run button (Left side)
    with col1:
        st.header("Decks")
        your_deck_hash = st.text_input("Your Deck")
        opponents_decks_input = st.text_area("Decks of opponents (one hash per line)")
        replacement_card_hash = st.text_input("Hashes of Replacement cards")
        numb_sims = st.text_input("Number of Simulations:", value = 10000)
        c1, c2 = st.columns(2)
        with c1:
            deck_type = st.radio("What deck do you want to optimze?", ["Offence", "Defence"])
        with c2:
            battle_type = st.radio("Type of battles", ["Tower Battles", "Arena"])
        c1, c2, c3 = st.columns(3)
        with c1:
            run_button_cards = st.button("Run Card Optimization")
        with c2:
            run_button_hero = st.button("Run Hero Optimization")
        with c3:
            run_button_replacement = st.button("Find Replacement")

    # Results (Right side)
    with col2:
        st.header("Results")

        if run_button_cards:
            if not opponents_decks_input or not your_deck_hash:
                st.error("Please enter both attack deck hashes and a defense deck hash.")
            else:
                opponents_decks = [line.strip() for line in opponents_decks_input.split("\n") if line.strip()]


                with st.spinner("Running simulations... this may take a while."):

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    # Pass context into the optimization function
                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
                        context = await browser.new_context()

                        avg_winrate, avg_winrates, removed_names, removed_runes = await run_optimization(your_deck_hash, opponents_decks, deck_type, battle_type, numb_sims, context)

                        await browser.close()

                    # Store results in session state
                    st.session_state["avg_winrate"] = avg_winrate
                    st.session_state["avg_winrates"] = avg_winrates
                    st.session_state["removed_names"] = removed_names
                    st.session_state["removed_runes"] = removed_runes

            # Display results if available
            if "avg_winrate" in st.session_state:
                st.write(f"**Winrate of Current Deck:** {st.session_state['avg_winrate']:.2f}%")

                st.subheader("Winrates After Removing Each Card")
                if deck_type == "Defence":
                    st.caption("High winrate equals a good card was removed.")
                if deck_type == "Offence":
                    st.caption("Low winrate equals a good card was removed.")

                # Create a list of strings with each card and winrate on a new line
                winrate_text = [
                    f"`{name} ({rune})` → **{winrate:.2f}%**"
                    for name, rune, winrate in zip(
                        st.session_state["removed_names"], st.session_state["removed_runes"], st.session_state["avg_winrates"].values()
                    )
                ]

                # Split the list into two halves for two columns
                column_1 = winrate_text[:8]
                column_2 = winrate_text[8:]

                # Create two columns for display
                col1, col2 = st.columns(2)

                with col1:
                    # Display the first half of the winrate_text list
                    for text in column_1:
                        st.write(text)

                with col2:
                    # Display the second half of the winrate_text list
                    for text in column_2:
                        st.write(text)

        if run_button_hero:
            if not opponents_decks_input or not your_deck_hash:
                st.error("Please enter both attack deck hashes and a defense deck hash.")
            else:
                opponents_decks = [line.strip() for line in opponents_decks_input.split("\n") if line.strip()]

                with st.spinner("Running simulations... this may take a while."):


                    your_deck = [replace_hero(your_deck_hash, hero_hash) for hero_hash in heroes.values()]

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
                        context = await browser.new_context()

                        hero_names = list(heroes.keys())

                        if deck_type == "Defence":
                            results = await run_simulations_parallel( opponents_decks, your_deck, battle_type, numb_sims)
                            # Dictionary to store win rates for each defense deck
                            winrate_dict = defaultdict(list)

                            # Populate the dictionary
                            for attack_deck, defense_deck, winrate in results:
                                winrate_dict[defense_deck].append(float(winrate.strip('%')))

                            # Compute the average win rate for each defense deck
                            average_winrates = {deck: sum(rates) / len(rates) for deck, rates in winrate_dict.items()}

                        elif deck_type == "Offence":
                            results = await run_simulations_parallel(your_deck, opponents_decks, battle_type, numb_sims)
                            winrate_dict = defaultdict(list)

                            # Populate the dictionary
                            for attack_deck, defense_deck, winrate in results:
                                winrate_dict[attack_deck].append(float(winrate.strip('%')))

                            # Compute the average win rate for each attack deck
                            average_winrates = {deck: sum(rates) / len(rates) for deck, rates in winrate_dict.items()}

                        await browser.close()

            st.subheader("Best Hero")
            if deck_type == "Defence":
                st.caption("Low winrate equals a good hero.")
            if deck_type == "Offence":
                st.caption("High winrate equals a good hero.")
            winrate_text = [
                f"`{name}` → **{winrate:.2f}%**"
                for name, winrate in zip(hero_names,average_winrates.values())
            ]
            # Split the list into two halves for two columns
            column_1 = winrate_text[:7]
            column_2 = winrate_text[7:]

            # Create two columns for display
            col1, col2 = st.columns(2)

            with col1:
                # Display the first half of the winrate_text list
                for text in column_1:
                    st.write(text)

            with col2:
                # Display the second half of the winrate_text list
                for text in column_2:
                    st.write(text)

        if run_button_replacement:
            if not opponents_decks_input or not your_deck_hash:
                st.error("Please enter both attack deck hashes and a defense deck hash.")
            else:
                card_hashes = [replacement_card_hash[i:i + 5] for i in range(0, len(replacement_card_hash), 5)]
                your_decks = [your_deck_hash + card for card in card_hashes]
                opponents_decks = [line.strip() for line in opponents_decks_input.split("\n") if line.strip()]

                with st.spinner("Running simulations... this may take a while."):


                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
                        context = await browser.new_context()

                        card_names = {}
                        card_runes = {}
                        for card_hash in card_hashes:
                            card_name, card_rune = await get_card_name_from_hash(card_hash, context)
                            card_names[card_hash] = card_name
                            card_runes[card_hash] = card_rune


                        if deck_type == "Defence":
                            results = await run_simulations_parallel(opponents_decks, your_decks, battle_type, numb_sims)
                            # Dictionary to store win rates for each defense deck
                            winrate_dict = defaultdict(list)

                            # Populate the dictionary
                            for attack_deck, defense_deck, winrate in results:
                                winrate_dict[defense_deck].append(float(winrate.strip('%')))

                            # Compute the average win rate for each defense deck
                            average_winrates = {deck: sum(rates) / len(rates) for deck, rates in winrate_dict.items()}

                        elif deck_type == "Offence":
                            results = await run_simulations_parallel(your_decks, opponents_decks, battle_type, numb_sims)
                            winrate_dict = defaultdict(list)

                            # Populate the dictionary
                            for attack_deck, defense_deck, winrate in results:
                                winrate_dict[attack_deck].append(float(winrate.strip('%')))

                            # Compute the average win rate for each attack deck
                            average_winrates = {deck: sum(rates) / len(rates) for deck, rates in winrate_dict.items()}

                        await browser.close()


                        st.subheader("Winrates of Replacement Cards")
                        if deck_type == "Defence":
                            st.caption("Low winrate equals a good replacement card.")
                        if deck_type == "Offence":
                            st.caption("High winrate equals a good replacement card.")

                        st.session_state["avg_winrates"] = average_winrates
                        st.session_state["card_names"] = card_names
                        st.session_state["card_runes"] = card_runes

                        # Create a list of strings with each card and winrate on a new line
                        winrate_text = []
                        for full_deck_hash, winrate in st.session_state["avg_winrates"].items():
                            replaced_card_hash = full_deck_hash[-5:]  # Assumes the replaced card is at the end
                            card_name = st.session_state["card_names"].get(replaced_card_hash, replaced_card_hash)
                            card_rune = st.session_state["card_runes"].get(replaced_card_hash, replaced_card_hash)
                            winrate_text.append(f"`{card_name} ({card_rune})` → **{winrate:.2f}%**")

                        # Split the list into two halves for two columns
                        column_1 = winrate_text[:8]
                        column_2 = winrate_text[8:]

                        # Create two columns for display
                        col1, col2 = st.columns(2)

                        with col1:
                            # Display the first half of the winrate_text list
                            for text in column_1:
                                st.write(text)

                        with col2:
                            # Display the second half of the winrate_text list
                            for text in column_2:
                                st.write(text)



if __name__ == "__main__":
    asyncio.run(main())