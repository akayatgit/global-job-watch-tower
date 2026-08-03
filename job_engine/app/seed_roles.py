"""Dual-track India search catalogue for Watch Tower.

Track A — Fresher (primary): LinkedIn f_E=1,2 (Internship + Entry level),
early-career keywords, daily flywheel for graduate employability.

Track B — Market Signal (secondary): no experience filter, thinner pages,
major tech roles for hiring-signal / economy decode.

Critical sectors (2026-08-02): Tech·AI, Tech·Digital, Manufacturing,
Healthcare, Green economy, Logistics, Tourism — light coverage outside Tech.
"""

from __future__ import annotations

from app.sectors import infer_sector

# LinkedIn f_E: 1=Internship, 2=Entry level
FRESHER_EXPERIENCE_FILTER = '1,2'
SIGNAL_EXPERIENCE_FILTER = ''  # all levels — economy / mid-senior mix

# Seed row: (display_name, linkedin_keywords, experience_filter, track)
# track: 'fresher' | 'signal'

FRESHER_ROLES: list[tuple[str, str]] = [
    # —— Classic fresher / campus funnels (priority pages) ——
    ('Graduate Software Engineer', 'graduate software engineer'),
    ('Junior Software Developer', 'junior software developer'),
    ('Software Intern', 'software intern'),
    ('Data Intern', 'data intern'),
    ('Campus Hire Software', 'campus hire software'),
    ('Graduate Trainee', 'graduate trainee'),
    ('Management Trainee', 'management trainee'),
    ('Analyst Trainee', 'analyst trainee'),
    ('Helpdesk Analyst', 'helpdesk analyst'),
    ('Process Associate', 'process associate'),
    ('IT Support Fresher', 'it support fresher'),
    ('Technical Support Fresher', 'technical support fresher'),

    # —— AI / GenAI / ML (early career) ——
    ('AI Engineer Fresher', 'ai engineer fresher'),
    ('Junior AI Engineer', 'junior ai engineer'),
    ('ML Engineer Fresher', 'ml engineer fresher'),
    ('Junior Machine Learning Engineer', 'junior machine learning engineer'),
    ('Junior Data Scientist', 'junior data scientist'),
    ('Data Scientist Fresher', 'data scientist fresher'),
    ('GenAI Engineer Fresher', 'genai engineer fresher'),
    ('Junior Prompt Engineer', 'junior prompt engineer'),
    ('AI/ML Intern', 'ai ml intern'),
    ('AI Research Intern', 'ai research intern'),
    ('Junior NLP Engineer', 'junior nlp engineer'),
    ('Junior Computer Vision Engineer', 'junior computer vision'),
    ('Junior LLM Engineer', 'junior llm engineer'),
    ('AI QA Fresher', 'ai qa fresher'),
    ('Junior Agentic AI Engineer', 'junior agentic ai'),

    # —— Data ——
    ('Junior Data Analyst', 'junior data analyst'),
    ('Data Analyst Fresher', 'data analyst fresher'),
    ('Junior Data Engineer', 'junior data engineer'),
    ('Junior Business Analyst', 'junior business analyst'),
    ('Junior BI Analyst', 'junior business intelligence'),
    ('Junior Analytics Engineer', 'junior analytics engineer'),
    ('Junior SQL Developer', 'junior sql developer'),
    ('Junior ETL Developer', 'junior etl developer'),
    ('Junior Power BI Developer', 'junior power bi'),
    ('Data Annotation', 'data annotation'),
    ('AI Trainer Fresher', 'ai trainer fresher'),

    # —— Software engineering ——
    ('Junior Backend Developer', 'junior backend developer'),
    ('Junior Frontend Developer', 'junior frontend developer'),
    ('Junior Full Stack Developer', 'junior full stack developer'),
    ('Junior Java Developer', 'junior java developer'),
    ('Junior Python Developer', 'junior python developer'),
    ('Junior JavaScript Developer', 'junior javascript developer'),
    ('Junior React Developer', 'junior react developer'),
    ('Junior Node.js Developer', 'junior nodejs developer'),
    ('Junior .NET Developer', 'junior .net developer'),
    ('Junior Android Developer', 'junior android developer'),
    ('Junior iOS Developer', 'junior ios developer'),
    ('Junior Flutter Developer', 'junior flutter developer'),
    ('Junior Golang Developer', 'junior golang developer'),
    ('Junior C++ Developer', 'junior c++ developer'),

    # —— QA / DevOps / Cloud (early) ——
    ('Junior QA Engineer', 'junior qa engineer'),
    ('Software Tester Fresher', 'software tester fresher'),
    ('Junior SDET', 'junior sdet'),
    ('Junior Automation Test Engineer', 'junior automation test'),
    ('Junior DevOps Engineer', 'junior devops'),
    ('Junior Cloud Engineer', 'junior cloud engineer'),
    ('Junior AWS Cloud Engineer', 'junior aws cloud'),
    ('Junior Azure Engineer', 'junior azure engineer'),

    # —— Cybersecurity ——
    ('Junior Cybersecurity Analyst', 'junior cybersecurity analyst'),
    ('Junior Security Analyst', 'junior security analyst'),
    ('SOC Analyst Fresher', 'soc analyst fresher'),
    ('Junior Information Security Analyst', 'junior information security'),
    ('Cyber Security Fresher', 'cyber security fresher'),
    ('Junior GRC Analyst', 'junior grc analyst'),

    # —— Product / Design (early only) ——
    ('Associate Product Manager', 'associate product manager'),
    ('Junior Product Analyst', 'junior product analyst'),
    ('Junior UI UX Designer', 'junior ui ux designer'),
    ('Junior Product Designer', 'junior product designer'),
    ('UX Researcher Intern', 'ux researcher intern'),

    # —— Support / IT ——
    ('Desktop Support Engineer Fresher', 'desktop support fresher'),
    ('Junior System Administrator', 'junior system administrator'),
    ('Junior Network Engineer', 'junior network engineer'),
    ('Application Support Fresher', 'application support fresher'),

    # —— Business / consulting / finance adjacent ——
    ('Risks & Controls Fresher', 'risk and control fresher'),
    ('Consultant Fresher', 'consultant fresher'),
    ('Associate Consultant', 'associate consultant'),
    ('Junior Risk Analyst', 'junior risk analyst'),
    ('Junior Compliance Analyst', 'junior compliance analyst'),
    ('Audit Associate', 'audit associate'),
    ('Junior Financial Analyst', 'junior financial analyst'),
    ('Junior Operations Analyst', 'junior operations analyst'),
    ('HR Fresher', 'hr fresher'),
    ('Talent Acquisition Fresher', 'talent acquisition fresher'),
    ('Sales Development Representative', 'sales development representative'),
    ('Business Development Associate', 'business development associate'),
    ('Junior Marketing Analyst', 'junior marketing analyst'),
    ('Digital Marketing Executive', 'digital marketing executive'),
    ('Junior Content Writer', 'junior content writer'),
    ('Junior Technical Writer', 'junior technical writer'),

    # —— Emerging platforms ——
    ('Junior RPA Developer', 'junior rpa developer'),
    ('Junior Salesforce Developer', 'junior salesforce developer'),
    ('SAP Fresher', 'sap fresher'),
    ('Junior Blockchain Developer', 'junior blockchain developer'),
    ('Junior Game Developer', 'junior game developer'),
    ('Junior Embedded Engineer', 'junior embedded engineer'),
    ('Junior IoT Engineer', 'junior iot engineer'),
]

