import streamlit as st
import pandas as pd
import utils # Import our helper functions
import tempfile # To create temporary directories for downloads
import os
import shutil # To clean up temporary directories
import copy # To deep copy the default rubric

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
# --- Initialize custom rubric weights in session state ---
if 'custom_weights' not in st.session_state:
    # Initialize with default weights from utils.DEFAULT_RUBRIC
    st.session_state.custom_weights = {
        criterion['name']: criterion['weight']
        for criterion in utils.DEFAULT_RUBRIC['criteria']
    }

# --- Define Rubric (Using default initially, will be customized) ---
# Make a deep copy to avoid modifying the original DEFAULT_RUBRIC
# This will be updated with custom weights before judging
current_rubric = copy.deepcopy(utils.DEFAULT_RUBRIC)

# --- Callback Functions ---

def add_single_project():
    """Callback to scrape and add a single project."""
    single_url = st.session_state.get("single_url", "") # Get URL from state
    if not single_url or not single_url.startswith("http"):
        st.warning("Please enter a valid URL.")
        return # Exit callback if invalid

    with st.spinner(f"Scraping project details from {single_url}..."):
        scraped_data = utils.scrape_project_page(single_url)

    if scraped_data and "error" not in scraped_data:
        # Basic validation
        if scraped_data.get("name", "Name Not Found") == "Name Not Found":
             st.warning(f"Could not reliably scrape project name from {single_url}.", icon="⚠️")
        if scraped_data.get("video_url", "Video URL Not Found") == "Video URL Not Found":
             st.warning(f"Could not find a video URL on {single_url}.", icon="⚠️")
        if scraped_data.get("repo_link", "GitHub Link Not Found") == "GitHub Link Not Found":
             st.warning(f"Could not find a GitHub link on {single_url}.", icon="⚠️")

        # Add to project list
        st.session_state.projects.append({
            "name": scraped_data.get("name", "Unknown Project"),
            "description": scraped_data.get("description", "No description found."),
            "video_url": scraped_data.get("video_url"),
            "repo_link": scraped_data.get("repo_link"),
            "status": "Pending",
            "source_url": single_url
        })
        st.success(f"Project '{scraped_data.get('name', 'Unknown Project')}' added from URL!")
        # Clear the input field state *within the callback*
        st.session_state.single_url = ""
    elif scraped_data and "error" in scraped_data:
        st.error(f"Failed to scrape {single_url}: {scraped_data['error']}")
    else:
        st.error(f"An unknown error occurred while scraping {single_url}.")


def add_projects_from_list():
    """Callback to scrape a list page and add multiple projects."""
    list_url = st.session_state.get("list_url", "") # Get URL from state
    if not list_url or not list_url.startswith("http"):
        st.warning("Please enter a valid URL.")
        return # Exit callback if invalid

    project_links = []
    with st.spinner(f"Scanning {list_url} for project links..."):
        scrape_result = utils.scrape_project_list_page(list_url)
        if isinstance(scrape_result, dict) and "error" in scrape_result:
             st.error(f"Failed to scan list page: {scrape_result['error']}")
             return # Exit callback on error
        elif isinstance(scrape_result, list):
             project_links = scrape_result
             st.info(f"Found {len(project_links)} potential project links. Now scraping details...")
        else:
             st.error("Unknown error scanning list page.")
             return # Exit callback on error

    if project_links:
        added_count = 0
        failed_count = 0
        # Display progress within the main app area after callback runs
        # We can't easily update progress bar *during* callback execution directly
        # So we'll just show status messages.
        st.info(f"Starting scrape for {len(project_links)} projects...")

        for i, link in enumerate(project_links):
            # Consider adding a small delay or status update if needed,
            # but direct UI updates from callbacks are limited.
            scraped_data = utils.scrape_project_page(link)

            if scraped_data and "error" not in scraped_data:
                 st.session_state.projects.append({
                    "name": scraped_data.get("name", f"Unknown Project {i+1}"),
                    "description": scraped_data.get("description", "No description found."),
                    "video_url": scraped_data.get("video_url"),
                    "repo_link": scraped_data.get("repo_link"),
                    "status": "Pending",
                    "source_url": link
                 })
                 added_count += 1
            else:
                failed_count += 1
                error_msg = scraped_data.get('error', 'Unknown scraping error') if isinstance(scraped_data, dict) else 'Unknown scraping error'
                st.warning(f"Skipped {link}: {error_msg}", icon="⚠️")

        st.success(f"Finished scraping. Added {added_count} projects, failed to scrape {failed_count}.")
        # Clear the input field state *within the callback*
        st.session_state.list_url = ""


# --- New Input Section ---
st.header("Add Projects via URL")

input_mode = st.radio(
    "Select Input Mode:",
    ("Single Project URL", "Project List URL (e.g., Showcase Page)"),
    horizontal=True,
    key="input_mode"
)

