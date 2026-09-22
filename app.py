import streamlit as st
import google.generativeai as genai
import requests
import json
import re

# requirements.txt for this app should include:
#   streamlit
#   google-generativeai
#   requests
#   pytrends        (optional — enables the Google Trends interest score)
#   beautifulsoup4  (optional — enables the "actually selling" real-signal scraper below)

# Optional: real (relative) search-interest signal from Google Trends.
# This is an unofficial API and can occasionally fail/rate-limit — always wrapped in try/except.
try:
    from pytrends.request import TrendReq
    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False

# Optional: needed to parse Etsy's public search-results HTML for real "bought/bestseller" badges.
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# Page Configuration
st.set_page_config(page_title="Etsy Digital Gem Finder", page_icon="💎", layout="wide")

st.title("💎 Etsy Digital Product Gem Finder")
st.write("Discover low-competition, high-demand digital product ideas — filtered to products you can actually build with AI (Claude/Gemini), not design tools.")

# Initialize Session State
if "used_gems" not in st.session_state:
    st.session_state.used_gems = set()
if "real_signals" not in st.session_state:
    st.session_state.real_signals = []
if "real_signal_notes" not in st.session_state:
    st.session_state.real_signal_notes = []

# ---------------------------------------------------------------------------
# API KEY HANDLING (fixes: app asking for the key every session)
# ---------------------------------------------------------------------------
def get_secret_api_key():
    """Pull the key from Streamlit secrets if it's been set there."""
    try:
        return st.secrets.get("GEMINI_API_KEY", None)
    except Exception:
        return None

st.sidebar.header("⚙️ Configuration")

secret_key = get_secret_api_key()

if secret_key:
    api_key = secret_key
    st.sidebar.success("✅ Gemini API key loaded from secrets — no need to paste it.")
    with st.sidebar.expander("Use a different key instead"):
        override_key = st.text_input("Override Gemini API Key:", type="password")
        if override_key:
            api_key = override_key
else:
    st.sidebar.warning("No GEMINI_API_KEY found in st.secrets — add one in your Streamlit Cloud app settings "
                        "(Settings → Secrets → `GEMINI_API_KEY = \"...\"`) so you stop having to paste it every session.")
    api_key = st.sidebar.text_input("Enter Gemini API Key:", type="password")

num_gems = st.sidebar.slider("How many AI product ideas to generate:", min_value=3, max_value=10, value=3)
min_price = st.sidebar.number_input("Minimum typical price ($):", min_value=0, value=15, step=1)

st.sidebar.divider()
st.sidebar.header("📈 Real Sales Signal")
use_real_sales = st.sidebar.checkbox(
    "Check Etsy search results for listings that are ACTUALLY selling",
    value=True,
    help="Experimental / best-effort. There is no public Etsy API that reports real sale counts across the "
         "marketplace (the official API only exposes a shop's own orders to that shop's owner). This instead "
         "scrapes Etsy's own public search-results page and looks for listings that currently display a real "
         "'X+ bought in the last/past month' or 'Bestseller' badge — i.e. proof of recent, actual sales, not "
         "an AI guess. Etsy actively blocks bots and changes its page layout without notice, especially from "
         "cloud-server IPs (like Streamlit Cloud), so this can return few or zero results even when the "
         "products genuinely are selling. Treat empty results as inconclusive, not as 'nothing sells here.'"
)
max_listings_per_query = st.sidebar.slider("Max listings to check per search term", 5, 30, 15)

