from __future__ import annotations

from app.envfile import update_env_file


def test_update_env_file_replaces_and_appends_without_touching_the_rest(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text("# keys\nMODE=real\nEBAY_SB_REFRESH_TOKEN=\nexport OTHER=1\n")
    update_env_file(env, {"EBAY_SB_REFRESH_TOKEN": "v^1.1#abc", "EBAY_SB_PAYMENT_POLICY_ID": "p1"})
    assert env.read_text() == (
        "# keys\nMODE=real\nEBAY_SB_REFRESH_TOKEN=v^1.1#abc\nexport OTHER=1\n"
        "EBAY_SB_PAYMENT_POLICY_ID=p1\n"
    )


def test_update_env_file_creates_a_missing_file(tmp_path) -> None:
    env = tmp_path / "missing.env"
    update_env_file(env, {"A": "1"})
    assert env.read_text() == "A=1\n"
