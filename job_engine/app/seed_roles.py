"""Canonical fresher + major role catalogue for Watch Tower India searches.

Priority: be first to collect daily 24h market insights across the major
entry-level / early-career talent map (AI, software, data, cloud, cyber,
product, business, and classic fresher funnels).
"""

from __future__ import annotations

# (display_name, linkedin_keywords)
# Keywords tuned for LinkedIn search — short, role-shaped phrases.
FRESHER_MAJOR_ROLES: list[tuple[str, str]] = [
    # —— Keep / align with existing pilot (also upserted) ——
    ('AI Product Owner', 'ai product owner'),
    ('Risks & Controls', 'risk and control'),

    # —— AI / GenAI / ML (campus premium 2026) ——
    ('AI Engineer', 'ai engineer'),
    ('Machine Learning Engineer', 'machine learning engineer'),
    ('ML Engineer Fresher', 'ml engineer fresher'),
    ('Data Scientist', 'data scientist'),
    ('Junior Data Scientist', 'junior data scientist'),
    ('GenAI Engineer', 'genai engineer'),
    ('Generative AI Engineer', 'generative ai engineer'),
    ('Prompt Engineer', 'prompt engineer'),
    ('AI/ML Intern', 'ai ml intern'),
    ('NLP Engineer', 'nlp engineer'),
    ('Computer Vision Engineer', 'computer vision engineer'),
    ('LLM Engineer', 'llm engineer'),
    ('AI Research Intern', 'ai research intern'),
    ('Applied Scientist', 'applied scientist'),
    ('MLOps Engineer', 'mlops engineer'),
    ('AI QA Engineer', 'ai qa'),
    ('Agentic AI Engineer', 'agentic ai engineer'),

    # —— Data ——
    ('Data Analyst', 'data analyst'),
    ('Junior Data Analyst', 'junior data analyst'),
    ('Data Engineer', 'data engineer'),
    ('Junior Data Engineer', 'junior data engineer'),
    ('Business Analyst', 'business analyst'),
    ('BI Analyst', 'business intelligence analyst'),
    ('Analytics Engineer', 'analytics engineer'),
    ('SQL Developer', 'sql developer'),
    ('ETL Developer', 'etl developer'),
    ('Power BI Developer', 'power bi developer'),

    # —— Software engineering ——
    ('Software Engineer', 'software engineer'),
    ('Software Developer', 'software developer'),
    ('Graduate Software Engineer', 'graduate software engineer'),
    ('Junior Software Developer', 'junior software developer'),
    ('Backend Developer', 'backend developer'),
    ('Frontend Developer', 'frontend developer'),
    ('Full Stack Developer', 'full stack developer'),
    ('Java Developer', 'java developer'),
    ('Python Developer', 'python developer'),
    ('JavaScript Developer', 'javascript developer'),
    ('React Developer', 'react developer'),
    ('Node.js Developer', 'nodejs developer'),
    ('.NET Developer', '.net developer'),
    ('Android Developer', 'android developer'),
    ('iOS Developer', 'ios developer'),
    ('Flutter Developer', 'flutter developer'),
    ('Golang Developer', 'golang developer'),
    ('C++ Developer', 'c++ developer'),

    # —— QA / SRE / DevOps / Cloud ——
    ('QA Engineer', 'qa engineer'),
    ('Software Tester', 'software tester'),
    ('SDET', 'sdet'),
    ('Automation Test Engineer', 'automation test engineer'),
    ('DevOps Engineer', 'devops engineer'),
    ('Junior DevOps Engineer', 'junior devops'),
    ('Site Reliability Engineer', 'site reliability engineer'),
    ('Cloud Engineer', 'cloud engineer'),
    ('AWS Cloud Engineer', 'aws cloud engineer'),
    ('Azure Engineer', 'azure engineer'),
    ('Platform Engineer', 'platform engineer'),
    ('Kubernetes Engineer', 'kubernetes'),

    # —— Cybersecurity ——
    ('Cybersecurity Analyst', 'cybersecurity analyst'),
    ('Security Analyst', 'security analyst'),
    ('SOC Analyst', 'soc analyst'),
    ('Information Security Analyst', 'information security analyst'),
    ('Cyber Security Fresher', 'cyber security fresher'),
    ('Penetration Tester', 'penetration tester'),
    ('GRC Analyst', 'grc analyst'),

    # —— Product / Design / UX ——
    ('Product Manager', 'product manager'),
    ('Associate Product Manager', 'associate product manager'),
    ('Product Analyst', 'product analyst'),
    ('UI UX Designer', 'ui ux designer'),
    ('Product Designer', 'product designer'),
    ('UX Researcher', 'ux researcher'),
    ('Technical Product Manager', 'technical product manager'),

    # —— Support / IT / Ops fresher funnels ——
    ('Technical Support Engineer', 'technical support engineer'),
    ('IT Support', 'it support'),
    ('Desktop Support Engineer', 'desktop support engineer'),
    ('System Administrator', 'system administrator'),
    ('Network Engineer', 'network engineer'),
    ('Helpdesk Analyst', 'helpdesk analyst'),
    ('Application Support', 'application support'),

    # —— Business / consulting / finance adjacent (freshers) ——
    ('Management Trainee', 'management trainee'),
    ('Graduate Trainee', 'graduate trainee'),
    ('Analyst Trainee', 'analyst trainee'),
    ('Consultant', 'consultant fresher'),
    ('Associate Consultant', 'associate consultant'),
    ('Risk Analyst', 'risk analyst'),
    ('Compliance Analyst', 'compliance analyst'),
    ('Audit Associate', 'audit associate'),
    ('Financial Analyst', 'financial analyst'),
    ('Operations Analyst', 'operations analyst'),
    ('Process Associate', 'process associate'),
    ('HR Fresher', 'hr fresher'),
    ('Talent Acquisition', 'talent acquisition fresher'),
    ('Sales Development Representative', 'sales development representative'),
    ('Business Development Associate', 'business development associate'),
    ('Marketing Analyst', 'marketing analyst'),
    ('Digital Marketing Executive', 'digital marketing executive'),
    ('Content Writer', 'content writer'),
    ('Technical Writer', 'technical writer'),

    # —— Emerging / adjacent skill labels as searches ——
    ('RPA Developer', 'rpa developer'),
    ('Salesforce Developer', 'salesforce developer'),
    ('SAP Fresher', 'sap fresher'),
    ('Blockchain Developer', 'blockchain developer'),
    ('Game Developer', 'game developer'),
    ('Embedded Engineer', 'embedded engineer'),
    ('IoT Engineer', 'iot engineer'),
    ('Data Annotation', 'data annotation'),
    ('AI Trainer', 'ai trainer'),
    ('Internship Software', 'software intern'),
    ('Internship Data', 'data intern'),
    ('Campus Hire Software', 'campus hire software'),
]

# Default India geo used across the tower pilot
INDIA_GEO_ID = '102713980'
INDIA_LABEL = 'India'

# Past-24h searches: few pages usually cover the day; keep dwell human-scale.
DEFAULT_MAX_PAGES = 5
PRIORITY_MAX_PAGES = 10  # existing pilot / high-value roles
