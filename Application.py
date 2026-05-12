import streamlit as st
import mysql.connector
import pandas as pd
from sentence_transformers import SentenceTransformer, util
import os
import io
import json
import warnings
import base64
from dotenv import load_dotenv
from openai import OpenAI
import mammoth

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

warnings.filterwarnings('ignore')
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
load_dotenv()

st.set_page_config(page_title="TalentSift AI", layout="wide", page_icon="🎯")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

ALLOWED_IDS = os.getenv("TS_ALLOWED_IDS", "").split(",")
GLOBAL_PASSWORD = os.getenv("TS_GLOBAL_PASSWORD", "default_pass")

PAGE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');

html, body, [data-testid="stAppViewContainer"] {
    background-color: #f4f6f9 !important;
    font-family: 'DM Sans', sans-serif !important;
}
[data-testid="stHeader"], [data-testid="stToolbar"] { display: none; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

div[data-baseweb="select"] > div {
    background-color: #ffffff !important;
    border: 1px solid #e4e8ee !important;
    border-radius: 10px !important;
}

.stTextInput > label, .stTextArea > label, .stNumberInput > label, .stSelectbox > label {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    color: #29aae2 !important;
    letter-spacing: 0.4px !important;
    text-transform: uppercase !important;
    margin-bottom: 8px !important;
}

.stTextInput > div > div > input, .stTextArea > div > div > textarea, input, textarea {
    background: #ffffff !important;
    border: 1px solid #e4e8ee !important;
    border-radius: 10px !important;
    padding: 12px 16px !important;
    color: #1a1a2e !important;
}

.stButton > button {
    width: 100% !important;
    background: linear-gradient(135deg, #29aae2, #1a8abf) !important;
    border: none !important;
    border-radius: 10px !important;
    color: #fff !important;
    font-weight: 500 !important;
    transition: 0.2s;
}

.ts-card {
    background: #ffffff;
    border: 1px solid #e4e8ee;
    border-radius: 16px;
    padding: 28px 36px;
    margin-bottom: 16px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.06);
}
</style>
"""

# =====================================================
# SPEED OPTIMIZATION
# =====================================================
@st.cache_resource
def load_model():
    return SentenceTransformer('all-MiniLM-L6-v2')

@st.cache_data(show_spinner=False)
def get_cached_embeddings(_model, text_list):
    return _model.encode(text_list, convert_to_tensor=True)

# =====================================================
# AI BRAIN — Rules Extraction
# =====================================================
def perfect_match_rules(jd_input, target_loc_input):
    prompt = f"""
    Analyze JD: "{jd_input}" and Target Location: "{target_loc_input}"
    1. Find US State Code and 3 nearby states.
    2. Identify 5-8 Job Title synonyms.
    3. Identify ALL technical skills and tools (List 8-12 key skills).
    4. Extract minimum years of experience (integer).
    Return ONLY JSON:
    {{
        "state_code": "TX", "nearby": ["OK", "LA", "NM"],
        "role_keywords": ["Java", "Backend"],
        "all_skills": ["Java", "Spring Boot", "Kafka", "SQL", "AWS"], 
        "extracted_exp": 5
    }}
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0
    )
    return json.loads(response.choices[0].message.content)

