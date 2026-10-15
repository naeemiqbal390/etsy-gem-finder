import io
import json
import re
import time
import uuid
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st
import google.generativeai as genai

try:
    from pytrends.request import TrendReq
    PYTRENDS = True
except ImportError:
    PYTRENDS = False

st.set_page_config(page_title="Opportunity Radar", page_icon="🎯", layout="wide")

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------
WEIGHTS = {"demand": 20, "intent": 15, "gap": 20, "pain": 15,
           "wtp": 15, "feasibility": 10, "distribution": 5}
CONF_FACTOR = {"High": 1.0, "Medium": 0.85, "Low": 0.7}

PROBLEM_COLS = ["problem_id", "buyer", "problem", "desired_outcome", "workaround",
                "gap", "solution", "search_phrases", "evidence_type",
                "evidence_strength", "source_url", "source_date", "notes"]
OPP_COLS = ["opp_id", "cluster", "buyer", "problem", "transformation", "product_idea",
            "working_title", "hero_line", "format", "price_hint", "search_phrases",
            "alternatives", "unmet_need", "demand", "intent", "gap", "pain", "wtp",
            "feasibility", "distribution", "confidence", "autocomplete_hits",
            "trends", "status", "next_action"]
KW_COLS = ["keyword", "seed", "source", "date"]

BUYERS = ["Freelancers & consultants", "Etsy & digital-product sellers", "Landlords & property managers",
          "Small retailers & shopkeepers", "Teachers & tutors", "Job seekers", "Bookkeepers",
          "Event & wedding planners", "Content creators", "Coaches", "Home-based businesses",
          "Parents managing family logistics", "Students", "Fitness professionals",
          "Pet-service providers", "Tradespeople & contractors", "Nonprofit administrators",
          "Photographers", "Foster & kinship parents", "Therapists & counselors (admin side)"]
JOBS = ["calculate", "track", "compare options", "prepare a document", "plan a project",
        "prevent costly errors", "price correctly", "get paid on time", "stay organized",
        "onboard a client", "forecast expenses", "prepare for a deadline", "reconcile records",
        "report results", "save time on repeat work"]
SUFFIXES = ["spreadsheet", "template", "calculator", "tracker", "checklist", "workbook",
            "system", "kit", "for beginners", "excel", "google sheets"]
PREFIXES = ["how to", "best way to", "i need to", "help with"]

# ---------------------------------------------------------------------------
# STATE
# ---------------------------------------------------------------------------
def init_state():
    for key, cols in (("problems", PROBLEM_COLS), ("opps", OPP_COLS), ("keywords", KW_COLS)):
        if key not in st.session_state:
            st.session_state[key] = pd.DataFrame(columns=cols)

init_state()


def ensure(df, cols):
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols]


def add_rows(key, cols, rows):
    new = pd.DataFrame(rows)
    new = ensure(new, cols)
    old = ensure(st.session_state[key], cols)
    st.session_state[key] = pd.concat([old, new], ignore_index=True)


def uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:6]}"

# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
st.sidebar.header("⚙️ Setup (all free)")
try:
    secret_key = st.secrets.get("GEMINI_API_KEY", None)
except Exception:
    secret_key = None
if secret_key:
    api_key = secret_key
    st.sidebar.success("Gemini key loaded from secrets.")
else:
    api_key = st.sidebar.text_input("Gemini API key (free from aistudio.google.com):", type="password")
model_name = st.sidebar.text_input(
    "Gemini model name", value="gemini-3.8-flash",
    help="If you get a 'model not found' error, open aistudio.google.com and copy a current free-tier "
         "Flash model name here.")
min_price = st.sidebar.number_input("Minimum realistic listing value ($)", 0, 200, 15)
st.sidebar.caption("Tip: your database lives in this browser session. Download it from the 💾 Database tab "
                   "before closing, and upload it next time.")


