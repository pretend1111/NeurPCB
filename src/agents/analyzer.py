"""
analyzer.py
The Analyzer agent reads the raw schematic components and clusters them into modules.
"""
import json
from agents.llm_client import query_llm

def chunk_schematic(components: list, nets: list) -> list:
    """
    Groups raw schematic components into blackbox modules.
    """
    print("[Analyzer] Identifying logical modules from schema...")
    
    sys_prompt = (
        "You are an expert PCB Analyzer Agent.\n"
        "Your task is to chunk (group) the provided schematic components into cohesive functional modules.\n"
        "Output format required: {\"modules\": [{\"module_id\": \"Module_XXX\", \"components\": [\"U1\", \"C1\"], \"rationale\": \"...\"}]}"
    )
    
    user_prompt = (
        f"Components List: {json.dumps(components)}\n"
        f"Net Connections: {json.dumps(nets)}\n\n"
        "Please output the assigned modules."
    )
    
    resp = query_llm(sys_prompt, user_prompt)
    modules = resp.get("modules", [])
    print(f"[Analyzer] Extracted {len(modules)} cohesive modules.")
    return modules
