"""Crop the owner's Bob IDE stills (bob_sessions/, chat pane 1060x1020) into the page's figures: Bob's
header strip (task title and coin counter) above the chat region each figure is about.

Usage (from the repository root): python site/tools/crop_bob_shots.py
"""
from pathlib import Path

from PIL import Image

TARE = Path(__file__).resolve().parents[2]
SRC = TARE / "bob_sessions"
OUT = TARE / "site" / "dist" / "img"
HEADER = (88, 136)                       # the task title row with the coin counter
CROPS = {                                # out name: (still, first row, last row)
    "bob_1_blocked.png": ("tare_task01_01_first_block_no_weigh.png", 595, 750),
    "bob_2_subagents.png": ("tare_task01_03_two_subagents_running.png", 336, 745),
    "bob_3_stale_edit.png": ("tare_task01_05_stale_edit_block.png", 414, 662),
    "bob_4_wrong_guess.png": ("tare_task01_06_wrong_guess_296_still_differ.png", 197, 704),
    "bob_5_balanced.png": ("tare_task01_07_balanced_408_of_408.png", 455, 714),
    "bob_6_committed.png": ("tare_task01_08_committed_task_summary_3.74.png", 140, 740),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (still, a, b) in CROPS.items():
        im = Image.open(SRC / still).convert("RGB")
        head = im.crop((0, HEADER[0], im.width, HEADER[1]))
        body = im.crop((0, a, im.width, b))
        out = Image.new("RGB", (im.width, head.height + body.height))
        out.paste(head, (0, 0))
        out.paste(body, (0, head.height))
        out.save(OUT / name, optimize=True)
        print(f"{name} {out.size} from {still} rows {a}-{b}")


if __name__ == "__main__":
    main()
