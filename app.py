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


async def run_simulation(attack_deck, defense_deck, battle_type, context):
    if battle_type == "Tower Battles":
        url = f"https://vuzaldo.github.io/SIMSpellstone/Titans.html?deck1={attack_deck}&deck2={defense_deck}&mission_level=7&raid_level=25&siege&tower_level=18&tower_type={tower_type}&bges={bge}&sims=100000&autostart"
    elif battle_type == "Arena":
        url = f"https://vuzaldo.github.io/SIMSpellstone/Titans.html?deck1={attack_deck}&deck2={defense_deck}&mission_level=7&raid_level=25&bges={BGE}&sims=100000&autostart"
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


async def simulate_pair(pair, battle_type, context, semaphore, pbar):
    async with semaphore:
        attack_deck, defense_deck = pair
        result = await run_simulation(attack_deck, defense_deck, battle_type, context)
        pbar.update(1)
        return (attack_deck, defense_deck, result)


async def run_simulations_parallel(attack_decks, defense_decks, battle_type):
    deck_pairs = [(attack_deck, defense_deck) for attack_deck in attack_decks for defense_deck in defense_decks]
    total_simulations = len(deck_pairs)
    semaphore = asyncio.Semaphore(8)

    with tqdm(total=total_simulations, desc="Simulations Progress", unit="sim") as pbar:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
            context = await browser.new_context()
            tasks = [simulate_pair(pair, battle_type, context, semaphore, pbar) for pair in deck_pairs]
            results = await asyncio.gather(*tasks)
            await browser.close()

    return results


async def get_card_name_from_hash(card_hash, context):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto("https://vuzaldo.github.io/SIMSpellstone/DeckBuilder.html")
        await page.wait_for_load_state("domcontentloaded")

        js_script = f"""
        (() => {{
            var d = hash_decode("{card_hash}");

            var card_id = d.deck[0].id;
            var rune_id = d.deck[0].runes[0].id;

            var cardName = "";
            var cardRune = "";

            Object.values(CARDS).forEach(c => {{
                if (c.id == card_id) {{
                    cardName = c.name;
                }}
            }});

            Object.values(RUNES).forEach(c => {{
                if (c.id == rune_id) {{
                    cardRune = c.name;
                }}
            }});

            return [cardName, cardRune];
        }})()
        """

        card_name, card_rune = await page.evaluate(js_script)

        await page.close()

    return [card_name, card_rune]


async def get_card_names_from_hashes(card_hashes, context):
    tasks = []
    for card_hash in card_hashes:
        tasks.append(get_card_name_from_hash(card_hash, context))

    card_names_and_runes = await asyncio.gather(*tasks)
    return card_names_and_runes


async def optimize_deck(your_deck, opponents_decks, deck_type, battle_type, context):
    if deck_type == "Defence":
        attack_decks = opponents_decks
        defence_deck = your_deck
        len_hash = len(defence_deck)
        card_hashes = [defence_deck[i:i + 5] for i in range(5, len_hash, 5)]
    elif deck_type == 'Offence':
        defence_decks = opponents_decks
        attack_deck = your_deck
        len_hash = len(attack_deck)
        card_hashes = [attack_deck[i:i + 5] for i in range(5, len_hash, 5)]
    seen_card_hashes = set()
    modified_decks = []
    removed_names = []
    removed_runes = []

    card_names_and_runes = await get_card_names_from_hashes(card_hashes, context)
    for i, (card_name, card_rune) in enumerate(card_names_and_runes):
        card_hash = card_hashes[i]
        if card_hash in seen_card_hashes:
            continue
        seen_card_hashes.add(card_hash)
        if deck_type == "Defence":
            modified_deck = defence_deck.replace(card_hash, "", 1)
        elif deck_type == "Offence":
            modified_deck = attack_deck.replace(card_hash, "", 1)
        modified_decks.append(modified_deck)
        removed_names.append(card_name)
        removed_runes.append(card_rune)

    if deck_type == "Defence":
        initial_results = await run_simulations_parallel(attack_decks, [your_deck], battle_type)
        winrates = [float(result[2].strip('%')) for result in initial_results if result[2]]
        results = await run_simulations_parallel(attack_decks, modified_decks, battle_type)
    elif deck_type == "Offence":
        initial_results = await run_simulations_parallel([your_deck], defence_decks, battle_type)
        winrates = [float(result[2].strip('%')) for result in initial_results if result[2]]
        results = await run_simulations_parallel(modified_decks, defence_decks, battle_type)

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


async def run_optimization(attack_decks, defense_deck_hash, deck_type, battle_type, context):
    return await optimize_deck(attack_decks, defense_deck_hash, deck_type, battle_type, context)


st.set_page_config(layout="wide")


async def main():
    st.title("Family Simulation Tool")
    col1, col2 = st.columns(2)

    with col1:
        st.header("Decks")
        your_deck_hash = st.text_input("Your deck")
        opponents_decks_input = st.text_area("Decks of opponents (one hash per line)")
        c1, c2 = st.columns(2)
        with c1:
            deck_type = st.radio("What deck do you want to optimize?", ["Offence", "Defence"])
            run_button_cards = st.button("Run Card Optimization")
        with c2:
            battle_type = st.radio("Type of battles", ["Tower Battles", "Arena"])
            run_button_hero = st.button("Run Hero Optimization")

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

                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
                        context = await browser.new_context()

                        avg_winrate, avg_winrates, removed_names, removed_runes = await run_optimization(your_deck_hash, opponents_decks, deck_type, battle_type, context)

                        await browser.close()

                    st.session_state["avg_winrate"] = avg_winrate
                    st.session_state["avg_winrates"] = avg_winrates
                    st.session_state["removed_names"] = removed_names
                    st.session_state["removed_runes"] = removed_runes

            if "avg_winrate" in st.session_state:
                st.write(f"**Average Winrate:** {st.session_state['avg_winrate']:.2f}%")
                if deck_type == "Defence":
                    st.write("**Cards to remove (Defence):**")
                elif deck_type == "Offence":
                    st.write("**Cards to remove (Offence):**")
                for name, rune in zip(st.session_state["removed_names"], st.session_state["removed_runes"]):
                    st.write(f"{name} ({rune})")

        if run_button_hero:
            if not opponents_decks_input or not your_deck_hash:
                st.error("Please enter both attack deck hashes and a defense deck hash.")
            else:
                opponents_decks = [line.strip() for line in opponents_decks_input.split("\n") if line.strip()]

                with st.spinner("Running hero optimization..."):

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
                        context = await browser.new_context()

                        avg_winrate, avg_winrates, removed_names, removed_runes = await run_optimization(your_deck_hash, opponents_decks, deck_type, battle_type, context)

                        await browser.close()

                    st.session_state["avg_winrate"] = avg_winrate
                    st.session_state["avg_winrates"] = avg_winrates
                    st.session_state["removed_names"] = removed_names
                    st.session_state["removed_runes"] = removed_runes

            if "avg_winrate" in st.session_state:
                st.write(f"**Average Winrate:** {st.session_state['avg_winrate']:.2f}%")
                if deck_type == "Defence":
                    st.write("**Heroes to remove (Defence):**")
                elif deck_type == "Offence":
                    st.write("**Heroes to remove (Offence):**")
                for name, rune in zip(st.session_state["removed_names"], st.session_state["removed_runes"]):
                    st.write(f"{name} ({rune})")

# Running the streamlit app
if __name__ == "__main__":
    asyncio.run(main())