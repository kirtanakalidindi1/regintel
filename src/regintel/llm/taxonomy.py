"""Fixed label sets. The LLM, the API, the review screen and the evaluation all use these."""

TOPICS = {
    "recall": "A product is being recalled or withdrawn from the market or supply chain.",
    "safety_communication": "New or updated safety information, risks or advice to healthcare "
    "professionals or patients, without a recall. Also used for safety digests.",
    "labelling_change": "Changes or corrections to product information: SmPC, PIL, US label, "
    "artwork, dosing tables or instructions for use, including when issued as a defect notice.",
    "authorisation_change": "A marketing authorisation, approval or certification is withdrawn, "
    "suspended, varied or newly restricted.",
    "clinical_trials": "Clinical trial regulation, CTA requirements, protocol or trial conduct.",
    "supply_shortage": "Shortages, discontinuations or supply disruption.",
    "policy_guidance": "Regulatory policy, guidance, process or system changes.",
    "other": "None of the above.",
}

PRODUCT_TYPES = {
    "medicine": "Small-molecule or other conventional medicinal products.",
    "medical_device": "Medical devices, including in vitro diagnostics and software as a device.",
    "vaccine_biologic": "Vaccines, monoclonal antibodies and other biologics.",
    "cell_gene_therapy": "Cell and gene therapies and other ATMPs.",
    "blood_product": "Blood components and blood products.",
    "other": "Anything else, or not product-specific.",
}

THERAPEUTIC_AREAS = [
    "oncology",
    "haematology",
    "cardiovascular",
    "neurology",
    "psychiatry",
    "infectious_disease",
    "immunology_vaccines",
    "respiratory",
    "endocrine_metabolic",
    "gastroenterology",
    "renal",
    "musculoskeletal",
    "ophthalmology",
    "dermatology",
    "womens_health",
    "paediatrics",
    "other_multiple",
]

RELEVANCE = {
    "high": "Immediate action, or reports of death or serious harm. Includes FDA Class I and "
    "MHRA Class 1 recalls, and withdrawal or suspension of an authorisation.",
    "medium": "Action needed within days. Includes FDA Class II recalls, MHRA Class 2 and "
    "Class 3 recalls, and dosing, labelling or prescribing changes clinicians must act on.",
    "low": "Informational or caution only. Includes FDA Class III recalls, MHRA Class 4 defect "
    "notifications, campaigns, digests and process updates.",
}

RELEVANCE_RULES = """\
- Content outranks class number: any report of death or serious harm is high, and an MHRA \
Class 4 notice that changes clinical practice (for example a dosing error) is medium.
- MHRA recall classes run from Class 1 (most serious) to Class 4 (caution in use, no recall).
- Digests that bundle several notices (safety roundups, weekly field safety notice lists) are \
low, because each item is published separately."""

ACTION_OWNERS = {
    "regulatory_affairs": "Submissions, variations, authorisation status, health authority "
    "interactions.",
    "labelling": "SmPC, PIL, US label, artwork or instructions for use need assessing or "
    "updating.",
    "pharmacovigilance": "Safety signals, risk management, adverse event monitoring.",
    "clinical_operations": "Ongoing or planned clinical trials are affected.",
    "quality_supply": "Batches, manufacturing, distribution, stock or shortages.",
    "healthcare_professionals": "Prescribers, pharmacists or clinicians must change practice.",
}

LABELLING_DOCUMENTS = {
    "smpc": "Summary of Product Characteristics",
    "pil": "Patient information leaflet",
    "us_label": "US prescribing information or Medication Guide",
    "artwork": "Carton, container label or packaging artwork",
    "ifu": "Instructions for use",
}


def describe(labels: dict[str, str]) -> str:
    return "\n".join(f"- {name}: {meaning}" for name, meaning in labels.items())
