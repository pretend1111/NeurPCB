from bridge.blackbox import BlackBoxManager
from bridge.radar import LocalRadar
from bridge.turtle import TurtleRouter

class MockBoard:
    def get_footprints(self):
        return []

def run_tests():
    print("Initializing Mock Board...")
    board = MockBoard()
    
    print("\n--- Testing BlackBoxManager ---")
    bb_mgr = BlackBoxManager(board)
    io_nets = [{"net": "SPI_CLK", "side": "Top", "offset_percent": 0.5}]
    res = bb_mgr.encapsulate_module("M01", ["U1", "C1"], io_nets)
    print("Result:", res)
    
    print("\n--- Testing LocalRadar ---")
    radar = LocalRadar(board)
    res = radar.probe_environment((15.0, 15.0), 5.0)
    print(res)
    
    print("\n--- Testing TurtleRouter ---")
    turtle = TurtleRouter(board)
    moves = [{"dir": "RIGHT", "dist": 3.0}, {"dir": "UP_RIGHT", "dist": 2.0}]
    res = turtle.route_sequence("SPI_CLK", "F.Cu", (10.0, 10.0), moves)
    print("Result:", res)

if __name__ == "__main__":
    run_tests()
