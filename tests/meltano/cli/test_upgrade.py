from __future__ import annotations

import json
import platform
import shutil
import typing as t

import boto3
import mock
import pytest
from moto import mock_s3

import meltano
from asserts import assert_cli_runner
from meltano.cli import cli

if t.TYPE_CHECKING:
    from click.testing import CliRunner


class TestCliUpgrade:
    @pytest.mark.usefixtures("project")
    def test_upgrade(self, cli_runner: CliRunner):
        if platform.system() == "Windows":
            pytest.xfail(
                "Fails on Windows: https://github.com/meltano/meltano/issues/3444",
            )
        # If an editable install was used, test that it cannot be upgraded automatically
        if meltano.__file__.endswith("/src/meltano/__init__.py"):
            result = cli_runner.invoke(cli, ["upgrade"])
            assert_cli_runner(result)

            assert (
                "The `meltano` package could not be upgraded automatically"
                in result.stdout
            )
            assert "run `meltano upgrade --skip-package`" in result.stdout

        with mock.patch(
            "meltano.cli.upgrade.UpgradeService._upgrade_package",
        ) as upgrade_package_mock:
            upgrade_package_mock.return_value = True

            result = cli_runner.invoke(cli, ["upgrade"])
            assert_cli_runner(result)

            assert (
                "Meltano and your Meltano project have been upgraded!" in result.stdout
            )

    @pytest.mark.usefixtures("project")
    def test_upgrade_skip_package(self, cli_runner: CliRunner):
        result = cli_runner.invoke(cli, ["upgrade", "--skip-package"])
        assert_cli_runner(result)

        assert "Your Meltano project has been upgraded!" in result.stdout

    @pytest.mark.usefixtures("project")
    def test_upgrade_package(self, cli_runner: CliRunner):
        if platform.system() == "Windows":
            pytest.xfail(
                "Fails on Windows: https://github.com/meltano/meltano/issues/3444",
            )
        # If an editable install was used, test that it cannot be upgraded automatically
        if meltano.__file__.endswith("/src/meltano/__init__.py"):
            result = cli_runner.invoke(cli, ["upgrade", "package"])
            assert_cli_runner(result)

            assert (
                "The `meltano` package could not be upgraded automatically"
                in result.stdout
            )
            assert "run `meltano upgrade --skip-package`" not in result.stdout

    @pytest.mark.order(before="test_upgrade_files_glob_path")
    @pytest.mark.usefixtures("session")
    def test_upgrade_files(self, project, cli_runner: CliRunner):
        if platform.system() == "Windows":
            pytest.xfail(
                "Fails on Windows: https://github.com/meltano/meltano/issues/3444",
            )
        result = cli_runner.invoke(cli, ["upgrade", "files"])
        output = result.stdout + result.stderr
        assert_cli_runner(result)

        assert "Nothing to update" in result.stdout

        result = cli_runner.invoke(cli, ["add", "files", "airflow"])
        output = result.stdout + result.stderr
        assert_cli_runner(result)

        # Don't update file if unchanged
        file_path = project.root_dir("orchestrate/dags/meltano.py")
        file_content = file_path.read_text()

        result = cli_runner.invoke(cli, ["upgrade", "files"])
        output = result.stdout + result.stderr
        assert_cli_runner(result)

        assert "Updating 'airflow' files in project..." in output
        assert "Nothing to update" in output
        assert file_path.read_text() == file_content

        # Update file if changed
        file_path.write_text("Overwritten!")

        # The behavior being tested assumes that the file is not locked.
        shutil.rmtree(project.root_dir("plugins/files"), ignore_errors=True)
        result = cli_runner.invoke(cli, ["upgrade", "files"])
        output = result.stdout + result.stderr
        assert_cli_runner(result)

        assert "Updated orchestrate/dags/meltano.py" in output
        assert file_path.read_text() == file_content

        # Don't update file if unchanged
        result = cli_runner.invoke(cli, ["upgrade", "files"])
        output = result.stdout + result.stderr
        assert_cli_runner(result)

        assert "Nothing to update" in output
        assert file_path.read_text() == file_content

        # Don't update file if automatic updating is
        result = cli_runner.invoke(
            cli,
            [
                "config",
                "--plugin-type",
                "files",
                "airflow",
                "set",
                "_update",
                "orchestrate/dags/meltano.py",
                "false",
            ],
        )
        output = result.stdout + result.stderr
        assert_cli_runner(result)

        file_path.write_text("Overwritten!")

        cli_runner.invoke(cli, ("lock", "airflow"))
        result = cli_runner.invoke(cli, ["upgrade", "files"])
        output = result.stdout + result.stderr
        assert_cli_runner(result)

        assert "Nothing to update" in output
        assert file_path.read_text() != file_content

        # Update file if automatic updating is re-enabled
        result = cli_runner.invoke(
            cli,
            [
                "config",
                "--plugin-type",
                "files",
                "airflow",
                "unset",
                "_update",
                "orchestrate/dags/meltano.py",
            ],
        )
        output = result.stdout + result.stderr
        assert_cli_runner(result)

        result = cli_runner.invoke(cli, ["upgrade", "files"])
        output = result.stdout + result.stderr
        assert_cli_runner(result)
        assert "Updated orchestrate/dags/meltano.py" in output

    @pytest.mark.usefixtures("session")
    def test_upgrade_files_glob_path(self, project, cli_runner: CliRunner):
        if platform.system() == "Windows":
            pytest.xfail(
                "Fails on Windows: https://github.com/meltano/meltano/issues/3444",
            )

        result = cli_runner.invoke(cli, ["add", "files", "airflow"])
        assert_cli_runner(result)

        file_path = project.root_dir("orchestrate/dags/meltano.py")
        file_path.write_text("Overwritten!")

        # override airflow--meltano.lock update extra config
        result = cli_runner.invoke(
            cli,
            [
                "config",
                "--plugin-type",
                "files",
                "airflow",
                "set",
                "_update",
                json.dumps(
                    {
                        "orchestrate/dags/meltano.py": False,
                        "*.py": True,
                    },
                ),
            ],
        )
        assert_cli_runner(result)

        result = cli_runner.invoke(cli, ["upgrade", "files"])
        output = result.stdout + result.stderr
        assert_cli_runner(result)
        assert "Updated orchestrate/dags/meltano.py" in output

    @pytest.mark.usefixtures("project")
    def test_upgrade_database(self, cli_runner: CliRunner):
        result = cli_runner.invoke(cli, ["upgrade", "database"])
        assert_cli_runner(result)

    @mock_s3
    @pytest.mark.usefixtures("project")
    def test_upgrade_state(self, cli_runner, monkeypatch):
        state_ids = [f"dev:tap-{i}-to-target-{i}" for i in range(10)]
        conn = boto3.resource("s3", region_name="us-east-1")
        bucket = conn.create_bucket(Bucket="test-state-bucket")
        for state_id in state_ids:
            bucket.put_object(
                Key=f"some/trailing/delim/path/some/trailing/delim/path/{state_id}/state.json",  # noqa: E501
            )
        monkeypatch.setenv(
            "MELTANO_STATE_BACKEND_URI",
            "s3://test-state-bucket/some/trailing/delim/path/",
        )
        result = cli_runner.invoke(cli, ["upgrade", "--skip-package"])
        assert_cli_runner(result)
        keys = [s3_object.key for s3_object in bucket.objects.all()]
        for state_id in state_ids:
            key = f"/some/trailing/delim/path/{state_id}/state.json"
            assert key in keys
