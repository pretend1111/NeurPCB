"""
kicad_extractor.py
Extracts real footprint and netlist data from an active KiCad session via kipy.
"""
import sys
try:
    from kipy import KiCad
    from kipy.util.units import to_mm
except ImportError:
    pass

class KiCadExtractor:
    def __init__(self):
        pass
        
    def extract_design_data(self):
        print("[KiCadExtractor] Attempting to connect to KiCad IPC Server...")
        try:
            with KiCad() as kicad:
                board = kicad.get_board()
                print(f"[KiCadExtractor] Connected! Reading board: {board.name}")
                
                # 1. Components
                components = []
                footprints = board.get_footprints()
                for fp in footprints:
                    if fp.reference.startswith('REF'): continue 
                    comp = {
                        "ref": fp.reference,
                        "val": fp.value,
                        "type": self._guess_type(fp.reference),
                        "position_mm": (round(to_mm(fp.position.x),2), round(to_mm(fp.position.y),2))
                    }
                    components.append(comp)
                
                # 2. Nets
                nets_dict = {}
                for fp in footprints:
                    ref = fp.reference
                    for pad in fp.pads:
                        if pad.net and pad.net.name:
                            net_name = pad.net.name
                            if net_name not in nets_dict:
                                nets_dict[net_name] = []
                            nets_dict[net_name].append(f"{ref}.{pad.number}")
                            
                netlist = []
                for net_name, nodes in nets_dict.items():
                    netlist.append({"net": net_name, "nodes": list(set(nodes))})
                    
                print(f"[KiCadExtractor] Extracted {len(components)} components and {len(netlist)} nets.")
                return components, netlist, (150, 100) # Generic fallback for board dim without analyzing Edge.Cuts
                
        except Exception as e:
            print(f"[KiCadExtractor] Failed to connect to KiCad IPC: {e}")
            return None, None, None

    def _guess_type(self, ref):
        if ref.startswith('C'): return 'CAP'
        if ref.startswith('R'): return 'RES'
        if ref.startswith('U'): return 'IC'
        if ref.startswith('J'): return 'CONN'
        if ref.startswith('L'): return 'IND'
        if ref.startswith('D'): return 'DIODE'
        return 'UNKNOWN'
