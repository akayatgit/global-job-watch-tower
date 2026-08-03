"""Living labor-market world model for the VIGIL Neural Core.

Summarises Postgres hiring data into a capped node/edge graph:
  core → sectors → cities / companies / roles
Edges are real co-occurrence counts (never invented).
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.cities import CITY_BY_ID
from app.models import Company, JobMaster, SearchConfig
from app.sectors import SECTOR_BY_ID
from app.signals import ALLOWED_WINDOWS, WINDOW_OPTIONS, _window_bounds


def _slug(label: str) -> str:
    s = ''.join(ch.lower() if ch.isalnum() else '-' for ch in (label or ''))
    while '--' in s:
        s = s.replace('--', '-')
    return s.strip('-')[:48] or 'unknown'

# Caps keep the Three.js scene readable on the ThinkPad while Ollama runs.
MAX_SECTORS = 8
MAX_CITIES = 10
MAX_COMPANIES = 12
MAX_ROLES = 10
MAX_EXPERIENCE = 8
MAX_DEGREE = 8
MAX_CERT = 8
MAX_DOMAIN = 8
MAX_EDGES = 220
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
        select(
            Company.id, Company.name, Company.logo_url, Company.punchline,
            Company.tagline, Company.follower_count, Company.employee_count_label,
            func.count(JobMaster.id).label('n'),
        )
        .join(JobMaster, JobMaster.company_id == Company.id)
        .where(time_col >= recent_start, time_col < recent_end)
        .group_by(
            Company.id, Company.name, Company.logo_url, Company.punchline,
            Company.tagline, Company.follower_count, Company.employee_count_label,
        )
        .order_by(desc('n'))
        .limit(MAX_COMPANIES)
    ).all()
    for (
        company_id, name, logo_url, punchline, tagline,
        followers, emp_label, n,
    ) in co_rows:
        nid = f'company:{company_id}'
        add_node(
            nid, 'company', name or 'Unknown', n,
            company_id=company_id,
            logo_url=logo_url,
            punchline=punchline or tagline,
            tagline=tagline,
            follower_count=followers,
            employee_count_label=emp_label,
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
        .limit(60)
    ).all()
    for search_id, company_id, n in rc_rows:
        # Neural hierarchy: company ↔ role so climb is company → role → sector
        add_edge(f'role:{search_id}', f'company:{company_id}', n, 'hiring')

    # --- Requirement clusters (experience / degree / cert / domain) ---
    # Aggregate from enriched rows only — real extract, never invented.
    req_rows = db.execute(
        select(
            JobMaster.experience_band,
            JobMaster.degrees,
            JobMaster.certifications,
            JobMaster.domains,
            JobMaster.company_id,
            JobMaster.search_config_id,
        )
        .where(
            time_col >= recent_start, time_col < recent_end,
            JobMaster.requirements_enriched_at.is_not(None),
        )
        .limit(8000)
    ).all()

    exp_c: Counter[str] = Counter()
    deg_c: Counter[str] = Counter()
    cert_c: Counter[str] = Counter()
    dom_c: Counter[str] = Counter()
    exp_co: Counter[tuple[str, int]] = Counter()
    deg_role: Counter[tuple[str, int]] = Counter()
    cert_role: Counter[tuple[str, int]] = Counter()
    dom_co: Counter[tuple[str, int]] = Counter()

    for band, degrees, certs, domains, company_id, search_id in req_rows:
        if band:
            exp_c[band] += 1
            if company_id is not None:
                exp_co[(band, int(company_id))] += 1
        for d in degrees or []:
            if not d:
                continue
            deg_c[str(d)] += 1
            if search_id is not None:
                deg_role[(str(d), int(search_id))] += 1
        for c in certs or []:
            if not c:
                continue
            cert_c[str(c)] += 1
            if search_id is not None:
                cert_role[(str(c), int(search_id))] += 1
        for dom in domains or []:
            if not dom:
                continue
            dom_c[str(dom)] += 1
            if company_id is not None:
                dom_co[(str(dom), int(company_id))] += 1

    for label, n in exp_c.most_common(MAX_EXPERIENCE):
        nid = f'experience:{_slug(label)}'
        add_node(nid, 'experience', label, n)
        add_edge('core', nid, n, 'requires_exp')

    for label, n in deg_c.most_common(MAX_DEGREE):
        nid = f'degree:{_slug(label)}'
        add_node(nid, 'degree', label, n)
        add_edge('core', nid, n, 'requires_degree')

    for label, n in cert_c.most_common(MAX_CERT):
        nid = f'cert:{_slug(label)}'
        add_node(nid, 'certification', label, n)
        add_edge('core', nid, n, 'requires_cert')

    for label, n in dom_c.most_common(MAX_DOMAIN):
        nid = f'domain:{_slug(label)}'
        add_node(nid, 'domain', label, n)
        add_edge('core', nid, n, 'requires_domain')

    for (band, company_id), n in exp_co.most_common(30):
        add_edge(
            f'experience:{_slug(band)}',
            f'company:{company_id}',
            n,
            'exp_at',
        )
    for (deg, search_id), n in deg_role.most_common(30):
        add_edge(
            f'degree:{_slug(deg)}',
            f'role:{search_id}',
            n,
            'degree_for',
        )
    for (cert, search_id), n in cert_role.most_common(30):
        add_edge(
            f'cert:{_slug(cert)}',
            f'role:{search_id}',
            n,
            'cert_for',
        )
    for (dom, company_id), n in dom_co.most_common(30):
        add_edge(
            f'domain:{_slug(dom)}',
            f'company:{company_id}',
            n,
            'domain_at',
        )

    enriched_n = len(req_rows)
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
            'requirements_enriched': enriched_n,
        },
        'nodes': nodes,
        'edges': edges,
        'hint': (
            'Living world model — sectors, cities, companies, roles, plus '
            'experience / degree / certification / domain requirement clusters '
            'from job detail pages.'
        ),
    }
