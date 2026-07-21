"""Direct Collaboration Driver v1 (GitHub Issue #14).

A bounded, owner-visible system that removes manual Claude<->GPT copy/paste: SHA-bound collaboration
envelopes over the existing review-relay store, an autonomous OpenAI-backed reviewer driver, safe
delivery into one bound local Claude session, and a Dashboard monitor. It is enabling infrastructure
for product completion, not a general multi-agent platform: it can never merge, write source, run
arbitrary shell, or send externally.
"""
