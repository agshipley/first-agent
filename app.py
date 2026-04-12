import anthropic
import queue
import threading
import time
import uuid
import json
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from prompts import get_system_prompt, get_la_permitting_system_prompt
from tools import (
    save_leads_to_spreadsheet,
    get_existing_leads_for_segment,
    get_all_leads_for_segment,
    save_deep_dive_to_spreadsheet,
)
from flask import Flask, render_template, request, Response, send_file, stream_with_context, jsonify

load_dotenv()

app = Flask(__name__)

DATA_DIR = os.environ.get("DATA_DIR", ".")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

# ── Lead search tools ─────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "web_search_20250305",
        "name": "web_search"
    },
    {
        "name": "save_leads_to_spreadsheet",
        "description": "Saves the final list of evaluated leads to an Excel spreadsheet. Call this once when you have finished researching and are ready to save your findings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "leads": {
                    "type": "array",
                    "description": "List of leads to save",
                    "items": {
                        "type": "object",
                        "properties": {
                            "company_name": {"type": "string"},
                            "type": {"type": "string"},
                            "location": {"type": "string"},
                            "geographic_area": {"type": "string"},
                            "why_a_lead": {"type": "string"},
                            "company_website": {"type": "string"},
                            "source_url": {"type": "string"},
                            "potential_contact": {"type": "string"},
                            "icp_score": {"type": "number"},
                            "estimated_budget": {"type": "string"},
                            "budget_basis": {"type": "string"},
                            "budget_confidence": {"type": "string"},
                            "project_stage": {"type": "string"},
                            "lead_source": {"type": "string"},
                            "notes": {"type": "string"}
                        }
                    }
                }
            },
            "required": ["leads"]
        }
    }
]

# ── Deep dive tools ───────────────────────────────────────────────────────────

_SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
        "completeness": {"type": "string", "enum": ["Comprehensive", "Partial", "Limited"]}
    },
    "required": ["findings", "sources", "completeness"]
}

DEEP_DIVE_TOOLS = [
    {
        "type": "web_search_20250305",
        "name": "web_search"
    },
    {
        "name": "save_deep_dive_report",
        "description": "Save the completed deep dive research report. Call this once after finishing all searches.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_status":            _SECTION_SCHEMA,
                "news_and_media":            _SECTION_SCHEMA,
                "existing_art_attachments":  _SECTION_SCHEMA,
                "key_principals":            _SECTION_SCHEMA,
                "commissioning_history":     _SECTION_SCHEMA,
            },
            "required": [
                "project_status",
                "news_and_media",
                "existing_art_attachments",
                "key_principals",
                "commissioning_history",
            ]
        }
    }
]

DEEP_DIVE_SYSTEM_PROMPT = """You are a research analyst conducting a targeted deep dive for Tre Borden /Co, \
a creative studio that curates and commissions art for corporate and public spaces.

You will receive information about a specific lead and must research five areas using web_search. \
Use no more than 5 searches total — choose queries that yield the most specific, current information.

For each section provide:
- findings: a narrative summary (2–4 sentences) of what you found
- sources: list of URLs you referenced
- completeness: exactly one of "Comprehensive", "Partial", or "Limited"
  - Comprehensive: substantial specific information found
  - Partial: some details found but gaps remain
  - Limited: only general background or nothing specific found

The five sections:

1. project_status — Current phase (planning / entitled / under construction / near completion), \
recent milestones, projected completion dates.

2. news_and_media — Recent press coverage, announcements, or public commentary that affects \
attractiveness as an art commissioning opportunity.

3. existing_art_attachments — Has an art consultant, artist, or design firm already been attached \
to this project? Are there open RFPs or calls for artists?

4. key_principals — Decision-makers relevant to art commissioning: developer principals, lead \
architects, arts program administrators. Note their roles, relevant background, and any red flags \
(litigation, controversy, reputation issues).

5. commissioning_history — Prior art commissions by this organization: type of work, scale, \
and which artists or consultants were engaged.

When you have finished all research, call save_deep_dive_report with your structured findings."""


# ── Agent loop helper ─────────────────────────────────────────────────────────

