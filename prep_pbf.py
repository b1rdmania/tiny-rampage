# Geofabrik London .osm.pbf -> game/buildings.json (Zone 1 buildings + fence) and game/roads.json (drivable graph)
# usage: venv/bin/python prep_pbf.py london.osm.pbf zones.json game/
import json, math, re, sys
import osmium

a = 6378137.0; e2 = 0.0066943799901413165
def ecef(la, lo):
    la, lo = math.radians(la), math.radians(lo); N = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return (N * math.cos(la) * math.cos(lo), N * math.cos(la) * math.sin(lo), N * (1 - e2) * math.sin(la))
C = (51.507, -0.106); X0 = ecef(*C); cla, clo = map(math.radians, C)
t = math.radians(15); m = 0.29296875; s45 = math.sin(math.radians(45))
def proj(la, lo):
    x, y, z = ecef(la, lo); dx, dy, dz = x - X0[0], y - X0[1], z - X0[2]
    E = -math.sin(clo) * dx + math.cos(clo) * dy
    N = -math.sin(cla) * math.cos(clo) * dx - math.sin(cla) * math.sin(clo) * dy + math.cos(cla) * dz
    U = math.cos(cla) * math.cos(clo) * dx + math.cos(cla) * math.sin(clo) * dy + math.sin(cla) * dz
    r = E * math.cos(t) + N * math.sin(t); f = -E * math.sin(t) + N * math.cos(t)
    return r / m + 109056, -(f * s45 + U * s45) / m + 57600
def num(v):
    if not v: return None
    mm = re.match(r'[\d.]+', v.replace(',', '.'))
    try: return float(mm.group()) if mm else None
    except ValueError: return None

zone = [c for p in json.load(open(sys.argv[2]))['zones'][0]['lines'][0] for c in p]
zx = zone[0::2]; zy = zone[1::2]; ZB = (min(zx) - 300, min(zy) - 300, max(zx) + 300, max(zy) + 300)
def inpoly(p, x, y):
    c = False; j = len(p) - 2
    for i in range(0, len(p), 2):
        xi, yi, xj, yj = p[i], p[i + 1], p[j], p[j + 1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi: c = not c
        j = i
    return c
inbox = lambda x, y: ZB[0] <= x <= ZB[2] and ZB[1] <= y <= ZB[3]

DRIVE = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'living_street',
         'motorway_link', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link'}

class H(osmium.SimpleHandler):
    def __init__(self):
        super().__init__(); self.b = []; self.roads = []
    def area(self, ar):
        tg = ar.tags
        if 'building' not in tg: return
        h = num(tg.get('height')) or num(tg.get('building:height'))
        if not h:
            lv = num(tg.get('building:levels')); h = lv * 3.4 + 2 if lv else 10
        h = max(3, min(h, 320)); nm = tg.get('name', '')
        for ring in ar.outer_rings():
            try: pts = [proj(n.lat, n.lon) for n in ring]
            except osmium.InvalidLocationError: continue
            if len(pts) < 4: continue
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
            if not inbox(cx, cy) or not inpoly(zone, cx, cy): continue
            A = abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2 * m * m / s45
            if A < 8: continue
            flat = []
            for p in pts[:-1]: flat += [round(p[0]), round(p[1])]
            self.b.append([round(h), round(A), nm, flat])
    def way(self, w):
        if w.tags.get('highway') not in DRIVE or w.tags.get('access') in ('private', 'no'): return
        try: seq = [(n.ref, proj(n.lat, n.lon)) for n in w.nodes]
        except osmium.InvalidLocationError: return
        if any(inbox(*p) for _, p in seq): self.roads.append(seq)

h = H(); h.apply_file(sys.argv[1], locations=True)
out = sorted(h.b, key=lambda b: b[3][1])
json.dump({'zone': zone, 'b': out}, open(sys.argv[3] + 'buildings.json', 'w'), separators=(',', ':'), ensure_ascii=False)

# road graph: nodes inside Zone 1 (plus a small margin), largest connected piece only
idx = {}; xy = []; adj = []
def node(ref, p):
    if ref not in idx: idx[ref] = len(xy); xy.append(p); adj.append(set())
    return idx[ref]
for seq in h.roads:
    for (r1, p1), (r2, p2) in zip(seq, seq[1:]):
        if not (inpoly(zone, *p1) or inpoly(zone, *p2)): continue
        i, j = node(r1, p1), node(r2, p2); adj[i].add(j); adj[j].add(i)
seen = [-1] * len(xy); best = None
for s0 in range(len(xy)):
    if seen[s0] >= 0: continue
    comp = [s0]; seen[s0] = s0; k = 0
    while k < len(comp):
        for v in adj[comp[k]]:
            if seen[v] < 0: seen[v] = s0; comp.append(v)
        k += 1
    if not best or len(comp) > len(best): best = comp
keep = {v: n for n, v in enumerate(best)}
nodes = [c for v in best for c in (round(xy[v][0]), round(xy[v][1]))]
edges = [c for v in best for u in adj[v] if v < u and u in keep for c in (keep[v], keep[u])]
json.dump({'n': nodes, 'e': edges}, open(sys.argv[3] + 'roads.json', 'w'), separators=(',', ':'))
hs = sorted(b[0] for b in out)
print(len(out), 'buildings, median h', hs[len(hs) // 2], '| roads', len(best), 'nodes', len(edges) // 2, 'edges (of', len(xy), 'total)')
