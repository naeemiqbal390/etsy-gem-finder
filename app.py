import streamlit as st
import google.generativeai as genai
import requests
import json

# Optional: real (relative) search-interest signal from Google Trends.
# This is an unofficial API and can occasionally fail/rate-limit — always wrapped in try/except.
try:
    from pytrends.request import TrendReq
    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False

# Page Configuration
st.set_page_config(page_title="Etsy Digital Gem Finder", page_icon="💎", layout="wide")

st.title("💎 Etsy Digital Product Gem Finder")
st.write("Discover low-competition, high-demand digital product ideas — filtered to products you can actually build with AI (Claude/Gemini), not design tools.")

# Initialize Session State for Used Products
if "used_gems" not in st.session_state:
    st.session_state.used_gems = set()

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

num_gems = st.sidebar.slider("How many product ideas to generate:", min_value=3, max_value=10, value=3)
min_price = st.sidebar.number_input("Minimum typical price ($):", min_value=0, value=15, step=1)

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


# Function to generate product gems
def generate_gems(niche, api_key, count, min_price):
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

    prompt = f"""
    You are an expert Etsy market researcher specializing in digital downloads.
    Target Niche: {niche}
    Real Search Signals Found: {signals_text}
    Previously Used/Excluded Ideas: {excluded_text}

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
    if not api_key:
        st.error("Please provide a Gemini API key (via secrets or the sidebar) to run the research pipeline.")
    elif not selected_niche or selected_niche == "Enter Custom Niche...":
        st.warning("Please select or type a valid niche first.")
    else:
        with st.spinner(f"Extracting search signals & generating gems for '{selected_niche}'..."):
            try:
                gems = generate_gems(selected_niche, api_key, num_gems, min_price)
                st.session_state.current_gems = gems
            except Exception as e:
                st.error(f"Error generating ideas: {e}")

# Display Results
if "current_gems" in st.session_state and st.session_state.current_gems:
    st.subheader(f"Results for: {selected_niche}")
    st.caption("⚠️ Competition score and monthly-search numbers are AI estimates, not scraped Etsy/Google data. "
               "'Trends interest' (where shown) is a real signal from Google Trends, but it's relative popularity "
               "(0-100), not an absolute search count.")

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
