"""
Combined fetch (transcripts) + LLM analysis throughput tester.

Usage:
  - Ensure your Flask backend is running (default: http://127.0.0.1:5000).
  - Update the `URLS` list below with one or more YouTube video URLs (or playlist URLs).
  - Ensure you have `requests` and `llama-cpp-python` installed and the LLM model path set.
  - Run from the `test/` directory:
      python3 combined_fetch_and_analysis_test.py

Notes:
  - This script measures two stages separately and combined:
      * fetch/transcription (backend `/transcripts`) — uses backend metrics if present
      * analysis (local Llama) — measured locally according to each config
  - Loading the model for each config is slow and memory-intensive. Make sure you have enough RAM.
"""
import os
import time
import textwrap
import json
import gc
import statistics
import argparse

import requests
from llama_cpp import Llama

# --- CLI / env configuration ---
parser = argparse.ArgumentParser(description='Combined fetch + LLM analysis throughput tester')
parser.add_argument('--urls', '-u', nargs='+', help='One or more YouTube video (or playlist) URLs to fetch')
parser.add_argument('--backend-url', '-b', help='Backend base URL (default: http://127.0.0.1:5000)')
parser.add_argument('--model-path', '-m', help='LLM model path (overrides LLM_MODEL_PATH env)')
parser.add_argument('--iterations', '-n', type=int, help='Number of iterations per test (default: 3)')
parser.add_argument('--max-tokens', type=int, help='Max tokens to request from the model (default: 300)')
parser.add_argument('--output', '-o', help='Output JSON filename (default: combined_fetch_analysis_results.json)')
args = parser.parse_args()

# Configurable fields (env vars are fallbacks)
BACKEND_URL = args.backend_url or os.environ.get('BACKEND_URL', 'http://127.0.0.1:5000')
MODEL_PATH = args.model_path or os.environ.get('LLM_MODEL_PATH', './models/llm/Mistral-7B-Instruct-v0.3-Q6_K.gguf')
URLS = args.urls or []

PROMPT = "Provide a concise structured summary and action items for the transcript below."
MAX_TOKENS = args.max_tokens or 300
ITERATIONS = args.iterations or 3
OUT_PATH = args.output or 'combined_fetch_analysis_results.json'

configs = [
    {"name": "config_low_threads", "n_ctx": 8192, "n_batch": 64, "n_threads": 2, "n_gpu_layers": 20},
    {"name": "config_mid", "n_ctx": 8192, "n_batch": 128, "n_threads": 6, "n_gpu_layers": 30},
    {"name": "config_high_threads", "n_ctx": 8192, "n_batch": 256, "n_threads": 12, "n_gpu_layers": 40},
]

# Simple token estimator (same heuristic as hub.py)
def estimate_token_count(text):
    if not text:
        return 0
    words = len(text.split())
    estimated_tokens = max(1, int(words * 1.3))
    return estimated_tokens

if not URLS:
    print("No URLs configured. Use --urls to specify YouTube video URLs.")
    print("Example: python3 combined_fetch_and_analysis_test.py --urls 'https://youtu.be/OB_TJCFVWnw?si=KLfJjrkIZ9dXCZSf'")
    print("Exiting.")
    exit(1)

if not os.path.exists(MODEL_PATH):
    print(f"Model not found at {MODEL_PATH}. Set LLM_MODEL_PATH env or place model at that path.")
    exit(1)

results = {
    'meta': {
        'backend_url': BACKEND_URL,
        'model_path': MODEL_PATH,
        'iterations': ITERATIONS,
        'max_tokens': MAX_TOKENS,
        'urls': URLS
    },
    'results': []
}

# first measure fetch/transcript stage independently 
print('\n== Measuring fetch/transcript stage (backend) ==')
fetch_times = []
fetch_tokens = []
for i in range(ITERATIONS):
    print(f'Fetch iteration {i+1}/{ITERATIONS}...', end=' ')
    t0 = time.time()
    try:
        resp = requests.post(f"{BACKEND_URL}/transcripts", json={'urls': URLS}, timeout=600)
        elapsed = time.time() - t0
        print(f'done in {elapsed:.2f}s')
        fetch_times.append(elapsed)
        data = resp.json()
        metrics = data.get('metrics', {})
        total_tokens = metrics.get('total_tokens')
        # If backend didn't supply tokens, estimate from transcripts
        if total_tokens is None:
            total_tokens = 0
            for r in data.get('results', []):
                total_tokens += estimate_token_count(r.get('transcript', ''))
        fetch_tokens.append(total_tokens)
    except Exception as e:
        elapsed = time.time() - t0
        print(f'error after {elapsed:.2f}s: {e}')
        fetch_times.append(None)
        fetch_tokens.append(0)

