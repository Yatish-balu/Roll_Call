def test_basic_math():
    """Simple smoke test to verify pytest execution."""
    assert 1 + 1 == 2


def test_import_app():
    """Verify app package can be imported."""
    from app.main import app
    assert app.title == "RollCall AI"
