import os
import shutil
import subprocess
import tempfile
import unittest

from lazy_agentd.cli import main

from .helpers import ROOT, free_port, get, run_cli, wait_for_port


class TestGenerateSystemd(unittest.TestCase):
    def test_writes_units(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out)
        rc = main(["--generate-systemd", "--name", "ollama-lazy", "--port", "11434",
                   "--target", "env OLLAMA_HOST=127.0.0.1:{port} ollama serve",
                   "--output-dir", out])
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(os.listdir(out)), ["ollama-lazy.service", "ollama-lazy.socket"])
        with open(os.path.join(out, "ollama-lazy.socket")) as f:
            sock = f.read()
        with open(os.path.join(out, "ollama-lazy.service")) as f:
            svc = f.read()
        self.assertIn("ListenStream=127.0.0.1:11434", sock)
        self.assertIn("WantedBy=sockets.target", sock)
        self.assertIn("Requires=ollama-lazy.socket", svc)
        self.assertNotIn("[Install]", svc)
        self.assertIn("--target 'env OLLAMA_HOST=127.0.0.1:{port} ollama serve'", svc)

    def test_escapes_systemd_specifiers(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out)
        main(["--generate-systemd", "--target", "echo 100% $HOME {port}", "--output-dir", out])
        with open(os.path.join(out, "lazy-agentd.service")) as f:
            self.assertIn("100%% $$HOME", f.read())


class TestDemoServer(unittest.TestCase):
    def test_demo_server_roundtrip(self):
        port = free_port()
        proc = run_cli("-p", str(port), "--idle-timeout", "1")
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.assertTrue(wait_for_port(port))
        status, body = get(port)
        self.assertEqual(status, 200)
        self.assertIn(b'"Ready"', body)
        out, _ = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, out)


@unittest.skipUnless(shutil.which("systemd-socket-activate"), "systemd-socket-activate not installed")
class TestRealSocketActivation(unittest.TestCase):
    def test_activated_by_systemd(self):
        import sys

        port = free_port()
        env = dict(os.environ, PYTHONPATH=ROOT, PYTHONUNBUFFERED="1")
        proc = subprocess.Popen(
            ["systemd-socket-activate", "-l", f"127.0.0.1:{port}",
             "-E", "PYTHONPATH", "-E", "PYTHONUNBUFFERED",
             sys.executable, "-m", "lazy_agentd", "--idle-timeout", "1"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.assertTrue(wait_for_port(port))
        self.assertEqual(get(port)[0], 200)
        out, _ = proc.communicate(timeout=10)
        self.assertIn("Activated via systemd socket passing", out)
        self.assertEqual(proc.returncode, 0, out)


if __name__ == "__main__":
    unittest.main()
