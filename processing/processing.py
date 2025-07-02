"""
MIMIC-IV to openEHR Processing Script
-------------------------------------

This script extracts, transforms, and commits patient admission data from the MIMIC-IV database 
into openEHR compositions using the EHRbase platform. It supports both structured data (e.g., 
admissions, diagnoses, procedures, medications) and unstructured data (e.g., discharge notes with LLM-extracted information).

Main Workflow:
--------------
1. Connect to a local PostgreSQL instance hosting MIMIC-IV.
2. Identify patients diagnosed with a target condition (e.g., heart failure via ICD-10 I50%).
3. For each patient:
   - Extract latest admission and validate presence of discharge notes.
   - If discharge notes exist, send to a remote server for LLM inference (chief complaint and vitals).
   - Generate structured JSON compositions using `structure_template()`.
4. Commit validated compositions to EHRbase via REST API.

Key Components:
---------------
- 'get_*' functions: Modular SQL queries to retrieve structured EHR data.
- 'structure_template()': Converts admission-related data into a flat openEHR-compatible JSON structure.
- 'commit()': Sends compositions to EHRbase and logs the result.
- 'information_extraction': External module for processing and inferring data from free-text notes using GPU.
- 'EHRbase_functions': Handles EHR creation and composition commit requests.

"""

import information_extraction as ie
import ehrbase_functions as ehrbase

from sqlalchemy import create_engine
from sqlalchemy import text
from datetime import timedelta
import pandas as pd
import shutil
import uuid
import time
import json
import csv
import os

print("libraries imported")



# === Connect to PostgreSQL ===