# =====================================================
# HR INSIGHT
# =====================================================
def get_ai_insight(jd, resume, cand_name, role, experience, location, skills):
    prompt = f"""
Write EXACTLY in this format.

Hello Team,

Please find the attached resume and details of {cand_name} for [Job Title] – [Location]

Note: [3 professional sentences on expertise and fit based on resume and JD.]

Full Legal Name: {cand_name}
Work Authorization: [Guess USC / GC / H1B based on resume context]
Total Experience: {experience}+ Years
Current Location: {location}
Key Skills: {skills[:100]}
Availability: Immediate / 2 weeks
Willing for Relocation: Yes / No

Best Regards,
TalentSift AI Recruiting Team

JD: {jd[:400]} | Resume: {resume[:500]}
"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400
    )
    return response.choices[0].message.content

# =====================================================
# DRIVE FETCH — Local JSON Version
# =====================================================
def fetch_drive_file(filename):
    try:
        with open("service_account.json") as f:
            service_account_info = json.load(f)
        
        creds = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        
        service = build('drive', 'v3', credentials=creds)
        
        res = service.files().list(
            q=f"name='{filename}' and trashed=false",
            fields="files(id)"
        ).execute()
        
        files = res.get('files', [])
        if not files: 
            return None
            
        req = service.files().get_media(fileId=files[0]['id'])
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, req)
        
        done = False
        while not done:
            _, done = downloader.next_chunk()
            
        return fh.getvalue()
        
    except Exception as e:
        st.error(f"Drive error: {e}")
        return None
# =====================================================
# DIALOGS
# =====================================================
@st.dialog("🗑️ Hide Candidate")
def delete_dialog(cand_id, cand_name):
    st.write(f"Do you want to hide **{cand_name}** from the results?")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Confirm"):
            db = mysql.connector.connect(
                host="localhost", user="root",
                password=os.getenv("DB_PASSWORD"),
                database="drive_to_sql_v2"
            )
            curr = db.cursor()
            curr.execute("UPDATE users SET is_active = 0 WHERE id = %s", (cand_id,))
            db.commit(); db.close()
            st.cache_data.clear()
            st.rerun()
    with c2:
        if st.button("No"): st.rerun()

@st.dialog("📥 Download Confirmation")
def download_dialog(filename, cand_name):
    st.write(f"Download **{cand_name}**'s resume?")
    file_data = fetch_drive_file(filename)
    c1, c2 = st.columns(2)
    with c1:
        if file_data:
            st.download_button("Yes, Download", data=file_data, file_name=filename)
    with c2:
        if st.button("No"): st.rerun()

@st.dialog("📄 Resume Preview", width="large")
def preview_dialog(filename):
    file_bytes = fetch_drive_file(filename)
    if file_bytes:
        file_ext = filename.split('.')[-1].lower()
        if file_ext == 'pdf':
            base64_pdf = base64.b64encode(file_bytes).decode('utf-8')
            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="900" type="application/pdf"></iframe>'
            st.markdown(pdf_display, unsafe_allow_html=True)
        elif file_ext in ['docx', 'doc']:
            with st.spinner("Getting Word document ready..."):
                try:
                    result = mammoth.convert_to_html(io.BytesIO(file_bytes))
                    html_content = result.value
                    st.markdown(f"""
                    <div style="background:white;padding:40px;border:1px solid #eee;
                    border-radius:10px;height:800px;overflow-y:scroll;color:black;">
                        {html_content}
                    </div>
                    """, unsafe_allow_html=True)
                    st.info("💡 This is a quick preview. Formatting may vary slightly.")
                except:
                    st.error("Unable to preview. Please download.")
                    st.download_button("📥 Download Now", data=file_bytes, file_name=filename)
    else:
        st.error("Unable to retrieve file from Google Drive.")

# =====================================================
# LOGIN PAGE
# =====================================================
def show_login():
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<div style='height:48px'></div>", unsafe_allow_html=True)
        logo_col, name_col = st.columns([1, 2])
        with logo_col:
            try: st.image("logo.png", width=130)
            except: pass
        with name_col:
            st.markdown("""
            <div style='display:flex;align-items:center;height:130px;margin-bottom:8px;'>
                <div>
                    <span style='font-family:Syne,sans-serif;font-size:28px;
                    font-weight:800;color:#29aae2;'>TalentSift </span>
                    <span style='font-family:Syne,sans-serif;font-size:28px;
                    font-weight:800;color:#38b000;'>AI</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
        emp_id = st.text_input("Employee ID", placeholder="Enter your Employee ID", key="login_id")
        password = st.text_input("Password", type="password", key="login_pass")
        if st.button("Sign in to TalentSift AI"):
            if any(emp_id.strip().lower() == a.lower() for a in ALLOWED_IDS) and password.strip() == GLOBAL_PASSWORD:
                st.session_state.logged_in = True
                st.session_state.employee_id = emp_id.strip()
                st.rerun()
            else:
                st.error("❌ Invalid Credentials!")

if not st.session_state.get('logged_in', False):
    show_login()
    st.stop()

# =====================================================
# MAIN APP
# =====================================================
st.markdown(PAGE_CSS, unsafe_allow_html=True)

if 'ranked_results' not in st.session_state: st.session_state.ranked_results = None
if 'insight_cache' not in st.session_state: st.session_state.insight_cache = {}
if 'jd_input_value' not in st.session_state: st.session_state.jd_input_value = ""
if 'clear_counter' not in st.session_state: st.session_state.clear_counter = 0
if 'llm_rules' not in st.session_state: st.session_state.llm_rules = None

