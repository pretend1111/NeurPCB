"""
kicad_scrambler.py
Randomly scatters all footprints outside the board area to simulate a raw unplaced netlist layout.
"""
import random
try:
    from kipy import KiCad
    from kipy.geometry import Vector2, Angle
    from kipy.util.units import from_mm
except ImportError:
    pass

def scramble_board():
    print("-" * 50)
    print(" KICAD CHAOS SCRAMBLER INITIATED")
    print("-" * 50)
    print("[Scrambler] Connecting to KiCad IPC Server...")
    
    try:
        with KiCad() as kicad:
            board = kicad.get_board()
            footprints = board.get_footprints()
            
            if not footprints:
                print("[Scrambler] FATAL: No footprints detected. Board is empty.")
                return
                
            print(f"[Scrambler] Detected {len(footprints)} footprints. Engaging chaos engine...")
            
            updated_fps = []
            for fp in footprints:
                # unlock every footprint to ensure absolute scrambling
                fp.locked = False
                
                # Scatter them to a chaotic grid outside the main board area
                rand_x = random.uniform(-180, -20)
                rand_y = random.uniform(-180, -20)
                rand_angle = random.choice([0.0, 90.0, 180.0, 270.0])
                
                fp.position = Vector2.from_xy_mm(rand_x, rand_y)
                fp.orientation = Angle.from_degrees(rand_angle)
                updated_fps.append(fp)
                
            # Perform bulk update across IPC
            board.update_items(updated_fps)
            print(f"[Scrambler] BOOM! {len(updated_fps)} footprints have been hurled outside the board.")
            print("[Scrambler] Your perfectly routed board is now officially a disaster.")
            print("-" * 50)
    except Exception as e:
        print(f"[Scrambler] Error executing scramble: {e}")

if __name__ == "__main__":
    scramble_board()