# Categorized Niche Library (100+ Specific Micro-Niches)
CATEGORIZED_NICHES = {
    "🐔 Pets, Animals & Farming": [
        "Backyard Poultry Farming", "Dog Groomers", "Dog Trainers", "Pet Sitting & Dog Walking",
        "Cat Breeders & Catteries", "Aquarium & Fish Keepers", "Reptile & Exotic Pet Owners",
        "Equestrians & Horse Owners", "Beekeepers & Apiaries", "Veterinary Technicians",
        "Animal Rescue & Shelters", "Bird Watching Enthusiasts"
    ],
    "💼 Business & Service Providers": [
        "Real Estate Agents", "Airbnb & Short-Term Rental Hosts", "Etsy Shop Owners",
        "Shopify & E-commerce Sellers", "Bookkeepers & Accountants", "Virtual Assistants",
        "Social Media Managers", "Freelance Copywriters", "Graphic Designers",
        "Event & Wedding Planners", "Interior Designers", "Content Creators & YouTubers",
        "Podcasters", "Life & Business Coaches", "Commercial Cleaning Businesses", "Mobile Car Detailers"
    ],
    "🍞 Food, Baking & Hospitality": [
        "Sourdough Bakers", "Home Bakers & Cake Decorators", "Meal Prep & Planning",
        "Coffee Shop & Cafe Owners", "Food Truck Vendors", "Catering Businesses",
        "Canning & Food Preserving", "Homebrewers & Craft Beer", "Bartenders & Mixologists",
        "Nutritionists & Health Coaches"
    ],
    "📚 Education & Parenting": [
        "Special Education Teachers", "Homeschooling Parents", "Preschool & Kindergarten Teachers",
        "Elementary Teachers", "High School STEM Teachers", "Music Teachers & Tutors",
        "Art Teachers", "ESL / TEFL Teachers", "School Counselors", "Daycare & Childcare Owners",
        "Toddler & Baby Milestones"
    ],
    "🧘 Health, Fitness & Wellness": [
        "Personal Trainers", "Yoga Instructors", "Pilates Instructors", "Mental Health Therapists",
        "Massage Therapists", "Estheticians & Skincare Techs", "Lash & Nail Technicians",
        "Doulas & Midwives", "Chiropractors", "Physical Therapists", "Meditation & Mindfulness Guides"
    ],
    "🌱 Home, Garden & Homesteading": [
        "Urban Homesteaders", "Indoor Houseplant Collectors", "Vegetable & Herb Gardeners",
        "Home Organization & Decluttering", "Landscaping & Lawn Care", "Interior Decorators",
        "Home Stagers", "Tiny House & Van Life", "DIY Home Renovators"
    ],
    "🎨 Crafts, Arts & Trades": [
        "Handmade Soap Makers", "Candle Makers", "Crochet & Knitting Designers", "Quilters",
        "Embroidery Artists", "Resin Artists", "Polymer Clay Crafters", "Leather Crafters",
        "Paper Crafters & Origami", "Jewelry Makers", "Ceramicists & Potters", "Woodworking Hobbyists",
        "Stained Glass Crafters", "Upcycling Enthusiasts"
    ],
    "🎉 Events, Parties & Holidays": [
        "Wedding Planning & Brides", "Bridal Shower Organizers", "Baby Shower Planners",
        "Birthday Party Decorators", "Corporate Event Planners", "Graduation Planners"
    ],
    "📸 Hobbies & Specialized Interests": [
        "Photographers", "Videographers", "Travel & RV Living", "Board Game Designers",
        "Tabletop RPG & D&D Players", "Genealogy & Family Tree Researchers", "Book Club Organizers",
        "Musicians & Songwriters", "Fitness Competitors", "Scrapbookers & Memory Keeping"
    ],
    "✍️ Custom Niche": [
        "Enter Custom Niche..."
    ]
}

# Select Category first
category = st.selectbox("1. Select Category:", list(CATEGORIZED_NICHES.keys()))

# Select Niche based on Category
if category == "✍️ Custom Niche":
    selected_niche = st.text_input("Enter your custom niche or sub-topic:", value="Custom Mechanical Keyboard Builders")
else:
    selected_niche = st.selectbox("2. Select Niche:", CATEGORIZED_NICHES[category])


# Function to fetch Google Autocomplete keywords (real signal: what people actually type)
def get_live_search_suggestions(query):
    try:
        url = f"https://suggestqueries.google.com/complete/search?client=chrome&q={query}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = json.loads(response.text)
            return data[1][:5]
    except Exception:
        pass
    return []


# Function to fetch a real (relative) interest score from Google Trends
def get_trends_interest(keyword):
    if not PYTRENDS_AVAILABLE:
        return None
    try:
        pytrends = TrendReq(hl="en-US", tz=360)
        pytrends.build_payload([keyword], timeframe="today 12-m")
        data = pytrends.interest_over_time()
        if data.empty:
            return None
        return int(data[keyword].mean())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# REAL SIGNAL: check Etsy's own search results for listings that are
# currently displaying a genuine "bought in the last/past month" or
# "Bestseller" badge — i.e. proof of recent, actual sales.
# ---------------------------------------------------------------------------
_SOLD_BADGE_PATTERNS = [
    re.compile(r'[\d,]+\+?\s*bought\s*in\s*the\s*(?:last|past)\s*(?:month|3\s*months|year)', re.I),
    re.compile(r'[\d,]+\+?\s*bought\s*this', re.I),
    re.compile(r'[\d,]+\+?\s*sold\s*in\s*the\s*(?:last|past)\s*(?:month|3\s*months|year)', re.I),
]
_BESTSELLER_PATTERN = re.compile(r'\bbestseller\b', re.I)


