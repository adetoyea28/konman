import json
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from ruamel.yaml import YAML

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from click.testing import CliRunner
from konman import cli
from konman.config import (
    clear_global_api_credentials,
    inject_antigravity_hooks,
    inject_claude_code_adapters,
    inject_codex_adapters,
    inject_cursor_adapters,
    inject_kiro_adapters,
    inject_vsc_copilot_adapters,
    load_global_api_credentials,
    migrate_legacy_credentials,
    save_global_api_credentials,
)
from konman.engine import ContextEngine
from konman.context_graph import ContextDataError, ConcurrentEditError, ContextWorkspace, build_graph
from konman.transcripts import parse_record


class CommandFixTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.runner = CliRunner()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_extract_saves_only_grounded_proposed_nodes(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        (engine.ctx_dir / ".raw" / "hook.json").write_text(
            json.dumps({
                "hook_event_name": "UserPromptSubmit",
                "prompt": "Keep the API backward compatible.",
                "assistant_response": "Always use a graph database.",
            }),
            encoding="utf-8",
        )
        response = json.dumps({
            "requirements": [
                {"statement": "Keep the API backward compatible", "kind": "hard", "evidence": "Keep the API backward compatible."},
                {"statement": "Invented requirement", "kind": "hard", "evidence": "not in the source"},
                {"statement": "Assistant suggestion is a requirement", "kind": "hard", "evidence": "Always use a graph database."},
            ],
            "decisions": [],
        })
        with patch.object(ContextEngine, "execute_llm_distillation", return_value=response):
            result = self.runner.invoke(cli.main, ["extract", "--api-key", "test-key", "--dir", str(self.root)])
        self.assertEqual(result.exit_code, 0, result.output)
        node = (engine.ctx_dir / "requirements" / "R-001.yaml").read_text(encoding="utf-8")
        self.assertIn("status: proposed", node)
        requirement = YAML().load(node)
        self.assertEqual(len(requirement["evidence_ids"]), 1)
        evidence_path = engine.ctx_dir / "evidence" / f"{requirement['evidence_ids'][0]}.yaml"
        self.assertTrue(evidence_path.is_file())
        self.assertFalse((engine.ctx_dir / "requirements" / "R-002.yaml").exists())

    def test_extract_can_select_boundary_nodes_only(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        (engine.ctx_dir / ".raw" / "hook.json").write_text(
            json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "Do not edit src/auth.py without approval."}),
            encoding="utf-8",
        )
        response = json.dumps({
            "requirements": [{"statement": "An ignored requirement", "kind": "hard", "evidence": "Do not edit src/auth.py without approval."}],
            "decisions": [{"chosen": "An ignored decision", "mode": "forced", "evidence": "Do not edit src/auth.py without approval."}],
            "boundaries": [{
                "path": "src/auth.py",
                "rule": "no_edit_without_approval",
                "why": "Authentication changes require review.",
                "evidence": "Do not edit src/auth.py without approval.",
            }],
        })
        with patch.object(ContextEngine, "execute_llm_distillation", return_value=response) as extract:
            result = self.runner.invoke(
                cli.main,
                ["extract", "--api-key", "test-key", "--type", "boundary", "--dir", str(self.root)],
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(extract.call_args.kwargs["node_types"], ("boundary",))
        boundaries = YAML().load((engine.ctx_dir / "boundaries.yaml").read_text(encoding="utf-8"))
        self.assertEqual(len(boundaries), 1)
        self.assertEqual(boundaries[0]["id"], "B-001")
        self.assertEqual(boundaries[0]["path"], "src/auth.py")
        self.assertEqual(boundaries[0]["status"], "proposed")
        self.assertFalse(list((engine.ctx_dir / "requirements").glob("R-*.yaml")))
        self.assertFalse(list((engine.ctx_dir / "decisions").glob("D-*.yaml")))

    def test_extract_supports_all_context_node_types_with_evidence_links(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        quote = "Keep existing sessions compatible."
        (engine.ctx_dir / ".raw" / "hook.json").write_text(
            json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": quote}),
            encoding="utf-8",
        )
        response = json.dumps({
            "requirements": [{"statement": "Preserve session compatibility", "kind": "hard", "evidence": quote}],
            "decisions": [{"chosen": "Session token", "mode": "default", "reason": "Stable identifiers.", "evidence": quote}],
            "boundaries": [{"path": "src/session.py", "rule": "no_edit_without_approval", "evidence": quote}],
            "evidence": [{"source_type": "transcript", "excerpt": quote}],
            "changes": [{"summary": "Keep session parsing compatible", "files": "src/session.py", "evidence": quote}],
            "questions": [{"question": "Which legacy formats are required?", "evidence": quote}],
            "risks": [{"statement": "Legacy sessions could fail to load.", "likelihood": "medium", "impact": "high", "evidence": quote}],
            "objects": [{"name": "Session token", "kind": "identifier", "description": "Stable session identifier.", "evidence": quote}],
        })
        with patch.object(ContextEngine, "execute_llm_distillation", return_value=response):
            result = self.runner.invoke(
                cli.main, ["extract", "--api-key", "test-key", "--dir", str(self.root)]
            )
        self.assertEqual(result.exit_code, 0, result.output)
        expected_files = {
            "requirements": "R-001.yaml",
            "decisions": "D-001.yaml",
            "evidence": "E-001.yaml",
            "changes": "C-001.yaml",
            "questions": "Q-001.yaml",
            "risks": "X-001.yaml",
            "objects": "O-001.yaml",
        }
        for folder, filename in expected_files.items():
            self.assertTrue((engine.ctx_dir / folder / filename).is_file(), folder)
        boundaries = YAML().load((engine.ctx_dir / "boundaries.yaml").read_text(encoding="utf-8"))
        self.assertEqual(boundaries[0]["id"], "B-001")
        self.assertEqual(YAML().load((engine.ctx_dir / "requirements" / "R-001.yaml").read_text())["evidence_ids"], ["E-001"])
        change = YAML().load((engine.ctx_dir / "changes" / "C-001.yaml").read_text())
        self.assertEqual(change["files"], ["src/session.py"])
        self.assertEqual(engine.check_graph_validity(), [])

    def test_extract_can_process_another_type_from_a_completed_capture(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        (engine.ctx_dir / ".raw" / "hook.json").write_text(
            json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "Do not edit src/auth.py without approval."}),
            encoding="utf-8",
        )
        response = json.dumps({
            "requirements": [{
                "statement": "Protect authentication changes",
                "kind": "hard",
                "evidence": "Do not edit src/auth.py without approval.",
            }],
            "boundaries": [{
                "path": "src/auth.py",
                "evidence": "Do not edit src/auth.py without approval.",
            }],
        })
        with patch.object(ContextEngine, "execute_llm_distillation", return_value=response) as extract:
            first = self.runner.invoke(
                cli.main,
                ["extract", "--api-key", "test-key", "--type", "requirement", "--dir", str(self.root)],
            )
            second = self.runner.invoke(
                cli.main,
                ["extract", "--api-key", "test-key", "--type", "boundary", "--dir", str(self.root)],
            )
        self.assertEqual(first.exit_code, 0, first.output)
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertEqual(extract.call_count, 2)
        self.assertEqual(extract.call_args.kwargs["node_types"], ("boundary",))
        self.assertTrue((engine.ctx_dir / "requirements" / "R-001.yaml").exists())
        self.assertTrue((engine.ctx_dir / "boundaries.yaml").exists())

    def test_extract_redacts_secrets_before_provider_request(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        (engine.ctx_dir / ".raw" / "hook.json").write_text(json.dumps({
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Do not use token sk-proj-123456789012345678901234567890123456",
            "password": "sensitive-password-value",
        }), encoding="utf-8")
        with patch.object(ContextEngine, "execute_llm_distillation", return_value='{"requirements": [], "decisions": []}') as request:
            result = self.runner.invoke(cli.main, ["extract", "--api-key", "test-key", "--dir", str(self.root)])
        self.assertEqual(result.exit_code, 0, result.output)
        provider_input = request.call_args.args[0]
        self.assertNotIn("123456789012345678901234567890123456", provider_input)
        self.assertNotIn("sensitive-password-value", provider_input)
        self.assertIn("[REDACTED]", provider_input)

    def test_extraction_failure_remains_retryable_and_records_attempts(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        capture = engine.ctx_dir / ".raw" / "hook.json"
        capture.write_text(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "Keep the API stable"}), encoding="utf-8")
        response = json.dumps({"requirements": [], "decisions": []})
        with patch.object(ContextEngine, "execute_llm_distillation", side_effect=['{"error":"temporary provider failure"}', response]) as call:
            first = self.runner.invoke(cli.main, ["extract", "--api-key", "test-key", "--dir", str(self.root)])
            self.assertNotEqual(first.exit_code, 0)
            state_path = next((engine.ctx_dir / ".raw" / ".processed").glob("*.json"))
            failed_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(next(iter(failed_state["chunks"].values()))["status"], "failed")

            second = self.runner.invoke(cli.main, ["extract", "--api-key", "test-key", "--dir", str(self.root)])
        self.assertEqual(second.exit_code, 0, second.output)
        final_state = json.loads(state_path.read_text(encoding="utf-8"))
        chunk = next(iter(final_state["chunks"].values()))
        self.assertEqual(chunk["status"], "processed")
        self.assertEqual(chunk["attempts"], 2)
        self.assertEqual(call.call_count, 2)

    def test_capture_chunks_only_accept_human_evidence_from_same_chunk(self):
        first = json.dumps({"role": "user", "content": "User requirement phrase."})
        second = json.dumps({"role": "assistant", "content": "Assistant-only phrase."})
        chunks = cli._split_capture(first + "\n" + second, max_chars=max(len(first), len(second)) + 1)
        self.assertEqual(len(chunks), 2)
        self.assertIn("User requirement phrase.", chunks[0][2])
        self.assertEqual(chunks[1][2], "")
        self.assertEqual(chunks[1][0], len((first + "\n").encode("utf-8")))

    def test_setup_and_disable_preserve_user_hook(self):
        hook = self.root / "pre-commit"
        hook.write_text("#!/bin/sh\necho user-hook\n", encoding="utf-8")
        with patch.object(cli, "_pre_commit_path", return_value=hook):
            first = self.runner.invoke(cli.main, ["setup-hooks", "--dir", str(self.root)])
            second = self.runner.invoke(cli.main, ["setup-hooks", "--dir", str(self.root)])
            installed = hook.read_text(encoding="utf-8")
            removed = self.runner.invoke(cli.main, ["disable-hooks", "--dir", str(self.root)])
        self.assertEqual(first.exit_code, 0, first.output)
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertEqual(removed.exit_code, 0, removed.output)
        self.assertEqual(installed.count("konman check"), 1)
        self.assertIn("echo user-hook", hook.read_text(encoding="utf-8"))
        self.assertNotIn("konman check", hook.read_text(encoding="utf-8"))

    def test_handoff_writes_context_pack_and_configures_alias(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        (engine.ctx_dir / "requirements" / "R-001.yaml").write_text(
            "id: R-001\nstatement: Keep the API stable\nkind: hard\nstatus: active\n",
            encoding="utf-8",
        )
        with patch.object(cli, "inject_vsc_copilot_adapters", return_value=["adapter configured"]):
            result = self.runner.invoke(cli.main, ["handoff", "claude-code", "vscode-copilot", "--dir", str(self.root)])
        self.assertEqual(result.exit_code, 0, result.output)
        packs = list((engine.ctx_dir / "state" / "history").glob("handoff-*.md"))
        self.assertEqual(len(packs), 1)
        self.assertIn("Keep the API stable", packs[0].read_text(encoding="utf-8"))

    def test_doc_generates_markdown_from_context_without_raw_capture_data(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        (engine.ctx_dir / "project.md").write_text("# Example API\nA service for project planning.\n", encoding="utf-8")
        (engine.ctx_dir / "requirements" / "R-001.yaml").write_text(
            "id: R-001\nstatement: Keep the API stable\nkind: hard\nstatus: proposed\n"
            "evidence: Keep the API stable.\ncapture_id: internal-capture-metadata\n",
            encoding="utf-8",
        )
        (engine.ctx_dir / "decisions" / "D-001.yaml").write_text(
            "id: D-001\nchosen: SQLite\nmode: default\nstatus: active\nreason: Local-first storage.\n",
            encoding="utf-8",
        )
        (engine.ctx_dir / "boundaries.yaml").write_text(
            "- id: B-001\n  path: src/auth.py\n  rule: no_edit_without_approval\n  status: active\n",
            encoding="utf-8",
        )
        (engine.ctx_dir / "state" / "current.yaml").write_text(
            "summary: Refactoring authentication\n", encoding="utf-8"
        )
        (engine.ctx_dir / "questions" / "Q-001.md").write_text(
            "Should API keys support rotation?\n", encoding="utf-8"
        )
        (engine.ctx_dir / "questions" / "Q-001.yaml").write_text(
            "id: Q-001\nquestion: Can clients rotate keys?\nstatus: open\n",
            encoding="utf-8",
        )
        (engine.ctx_dir / "objects" / "O-001.yaml").write_text(
            "id: O-001\nname: API key\nkind: credential\nstatus: active\n",
            encoding="utf-8",
        )
        (engine.ctx_dir / "evidence" / "E-001.yaml").write_text(
            "id: E-001\nsource_type: test\nexcerpt: Key rotation is covered.\nstatus: active\n",
            encoding="utf-8",
        )
        (engine.ctx_dir / "changes" / "C-001.yaml").write_text(
            "id: C-001\nsummary: Add key rotation\nstatus: proposed\n",
            encoding="utf-8",
        )
        (engine.ctx_dir / "risks" / "X-001.yaml").write_text(
            "id: X-001\nstatement: Clients may lose access during rotation.\nstatus: open\n",
            encoding="utf-8",
        )
        (engine.ctx_dir / ".raw" / "capture.json").write_text(
            '{"prompt":"raw-capture-secret"}', encoding="utf-8"
        )

        result = self.runner.invoke(cli.main, ["doc", "--dir", str(self.root)])

        self.assertEqual(result.exit_code, 0, result.output)
        output = engine.ctx_dir / "context-document.md"
        self.assertTrue(output.is_file())
        document = output.read_text(encoding="utf-8")
        for expected in (
            "Project Context and Specifications: " + self.root.name,
            "A service for project planning.",
            "Keep the API stable",
            "SQLite",
            "src/auth.py",
            "Refactoring authentication",
            "Should API keys support rotation?",
            "Can clients rotate keys?",
            "API key",
            "Key rotation is covered.",
            "Add key rotation",
            "Clients may lose access during rotation.",
        ):
            self.assertIn(expected, document)
        self.assertNotIn("internal-capture-metadata", document)
        self.assertNotIn("raw-capture-secret", document)

    def test_doc_reports_missing_context_directory(self):
        result = self.runner.invoke(cli.main, ["doc", "--dir", str(self.root)])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("run `konman init` first", result.output)

    @unittest.skipUnless(importlib.util.find_spec("reportlab"), "ReportLab optional PDF dependency is not installed")
    def test_doc_generates_pdf_output(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        (engine.ctx_dir / "project.md").write_text("# Example API\nA service.\n", encoding="utf-8")
        (engine.ctx_dir / "requirements" / "R-001.yaml").write_text(
            "id: R-001\nstatement: Keep the API response < 100 ms\nkind: hard\n"
            "status: active\nwhy: Preserve a responsive service.\n",
            encoding="utf-8",
        )

        result = self.runner.invoke(
            cli.main,
            ["doc", "--format", "pdf", "--output", "docs/project-context.pdf", "--dir", str(self.root)],
        )

        self.assertEqual(result.exit_code, 0, result.output)
        output = self.root / "docs" / "project-context.pdf"
        self.assertTrue(output.read_bytes().startswith(b"%PDF-"))
        self.assertGreater(output.stat().st_size, 1000)

    def test_setup_adapters_write_hooks_and_preserve_existing_config(self):
        claude_settings = self.root / ".claude" / "settings.json"
        claude_settings.parent.mkdir()
        claude_settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo existing"}]}]}}), encoding="utf-8")
        codex_hooks = self.root / ".codex" / "hooks.json"
        codex_hooks.parent.mkdir()
        codex_hooks.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo existing"}]}]}}), encoding="utf-8")
        cursor_hooks = self.root / ".cursor" / "hooks.json"
        cursor_hooks.parent.mkdir()
        cursor_hooks.write_text(json.dumps({"hooks": {"beforeSubmitPrompt": [{"command": "echo existing"}]}}), encoding="utf-8")

        inject_claude_code_adapters(str(self.root))
        inject_codex_adapters(str(self.root))
        inject_cursor_adapters(str(self.root))
        inject_vsc_copilot_adapters(str(self.root))
        inject_kiro_adapters(str(self.root))

        claude_payload = json.loads(claude_settings.read_text(encoding="utf-8"))
        self.assertIn("echo existing", json.dumps(claude_payload))
        self.assertIn("konman hook --event UserPromptSubmit", json.dumps(claude_payload))
        codex_payload = json.loads(codex_hooks.read_text(encoding="utf-8"))
        self.assertIn("echo existing", json.dumps(codex_payload))
        cursor_payload = json.loads(cursor_hooks.read_text(encoding="utf-8"))
        self.assertIn("echo existing", json.dumps(cursor_payload))
        copilot_payload = json.loads((self.root / ".github" / "hooks" / "konman.json").read_text(encoding="utf-8"))
        self.assertIn("UserPromptSubmit", copilot_payload["hooks"])
        kiro_payload = json.loads((self.root / ".kiro" / "hooks" / "konman.json").read_text(encoding="utf-8"))
        self.assertEqual(kiro_payload["version"], "v1")
        self.assertTrue(any(item["trigger"] == "UserPromptSubmit" for item in kiro_payload["hooks"]))

    def test_antigravity_setup_merges_global_and_project_hooks_idempotently(self):
        home = self.root / "home"
        system_config = home / ".gemini" / "config" / "mcp_config.json"
        system_config.parent.mkdir(parents=True)
        system_config.write_text(json.dumps({"mcpServers": {"other": {"command": "other-server"}}}), encoding="utf-8")
        project_hooks = self.root / ".agents" / "hooks.json"
        project_hooks.parent.mkdir()
        project_hooks.write_text(json.dumps({"hooks": [{"event": "Custom", "command": "echo keep"}]}), encoding="utf-8")

        with patch("pathlib.Path.home", return_value=home):
            inject_antigravity_hooks(str(self.root))
            inject_antigravity_hooks(str(self.root))

        servers = json.loads(system_config.read_text(encoding="utf-8"))["mcpServers"]
        self.assertIn("other", servers)
        self.assertIn("konman", servers)
        hooks = json.loads(project_hooks.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(sum(item.get("event") == "UserPromptSubmit" for item in hooks), 1)
        self.assertTrue(any(item.get("event") == "Custom" for item in hooks))

    def test_antigravity_invalid_json_is_not_overwritten(self):
        home = self.root / "home"
        system_config = home / ".gemini" / "config" / "mcp_config.json"
        system_config.parent.mkdir(parents=True)
        system_config.write_text("{invalid", encoding="utf-8")
        original = system_config.read_text(encoding="utf-8")
        with patch("pathlib.Path.home", return_value=home):
            with self.assertRaises(ValueError):
                inject_antigravity_hooks(str(self.root))
        self.assertEqual(system_config.read_text(encoding="utf-8"), original)

    def test_agents_refresh_keeps_user_content_and_is_idempotent(self):
        agents = self.root / "AGENTS.md"
        agents.write_text("# Team Instructions\n\nNever change generated clients.\n", encoding="utf-8")
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        engine.compile_agents_md()
        engine.compile_agents_md()
        content = agents.read_text(encoding="utf-8")
        self.assertIn("Never change generated clients.", content)
        self.assertEqual(content.count("<!-- konman:context:start -->"), 1)

    def test_init_ignores_raw_without_replacing_gitignore(self):
        gitignore = self.root / ".gitignore"
        gitignore.write_text("build/\n# keep this comment\n", encoding="utf-8")
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        engine.init_folders()
        content = gitignore.read_text(encoding="utf-8")
        self.assertIn("build/", content)
        self.assertIn("# keep this comment", content)
        self.assertEqual(content.count(".context/.raw/"), 1)

    def test_credentials_use_store_and_migrate_legacy_plaintext(self):
        passwords = {}
        fake_keyring = types.ModuleType("keyring")
        fake_keyring.get_keyring = lambda: types.SimpleNamespace(priority=1)
        fake_keyring.set_password = lambda service, username, password: passwords.__setitem__((service, username), password)
        fake_keyring.get_password = lambda service, username: passwords.get((service, username))
        fake_keyring.delete_password = lambda service, username: passwords.pop((service, username), None)
        with patch.dict(sys.modules, {"keyring": fake_keyring}), patch("pathlib.Path.home", return_value=self.root):
            config_path = Path(save_global_api_credentials("super-secret", "test-provider", "https://example.test/v1", "test-model", "openai-compatible"))
            metadata = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertNotIn("super-secret", config_path.read_text(encoding="utf-8"))
            self.assertEqual(load_global_api_credentials()["api_key"], "super-secret")
            config_path.write_text(json.dumps({"provider": "legacy", "api_key": "legacy-secret"}), encoding="utf-8")
            self.assertTrue(migrate_legacy_credentials())
            self.assertNotIn("legacy-secret", config_path.read_text(encoding="utf-8"))
            self.assertEqual(load_global_api_credentials()["api_key"], "legacy-secret")
            self.assertTrue(clear_global_api_credentials())
            self.assertFalse(config_path.exists())

    def test_plaintext_credential_fallback_is_not_written(self):
        with patch("konman.config._get_credential_store", side_effect=RuntimeError("no secure backend")), patch("pathlib.Path.home", return_value=self.root):
            with self.assertRaises(RuntimeError):
                save_global_api_credentials("secret", "provider", "https://example.test/v1", "model")
        self.assertFalse((self.root / ".config" / "konman" / "config.json").exists())

    def test_mcp_initializes_and_lists_tools(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        (engine.ctx_dir / "requirements" / "R-001.yaml").write_text(
            "id: R-001\nstatement: Keep dates serializable\nkind: hard\nstatus: active\nsource:\n  when: 2026-10-13\n",
            encoding="utf-8",
        )
        (engine.ctx_dir / "objects" / "O-001.yaml").write_text(
            "id: O-001\nname: API service\nstatus: active\n", encoding="utf-8"
        )
        messages = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_context", "arguments": {}}}),
        ]) + "\n"
        result = self.runner.invoke(cli.main, ["mcp", "--dir", str(self.root)], input=messages)
        self.assertEqual(result.exit_code, 0, result.output)
        replies = [json.loads(line) for line in result.output.splitlines()]
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "konman")
        self.assertIn("get_context", [tool["name"] for tool in replies[1]["result"]["tools"]])
        context = json.loads(replies[2]["result"]["content"][0]["text"])
        self.assertEqual(context["requirements"][0]["source"]["when"], "2026-10-13")
        self.assertEqual(context["objects"][0]["name"], "API service")
        self.assertEqual(cli._mcp_context(engine, "list_context_nodes", {"type": "objects"})[0]["id"], "O-001")

    def test_tail_discovers_nested_vscode_extension_logs(self):
        appdata = self.root / "appdata"
        log = appdata / "Code" / "logs" / "session" / "exthost" / "GitHub.copilot-chat" / "chat.log"
        log.parent.mkdir(parents=True)
        log.write_text("User prompt: preserve the database format\n", encoding="utf-8")
        with patch.dict("os.environ", {"APPDATA": str(appdata)}):
            result = self.runner.invoke(cli.main, ["tail", "--dir", str(self.root)])
        self.assertEqual(result.exit_code, 0, result.output)
        captures = list((self.root / ".context" / ".raw").glob("backfill-copilot-*.json"))
        self.assertEqual(len(captures), 1)
        self.assertIn("preserve the database format", captures[0].read_text(encoding="utf-8"))

    def test_each_transcript_source_normalizes_user_events(self):
        fixtures = {
            "claude-code": {"type": "user", "message": {"role": "user", "content": "Claude prompt"}},
            "codex": {"type": "event_msg", "payload": {"type": "user_message", "message": "Codex prompt"}},
            "cursor": {"role": "user", "content": "Cursor prompt"},
            "copilot": {"line": "User prompt: Copilot prompt"},
            "kiro": {"trigger": "UserPromptSubmit", "prompt": "Kiro prompt"},
            "antigravity": {"role": "user", "parts": [{"text": "Antigravity prompt"}]},
        }
        for source, fixture in fixtures.items():
            with self.subTest(source=source):
                events = parse_record(source, fixture)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].role, "user")
                self.assertTrue(events[0].text.endswith("prompt"))

    def test_backfill_skips_bad_jsonl_record_but_keeps_later_events(self):
        transcript = self.root / "mixed.jsonl"
        transcript.write_text(
            "{not-json}\n" + json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "later valid prompt"}}) + "\n",
            encoding="utf-8",
        )
        result = self.runner.invoke(cli.main, ["backfill", "--source", "codex", "--source-path", str(transcript), "--dir", str(self.root)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("failed=1", result.output)
        captures = list((self.root / ".context" / ".raw").glob("backfill-codex-*.json"))
        self.assertEqual(len(captures), 1)
        self.assertIn("later valid prompt", captures[0].read_text(encoding="utf-8"))

    def test_backfill_detects_in_place_rotation_and_oversized_records(self):
        transcript = self.root / "rotating.jsonl"
        first = {"type": "event_msg", "payload": {"type": "user_message", "message": "original prompt", "session_id": "rotation"}}
        transcript.write_text(json.dumps(first) + "\n", encoding="utf-8")
        args = ["backfill", "--source", "codex", "--source-path", str(transcript), "--dir", str(self.root)]
        initial = self.runner.invoke(cli.main, args)
        self.assertEqual(initial.exit_code, 0, initial.output)

        replacement = {"type": "event_msg", "payload": {"type": "user_message", "message": "replacement prompt", "session_id": "rotation"}}
        transcript.write_text(json.dumps(replacement) + "\n", encoding="utf-8")
        rotated = self.runner.invoke(cli.main, args)
        self.assertEqual(rotated.exit_code, 0, rotated.output)
        self.assertIn("persisted=1", rotated.output)

        valid = {"type": "event_msg", "payload": {"type": "user_message", "message": "after oversized event", "session_id": "rotation"}}
        transcript.write_text(("x" * (2 * 1024 * 1024 + 1)) + "\n" + json.dumps(valid) + "\n", encoding="utf-8")
        oversized = self.runner.invoke(cli.main, args)
        self.assertEqual(oversized.exit_code, 0, oversized.output)
        self.assertIn("failed=1", oversized.output)
        self.assertIn("persisted=1", oversized.output)

    def test_backfill_cursor_resumes_after_append_without_duplicate_events(self):
        transcript = self.root / "rollout.jsonl"
        records = [
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Keep the migration reversible", "session_id": "session-1", "timestamp": "2026-10-12T10:00:00Z"}},
            {"type": "event_msg", "payload": {"type": "assistant_message", "message": "I will preserve compatibility", "session_id": "session-1", "timestamp": "2026-10-12T10:00:01Z"}},
        ]
        transcript.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        args = ["backfill", "--source", "codex", "--source-path", str(transcript), "--dir", str(self.root)]
        first = self.runner.invoke(cli.main, args)
        self.assertEqual(first.exit_code, 0, first.output)
        self.assertIn("persisted=2", first.output)
        second = self.runner.invoke(cli.main, args)
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertIn("persisted=0", second.output)

        records.append({"type": "event_msg", "payload": {"type": "user_message", "message": "Keep the API stable too", "session_id": "session-1", "timestamp": "2026-10-12T10:00:02Z"}})
        transcript.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        third = self.runner.invoke(cli.main, args)
        self.assertEqual(third.exit_code, 0, third.output)
        self.assertIn("persisted=1", third.output)
        self.assertEqual(len(list((self.root / ".context" / ".raw").glob("backfill-codex-*.json"))), 3)

    def test_backfill_dry_run_does_not_write_state(self):
        transcript = self.root / "rollout.jsonl"
        transcript.write_text(json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Keep the API stable"}}) + "\n", encoding="utf-8")
        result = self.runner.invoke(cli.main, ["backfill", "--source", "codex", "--source-path", str(transcript), "--dir", str(self.root), "--dry-run"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse((self.root / ".context").exists())

    def test_clean_requires_age_and_dry_run_preserves_raw_capture(self):
        raw_dir = self.root / ".context" / ".raw"
        raw_dir.mkdir(parents=True)
        old_capture = raw_dir / "capture.json"
        old_capture.write_text("{}", encoding="utf-8")
        old_time = 1
        import os
        os.utime(old_capture, (old_time, old_time))
        preview = self.runner.invoke(cli.main, ["clean", "--older-than", "1", "--dry-run", "--dir", str(self.root)])
        self.assertEqual(preview.exit_code, 0, preview.output)
        self.assertTrue(old_capture.exists())
        removed = self.runner.invoke(cli.main, ["clean", "--older-than", "1", "--dir", str(self.root)])
        self.assertEqual(removed.exit_code, 0, removed.output)
        self.assertFalse(old_capture.exists())

    def test_hook_redacts_secrets_and_never_overwrites_capture(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        manifest = engine.ctx_dir / "manifest.yaml"
        manifest.write_text("schema_version: 1\nredaction:\n  patterns:\n    - 'private-value-[A-Z]+'\n", encoding="utf-8")
        raw_dir = engine.ctx_dir / ".raw"
        payload = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "Token is private-value-ABC", "api_key": "secret-value", "cwd": str(self.root)})
        with patch.object(cli, "_resolve_raw_capture_dir", return_value=raw_dir):
            first = self.runner.invoke(cli.main, ["hook", "--event", "UserPromptSubmit"], input=payload)
            second = self.runner.invoke(cli.main, ["hook", "--event", "UserPromptSubmit"], input=payload)
        captures = list(raw_dir.glob("UserPromptSubmit_*.json"))
        self.assertEqual(first.output, "")
        self.assertEqual(second.output, "")
        self.assertEqual(len(captures), 2)
        self.assertTrue(all("secret-value" not in path.read_text(encoding="utf-8") for path in captures))
        self.assertTrue(all("private-value-ABC" not in path.read_text(encoding="utf-8") for path in captures))
        self.assertTrue(all(str(self.root) not in path.read_text(encoding="utf-8") for path in captures))

    def test_invalid_custom_redaction_pattern_fails_closed(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        (engine.ctx_dir / "manifest.yaml").write_text("redaction:\n  patterns:\n    - '['\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            cli._custom_redaction_patterns(engine.ctx_dir)

    def test_config_persists_provider_endpoint_and_model(self):
        existing = {
            "provider": "gemini",
            "api_format": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "model": "old-model",
            "api_key": "old-key",
        }
        with patch.object(cli, "load_global_api_credentials", return_value=existing), patch.object(
            cli, "save_global_api_credentials", return_value="config-path"
        ) as save:
            result = self.runner.invoke(cli.main, [
                "config", "--api-key", "test-key", "--provider", "groq",
                "--base-url", "https://api.groq.com/openai/v1", "--model", "llama-model",
            ])
        self.assertEqual(result.exit_code, 0, result.output)
        save.assert_called_once_with("test-key", "groq", "https://api.groq.com/openai/v1", "llama-model", "openai-compatible")

    def test_config_accepts_keyless_ollama(self):
        existing = {
            "provider": "gemini",
            "api_format": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "model": "old-model",
            "api_key": "old-key",
        }
        with patch.object(cli, "load_global_api_credentials", return_value=existing), patch.object(
            cli, "save_global_api_credentials", return_value="config-path"
        ) as save:
            result = self.runner.invoke(cli.main, ["config", "--provider", "ollama", "--model", "qwen-local"])
        self.assertEqual(result.exit_code, 0, result.output)
        save.assert_called_once_with("", "ollama", "http://localhost:11434", "qwen-local", "ollama")

    def test_config_partial_update_keeps_saved_provider_and_key(self):
        existing = {
            "provider": "anthropic",
            "api_format": "anthropic",
            "base_url": "https://api.anthropic.com/v1",
            "model": "old-model",
            "api_key": "stored-secret",
        }
        with patch.object(cli, "load_global_api_credentials", return_value=existing), patch.object(
            cli, "save_global_api_credentials", return_value="config-path"
        ) as save:
            result = self.runner.invoke(cli.main, ["config", "--model", "new-model"])
        self.assertEqual(result.exit_code, 0, result.output)
        save.assert_called_once_with("stored-secret", "anthropic", "https://api.anthropic.com/v1", "new-model", "anthropic")

    def test_custom_provider_requires_url_and_help_shows_usage(self):
        existing = {
            "provider": "gemini",
            "api_format": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "model": "old-model",
            "api_key": "old-key",
        }
        with patch.object(cli, "load_global_api_credentials", return_value=existing):
            missing_url = self.runner.invoke(cli.main, ["config", "-k", "test-key", "-p", "my-provider"])
        self.assertNotEqual(missing_url.exit_code, 0)
        self.assertIn("requires --base-url", missing_url.output)

        help_result = self.runner.invoke(cli.main, ["--help"], prog_name="konman")
        self.assertEqual(help_result.exit_code, 0, help_result.output)
        self.assertIn("konman setup claude-code [OPTIONS]", help_result.output)
        self.assertIn("konman config --api-key", help_result.output)
        self.assertNotIn("\nCommands:\n", help_result.output)

        config_help = self.runner.invoke(cli.main, ["config", "--help"], prog_name="konman")
        self.assertIn("anthropic", config_help.output)
        self.assertIn("gemini", config_help.output)
        self.assertIn("ollama", config_help.output)

    def test_review_requires_confirmation_and_records_approval(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        proposed = engine.ctx_dir / "requirements" / "R-001.yaml"
        proposed.write_text(
            "id: R-001\nstatement: Keep the API stable\nkind: hard\nevidence: Keep the API stable\nstatus: proposed\nsource: {who: llm:test, when: 2026-10-13}\n",
            encoding="utf-8",
        )
        cancelled = self.runner.invoke(cli.main, ["review", "--id", "R-001", "--approve", "--dir", str(self.root)], input="n\n")
        self.assertEqual(cancelled.exit_code, 0, cancelled.output)
        self.assertIn("status: proposed", proposed.read_text(encoding="utf-8"))

        approved = self.runner.invoke(cli.main, ["review", "--id", "R-001", "--approve", "--yes", "--dir", str(self.root)])
        self.assertEqual(approved.exit_code, 0, approved.output)
        content = proposed.read_text(encoding="utf-8")
        self.assertIn("status: active", content)
        self.assertIn("review:", content)

    def test_review_rejects_with_reason(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        proposed = engine.ctx_dir / "decisions" / "D-001.yaml"
        proposed.write_text(
            "id: D-001\nchosen: SQLite\nmode: default\nstatus: proposed\nevidence: use SQLite\nconsidered: [{object: SQLite, verdict: proposed}]\n",
            encoding="utf-8",
        )
        result = self.runner.invoke(cli.main, ["review", "--id", "D-001", "--reject", "--dir", str(self.root)], input="Rejected by reviewer\n")
        self.assertEqual(result.exit_code, 0, result.output)
        content = proposed.read_text(encoding="utf-8")
        self.assertIn("status: rejected", content)
        self.assertIn("Rejected by reviewer", content)

    def test_review_can_approve_extracted_boundary(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        boundary_path = engine.ctx_dir / "boundaries.yaml"
        boundary_path.write_text(
            "- id: B-001\n  path: src/auth.py\n  rule: no_edit_without_approval\n"
            "  why: Authentication changes require review.\n  evidence: Do not edit src/auth.py without approval.\n"
            "  status: proposed\n",
            encoding="utf-8",
        )
        engine.compile_agents_md()
        self.assertNotIn("src/auth.py", (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(cli._mcp_context(engine, "get_boundaries", {}), [])
        self.assertTrue(any("Boundary 'B-001' is awaiting review." in item for item in engine.check_graph_validity(strict=True)))
        result = self.runner.invoke(
            cli.main,
            ["review", "--id", "B-001", "--approve", "--yes", "--dir", str(self.root)],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        boundaries = YAML().load(boundary_path.read_text(encoding="utf-8"))
        self.assertEqual(boundaries[0]["status"], "active")
        self.assertIn("src/auth.py", (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(len(cli._mcp_context(engine, "get_boundaries", {})), 1)

    def test_resolve_replaces_stale_requirement_and_rechecks_graph(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        (engine.ctx_dir / "requirements" / "R-001.yaml").write_text("id: R-001\nstatement: old\nkind: hard\nstatus: superseded\n", encoding="utf-8")
        (engine.ctx_dir / "requirements" / "R-002.yaml").write_text("id: R-002\nstatement: replacement\nkind: hard\nstatus: active\n", encoding="utf-8")
        decision = engine.ctx_dir / "decisions" / "D-001.yaml"
        decision.write_text(
            "id: D-001\nchosen: sqlite\nmode: compared\nstatus: needs_review\nconsidered:\n- object: sqlite\n  verdict: selected\n  evaluations:\n  - req: R-001\n    result: pass\n    via: embedded\n",
            encoding="utf-8",
        )
        result = self.runner.invoke(
            cli.main,
            ["resolve", "D-001", "--replace-req", "R-001=R-002", "--dir", str(self.root)],
            input="Updated rationale\ny\n",
        )
        self.assertEqual(result.exit_code, 0, result.output)
        resolved = YAML().load(decision.read_text(encoding="utf-8"))
        self.assertEqual(resolved["status"], "active")
        self.assertEqual(resolved["considered"][0]["evaluations"][0]["req"], "R-002")

    def test_check_finds_stale_dependencies_and_strict_proposals_without_mutation(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        requirement = engine.ctx_dir / "requirements" / "R-001.yaml"
        decision = engine.ctx_dir / "decisions" / "D-001.yaml"
        requirement.write_text("id: R-001\nstatement: old\nkind: hard\nstatus: superseded\n", encoding="utf-8")
        decision.write_text(
            "id: D-001\nchosen: sqlite\nmode: compared\nstatus: active\nconsidered:\n- object: sqlite\n  verdict: selected\n  evaluations:\n  - req: R-001\n    result: pass\n    via: embedded\n",
            encoding="utf-8",
        )
        decision_before = decision.read_text(encoding="utf-8")
        normal = self.runner.invoke(cli.main, ["check", "--dir", str(self.root)])
        self.assertEqual(normal.exit_code, 1, normal.output)
        self.assertIn("depends on stale requirement", normal.output)
        self.assertEqual(decision.read_text(encoding="utf-8"), decision_before)

        requirement.write_text("id: R-001\nstatement: new\nkind: hard\nstatus: active\n", encoding="utf-8")
        proposed = engine.ctx_dir / "requirements" / "R-002.yaml"
        proposed.write_text("id: R-002\nstatement: proposal\nkind: hard\nstatus: proposed\n", encoding="utf-8")
        ordinary = self.runner.invoke(cli.main, ["check", "--dir", str(self.root)])
        strict = self.runner.invoke(cli.main, ["check", "--strict", "--dir", str(self.root)])
        self.assertEqual(ordinary.exit_code, 0, ordinary.output)
        self.assertEqual(strict.exit_code, 1, strict.output)

    def test_doctor_reports_project_and_adapter_state_without_mutating(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        adapter = self.root / ".claude" / "settings.json"
        adapter.parent.mkdir(parents=True)
        adapter.write_text('{"hooks": {}}\n', encoding="utf-8")
        with patch.object(cli, "load_global_api_credentials", return_value={}):
            result = self.runner.invoke(cli.main, ["doctor", "--dir", str(self.root)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("[PASS] Raw data ignore", result.output)
        self.assertIn("[PASS] Adapter claude-code", result.output)
        self.assertEqual(adapter.read_text(encoding="utf-8"), '{"hooks": {}}\n')

    def test_doctor_warns_on_unmigrated_plaintext_credential(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        with patch.object(cli, "load_global_api_credentials", return_value={
            "provider": "openai", "legacy_plaintext_credential": True,
        }):
            result = self.runner.invoke(cli.main, ["doctor", "--dir", str(self.root)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("konman config --migrate", result.output)

    def test_record_appends_boundaries_and_refuses_duplicate_ids(self):
        first = self.runner.invoke(cli.main, ["record", "--type", "boundary", "--id", "B-001", "--dir", str(self.root)], input="src/one\nProtect one\n\n")
        second = self.runner.invoke(cli.main, ["record", "--type", "boundary", "--id", "B-002", "--dir", str(self.root)], input="src/two\nProtect two\n\n")
        self.assertEqual(first.exit_code, 0, first.output)
        self.assertEqual(second.exit_code, 0, second.output)
        boundaries = YAML().load((self.root / ".context" / "boundaries.yaml").read_text(encoding="utf-8"))
        self.assertEqual([item["id"] for item in boundaries], ["B-001", "B-002"])

        duplicate = self.runner.invoke(cli.main, ["record", "--type", "boundary", "--id", "B-001", "--dir", str(self.root)], input="src/three\nProtect three\n")
        self.assertNotEqual(duplicate.exit_code, 0)
        self.assertEqual(len(YAML().load((self.root / ".context" / "boundaries.yaml").read_text(encoding="utf-8"))), 2)

    def test_miner_uses_count_as_separate_argument_and_target_directory(self):
        engine = ContextEngine(str(self.root))
        output = "hash\x1fauthor\x1f2026-10-13\x1fFix cache because writes race\x1e"
        with patch("subprocess.run") as run:
            run.return_value.stdout = output
            count = engine.mine_git_history(4)
        self.assertEqual(count, 1)
        args, kwargs = run.call_args
        self.assertEqual(args[0][1:3], ["log", "-n"])
        self.assertEqual(args[0][3], "4")
        self.assertTrue(Path(kwargs["cwd"]).samefile(self.root))

    def test_mined_commit_creates_deduplicated_proposed_change_and_evidence(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        result = types.SimpleNamespace(
            stdout="a" * 40 + "\x1fDev User\x1f2026-01-02\x1fFixes auth because token validation was missing.\x1e"
        )
        with patch("subprocess.run", return_value=result):
            first_count = engine.mine_git_history(1)
            second_count = engine.mine_git_history(1)
        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        changes = list((engine.ctx_dir / "changes").glob("C-*.yaml"))
        evidence = list((engine.ctx_dir / "evidence").glob("E-*.yaml"))
        self.assertEqual(len(changes), 1)
        self.assertEqual(len(evidence), 1)
        change = YAML().load(changes[0].read_text(encoding="utf-8"))
        proof = YAML().load(evidence[0].read_text(encoding="utf-8"))
        self.assertEqual(change["status"], "proposed")
        self.assertEqual(change["evidence"], [proof["id"]])
        self.assertEqual(proof["source_type"], "commit")

    def test_check_validates_new_context_node_relationships(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        nodes = {
            "evidence": [{
                "id": "E-001", "source_type": "document", "excerpt": "API contract",
                "related_nodes": ["R-001", "D-001", "O-001"], "status": "active",
            }],
            "objects": [{
                "id": "O-001", "name": "Public API", "evidence": ["E-001"], "status": "active",
            }],
            "requirements": [{
                "id": "R-001", "statement": "Keep API stable", "kind": "hard",
                "evidence_ids": ["E-001"], "status": "active",
            }],
            "decisions": [{
                "id": "D-001", "chosen": "Public API", "mode": "default", "status": "active",
                "considered": [{
                    "object": "Public API", "object_id": "O-001", "verdict": "selected",
                }],
            }],
            "changes": [{
                "id": "C-001", "summary": "Preserve API contract", "implements": ["D-001"],
                "affects": ["R-001"], "evidence": ["E-001"], "status": "active",
            }],
            "questions": [{
                "id": "Q-001", "question": "Which clients need support?", "objects": ["O-001"],
                "evidence": ["E-001"], "status": "open",
            }],
            "risks": [{
                "id": "X-001", "statement": "Breaking clients", "changes": ["C-001"],
                "evidence": ["E-001"], "status": "open",
            }],
        }
        from io import StringIO
        for folder, items in nodes.items():
            for item in items:
                serialized = StringIO()
                engine.yaml.dump(item, serialized)
                (engine.ctx_dir / folder / f"{item['id']}.yaml").write_text(
                    serialized.getvalue(), encoding="utf-8"
                )
        serialized = StringIO()
        engine.yaml.dump(
            [{"id": "B-001", "path": "src/auth.py", "constrains": ["R-001"], "evidence_ids": ["E-001"]}],
            serialized,
        )
        (engine.ctx_dir / "boundaries.yaml").write_text(serialized.getvalue(), encoding="utf-8")
        self.assertEqual(engine.check_graph_validity(), [])

        risk_path = engine.ctx_dir / "risks" / "X-001.yaml"
        risk_path.write_text(risk_path.read_text(encoding="utf-8").replace("C-001", "C-999"), encoding="utf-8")
        self.assertTrue(any("missing change 'C-999'" in issue for issue in engine.check_graph_validity()))

    def test_question_risk_resolution_and_decision_resolution_without_action_flag(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        (engine.ctx_dir / "questions" / "Q-001.yaml").write_text(
            "id: Q-001\nquestion: Which API version?\nstatus: open\n", encoding="utf-8"
        )
        (engine.ctx_dir / "risks" / "X-001.yaml").write_text(
            "id: X-001\nstatement: Compatibility regression\nstatus: open\n", encoding="utf-8"
        )
        decision = engine.ctx_dir / "decisions" / "D-001.yaml"
        decision.write_text(
            "id: D-001\nchosen: SQLite\nmode: default\nstatus: needs_review\nconsidered: []\n",
            encoding="utf-8",
        )
        answered = self.runner.invoke(
            cli.main, ["resolve", "Q-001", "--answer", "Use v2", "--dir", str(self.root)]
        )
        mitigated = self.runner.invoke(
            cli.main, ["resolve", "X-001", "--mitigate", "Add a compatibility test", "--dir", str(self.root)]
        )
        decision_result = self.runner.invoke(
            cli.main, ["resolve", "D-001", "--dir", str(self.root)], input="Reviewed rationale\ny\n"
        )
        self.assertEqual(answered.exit_code, 0, answered.output)
        self.assertEqual(mitigated.exit_code, 0, mitigated.output)
        self.assertEqual(decision_result.exit_code, 0, decision_result.output)
        self.assertEqual(YAML().load((engine.ctx_dir / "questions" / "Q-001.yaml").read_text())["status"], "answered")
        self.assertEqual(YAML().load((engine.ctx_dir / "risks" / "X-001.yaml").read_text())["status"], "mitigated")
        self.assertEqual(YAML().load(decision.read_text())["status"], "active")
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("Which API version?", agents)
        self.assertIn("[MITIGATED]", agents)

    def test_review_approves_proposed_change(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        change = engine.ctx_dir / "changes" / "C-001.yaml"
        change.write_text("id: C-001\nsummary: Add API test\nstatus: proposed\n", encoding="utf-8")
        result = self.runner.invoke(
            cli.main, ["review", "--id", "C-001", "--approve", "--yes", "--dir", str(self.root)]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(YAML().load(change.read_text(encoding="utf-8"))["status"], "active")

    def test_context_graph_builds_typed_relationships(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        workspace = ContextWorkspace(engine)
        evidence_id, _ = workspace.save("evidence", {
            "source_type": "document", "excerpt": "API must remain stable.", "status": "active",
        })
        requirement_id, _ = workspace.save("requirement", {
            "statement": "Keep API stable", "kind": "hard", "evidence_ids": [evidence_id],
        })
        object_id, _ = workspace.save("object", {"name": "Public API", "evidence": [evidence_id]})
        decision_id, _ = workspace.save("decision", {
            "chosen": "Public API",
            "mode": "default",
            "considered": [{
                "object": "Public API", "object_id": object_id, "verdict": "selected",
                "evaluations": [{
                    "req": requirement_id, "result": "pass", "via": "contract",
                    "object_id": object_id,
                }],
            }],
            "evidence_ids": [evidence_id],
        })
        boundary_id, _ = workspace.save("boundary", {
            "path": "src/api.py", "constrains": [requirement_id],
            "evidence_ids": [evidence_id], "status": "active",
        })
        snapshot = workspace.load()
        nodes, edges = build_graph(snapshot)
        self.assertEqual({node["id"] for node in nodes}, {
            evidence_id, requirement_id, object_id, decision_id, boundary_id,
        })
        links = {(edge["source"], edge["target"], edge["label"]) for edge in edges}
        self.assertIn((requirement_id, evidence_id, "supported by"), links)
        self.assertIn((decision_id, requirement_id, "evaluates: pass"), links)
        self.assertIn((decision_id, object_id, "considers"), links)
        self.assertIn((boundary_id, requirement_id, "constrains"), links)
        self.assertEqual(engine.check_graph_validity(), [])

    def test_context_workspace_validates_saves_and_detects_concurrent_edits(self):
        engine = ContextEngine(str(self.root))
        engine.init_folders()
        workspace = ContextWorkspace(engine)
        evidence_id, _ = workspace.save("evidence", {
            "source_type": "test", "excerpt": "This is verified.", "status": "active",
        })
        requirement_id, _ = workspace.save("requirement", {
            "statement": "Preserve verified behavior",
            "kind": "hard",
            "evidence_ids": [evidence_id],
        })
        snapshot = workspace.load()
        edited = dict(snapshot.records["requirement"][requirement_id])
        edited["why"] = "Avoid regressions."
        requirement_path = engine.ctx_dir / "requirements" / f"{requirement_id}.yaml"
        requirement_path.write_text(
            requirement_path.read_text(encoding="utf-8") + "# concurrent modification\n",
            encoding="utf-8",
        )
        with self.assertRaises(ConcurrentEditError):
            workspace.save(
                "requirement", edited, node_id=requirement_id,
                expected_token=snapshot.tokens[("requirement", requirement_id)],
            )
        with self.assertRaises(ContextDataError):
            workspace.save("question", {
                "question": "Which requirement?",
                "requirements": ["R-999"],
                "status": "open",
            })
        self.assertFalse((engine.ctx_dir / "questions" / "Q-001.yaml").exists())

    def test_gui_command_binds_localhost_and_passes_project_path(self):
        with patch("konman.cli.importlib.util.find_spec", return_value=object()), patch(
            "konman.cli.subprocess.run", return_value=types.SimpleNamespace(returncode=0)
        ) as run:
            result = self.runner.invoke(
                cli.main, ["gui", "--dir", str(self.root), "--port", "8765", "--no-browser"]
            )
        self.assertEqual(result.exit_code, 0, result.output)
        args, kwargs = run.call_args
        self.assertIn("--server.address=127.0.0.1", args[0])
        self.assertIn("--server.port=8765", args[0])
        self.assertIn("--server.headless=true", args[0])
        self.assertEqual(args[0][-2:], ["--dir", str(self.root.resolve())])
        self.assertEqual(kwargs["cwd"], self.root.resolve())

    def test_gui_command_explains_optional_dependency(self):
        with patch("konman.cli.importlib.util.find_spec", return_value=None):
            result = self.runner.invoke(cli.main, ["gui", "--dir", str(self.root)])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('pip install "konman[gui]"', result.output)

    def test_llm_response_parsing_uses_chat_completions_shape(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=Response()) as urlopen:
            result = ContextEngine(str(self.root)).execute_llm_distillation("input", "key", base_url="https://api.example/v1")
        self.assertEqual(result, "{}")
        self.assertEqual(urlopen.call_args.args[0].full_url, "https://api.example/v1/chat/completions")

    def test_llm_prompt_contains_only_requested_node_types(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=Response()) as urlopen:
            ContextEngine(str(self.root)).execute_llm_distillation(
                "input", "key", base_url="https://api.example/v1", node_types=("boundary",)
            )
        request_data = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        system_prompt = request_data["messages"][0]["content"]
        self.assertIn('"boundaries"', system_prompt)
        self.assertNotIn('"requirements"', system_prompt)
        self.assertNotIn('"decisions"', system_prompt)

    def test_llm_protocol_adapters_parse_provider_responses(self):
        cases = [
            (
                "anthropic", "https://api.anthropic.com/v1", "key",
                {"content": [{"type": "text", "text": "{}"}]},
                "https://api.anthropic.com/v1/messages", "X-api-key", "key",
            ),
            (
                "gemini", "https://generativelanguage.googleapis.com/v1beta", "key",
                {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]},
                "https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent", "X-goog-api-key", "key",
            ),
            (
                "ollama", "http://localhost:11434", None,
                {"message": {"content": "{}"}},
                "http://localhost:11434/api/chat", None, None,
            ),
        ]
        for api_format, base_url, api_key, payload, expected_url, auth_header, auth_value in cases:
            with self.subTest(api_format=api_format):
                class Response:
                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        return False

                    def read(self):
                        return json.dumps(payload).encode("utf-8")

                with patch("urllib.request.urlopen", return_value=Response()) as urlopen:
                    result = ContextEngine(str(self.root)).execute_llm_distillation(
                        "input", api_key, "test-model", base_url, api_format
                    )
                request = urlopen.call_args.args[0]
                self.assertEqual(result, "{}")
                self.assertEqual(request.full_url, expected_url)
                if auth_header:
                    self.assertEqual(request.get_header(auth_header), auth_value)


if __name__ == "__main__":
    unittest.main()