import streamlit as st
import database as db
import plotly.express as px
import os
import pandas as pd
import PyPDF2
import docx
from PIL import Image
import pytesseract
import re
from groq import Groq
from streamlit_mic_recorder import speech_to_text

# ==========================================
# 1. CONFIG & INITIALIZATION (MUST BE FIRST)
# ==========================================
st.set_page_config(page_title="EduSmart Pro", page_icon="🎓", layout="wide")

db.init_db()
if not os.path.exists("materials"):
    os.makedirs("materials")

client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# ==========================================
# 2. YOUR ORIGINAL HELPER FUNCTIONS
# ==========================================
def parse_quiz(text):
    questions = []
    # Split by the separator we told the AI to use
    blocks = text.split("---")
    for block in blocks:
        if "Q:" in block and "A:" in block:
            # Extract Question
            q_match = re.search(r"Q:\s*(.*?)(?=\n|A:)", block, re.DOTALL)
            # Extract Answer Letter (e.g., 'b')
            a_match = re.search(r"A:\s*([a-d])", block, re.IGNORECASE)
            # Extract Options
            opts = re.findall(r"([a-d]\)\s*.*)", block)

            if q_match and a_match and len(opts) >= 4:
                questions.append({
                    "q": q_match.group(1).strip(),
                    "correct": a_match.group(1).strip().lower(),
                    "options": [o.strip() for o in opts[:4]]
                })
    return questions

def parse_flashcards(text):
    cards = []
    # Split by the separator
    blocks = text.split("---")
    for block in blocks:
        # Using re.IGNORECASE makes it less likely to fail
        f_match = re.search(r"Front:\s*(.*)", block, re.IGNORECASE)
        b_match = re.search(r"Back:\s*(.*)", block, re.IGNORECASE)
        if f_match and b_match:
            cards.append({
                "q": f_match.group(1).strip(),
                "a": b_match.group(1).strip()
            })
    return cards

def extract_text(file):
    text = ""
    if file.type == "application/pdf":
        pdf_reader = PyPDF2.PdfReader(file)
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
    elif file.type == "text/plain":
        text = file.read().decode("utf-8")
    elif file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        doc = docx.Document(file)
        for para in doc.paragraphs:
            text += para.text + "\n"
    elif "image" in file.type:
        image = Image.open(file)
        text = pytesseract.image_to_string(image)
    return text


def get_prompt(mode, study_feature, lang ="English"):
    base_instructions = f"IMPORTANT: You must provide all explanations and content in {lang}."

    if mode == "Coding":
        return f"You are a coding expert.{base_instructions} Give clean, optimized code with short explanation."

    elif mode == "Analyst":
        return f"You are a data analyst.{base_instructions} Explain insights, charts, and trends clearly."

    elif mode == "Study":
        if study_feature == "Flashcards":
            return f"""{base_instructions}
            Create 10 Flashcards. 
            STRICT FORMAT for each card:
            Front: [Question or term]
            Back: [Answer or definition]
            ---
            Make sure to include the '---' line between EVERY single flashcard.Do not add any other text or conversational filler.
            """

        elif study_feature == "Quiz":
            # ADDED: Bloom's Taxonomy Instruction
            return f"""{base_instructions}
            Create 5 Multiple Choice Questions based on Bloom's Taxonomy (mix of Remembering, Applying, and Analyzing levels). 
            Format each question EXACTLY like this:
            Q: [Question text]
            A: [Correct Option Letter, e.g., a]
            Options:
            a) [Option 1]
            b) [Option 2]
            c) [Option 3]
            d) [Option 4]
            Make sure to include the '---' line between EVERY single question .Do not add any other text or conversational filler. 
            """

        elif study_feature == "Quick Notes":
            return f"{base_instructions}Give short revision notes in bullet points."

        else:
            return f"You are a tutor.{base_instructions} Explain the topic simply with examples."

    else:
        return f"You are a helpful assistant. Keep answers short and clear.{base_instructions}"