def _extract_sold_signal(card_text):
    for pat in _SOLD_BADGE_PATTERNS:
        m = pat.search(card_text)
        if m:
            return m.group(0).strip()
    if _BESTSELLER_PATTERN.search(card_text):
        return "Bestseller badge"
    return None


def scrape_etsy_recent_sales(query, max_results=15):
    """
    Best-effort REAL signal. Fetches Etsy's own public search-results page and
    looks for listings that right now display a genuine "X+ bought in the
    last/past month" or "Bestseller" badge.

    This is NOT the official Etsy API — Etsy's Open API only exposes a shop's
    own order/receipt history to that shop's authenticated owner, not sales
    data for arbitrary listings across the marketplace. Scraping the public
    search page is the closest available real signal, but it is fragile:
    Etsy's bot protection can block or soft-block requests (more likely from
    a cloud server than a home IP), and their markup can change without
    notice. This function always degrades gracefully and reports *why* it
    found nothing, rather than silently returning an empty list.

    Returns: (results, note)
      results -> list of dicts: title, sold_signal, price_text, url
      note    -> None on success, otherwise a short human-readable reason
    """
    if not BS4_AVAILABLE:
        return [], "beautifulsoup4 isn't installed, so real-signal scraping is disabled (add it to requirements.txt)."

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(
            "https://www.etsy.com/search",
            headers=headers,
            params={"q": query, "explicit": "1"},
            timeout=8,
        )
    except Exception as e:
        return [], f"Request to Etsy failed for '{query}': {e}"

    if resp.status_code != 200:
        return [], f"Etsy returned HTTP {resp.status_code} for '{query}' (likely bot-blocked)."

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        return [], f"Couldn't parse Etsy's response for '{query}': {e}"

    cards = soup.select("[data-listing-id]")
    if not cards:
        return [], f"Fetched Etsy's search page for '{query}', but no listing cards matched — Etsy likely changed its layout or soft-blocked the request."

    results = []
    for card in cards[:max_results]:
        card_text = card.get_text(" ", strip=True)
        signal = _extract_sold_signal(card_text)
        if not signal:
            continue

        title = None
        img = card.find("img")
        if img and img.get("alt"):
            title = img["alt"].strip()
        if not title:
            heading = card.find(["h3", "h2"])
            if heading:
                title = heading.get_text(strip=True)
        if not title:
            title = card_text[:80]

        price_match = re.search(r'\$[\d,]+(?:\.\d{2})?', card_text)
        link_tag = card.find("a", href=True)

        results.append({
            "title": title,
            "sold_signal": signal,
            "price_text": price_match.group(0) if price_match else None,
            "url": link_tag["href"].split("?")[0] if link_tag else None,
        })

    if not results:
        return [], f"Fetched Etsy's search page for '{query}' ({len(cards)} listings seen), but none currently show a 'bought'/'Bestseller' badge — inconclusive, not proof of no demand."

    return results, None


def gather_real_signals(niche, max_per_query):
    """Runs scrape_etsy_recent_sales across a handful of seed terms for the niche and dedupes."""
    seed_terms = [
        niche,
        f"{niche} tracker",
        f"{niche} planner",
        f"{niche} template",
        f"{niche} printable",
    ]
    all_results, notes, seen_titles = [], [], set()
    for term in seed_terms:
        results, note = scrape_etsy_recent_sales(term, max_results=max_per_query)
        if note:
            notes.append(note)
        for r in results:
            key = r["title"].strip().lower()
            if key not in seen_titles:
                seen_titles.add(key)
                all_results.append(r)
    return all_results, notes


