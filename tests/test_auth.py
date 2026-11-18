import asyncio
import base64
import unittest
from unittest.mock import patch

from dashb import auth
from dashb.probe import lhm

# Importing dashb.server builds the metric catalog. Pretend no LHM helper exists
# so the test run never launches the elevated helper (and its UAC prompt).
lhm._client, lhm._client_checked = None, True
from dashb import server  # noqa: E402


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


class PasswordHashTests(unittest.TestCase):
    def test_round_trip(self):
        encoded = auth.hash_password("hunter2")
        self.assertTrue(encoded.startswith("scrypt$"))
        self.assertNotIn("hunter2", encoded)
        self.assertTrue(auth.verify_password("hunter2", encoded))
        self.assertFalse(auth.verify_password("hunter3", encoded))

    def test_salted(self):
        self.assertNotEqual(auth.hash_password("same"), auth.hash_password("same"))

    def test_malformed_or_hostile_hashes_are_rejected(self):
        good = auth.hash_password("pw").split("$")
        for bad in [
            None,
            "",
            "plaintext",
            "$".join(["bcrypt", *good[1:]]),
            "$".join([good[0], str(2**30), *good[2:]]),  # memory bomb
            "$".join([good[0], "1000", *good[2:]]),  # n not a power of two
            "$".join([*good[:4], "!!notbase64", good[5]]),
        ]:
            with self.subTest(bad=bad):
                self.assertFalse(auth.is_valid_hash(bad))
                self.assertFalse(auth.verify_password("pw", bad))


class ServerAuthTests(unittest.TestCase):
    def tearDown(self):
        server.configure_auth(None, None)

    def check(self, header):
        return asyncio.run(server.check_basic_auth(header))

    def test_disabled_without_username(self):
        server.configure_auth(None, None)
        self.assertFalse(server.auth_enabled())
        self.assertTrue(self.check(None))

    def test_verifies_against_hash_and_caches_only_successes(self):
        server.configure_auth("u", auth.hash_password("p"))
        with patch.object(
            server.auth, "verify_password", wraps=auth.verify_password
        ) as verify:
            self.assertFalse(self.check(basic("u", "x")))
            self.assertFalse(self.check(basic("u", "x")))
            self.assertFalse(self.check(basic("x", "p")))
            self.assertFalse(self.check("Basic !!!"))
            self.assertFalse(self.check(None))
            self.assertEqual(verify.call_count, 3)  # failures always pay full cost

            for _ in range(5):
                self.assertTrue(self.check(basic("u", "p")))
            self.assertEqual(verify.call_count, 4)  # success verified once

    def test_fails_closed_with_missing_or_corrupt_hash(self):
        for bad_hash in (None, "garbage"):
            with self.subTest(bad_hash=bad_hash):
                server.configure_auth("u", bad_hash)
                self.assertTrue(server.auth_enabled())
                self.assertFalse(self.check(basic("u", "")))
                self.assertFalse(server.check_auth_cookie(server.auth_cookie_value()))

    def test_cookie_is_invalidated_by_password_change(self):
        server.configure_auth("u", auth.hash_password("old"))
        cookie = server.auth_cookie_value()
        self.assertTrue(server.check_auth_cookie(cookie))
        server.configure_auth("u", auth.hash_password("new"))
        self.assertFalse(server.check_auth_cookie(cookie))


class HttpAuthFlowTests(unittest.TestCase):
    def tearDown(self):
        server.configure_auth(None, None)

    def test_basic_auth_issues_cookie_that_then_suffices(self):
        server.configure_auth("u", auth.hash_password("p"))

        async def scenario():
            client = server.app.test_client()
            denied = await client.get("/api/themes")
            wrong = await client.get(
                "/api/themes", headers={"Authorization": basic("u", "x")}
            )
            ok = await client.get(
                "/api/themes", headers={"Authorization": basic("u", "p")}
            )
            via_cookie = await client.get("/api/themes")
            return denied, wrong, ok, via_cookie

        denied, wrong, ok, via_cookie = asyncio.run(scenario())
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertNotIn("Set-Cookie", wrong.headers)
        self.assertEqual(ok.status_code, 200)
        self.assertIn(server.AUTH_COOKIE_NAME, ok.headers.get("Set-Cookie", ""))
        self.assertEqual(via_cookie.status_code, 200)


if __name__ == "__main__":
    unittest.main()
