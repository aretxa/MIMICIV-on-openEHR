-- Validate the MIMIC-IV tables are built correctly by checking against known row counts

-- I coudn't find the validation row counts udpated for MIMIC-IV-3.1 version, so I got them for version 2.2 
-- and updated the hosp numbers when I managed to load the full dataset on a single time. 
-- It could be possible that it's not completelly accurate, but it should be close enough to validate the data.

-- mimiciv - note

WITH expected AS
(
    SELECT 'discharge'          AS tbl, 331793   AS row_count UNION ALL
    SELECT 'radiology'          AS tbl, 2321355  AS row_count UNION ALL
    SELECT 'discharge_detail'   AS tbl, 186138   AS row_count UNION ALL
    SELECT 'radiology_detail'   AS tbl, 6046121  AS row_count
)
, observed as
(
    SELECT 'discharge'          AS tbl, COUNT(*) AS row_count FROM mimiciv_note.discharge UNION ALL
    SELECT 'radiology'          AS tbl, COUNT(*) AS row_count FROM mimiciv_note.radiology UNION ALL
    SELECT 'discharge_detail'   AS tbl, COUNT(*) AS row_count FROM mimiciv_note.discharge_detail UNION ALL
    SELECT 'radiology_detail'   AS tbl, COUNT(*) AS row_count FROM mimiciv_note.radiology_detail
)
SELECT
    exp.tbl
    , exp.row_count AS expected_count
    , obs.row_count AS observed_count
    , CASE
        WHEN exp.row_count = obs.row_count
        THEN 'PASSED'
        ELSE 'FAILED'
    END AS ROW_COUNT_CHECK
FROM expected exp
INNER JOIN observed obs
  ON exp.tbl = obs.tbl
ORDER BY exp.tbl
;


-- mimiciv - hosp

WITH expected AS
(
    SELECT 'admissions' AS tbl,         546028 AS row_count UNION ALL
    SELECT 'd_hcpcs' AS tbl,            89208 AS row_count UNION ALL
    SELECT 'd_icd_diagnoses' AS tbl,    112107 AS row_count UNION ALL
    SELECT 'd_icd_procedures' AS tbl,   86423 AS row_count UNION ALL
    SELECT 'd_labitems' AS tbl,         1650 AS row_count UNION ALL
    SELECT 'diagnoses_icd' AS tbl,      6364488 AS row_count UNION ALL
    SELECT 'drgcodes' AS tbl,           761856 AS row_count UNION ALL
    SELECT 'emar' AS tbl,               42808593 AS row_count UNION ALL
    SELECT 'emar_detail' AS tbl,        87371064 AS row_count UNION ALL
    SELECT 'hcpcsevents' AS tbl,        186074 AS row_count UNION ALL
    SELECT 'labevents' AS tbl,          158374764 AS row_count UNION ALL
    SELECT 'microbiologyevents' AS tbl, 3988224 AS row_count UNION ALL
    SELECT 'omr' AS tbl,                7753027 AS row_count UNION ALL
    SELECT 'patients' AS tbl,           364627 AS row_count UNION ALL
    SELECT 'pharmacy' AS tbl,           17847567 AS row_count UNION ALL
    SELECT 'poe' AS tbl,                52212109 AS row_count UNION ALL
    SELECT 'poe_detail' AS tbl,         8504982 AS row_count UNION ALL
    SELECT 'prescriptions' AS tbl,      20292611 AS row_count UNION ALL
    SELECT 'procedures_icd' AS tbl,     859655 AS row_count UNION ALL
    SELECT 'provider' AS tbl,           42244 AS row_count UNION ALL
    SELECT 'services' AS tbl,           593071 AS row_count UNION ALL
    SELECT 'transfers' AS tbl,          2413581 AS row_count
)
, observed as
(
    SELECT 'admissions' AS tbl, count(*) AS row_count FROM mimiciv_hosp.admissions UNION ALL
    SELECT 'd_hcpcs' AS tbl, count(*) AS row_count FROM mimiciv_hosp.d_hcpcs UNION ALL
    SELECT 'd_icd_diagnoses' AS tbl, count(*) AS row_count FROM mimiciv_hosp.d_icd_diagnoses UNION ALL
    SELECT 'd_icd_procedures' AS tbl, count(*) AS row_count FROM mimiciv_hosp.d_icd_procedures UNION ALL
    SELECT 'd_labitems' AS tbl, count(*) AS row_count FROM mimiciv_hosp.d_labitems UNION ALL
    SELECT 'diagnoses_icd' AS tbl, count(*) AS row_count FROM mimiciv_hosp.diagnoses_icd UNION ALL
    SELECT 'drgcodes' AS tbl, count(*) AS row_count FROM mimiciv_hosp.drgcodes UNION ALL
    SELECT 'emar' AS tbl, count(*) AS row_count FROM mimiciv_hosp.emar UNION ALL
    SELECT 'emar_detail' AS tbl, count(*) AS row_count FROM mimiciv_hosp.emar_detail UNION ALL
    SELECT 'hcpcsevents' AS tbl, count(*) AS row_count FROM mimiciv_hosp.hcpcsevents UNION ALL
    SELECT 'labevents' AS tbl, count(*) AS row_count FROM mimiciv_hosp.labevents UNION ALL
    SELECT 'microbiologyevents' AS tbl, count(*) AS row_count FROM mimiciv_hosp.microbiologyevents UNION ALL
    SELECT 'omr' AS tbl, count(*) AS row_count FROM mimiciv_hosp.omr UNION ALL
    SELECT 'patients' AS tbl, count(*) AS row_count FROM mimiciv_hosp.patients UNION ALL
    SELECT 'pharmacy' AS tbl, count(*) AS row_count FROM mimiciv_hosp.pharmacy UNION ALL
    SELECT 'poe' AS tbl, count(*) AS row_count FROM mimiciv_hosp.poe UNION ALL
    SELECT 'poe_detail' AS tbl, count(*) AS row_count FROM mimiciv_hosp.poe_detail UNION ALL
    SELECT 'prescriptions' AS tbl, count(*) AS row_count FROM mimiciv_hosp.prescriptions UNION ALL
    SELECT 'procedures_icd' AS tbl, count(*) AS row_count FROM mimiciv_hosp.procedures_icd UNION ALL
    SELECT 'provider' AS tbl, count(*) AS row_count FROM mimiciv_hosp.provider UNION ALL
    SELECT 'services' AS tbl, count(*) AS row_count FROM mimiciv_hosp.services UNION ALL
    SELECT 'transfers' AS tbl, count(*) AS row_count FROM mimiciv_hosp.transfers
)
SELECT
    exp.tbl
    , exp.row_count AS expected_count
    , obs.row_count AS observed_count
    , CASE
        WHEN exp.row_count = obs.row_count
        THEN 'PASSED'
        ELSE 'FAILED'
    END AS ROW_COUNT_CHECK