def _collect_leads(client, system_prompt, tools, user_message):
    """
    Generator that runs an agent loop until save_leads_to_spreadsheet is called.
    Yields status strings or ": keepalive" SSE comments to prevent proxy timeouts.
    Callers must check the prefix:
        msg.startswith(":") → yield f"{msg}\\n\\n"  (raw SSE comment, invisible to client)
        otherwise          → yield f"data: {msg}\\n\\n"
    Returns the collected leads list via StopIteration.value.
    """
    messages = [{"role": "user", "content": user_message}]
    max_iterations = 20
    iteration = 0

    while True:
        iteration += 1
        if iteration > max_iterations:
            yield "Search loop safety limit reached."
            return []

        # Run the blocking API call in a background thread so we can yield
        # SSE keepalives every 20 s and prevent Railway's proxy from timing out.
        _result = [None]
        _error  = [None]
        _done   = threading.Event()

        def _call():
            try:
                _result[0] = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=4096,
                    system=system_prompt,
                    tools=tools,
                    messages=messages
                )
            except Exception as e:
                _error[0] = e
            finally:
                _done.set()

        threading.Thread(target=_call, daemon=True).start()
        while not _done.wait(timeout=20):
            yield ": keepalive"  # SSE comment — keeps proxy alive, invisible to JS

        if _error[0] is not None:
            if isinstance(_error[0], anthropic.RateLimitError):
                yield "Rate limit hit, waiting 60 seconds..."
                for i in range(12):
                    time.sleep(5)
                    yield f"Waiting... ({(i+1)*5}s)"
                yield "Retrying..."
                continue
            yield f"ERROR: {type(_error[0]).__name__}: {str(_error[0])}"
            return []

        response = _result[0]
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    yield block.text
            return []

        elif response.stop_reason == "tool_use":
            for block in response.content:
                if block.type == "tool_use":
                    if block.name == "save_leads_to_spreadsheet":
                        return block.input.get("leads", [])
                    # Do NOT handle web_search — it's a server-side tool.


# ── Existing routes ───────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return "ok", 200

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/leads")
def leads():
    segment = request.args.get("segment", "corporate")
    all_leads = get_all_leads_for_segment(segment)
    return jsonify(all_leads)

