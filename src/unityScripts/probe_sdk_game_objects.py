#!/usr/bin/env python3
"""
Standalone probe: verify a Unity game exposes objects via AltTester the same way
the agent does in SDK mode (vision off).

Prerequisites:
  - Game build with AltTester, connected (default 127.0.0.1:13000)
  - Device/emulator on ADB so Unity view bounds can be resolved (for screen coords)

Usage:
  cd /path/to/alttester
  python scripts/probe_sdk_game_objects.py              # full action space (like agent)
  python scripts/probe_sdk_game_objects.py --discover   # scan many component types
  python scripts/probe_sdk_game_objects.py --json       # machine-readable summary

Env (optional): ALTTESTER_HOST, ALTTESTER_PORT (defaults 127.0.0.1 / 13000)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

# Common Unity types to try when mapping an unknown game
DISCOVER_COMPONENTS = [
    ("UnityEngine.UI.Button", "UnityEngine.UI")
    # ("UnityEngine.UI.Toggle", "UnityEngine.UI"),
    # ("UnityEngine.UI.Slider", "UnityEngine.UI"),
    # ("UnityEngine.UI.InputField", "UnityEngine.UI"),
    # ("UnityEngine.UI.Dropdown", "UnityEngine.UI"),
    # ("UnityEngine.UI.Scrollbar", "UnityEngine.UI"),
    # ("UnityEngine.EventSystems.EventTrigger", "UnityEngine.UI"),
    # ("UnityEngine.UI.Selectable", "UnityEngine.UI"),
    # ("UnityEngine.BoxCollider2D", "UnityEngine.CoreModule"),
    # ("UnityEngine.CircleCollider2D", "UnityEngine.CoreModule"),
    # ("UnityEngine.PolygonCollider2D", "UnityEngine.Physics2D"),
    # ("UnityEngine.BoxCollider", "UnityEngine.CoreModule"),
    # ("UnityEngine.SphereCollider", "UnityEngine.CoreModule"),
    # ("UnityEngine.MeshCollider", "UnityEngine.PhysicsModule"),
]


def run_discover(driver, limit_names: int) -> dict:
    from alttester import By

    results = {}
    t0 = time.perf_counter()
    for component_name, _assembly in DISCOVER_COMPONENTS:
        try:
            t1 = time.perf_counter()
            objs = driver.find_objects(By.COMPONENT, component_name)
            dt = time.perf_counter() - t1
            n = len(objs) if objs else 0
            sample = []
            if objs:
                for o in objs[:limit_names]:
                    sample.append(getattr(o, "name", "?"))
            results[component_name] = {
                "count": n,
                "seconds": round(dt, 3),
                "sample_names": sample,
            }
        except Exception as e:
            results[component_name] = {"count": -1, "error": str(e), "seconds": None}
    results["_total_wall_seconds"] = round(time.perf_counter() - t0, 3)
    return results


def run_action_space() -> dict:
    from tester import AltTesterClient
    from agent.adb_manager import ADBManager
    from agent.actions.action_handler import ActionHandler

    host = os.getenv("ALTTESTER_HOST", "127.0.0.1")
    port = int(os.getenv("ALTTESTER_PORT", "13000"))

    t_connect = time.perf_counter()
    client = AltTesterClient(host=host, port=port, timeout=60)
    driver = client.get_driver()
    connect_s = time.perf_counter() - t_connect

    adb = ADBManager(
        host=os.getenv("ADB_HOST", "127.0.0.1"),
        port=int(os.getenv("ADB_PORT", "5037")),
    )
    handler = ActionHandler(driver, adb_manager=adb)

    t0 = time.perf_counter()
    try:
        available = handler.get_available_actions()
    except ValueError as e:
        if "Unity bounds" in str(e) or "bounds" in str(e).lower():
            print(
                "\n❌ Could not read Unity view bounds from ADB.\n"
                "   Connect exactly one device/emulator and ensure the game is in foreground.\n",
                file=sys.stderr,
            )
        raise
    elapsed = time.perf_counter() - t0

    buttons = available.get("buttons") or []
    sliders = available.get("sliders") or []
    i2d = available.get("interactable_2d") or []
    keys = (
        (available.get("keyboard") or {})
        .get("key_press", {})
        .get("available_keys", [])
    )

    summary = {
        "alt_tester_host": host,
        "alt_tester_port": port,
        "connect_seconds": round(connect_s, 3),
        "get_available_actions_seconds": round(elapsed, 3),
        "counts": {
            "buttons": len(buttons),
            "sliders": len(sliders),
            "interactable_2d": len(i2d),
            "keyboard_keys_configured": len(keys),
        },
        "buttons": [
            {
                "id": b.get("id"),
                "name": b.get("name"),
                "screen_position": b.get("screen_position"),
                "enabled": b.get("enabled"),
                "visible": b.get("visible"),
                "on_screen": b.get("on_screen"),
            }
            for b in buttons
        ],
        "sliders": [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "screen_position": s.get("screen_position"),
                "value": s.get("value"),
                "enabled": s.get("enabled"),
                "visible": s.get("visible"),
                "on_screen": s.get("on_screen"),
            }
            for s in sliders
        ],
        "interactable_2d": [
            {
                "id": x.get("id"),
                "name": x.get("name"),
                "type": x.get("type"),
                "screen_position": x.get("screen_position"),
                "enabled": x.get("enabled"),
                "visible": x.get("visible"),
                "on_screen": x.get("on_screen"),
            }
            for x in i2d
        ],
    }
    try:
        client.disconnect()
    except Exception:
        pass
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe AltTester game object exposure")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Scan many component types (find what the game exposes)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    parser.add_argument(
        "--sample",
        type=int,
        default=5,
        help="Max sample names per type in discover mode (default 5)",
    )
    args = parser.parse_args()

    if args.discover:
        from tester import AltTesterClient

        host = os.getenv("ALTTESTER_HOST", "127.0.0.1")
        port = int(os.getenv("ALTTESTER_PORT", "13000"))
        client = AltTesterClient(host=host, port=port, timeout=60)
        driver = client.get_driver()
        print(f"🔍 Driver: {driver}")
        data = run_discover(driver, args.sample)
        try:
            client.disconnect()
        except Exception:
            pass

        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"\n{'Component':<50} {'Count':>8} {'Time(s)':>10}")
            print("-" * 70)
            for k, v in data.items():
                if k.startswith("_"):
                    continue
                if v.get("count", 0) < 0:
                    print(f"{k:<50} {'ERR':>8} {str(v.get('error', ''))[:40]}")
                elif v.get("count", 0) > 0:
                    print(f"{k:<50} {v['count']:>8} {v.get('seconds', 0):>10.3f}")
                    for name in v.get("sample_names") or []:
                        print(f"    · {name}")
            print("-" * 70)
            print(f"Total wall time (all queries): {data.get('_total_wall_seconds')}s")
            nonzero = sum(1 for k, v in data.items() if not k.startswith("_") and v.get("count", 0) > 0)
            print(f"Component types with ≥1 object: {nonzero}\n")
        return

    summary = run_action_space()
    if args.json:
        print(json.dumps(summary, indent=2))
        return

    c = summary["counts"]
    print("\n=== SDK action space (same as agent with SDK_ENABLED=true) ===\n")
    print(f"  AltTester: {summary['alt_tester_host']}:{summary['alt_tester_port']}")
    print(f"  get_available_actions(): {summary['get_available_actions_seconds']}s")
    print(f"  Buttons:          {c['buttons']}")
    print(f"  Sliders:          {c['sliders']}")
    print(f"  Interactable 2D:  {c['interactable_2d']}")
    print(f"  Keyboard keys:    {c['keyboard_keys_configured']} (from config)\n")

    if c["buttons"] + c["sliders"] + c["interactable_2d"] == 0:
        print(
            "⚠️  Zero interactables. Try:\n"
            "   • python scripts/probe_sdk_game_objects.py --discover\n"
            "   • Edit src/agent/actions/config/action_config.json "
            "element_extraction.components for your game's types.\n"
        )
    else:
        print("First few buttons:")
        for b in summary["buttons"][:15]:
            print(
                f"  - {b['name']} id={b['id']} pos={b['screen_position']} "
                f"enabled={b['enabled']} visible={b.get('visible')} on_screen={b.get('on_screen')}"
            )
        if c["interactable_2d"]:
            print("\nFirst few interactable_2d:")
            for x in summary["interactable_2d"][:15]:
                print(
                    f"  - {x['name']} ({x['type']}) id={x['id']} pos={x['screen_position']} "
                    f"enabled={x.get('enabled')} visible={x.get('visible')} on_screen={x.get('on_screen')}"
                )


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(ROOT, ".env"))
    except ImportError:
        pass
    main()
