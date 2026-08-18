import streamlit as st
import google.generativeai as genai
import requests
import json

# Page Configuration
st.set_page_config(page_title="Etsy Digital Gem Finder", page_icon="💎", layout="wide")

st.title("💎 Etsy Digital Product Gem Finder")
st.write("Discover low-competition, high-demand digital product ideas based on real search intent.")

# Initialize Session State for Used Products
if "used_gems" not in st.session_state:
    st.session_state.used_gems = set()

# Sidebar Setup
st.sidebar.header("⚙️ Configuration")
api_key = st.sidebar.text_input("Enter Gemini API Key:", type="password")

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

# Function to fetch Google Autocomplete keywords
def get_live_search_suggestions(query):
    try:
        url = f"https://suggestqueries.google.com/complete/search?client=chrome&q={query}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = json.loads(response.text)
            return data[1][:5] # Return top 5 suggestions
    except Exception:
        pass
    return []

# Function to generate product gems
def generate_gems(niche, api_key):
    genai.configure(api_key=api_key)

    # 1. Dynamically find an active model on your API key
    try:
        available_models = [
            m.name for m in genai.list_models() 
            if 'generateContent' in m.supported_generation_methods
        ]
        selected_model = next((m for m in available_models if 'flash' in m), available_models[0])
        model = genai.GenerativeModel(selected_model)
    except Exception as err:
        raise Exception(f"Could not load an active model from your API key: {err}")
        
    # Fetch live search signals
    seed_terms = [f"{niche} tracker", f"{niche} binder", f"{niche} log book", f"{niche} template"]
    live_signals = []
    for term in seed_terms:
        live_signals.extend(get_live_search_suggestions(term))

    signals_text = ", ".join(live_signals) if live_signals else "general search trends"
    excluded_text = ", ".join(st.session_state.used_gems) if st.session_state.used_gems else "None"

    prompt = f"""
    You are an expert Etsy market researcher specializing in digital downloads (PDFs, Canva templates, spreadsheets).
    Target Niche: {niche}
    Real Search Signals Found: {signals_text}
    Previously Used/Excluded Ideas: {excluded_text}

    Task:
    Provide exactly 3 hidden gem digital product ideas that have HIGH search intent but LOW competition on Etsy.
    Do NOT suggest basic/generic ideas (e.g., plain "Daily Planner" or "Goal Tracker"). Suggest specific, functional tools for this micro-niche.

    Return ONLY a raw JSON array containing 3 objects with these exact keys:
    [
      {{
        "title": "Exact Product Name",
        "format": "e.g., Printable PDF / Canva Template / Excel Sheet",
        "description": "2-sentence functional overview of what is included in the download.",
        "search_intent": "The long-tail keyword real users search for",
        "competition": "Low or Very Low",
        "demand": "High"
      }}
    ]
    """

    response = model.generate_content(prompt)
    clean_json = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean_json)

# Main Trigger
if st.button("✨ Find 3 Hidden Product Gems"):
    if not api_key:
        st.error("Please enter your free Gemini API key in the sidebar to run the research pipeline.")
    elif not selected_niche or selected_niche == "Enter Custom Niche...":
        st.warning("Please select or type a valid niche first.")
    else:
        with st.spinner(f"Extracting search signals & generating gems for '{selected_niche}'..."):
            try:
                gems = generate_gems(selected_niche, api_key)
                st.session_state.current_gems = gems
            except Exception as e:
                st.error(f"Error generating ideas. Check your API key. Details: {e}")

# Display Results
if "current_gems" in st.session_state:
    st.subheader(f"Results for: {selected_niche}")
    cols = st.columns(3)

    for idx, gem in enumerate(st.session_state.current_gems):
        title = gem.get("title", "Product Idea")
        with cols[idx]:
            st.markdown(f"### {title}")
            st.caption(f"**Format:** {gem.get('format')}")
            st.write(gem.get('description'))
            
            st.info(f"**Target Keyword:** `{gem.get('search_intent')}`")
            st.write(f"📊 **Demand:** {gem.get('demand')} | **Competition:** {gem.get('competition')}")

            # Checkbox to mark as used
            is_checked = st.checkbox("Mark as Used / Ignore", key=f"check_{title}_{idx}")
            if is_checked:
                st.session_state.used_gems.add(title)

# Display Excluded List Summary
if st.session_state.used_gems:
    st.markdown("---")
    st.caption(f"🔒 Excluded Items ({len(st.session_state.used_gems)} saved in memory to avoid duplicates):")
    st.write(", ".join(list(st.session_state.used_gems)))
