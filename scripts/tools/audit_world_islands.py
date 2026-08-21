#!/usr/bin/env python3
"""Audit disconnected/island Admin-1 geometry and current region assignments.

No source data is modified. The report is used to apply island-specific region
inheritance safely instead of guessing from screenshots or names.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from collections import Counter
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection

ROOT = Path(__file__).resolve().parents[2]
WORLD_PX = 8192.0
EARTH_RADIUS_KM = 6371.0088
GEOMETRY = ROOT / 'assets' / 'map_geometry' / 'provinces.json'
IDENTITY = ROOT / 'assets' / 'game_data' / 'provinces.json'
ASSIGNMENTS = ROOT / 'assets' / 'game_data' / 'world_region_assignments_draft.json'
TARGETS = ROOT / 'assets' / 'game_data' / 'world_province_cell_targets.json'
OUT = ROOT / 'reports' / 'world_island_audit.json'


def read(path): return json.loads(path.read_text(encoding='utf-8'))

def km_per_world_px(y):
    n = math.pi - 2.0 * math.pi * y / WORLD_PX
    lat = math.degrees(math.atan(math.sinh(n)))
    return 2.0 * math.pi * EARTH_RADIUS_KM / WORLD_PX * math.cos(math.radians(lat))

def geom(entry):
    rings=entry.get('rings',[])
    if not rings: return Polygon()
    g=Polygon(rings[0],rings[1:])
    if not g.is_valid: g=g.buffer(0)
    return g

def parts(g):
    if g.is_empty: return []
    if isinstance(g,Polygon): return [g]
    if isinstance(g,(MultiPolygon,GeometryCollection)) or hasattr(g,'geoms'):
        return [p for p in g.geoms if isinstance(p,Polygon) and not p.is_empty]
    return []
def area_km2(g):
    if g.is_empty: return 0.0
    s=km_per_world_px(g.representative_point().y)
    return g.area*s*s


def main():
    identities={str(x['id']):x for x in read(IDENTITY).get('provinces',[])}
    assignments={str(x['province_id']):x for x in read(ASSIGNMENTS).get('assignments',[])}
    targets={str(x['province_id']):x for x in read(TARGETS).get('provinces',[])} if TARGETS.exists() else {}
    geoms={}
    for e in read(GEOMETRY).get('provinces',[]):
        pid=str(e.get('id','')); g=geom(e)
        if pid and not g.is_empty: geoms[pid]=g
    rows=[]
    for pid,g in geoms.items():
        ps=parts(g)
        ident=identities.get(pid,{})
        assign=assignments.get(pid,{})
        target=targets.get(pid,{})
        component_areas=sorted((area_km2(p) for p in ps), reverse=True)
        rows.append({
            'province_id':pid,'legacy_id':str(ident.get('legacy_id','')),'name':str(ident.get('name','')),
            'region_id':str(assign.get('region_id','')),'region_name':str(assign.get('region_name','')),
            'confidence':str(assign.get('confidence','')),'total_area_km2':round(area_km2(g),3),
            'polygon_component_count':len(ps),'component_areas_km2':[round(a,3) for a in component_areas],
            'target_cell_count':int(target.get('target_cell_count',0) or 0),
            'target_cell_area_km2':float(target.get('region_target_cell_area_km2',0) or 0),
        })
    multipart=sorted([r for r in rows if r['polygon_component_count']>1], key=lambda r:(-r['polygon_component_count'],-r['total_area_km2']))
    named=[]
    needles=('island','islands','isle','gotland','iceland','faroe','orkney','shetland','hebr','azores','madeira','canar','balear')
    for r in rows:
        text=(r['name']+' '+r['legacy_id']).lower()
        if any(n in text for n in needles): named.append(r)
    report={
        'schema_version':1,'format':'world_island_audit/v1','province_count':len(rows),
        'multipart_province_count':len(multipart),
        'multipart_component_count_distribution':dict(sorted(Counter(r['polygon_component_count'] for r in multipart).items())),
        'named_island_candidate_count':len(named),
        'named_island_candidates':named,
        'multipart_provinces':multipart,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('WORLD_ISLAND_AUDIT_OK','provinces=',len(rows),'multipart=',len(multipart),'named=',len(named))

if __name__=='__main__': main()
