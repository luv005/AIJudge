import os
import tempfile
import requests
import shutil # For cleaning up temporary directories
from moviepy.editor import VideoFileClip
from openai import OpenAI
from dotenv import load_dotenv, find_dotenv
import json
import yt_dlp # Import the downloader library

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
        {"name": "Innovation & Originality", "weight": 30, "description": "How novel or creative the project idea is."},
        {"name": "Technical Implementation", "weight": 30, "description": "The complexity and quality of the engineering (skillful use of tech, solid code, etc.)."},
        {"name": "Impact & Usefulness", "weight": 20, "description": "Potential impact, usefulness, or value of the solution."},
        {"name": "Presentation & Communication", "weight": 20, "description": "Clarity and effectiveness of the demo and pitch in conveying the idea."}
    ],
    "scale": (1, 10) # Min and Max score for each criterion
}

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
    criteria_str = "\n".join([
        f"- {c['name']} (Weight: {c['weight']}%, Scale: {rubric['scale'][0]}-{rubric['scale'][1]}): {c['description']}"
        for c in rubric['criteria']
    ])

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

Ensure the keys in "scores" and "rationales" exactly match the criterion names from the rubric: {[c['name'] for c in rubric['criteria']]}. Ensure the "feedback" key is present.

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
    """Calculates the weighted total score."""
    total_score = 0
    total_weight = sum(c['weight'] for c in rubric['criteria'])
    if total_weight == 0: return 0 # Avoid division by zero

    for criterion in rubric['criteria']:
        name = criterion['name']
        weight = criterion['weight']
        score = scores.get(name, 0) # Default to 0 if score is missing
        total_score += score * weight

    # Normalize to 100 if weights don't sum to 100, or scale appropriately
    # Assuming weights are percentages summing to 100 based on example
    # If scale is 1-10, max possible weighted score is 10 * total_weight
    # Normalize to a 0-100 scale
    max_possible_score = rubric['scale'][1] * total_weight
    if max_possible_score == 0: return 0

    normalized_score = (total_score / max_possible_score) * 100
    return round(normalized_score, 2) # Return score rounded to 2 decimal places 