@app.route("/run", methods=["GET", "POST"])
def run():
    segment = request.args.get("segment") or request.form.get("segment", "corporate")
    geography = request.args.get("geography") or request.form.get("geography", "Greater Los Angeles Area")
    budget = request.args.get("budget") or request.form.get("budget", "Any Budget")
    project_stage = request.args.get("project_stage") or request.form.get("project_stage", "All Stages")

    def generate():
        client = anthropic.Anthropic()

        budget_instruction = (
            f" Prioritize leads whose estimated art commissioning budget is likely to fall within {budget}."
            if budget != "Any Budget" else ""
        )

        if project_stage == "Early Stage (Pre-Construction)":
            stage_instruction = (
                "\n\nProject Stage Focus: Focus on projects that have NOT yet broken ground. "
                "The goal is to identify opportunities early enough that art commissioning decisions "
                "haven't been made yet. Projects in the permitting, entitlement, or design phase are "
                "more valuable than projects already under construction. "
                "Prioritize searching for:\n"
                "- Planning commission agendas and meeting minutes mentioning new development projects\n"
                "- Environmental review notices (CEQA in California, NEPA for federal, local equivalents elsewhere)\n"
                "- Entitlement applications and zoning change requests\n"
                "- Building permit applications for new construction or major renovation\n"
                "- Developer announcements of projects in planning or pre-development\n"
                "- Percent-for-art program announcements tied to upcoming capital projects\n"
                "- RFQ/RFP postings from arts commissions or cultural affairs departments "
                "for projects not yet under construction"
            )
        elif project_stage == "Active Construction":
            stage_instruction = (
                "\n\nProject Stage Focus: Focus on projects currently under construction where art "
                "commissioning may still be open. Prioritize larger projects with extended construction "
                "timelines where interior art programs haven't been finalized. Look for construction "
                "starts, issued building permits, and projects with completion dates 12+ months out."
            )
        else:
            stage_instruction = ""

        if segment == "corporate":
            user_message = (
                f"Please search for potential corporate art program leads for Tre Borden /Co "
                f"in the {geography} area. Find at least 5 strong leads, evaluate "
                f"them carefully, and save the results to the spreadsheet. "
                f"Set the `geographic_area` field to \"{geography}\" for every lead you save."
                f"{budget_instruction}{stage_instruction}"
            )
        else:
            user_message = (
                f"Please search for potential public sector art commission leads for Tre Borden /Co "
                f"in the {geography} area. Focus on active RFPs, percent-for-art "
                f"opportunities, and public construction projects with budgets over $100k. Find at "
                f"least 5 strong leads, evaluate them carefully, and save the results to the spreadsheet. "
                f"Set the `geographic_area` field to \"{geography}\" for every lead you save."
                f"{budget_instruction}{stage_instruction}"
            )

        existing = get_existing_leads_for_segment(segment)
        existing_names = existing if existing else None
        system_prompt = get_system_prompt(segment, existing_names)

        is_la_enhanced = (
            geography == "Greater Los Angeles Area"
            and project_stage == "Early Stage (Pre-Construction)"
        )

        if is_la_enhanced:
            # ── Enhanced path: both phases run in parallel ─────────────────────
            # Running sequentially took ~120s and hit gunicorn's worker timeout.
            # Parallel execution cuts wall-clock time to max(phase1, phase2) ≈ 60s.
            yield "data: Starting enhanced LA early-stage search...\n\n"
            yield "data: Running general search and LA permitting search in parallel...\n\n"

            la_system_prompt = get_la_permitting_system_prompt(existing_names)
            la_user_message = (
                "Search these specific Los Angeles municipal sources for early-stage development "
                "projects that are strong candidates for art commissioning by Tre Borden /Co. "
                "Focus on private developments with permit valuations above $5M and public capital "
                "projects with percent-for-art requirements. Use all 5 searches on municipal sources."
            )

            status_q = queue.Queue()
            phase1_result = [None]
            phase2_result = [None]

            def _run_phase(gen, result_holder):
                try:
                    while True:
                        status_q.put(next(gen))
                except StopIteration as exc:
                    result_holder[0] = exc.value or []
                status_q.put(None)  # signal this phase is done

            t1 = threading.Thread(
                target=_run_phase,
                args=(_collect_leads(client, system_prompt, TOOLS, user_message), phase1_result),
                daemon=True
            )
            t2 = threading.Thread(
                target=_run_phase,
                args=(_collect_leads(client, la_system_prompt, TOOLS, la_user_message), phase2_result),
                daemon=True
            )
            t1.start()
            t2.start()

            done_count = 0
            while done_count < 2:
                try:
                    msg = status_q.get(timeout=15)
                    if msg is None:
                        done_count += 1
                    elif msg.startswith(":"):
                        yield f"{msg}\n\n"
                    else:
                        yield f"data: {msg}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"  # both phases quiet — keep proxy alive

            t1.join()
            t2.join()

            main_leads = phase1_result[0] or []
            la_leads   = phase2_result[0] or []

            for lead in main_leads:
                lead.setdefault("lead_source", "Web Search")

            # Merge: main leads first, then LA leads not already present
            main_names = {l.get("company_name", "").strip().lower() for l in main_leads}
            for lead in la_leads:
                name = lead.get("company_name", "").strip().lower()
                if name and name not in main_names:
                    main_leads.append(lead)
                    main_names.add(name)

            yield "data: Saving leads to spreadsheet...\n\n"
            try:
                result, actually_saved = save_leads_to_spreadsheet(main_leads, segment)
                yield f"data: DONE|{json.dumps(actually_saved)}\n\n"
            except Exception as e:
                yield f"data: Error saving leads: {e}\n\n"
                yield "data: DONE|[]\n\n"
            return

        else:
            # ── Standard path ─────────────────────────────────────────────────
            yield f"data: Starting {segment.replace('_', ' ')} lead search...\n\n"

            gen = _collect_leads(client, system_prompt, TOOLS, user_message)
            try:
                while True:
                    msg = next(gen)
                    yield f"{msg}\n\n" if msg.startswith(":") else f"data: {msg}\n\n"
            except StopIteration as exc:
                leads = exc.value or []

            for lead in leads:
                lead.setdefault("lead_source", "Web Search")

            yield "data: Saving leads to spreadsheet...\n\n"
            try:
                result, actually_saved = save_leads_to_spreadsheet(leads, segment)
                yield f"data: DONE|{json.dumps(actually_saved)}\n\n"
            except Exception as e:
                yield f"data: Error saving leads: {e}\n\n"
                yield "data: DONE|[]\n\n"
            return

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/download")
def download():
    filepath = os.path.join(DATA_DIR, "leads.xlsx")
    if not os.path.exists(filepath):
        return "No spreadsheet found yet.", 404
    return send_file(
        filepath,
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        download_name="TreBorden_Leads.xlsx"
    )


# ── Deep dive routes ──────────────────────────────────────────────────────────