# --- HEADER BAR ---
st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
col_brand, col_logout = st.columns([8, 1])
with col_brand:
    nav_logo_col, nav_text_col = st.columns([1, 9])
    with nav_logo_col:
        try: st.image("logo.png", width=130)
        except: pass
    with nav_text_col:
        st.markdown(f"""
        <div style='background:#ffffff;border:1px solid #e4e8ee;border-radius:16px;
        padding:20px 36px;box-shadow:0 4px 24px rgba(0,0,0,0.06);
        display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;'>
            <div>
                <span style='font-family:Syne,sans-serif;font-size:24px;
                font-weight:800;color:#29aae2;'>TalentSift </span>
                <span style='font-family:Syne,sans-serif;font-size:24px;
                font-weight:800;color:#38b000;'>AI</span>
            </div>
            <div style='font-size:13px;color:#aaa;'>
                👤 {st.session_state.employee_id}
            </div>
        </div>
        """, unsafe_allow_html=True)

with col_logout:
    if st.button("🚪 Logout"):
        st.session_state.logged_in = False
        st.rerun()

ranking_model = load_model()

# --- UI INPUTS ---
col_jd1, col_jd2 = st.columns([5, 1])
with col_jd1:
    jd_area_input = st.text_area(
        "📋 Job Description / Key Skills:",
        value=st.session_state.jd_input_value,
        height=220,
        key=f"jd_{st.session_state.clear_counter}"
    )
with col_jd2:
    st.markdown("<div style='height:148px'></div>", unsafe_allow_html=True)
    if jd_area_input and jd_area_input.strip(): 
        if st.button("🧹 Clear"):
            st.session_state.jd_input_value = ""
            st.session_state.clear_counter += 1
            st.rerun()

col_sub1, col_sub2, col_sub3 = st.columns([1, 1, 1])
with col_sub1:
    ui_min_exp = st.number_input("⏳ Experience :", min_value=0, value=5)
with col_sub2:
    target_loc_input = st.selectbox("📍 Target Location:", options=[
        "All States","AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
        "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI",
        "MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND",
        "OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA",
        "WA","WV","WI","WY"
    ])

# --- SEARCH BUTTON ---
if st.button("🚀 Find & Rank Perfect Matches", use_container_width=True):
    if jd_area_input:
        st.session_state.jd_input_value = jd_area_input
        with st.spinner("Analyzing & Ranking... 🧠⚡"):
            try:
                # 1. AI Rules Extraction
                rules = perfect_match_rules(
                    jd_area_input,
                    target_loc_input if target_loc_input != "All States" else "USA"
                )
                final_min_exp = rules['extracted_exp'] if rules['extracted_exp'] > 0 else ui_min_exp
                extracted_skills = rules.get('all_skills', [])

                # --- SMART LOCATION LOGIC ---
                strict_keywords = ["strictly", "only", "must be", "required in"]
                is_strict = any(word in jd_area_input.lower() for word in strict_keywords)

                if target_loc_input != "All States":
                    state = target_loc_input
                    loc_condition = f"location = '{state}'" if is_strict else f"(location = '{state}' OR location = 'N/A')"
                elif rules.get('state_code'):
                    state = rules['state_code']
                    nearby = "','".join(rules.get('nearby', []))
                    loc_condition = f"location = '{state}'" if is_strict else f"(location IN ('{state}', '{nearby}') OR location = 'N/A')"
                else:
                    loc_condition = "1=1"

                role_conditions = " OR ".join([f"role LIKE '%{k}%'" for k in rules['role_keywords']])

                # --- SPEED FIX & SAFETY: SQL Filter with Quote Escaping ---
                if extracted_skills:
                    safe_skills = [s.replace("'", "''") for s in extracted_skills]
                    skill_sql_part = " OR ".join([f"(skills LIKE '%{s}%' OR resume_text LIKE '%{s}%')" for s in safe_skills])
                    skill_condition = f"AND ({skill_sql_part})"
                else:
                    skill_condition = "AND 1=1"
                
                db = mysql.connector.connect(
                    host="localhost", user="root",
                    password=os.getenv("DB_PASSWORD"),
                    database="drive_to_sql_v2"
                )
                sql_query = f"""
                    SELECT * FROM users
                    WHERE experience >= {final_min_exp}
                    AND {loc_condition}
                    AND ({role_conditions})
                    {skill_condition}
                    AND is_active = 1
                """
                df = pd.read_sql(sql_query, db)
                db.close()

                if not df.empty:
                    # Semantic scoring
                    jd_emb = ranking_model.encode(jd_area_input, convert_to_tensor=True)
                    res_emb = get_cached_embeddings(ranking_model, df['resume_text'].tolist())
                    scores = util.cos_sim(jd_emb, res_emb)[0].tolist()
                    
                    # --- SMART SKILL MATCH LOGIC ---
                    total_skills_count = len(extracted_skills)
                    skill_threshold = 50 if total_skills_count >= 5 else 40
                    
                    processed_results = []

                    for idx, row in df.iterrows():
                        search_content = (str(row['skills']) + " " + str(row['resume_text'])).lower()
                        match_count = sum(1 for s in extracted_skills if s.lower() in search_content)
                        
                        match_percent = (match_count / total_skills_count * 100) if total_skills_count > 0 else 0
                        
                        # Apply Dynamic Threshold
                        if match_percent >= skill_threshold:
                            row_dict = row.to_dict()
                            ai_relativity = round(min(99.5, 75 + (scores[idx] * 40)), 1)
                            
                            # --- WEIGHTED RANKING: 60% Skills + 40% AI Context ---
                            final_weighted_score = (match_percent * 0.6) + (ai_relativity * 0.4)
                            
                            row_dict['AI_Score'] = ai_relativity
                            row_dict['match_percent'] = match_percent
                            row_dict['final_score'] = final_weighted_score
                            processed_results.append(row_dict)

                    if processed_results:
                        final_df = pd.DataFrame(processed_results)
                        # Rank by Final Weighted Score
                        st.session_state.ranked_results = final_df.sort_values(
                            by='final_score', ascending=False
                        ).head(10)
                        st.session_state.strict_no_result = False
                    else:
                        st.session_state.ranked_results = None
                        st.session_state.strict_no_result = True
                    
                    st.session_state.llm_rules = {
                        "skill": f"{total_skills_count} Skills Tracked",
                        "exp": final_min_exp,
                        "state": state if 'state' in locals() else "All"
                    }
                    st.rerun()
                else:
                    st.session_state.ranked_results = None
                    st.session_state.strict_no_result = True
                    st.rerun()

            except Exception as e:
                st.error(f"Error: {e}")

