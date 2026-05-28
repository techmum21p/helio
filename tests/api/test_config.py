import config

def test_helio_db_path_defined():
    assert hasattr(config, "HELIO_DB")
    assert str(config.HELIO_DB).endswith("helio.db")

def test_weights_v2():
    assert config.WEIGHTS["solar"] == 0.35
    assert config.WEIGHTS["income"] == 0.45
    assert config.WEIGHTS["pop_density"] == 0.20
    assert abs(sum(config.WEIGHTS.values()) - 1.0) < 1e-9

def test_weights_no_population_key():
    assert "population" not in config.WEIGHTS
