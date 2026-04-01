#!/usr/bin/env python3
"""
run_autolayout.py — NeurPCB 一键自动布局

用法:
    # 1. KiCad 9.0 打开 .kicad_pcb 文件，启用 API Server
    # 2. 运行:
    DEEPSEEK_API_KEY=sk-... python run_autolayout.py

    # 可选参数:
    python run_autolayout.py --scramble    # 先打乱再布局（测试用）
    python run_autolayout.py --dry-run     # 只分析不写回
"""
import argparse
import json
import logging
import os
import random
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="NeurPCB Auto-Layout")
    parser.add_argument("--scramble", action="store_true", help="Scramble all components first (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Analyze only, don't write back to KiCad")
    args = parser.parse_args()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("ERROR: DEEPSEEK_API_KEY not set. Run: export DEEPSEEK_API_KEY=sk-...")
        sys.exit(1)

    from bridge.kicad_bridge import KiCadBridge
    from agents.architect import Architect
    from geometry.core import Rect

    # =========================================================
    # Step 1: 连接 KiCad，读取板子
    # =========================================================
    logger.info("=" * 55)
    logger.info("  NeurPCB Auto-Layout")
    logger.info("=" * 55)

    bridge = KiCadBridge()
    bridge.connect()
    logger.info("Board: %s", bridge.board_name)

    outline = bridge.get_board_outline()
    board_rect = Rect(outline.min_x_mm, outline.min_y_mm, outline.width_mm, outline.height_mm)
    copper = bridge.get_copper_layer_count()
    locked_refs = bridge.get_locked_footprints()

    comps_raw = bridge.get_footprints()
    nets_raw = bridge.get_nets()
    real_sizes = bridge.get_real_footprint_sizes()

    # 过滤非电气器件
    components = []
    for c in comps_raw:
        if c.ref.startswith("kibuzzard") or c.value in ("LOGO", "G***") or c.ref == "REF**":
            continue
        components.append({"ref": c.ref, "value": c.value, "footprint": c.footprint})
    nets = [{"name": n.name, "nodes": n.nodes} for n in nets_raw]

    logger.info("Board: %.1f × %.1f mm at (%.1f, %.1f)",
                board_rect.w, board_rect.h, board_rect.x, board_rect.y)
    logger.info("Components: %d electrical, Nets: %d, Copper layers: %d",
                len(components), len(nets), copper)
    logger.info("Locked: %s", locked_refs or "none")

    # =========================================================
    # Step 2 (可选): 打乱
    # =========================================================
    original_positions = None
    if args.scramble:
        logger.info("")
        logger.info("Scrambling all unlocked components...")
        original_positions = {c.ref: (c.x_mm, c.y_mm) for c in comps_raw
                              if not c.ref.startswith("kibuzzard") and c.value not in ("LOGO", "G***")}
        with open("/tmp/neurpcb_backup.json", "w") as f:
            json.dump(original_positions, f)
        logger.info("  Original positions backed up to /tmp/neurpcb_backup.json")

        rng = random.Random(42)
        scramble = {}
        for c in comps_raw:
            if c.locked or c.ref.startswith("kibuzzard") or c.value in ("LOGO", "G***") or c.ref == "REF**":
                continue
            scramble[c.ref] = (
                rng.uniform(outline.min_x_mm - 80, outline.min_x_mm - 20),
                rng.uniform(outline.min_y_mm - 40, outline.max_y_mm + 40),
            )
        bridge.begin_commit()
        bridge.batch_move_footprints(scramble)
        bridge.push_commit("NeurPCB: Scramble")
        logger.info("  Scrambled %d components", len(scramble))

    # =========================================================
    # Step 3: 运行 Pipeline
    # =========================================================
    logger.info("")
    logger.info("=" * 55)
    logger.info("  Running Auto-Layout Pipeline")
    logger.info("=" * 55)
    t0 = time.time()

    architect = Architect()
    result = architect.run_pipeline(
        components, nets, board_rect,
        copper_layers=copper,
        locked_components=[{"ref": r} for r in locked_refs],
        real_sizes=real_sizes,
        max_iterations=2,
    )

    elapsed = time.time() - t0
    logger.info("Pipeline completed in %.1f seconds", elapsed)

    # =========================================================
    # Step 4: 写回 KiCad
    # =========================================================
    if args.dry_run:
        logger.info("")
        logger.info("[DRY RUN] Skipping write-back to KiCad")
    else:
        logger.info("")
        logger.info("Writing results to KiCad...")
        positions = result.get_final_positions()
        for lr in locked_refs:
            positions.pop(lr, None)

        bridge.begin_commit()
        count = bridge.batch_move_footprints(positions)
        bridge.push_commit("NeurPCB: Auto-layout")
        logger.info("Written %d / %d components to KiCad", count, len(positions))

    bridge.disconnect()

    # =========================================================
    # Step 5: 输出报告
    # =========================================================
    print("")
    print(result.summary)
    print("")

    if result.success:
        logger.info("Status: SUCCESS")
    else:
        logger.info("Status: NEEDS_ATTENTION (%d critical issues)",
                     result.critic_report.critical if result.critic_report else 0)

    if args.scramble:
        logger.info("")
        logger.info("To restore original positions:")
        logger.info("  python -c \"import json; exec(open('/tmp/neurpcb_restore.py').read())\"")
        # 写恢复脚本
        with open("/tmp/neurpcb_restore.py", "w") as f:
            f.write("import json, sys; sys.path.insert(0, '.')\n")
            f.write("from bridge.kicad_bridge import KiCadBridge\n")
            f.write("bridge = KiCadBridge(); bridge.connect()\n")
            f.write("with open('/tmp/neurpcb_backup.json') as f: orig = json.load(f)\n")
            f.write("bridge.begin_commit(); bridge.batch_move_footprints(orig)\n")
            f.write("bridge.push_commit('Restore'); bridge.disconnect()\n")
            f.write("print(f'Restored {len(orig)} components')\n")


if __name__ == "__main__":
    main()
