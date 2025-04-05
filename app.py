import streamlit as st
import pandas as pd
import utils # Import our helper functions
import tempfile # To create temporary directories for downloads
import os
import shutil # To clean up temporary directories

st.set_page_config(layout="wide")

st.title(" Hackathon AI Judge MVP ")

# --- Session State Initialization ---
# Use session state to store project data and results across reruns
if 'projects' not in st.session_state:
    st.session_state.projects = []
if 'results' not in st.session_state:
    st.session_state.results = None
if 'processing' not in st.session_state:
    st.session_state.processing = False # Flag to prevent multiple clicks

# --- Define Rubric (Using default from utils for now) ---
# In a future version, this could be configurable in the UI
rubric = utils.DEFAULT_RUBRIC

# --- Input Form ---
st.header("Add Project for Judging")
with st.form("project_form", clear_on_submit=True):
    project_name = st.text_input("Project Name", key="project_name")
    project_description = st.text_area("Project Description", key="project_desc")
    # Changed from file_uploader to text_input for URL
    pitch_video_url = st.text_input("Pitch Video URL (YouTube, Vimeo, direct link, etc.)", key="project_video_url")
    github_repo_link = st.text_input("GitHub Repository Link", key="project_repo")
    submitted = st.form_submit_button("Add Project")

    if submitted:
        if not project_name:
            st.warning("Please enter a project name.")
        elif not project_description:
            st.warning("Please enter a project description.")
        elif not pitch_video_url: # Check for URL instead of file
            st.warning("Please enter a pitch video URL.")
        elif not github_repo_link:
            st.warning("Please enter a GitHub repo link.")
        else:
            # Store project details temporarily in session state
            st.session_state.projects.append({
                "name": project_name,
                "description": project_description,
                "video_url": pitch_video_url, # Store the URL
                "repo_link": github_repo_link,
                "status": "Pending" # Add a status field
            })
            st.success(f"Project '{project_name}' added!")

# --- Display Added Projects ---
st.header("Projects Added for Judging")
if st.session_state.projects:
    # Create a simple display for added projects
    project_names = [p["name"] for p in st.session_state.projects]
    st.write("Projects in queue:", ", ".join(project_names))
else:
    st.info("No projects added yet. Use the form above.")

# --- Judging Trigger ---
st.header("Start Judging")

# Now, check conditions for showing the button *under* the header
if st.session_state.projects and not st.session_state.processing:
    if st.button("Judge All Pending Projects"):
        st.session_state.processing = True
        st.session_state.results = [] # Reset results
        st.info(f"Starting judgment for {len(st.session_state.projects)} projects...")

        progress_bar = st.progress(0)
        total_projects = len(st.session_state.projects)
        results_list = []

        # Create a parent temporary directory for all downloads in this run
        parent_temp_dir = tempfile.mkdtemp()
        st.info(f"Using temporary directory for downloads: {parent_temp_dir}")

        for i, project in enumerate(st.session_state.projects):
            if project["status"] == "Pending": # Only process pending projects
                st.write(f"Processing: {project['name']}...")
                project_status_placeholder = st.empty()
                project_status_placeholder.info("➡️ Starting...")
                transcript = "Error: Processing failed"
                readme_content = "Error: Processing failed"
                ai_result = {"error": "Initial processing failed"}
                final_scores = {}
                total_score = 0
                temp_project_dir = None # Directory for this specific project's downloads
                downloaded_video_path = None
                audio_path = None

                try:
                    # Create a unique temp directory for this project's video/audio
                    temp_project_dir = tempfile.mkdtemp(dir=parent_temp_dir)

                    # --- 1. Download Video ---
                    project_status_placeholder.info("⬇️ Downloading video...")
                    downloaded_video_path = utils.download_video_from_url(project["video_url"], temp_project_dir)
                    if not downloaded_video_path:
                        project["status"] = "Error: Video Download Failed"
                        transcript = "N/A - Video download failed"
                        raise Exception("Video download failed") # Skip to finally block for cleanup
                    else:
                        project_status_placeholder.info("🔈 Extracting audio...")
                        # --- 2. Extract Audio ---
                        # Pass the path to the downloaded video
                        audio_path = utils.extract_audio_from_video(downloaded_video_path)

                        if not audio_path:
                            project["status"] = "Error: Audio Extraction Failed"
                            transcript = "N/A - Audio extraction failed"
                            raise Exception("Audio extraction failed") # Skip to finally block for cleanup
                        else:
                            project_status_placeholder.info("2. Transcribing audio (Whisper)...")
                            transcript = utils.transcribe_audio(audio_path)
                            if "Error:" in transcript:
                                project["status"] = "Error: Transcription Failed"
                            else:
                                project_status_placeholder.info("📄 Fetching README...")
                                # --- 4. Fetch README ---
                                readme_content = utils.fetch_readme(project["repo_link"])
                                if "Error:" in readme_content:
                                    # Limit readme length if necessary
                                    readme_content = readme_content[:4000] # Limit to ~4k chars

                                project_status_placeholder.info("🤖 Calling AI Judge...")
                                # --- 5. AI Judging ---
                                ai_result = utils.get_ai_judgment(
                                    project["description"], # Pass description
                                    transcript if not transcript.startswith("Error:") else None, # Pass transcript
                                    readme_content if not readme_content.startswith("Error:") else None, # Pass readme
                                    rubric
                                )

                                if "error" in ai_result:
                                    st.error(f"Failed to judge {project['name']}: {ai_result['error']}")
                                    scores = {c['name']: 0 for c in rubric['criteria']} # Assign 0 scores on error
                                    rationales = {c['name']: f"Judging failed: {ai_result['error']}" for c in rubric['criteria']}
                                    total_score = 0
                                    project["status"] = "Error"
                                else:
                                    scores = ai_result.get("scores", {})
                                    rationales = ai_result.get("rationales", {})
                                    total_score = utils.calculate_total_score(scores, rubric)
                                    project["status"] = "Judged"
                                    project_status_placeholder.success("Judgment complete!")

                                final_scores = scores
                                total_score = total_score

                except Exception as e:
                    project["status"] = f"Error: {e}"
                    transcript = transcript or "N/A"
                    readme_content = readme_content or "N/A"
                    ai_result = {"error": str(e)}
                    scores = {c['name']: 0 for c in rubric['criteria']} # Assign 0 scores on error
                    rationales = {c['name']: f"Judging failed: {e}" for c in rubric['criteria']}
                    total_score = 0

                # Store results regardless of success/failure for display
                results_list.append({
                    "Project Name": project["name"],
                    "Description": project["description"],
                    "Total Score": total_score,
                    **scores, # Add individual scores to the dict
                    "Rationales": rationales, # Keep rationales nested for now
                    "Transcript": transcript,
                    "README": readme_content,
                    "Status": project["status"]
                })

                progress_bar.progress((i + 1) / total_projects)
                # Brief pause or clear placeholder if needed
                # time.sleep(0.5)
                project_status_placeholder.empty()

        # --- Final Cleanup ---
        if parent_temp_dir and os.path.exists(parent_temp_dir):
            try:
                shutil.rmtree(parent_temp_dir)
                print(f"Cleaned up parent temp directory: {parent_temp_dir}")
            except Exception as final_cleanup_e:
                print(f"Error cleaning up parent temp directory {parent_temp_dir}: {final_cleanup_e}")

        # Sort results by total score (descending)
        results_list.sort(key=lambda x: x.get("Total Score", -1), reverse=True) # Use .get for safety
        st.session_state.results = results_list
        st.session_state.processing = False # Reset processing flag
        st.success("All projects processed!")
        st.balloons()

