import importlib


def test_database_url_configures_mysql_connection(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://dex_user:secret%20pass@example.com:3307/dex_db")
    monkeypatch.delenv("DEX_DB_ENABLED", raising=False)
    monkeypatch.delenv("DEX_DB_HOST", raising=False)
    monkeypatch.delenv("DEX_DB_USER", raising=False)
    monkeypatch.delenv("DEX_DB_PASSWORD", raising=False)
    monkeypatch.delenv("DEX_DB_NAME", raising=False)

    import dexweb.config as config

    importlib.reload(config)

    assert config.DexwebConfig.DB_ENABLED is True
    assert config.DexwebConfig.DB_HOST == "example.com"
    assert config.DexwebConfig.DB_PORT == 3307
    assert config.DexwebConfig.DB_USER == "dex_user"
    assert config.DexwebConfig.DB_PASSWORD == "secret pass"
    assert config.DexwebConfig.DB_NAME == "dex_db"
