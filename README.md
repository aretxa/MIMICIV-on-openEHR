# Standardization of EHRs: MIMIC-IV on openEHR

This repository contains the complete codebase and related resources developed for the Final Degree Project titled "Standardization of EHRs: MIMIC-IV on openEHR". The project focuses on enabling the migration of structured and unstructured data from the MIMIC-IV database to the openEHR standard using rule-based and NLP-based approaches.

## Project description
Electronic health records (EHRs) play a crucial role in modern healthcare, enabling the digital storage, use, and exchange of patient information. However, interoperability remains a challenge due to the variety of existing systems and formats. While the MIMIC-IV database is already structured and available in formats such as FHIR, its transformation into the openEHR standard, a framework for standardized, interoperable EHRs, can provide additional benefits, particularly for research and interoperability purposes.
This project focuses on developing a pipeline for converting both structured and unstructured data into the openEHR format, ensuring standardized and reusable clinical information. By presenting an implementation path and creating an openEHR-compliant dataset, this work aims to facilitate data integration, support research applications, and contribute to healthcare data interoperability efforts.


## Repository Structure

```
.
├── archetype_oracle/             # Archetypes and tools to extract their metadata
├── data/                         # Migration logs, emissions logs, and empty templates
├── db/
│   ├── ehrbase/                  # EHRbase setup and openEHR template
│   └── mimiciv/                  # Scripts to build and validate the MIMIC-IV database (no data included)
├── processing/                   # Migration pipeline, NLP scripts, validation tools
│   ├── gpu_scripts/              # GPU-enabled processing scripts and prompts
│   └── validation/               # Evaluation and dataset creation tools
```

## Setup Instructions
1. Clone this repository
2. Install dependencies
3. Prepare MIMIC-IV data
    - Download MIMIC-IV from PhysioNet after completing credentialing
    - Load the data into PostgreSQL using the scripts in db/mimiciv
4. Set up EHRbase
5. Run the pipeline

## Important Notice on Data
This repository does not contain any MIMIC-IV data or derived patient information.
- All included files are either synthetic, structural, or logs generated during project execution.
- Any user wishing to work with MIMIC-IV must independently obtain the dataset via PhysioNet and comply with its Data Use Agreement (DUA).
- The scripts in db/mimiciv are provided solely to create the database schema and load the data you have obtained through the proper licensing process.

## Resources used
- MIMIC-IV
Johnson AEW, Pollard TJ, Shen L, et al. MIMIC-IV (version 2.0). PhysioNet. 2022.
DOI: 10.13026/s6n6-xd98

- [PostgreSQL](https://www.postgresql.org/)

- [openEHR](https://www.openehr.org/)

- [EHRbase](https://github.com/ehrbase/ehrbase/)

- [LLaMa3 8B Instruct](http://arxiv.org/abs/2407.21783/) - DOI: 10.48550/arXiv.2407.21783

- [Meditron3 8B](https://huggingface.co/OpenMeditron/Meditron3-8B/) - paper in progress

- [Deepseek LLM 7B Chat](http://arxiv.org/abs/2401.02954/) - DOI: 10.48550/arXiv.2401.02954

- [CodeCarbon](https://codecarbon.io/)

## Citation
If you use this code or base your work on this project, please cite this project: 
Asier Ruiz de Aretxabaleta Berganza. Standardization of EHRs: MIMIC-IV on openEHR. Final Degree Project, Mondragon Unibertsitatea and Halmstad University, 2024-2025.

## License
This project is licensed under the Creative Commons Attribution-NonCommercial-ShareAlike (CC BY-NC-SA). Commercial use of the original work and any derivative works is not permitted, and distribution of derivative works must be under a licence equal to that governing the original work.

For questions, suggestions, or collaborations, feel free to open an issue or contact the author.