def ask_gemini(prompt, want_json=True):
    if not api_key:
        raise RuntimeError("Add a Gemini API key in the sidebar first.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    try:
        cfg = {"response_mime_type": "application/json"} if want_json else None
        resp = model.generate_content(prompt, generation_config=cfg) if cfg else model.generate_content(prompt)
    except Exception:
        resp = model.generate_content(prompt)
    return resp.text


def parse_json(text):
    text = text.replace("```json", "").replace("```", "").strip()
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if starts:
        text = text[min(starts):]
    return json.loads(text)


def suggest(query):
    """Google autocomplete: real phrases real people type. Free, no key."""
    try:
        r = requests.get("https://suggestqueries.google.com/complete/search",
                         params={"client": "firefox", "q": query}, timeout=5)
        if r.status_code == 200:
            return r.json()[1]
    except Exception:
        pass
    return []


def trends_score(keyword):
    if not PYTRENDS:
        return ""
    try:
        t = TrendReq(hl="en-US", tz=360)
        t.build_payload([keyword], timeframe="today 12-m")
        d = t.interest_over_time()
        return int(d[keyword].mean()) if not d.empty else ""
    except Exception:
        return ""


def score_row(r):
    total, done = 0.0, 0
    for k, w in WEIGHTS.items():
        v = pd.to_numeric(r.get(k), errors="coerce")
        v = 0 if pd.isna(v) else min(max(v, 0), 5)
        total += w * v / 5
        done += 1 if v > 0 else 0
    completeness = done / len(WEIGHTS)
    adj = total * CONF_FACTOR.get(r.get("confidence"), 0.7) * (0.5 + 0.5 * completeness)
    return round(total, 1), round(completeness * 100), round(adj, 1)


def verdict(adj, completeness):
    if completeness < 70:
        return "Research more (incomplete scoring)"
    if adj >= 70:
        return "VALIDATE NOW"
    if adj >= 55:
        return "Investigate competitors"
    if adj >= 40:
        return "Collect more evidence"
    return "Archive"


def df_download(df, label, name):
    st.download_button(label, df.to_csv(index=False).encode("utf-8"), name, "text/csv")

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("🎯 Opportunity Radar")
st.write("Find painful, paid-for problems first. Build the smallest solution second. "
         "Every idea here is a **From (painful state) → To (clear outcome)** transformation, not a generic planner.")

tabs = st.tabs(["1️⃣ Discover", "2️⃣ Evidence", "3️⃣ Opportunities", "4️⃣ Score & Rank",
                "5️⃣ Validate & Brief", "💾 Database", "⚠️ Limits"])

# ---------------------------- TAB 1: DISCOVER ------------------------------
with tabs[0]:
    st.subheader("Bulk problem discovery")
    st.caption("Real signal = Google autocomplete (what people actually type). The search-query matrix below "
               "gives you click-ready searches for Reddit, forums and Etsy reviews, so you never type random keywords.")
    c1, c2 = st.columns(2)
    sel_buyers = c1.multiselect("Buyer groups", BUYERS, default=BUYERS[:3])
    extra_buyer = c1.text_input("Add your own buyer group (optional)")
    sel_jobs = c2.multiselect("Painful jobs", JOBS, default=JOBS[:4])
    extra_job = c2.text_input("Add your own job (optional)")
    buyers = sel_buyers + ([extra_buyer] if extra_buyer else [])
    jobs = sel_jobs + ([extra_job] if extra_job else [])

    st.markdown("#### A. Problem-mining search matrix (opens real searches)")
    templates = {
        "Reddit wishes": 'site:reddit.com "{b}" "I wish" {j}',
        "Is there a tool": '"{b}" "is there a tool" {j}',
        "Spreadsheet pain": '"{b}" spreadsheet {j} "template" not working',
        "Etsy review gaps": 'site:etsy.com {b} {j} "I wish it had"',
        "Forum how-do-you": '"{b}" "how do you" {j}',
    }
    rows = []
    for b in buyers:
        for j in jobs:
            for name, tpl in templates.items():
                q = tpl.format(b=b.split(" &")[0], j=j)
                rows.append({"buyer": b, "job": j, "type": name, "query": q,
                             "open": "https://www.google.com/search?q=" + quote_plus(q)})
    if rows:
        mdf = pd.DataFrame(rows)
        st.dataframe(mdf, use_container_width=True, height=260,
                     column_config={"open": st.column_config.LinkColumn("Search", display_text="Open ↗")})
        st.caption(f"{len(mdf)} ready-made searches. Open a few per buyer, copy complaints and URLs into the Evidence tab.")
        df_download(mdf, "Download query matrix (CSV)", "query_matrix.csv")

    st.markdown("#### B. Autocomplete mining (real buyer phrasing, free)")
    seed_text = st.text_area("Seed topics, one per line (a problem or topic, e.g. 'foster parent reimbursement', 'freelance pricing')",
                             height=100)
    depth = st.slider("Expansion depth (more = slower)", 1, 3, 2)
    if st.button("⛏️ Mine autocomplete"):
        seeds = [s.strip() for s in seed_text.splitlines() if s.strip()]
        if not seeds:
            st.warning("Add at least one seed.")
        else:
            found, prog = [], st.progress(0.0)
            patterns = []
            for s in seeds:
                patterns += [(s, s)] + [(s, f"{s} {x}") for x in SUFFIXES[: 3 + depth * 3]]
                patterns += [(s, f"{p} {s}") for p in PREFIXES[:depth + 1]]
            for i, (seed, q) in enumerate(patterns):
                for kw in suggest(q):
                    found.append({"keyword": kw, "seed": seed, "source": "google_autocomplete",
                                  "date": time.strftime("%Y-%m-%d")})
                time.sleep(0.12)
                prog.progress((i + 1) / len(patterns))
            if found:
                kdf = pd.DataFrame(found).drop_duplicates("keyword")
                add_rows("keywords", KW_COLS, kdf.to_dict("records"))
                st.session_state.keywords = st.session_state.keywords.drop_duplicates("keyword", ignore_index=True)
                st.success(f"Collected {len(kdf)} unique real search phrases.")
            else:
                st.warning("No suggestions returned (network or rate limit). Try again in a minute.")
    if len(st.session_state.keywords):
        st.dataframe(st.session_state.keywords, use_container_width=True, height=240)

# ---------------------------- TAB 2: EVIDENCE ------------------------------
with tabs[1]:
    st.subheader("Turn pasted evidence into structured problems")
    st.caption("Paste reviews, forum posts or complaints with their URLs. AI classifies them; it must not invent anything. "
               "Five comments from one thread count as one observation.")
    excerpts = st.text_area("Paste excerpts + source URLs (one source per block, include the URL above each block):", height=260)
    if st.button("🧠 Extract problems"):
        non_url = [l for l in excerpts.splitlines() if l.strip() and not re.match(r"^\s*https?://\S+\s*$", l)]
        if not excerpts.strip():
            st.warning("Paste some evidence first.")
        elif len(" ".join(non_url)) < 200:
            st.warning("These look like links only. The AI cannot open links, so it would have nothing real to analyze "
                       "(and might guess from the URL words). Open each page, copy the actual post and comment text, "
                       "and paste it under its URL.")
        else:
            prompt = f"""You are a customer-problem extraction analyst. From ONLY the excerpts below, extract distinct,
real problems a digital product (spreadsheet, calculator, template, workbook, guide) could solve.
Never invent quotes, URLs, volumes, prices or sales. Merge duplicates. Separate evidence from interpretation.
Flag regulated-advice topics (tax, legal, medical, clinical) in notes.
Return ONLY a JSON array. Each object keys: buyer, problem, desired_outcome, workaround, gap (why existing
solutions fail, only if stated), solution (digital product idea), search_phrases (comma-separated),
evidence_type (complaint|request|purchase_review|question), evidence_strength (weak|moderate|strong),
source_url, source_date, notes.

EXCERPTS:
{excerpts[:24000]}"""
            try:
                with st.spinner("Extracting..."):
                    rows = parse_json(ask_gemini(prompt))
                for r in rows:
                    r["problem_id"] = uid("P")
                add_rows("problems", PROBLEM_COLS, rows)
                st.success(f"Added {len(rows)} problem records.")
            except Exception as e:
                st.error(f"Extraction failed: {e}")
    st.markdown("#### Problem database (editable)")
    st.session_state.problems = st.data_editor(
        ensure(st.session_state.problems, PROBLEM_COLS), num_rows="dynamic",
        use_container_width=True, key="problems_editor")

# ---------------------------- TAB 3: OPPORTUNITIES -------------------------
with tabs[2]:
    st.subheader("Create transformation opportunities")
    mode = st.radio("Source", ["From my evidence + autocomplete (recommended)", "AI hypotheses for a buyer group (unproven)"],
                    horizontal=True)
    buyer_in = st.text_input("Buyer group / focus", value=BUYERS[0])
    n_opps = st.slider("How many opportunities", 3, 12, 6)
    if st.button("🚀 Generate opportunities"):
        probs = ensure(st.session_state.problems, PROBLEM_COLS)
        kws = st.session_state.keywords
        prob_txt = probs.head(60)[["problem_id", "buyer", "problem", "desired_outcome", "workaround", "gap"]].to_json(orient="records")
        kw_txt = ", ".join(kws["keyword"].head(120).tolist()) if len(kws) else "none collected"
        evid = (f"REAL problem records (use these as the basis): {prob_txt}\nREAL autocomplete phrases: {kw_txt}"
                if mode.startswith("From") else
                f"No verified evidence supplied. Brainstorm HYPOTHESES for the buyer group; every one is unproven.\nREAL autocomplete phrases: {kw_txt}")
        prompt = f"""You design Etsy digital products that sell a TRANSFORMATION, never a generic planner/journal/tracker.
Buyer focus: {buyer_in}
{evid}

Rules:
- Each opportunity = ONE painful, specific problem and ONE concrete outcome. 'transformation' is written 'From <painful state> -> To <clear outcome>'.
- Product must be buildable by AI writing text, data, formulas or code (spreadsheet, fillable PDF, Word, swipe file). No Canva, no Notion, no illustration.
- Typical Etsy value >= ${min_price}. Reject anything a blank planner already solves.
- Promise a useful PROCESS, never guaranteed results (no 'guaranteed debt-free', 'maximize refund', 'make $X').
- Flag regulated topics (tax, legal, medical, clinical) in unmet_need as 'REGULATED'.
- working_title: starts with the phrase a buyer would type, then the outcome. Under 140 characters.
- hero_line: 2-5 word headline plus a one-line outcome.
- Do not claim demand, competition or sales numbers. Set alternatives to 'verify manually'.
- feasibility: 1-5 estimate of how buildable it is. Do not fill other scores.
Return ONLY a JSON array of {n_opps} objects with keys: cluster, buyer, problem, transformation, product_idea,
working_title, hero_line, format, price_hint (number), search_phrases (comma-separated), unmet_need, feasibility."""
        try:
            with st.spinner("Designing opportunities..."):
                rows = parse_json(ask_gemini(prompt))
            for r in rows:
                r.update({"opp_id": uid("O"), "alternatives": "verify manually", "demand": 0, "intent": 0,
                          "gap": 0, "pain": 0, "wtp": 0, "distribution": 0, "confidence": "Low",
                          "status": "Hypothesis" if not mode.startswith("From") else "Evidence-based",
                          "next_action": "Check autocomplete + competitors", "autocomplete_hits": "", "trends": ""})
            add_rows("opps", OPP_COLS, rows)
            st.success(f"Added {len(rows)} opportunities. Go to Score & Rank.")
        except Exception as e:
            st.error(f"Generation failed: {e}")
    if len(st.session_state.opps):
        show = ensure(st.session_state.opps, OPP_COLS)[["opp_id", "working_title", "transformation", "buyer", "status"]]
        st.dataframe(show, use_container_width=True)

# ---------------------------- TAB 4: SCORE ---------------------------------
with tabs[3]:
    st.subheader("Score with evidence, not vibes")
    st.caption("Rate each factor 0-5. 0 = no evidence. 5 = strong, independent, relevant evidence. "
               "Weights: Demand 20, Intent 15, Gap 20, Pain 15, Willingness-to-pay 15, Feasibility 10, Distribution 5.")
    with st.expander("Rubric (what a 5 requires)"):
        st.markdown("""
- **Demand**: autocomplete phrases + Trends + recurring questions agree.
- **Intent**: searches contain 'template', 'spreadsheet', 'calculator', 'tracker' (buying words), not just 'what is'.
- **Gap**: several named shortcomings in top sellers (1-3 star reviews, locked cells, no phone support), not just a low listing count.
- **Pain**: costly, recurring or urgent, shown in 3+ independent sources.
- **Willingness to pay**: comparable products show real purchase signals (review counts, 'bought recently').
- **Feasibility**: AI can build a complete working version.
- **Distribution**: Etsy search, Pinterest or a community can reach the buyer.
""")
    if len(st.session_state.opps) == 0:
        st.info("Generate opportunities first.")
    else:
        b1, b2 = st.columns(2)
        if b1.button("🔎 Refresh real signals (autocomplete + Trends)"):
            df = ensure(st.session_state.opps, OPP_COLS).copy()
            bar = st.progress(0.0)
            for i, idx in enumerate(df.index):
                phrase = str(df.at[idx, "search_phrases"]).split(",")[0].strip() or str(df.at[idx, "working_title"])[:40]
                df.at[idx, "autocomplete_hits"] = len(suggest(phrase))
                df.at[idx, "trends"] = trends_score(phrase)
                bar.progress((i + 1) / len(df))
            st.session_state.opps = df
        prep = ensure(st.session_state.opps, OPP_COLS).copy()
        for k in WEIGHTS:
            prep[k] = pd.to_numeric(prep[k], errors="coerce").fillna(0).astype(int)
        edited = st.data_editor(
            prep, num_rows="dynamic", use_container_width=True, key="opps_editor",
            column_config={
                **{k: st.column_config.NumberColumn(k.title(), min_value=0, max_value=5, step=1) for k in WEIGHTS},
                "confidence": st.column_config.SelectboxColumn("Confidence", options=["Low", "Medium", "High"]),
                "status": st.column_config.SelectboxColumn("Status", options=[
                    "Hypothesis", "Evidence-based", "Validating", "Build", "Rejected", "Built"]),
            })
        st.session_state.opps = edited
        ranked = edited.copy()
        res = ranked.apply(lambda r: score_row(r), axis=1, result_type="expand")
        ranked["score"], ranked["completeness_%"], ranked["adjusted"] = res[0], res[1], res[2]
        ranked["verdict"] = [verdict(a, c) for a, c in zip(ranked["adjusted"], ranked["completeness_%"])]
        ranked = ranked.sort_values("adjusted", ascending=False)
        st.markdown("#### Ranking")
        st.dataframe(ranked[["working_title", "score", "completeness_%", "adjusted", "confidence",
                              "autocomplete_hits", "trends", "verdict"]], use_container_width=True)
        st.caption("Adjusted = score x confidence factor (High 1.0 / Medium 0.85 / Low 0.7) x completeness. "
                   "A high score with thin evidence will not outrank a smaller, well-supported one.")

# ---------------------------- TAB 5: BRIEF ---------------------------------
with tabs[4]:
    st.subheader("Validate, then generate the Transformation Brief")
    opps = ensure(st.session_state.opps, OPP_COLS)
    if len(opps) == 0:
        st.info("No opportunities yet.")
    else:
        labels = {f"{r.working_title[:70]}  [{r.opp_id}]": r.opp_id for r in opps.itertuples()}
        choice = st.selectbox("Pick the opportunity to build", list(labels))
        row = opps[opps["opp_id"] == labels[choice]].iloc[0].to_dict()
        st.markdown("**Manual validation checklist (do this before building)**")
        st.checkbox("Looked at 10+ competing Etsy listings and wrote down specific shortcomings")
        st.checkbox("Found at least 3 independent sources where buyers express this pain")
        st.checkbox("Saw real purchase signals (reviews, 'bought recently') on comparable products")
        st.checkbox("Can state in one line how mine is different and better")
        st.checkbox("Checked it is not a regulated-advice trap (tax, legal, medical, clinical) or added a disclaimer plan")
        comp_notes = st.text_area("Competitor findings (paste: top 5 titles, current prices, common 1-3 star complaints). "
                                  "The brief becomes much better with real data.", height=140)
        if st.button("📝 Generate Transformation Brief"):
            prompt = f"""Create a Transformation Brief for an Etsy digital product. It will be pasted into a product-build prompt.
Opportunity: {json.dumps(row)}
Real competitor notes from the seller (may be empty): {comp_notes or 'none'}
Related evidence: {st.session_state.problems.head(30).to_json(orient='records')}

Rules: no guaranteed outcomes or income/debt/refund promises; no brand names or trademarks in title/tags;
buyer-typed phrase first in the title; every field must point at the problem and its solution; plain language.
Return ONLY a JSON object with keys:
product_name (what the buyer would type, 3-6 words), buyer, from_state (the painful situation, buyer's words),
to_state (the concrete outcome the file delivers), core_promise (one sentence: 'Go from X to Y'),
journey_steps (array of 3-6 short steps the product walks the buyer through, each ending in a visible result),
outcome_at_a_glance (the number/status the main dashboard must show), hero_headline (2-5 words),
hero_outcome_line (one line), title (under 140 chars), tags (array of exactly 13, each max 20 chars, multi-word,
mix of problem phrases, solution phrases, and buyer-intent phrases like 'google sheets template'),
first_sentence (stands alone: problem in buyer's words + outcome), recommended_format, compliance_flags (array),
differentiators (array of 3-5 specific, honest advantages; use competitor notes if given), risks (array)."""
            try:
                with st.spinner("Drafting brief..."):
                    brief = parse_json(ask_gemini(prompt))
                if isinstance(brief, list):
                    brief = brief[0]
                good = [t for t in brief.get("tags", []) if len(t) <= 20]
                dropped = len(brief.get("tags", [])) - len(good)
                brief["tags"] = good
                brief["_tag_note"] = (f"{dropped} tag(s) exceeded 20 characters and were removed; add replacements manually."
                                      if dropped else "")
                st.session_state.brief = brief
            except Exception as e:
                st.error(f"Brief failed: {e}")
        brief = st.session_state.get("brief")
        if brief:
            if brief.get("_tag_note"):
                st.warning(brief["_tag_note"])
            if len(brief.get("title", "")) >= 140:
                st.warning("Title is 140+ characters. Shorten it.")
            md = f"""TRANSFORMATION BRIEF
PRODUCT NAME: {brief.get('product_name')}
BUYER: {brief.get('buyer')}
FROM (painful state): {brief.get('from_state')}
TO (outcome): {brief.get('to_state')}
CORE PROMISE: {brief.get('core_promise')}
JOURNEY STEPS: {' | '.join(brief.get('journey_steps', []))}
OUTCOME AT A GLANCE (main dashboard must show): {brief.get('outcome_at_a_glance')}
HERO HEADLINE: {brief.get('hero_headline')}
HERO OUTCOME LINE: {brief.get('hero_outcome_line')}
CANDIDATE TITLE: {brief.get('title')}
CANDIDATE TAGS: {', '.join(brief.get('tags', []))}
FIRST DESCRIPTION SENTENCE: {brief.get('first_sentence')}
RECOMMENDED FORMAT: {brief.get('recommended_format')}
COMPLIANCE FLAGS: {', '.join(brief.get('compliance_flags', []))}
DIFFERENTIATORS: {' | '.join(brief.get('differentiators', []))}
RISKS: {' | '.join(brief.get('risks', []))}
COMPETITOR NOTES FROM SELLER: {comp_notes or 'none supplied'}
"""
            st.text_area("Copy this block into the BUILD prompt (replaces the brief placeholder)", md, height=380)
            st.download_button("⬇️ Download brief (.txt)", md.encode("utf-8"), "transformation_brief.txt", "text/plain")

# ---------------------------- TAB 6: DATABASE ------------------------------
with tabs[5]:
    st.subheader("Save and restore your research")
    st.caption("Streamlit Cloud does not keep files between sessions. Download after each session, upload to continue.")
    c1, c2, c3 = st.columns(3)
    with c1:
        df_download(ensure(st.session_state.problems, PROBLEM_COLS), "⬇️ Problems.csv", "problems.csv")
        up = st.file_uploader("Restore problems.csv", type="csv", key="u1")
        if up:
            st.session_state.problems = ensure(pd.read_csv(up).fillna(""), PROBLEM_COLS)
    with c2:
        df_download(ensure(st.session_state.opps, OPP_COLS), "⬇️ Opportunities.csv", "opportunities.csv")
        up = st.file_uploader("Restore opportunities.csv", type="csv", key="u2")
        if up:
            st.session_state.opps = ensure(pd.read_csv(up).fillna(""), OPP_COLS)
    with c3:
        df_download(ensure(st.session_state.keywords, KW_COLS), "⬇️ Keywords.csv", "keywords.csv")
        up = st.file_uploader("Restore keywords.csv", type="csv", key="u3")
        if up:
            st.session_state.keywords = ensure(pd.read_csv(up).fillna(""), KW_COLS)
    st.write(f"Problems: {len(st.session_state.problems)} | Opportunities: {len(st.session_state.opps)} | "
             f"Keywords: {len(st.session_state.keywords)}")

# ---------------------------- TAB 7: LIMITS --------------------------------
with tabs[6]:
    st.markdown("""
**What this app can and cannot do**
- Autocomplete phrases are real. AI-generated opportunities are **hypotheses** until you attach evidence.
- Google Trends (if installed) shows relative interest 0-100, not search volume, and is unofficial and can rate-limit.
- No free tool reports true Etsy sales for other shops. Use review counts, 'bought recently' badges and listing age by eye, and record them in the Competitor notes.
- The app does not scrape Etsy or Reddit (fragile, blocked from cloud servers, restricted by their terms). The query matrix opens the searches for you; you paste in what you find.
- Gemini free tier has rate and daily limits. Process evidence in chunks.
- A high score means "worth validating", not "will sell". Most candidates should be rejected.
- Results promised to buyers must be about the process, not guaranteed outcomes.
""")
