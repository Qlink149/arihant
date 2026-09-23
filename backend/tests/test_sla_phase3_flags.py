from crm.services.sla_feature_flags import phase2_rules_enabled, phase3_rules_enabled


def test_phase3_flag_defaults_false(monkeypatch):
    monkeypatch.delenv("SLA_PHASE3_RULES_ENABLED", raising=False)
    assert phase3_rules_enabled() is False


def test_phase3_flag_true(monkeypatch):
    monkeypatch.setenv("SLA_PHASE3_RULES_ENABLED", "true")
    assert phase3_rules_enabled() is True


def test_phase2_flag_defaults_true(monkeypatch):
    monkeypatch.delenv("SLA_PHASE2_RULES_ENABLED", raising=False)
    assert phase2_rules_enabled() is True


def test_phase2_flag_can_disable(monkeypatch):
    monkeypatch.setenv("SLA_PHASE2_RULES_ENABLED", "false")
    assert phase2_rules_enabled() is False
