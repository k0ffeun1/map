#!/usr/bin/env python3
"""Apply island-aware region and cell-count corrections worldwide.

Design rules:
- Remote North-Atlantic European islands (Iceland/Faroe family) share one region.
- Near-shore Scottish islands stay with the appropriate Scottish region.
- Satellite islands near a parent island inherit that parent's region.
- Cell counts are allocated PER disconnected significant island component.
- A small island whose own area is below its regional target area gets exactly
  one cell by default.
- A gameplay cell may never span two significant islands across sea.

No terrain/relief is used. No Admin-1 geometry is modified.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP

from shapely.geometry import Polygon, MultiPolygon, GeometryCollection

ROOT = Path(__file__).resolve().parents[2]
WORLD_PX=8192.0
EARTH_RADIUS_KM=6371.0088

GEOMETRY_PATH=ROOT/'assets'/'map_geometry'/'provinces.json'
IDENTITY_PATH=ROOT/'assets'/'game_data'/'provinces.json'
ASSIGN_PATH=ROOT/'assets'/'game_data'/'world_region_assignments_draft.json'
TARGET_PATH=ROOT/'assets'/'game_data'/'world_province_cell_targets.json'
PROFILE_PATH=ROOT/'assets'/'game_data'/'world_region_cell_profiles.json'
RULES_PATH=ROOT/'assets'/'game_data'/'world_island_region_rules.json'
OUT_ASSIGN=ROOT/'assets'/'game_data'/'world_region_assignments_island_corrected.json'
OUT_TARGET=ROOT/'assets'/'game_data'/'world_province_cell_targets_island_corrected.json'
OUT_REPORT=ROOT/'reports'/'world_island_logic_report.json'

NORTH_ATLANTIC_REGION_ID='region:world:north_atlantic_european_islands'
NORTH_ATLANTIC_REGION_NAME='Северо-Атлантические острова Европы'
ATLANTIC_EUROPE_REGION_ID='region:world:atlantic_european_islands'
ATLANTIC_EUROPE_REGION_NAME='Атлантические острова Европы'

# Explicit semantic membership. Names are matched case-insensitively against
# province name + legacy id, so source naming variants remain safe.
NORTH_ATLANTIC_TOKENS=('iceland','faroe')
ATLANTIC_EUROPE_TOKENS=('azores','a_ores','madeira')
SCOTTISH_ISLAND_TOKENS=('orkney','shetland','hebr','western_isles','argyll')
GOTLAND_TOKEN='gotland'

SCOTTISH_ALLOWED=('Шотландская низменность','Шотландское нагорье')


def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def round_half_up(x): return int(Decimal(str(x)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def km_per_world_px(y):
    n=math.pi-2*math.pi*y/WORLD_PX
    lat=math.degrees(math.atan(math.sinh(n)))
    return 2*math.pi*EARTH_RADIUS_KM/WORLD_PX*math.cos(math.radians(lat))
def area_km2(g):
    if g.is_empty:return 0.0
    s=km_per_world_px(g.representative_point().y)
    return float(g.area)*s*s

def geom(entry):
    rings=entry.get('rings',[])
    if not rings:return Polygon()
    g=Polygon(rings[0],rings[1:])
    if not g.is_valid:g=g.buffer(0)
    return g

def parts(g):
    if g.is_empty:return []
    if isinstance(g,Polygon):return [g]
    if isinstance(g,(MultiPolygon,GeometryCollection)) or hasattr(g,'geoms'):
        return [p for p in g.geoms if isinstance(p,Polygon) and not p.is_empty]
    return []
def keytext(identity): return (str(identity.get('name',''))+' '+str(identity.get('legacy_id',''))).lower()
def contains_any(text,tokens): return any(t in text for t in tokens)


def significant_components(g,target_area):
    ps=sorted(parts(g),key=lambda p:p.area,reverse=True)
    if len(ps)<=1:return ps,[]
    total=sum(area_km2(p) for p in ps)
    significant=[]; tiny=[]
    # No arbitrary global island-size cutoff. A disconnected component is
    # significant if it is at least 2% of the province OR at least 10% of one
    # regional target cell. This only separates tiny rocks from real islands;
    # the actual 1-vs-many cell decision is area/target below.
    abs_floor=max(1.0,float(target_area)*0.10)
    rel_floor=total*0.02
    floor=min(abs_floor,rel_floor) if total>0 else abs_floor
    for p in ps:
        a=area_km2(p)
        (significant if a>=floor else tiny).append(p)
    if not significant and ps:
        significant=[ps[0]];tiny=ps[1:]
    return significant,tiny


def component_counts(g,target_area,min_cells,max_cells,base_anchor=1):
    significant,tiny=significant_components(g,target_area)
    if not significant:
        return [max(1,min_cells)],tiny
    counts=[]
    for p in significant:
        a=area_km2(p)
        # User rule: a small island = 1 cell. Here "small" is defined relative
        # to the region's own table target, not a made-up global km² value.
        c=1 if a<=target_area else max(1,round_half_up(a/target_area))
        counts.append(c)
    total=max(sum(counts),base_anchor,min_cells)
    total=min(total,max_cells)
    # If min/anchor requires more, give extras to largest islands first.
    while sum(counts)<total:
        idx=max(range(len(significant)),key=lambda i:area_km2(significant[i])/counts[i])
        counts[idx]+=1
    # If max forced a reduction, remove extras from islands with the smallest
    # area-per-cell while never dropping a significant island below one cell.
    while sum(counts)>total:
        candidates=[i for i,c in enumerate(counts) if c>1]
        if not candidates:break
        idx=min(candidates,key=lambda i:area_km2(significant[i])/counts[i])
        counts[idx]-=1
    return counts,tiny


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    identities={str(x['id']):x for x in read(IDENTITY_PATH).get('provinces',[])}
    assignments=read(ASSIGN_PATH)
    assign_list=[dict(x) for x in assignments.get('assignments',[])]
    targets=read(TARGET_PATH)
    target_list=[dict(x) for x in targets.get('provinces',[])]
    target_by_id={str(x['province_id']):x for x in target_list}
    geom_by_id={}
    for e in read(GEOMETRY_PATH).get('provinces',[]):
        pid=str(e.get('id',''));g=geom(e)
        if pid and not g.is_empty:geom_by_id[pid]=g

    # First pass: semantic explicit region corrections.
    corrections=[]
    gotland_region=None
    for a in assign_list:
        pid=str(a.get('province_id',''));ident=identities.get(pid,{})
        text=keytext(ident)
        if GOTLAND_TOKEN in text and 'sweden' in str(ident.get('legacy_id','')).lower():
            # Prefer the largest/base Gotland province current region as parent.
            if gotland_region is None:
                gotland_region=(str(a.get('region_id','')),str(a.get('region_name','')))
    for a in assign_list:
        pid=str(a.get('province_id',''));ident=identities.get(pid,{})
        text=keytext(ident);legacy=str(ident.get('legacy_id','')).lower()
        old=(str(a.get('region_id','')),str(a.get('region_name','')))
        new=None;reason=''
        if contains_any(text,NORTH_ATLANTIC_TOKENS):
            new=(NORTH_ATLANTIC_REGION_ID,NORTH_ATLANTIC_REGION_NAME);reason='explicit_north_atlantic_family'
        elif contains_any(text,ATLANTIC_EUROPE_TOKENS):
            new=(ATLANTIC_EUROPE_REGION_ID,ATLANTIC_EUROPE_REGION_NAME);reason='explicit_atlantic_europe_family'
        elif 'united_kingdom' in legacy and contains_any(text,SCOTTISH_ISLAND_TOKENS):
            # Keep existing assignment if already Scottish; otherwise choose
            # Scottish Highlands as conservative island parent and mark review.
            if old[1] not in SCOTTISH_ALLOWED:
                new=('region:world:shotlandskoe_nagore','Шотландское нагорье');reason='scottish_nearshore_inheritance_review'
        elif 'sweden' in legacy and GOTLAND_TOKEN in text and gotland_region is not None and old!=gotland_region:
            new=gotland_region;reason='gotland_satellite_inherits_parent'
        if new and new!=old:
            a['region_id'],a['region_name']=new
            a['method']='island_semantic_override'
            a['confidence']='locked' if 'review' not in reason else 'review'
            corrections.append({'province_id':pid,'name':ident.get('name',''),'legacy_id':ident.get('legacy_id',''),'from_region':old[1],'to_region':new[1],'reason':reason})

    # Profile lookup including two new island groups. New group target values
    # intentionally reuse existing table archetypes rather than inventing a new
    # numeric density model: North Atlantic = P4 baseline; Atlantic Europe =
    # P3 baseline. They are explicit metadata and easy to revise later.
    profile_doc=read(PROFILE_PATH)
    profiles=profile_doc.get('profiles',[])
    by_region_name={str(x.get('name','')):x for x in profiles}
    base_profiles=read(ROOT/'assets'/'game_data'/'land_cell_generation_profiles.json').get('profiles',{})
    by_region_name[NORTH_ATLANTIC_REGION_NAME]={
        'profile_id':'P4','target_cell_area_km2':base_profiles['P4']['target_cell_area_km2'],
        'min_cells_per_province':1,'max_cells_per_province':12,
    }
    by_region_name[ATLANTIC_EUROPE_REGION_NAME]={
        'profile_id':'P3','target_cell_area_km2':base_profiles['P3']['target_cell_area_km2'],
        'min_cells_per_province':1,'max_cells_per_province':10,
    }

    assign_by_id={str(x['province_id']):x for x in assign_list}
    allocation=[];changed_counts=[];multipart=0;significant_total=0;tiny_total=0
    for t in target_list:
        pid=str(t['province_id']);g=geom_by_id[pid];a=assign_by_id[pid]
        region_name=str(a.get('region_name',''))
        profile=by_region_name.get(region_name)
        if profile is None:
            # Preserve previous profile if no new semantic profile needed.
            target_area=float(t.get('region_target_cell_area_km2',2200.0))
            minimum=int(t.get('region_min_cells',1));maximum=int(t.get('region_max_cells',14));profile_id=str(t.get('profile_id','P3'))
        else:
            target_area=float(profile['target_cell_area_km2']);minimum=int(profile['min_cells_per_province']);maximum=int(profile['max_cells_per_province']);profile_id=str(profile['profile_id'])
        anchor=int(t.get('anchor_min',1) or 1)
        counts,tiny=component_counts(g,target_area,minimum,maximum,anchor)
        sig_count=len(counts)
        if len(parts(g))>1:multipart+=1
        significant_total+=sig_count;tiny_total+=len(tiny)
        old_count=int(t.get('target_cell_count',1));new_count=sum(counts)
        t['region_id']=str(a.get('region_id',''));t['region_name']=region_name
        t['profile_id']=profile_id;t['region_target_cell_area_km2']=target_area;t['region_min_cells']=minimum;t['region_max_cells']=maximum
        t['island_component_cell_counts']=counts
        t['significant_island_component_count']=sig_count
        t['tiny_island_component_count']=len(tiny)
        t['cross_sea_cell_merge_forbidden']=sig_count>1
        t['target_cell_count']=new_count
        if old_count!=new_count:
            changed_counts.append({'province_id':pid,'name':t.get('name',''),'region_name':region_name,'old_count':old_count,'new_count':new_count,'component_counts':counts})
        allocation.append({'province_id':pid,'name':t.get('name',''),'region_name':region_name,'significant_components':sig_count,'tiny_components':len(tiny),'component_cell_counts':counts,'total_cells':new_count})

    out_assign=dict(assignments);out_assign['format']='world_region_assignments_island_corrected/v1';out_assign['assignments']=assign_list
    out_target=dict(targets);out_target['format']='world_province_cell_targets_island_corrected/v1';out_target['provinces']=target_list;out_target['total_target_cells']=sum(int(x['target_cell_count']) for x in target_list)
    report={
        'schema_version':1,'format':'world_island_logic_report/v1','province_count':len(target_list),
        'region_correction_count':len(corrections),'region_corrections':corrections,
        'multipart_province_count':multipart,'significant_island_component_count':significant_total,'tiny_component_count':tiny_total,
        'cell_count_changed_province_count':len(changed_counts),'cell_count_changes':changed_counts,
        'total_target_cells_before':int(targets.get('total_target_cells',0)),'total_target_cells_after':out_target['total_target_cells'],
        'allocation':allocation,
    }
    if args.check:
        for path,obj in ((OUT_ASSIGN,out_assign),(OUT_TARGET,out_target),(OUT_REPORT,report)):
            expected=json.dumps(obj,ensure_ascii=False,indent=2)+'\n'
            if not path.exists() or path.read_text(encoding='utf-8')!=expected: raise SystemExit(f'CHECK_MISMATCH {path}')
    else:
        write(OUT_ASSIGN,out_assign);write(OUT_TARGET,out_target);write(OUT_REPORT,report)
    print('WORLD_ISLAND_LOGIC_OK','corrections=',len(corrections),'changed_counts=',len(changed_counts),'cells_before=',report['total_target_cells_before'],'cells_after=',report['total_target_cells_after'])

if __name__=='__main__':main()
