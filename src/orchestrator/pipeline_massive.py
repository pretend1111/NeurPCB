"""
pipeline_massive.py
Massive-scale test with 40+ components and complete multi-layer A* router for visualization.
"""
import json
import time
import heapq

from agents.analyzer import chunk_schematic
from agents.architect import orchestrate_global_layout
from agents.module_placer import place_module_internals

COMPONENTS = []
for i in range(1, 9): COMPONENTS.append({"ref": f"C_MCU{i}", "val": "0.1uF", "desc": "MCU Decap", "type": "CAP"})
COMPONENTS.extend([
    {"ref": "U_MCU", "val": "ESP32-S3", "desc": "Main Processor", "type": "MCU"},
    {"ref": "U_PMIC", "val": "EA3036", "desc": "Power Management", "type": "PMIC"},
    {"ref": "L_PWR1", "val": "2.2uH", "desc": "Buck Inductor", "type": "IND"},
    {"ref": "L_PWR2", "val": "2.2uH", "desc": "Buck Inductor", "type": "IND"},
    {"ref": "C_PWR1", "val": "22uF", "type": "CAP"},
    {"ref": "C_PWR2", "val": "22uF", "type": "CAP"},
    {"ref": "C_PWR3", "val": "22uF", "type": "CAP"},
    {"ref": "C_PWR4", "val": "22uF", "type": "CAP"},
    {"ref": "U_FLASH", "val": "W25Q128", "desc": "External Flash", "type": "FLASH"},
    {"ref": "U_RAM", "val": "APS6404", "desc": "PSRAM", "type": "PSRAM"},
    {"ref": "C_MEM1", "val": "0.1uF", "type": "CAP"},
    {"ref": "C_MEM2", "val": "0.1uF", "type": "CAP"},
    {"ref": "U_HUB", "val": "CH334", "desc": "USB 2.0 Hub", "type": "USB_HUB"},
    {"ref": "Y_HUB", "val": "12MHz", "desc": "Hub Crystal", "type": "XTAL"},
    {"ref": "C_HUB1", "val": "1uF", "type": "CAP"},
    {"ref": "C_HUB2", "val": "1uF", "type": "CAP"},
    {"ref": "U_IMU", "val": "MPU6050", "desc": "6-Axis Sensor", "type": "SENSOR"},
    {"ref": "U_TEMP", "val": "SHTC3", "desc": "Temp Sensor", "type": "SENSOR"},
    {"ref": "J_MAIN", "val": "USB-C", "desc": "Main Power/Data", "type": "CONN"}
])
for i in range(1, 11): COMPONENTS.append({"ref": f"R_IO{i}", "val": "4.7k", "type": "RES"})

NETS = [
    {"net": "3V3", "nodes": ["U_PMIC.VOUT", "C_PWR1.1", "C_PWR2.1", "U_MCU.VDD", "U_FLASH.VCC", "U_RAM.VCC", "U_HUB.VDD", "U_IMU.VDD", "U_TEMP.VDD"]},
    {"net": "GND", "nodes": ["J_MAIN.GND", "U_PMIC.GND", "U_MCU.GND", "U_FLASH.GND", "U_RAM.GND", "U_HUB.GND", "U_IMU.GND", "U_TEMP.GND"] + [f"C_MCU{i}.2" for i in range(1,9)]},
    {"net": "SPI_CLK", "nodes": ["U_MCU.SCLK", "U_FLASH.CLK", "U_RAM.CLK"]},
    {"net": "SPI_CS0", "nodes": ["U_MCU.CS0", "U_FLASH.CS"]},
    {"net": "SPI_CS1", "nodes": ["U_MCU.CS1", "U_RAM.CS"]},
    {"net": "SPI_MISO", "nodes": ["U_MCU.MISO", "U_FLASH.DO", "U_RAM.DO"]},
    {"net": "SPI_MOSI", "nodes": ["U_MCU.MOSI", "U_FLASH.DI", "U_RAM.DI"]},
    {"net": "I2C_SCL", "nodes": ["U_MCU.SCL", "U_IMU.SCL", "U_TEMP.SCL"]},
    {"net": "I2C_SDA", "nodes": ["U_MCU.SDA", "U_IMU.SDA", "U_TEMP.SDA"]},
    {"net": "USB_DP", "nodes": ["J_MAIN.DP", "U_HUB.DP_U"]},
    {"net": "USB_DN", "nodes": ["J_MAIN.DN", "U_HUB.DN_U"]}
]

BOARD_DIM = (100, 100) # mm
USER_PREFS = "Place J_MAIN on the left edge. Place U_IMU on the right edge. Group memories precisely. Keep PMIC away from Sensors."

def manhattan(p1, p2):
    return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])

def a_star_route(start, end, obstacles, width, height):
    start_grid = (int(max(0, start[0])), int(max(0, start[1])))
    end_grid = (int(max(0, end[0])), int(max(0, end[1])))
    
    open_set = []
    heapq.heappush(open_set, (0, start_grid))
    came_from = {}
    g_score = {start_grid: 0}
    f_score = {start_grid: manhattan(start_grid, end_grid)}
    
    while open_set:
        _, current = heapq.heappop(open_set)
        if current == end_grid:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.append(start_grid)
            return path[::-1]
            
        for dx, dy in [(0,1), (0,-1), (1,0), (-1,0)]:
            neighbor = (current[0]+dx, current[1]+dy)
            if not (0 <= neighbor[0] < width and 0 <= neighbor[1] < height):
                continue
            if neighbor in obstacles and neighbor != end_grid:
                continue
                
            tent_g = g_score[current] + 1
            if neighbor not in g_score or tent_g < g_score[neighbor]:
                came_from[neighbor] = current
                g_score[neighbor] = tent_g
                f_score[neighbor] = tent_g + manhattan(neighbor, end_grid)
                heapq.heappush(open_set, (f_score[neighbor], neighbor))
    return None

