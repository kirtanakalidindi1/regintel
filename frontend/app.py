"""RegIntel review app. Talks only to the FastAPI backend.

Run (with the API already running):
    uv run streamlit run frontend/app.py
"""

import os
from datetime import date

import requests
import streamlit as st
from helpers import RELEVANCE_BADGES, REVIEW_BADGES, highlight_quotes, pretty

API_URL = os.getenv("REGINTEL_API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="RegIntel", page_icon="📋", layout="wide")


# ---------- API helpers ----------


def api_get(path: str, **params):
    resp = requests.get(f"{API_URL}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp


@st.cache_data(ttl=300)
def get_taxonomy() -> dict:
    return api_get("/taxonomy").json()


def clean(params: dict) -> dict:
    return {k: v for k, v in params.items() if v not in (None, "", "All")}


try:
    taxonomy = get_taxonomy()
    stats = api_get("/stats").json()
except requests.RequestException:
    st.error(
        f"Can't reach the RegIntel API at {API_URL}. Start it in another terminal with:\n\n"
        "`uv run uvicorn regintel.api.main:app --reload --app-dir src --reload-dir src`"
    )
    st.stop()


# ---------- Sidebar: filters and export ----------

with st.sidebar:
    st.title("📋 RegIntel")
    st.caption("FDA and MHRA regulatory intelligence")
    c1, c2 = st.columns(2)
    c1.metric("Updates", stats["updates"])
    c2.metric("Analysed", stats["analysed_updates"])
    pending = stats["by_review_status"].get("pending", 0)
    if pending:
        st.caption(f"{pending} analyses waiting for review")

    st.subheader("Filters")
    q = st.text_input("Search", placeholder="e.g. valproate, pacemaker")
    source = st.selectbox("Regulator", ["All", "FDA", "MHRA"])
    source_type = st.selectbox(
        "Document type",
        [
            "All",
            "drug_enforcement",
            "device_enforcement",
            "drug_safety_update",
            "medical_safety_alert",
        ],
        format_func=lambda v: v if v == "All" else pretty(v),
    )
    relevance = st.selectbox(
        "Relevance",
        ["All", *taxonomy["relevance"]],
        format_func=lambda v: RELEVANCE_BADGES.get(v, v),
    )
    topic = st.selectbox("Topic", ["All", *taxonomy["topics"]], format_func=pretty)
    therapeutic_area = st.selectbox(
        "Therapeutic area", ["All", *taxonomy["therapeutic_areas"]], format_func=pretty
    )
    review_status = st.selectbox(
        "Review status",
        ["All", *taxonomy["review_statuses"]],
        format_func=lambda v: REVIEW_BADGES.get(v, v),
    )
    use_dates = st.checkbox("Filter by date")
    date_from = date_to = None
    if use_dates:
        date_from = st.date_input("From", value=date(date.today().year, 1, 1))
        date_to = st.date_input("To", value=date.today())

    filters = clean(
        {
            "q": q,
            "source": source,
            "source_type": source_type,
            "relevance": relevance,
            "topic": topic,
            "therapeutic_area": therapeutic_area,
            "review_status": review_status,
            "date_from": date_from,
            "date_to": date_to,
        }
    )

    st.subheader("Export")
    st.download_button(
        "Download filtered results (CSV)",
        data=lambda: api_get("/export", **filters, format="csv").content,
        file_name=f"regintel_{date.today():%Y%m%d}.csv",
        mime="text/csv",
        width="stretch",
    )


# ---------- Main: list of updates ----------

data = api_get("/updates", **filters, limit=500).json()
st.subheader(f"{data['total']} updates")

if not data["items"]:
    st.info("No updates match these filters.")
    st.stop()

rows = [
    {
        "Date": item["published_date"],
        "Regulator": item["source"],
        "Type": pretty(item["source_type"]),
        "Title": item["title"],
        "Relevance": RELEVANCE_BADGES.get(item["relevance"], "Not analysed"),
        "Topic": pretty(item["topic"]),
        "Review": REVIEW_BADGES.get(item["review_status"], "—"),
    }
    for item in data["items"]
]
selection = st.dataframe(
    rows,
    hide_index=True,
    width="stretch",
    height=320,
    on_select="rerun",
    selection_mode="single-row",
    key="updates_table",
)

selected = selection.selection.rows
if not selected:
    st.caption("Select a row to see the analysis and review it.")
    st.stop()

update_id = data["items"][selected[0]]["id"]
detail = api_get(f"/updates/{update_id}").json()
analysis = detail["analysis"]


# ---------- Detail: analysis beside source ----------

st.divider()
st.markdown(f"### {detail['title']}")
st.caption(
    f"{pretty(detail['source_type'])} · Published {detail['published_date'] or 'unknown'} · "
    f"[Official source]({detail['url']})"
)

left, right = st.columns([1, 1], gap="large")

with left:
    st.markdown("#### AI analysis")
    if analysis is None:
        st.info(
            "Not analysed yet. Run `uv run python -m regintel.llm.run --limit 5` "
            "to analyse updates with Claude."
        )
    else:
        final = {**analysis, **(analysis["reviewed_output"] or {})}
        m1, m2, m3 = st.columns(3)
        m1.metric(
            "Relevance", RELEVANCE_BADGES.get(final["relevance"], final["relevance"])
        )
        m2.metric("Topic", pretty(final["topic"]))
        m3.metric("Product", pretty(final["product_type"]))
        st.markdown(
            "**Therapeutic areas:** "
            + ", ".join(pretty(a) for a in final["therapeutic_areas"])
        )
        st.markdown(f"**Why this relevance:** {analysis['relevance_rationale']}")

        st.markdown("**Summary**")
        for point in analysis["summary_points"]:
            icon = "✅" if point.get("supported") else "⚠️"
            st.markdown(f"{icon} {point['claim']}")
            st.caption(f"“{point['quote']}”")
        if not analysis["all_citations_supported"]:
            st.warning(
                "At least one quote was not found in the source text. Check it before "
                "approving."
            )

        st.caption(
            f"Model {analysis['model']} · prompt {analysis['prompt_version']} · "
            f"status {REVIEW_BADGES.get(analysis['review_status'])}"
        )

with right:
    st.markdown("#### Source text")
    st.caption("Quoted passages are highlighted.")
    quotes = [p["quote"] for p in analysis["summary_points"]] if analysis else []
    with st.container(height=520):
        st.markdown(
            highlight_quotes(detail["body_text"], quotes), unsafe_allow_html=True
        )


# ---------- Review ----------

if analysis is not None:
    st.divider()
    st.markdown("#### Review")
    k = analysis["id"]  # unique widget keys per analysis, so values don't carry over
    with st.form(key=f"review_{k}"):
        decision = st.radio(
            "Decision",
            ["approved", "corrected", "rejected"],
            horizontal=True,
            format_func=lambda v: REVIEW_BADGES[v],
            key=f"decision_{k}",
        )
        st.caption("Label changes are saved only when you choose Corrected.")
        c1, c2, c3 = st.columns(3)
        new_relevance = c1.selectbox(
            "Relevance",
            taxonomy["relevance"],
            index=taxonomy["relevance"].index(analysis["relevance"]),
            format_func=lambda v: RELEVANCE_BADGES[v],
            key=f"relevance_{k}",
        )
        new_topic = c2.selectbox(
            "Topic",
            taxonomy["topics"],
            index=taxonomy["topics"].index(analysis["topic"]),
            format_func=pretty,
            key=f"topic_{k}",
        )
        new_product = c3.selectbox(
            "Product type",
            taxonomy["product_types"],
            index=taxonomy["product_types"].index(analysis["product_type"]),
            format_func=pretty,
            key=f"product_{k}",
        )
        new_areas = st.multiselect(
            "Therapeutic areas (1 to 3)",
            taxonomy["therapeutic_areas"],
            default=analysis["therapeutic_areas"],
            format_func=pretty,
            max_selections=3,
            key=f"areas_{k}",
        )
        note = st.text_area(
            "Reviewer note (optional)",
            value=analysis["reviewer_note"] or "",
            key=f"note_{k}",
        )
        submitted = st.form_submit_button("Save review", type="primary")

    if submitted:
        payload = {"status": decision, "note": note or None}
        if decision == "corrected":
            changed = {
                "relevance": new_relevance,
                "topic": new_topic,
                "product_type": new_product,
                "therapeutic_areas": new_areas,
            }
            corrections = {key: v for key, v in changed.items() if v != analysis[key]}
            if not new_areas:
                st.error("Pick at least one therapeutic area.")
                st.stop()
            if not corrections:
                st.error("You chose Corrected but didn't change any field.")
                st.stop()
            payload["corrections"] = corrections
        resp = requests.post(
            f"{API_URL}/analyses/{analysis['id']}/review", json=payload, timeout=30
        )
        if resp.ok:
            st.toast("Review saved", icon="✅")
            st.rerun()
        else:
            st.error(f"Could not save review: {resp.text}")
