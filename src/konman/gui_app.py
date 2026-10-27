"""Streamlit application for exploring and editing a local Konman context graph."""

from __future__ import annotations

import argparse
from datetime import datetime
import getpass
import os
import sys

from ruamel.yaml import YAML

from konman.context_graph import (
    CONTEXT_NODE_CONFIG,
    TEMPLATES,
    TYPE_TITLES,
    ContextDataError,
    ContextWorkspace,
    build_graph,
)
from konman.engine import ContextEngine
from konman.models import BOUNDARY_RELATIONSHIP_FIELDS, RELATED_NODE_TYPES


NODE_COLORS = {
    "requirement": "#3b82f6",
    "decision": "#8b5cf6",
    "object": "#06b6d4",
    "evidence": "#64748b",
    "question": "#eab308",
    "change": "#22c55e",
    "boundary": "#f97316",
    "risk": "#ef4444",
}

RELATIONSHIP_FIELDS = {
    "requirement": {"evidence_ids": "evidence"},
    "decision": {"evidence_ids": "evidence"},
    "boundary": {**BOUNDARY_RELATIONSHIP_FIELDS, "evidence_ids": "evidence"},
    "evidence": {"related_nodes": tuple(sorted(RELATED_NODE_TYPES["evidence"]))},
    "change": {"implements": "decision", "affects": "requirement", "evidence": "evidence"},
    "question": {
        "requirements": "requirement", "decisions": "decision",
        "objects": "object", "evidence": "evidence",
    },
    "risk": {
        "requirements": "requirement", "decisions": "decision",
        "changes": "change", "evidence": "evidence",
    },
    "object": {"evidence": "evidence", "related_nodes": tuple(sorted(RELATED_NODE_TYPES["object"]))},
}

for _node_type, _target_types in RELATED_NODE_TYPES.items():
    if _node_type != "object":
        RELATIONSHIP_FIELDS.setdefault(_node_type, {})["related_nodes"] = tuple(sorted(_target_types))


def _application_arguments() -> argparse.Namespace:
    arguments = sys.argv[1:]
    if "--" in arguments:
        arguments = arguments[arguments.index("--") + 1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=".")
    return parser.parse_args(arguments)


def _yaml_text(yaml: YAML, record: dict) -> str:
    from io import StringIO

    output = StringIO()
    yaml.dump(record, output)
    return output.getvalue()


def _state_node_id(flow_state) -> str | None:
    if flow_state is None:
        return None
    selected_id = (
        flow_state.get("selected_id")
        if isinstance(flow_state, dict)
        else getattr(flow_state, "selected_id", None)
    )
    if selected_id:
        return selected_id
    nodes = flow_state.get("nodes", []) if isinstance(flow_state, dict) else getattr(flow_state, "nodes", [])
    for node in nodes or []:
        selected = node.get("selected") if isinstance(node, dict) else getattr(node, "selected", False)
        if selected:
            return node.get("id") if isinstance(node, dict) else getattr(node, "id", None)
    return None


def _prepare_selected_node(session_state, node_options, clicked_id=None) -> None:
    pending_selection = session_state.pop("konman_pending_selected_node", None)
    if pending_selection in node_options:
        session_state["konman_selected_node"] = pending_selection
    elif clicked_id in node_options:
        session_state["konman_selected_node"] = clicked_id
    elif session_state.get("konman_selected_node") not in node_options:
        session_state["konman_selected_node"] = node_options[0] if node_options else None


