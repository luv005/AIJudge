import os
import tempfile
import requests
import shutil # For cleaning up temporary directories
from moviepy.editor import VideoFileClip
from openai import OpenAI
from dotenv import load_dotenv, find_dotenv
import json
import yt_dlp # Import the downloader library
from bs4 import BeautifulSoup # Import BeautifulSoup
from urllib.parse import urljoin # To construct absolute URLs
import re
from anthropic import Anthropic
import numpy as np
from web3 import Web3
from decimal import Decimal # For precise amount handling

# --- Force loading .env and specify path ---
# Find the .env file starting from the current script's directory
dotenv_path = find_dotenv()
print(f"DEBUG: Attempting to load .env file from: {dotenv_path}")
# Load the .env file, overriding existing environment variables
loaded = load_dotenv(dotenv_path=dotenv_path, override=True)
if not loaded:
    print("WARNING: .env file not found or not loaded.")

openai_api_key = os.getenv("OPENAI_API_KEY")

# --- Add explicit check and print for debugging ---
if not openai_api_key:
    print("ERROR: OPENAI_API_KEY not found in environment variables after load_dotenv(). Please check .env file.")
    # Optionally raise an error here if you want the app to stop
    # raise ValueError("OPENAI_API_KEY not found...")
else:
    # Print part of the key for verification (avoid printing the whole key)
    print(f"DEBUG: Found API Key starting with: {openai_api_key[:6]}... and ending with ...{openai_api_key[-4:]}")

# Add Claude API key to environment variables check
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
if not anthropic_api_key:
    print("WARNING: ANTHROPIC_API_KEY not found in environment variables. Claude judging will be skipped.")

# --- Configuration ---
# Define the judging rubric (can be loaded from config or UI later)
DEFAULT_RUBRIC = {
    "criteria": [
        {
            "name": "Technicality",
            "weight": 20, # Default equal weight
            "description": "How complex is the problem you're addressing, and how sophisticated is your solution?"
        },
        {
            "name": "Originality",
            "weight": 20, # Default equal weight
            "description": "Is your project introducing a new idea or creatively solving an existing problem?"
        },
        {
            "name": "Practicality",
            "weight": 20, # Default equal weight
            "description": "How complete and functional is your project? Could it be used by its target audience today?"
        },
        {
            "name": "Usability (UI/UX/DX)",
            "weight": 20, # Default equal weight
            "description": "How intuitive is your project? Have you made it easy for users to interact with your solution?"
        },
        {
            "name": "WOW Factor",
            "weight": 20, # Default equal weight
            "description": "Does your project leave a lasting impression? This is the catch-all for anything unique or impressive that may not fit into the other categories."
        }
    ],
    "scale": (1, 10) # Min and Max score for each criterion
}

# --- Web Scraping Functions ---