elif st.session_state.processing:
    # Show this warning under the "Start Judging" header if processing
    st.warning("Processing already in progress...")
elif not st.session_state.projects:
    # Show this warning under the "Start Judging" header if no projects
    st.warning("Add projects using the form above before starting the judgment.")


# --- Display Results ---
st.header("Judging Results")
if st.session_state.results:
    # Prepare DataFrame for display (excluding nested rationales for main table)
    display_df_data = []
    for res in st.session_state.results:
        row = {
            "Rank": len(display_df_data) + 1,
            "Project Name": res["Project Name"],
            "Total Score": res["Total Score"],
            "Status": res["Status"]
        }
        # Add individual scores to the row
        for crit in rubric['criteria']:
            row[crit['name']] = res.get(crit['name'], 'N/A') # Use .get for safety
        display_df_data.append(row)

    results_df = pd.DataFrame(display_df_data)
    st.dataframe(results_df.set_index('Rank'))

    st.subheader("Detailed Rationales")
    # Use expanders to show details for each project
    for i, res in enumerate(st.session_state.results):
        with st.expander(f"{i+1}. {res['Project Name']} (Score: {res['Total Score']})"):
            st.markdown(f"**Description:** {res['Description']}")
            st.markdown(f"**Status:** {res['Status']}")
            st.markdown("**Scores & Rationales:**")
            if isinstance(res.get("Rationales"), dict):
                for crit in rubric['criteria']:
                    crit_name = crit['name']
                    score = res.get(crit_name, 'N/A')
                    rationale = res["Rationales"].get(crit_name, "No rationale provided.")
                    st.markdown(f"- **{crit_name}:** {score}/{rubric['scale'][1]} \n - *Rationale:* {rationale}")
            else:
                st.warning("Rationales not available in the expected format.")

            with st.container(): # Collapsible container for raw data
                 st.markdown("**Raw Data:**")
                 st.text_area("Pitch Transcript", value=res.get("Transcript", "N/A"), height=150, disabled=True)
                 st.text_area("README Content", value=res.get("README", "N/A"), height=150, disabled=True)

else:
    st.info("Results will appear here after judging is complete.")

# --- Option to Clear Data ---
st.sidebar.header("Admin")
if st.sidebar.button("Clear All Projects and Results"):
    st.session_state.projects = []
    st.session_state.results = None
    st.session_state.processing = False
    st.rerun() # Rerun the app to reflect the cleared state 