# Function to generate AI product ideas, now grounded in real scraped competitor evidence
def generate_gems(niche, api_key, count, min_price, real_signals=None):
    genai.configure(api_key=api_key)

    # Strictly target gemini-3.6-flash
    model = genai.GenerativeModel('gemini-3.6-flash')

    # Fetch live search signals
    seed_terms = [f"{niche} tracker", f"{niche} binder", f"{niche} log book", f"{niche} template"]
    live_signals = []
    for term in seed_terms:
        live_signals.extend(get_live_search_suggestions(term))

    signals_text = ", ".join(live_signals) if live_signals else "general search trends"
    excluded_text = ", ".join(st.session_state.used_gems) if st.session_state.used_gems else "None"

    real_signals = real_signals or []
    if real_signals:
        evidence_lines = [
            f"- \"{r['title']}\" — currently shows: {r['sold_signal']}"
            + (f" (price {r['price_text']})" if r.get("price_text") else "")
            for r in real_signals[:15]
        ]
        real_evidence_text = (
            "The following are REAL Etsy listings, scraped just now, that currently display a genuine "
            "'bought'/'Bestseller' badge — i.e. confirmed evidence they are actually selling right now:\n"
            + "\n".join(evidence_lines)
        )
    else:
        real_evidence_text = (
            "No confirmed 'actually selling' listings were found by the live scraper for this niche just now "
            "(this can mean low visible demand, or simply that Etsy blocked/limited the scrape — treat as "
            "inconclusive, not as proof nothing sells here)."
        )

    prompt = f"""
    You are an expert Etsy market researcher specializing in digital downloads.
    Target Niche: {niche}
    Real Search Signals Found: {signals_text}
    Previously Used/Excluded Ideas: {excluded_text}

    {real_evidence_text}

    Use the real evidence above (when present) to ground your ideas in what is demonstrably already selling —
    e.g. propose a differentiated or improved variant of a confirmed-selling listing, rather than a totally
    unproven concept, whenever real evidence is available.

    STRICT PRODUCT CONSTRAINTS — every idea MUST satisfy all of these:

    1. BUILDABLE WITH AI TEXT/CODE GENERATION ONLY. The entire product must be creatable by an AI
       model like Claude or Gemini writing text, data, formulas, or code — with NO graphic design
       software (Canva, Photoshop, Illustrator) and NO manual database-building in apps like Notion
       or Airtable. Good categories: written guides/ebooks, workbooks with substantial written
       content, spreadsheets built from formulas/logic (Google Sheets/Excel), calculators built with
       spreadsheet formulas, swipe files / script & copy templates, curated data lists, checklists
       with detailed written instructions, email/SOP template packs. BAD categories to reject: Canva
       templates, Notion dashboards/templates, printable planners that are primarily a graphic design
       layout with little unique text content, anything requiring illustration or custom graphics.

    2. PRICING: Must be a type of product that typically sells on Etsy for ${min_price} or more.
       Give your best real-world estimate of typical selling price as "typical_price_usd" (a number),
       and a one-sentence "price_justification" for why it commands that price (e.g., complexity,
       time saved, professional use case).

    3. COMPETITION SCORE: Give an honest numeric estimate "competition_score" from 1-100, where 100
       is extremely saturated/hard to rank and 1 is almost no competing listings. Base this on your
       knowledge of how common this type of listing is on Etsy. This is an ESTIMATE, not scraped data.

    4. DEMAND / SEARCH VOLUME: Give your best numeric estimate of "est_monthly_searches" (a number,
       combining Etsy + Google search behavior you're aware of for this kind of query) and a short
       "demand_reasoning" sentence. Flag this clearly as an ESTIMATE — you do not have live search
       volume data.

    5. AVOID GENERIC IDEAS (e.g., plain "Daily Planner" or "Goal Tracker"). Be specific and functional
       to this micro-niche.

    Return ONLY a raw JSON array containing exactly {count} objects with these exact keys:
    [
      {{
        "title": "Exact Product Name",
        "format": "e.g., Printable PDF Guide / Google Sheets Calculator / Swipe File",
        "description": "2-sentence functional overview of what is included in the download.",
        "search_intent": "The long-tail keyword real users search for",
        "typical_price_usd": 19,
        "price_justification": "...",
        "competition_score": 24,
        "est_monthly_searches": 880,
        "demand_reasoning": "..."
      }}
    ]
    """

    response = model.generate_content(prompt)
    clean_json = response.text.replace("```json", "").replace("```", "").strip()
    gems = json.loads(clean_json)

    # Filter defensively in case the model doesn't fully respect the price constraint
    gems = [g for g in gems if g.get("typical_price_usd", 0) >= min_price]

    # Attach a real Google Trends signal alongside the AI estimate, where available
    for g in gems:
        g["trends_interest"] = get_trends_interest(g.get("search_intent", niche))

    return gems


def competition_color(score):
    if score is None:
        return "gray"
    if score <= 33:
        return "green"
    if score <= 66:
        return "orange"
    return "red"


