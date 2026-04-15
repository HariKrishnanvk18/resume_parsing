import streamlit as st
import mysql.connector
import pandas as pd
from sentence_transformers import SentenceTransformer, util
import os
import io
import json
import warnings
from dotenv import load_dotenv
from openai import OpenAI

# --- Google Drive API Imports ---
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- SETUP ---
warnings.filterwarnings('ignore')
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
load_dotenv()

st.set_page_config(page_title="TalentSift AI", layout="wide", page_icon="🎯")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- EMPLOYEE CREDENTIALS ---
EMPLOYEES = {
    "N2global001": "talentsift123",
    "N2global002": "talentsift123",
    "N2global003": "talentsift123",
    "N2global004": "talentsift123",
    "N2global005": "talentsift123",
    "N2global006": "talentsift123",
    "N2global007": "talentsift123",
    "N2global008": "talentsift123",
    "N2global009": "talentsift123",
    "N2global010": "talentsift123",
}

# --- EXACT LOGIN PAGE STYLE CSS ---
PAGE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');

html, body, [data-testid="stAppViewContainer"] {
    background-color: #f4f6f9 !important;
    font-family: 'DM Sans', sans-serif !important;
}
[data-testid="stHeader"] { display: none; }
[data-testid="stToolbar"] { display: none; }
[data-testid="stSidebar"] { display: none; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

/* Input labels */
.stTextInput > label,
.stTextArea > label,
.stNumberInput > label,
.stSelectbox > label {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    color: #29aae2 !important;
    letter-spacing: 0.4px !important;
    text-transform: uppercase !important;
    margin-bottom: 8px !important;
}

/* Input fields */
.stTextInput > div > div > input,
.stTextInput > div > input,
.stTextArea > div > div > textarea,
.stTextArea > div > textarea,
.stNumberInput > div > div > input,
input[type="text"], input[type="password"], textarea {
    background: #ffffff !important;
    background-color: #ffffff !important;
    border: 1px solid #e4e8ee !important;
    border-radius: 10px !important;
    padding: 12px 16px !important;
    font-size: 14px !important;
    color: #1a1a2e !important;
    -webkit-text-fill-color: #1a1a2e !important;
    font-family: 'DM Sans', sans-serif !important;
    caret-color: #1a1a2e !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #29aae2 !important;
    box-shadow: 0 0 0 3px rgba(41,170,226,0.10) !important;
    background: #ffffff !important;
    background-color: #ffffff !important;
    color: #1a1a2e !important;
    -webkit-text-fill-color: #1a1a2e !important;
}

/* Selectbox */
.stSelectbox > div > div {
    background: #f8fafc !important;
    border: 1px solid #e4e8ee !important;
    border-radius: 10px !important;
    color: #29aae2 !important;
    font-family: 'DM Sans', sans-serif !important;
}

/* Buttons - exact login page style */
.stButton > button {
    width: 100% !important;
    background: linear-gradient(135deg, #29aae2, #1a8abf) !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 13px !important;
    font-size: 15px !important;
    font-weight: 500 !important;
    color: #fff !important;
    font-family: 'DM Sans', sans-serif !important;
    transition: opacity 0.2s, transform 0.1s !important;
}
.stButton > button:hover {
    opacity: 0.9 !important;
    transform: translateY(-1px) !important;
}

/* Download button - green version */
.stDownloadButton > button {
    width: 100% !important;
    background: linear-gradient(135deg, #38b000, #2d9200) !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 13px !important;
    font-size: 15px !important;
    font-weight: 500 !important;
    color: #fff !important;
    font-family: 'DM Sans', sans-serif !important;
}

/* Cards - exact login card style */
.ts-card {
    background: #ffffff;
    border: 1px solid #e4e8ee;
    border-radius: 16px;
    padding: 28px 36px;
    margin-bottom: 16px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.06);
}

/* Candidate name */
.cand-name {
    font-family: 'Syne', sans-serif !important;
    font-size: 18px !important;
    font-weight: 700 !important;
    color: #1a1a2e !important;
}
.cand-score {
    float: right;
    color: #29aae2 !important;
    font-size: 18px !important;
    font-weight: 700 !important;
}
.cand-role {
    color: #aaa !important;
    font-size: 13px !important;
    font-family: 'DM Sans', sans-serif !important;
}
.cand-skills {
    color: #38b000 !important;
    font-size: 13px !important;
    font-family: 'DM Sans', sans-serif !important;
    margin-top: 6px !important;
}

hr {
    border: none !important;
    border-top: 1px solid #e4e8ee !important;
    margin: 20px 0 !important;
}

/* Spinner text black */
.stSpinner > div > div {
    color: #1a1a2e !important;
}
[data-testid="stSpinner"] p {
    color: #1a1a2e !important;
}
</style>
"""

# =====================================================
# LOGIN PAGE
# =====================================================
def show_login():
    st.markdown(PAGE_CSS, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<div style='height:48px'></div>", unsafe_allow_html=True)

        # Brand - logo LEFT side of heading
        logo_col, name_col = st.columns([1, 2])
        with logo_col:
            try:
                st.image("logo.png", width=130)
            except:
                pass
        with name_col:
            st.markdown("""
                <div style='display:flex;align-items:center;height:130px;margin-bottom:8px;'>
                    <div>
                        <span style='font-family:Syne,sans-serif;font-size:28px;font-weight:800;letter-spacing:-0.5px;color:#29aae2;'>TalentSift </span>
                        <span style='font-family:Syne,sans-serif;font-size:28px;font-weight:800;letter-spacing:-0.5px;color:#38b000;'>AI</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)

        emp_id = st.text_input("Employee ID", placeholder="Enter your Employee ID", key="login_id")
        password = st.text_input("Password", type="password", placeholder="••••••••••", key="login_pass")
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        if st.button("Sign in to TalentSift AI", use_container_width=True):
            matched_key = next((k for k in EMPLOYEES if k.lower() == emp_id.strip().lower()), None)
            if matched_key and EMPLOYEES[matched_key] == password.strip():
                st.session_state.logged_in = True
                st.session_state.employee_id = matched_key
                st.rerun()
            else:
                st.error("❌ Invalid Employee ID or Password!")

        st.markdown("""
            <p style='font-size:13px;color:#bbb;text-align:center;margin-top:20px;font-family:DM Sans,sans-serif;'>
                By signing in, you agree to our
                <a href='#' style='color:#29aae2;text-decoration:none;'>Terms</a> &amp;
                <a href='#' style='color:#29aae2;text-decoration:none;'>Privacy</a>
            </p>
        """, unsafe_allow_html=True)

# --- CHECK LOGIN ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    show_login()
    st.stop()

# =====================================================
# MAIN APP - EXACT SAME STYLE AS LOGIN PAGE
# =====================================================
st.markdown(PAGE_CSS, unsafe_allow_html=True)

if 'ranked_results' not in st.session_state:
    st.session_state.ranked_results = None
if 'llm_rules' not in st.session_state:
    st.session_state.llm_rules = None
if 'jd_input_value' not in st.session_state:
    st.session_state.jd_input_value = ""
if 'clear_counter' not in st.session_state:
    st.session_state.clear_counter = 0

# --- TOP BAR - same card style as login ---
st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

col_brand, col_logout = st.columns([8, 1])
with col_brand:
    nav_logo_col, nav_text_col = st.columns([1, 9])
    with nav_logo_col:
        try:
            st.image("logo.png", width=130)
        except:
            pass
    with nav_text_col:
        st.markdown(f"""
            <div style='background:#ffffff;border:1px solid #e4e8ee;border-radius:16px;
                        padding:20px 36px;box-shadow:0 4px 24px rgba(0,0,0,0.06);
                        display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;'>
                <div>
                    <span style='font-family:Syne,sans-serif;font-size:24px;font-weight:800;color:#29aae2;'>TalentSift </span>
                    <span style='font-family:Syne,sans-serif;font-size:24px;font-weight:800;color:#38b000;'>AI</span>
                </div>
                <div style='font-size:13px;color:#aaa;font-family:DM Sans,sans-serif;'>
                    👤 {st.session_state.get('employee_id', '')}
                </div>
            </div>
        """, unsafe_allow_html=True)
with col_logout:
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    if st.button("🚪 Logout"):
        st.session_state.logged_in = False
        st.rerun()

# --- MAIN CARD - same card style ---
st.markdown("""
    <div style='background:#ffffff;border:1px solid #e4e8ee;border-radius:16px;
                padding:36px 44px;box-shadow:0 4px 24px rgba(0,0,0,0.06);margin-bottom:24px;'>
        <p style='font-family:Syne,sans-serif;font-size:20px;font-weight:700;color:#1a1a2e;margin-bottom:4px;'>
            🎯 Find & Rank Perfect Candidates
        </p>
        <p style='font-size:13px;color:#aaa;font-family:DM Sans,sans-serif;'>
            Enter a job description to find the best matching candidates.
        </p>
    </div>
""", unsafe_allow_html=True)

# --- LOAD MODEL ---
@st.cache_resource
def load_model():
    return SentenceTransformer('all-MiniLM-L6-v2')

ranking_model = load_model()

def perfect_match_rules(jd_input, target_loc_input):
    prompt = f"""
    Analyze JD: "{jd_input}" and Target Location: "{target_loc_input}"
    1. Find US State Code and 3 nearby states.
    2. Identify 5-8 Job Title synonyms.
    3. Identify ONE mandatory tech skill.
    4. Extract minimum years of experience (integer).
    Return ONLY JSON:
    {{
        "state_code": "TX", "nearby": ["OK", "LA", "NM"],
        "role_keywords": ["Java", "Backend"],
        "mandatory_skill": "Kafka", "extracted_exp": 5
    }}
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0
    )
    return json.loads(response.choices[0].message.content)

def get_ai_insight(jd, resume, cand_name):
    prompt = f"""
    Act as a Senior Executive Recruiting Manager.
    Explain why '{cand_name}' is a high-potential match for this JD.
    Tone: "I highly recommend {cand_name} because..."
    JD: {jd[:300]}
    Resume: {resume[:500]}
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=250
    )
    return response.choices[0].message.content