# ==========================================
# 3. TEACHER DASHBOARD (Fixed Ranking)
# ==========================================
def show_teacher_dashboard():
    st.header("👩‍🏫 Class Analytics Overview")
    conn = db.create_connection()
    df = pd.read_sql_query("SELECT * FROM marks", conn)
    conn.close()

    if df.empty:
        st.info("⚠ No data found. Upload CSV in 'Manage Marks' first.")
        return

    classes = df['class_name'].unique()
    selected_class = st.sidebar.selectbox("Filter Analytics by Class", classes)
    df = df[df['class_name'] == selected_class]

    if df.empty:
        st.warning(f"No records found for {selected_class}.")
        return

    df["Rank"] = df["score"].rank(method="dense", ascending=False).astype(int)
    df = df.sort_values(by="Rank")

    # 🥇 Top 3 Students
    top3 = df.nsmallest(3, "Rank")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.success(f"🥇 1st: {top3.iloc[0]['student_name']} ({top3.iloc[0]['score']}%)")
    with c2:
        if len(top3) > 1: st.info(f"🥈 2nd: {top3.iloc[1]['student_name']} ({top3.iloc[1]['score']}%)")
    with c3:
        if len(top3) > 2: st.warning(f"🥉 3rd: {top3.iloc[2]['student_name']} ({top3.iloc[2]['score']}%)")

    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("Highest Score", f"{df['score'].max()}%")
    m2.metric("Lowest Score", f"{df['score'].min()}%")
    m3.metric("Class Average", f"{df['score'].mean():.1f}%")

    tab_summary, tab_details = st.tabs(["📊 Executive Summary", "🔍 Full Class Analysis"])
    with tab_summary:
        col1, col2 = st.columns(2)
        with col1: st.plotly_chart(
            px.bar(df.head(5), x='score', y='student_name', orientation='h', title="Top 5 Performers",
                   color='student_name'), use_container_width=True)
        with col2: st.plotly_chart(
            px.scatter(df, x='attendance', y='score', color='student_name', size='score', title="Attendance vs Marks"),
            use_container_width=True)

        # Pie Chart Fix
        bins, labels = [0, 50, 70, 85, 100], ["Poor", "Average", "Good", "Excellent"]
        df['category'] = pd.cut(df['score'], bins=bins, labels=labels)
        dist_df = df['category'].value_counts().reset_index()
        dist_df.columns = ['Category', 'Count']
        st.plotly_chart(px.pie(dist_df, values='Count', names='Category', title="Performance Distribution", hole=0.4),
                        use_container_width=True)

    with tab_details:
        st.plotly_chart(px.bar(df, x='student_name', y='score', color='subject', barmode='group',
                               title="Individual Subject Breakdown"), use_container_width=True)
        sub_avg = df.groupby('subject')['score'].mean().reset_index()
        st.plotly_chart(px.line(sub_avg, x='subject', y='score', markers=True, title="Subject-wise Average Trend"),
                        use_container_width=True)

    st.divider()
    st.subheader("📋 Official Student Ranking Table")
    st.dataframe(df[['Rank', 'student_name', 'subject', 'score', 'attendance']].set_index('Rank'),
                 use_container_width=True)


# ==========================================
# 4. SESSION STATE INITIALIZATION
# ==========================================
# We initialize ALL keys your bot uses exactly as you defined them
init_keys = {
    "logged_in": False, "role": None, "username": None, "messages": [],
    "quiz_data": [], "quiz_answers": {}, "last_processed_input": "",
    "voice_text": None, "file_context": "", "flashcards": [],
    "card_index": 0, "show_answer": False, "quiz_id": 0
}
for key, val in init_keys.items():
    if key not in st.session_state: st.session_state[key] = val

# ==========================================
# 5. MAIN APP NAVIGATION
# ==========================================
if not st.session_state.logged_in:
    st.title("🎓 EduSmart Management System")
    tab_login, tab_reg = st.tabs(["🔐 Login", "📝 Register"])

    with tab_login:
        with st.form("login_form"):
            u, p, r = st.text_input("Username"), st.text_input("Password", type="password"), st.selectbox("Role",
                                                                                                          ["Teacher",
                                                                                                           "Student"])
            if st.form_submit_button("Login"):
                if db.verify_user(u, p, r):
                    st.session_state.update({"logged_in": True, "role": r, "username": u})
                    st.rerun()
                else:
                    st.error("Invalid Login")

    with tab_reg:
        with st.form("reg_form"):
            new_u = st.text_input("New Username")
            new_p = st.text_input("New Password", type="password")
            new_r = st.selectbox("I am a...", ["Teacher", "Student"])
            if st.form_submit_button("Register Account"):
                conn = db.create_connection()
                try:
                    conn.execute("INSERT INTO users VALUES (?, ?, ?)", (new_u, new_p, new_r))
                    conn.commit()
                    st.success("Account Created! You can now login.")
                except:
                    st.error("Username already exists!")
                conn.close()

