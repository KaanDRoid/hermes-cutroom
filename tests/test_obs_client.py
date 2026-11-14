"""OBS recording over obs-websocket v5, against a small local test server.

The server speaks the real protocol (HTTP upgrade, masked client frames,
Hello/Identify with the documented SHA-256 authentication, Request/Response),
so the client is tested without OBS and without the optional SDK.
"""

import base64
import hashlib
import json
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path

from cutroom import integrations

PASSWORD = "local obs password"
SALT = "c2FsdA=="
CHALLENGE = "Y2hhbGxlbmdl"


def expected_auth(password):
    secret = base64.b64encode(hashlib.sha256((password + SALT).encode()).digest())
    return base64.b64encode(
        hashlib.sha256(secret + CHALLENGE.encode()).digest()
    ).decode()


def send_frame(conn, text):
    data = text.encode()
    header = bytes([0x81])
    if len(data) < 126:
        header += bytes([len(data)])
    elif len(data) < 65536:
        header += bytes([126]) + struct.pack(">H", len(data))
    else:
        header += bytes([127]) + struct.pack(">Q", len(data))
    conn.sendall(header + data)


def read_exact(conn, size):
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise ConnectionError
        data += chunk
    return data


def read_frame(conn):
    first, second = read_exact(conn, 2)
    assert second & 0x80, "client frames must be masked"
    length = second & 0x7F
    if length == 126:
        (length,) = struct.unpack(">H", read_exact(conn, 2))
    elif length == 127:
        (length,) = struct.unpack(">Q", read_exact(conn, 8))
    mask = read_exact(conn, 4)
    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(read_exact(conn, length)))
    return first & 0x0F, payload


class FakeObs:
    def __init__(self, recording_path, password=PASSWORD, padding=0, lag=0):
        self.recording_path = recording_path
        self.password = password
        self.padding = padding
        self.active = False
        # Real OBS starts and stops the output a moment after answering: the
        # first status requests still report the old state.
        self.lag = lag
        self.pending = 0
        self.requests = []
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen()
        self.port = self.socket.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.socket.accept()
            except OSError:
                return
            threading.Thread(target=self.client, args=(conn,), daemon=True).start()

    def client(self, conn):
        with conn:
            request = b""
            while b"\r\n\r\n" not in request:
                request += conn.recv(1024)
            headers = dict(
                line.split(": ", 1)
                for line in request.decode().split("\r\n")[1:]
                if ": " in line
            )
            accept = base64.b64encode(
                hashlib.sha1(
                    (
                        headers["Sec-WebSocket-Key"]
                        + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                    ).encode()
                ).digest()
            ).decode()
            assert headers.get("Sec-WebSocket-Protocol") == "obswebsocket.json"
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                    f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n"
                    "Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n"
                ).encode()
            )
            hello = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1}
            if self.password is not None:
                hello["authentication"] = {"challenge": CHALLENGE, "salt": SALT}
            send_frame(conn, json.dumps({"op": 0, "d": hello}))
            try:
                _, payload = read_frame(conn)
                identify = json.loads(payload)
                if self.password is not None and identify["d"].get(
                    "authentication"
                ) != expected_auth(self.password):
                    conn.sendall(bytes([0x88, 2]) + struct.pack(">H", 4009))
                    return
                send_frame(
                    conn, json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}})
                )
                while True:
                    opcode, payload = read_frame(conn)
                    if opcode == 8:
                        return
                    message = json.loads(payload)["d"]
                    self.requests.append(message["requestType"])
                    data = {}
                    if message["requestType"] == "StartRecord":
                        self.active, self.pending = True, self.lag
                    elif message["requestType"] == "StopRecord":
                        self.active, self.pending = False, self.lag
                        data = {"outputPath": str(self.recording_path)}
                    elif message["requestType"] == "GetRecordStatus":
                        shown = self.active
                        if self.pending:
                            self.pending -= 1
                            shown = not self.active
                        data = {
                            "outputActive": shown,
                            "outputPaused": False,
                            "outputTimecode": "00:00:02.000",
                            "padding": "x" * self.padding,
                        }
                    send_frame(
                        conn,
                        json.dumps(
                            {
                                "op": 7,
                                "d": {
                                    "requestType": message["requestType"],
                                    "requestId": message["requestId"],
                                    "requestStatus": {"result": True, "code": 100},
                                    "responseData": data,
                                },
                            }
                        ),
                    )
            except (ConnectionError, OSError):
                return

    def close(self):
        self.socket.close()


class ObsClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.recording = Path(temporary.name) / "2026-11-14 02-30-00.mkv"
        self.recording.write_bytes(b"recorded by obs")

    def server(self, **kwargs):
        obs = FakeObs(self.recording, **kwargs)
        self.addCleanup(obs.close)
        return obs

    def test_record_and_stop_return_the_recorded_file(self):
        obs = self.server()
        status = integrations.obs_record("status", port=obs.port, password=PASSWORD)
        self.assertFalse(status["recording"])
        started = integrations.obs_record(
            "start", port=obs.port, password=PASSWORD, confirmed=True
        )
        self.assertTrue(started["recording"])
        stopped = integrations.obs_record(
            "stop", port=obs.port, password=PASSWORD, confirmed=True
        )
        self.assertEqual(stopped["output"], str(self.recording))
        self.assertTrue(stopped["file_verified"])
        self.assertIn("StartRecord", obs.requests)
        self.assertIn("StopRecord", obs.requests)

    def test_start_and_stop_wait_for_obs_to_change_state(self):
        obs = self.server(lag=3)
        started = integrations.obs_record(
            "start", port=obs.port, password=PASSWORD, confirmed=True
        )
        self.assertTrue(started["recording"])
        stopped = integrations.obs_record(
            "stop", port=obs.port, password=PASSWORD, confirmed=True
        )
        self.assertFalse(stopped["recording"])

    def test_large_responses_are_read_whole(self):
        obs = self.server(padding=70_000)
        status = integrations.obs_record("status", port=obs.port, password=PASSWORD)
        self.assertEqual(status["timecode"], "00:00:02.000")

    def test_obs_without_a_password_is_accepted(self):
        obs = self.server(password=None)
        self.assertFalse(integrations.obs_record("status", port=obs.port)["recording"])

    def test_a_wrong_password_is_named(self):
        obs = self.server()
        with self.assertRaisesRegex(RuntimeError, "password") as caught:
            integrations.obs_record("status", port=obs.port, password="wrong")
        self.assertNotIn("wrong", str(caught.exception))

    def test_closed_obs_is_explained(self):
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        with self.assertRaisesRegex(RuntimeError, "Open OBS"):
            integrations.obs_record("status", port=port, password=PASSWORD)

    def test_recording_needs_consent_and_loopback(self):
        with self.assertRaises(PermissionError):
            integrations.obs_record("start", password=PASSWORD)
        with self.assertRaises(ValueError):
            integrations.obs_record("status", host="192.168.1.5")

    def test_the_sdk_is_not_needed(self):
        obs = self.server()
        import sys
        from unittest.mock import patch

        with patch.dict(sys.modules, {"obsws_python": None}):
            self.assertFalse(
                integrations.obs_record("status", port=obs.port, password=PASSWORD)[
                    "recording"
                ]
            )


if __name__ == "__main__":
    unittest.main()
