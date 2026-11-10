"""RegIntel review app. Talks only to the FastAPI backend.

Run (with the API already running), from the project folder:
    uv run streamlit run frontend/app.py
"""

import html
import os
from datetime import date
from pathlib import Path

import requests
import streamlit as st
from helpers import RELEVANCE_LABELS, REVIEW_LABELS, chip, highlight_quotes, pretty

API_URL = os.getenv("REGINTEL_API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="RegIntel", page_icon="📑", layout="wide")
st.markdown(
    f"<style>{(Path(__file__).parent / 'styles.css').read_text()}</style>",
    unsafe_allow_html=True,
)


# ---------- API helpers ----------


def api_get(path: str, **params):
    resp = requests.get(f"{API_URL}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp


@st.cache_data(ttl=300)
def get_reference_data() -> tuple[dict, list[dict]]:
    return api_get("/taxonomy").json(), api_get("/portfolio").json()


def clean(params: dict) -> dict:
    return {k: v for k, v in params.items() if v not in (None, "", "All")}


try:
    taxonomy, portfolio = get_reference_data()
    stats = api_get("/stats").json()
except requests.RequestException:
    st.error(
        f"RegIntel can't reach its API at {API_URL}. Start the API in another terminal, "
        "then refresh this page:\n\n"
        "`uv run uvicorn regintel.api.main:app --reload --app-dir src --reload-dir src`"
    )
    st.stop()


# ---------- Header and queues ----------

st.markdown(
    '<div class="ri-title">RegIntel</div>'
    '<div class="ri-sub">FDA and MHRA updates, analysed by Claude, checked against your '
    "watchlist and routed for review.</div>",
    unsafe_allow_html=True,
)

queues = stats["queues"]
QUEUE_OPTIONS = {
    "review": (
        f"Needs review ({queues['needs_review']})",
        {"review_status": "pending"},
    ),
    "high": (f"High relevance ({queues['high_relevance']})", {"relevance": "high"}),
    "labelling": (
        f"Labelling impact ({queues['labelling_impact']})",
        {"labelling_impact": True},
    ),
    "watchlist": (
        f"Watchlist matches ({queues['portfolio_matches']})",
        {"analysed": True, "has_watchlist": True},
    ),
    "all": (f"All updates ({stats['updates']})", {}),
}
queue = st.segmented_control(
    "Queue",
    options=list(QUEUE_OPTIONS),
    format_func=lambda key: QUEUE_OPTIONS[key][0],
    default="review" if queues["needs_review"] else "all",
    label_visibility="collapsed",
    key="queue",
)
queue = queue or "all"
queue_filters = dict(QUEUE_OPTIONS[queue][1])
only_watchlist = queue_filters.pop("has_watchlist", False)


# ---------- Sidebar: filters and export ----------

with st.sidebar:
    st.markdown("### Filters")
    q = st.text_input("Search titles and text", placeholder="e.g. valproate, pacemaker")
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
    watch_item = st.selectbox(
        "Watchlist item", ["All", *[item["name"] for item in portfolio]]
    )
    therapeutic_area = st.selectbox(
        "Therapeutic area", ["All", *taxonomy["therapeutic_areas"]], format_func=pretty
    )
    topic = st.selectbox("Topic", ["All", *taxonomy["topics"]], format_func=pretty)
    action_owner = st.selectbox(
        "Team to act", ["All", *taxonomy["action_owners"]], format_func=pretty
    )
    rare_only = st.checkbox("Rare disease only")
    use_dates = st.checkbox("Filter by date")
    date_from = date_to = None
    if use_dates:
        date_from = st.date_input("From", value=date(date.today().year, 1, 1))
        date_to = st.date_input("To", value=date.today())

    filters = clean(
        {
            **queue_filters,
            "q": q,
            "source": source,
            "source_type": source_type,
            "portfolio_item": watch_item,
            "therapeutic_area": therapeutic_area,
            "topic": topic,
            "action_owner": action_owner,
            "rare_disease": True if rare_only else None,
            "date_from": date_from,
            "date_to": date_to,
        }
    )

    st.markdown("### Export")
    st.download_button(
        "Download these results (CSV)",
        data=lambda: api_get("/export", **filters, format="csv").content,
        file_name=f"regintel_{date.today():%Y%m%d}.csv",
        mime="text/csv",
        width="stretch",
    )

    with st.expander("Watchlist"):
        for item in portfolio:
            st.markdown(f"**{item['name']}**  \n{', '.join(item.get('examples', []))}")
        st.caption("Edit portfolio.json in the project folder to change the watchlist.")


# ---------- Updates table ----------

data = api_get("/updates", **filters, limit=500).json()
items = data["items"]
if only_watchlist:
    items = [item for item in items if item["portfolio_items"]]

if not items:
    empty_messages = {
        "review": "Nothing is waiting for review. Run the analysis on more updates with "
        "`uv run python -m regintel.llm.run --limit 20`.",
        "labelling": "No analysed update currently has labelling impact.",
        "watchlist": "No analysed update matches the watchlist yet.",
    }
    st.info(
        empty_messages.get(
            queue, "No updates match these filters. Try clearing a filter."
        )
    )
    st.stop()

rows = [
    {
        "Published": item["published_date"],
        "Regulator": item["source"],
        "Title": item["title"],
        "Relevance": (item["relevance"] or "Not analysed").capitalize(),
        "Labelling": "Yes" if item["labelling_impact"] else "",
        "Watchlist": ", ".join(item["portfolio_items"]),
        "Status": REVIEW_LABELS.get(item["review_status"], ""),
    }
    for item in items
]
st.caption(f"{len(items)} updates. Select a row to open it.")
selection = st.dataframe(
    rows,
    hide_index=True,
    width="stretch",
    height=min(330, 38 + 35 * len(rows)),
    on_select="rerun",
    selection_mode="single-row",
    key=f"table_{queue}",
    column_config={
        "Title": st.column_config.TextColumn(width="large"),
        "Published": st.column_config.TextColumn(width="small"),
        "Regulator": st.column_config.TextColumn(width="small"),
    },
)

selected = selection.selection.rows
if not selected:
    st.stop()

update_id = items[selected[0]]["id"]
detail = api_get(f"/updates/{update_id}").json()
analysis = detail["analysis"]
final = {**analysis, **(analysis["reviewed_output"] or {})} if analysis else {}


# ---------- Detail: analysis beside the source document ----------

st.divider()
st.markdown(f"### {html.escape(detail['title'])}")

left, right = st.columns([5, 6], gap="large")

with left:
    if analysis is None:
        st.info(
            "Claude hasn't analysed this update yet. Run "
            "`uv run python -m regintel.llm.run --limit 20` and refresh."
        )
    else:
        chips = [
            chip(RELEVANCE_LABELS[final["relevance"]], final["relevance"]),
            chip(pretty(final["topic"])),
            chip(pretty(final["product_type"])),
            *[chip(pretty(a)) for a in final["therapeutic_areas"]],
        ]
        if final.get("rare_disease"):
            chips.append(chip("Rare disease", "rare"))
        st.markdown("".join(chips), unsafe_allow_html=True)
        st.markdown(
            f'<p class="ri-rationale">{html.escape(analysis["relevance_rationale"])}</p>',
            unsafe_allow_html=True,
        )

        if final.get("labelling_impact"):
            docs = ", ".join(
                pretty(d) for d in final.get("labelling_documents") or []
            ) or ("documents not specified")
            st.markdown(
                f'<div class="ri-callout"><b>Labelling impact.</b> Assess {docs}.</div>',
                unsafe_allow_html=True,
            )
        elif final.get("labelling_impact") is False:
            st.markdown(
                '<div class="ri-callout ri-callout-none">No labelling impact identified.</div>',
                unsafe_allow_html=True,
            )

        for impact in final.get("portfolio_impacts") or []:
            st.markdown(
                f'<div class="ri-callout ri-watch"><b>{html.escape(impact["watchlist_item"])}.'
                f"</b> {html.escape(impact['reason'])}</div>",
                unsafe_allow_html=True,
            )

        if final.get("action_owners"):
            st.markdown(
                '<p class="ri-section">Teams to act</p>', unsafe_allow_html=True
            )
            st.markdown(
                "".join(chip(pretty(o)) for o in final["action_owners"]),
                unsafe_allow_html=True,
            )

        st.markdown('<p class="ri-section">Summary</p>', unsafe_allow_html=True)
        for number, point in enumerate(analysis["summary_points"], start=1):
            verified = point.get("supported")
            status = (
                ""
                if verified
                else (
                    '<div class="ri-unverified">Quote not found in source. Check before '
                    "approving.</div>"
                )
            )
            st.markdown(
                f'<div class="ri-claim"><span class="ri-num{"" if verified else " ri-num-warn"}">'
                f"{number}</span><div><p>{html.escape(point['claim'])}</p>"
                f'<div class="ri-quote">“{html.escape(point["quote"])}”</div>{status}</div></div>',
                unsafe_allow_html=True,
            )
        st.caption(
            f"{analysis['model']}, prompt {analysis['prompt_version']}. "
            f"Status: {REVIEW_LABELS.get(analysis['review_status'])}."
        )

with right:
    quotes = [p["quote"] for p in analysis["summary_points"]] if analysis else []
    published = detail["published_date"] or "date unknown"
    with st.container(height=640, border=False):
        st.markdown(
            f'<div class="ri-doc"><div class="ri-doc-head">{pretty(detail["source_type"])}, '
            f'published {published}. <a href="{html.escape(detail["url"])}" target="_blank">'
            "Open the official source</a></div>"
            f"{highlight_quotes(detail['body_text'], quotes, numbered=True)}</div>",
            unsafe_allow_html=True,
        )


# ---------- Labelling impact assessment ----------

URGENCY_CHIPS = {
    "immediate": ("Implement immediately", "high"),
    "within_weeks": ("Implement within weeks", "medium"),
    "next_routine_update": ("Next routine update", "low"),
}
ASSESSMENT_STATUS = {
    "draft": "Draft",
    "accepted": "Accepted as starting point",
    "needs_rework": "Needs rework",
}

if analysis is not None and final.get("labelling_impact"):
    st.divider()
    st.markdown("### Labelling impact assessment")
    assessment = detail.get("assessment")

    if assessment is None:
        st.markdown(
            '<p class="ri-rationale">Draft a section-by-section assessment of what this '
            "update means for product information: SmPC and PIL sections to change, the "
            "regulator's wording, urgency, suggested routes and open questions for the "
            "labelling team.</p>",
            unsafe_allow_html=True,
        )
        if st.button(
            "Draft impact assessment", type="primary", key=f"draft_{analysis['id']}"
        ):
            with st.spinner("Drafting the assessment. This takes 10 to 30 seconds."):
                resp = requests.post(
                    f"{API_URL}/analyses/{analysis['id']}/assessment", timeout=180
                )
            if resp.ok:
                st.rerun()
            else:
                try:
                    reason = resp.json().get("detail", resp.text)
                except ValueError:
                    reason = resp.text
                st.error(f"The assessment wasn't drafted. {reason}")
    else:
        c = assessment["content"]
        urgency_text, urgency_kind = URGENCY_CHIPS[c["urgency"]]
        st.markdown(
            chip(urgency_text, urgency_kind)
            + chip(
                ASSESSMENT_STATUS.get(assessment["status"], assessment["status"]),
                "label",
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<p class="ri-rationale"><b>Scope.</b> {html.escape(c["scope"])} '
            f"{html.escape(c['urgency_rationale'])}</p>",
            unsafe_allow_html=True,
        )
        for effect in c["watchlist_effects"]:
            st.markdown(
                f'<div class="ri-callout ri-watch"><b>{html.escape(effect["watchlist_item"])}.'
                f"</b> {html.escape(effect['why'])}</div>",
                unsafe_allow_html=True,
            )

        rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(pretty(ch['document']))}</td>"
            f"<td>{html.escape(ch['section'])}</td>"
            f'<td><span class="ri-change ri-change-{ch["change_type"]}">'
            f"{ch['change_type'].capitalize()}</span></td>"
            f"<td>{html.escape(ch['description'])}</td>"
            f'<td class="ri-source">“{html.escape(ch["source_quote"])}”'
            + (
                ""
                if ch["supported"]
                else '<div class="ri-unverified">Not found in source</div>'
            )
            + "</td></tr>"
            for ch in c["section_changes"]
        )
        st.markdown(
            '<div class="ri-table-wrap"><table class="ri-table"><thead><tr><th>Document</th>'
            "<th>Section</th><th>Change</th><th>What to do</th><th>Regulator's wording</th>"
            f"</tr></thead><tbody>{rows_html}</tbody></table></div>",
            unsafe_allow_html=True,
        )

        col_routes, col_questions = st.columns(2, gap="large")
        with col_routes:
            st.markdown(
                '<p class="ri-section">Suggested routes (to confirm)</p>',
                unsafe_allow_html=True,
            )
            if c["routes"]:
                for r in c["routes"]:
                    st.markdown(
                        f"**{html.escape(r['region'])}: {html.escape(r['route'])}.** "
                        f"{html.escape(r['rationale'])}"
                    )
            else:
                st.caption("No route suggested.")
        with col_questions:
            st.markdown(
                '<p class="ri-section">Open questions for the labelling team</p>',
                unsafe_allow_html=True,
            )
            if c["open_questions"]:
                st.markdown("\n".join(f"- {q}" for q in c["open_questions"]))
            else:
                st.caption("None raised.")

        a_id = assessment["id"]
        note = st.text_input(
            "Note on this assessment (optional)",
            value=assessment["reviewer_note"] or "",
            key=f"assess_note_{a_id}",
        )
        b1, b2, b3, b4 = st.columns(4)
        b1.download_button(
            "Download as Markdown",
            data=lambda: api_get(f"/assessments/{a_id}/export").content,
            file_name=f"impact_assessment_{detail['id']}.md",
            mime="text/markdown",
            key=f"assess_dl_{a_id}",
            width="stretch",
        )
        for column, status, label in (
            (b2, "accepted", "Accept as starting point"),
            (b3, "needs_rework", "Mark needs rework"),
        ):
            if column.button(label, key=f"assess_{status}_{a_id}", width="stretch"):
                requests.post(
                    f"{API_URL}/assessments/{a_id}/review",
                    json={"status": status, "note": note or None},
                    timeout=30,
                )
                st.toast("Assessment updated", icon="✅")
                st.rerun()
        if b4.button("Redraft", key=f"assess_redraft_{a_id}", width="stretch"):
            with st.spinner("Redrafting the assessment."):
                requests.post(
                    f"{API_URL}/analyses/{analysis['id']}/assessment", timeout=180
                )
            st.rerun()
        st.caption(
            f"Drafted by {assessment['model']}, assessment version "
            f"{assessment['prompt_version']}. A starting point for the labelling team: routes "
            "are suggestions, and the draft doesn't know what your current labels say."
        )


# ---------- Review ----------

if analysis is not None:
    st.divider()
    st.markdown("### Review")
    k = analysis["id"]  # unique widget keys per analysis, so values don't carry over
    with st.form(key=f"review_{k}"):
        decision = st.radio(
            "Decision",
            ["approved", "corrected", "rejected"],
            horizontal=True,
            format_func=lambda v: {
                "approved": "Approve",
                "corrected": "Correct labels",
                "rejected": "Reject",
            }[v],
            key=f"decision_{k}",
        )
        st.caption("Label changes below are saved only when you choose Correct labels.")
        c1, c2, c3 = st.columns(3)
        new_relevance = c1.selectbox(
            "Relevance",
            taxonomy["relevance"],
            index=taxonomy["relevance"].index(analysis["relevance"]),
            format_func=lambda v: v.capitalize(),
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
        c4, c5 = st.columns(2)
        new_areas = c4.multiselect(
            "Therapeutic areas (1 to 3)",
            taxonomy["therapeutic_areas"],
            default=analysis["therapeutic_areas"],
            format_func=pretty,
            max_selections=3,
            key=f"areas_{k}",
        )
        new_owners = c5.multiselect(
            "Teams to act (1 to 4)",
            taxonomy["action_owners"],
            default=analysis.get("action_owners") or [],
            format_func=pretty,
            max_selections=4,
            key=f"owners_{k}",
        )
        c6, c7 = st.columns(2)
        new_labelling = c6.checkbox(
            "Labelling impact",
            value=bool(analysis.get("labelling_impact")),
            key=f"lab_{k}",
        )
        new_rare = c7.checkbox(
            "Rare disease", value=bool(analysis.get("rare_disease")), key=f"rare_{k}"
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
                "action_owners": new_owners,
                "labelling_impact": new_labelling,
                "rare_disease": new_rare,
            }
            original = {
                **analysis,
                "labelling_impact": bool(analysis.get("labelling_impact")),
                "rare_disease": bool(analysis.get("rare_disease")),
                "action_owners": analysis.get("action_owners") or [],
            }
            corrections = {key: v for key, v in changed.items() if v != original[key]}
            if not new_areas or not new_owners:
                st.error("Choose at least one therapeutic area and one team to act.")
                st.stop()
            if not corrections:
                st.error("You chose Correct labels but didn't change any label.")
                st.stop()
            payload["corrections"] = corrections
        resp = requests.post(
            f"{API_URL}/analyses/{analysis['id']}/review", json=payload, timeout=30
        )
        if resp.ok:
            st.toast("Review saved", icon="✅")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error(f"The review wasn't saved. The API said: {resp.text}")
