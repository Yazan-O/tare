"""Build site/data/map.json: metropolitan France's 2018 communes and départements, simplified for the page.

Source: IGN ADMIN EXPRESS COG, edition 2018-04-03 (COMMUNE_CARTO and DEPARTEMENT_CARTO layers, Lambert-93),
Licence Ouverte / Open Licence 2.0. Download:
https://data.geopf.fr/telechargement/download/ADMIN-EXPRESS-COG/ADMIN-EXPRESS-COG_1-1__SHP__FRA_2018-04-03/ADMIN-EXPRESS-COG_1-1__SHP__FRA_2018-04-03.7z

Usage: python build_map.py <folder holding COMMUNE_CARTO.* and DEPARTEMENT_CARTO.*> --out ../data/map.json
Needs pyshp (pip install pyshp). Coordinates are Lambert-93 metres divided by GRID, rounded, delta-encoded
per ring; y grows northwards (the page flips it).
"""
import argparse
import json
from pathlib import Path

import shapefile

GRID = 200          # metres per unit
TOL_COM = 350       # Douglas-Peucker tolerance, metres, communes
TOL_DEP = 600       # départements


def dp(pts, tol):
    """Douglas-Peucker on a closed ring; keeps the first point and the farthest-from-first point as anchors."""
    n = len(pts)
    if n < 5:
        return pts
    far = max(range(n), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
    keep = [False] * n
    keep[0] = keep[far] = keep[n - 1] = True
    stack = [(0, far), (far, n - 1)]
    t2 = tol * tol
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if L == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                c = dx * (py - ay) - dy * (px - ax)
                d = c * c / L
            if d > best:
                best, bi = d, i
        if best > t2:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


def rings(shape):
    parts = list(shape.parts) + [len(shape.points)]
    return [shape.points[parts[i]:parts[i + 1]] for i in range(len(parts) - 1)]


def ring_area(r):
    return abs(sum(r[i][0] * r[i - 1][1] - r[i - 1][0] * r[i][1] for i in range(len(r)))) / 2


def encode(shape, tol, min_area):
    out = []
    rs = rings(shape)
    biggest = max(rs, key=ring_area)
    for r in rs:
        if r is not biggest and ring_area(r) < min_area:
            continue                      # drop islets and holes too small to see at page scale
        s = dp(r[:-1] if r[0] == r[-1] else r, tol)
        q, last = [], None
        for x, y in s:
            p = (round(x / GRID), round(y / GRID))
            if p != last:
                q.append(p)
                last = p
        if len(q) < 3:
            if r is not biggest:
                continue
            q = [(round(x / GRID), round(y / GRID)) for x, y in r[:3]]
        flat, px, py = [], 0, 0
        for x, y in q:
            flat += [x - px, y - py]
            px, py = x, y
        out.append(flat)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    com = shapefile.Reader(str(a.src / "COMMUNE_CARTO"), encoding="cp1252")
    dep = shapefile.Reader(str(a.src / "DEPARTEMENT_CARTO"), encoding="cp1252")
    ci = [f[0] for f in com.fields[1:]].index("INSEE_COM")
    di = [f[0] for f in dep.fields[1:]].index("INSEE_DEP")
    communes = {}
    for sr in com.iterShapeRecords():
        communes[sr.record[ci]] = encode(sr.shape, TOL_COM, 4 * GRID * GRID)
    deps = {sr.record[di]: encode(sr.shape, TOL_DEP, 2_000_000) for sr in dep.iterShapeRecords()}
    xs = [b for s in com.shapes() for b in (s.bbox[0], s.bbox[2])]
    ys = [b for s in com.shapes() for b in (s.bbox[1], s.bbox[3])]
    doc = {"source": "IGN ADMIN EXPRESS COG 2018-04-03, COMMUNE_CARTO and DEPARTEMENT_CARTO, Licence Ouverte 2.0",
           "crs": "EPSG:2154 / GRID", "grid": GRID,
           "bbox": [round(min(xs) / GRID), round(min(ys) / GRID), round(max(xs) / GRID), round(max(ys) / GRID)],
           "communes": communes, "departements": deps}
    a.out.write_text(json.dumps(doc, separators=(",", ":")), encoding="cp1252")
    pts = sum(len(r) // 2 for v in communes.values() for r in v)
    print(f"communes {len(communes)}, points {pts}, départements {len(deps)}, {a.out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
