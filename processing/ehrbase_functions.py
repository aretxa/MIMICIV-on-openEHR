"""
MIMIC-IV to openEHR EHRbase Script
-------------------------------------

This module provides utility functions to interact with an EHRbase server via REST API.

Main functionalities:
- Server operations:
    * Check server status.

- Template management:
    * List available templates.
    * Upload new templates from ADL files.
    * Delete existing templates.

- EHR management:
    * Create new EHRs with a specified identifier.
    * Delete EHRs by identifier.

- Composition management:
    * Retrieve example compositions in different formats (FLAT, STRUCTURED, XML, JSON).
    * Commit compositions to an EHR from local files.
    * Retrieve committed compositions by ID.

Key components:
- check_server_status: Verify that the EHRbase server is reachable.
- list_templates / upload_template / delete_template: Manage archetype templates.
- create_ehr / delete_ehr: Create and remove EHR records.
- composition_example: Fetch example composition data for a template.
- commit_composition: Store a new composition in the EHRbase server.
- get_composition: Retrieve an existing composition.

"""


import requests

# === Server ===
def check_server_status():
    URL = "http://localhost:8080/ehrbase/rest/status"
    response = requests.get(URL)
    return response.status_code


# === Templates ===
def list_templates():
    URL = "http://localhost:8080/ehrbase/rest/openehr/v1/definition/template/adl1.4"
    response = requests.get(URL)
    return response.json()

def upload_template(path):
    URL = "http://localhost:8080/ehrbase/rest/openehr/v1/definition/template/adl1.4"
    with open(path, 'r') as file:
        data = file.read()
    headers = {'Content-Type': 'application/xml'}
    response = requests.post(URL, data=data, headers=headers)
    return response.status_code

def delete_template(template_id):
    URL = f"http://localhost:8080/ehrbase/rest/admin/template/{template_id}"
    response = requests.delete(URL)
    return response.status_code


# === EHRs ===
def create_ehr(ehr_id):
    URL = f"http://localhost:8080/ehrbase/rest/openehr/v1/ehr/{ehr_id}"
    body = {
        "_type": "EHR_STATUS",    
        "archetype_node_id": "openEHR-EHR-EHR_STATUS.generic.v1",
        "name": {
            "_type": "DV_TEXT",
            "value": "EHR status"
        },
        "uid": {
            "_type": "OBJECT_VERSION_ID",
            "value": f"{ehr_id}::local.ehrbase.org::1"
        },
        "subject": {
            "_type": "PARTY_SELF"
        },
        "is_queryable": True,
        "is_modifiable": True
    }
    response = requests.put(URL, json=body, timeout=(10, 60))
    return response.status_code

def delete_ehr(ehr_id):
    URL = f"http://localhost:8080/ehrbase/rest/admin/ehr/{ehr_id}"
    response = requests.delete(URL)
    return response.status_code


# === Compositions ===
def composition_example(template_id, ehr_id, format="FLAT"):
    URL = f"http://localhost:8080/ehrbase/rest/openehr/v1/ehr/{ehr_id}/composition?templateId={template_id}"
    formats = {
        "XML": 'application/xml', 
        "JSON": 'application/json', 
        "FLAT": 'application/openehr.wt.flat.schema+json', 
        "STRUCTURED": 'application/openehr.wt.structured.schema+json'
    }
    headers={"Accept": formats[format]}
    response = requests.get(URL, headers=headers)
    return response.status_code, response.text

def commit_composition(path, template_id, ehr_id, format="FLAT", timeout=(10, 300)):
    URL = f"http://localhost:8080/ehrbase/rest/openehr/v1/ehr/{ehr_id}/composition?templateId={template_id}"
    with open(path, 'r') as file:
        data = file.read()
    formats = {
        "XML": 'application/xml', 
        "JSON": 'application/json', 
        "FLAT": 'application/openehr.wt.flat.schema+json', 
        "STRUCTURED": 'application/openehr.wt.structured.schema+json'
    }
    headers={"Content-Type": formats[format], "Accept": formats[format]}
    response = requests.post(URL, headers=headers, data=data, timeout=timeout)
    return response.status_code

def get_composition(ehr_id, comp_id, format="FLAT"):
    URL = f"http://localhost:8080/ehrbase/rest/openehr/v1/ehr/{ehr_id}/composition/{comp_id}"
    formats = {
        "XML": 'application/xml', 
        "JSON": 'application/json', 
        "FLAT": 'application/openehr.wt.flat+json', 
        "STRUCTURED": 'application/openehr.wt.structured+json'
    }
    headers = {"Accept": formats[format]}
    response = requests.get(URL, headers=headers)
    print(response.text)
    return response.status_code, response.text