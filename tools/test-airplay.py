#!/usr/bin/env python3
"""Offline test of the AirPlay receiver's video path (no device, no GStreamer): python3 tools/test-airplay.py

Acceptance criteria of the screen mirroring (device/files/usr/local/bin/airplay); this file pins the ones that do
not need the hardware, tools/smoke-airplay.sh the speed on the device:
 1. UxPlay does not decode: its -vd ends the stream at fdsink on the pipe it is given, whole pictures in byte-stream.
 2. The drawer decodes in hardware straight into kmssink, nothing but a queue between them (anything else makes the
    decoder copy every picture: a Mac's 1080p then falls behind).
 3. A drawer started late gets the stream from the last SPS on, so it starts on a whole picture; an SPS split
    between two reads counts, and so does a Mac's (header byte 0x27).
 4. Past KEEP_MAX nothing more is kept until the next SPS; after the phone lets go (reset) nothing old is sent.
 5. A drawer that died is let go without stopping the stream; the next one gets the kept bytes again."""
import importlib.machinery
import importlib.util
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
AIRPLAY = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "airplay")
sys.dont_write_bytecode = True

loader = importlib.machinery.SourceFileLoader("airplay", AIRPLAY)
spec = importlib.util.spec_from_loader("airplay", loader)
airplay = importlib.util.module_from_spec(spec)
loader.exec_module(airplay)

SPS_IPHONE = b"\x00\x00\x00\x01\x67\x64\x00\x1f"
SPS_MAC = b"\x00\x00\x00\x01\x27\x64\x00\x2a"
PPS = b"\x00\x00\x00\x01\x68\xee\x3c\x80"
IDR = b"\x00\x00\x00\x01\x65" + b"\x88" * 50
P = b"\x00\x00\x00\x01\x41" + b"\x9a" * 30


def drain(fd):
    os.set_blocking(fd, False)
    out = b""
    try:
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            out += chunk
    except BlockingIOError:
        pass
    return out


class Pipe:
    def __enter__(self):
        self.r, self.w = os.pipe()
        return self

    def __exit__(self, *a):
        for fd in (self.r, self.w):
            try:
                os.close(fd)
            except OSError:
                pass


class UxPlayArgs(unittest.TestCase):
    def test_uxplay_writes_h264_to_the_pipe_and_does_not_decode(self):
        args = airplay.uxplay(7)
        vd = args[args.index("-vd") + 1]
        self.assertIn("fdsink fd=7 ", vd)
        self.assertIn("stream-format=byte-stream", vd)
        self.assertIn("alignment=au", vd)
        whole = " ".join(args)
        for decoder in ("decodebin", "v4l2h264dec", "avdec_h264", "-v4l2", "-bt709"):
            self.assertNotIn(decoder, whole)
        self.assertEqual(args[args.index("-vs") + 1], "fakesink")

    def test_sound_card_buffer_is_short_so_sound_keeps_up_with_the_picture(self):
        args = airplay.uxplay(7)
        sink = args[args.index("-as") + 1].split()
        self.assertEqual(sink[0], "alsasink")
        buffer_us = int(dict(p.split("=") for p in sink[1:])["buffer-time"])
        self.assertLess(buffer_us, 200000)   # alsasink's own default
        self.assertGreaterEqual(buffer_us, 40000)

    def test_drawer_decodes_straight_into_kmssink(self):
        args = airplay.drawer()
        launch = args[args.index("gst-launch-1.0") + 1:]
        elements = [a for a in launch if a == "fdsrc"] + [launch[i + 1] for i, a in enumerate(launch) if a == "!"]
        self.assertEqual(elements, ["fdsrc", "h264parse", "capssetter", "v4l2h264dec", "queue", "kmssink"])
        self.assertIn("fd=0", launch)
        self.assertIn("caps=video/x-h264,colorimetry=bt709", launch)


