# Opportunity Pre-screening & Approval Flow

This document defines the practical operating flow for using AI QA Factory before spending Connects, accepting work, or testing a real app.

## Goal

Factory must act as a pre-screening and execution cockpit, not only as a proposal generator.

For each pasted job, direct lead, platform task, brief, link description, or screenshot-derived text, Factory should answer:

1. Is this suitable for Dmytro?
2. Is this suitable for Factory execution, partial support, advisory only, or skip?
3. What can be done safely and realistically?
4. What is the rough timebox or first milestone?
5. What inputs/access are missing?
6. Which agents/workflow should run next?
7. Where does Dmytro need to approve before continuing?

## Standard flow

```bash
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --allow-mock
```

Then review:

- `READ_ME_FIRST.md`
- `PRESCREENING_REPORT.md`
- `DECISION.md`
- `NEXT_ACTIONS.md`
- `APPROVAL_CHECKPOINTS.md`
- `PROJECT_INTAKE_CHECKLIST.md`
- `TESTING_READINESS_CHECKLIST.md`
- `SELF_HEALTH_REPORT.md`

## Approval gates

Factory may draft, analyze, classify and prepare artifacts. Dmytro approves:

- spending Connects or replying;
- scope and first milestone;
- claims and evidence;
- real-site testing boundary;
- credential handling;
- final client-facing text;
- delivery artifacts.

## Decision vocabulary

- `strong_apply` — good fit, prepare proposal / screening answers.
- `apply_selectively` — possible, but with a narrow scope or stronger evidence.
- `advisory_only` — Factory can help analyze, but should not claim execution expertise.
- `skip_low_value` — low commercial value / low rate.
- `skip_risky` — identity, deposit, unauthorized testing, real payment, or policy risk.
- `skip_not_core` — developer-only or outside strategic positioning.
- `review_manually` — not enough information to decide.

## Human-friendly rule

The first useful output is not `state.json`. It is `READ_ME_FIRST.md`.
If that file does not clearly answer “what should I do next?”, the run should be treated as needing prompt/report tuning.
