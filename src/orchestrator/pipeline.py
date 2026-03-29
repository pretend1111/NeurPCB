"""
pipeline.py
The centralized Orchestrator that stitches together the Multi-Agent PCB Design Workflow.
Simulates: Read Sch -> Chunking -> Global Layout -> Iterative Sub-layout.
"""
import json
import time
from agents.analyzer import chunk_schematic
from agents.architect import orchestrate_global_layout
from agents.module_placer import place_module_internals

# 1. Mock Schematic Data
MOCK_COMPONENTS = [
    {"ref": "U1", "val": "ESP32", "type": "MCU"},
    {"ref": "C1", "val": "10uF", "type": "CAP"},
    {"ref": "C2", "val": "100nF", "type": "CAP"},
    {"ref": "J1", "val": "USB-C", "type": "CONN"},
    {"ref": "D1", "val": "TVS", "type": "DIODE"}
]
MOCK_NETS = [
    {"net": "VCC", "nodes": ["J1.VBUS", "U1.3V3", "C1.1", "C2.1"]},
    {"net": "GND", "nodes": ["J1.GND", "U1.GND", "C1.2", "C2.2", "D1.2"]},
    {"net": "USB_DP", "nodes": ["J1.D+", "D1.1", "U1.DP"]}
]
BOARD_DIM = (50, 50)
USER_PREFS = "USB connector J1 must be securely placed along the left board edge."

def run_pipeline():
    print("\n" + "="*50)
    print(" EDA MULTI-AGENT PIPELINE STARTED ")
    print("="*50 + "\n")
    
    # PHASE 1: Analyzer (Read Sch -> Chunking)
    print(">>> [STAGE 1] ANALYZER TRIGGERED")
    modules = chunk_schematic(MOCK_COMPONENTS, MOCK_NETS)
    print(f"\n[Artifact Output] Analyzer Output:\n{json.dumps(modules, indent=2)}\n")
    time.sleep(1)
    
    abstract_modules = []
    for m in modules:
        if isinstance(m, dict) and "module_id" in m:
            abstract_modules.append({
                "id": m["module_id"], 
                "components_count": len(m.get("components", [])),
                "rationale": m.get("rationale", "")
            })
            
    if not abstract_modules:
        print("[Error] Analyzer failed to return properly grouped modules. Exiting.")
        return
    
    # PHASE 2: Architect (Global Layout)
    print(">>> [STAGE 2] ARCHITECT TRIGGERED")
    global_layout = orchestrate_global_layout(BOARD_DIM, abstract_modules, MOCK_NETS, USER_PREFS)
    print(f"\n[Artifact Output] Architect Global Coordinates:\n{json.dumps(global_layout, indent=2)}\n")
    time.sleep(1)
    
    # PHASE 3: Module Placer (Iterative sub-layouts)
    print(">>> [STAGE 3] MODULE PLACER TRIGGERED")
    final_placements = {}
    for mod in modules:
        mod_id = mod.get("module_id")
        comps = mod.get("components", [])
        
        # Find allocated bbox from global layout
        mod_bbox = [20, 20] # fallback defaults
        for gl_mod in global_layout:
            if gl_mod.get("module_id") == mod_id:
                mod_bbox = gl_mod.get("bbox_size", [20, 20])
                break
                
        sub_layout = place_module_internals(mod_id, comps, tuple(mod_bbox))
        final_placements[mod_id] = sub_layout
        
    print(f"\n[Artifact Output] Final Internal Placements:\n{json.dumps(final_placements, indent=2)}\n")
    
    print("="*50)
    print(" EDA MULTI-AGENT PIPELINE COMPLETED ")
    print("="*50 + "\n")

if __name__ == "__main__":
    run_pipeline()
