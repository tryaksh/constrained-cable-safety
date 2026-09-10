"""Conceptual research-task diagram; proposed apparatus is not an executed result."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle

ROOT = Path(__file__).resolve().parents[1]
fig, ax = plt.subplots(figsize=(13, 6))
fig.patch.set_facecolor("#f6f8fa")
ax.set(xlim=(0, 13), ylim=(0, 6))
ax.axis("off")
for x, w in ((0.15, 4.55), (4.95, 7.9)):
    ax.add_patch(FancyBboxPatch((x, 0.6), w, 4.65, boxstyle="round,pad=0.05", facecolor="white", edgecolor="#d6dee5"))
ax.text(
    0.25,
    5.65,
    "The research target: repair insertion without undoing earlier cable work",
    size=19,
    weight="bold",
    color="#172c3b",
)
ax.text(0.4, 4.93, "CURRENT: measured alignment test", size=13, weight="bold", color="#354b5a")
ax.text(5.2, 4.93, "NEXT: proposed clip-preserving recovery test", size=13, weight="bold", color="#086f68")
# Current held plug, fixed socket and a free cable.
ax.add_patch(Rectangle((2.0, 3.35), 0.7, 0.75, color="#808d97"))
ax.add_patch(Rectangle((2.20, 2.9), 0.3, 0.6, color="#336da4"))
ax.add_patch(Rectangle((2.1, 2.22), 0.5, 0.35, color="#336da4"))
ax.add_patch(Rectangle((2.25, 2.38), 0.2, 0.19, color="white"))
ax.plot([2.25, 2.7, 2.95, 2.95], [3.42, 3.05, 2.3, 1.25], color="#12a3b4", lw=4)
ax.text(0.5, 3.9, "Robot holds plug", size=12)
ax.text(0.5, 2.35, "Fixed socket", size=12)
ax.text(3.05, 1.35, "Free end", size=11, color="#087e8b")
ax.add_patch(FancyArrowPatch((2.6, 3.07), (2.6, 2.62), arrowstyle="->", mutation_scale=15, color="#333333"))
ax.text(
    0.45,
    0.92,
    "6/6 guided seats vs 3/6 continued insertion.\nNo clip, snag, learned policy or recovery event.",
    size=10.5,
    color="#485c6c",
)
# Proposed boundary / clip / post / retained gripper assembly.
ax.add_patch(Rectangle((5.35, 2.68), 0.28, 0.35, color="#526574"))
ax.text(5.2, 4.15, "1  Fixed strain relief", size=11, weight="bold")
ax.text(5.2, 3.85, "Explicit boundary,\nnot an unplugging claim", size=10, color="#485c6c")
ax.plot([5.49, 5.49], [3.65, 3.07], lw=1, color="#8899a6")
ax.plot([6.95, 6.95, 7.4, 7.4], [3.12, 2.68, 2.68, 3.12], lw=5, color="#526574")
ax.text(6.6, 1.8, "2  Required open clip", size=11, weight="bold")
ax.text(6.6, 1.48, "Its physical release\ncounts as a failed task", size=10, color="#485c6c")
ax.plot([7.17, 7.17], [2.15, 2.58], lw=1, color="#8899a6")
ax.add_patch(Circle((9.0, 2.83), 0.23, facecolor="#f5af67", edgecolor="#b86a20", lw=2))
ax.text(8.45, 4.15, "3  Optional snag", size=11, weight="bold")
ax.text(8.45, 3.85, "Must have a feasible\nrobot-driven release", size=10, color="#485c6c")
ax.plot([9.0, 9.0], [3.65, 3.15], lw=1, color="#8899a6")
ax.add_patch(Rectangle((11.55, 3.30), 0.7, 0.75, color="#808d97"))
ax.add_patch(Rectangle((11.75, 2.87), 0.3, 0.58, color="#336da4"))
ax.add_patch(Rectangle((11.65, 2.12), 0.5, 0.36, color="#336da4"))
ax.add_patch(Rectangle((11.8, 2.29), 0.2, 0.2, color="white"))
ax.plot(
    [5.62, 6.3, 7.16, 8.0, 8.67, 8.8, 9.07, 9.3, 10.4, 11.9],
    [2.86, 2.86, 2.85, 2.84, 2.84, 2.51, 2.49, 2.83, 2.85, 3.4],
    color="#12a3b4",
    lw=4,
)
ax.add_patch(
    FancyArrowPatch(
        (9.3, 3.02),
        (10.1, 3.38),
        connectionstyle="arc3,rad=-.6",
        arrowstyle="->",
        mutation_scale=17,
        color="#087e8b",
        lw=2,
    )
)
ax.text(10.2, 1.65, "4  Seat while still held", size=11, weight="bold")
ax.text(10.2, 1.32, "Preserve clip and load limits.\nFinal release/latching is later.", size=10, color="#485c6c")
ax.text(
    5.2,
    0.88,
    "Question: when should the robot correct the plug,\nand when must it free the cable first?",
    size=10.7,
    color="#086f68",
    weight="bold",
)
ax.text(
    0.3,
    0.23,
    "Conceptual layout only; not dimensioned CAD, a built extension, or an experimental result. All future methods share the same observations, actions and task.",
    size=9.5,
    color="#566a79",
)
fig.tight_layout(pad=0.3)
for ext in ("svg", "png", "pdf"):
    output = ROOT / f"evidence/cable_research_task_v2.{ext}"
    fig.savefig(output, dpi=170)
    if ext == "svg":
        lines = output.read_text(encoding="utf-8").splitlines()
        output.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")