# Main Trigger
if st.button("✨ Find Hidden Product Gems"):
    if not selected_niche or selected_niche == "Enter Custom Niche...":
        st.warning("Please select or type a valid niche first.")
    else:
        real_signals, real_notes = [], []
        if use_real_sales:
            with st.spinner(f"Checking Etsy search results for listings actually selling in '{selected_niche}'..."):
                real_signals, real_notes = gather_real_signals(selected_niche, max_listings_per_query)
                st.session_state.real_signals = real_signals
                st.session_state.real_signal_notes = real_notes

        if not api_key:
            st.info("No Gemini API key provided — showing real Etsy signals only (AI idea generation skipped).")
        else:
            with st.spinner(f"Generating AI product ideas for '{selected_niche}'..."):
                try:
                    gems = generate_gems(selected_niche, api_key, num_gems, min_price, real_signals=real_signals)
                    st.session_state.current_gems = gems
                except Exception as e:
                    st.error(f"Error generating ideas: {e}")

# ---------------------------------------------------------------------------
# Display: REAL listings that are actually selling right now
# ---------------------------------------------------------------------------
if use_real_sales and st.session_state.real_signals:
    st.subheader(f"✅ Actually Selling Right Now — real Etsy listings for '{selected_niche}'")
    st.caption("Each of these currently shows a genuine 'bought in the last/past month' or 'Bestseller' badge "
               "on Etsy's own search page, scraped moments ago — this is real evidence of recent sales, not an estimate.")
    for r in st.session_state.real_signals:
        with st.container(border=True):
            cols = st.columns([3, 1])
            with cols[0]:
                st.markdown(f"**{r['title']}**")
                st.write(f"📦 {r['sold_signal']}")
                if r.get("price_text"):
                    st.caption(f"Listed at {r['price_text']}")
            with cols[1]:
                if r.get("url"):
                    st.link_button("View on Etsy", r["url"])
elif use_real_sales and "current_gems" in st.session_state:
    st.info("No listings with a confirmed 'bought'/'Bestseller' badge were found for this niche just now. "
            "This can mean genuinely low current demand, or that Etsy blocked/limited the live check — "
            "treat it as inconclusive rather than definitive.")

if use_real_sales and st.session_state.real_signal_notes:
    with st.expander("⚠️ Scraper notes / why some searches returned nothing"):
        for n in st.session_state.real_signal_notes:
            st.write(f"- {n}")

# ---------------------------------------------------------------------------
# Display: AI-generated product ideas
# ---------------------------------------------------------------------------
if "current_gems" in st.session_state and st.session_state.current_gems:
    st.subheader(f"💡 AI-Generated Ideas for: {selected_niche}")
    st.caption("⚠️ Competition score and monthly-search numbers are AI estimates, not scraped Etsy/Google data. "
               "'Trends interest' (where shown) is a real signal from Google Trends, but it's relative popularity "
               "(0-100), not an absolute search count. Where real Etsy evidence was found above, these ideas were "
               "prompted to build on it.")

    gems = st.session_state.current_gems
    for row_start in range(0, len(gems), 3):
        cols = st.columns(3)
        row_gems = gems[row_start:row_start + 3]
        for idx, gem in enumerate(row_gems):
            global_idx = row_start + idx
            title = gem.get("title", "Product Idea")
            with cols[idx]:
                st.markdown(f"### {title}")
                st.caption(f"**Format:** {gem.get('format')}")
                st.write(gem.get('description'))

                st.info(f"**Target Keyword:** `{gem.get('search_intent')}`")

                price = gem.get("typical_price_usd")
                if price is not None:
                    st.metric("Typical Price", f"${price}")
                    st.caption(gem.get("price_justification", ""))

                comp_score = gem.get("competition_score")
                if comp_score is not None:
                    st.write(f"**Competition:** {comp_score}/100")
                    st.progress(min(max(comp_score, 0), 100) / 100)

                searches = gem.get("est_monthly_searches")
                if searches is not None:
                    st.write(f"📊 **Est. Monthly Searches (AI estimate):** {searches:,}")
                    st.caption(gem.get("demand_reasoning", ""))

                trends = gem.get("trends_interest")
                if trends is not None:
                    st.write(f"📈 **Google Trends interest (real, relative 0-100):** {trends}")

                # Checkbox to mark as used
                is_checked = st.checkbox("Mark as Used / Ignore", key=f"check_{title}_{global_idx}")
                if is_checked:
                    st.session_state.used_gems.add(title)

# Display Excluded List Summary
if st.session_state.used_gems:
    st.markdown("---")
    st.caption(f"🔒 Excluded Items ({len(st.session_state.used_gems)} saved in memory to avoid duplicates):")
    st.write(", ".join(list(st.session_state.used_gems)))
