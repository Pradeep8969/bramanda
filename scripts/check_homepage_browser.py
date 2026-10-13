"""Local Chrome/CDP viewport checks, using only Python's standard library.

Start Django on 127.0.0.1:8008 first. Anonymous browsing only; no data mutation.
Screenshots are written to a temporary directory printed at completion.
"""

import base64
import json
import os
import secrets
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen


class DevTools:
    def __init__(self, url):
        parts = urlsplit(url)
        self.sock = socket.create_connection((parts.hostname, parts.port), timeout=15)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        self.sock.sendall(
            (
                f"GET {parts.path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n"
                f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        header = b""
        while not header.endswith(b"\r\n\r\n"):
            chunk = self.sock.recv(1)
            if not chunk:
                raise RuntimeError("Chrome closed the handshake connection")
            header += chunk
        assert header.startswith(b"HTTP/1.1 101 "), header
        self.serial = 0

    def read(self, size):
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise RuntimeError("Chrome closed the connection")
            data += chunk
        return data

    def call(self, method, params=None):
        self.serial += 1
        payload = json.dumps(
            {"id": self.serial, "method": method, "params": params or {}}
        ).encode()
        length = len(payload)
        header = (
            bytes([0x81, 0x80 | length])
            if length < 126
            else bytes([0x81, 0xFE]) + struct.pack("!H", length)
        )
        mask = secrets.token_bytes(4)
        self.sock.sendall(
            header
            + mask
            + bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        )
        while True:
            first, second = self.read(2)
            size = second & 0x7F
            if size == 126:
                size = struct.unpack("!H", self.read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.read(8))[0]
            body = self.read(size)
            if first & 0xF == 1:
                reply = json.loads(body)
                if reply.get("id") == self.serial:
                    if "error" in reply:
                        raise RuntimeError(reply["error"])
                    return reply.get("result", {})

    def evaluate(self, expression):
        result = self.call(
            "Runtime.evaluate", {"expression": expression, "returnByValue": True}
        )
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"])
        return result["result"].get("value")


def main():
    artifacts = Path(tempfile.mkdtemp(prefix="bramanda-home-"))
    chrome = (
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
        / "Google/Chrome/Application/chrome.exe"
    )
    process = subprocess.Popen(
        [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-port=9225",
            f'--user-data-dir={artifacts / "chrome-profile"}',
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    client = None
    try:
        for attempt in range(50):
            try:
                with urlopen("http://127.0.0.1:9225/json", timeout=1) as response:
                    targets = json.load(response)
                target = next(target for target in targets if target["type"] == "page")
                break
            except (OSError, StopIteration):
                time.sleep(0.2)
        else:
            raise RuntimeError("Chrome remote debugging did not start")
        client = DevTools(target["webSocketDebuggerUrl"])
        client.call("Page.enable")
        for width in (1440, 1024, 768, 390, 320):
            client.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": 1000,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            client.call("Page.navigate", {"url": "http://127.0.0.1:8008/"})
            for _ in range(50):
                if client.evaluate(
                    "document.readyState === 'complete' && !!document.querySelector('.home-hero')"
                ):
                    break
                time.sleep(0.1)
            client.evaluate(
                "document.querySelector('.home-stories').scrollIntoView({behavior:'instant'})"
            )
            for _ in range(50):
                if client.evaluate(
                    "[...document.images].every(img => img.complete && img.naturalWidth > 0)"
                ):
                    break
                time.sleep(0.1)
            metrics = client.evaluate(
                """(() => ({width: innerWidth, content: document.documentElement.scrollWidth,
                heading: document.querySelector('h1').getBoundingClientRect().right,
                imagesLoaded: [...document.images].every(img => img.complete && img.naturalWidth > 0)}))()"""
            )
            assert metrics["content"] <= width, metrics
            assert metrics["heading"] <= width, metrics
            assert metrics["imagesLoaded"], metrics
            client.evaluate(
                "document.querySelector('.home-stories').scrollIntoView({behavior:'instant'})"
            )
            time.sleep(0.2)
            measure = """(() => {
                const rect = el => {const r = el.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height};};
                const left = document.querySelector('.home-perspective');
                const right = document.querySelector('.home-details');
                const images = [...right.querySelectorAll('.home-details-artwork')];
                return {left:rect(left),right:rect(right),frame:rect(right.querySelector('.home-details-media')),
                    copy:rect(right.querySelector('.home-details-copy')),
                    logo:rect(left.querySelector('.home-perspective-logo img')),leftCopy:rect(left.querySelector('.home-perspective-copy')),
                    brightness:getComputedStyle(images[0]).filter,
                    visible:images.filter(img => Number(getComputedStyle(img).opacity) > .99).map(img => img.src),
                    layers:images.map(img => ({rect:rect(img),position:getComputedStyle(img).position,fit:getComputedStyle(img).objectFit})),
                    leftLink:!!left.querySelector('a'),rightLink:!!right.querySelector('a')};
            })()"""
            before = client.evaluate(measure)
            assert before["left"]["height"] == before["right"]["height"] == 320, before
            assert before["frame"] == before["right"], before
            assert len(before["visible"]) == 1, before
            assert before["leftLink"] and not before["rightLink"], before
            assert before["brightness"] == "brightness(1.1)", before
            assert (
                before["leftCopy"]["x"] + before["leftCopy"]["width"]
                <= before["logo"]["x"]
            ), before
            assert before["logo"]["y"] >= before["left"]["y"], before
            assert (
                before["logo"]["y"] + before["logo"]["height"]
                <= before["left"]["y"] + 320
            ), before
            for layer in before["layers"]:
                assert (
                    layer["position"] == "absolute" and layer["rect"]["height"] == 320
                ), before
                assert layer["rect"]["x"] >= before["right"]["x"], before
                assert (
                    layer["rect"]["x"] + layer["rect"]["width"]
                    <= before["right"]["x"] + before["right"]["width"]
                ), before
            if width > 700:
                assert before["left"]["y"] == before["right"]["y"], before
                assert before["left"]["width"] == before["right"]["width"], before
            else:
                assert before["right"]["y"] == before["left"]["y"] + 320, before
            time.sleep(6)
            after = client.evaluate(measure)
            for key in ("left", "right", "frame", "copy"):
                assert after[key] == before[key], (before, after)
            assert (
                len(after["visible"]) == 1 and after["visible"] == before["visible"]
            ), (before, after)
            print(
                json.dumps(
                    {
                        "bannerWidth": width,
                        "panelHeight": 320,
                        "fixedFrame": True,
                        "stationaryText": True,
                        "containedLogo": True,
                        "staticArtwork": True,
                    }
                )
            )
            if width < 1200:
                client.evaluate("document.querySelector('.menu-toggle').click()")
                assert client.evaluate(
                    "document.querySelector('.menu-toggle').getAttribute('aria-expanded') === 'true'"
                )
                client.call(
                    "Input.dispatchKeyEvent",
                    {"type": "keyDown", "key": "Escape", "code": "Escape"},
                )
                assert client.evaluate(
                    "document.querySelector('.menu-toggle').getAttribute('aria-expanded') === 'false'"
                )
            bounds = client.evaluate(
                "(() => {const r=document.querySelector('.home-stories').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()"
            )
            screenshot = client.call(
                "Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": True, "clip": bounds},
            )
            (artifacts / f"home-{width}.png").write_bytes(
                base64.b64decode(screenshot["data"])
            )
            print(json.dumps(metrics))
        print(f"Screenshots: {artifacts}")
    finally:
        if client:
            client.sock.close()
        process.terminate()
        process.wait(timeout=15)


if __name__ == "__main__":
    main()
