from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp
import whisper
import os
import re # Added for better video ID extraction
from hub import analyze_text # Make sure you have this file
from pydub import AudioSegment

app = Flask(__name__)
CORS(app)

# Load Whisper model
# Consider using a smaller model if speed is an issue, or larger if accuracy is key
print("Loading Whisper base model...")
model = whisper.load_model("base")
print("Whisper model loaded.")

# ------------------------------
# Helpers
# ------------------------------

def extract_video_id(url):
    """
    Extracts the YouTube video ID from various URL formats.
    """
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/v\/([a-zA-Z0-9_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
            
    # Fallback for simple v= links
    if "v=" in url:
        video_id = url.split("v=")[-1].split("&")[0]
        if len(video_id) == 11:
            return video_id
            
    return None

def chunk_text(text, max_length=3000):
    """Split text into smaller chunks (for LLM analysis)."""
    # This is a simplified chunker, you might want to split on sentences.
    chunks = []
    while len(text) > max_length:
        split_index = text.rfind(" ", 0, max_length)
        if split_index == -1: # No spaces, hard cut
            split_index = max_length
        chunks.append(text[:split_index])
        text = text[split_index:].lstrip() # Remove leading space
    chunks.append(text)
    return chunks

def split_audio(file_path, chunk_length_ms=60_000):
    """Split long audio for Whisper."""
    print(f"Splitting audio file: {file_path}")
    audio = AudioSegment.from_file(file_path)
    chunks = []
    for i, start_ms in enumerate(range(0, len(audio), chunk_length_ms)):
        chunk_file = f"temp_chunk_{i}.wav"
        audio[start_ms : start_ms + chunk_length_ms].export(chunk_file, format="wav")
        chunks.append(chunk_file)
    print(f"Split into {len(chunks)} chunks.")
    return chunks

def transcribe_whisper(file_path):
    """Transcribe audio in chunks using Whisper."""
    # Note: Whisper can handle long files, but chunking can be more robust
    # for very long audio or lower memory.
    # Simple method:
    print(f"Transcribing {file_path} with Whisper...")
    result = model.transcribe(file_path)
    print("Transcription complete.")
    return result["text"]
    
    # Your chunking method (can be slower but safer for memory):
    # chunk_files = split_audio(file_path, chunk_length_ms=10 * 60 * 1000) # 10 min chunks
    # transcripts = []
    # for chunk_file in chunk_files:
    #     try:
    #         result = model.transcribe(chunk_file)
    #         transcripts.append(result["text"])
    #     except Exception as e:
    #         print(f"❌ Failed on chunk {chunk_file}:", e)
    #     finally:
    #         if os.path.exists(chunk_file):
    #             os.remove(chunk_file)
    # return " ".join(transcripts)


# ------------------------------
# ROUTE: Get transcripts for multiple videos
# ------------------------------
@app.route("/transcripts", methods=["POST"])
def get_transcripts():
    data = request.get_json()
    urls = data.get("urls", [])

    if not urls or not isinstance(urls, list):
        return jsonify({"error": "Missing or invalid URLs"}), 400

    results = []
    temp_audio_path = "temp_audio.wav"
    
    # --- NEW PLAYLIST EXPANSION LOGIC ---
    expanded_urls = []
    playlist_ydl_opts = {
        'extract_flat': True,  # Get playlist metadata, not all video info
        'noplaylist': False, # We WANT to process playlists here
        'quiet': True,
    }

    print("Expanding URLs... (Checking for playlists)")
    with yt_dlp.YoutubeDL(playlist_ydl_opts) as ydl:
        for url in urls:
            if "list=" in url:
                try:
                    print(f"Expanding playlist: {url}")
                    info = ydl.extract_info(url, download=False)
                    if 'entries' in info:
                        for entry in info['entries']:
                            if entry and entry.get('id'):
                                video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                                expanded_urls.append(video_url)
                        print(f"Added {len(info['entries'])} videos from playlist.")
                except Exception as e:
                    print(f"Could not expand playlist {url}: {e}")
                    # Optionally add an error, or just skip it
                    results.append({"url": url, "error": f"Failed to expand playlist: {str(e)}"})
            else:
                # It's just a regular video URL
                expanded_urls.append(url)
    
    print(f"Total videos to process after expansion: {len(expanded_urls)}")
    # --- END OF NEW LOGIC ---

    # NOW, iterate over the EXPANDED list
    for url in expanded_urls:
        print(f"🟦 Processing {url}...")
        video_id = extract_video_id(url)
        title = None
        transcript_text = None
        source = "YouTubeAPI"

        if not video_id:
            results.append({"url": url, "error": "Could not parse YouTube video ID"})
            continue

        # Try YouTubeTranscriptApi
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
            transcript_text = " ".join([t["text"] for t in transcript_list])
            print("✅ Got transcript from YouTubeTranscriptApi")
        except Exception:
            print("ℹ️ No API transcript found. Falling back to Whisper...")
            # Fallback: download + transcribe with Whisper
            try:
                ydl_opts = {
                    "format": "bestaudio/best",
                    "outtmpl": "temp_audio.%(ext)s", # Use a consistent name
                    "noplaylist": True,
                    "quiet": True,
                    "postprocessors": [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'wav',
                        'preferredquality': '192',
                    }],
                }
                
                # Clean up old temp files if they exist
                if os.path.exists(temp_audio_path):
                    os.remove(temp_audio_path)
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    # ffmpeg post-processor should have created 'temp_audio.wav'
                    filename = "temp_audio.wav"
                    if not os.path.exists(filename):
                         # Fallback if post-processor failed
                         original_filename = ydl.prepare_filename(info)
                         print(f"Converting {original_filename} to wav...")
                         AudioSegment.from_file(original_filename).export(filename, format="wav")
                         os.remove(original_filename)
                         
                    title = info.get("title", "Untitled")
                
                transcript_text = transcribe_whisper(filename)
                source = "WhisperASR"
                print("✅ Got transcript from Whisper")

            except Exception as e:
                print(f"❌ Transcription failed for {url}: {str(e)}")
                results.append({
                    "url": url,
                    "error": f"Transcription failed: {str(e)}"
                })
                continue
            finally:
                # Clean up wav file
                if os.path.exists(temp_audio_path):
                    os.remove(temp_audio_path)

        results.append({
            "url": url,
            "title": title or f"Video ({video_id})",
            "source": source,
            "transcript": transcript_text
        })

    print("Finished processing all URLs.")
    return jsonify(results)


# ------------------------------
# ROUTE: Analyze a single transcript
# ------------------------------
@app.route("/analyze", methods=["POST"])
def analyze_transcript():
    data = request.get_json()
    transcript = data.get("transcript")
    instruction = data.get(
        "prompt",
        "Summarize the main ideas, arguments, and tone clearly and factually."
    )

    if not transcript:
        return jsonify({"error": "Missing transcript"}), 400

    try:
        chunks = chunk_text(transcript, max_length=4000)
        summaries = []

        # If only one chunk, just analyze it directly
        if len(chunks) == 1:
            print("Analyzing single chunk...")
            final_summary = analyze_text(instruction, chunks[0])
            return jsonify({
                "chunks_analyzed": 1,
                "partial_summaries": [],
                "final_analysis": final_summary
            })

        # Process multiple chunks
        for i, chunk in enumerate(chunks, start=1):
            print(f"Analyzing chunk {i}/{len(chunks)}...")
            # Modify prompt to be aware of chunks
            chunk_prompt = f"This is part {i} of {len(chunks)}. Summarize this part based on the instruction: {instruction}"
            chunk_summary = analyze_text(chunk_prompt, chunk)
            summaries.append(chunk_summary)

        print("Combining summaries...")
        combined_text = "\n\n".join(summaries)
        final_summary = analyze_text(
            f"Combine the following partial summaries into a final, cohesive analysis that fulfills this instruction: {instruction}",
            combined_text
        )

        return jsonify({
            "chunks_analyzed": len(chunks),
            "partial_summaries": summaries,
            "final_analysis": final_summary
        })

    except Exception as e:
        print(f"❌ Analysis failed: {str(e)}")
        return jsonify({"error": f"Failed to analyze transcript: {str(e)}"}), 500


# ------------------------------
# Run app
# ------------------------------
if __name__ == "__main__":
    # Runs on http://127.0.0.1:5000 by default
    app.run(debug=True)