fetch_total_time = sum(t for t in fetch_times if t)
fetch_total_tokens = sum(fetch_tokens)
fetch_avg_time = statistics.mean([t for t in fetch_times if t]) if any(fetch_times) else None
fetch_tokens_per_sec = fetch_total_tokens / fetch_total_time if fetch_total_time > 0 else 0
print(f"Fetch stage: total_tokens={fetch_total_tokens} total_time={fetch_total_time:.2f}s tokens/sec={fetch_tokens_per_sec:.2f}\n")

results['fetch_stage'] = {
    'per_iteration_s': fetch_times,
    'per_iteration_tokens': fetch_tokens,
    'total_time_s': fetch_total_time,
    'total_tokens': fetch_total_tokens,
    'avg_time_s': fetch_avg_time,
    'tokens_per_sec': fetch_tokens_per_sec
}

# Extract concatenated transcripts for analysis (use the last successful fetch result)
last_fetch = None
try:
    last_fetch = resp.json()
except Exception:
    pass

transcript_text = ''
if last_fetch and 'results' in last_fetch:
    parts = [r.get('transcript', '') for r in last_fetch['results'] if r.get('transcript')]
    transcript_text = '\n'.join(parts)
else:
    print('No transcript text returned from backend; analysis stage will run on fetched transcript placeholder.')
    transcript_text = ' '.join(['This is a sample sentence.'] * 500)

# Now run analysis stage for each LLM config
for cfg in configs:
    print(f"\n== Testing analysis with {cfg['name']} ==")
    cfg_result = {'config': cfg['name'], 'params': cfg, 'iterations': ITERATIONS, 'per_iteration': []}

    for i in range(ITERATIONS):
        print(f'Analysis iter {i+1}/{ITERATIONS}...', end=' ')
        try:
            # load model per-config
            start_load = time.time()
            llm = Llama(
                model_path=MODEL_PATH,
                n_ctx=cfg['n_ctx'],
                n_batch=cfg['n_batch'],
                n_threads=cfg['n_threads'],
                n_gpu_layers=cfg['n_gpu_layers'],
                use_mlock=True,
                verbose=False
            )
            load_time = time.time() - start_load
            # Run analysis
            t0 = time.time()
            resp = llm.create_completion(
                prompt=(PROMPT + "\n\nTranscript:\n" + textwrap.shorten(transcript_text, width=4000)),
                temperature=0.5,
                max_tokens=MAX_TOKENS,
                top_p=0.9,
            )
            elapsed = time.time() - t0
            # extract text
            try:
                out_text = resp['choices'][0]['text']
            except Exception:
                out_text = str(resp)
            est_out_tokens = estimate_token_count(out_text)
            print(f'done load {load_time:.1f}s analyze {elapsed:.2f}s est_tokens={est_out_tokens}')

            # combined tokens/time includes fetched transcript tokens + generated tokens
            fetched_tokens_iter = fetch_tokens[i] if i < len(fetch_tokens) else fetch_tokens[-1] if fetch_tokens else 0
            combined_tokens = fetched_tokens_iter + est_out_tokens
            combined_time = (fetch_times[i] if i < len(fetch_times) and fetch_times[i] else 0) + elapsed
            combined_tokens_per_sec = combined_tokens / combined_time if combined_time > 0 else 0

            cfg_result['per_iteration'].append({
                'load_time_s': load_time,
                'analyze_time_s': elapsed,
                'est_output_tokens': est_out_tokens,
                'fetched_tokens': fetched_tokens_iter,
                'combined_tokens': combined_tokens,
                'combined_time_s': combined_time,
                'combined_tokens_per_sec': combined_tokens_per_sec
            })

        except Exception as e:
            print(f'error: {e}')
            cfg_result['per_iteration'].append({'error': str(e)})
        finally:
            try:
                del llm
                gc.collect()
                time.sleep(1.0)
            except Exception:
                pass

    # summarize
    successful = [p for p in cfg_result['per_iteration'] if 'combined_tokens_per_sec' in p]
    if successful:
        avg_combined_tps = statistics.mean([p['combined_tokens_per_sec'] for p in successful])
        cfg_result['avg_combined_tokens_per_sec'] = avg_combined_tps
    else:
        cfg_result['avg_combined_tokens_per_sec'] = 0

    results['results'].append(cfg_result)

# Write results
OUT_PATH = 'combined_fetch_analysis_results.json'
with open(OUT_PATH, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\nResults written to {OUT_PATH}")
print('Done.')
