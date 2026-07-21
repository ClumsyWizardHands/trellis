"""Conversation-key injectivity (Codex High 7): distinct tuples never collide.

A `__` inside a field must not masquerade as the delimiter — otherwise two
different conversations (a different thread vs a different scope) map to one key,
which is the user_id-only conflation that leaked private chief discussions."""

from trellis.surfaces import ConversationKey, Surface, ThreadRef


def test_delimiter_inside_a_field_does_not_collide():
    a = ConversationKey("ag", Surface.DM, "scope", "human", ThreadRef("thread__tail", "p"))
    b = ConversationKey("ag", Surface.DM, "scope__thread", "human", ThreadRef("tail", "p"))
    assert a.storage_key() != b.storage_key()          # the Codex collision, closed


def test_distinct_humans_get_distinct_keys():
    a = ConversationKey("ag", Surface.DM, "s", "alice")
    b = ConversationKey("ag", Surface.DM, "s", "bob")
    assert a.storage_key() != b.storage_key()


def test_same_tuple_is_stable():
    a = ConversationKey("ag", Surface.CHANNEL, "chiefs", "")
    b = ConversationKey("ag", Surface.CHANNEL, "chiefs", "")
    assert a.storage_key() == b.storage_key()          # deterministic


def test_key_is_filesystem_safe():
    import re
    k = ConversationKey("ag", Surface.DM, "a/b_c", "x%y", ThreadRef("t__z", "p")).storage_key()
    assert re.fullmatch(r"[A-Za-z0-9%._~-]+", k)       # only safe chars


def test_no_collision_across_many_shapes():
    seen = {}
    shapes = []
    for scope in ("s", "s_", "s__", "_s", "a__b"):
        for human in ("", "h", "h_"):
            for tid in (None, "t", "t__u", "_"):
                thread = ThreadRef(tid, "p") if tid else None
                shapes.append(ConversationKey("ag", Surface.DM, scope, human, thread))
    for k in shapes:
        key = k.storage_key()
        assert key not in seen or seen[key] == (k.scope, k.human, k.thread), \
            f"collision: {seen.get(key)} vs {(k.scope, k.human, k.thread)}"
        seen[key] = (k.scope, k.human, k.thread)
