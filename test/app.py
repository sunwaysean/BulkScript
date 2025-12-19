from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp
import whisper
import os
import re 
from hub import analyze_text, estimate_token_count, MODEL_PATH 
from llama_cpp import Llama
import gc
from pydub import AudioSegment
import time

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["http://localhost:3000", "http://127.0.0.1:3000"]}}, supports_credentials=True)

# Load Whisper model
print("Loading Whisper base model...")
model = whisper.load_model("base")
print("Whisper model loaded.")

# ------------------------------

# Helpers
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
    import re
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
# ------------------------------

def calculate_quality_score(summary, transcript):
    """
    Calculate quality score (1-5) for how well the summary captures the transcript.
    Uses the global LLM instance with detailed evaluation.
    """
    if not summary or not summary.strip():
        return 3  
    
    try:
        from hub import evaluate_analysis
        eval_result = evaluate_analysis(transcript, summary)
        # Return insight score as overall quality
        return eval_result.get("insight", 3)
    except Exception as e:
        print(f"Quality evaluation failed: {e}")
        return 3  # Default to average

def chunk_text(text, max_length=3000):
    """Split text into smaller chunks (for LLM analysis)."""
    chunks = []
    while len(text) > max_length:
        split_index = text.rfind(" ", 0, max_length)
        if split_index == -1: 
            split_index = max_length
        chunks.append(text[:split_index])
        text = text[split_index:].lstrip() 
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
    print(f"Transcribing {file_path} with Whisper...")
    result = model.transcribe(file_path)
    print("Transcription complete.")
    return result["text"]
    