def _graph_elements(nodes, edges):
    from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode

    node_elements = []
    for index, node in enumerate(nodes):
        label = f"{node['id']}  {node['label']}\n{node['status']}"
        color = NODE_COLORS[node["type"]]
        node_elements.append(StreamlitFlowNode(
            id=node["id"],
            pos=(80 + (index % 5) * 250, 70 + (index // 5) * 140),
            data={"content": label},
            node_type="default",
            source_position="right",
            target_position="left",
            selectable=True,
            style={
                "background": "#111827",
                "border": f"2px solid {color}",
                "borderRadius": "8px",
                "color": "#f8fafc",
                "padding": "8px",
                "width": "210px",
            },
        ))
    edge_elements = [
        StreamlitFlowEdge(
            id=edge["id"],
            source=edge["source"],
            target=edge["target"],
            label=edge["label"],
            animated=False,
        )
        for edge in edges
    ]
    return node_elements, edge_elements


def _initial_flow_state(nodes, edges):
    from streamlit_flow.state import StreamlitFlowState

    return StreamlitFlowState(nodes=nodes, edges=edges)


def _save_editor(workspace, snapshot, node_type: str, selected_id: str, submitted_yaml: str):
    record = workspace.yaml.load(submitted_yaml)
    if not isinstance(record, dict):
        raise ContextDataError("The editor must contain one YAML mapping.")
    node_id, notices = workspace.save(
        node_type,
        record,
        node_id=selected_id,
        expected_token=snapshot.tokens[(node_type, selected_id)],
    )
    return node_id, notices


def _relationship_controls(st, snapshot, node_type: str, record: dict, key_prefix: str) -> dict:
    relationships = {}
    for field, target_type in RELATIONSHIP_FIELDS.get(node_type, {}).items():
        target_types = tuple(CONTEXT_NODE_CONFIG) if target_type == "any" else (
            target_type if isinstance(target_type, tuple) else (target_type,)
        )
        available = [
            (node_id, node_type_name, target_record)
            for node_type_name in target_types
            for node_id, target_record in snapshot.records[node_type_name].items()
        ]
        default_values = record.get(field, [])
        if not isinstance(default_values, list):
            default_values = []
        available_ids = {node_id for node_id, _, _ in available}
        for node_id in default_values:
            if isinstance(node_id, str) and node_id not in available_ids:
                available.append((node_id, target_type, {"id": node_id}))
        label_fields = {
            node_type_name: CONTEXT_NODE_CONFIG[node_type_name][3]
            for node_type_name in CONTEXT_NODE_CONFIG
        }
        labels = {
            node_id: (
                f"{node_id} · {TYPE_TITLES[kind]} · {record.get(label_fields.get(kind, 'id'), '')}"
            )
            for node_id, kind, record in available
        }
        options = list(dict.fromkeys(node_id for node_id, _, _ in available))
        relationships[field] = st.multiselect(
            f"Link {field.replace('_', ' ')}",
            options=options,
            default=[node_id for node_id in default_values if node_id in options],
            format_func=lambda node_id, labels=labels: labels.get(node_id, node_id),
            key=f"{key_prefix}-{field}",
        )
    return relationships


def _save_lifecycle_action(st, workspace, snapshot, node_type, node_id, record):
    try:
        saved_id, notices = workspace.save(
            node_type,
            record,
            node_id=node_id,
            expected_token=snapshot.tokens[(node_type, node_id)],
        )
        st.success(f"Saved {saved_id}.")
        for notice in notices:
            st.warning(notice)
        st.rerun()
    except Exception as error:
        st.error(f"Lifecycle action was not saved: {error}")


def _render_lifecycle_actions(st, workspace, snapshot, node_type, node_id, record):
    if record.get("status") == "proposed":
        with st.expander("Review proposal", expanded=True):
            with st.form(f"review-action-{node_type}-{node_id}"):
                rejection_reason = st.text_input("Reason (required when rejecting)")
                confirmed = st.checkbox("I confirm this review action.")
                approve = st.form_submit_button("Approve and activate")
                reject = st.form_submit_button("Reject proposal")
            if approve:
                if not confirmed:
                    st.error("Confirm the review action before saving.")
                else:
                    updated = dict(record)
                    updated["status"] = {"question": "open", "risk": "open"}.get(node_type, "active")
                    if node_type == "decision":
                        for considered in updated.get("considered", []) or []:
                            if isinstance(considered, dict) and considered.get("object") == updated.get("chosen"):
                                considered["verdict"] = "selected"
                    updated["review"] = {
                        "who": os.environ.get("KONMAN_REVIEWER") or getpass.getuser(),
                        "when": datetime.now().isoformat(timespec="seconds"),
                    }
                    _save_lifecycle_action(st, workspace, snapshot, node_type, node_id, updated)
            elif reject:
                if not confirmed:
                    st.error("Confirm the review action before saving.")
                elif not rejection_reason.strip():
                    st.error("A rejection reason is required.")
                else:
                    updated = dict(record)
                    updated["status"] = "rejected"
                    updated["rejection_reason"] = rejection_reason.strip()
                    updated["review"] = {
                        "who": os.environ.get("KONMAN_REVIEWER") or getpass.getuser(),
                        "when": datetime.now().isoformat(timespec="seconds"),
                    }
                    _save_lifecycle_action(st, workspace, snapshot, node_type, node_id, updated)

    if node_type == "question" and record.get("status") in {"open", "deferred"}:
        with st.expander("Resolve question"):
            with st.form(f"resolve-question-{node_id}"):
                action = st.radio("Action", ["Answer", "Defer"], horizontal=True)
                resolution = st.text_area("Answer or deferral reason")
                confirmed = st.checkbox("I confirm this resolution.")
                submit = st.form_submit_button("Save resolution")
            if submit:
                if not confirmed:
                    st.error("Confirm the resolution before saving.")
                elif not resolution.strip():
                    st.error("Enter an answer or deferral reason.")
                else:
                    updated = dict(record)
                    if action == "Answer":
                        updated.update({
                            "status": "answered",
                            "answer": resolution.strip(),
                            "resolution": resolution.strip(),
                        })
                    else:
                        updated.update({"status": "deferred", "resolution": resolution.strip()})
                    _save_lifecycle_action(st, workspace, snapshot, node_type, node_id, updated)

    if node_type == "risk" and record.get("status") in {"open", "mitigated", "accepted"}:
        with st.expander("Resolve or track risk"):
            with st.form(f"resolve-risk-{node_id}"):
                action = st.selectbox("Action", ["Mitigate", "Accept", "Close"])
                resolution = st.text_area("Mitigation or rationale")
                confirmed = st.checkbox("I confirm this risk action.")
                submit = st.form_submit_button("Save risk action")
            if submit:
                if not confirmed:
                    st.error("Confirm the risk action before saving.")
                elif not resolution.strip():
                    st.error("Enter a mitigation, rationale, or closure reason.")
                else:
                    updated = dict(record)
                    if action == "Mitigate":
                        updated.update({
                            "status": "mitigated",
                            "mitigation": resolution.strip(),
                            "resolution": resolution.strip(),
                        })
                    elif action == "Accept":
                        updated.update({"status": "accepted", "resolution": resolution.strip()})
                    else:
                        updated.update({"status": "closed", "resolution": resolution.strip()})
                    _save_lifecycle_action(st, workspace, snapshot, node_type, node_id, updated)

    if node_type == "decision" and record.get("status") == "needs_review":
        stale_ids = set()
        for considered in record.get("considered", []) or []:
            if not isinstance(considered, dict):
                continue
            for evaluation in considered.get("evaluations", []) or []:
                if not isinstance(evaluation, dict):
                    continue
                requirement = snapshot.records["requirement"].get(evaluation.get("req"), {})
                if requirement.get("status") in {"superseded", "disproven"}:
                    stale_ids.add(evaluation["req"])
        active_requirements = {
            requirement_id: item
            for requirement_id, item in snapshot.records["requirement"].items()
            if item.get("status", "active") == "active"
        }
        with st.expander("Reconcile stale decision", expanded=True):
            if not active_requirements and stale_ids:
                st.error("No active requirements are available as replacements.")
            else:
                with st.form(f"resolve-decision-{node_id}"):
                    replacements = {
                        stale_id: st.selectbox(
                            f"Replace {stale_id} with",
                            options=sorted(active_requirements),
                            key=f"replacement-{node_id}-{stale_id}",
                        )
                        for stale_id in sorted(stale_ids)
                    }
                    reason = st.text_area("Updated decision rationale")
                    confirmed = st.checkbox("I confirm this decision reconciliation.")
                    submit = st.form_submit_button("Reconcile and reactivate")
                if submit:
                    if not confirmed:
                        st.error("Confirm the decision reconciliation before saving.")
                    elif not reason.strip():
                        st.error("Enter an updated decision rationale.")
                    else:
                        updated = dict(record)
                        for considered in updated.get("considered", []) or []:
                            if not isinstance(considered, dict):
                                continue
                            for evaluation in considered.get("evaluations", []) or []:
                                if isinstance(evaluation, dict) and evaluation.get("req") in replacements:
                                    evaluation["req"] = replacements[evaluation["req"]]
                        updated.update({"reason": reason.strip(), "status": "active"})
                        _save_lifecycle_action(st, workspace, snapshot, node_type, node_id, updated)


def main() -> None:
    import streamlit as st
    from streamlit_flow import streamlit_flow

    args = _application_arguments()
    engine = ContextEngine(args.dir)
    workspace = ContextWorkspace(engine)
    yaml = YAML()
    yaml.preserve_quotes = True

    st.set_page_config(page_title="Konman Context Graph", layout="wide")
    st.title("Konman Context Graph")
    st.caption(f"Project: `{engine.base_dir}` · YAML-backed · local-only")

    if not engine.ctx_dir.is_dir():
        st.warning("No .context directory found. Initialize the project before editing context.")
        if st.button("Initialize .context"):
            try:
                engine.init_folders()
                st.rerun()
            except OSError as error:
                st.error(f"Could not initialize context storage: {error}")
        return

    try:
        snapshot = workspace.load()
    except (OSError, ValueError) as error:
        st.error(f"Could not load project context: {error}")
        return

    if snapshot.errors:
        with st.expander(f"Data warnings ({len(snapshot.errors)})", expanded=True):
            for error in snapshot.errors:
                st.warning(error)

    nodes, edges = build_graph(snapshot)
    all_types = list(CONTEXT_NODE_CONFIG)
    all_statuses = sorted({node["status"] for node in nodes})
    with st.sidebar:
        st.header("Graph filters")
        selected_types = st.multiselect(
            "Node types",
            all_types,
            default=all_types,
            format_func=lambda value: TYPE_TITLES[value],
        )
        selected_statuses = st.multiselect("Statuses", all_statuses, default=all_statuses)
        search = st.text_input("Search nodes")
        strict_check = st.checkbox("Strict check (include proposals)", value=False)

    filtered_nodes = [
        node for node in nodes
        if node["type"] in selected_types
        and node["status"] in selected_statuses
        and search.casefold() in (node["id"] + " " + node["label"]).casefold()
    ]
    visible_ids = {node["id"] for node in filtered_nodes}
    filtered_edges = [
        edge for edge in edges
        if edge["source"] in visible_ids and edge["target"] in visible_ids
    ]

    count_columns = st.columns(4)
    count_columns[0].metric("Nodes", len(nodes))
    count_columns[1].metric("Relationships", len(edges))
    count_columns[2].metric("Proposed", sum(node["status"] == "proposed" for node in nodes))
    count_columns[3].metric("Open questions / risks", sum(
        node["status"] in {"open", "deferred"} and node["type"] == "question"
        or node["status"] in {"open", "mitigated", "accepted"} and node["type"] == "risk"
        for node in nodes
    ))

    st.subheader("Project context map")
    st.caption("Node color denotes type; status appears in each node. Select a record below to inspect or edit it.")
    st.caption("🔵 Requirement · 🟣 Decision · 🟦 Component · ⚪ Source · 🟡 Question · 🟢 Change · 🟠 Boundary · 🔴 Risk")
    if filtered_nodes:
        flow_nodes, flow_edges = _graph_elements(filtered_nodes, filtered_edges)
        try:
            flow_signature = (
                tuple((node["id"], node["label"], node["status"]) for node in filtered_nodes),
                tuple((edge["id"], edge["label"]) for edge in filtered_edges),
            )
            if st.session_state.get("konman_flow_signature") != flow_signature:
                st.session_state["konman_flow_state"] = _initial_flow_state(flow_nodes, flow_edges)
                st.session_state["konman_flow_signature"] = flow_signature
            flow_state = streamlit_flow(
                "konman_context_graph",
                st.session_state["konman_flow_state"],
                fit_view=True,
                height=590,
                show_minimap=True,
                show_controls=True,
                allow_new_edges=False,
                get_node_on_click=True,
                get_edge_on_click=True,
            )
            st.session_state["konman_flow_state"] = flow_state
            clicked_id = _state_node_id(flow_state)
        except Exception as error:
            st.error(f"The graph canvas could not render: {error}")
            clicked_id = None
    else:
        st.info("No nodes match the selected filters.")
        clicked_id = None

    selectable_nodes = filtered_nodes or nodes
    if not selectable_nodes:
        st.info("This project has no context records yet. Create a record below to begin the graph.")
    node_options = [node["id"] for node in selectable_nodes]
    _prepare_selected_node(st.session_state, node_options, clicked_id)

    selected_id = st.selectbox(
        "Inspect a node",
        options=node_options,
        key="konman_selected_node",
        format_func=lambda value: next(
            f"{value} · {TYPE_TITLES[node['type']]} · {node['label']}"
            for node in selectable_nodes if node["id"] == value
        ),
    ) if node_options else None

    tabs = st.tabs(["Node details", "Context list", "Check graph", "Create node"])
    with tabs[0]:
        if selected_id:
            selected_node = next(node for node in selectable_nodes if node["id"] == selected_id)
            record = selected_node["record"]
            connected_edges = [
                edge for edge in edges
                if edge["source"] == selected_id or edge["target"] == selected_id
            ]
            st.markdown(f"### {selected_id} · {TYPE_TITLES[selected_node['type']]}")
            st.markdown(f"**Status:** `{selected_node['status']}`")
            st.markdown(f"**Relationships:** {len(connected_edges)}")
            for edge in connected_edges:
                other_id = edge["target"] if edge["source"] == selected_id else edge["source"]
                st.write(f"- {edge['label']} → `{other_id}`")
            with st.form(f"edit-{selected_node['type']}-{selected_id}"):
                record_yaml = st.text_area(
                    "Edit record YAML (including relationship IDs)",
                    value=_yaml_text(yaml, record),
                    height=330,
                    key=f"record-yaml-{selected_node['type']}-{selected_id}",
                )
                selected_relationships = _relationship_controls(
                    st, snapshot, selected_node["type"], record,
                    f"edit-{selected_node['type']}-{selected_id}",
                )
                save_record = st.form_submit_button("Validate and save")
            if save_record:
                try:
                    edited_record = yaml.load(record_yaml)
                    if isinstance(edited_record, dict):
                        edited_record.update(selected_relationships)
                    record_yaml = _yaml_text(yaml, edited_record) if isinstance(edited_record, dict) else record_yaml
                    saved_id, notices = _save_editor(
                        workspace, snapshot, selected_node["type"], selected_id, record_yaml
                    )
                    st.success(f"Saved {saved_id}.")
                    for notice in notices:
                        st.warning(notice)
                    st.rerun()
                except Exception as error:
                    st.error(f"Record was not saved: {error}")
            _render_lifecycle_actions(
                st, workspace, snapshot, selected_node["type"], selected_id, record
            )

    with tabs[1]:
        if nodes:
            st.dataframe(
                [
                    {
                        "ID": node["id"],
                        "Type": TYPE_TITLES[node["type"]],
                        "Status": node["status"],
                        "Label": node["label"],
                        "Relationships": sum(
                            edge["source"] == node["id"] or edge["target"] == node["id"]
                            for edge in edges
                        ),
                    }
                    for node in filtered_nodes
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No context records are available.")

    with tabs[2]:
        violations = engine.check_graph_validity(strict=strict_check)
        if violations:
            st.error(f"Graph check found {len(violations)} issue(s).")
            for violation in violations:
                st.write(f"- {violation}")
        else:
            st.success("Context graph passed validation.")

    with tabs[3]:
        node_type = st.selectbox(
            "New node type",
            options=all_types,
            format_func=lambda value: TYPE_TITLES[value],
            key="konman_new_type",
        )
        next_id = workspace.allocate_id(node_type, snapshot)
        initial_record = {"id": next_id, **TEMPLATES[node_type]}
        if node_type == "boundary":
            initial_record["id"] = next_id
        with st.form("create-context-node"):
            st.caption(f"Next available ID: `{next_id}`. Edit the sample fields and add links using existing IDs.")
            new_yaml = st.text_area(
                "New record YAML",
                value=_yaml_text(yaml, initial_record),
                height=300,
                key=f"create-yaml-{node_type}",
            )
            _relationship_controls(st, snapshot, node_type, initial_record, f"create-{node_type}")
            create_record = st.form_submit_button("Validate and create")
        if create_record:
            try:
                payload = yaml.load(new_yaml)
                if not isinstance(payload, dict):
                    raise ContextDataError("The editor must contain one YAML mapping.")
                payload.update({
                    field: st.session_state.get(f"create-{node_type}-{field}", [])
                    for field in RELATIONSHIP_FIELDS.get(node_type, {})
                })
                saved_id, notices = workspace.save(node_type, payload)
                st.success(f"Created {saved_id}.")
                for notice in notices:
                    st.warning(notice)
                st.session_state["konman_pending_selected_node"] = saved_id
                st.rerun()
            except Exception as error:
                st.error(f"Record was not created: {error}")

    st.caption("Context is stored in the project’s `.context/` YAML files. Raw captures are not displayed.")


if __name__ == "__main__":
    main()