else:
    st.sidebar.title(f"👋 {st.session_state.username}")
    menu = ["Dashboard", "Manage Marks", "Upload Materials"] if st.session_state.role == "Teacher" else ["Student Home",
                                                                                                         "My Progress",
                                                                                                         "Routine Builder",
                                                                                                         "AI Study Bot"]
    choice = st.sidebar.radio("Navigation", menu)

    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()

    # --- TEACHER PAGES ---
    if choice == "Dashboard":
        show_teacher_dashboard()

    elif choice == "Manage Marks":
        st.header("📝 Student Marks Management")
        # Ensure the directory for storing mark CSVs exists
        marks_dir = "student_marks_files"
        if not os.path.exists(marks_dir):
            os.makedirs(marks_dir)

        target_class = st.selectbox("Select Class", ["ITDS-SEM 4", "CTIS-SEM 6", "ITDS-SEM 7"])
        sub_cat = st.selectbox("Subject Category",["Machine Learning","PYTHON", "Data Analytics", "COMPUTER NETWORKS"])

        tab1, tab2 = st.tabs(["📤 Bulk Upload", "✍️ Manual Entry"])

        with tab1:
            csv = st.file_uploader("Upload CSV", type=['csv'])
            if csv and st.button("Confirm Import"):
                # 1. Save the physical file so it shows in the list
                file_path = os.path.join(marks_dir, f"{target_class}_{csv.name}")
                with open(file_path, "wb") as f:
                    f.write(csv.getbuffer())


                df_up = pd.read_csv(csv)
                df_up.rename(columns={'Name': 'student_name', 'Subject': 'subject', 'Score': 'score',
                                      'Attendance': 'attendance'}, inplace=True)
                df_up['class_name'] = target_class
                conn = db.create_connection()
                df_up.to_sql('marks', conn, if_exists='append', index=False)
                conn.close()
                st.success(f"Imported successfully and saved {csv.name}!")

        with tab2:
            with st.form("manual"):
                n, s, sc, at = st.text_input("Name"), st.selectbox("Subject", ["MACHINE LEARNING", "PYTHON",
                                                                               "MATH"]), st.number_input("Score", 0,
                                                                                                         100), st.number_input(
                    "Att", 0, 100)
                if st.form_submit_button("Save Student"):
                    conn = db.create_connection()
                    conn.execute("INSERT INTO marks VALUES (?,?,?,?,?)", (n, s, sc, at, target_class))
                    conn.commit()
                    conn.close()
                    st.success("Saved!")


        st.divider()
        st.subheader("📂 Uploaded Marks Files")

        if os.path.exists(marks_dir):
            # Only show files for the selected class to keep it clean
            files = [f for f in os.listdir(marks_dir) if f.startswith(target_class)]

            if not files:
                st.info(f"No files uploaded for {target_class} yet.")
            else:
                for file_name in files:
                    col1, col2 = st.columns([0.8, 0.2])
                    col1.text(f"📄 {file_name}")

                    # This button is now safe because it is NOT inside st.form
                    if col2.button("🗑️", key=f"del_file_{file_name}"):
                        os.remove(os.path.join(marks_dir, file_name))
                        st.toast(f"Removed {file_name}")
                        st.rerun()

                # --- 📋 DATABASE RECORDS VIEW ---
                with st.expander("🔍 View All Database Records for this Class"):
                    conn = db.create_connection()
                    rec_df = pd.read_sql_query("SELECT student_name, subject, score FROM marks WHERE class_name=?",
                                               conn, params=(target_class,))
                    conn.close()
                    st.dataframe(rec_df, use_container_width=True)

        st.divider()
        st.subheader(f"📋 Current Records for {target_class}")

        conn = db.create_connection()
        # Fetch current records for this class
        records_df = pd.read_sql_query("SELECT rowid, student_name, subject, score FROM marks WHERE class_name=?",
                                       conn, params=(target_class,))
        conn.close()

        if records_df.empty:
            st.info("No records found for this class.")
        else:
            for index, row in records_df.iterrows():
                col1, col2 = st.columns([0.8, 0.2])
                # Show record info
                col1.text(f"👤 {row['student_name']} | 📚 {row['subject']} | ⭐ {row['score']}%")

                # Delete button with unique key using rowid
                if col2.button("🗑️", key=f"del_mark_{row['rowid']}"):
                    conn = db.create_connection()
                    conn.execute("DELETE FROM marks WHERE rowid=?", (row['rowid'],))
                    conn.commit()
                    conn.close()
                    st.toast(f"Deleted record for {row['student_name']}")
                    st.rerun()

    elif choice == "Upload Materials":
        st.header("📂 Upload Study Materials")
        sub_cat = st.selectbox("Subject Category", ["Machine Learning", "PYTHON", "Data Analytics", "COMPUTER NETWORKS"])
        f = st.file_uploader("Choose File", type=['pdf', 'txt', 'docx'])
        if f:
            with open(f"materials/{sub_cat}_{f.name}", "wb") as m: m.write(f.getbuffer())
            st.success(f"Uploaded to {sub_cat}!")
        for file in os.listdir("materials"):
            c1, c2 = st.columns([0.8, 0.2]);
            c1.text(file)
            if c2.button("🗑️", key=f"del_{file}"): os.remove(f"materials/{file}"); st.rerun()

    # --- STUDENT PAGES ---
    elif choice == "Student Home":
        st.header(f"👋 Welcome, {st.session_state.username}!")
        st.info("Check 'Routine Builder' for your schedule or 'AI Study Bot' to learn from class notes or 'My Progress' to see your marks analysis.")

    elif choice == "My Progress":
        st.title("📊 My Marks Analysis Dashboard")

        # 1. Fetch data for ONLY the logged-in student
        conn = db.create_connection()
        df = pd.read_sql_query("SELECT * FROM marks WHERE student_name=?", conn, params=(st.session_state.username,))
        conn.close()
        personal_file = st.file_uploader("📂 Upload your own marks CSV for instant analysis", type=["csv"])

        if personal_file:
            df = pd.read_csv(personal_file)
            # Standardize: Ensure 'score' exists if they used 'Marks' in CSV
            df.columns = [c.lower() for c in df.columns]
            if 'marks' in df.columns: df.rename(columns={'marks': 'score'}, inplace=True)
            if 'subject' not in df.columns and 'name' in df.columns: df.rename(columns={'name': 'subject'},
                                                                               inplace=True)
        else:
            # Pull from Database if no file is uploaded
            conn = db.create_connection()
            df = pd.read_sql_query("SELECT * FROM marks WHERE student_name=?", conn,
                                   params=(st.session_state.username,))
            conn.close()
        if not df.empty:
            # -----------------------------
            # Basic Metrics (From your code)
            # -----------------------------
            avg_marks = df["score"].mean()
            max_marks = df["score"].max()
            min_marks = df["score"].min()

            st.subheader("📈 Key Insights")
            c1, c2, c3 = st.columns(3)
            c1.metric("Average Marks", f"{avg_marks:.2f}")
            c2.metric("Highest Marks", f"{max_marks}")
            c3.metric("Lowest Marks", f"{min_marks}")

            st.divider()

            # -----------------------------
            # Charts (Bar, Line, Pie)
            # -----------------------------
            col_left, col_right = st.columns(2)

            with col_left:
                st.subheader("📊 Subject-wise Performance")
                fig_bar = px.bar(df, x='subject', y='score', color='subject', title="My Marks")
                st.plotly_chart(fig_bar, use_container_width=True)

                st.subheader("📈 Marks Trend")
                fig_line = px.line(df, x='subject', y='score', markers=True, title="Growth Trend")
                st.plotly_chart(fig_line, use_container_width=True)

            with col_right:
                st.subheader("🥧 Performance Distribution")
                # Creating grades for the pie chart
                bins = [0, 50, 70, 85, 100]
                labels = ["D", "C", "B", "A"]
                df["Grade"] = pd.cut(df["score"], bins=bins, labels=labels)
                grade_counts = df["Grade"].value_counts().reset_index()

                fig_pie = px.pie(grade_counts, values='count', names='Grade', title="Grade Split")
                st.plotly_chart(fig_pie, use_container_width=True)

            # -----------------------------
            # Top & Weak Subjects
            # -----------------------------
            st.divider()
            top_sub = df.loc[df["score"].idxmax()]
            weak_sub = df.loc[df["score"].idxmin()]

            st.subheader("📌 Performance Summary")
            st.success(f"🏆 Best Subject: {top_sub['subject']} ({top_sub['score']} marks)")
            st.error(f"⚠️ Weakest Subject: {weak_sub['subject']} ({weak_sub['score']} marks)")

            # -----------------------------
            # Performance Remark (From your code)
            # -----------------------------
            st.subheader("🧠 Performance Remark")
            if avg_marks >= 85:
                st.success("Excellent performance! Keep it up 💯")
            elif avg_marks >= 70:
                st.info("Good performance, but room for improvement 👍")
            else:
                st.warning("Needs improvement. Focus on weak subjects 📚")
        else:
            st.warning("⚠ Your marks haven't been uploaded by the teacher yet.")

    elif choice == "Routine Builder":
        st.header("📅 Flexible Routine Builder")
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        full_routine = []
        for d in days:
            num = st.number_input(f"Tasks for {d}?", 1, 10, 1, key=f"rout_{d}")
            for i in range(num):
                c1, c2 = st.columns(2)
                full_routine.append([d, c1.text_input(f"Time {i + 1}", key=f"{d}_t{i}"),
                                     c2.text_input(f"Task {i + 1}", key=f"{d}_tk{i}")])
        if st.button("Generate Routine Table"): st.table(pd.DataFrame(full_routine, columns=["Day", "Time", "Task"]))

    elif choice == "AI Study Bot":
        # ==========================================
        # 6. YOUR EXACT ORIGINAL AI BOT CODE
        # ==========================================
        if "messages" not in st.session_state: st.session_state.messages = []
        if "quiz_data" not in st.session_state: st.session_state.quiz_data = []
        if "quiz_answers" not in st.session_state: st.session_state.quiz_answers = {}
        # Add these to your Section 3: Sidebar & State
        if "last_processed_input" not in st.session_state:
            st.session_state.last_processed_input = ""
        if "voice_text" not in st.session_state:
            st.session_state.voice_text = None
        if "file_context" not in st.session_state:
            st.session_state.file_context = ""
        # Add these inside your Section 3 initialization block
        if "flashcards" not in st.session_state: st.session_state.flashcards = []
        if "card_index" not in st.session_state: st.session_state.card_index = 0
        if "show_answer" not in st.session_state: st.session_state.show_answer = False
        if "quiz_id" not in st.session_state: st.session_state.quiz_id = 0

        st.sidebar.title("⚙️ Settings")
        if st.sidebar.button("🧹Clear Chat"):
            st.session_state.messages = []
            st.session_state.quiz_data = []
            st.rerun()

        uploaded_file = st.sidebar.file_uploader("📄 Upload Notes", type=["pdf", "txt", "docx", "png", "jpg", "jpeg"])
        if uploaded_file:
            # Extract text once and save it to the "Safe Box"
            file_text = extract_text(uploaded_file)
            st.session_state.file_context = file_text
            st.sidebar.success("✅ Notes Uploaded & Processed!")
        # --- ADDED: TEACHER'S MATERIALS SECTION ---
        st.sidebar.markdown("---")
        st.sidebar.subheader("📂 Course Materials (From Teacher)")
        if os.path.exists("materials"):
            teacher_files = os.listdir("materials")
            selected_teacher_file = st.sidebar.selectbox("Load Teacher's Notes", ["None"] + teacher_files)

            if selected_teacher_file != "None" and st.sidebar.button("📖 Load to AI Memory"):
                try:
                    with open(os.path.join("materials", selected_teacher_file), "rb") as f:
                        pdf_reader = PyPDF2.PdfReader(f)
                        teacher_text = "".join([page.extract_text() for page in pdf_reader.pages])
                        st.session_state.file_context = teacher_text
                        st.sidebar.success(f"✅ Loaded: {selected_teacher_file}")
                except Exception as e:
                    st.sidebar.error("Error loading PDF.")

        mode = st.sidebar.selectbox("Choose Assistant Mode", ["General", "Coding", "Analyst", "Study"])

        # --- MULTILINGUAL SUPPORT ---
        target_lang = st.sidebar.selectbox("🌍 Study in My Language",
                                           ["English", "Hindi", "Marathi", "Spanish", "French"])

        # --- GAMIFICATION (STREAK & POINTS) ---
        if "streak" not in st.session_state: st.session_state.streak = 1
        if "points" not in st.session_state: st.session_state.points = 0

        st.sidebar.markdown("---")
        st.sidebar.subheader("🏆 Your Achievements")
        st.sidebar.write(f"🔥 **{st.session_state.streak} Day Study Streak**")
        # Progress bar for "Study Warrior" badge
        progress = min(st.session_state.points / 100, 1.0)
        st.sidebar.progress(progress)
        if st.session_state.points >= 100:
            st.sidebar.success("🏅 Badge Unlocked: Study Warrior")
        else:
            st.sidebar.caption(f"Collect {100 - st.session_state.points} more points for your next badge!")



        study_feature = None
        if mode == "Study":
            study_feature = st.sidebar.radio("Study Tools", ["Normal", "Flashcards", "Quick Notes", "Quiz"])

        # 4. Input Handling

        user_input = None

        with st.sidebar:
            st.markdown("---")


            # 🎤 Using a callback ensures the text is SAVED the moment you stop speaking
            def voice_callback():
                if st.session_state.my_stt_output:
                    st.session_state.voice_text = st.session_state.my_stt_output


            speech_to_text(
                key='my_stt',
                callback=voice_callback,
                start_prompt="🎤 Start Speaking",
                stop_prompt="🛑 Stop"
            )

        # Now, check the "Safe Box" outside the sidebar
        text_input = st.chat_input("Ask me anything...")

        if text_input:
            user_input = text_input
        elif "voice_text" in st.session_state and st.session_state.voice_text:
            user_input = st.session_state.voice_text
            st.session_state.voice_text = None  # Clear it so it doesn't repeat
        # If no input at all, we don't need to stop the script anymore!
        # The rest of the code will just show the history and UI.

        # 5. Chat & Response Logic

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])

        # 🤖 AI RESPONSE ( to prevent loops)

        if user_input and user_input != st.session_state.get('last_processed_input'):
            st.session_state.last_processed_input = user_input

            # 1. Create a "Super Prompt" that includes your notes
            # We check if there's context; if so, we force the AI to use it.
            if st.session_state.get("file_context"):
                prompt_with_context = f"""
                USE THE FOLLOWING NOTES TO ANSWER THE USER:
                {st.session_state.file_context[:5000]} # Limiting to 5000 chars to avoid API errors

                USER REQUEST: {user_input}
                """
            else:
                prompt_with_context = user_input

            # 2. Add the clean user message to history (so the UI looks nice)
            st.session_state.messages.append({"role": "user", "content": user_input})

            with st.chat_message("assistant"):
                system_prompt = {"role": "system", "content": get_prompt(mode, study_feature,target_lang)}

                with st.spinner("🤖 Thinking..."):
                    response = client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        # ❗ IMPORTANT: We send the 'prompt_with_context' as the latest message
                        messages=[system_prompt] + st.session_state.messages[:-1] + [
                            {"role": "user", "content": prompt_with_context}]
                    )
                    response_text = response.choices[0].message.content

                    # --- QUIZ / FLASHCARD PARSING LOGIC ---
                    if mode == "Study":
                        if study_feature == "Quiz":
                            st.session_state.quiz_data = parse_quiz(response_text)
                            st.session_state.quiz_answers = {}
                            st.session_state.quiz_id += 1
                        elif study_feature == "Flashcards":
                            st.session_state.flashcards = parse_flashcards(response_text)

                st.session_state.messages.append({"role": "assistant", "content": response_text})
                st.rerun()


        # --- 6. Interactive UI (Final Stable Version) ---
        if mode == "Study" and study_feature == "Quiz" and st.session_state.quiz_data:
            st.divider()
            st.subheader("📝 Interactive Quiz")

            # We create a container to hold ALL questions
            quiz_container = st.container()

            with quiz_container:
                for i, item in enumerate(st.session_state.quiz_data):
                    # 1. Validation: Skip if the item is missing data
                    if not all(k in item for k in ("q", "correct", "options")):
                        continue

                    st.markdown(f"### Question {i + 1}")
                    st.write(f"**{item['q']}**")

                    # 2. Layout: Display options in a 2x2 grid
                    cols = st.columns(2)

                    for idx, opt in enumerate(item['options']):
                        # Clean the option string to get the letter (a, b, c, or d)
                        current_char = opt[0].lower() if opt and len(opt) > 0 else ""

                        # UNIQUE KEY: This is the most important part!
                        # Uses Quiz ID + Question Index + Option Letter
                        btn_key = f"quiz_btn_{st.session_state.get('quiz_id', 0)}_{i}_{idx}"

                        # Check if this specific question has been answered
                        answered_char = st.session_state.quiz_answers.get(f"q_{i}")

                        if answered_char:
                            # Logic: Is this the correct one? Show Green.
                            if current_char == item['correct']:
                                cols[idx % 2].success(f"✅ {opt}")
                            # Was this the wrong one the user clicked? Show Red.
                            elif current_char == answered_char:
                                cols[idx % 2].error(f"❌ {opt}")
                            else:
                                cols[idx % 2].info(opt)
                        else:
                            # Display the clickable button
                            if cols[idx % 2].button(opt, key=btn_key, use_container_width=True):
                                st.session_state.quiz_answers[f"q_{i}"] = current_char
                                st.rerun()

                    st.write("---") # Visual line between questions

                if st.session_state.quiz_answers:
                    st.divider()
                    st.subheader("📊 Cognitive Strength Analysis (Bloom's Taxonomy)")

                    wrong_questions = []
                    for i, item in enumerate(st.session_state.quiz_data):
                        ans = st.session_state.quiz_answers.get(f"q_{i}")
                        # If they have answered, check if it's wrong
                        if ans and ans != item['correct']:
                            wrong_questions.append(item['q'])

                    # Only show the dashboard once they've finished or started answering
                    total = len(st.session_state.quiz_data)
                    correct = total - len(wrong_questions)
                    score_pct = (correct / total) * 100

                    c1, c2 = st.columns(2)
                    c1.metric("Quiz Accuracy", f"{score_pct}%")

                    # Determine if they finished the quiz
                    if len(st.session_state.quiz_answers) == total:
                        if score_pct < 100:
                            st.warning(
                                f"⚠️ **Learning Gap Identified:** You missed {len(wrong_questions)} questions. The AI detects a gap in your 'Application' of these concepts.")

                            if st.button("🪄 Generate AI Smart Study Plan"):
                                with st.spinner("Analyzing your gaps..."):
                                    gap_text = ", ".join(wrong_questions)
                                    smart_res = client.chat.completions.create(
                                        model="llama-3.1-8b-instant",
                                        messages=[{"role": "user",
                                                   "content": f"Based on these missed questions: {gap_text}, provide a 15-minute quick study plan to fix these gaps in {target_lang}."}]
                                    )
                                    st.info(smart_res.choices[0].message.content)
                                    st.session_state.points += 20
                        else:
                            st.balloons()
                            st.success("Perfect Score! You've mastered this topic at all cognitive levels.")
                            st.session_state.points += 50

        # --- 7. Interactive Flashcards UI ---
        if mode == "Study" and study_feature == "Flashcards" and "flashcards" in st.session_state:
            if st.session_state.flashcards:
                st.divider()
                idx = st.session_state.card_index
                card = st.session_state.flashcards[idx]

                # The "Visual" Card
                content = card['a'] if st.session_state.show_answer else card['q']
                label = "✅ ANSWER" if st.session_state.show_answer else "🧠 QUESTION"

                st.markdown(f"""
                    <div style="
                        height: 200px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        border-radius: 15px;
                        padding: 20px;
                        background: linear-gradient(135deg, #667eea, #764ba2);
                        color: white;
                        text-align: center;
                        font-size: 22px;
                        font-weight: bold;
                        box-shadow: 5px 5px 15px rgba(0,0,0,0.1);
                    ">
                        <div>
                            <small style="opacity: 0.8;">{label}</small><br>
                            {content}
                        </div>
                    </div>
                """, unsafe_allow_html=True)

                # Buttons
                st.write("")  # Spacer
                col1, col2, col3 = st.columns(3)

                if col1.button("⬅ Previous") and idx > 0:
                    st.session_state.card_index -= 1
                    st.session_state.show_answer = False
                    st.rerun()

                if col2.button("🔄 Flip Card"):
                    st.session_state.show_answer = not st.session_state.show_answer
                    st.rerun()

                if col3.button("Next ➡") and idx < len(st.session_state.flashcards) - 1:
                    st.session_state.card_index += 1
                    st.session_state.show_answer = False
                    st.rerun()

                st.caption(f"Card {idx + 1} of {len(st.session_state.flashcards)}")
