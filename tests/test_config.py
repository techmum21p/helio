import config


def test_geo_weights_sum_to_one():
    assert abs(sum(config.WEIGHTS.values()) - 1.0) < 1e-9


def test_income_weight_is_dominant():
    assert config.WEIGHTS["income"] == 0.45


def test_solar_weight_revised():
    assert config.WEIGHTS["solar"] == 0.35


def test_population_weight_revised():
    assert config.WEIGHTS["population"] == 0.20


def test_final_weights_sum_to_one():
    assert abs(config.FINAL_GEO_WEIGHT + config.FINAL_WEB_WEIGHT - 1.0) < 1e-9


def test_final_web_weight_raised():
    assert config.FINAL_WEB_WEIGHT == 0.30


def test_helio_db_path_defined():
    assert config.HELIO_DB.name == "helio.db"
    assert config.HELIO_DB.parent.name == "data"


def test_ollama_defaults():
    assert config.OLLAMA_EMBED_MODEL == "qwen3-embedding:0.6b"
    assert "11434" in config.OLLAMA_URL