def connect_to_postgres():
    DB_NAME = "mimic"
    DB_USER = "postgres"
    DB_PASSWORD = "sd98hS&GD3F4"
    DB_HOST = "localhost"
    DB_PORT = "5432"

    engine = create_engine(f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

    try: 
        df = pd.read_sql("SELECT * FROM mimic.mimiciv_hosp.admissions LIMIT 5;", engine)
        return engine
    except Exception as e:
        print(f"Connection failed: {e}")



# === Feature selection ===

def get_cohort(icd_code, engine):
    query = text('''
    SELECT DISTINCT subject_id
    FROM mimiciv_hosp.diagnoses_icd
    WHERE icd_code_v2 LIKE :icd_code
    ORDER BY subject_id;
    ''')               
    return pd.read_sql(query, engine, params={"icd_code": icd_code})

def get_last_admission(subject_ids, engine):
    query = text('''
    WITH last_admissions AS (
        SELECT 
            a.hadm_id,
            a.subject_id,
            ROW_NUMBER() OVER (PARTITION BY a.subject_id ORDER BY a.admittime DESC) AS rn
        FROM 
            mimiciv_hosp.admissions a
        WHERE 
            a.subject_id IN :subject_ids
        )
    SELECT 
        hadm_id
    FROM 
        last_admissions
    WHERE 
        rn = 1
    ORDER BY
        subject_id;
    ''')
    admissions = pd.read_sql(query, engine, params={"subject_ids": tuple(subject_ids)})
    return admissions

def get_admissions_with_notes(hadm_ids, engine):
    query = text('''
    SELECT
        dis.hadm_id
    FROM mimiciv_note.discharge AS dis
    WHERE dis.hadm_id IN :hadm_ids
    ORDER BY
        subject_id;                 
    ''')
    admissions = pd.read_sql(query, engine, params={"hadm_ids": tuple(hadm_ids)})
    return admissions

def get_admissions(hadm_ids, engine):
    query = text('''
    SELECT DISTINCT
        a.subject_id,
        a.hadm_id,
        a.admittime,
        a.dischtime,
        a.admission_type,
        a.admit_provider_id,
        a.admission_location,
        a.discharge_location,
        a.insurance,
        a.edregtime
    FROM mimiciv_hosp.admissions AS a
    where a.hadm_id IN :hadm_ids        
    ORDER BY subject_id asc
    ''')
    admissions = pd.read_sql(query, engine, params={"hadm_ids": hadm_ids})
    return admissions

def get_services(hadm_ids, engine):
    query = text('''
    SELECT DISTINCT
        s.hadm_id,
        s.curr_service,
        s.transfertime
    FROM mimiciv_hosp.services AS s
    where hadm_id IN :hadm_ids        
    ORDER BY transfertime asc
    ''')
    transfers = pd.read_sql(query, engine, params={"hadm_ids": hadm_ids})
    return transfers

def get_transfers(hadm_ids, engine):
    query = text('''
    SELECT DISTINCT
        t.hadm_id,
        t.eventtype,
        t.careunit,
        t.intime,
        t.outtime
    FROM mimiciv_hosp.transfers AS t
    where hadm_id IN :hadm_ids        
    ORDER BY intime asc
    ''')
    transfers = pd.read_sql(query, engine, params={"hadm_ids": hadm_ids})
    return transfers

def get_diagnoses(hadm_ids, engine):
    query = text('''
    SELECT  
        di.hadm_id,
        di.seq_num,
        di.icd_code,
        di.icd_version,
        def.long_title
    FROM mimiciv_hosp.diagnoses_icd AS di
    LEFT JOIN mimiciv_hosp.d_icd_diagnoses AS def
        ON di.icd_code = def.icd_code
    WHERE di.hadm_id IN :hadm_ids
    ORDER BY di.seq_num
    ''')
    diagnoses = pd.read_sql(query, engine, params={"hadm_ids": hadm_ids})
    return diagnoses

def get_procedures(hadm_ids, engine):
    query = text('''
    SELECT  
        p.hadm_id,
        p.seq_num,
        p.icd_code,
        p.icd_version,
        p.chartdate,
        def.long_title
    FROM mimiciv_hosp.procedures_icd AS p
    LEFT JOIN mimiciv_hosp.d_icd_procedures AS def
        ON p.icd_code = def.icd_code
    WHERE p.hadm_id IN :hadm_ids
    ORDER BY p.seq_num
    ''')
    procedures = pd.read_sql(query, engine, params={"hadm_ids": hadm_ids})
    return procedures

def get_orders(hadm_ids, engine):
    query = text('''
    SELECT
        poe.hadm_id,
        poe.poe_id,
        poe.poe_seq, 
        poe.ordertime,
        poe.order_type,
        poe.order_subtype,
        poe.transaction_type,
        poe.order_provider_id,
        poe.order_status
    FROM mimiciv_hosp.poe AS poe
    WHERE poe.hadm_id IN :hadm_ids
    ORDER BY poe_seq
    ''')
    orders = pd.read_sql(query, engine, params={"hadm_ids": hadm_ids})
    return orders

def get_medication_order(hadm_ids, engine):
    query = text('''
    SELECT
        ph.hadm_id,
        ph.poe_id,
        ph.pharmacy_id,
                
        -- medication item
        ph.medication,
        pr.drug,
                
        -- medication details
        pr.ndc,
        pr.drug_type,
        pr.prod_strength,
        ph.expiration_value,
        ph.expiration_unit,
        ph.proc_type,
                
        -- route
        ph.route,
        --pr.route,
                
        -- structured dose and timings
        ph.starttime,
        ph.stoptime,
        ph.disp_sched,
        ph.doses_per_24_hrs,
        --pr.doses_per_24_hrs,  
        ph.frequency,
        pr.dose_val_rx,
        pr.dose_unit_rx,
        pr.form_val_disp,
        pr.form_unit_disp,
        ph.dispensation,
                
        -- order details
        ph.entertime,
        ph.verifiedtime,
        ph.status
    FROM mimiciv_hosp.pharmacy AS ph
    LEFT JOIN mimiciv_hosp.prescriptions AS pr
        ON ph.pharmacy_id = pr.pharmacy_id
    WHERE ph.hadm_id IN :hadm_ids
    ORDER BY entertime
    ''')
    medication_order = pd.read_sql(query, engine, params={"hadm_ids": hadm_ids})
    return medication_order

def get_medication_management(hadm_ids, engine):
    query = text('''
    SELECT
        e.hadm_id,
        e.emar_id,
        e.emar_seq,
        e.poe_id,
        e.pharmacy_id,
                
        -- medication item
        e.medication,
                
        -- amount/dosage
        ed.parent_field_ordinal,
        -- original Schedule date/time
        e.scheduletime,

        -- pathway
        e.event_txt,
                 
        ed.administration_type,
        e.charttime

    FROM mimiciv_hosp.emar AS e
    LEFT JOIN mimiciv_hosp.emar_detail AS ed
        ON e.emar_id = ed.emar_id
    WHERE e.hadm_id IN :hadm_ids
    ORDER BY e.emar_id
    ''')
    medication_management = pd.read_sql(query, engine, params={"hadm_ids": hadm_ids})
    return medication_management

def get_notes(hadm_ids, engine):
    query = text('''
    SELECT
        dis.note_id,
        dis.hadm_id,
        dis.text
    FROM mimiciv_note.discharge AS dis
    WHERE dis.hadm_id IN :hadm_ids
    ''')
    notes = pd.read_sql(query, engine, params={"hadm_ids": tuple(hadm_ids)})
    return notes



# === Structure composition ===

def safe_str(value, default=None):
    try:
        if pd.notnull(value):
            return str(value)
    except:
        pass
    return default

def safe_int(value, default=0):
    try:
        if pd.notnull(value) and float(value).is_integer():
            return int(value)
    except:
        pass
    return default

def safe_float(value, default=0.0):
    try:
        return float(value)
    except:
        return default

def safe_date(value, default=None):
    if pd.isnull(value):
        return default
    try:
        return pd.to_datetime(value).isoformat()
    except Exception:
        return default
    
def structure_template(admission, services, transfers, diagnoses, procedures, orders, medication_order, medication_management, CC=None, VS=None):
    
    # Define variables
    template_name = "mimic-iv_to_openehr"
    language = "en"                                 # English
    lan_terminology = "ISO_639-1"                   # ISO 639-1 language codec
    encoding = "UTF-8"                              # UTF-8 encoding
    enco_terminology = "IANA_character-sets"        # IANA character sets terminology
    territory = "US"                                # The events happened in United States
    ter_terminology = "ISO_3166-1"                  # ISO 3166-1 country code
    
    composition_type = "event"

    # Define Maps
    category_map = {"event": 433, "persistent": 431, "episodic": 451, "report": 815}
    attending_unit_map = {
        "CMED": "Cardiac Medical - for non-surgical cardiac related admissions",
        "CSURG": "Cardiac Surgery - for surgical cardiac admissions",
        "DENT": "Dental - for dental/jaw related admissions",
        "ENT": "Ear, nose, and throat - conditions primarily affecting these areas",
        "EYE": "Eye diseases - including subspecialty services in glaucoma, cataract surgery, cornea and external diseases, and neuro-ophthalmology",
        "GU": "Genitourinary - reproductive organs/urinary system",
        "GYN": "Gynecological - female reproductive systems and breasts",
        "MED": "Medical - general service for internal medicine",
        "NB": "Newborn - infants born at the hospital",
        "NBB": "Newborn baby - infants born at the hospital",
        "NMED": "Neurologic Medical - non-surgical, relating to the brain",
        "NSURG": "Neurologic Surgical - surgical, relating to the brain",
        "OBS": "Obstetrics - conerned with childbirth and the care of women giving birth",
        "ORTHO": "Orthopaedic - surgical, relating to the musculoskeletal system",
        "OMED": "Oncologic Medical - non-surgical, relating to cancer",
        "PSURG": "Plastic - restortation/reconstruction of the human body (including cosmetic or aesthetic)",
        "PSYCH": "Psychiatric - mental disorders relating to mood, behaviour, cognition, or perceptions",
        "SURG": "Surgical - general surgical service not classified elsewhere",
        "TRAUM": "Trauma - injury or damage caused by physical harm from an external source",
        "TSURG": "Thoracic Surgical - surgery on the thorax, located between the neck and the abdomen",
        "VSURG": "Vascular Surgical - surgery relating to the circulatory system"}
    orders_action_archetype_map = {
        "Lab": "service.v1",
        "ADT orders": "service.v1",
        "Nutrition": "service.v1",
        "Radiology": "service.v1",
        "Consults": "service.v1",
        "Blood Bank": "service.v1",
        "Cardiology": "service.v1",
        "TPN": "service.v1",
        "Critical Care": "service.v1",
        "Neurology": "service.v1",
        "General Care": "procedure.v1",
        "IV therapy": "procedure.v1",
        "Respiratory": "procedure.v1",
        "Hemodialysis": "procedure.v1",
        "OB": "procedure.v1"}
    medication_order_status_map = {
        "Discontinued via patient discharge": ("Stopped", "at0022"),
        "Discontinued": ("Stopped", "at0022"),
        "Expired": ("Stopped", "at0024"), # +-
        "Inactive (Due to a change order)": ("Obsolete", "at0025"),
        "Active": ("Active", "at0021"),
        "H": ("Suspended", "at0026"), # on Hold?
        "Inactive": ("Stopped", "at0022"),
        "TPN Order (Acknowledged, Not Pumped)": ("Never active", "at0023"),
        "U":("Stopped", "at0022")} # Unknown?
    medication_order_role_map = {
        "MAIN": ("Therapeutic", "at0080"),
        "BASE": ("Adjuvant", "at0083"),
        "ADDITIVE": ("Excipient", "at0084")
    }
    medication_management_ism_category_map = { #https://specifications.openehr.org/releases/TERM/Release-3.0.0/SupportTerminology.html#_instruction_transitions
        "initial": "526", #"524",
        "planned": "526",
        "postponed": "527",
        "cancelled": "528",
        "scheduled": "529",
        "active": "245",
        "suspended": "530",
        "aborted": "531",
        "completed": "532",
        "expired": "533"
        }
    medication_management_ism_transition_map = {
        "Administered": "active",
        "Flushed": "active",
        "Not Given": "initial",
        "Confirmed": "active",
        "Not Flushed": "initial",
        "Not Given per Sliding Scale": "initial",
        "Started": "active",
        "Assessed": "active",
        "Stopped": "aborted",
        "Applied": "active",
        "Removed": "completed",
        "Stopped - Unscheduled": "cancelled",
        "Delayed Administered": "postponed",
        "Hold Dose": "suspended",
        "Not Applied": "initial",
        "Infusion Reconciliation": "planned",
        " in Other Location": "active",
        "Restarted": "active",
        "Administered Bolus from IV Drip": "active",
        "Not Started": "initial",
        "Not Confirmed": "initial",
        "Stopped in Other Location": "suspended",
        "Administered in Other Location": "active",
        "Stopped As Directed": "suspended",
        "Pain score re-assessment": "planned",
        "Not Stopped": "initial",
        "Removed Existing / Applied New": "active",
        "Rate Change": "active",
        "Flushed in Other Location": "active",
        "Delayed": "postponed",
        "Not Assessed": "initial",
        "Not Removed": "initial",
        "Started in Other Location": "active",
        "Delayed Started": "postponed",
        "Partial Administered": "completed",
        "Pain score re-assess not done": "planned",
        "Delayed Flushed": "postponed",
        "Delayed Confirmed": "postponed",
        "Documented in O.R. Holding": "completed",
        "Confirmed in Other Location": "active",
        "Applied in Other Location": "active",
        "Stopped - Unscheduled in Other Location": "cancelled",
        "Infusion Reconciliation Not Done": "initial",
        "Delayed Stopped": "postponed",
        "Assessed in Other Location": "active",
        "Delayed Removed": "postponed",
        "Read": "planned",
        "Delayed Assessed": "postponed",
        "Removed in Other Location": "completed",
        "Not Started per Sliding Scale": "initial",
        "TPN Rate Not Changed": "initial",
        "Not Stopped per Sliding Scale": "initial",
        "Delayed Not Applied": "postponed",
        "Removed Existing / Applied New in Other Location": "active",
        "Delayed Applied": "postponed",
        "Delayed Not Flushed": "postponed",
        "Removed - Unscheduled": "cancelled",
        "Delayed Not Started": "postponed",
        "Not Read": "initial",
        "Delayed Not Confirmed": "postponed",
        "Delayed Not Removed": "postponed",
        "Delayed Restarted": "postponed",
        "Restarted in Other Location": "active",
        "Delayed Rate Change": "postponed",
        "Rate Change in Other Location": "active",
        "Read in Other Location": "planned",
        "Partial ": "completed",
        "Not Given per Sliding Scale in Other Location": "initial",
        "Delayed Not Assessed": "postponed",
        "Delayed Not Stopped": "postponed",
        "Delayed Stopped As Directed": "postponed",
        "Infusion Reconciliation in Other Location": "planned"
    }
    transfer_event_map = {"Emergency Department": "ED", "Discharge": "discharge", "Admission": "admit", "Transfer": "transfer", "Unknown": "ED"}

    flat_json = {}
    
    flat_json[f"{template_name}/category|code"] = category_map[composition_type]
    flat_json[f"{template_name}/category|value"] = composition_type
    flat_json[f"{template_name}/category|terminology"] = "openehr"
    flat_json[f"{template_name}/context/start_time"] = safe_date(admission["edregtime"])
    flat_json[f"{template_name}/context/_health_care_facility|name"] = "BIDMC" # Beth Israel Deaconess Medical Center

    # ADT - Admission, Discharge, Transfer
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/episode_id|id"] = int(admission["hadm_id"])
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/admission_date"] = safe_date(admission["admittime"])
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/reason_for_admission"] = CC
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/admission_category"] = admission["admission_type"]
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/source_category"] = admission["admission_location"]
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/medical_record_number/text_value"] = int(admission["subject_id"])
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/health_insurance_category"] = safe_str(admission["insurance"])
    
    index = 0
    for _, row in services.iterrows():
        flat_json[f"{template_name}/adt/episode_of_care_-_institution/attending_unit:{index}|value"] = attending_unit_map[row["curr_service"]]
        flat_json[f"{template_name}/adt/episode_of_care_-_institution/attending_unit:{index}|code"] = row["curr_service"]
        flat_json[f"{template_name}/adt/episode_of_care_-_institution/attending_unit:{index}|terminology"] = "local_terms"
        index += 1
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/person/identifier:0/text_value"] = admission["admit_provider_id"]
    
    index = 0
    for _, row in transfers.iterrows():
        flat_json[f"{template_name}/adt/episode_of_care_-_institution/physical_location:{index}/location_onset"] = safe_date(row["intime"])
        flat_json[f"{template_name}/adt/episode_of_care_-_institution/physical_location:{index}/location_category"] = safe_str(row["careunit"])
        flat_json[f"{template_name}/adt/episode_of_care_-_institution/physical_location:{index}/location_end"] = safe_date(row["outtime"])
        index += 1
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/separation_date"] = safe_date(admission["dischtime"])
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/destination_category"] = admission["discharge_location"]
    
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/language|code"] = language
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/language|terminology"] = lan_terminology
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/encoding|code"] = encoding
    flat_json[f"{template_name}/adt/episode_of_care_-_institution/encoding|terminology"] = enco_terminology

    # Diagnoses
    index = 0
    for _, row in diagnoses.iterrows():
        flat_json[f"{template_name}/diagnosis/problem_diagnosis:{index}/problem_diagnosis_name|code"] = row['icd_code']
        flat_json[f"{template_name}/diagnosis/problem_diagnosis:{index}/problem_diagnosis_name|terminology"] =  row['icd_version']
        flat_json[f"{template_name}/diagnosis/problem_diagnosis:{index}/problem_diagnosis_name|value"] =  row["long_title"]

        flat_json[f"{template_name}/diagnosis/problem_diagnosis:{index}/language|code"] = language
        flat_json[f"{template_name}/diagnosis/problem_diagnosis:{index}/language|terminology"] = lan_terminology
        flat_json[f"{template_name}/diagnosis/problem_diagnosis:{index}/encoding|code"] = encoding
        flat_json[f"{template_name}/diagnosis/problem_diagnosis:{index}/encoding|terminology"] = enco_terminology
        index += 1

    # Procedures
    index = 0
    for _, row in procedures.iterrows():
        flat_json[f"{template_name}/procedures/procedure:{index}/procedure_name|code"] = row['icd_code']
        flat_json[f"{template_name}/procedures/procedure:{index}/procedure_name|terminology"] = row["icd_version"]
        flat_json[f"{template_name}/procedures/procedure:{index}/procedure_name|value"] = row["long_title"]
        
        flat_json[f"{template_name}/procedures/procedure:{index}/language|code"] = language
        flat_json[f"{template_name}/procedures/procedure:{index}/language|terminology"] = lan_terminology
        flat_json[f"{template_name}/procedures/procedure:{index}/encoding|code"] = encoding
        flat_json[f"{template_name}/procedures/procedure:{index}/encoding|terminology"] = enco_terminology
        flat_json[f"{template_name}/procedures/procedure:{index}/time"] = safe_date(row["chartdate"])
        index += 1    

    # Orders
    index = 0
    for _, row in orders.iterrows():    
        if row["order_type"] == "Medications": # Skip orders when order_type is "medication"
            continue
        flat_json[f"{template_name}/orders/service_request:{index}/current_activity/service_name"] = row["order_subtype"] if pd.notna(row['order_subtype']) else row['order_type'] # order subtype unless its empty, then order type
        flat_json[f"{template_name}/orders/service_request:{index}/current_activity/service_type"] = row["order_type"]
        flat_json[f"{template_name}/orders/service_request:{index}/current_activity/order_detail:0"] = row["transaction_type"]
        flat_json[f"{template_name}/orders/service_request:{index}/current_activity/timing"] = safe_date(row["ordertime"])
        flat_json[f"{template_name}/orders/service_request:{index}/current_activity/timing|formalism"] = "timing"
        flat_json[f"{template_name}/orders/service_request:{index}/current_activity/action_archetype_id"] = orders_action_archetype_map[row["order_type"]]
        flat_json[f"{template_name}/orders/service_request:{index}/requester_order_identifier/text_value"] = row["poe_id"]
        flat_json[f"{template_name}/orders/service_request:{index}/person/identifier:0/text_value"] = safe_str(row["order_provider_id"])
        flat_json[f"{template_name}/orders/service_request:{index}/request_status"] = row["order_status"]

        flat_json[f"{template_name}/orders/service_request:{index}/language|terminology"] = lan_terminology
        flat_json[f"{template_name}/orders/service_request:{index}/language|code"] = language
        flat_json[f"{template_name}/orders/service_request:{index}/encoding|code"] = encoding
        flat_json[f"{template_name}/orders/service_request:{index}/encoding|terminology"] = enco_terminology
        index += 1

    # Medication order
    index = 0
    for _, row in medication_order.iterrows():
        flat_json[f"{template_name}/medications/medication_order:{index}/order/medication_item"] =  safe_str(row['medication'], "Unknown")

        if pd.notna(row['form_val_disp']) and pd.notna(row['form_unit_disp']):
            flat_json[f"{template_name}/medications/medication_order:{index}/order/medication_details/form:0"] = safe_str(row['form_val_disp'] + " " + row['form_unit_disp'])
        
        time = safe_date(row["starttime"])
        unit = safe_str(row['expiration_unit'])
        value = safe_int(row['expiration_value'])
        if time and pd.notna(unit) and pd.notna(value):
            base_time = pd.to_datetime(time)
            if unit == "Hours":
                expiry_time = base_time  + timedelta(hours=value)
            elif unit == "Days":
                expiry_time = base_time  + timedelta(days=value)
            else:
                expiry_time = None
            if expiry_time: flat_json[f"{template_name}/medications/medication_order:{index}/order/medication_details/expiry"] = expiry_time.isoformat()
    
        flat_json[f"{template_name}/medications/medication_order:{index}/order/medication_details/role|terminology"] = "local"
        
        if pd.notna(row['drug_type']):
            flat_json[f"{template_name}/medications/medication_order:{index}/order/medication_details/role|code"] = medication_order_role_map[row['drug_type']][1]
            flat_json[f"{template_name}/medications/medication_order:{index}/order/medication_details/role|value"] =  medication_order_role_map[row['drug_type']][0]
        # flat_json[f"{template_name}/medications/medication_order:{index}/order/medication_details/name:0"] = GSN
        flat_json[f"{template_name}/medications/medication_order:{index}/order/route:0"] =  safe_str(row['route'])
        flat_json[f"{template_name}/medications/medication_order:{index}/order/administration_method:0"] =  row['proc_type']
        flat_json[f"{template_name}/medications/medication_order:{index}/order/therapeutic_direction/dosage/dose/quantity_value|magnitude"] = safe_float(row['dose_val_rx'], 0)
        flat_json[f"{template_name}/medications/medication_order:{index}/order/therapeutic_direction/dosage/dose/quantity_value|unit"] = safe_str(row['dose_unit_rx'])
        flat_json[f"{template_name}/medications/medication_order:{index}/order/therapeutic_direction/dosage/dose_description"] =  safe_str(row['prod_strength'])

        flat_json[f"{template_name}/medications/medication_order:{index}/order/therapeutic_direction/dosage/timing_-_daily/timing_description"] =  safe_str(row['frequency']) # in theory I would use the frequency field, but the data its messy and I don't have that mach time

        if pd.notna(row['doses_per_24_hrs']):
            flat_json[f"{template_name}/medications/medication_order:{index}/order/medication_safety/total_daily_effective_dose/total_daily_amount|magnitude"] = row['doses_per_24_hrs']
            flat_json[f"{template_name}/medications/medication_order:{index}/order/medication_safety/total_daily_effective_dose/total_daily_amount|unit"] = "dose"

        flat_json[f"{template_name}/medications/medication_order:{index}/order/order_details/order_start_date_time"] =  safe_date(row['starttime'])
        flat_json[f"{template_name}/medications/medication_order:{index}/order/order_details/order_stop_date_time"] =  safe_date(row['stoptime'])
        flat_json[f"{template_name}/medications/medication_order:{index}/order/order_details/medication_order_summary/order_status|value"] = medication_order_status_map[row['status']][0]
        flat_json[f"{template_name}/medications/medication_order:{index}/order/order_details/medication_order_summary/order_status|code"] =  medication_order_status_map[row['status']][1]
        flat_json[f"{template_name}/medications/medication_order:{index}/order/order_details/medication_order_summary/order_status|terminology"] =  "local"
        flat_json[f"{template_name}/medications/medication_order:{index}/order/order_details/medication_order_summary/date_ordered_recommended:0"] =  safe_date(row['entertime'])
        flat_json[f"{template_name}/medications/medication_order:{index}/order/order_details/medication_order_summary/date_reviewed:0"] =  safe_date(row['verifiedtime'])
        flat_json[f"{template_name}/medications/medication_order:{index}/order/dispense_directions/dispense_instruction"] =  safe_str(row['dispensation'])

        flat_json[f"{template_name}/medications/medication_order:{index}/order/action_archetype_id"] =  'openEHR-EHR-ACTION.medication.v1'
        flat_json[f"{template_name}/medications/medication_order:{index}/narrative"] =  f"Medication order: {safe_str(row['prod_strength'])}"

        flat_json[f"{template_name}/medications/medication_order:{index}/language|code"] =  language
        flat_json[f"{template_name}/medications/medication_order:{index}/language|terminology"] = lan_terminology
        flat_json[f"{template_name}/medications/medication_order:{index}/encoding|code"] =  encoding
        flat_json[f"{template_name}/medications/medication_order:{index}/encoding|terminology"] =  enco_terminology
        index += 1

    # Medication administrations
    index = 0
    for _, row in medication_management.iterrows():
        ism_category = medication_management_ism_transition_map.get(row['event_txt'], "initial")
        flat_json[f"{template_name}/medications/medication_management:{index}/ism_transition/current_state|code"] = medication_management_ism_category_map[ism_category]
        flat_json[f"{template_name}/medications/medication_management:{index}/ism_transition/current_state|terminology"] = "openehr"
        flat_json[f"{template_name}/medications/medication_management:{index}/ism_transition/current_state|value"] = ism_category
        flat_json[f"{template_name}/medications/medication_management:{index}/medication_item"] = safe_str(row["medication"], "Unkown")
        flat_json[f"{template_name}/medications/medication_management:{index}/original_scheduled_date_time"] = safe_date(row["scheduletime"])
        flat_json[f"{template_name}/medications/medication_management:{index}/administration_details/administration_method:0"] = safe_str(row['administration_type'])

        flat_json[f"{template_name}/medications/medication_management:{index}/language|code"] = language
        flat_json[f"{template_name}/medications/medication_management:{index}/language|terminology"] = lan_terminology
        flat_json[f"{template_name}/medications/medication_management:{index}/encoding|code"] = encoding                        
        flat_json[f"{template_name}/medications/medication_management:{index}/encoding|terminology"] =  enco_terminology
        flat_json[f"{template_name}/medications/medication_management:{index}/time"] = safe_date(row["charttime"])
        index += 1

    # Vitals
    if pd.notna(VS):
        index = 0
        for key in VS.keys():
            section_data = VS[key]            
            filtered_transfers = transfers[transfers["eventtype"] == transfer_event_map[key]]
            if not filtered_transfers.empty:
                time = safe_date(filtered_transfers["intime"].iloc[0])
            
                # Body Temperature
                temp = section_data.get("Body Temperature")
                if temp is not None:
                    flat_json[f"{template_name}/vital_signs/body_temperature/any_event:{index}/temperature|magnitude"] = VS[key]["Body Temperature"]
                    flat_json[f"{template_name}/vital_signs/body_temperature/any_event:{index}/temperature|unit"] = "Cel"
                    flat_json[f"{template_name}/vital_signs/body_temperature/any_event:{index}/time"] = time
                    flat_json[f"{template_name}/vital_signs/body_temperature/any_event:{index}/comment"] = "These vitals have been automatically extracted by a LLM and may not be entirely accurate. For confirmed values, please refer to the original discharge summary."
                
                # Blood Pressure
                systolic = section_data.get("Systolic Blood Pressure")
                diastolic = section_data.get("Diastolic Blood Pressure")
                if systolic is not None and diastolic is not None:           
                    flat_json[f"{template_name}/vital_signs/blood_pressure/any_event:{index}/systolic|magnitude"] = VS[key]["Systolic Blood Pressure"]
                    flat_json[f"{template_name}/vital_signs/blood_pressure/any_event:{index}/systolic|unit"] =  "mm[Hg]"
                    flat_json[f"{template_name}/vital_signs/blood_pressure/any_event:{index}/diastolic|magnitude"] = VS[key]["Diastolic Blood Pressure"]
                    flat_json[f"{template_name}/vital_signs/blood_pressure/any_event:{index}/diastolic|unit"] = "mm[Hg]"
                    flat_json[f"{template_name}/vital_signs/blood_pressure/any_event:{index}/time"] = time
                    flat_json[f"{template_name}/vital_signs/blood_pressure/any_event:{index}/comment"] = "These vitals have been automatically extracted by a LLM and may not be entirely accurate. For confirmed values, please refer to the original discharge summary."

                # Heart Rate
                hr = section_data.get("Heart Rate")
                if hr is not None:
                        flat_json[f"{template_name}/vital_signs/pulse_heart_beat/any_event:{index}/rate|magnitude"] = VS[key]["Heart Rate"]
                        flat_json[f"{template_name}/vital_signs/pulse_heart_beat/any_event:{index}/rate|unit"] = "/min"
                        flat_json[f"{template_name}/vital_signs/pulse_heart_beat/any_event:{index}/time"] = time
                        flat_json[f"{template_name}/vital_signs/pulse_heart_beat/any_event:{index}/comment"] = "These vitals have been automatically extracted by a LLM and may not be entirely accurate. For confirmed values, please refer to the original discharge summary."

                # Respiratory Rate
                rr = section_data.get("Respiratory Rate")
                if rr is not None:                    
                    flat_json[f"{template_name}/vital_signs/respiration/any_event:{index}/rate|magnitude"] = VS[key]["Respiratory Rate"]
                    flat_json[f"{template_name}/vital_signs/respiration/any_event:{index}/rate|unit"] = "/min"
                    flat_json[f"{template_name}/vital_signs/respiration/any_event:{index}/time"] = time
                    flat_json[f"{template_name}/vital_signs/respiration/any_event:{index}/comment"] = "These vitals have been automatically extracted by a LLM and may not be entirely accurate. For confirmed values, please refer to the original discharge summary."

                # Oxygen Saturation
                spo = section_data.get("Oxygen Saturation")
                if spo is not None and safe_float(VS[key]["Oxygen Saturation"]) is not None:
                    flat_json[f"{template_name}/vital_signs/pulse_oximetry/any_event:{index}/spo|numerator"] = safe_float(VS[key]["Oxygen Saturation"])
                    flat_json[f"{template_name}/vital_signs/pulse_oximetry/any_event:{index}/spo|denominator"] = 100
                    flat_json[f"{template_name}/vital_signs/pulse_oximetry/any_event:{index}/time"] = time
                    flat_json[f"{template_name}/vital_signs/pulse_oximetry/any_event:{index}/comment"] = "These vitals have been automatically extracted by a LLM and may not be entirely accurate. For confirmed values, please refer to the original discharge summary."

            index += 1    

    flat_json[f"{template_name}/language|code"] = language
    flat_json[f"{template_name}/language|terminology"] = lan_terminology
    flat_json[f"{template_name}/territory|code"] = territory
    flat_json[f"{template_name}/territory|terminology"] = ter_terminology
    flat_json[f"{template_name}/composer|name"] = "MIMIC-IV to openEHR"

    return flat_json



# === Check structure validity and commit compositions ===

def try_parse_json(output_str):
    try:
        parsed = json.loads(output_str)
        return parsed
    except json.JSONDecodeError as e:
        return None
    
subfields = [
    "Body Temperature", "Systolic Blood Pressure", "Diastolic Blood Pressure",
    "Heart Rate", "Respiratory Rate", "Oxygen Saturation"]

allowed_structure = {"Emergency Department": subfields, "Transfer": subfields, "Admission": subfields, "Discharge": subfields, "Unknown": subfields,}

def is_valid_structure(json_obj):
    if not isinstance(json_obj, dict):
        return None
    for main_key, sub_obj in json_obj.items():
        if main_key not in allowed_structure:
            return False
        if not isinstance(sub_obj, dict):
            return None
        for sub_key in sub_obj:
            if sub_key not in allowed_structure[main_key]:
                return False
    return True

def commit(local_path, filename, template_id):
    done_folder = os.path.join(local_path, "done")
    error_folder = os.path.join(local_path, "error")
    os.makedirs(done_folder, exist_ok=True)
    os.makedirs(error_folder, exist_ok=True)
    log_path=f"{local_path}/ehr_log.csv"
    log_exists = os.path.exists(log_path)
    
    with open(log_path, "a", buffering=1) as log_file:
        if not log_exists:
            log_file.write("filename,ehr_id,status\n")

        path = f"{local_path}/{filename}"
        ehr_id = str(uuid.uuid4())
        print(f"Processing {filename}...")

        try:
            # === Create EHR ===
            ehr_status = ehrbase.create_ehr(ehr_id)
            print("EHR created")
            if not (200 <= ehr_status < 300):
                print(f"Failed to create EHR for {ehr_id}, status {ehr_status}")
                shutil.move(path, os.path.join(error_folder, filename))
                log_file.write(f"{filename},{ehr_id},EHR_FAIL_{ehr_status}\n")

            # === Commit composition ===
            comp_status = ehrbase.commit_composition(path, template_id, ehr_id)
            if 200 <= comp_status < 300:
                shutil.move(path, os.path.join(done_folder, filename))
                print(f"Committed: {filename}")
                log_file.write(f"{filename},{ehr_id},COMMITTED_{comp_status }\n")
            else:
                shutil.move(path, os.path.join(error_folder, filename))
                print(f"Composition commit failed: {comp_status}")
                log_file.write(f"{filename},{ehr_id},COMP_FAIL_{comp_status}\n")
        except Exception as e:
            print(f"Error processing {filename}: {e}")
            shutil.move(path, os.path.join(error_folder, filename))
            log_file.write(f"{filename},{ehr_id},EXCEPTION_{str(e).replace(',', ';')}\n")



def main():

    icd_code = "I50%" # Heart failure ICD-10 code
    engine = connect_to_postgres()
    cohort = get_cohort(icd_code, engine)

    subject_ids = cohort.iloc[0:1500]
    subject_ids = subject_ids['subject_id'].tolist() # cohort['subject_id'].tolist()
    hadm_ids = get_last_admission(subject_ids, engine)
    hadm_ids = hadm_ids['hadm_id'].tolist()
    hadm_ids_with_notes = get_admissions_with_notes(hadm_ids, engine)
    hadm_ids_with_notes = hadm_ids_with_notes['hadm_id'].tolist()
    hadm_ids_without_notes = list(set(hadm_ids) - set(hadm_ids_with_notes))

    print("All admissions: ", len(hadm_ids))
    print("Admissions with notes: ", len(hadm_ids_with_notes))
    print("Admissions without notes: ", len(hadm_ids_without_notes))

    local_path_notes = "data/notes"
    local_path_compositions = "data/compositions"
    remote_path = "/data/home/asirui24/notes"

    # Get set of already committed filenames from the log
    processed_files = set()
    log_path = os.path.join(local_path_compositions, "ehr_log.csv")
    if os.path.exists(log_path):
        with open(log_path, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                    processed_files.add(row["filename"])

    batch_ids = [] #['0-500', '500-1000', '1000-1500', '1500-2000', '2000-2500', '2500-3000', '3000-3500']
    batch_size = 500
    for start in range(0, len(hadm_ids_with_notes), batch_size):
        batch = hadm_ids_with_notes[start:start+batch_size]
        batch_id = f"{start}-{start+batch_size}"
        batch_ids.append(batch_id)
        notes = get_notes(batch, engine)
        ie.process_notes(notes, batch_id, local_path_notes)

    print(batch_ids)
    ssh = ie.connect_with_gpu()
    ie.send_notes(ssh, local_path_notes, remote_path, batch_ids)
    ie.inference(ssh, batch_ids)
    ie.close_gpu_connection(ssh)

    batch_size = 100
    for start in range(0, len(hadm_ids_without_notes), batch_size):
        batch = hadm_ids_without_notes[start:start+batch_size]
        hadm_ids = tuple(batch)

        admissions = get_admissions(hadm_ids, engine)
        services = get_services(hadm_ids, engine)
        transfers = get_transfers(hadm_ids, engine)
        diagnoses = get_diagnoses(hadm_ids, engine)
        procedures = get_procedures(hadm_ids, engine)
        orders = get_orders(hadm_ids, engine)
        medication_order = get_medication_order(hadm_ids, engine)
        medication_management = get_medication_management(hadm_ids, engine)

        # Iterate through each admssion
        for _, admission in admissions.iterrows():
            
            hadm_id = admission["hadm_id"]
            file_name = f"{admission['subject_id']}_{admission['hadm_id']}.json"
            if not file_name in processed_files:
                composition = structure_template(admission, services[services['hadm_id'] == hadm_id], transfers[transfers['hadm_id'] == hadm_id], diagnoses[diagnoses['hadm_id'] == hadm_id], procedures[procedures['hadm_id'] == hadm_id], orders[orders['hadm_id'] == hadm_id], medication_order[medication_order['hadm_id'] == hadm_id], medication_management[medication_management['hadm_id'] == hadm_id])
                composition = {k: v for k, v in composition.items() if v is not None}
                with open(f"{local_path_compositions}/{file_name}", "w", encoding="utf-8") as f:
                    json.dump(composition, f, indent=2)
                print(f"{local_path_compositions}/{file_name}")
                commit(local_path_compositions, file_name, "mimiciv2openehr7")
            else: 
                print(file_name, " already processed")   

    # batch_ids = ['0-500', '500-1000', '1000-1500', '1500-2000', '2000-2500', '2500-3000']
    ssh = ie.connect_with_gpu()
    ie.retrieve_notes(ssh, local_path_notes, remote_path, batch_ids)

    batch_size = 100
    for start in range(0, len(hadm_ids_with_notes), batch_size):
        batch = hadm_ids_with_notes[start:start+batch_size]
        batch_id = f"{start}-{start+batch_size}"
        hadm_ids = tuple(batch)

        admissions = get_admissions(hadm_ids, engine)
        services = get_services(hadm_ids, engine)
        transfers = get_transfers(hadm_ids, engine)
        diagnoses = get_diagnoses(hadm_ids, engine)
        procedures = get_procedures(hadm_ids, engine)
        orders = get_orders(hadm_ids, engine)
        medication_order = get_medication_order(hadm_ids, engine)
        medication_management = get_medication_management(hadm_ids, engine)

        print("contents queried")

        # === Load vitals and chief complaints ===
        with open(f"{local_path_notes}/output_batch_{batch_id}.json", "r") as f:
            vitals_data = json.load(f)
            for entry in vitals_data:
                parsed = try_parse_json(entry["vitals"])
                entry["vitals"] = parsed if parsed and is_valid_structure(parsed) else None
        with open(f"{local_path_notes}/CC_{batch_id}.json", "r") as f:
            cc_data = json.load(f)
        VS = {entry["hadm_id"]: entry["vitals"] for entry in vitals_data}
        CC = {entry["hadm_id"]: entry["chief_complaint"] for entry in cc_data}

        for _, admission in admissions.iterrows():
            
            hadm_id = admission["hadm_id"]
            file_name = f"{admission['subject_id']}_{admission['hadm_id']}.json"
            
            if not file_name in processed_files:     
                print(hadm_id)
                print(CC.get(hadm_id), VS.get(hadm_id))

                composition = structure_template(admission, services[services['hadm_id'] == hadm_id], transfers[transfers['hadm_id'] == hadm_id], diagnoses[diagnoses['hadm_id'] == hadm_id], procedures[procedures['hadm_id'] == hadm_id], orders[orders['hadm_id'] == hadm_id], medication_order[medication_order['hadm_id'] == hadm_id], medication_management[medication_management['hadm_id'] == hadm_id], CC.get(hadm_id), VS.get(hadm_id))
                composition = {k: v for k, v in composition.items() if v is not None}

                with open(f"{local_path_compositions}/{file_name}", "w", encoding="utf-8") as f:
                    json.dump(composition, f, indent=2)
                
                print(f"{local_path_compositions}/{file_name}")
                commit(local_path_compositions, file_name, "mimiciv2openehr7")

            else: 
                print(file_name, " already processed")

    engine.dispose()

    # === Repeat failed compositions ===
    failed_compositions = set()
    log_path = os.path.join(local_path_compositions, "ehr_log.csv")
    if os.path.exists(log_path):
        with open(log_path, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if not row.get("status", "").startswith("COMMITTED"):
                    failed_compositions.add(row["filename"])

    for file_name in failed_compositions:
        file_path = f"{local_path_compositions}/error/{file_name}"
        if os.path.exists(file_path):
            print(f"Retrying commit for: {file_name}")
            try:
                commit(f"{local_path_compositions}/error", file_name, "mimiciv2openehr7")
            except Exception as e:
                print(f"Retry failed for {file_name}: {e}")
        else:
            print(f"File not found: {file_name}")                    

if __name__ == "__main__":
    start_time = time.time()
    main()
    end_time = time.time()
    print(f"finished in {end_time - start_time:.2f} seconds")