# Market Signal — major tech roles, no f_E (experienced mix for economy decode)
SIGNAL_ROLES: list[tuple[str, str]] = [
    ('Software Engineer · Market Signal', 'software engineer'),
    ('Backend Developer · Market Signal', 'backend developer'),
    ('Full Stack Developer · Market Signal', 'full stack developer'),
    ('Data Scientist · Market Signal', 'data scientist'),
    ('Data Engineer · Market Signal', 'data engineer'),
    ('Machine Learning Engineer · Market Signal', 'machine learning engineer'),
    ('AI Engineer · Market Signal', 'ai engineer'),
    ('MLOps Engineer · Market Signal', 'mlops engineer'),
    ('Applied Scientist · Market Signal', 'applied scientist'),
    ('DevOps Engineer · Market Signal', 'devops engineer'),
    ('Platform Engineer · Market Signal', 'platform engineer'),
    ('Site Reliability Engineer · Market Signal', 'site reliability engineer'),
    ('Cloud Engineer · Market Signal', 'cloud engineer'),
    ('Kubernetes Engineer · Market Signal', 'kubernetes'),
    ('Product Manager · Market Signal', 'product manager'),
    ('Technical Product Manager · Market Signal', 'technical product manager'),
    ('AI Product Owner · Market Signal', 'ai product owner'),
    ('Penetration Tester · Market Signal', 'penetration tester'),
    ('Cybersecurity Analyst · Market Signal', 'cybersecurity analyst'),
    ('Business Analyst · Market Signal', 'business analyst'),
    ('QA Engineer · Market Signal', 'qa engineer'),
    ('Java Developer · Market Signal', 'java developer'),
    ('Python Developer · Market Signal', 'python developer'),
    ('React Developer · Market Signal', 'react developer'),
    ('Android Developer · Market Signal', 'android developer'),
]

