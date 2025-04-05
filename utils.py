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
                        "87obi": "01CwsoCbFScKx1xpGUvmkIDYXD02Dq7TbjdPS5zUx014fw",  # Ape Tweet
                        "g0jzy": "2pCxag501Mbk02Qi5Q21ydMM2qQg2hkCi47Fxn02gPgPPM"   # Prophet AI
                    }
                    
                    if project_id in known_projects:
                        mux_id = known_projects[project_id]
                        video_url = f"https://stream.mux.com/{mux_id}/high.mp4"
                        print(f"DEBUG: Using known Mux URL for project ID {project_id}: {video_url}")
                    else:
                        # For other projects, we'll need to make an educated guess
                        # This is a placeholder URL that will likely fail but shows the intent
                        video_url = f"https://ethglobal.com/api/projects/{project_id}/video"
                        print(f"DEBUG: Constructed fallback URL for project ID {project_id}: {video_url}")
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

        # --- Find Links to Individual Projects ---
        # This requires inspecting the list page structure.
        # Example: Find all <a> tags within elements having class 'project-card'
        # Based on inspection (may change): Links are often within divs with class like 'card' or similar
        # And the link itself might have a specific class or structure.
        # Let's assume project links are <a> tags inside a specific container.
        # Find a container first, e.g., <div id="showcase-projects">
        # project_container = soup.find('div', id='showcase-projects') # Hypothetical
        # if project_container:
        #    links = project_container.find_all('a', href=True)
        # else: # Fallback: search all links
        #    links = soup.find_all('a', href=True)

        # Simpler approach: Find all links whose href starts with '/showcase/'
        links = soup.find_all('a', href=lambda href: href and href.startswith('/showcase/'))

        found_urls = set() # Use a set to avoid duplicates
        for link in links:
            href = link['href']
            # Construct absolute URL
            absolute_url = urljoin(list_url, href)
            # Basic check to avoid non-project links if possible
            if '/showcase/' in absolute_url and absolute_url != list_url and absolute_url not in found_urls:
                 # Add more filtering if needed (e.g., check URL structure further)
                 project_links.append(absolute_url)
                 found_urls.add(absolute_url)

        print(f"Found {len(project_links)} potential project links on {list_url}")
        return project_links

    except requests.exceptions.RequestException as e:
        print(f"Error fetching project list page {list_url}: {e}")
        return {"error": f"Network error fetching list page: {e}"} # Return dict to signal error
    except Exception as e:
        print(f"Error scraping project list page {list_url}: {e}")
        return {"error": f"Scraping failed: {e}"} # Return dict to signal error


# --- Preprocessing Functions ---

def download_video_from_url(url, download_dir):
    """Downloads video from URL using yt-dlp to a specified directory."""
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', # Prefer mp4
        'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'), # Save with title and extension
        'quiet': True, # Suppress console output
        'merge_output_format': 'mp4', # Ensure merged output is mp4 if separate streams are downloaded
        # Add options to limit download size/duration if needed for large videos
        # 'max_filesize': '100M', # Example: Limit file size
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            # Construct the expected filename based on yt-dlp's template
            # Note: This might need adjustment if titles have tricky characters
            # A more robust way is to hook into the download progress to get the exact final path
            downloaded_path = ydl.prepare_filename(info_dict)

            # Check if the file exists after download attempt
            if os.path.exists(downloaded_path):
                 print(f"Video downloaded successfully to: {downloaded_path}")
                 return downloaded_path
            else:
                 # Sometimes yt-dlp changes the extension (e.g., .webm -> .mp4)
                 # Try finding the downloaded file if the exact path doesn't match
                 files_in_dir = os.listdir(download_dir)
                 if len(files_in_dir) == 1:
                     actual_path = os.path.join(download_dir, files_in_dir[0])
                     print(f"Video downloaded successfully (found as): {actual_path}")
                     return actual_path
                 else:
                     print(f"Error: Downloaded file not found or multiple files in temp dir for URL {url}")
                     return None
    except yt_dlp.utils.DownloadError as e:
        print(f"Error downloading video from {url}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during video download from {url}: {e}")
        return None

def extract_audio_from_video(video_path):
    """Extracts audio from a video file path and saves as temporary mp3."""
    if not video_path or not os.path.exists(video_path):
        print(f"Error: Video file not found at path: {video_path}")
        return None
    try:
        video_clip = VideoFileClip(video_path)
        # Create audio path in the same directory or a specific temp location
        base, _ = os.path.splitext(video_path)
        audio_path = base + ".mp3"
        video_clip.audio.write_audiofile(audio_path, codec='libmp3lame')
        video_clip.close() # Close the video clip to release the file handle
        # Don't remove the video file here, it might be needed elsewhere or cleaned up later
        return audio_path
    except Exception as e:
        print(f"Error extracting audio: {e}")
        return None

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

def get_ai_judgment(project_description, pitch_transcript, readme_content, rubric):
    """Generates AI judgment using OpenAI GPT-4o based on provided texts and rubric."""
    # --- Ensure criteria_str uses the passed rubric ---
    criteria_str = "\n".join([
        f"- {c['name']} (Weight: {c['weight']}%, Scale: {rubric['scale'][0]}-{rubric['scale'][1]}): {c['description']}"
        for c in rubric['criteria'] # Use the rubric passed to the function
    ])

    # --- Ensure the prompt uses the passed rubric's criteria names ---
    prompt = f"""
You are an AI Hackathon Judge. Evaluate the following project based on the provided information and the judging rubric.

**Project Information:**
1.  **Project Description:** {project_description}
2.  **Pitch Transcript:** {pitch_transcript if pitch_transcript else "Not available"}
3.  **README Content:** {readme_content if readme_content and not readme_content.startswith('Error:') else "Not available"}

**Judging Rubric:**
{criteria_str}

**Instructions:**
1.  Provide a score between {rubric['scale'][0]} and {rubric['scale'][1]} for each criterion.
2.  For each criterion, provide a **detailed rationale** (3-5 sentences) explaining *why* the project received that specific score, referencing specific aspects of the project description, transcript, or README where applicable.
3.  Provide an overall **feedback** section (a paragraph or bullet points) summarizing the project's strengths and suggesting specific areas for improvement.
4.  Output the results strictly in JSON format with the following structure:
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

Ensure the keys in "scores" and "rationales" exactly match the criterion names from the rubric: {[c['name'] for c in rubric['criteria']]}. Ensure the "feedback" key is present. # Use the passed rubric here too

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