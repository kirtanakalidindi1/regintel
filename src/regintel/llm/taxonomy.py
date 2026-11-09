"""Fixed label sets. The LLM, the reviewer UI and the evaluation set all use these lists."""

TOPICS = {
    "recall": "A product is being recalled or withdrawn from the market or supply chain.",
    "safety_communication": "New or updated safety information, risks, adverse events or advice "
    "to healthcare professionals or patients, without a recall.",
    "labelling_change": "Changes to product information, labels, SmPC, PIL or instructions for use.",
    "authorisation_change": "A marketing authorisation, approval or certification is withdrawn, "
    "suspended, varied or newly restricted.",
    "supply_shortage": "Shortages, discontinuations or supply disruption.",
    "policy_guidance": "Regulatory policy, guidance, process or system changes.",
    "other": "None of the above.",
}

PRODUCT_TYPES = {
    "medicine": "Small-molecule or other conventional medicinal products.",
    "medical_device": "Medical devices, including in vitro diagnostics and software as a device.",
    "vaccine_biologic": "Vaccines, biologics, cell and gene therapies.",
    "blood_product": "Blood components and blood products.",
    "other": "Anything else, or not product-specific.",
}

THERAPEUTIC_AREAS = [
    "oncology",
    "cardiovascular",
    "neurology",
    "psychiatry",
    "infectious_disease",
    "immunology_vaccines",
    "respiratory",
    "endocrine_metabolic",
    "gastroenterology",
    "haematology",
    "dermatology",
    "womens_health",
    "paediatrics",
    "other_multiple",
]

RELEVANCE = {
    "high": "Immediate action needed: e.g. Class I recall, reports of death or serious harm, "
    "or a withdrawal/suspension of authorisation.",
    "medium": "Action needed but not urgent: e.g. Class II recall, new precautions, "
    "labelling changes healthcare professionals must act on.",
    "low": "Informational: e.g. Class III recall, campaigns, process updates, no action required.",
}


def describe(labels: dict[str, str]) -> str:
    return "\n".join(f"- {name}: {meaning}" for name, meaning in labels.items())