def run_massive_pipeline():
    print("="*60)
    print(" MASSIVE EDA PIPELINE WITH CORRIDOR A* ROUTING")
    print("="*60)
    
    modules = chunk_schematic(COMPONENTS, NETS)
    print(f"\n[INFO] Chunker processed ~40 components into {len(modules)} strategic modules.")
    
    abstract_modules = []
    for m in modules:
        if "module_id" in m:
            abstract_modules.append({
                "id": m["module_id"], 
                "components_count": len(m.get("components", [])),
                "rationale": m.get("rationale", "")
            })
            
    global_layout = orchestrate_global_layout(BOARD_DIM, abstract_modules, NETS, USER_PREFS)
    
    all_obstacles = set()
    mod_bboxes = {}
    for gl_mod in global_layout:
        mod_id = gl_mod["module_id"]
        x, y = gl_mod.get("position_mm", [10,10])
        w, h = gl_mod.get("bbox_size", [25,25])
        mod_bboxes[mod_id] = (x, y, w, h)
        
        for gx in range(int(x), int(x+w)):
            for gy in range(int(y), int(y+h)):
                all_obstacles.add((gx, gy))
    
    final_placements = {}
    master_comp_pos = {} 
    comp_to_mod = {}
    
    for mod in modules:
        mod_id = mod.get("module_id")
        comps = mod.get("components", [])
        
        x, y, w, h = mod_bboxes.get(mod_id, (50,50,25,25))
        sub_layout = place_module_internals(mod_id, comps, (w, h))
        final_placements[mod_id] = sub_layout
        
        for c in sub_layout:
            ref = c["ref"]
            rx, ry = c.get("relative_pos_mm", [w/2, h/2])
            cx, cy = x + rx, y + ry
            master_comp_pos[ref] = (cx, cy)
            comp_to_mod[ref] = mod_id
            
    print("\n[ROUTER] Starting Global A* Trace Routing")
    svg_traces = []
    colors = ["#FF3366", "#33CCFF", "#66FF33", "#FFCC00", "#CC33FF"]
    color_idx = 0
    
    success_routes = 0
    total_routes = 0
    
    for net in NETS:
        nodes = net["nodes"]
        for i in range(len(nodes)-1):
            total_routes += 1
            refA = nodes[i].split('.')[0]
            refB = nodes[i+1].split('.')[0]
            
            if refA not in master_comp_pos or refB not in master_comp_pos:
                continue
                
            posA = master_comp_pos[refA]
            posB = master_comp_pos[refB]
            modA = comp_to_mod.get(refA)
            modB = comp_to_mod.get(refB)
            
            safe_obs = set(all_obstacles)
            for mod in [modA, modB]:
                if mod in mod_bboxes:
                    x,y,w,h = mod_bboxes[mod]
                    for gx in range(int(x), int(x+w)):
                        for gy in range(int(y), int(y+h)):
                            safe_obs.discard((gx, gy))
                            
            path = a_star_route(posA, posB, safe_obs, BOARD_DIM[0], BOARD_DIM[1])
            if path:
                success_routes += 1
                color = colors[color_idx % len(colors)]
                color_idx += 1
                
                path_str = " ".join([f"{int(px*10)},{int(py*10)}" for px, py in path])
                svg_traces.append(f'<polyline points="{path_str}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
                
    print(f"\n[INFO] Routing Completion Rate: {success_routes}/{total_routes} ({(success_routes/max(1,total_routes))*100:.1f}%)")
    
    print("\n--- GENERATING SVG RENDER ---")
    svg = ['<svg viewBox="0 0 1000 1000" width="1000" height="1000" xmlns="http://www.w3.org/2000/svg">']
    svg.append('<rect x="0" y="0" width="1000" height="1000" fill="#1e1e1e" stroke="#000" stroke-width="4"/>')
    svg.append('<text x="10" y="20" font-family="monospace" font-size="16" fill="#0f0">MASSIVE AI-LAYOUT (40+ COMPS) + CORRIDOR ROUTING</text>')
    
    svg.extend(svg_traces)
    
    for gl_mod in global_layout:
        x, y = gl_mod.get("position_mm", [10,10])
        w, h = gl_mod.get("bbox_size", [15,15])
        mx, my, mw, mh = x*10, y*10, w*10, h*10
        svg.append(f'<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" fill="#333333" stroke="#fff" stroke-width="2" stroke-dasharray="5,5" fill-opacity="0.6"/>')
        svg.append(f'<text x="{mx+10}" y="{my+20}" font-family="verdana" font-weight="bold" font-size="14" fill="#aaa">{gl_mod.get("module_id")}</text>')
        
    for ref, pos in master_comp_pos.items():
        cx, cy = pos[0]*10, pos[1]*10
        svg.append(f'<circle cx="{cx}" cy="{cy}" r="5" fill="#ffaa00"/>')
        svg.append(f'<text x="{cx+6}" y="{cy-6}" font-family="verdana" font-size="10" fill="#ffddaa">{ref}</text>')
                
    svg.append('</svg>')
    
    with open("massive_render.svg", "w") as f:
        f.write("\n".join(svg))
        
    print("[SUCCESS] SVG output saved to massive_render.svg")

if __name__ == "__main__":
    run_massive_pipeline()
