"""
architect.py
The Architect agent acts as the Global Placer, assigning top-level board real estate to Modules.
"""
import json
from agents.llm_client import query_llm

def orchestrate_global_layout(board_dim: tuple, modules: list, unified_nets: list, preferences: str) -> list:
    """
    Takes abstract module blocks and maps their bounding boxes globally on the PCB.
    """
    print("[Architect] Planning global spatial layout for module blackboxes...")
    
    sys_prompt = (
        "You are an expert PCB Architect Agent acting as a Global Placer.\n"
        "Your task is to assign spatial locations on a board for a given set of black-boxed modules.\n"
        "Do not place them overlapping. Output format required:\n"
        "{\"layout\": [{\"module_id\": \"Module_1\", \"position_mm\": [x, y], \"bbox_size\": [w, h], \"rotation_deg\": 0}]}"
    )
    
    user_prompt = (
        f"Board Dimensions (Width x Height) mm: {board_dim[0]} x {board_dim[1]}\n"
        f"Modules to place (id, estimated internal area needed, etc.): {json.dumps(modules)}\n"
        f"Inter-Module connections (Unified I/O): {json.dumps(unified_nets)}\n"
        f"User Preferences: {preferences}\n\n"
        "Please provide the macro layout."
    )
    
    resp = query_llm(sys_prompt, user_prompt)
    layout = resp.get("layout", [])
    print(f"[Architect] Successfully mapped global coordinates for {len(layout)} modules.")
    return layout
