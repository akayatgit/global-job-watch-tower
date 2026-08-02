"""Living labor-market world model for the VIGIL Neural Core.

Summarises Postgres hiring data into a capped node/edge graph:
  core → sectors → cities / companies / roles
Edges are real co-occurrence counts (never invented).
"""

from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.cities import CITY_BY_ID
from app.models import Company, JobMaster, SearchConfig
from app.sectors import SECTOR_BY_ID
from app.signals import ALLOWED_WINDOWS, WINDOW_OPTIONS, _window_bounds

# Caps keep the Three.js scene readable on the ThinkPad while Ollama runs.
MAX_SECTORS = 8
MAX_CITIES = 10
MAX_COMPANIES = 12
MAX_ROLES = 10
MAX_EDGES = 120
RANK_CITIES = {
    'bengaluru', 'hyderabad', 'chennai', 'kerala', 'pune', 'mumbai',
    'delhi', 'gurugram', 'noida', 'ahmedabad', 'kolkata', 'remote',
}


def compute_world_model(db: Session, window_days: int = 7) -> dict:
    if window_days not in ALLOWED_WINDOWS:
        window_days = 7
    (window_days, recent_start, recent_end, _ps, _pe,
     by_scraped) = _window_bounds(window_days)
    time_col = JobMaster.scraped_at if by_scraped else JobMaster.posted_date

    # Aggregate queries only — never load full job rows into the graph.
    total = db.execute(
        select(func.count(JobMaster.id)).where(
            time_col >= recent_start, time_col < recent_end,
        )
    ).scalar() or 0

    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()

    def add_node(nid: str, kind: str, label: str, weight: int, **meta):
        if nid in node_ids or weight <= 0:
            return
        node_ids.add(nid)
        nodes.append({
            'id': nid,
            'kind': kind,
            'label': label,
            'weight': int(weight),
            **meta,
        })

    def add_edge(src: str, dst: str, weight: int, relation: str):
        if src not in node_ids or dst not in node_ids or weight <= 0:
            return
        if len(edges) >= MAX_EDGES:
            return
        edges.append({
            'source': src,
            'target': dst,
            'weight': int(weight),
            'relation': relation,
        })

    add_node(
        'core', 'core', 'Labor Market', total,
        subtitle='World model',
    )

    # --- Sectors ---
    sector_rows = db.execute(
        select(JobMaster.sector, func.count(JobMaster.id).label('n'))
        .where(time_col >= recent_start, time_col < recent_end)
        .group_by(JobMaster.sector)
        .order_by(desc('n'))
        .limit(MAX_SECTORS)
    ).all()
    for sid, n in sector_rows:
        if not sid:
            continue
        meta = SECTOR_BY_ID.get(sid, {})
        label = meta.get('label') or sid.replace('_', ' ').title()
        nid = f'sector:{sid}'
        add_node(nid, 'sector', label, n, sector_id=sid)
        add_edge('core', nid, n, 'contains')

    # --- Cities (metros + remote) ---
    city_rows = db.execute(
        select(JobMaster.city_key, func.count(JobMaster.id).label('n'))
        .where(
            time_col >= recent_start, time_col < recent_end,
            JobMaster.city_key.in_(RANK_CITIES),
        )
        .group_by(JobMaster.city_key)
        .order_by(desc('n'))
        .limit(MAX_CITIES)
    ).all()
    for cid, n in city_rows:
        if not cid:
            continue
        label = CITY_BY_ID.get(cid, {}).get('label') or cid.title()
        nid = f'city:{cid}'
        add_node(nid, 'city', label, n, city_id=cid)
        add_edge('core', nid, max(1, n // 3), 'places')

    # --- Companies ---
    co_rows = db.execute(
        select(Company.id, Company.name, func.count(JobMaster.id).label('n'))
        .join(JobMaster, JobMaster.company_id == Company.id)
        .where(time_col >= recent_start, time_col < recent_end)
        .group_by(Company.id, Company.name)
        .order_by(desc('n'))
        .limit(MAX_COMPANIES)
    ).all()
    for company_id, name, n in co_rows:
        nid = f'company:{company_id}'
        add_node(
            nid, 'company', name or 'Unknown', n,
            company_id=company_id,
        )
        add_edge('core', nid, max(1, n // 4), 'employs')

    # --- Growing / active roles (by job volume in window) ---
    role_rows = db.execute(
        select(
            SearchConfig.id, SearchConfig.name, SearchConfig.sector,
            func.count(JobMaster.id).label('n'),
        )
        .join(JobMaster, JobMaster.search_config_id == SearchConfig.id)
        .where(time_col >= recent_start, time_col < recent_end)
        .group_by(SearchConfig.id, SearchConfig.name, SearchConfig.sector)
        .order_by(desc('n'))
        .limit(MAX_ROLES)
    ).all()
    for search_id, name, sector, n in role_rows:
        nid = f'role:{search_id}'
        add_node(
            nid, 'role', name or f'Role {search_id}', n,
            search_id=search_id, sector_id=sector or '',
        )
        if sector:
            add_edge(f'sector:{sector}', nid, n, 'role_in')
        else:
            add_edge('core', nid, n, 'role_in')

    # --- Sector ↔ City co-occurrence ---
    sc_rows = db.execute(
        select(
            JobMaster.sector, JobMaster.city_key,
            func.count(JobMaster.id).label('n'),
        )
        .where(
            time_col >= recent_start, time_col < recent_end,
            JobMaster.city_key.in_(RANK_CITIES),
            JobMaster.sector.is_not(None),
        )
        .group_by(JobMaster.sector, JobMaster.city_key)
        .order_by(desc('n'))
        .limit(40)
    ).all()
    for sector, city, n in sc_rows:
        add_edge(f'sector:{sector}', f'city:{city}', n, 'hires_in')

    # --- Sector ↔ Company ---
    sco_rows = db.execute(
        select(
            JobMaster.sector, Company.id,
            func.count(JobMaster.id).label('n'),
        )
        .join(Company, JobMaster.company_id == Company.id)
        .where(
            time_col >= recent_start, time_col < recent_end,
            JobMaster.sector.is_not(None),
        )
        .group_by(JobMaster.sector, Company.id)
        .order_by(desc('n'))
        .limit(40)
    ).all()
    for sector, company_id, n in sco_rows:
        add_edge(f'sector:{sector}', f'company:{company_id}', n, 'company_in')

    # --- City ↔ Company ---
    cc_rows = db.execute(
        select(
            JobMaster.city_key, Company.id,
            func.count(JobMaster.id).label('n'),
        )
        .join(Company, JobMaster.company_id == Company.id)
        .where(
            time_col >= recent_start, time_col < recent_end,
            JobMaster.city_key.in_(RANK_CITIES),
        )
        .group_by(JobMaster.city_key, Company.id)
        .order_by(desc('n'))
        .limit(40)
    ).all()
    for city, company_id, n in cc_rows:
        add_edge(f'city:{city}', f'company:{company_id}', n, 'company_at')

    # --- Role ↔ Company (top links) ---
    rc_rows = db.execute(
        select(
            JobMaster.search_config_id, Company.id,
            func.count(JobMaster.id).label('n'),
        )
        .join(Company, JobMaster.company_id == Company.id)
        .where(
            time_col >= recent_start, time_col < recent_end,
            JobMaster.search_config_id.is_not(None),
        )
        .group_by(JobMaster.search_config_id, Company.id)
        .order_by(desc('n'))
        .limit(30)
    ).all()
    for search_id, company_id, n in rc_rows:
        add_edge(f'role:{search_id}', f'company:{company_id}', n, 'hiring')

    max_w = max([n['weight'] for n in nodes] + [1])
    window_label = dict(WINDOW_OPTIONS).get(window_days, f'{window_days}d')

    return {
        'days': window_days,
        'window_label': window_label,
        'generated_at': None,  # filled by route with iso
        'stats': {
            'jobs': total,
            'nodes': len(nodes),
            'edges': len(edges),
            'max_weight': max_w,
        },
        'nodes': nodes,
        'edges': edges,
        'hint': (
            'Living world model — nodes and links from real hiring data. '
            'Click a point to open its insight panel.'
        ),
    }
