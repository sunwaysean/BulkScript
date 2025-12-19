from llama_cpp import Llama
import textwrap
import os

MODEL_PATH = "./models/llm/Mistral-7B-Instruct-v0.3-Q6_K.gguf"

print(f"🔥 DEBUG: Loading LLM from: {MODEL_PATH}")

if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"❌ Model not found at: {MODEL_PATH}")

print(f"✅ Loading Mistral model from {MODEL_PATH}...")

# Optimized settings for Apple M3 (Metal backend)
llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=8192,          # increased context window (safe for 16GB RAM)
    n_batch=128,         # reduce batch size slightly to save memory
    n_threads=6,         # balanced for M3 performance cores
    n_gpu_layers=30,     # main layers offloaded to Metal GPU
    use_mlock=True,      # prevent swapping
    verbose=False
)

def estimate_token_count(text):
    """
    Estimate token count using simple word-based approximation.
    Typically: 1 token ≈ 0.75 words (for English text with Mistral tokenizer)
    """
    if not text:
        return 0
    words = len(text.split())
    # Conservative estimate: 1 token ≈ 1.3 characters on average for Mistral
    estimated_tokens = max(1, int(words * 1.3))
    return estimated_tokens

def analyze_text(prompt, text):
    """
    Generate structured analysis using Mistral.
    """
    # truncate text safely
    text = textwrap.shorten(text, width=16000, placeholder="...")

    try:
        response = llm.create_completion(
            prompt=f"{prompt}\n\nTranscript:\n{text}\n\nProvide a clear, structured analysis:",
            temperature=0.5,
            max_tokens=600,
            top_p=0.9,
            stop=["User:", "Assistant:"]
        )
        return response["choices"][0]["text"].strip()
    except Exception as e:
        print("❌ Error in analyze_text():", e)
        return f"⚠️ Analysis failed: {e}"

def evaluate_analysis(transcript, analysis):
    """
    Evaluate analysis quality using Mistral's JSON mode.
    Rates Groundedness, Conciseness, and Insight on 1-5 scale.
    Returns JSON object with scores and reason.
    """
    prompt = f"""Evaluate this analysis of a transcript. Rate on three criteria (1-5 scale):

Groundedness: How well does the analysis stay grounded in the transcript content?
Conciseness: How concise and to-the-point is the analysis?
Insight: How insightful and valuable are the conclusions?

Transcript excerpt: {transcript[:800]}

Analysis: {analysis[:600]}

Respond ONLY with a JSON object in this exact format:
{{
  "groundedness": 3,
  "conciseness": 3, 
  "insight": 3,
  "reason": "Brief explanation of scores"
}}"""

    try:
        response = llm.create_completion(
            prompt=prompt,
            temperature=0.3,
            max_tokens=150,
            top_p=0.9,
            stop=["User:", "Assistant:"]
        )
        result_text = response["choices"][0]["text"].strip()
        
        # Try to parse as JSON
        import json
        try:
            result = json.loads(result_text)
            # Validate required fields
            required = ["groundedness", "conciseness", "insight", "reason"]
            if all(k in result for k in required):
                # Ensure scores are 1-5
                for key in ["groundedness", "conciseness", "insight"]:
                    if key in result:
                        result[key] = max(1, min(5, int(result[key])))
                return result
        except json.JSONDecodeError:
            pass
        
        # Fallback if JSON parsing fails
        return {
            "groundedness": 3,
            "conciseness": 3,
            "insight": 3,
            "reason": "Evaluation failed, using defaults"
        }
        
    except Exception as e:
        print(f"❌ Error in evaluate_analysis(): {e}")
        return {
            "groundedness": 3,
            "conciseness": 3,
            "insight": 3,
            "reason": f"Error: {str(e)}"
        }
