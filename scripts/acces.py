"""Zones accessibles à pied pour Cimes, calculées à l'avance.

Entrée : export GeoJSON séquentiel des voies OpenStreetMap (déjà filtrées par osmium).
Sortie : pour chaque taille de zone (H3 résolutions 8, 9, 10), la liste des cellules
traversées par au moins une voie praticable à pied, découpée en tuiles (cellules H3 de
résolution 5, environ 250 km²) pour que l'appli ne télécharge que ce qui entoure le joueur.

Un chemin cartographié n'est pas une garantie d'accès : ces données servent seulement
à calculer le pourcentage de complétion, jamais à recommander un itinéraire.
Données © les contributeurs d'OpenStreetMap, sous licence ODbL.
"""
import json, sys, os, math, datetime, collections
import h3

src, outdir, region = sys.argv[1], sys.argv[2], sys.argv[3]
STEP = 15            # un point tous les 15 m le long de chaque voie
RES = (8, 9, 10)     # tailles de zones L, M, S
TUILE = 5
WALK = {"footway", "path", "track", "pedestrian", "living_street", "residential", "service",
        "unclassified", "tertiary", "tertiary_link", "secondary", "secondary_link", "primary",
        "primary_link", "steps", "cycleway", "bridleway", "road"}
NON = {"private", "no"}

def ok(t):
    if t.get("highway") not in WALK: return False
    if t.get("access") in NON and t.get("foot") not in ("yes", "designated", "permissive"): return False
    if t.get("foot") in NON: return False
    return True

def metres(a, b):
    k = 111320 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((b[0] - a[0]) * k, (b[1] - a[1]) * 110540)

cells = set(); n_ok = 0; rejets = collections.Counter(); km = 0.0
with open(src, encoding="utf-8") as f:
    for line in f:
        line = line.strip().lstrip("\x1e")
        if not line: continue
        g = json.loads(line); t = g.get("properties", {}); geo = g.get("geometry") or {}
        if not ok(t): rejets["non praticable ou privé"] += 1; continue
        ty = geo.get("type")
        if ty == "LineString": lignes = [geo["coordinates"]]
        elif ty == "MultiLineString": lignes = geo["coordinates"]
        elif ty == "Polygon": lignes = geo["coordinates"][:1]
        elif ty == "MultiPolygon": lignes = [p[0] for p in geo["coordinates"]]
        else: rejets["géométrie " + str(ty)] += 1; continue
        n_ok += 1
        for L in lignes:
            for i in range(1, len(L)):
                a, b = L[i - 1], L[i]; d = metres(a, b); km += d / 1000
                m = max(1, math.ceil(d / STEP))
                for k in range(m + (1 if i == len(L) - 1 else 0)):
                    u = k / m
                    cells.add(h3.latlng_to_cell(a[1] + (b[1] - a[1]) * u, a[0] + (b[0] - a[0]) * u, 10))
            if len(L) == 1: cells.add(h3.latlng_to_cell(L[0][1], L[0][0], 10))

print(f"Voies retenues : {n_ok} ({km:,.0f} km)", "| rejetées :", dict(rejets))
if not cells: sys.exit("ERREUR : aucune voie praticable trouvée, rien n'est écrit.")

version = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
par_res = {10: cells, 9: {h3.cell_to_parent(c, 9) for c in cells}, 8: {h3.cell_to_parent(c, 8) for c in cells}}
index = {"region": region, "version": version, "tuile_res": TUILE,
         "licence": "© les contributeurs d'OpenStreetMap, ODbL 1.0 (https://www.openstreetmap.org/copyright)",
         "note": "Cellules H3 traversées par une voie praticable à pied. Un chemin cartographié n'est pas une garantie d'accès.",
         "res": {}}
import shutil
shutil.rmtree(outdir, ignore_errors=True)
for r in RES:
    tu = collections.defaultdict(list)
    for c in par_res[r]: tu[h3.cell_to_parent(c, TUILE)].append(c)
    os.makedirs(f"{outdir}/{r}", exist_ok=True); taille = 0
    for k, L in tu.items():
        p = f"{outdir}/{r}/{k}.json"
        with open(p, "w") as f: json.dump({"v": version, "res": r, "cells": sorted(L)}, f, separators=(",", ":"))
        taille += os.path.getsize(p)
    index["res"][str(r)] = {"zones": len(par_res[r]), "tuiles": sorted(tu)}
    print(f"Résolution {r} : {len(par_res[r]):,} zones accessibles, {len(tu)} tuiles, {taille/1e6:.1f} Mo")
    if len(par_res[r]) < 1000: print(f"::warning::Peu de zones accessibles en résolution {r} ({len(par_res[r])}). À vérifier.")
with open(f"{outdir}/index.json", "w") as f: json.dump(index, f, separators=(",", ":"))
# contrôle : chaque tuile listée existe et se relit
for r in RES:
    for k in index["res"][str(r)]["tuiles"]:
        with open(f"{outdir}/{r}/{k}.json") as f: assert json.load(f)["cells"], "tuile vide"
print("Index écrit et vérifié :", f"{outdir}/index.json")