@app.route("/deep-dive", methods=["POST"])
def deep_dive():
    lead_data = request.get_json(silent=True) or {}
    report_id = str(uuid.uuid4())

    def generate():
        client = anthropic.Anthropic()
        messages = []

        company_name = lead_data.get("company_name", "Unknown")
        yield f"data: REPORT_ID|{report_id}\n\n"
        yield f"data: Starting deep dive on {company_name}...\n\n"

        user_message = (
            f"Research the following lead for Tre Borden /Co:\n\n"
            f"Company: {company_name}\n"
            f"Type: {lead_data.get('type', '')}\n"
            f"Location: {lead_data.get('location', '')}\n"
            f"Geographic Area: {lead_data.get('geographic_area', '')}\n"
            f"Why a Lead: {lead_data.get('why_a_lead', '')}\n"
            f"ICP Score: {lead_data.get('icp_score', '')}\n"
            f"Source URL: {lead_data.get('source_url', '')}\n\n"
            f"Use this as your starting point and search for current, detailed information "
            f"across the five research areas."
        )
        messages.append({"role": "user", "content": user_message})

        max_iterations = 20
        iteration = 0

        while True:
            iteration += 1
            if iteration > max_iterations:
                yield "data: Search loop safety limit reached.\n\n"
                yield f"data: ERROR|Deep dive did not complete within iteration limit\n\n"
                return

            while True:
                try:
                    response = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=4096,
                        system=DEEP_DIVE_SYSTEM_PROMPT,
                        tools=DEEP_DIVE_TOOLS,
                        messages=messages
                    )
                    break
                except anthropic.RateLimitError:
                    yield "data: Rate limit hit, waiting 60 seconds...\n\n"
                    for i in range(12):
                        time.sleep(5)
                        yield f"data: Waiting... ({(i+1)*5}s)\n\n"
                    yield "data: Retrying...\n\n"
                except Exception as e:
                    yield f"data: ERROR|{type(e).__name__}: {str(e)}\n\n"
                    return

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                yield "data: Deep dive complete — no report was saved.\n\n"
                yield f"data: ERROR|Claude finished without calling save_deep_dive_report\n\n"
                return

            elif response.stop_reason == "tool_use":
                tool_results = []

                for block in response.content:
                    if block.type == "tool_use":
                        if block.name == "save_deep_dive_report":
                            yield "data: Saving deep dive report...\n\n"

                            # Build the report, tolerating missing/malformed sections
                            sections = {}
                            for key in ("project_status", "news_and_media",
                                        "existing_art_attachments", "key_principals",
                                        "commissioning_history"):
                                raw = block.input.get(key) or {}
                                sections[key] = {
                                    "findings":     raw.get("findings", ""),
                                    "sources":      raw.get("sources", []) if isinstance(raw.get("sources"), list) else [],
                                    "completeness": raw.get("completeness", "Limited"),
                                }

                            report = {
                                "report_id":      report_id,
                                "company_name":   company_name,
                                "geographic_area": lead_data.get("geographic_area", ""),
                                "lead_data":      lead_data,
                                "report_sections": sections,
                                "created_at":     datetime.now(timezone.utc).isoformat(),
                            }

                            try:
                                report_path = os.path.join(REPORTS_DIR, f"{report_id}.json")
                                with open(report_path, "w") as f:
                                    json.dump(report, f, indent=2)
                            except Exception as e:
                                yield f"data: Warning: could not save report file: {e}\n\n"

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": "Report saved."
                            })
                            yield f"data: DONE|{report_id}\n\n"
                            return
                        # Do NOT handle web_search — server-side tool.

                if tool_results:
                    messages.append({"role": "user", "content": tool_results})

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app.route("/reports")
def reports_archive():
    return render_template("reports.html")


@app.route("/api/reports", methods=["GET"])
def list_reports():
    reports = []
    try:
        for filename in os.listdir(REPORTS_DIR):
            if not filename.endswith(".json"):
                continue
            try:
                with open(os.path.join(REPORTS_DIR, filename)) as f:
                    data = json.load(f)
                reports.append({
                    "report_id":      data.get("report_id", ""),
                    "company_name":   data.get("company_name", ""),
                    "geographic_area": data.get("geographic_area", ""),
                    "created_at":     data.get("created_at", ""),
                })
            except Exception:
                continue  # skip malformed files
    except FileNotFoundError:
        pass

    reports.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return jsonify(reports)


@app.route("/api/reports/<report_id>", methods=["GET"])
def get_report(report_id):
    # Sanitise the report_id to prevent path traversal
    safe_id = os.path.basename(report_id)
    report_path = os.path.join(REPORTS_DIR, f"{safe_id}.json")
    if not os.path.exists(report_path):
        return jsonify({"error": "Report not found"}), 404
    with open(report_path) as f:
        return jsonify(json.load(f))


@app.route("/deep-dive/save", methods=["POST"])
def deep_dive_save():
    data = request.get_json(silent=True) or {}
    report_id = data.get("report_id", "")
    if not report_id:
        return jsonify({"error": "report_id is required"}), 400

    safe_id = os.path.basename(report_id)
    report_path = os.path.join(REPORTS_DIR, f"{safe_id}.json")
    if not os.path.exists(report_path):
        return jsonify({"error": "Report not found"}), 404

    with open(report_path) as f:
        report = json.load(f)

    message = save_deep_dive_to_spreadsheet(report)
    if message.startswith("Lead '") and "not found" in message:
        return jsonify({"error": message}), 404
    if message.startswith("leads.xlsx not found"):
        return jsonify({"error": message}), 404
    return jsonify({"message": message})


@app.route("/report")
def report():
    return render_template("report.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