FROM expected exp
INNER JOIN observed obs
  ON exp.tbl = obs.tbl
ORDER BY exp.tbl
;


/*
-- mimiciv - icu

WITH expected AS
(
    SELECT 'icustays' AS tbl,           73181 AS row_count UNION ALL
    SELECT 'd_items' AS tbl,            4014 AS row_count UNION ALL
    SELECT 'chartevents' AS tbl,        313645063 AS row_count UNION ALL
    SELECT 'datetimeevents' AS tbl,     7112999 AS row_count UNION ALL
    SELECT 'inputevents' AS tbl,        8978893 AS row_count UNION ALL
    SELECT 'outputevents' AS tbl,       4234967 AS row_count UNION ALL
    SELECT 'procedureevents' AS tbl,    696092 AS row_count
)
, observed as
(
    SELECT 'icustays' AS tbl, count(*) AS row_count FROM mimiciv_icu.icustays UNION ALL
    SELECT 'chartevents' AS tbl, count(*) AS row_count FROM mimiciv_icu.chartevents UNION ALL
    SELECT 'd_items' AS tbl, count(*) AS row_count FROM mimiciv_icu.d_items UNION ALL
    SELECT 'datetimeevents' AS tbl, count(*) AS row_count FROM mimiciv_icu.datetimeevents UNION ALL
    SELECT 'inputevents' AS tbl, count(*) AS row_count FROM mimiciv_icu.inputevents UNION ALL
    SELECT 'outputevents' AS tbl, count(*) AS row_count FROM mimiciv_icu.outputevents UNION ALL
    SELECT 'procedureevents' AS tbl, count(*) AS row_count FROM mimiciv_icu.procedureevents
)
SELECT
    exp.tbl
    , exp.row_count AS expected_count
    , obs.row_count AS observed_count
    , CASE
        WHEN exp.row_count = obs.row_count
        THEN 'PASSED'
        ELSE 'FAILED'
    END AS ROW_COUNT_CHECK
FROM expected exp
INNER JOIN observed obs
  ON exp.tbl = obs.tbl
ORDER BY exp.tbl
;
*/