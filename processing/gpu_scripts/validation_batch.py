"""
This script evaluates the inference efficiency of a local LLM (e.g., LLaMA) 
on a fixed validation set of clinical notes using configurable batch sizes.
It is used to determine optimal batch size vs. performance trade-off.

Usage:
------
Run with arguments:
    --model_path     Path to the local model directory
    --input_dir      Folder with 'input_x.txt' files
    --output_dir     Folder where outputs and logs are saved 
    --prompt_path    Prompting strategy
    --batch_size     Number of notes per batch

Workflow:
---------
1. Batches `input_*.txt` files by the given batch size.
2. Constructs system+user prompts and performs batched inference via HuggingFace pipeline.
3. Writes output files (`output_<n>.txt`) and logs inference time and failures.
4. Tracks carbon emissions per run using CodeCarbon.

"""


from codecarbon import EmissionsTracker
from transformers import pipeline
from datetime import datetime
import argparse
import torch
import time
import os
import re

# === Parse arguments ===
parser = argparse.ArgumentParser(description="Batch process clinical notes with LLM")
parser.add_argument("--model_path", type=str, required=True)
parser.add_argument("--input_dir", type=str, default="validation/notes")
parser.add_argument("--output_dir", type=str, default="validation/results_batch")
parser.add_argument("--prompt_path", type=str, default="prompts/inference_00.txt")
parser.add_argument("--batch_size", type=int, default=4, help="Number of notes per batch")
args = parser.parse_args()

# === Setup ===
model_name = os.path.basename(args.model_path)
prompt_filename = os.path.basename(args.prompt_path)
match = re.search(r'(\d+)', prompt_filename)
prompt_id = match.group(1) if match else "unknown"

output_dir = os.path.join(args.output_dir, f"{model_name}_{prompt_id}")
input_dir = args.input_dir
log_file = os.path.join(args.output_dir, "inference_log.txt")
error_file = os.path.join(args.output_dir, "failed_cases.txt")
os.makedirs(output_dir, exist_ok=True)

tracker = EmissionsTracker(project_name=f"{model_name}_{prompt_id}", output_dir=args.output_dir, output_file="emissions.csv")
tracker.start()

# === Load model ===
text_gen = pipeline(
    "text-generation",
    model=args.model_path,
    torch_dtype=torch.float16,
    device_map="auto"
)

# === Load prompt ===
with open(args.prompt_path, "r") as f:
    base_prompt = f.read()

# === Get all input files ===
input_files = sorted([f for f in os.listdir(input_dir) if f.startswith("input_") and f.endswith(".txt")],
                     key=lambda x: int(re.findall(r'\d+', x)[0]))

with open(log_file, "a") as log, open(error_file, "a") as err_log:
    log.write(f"\n{model_name}_{prompt_id}:\n")

    for batch_start in range(0, len(input_files), args.batch_size):
        batch_files = input_files[batch_start:batch_start + args.batch_size]
        prompts = []
        filenames = []

        for filename in batch_files:
            input_path = os.path.join(input_dir, filename)
            try:
                with open(input_path, "r", encoding="utf-8") as f:
                    note = f.read()
                prompt = [{"role": "system", "content": base_prompt}, {"role": "user", "content": note}]
                prompts.append(prompt)
                filenames.append(filename)
            except Exception as e:
                err_log.write(f"{datetime.now()}: Failed to load {filename}: {str(e)}\n")

        if not prompts:
            continue

        try:
            start_time = time.time()
            outputs = text_gen(prompts, max_new_tokens=1024)
            elapsed_time = time.time() - start_time
        except Exception as e:
            for fname in filenames:
                err_log.write(f"{datetime.now()}: Failed to run batch including {fname}: {str(e)}\n")
            continue

        for output, fname in zip(outputs, filenames):
            try:
                result = output[0]['generated_text'][-1]['content']
                output_path = os.path.join(output_dir, fname.replace("input_", "output_"))
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(result)
                log.write(f"{datetime.now()}: {fname} → {output_path} in {elapsed_time:.2f}s\n")
            except Exception as e:
                err_log.write(f"{datetime.now()}: Failed to write output for {fname}: {str(e)}\n")

tracker.stop()
