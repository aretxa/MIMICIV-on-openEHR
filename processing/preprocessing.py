"""
MIMIC-IV to openEHR Preprocessing Script
-------------------------------------

This script connects to the MIMIC-IV PostgreSQL database and performs preprocessing 
on diagnosis records to map ICD-9 codes to ICD-10 using an external mapping file. 

Main Steps:
-----------
1. Connect to PostgreSQL database
2. Load admissions and diagnoses tables
3. Use a mapping file to convert ICD-9 codes to ICD-10
4. Add a new column 'icd_code_v2' to store the unified ICD-10 code
5. Save the updated codes back to the PostgreSQL database
6. Build a heart failure patient cohort (ICD-10 code 'I50%')
7. Merge demographic information for basic cohort characterization

"""

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text

# === Database connection ===
DB_NAME = "mimic"
DB_USER = "postgres"
DB_PASSWORD = "sd98hS&GD3F4"
DB_HOST = "localhost"
DB_PORT = "5432"

engine = create_engine(f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

# === Load data ===
diag = pd.read_sql("SELECT * FROM mimic.mimiciv_hosp.diagnoses_icd", engine)
icd_map = pd.read_csv("./ICD9_to_ICD10_mapping.txt", delimiter="\t")
icd_map["diagnosis_description"] = icd_map["diagnosis_description"].str.lower()

# === ICD-9 to ICD-10 Mapping ===
def standardize_icd(mapping: pd.DataFrame, diag: pd.DataFrame, map_code_col="diagnosis_code", root=True):
    errors = []
    col_name = "root_icd10_convert"
    diag[col_name] = diag["icd_code"].values

    def icd_9to10(icd):
        if root:
            icd = icd[:3]
        matches = mapping[mapping[map_code_col] == icd]
        if matches.empty:
            errors.append(f"ICD NOT FOUND: {icd}")
            return np.nan
        return matches.icd10cm.iloc[0]

    for code, group in diag[diag.icd_version == 9].groupby("icd_code"):
        new_code = icd_9to10(code)
        diag.loc[group.index, col_name] = new_code

    diag["root"] = diag[col_name].apply(lambda x: x[:3] if isinstance(x, str) else np.nan)

standardize_icd(icd_map, diag)

# === Add column and update PostgreSQL ===
add_column = text("""
DO $$ 
BEGIN 
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'diagnoses_icd' 
        AND column_name = 'icd_code_v2'
    ) THEN 
        ALTER TABLE mimiciv_hosp.diagnoses_icd ADD COLUMN icd_code_v2 VARCHAR(10);
    END IF;
END $$;
""")

df_temp = diag[["hadm_id", "seq_num", "root_icd10_convert"]]
df_temp.to_sql("temp_table", engine, if_exists="replace", index=False)

load_codes = text("""
UPDATE mimiciv_hosp.diagnoses_icd
SET icd_code_v2 = temp_table.root_icd10_convert
FROM temp_table
WHERE diagnoses_icd.hadm_id = temp_table.hadm_id
  AND diagnoses_icd.seq_num = temp_table.seq_num;
""")

with engine.begin() as conn:
    conn.execute(add_column)
    conn.execute(load_codes)

# === Build cohort of interest (e.g., Heart Failure) ===
diag.dropna(subset=["root"], inplace=True)
cohort = pd.DataFrame(
    diag[diag.root.str.contains("I50")].subject_id.unique(), columns=["subject_id"]
)

# === Merge demographics ===
query = text("""
WITH selected_patients AS (
    SELECT DISTINCT di.subject_id
    FROM mimiciv_hosp.diagnoses_icd AS di
    WHERE di.icd_code_v2 LIKE 'I50%'
)
SELECT DISTINCT ON (a.subject_id) 
    a.subject_id,
    a.insurance,
    a.marital_status, 
    a.race,
    p.gender,
    p.anchor_age,
    p.anchor_year,
    p.anchor_year_group,
    p.dod
FROM mimiciv_hosp.admissions AS a
JOIN selected_patients AS sp ON a.subject_id = sp.subject_id
LEFT JOIN mimiciv_hosp.patients AS p ON a.subject_id = p.subject_id
ORDER BY a.subject_id, a.hadm_id DESC;
""")

demographics = pd.read_sql(query, engine)

# === Check cohort consistency ===
demographics_subject_ids = set(demographics['subject_id'])
cohort_subject_ids = set(cohort['subject_id'])

print("Do subject_id values match?", demographics_subject_ids == cohort_subject_ids)
print("Missing in demographics:", cohort_subject_ids - demographics_subject_ids)
print("Missing in cohort:", demographics_subject_ids - cohort_subject_ids)