def get_db_connection():
    return mysql.connector.connect(
        host="localhost", user="root", password=os.getenv("DB_PASSWORD"), database="drive_to_sql_v2"
    )

def fetch_drive_file(filename):
    try:
        creds = Credentials.from_authorized_user_file('token.json', ['https://www.googleapis.com/auth/drive'])
        service = build('drive', 'v3', credentials=creds)
        query = f"name='{filename}' and trashed=false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        if not files: return None
        file_id = files[0]['id']
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return fh.getvalue()
    except:
        return None

# --- INPUTS - same card style ---
col_jd1, col_jd2 = st.columns([4, 1])
with col_jd1:
    jd_area_input = st.text_area(
        "📋 Job Description / Key Skills:",
        value=st.session_state.jd_input_value,
        height=150,
        key=f"jd_input_field_{st.session_state.clear_counter}"
    )
with col_jd2:
    st.write("##")
    if st.button("🧹 Clear JD"):
        st.session_state.jd_input_value = ""
        st.session_state.clear_counter += 1
        st.rerun()

col_sub1, col_sub2, col_sub3 = st.columns([1, 1, 1])
with col_sub1:
    ui_min_exp = st.number_input("⏳ UI Exp Fallback:", min_value=0, value=5)
with col_sub2:
    us_states = ["All States", "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]
    target_loc_input = st.selectbox("📍 Target Location:", options=us_states, index=0)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
search_btn = st.button("🚀 Find & Rank Perfect Matches", use_container_width=True)
st.markdown("---")

# --- RANKING ENGINE ---
if search_btn:
    if jd_area_input:
        st.session_state.jd_input_value = jd_area_input
        with st.spinner("Analyzing & Ranking... 🧠"):
            try:
                rules = perfect_match_rules(jd_area_input, target_loc_input if target_loc_input != "All States" else "USA")
                final_min_exp = rules['extracted_exp'] if rules['extracted_exp'] > 0 else ui_min_exp
                loc_condition = "1=1" if target_loc_input == "All States" else f"(location IN ('{rules['state_code']}','{','.join(rules['nearby'])}') OR location = 'Unknown')"
                role_conditions = " OR ".join([f"role LIKE '%{k}%'" for k in rules['role_keywords']])
                mandatory_skill = rules['mandatory_skill']
                skill_condition = f"(skills LIKE '%{mandatory_skill}%' OR resume_text LIKE '%{mandatory_skill}%')"
                db = get_db_connection()
                sql_query = f"SELECT * FROM users WHERE experience >= {final_min_exp} AND {loc_condition} AND ({role_conditions}) AND {skill_condition} AND is_active = 1"
                df = pd.read_sql(sql_query, db)
                db.close()
                if df.empty:
                    st.warning("No matches found.")
                    st.session_state.ranked_results = None
                else:
                    jd_embedding = ranking_model.encode(jd_area_input, convert_to_tensor=True)
                    resume_embeddings = ranking_model.encode(df['resume_text'].tolist(), convert_to_tensor=True)
                    scores = util.cos_sim(jd_embedding, resume_embeddings)[0].tolist()
                    df['AI_Score'] = [round(min(99.5, 75 + (s * 40)), 1) for s in scores]
                    st.session_state.ranked_results = df.sort_values(by='AI_Score', ascending=False).head(10)
                    st.session_state.llm_rules = {"skill": mandatory_skill, "exp": final_min_exp}
            except Exception as e:
                st.error(f"Error: {e}")

# --- DISPLAY RESULTS ---
if st.session_state.ranked_results is not None:
    res = st.session_state.ranked_results
    st.success(f"🎯 Target Exp: {st.session_state.llm_rules['exp']}+ yrs | Mandatory Skill: {st.session_state.llm_rules['skill']}")

    for idx, row in res.iterrows():
        # Candidate card - exact same white card style as login
        st.markdown(f"""
            <div style='background:#ffffff;border:1px solid #e4e8ee;border-radius:16px;
                        padding:28px 36px;margin-bottom:16px;
                        box-shadow:0 4px 24px rgba(0,0,0,0.06);'>
                <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;'>
                    <span style='font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:#1a1a2e;'>
                        {row['name']}
                    </span>
                    <span style='font-family:Syne,sans-serif;font-size:18px;font-weight:700;color:#29aae2;'>
                        {row['AI_Score']}% Match
                    </span>
                </div>
                <p style='font-size:13px;color:#aaa;font-family:DM Sans,sans-serif;margin-bottom:6px;'>
                    💼 <b>{row['role']}</b> &nbsp;|&nbsp; ⏳ {row['experience']} yrs &nbsp;|&nbsp; 📍 {row['location']}
                </p>
                <p style='font-size:13px;color:#38b000;font-family:DM Sans,sans-serif;'>
                    ✅ <b>Matched Skills:</b> {row['skills'][:150]}...
                </p>
            </div>
        """, unsafe_allow_html=True)

        c1, c2, c3 = st.columns([1.5, 1.5, 0.5])
        with c1:
            if st.button(f"✨ Senior HR Insight", key=f"ai_{row['id']}"):
                st.info(get_ai_insight(st.session_state.jd_input_value, row['resume_text'], row['name']))
        with c2:
            file_bytes = fetch_drive_file(row['filename'])
            if file_bytes:
                st.download_button(f"📥 Download Resume", data=file_bytes, file_name=row['filename'], key=f"dl_{row['id']}")
        with c3:
            with st.popover("🗑️"):
                st.write(f"Hide {row['name']}?")
                if st.button("Confirm", key=f"del_{row['id']}"):
                    db = get_db_connection()
                    curr = db.cursor()
                    curr.execute(f"UPDATE users SET is_active = 0 WHERE id = {row['id']}")
                    db.commit()
                    db.close()
                    st.rerun()
