#!/usr/bin/env python3
"""The Home Assistant app (homeassistant/): the files the Supervisor reads agree with each other, with VERSION and with run.py."""
import importlib.util
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "homeassistant"
CONFIG = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))


def load_run():
    spec = importlib.util.spec_from_file_location("addon_run", APP / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepositoryTest(unittest.TestCase):
    def test_the_repository_is_named(self):
        repo = yaml.safe_load((ROOT / "repository.yaml").read_text(encoding="utf-8"))
        self.assertTrue(repo["name"])

    def test_the_required_keys_are_there(self):
        for key in ("name", "version", "slug", "description", "arch"):
            self.assertTrue(CONFIG.get(key), key)
        self.assertRegex(CONFIG["slug"], r"^[A-Za-z0-9_.-]+$")
        self.assertIsInstance(CONFIG["version"], str)              # a number would turn 0.26.20 into something else

    def test_the_version_is_the_version_of_the_image_it_is_built_on(self):
        self.assertEqual(CONFIG["version"], (ROOT / "VERSION").read_text(encoding="utf-8").strip())

    def test_only_architectures_the_published_image_is_built_for(self):
        workflows = (ROOT / ".github" / "workflows" / "docker.yml").read_text(encoding="utf-8")
        if "platforms:" in workflows:                               # the image is amd64 only until the workflows say otherwise
            self.assertNotEqual(CONFIG["arch"], ["amd64"], "docker.yml builds more platforms: offer them in arch")
        else:
            self.assertEqual(CONFIG["arch"], ["amd64"])

    def test_the_app_is_stopped_for_a_backup_because_the_database_runs_inside_it(self):
        self.assertEqual(CONFIG["backup"], "cold")

    def test_the_icons_exist(self):
        for name in ("icon.png", "logo.png"):
            self.assertTrue((APP / name).read_bytes().startswith(b"\x89PNG"), name)


class OptionsTest(unittest.TestCase):
    def test_every_default_is_an_option_and_every_option_has_a_default_or_is_optional(self):
        for name in CONFIG["options"]:
            self.assertIn(name, CONFIG["schema"])
        for name, kind in CONFIG["schema"].items():
            self.assertTrue(name in CONFIG["options"] or str(kind).endswith("?"), name)

    def test_run_py_reads_every_option(self):
        source = (APP / "run.py").read_text(encoding="utf-8")
        for name in CONFIG["schema"]:
            self.assertRegex(source, rf'options(\.get\(|\[)"{name}"', name)

    def test_both_languages_describe_every_option_and_the_port(self):
        for language in ("en", "nl"):
            texts = yaml.safe_load((APP / "translations" / f"{language}.yaml").read_text(encoding="utf-8"))
            for name in CONFIG["schema"]:
                self.assertTrue(texts["configuration"][name]["name"] and texts["configuration"][name]["description"], f"{language}: {name}")
            for port in CONFIG["ports"]:
                self.assertTrue(texts["network"][port], f"{language}: {port}")

    def test_the_port_is_the_one_the_image_listens_on(self):
        self.assertEqual(list(CONFIG["ports"]), ["6080/tcp"])
        self.assertIn("WEB_PORT=6080", (ROOT / "Dockerfile").read_text(encoding="utf-8"))
        self.assertIn("[PORT:6080]/healthz", CONFIG["watchdog"])

    def test_the_options_are_the_variables_of_the_env_example(self):
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        run = load_run()
        with tempfile.TemporaryDirectory() as tmp:
            run.DATA, run.SECRETS = Path(tmp), Path(tmp) / "secrets.json"
            kept = {"postgres_password": "p", "session_secret": "s" * 64, "setup_code": "c", "vapid_public_key": "a", "vapid_private_key": "b"}
            for name in run.settings({"rp_id": "print.example.com"}, kept):
                if name not in ("DATABASE_URL", "DATA_PATH"):
                    self.assertRegex(env, rf"(?m)^#?\s*{name}=", name)


class DockerfileTest(unittest.TestCase):
    text = (APP / "Dockerfile").read_text(encoding="utf-8")

    def test_it_is_built_on_the_image_of_its_own_version(self):
        self.assertRegex(self.text, r"(?m)^FROM ghcr\.io/flux76hq/3dprint_pricing:\$\{BUILD_VERSION\}$")

    def test_it_asks_for_the_postgresql_the_compose_file_runs(self):
        self.assertIn("postgres:17", (ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        self.assertIn("postgresql-17", self.text)

    def test_it_starts_run_py_and_not_the_entrypoint_directly(self):
        self.assertIn("COPY run.py /run.py", self.text)
        self.assertIn('CMD ["python", "/run.py"]', self.text)


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_py = load_run()
        quiet = contextlib.ExitStack()
        quiet.enter_context(contextlib.redirect_stdout(io.StringIO()))
        quiet.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.addCleanup(quiet.close)
        self.run_py.DATA = Path(self.tmp.name)
        self.run_py.SECRETS = Path(self.tmp.name) / "secrets.json"
        self.kept = {"postgres_password": "pw", "session_secret": "s" * 64, "setup_code": "gen", "vapid_public_key": "pub", "vapid_private_key": "priv"}

    def test_the_origin_is_https_and_the_domain_unless_it_is_given(self):
        env = self.run_py.settings({"rp_id": "Print.Example.com"}, self.kept)
        self.assertEqual((env["RP_ID"], env["RP_ORIGINS"]), ("print.example.com", "https://print.example.com"))
        env = self.run_py.settings({"rp_id": "print.example.com", "rp_origins": "https://a.nl, https://b.nl"}, self.kept)
        self.assertEqual(env["RP_ORIGINS"], "https://a.nl, https://b.nl")

    def test_no_domain_is_fine_the_app_then_follows_the_address_it_is_opened_on(self):
        for options in ({}, {"rp_id": ""}, {"rp_id": "  "}):
            env = self.run_py.settings(options, self.kept)
            self.assertEqual((env["RP_ID"], env["RP_ORIGINS"]), ("", ""), str(options))
        env = self.run_py.settings({"rp_origins": "http://192.168.1.20:6080"}, self.kept)
        self.assertEqual((env["RP_ID"], env["RP_ORIGINS"]), ("", "http://192.168.1.20:6080"))

    def test_a_domain_with_a_scheme_or_port_stops_the_start(self):
        for bad in ({"rp_id": "https://print.example.com"}, {"rp_id": "print.example.com:6080"}, {"rp_id": "a/b"}):
            with self.assertRaises(SystemExit, msg=str(bad)):
                self.run_py.settings(bad, self.kept)

    def test_the_setup_code_option_wins_over_the_generated_one(self):
        self.assertEqual(self.run_py.settings({"rp_id": "x.nl"}, self.kept)["SETUP_CODE"], "gen")
        self.assertEqual(self.run_py.settings({"rp_id": "x.nl", "setup_code": "mine"}, self.kept)["SETUP_CODE"], "mine")

    def test_switches_become_the_values_the_app_reads(self):
        env = self.run_py.settings({"rp_id": "x.nl", "ai_images_enabled": True, "update_check": False, "proxy_hops": 1, "max_upload_mb": 80}, self.kept)
        self.assertEqual((env["AI_IMAGES_ENABLED"], env["PRINTPRICING_UPDATE_CHECK"], env["PROXY_HOPS"], env["MAX_UPLOAD_MB"]), ("TRUE", "false", "1", "80"))
        env = self.run_py.settings({"rp_id": "x.nl"}, self.kept)
        self.assertEqual((env["AI_IMAGES_ENABLED"], env["PRINTPRICING_UPDATE_CHECK"]), ("FALSE", "true"))

    def test_the_database_login_is_the_kept_password_on_the_loopback(self):
        self.assertEqual(self.run_py.settings({"rp_id": "x.nl"}, self.kept)["DATABASE_URL"], "postgresql://printpricing:pw@127.0.0.1:5432/printpricing")

    def test_the_secrets_are_made_once_kept_private_and_reused(self):
        with mock.patch.dict(os.environ, {"VAPID_DIR": str(ROOT / "scripts")}):
            first = self.run_py.kept_secrets({"setup_code": "typed"})
            second = self.run_py.kept_secrets({})
        self.assertEqual(first, second)
        self.assertEqual(oct(self.run_py.SECRETS.stat().st_mode & 0o777), "0o600")
        self.assertGreaterEqual(len(first["session_secret"]), 32)
        self.assertEqual(json.loads(self.run_py.SECRETS.read_text())["postgres_password"], first["postgres_password"])
        self.assertTrue(re.fullmatch(r"[0-9a-f]{32}", first["postgres_password"]))      # hex: it is written into a statement without quoting


if __name__ == "__main__":
    unittest.main()
