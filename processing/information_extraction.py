"""
MIMIC-IV to openEHR Information Extraction Script
-------------------------------------

This module provides tools to process and extract structured information from clinical notes,
and to offload NLP inference tasks to a remote GPU server over SSH.

Main functionalities:
- SSH/SCP utilities:
    * Establish and close SSH connections to a GPU server.
    * Transfer input and output files between local and remote paths.
    * Launch remote inference jobs asynchronously.

- Clinical note processing:
    * Extract key sections from unstructured text, including:
        - Chief Complaint
        - History of Present Illness
        - Physical Exam
    * Prepare batched JSON files for inference.
    * Retrieve processed output files.

Key components:
- connect_with_gpu / close_gpu_connection: Manage remote SSH sessions.
- extract_sections: Parse notes and extract target sections using regex patterns.
- send_notes / retrieve_notes: Handle file transfer via SCP.
- inference: Launch remote inference commands in background.
- process_notes: Process raw notes DataFrame into JSON batches.

"""


from scp import SCPClient
from pathlib import Path
import paramiko
import json
import time
import regex as re
import os



# === GPU create/close connection ===

def connect_with_gpu():
    gpu_host = "bristol.hh.se" #"denver.hh.se"
    gpu_port = 20022
    gpu_username = "asirui24"
    private_key_path = "C:/Users/asirui/.ssh/id_rsa"

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=gpu_host, port=gpu_port, username=gpu_username, key_filename=private_key_path)
    return ssh

def close_gpu_connection(ssh):
    try:
        ssh.close()
    except Exception as e:
        print(f"Failed to close SSH connection: {e}")


# === Extract Chief Complaint, Past Medical History and Physical Exam sections ===

def extract_sections(note):

    # === Define the pattern to match the desired section ===  
    sections = {
        "Chief Complaint": [
            ("Chief Complaint:", "Major Surgical or Invasive Procedure:"),
            ("___ Complaint:", "Major Surgical or Invasive Procedure:")
        ],
        "History of Present Illness": [
            ("History of Present Illness:", "Past Medical History:"),
            ("___ Present Illness:", "Past Medical History:")
        ],
        "Physical Exam": [
            ("Physical Exam:", "Pertinent Results:"),
            ("Physical ___:", "Pertinent Results:"),
            ("Physical Exam:", "Brief Hospital Course:")
        ]
    }

    extracted_sections = {}
    for section_name, marker_pairs in sections.items():
        found = False
        for start_marker, end_marker in marker_pairs:
            if start_marker in note and end_marker in note:
                pattern = re.escape(start_marker) + r"\s*(.*?)\s*" + re.escape(end_marker)
                match = re.search(pattern, note, re.DOTALL)
                if match:
                    extracted_sections[section_name] = match.group(1).strip()
                    found = True
                    break
        if not found:
            extracted_sections[section_name] = "Section not found."
    return extracted_sections


# === Send, Infer and Retrive notes ===

def send_notes(ssh, local_path, remote_path, batch_ids):
    for batch_id in batch_ids:
        try:
            with SCPClient(ssh.get_transport()) as scp:
                scp.put(f"{local_path}/input_{batch_id}.json", f"{remote_path}/input_{batch_id}.json")
        except Exception as e:
            print(f"Failed to transfer batch {batch_id}: {e}")

def inference(ssh, batch_ids):    
    batch_list_str = " ".join(batch_ids)
    print(batch_list_str)
    remote_path = "/data/home/asirui24/notes"
    try:
        command = (
            "nohup bash -c '"
            "source /opt/anaconda3/etc/profile.d/conda.sh && "
            "conda activate /nfs/home/asirui24/conda_envs/nlp-env && "
            f"for batch in {batch_list_str}; do "
            "python /data/home/asirui24/process_notes.py --batch=$batch; "
            "done"
            f"' > {remote_path}/inference.log 2>&1 &"
        )
        ssh.exec_command(command)
    except Exception as e:
        print(f"Remote inference failed: {e}")

def retrieve_notes(ssh, local_path, remote_path, batch_ids):
    for batch_id in batch_ids:    
        try:
            with SCPClient(ssh.get_transport()) as scp:
                scp.get(f"{remote_path}/output_{batch_id}.json", f"{local_path}/output_batch_{batch_id}.json")
        except Exception as e:
            print(f"Failed to retrieve output for batch {batch_id}: {e}")
    close_gpu_connection(ssh)
        

# === Process notes ===        

def process_notes(notes, batch_id, local_path):

    batch = []
    chief_complaints = []

    for _, row in notes.iterrows():
        
        sections = extract_sections(row["text"])
        
        cc = sections["Chief Complaint"]
        hpi = sections["History of Present Illness"]
        pe = sections["Physical Exam"]

        note_fragment = f"History of Present Illness:\n{hpi}\n\n---------------------------\n\nPhysical Exam:\n{pe}"

        batch_note = {
            "note_id": row.get("note_id"),
            "hadm_id": row.get("hadm_id"),
            "note_fragment": note_fragment
        } 
        batch_cc = {
            "note_id": row.get("note_id"),
            "hadm_id": row.get("hadm_id"),
            "chief_complaint": cc
        } 
        
        batch.append(batch_note)
        chief_complaints.append(batch_cc)

    with open(f"{local_path}/input_{batch_id}.json", "w", encoding="utf-8") as f:
        json.dump(batch, f, indent=2)

    with open(f"{local_path}/CC_{batch_id}.json", "w", encoding="utf-8") as f:
        json.dump(chief_complaints, f, indent=2)

    ssh = connect_with_gpu()