class RelayKeeps(unittest.TestCase):
    def test_late_drawer_starts_at_the_last_sps(self):
        relay = airplay.Relay()
        relay.feed(P * 3)                       # the middle of something: not kept
        self.assertIsNone(relay.kept)
        relay.feed(SPS_IPHONE + PPS + IDR + P)
        relay.feed(P * 2)
        with Pipe() as p:
            relay.attach(p.w)
            relay.feed(P)
            self.assertEqual(drain(p.r), SPS_IPHONE + PPS + IDR + P * 4)

    def test_a_newer_sps_replaces_what_was_kept(self):
        relay = airplay.Relay()
        relay.feed(SPS_IPHONE + PPS + IDR + P * 5)
        relay.feed(P + SPS_MAC + PPS + IDR)       # turned, or a Mac (0x27)
        self.assertEqual(bytes(relay.kept), SPS_MAC + PPS + IDR)

    def test_sps_start_code_split_between_reads(self):
        stream = P * 2 + SPS_MAC + PPS + IDR
        cut = len(P * 2) + 3                    # inside "00 00 00 01 27"
        relay = airplay.Relay()
        relay.feed(stream[:cut])
        relay.feed(stream[cut:])
        self.assertEqual(bytes(relay.kept), SPS_MAC + PPS + IDR)

    def test_too_much_is_not_kept_until_the_next_sps(self):
        relay = airplay.Relay()
        relay.feed(SPS_IPHONE + IDR)
        relay.feed(b"\x00\x00\x00\x01\x41" + b"\x01" * (airplay.KEEP_MAX + 1))
        self.assertIsNone(relay.kept)
        relay.feed(P)
        self.assertIsNone(relay.kept)
        relay.feed(SPS_IPHONE + IDR)
        self.assertEqual(bytes(relay.kept), SPS_IPHONE + IDR)

    def test_reset_forgets_the_old_stream(self):
        relay = airplay.Relay()
        relay.feed(SPS_IPHONE + IDR + P)
        relay.reset()
        relay.feed(P)
        with Pipe() as p:
            relay.attach(p.w)
            self.assertEqual(drain(p.r), b"")


class RelayDrawerDies(unittest.TestCase):
    def test_dead_drawer_is_let_go_and_the_next_gets_the_kept_bytes(self):
        relay = airplay.Relay()
        relay.feed(SPS_IPHONE + IDR)
        p1 = Pipe().__enter__()
        relay.attach(p1.w)
        os.close(p1.r)                          # the drawer died
        relay.feed(P)                           # must not raise
        self.assertIsNone(relay.out)
        os.close(p1.w)
        with Pipe() as p2:
            relay.attach(p2.w)
            self.assertEqual(drain(p2.r), SPS_IPHONE + IDR + P)


class SplashOnTheSwitch(unittest.TestCase):
    """The screen shows the boot picture, not black, while it changes hands."""

    def test_rows_land_pitch_apart(self):
        data = bytes(range(2 * 4)) * 2           # 2 x 2 pixels
        mem = bytearray(2 * 12)                  # rows 12 bytes apart, 4 bytes of padding
        airplay.put_rows(mem, data, 2, 2, 12)
        self.assertEqual(bytes(mem), data[:8] + b"\0" * 4 + data[8:] + b"\0" * 4)

    def test_unpadded_rows_are_copied_whole(self):
        data = b"\x01\x02\x03\x00" * 6
        mem = bytearray(len(data))
        airplay.put_rows(mem, data, 3, 2, 12)
        self.assertEqual(bytes(mem), data)

    def test_kept_picture_is_used_while_newer_than_the_png(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            png = os.path.join(d, "splash.png")
            open(png, "wb").close()
            os.utime(png, (1000, 1000))
            raw = os.path.join(d, "splash-2x1.xrgb")
            with open(raw, "wb") as f:
                f.write(b"\x10\x12\x18\x00" * 2)
            self.assertEqual(airplay.splash_pixels(2, 1, png, d), b"\x10\x12\x18\x00" * 2)

    def test_no_picture_gives_none_so_the_screen_stays_black(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(airplay.splash_pixels(2, 1, os.path.join(d, "none.png"), d))


if __name__ == "__main__":
    unittest.main(verbosity=2)
