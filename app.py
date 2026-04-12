import anthropic
import time
import uuid
import json
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from prompts import get_system_prompt
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

    def generate():
        client = anthropic.Anthropic()
        messages = []
        saved_leads = []

        budget_instruction = (
            f" Prioritize leads whose estimated art commissioning budget is likely to fall within {budget}."
            if budget != "Any Budget" else ""
        )

        if segment == "corporate":
            user_message = (
                f"Please search for potential corporate art program leads for Tre Borden /Co "
                f"in the {geography} area. Find at least 5 strong leads, evaluate "
                f"them carefully, and save the results to the spreadsheet. "
                f"Set the `geographic_area` field to \"{geography}\" for every lead you save."
                f"{budget_instruction}"
            )
        else:
            user_message = (
                f"Please search for potential public sector art commission leads for Tre Borden /Co "
                f"in the {geography} area. Focus on active RFPs, percent-for-art "
                f"opportunities, and public construction projects with budgets over $100k. Find at "
                f"least 5 strong leads, evaluate them carefully, and save the results to the spreadsheet. "
                f"Set the `geographic_area` field to \"{geography}\" for every lead you save."
                f"{budget_instruction}"
            )

        existing = get_existing_leads_for_segment(segment)
        system_prompt = get_system_prompt(segment, existing if existing else None)

        yield f"data: Starting {segment.replace('_', ' ')} lead search...\n\n"
        messages.append({"role": "user", "content": user_message})

        max_iterations = 20
        iteration = 0

        while True:
            iteration += 1
            if iteration > max_iterations:
                yield "data: Search loop safety limit reached.\n\n"
                yield f"data: DONE|{json.dumps(saved_leads)}\n\n"
                return

            while True:
                try:
                    response = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=4096,
                        system=system_prompt,
                        tools=TOOLS,
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
                    yield f"data: ERROR: {type(e).__name__}: {str(e)}\n\n"
                    return

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if hasattr(block, "text"):
                        yield f"data: {block.text}\n\n"
                yield f"data: DONE|{json.dumps(saved_leads)}\n\n"
                break

            elif response.stop_reason == "tool_use":
                tool_results = []

                for block in response.content:
                    if block.type == "tool_use":
                        if block.name == "save_leads_to_spreadsheet":
                            yield "data: Saving leads to spreadsheet...\n\n"
                            try:
                                result, actually_saved = save_leads_to_spreadsheet(block.input.get("leads", []), segment)
                                saved_leads = actually_saved
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": result
                                })
                            except Exception as e:
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": f"Error saving leads: {str(e)}",
                                    "is_error": True
                                })
                            # Early return to avoid Railway timeout
                            yield f"data: DONE|{json.dumps(saved_leads)}\n\n"
                            return
                        # Do NOT handle web_search here — it's a server-side tool.

                if tool_results:
                    messages.append({"role": "user", "content": tool_results})

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/download")
def download():
    filepath = os.path.join(DATA_DIR, "leads.xlsx")
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
    return jsonify({"message": message})


@app.route("/report")
def report():
    return render_template("report.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
