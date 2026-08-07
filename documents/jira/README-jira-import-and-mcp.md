# Jira pages — SIPROG (epics) & SIMET (tasks/bugs)

CSV "pages" for Jira, written so they import cleanly later and stay readable
in git meanwhile. One epic per feature; tasks/bugs link via `Epic Link`.

- `page-1-siprog-epic.csv` — epics (currently: **Job Alerts 🔔**, Sprint 1.1)
- `page-2-simet-tasks.csv` — tasks + preventive bugs for that epic

## Import into Jira (when we create the site)

Jira → Settings → System → External System Import → CSV. Map columns:
Issue Type, Summary, Description, Priority, Epic Name / Epic Link, Labels.
`T-Shirt Size`, `Acceptance Criteria`, `Definition of Done`, `Smart
Checklist` map to custom fields (create them once, reuse forever).

## Connect Cursor to Jira via MCP (confirmed, official)

Atlassian ships an official **Rovo MCP Server** that works with Cursor —
search/create/update Jira epics and issues straight from chat.

1. Needs an Atlassian Cloud site (free tier is fine to start).
2. Cursor → MCP settings → add:
   `"Atlassian-MCP-Server": { "url": "https://mcp.atlassian.com/v1/mcp/authv2" }`
   (or install from the Cursor marketplace: cursor.com/marketplace/atlassian)
3. Restart, sign in via the OAuth browser flow — done. Akay can then push
   these CSVs into the real board and manage sprints through chat.

Until the Jira site exists, these CSVs are the board of record alongside
`documents/kanban.md` (the product backlog).