# --- DISPLAY RESULTS ---
if st.session_state.get('strict_no_result'):
    st.error("❌ No candidates met the required skill threshold for this JD.")
    st.info("💡 Tip: Try ensuring the JD has clear technical keywords.")
    st.session_state.strict_no_result = False 

if st.session_state.ranked_results is not None:
    if st.session_state.llm_rules:
        r = st.session_state.llm_rules
        st.success(f"🎯 Target: {r['state']} | Exp: {r['exp']}+ yrs | {r['skill']}")

    for _, row in st.session_state.ranked_results.iterrows():
        st.markdown(f"""
        <div class='ts-card'>
            <b style='font-size:16px;'>{row['name']}</b>
            <span style='float:right;color:#29aae2;font-weight:700;'>{int(row['final_score'])}% Overall Match</span>
            <br>
            <small style='color:#38b000;font-weight:600;'>{int(row['match_percent'])}% Skills Found</small> | 
            <small style='color:#1a8abf;'>{row['AI_Score']}% AI Context Score</small>
            <br>
            <small style='color:#666;'>{row['role']} | {row['experience']} yrs | {row['location']}</small>
            <br>
            <small style='color:#29aae2;'>{str(row['skills'])[:120]}...</small>
        </div>
        """, unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns([1, 1, 1, 0.5])
        with c1:
            with st.expander("✨ HR Insight"):
                if row['id'] not in st.session_state.insight_cache:
                    with st.spinner("Generating..."):
                        st.session_state.insight_cache[row['id']] = get_ai_insight(
                            st.session_state.jd_input_value,
                            row['resume_text'],
                            row['name'],
                            row['role'],
                            row['experience'],
                            row['location'],
                            row['skills']
                        )
                st.markdown(f"""
                <div style='background:#f8fbff;padding:15px;border-radius:10px;'>
                    {st.session_state.insight_cache[row['id']].replace(chr(10), '<br>')}
                </div>
                """, unsafe_allow_html=True)
        with c2:
            if st.button("👁️ Preview", key=f"pre_{row['id']}"):
                preview_dialog(row['filename'])
        with c3:
            if st.button("📥 Download", key=f"dl_{row['id']}"):
                download_dialog(row['filename'], row['name'])
        with c4:
            if st.button("🗑️", key=f"del_{row['id']}"):
                delete_dialog(row['id'], row['name'])