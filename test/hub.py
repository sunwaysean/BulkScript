from llama_cpp import Llama
import textwrap
import os

# ✅ Path to the Mistral model
MODEL_PATH = "./models/llm/Mistral-7B-Instruct-v0.3-Q6_K.gguf"

print(f"🔥 DEBUG: Loading LLM from: {MODEL_PATH}")

if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"❌ Model not found at: {MODEL_PATH}")

print(f"✅ Loading Mistral model from {MODEL_PATH}...")

# ⚙️ Optimized settings for Apple M3 (Metal backend)
llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=8192,          # increased context window (safe for 16GB RAM)
    n_batch=128,         # reduce batch size slightly to save memory
    n_threads=6,         # balanced for M3 performance cores
    n_gpu_layers=30,     # main layers offloaded to Metal GPU
    use_mlock=True,      # prevent swapping
    verbose=False
)

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