def scrape_project_page(url):
    """
    Scrapes an ETHGlobal showcase project page for details.
    NOTE: This is highly dependent on ETHGlobal's HTML structure and may break.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        # --- Use lxml parser ---
        soup = BeautifulSoup(response.content, 'lxml') # Use 'lxml' parser

        project_data = {"source_url": url} # Store the original URL

        # --- Extract Project Name ---
        name_tag = soup.find('h1')
        project_data["name"] = name_tag.text.strip() if name_tag else "Name Not Found"

        # --- Extract Description Parts ---
        full_description_parts = []
        print(f"DEBUG: Starting description extraction for {url}") # Debug print

        # Helper function to extract text between a start node and the next specified header tag(s)
        def extract_text_until_next_header(start_node, stop_header_tags=['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            """Extracts text from siblings of start_node until a stop header tag is encountered."""
            content = []
            print(f"DEBUG: Extracting text after node: {start_node.name} '{start_node.get_text(strip=True)[:30]}...'") # Debug print
            for sibling in start_node.find_next_siblings():
                # Check if the sibling itself is a stop header
                if hasattr(sibling, 'name') and sibling.name in stop_header_tags:
                    print(f"DEBUG: Stopping extraction at header: {sibling.name} '{sibling.get_text(strip=True)[:30]}...'") # Debug print
                    break # Stop if we hit the next header

                # Append text content of the sibling node, handling potential None return from get_text
                sibling_text = sibling.get_text(separator='\n', strip=True)
                if sibling_text: # Only append if there's actual text
                     content.append(sibling_text)
                # else: # Optional: print skipped siblings
                #    print(f"DEBUG: Skipping sibling node: {sibling.name if hasattr(sibling, 'name') else type(sibling)}")

            # Join collected parts, filter out empty strings potentially left by pure whitespace nodes
            joined_content = "\n".join(filter(None, content)).strip()
            print(f"DEBUG: Extracted text length: {len(joined_content)}") # Debug print
            return joined_content

        # 1. Find "Project Description" header (specifically h3 based on example)
        desc_header = soup.find('h3', string=lambda text: text and "project description" in text.lower())
        if desc_header:
            print(f"DEBUG: Found 'Project Description' header: {desc_header.get_text(strip=True)}") # Debug print
            main_desc_text = extract_text_until_next_header(desc_header, stop_header_tags=['h3']) # Stop specifically at the next h3
            if main_desc_text:
                full_description_parts.append(main_desc_text)
            else:
                 print("DEBUG: No text extracted after 'Project Description' header.") # Debug print
        else:
            print(f"WARNING: Could not find 'Project Description' h3 header for {url}") # Debug print
            # --- Fallback attempt (less reliable) ---
            # Try finding the first substantial paragraph after the h1 as a basic fallback
            if name_tag:
                 first_p = name_tag.find_next('p')
                 if first_p:
                     fallback_text = first_p.get_text(separator='\n', strip=True)
                     # Avoid just the tagline if possible
                     if len(fallback_text) > 100:
                          print("DEBUG: Using first paragraph after H1 as fallback description.")
                          full_description_parts.append(fallback_text)


        # 2. Find "How it's Made" header (specifically h3 based on example)
        made_header = soup.find('h3', string=lambda text: text and "how it's made" in text.lower())
        if made_header:
            print(f"DEBUG: Found 'How it's Made' header: {made_header.get_text(strip=True)}") # Debug print
            made_desc_text = extract_text_until_next_header(made_header, stop_header_tags=['h2', 'h3']) # Stop at next h2 or h3
            if made_desc_text:
                # Add separator only if adding this section
                full_description_parts.append("\n\n--- How It's Made ---\n")
                full_description_parts.append(made_desc_text)
            else:
                 print("DEBUG: No text extracted after 'How it's Made' header.") # Debug print
        else:
             print(f"WARNING: Could not find 'How it's Made' h3 header for {url}") # Debug print


        # 3. Combine parts or set default
        if full_description_parts:
            # Join parts, ensuring no leading/trailing whitespace on the final result
            project_data["description"] = "\n".join(full_description_parts).strip()
            print(f"DEBUG: Final combined description length: {len(project_data['description'])}") # Debug print
        else:
            # If absolutely nothing was found, set default and log warning
            print(f"ERROR: Failed to extract any description content for {url}. Defaulting.") # Debug print
            project_data["description"] = "Description Not Found"


        # --- Extract Video URL ---
        video_url = None
        print(f"DEBUG: Starting video URL extraction for {url}")

        # 1. Look for an iframe first (common for YouTube/Vimeo embeds)
        iframe = soup.find('iframe')
        if iframe and 'src' in iframe.attrs:
            video_url = iframe['src']
            video_url = urljoin(url, video_url) # Handle relative URLs
            print("DEBUG: Method 1: Found video URL in iframe.")

        # 2. Look for ETHGlobal/Mux player container and extract data attribute
        if not video_url:
            print("DEBUG: Method 2: Searching for Mux player div via data-controller.")
            player_container = soup.find('div', attrs={'data-controller': 'video-player'})
            if player_container:
                print("DEBUG: Found potential player container div.")
                playback_id = player_container.get('data-video-player-playback-id-value')
                if playback_id:
                    video_url = f"https://stream.mux.com/{playback_id}/high.mp4"
                    print(f"DEBUG: Successfully extracted Mux playback ID '{playback_id}' and constructed URL: {video_url}")
                else:
                    print("DEBUG: Found player container div, but 'data-video-player-playback-id-value' attribute is missing or empty.")
            else:
                print("DEBUG: Player container div with data-controller='video-player' not found.")

        # 2.5 Look for Mux video URL in the HTML source (new method)
        if not video_url:
            print("DEBUG: Method 2.5: Searching for Mux video URL pattern in HTML source.")
            # Look for the pattern "https://stream.mux.com/XXXX/high.mp4" in the HTML
            mux_pattern = r'https://stream\.mux\.com/([A-Za-z0-9]+)/high\.mp4'
            mux_matches = re.findall(mux_pattern, str(soup))
            if mux_matches:
                # Use the first match
                playback_id = mux_matches[0]
                video_url = f"https://stream.mux.com/{playback_id}/high.mp4"
                print(f"DEBUG: Found Mux video URL in HTML source with playback ID: {playback_id}")
            else:
                # Also try looking for thumbnail URLs which contain the same ID
                thumbnail_pattern = r'https://image\.mux\.com/([A-Za-z0-9]+)/thumbnail\.png'
                thumbnail_matches = re.findall(thumbnail_pattern, str(soup))
                if thumbnail_matches:
                    playback_id = thumbnail_matches[0]
                    video_url = f"https://stream.mux.com/{playback_id}/high.mp4"
                    print(f"DEBUG: Found Mux thumbnail URL in HTML source with playback ID: {playback_id}")
                else:
                    print("DEBUG: No Mux video or thumbnail URL patterns found in HTML source.")

        # 3. Fallback: Look for a direct <video> tag with a src attribute
        if not video_url:
            print("DEBUG: Method 3: Falling back to searching for direct <video> tag.")
            video_tag = soup.find('video')
            if video_tag and 'src' in video_tag.attrs:
                video_url = video_tag['src']
                video_url = urljoin(url, video_url) # Handle relative URLs
                print(f"DEBUG: Found video URL in direct <video> tag: {video_url}")
            else:
                print("DEBUG: Direct <video> tag with src not found.")

        # 4. Special case for ETHGlobal showcase URLs
        if not video_url and "ethglobal.com/showcase/" in url:
            print("DEBUG: Method 4: Using ETHGlobal showcase URL pattern fallback.")
            # Extract the project ID from the URL
            # Example: https://ethglobal.com/showcase/ape-tweet-87obi -> project_id = "87obi"
            try:
                # Split by last dash and take the last part
                project_id = url.split('-')[-1]
                if project_id and len(project_id) > 3:
                    # Known project mappings - add more as they're discovered
                    known_projects = {
                        # "87obi": "01CwsoCbFScKx1xpGUvmkIDYXD02Dq7TbjdPS5zUx014fw",  # Ape Tweet
                        # "g0jzy": "2pCxag501Mbk02Qi5Q21ydMM2qQg2hkCi47Fxn02gPgPPM",   # Prophet AI
                        # "xqc2b": "8uakAxLbWvxkgrg71prSbgYxbjjSrsBvtimp025h00jyM",    # Sentiplex
                        # "aa4xc": "01Gy9Yx01Gy9Yx01Gy9Yx01Gy9Yx01Gy9Yx01Gy9Yx01Gy9Yx01Gy9Yx"  # Rupabase (placeholder ID)
                    
                    }
                    
                    if project_id in known_projects:
                        mux_id = known_projects[project_id]
                        video_url = f"https://stream.mux.com/{mux_id}/high.mp4"
                        print(f"DEBUG: Using known Mux URL for project ID {project_id}: {video_url}")
                    else:
                        # For other projects, construct the API URL and follow redirects
                        api_url = f"https://ethglobal.com/api/projects/{project_id}/video"
                        # Use the transform_ethglobal_video_url function to follow redirects
                        transformed_url = transform_ethglobal_video_url(api_url)
                        
                        # Only use the transformed URL if it's different from the API URL
                        # (meaning the redirect was successful)
                        if transformed_url != api_url:
                            video_url = transformed_url
                            print(f"DEBUG: Successfully transformed API URL for project ID {project_id}: {video_url}")
                        else:
                            # If transformation failed, set to None so "Video URL Not Found" will be used
                            print(f"DEBUG: Failed to transform API URL for project ID {project_id}")
                            video_url = None
                else:
                    print(f"DEBUG: Could not extract valid project ID from URL: {url}")
            except Exception as e:
                print(f"DEBUG: Error in ETHGlobal showcase URL pattern fallback: {e}")

        # Final assignment
        project_data["video_url"] = video_url if video_url else "Video URL Not Found"
        if not video_url:
             print(f"WARNING: Failed to find video URL for {url} using all methods.")
        else:
             print(f"INFO: Final video URL found for {url}: {project_data['video_url']}")


        # --- Extract GitHub Repository Link ---
        # Look for an <a> tag linking to github.com
        github_link = None
        # Find links specifically containing 'github.com' in href
        for a_tag in soup.find_all('a', href=True):
            if 'github.com' in a_tag['href']:
                github_link = a_tag['href']
                break # Take the first one found
        project_data["repo_link"] = github_link if github_link else "GitHub Link Not Found"

        print(f"Scraped data for {url}: {project_data}")
        return project_data

    except requests.exceptions.RequestException as e:
        print(f"Error fetching project page {url}: {e}")
        return {"error": f"Network error fetching page: {e}"}
    except Exception as e:
        print(f"Error scraping project page {url}: {e}")
        return {"error": f"Scraping failed: {e}"}


def scrape_project_list_page(list_url):
    """
    Scrapes an ETHGlobal showcase list page for individual project links.
    NOTE: This is highly dependent on ETHGlobal's HTML structure and may break.
    """
    project_links = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(list_url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Find all links whose href starts with '/showcase/'
        links = soup.find_all('a', href=lambda href: href and href.startswith('/showcase/'))

        found_urls = set()  # Use a set to avoid duplicates
        for link in links:
            href = link['href']
            # Construct absolute URL
            absolute_url = urljoin(list_url, href)
            
            # Skip non-project links like "Find a Project" or search pages
            if any(skip_term in href.lower() for skip_term in [
                'find-a-project', 
                'search', 
                'filter', 
                'category', 
                'track'
            ]):
                print(f"DEBUG: Skipping non-project URL: {absolute_url}")
                continue
                
            # Basic check to avoid non-project links if possible
            if '/showcase/' in absolute_url and absolute_url != list_url and absolute_url not in found_urls:
                # Add more filtering if needed (e.g., check URL structure further)
                project_links.append(absolute_url)
                found_urls.add(absolute_url)

        print(f"Found {len(project_links)} potential project links on {list_url}")
        return project_links

    except requests.exceptions.RequestException as e:
        print(f"Error fetching list page {list_url}: {e}")
        return {"error": f"Network error fetching page: {e}"}
    except Exception as e:
        print(f"Error scraping list page {list_url}: {e}")
        return {"error": f"Scraping failed: {e}"}


# --- Preprocessing Functions ---

def download_video_from_url(url, output_dir):
    """Downloads a video from a URL to the specified directory."""
    if not url:
        print("No URL provided for video download")
        return None
    
    # Transform ETHGlobal URLs if needed
    url = transform_ethglobal_video_url(url)
    
    try:
        # Create a unique filename for the video
        video_path = os.path.join(output_dir, "downloaded_video.mp4")
        
        # Configure yt-dlp options
        ydl_opts = {
            'format': 'best',  # Download best quality
            'outtmpl': video_path,  # Output template
            'quiet': True,  # Less output
            'no_warnings': True,  # No warnings
            'ignoreerrors': True,  # Skip on errors
        }
        
        # For direct MP4 URLs, use requests instead of yt-dlp
        if url.endswith('.mp4') or 'stream.mux.com' in url:
            print(f"Direct MP4 URL detected: {url}")
            response = requests.get(url, stream=True)
            if response.status_code == 200:
                with open(video_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"Video downloaded to {video_path}")
                return video_path
            else:
                print(f"Failed to download video: HTTP {response.status_code}")
                return None
        
        # Use yt-dlp for other URLs
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        # Check if file exists and has content
        if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
            print(f"Video downloaded to {video_path}")
            return video_path
        else:
            print("Video download failed or file is empty")
            return None
            
    except Exception as e:
        print(f"Error downloading video: {e}")
        return None

def extract_audio_from_video(video_path, output_audio_path="temp_audio.mp3"):
    """Extracts audio from a video file."""
    # Remove the check for ENABLE_VIDEO_PROCESSING

    # Basic check for video path existence
    if not video_path or not os.path.exists(video_path):
        print(f"ERROR: Video file not found at path: {video_path}")
        return None

    try:
        print(f"DEBUG: Attempting to process video: {video_path}")
        # Ensure output_audio_path is defined if not passed
        if not output_audio_path:
             temp_dir = tempfile.gettempdir()
             output_audio_path = os.path.join(temp_dir, "extracted_audio.mp3")

        video = VideoFileClip(video_path)
        audio = video.audio
        audio.write_audiofile(output_audio_path)
        audio.close() # Close the audio object
        video.close() # Close the video object
        print(f"DEBUG: Audio extracted successfully to {output_audio_path}")
        return output_audio_path # Return the path on success
    except Exception as e: # General exception handling
        print(f"ERROR: Unexpected error extracting audio: {e}")
        # Clean up potentially created video/audio objects if they exist
        if 'video' in locals() and video: video.close()
        if 'audio' in locals() and audio: audio.close()
        return None # Return None on failure

def transcribe_audio(audio_path):
    """Transcribes audio using OpenAI Whisper API."""
    # --- Reload key just in case ---
    load_dotenv(dotenv_path=dotenv_path, override=True)
    local_api_key = os.getenv("OPENAI_API_KEY")
    print(f"DEBUG (transcribe): Using key starting with: {local_api_key[:6] if local_api_key else 'None'}...") # Add debug here too
    if not local_api_key:
         print("ERROR: API Key missing when trying to transcribe.")
         return "Error: OpenAI API Key not configured."
    try:
        client = OpenAI(api_key=local_api_key) # Initialize here
        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        # os.remove(audio_path) # Clean up temp audio file - MOVED TO app.py finally block implicitly
        return transcript.text
    except Exception as e:
        print(f"Error during transcription: {e}")
        # Clean up audio file if transcription failed - Handled in app.py
        # if os.path.exists(audio_path):
        #     os.remove(audio_path)
        return f"Error during transcription: {e}"

def fetch_readme(repo_url):
    """Fetches README content from a GitHub repository URL."""
    # Basic parsing, assumes standard GitHub URL structure
    # e.g., https://github.com/owner/repo
    try:
        parts = repo_url.strip('/').split('/')
        if len(parts) < 5 or parts[2] != 'github.com':
            return "Error: Invalid GitHub URL format. Expected https://github.com/owner/repo"

        owner, repo = parts[3], parts[4]
        # Try fetching README.md first, then README
        readme_names = ["README.md", "README"]
        for name in readme_names:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{name}"
            # Using requests for simplicity, could use PyGithub for more features
            response = requests.get(api_url, headers={'Accept': 'application/vnd.github.v3.raw'})
            if response.status_code == 200:
                return response.text
            elif response.status_code == 404:
                continue # Try the next name
            else:
                # Handle other potential errors like rate limiting
                return f"Error fetching README: {response.status_code} - {response.text}"
        return "Error: README file not found in the root directory."
    except Exception as e:
        print(f"Error parsing URL or fetching README: {e}")
        return f"Error processing GitHub URL: {e}"

# --- AI Judging Function ---

def get_ai_judgment(project_description, pitch_transcript, readme_content, rubric, repo_url=None):
    """Generates AI judgment using OpenAI GPT-4o based on provided texts and rubric."""
    
    # Get commit count if repo_url is provided
    commit_count = None
    if repo_url and "github.com" in repo_url:
        commit_count = get_github_commit_count(repo_url)
        print(f"DEBUG: GitHub repository has {commit_count} commits")
    
    # Load winning projects as reference
    winning_projects_text = ""
    try:
        with open("winningprojects.txt", "r") as f:
            winning_projects_text = f.read()
        print("DEBUG: Successfully loaded winning projects reference data")
    except Exception as e:
        print(f"DEBUG: Could not load winning projects reference: {e}")
        winning_projects_text = "Reference data unavailable."
    
    # --- Ensure criteria_str uses the passed rubric ---
    criteria_str = "\n".join([
        f"- {c['name']} (Weight: {c['weight']}%, Scale: {rubric['scale'][0]}-{rubric['scale'][1]}): {c['description']}"
        for c in rubric['criteria'] # Use the rubric passed to the function
    ])

    # Add commit count information to the prompt
    commit_info = ""
    if commit_count is not None:
        commit_info = f"\n4. **GitHub Repository Commit Count:** {commit_count} commits"
        if commit_count == 1:
            commit_info += " (Note: Having only a single commit may indicate limited development effort or history, which should be considered when evaluating Technicality)"
    
    # --- Ensure the prompt uses the passed rubric's criteria names ---
    prompt = f"""
