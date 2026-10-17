"""A partner's database user can read everyone's memory and its own key, and nothing else."""

from __future__ import annotations

import pytest

from codebook import acl, keys
from codebook.db import Db, NoPermission
from codebook.memory import Memory

pytestmark = pytest.mark.contract


def test_partner_user_is_locked_to_its_own_key(population, test_settings):
    memory = Memory(population)
    memory.ensure_partner("acltest")
    memory.ensure_partner("acl-other")
    user, password = acl.grant(population, "acltest")
    try:
        mine = Db(test_settings, username=user, password=password)
        assert mine.ro_query(keys.POPULATION, "MATCH (w:Word) RETURN count(w)").scalar() > 0
        assert mine.query(keys.partner_key("acltest"), "MATCH (p:Partner) SET p.touched = true RETURN 1").scalar() == 1
        with pytest.raises(NoPermission):
            mine.query(keys.POPULATION, "CREATE (:Word {text: 'intruder'})")
        with pytest.raises(NoPermission):
            mine.ro_query(keys.partner_key("acl-other"), "MATCH (n) RETURN count(n)")
        with pytest.raises(NoPermission):
            mine.graph_keys()
    finally:
        acl.revoke(population, "acltest")
