import anthropic
import time
from datetime import date
from dotenv import load_dotenv
from tools import save_leads_to_spreadsheet
import json
import os
from flask import Flask, render_template, request, Response, send_file, stream_with_context

load_dotenv()

app = Flask(__name__)

def get_system_prompts():
    today = date.today().strftime("%B %d, %Y")
    return {
        "corporate": """You are a business development researcher for Tre Borden /Co, a creative studio 
and production company based in Los Angeles that curates and commissions art for corporate spaces.

Their ideal clients are:
- Real estate developers building or renovating commercial/corporate spaces in LA and surrounding areas
- Architecture and interior design firms working on corporate office projects
- Large companies announcing new headquarters, office relocations, or major renovations
- Property management companies with large commercial portfolios in the LA region

When searching for leads, look for signals like:
- New office construction or renovation announcements
- Companies relocating or expanding their LA presence
- Architecture firms winning corporate office contracts
- Real estate developers launching new commercial projects
- Requests for proposals (RFPs) related to corporate art programs

For each lead you find, extract:
- company_name: the clean canonical name of the company only — no parentheticals, 
  no office locations, no legal suffixes like LLP or Inc. Save descriptive detail 
  to the notes field instead. Example: "Gensler" not "Gensler (Los Angeles Office)"
- type: one of "Developer", "Architecture Firm", or "Corporate Client"
- location: city and state
- why_a_lead: specific reason this company is a good lead (be concrete - mention the specific project or announcement)
- company_website: their main website URL
- source_url: the specific URL where the information on which the good lead determination is based is located
- potential_contact: name and title of the most relevant person if findable, otherwise ""
- icp_score: a number from 1-10 based on the following rubric:
    1-3: relevant company type but no specific trigger — no expansion, renovation, or project announcement
    4-6: active trigger exists (expansion, relocation, renovation) but no evidence of art investment or creative design culture
    7-9: active trigger plus evidence of design investment — past art commissions, design-forward reputation, creative workplace culture
    10: active trigger, strong design culture, and something highly specific — open RFP, direct connection to Tre Borden's past clients, or project at exactly the right commissioning stage
- notes: anything else relevant

Only include leads you are confident are genuinely relevant. Quality over quantity.

When you have found and evaluated leads, call the save_leads_to_spreadsheet function with your findings.""",

        "public_sector": f"""You are a business development researcher for Tre Borden /Co, a creative studio 
and production company based in Los Angeles that curates and commissions art for public and institutional spaces.

Their ideal public sector clients are:
- Municipal and government agencies in the LA region with active construction, renovation, or facility projects
- Public infrastructure projects — transit authorities, libraries, civic buildings, public plazas
- Universities and institutional campuses with capital projects underway
- Any public entity subject to percent-for-art requirements on projects over $100k

When searching for leads, prioritize:
- Active RFPs or calls for artists with confirmed budgets over $100k and deadlines that have not yet passed — explicitly discard any RFP or opportunity with a deadline prior to today's date
- Announced public construction or renovation projects where percent-for-art likely applies
- Government agencies or universities relocating or expanding

For each lead you find, extract:
- company_name: the clean canonical name of the organization only — no parentheticals or department suffixes
- type: one of "Municipal Agency", "Transit Authority", "University", or "Public Infrastructure"
- location: city and state
- why_a_lead: specific reason this is a good lead — name the specific project, RFP, or announcement
- company_website: their main website URL
- source_url: the specific URL where the information on which the good lead determination is based is located
- potential_contact: name and title of the most relevant person if findable, otherwise ""
- icp_score: a number from 1-10 based on the following rubric:
    1-3: public agency with known art program but no active project or RFP currently identified
    4-6: active project signal exists, percent-for-art likely applies, but no RFP found and budget unclear
    7-8: active RFP or call for artists identified, budget confirmed above $100k
    9-10: active RFP with budget confirmed significantly above $100k, deadline upcoming, project scope aligns closely with Tre Borden's portfolio
- notes: anything else relevant including budget if known

Only save leads you are confident score 6 or above. Do not save weak signals.

Important: today's date is {today}. Do not include any opportunities with deadlines that have already passed.

When you have found and evaluated leads, call the save_leads_to_spreadsheet function with your findings."""
    }

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
                            "why_a_lead": {"type": "string"},
                            "company_website": {"type": "string"},
                            "source_url": {"type": "string"},
                            "potential_contact": {"type": "string"},
                            "icp_score": {"type": "number"},
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

@app.route("/run", methods=["GET", "POST"])
def run():
    segment = request.args.get("segment") or request.form.get("segment", "corporate")

    def generate():
        client = anthropic.Anthropic()
        messages = []
        system_prompts = get_system_prompts()
        saved_leads = []

        if segment == "corporate":
            user_message = """Please search for potential corporate art program leads for Tre Borden /Co 
            in Los Angeles and surrounding areas. Find at least 5 strong leads, evaluate them carefully, 
            and save the results to the spreadsheet."""
        else:
            user_message = """Please search for potential public sector art commission leads for Tre Borden /Co 
            in Los Angeles and surrounding areas. Focus on active RFPs, percent-for-art opportunities, 
            and public construction projects with budgets over $100k. Find at least 5 strong leads, 
            evaluate them carefully, and save the results to the spreadsheet."""

        yield f"data: Starting {segment.replace('_', ' ')} lead search...\n\n"
        messages.append({"role": "user", "content": user_message})

        while True:
            while True:
                try:
                    response = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=8096,
                        system=system_prompts[segment],
                        tools=TOOLS,
                        messages=messages
                    )
                    break
                except anthropic.RateLimitError:
                    yield "data: Rate limit hit, waiting 60 seconds...\n\n"
                    time.sleep(60)
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
                        if block.name == "web_search":
                            yield "data: Searching the web...\n\n"
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": "Search completed"
                            })

                        elif block.name == "save_leads_to_spreadsheet":
                            yield "data: Evaluating and saving leads...\n\n"
                            result = save_leads_to_spreadsheet(block.input["leads"], segment)
                            saved_leads = block.input["leads"]
                            yield f"data: {result}\n\n"
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result
                            })

                if tool_results:
                    messages.append({"role": "user", "content": tool_results})

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/download")
def download():
    return send_file(
        "leads.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        download_name="TreBorden_Leads.xlsx"
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)