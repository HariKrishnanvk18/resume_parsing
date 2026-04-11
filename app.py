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

st.set_page_config(page_title="ResumeRadar AI | N2 Global", layout="wide", page_icon="🎯")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- INITIALIZE SESSION STATE ---
if 'ranked_results' not in st.session_state:
    st.session_state.ranked_results = None
if 'llm_rules' not in st.session_state:
    st.session_state.llm_rules = None
if 'jd_input_value' not in st.session_state:
    st.session_state.jd_input_value = ""
if 'clear_counter' not in st.session_state:
    st.session_state.clear_counter = 0

# --- CUSTOM CSS (Vibrant UI & Black Text Buttons) ---
st.markdown(f"""
<style>
    /* Global Background */
    .stApp {{
        background-color: #562a83;
    }}
    
    /* Labels & Text to Pure White */
    label, .stMarkdown p, p, span, .stTextArea label, .stNumberInput label, .stSelectbox label {{
        color: white !important;
        font-weight: bold !important;
        font-size: 16px !important;
    }}

    /* Intense Neon Logo Title */
    .neon-logo {{
        font-size: 70px; font-weight: 900; color: #fff; text-align: center;
        text-transform: uppercase; letter-spacing: 5px;
        text-shadow: 
            0 0 10px #fff, 0 0 20px #fff, 
            0 0 40px #0ff, 0 0 60px #0ff, 
            0 0 80px #0ff, 0 0 120px #0ff;
        margin-top: -10px; margin-bottom: 25px;
        display: block; width: 100%;
    }}

    /* Logo Centering Fix */
    [data-testid="stImage"] {{
        display: block;
        margin-left: auto;
        margin-right: auto;
    }}

    /* Candidate Card */
    .candidate-card {{
        background-color: #1e1e1e; padding: 25px; border-radius: 20px;
        border-left: 8px solid #01efac; margin-bottom: 20px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }}

    /* FIX: Button Style (All Action Buttons with BLACK LETTERS) */
    .stButton>button {{
        background-color: #01efac !important; /* Seafoam background */
        color: black !important;             /* BLACK TEXT as requested */
        font-weight: 900 !important;
        border: none !important;
        border-radius: 20px !important;
        width: 100%;
        transition: 0.3s;
    }}

    /* Extra Glow for Rank Button */
    div.stButton > button:first-child {{
        box-shadow: 0 0 20px #01efac;
    }}

    #MainMenu {{visibility: hidden;}} 
    footer {{visibility: hidden;}}
    header {{visibility: hidden;}}
</style>
""", unsafe_allow_html=True)

# --- HEADER ---
_, center_col, _ = st.columns([2, 1, 2])
with center_col:
    try:
        st.image("logo.png", width=180)
    except:
        st.write("<h3 style='text-align:center; color:white;'>[ N2 ]</h3>", unsafe_allow_html=True)

st.markdown('<div class="neon-logo">N2 GLOBAL SERVICES</div>', unsafe_allow_html=True)

# --- LOAD AI MODEL ---
@st.cache_resource
def load_model():
    return SentenceTransformer('all-MiniLM-L6-v2')

ranking_model = load_model()

# --- THE PERFECT MATCH BRAIN ---
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
        response_format={ "type": "json_object" },
        temperature=0
    )
    return json.loads(response.choices[0].message.content)

# --- SENIOR HR INSIGHT (FIXED CONTENT & NAME) ---
def get_ai_insight(jd, resume, cand_name):
    prompt = f"""
    Act as a Senior Executive Recruiting Manager. 
    Explain why '{cand_name}' is a high-potential match for this JD. 
    State explicitly WHY we should hire this person, focusing on technical match and achievements.
    Tone: Professional recommendation: "I highly recommend {cand_name} because..."
    JD: {jd[:300]}
    Resume: {resume[:500]}
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=250
    )
    return response.choices[0].message.content

# --- DB & DRIVE FUNCTIONS ---
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
    except: return None

# --- UI LAYOUT ---
col_jd1, col_jd2 = st.columns([4, 1])
with col_jd1:
    # FIX: Using 'value' linked to session_state and a dynamic key to force reset
    jd_area_input = st.text_area(
        "📋 Job Description / Key Skills:", 
        value=st.session_state.jd_input_value, 
        height=150, 
        key=f"jd_input_field_{st.session_state.clear_counter}"
    )
with col_jd2:
    st.write("##")
    if st.button("🧹 Clear JD"):
        # This increments the counter which changes the widget key, forcing a total reset
        st.session_state.jd_input_value = ""
        st.session_state.clear_counter += 1
        st.rerun()

col_sub1, col_sub2, col_sub3 = st.columns([1, 1, 1])
with col_sub1:
    ui_min_exp = st.number_input("⏳ UI Exp Fallback:", min_value=0, value=5)
with col_sub2:
    us_states = ["All States", "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]
    target_loc_input = st.selectbox("📍 Target Location:", options=us_states, index=0)

search_btn = st.button("🚀 Find & Rank Perfect Matches")
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
    st.success(f"🎯 Target Exp: {st.session_state.llm_rules['exp']}+ | Mandatory Skill: {st.session_state.llm_rules['skill']}")

    for idx, row in res.iterrows():
        with st.container():
            st.markdown(f"""
            <div class="candidate-card">
                <h3 style="color: #fff; margin-bottom: 5px;">{row['name']} <span style="float:right; color:#01efac;">{row['AI_Score']}%</span></h3>
                <p style="color: #ccc;"><b>{row['role']}</b> | {row['experience']} yrs | {row['location']}</p>
                <p style="color: #01efac; font-size: 14.5px;"><b>Matched Skills:</b> {row['skills'][:150]}...</p>
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