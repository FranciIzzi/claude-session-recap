"""Test di sessions.py su file .jsonl finti. Lancio: python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sessions as S  # noqa: E402


def _user(text, ts, cwd, **extra):
    return {"parentUuid": None, "isSidechain": False, "message": {"role": "user", "content": text},
            "type": "user", "timestamp": ts, "cwd": cwd, "gitBranch": "main", **extra}


def _assistant(text, ts, cwd):
    return {"parentUuid": None, "isSidechain": False,
            "message": {"type": "message", "role": "assistant",
                        "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}]},
            "type": "assistant", "timestamp": ts, "cwd": cwd}


class SessionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.proj_cwd = str(self.root / "work" / "D&D" / "app")
        Path(self.proj_cwd).mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, cwd, sid, records):
        d = self.root / "projects" / S.encode_dir(cwd)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{sid}.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return p

    def test_parse_extracts_title_prompts_and_reply(self):
        cwd = self.proj_cwd
        p = self._write(cwd, "aaaa-1111", [
            {"type": "api-request-blob", "message": {"role": "user", "content": [{"type": "text", "text": "x" * 5000}]}},
            _user("<command-name>/clear</command-name>", "2026-11-01T10:00:00Z", cwd),
            _user("Sistema il login", "2026-11-01T10:00:01Z", cwd),
            _assistant("Ok, guardo il login", "2026-11-01T10:00:02Z", cwd),
            _user([{"type": "tool_result", "content": "..."}], "2026-11-01T10:00:03Z", cwd),
            {"type": "ai-title", "aiTitle": "Fix login", "sessionId": "aaaa-1111"},
            {"type": "custom-title", "customTitle": "Login", "sessionId": "aaaa-1111"},
            _user("ora i test", "2026-11-01T10:05:00Z", cwd + "/sub"),
            _assistant("Test verdi", "2026-11-01T10:06:00Z", cwd + "/sub"),
            '{"type":"user", troncata',
        ])
        info = S.parse_session(p)
        self.assertEqual(info["title"], "Login")
        self.assertEqual(info["ai_title"], "Fix login")
        self.assertEqual(info["user_msgs"], 2)
        self.assertEqual(info["assistant_msgs"], 2)
        self.assertEqual(info["first_prompt"], "Sistema il login")
        self.assertEqual(info["last_prompts"], ["Sistema il login", "ora i test"])
        self.assertEqual(info["last_reply"], "Test verdi")
        # il cwd di resume è quello di avvio, non quello dopo un `cd`
        self.assertEqual(info["cwd"], cwd)
        self.assertEqual(info["last_cwd"], cwd + "/sub")
        self.assertTrue(info["cwd_exists"])
        self.assertIn("'", info["resume_cmd"])  # path con & viene quotato
        self.assertTrue(info["resume_cmd"].endswith("claude --resume aaaa-1111"))

    def test_sessions_without_real_prompts_are_skipped(self):
        p = self._write(self.proj_cwd, "empty", [
            _user("This session is being continued from a previous conversation", "2026-11-01T10:00:00Z", self.proj_cwd),
            {"type": "ai-title", "aiTitle": "x"},
        ])
        self.assertIsNone(S.parse_session(p))

    def test_sidechain_ignored(self):
        p = self._write(self.proj_cwd, "side", [
            _user("prompt vero", "2026-11-01T10:00:00Z", self.proj_cwd),
            {**_user("prompt subagent", "2026-11-01T10:01:00Z", self.proj_cwd), "isSidechain": True},
        ])
        self.assertEqual(S.parse_session(p)["last_prompts"], ["prompt vero"])

    def test_collect_sorts_filters_and_find(self):
        # cwd fuori dalle cartelle temporanee di sistema (tempfile su macOS sta in /var/folders)
        cwd = "/Users/test/D&D/app"
        self._write(cwd, "old-1", [_user("vecchia", "2026-10-01T10:00:00Z", cwd)])
        self._write(cwd, "new-2", [_user("nuova sul coach", "2026-11-02T10:00:00Z", cwd)])
        self._write("/private/tmp/x", "tmp-3", [_user("tmp", "2026-11-03T10:00:00Z", "/private/tmp/x")])
        projects = self.root / "projects"
        got = S.collect(projects, days=None)
        self.assertEqual([s["id"] for s in got], ["new-2", "old-1"])
        self.assertEqual(len(S.collect(projects, days=None, include_tmp=True)), 3)
        self.assertEqual(S.collect(projects, days=None, project="nessuno"), [])
        self.assertEqual([s["id"] for s in S.find("coach", got)], ["new-2"])
        self.assertEqual([s["id"] for s in S.find("old", got)], ["old-1"])  # prefisso id
        self.assertEqual([s["id"] for s in S.find("2", got)], ["old-1"])  # numero di riga
        self.assertEqual([s["id"] for s in S.find("2", got, {"2": "new-2"})], ["new-2"])  # numerazione in cache

    def test_secrets_are_redacted(self):
        out = S._clip("copia sul server, password Esempio-Finto42! e token ghp_FAKE0000example1111TOKEN", 300)
        self.assertNotIn("Esempio-Finto42", out)
        self.assertNotIn("FAKE0000", out)
        self.assertIn("password [REDACTED]", out)
        self.assertEqual(S._clip("api_key=sk-ant-abcdefghijklmnop", 300), "api_key=[REDACTED]")
        self.assertEqual(S._clip("niente di segreto qui", 300), "niente di segreto qui")
        self.assertEqual(S._clip("Il token l'ho trovato", 300), "Il token l'ho trovato")
        self.assertNotIn("AB12", S._clip("stesso `gho_AB12…ZZ99`", 300))

    def test_numbering_roundtrip(self):
        cache = self.root / "cache" / "last.json"
        S.save_numbering([{"n": 1, "id": "abc"}], cache)
        self.assertEqual(S.load_numbering(cache), {"1": "abc"})
        self.assertEqual(S.load_numbering(self.root / "missing.json"), {})


if __name__ == "__main__":
    unittest.main()
