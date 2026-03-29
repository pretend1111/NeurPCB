"""
module_placer.py
The Local Placer agent arranges atomic components inside the strict bounding box of a module.
"""
import json
from agents.llm_client import query_llm

def place_module_internals(module_id: str, components: list, local_bbox: tuple) -> list:
    """
    Determines the relative `(x, y)` location for each discrete component within its assigned module keepout.
    """
    print(f"[ModulePlacer] Calculating internal micro-layout for {module_id}...")
    
    sys_prompt = (
        "You are an expert PCB Local Placer Agent.\n"
        "Your task is to arrange specific electronic micro-components optimally within a restricted bounding box.\n"
        "Output format required: {\"placements\": [{\"ref\": \"U1\", \"relative_pos_mm\": [x, y], \"rotation\": 0}]}"
    )
    
    user_prompt = (
        f"Module Region ID: {module_id}\n"
        f"Bounding Box Allocation (Max width x height) mm: {local_bbox[0]} x {local_bbox[1]}\n"
        f"Components details: {json.dumps(components)}\n\n"
        "Please specify relative internal layouts."
    )
    
    resp = query_llm(sys_prompt, user_prompt)
    placements = resp.get("placements", [])
    print(f"[ModulePlacer] Complete. Placed {len(placements)} components tightly.")
    return placements