You are an AI Hackathon Judge for Ethereum Global hackathons. Evaluate the following project based on the provided information and the judging rubric.

**Project Information:**
1.  **Project Description:** {project_description}
2.  **Pitch Transcript:** {pitch_transcript if pitch_transcript else "Not available"}
3.  **README Content:** {readme_content if readme_content and not readme_content.startswith('Error:') else "Not available"}{commit_info}

**Reference: Previous ETHGlobal Winning Projects**
The following are descriptions of previous winning projects from ETHGlobal hackathons. Use these as reference points when evaluating the current project:

{winning_projects_text[:3000]}  

**Judging Rubric:**
{criteria_str}

**Instructions:**
1.  Provide a score between {rubric['scale'][0]} and {rubric['scale'][1]} for each criterion.
2.  For each criterion, provide a **detailed rationale** (3-5 sentences) explaining *why* the project received that specific score, referencing specific aspects of the project description, transcript, or README where applicable.
3.  Compare the project to previous winning projects where relevant, noting similarities or differences in quality, innovation, or execution.
4.  Provide an overall **feedback** section (a paragraph or bullet points) summarizing the project's strengths and suggesting specific areas for improvement.
5.  Output the results strictly in JSON format with the following structure:
{{
  "scores": {{
    "Criterion Name 1": score_1,
    "Criterion Name 2": score_2,
    ...
  }},
  "rationales": {{
    "Criterion Name 1": "Detailed rationale text 1...",
    "Criterion Name 2": "Detailed rationale text 2...",
    ...
  }},
  "feedback": "Overall feedback text..."
}}

