"""Create a deterministic synthetic CSV for the menu walkthrough."""
import csv
from pathlib import Path
import random


def generate():
    rng = random.Random(20261028)
    output = Path(__file__).resolve().parents[1] / "examples/pathlab-demo.csv"
    output.parent.mkdir(exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["X", "M1", "M2", "Y", "W", "Z", "Q", "C"])
        for _ in range(180):
            x, w, z, q, c = [rng.gauss(0, 1) for _ in range(5)]
            m1 = .6*x + .2*w + .25*x*w + .1*c + rng.gauss(0, 1)
            m2 = .55*m1 + .2*z + .2*m1*z + .1*c + rng.gauss(0, 1)
            y = .15*x + .65*m2 + .2*q + .18*m2*q + .15*c + rng.gauss(0, 1)
            writer.writerow([format(v, ".12g") for v in [x, m1, m2, y, w, z, q, c]])
    return output


if __name__ == "__main__":
    print(generate())
