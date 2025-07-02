"""
This script performs sequential inference over a validation set of clinical notes using a 
local Large Language Model (LLM), saving the outputs for model and prompt evaluation. It also servers
to track carbon emissions during infrerence and log inference time and errors.

Usage:
------
Run with command-line arguments:
    --model_path     Path to the local model directory (e.g., LLaMA 3)
    --input_dir      Directory containing note files (input_1.txt to input_50.txt)
    --output_dir     Directory where outputs and logs will be stored
    --prompt_path    Prompt file guiding inference (

Main Steps:
-----------
1. Load each '.txt' note file in sequence.
2. Build a system+user role prompt using the selected prompt strategy.
3. Run inference using HuggingFace 'pipeline'.
4. Save results as 'output_x.txt' and log inference time per note.

"""

from codecarbon import EmissionsTracker
from transformers import pipeline
from datetime import datetime
import argparse
import torch
import time
import os
import re

# === Parse command-line arguments ===
parser = argparse.ArgumentParser(description="Process clinical notes with LLM.")
parser.add_argument("--model_path", type=str, required=True, help="Path to the local model directory")
parser.add_argument("--input_dir", type=str, default="validation/notes", help="Directory with input .txt files")
parser.add_argument("--output_dir", type=str, default="validation/results", help="Directory to save output files")
parser.add_argument("--prompt_path", type=str, default="prompts/inference_00.txt", help="Prompting strategy to use")
args = parser.parse_args()

# === Extract model and prompt names ===
model_name = os.path.basename(args.model_path)
prompt_filename = os.path.basename(args.prompt_path)
match = re.search(r'(\d+)', prompt_filename)
prompt_id = match.group(1) if match else "unknown"

# === Define paths ===
output_dir = args.output_dir + "/" + model_name + "_" + prompt_id
input_dir = args.input_dir
log_file = f"{args.output_dir}/inference_log.txt"
error_file = f"{args.output_dir}/failed_cases.txt"
os.makedirs(output_dir, exist_ok=True)

# === Create tracker ===
tracker = EmissionsTracker(project_name=f"{model_name}_{prompt_id}", output_dir=args.output_dir, output_file= f"emissions.csv")
tracker.start()

# === Load model once ===
pipeline = pipeline(
    "text-generation",
    model=args.model_path,
    torch_dtype=torch.float16,
    device_map="auto"
)

# === Read base prompt ===
with open(args.prompt_path, "r") as f:
    base_prompt = f.read()

with open(log_file, "a") as log, open(error_file, "a") as err_log:
    log.write(f"\n{model_name}_{prompt_id}:\n")
    for i in range(1, 51):
        input_file = os.path.join(input_dir, f"input_{i}.txt")
        output_file = os.path.join(output_dir, f"output_{i}.txt")

        try:
            start_time = time.time()
            with open(input_file, "r", encoding="utf-8") as f:
                note = f.read()

            prompt = [{"role": "system", "content": base_prompt},{"role": "user", "content": note}]

            output = pipeline(prompt, max_new_tokens=1024)

            result = output[0]['generated_text'][-1]['content']

            with open(output_file, "w", encoding="utf-8") as f:
                f.write(result)

            elapsed_time = time.time() - start_time
            log.write(f"{datetime.now()}: input_{i}.txt → output_{i}.txt in {elapsed_time:.2f}s\n")

        except Exception as e:
            err_log.write(f"{datetime.now()}: Failed input_{i}.txt: {str(e)}\n")

tracker.stop()
