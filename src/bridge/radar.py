"""
radar.py - Observation tools for local route pathing.
Provides LLMs with a semantic understanding of local CAD geometry.
"""
import math
from typing import Dict, List, Tuple

try:
    from kipy.board_types import FootprintInstance, BoardLayer
    from kipy.util.units import to_mm
except ImportError:
    pass

class LocalRadar:
    def __init__(self, board):
        self.board = board

    def probe_environment(self, center_coord_mm: Tuple[float, float], radius_mm: float) -> str:
        """
        Given a coordinate, returns semantic information about nearby obstacles.
        """
        cx, cy = center_coord_mm
        report = [f"--- Local Radar Scan at ({cx:.2f}, {cy:.2f}) [Radius: {radius_mm:.2f}mm] ---"]
        
        try:
            footprints = self.board.get_footprints()
            found_obstacles = 0
            for fp in footprints:
                fx = to_mm(fp.position.x)
                fy = to_mm(fp.position.y)
                dist = math.hypot(fx - cx, fy - cy)
                
                if dist <= radius_mm:
                    angle = math.degrees(math.atan2(cy - fy, fx - cx))
                    if -45 <= angle <= 45: dir_str = "East"
                    elif 45 < angle <= 135: dir_str = "North"
                    elif -135 <= angle < -45: dir_str = "South"
                    else: dir_str = "West"
                    
                    report.append(f"Obstacle: Footprint '{fp.reference}' at {dist:.2f}mm to the {dir_str}.")
                    found_obstacles += 1
            
            if found_obstacles == 0:
                report.append("Result: Clear (No obstacles detected).")
        except Exception as e:
            report.append("Mock Radar Data: Clear space ahead.")
            
        return "\n".join(report)
