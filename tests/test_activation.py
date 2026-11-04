import os
import socket
import unittest

from lazy_agentd.activation import bind_socket, describe, listen_fds


class TestListenFds(unittest.TestCase):
    def setUp(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()

    def tearDown(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def test_no_env_means_no_sockets(self):
        self.assertEqual(listen_fds(env={}), [])

    def test_claims_socket_and_clears_env(self):
        env = {"LISTEN_PID": str(os.getpid()), "LISTEN_FDS": "1", "LISTEN_FDNAMES": "x"}
        fd = self.sock.detach()
        socks = listen_fds(env=env, start=fd)
        self.assertEqual(len(socks), 1)
        self.assertEqual(socks[0].family, socket.AF_INET)
        self.assertFalse(socks[0].get_inheritable())
        self.assertEqual(env, {})
        socks[0].close()

    def test_ignores_sockets_meant_for_another_pid(self):
        env = {"LISTEN_PID": str(os.getpid() + 1), "LISTEN_FDS": "1"}
        self.assertEqual(listen_fds(env=env, start=self.sock.fileno()), [])
        self.assertIn("LISTEN_FDS", env)

    def test_malformed_env(self):
        env = {"LISTEN_PID": str(os.getpid()), "LISTEN_FDS": "lots"}
        self.assertEqual(listen_fds(env=env), [])
        self.assertEqual(env, {})


class TestBindSocket(unittest.TestCase):
    def test_ipv4(self):
        s = bind_socket("127.0.0.1", 0)
        self.addCleanup(s.close)
        self.assertTrue(describe(s).startswith("127.0.0.1:"))

    @unittest.skipUnless(socket.has_ipv6, "no IPv6")
    def test_ipv6(self):
        try:
            s = bind_socket("::1", 0)
        except OSError:
            self.skipTest("IPv6 loopback unavailable")
        self.addCleanup(s.close)
        self.assertEqual(s.family, socket.AF_INET6)
        self.assertTrue(describe(s).startswith("[::1]:"))


if __name__ == "__main__":
    unittest.main()
