import streamlit as st
import pandas as pd
import utils # Import our helper functions
import tempfile # To create temporary directories for downloads
import os
import shutil # To clean up temporary directories
import copy # To deep copy the default rubric
from PIL import Image  # Add this import for handling images
import io # For parsing CSV data from text area

st.set_page_config(layout="wide", page_title="AI Judge", page_icon="⚖️")

# --- Sidebar with Logo ---
st.sidebar.header("AI Judge")
try:
    # Try to load and display the logo
    logo = Image.open("AIJudgeLogo.png")
    st.sidebar.image(logo, width=200)
except Exception as e:
    # If logo can't be loaded, show a text message instead
    st.sidebar.info("AI Judge - Automated Hackathon Project Evaluation")
    print(f"Note: Could not load logo: {e}")

# --- Main Title ---
st.title("ETH Hackathon AI Judge")

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
        
        # Handle video URL - show N/A if missing or error
        video_url = p.get('video_url', 'N/A')
        if not video_url or video_url == "Video URL Not Found":
            video_url = 'N/A'
            
        # Handle GitHub repo link - show N/A if missing or error
        repo_link = p.get('repo_link', 'N/A')
        if not repo_link or repo_link == "GitHub Link Not Found":
            repo_link = 'N/A'

        display_data.append({
            "Project Name": p.get('name', 'N/A'),
            # --- Show truncated description ---
            "Project Description": truncated_desc,
            "Video Url": video_url,
            "Github Repo link": repo_link,
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
                    if project["video_url"] and project["video_url"] != "Video URL Not Found" and project["video_url"] != "N/A":
                        # Transform ETHGlobal video URLs if needed
                        video_url = utils.transform_ethglobal_video_url(project["video_url"])
                        downloaded_video_path = utils.download_video_from_url(video_url, temp_project_dir)
                        if not downloaded_video_path:
                            project_status_placeholder.warning("⚠️ Video download failed, continuing without video")
                            transcript = "N/A - No video available"
                        else:
                            project_status_placeholder.info("🔈 Extracting audio...")
                            # --- 2. Extract Audio ---
                            audio_path = utils.extract_audio_from_video(downloaded_video_path)
                            if not audio_path:
                                project_status_placeholder.warning("⚠️ Audio extraction failed, continuing without transcript")
                                transcript = "N/A - Audio extraction failed"
                            else:
                                project_status_placeholder.info("🎤 Transcribing audio (Whisper)...")
                                transcript = utils.transcribe_audio(audio_path)
                    else:
                        project_status_placeholder.info("ℹ️ No video URL available, skipping video processing")
                        transcript = "N/A - No video URL provided"

                    # --- 4. Fetch README ---
                    project_status_placeholder.info("📄 Fetching README...")
                    if project["repo_link"] and project["repo_link"] != "GitHub Link Not Found" and project["repo_link"] != "N/A":
                        readme_content = utils.fetch_readme(project["repo_link"])
                        if "Error:" in readme_content:
                            # Limit readme length if necessary
                            readme_content = readme_content[:4000]  # Limit to ~4k chars
                    else:
                        project_status_placeholder.info("ℹ️ No GitHub repository link available, skipping README")
                        readme_content = "N/A - No GitHub repository link provided"

                    project_status_placeholder.info("🤖 Calling AI Judges (GPT-4o and Claude)...")
                    # --- 5. AI Judging ---
                    # --- Pass the final_custom_rubric ---
                    ai_result = utils.get_combined_judgment(
                        project["description"],
                        transcript if not transcript.startswith("Error:") else None,
                        readme_content if not readme_content.startswith("Error:") else None,
                        final_custom_rubric, # Pass the rubric with custom weights
                        project["repo_link"] # Pass the repository URL
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
    # --- Create a DataFrame for display ---
    display_df_data = []
    # Use the rubric that was actually used for judging
    display_rubric = st.session_state.results[0].get('rubric_used', current_rubric)
    
    for i, res in enumerate(st.session_state.results):
        # Create a row for each result
        row = {
            "Project Name": res.get('Project Name', 'Unknown Project'),
            "Total Score": res.get('Total Score', 'N/A'),
            "Status": res.get('Status', 'Unknown')
        }
        
        # Add a rank column (1-based index)
        row["Rank"] = i + 1
        
        # Add individual criterion scores
        scores = res.get('scores', {})
        for criterion in display_rubric['criteria']:
            criterion_name = criterion['name']
            row[criterion_name] = scores.get(criterion_name, 'N/A')
        
        display_df_data.append(row)

    results_df = pd.DataFrame(display_df_data)
    # --- Dynamically set columns based on display_rubric ---
    column_order = ["Rank", "Project Name", "Total Score", "Status"] + [c['name'] for c in display_rubric['criteria']]
    
    # Check if all columns in column_order exist in the DataFrame
    valid_columns = [col for col in column_order if col in results_df.columns]
    
    # Use only valid columns and set Rank as index if it exists
    if "Rank" in results_df.columns:
        st.dataframe(results_df.set_index("Rank")[valid_columns[1:]])  # Skip 'Rank' in columns since it's the index
    else:
        # If 'Rank' doesn't exist, just display with all valid columns
        st.dataframe(results_df[valid_columns])

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
            # Get transcript and handle potential issues
            transcript = res.get('Transcript', 'N/A')
            try:
                # Limit length to avoid display issues
                if len(transcript) > 50000:
                    transcript = transcript[:50000] + "... (truncated due to length)"
                st.markdown("```\n" + transcript + "\n```")
            except Exception as e:
                st.error(f"Error displaying transcript: {e}")
                st.markdown("Transcript is available but cannot be displayed properly.")
            
        with st.expander("View README"):
            # Get README and handle potential issues
            readme = res.get('README', 'N/A')
            try:
                # Limit length to avoid display issues
                if len(readme) > 50000:
                    readme = readme[:50000] + "... (truncated due to length)"
                st.markdown("```\n" + readme + "\n```")
            except Exception as e:
                st.error(f"Error displaying README: {e}")
                st.markdown("README is available but cannot be displayed properly.")

else:
    st.info("No results to display yet. Add projects and click 'Judge All Pending Projects'.")

# --- Reward Distribution Section (In Sidebar) ---
st.sidebar.header("🏆 Reward Distribution (Polygon)")

# Check if distributor key is configured in environment
distributor_pk_configured = os.getenv("DISTRIBUTOR_PRIVATE_KEY") is not None

# Add input field for private key if not in environment
if not distributor_pk_configured:
    st.sidebar.info("Enter your distributor wallet private key below:")
    private_key_input = st.sidebar.text_input(
        "Distributor Private Key (0x...)",
        type="password",  # Hide the input for security
        help="Your private key is never stored and only used for this session."
    )
    # Consider the key configured if user has entered it in the UI
    distributor_pk_configured = bool(private_key_input)
else:
    st.sidebar.success("✅ Distributor wallet configured via environment")
    private_key_input = None  # No need for input if configured in environment


st.sidebar.subheader("Winners Data")
winners_input = st.sidebar.text_area(
    "Enter Winners (Address,Polygon Amount per line)",
    height=150,
    key="winners_data",
    help="Format: 0xAddress,RewardAmount\nExample:\n0x123...,100\n0x456...,50.5"
)

if st.sidebar.button("💸 Distribute Rewards", key="distribute_button", disabled=not distributor_pk_configured):
    if not distributor_pk_configured:
        st.sidebar.error("Please enter your distributor private key.")
    elif not winners_input:
        st.sidebar.error("Winners data cannot be empty.")
    else:
        # Parse winners data
        parsed_winners = []
        try:
            reader = io.StringIO(winners_input)
            for line in reader:
                line = line.strip()
                if not line or ',' not in line:
                    continue # Skip empty or invalid lines
                address, amount_str = line.split(',', 1)
                parsed_winners.append({'address': address.strip(), 'amount': amount_str.strip()})

            if not parsed_winners:
                 raise ValueError("No valid winner entries found in the input.")

            st.sidebar.info(f"Parsed {len(parsed_winners)} winner entries. Starting distribution...")

            # Call the backend function - now passing the private key from UI if needed
            with st.spinner("Sending transactions... Please wait."):
                distribution_results = utils.distribute_rewards(
                    private_key=private_key_input,  # Use UI input if provided
                    rpc_url=rpc_url_input,          # Use UI input for RPC
                    winners_data=parsed_winners,
                    # token_address is now loaded from environment in the function
                )

            # Display results
            st.sidebar.subheader("Distribution Results")
            success_count = 0
            error_count = 0
            for res in distribution_results:
                if res.get('status') == 'success':
                    success_count += 1
                    st.sidebar.success(f"✅ To: {res['address'][:6]}...{res['address'][-4:]}, Amount: {res['amount']}, Tx: {res['tx_hash'][:10]}...")
                elif res.get('status') == 'error':
                    error_count += 1
                    addr = res.get('address', 'N/A')
                    amt = res.get('amount', 'N/A')
                    st.sidebar.error(f"❌ To: {addr}, Amount: {amt}, Error: {res.get('message', 'Unknown error')}")
                else:
                     st.sidebar.warning(f"❓ Unknown status for entry: {res}")

            st.sidebar.info(f"Distribution complete. Success: {success_count}, Errors: {error_count}")

        except ValueError as ve:
             st.sidebar.error(f"Input Error: {ve}")
        except Exception as e:
            st.sidebar.error(f"An unexpected error occurred: {e}")
            # Fix the incorrect use of exc_info with print
            print(f"Distribution Error Traceback: {e}")
            # If you want to print the full traceback, use this instead:
            import traceback
            traceback.print_exc()


# --- Option to Clear Data ---
st.sidebar.header("Admin")
if st.sidebar.button("Clear All Projects and Results"):
    st.session_state.projects = []
    st.session_state.results = None
    st.session_state.processing = False
    st.rerun() # Rerun the app to reflect the cleared state 

# Add some space at the bottom of the sidebar
st.sidebar.markdown("<br><br>", unsafe_allow_html=True)

# Add the attribution to the sidebar
st.sidebar.markdown("<div style='color: rgba(38, 39, 48, 0.7); font-size: 14px;'>Made by Queenie Wu and Lucas</div>", unsafe_allow_html=True) 