# Weather Progress

current_stage: maintenance
current_chapter: physical Qt acceptance
state: maintenance
next_action: During relevant UI work, complete physical Pi checks for every debug scene, swipe, narration, refresh, and cleanup path.
last_verified: 2026-08-28

## Current state

Production Weather is QML-native and starts no Chromium or loopback bridge.
The legacy Tk renderer remains for one validation cycle. Provider behavior and
Qt models have automated coverage; full physical scene/performance acceptance
remains an operator check, not a code blocker.