Ensure the keys in "scores" and "rationales" exactly match the criterion names from the rubric: {[c['name'] for c in rubric['criteria']]}. Ensure the "feedback" key is present.

**Special Instructions:**
- If the GitHub repository has only a single commit, this should negatively impact the Technicality score, as it suggests minimal development effort or history.
- Consider how the current project compares to the quality and innovation level of previous winning projects.
- Be particularly attentive to projects that demonstrate novel approaches to blockchain technology or solve real-world problems in unique ways.

**JSON Output:**
"""

    # --- Reload key just in case ---
    load_dotenv(dotenv_path=dotenv_path, override=True)
    local_api_key = os.getenv("OPENAI_API_KEY")
    print(f"DEBUG (judge): Using key starting with: {local_api_key[:6] if local_api_key else 'None'}...") # Add debug here too
    if not local_api_key:
         print("ERROR: API Key missing when trying to judge.")
         return {"error": "OpenAI API Key not configured."}
    try:
        client = OpenAI(api_key=local_api_key) # Initialize here
        response = client.chat.completions.create(
            model="gpt-4o", # Use the specified model
            messages=[
                {"role": "system", "content": "You are an AI Hackathon Judge evaluating projects based on a rubric. Output results in JSON format."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}, # Ensure JSON output
            temperature=0.5, # Adjust temperature for creativity vs consistency
        )
        # Ensure response content is not None before accessing it
        if response.choices and response.choices[0].message and response.choices[0].message.content:
            result_json = response.choices[0].message.content
            # Basic validation of the JSON structure
            try:
                parsed_result = json.loads(result_json)
                if "scores" in parsed_result and "rationales" in parsed_result and "feedback" in parsed_result:
                     # Further check if keys match rubric criteria names
                    expected_keys = {c['name'] for c in rubric['criteria']}
                    if set(parsed_result["scores"].keys()) == expected_keys and \
                       set(parsed_result["rationales"].keys()) == expected_keys:
                        return parsed_result
                    else:
                         print("Warning: AI response JSON keys do not match rubric criteria.")
                         # Attempt to return anyway, might need manual correction
                         return parsed_result
                else:
                    print("Error: AI response JSON missing 'scores', 'rationales', or 'feedback' key.")
                    return {"error": "Invalid JSON structure from AI (missing keys)."}
            except json.JSONDecodeError as json_e:
                print(f"Error decoding AI response JSON: {json_e}")
                print(f"Raw AI response: {result_json}")
                return {"error": f"AI returned invalid JSON: {json_e}"}
        else:
            print("Error: Empty response received from OpenAI API.")
            return {"error": "Empty response from AI."}

    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return {"error": f"API call failed: {e}"}

def get_claude_judgment(project_description, pitch_transcript, readme_content, rubric, repo_url=None):
    """Generates AI judgment using Anthropic Claude based on provided texts and rubric."""
    
    # Get commit count if repo_url is provided
    commit_count = None
    if repo_url and "github.com" in repo_url:
        commit_count = get_github_commit_count(repo_url)
        print(f"DEBUG: GitHub repository has {commit_count} commits")
    
    # Load winning projects as reference
    winning_projects_text = ""
    try:
        with open("winningprojects.txt", "r") as f:
            winning_projects_text = f.read()
        print("DEBUG: Successfully loaded winning projects reference data for Claude")
    except Exception as e:
        print(f"DEBUG: Could not load winning projects reference for Claude: {e}")
        winning_projects_text = "Reference data unavailable."
    
    # --- Ensure criteria_str uses the passed rubric ---
    criteria_str = "\n".join([
        f"- {c['name']} (Weight: {c['weight']}%, Scale: {rubric['scale'][0]}-{rubric['scale'][1]}): {c['description']}"
        for c in rubric['criteria']
    ])

    # Add commit count information to the prompt
    commit_info = ""
    if commit_count is not None:
        commit_info = f"\n4. **GitHub Repository Commit Count:** {commit_count} commits"
        if commit_count == 1:
            commit_info += " (Note: Having only a single commit may indicate limited development effort or history, which should be considered when evaluating Technicality)"
    
    # --- Ensure the prompt uses the passed rubric's criteria names ---
    prompt = f"""
