"""v3.3 — operator attention/notification policy: notify only when needed, deduped, off by default."""
from __future__ import annotations

from core.scout.attention import (
    LEVEL_ACTIONABLE,
    LEVEL_DIGEST,
    LEVEL_IMMEDIATE,
    LEVEL_NONE,
    AttentionCenter,
    NotificationSettings,
    classify_event,
    should_notify,
)


def test_event_level_classification():
    assert classify_event("public_captcha") == LEVEL_NONE
    assert classify_event("duplicate_target") == LEVEL_NONE
    assert classify_event("campaign_completed") == LEVEL_DIGEST
    assert classify_event("campaign_stopped_checkpoint") == LEVEL_ACTIONABLE
    assert classify_event("human_checkpoint") == LEVEL_IMMEDIATE
    assert classify_event("something_unknown") == LEVEL_NONE     # unknown never interrupts


def test_dedup_does_not_create_duplicate_items():
    c = AttentionCenter()
    a = c.record(event_type="human_checkpoint", campaign_id="c1", target="a.com", reason="captcha")
    b = c.record(event_type="human_checkpoint", campaign_id="c1", target="a.com", reason="captcha2")
    assert a.id == b.id                                          # same dedup key => one item
    assert len(c.open_items(min_level=LEVEL_DIGEST)) == 1


def test_open_items_filtered_by_level_and_sorted():
    c = AttentionCenter()
    c.record(event_type="public_captcha", campaign_id="c1", target="x")     # level 0
    c.record(event_type="campaign_completed", campaign_id="c1")             # level 1
    c.record(event_type="global_safety_blocker", campaign_id="c1")         # level 3
    items = c.open_items(min_level=LEVEL_DIGEST)
    assert all(i.level >= LEVEL_DIGEST for i in items)           # level-0 excluded
    assert items[0].level == LEVEL_IMMEDIATE                     # highest first


def test_notifications_off_by_default():
    c = AttentionCenter()
    item = c.record(event_type="human_checkpoint", campaign_id="c1")
    assert should_notify(item, NotificationSettings(), now_epoch=1000.0) is False   # disabled


def test_level0_never_notifies_even_when_enabled():
    c = AttentionCenter()
    item = c.record(event_type="public_captcha", campaign_id="c1", target="x")
    s = NotificationSettings(enabled=True, min_level=0)
    assert should_notify(item, s, now_epoch=1000.0) is False


def test_enabled_notifies_above_min_level_with_cooldown():
    c = AttentionCenter()
    item = c.record(event_type="campaign_stopped_checkpoint", campaign_id="c1")   # level 2
    s = NotificationSettings(enabled=True, min_level=LEVEL_ACTIONABLE, cooldown_s=900.0)
    assert should_notify(item, s, now_epoch=1000.0, last_notified_epoch=None) is True
    # within cooldown => suppressed (no spam)
    assert should_notify(item, s, now_epoch=1100.0, last_notified_epoch=1000.0) is False
    # after cooldown => allowed again
    assert should_notify(item, s, now_epoch=2000.0, last_notified_epoch=1000.0) is True


def test_digest_level_below_min_does_not_notify():
    c = AttentionCenter()
    item = c.record(event_type="campaign_completed", campaign_id="c1")            # level 1
    s = NotificationSettings(enabled=True, min_level=LEVEL_ACTIONABLE)            # min 2
    assert should_notify(item, s, now_epoch=1000.0) is False
