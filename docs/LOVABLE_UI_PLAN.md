# Future Lovable Web UI Plan

Do not build this before the CLI proves useful.

A web UI can be useful later for:

- Pasting client briefs
- Selecting mode: job/audit/plan/scaffold/review/delivery
- Viewing generated outputs
- Approving outputs
- Tracking projects and clients

Recommended architecture:

- Backend: Python AI QA Factory as API service
- Frontend: React/TypeScript UI generated in Lovable or built manually
- Storage: Supabase or lightweight database
- Code execution: never directly from the browser; run only in controlled backend environment

Phase gate: build UI after 10-20 real CLI runs.
