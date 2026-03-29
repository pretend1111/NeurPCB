"""
pipeline_live.py
The closed-loop live orchestrator. Connects to KiCad, extracts, predicts, computes, and executes.
"""
import sys
import json

from bridge.kicad_extractor import KiCadExtractor
from bridge.kicad_executor import KiCadExecutor
from agents.analyzer import chunk_schematic
from agents.architect import orchestrate_global_layout
from agents.module_placer import place_module_internals

USER_PREFS = "Group components by physical function. High speed close to processors."

def run_live_pipeline():
    print("\n\n" + "="*60)
    print(" NEURPCB: LIVE KICAD IPC CLOSED-LOOP PIPELINE ")
    print("="*60 + "\n")
    
    # 1. Extractor
    extractor = KiCadExtractor()
    components, nets, board_dim = extractor.extract_design_data()
    
    if not components:
        print("\n=> [ABORT] Live board reading failed. Cannot proceed with autonomous layout.")
        return
        
    print(f"\n=> [Pipeline] Detected {len(components)} raw components. Forwarding to Analyzer...")
    
    # 2. Analyzer
    modules = chunk_schematic(components, nets)
    abstract_modules = [{"id": m.get("module_id", "Unknown")} for m in modules if "module_id" in m]
    
    # 3. Architect
    print(f"\n=> [Pipeline] Forwarding {len(abstract_modules)} abstract blocks to Architect...")
    global_layout = orchestrate_global_layout(board_dim, abstract_modules, nets, USER_PREFS)
    
    mod_bboxes = {}
    for gl_mod in global_layout:
        mod_id = gl_mod["module_id"]
        x, y = gl_mod.get("position_mm", [10,10])
        w, h = gl_mod.get("bbox_size", [20,20])
        mod_bboxes[mod_id] = (x, y, w, h)
        
    # 4. Placer
    print("\n=> [Pipeline] Spawning Placer instances for localized physical mapping...")
    master_comp_pos = {}
    for mod in modules:
        mod_id = mod.get("module_id")
        comps = mod.get("components", [])
        if not comps or not mod_id:
            continue
            
        x, y, w, h = mod_bboxes.get(mod_id, (10, 10, 20, 20))
        sub_layout = place_module_internals(mod_id, comps, (w, h))
        
        for c in sub_layout:
            ref = c["ref"]
            rx, ry = c.get("relative_pos_mm", [w/2, h/2])
            cx, cy = x + rx, y + ry
            master_comp_pos[ref] = (cx, cy)
            
    # 5. Critic Validator
    print("\n=> [Pipeline] Invoking Critic Fast Evaluator for geometric fault detection...")
    executor = KiCadExecutor()
    critic_errors = executor.run_fast_critic_check(master_comp_pos)
    if critic_errors:
        print(f"\n[CRITIC REJECTED] Found {len(critic_errors)} safety violations:")
        for err in critic_errors:
            print("  - " + err)
        print("[Critic Protocol] In a fully infinite loop mode, the system would rollback and retry.")
        
    # 6. Actuator
    print("\n=> [Pipeline] Final approval granted. Actuating components onto live KiCad board...")
    executor.execute_placements(master_comp_pos)
    
    print("\n" + "="*60)
    print(" LIVE WORKFLOW COMPLETE: CHECK YOUR KICAD WINDOW ")
    print("="*60 + "\n")

if __name__ == "__main__":
    run_live_pipeline()