if input_mode == "Single Project URL":
    # Input widget - reads initial value from state if it exists
    single_url_input = st.text_input(
        "Enter Project Showcase URL (e.g., ETHGlobal project page):",
        key="single_url" # State key
    )
    # Button - triggers the callback on click
    st.button(
        "Fetch and Add Single Project",
        key="fetch_single_btn", # Button's own key
        on_click=add_single_project # Assign the callback
    )
    # The logic previously inside 'if st.button(...)' is now in add_single_project

elif input_mode == "Project List URL (e.g., Showcase Page)":
    # Input widget
    list_url_input = st.text_input(
        "Enter URL of page listing projects (e.g., ETHGlobal showcase):",
        key="list_url" # State key
    )
    # Button - triggers the callback on click
    st.button(
        "Fetch Projects from List Page",
        key="fetch_list_btn", # Button's own key
        on_click=add_projects_from_list # Assign the callback
    )
    # The logic previously inside 'if st.button(...)' is now in add_projects_from_list


# --- Display Added Projects ---
st.header("Projects Added for Judging")
if st.session_state.projects:
    display_data = []
    for p_idx, p in enumerate(st.session_state.projects): # Use enumerate for unique keys if needed later
        full_desc = p.get('description', 'N/A')
        # --- Truncate description for the table ---
        truncated_desc = (full_desc[:150] + '...') if len(full_desc) > 150 else full_desc

        display_data.append({
            "Project Name": p.get('name', 'N/A'),
            # --- Show truncated description ---
            "Project Description": truncated_desc,
            "Video Url": p.get('video_url', 'Not Found') if p.get('video_url') and p.get('video_url') != "Video URL Not Found" else 'Not Found',
            "Github Repo link": p.get('repo_link', 'Not Found') if p.get('repo_link') and p.get('repo_link') != "GitHub Link Not Found" else 'Not Found',
        })
    st.dataframe(pd.DataFrame(display_data), use_container_width=True)
    # Optional: Add expanders below the table to show full descriptions if needed
    # with st.expander("View Full Descriptions"):
    #     for p in st.session_state.projects:
    #         st.markdown(f"**{p.get('name', 'N/A')}:**")
    #         st.markdown(p.get('description', 'N/A'))
    #         st.markdown("---")
else:
    st.info("No projects added yet. Use the URL input options above.")

# --- Rubric Weight Customization ---
st.header("Customize Judging Weights (%)")
total_weight = 0
weights_valid = True

# Use columns for better layout
cols = st.columns(len(current_rubric['criteria']))

for i, criterion in enumerate(current_rubric['criteria']):
    criterion_name = criterion['name']
    with cols[i]:
        # Use slider for weight input, referencing session state
        # The key for the slider must be unique, use criterion_name
        st.session_state.custom_weights[criterion_name] = st.number_input(
            label=f"{criterion_name} Weight",
            min_value=0,
            max_value=100,
            value=st.session_state.custom_weights[criterion_name], # Get current value from state
            step=5, # Increment by 5
            key=f"weight_{criterion_name}" # Unique key for the widget
        )
        # Display description below slider
        st.caption(criterion['description'])
        total_weight += st.session_state.custom_weights[criterion_name]

# Display total weight and validation message
st.metric("Total Weight Allocated", f"{total_weight}%")
if total_weight != 100:
    st.warning(f"Weights must sum to 100%. Current total: {total_weight}%")
    weights_valid = False
else:
    st.success("Weights sum to 100%. Ready to judge.")

# --- Judging Trigger ---
st.header("Start Judging")

