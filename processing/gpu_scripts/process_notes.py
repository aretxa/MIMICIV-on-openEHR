"""
This script processes batches of clinical discharge notes using a local Large Language Model (LLM) 
to extract vital signs and outputs structured JSON files for downstream EHR integration. It also servers
to track carbon emissions during infrerences and log inference time and errors.

Usage:
------
Run with command-line arguments:
    --model_path     Path to the local model
    --prompt_path    Prompt file to guide inference
    --batch_size     Number of notes per inference batch
    --notes_path     Directory containing input/output note files
    --batch          Batch ID (e.g., "0-500")

Main Steps:
-----------
1. Load prompt template and note fragments for the given batch.
2. Construct chat-style prompts (system + user roles).
3. Run batched inference using HuggingFace pipeline with automatic device placement.
4. Log emissions and errors, save output JSON (`output_<batch>.json`).
5. Create a '.done' file upon successful completion.

"""

from codecarbon import EmissionsTracker
from transformers import pipeline
from datetime import datetime
import argparse
import torch
import time
import json
import os
import re

# === Parse command-line arguments ===
parser = argparse.ArgumentParser(description="Process clinical notes with LLM")
parser.add_argument("--model_path", type=str, default="/tmp/llama3", help="Path to the local model")
parser.add_argument("--prompt_path", type=str, default="/data/home/asirui24/prompts/inference_13.txt", help="Prompting strategy to use")
parser.add_argument("--batch_size", type=int, default=2, help="Number of notes per batch")
parser.add_argument("--notes_path", type=str, default="/data/home/asirui24/notes", help="Directory with the note files")
parser.add_argument("--batch", type=str, required=True, help="Batch file to process")
args = parser.parse_args()

# === Extract model and prompt names ===
model_name = os.path.basename(args.model_path)
prompt_filename = os.path.basename(args.prompt_path)
match = re.search(r'(\d+)', prompt_filename)
prompt_id = match.group(1) if match else "unknown"

log_file = f"{args.notes_path}/inference_log.txt"
error_file = f"{args.notes_path}/failed_cases.txt"
output_data = []

# === Create tracker ===
tracker = EmissionsTracker(project_name=f"{model_name}_{prompt_id}_{args.batch}", output_dir=args.notes_path, output_file= f"emissions.csv")
tracker.start()

# === Load model ===
text_gen = pipeline(
    "text-generation",
    model=args.model_path,
    torch_dtype=torch.float16,
    device_map="auto"
)

# === Read base prompt ===
with open(args.prompt_path, "r") as f:
    base_prompt = f.read()

input_path = f"{args.notes_path}/input_{args.batch}.json"
output_path = f"{args.notes_path}/output_{args.batch}.json"
done_path = f"{args.notes_path}/batch_{args.batch}.done"

with open(input_path, "r", encoding="utf-8") as f:
    notes = json.load(f)

with open(log_file, "a") as log, open(error_file, "a") as err_log:
    log.write(f"\n{datetime.now()}: Start processing batch {args.batch}\n")

    for i in range(0, len(notes), args.batch_size):
        batch2 = notes[i:i + args.batch_size]
        prompts = []
        ids = []

        for item in batch2:
            try:
                note_text = item["note_fragment"]
                note_id = item.get("note_id")
                hadm_id = item.get("hadm_id")
                prompt = [{"role": "system", "content": base_prompt}, {"role": "user", "content": note_text}]
                prompts.append(prompt)
                ids.append({"note_id": note_id, "hadm_id": hadm_id})
            except Exception as e:
                err_log.write(f"{datetime.now()}: Failed to parse batch item: {str(e)}\n")

        if not prompts:
            continue

        try:
            start_time = time.time()
            outputs = text_gen(prompts, max_new_tokens=1024)
            elapsed_time = time.time() - start_time
        except Exception as e:
            err_log.write(f"{datetime.now()}: Failed inference on batch {i}: {str(e)}\n")
            continue

        for output, meta in zip(outputs, ids):
            try:
                result = output[0]['generated_text'][-1]['content']
                output_data.append({
                    "note_id": meta["note_id"],
                    "hadm_id": meta["hadm_id"],
                    "vitals": result
                })
                log.write(f"{datetime.now()}: Processed note {meta['note_id']} in {elapsed_time:.2f}s\n")
            except Exception as e:
                err_log.write(f"{datetime.now()}: Failed to parse output: {str(e)}\n")

        print(f"Batch {args.batch} finished")

# === Write output JSON ===
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output_data, f, indent=2)

# === Write done file ===
with open(done_path, "w", encoding="utf-8") as f:
    f.write("done")

log.close()
err_log.close()
tracker.stop()