You are an AI Hackathon Judge for Ethereum Global hackathons. Evaluate the following project based on the provided information and the judging rubric.

**Project Information:**
1.  **Project Description:** {project_description}
2.  **Pitch Transcript:** {pitch_transcript if pitch_transcript else "Not available"}
3.  **README Content:** {readme_content if readme_content and not readme_content.startswith('Error:') else "Not available"}{commit_info}

**Reference: Previous ETHGlobal Winning Projects**
The following are descriptions of previous winning projects from ETHGlobal hackathons. Use these as reference points when evaluating the current project:

{winning_projects_text[:3000]}  

**Judging Rubric:**
{criteria_str}

**Instructions:**
1.  Provide a score between {rubric['scale'][0]} and {rubric['scale'][1]} for each criterion.
2.  For each criterion, provide a **detailed rationale** (3-5 sentences) explaining *why* the project received that specific score, referencing specific aspects of the project description, transcript, or README where applicable.
3.  Compare the project to previous winning projects where relevant, noting similarities or differences in quality, innovation, or execution.
4.  Provide an overall **feedback** section (a paragraph or bullet points) summarizing the project's strengths and suggesting specific areas for improvement.
5.  Output the results strictly in JSON format with the following structure:
{{
  "scores": {{
    "Criterion Name 1": score_1,
    "Criterion Name 2": score_2,
    ...
  }},
  "rationales": {{
    "Criterion Name 1": "Detailed rationale text 1...",
    "Criterion Name 2": "Detailed rationale text 2...",
    ...
  }},
  "feedback": "Overall feedback text..."
}}

Ensure the keys in "scores" and "rationales" exactly match the criterion names from the rubric: {[c['name'] for c in rubric['criteria']]}. Ensure the "feedback" key is present.

**Special Instructions:**
- If the GitHub repository has only a single commit, this should negatively impact the Technicality score, as it suggests minimal development effort or history.
- Consider how the current project compares to the quality and innovation level of previous winning projects.
- Be particularly attentive to projects that demonstrate novel approaches to blockchain technology or solve real-world problems in unique ways.