# Now, check conditions for showing the button *under* the header
# Add check for valid weights
if st.session_state.projects and not st.session_state.processing:
    # Disable button if weights are invalid
    judge_button_disabled = not weights_valid
    button_tooltip = "Adjust weights to sum to 100% before judging." if judge_button_disabled else None

    if st.button("Judge All Pending Projects", disabled=judge_button_disabled, help=button_tooltip):
        st.session_state.processing = True
        st.session_state.results = [] # Reset results

        # --- Construct the final rubric with custom weights ---
        final_custom_rubric = copy.deepcopy(utils.DEFAULT_RUBRIC) # Start with default structure
        for criterion in final_custom_rubric['criteria']:
            criterion['weight'] = st.session_state.custom_weights.get(criterion['name'], 0) # Apply custom weight

        st.info(f"Starting judgment for {len(st.session_state.projects)} projects using custom weights...")

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
                                # --- Pass the final_custom_rubric ---
                                ai_result = utils.get_ai_judgment(
                                    project["description"],
                                    transcript if not transcript.startswith("Error:") else None,
                                    readme_content if not readme_content.startswith("Error:") else None,
                                    final_custom_rubric # Pass the rubric with custom weights
                                )

                                if "error" in ai_result:
                                    st.error(f"Failed to judge {project['name']}: {ai_result['error']}")
                                    # Use final_custom_rubric for default scores/rationales
                                    scores = {c['name']: 0 for c in final_custom_rubric['criteria']}
                                    rationales = {c['name']: f"Judging failed: {ai_result['error']}" for c in final_custom_rubric['criteria']}
                                    feedback = f"AI Judging Error: {ai_result['error']}"
                                    total_score = 0
                                    project["status"] = "Error"
                                else:
                                    scores = ai_result.get("scores", {})
                                    rationales = ai_result.get("rationales", {})
                                    feedback = ai_result.get("feedback", "No feedback provided by AI.")
                                    # --- Pass final_custom_rubric to calculate score ---
                                    total_score = utils.calculate_total_score(scores, final_custom_rubric)
                                    project["status"] = "Judged"
                                    project_status_placeholder.success("Judgment complete!")

                except Exception as e:
                    project["status"] = f"Error: {e}"
                    transcript = transcript or "N/A"
                    readme_content = readme_content or "N/A"
                    ai_result = {"error": str(e)}
                    # Use final_custom_rubric for default scores/rationales
                    scores = {c['name']: 0 for c in final_custom_rubric['criteria']}
                    rationales = {c['name']: f"Judging failed: {e}" for c in final_custom_rubric['criteria']}
                    feedback = f"Processing Error: {e}"
                    total_score = 0

                # Store results regardless of success/failure for display
                results_list.append({
                    "Project Name": project["name"],
                    "Description": project["description"],
                    "Total Score": total_score,
                    "scores": scores,
                    "Rationales": rationales,
                    "feedback": feedback,
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
    # --- Use the *last used* custom rubric for display headers/details ---
    # Reconstruct the rubric used for the displayed results if possible
    # For simplicity, we'll assume the current weights in session state
    # reflect the weights used for the last judgment run.
    # A more robust solution might store the rubric used with the results.
    display_rubric = copy.deepcopy(utils.DEFAULT_RUBRIC)
    for criterion in display_rubric['criteria']:
        criterion['weight'] = st.session_state.custom_weights.get(criterion['name'], 0)

    # Prepare DataFrame for display
    display_df_data = []
    for res in st.session_state.results:
        row = {
            "Rank": len(display_df_data) + 1,
            "Project Name": res.get("Project Name", "Unknown"), # Use .get here too
            "Total Score": res.get("Total Score", "N/A"),
            "Status": res.get("Status", "Unknown")
        }
        # Add individual scores to the row
        # --- Access scores correctly from the nested dictionary ---
        project_scores = res.get("scores", {}) # Get the scores dict for this project
        for crit in display_rubric['criteria']:
            row[crit['name']] = project_scores.get(crit['name'], 'N/A') # Get score from project_scores
        display_df_data.append(row)

    results_df = pd.DataFrame(display_df_data)
    # --- Dynamically set columns based on display_rubric ---
    column_order = ["Rank", "Project Name", "Total Score", "Status"] + [c['name'] for c in display_rubric['criteria']]
    st.dataframe(results_df.set_index('Rank')[column_order]) # Reorder columns

    # --- Display Detailed Judging Breakdown ---
    st.subheader("Detailed Judging Breakdown")
    for i, res in enumerate(st.session_state.results):
        st.markdown(f"---") # Separator
        st.markdown(f"### {i+1}. {res.get('Project Name', 'Unknown Project')}")
        st.markdown(f"**Status:** {res.get('Status', 'Unknown')}")
        st.markdown(f"**Total Score:** {res.get('Total Score', 'N/A')}")

        # --- Display the FULL Project Description here ---
        with st.expander("View Full Project Description"):
             # Access the full description stored during results aggregation
             # Assuming the 'Description' key was added to results_list
             full_description = res.get('Description', 'Full description not available in results.')
             st.markdown(full_description)

        # Display Scores & Rationales per criterion
        st.markdown("**Scores & Rationales:**")
        rationales = res.get('Rationales', {})
        scores = res.get('scores', {})
        if rationales or scores:
            # --- Use display_rubric criteria for iteration ---
            for crit in display_rubric['criteria']:
                criterion_name = crit['name']
                score = scores.get(criterion_name, "N/A")
                rationale = rationales.get(criterion_name, "No rationale provided.")
                # --- Use display_rubric scale ---
                with st.expander(f"**{criterion_name}:** {score}/{display_rubric['scale'][1]}"):
                    st.write(rationale)
        else:
            st.warning("No detailed scores or rationales available for this project.")

        # Display Overall Feedback
        st.markdown("**Overall Feedback:**")
        # --- Access feedback correctly ---
        feedback = res.get('feedback', 'No overall feedback provided.')
        st.info(feedback) # Use st.info or st.markdown for feedback display

        # Optionally display transcript and README in expanders
        with st.expander("View Transcript"):
            st.text_area("Transcript", res.get('Transcript', 'N/A'), height=150, disabled=True)
        with st.expander("View README"):
            st.text_area("README", res.get('README', 'N/A'), height=150, disabled=True)

else:
    st.info("No results to display yet. Add projects and click 'Judge All Pending Projects'.")

# --- Option to Clear Data ---
st.sidebar.header("Admin")
if st.sidebar.button("Clear All Projects and Results"):
    st.session_state.projects = []
    st.session_state.results = None
    st.session_state.processing = False
    st.rerun() # Rerun the app to reflect the cleared state 