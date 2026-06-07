from typer.testing import CliRunner

from patchpilot.cli import app


def test_run_cli_rejects_fake_provider_as_product_demo() -> None:
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--repo",
            "fixtures/buggy-python-repo",
            "--goal",
            "repair failing pytest",
            "--model-provider",
            "fake",
            "--model-profile",
            "minimax",
            "--allow-write",
            "--allow-exec",
        ],
    )

    assert result.exit_code != 0
    assert "fake" in result.output


def test_eval_cli_accepts_quiet_flag_for_machine_readable_runs() -> None:
    result = CliRunner().invoke(
        app,
        [
            "eval",
            "--suite",
            "v2",
            "--repo",
            "fixtures/multifile-parser-validator",
            "--model-provider",
            "openrouter",
            "--quiet",
        ],
    )

    assert result.exit_code == 0, result.output