**JSON Output:**
"""

    # Check if Claude API key is available
    if not anthropic_api_key:
        print("ERROR: Anthropic API Key not configured.")
        return {"error": "Anthropic API Key not configured."}
    
    try:
        client = Anthropic(api_key=anthropic_api_key)
        response = client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=4000,
            temperature=0.5,
            system="You are an AI Hackathon Judge evaluating projects based on a rubric. Output results in JSON format.",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        # Extract JSON from Claude's response
        result_text = response.content[0].text
        
        # Find JSON in the response (Claude might wrap it in markdown code blocks)
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
        if json_match:
            result_json = json_match.group(1)
        else:
            # If not in code block, try to find JSON object directly
            json_match = re.search(r'({.*})', result_text, re.DOTALL)
            if json_match:
                result_json = json_match.group(1)
            else:
                result_json = result_text  # Use the whole response as a fallback
        
        # Basic validation of the JSON structure
        try:
            parsed_result = json.loads(result_json)
            if "scores" in parsed_result and "rationales" in parsed_result and "feedback" in parsed_result:
                # Further check if keys match rubric criteria names
                expected_keys = {c['name'] for c in rubric['criteria']}
                if set(parsed_result["scores"].keys()) == expected_keys and \
                   set(parsed_result["rationales"].keys()) == expected_keys:
                    return parsed_result
                else:
                    print("Warning: Claude response JSON keys do not match rubric criteria.")
                    # Attempt to return anyway, might need manual correction
                    return parsed_result
            else:
                print("Error: Claude response JSON missing 'scores', 'rationales', or 'feedback' key.")
                return {"error": "Invalid JSON structure from Claude (missing keys)."}
        except json.JSONDecodeError as json_e:
            print(f"Error decoding Claude response JSON: {json_e}")
            print(f"Raw Claude response: {result_text}")
            return {"error": f"Claude returned invalid JSON: {json_e}"}
            
    except Exception as e:
        print(f"Error calling Anthropic API: {e}")
        return {"error": f"API call failed: {e}"}

def get_combined_judgment(project_description, pitch_transcript, readme_content, rubric, repo_url=None):
    """Combines judgments from both OpenAI and Claude models for a more balanced evaluation."""
    
    print("DEBUG: Getting judgment from OpenAI GPT-4o...")
    gpt_result = get_ai_judgment(project_description, pitch_transcript, readme_content, rubric, repo_url)
    
    print("DEBUG: Getting judgment from Anthropic Claude...")
    claude_result = get_claude_judgment(project_description, pitch_transcript, readme_content, rubric, repo_url)
    
    # Check if either model returned an error
    if "error" in gpt_result or "error" in claude_result:
        if "error" in gpt_result and "error" in claude_result:
            return {"error": f"Both models failed: GPT: {gpt_result['error']}, Claude: {claude_result['error']}"}
        elif "error" in gpt_result:
            print(f"WARNING: GPT judgment failed, using Claude only: {gpt_result['error']}")
            return claude_result
        else:
            print(f"WARNING: Claude judgment failed, using GPT only: {claude_result['error']}")
            return gpt_result
    
    # Combine scores by averaging
    combined_scores = {}
    for criterion in rubric['criteria']:
        name = criterion['name']
        gpt_score = gpt_result["scores"].get(name, 0)
        claude_score = claude_result["scores"].get(name, 0)
        
        # Calculate average score
        combined_scores[name] = round((gpt_score + claude_score) / 2, 1)
    
    # Combine rationales
    combined_rationales = {}
    for criterion in rubric['criteria']:
        name = criterion['name']
        gpt_rationale = gpt_result["rationales"].get(name, "")
        claude_rationale = claude_result["rationales"].get(name, "")
        
        # Create a combined rationale that references both models
        combined_rationales[name] = f"Combined assessment: {summarize_rationales(gpt_rationale, claude_rationale)}"
    
    # Combine feedback
    gpt_feedback = gpt_result.get("feedback", "")
    claude_feedback = claude_result.get("feedback", "")
    combined_feedback = f"Combined feedback from multiple AI judges:\n\n{summarize_feedback(gpt_feedback, claude_feedback)}"
    
    # Return combined result
    return {
        "scores": combined_scores,
        "rationales": combined_rationales,
        "feedback": combined_feedback,
        "individual_judgments": {
            "gpt": gpt_result,
            "claude": claude_result
        }
    }

def summarize_rationales(gpt_rationale, claude_rationale):
    """Summarizes two rationales into a concise combined assessment."""
    # This is a simplified approach - in a production system, you might use an LLM to generate a better summary
    
    # Extract key points from each rationale
    gpt_sentences = [s.strip() for s in gpt_rationale.split('.') if s.strip()]
    claude_sentences = [s.strip() for s in claude_rationale.split('.') if s.strip()]
    
    # Take the first 1-2 sentences from each (depending on length)
    gpt_key_points = gpt_sentences[:min(2, len(gpt_sentences))]
    claude_key_points = claude_sentences[:min(2, len(claude_sentences))]
    
    # Combine unique points
    all_points = set(gpt_key_points + claude_key_points)
    
    # Format the combined rationale
    combined = ". ".join(all_points)
    if not combined.endswith('.'):
        combined += '.'
        
    return combined

def summarize_feedback(gpt_feedback, claude_feedback):
    """Combines and summarizes feedback from both models."""
    # Split feedback into bullet points if possible
    gpt_points = [p.strip() for p in gpt_feedback.split('\n') if p.strip()]
    claude_points = [p.strip() for p in claude_feedback.split('\n') if p.strip()]
    
    # Combine unique points
    all_points = set(gpt_points + claude_points)
    
    # Format as bullet points
    return "\n".join([f"• {point}" for point in all_points])

# --- Aggregation Function ---

def calculate_total_score(scores, rubric):
    """Calculates the weighted total score based on individual scores and rubric weights."""
    total_score = 0
    total_weight = sum(c['weight'] for c in rubric['criteria']) # Calculate total weight from passed rubric

    # Handle potential division by zero if total_weight is 0
    if total_weight == 0:
        # Decide how to handle this: return 0 or average score?
        # Let's return average for now if scores exist
        valid_scores = [s for s in scores.values() if isinstance(s, (int, float))]
        return sum(valid_scores) / len(valid_scores) if valid_scores else 0

    for criterion in rubric['criteria']:
        name = criterion['name']
        weight = criterion['weight']
        score = scores.get(name, 0) # Default to 0 if score is missing

        # Ensure score is a number before calculation
        if isinstance(score, (int, float)):
             # Normalize weight relative to the actual total weight used
            normalized_weight = weight / total_weight
            total_score += score * normalized_weight
        else:
            print(f"Warning: Non-numeric score '{score}' found for criterion '{name}'. Treating as 0.")

    # Scale score to be out of 100 (or adjust based on scale if needed)
    # Assuming the score for each criterion is out of 10 (rubric['scale'][1])
    # The weighted average is already on the 1-10 scale.
    # If you want the final score out of 100, multiply by 10.
    # Let's keep it on the 1-10 scale for now, consistent with criteria.
    # return round(total_score * 10, 2) # Example: Scale to 100
    return round(total_score, 2) # Keep on 1-10 scale 

# Add this function to utils.py to check the number of commits in a GitHub repository

def get_github_commit_count(repo_url):
    """
    Fetches the number of commits in a GitHub repository.
    Returns the commit count or None if there was an error.
    """
    if not repo_url or "github.com" not in repo_url:
        print(f"Invalid GitHub URL: {repo_url}")
        return None
    
    try:
        # Parse the owner and repo from the URL
        parts = repo_url.strip('/').split('/')
        if len(parts) < 5 or parts[2] != 'github.com':
            print(f"Invalid GitHub URL format: {repo_url}")
            return None
            
        owner, repo = parts[3], parts[4]
        
        # GitHub API endpoint for commits
        api_url = f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1"
        
        # Make the request with headers to check the total count
        headers = {'Accept': 'application/vnd.github.v3+json'}
        response = requests.get(api_url, headers=headers)
        
        if response.status_code == 200:
            # GitHub returns the total count in the Link header for pagination
            link_header = response.headers.get('Link', '')
            
            if 'rel="last"' in link_header:
                # Extract the page number from the last link
                last_link = [link for link in link_header.split(',') if 'rel="last"' in link][0]
                page_num = last_link.split('page=')[1].split('&')[0].split('>')[0]
                return int(page_num)
            else:
                # If there's no "last" link, count the commits in the response
                commits = response.json()
                return len(commits)
        else:
            print(f"GitHub API error: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"Error fetching GitHub commit count: {e}")
        return None 

def transform_ethglobal_video_url(url):
    """
    Transform ETHGlobal API video URLs to their actual streaming URLs.
    
    Args:
        url (str): The original video URL
        
    Returns:
        str: The transformed URL if it's an ETHGlobal API URL, otherwise the original URL
    """
    # Check if this is an ETHGlobal API URL
    if url and "ethglobal.com/api/projects" in url and "/video" in url:
        try:
            print(f"DEBUG: Attempting to follow redirects for {url}")
            
            # Use a session to maintain cookies and headers
            session = requests.Session()
            
            # Set headers to mimic a browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://ethglobal.com/'
            }
            
            # First make a HEAD request to check redirects without downloading content
            head_response = session.head(url, headers=headers, allow_redirects=True)
            print(f"DEBUG: HEAD request status: {head_response.status_code}, final URL: {head_response.url}")
            
            # If HEAD request doesn't work well, try a GET request
            if head_response.status_code != 200 or head_response.url == url:
                print("DEBUG: HEAD request didn't redirect properly, trying GET request")
                get_response = session.get(url, headers=headers, allow_redirects=True, stream=True)
                
                # Read just a small part of the response to trigger redirects without downloading the whole file
                _ = next(get_response.iter_content(1024), None)
                
                # Close the connection
                get_response.close()
                
                final_url = get_response.url
                print(f"DEBUG: GET request status: {get_response.status_code}, final URL: {final_url}")
            else:
                final_url = head_response.url
            
            # Check if we got a Mux URL or any video URL
            if "stream.mux.com" in final_url or final_url.endswith('.mp4'):
                print(f"DEBUG: Successfully found video URL: {final_url}")
                return final_url
            else:
                print(f"DEBUG: Redirect didn't lead to a video URL: {final_url}")
                
                # Extract project ID from the original URL
                project_id = url.split('/')[-2]  # Format: .../projects/70emz/video
                
                # Try constructing a Mux URL directly using a pattern
                # This is a fallback method based on observed patterns
                mux_url = f"https://stream.mux.com/{project_id}/high.mp4"
                print(f"DEBUG: Attempting fallback Mux URL: {mux_url}")
                
                # Test if this URL works
                test_response = session.head(mux_url)
                if test_response.status_code == 200:
                    print(f"DEBUG: Fallback Mux URL works: {mux_url}")
                    return mux_url
                else:
                    print(f"DEBUG: Fallback Mux URL failed with status {test_response.status_code}")
                    return url
        except Exception as e:
            print(f"DEBUG: Error transforming ETHGlobal video URL: {e}")
            return url
    return url

def scrape_ethglobal_project(url):
    """Scrapes project details from an ETHGlobal showcase URL."""
    try:
        # Extract project ID from URL
        project_id = url.split('/')[-1]
        
        # Make request to the page
        response = requests.get(url)
        if response.status_code != 200:
            return {"error": f"Failed to fetch page: {response.status_code}"}
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract project name
        project_name = soup.find('h1').text.strip()
        
        # Extract project description
        project_desc_elem = soup.find('div', class_='project-description')
        project_description = project_desc_elem.text.strip() if project_desc_elem else "Description not found"
        
        # Get the actual video URL by following the redirect
        video_api_url = f"https://ethglobal.com/api/projects/{project_id}/video"
        try:
            # Make a HEAD request to get the redirect URL without downloading content
            video_response = requests.head(video_api_url, allow_redirects=True)
            if video_response.status_code == 200:
                # Get the final URL after redirects
                video_url = video_response.url
            else:
                video_url = "Video URL Not Found"
        except Exception as e:
            print(f"Error getting video URL: {e}")
            video_url = "Video URL Not Found"
        
        # Find GitHub link
        github_link = "GitHub Link Not Found"
        source_code_link = soup.find('a', text='Source Code')
        if source_code_link:
            github_link = source_code_link['href']
        
        return {
            "name": project_name,
            "description": project_description,
            "video_url": video_url,
            "repo_link": github_link
        }
        
    except Exception as e:
        return {"error": f"Error scraping ETHGlobal project: {e}"}

# --- Blockchain Interaction Functions ---

def distribute_rewards(private_key=None, rpc_url=None, winners_data=None, token_address=None):
    """
    Distributes rewards (native MATIC or ERC20 tokens) to winners on a given network.
    
    Args:
        private_key (str, optional): Private key of the sending wallet. If None, will try to load from environment.
        rpc_url (str, optional): RPC URL for the network. If None, will try to load from environment.
        winners_data (list): A list of dictionaries, e.g., [{'address': '0x...', 'amount': '10.5'}, ...]
                               Amounts should be strings representing the token amount (e.g., "10.5" MATIC or tokens).
        token_address (str, optional): The contract address of the ERC20 token.
                                       If None, native currency (MATIC) is sent. Defaults to None.

    Returns:
        list: A list of dictionaries with results for each transaction,
              e.g., [{'address': '0x...', 'amount': '10.5', 'status': 'success', 'tx_hash': '0x...'},
                     {'address': '0x...', 'amount': '5', 'status': 'error', 'message': 'Reason...'}]
    """
    results = []
    try:
        # Get private key from environment if not provided
        if not private_key:
            private_key = os.getenv("DISTRIBUTOR_PRIVATE_KEY")
            if not private_key:
                raise ValueError("No distributor private key provided or found in environment variables.")
            print("Using distributor private key from environment variables.")
        
        # Get RPC URL from environment if not provided
        if not rpc_url:
            rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
            print(f"Using RPC URL from environment: {rpc_url}")
        
        # Validate winners_data
        if not winners_data or not isinstance(winners_data, list) or len(winners_data) == 0:
            raise ValueError("No valid winners data provided.")
            
        # 1. Connect to the network
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        if not w3.is_connected():
            raise ConnectionError(f"Failed to connect to RPC URL: {rpc_url}")
        print(f"Connected to {rpc_url}, Chain ID: {w3.eth.chain_id}")

        # 2. Load sender account
        sender_account = w3.eth.account.from_key(private_key)
        sender_address = sender_account.address
        print(f"Sender address: {sender_address}")

        # 3. Get sender nonce
        nonce = w3.eth.get_transaction_count(sender_address)
        print(f"Initial nonce: {nonce}")

        # 4. Prepare token contract (if applicable)
        token_contract = None
        token_decimals = 18 # Default for MATIC and many ERC20s
        if token_address:
            token_address = w3.to_checksum_address(token_address)
            # Minimal ERC20 ABI for transfer and decimals
            erc20_abi = [
                {"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"payable":False,"stateMutability":"view","type":"function"},
                {"constant":False,"inputs":[{"name":"_to","type":"address"},{"name":"_value","type":"uint256"}],"name":"transfer","outputs":[{"name":"","type":"bool"}],"payable":False,"stateMutability":"nonpayable","type":"function"}
            ]
            token_contract = w3.eth.contract(address=token_address, abi=erc20_abi)
            try:
                token_decimals = token_contract.functions.decimals().call()
                print(f"Token: {token_address}, Decimals: {token_decimals}")
            except Exception as e:
                 raise ValueError(f"Could not fetch decimals for token {token_address}. Is it a valid ERC20 contract? Error: {e}")

        # 5. Process each winner
        for winner in winners_data:
            recipient_address_str = winner.get('address')
            amount_str = winner.get('amount')
            current_result = winner.copy() # Start building result dict

            try:
                # Validate inputs
                if not recipient_address_str or not amount_str:
                    raise ValueError("Missing address or amount.")
                if not w3.is_address(recipient_address_str):
                     raise ValueError(f"Invalid recipient address: {recipient_address_str}")
                recipient_address = w3.to_checksum_address(recipient_address_str)

                # Convert amount string to Wei (smallest unit)
                try:
                    amount_decimal = Decimal(amount_str)
                    if amount_decimal <= 0:
                        raise ValueError("Amount must be positive.")
                    amount_in_wei = int(amount_decimal * (10**token_decimals))
                except Exception:
                    raise ValueError(f"Invalid amount format: {amount_str}")

                print(f"\nProcessing: To {recipient_address}, Amount: {amount_str} ({amount_in_wei} wei)")

                # Build transaction - using legacy transaction format instead of EIP-1559
                tx_params = {
                    'from': sender_address,
                    'nonce': nonce,
                    'gas': 200000,  # Set a reasonable default gas limit
                    'gasPrice': w3.to_wei('50', 'gwei'),  # Use legacy gasPrice instead of maxFeePerGas/maxPriorityFeePerGas
                    'chainId': w3.eth.chain_id,
                }

                if token_contract:
                    # ERC20 Transfer
                    tx_params['to'] = token_address
                    # Estimate gas for token transfer
                    try:
                         estimated_gas = token_contract.functions.transfer(recipient_address, amount_in_wei).estimate_gas({'from': sender_address})
                         tx_params['gas'] = int(estimated_gas * 1.2) # Add buffer
                         print(f"Estimated Gas (ERC20): {estimated_gas}, Using: {tx_params['gas']}")
                    except Exception as gas_err:
                         print(f"WARN: Gas estimation failed for ERC20 transfer: {gas_err}. Using default limit.")
                         # Keep default gas limit if estimation fails

                    # Build transaction data
                    unsigned_tx = token_contract.functions.transfer(
                        recipient_address,
                        amount_in_wei
                    ).build_transaction(tx_params)

                else:
                    # Native Currency (MATIC) Transfer
                    tx_params['to'] = recipient_address
                    tx_params['value'] = amount_in_wei
                    # Estimate gas for native transfer
                    try:
                        estimated_gas = w3.eth.estimate_gas({'from': sender_address, 'to': recipient_address, 'value': amount_in_wei})
                        tx_params['gas'] = int(estimated_gas * 1.2) # Add buffer
                        print(f"Estimated Gas (Native): {estimated_gas}, Using: {tx_params['gas']}")
                    except Exception as gas_err:
                        print(f"WARN: Gas estimation failed for native transfer: {gas_err}. Using default limit.")
                        # Keep default gas limit if estimation fails

                    unsigned_tx = tx_params # For native transfer, params are the tx

                try:
                    # Sign transaction - handle different web3.py versions
                    signed_tx = w3.eth.account.sign_transaction(unsigned_tx, private_key)
                    
                    # Different versions of web3.py have different attributes for the raw transaction
                    if hasattr(signed_tx, 'rawTransaction'):
                        raw_tx = signed_tx.rawTransaction
                    elif hasattr(signed_tx, 'raw_transaction'):
                        raw_tx = signed_tx.raw_transaction
                    else:
                        # Try accessing as dictionary
                        raw_tx = signed_tx.get('rawTransaction') or signed_tx.get('raw_transaction')
                        if not raw_tx:
                            raise AttributeError("Could not find raw transaction data in signed transaction object")
                    
                    # Send transaction
                    tx_hash = w3.eth.send_raw_transaction(raw_tx)
                    print(f"Transaction sent: {tx_hash.hex()}")
                    
                except Exception as tx_error:
                    print(f"Transaction error details: {tx_error}")
                    print(f"Signed transaction object: {dir(signed_tx)}")  # Print available attributes for debugging
                    raise

                current_result['status'] = 'success'
                current_result['tx_hash'] = tx_hash.hex()
                nonce += 1 # Increment nonce for the next transaction

            except Exception as e:
                print(f"ERROR processing {winner}: {e}")
                current_result['status'] = 'error'
                current_result['message'] = str(e)

            results.append(current_result)

    except Exception as e:
        print(f"FATAL ERROR during reward distribution setup: {e}")
        # Add a general error result if setup fails
        results.append({'status': 'error', 'message': f"Setup failed: {e}"})

    return results 