# ------------------------------
# ROUTE: Get transcripts for multiple videos
# ------------------------------
@app.route("/transcripts", methods=["POST"])
def get_transcripts():
    start_time = time.time()
    data = request.get_json()
    urls = data.get("urls", [])

    if not urls or not isinstance(urls, list):
        return jsonify({"error": "Missing or invalid URLs"}), 400

    results = []
    temp_audio_path = "temp_audio.wav"
    
    # --- NEW PLAYLIST EXPANSION LOGIC ---
    expanded_urls = []
    playlist_ydl_opts = {
        'extract_flat': True,  
        'noplaylist': False, 
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
                    results.append({"url": url, "error": f"Failed to expand playlist: {str(e)}"})
            else:
                expanded_urls.append(url)
    
    print(f"Total videos to process after expansion: {len(expanded_urls)}")
    # --- END OF NEW LOGIC ---

    for url in expanded_urls:
        print(f"🟦 Processing {url}...")
        video_id = extract_video_id(url)
        title = None
        transcript_text = None
        source = "YouTubeAPI"

        if not video_id:
            results.append({"url": url, "error": "Could not parse YouTube video ID"})
            continue

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
                    "outtmpl": "temp_audio.%(ext)s",
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
    
    # Calculate metrics
    end_time = time.time()
    latency = end_time - start_time
    total_tokens = sum(estimate_token_count(r.get("transcript", "")) for r in results if "transcript" in r)
    throughput = total_tokens / latency if latency > 0 else 0
    
    metrics = {
        "latency_seconds": round(latency, 2),
        "total_tokens": total_tokens,
        "throughput_tokens_per_second": round(throughput, 2)
    }
    
    print(f"📊 Metrics: {metrics}")
    
    return jsonify({
        "results": results,
        "metrics": metrics
    })


# ------------------------------
# ROUTE: Analyze a single transcript
# ------------------------------
@app.route("/analyze", methods=["POST"])
def analyze_transcript():
    start_time = time.time()
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
            
            # Calculate quality score
            quality_score = calculate_quality_score(final_summary, chunks[0])
            
            # Calculate metrics
            end_time = time.time()
            latency = end_time - start_time
            prompt_tokens = estimate_token_count(instruction)
            output_tokens = estimate_token_count(final_summary)
            total_tokens = prompt_tokens + output_tokens
            throughput = total_tokens / latency if latency > 0 else 0
            
            metrics = {
                "latency_seconds": round(latency, 2),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": total_tokens,
                "throughput_tokens_per_second": round(throughput, 2),
                "quality_score": quality_score
            }
            
            print(f"📊 Analysis Metrics: {metrics}")
            
            return jsonify({
                "chunks_analyzed": 1,
                "partial_summaries": [],
                "final_analysis": final_summary,
                "metrics": metrics
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

        # Calculate quality score using original transcript
        full_transcript = " ".join(chunks)
        quality_score = calculate_quality_score(final_summary, full_transcript)

        # Calculate metrics
        end_time = time.time()
        latency = end_time - start_time
        prompt_tokens = estimate_token_count(instruction)
        summary_tokens = sum(estimate_token_count(s) for s in summaries)
        output_tokens = estimate_token_count(final_summary)
        total_tokens = prompt_tokens + summary_tokens + output_tokens
        throughput = total_tokens / latency if latency > 0 else 0
        
        metrics = {
            "latency_seconds": round(latency, 2),
            "prompt_tokens": prompt_tokens,
            "partial_summary_tokens": summary_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": total_tokens,
            "throughput_tokens_per_second": round(throughput, 2),
            "quality_score": quality_score
        }
        
        print(f"📊 Multi-chunk Analysis Metrics: {metrics}")

        return jsonify({
            "chunks_analyzed": len(chunks),
            "partial_summaries": summaries,
            "final_analysis": final_summary,
            "metrics": metrics
        })

    except Exception as e:
        print(f"❌ Analysis failed: {str(e)}")
        end_time = time.time()
        latency = end_time - start_time
        return jsonify({
            "error": f"Failed to analyze transcript: {str(e)}",
            "latency_seconds": round(latency, 2)
        }), 500


@app.route("/analyze_with_config", methods=["POST"])
def analyze_with_config():
    """
    Analyze a transcript using an ephemeral Llama instance created with provided config.
    Request JSON: { transcript: str, prompt?: str, config?: { n_ctx, n_batch, n_threads, n_gpu_layers }, max_tokens?: int }
    """
    start_time = time.time()
    data = request.get_json()
    transcript = data.get("transcript")
    instruction = data.get(
        "prompt",
        "Summarize the main ideas, arguments, and tone clearly and factually."
    )
    cfg = data.get("config", {}) or {}
    max_tokens = int(data.get("max_tokens", 300))

    if not transcript:
        return jsonify({"error": "Missing transcript"}), 400

    # Build Llama params with sensible defaults
    llm_params = {
        "model_path": MODEL_PATH,
        "n_ctx": int(cfg.get("n_ctx", 8192)),
        "n_batch": int(cfg.get("n_batch", 128)),
        "n_threads": int(cfg.get("n_threads", 6)),
        "n_gpu_layers": int(cfg.get("n_gpu_layers", 30)),
        "use_mlock": True,
        "verbose": False,
    }

    try:
        print(f"Creating ephemeral Llama with params: {llm_params}")
        local_llm = Llama(**llm_params)
        prompt = f"{instruction}\n\nTranscript:\n{transcript}\n\nProvide a clear, structured analysis:"
        t0 = time.time()
        resp = local_llm.create_completion(
            prompt=prompt,
            temperature=0.5,
            max_tokens=max_tokens,
            top_p=0.9,
        )
        elapsed = time.time() - t0

        # extract text
        try:
            text = resp["choices"][0]["text"]
        except Exception:
            text = str(resp)

        # metrics
        prompt_tokens = estimate_token_count(instruction)
        output_tokens = estimate_token_count(text)
        total_tokens = prompt_tokens + output_tokens
        throughput = total_tokens / elapsed if elapsed > 0 else 0

        # LLM-based quality rating (1-5 scale) - now using detailed evaluation
        from hub import evaluate_analysis
        quality_score = 3  # Default fallback
        try:
            eval_result = evaluate_analysis(transcript, text)
            # Use insight score as overall quality_score for backward compatibility
            quality_score = eval_result.get("insight", 3)
            print(f"Detailed evaluation: {eval_result}")
        except Exception as e:
            print(f"Quality evaluation failed: {e}")
            quality_score = 3

        # LLM-based quality rating (1-5 scale) - now using detailed evaluation
        from hub import evaluate_analysis
        quality_score = 3  # Default fallback
        eval_result = None
        try:
            eval_result = evaluate_analysis(transcript, text)
            # Use insight score as overall quality_score for backward compatibility
            quality_score = eval_result.get("insight", 3)
            print(f"Detailed evaluation: {eval_result}")
        except Exception as e:
            print(f"Quality evaluation failed: {e}")
            quality_score = 3

        metrics = {
            "latency_seconds": round(elapsed, 2),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": total_tokens,
            "throughput_tokens_per_second": round(throughput, 2),
            "quality_score": quality_score,
            "evaluation": eval_result  
        }

        return jsonify({
            "final_analysis": text,
            "metrics": metrics,
            "config_used": llm_params,
        })

    except Exception as e:
        print(f"❌ Ephemeral analysis failed: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            del local_llm
        except Exception:
            pass
        gc.collect()


# ------------------------------
# Run app
# ------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5001)