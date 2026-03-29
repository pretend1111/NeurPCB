"""
kicad_executor.py
Actuates LLM-calculated coordinates onto the live KiCad board using atomic batch updates.
"""
try:
    from kipy import KiCad
    from kipy.geometry import Vector2
    from kipy.util.units import from_mm
except ImportError:
    pass

class KiCadExecutor:
    def __init__(self):
        pass
        
    def execute_placements(self, master_comp_positions: dict):
        """
        master_comp_positions format: {"U1": (10.5, 20.0), "C1": (12.0, 20.0)}
        """
        print(f"[KiCadExecutor] Approaching KiCad IPC to push {len(master_comp_positions)} moving events...")
        try:
            with KiCad() as kicad:
                board = kicad.get_board()
                footprints = board.get_footprints()
                
                updated_fps = []
                for fp in footprints:
                    if fp.reference in master_comp_positions:
                        new_x, new_y = master_comp_positions[fp.reference]
                        fp.position = Vector2.from_xy_mm(new_x, new_y)
                        updated_fps.append(fp)
                        
                if updated_fps:
                    board.update_items(updated_fps) 
                    
                print(f"[KiCadExecutor] Successfully applied geometric placement to {len(updated_fps)} footprints live!")
                return True
        except Exception as e:
            print(f"\n[KiCadExecutor] KiCad IPC connection failed: {e}")
            return False
            
    def run_fast_critic_check(self, master_comp_positions: dict) -> list:
        """
        Critic Fast Review Level 1: Predicts courtyard/overlap overlaps in native python geometry
        prior to asking KiCad IPC to run full DRC check API, speeding up loop times.
        """
        errors = []
        refs = list(master_comp_positions.keys())
        for i in range(len(refs)):
            for j in range(i+1, len(refs)):
                p1 = master_comp_positions[refs[i]]
                p2 = master_comp_positions[refs[j]]
                # simple euclidean heuristic for overlapping
                dist = ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5
                if dist < 1.0: 
                    errors.append(f"[Critic Fast-Check] Overlap Risk: {refs[i]} and {refs[j]} span distance is only {dist:.2f}mm!")
        return errors
