import anthropic
import time
from dotenv import load_dotenv
from prompts import get_system_prompt
from tools import save_leads_to_spreadsheet, get_existing_leads_for_segment

load_dotenv()

SEGMENT = input("Which segment? (corporate / public_sector): ").strip().lower()

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

def run_agent():
    client = anthropic.Anthropic()
    messages = []

    existing = get_existing_leads_for_segment(SEGMENT)
    system_prompt = get_system_prompt(SEGMENT, existing if existing else None)

    if SEGMENT == "corporate":
        user_message = (
            "Please search for potential corporate art program leads for Tre Borden /Co "
            "in Los Angeles and surrounding areas. Find at least 5 strong leads, evaluate "
            "them carefully, and save the results to the spreadsheet."
        )
    else:
        user_message = (
            "Please search for potential public sector art commission leads for Tre Borden /Co "
            "in Los Angeles and surrounding areas. Focus on active RFPs, percent-for-art "
            "opportunities, and public construction projects with budgets over $100k. Find at "
            "least 5 strong leads, evaluate them carefully, and save the results to the spreadsheet."
        )

    print(f"Starting lead generation agent — segment: {SEGMENT}")
    if existing:
        print(f"Excluding {len(existing)} existing leads from this run.")
    print("-" * 50)

    messages.append({"role": "user", "content": user_message})

    max_iterations = 20
    iteration = 0

    while True:
        iteration += 1
        if iteration > max_iterations:
            print("Search loop safety limit reached.")
            break

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
                print("Rate limit hit, waiting 60 seconds...")
                time.sleep(60)
                print("Retrying...")

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    print(f"Agent: {block.text}")
            break

        elif response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    print(f"Using tool: {block.name}")

                    if block.name == "save_leads_to_spreadsheet":
                        result, actually_saved = save_leads_to_spreadsheet(block.input.get("leads", []), SEGMENT)
                        print(result)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result
                        })
                    else:
                        # web_search (server-side): API requires a tool_result for every
                        # tool_use before the next call, even though the search runs on
                        # Anthropic's servers. Pass empty content.
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "",
                        })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

if __name__ == "__main__":
    run_agent()
