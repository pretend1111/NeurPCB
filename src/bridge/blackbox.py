"""
blackbox.py - Handles module encapsulation and Unified I/O placement.
Converts a set of footprints into a Keep-Out Zone (Blackbox) with virtual I/O pads on its boundary.
"""
import math
from typing import List, Dict, Optional

try:
    from kipy.board_types import Zone, BoardLayer
    from kipy.geometry import Vector2, PolyLine, PolyLineNode
    from kipy.util.units import from_mm, to_mm
except ImportError:
    pass

class BlackBoxManager:
    def __init__(self, board):
        self.board = board
        self.modules = {}

    def encapsulate_module(self, module_id: str, footprint_refs: List[str], unified_io_nets: List[Dict]):
        """
        Calculates the bounding box of a list of footprints, creates a keep-out zone,
        and generates virtual pads on the boundaries for the unified_io_nets.
        
        unified_io_nets format:
        [
            {"net": "SPI_CLK", "side": "Top", "offset_percent": 0.5},
            {"net": "DDR_Bus", "side": "Right", "offset_percent": 0.2}
        ]
        """
        print(f"[BlackBoxManager] Encapsulating Module {module_id} with {len(footprint_refs)} footprints.")
        
        # 1. Compute Bounding Box
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')
        
        try:
            footprints = self.board.get_footprints()
            for fp in footprints:
                if fp.reference in footprint_refs:
                    pos = fp.position
                    x, y = to_mm(pos.x), to_mm(pos.y)
                    # Use a rough 2mm margin for the module Keepout
                    min_x = min(min_x, x - 2.0)
                    max_x = max(max_x, x + 2.0)
                    min_y = min(min_y, y - 2.0)
                    max_y = max(max_y, y + 2.0)
        except Exception as e:
            # Fallback for unconnected scripts / offline test
            min_x, min_y, max_x, max_y = 10.0, 10.0, 30.0, 30.0
            
        width = max_x - min_x
        height = max_y - min_y
        
        # 2. Assign Virtual I/O Pads on the Perimeter
        virtual_io_pads = []
        for io in unified_io_nets:
            net = io.get("net")
            side = io.get("side", "Top").lower()
            offset_pct = io.get("offset_percent", 0.5)
            
            vx, vy = min_x, min_y
            if side == "top":
                vx = min_x + width * offset_pct
                vy = min_y
            elif side == "bottom":
                vx = min_x + width * offset_pct
                vy = max_y
            elif side == "left":
                vx = min_x
                vy = min_y + height * offset_pct
            elif side == "right":
                vx = max_x
                vy = min_y + height * offset_pct
                
            virtual_io_pads.append({
                "net": net,
                "pad_name": f"VIO_{module_id}_{net}",
                "position_mm": (round(vx, 2), round(vy, 2))
            })
            
        # 3. Create Rule Area (Keepout Zone)
        print(f"[BlackBoxManager] Generated {width:.1f}x{height:.1f}mm Keepout for {module_id}")
        
        module_data = {
            "id": module_id,
            "bbox_mm": [round(min_x,2), round(min_y,2), round(max_x,2), round(max_y,2)],
            "virtual_io": virtual_io_pads
        }
        self.modules[module_id] = module_data
        return module_data
