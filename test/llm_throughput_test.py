"""
LLM throughput test script
Runs the Mistral model with 3 different initialization parameter sets and measures average tokens/sec

WARNING: Loading the model multiple times will be slow and memory-intensive. Run this on a machine with sufficient RAM.
"""
import time
import textwrap
from llama_cpp import Llama
import os

MODEL_PATH = "./models/llm/Mistral-7B-Instruct-v0.3-Q6_K.gguf"
if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"Model not found at {MODEL_PATH}")

PROMPT = "Provide a concise structured summary and action items for the transcript below."
TRANSCRIPT = "\n".join(["This is a sample sentence to simulate transcript content." for _ in range(200)])

# Simple token estimator (same approach as hub.py)
def estimate_token_count(text):
    if not text:
        return 0
    words = len(text.split())
    estimated_tokens = max(1, int(words * 1.3))
    return estimated_tokens

configs = [
    {
        "name": "config_low_threads",
        "n_ctx": 8192,
        "n_batch": 64,
        "n_threads": 2,
        "n_gpu_layers": 20
    },
    {
        "name": "config_mid",
        "n_ctx": 8192,
        "n_batch": 128,
        "n_threads": 6,
        "n_gpu_layers": 30
    },
    {
        "name": "config_high_threads",
        "n_ctx": 8192,
        "n_batch": 256,
        "n_threads": 12,
        "n_gpu_layers": 40
    }
]

# Use more iterations for statistical confidence and a fixed max token target
ITERATIONS = 5
MAX_TOKENS = 300

results = []

for cfg in configs:
    print(f"\n=== Testing {cfg['name']} ===")
    print(f"Params: n_threads={cfg['n_threads']} n_batch={cfg['n_batch']} n_gpu_layers={cfg['n_gpu_layers']}")
    print("Loading model (this may take a while)...")
    start_load = time.time()
    llm = Llama(
        model_path=MODEL_PATH,
        n_ctx=cfg["n_ctx"],
        n_batch=cfg["n_batch"],
        n_threads=cfg["n_threads"],
        n_gpu_layers=cfg["n_gpu_layers"],
        use_mlock=True,
        verbose=False
    )
    load_time = time.time() - start_load
    print(f"Model loaded in {load_time:.1f}s")

    import gc
    import statistics

    per_iter_times = []
    per_iter_est_tokens = []

    # Warmup (single short call)
    try:
        _ = llm.create_completion(
            prompt=(PROMPT + "\n\nTranscript:\n" + textwrap.shorten(TRANSCRIPT, width=4000)),
            temperature=0.5,
            max_tokens=64,
            top_p=0.9,
        )
    except Exception as e:
        print("Warmup failed:", e)

    for i in range(ITERATIONS):
        print(f"Iteration {i+1}/{ITERATIONS}...", end=" ")
        t0 = time.time()
        try:
            resp = llm.create_completion(
                prompt=(PROMPT + "\n\nTranscript:\n" + textwrap.shorten(TRANSCRIPT, width=4000)),
                temperature=0.5,
                max_tokens=MAX_TOKENS,
                top_p=0.9,
            )
            elapsed = time.time() - t0
            # try to extract text
            text = ""
            try:
                text = resp["choices"][0]["text"]
            except Exception:
                text = str(resp)

            est_tokens = estimate_token_count(text)
            per_iter_times.append(elapsed)
            per_iter_est_tokens.append(est_tokens)
            print(f"done in {elapsed:.2f}s (est tokens={est_tokens})")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"error after {elapsed:.2f}s:", e)

    # Compute statistics. report both estimated tokens/sec (based on actual output)
    # and requested-tokens/sec (based on MAX_TOKENS target) for consistency.
    total_time = sum(per_iter_times)
    total_est_tokens = sum(per_iter_est_tokens)
    avg_time = statistics.mean(per_iter_times) if per_iter_times else 0
    sd_time = statistics.stdev(per_iter_times) if len(per_iter_times) > 1 else 0
    est_tokens_per_sec = total_est_tokens / total_time if total_time > 0 else 0
    requested_tokens_per_sec = (MAX_TOKENS * len(per_iter_times)) / total_time if total_time > 0 else 0

    results.append({
        "config": cfg["name"],
        "params": {"n_threads": cfg["n_threads"], "n_batch": cfg["n_batch"], "n_gpu_layers": cfg["n_gpu_layers"]},
        "load_time_s": load_time,
        "avg_call_s": avg_time,
        "sd_call_s": sd_time,
        "iterations": len(per_iter_times),
        "total_estimated_tokens": total_est_tokens,
        "estimated_tokens_per_sec": est_tokens_per_sec,
        "requested_tokens_per_sec": requested_tokens_per_sec,
        "per_iteration_s": per_iter_times,
        "per_iteration_est_tokens": per_iter_est_tokens
    })

    # try to free memory (delete llm and collect)
    try:
        del llm
        gc.collect()
        time.sleep(1.0)
    except Exception:
        pass

print("\n=== Summary ===")
for r in results:
    print(f"{r['config']}: load {r['load_time_s']:.1f}s avg_call {r['avg_call_s']:.2f}s est_tokens/sec {r['estimated_tokens_per_sec']:.1f} requested_tokens/sec {r['requested_tokens_per_sec']:.1f}")

# Save results to file in the current test directory
import json
OUT_PATH = 'llm_throughput_results.json'
with open(OUT_PATH, 'w') as f:
    json.dump({"meta": {"iterations": ITERATIONS, "max_tokens": MAX_TOKENS}, "results": results}, f, indent=2)

print(f'\nResults written to {OUT_PATH}')