# Light everyday coverage for non-tech critical sectors (fresher track + f_E).
# (display_name, linkedin_keywords, sector_id)
SECTOR_EXPANSION_ROLES: list[tuple[str, str, str]] = [
    ('Junior AI Solutions Engineer', 'junior ai solutions engineer', 'tech_ai'),
    ('Junior Digital Transformation Analyst', 'junior digital transformation', 'tech_digital'),
    ('Junior Manufacturing Engineer', 'junior manufacturing engineer', 'manufacturing_advanced'),
    ('Junior Production Engineer', 'junior production engineer', 'manufacturing_advanced'),
    ('Clinical Research Associate Fresher', 'clinical research associate fresher', 'healthcare'),
    ('Junior Healthcare Analyst', 'junior healthcare analyst', 'healthcare'),
    ('Junior Sustainability Analyst', 'junior sustainability analyst', 'green_economy'),
    ('Junior Renewable Energy Engineer', 'junior renewable energy', 'green_economy'),
    ('Junior Supply Chain Analyst', 'junior supply chain analyst', 'logistics'),
    ('Logistics Coordinator Fresher', 'logistics coordinator fresher', 'logistics'),
    ('Hotel Operations Fresher', 'hotel operations fresher', 'tourism'),
    ('Travel Consultant Fresher', 'travel consultant fresher', 'tourism'),
]

# Keywords that get priority page depth on fresher track
PRIORITY_KEYWORD_NEEDLES = (
    'intern', 'campus', 'trainee', 'graduate', 'helpdesk', 'associate',
    'fresher', 'annotation',
)


def all_seed_roles() -> list[tuple[str, str, str, str, str]]:
    """Flatten catalogue into (name, keywords, sector_id, experience_filter, track)."""
    out: list[tuple[str, str, str, str, str]] = []
    seen: set[str] = set()

    def add(name: str, keywords: str, sector: str, exp: str, track: str) -> None:
        key = f'{keywords.strip().lower()}|{exp}|{track}'
        if key in seen:
            return
        seen.add(key)
        out.append((name, keywords, sector, exp, track))

    for name, keywords in FRESHER_ROLES:
        add(name, keywords, infer_sector(name, keywords), FRESHER_EXPERIENCE_FILTER, 'fresher')

    for name, keywords, sector in SECTOR_EXPANSION_ROLES:
        add(name, keywords, sector, FRESHER_EXPERIENCE_FILTER, 'fresher')

    for name, keywords in SIGNAL_ROLES:
        add(name, keywords, infer_sector(name, keywords), SIGNAL_EXPERIENCE_FILTER, 'signal')

    return out


# Backward-compatible alias used by older imports
FRESHER_MAJOR_ROLES = [(n, k) for n, k in FRESHER_ROLES]

INDIA_GEO_ID = '102713980'
INDIA_LABEL = 'India'

DEFAULT_MAX_PAGES = 5
PRIORITY_MAX_PAGES = 10
SIGNAL_MAX_PAGES = 3
SECTOR_LIGHT_MAX_PAGES = 3
