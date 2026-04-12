import anthropic
import time
from dotenv import load_dotenv
from prompts import get_system_prompt
from tools import save_leads_to_spreadsheet, get_existing_leads_for_segment, get_all_leads_for_segment
import json
import os
from flask import Flask, render_template, request, Response, send_file, stream_with_context, jsonify

load_dotenv()

app = Flask(__name__)

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
    data_dir = os.environ.get("DATA_DIR", ".")
    filepath = os.path.join(data_dir, "leads.xlsx")
    return send_file(
        filepath,
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        download_name="TreBorden_Leads.xlsx"
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
