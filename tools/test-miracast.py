#!/usr/bin/env python3
"""Offline test of the Miracast receiver (no device, no Wi-Fi, no GStreamer): python3 tools/test-miracast.py

Acceptance criteria of Win+K casting (device/files/usr/local/bin/miracast); the screen, the sound and the
Wi-Fi advertisement need the device, this file pins what does not:
 1. MICE: a SOURCE_READY gives the friendly name and the RTSP port, whole or split across reads, several in one
    read; a cut-off TLV and an unknown command do no harm.
 2. The WSC vendor extension has Microsoft's id, the MICE capability, the host name and the IPv4 address; clearing
    it is an empty array.
 3. The advertiser sets everything once, renews the listen, puts it all back when wpa_supplicant lost it or the IP
    or object path changed, stops listening while paused and clears everything at shutdown.
 4. RTSP: the sink answers M1, sends M2, answers M3 with only the parameters asked, takes M4, sends M6 with its
    client_port and M7, answers keep-alives and a TEARDOWN trigger; CRLF, bodies, split and joined messages.
 5. A real Windows' M3 list is answered (CEA-only formats, wfd_idr_request_capability 1), the friendly name is
    UTF-16LE, and the keyframe watchdog asks for an IDR every second until the first picture and then only when the
    stream breaks, counting the broken-NAL lines instead of logging them.
 6. The drawer decodes straight into kmssink with nothing but one queue between, and its audio branch is linked
    by caps.
 7. A session runs against a fake PC: the screen is taken before PLAY, STOP_PROJECTION or a close gives it back, a
    dead drawer is restarted with an IDR request; a second source and AirPlay's flag exclude a session; airplay
    ignores a phone while miracast has the screen.
 8. A drawer that never reads or never answers cannot take the receiver down: the relay writes without waiting and
    holds a payload whole in a bounded backlog when the pipe is full and drops it whole when that is full too
    (counted, a keyframe is asked for), a drawer with no picture is
    restarted once and then the session ends, a drawer that ignores SIGTERM is killed, and TEARDOWN and
    STOP_PROJECTION are still handled while it is stuck.
 9. The boot picture is painted when the screen is taken, black when that fails; the sound can be held back by
    AUDIO_DELAY_MS or the file miracast-audio-delay, and nothing else in the drawer changes; the latency tracer is gone.
Everything real (systemctl, wpa_cli, busctl, the drawer) is replaced by fakes."""
import importlib.machinery
import importlib.util
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BIN = os.path.join(ROOT, "device", "files", "usr", "local", "bin")
sys.dont_write_bytecode = True


def load(name):
    loader = importlib.machinery.SourceFileLoader(name, os.path.join(BIN, name))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


miracast = load("miracast")
airplay = load("airplay")


def tlv(t, v):
    return bytes([t]) + len(v).to_bytes(2, "big") + v


def mice(command, *tlvs, version=1):
    body = b"".join(tlvs)
    return (4 + len(body)).to_bytes(2, "big") + bytes([version, command]) + body


def source_ready(name="TEST-PC", port=7236):
    return mice(1, tlv(0, name.encode("utf-16-le")), tlv(2, port.to_bytes(2, "big")), tlv(3, bytes(range(16))))


class Mice(unittest.TestCase):
    def test_source_ready_gives_name_and_port(self):
        msg = source_ready()
        self.assertEqual(len(msg), 45)
        [(command, tlvs)] = miracast.MiceStream().feed(msg)
        self.assertEqual(command, miracast.MICE_SOURCE_READY)
        self.assertEqual(miracast.source_ready(tlvs), ("TEST-PC", 7236))
        self.assertEqual(dict(tlvs)[3], bytes(range(16)))

    def test_split_and_joined_messages(self):
        stream = miracast.MiceStream()
        msg = source_ready("A-PC", 9999) + mice(2)
        got = []
        for i in range(len(msg)):           # a byte at a time
            got += stream.feed(msg[i:i + 1])
        self.assertEqual([c for c, _ in got], [1, 2])
        self.assertEqual(miracast.source_ready(got[0][1]), ("A-PC", 9999))
        self.assertEqual([c for c, _ in miracast.MiceStream().feed(msg)], [1, 2])

    def test_no_port_means_7236_and_cut_off_tlv_is_dropped(self):
        self.assertEqual(miracast.source_ready([(0, "X".encode("utf-16-le"))]), ("X", 7236))
        body = tlv(0, "ab".encode("utf-16-le")) + b"\x02\x00\x09\x01"   # a TLV that says 9 bytes and has 1
        self.assertEqual(miracast.parse_tlvs(body), [(0, "ab".encode("utf-16-le"))])

    def test_friendly_name_is_utf16_little_endian_with_or_without_bom(self):
        self.assertEqual(miracast.source_ready([(0, b"T\x00E\x00S\x00T\x00")])[0], "TEST")
        self.assertEqual(miracast.source_ready([(0, b"\xff\xfeT\x00E\x00S\x00T\x00")])[0], "TEST")
        self.assertEqual(miracast.source_ready([(0, "Zü".encode("utf-16-le") + b"\x00\x00")])[0], "Zü")

    def test_unknown_command_is_returned_not_raised(self):
        self.assertEqual(miracast.MiceStream().feed(mice(9, tlv(7, b"zz"))), [(9, [(7, b"zz")])])

    def test_impossible_size_raises(self):
        with self.assertRaises(ValueError):
            miracast.MiceStream().feed(b"\x00\x02\x01\x01")


class VendorExtension(unittest.TestCase):
    def test_bytes(self):
        ext = miracast.vendor_extension("mediastick", "192.168.1.14")
        want = (bytes.fromhex("000137") + bytes.fromhex("2001000105")
                + bytes.fromhex("2002000a") + b"mediastick"
                + bytes.fromhex("2005000c") + b"192.168.1.14")
        self.assertEqual(ext, want)

    def test_non_ascii_host_name_is_dropped_to_ascii(self):
        self.assertIn(bytes.fromhex("20020002") + b"ab", miracast.vendor_extension("aéb", "10.0.0.1"))

    def test_busctl_arguments(self):
        args = miracast.vendor_args(b"\x00\x01\x37")
        self.assertEqual(args, ["a{sv}", "1", "VendorExtension", "aay", "1", "3", "0", "1", "55"])
        self.assertEqual(miracast.vendor_args(None), ["a{sv}", "1", "VendorExtension", "aay", "0"])


class FakeWpa:
    """wpa_cli, busctl and ip as wpa_supplicant would answer them."""

    def __init__(self):
        self.calls = []
        self.wifi_display = ""
        self.path = "/fi/w1/wpa_supplicant1/Interfaces/0"
        self.ip = "192.168.1.14"

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[0] == "ip":
            return 0, "3: wlan0    inet %s/24 brd 192.168.1.255 scope global dynamic wlan0\n" % self.ip if self.ip else ""
        if cmd[0] == "busctl" and cmd[1] == "call":
            return 0, 'o "%s"\n' % self.path
        if cmd[0] == "wpa_cli":
            args = cmd[cmd.index(miracast.P2P_DEV) + 1:]
            if args[:2] == ["set", "wifi_display"]:
                self.wifi_display = args[2]
            if args[:2] == ["get", "wifi_display"]:
                return 0, self.wifi_display + "\n"
        return 0, ""

    def wpa(self):
        return [c[c.index(miracast.P2P_DEV) + 1:] for c in self.calls if c[0] == "wpa_cli"]

    def sets(self):
        return [c for c in self.calls if c[0] == "busctl" and c[1] == "set-property"]

    def forget(self):
        self.calls.clear()


class AdvertiserTest(unittest.TestCase):
    def setUp(self):
        self.w = FakeWpa()
        self.adv = miracast.Advertiser(self.w, "Media Stick", "mediastick")

    def test_first_tick_sets_everything_and_listens(self):
        self.adv.tick(0)
        wpa = self.w.wpa()
        self.assertIn(["set", "device_name", "Media Stick"], wpa)
        self.assertIn(["set", "device_type", "7-0050F204-1"], wpa)
        self.assertIn(["wfd_subelem_set", "0", "000600111c440032"], wpa)
        self.assertLess(wpa.index(["wfd_subelem_set", "0", "000600111c440032"]), wpa.index(["set", "wifi_display", "1"]))
        self.assertEqual(wpa[-1], ["p2p_listen", str(miracast.LISTEN_SECS)])
        [setp] = self.w.sets()
        self.assertEqual(setp[2], "fi.w1.wpa_supplicant1")
        self.assertEqual(setp[3], self.w.path)
        self.assertEqual(setp[4:7], ["fi.w1.wpa_supplicant1.Interface.P2PDevice", "P2PDeviceConfig", "a{sv}"])
        data = bytes(int(x) for x in setp[-len(miracast.vendor_extension("mediastick", "192.168.1.14")):])
        self.assertEqual(data, miracast.vendor_extension("mediastick", "192.168.1.14"))

    def test_nothing_again_until_the_listen_runs_out(self):
        self.adv.tick(0)
        self.w.forget()
        self.adv.tick(5)
        self.assertEqual(self.w.wpa(), [["get", "wifi_display"]])
        self.assertEqual(self.w.sets(), [])
        self.adv.tick(miracast.LISTEN_RENEW + 1)
        self.assertIn(["p2p_listen", str(miracast.LISTEN_SECS)], self.w.wpa())
        self.assertEqual(self.w.sets(), [])

    def test_wpa_supplicant_restart_is_put_back(self):
        self.adv.tick(0)
        self.w.wifi_display = ""        # restarted: the runtime state is gone
        self.w.forget()
        self.adv.tick(5)
        self.assertIn(["set", "wifi_display", "1"], self.w.wpa())
        self.assertEqual(len(self.w.sets()), 1)
        self.assertIn(["p2p_listen", str(miracast.LISTEN_SECS)], self.w.wpa())

    def test_new_ip_or_object_path_is_put_back(self):
        self.adv.tick(0)
        for attr, value in (("ip", "192.168.1.77"), ("path", "/fi/w1/wpa_supplicant1/Interfaces/3")):
            self.w.forget()
            setattr(self.w, attr, value)
            self.adv.tick(1)
            self.assertEqual(len(self.w.sets()), 1, attr)
        self.assertIn(b"192.168.1.77", bytes(int(x) for x in self.w.sets()[0][12:]))

    def test_no_wifi_address_sets_nothing(self):
        self.w.ip = None
        self.adv.tick(0)
        self.assertEqual(self.w.sets(), [])
        self.assertEqual(self.w.wpa(), [])

    def test_paused_stops_listening_and_keeps_quiet(self):
        self.adv.tick(0)
        self.w.forget()
        self.adv.pause()
        self.assertEqual(self.w.wpa(), [["p2p_stop_find"]])
        self.w.forget()
        self.adv.tick(100)
        self.assertEqual(self.w.calls, [])
        self.adv.resume()
        self.adv.tick(101)
        self.assertIn(["p2p_listen", str(miracast.LISTEN_SECS)], self.w.wpa())

    def test_shutdown_clears_everything(self):
        self.adv.tick(0)
        self.w.forget()
        self.adv.shutdown()
        [setp] = self.w.sets()
        self.assertEqual(setp[-5:], ["a{sv}", "1", "VendorExtension", "aay", "0"])
        self.assertEqual(self.w.wpa(), [["set", "wifi_display", "0"], ["p2p_stop_find"]])


# what a real Windows 11 asks in M3 (names only), in its order
M3_ASKED = ["wfd_video_formats", "wfd_audio_codecs", "wfd_client_rtp_ports", "wfd_display_edid",
            "wfd_connector_type", "wfd_uibc_capability", "wfd2_rotation_capability", "wfd2_video_formats",
            "wfd2_audio_codecs", "wfd2_video_stream_control", "wfd_idr_request_capability",
            "intel_friendly_name", "intel_sink_manufacturer_name", "intel_sink_model_name",
            "intel_sink_version", "intel_sink_device_URL", "microsoft_latency_management_capability",
            "microsoft_format_change_capability", "microsoft_diagnostics_capability", "microsoft_cursor",
            "microsoft_rtcp_capability", "microsoft_video_formats", "microsoft_max_bitrate",
            "microsoft_multiscreen_projection", "microsoft_audio_mute", "microsoft_custom_video_formats",
            "microsoft_color_space_conversion"]
M4_BODY = ("wfd_video_formats: 00 00 01 10 00000080 00000000 00000000 00 0000 0000 00 none none\r\n"
           "wfd_audio_codecs: AAC 00000001 00\r\n"
           "wfd_presentation_URL: rtsp://192.168.1.50/wfd1.0/streamid=0 none\r\n"
           "wfd_client_rtp_ports: RTP/AVP/UDP;unicast 19000 0 mode=play\r\n")


def request(method, uri, cseq, headers=(), body=""):
    return miracast.rtsp_bytes("%s %s RTSP/1.0" % (method, uri), [("CSeq", cseq)] + list(headers), body)


def response(cseq, headers=(), body="", status="200 OK"):
    return miracast.rtsp_bytes("RTSP/1.0 " + status, [("CSeq", cseq)] + list(headers), body)


class Collect:
    def __init__(self):
        self.buf = bytearray()
        self.msgs = []

    def __call__(self, data):
        self.buf += data
        self.msgs += miracast.take_messages(self.buf)


class RtspParsing(unittest.TestCase):
    def test_body_by_content_length_and_bare_lf(self):
        buf = bytearray(b"SET_PARAMETER rtsp://x RTSP/1.0\nCSeq: 4\nContent-Length: 5\n\nab\r\ncRTSP/1.0 200 OK\r\n")
        [m] = miracast.take_messages(buf)
        self.assertEqual((m.method, m.cseq, m.body), ("SET_PARAMETER", "4", "ab\r\nc"))
        self.assertEqual(bytes(buf), b"RTSP/1.0 200 OK\r\n")   # the next one is not whole yet

    def test_response_status(self):
        [m] = miracast.take_messages(bytearray(b"RTSP/1.0 454 Session Not Found\r\nCSeq: 2\r\n\r\n"))
        self.assertTrue(m.response)
        self.assertEqual(m.status, 454)

    def test_cut_off_body_waits(self):
        buf = bytearray(request("GET_PARAMETER", "rtsp://localhost/wfd1.0", 3, body="wfd_video_formats\r\n")[:-4])
        self.assertEqual(miracast.take_messages(buf), [])
        buf += b"ts\r\n"
        self.assertEqual(len(miracast.take_messages(buf)), 1)


EDID_LINE = miracast.edid_value(miracast.build_edid())


class RtspAnswers(unittest.TestCase):
    def sink(self):
        out = Collect()
        return miracast.RtspSink(out, 19000, log=lambda *a: None, edid=lambda: EDID_LINE), out

    def test_m3_answers_only_what_was_asked(self):
        sink, out = self.sink()
        sink.feed(request("GET_PARAMETER", "rtsp://localhost/wfd1.0", 7, body="wfd_video_formats\r\nwfd_client_rtp_ports\r\n"))
        [m] = out.msgs
        self.assertEqual(m.status, 200)
        self.assertEqual(m.cseq, "7")
        self.assertEqual(m.headers["content-type"], "text/parameters")
        self.assertEqual(m.body, "wfd_video_formats: %s\r\nwfd_client_rtp_ports: RTP/AVP/UDP;unicast 19000 0 mode=play\r\n"
                         % miracast.VIDEO_FORMATS)

    def test_m3_offers_1080p30_when_the_switch_file_exists(self):
        with Rig():
            sink, out = self.sink()
            open(miracast.FPS30_FLAG, "w").close()
            sink.feed(request("GET_PARAMETER", "rtsp://localhost/wfd1.0", 5, body="wfd_video_formats\r\n"))
            fields = out.msgs[0].body.split(": ", 1)[1].split()
            self.assertEqual(fields[0], "38")               # native: CEA index 7, 1080p30
            self.assertEqual(" ".join(fields), miracast.VIDEO_FORMATS_30)
            self.assertEqual(" ".join(fields), "38 00 01 10 000000ab 00000000 00000000 06 0000 0000 00 none none")
            self.assertEqual(int(fields[4], 16) >> 8 & 1, 0)

    def test_m3_offers_1080p60_cbp_by_default(self):
        with Rig():
            sink, out = self.sink()
            sink.feed(request("GET_PARAMETER", "rtsp://localhost/wfd1.0", 5, body="wfd_video_formats\r\n"))
            value = out.msgs[0].body.split(": ", 1)[1].strip()
            self.assertEqual(value, miracast.VIDEO_FORMATS)
            self.assertEqual(value, "40 00 01 10 000001eb 00000000 00000000 06 0000 0000 00 none none")

    def m3_video_formats(self, profile, fps30):
        with Rig():
            sink, out = self.sink()
            if profile is not None:
                with open(miracast.PROFILE_FLAG, "w") as f:
                    f.write(profile)
            if fps30:
                open(miracast.FPS30_FLAG, "w").close()
            sink.feed(request("GET_PARAMETER", "rtsp://localhost/wfd1.0", 5, body="wfd_video_formats\r\n"))
            return out.msgs[0].body.split(": ", 1)[1].strip()

    def test_m3_profile_follows_the_switch_file(self):
        for fps30, native, cea in ((False, "40", "000001eb"), (True, "38", "000000ab")):
            for text, profile in (("cbp\n", "01"), ("chp", "02"), ("both", "03"), ("CHP\n", "02"),
                                  (None, "01"), ("", "01"), ("high", "01"), ("02", "01")):
                self.assertEqual(self.m3_video_formats(text, fps30),
                                 "%s 00 %s 10 %s 00000000 00000000 06 0000 0000 00 none none" % (native, profile, cea),
                                 (text, fps30))
        self.assertEqual(self.m3_video_formats("chp", True),
                         "38 00 02 10 000000ab 00000000 00000000 06 0000 0000 00 none none")
        self.assertEqual(self.m3_video_formats(None, True),
                         "38 00 01 10 000000ab 00000000 00000000 06 0000 0000 00 none none")
        self.assertEqual(self.m3_video_formats(None, False), miracast.VIDEO_FORMATS)

    def test_m3_full_list_as_windows_sends_it(self):
        sink, out = self.sink()
        sink.feed(request("GET_PARAMETER", "rtsp://localhost/wfd1.0", 2, body="".join(n + "\r\n" for n in M3_ASKED)))
        got = dict(l.split(": ", 1) for l in out.msgs[0].body.splitlines())
        self.assertEqual(list(got), M3_ASKED)
        self.assertEqual(got["wfd_audio_codecs"], "AAC 00000001 00")
        for name in M3_ASKED:
            if name.startswith(("wfd2_", "intel_", "microsoft_")) and not name.startswith(
                    ("microsoft_latency", "microsoft_format_change", "microsoft_max_bitrate",
                     "microsoft_video_formats")):
                self.assertEqual(got[name], "none", name)
        self.assertEqual(got["wfd_uibc_capability"], "none")
        self.assertEqual(got["microsoft_max_bitrate"], "20000000")
        self.assertEqual(got["microsoft_video_formats"], "000000000000")
        self.assertEqual(got["wfd_display_edid"], EDID_LINE)       # never none
        self.assertEqual(got["wfd_idr_request_capability"], "1")
        self.assertEqual(got["wfd_connector_type"], "05")
        self.assertEqual(got["wfd_video_formats"], "40 00 01 10 000001eb 00000000 00000000 06 0000 0000 00 none none")
        fields = got["wfd_video_formats"].split()
        self.assertEqual(len(fields), 13)
        self.assertEqual(int(fields[0], 16), 8 << 3)           # native: CEA table (0), index 8 = 1080p60
        self.assertEqual(int(fields[4], 16) >> 8 & 1, 1)       # CEA bit 8: 1920x1080p60 by default
        self.assertEqual(int(fields[4], 16) >> 6 & 1, 1)       # CEA bit 6: and 1280x720p60
        self.assertEqual(int(fields[4], 16) >> 7 & 1, 1)       # CEA bit 7: 1920x1080p30
        self.assertEqual((int(fields[5], 16), int(fields[6], 16)), (0, 0))   # no VESA, no handheld
        self.assertEqual(int(fields[2], 16) & 3, 1)            # CBP only

    def test_keep_alive_is_answered_with_nothing(self):
        sink, out = self.sink()
        sink.feed(request("GET_PARAMETER", "rtsp://localhost/wfd1.0", 9))
        [m] = out.msgs
        self.assertEqual((m.status, m.cseq, m.body), (200, "9", ""))

    def test_m1_is_answered_and_m2_sent_once(self):
        sink, out = self.sink()
        sink.feed(request("OPTIONS", "*", 1, [("Require", "org.wfa.wfd1.0")]))
        sink.feed(request("OPTIONS", "*", 2))
        first, m2, second = out.msgs
        self.assertEqual(first.headers["public"], "org.wfa.wfd1.0, GET_PARAMETER, SET_PARAMETER")
        self.assertEqual((m2.method, m2.uri, m2.headers["require"]), ("OPTIONS", "*", "org.wfa.wfd1.0"))
        self.assertEqual(second.status, 200)
        self.assertEqual(len(out.msgs), 3)

    def test_messages_split_and_joined(self):
        sink, out = self.sink()
        data = request("OPTIONS", "*", 1) + request("GET_PARAMETER", "rtsp://localhost/wfd1.0", 2, body="wfd_connector_type\r\n")
        sink.feed(data[:7])
        sink.feed(data[7:40])
        sink.feed(data[40:])
        self.assertEqual([m.status or m.method for m in out.msgs], [200, "OPTIONS", 200])
        self.assertIn("wfd_connector_type: 05", out.msgs[2].body)

    def test_unknown_method_is_not_implemented(self):
        sink, out = self.sink()
        sink.feed(request("DESCRIBE", "rtsp://x", 3))
        self.assertEqual(out.msgs[0].status, 501)

    def test_m4_records_the_choice(self):
        sink, out = self.sink()
        sink.feed(request("SET_PARAMETER", "rtsp://localhost/wfd1.0", 4, body=M4_BODY))
        self.assertEqual(out.msgs[0].status, 200)
        self.assertEqual(sink.url, "rtsp://192.168.1.50/wfd1.0/streamid=0")
        self.assertTrue(sink.video.startswith("00 00 01 10 00000080"))
        self.assertEqual(sink.audio, "AAC 00000001 00")
        self.assertEqual(miracast.describe_video(sink.video), "1920x1080p30 CBP")
        self.assertEqual(miracast.describe_video(sink.video.replace("00000080", "00000100")), "1920x1080p60 CBP")
        self.assertEqual(miracast.describe_video(
            "00 00 01 10 00000000 00000008 00000000 00 0000 0000 00 none none"), "1024x768p60 CBP")
        self.assertEqual(miracast.describe_video("garbage"), "garbage")

    def test_m4_with_chp_is_logged_as_chp(self):
        lines = []
        sink = miracast.RtspSink(Collect(), 19000, log=lambda *a: lines.append(" ".join(map(str, a))), edid=lambda: EDID_LINE)
        sink.feed(request("SET_PARAMETER", "rtsp://localhost/wfd1.0", 4, body=M4_BODY.replace("00 00 01 10", "00 00 02 10", 1)))
        self.assertEqual(miracast.describe_video(sink.video), "1920x1080p30 CHP")
        self.assertTrue(any("M4: video 1920x1080p30 CHP," in l for l in lines), lines)

    def test_idr_request_is_a_sink_to_source_set_parameter_and_its_200_changes_nothing(self):
        sink, out = self.sink()
        sink.request_idr("test")
        [m] = out.msgs
        self.assertEqual((m.method, m.uri), ("SET_PARAMETER", "rtsp://localhost/wfd1.0"))
        self.assertEqual(m.headers["content-type"], "text/parameters")
        self.assertEqual(m.body, "wfd_idr_request\r\n")
        self.assertEqual(m.headers["content-length"], str(len(m.body)))
        sink.feed(response(m.cseq))
        sink.feed(request("SET_PARAMETER", "rtsp://localhost/wfd1.0", 4, [], "wfd_trigger_method: SETUP\r\n"))
        setup = [x for x in out.msgs if x.method == "SETUP"][0]
        self.assertEqual(setup.cseq, "2")                  # our own CSeq went on counting
        self.assertIsNone(sink.ended)


class FakePc:
    """A Windows PC's RTSP server, in a thread, playing the source's side of the dialogue."""

    def __init__(self, on_play=None, mice_after_play=None):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.buf = bytearray()
        self.seen = {}
        self.error = None
        self.on_play = on_play or (lambda: None)
        self.keep_going = threading.Event()   # set by a test that wants the dialogue to go on after PLAY
        self.thread = threading.Thread(target=self.guard, daemon=True)
        self.thread.start()

    def read(self, n):
        out = []
        while len(out) < n:
            out += miracast.take_messages(self.buf)
            if len(out) < n:
                data = self.c.recv(65536)
                if not data:
                    raise EOFError("the sink closed")
                self.buf += data
        return out

    def guard(self):
        try:
            self.c, _ = self.srv.accept()
            self.c.settimeout(5)
            self.run()
        except Exception as e:   # a failing step is reported by the test that waits for it
            self.error = repr(e)

    def run(self):
        c, seen = self.c, self.seen
        c.sendall(request("OPTIONS", "*", 1, [("Require", "org.wfa.wfd1.0")]))                       # M1
        msgs = self.read(2)
        seen["m1_answer"] = next(m for m in msgs if m.response)
        seen["m2"] = next(m for m in msgs if not m.response)
        c.sendall(response(seen["m2"].cseq, [("Public", "org.wfa.wfd1.0, SETUP, TEARDOWN, PLAY, PAUSE, "
                                              "GET_PARAMETER, SET_PARAMETER")]))
        c.sendall(request("GET_PARAMETER", "rtsp://localhost/wfd1.0", 2, [], "".join(n + "\r\n" for n in M3_ASKED)))
        seen["m3"] = self.read(1)[0]
        c.sendall(request("SET_PARAMETER", "rtsp://localhost/wfd1.0", 3, [], M4_BODY))
        seen["m4_answer"] = self.read(1)[0]
        c.sendall(request("SET_PARAMETER", "rtsp://localhost/wfd1.0", 4, [], "wfd_trigger_method: SETUP\r\n"))
        msgs = self.read(2)
        seen["m5_answer"] = next(m for m in msgs if m.response)
        seen["m6"] = setup = next(m for m in msgs if not m.response)
        c.sendall(response(setup.cseq, [("Session", "7F3A9C21;timeout=30"),
                                        ("Transport", "RTP/AVP/UDP;unicast;client_port=19000;server_port=5000")]))
        seen["m7"] = play = self.read(1)[0]
        seen["at_play"] = self.on_play()
        c.sendall(response(play.cseq))
        seen["idr"] = idr = self.read(1)[0]
        c.sendall(response(idr.cseq))
        c.sendall(request("GET_PARAMETER", "rtsp://localhost/wfd1.0", 5))                            # keep-alive
        seen["keepalive_answer"] = self.read(1)[0]
        c.sendall(request("SET_PARAMETER", "rtsp://localhost/wfd1.0", 6, [], "wfd_trigger_method: TEARDOWN\r\n"))
        msgs = self.read(2)
        seen["m8_answer"] = next(m for m in msgs if m.response)
        seen["teardown"] = next(m for m in msgs if not m.response)
        self.done = True


def pump(sock, sink, seconds=5):
    sock.settimeout(0.2)
    end = time.monotonic() + seconds
    while not sink.ended and time.monotonic() < end:
        try:
            data = sock.recv(65536)
        except socket.timeout:
            continue
        if not data:
            sink.end("closed")
            break
        sink.feed(data)


class RtspAgainstPc(unittest.TestCase):
    def test_whole_dialogue(self):
        events = []
        pc = FakePc()
        sock = socket.create_connection(("127.0.0.1", pc.port), timeout=5)
        sink = miracast.RtspSink(sock.sendall, 19000, before_play=lambda: events.append("before_play"),
                                 playing=lambda: (events.append("playing"), sink.request_idr()), log=lambda *a: None)
        pump(sock, sink)
        pc.thread.join(5)
        sock.close()
        self.assertIsNone(pc.error)
        s = pc.seen
        self.assertEqual(s["m1_answer"].headers["public"], "org.wfa.wfd1.0, GET_PARAMETER, SET_PARAMETER")
        self.assertEqual((s["m2"].method, s["m2"].uri), ("OPTIONS", "*"))
        self.assertEqual(s["m3"].cseq, "2")
        self.assertEqual(len(s["m3"].body.splitlines()), len(M3_ASKED))
        self.assertEqual(s["m4_answer"].status, 200)
        self.assertEqual(s["m5_answer"].status, 200)
        self.assertEqual(s["m6"].method, "SETUP")
        self.assertEqual(s["m6"].uri, "rtsp://192.168.1.50/wfd1.0/streamid=0")
        self.assertEqual(s["m6"].headers["transport"], "RTP/AVP/UDP;unicast;client_port=19000")
        self.assertEqual(s["m7"].method, "PLAY")
        self.assertEqual(s["m7"].headers["session"], "7F3A9C21")
        self.assertEqual(s["idr"].method, "SET_PARAMETER")
        self.assertEqual(s["idr"].body.strip(), "wfd_idr_request")
        self.assertEqual((s["keepalive_answer"].status, s["keepalive_answer"].cseq, s["keepalive_answer"].body), (200, "5", ""))
        self.assertEqual(s["m8_answer"].status, 200)
        self.assertEqual(s["teardown"].method, "TEARDOWN")
        self.assertEqual(s["teardown"].headers["session"], "7F3A9C21")
        self.assertEqual(events, ["before_play", "playing"])
        self.assertEqual(sink.timeout, 30)
        self.assertTrue(sink.ended)

    def test_refused_setup_ends_it(self):
        out = Collect()
        sink = miracast.RtspSink(out, 19000, before_play=lambda: self.fail("no PLAY after a refusal"), log=lambda *a: None)
        sink.feed(request("SET_PARAMETER", "rtsp://localhost/wfd1.0", 4, [], M4_BODY + "wfd_trigger_method: SETUP\r\n"))
        setup = [m for m in out.msgs if m.method == "SETUP"][0]
        sink.feed(response(setup.cseq, status="406 Not Acceptable"))
        self.assertIn("SETUP answered 406", sink.ended)

    def test_a_failing_before_play_stops_before_play(self):
        out = Collect()

        def boom():
            raise OSError("no screen")
        sink = miracast.RtspSink(out, 19000, before_play=boom, log=lambda *a: None)
        sink.feed(request("SET_PARAMETER", "rtsp://localhost/wfd1.0", 4, [], "wfd_trigger_method: SETUP\r\n"))
        sink.feed(response(out.msgs[-1].cseq, [("Session", "1")]))
        self.assertIn("no screen", sink.ended)
        self.assertNotIn("PLAY", [m.method for m in out.msgs])


def edid_ext_block():
    b = bytearray(128)
    b[0], b[1] = 2, 3
    b[127] = -sum(b[:127]) & 255
    return bytes(b)


class EdidTest(unittest.TestCase):
    def test_built_in_edid_is_a_valid_1080p60_block(self):
        e = miracast.build_edid()
        self.assertEqual(len(e), 128)
        self.assertEqual(sum(e) % 256, 0)
        self.assertEqual(e[:8], bytes([0, 255, 255, 255, 255, 255, 255, 0]))
        d = e[54:72]                                # the first detailed timing: the preferred mode
        clock = d[0] | d[1] << 8
        h, hb = d[2] | (d[4] >> 4) << 8, d[3] | (d[4] & 15) << 8
        v, vb = d[5] | (d[7] >> 4) << 8, d[6] | (d[7] & 15) << 8
        self.assertEqual((h, v), (1920, 1080))
        self.assertEqual((hb, vb), (280, 45))
        self.assertEqual(clock, 14850)
        self.assertAlmostEqual(clock * 10000 / ((h + hb) * (v + vb)), 60.0, places=2)
        self.assertEqual(((d[8] | (d[11] >> 6) << 8), d[9], d[10] >> 4, d[10] & 15), (88, 44, 4, 5))
        self.assertTrue(e[24] & 2)                  # the preferred timing is the first descriptor
        self.assertIn(b"Media Stick", e[72:90])
        self.assertEqual(e[18:20], bytes([1, 3]))

    def test_value_is_block_count_and_hex_without_spaces(self):
        e = miracast.build_edid()
        value = miracast.edid_value(e)
        count, hexa = value.split(" ")
        self.assertEqual(count, "0001")
        self.assertEqual(bytes.fromhex(hexa), e)
        self.assertEqual(miracast.edid_value(e + edid_ext_block()).split(" ")[0], "0002")

    def test_display_edid_is_always_the_built_in_one(self):
        self.assertEqual(miracast.display_edid_value(), EDID_LINE)


def rtp(seq, payload=b"\x47" + bytes(187), pt=33, cc=0, ext=0, pad=0, version=2):
    head = bytes([version << 6 | (0x20 if pad else 0) | (0x10 if ext else 0) | cc, pt]) + seq.to_bytes(2, "big") + bytes(8)
    body = bytes(4 * cc)
    if ext:
        body += b"\xbe\xde" + ext.to_bytes(2, "big") + bytes(4 * ext)
    return head + body + payload + (bytes(pad - 1) + bytes([pad]) if pad else b"")


class RtpTest(unittest.TestCase):
    def test_header_is_taken_off(self):
        ts = bytes([0x47]) + bytes(range(187))
        self.assertEqual(miracast.parse_rtp(rtp(7, ts)), (7, ts))
        self.assertEqual(miracast.parse_rtp(rtp(65535, ts, cc=2)), (65535, ts))
        self.assertEqual(miracast.parse_rtp(rtp(8, ts, ext=3)), (8, ts))
        self.assertEqual(miracast.parse_rtp(rtp(9, ts, pad=4)), (9, ts))
        self.assertEqual(miracast.parse_rtp(rtp(10, ts, pt=96)), (10, ts))

    def test_not_a_stream_packet(self):
        self.assertIsNone(miracast.parse_rtp(rtp(1, version=1)))
        self.assertIsNone(miracast.parse_rtp(rtp(1, pt=72)))        # RTCP's range
        self.assertIsNone(miracast.parse_rtp(b"\x80\x21\x00"))

    def test_order_wraparound_is_not_a_gap(self):
        o = miracast.RtpOrder()
        got = []
        for s in (65533, 65534, 65535, 0, 1):
            out, lost = o.push(s, bytes([s & 255]))
            self.assertEqual(lost, 0)
            got += out
        self.assertEqual(got, [bytes([s & 255]) for s in (65533, 65534, 65535, 0, 1)])

    def test_gap_is_counted_after_the_reorder_wait(self):
        o = miracast.RtpOrder()
        for s in (1, 2):
            o.push(s, b"x")
        self.assertEqual(o.push(4, b"4"), ([], 0))
        self.assertEqual(o.push(5, b"5"), ([], 0))
        self.assertEqual(o.push(6, b"6"), ([], 0))
        self.assertEqual(o.push(7, b"7"), ([b"4", b"5", b"6", b"7"], 1))
        self.assertEqual(o.push(8, b"8"), ([b"8"], 0))

    def test_gap_across_the_wrap(self):
        o = miracast.RtpOrder()
        o.push(65534, b"a")
        lost = sum(o.push(s, b"x")[1] for s in (1, 2, 3, 4))      # 65535 and 0 missing
        self.assertEqual(lost, 2)

    def test_a_late_packet_by_one_or_two_is_put_in_order(self):
        o = miracast.RtpOrder()
        got = []
        for s in (1, 2, 4, 5, 3, 6):
            out, lost = o.push(s, bytes([s]))
            self.assertEqual(lost, 0)
            got += out
        self.assertEqual(got, [bytes([s]) for s in range(1, 7)])

    def test_duplicates_and_the_past_are_dropped(self):
        o = miracast.RtpOrder()
        for s in (1, 2, 3):
            o.push(s, b"x")
        self.assertEqual(o.push(3, b"x"), ([], 0))
        self.assertEqual(o.push(1, b"x"), ([], 0))
        self.assertEqual(o.push(4, b"y"), ([b"y"], 0))

    def test_a_jump_far_ahead_is_a_restart_not_a_wait(self):
        o = miracast.RtpOrder()
        o.push(1, b"a")
        out, lost = o.push(30000, b"z")
        self.assertEqual(out, [b"z"])
        self.assertGreater(lost, 0)
        self.assertEqual(o.push(30001, b"y"), ([b"y"], 0))

    def relay(self):
        self.now = 0.0
        self.written = []
        return miracast.RtpRelay(19000, "192.168.1.50", self.written.append, clock=lambda: self.now,
                                 backlog=lambda: 300 * 1024)

    def test_relay_passes_payload_and_ignores_other_hosts(self):
        r = self.relay()
        ts = bytes([0x47]) + bytes(187)
        r.handle(rtp(1, ts), "192.168.1.50")
        r.handle(rtp(2, ts), "10.9.9.9")
        r.handle(b"junk", "192.168.1.50")
        r.handle(rtp(2, ts), "192.168.1.50")
        self.assertEqual(self.written, [ts, ts])
        self.assertEqual((r.packets, r.foreign, r.bad, r.lost), (2, 1, 1, 0))
        self.assertFalse(r.idr_due())

    def feed(self, r, seqs):
        for s in seqs:
            r.handle(rtp(s), "192.168.1.50")

    def test_gap_asks_for_an_idr_at_most_once_a_second(self):
        r = self.relay()
        self.feed(r, [65533, 65534, 65535, 0])              # wraparound: no gap
        self.assertFalse(r.idr_due())
        self.feed(r, [2, 3, 4, 5])                          # 1 missing
        self.assertEqual(r.lost, 1)
        self.assertTrue(r.idr_due())
        self.assertFalse(r.idr_due())                       # asked already
        self.now = 0.5
        self.feed(r, [8, 9, 10, 11])                        # 6 and 7 missing: wants one again
        self.assertEqual(r.lost, 3)
        self.assertFalse(r.idr_due())                       # but not within a second
        self.now = 1.2
        self.assertTrue(r.idr_due())
        self.assertFalse(r.idr_due())

    def test_summary_every_five_seconds(self):
        r = self.relay()
        self.feed(r, [1, 2, 3])
        self.assertIsNone(r.summary(0))
        self.now = 5.1
        self.assertEqual(r.summary(2, 1), "RTP: 3 packets, 0 lost, 0 dropped, 0 ignored, 2 IDR requests so far (1 refresh), %.1f Mbit/s, pipe 300 KB, backlog 0 KB"
                         % (3 * 188 * 8 / 1e6 / 5.1))
        self.assertIsNone(r.summary(2))

    def test_over_a_real_socket(self):
        written = []
        r = miracast.RtpRelay(0, "127.0.0.1", written.append)
        r.start()
        port = r.sock.getsockname()[1]
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for s in (1, 2, 3):
                tx.sendto(rtp(s, bytes([0x47, s]) + bytes(186)), ("127.0.0.1", port))
            end = time.monotonic() + 3
            while len(written) < 3 and time.monotonic() < end:
                time.sleep(0.02)
            self.assertEqual([w[:2] for w in written], [b"\x47\x01", b"\x47\x02", b"\x47\x03"])
        finally:
            tx.close()
            r.stop()


class DumpTest(unittest.TestCase):
    def setUp(self):
        self.written, self.lines = [], []

    def relay(self, dump):
        return miracast.RtpRelay(19000, "192.168.1.50", self.written.append, dump=dump)

    def dump(self, path, limit=miracast.DUMP_MAX):
        return miracast.PayloadDump(path, limit, log=lambda *a: self.lines.append(" ".join(str(x) for x in a)))

    def test_the_file_is_what_the_drawer_got_and_is_0644(self):
        with Rig():
            self.lines = []
            r = self.relay(self.dump(miracast.DUMP_FILE))
            for s in (1, 2, 3):
                r.handle(rtp(s, bytes([0x47, s]) + bytes(186)), "192.168.1.50")
            r.stop()
            self.assertEqual(len(self.written), 3)
            self.assertEqual(open(miracast.DUMP_FILE, "rb").read(), b"".join(self.written))
            self.assertEqual(os.stat(miracast.DUMP_FILE).st_mode & 0o777, 0o644)
            self.assertEqual(len(self.lines), 2)
            self.assertIn("started", self.lines[0])
            self.assertIn("stopped", self.lines[1])

    def test_it_truncates_an_old_file_and_stops_at_the_limit(self):
        with Rig():
            open(miracast.DUMP_FILE, "wb").write(b"old" * 1000)
            r = self.relay(self.dump(miracast.DUMP_FILE, 300))
            for s in (1, 2, 3):
                r.handle(rtp(s), "192.168.1.50")
            self.assertEqual(len(self.written), 3)               # the drawer is not affected
            self.assertEqual(open(miracast.DUMP_FILE, "rb").read(), b"".join(self.written)[:300])
            self.assertEqual(len(self.lines), 2)
            self.assertIn("limit", self.lines[1])
            r.stop()
            self.assertEqual(len(self.lines), 2)                 # stopped once

    def test_a_write_error_turns_it_off_and_leaves_the_stream_alone(self):
        class Broken:
            def write(self, data):
                raise OSError("disk full")

            def close(self):
                pass
        with Rig():
            d = self.dump(miracast.DUMP_FILE)
            d.f = Broken()
            r = self.relay(d)
            r.handle(rtp(1), "192.168.1.50")
            r.handle(rtp(2), "192.168.1.50")
            self.assertEqual(len(self.written), 2)
            self.assertIsNone(d.f)
            self.assertEqual(len([l for l in self.lines if "stopped" in l]), 1)

    def test_session_dumps_only_when_the_flag_file_exists(self):
        for flag in (False, True):
            with Rig():
                if flag:
                    open(miracast.DUMP_FLAG, "w").close()
                a, b = socket.socketpair()
                session = miracast.Session(a, "127.0.0.1", FakeScreen(), rtp_port=19000, relay=FakeRelay)
                session.start_video()
                self.assertEqual(os.path.exists(miracast.DUMP_FILE), flag)
                a.close()
                b.close()


class DrawerDiagnosticsTest(unittest.TestCase):
    def test_the_latency_tracer_is_gone(self):
        # it deadlocked the pipeline (a drawer with every thread in a futex wait and no picture)
        with open(os.path.join(BIN, "miracast")) as f:
            text = f.read()
        for gone in ("miracast-trace", "TRACE_FLAG", "GST_TRACER"):
            self.assertNotIn(gone, text)
        self.assertFalse(hasattr(miracast, "TRACE_FLAG"))
        self.assertEqual([a for a in miracast.drawer() if "TRACER" in a], [])
        self.assertIn("GST_DEBUG=2,bufferpool:1", miracast.drawer())

    def test_backlog_asks_the_pipe_of_the_drawer(self):
        with Rig():
            proc = FakeProc(["gst"])
            proc.stdin = open(os.devnull, "wb")
            asked = []
            screen = miracast.Screen(systemctl=lambda *a: Out(), light=lambda: (None, 1, 1),
                                     popen=lambda *a, **k: proc, pending=lambda fd: asked.append(fd) or 4096)
            self.assertEqual(screen.backlog(), 0)         # no drawer yet
            screen.start_drawer()
            self.assertEqual(screen.backlog(), 4096)
            self.assertEqual(asked[-1], proc.stdin.fileno())
            proc.stdin.close()

    def test_pipe_pending_counts_what_is_in_a_real_pipe(self):
        r, w = os.pipe()
        try:
            os.write(w, b"x" * 1000)
            self.assertEqual(miracast.pipe_pending(w), 1000)
            self.assertEqual(miracast.pipe_pending(r), 1000)
        finally:
            os.close(r)
            os.close(w)
        self.assertEqual(miracast.pipe_pending(-1), 0)


class Drawer(unittest.TestCase):
    def test_decoder_feeds_kmssink_with_only_a_queue_between(self):
        args = miracast.drawer()
        line = " ".join(args)
        self.assertIn("v4l2h264dec ! queue max-size-buffers=1 leaky=downstream ! kmssink sync=false", line)
        launch = args[args.index("gst-launch-1.0") + 1:]
        video = launch[launch.index("d.") + 1:]
        video = video[:video.index("d.")]
        elements = [video[i + 1] for i, a in enumerate(video) if a == "!"]
        self.assertEqual(elements, ["video/x-h264", "queue", "h264parse", "capssetter", "v4l2h264dec", "queue", "kmssink"])
        self.assertEqual(elements[elements.index("v4l2h264dec") + 1:], ["queue", "kmssink"])
        self.assertNotIn("avdec_h264", line)
        self.assertNotIn("videoconvert", line)

    def test_source_and_audio(self):
        args = miracast.drawer()
        self.assertEqual(args[:len(miracast.AS_MEDIA)], miracast.AS_MEDIA)
        head = " ".join(args[args.index("gst-launch-1.0"):])
        self.assertIn("fdsrc fd=0 ! video/mpegts,systemstream=true ! tsdemux name=d", head)
        for gone in ("udpsrc", "rtpjitterbuffer", "rtpmp2tdepay"):
            self.assertNotIn(gone, head)
        self.assertIn("kmssink sync=false async=false", head)
        self.assertIn("d. ! audio/mpeg,mpegversion=4,stream-format=adts ! queue leaky=downstream", head)
        self.assertIn(" ! aacparse ! avdec_aac ! audioconvert ! audioresample ! alsasink buffer-time=", head)
        self.assertNotIn("video_0", head)
        self.assertNotIn("audio_0", head)


PICTURE = "/GstPipeline:pipeline0/GstV4l2H264Dec:v4l2h264dec0.GstPad:src: caps = video/x-raw, width=(int)1920"
BROKEN = "0:00:05.1 WARN h264parse gsth264parse.c:1234:gst_h264_parse_process_nal:<h264parse0> broken/invalid nal Type: 1 Slice"


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.asked, self.written = [], []
        self.w = miracast.DrawWatch(lambda: self.now, self.asked.append, self.written.append)

    def tick(self, dt=0.0):
        self.now += dt
        self.w.tick()

    def test_idle_before_play(self):
        self.tick(10)
        self.assertEqual(self.asked, [])

    def test_asks_every_second_until_the_first_picture(self):
        self.w.begin()
        self.tick()
        self.tick(0.4)
        self.assertEqual(len(self.asked), 0)       # the first second is waited for, not asked at once
        self.tick(0.7)
        self.tick(0.4)
        self.assertEqual(len(self.asked), 1)       # then not again within a second
        self.tick(0.7)
        self.assertEqual(len(self.asked), 2)
        self.w.feed(BROKEN)                       # broken NALs before a picture change nothing
        self.w.feed(PICTURE)
        self.tick(1.0)
        self.tick(10)
        self.assertEqual(len(self.asked), 2)      # a picture came: no more asking

    def test_after_the_picture_it_asks_only_when_the_stream_breaks_and_at_most_every_2_s(self):
        self.w.begin()
        self.tick()
        self.w.feed(PICTURE)
        self.tick(30)
        self.assertEqual(len(self.asked), 0)
        self.w.feed(BROKEN)
        self.tick(0.1)
        self.assertEqual(len(self.asked), 1)
        self.w.feed(BROKEN)
        self.tick(1.0)                            # within 2 s of the last request: not yet
        self.assertEqual(len(self.asked), 1)
        self.tick(1.1)
        self.assertEqual(len(self.asked), 2)
        self.tick(5)
        self.assertEqual(len(self.asked), 2)      # nothing broken since
        self.w.feed("0:00:09 ERROR v4l2videodec gstv4l2videodec.c:1: decoding error")
        self.tick(2.1)
        self.assertEqual(len(self.asked), 3)

    def held_tick(self, dt, held):
        self.now += dt
        self.w.tick(held=held)

    def test_nothing_is_asked_while_the_relay_still_holds_data_for_the_drawer(self):
        self.w.begin()
        for _ in range(10):
            self.held_tick(1.0, True)             # far past the window, but the picture may be in the backlog
        self.assertEqual(self.asked, [])
        self.held_tick(0.5, False)                # drained: the window starts over
        self.assertEqual(self.asked, [])
        self.held_tick(0.6, False)
        self.assertEqual(self.asked, ["no picture yet"])

    def test_held_data_does_not_hold_back_a_request_for_a_damaged_stream(self):
        self.w.begin()
        self.w.feed(PICTURE)
        self.w.feed(BROKEN)
        self.held_tick(0.1, True)
        self.assertEqual(self.asked, ["the stream is damaged"])

    def test_broken_nal_lines_are_counted_not_logged(self):
        self.w.begin()
        for _ in range(300):
            self.w.feed(BROKEN)
        self.w.feed("something else")
        self.assertEqual(self.written, ["something else"])
        self.tick(2)
        self.assertEqual(self.written, ["something else"])
        self.tick(4)
        self.assertEqual(self.written[1:], ["[miracast] 300 broken NAL units dropped by h264parse"])
        self.tick(6)
        self.assertEqual(len(self.written), 2)    # nothing new to sum up

    def test_stop_and_restart(self):
        self.w.begin()
        self.w.feed(PICTURE)
        self.w.stop()
        self.tick(5)
        self.assertEqual(self.asked, [])
        self.w.begin()                            # a new drawer: no picture again
        self.tick(1.1)
        self.assertEqual(len(self.asked), 1)


class FakeProc:
    def __init__(self, argv):
        self.argv, self.code, self.stopped = argv, None, False

    def poll(self):
        return self.code

    @property
    def returncode(self):
        return self.code

    def terminate(self):
        self.stopped, self.code = True, -15

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        self.code = -9


class Out:
    def __init__(self, stdout=""):
        self.stdout = stdout


class Rig:
    """The module's paths in a temporary folder, for the length of one test."""

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.saved = {n: getattr(miracast, n) for n in ("RUN", "FLAG", "AIRPLAY_FLAG", "LOG", "DRAW_LOG", "FPS30_FLAG", "PROFILE_FLAG", "DUMP_FLAG", "DUMP_FILE", "AUDIO_DELAY_FLAG", "IDR_REFRESH_FLAG", "BITRATE_FLAG")}
        d = self.dir.name
        miracast.RUN, miracast.FLAG = d, d + "/miracast"
        miracast.AIRPLAY_FLAG, miracast.LOG, miracast.DRAW_LOG = d + "/airplay", d + "/miracast.log", d + "/draw.log"
        miracast.FPS30_FLAG, miracast.AUDIO_DELAY_FLAG = d + "/miracast-30fps", d + "/miracast-audio-delay"
        miracast.IDR_REFRESH_FLAG, miracast.BITRATE_FLAG = d + "/miracast-idr-every", d + "/miracast-max-bitrate"
        miracast.PROFILE_FLAG = d + "/miracast-profile"
        miracast.DUMP_FLAG, miracast.DUMP_FILE = d + "/miracast-dump", d + "/miracast-dump.ts"
        return self

    def __exit__(self, *a):
        for n, v in self.saved.items():
            setattr(miracast, n, v)
        self.dir.cleanup()


class ScreenTest(unittest.TestCase):
    def test_take_and_give_back(self):
        with Rig():
            calls, procs = [], []

            def systemctl(*args):
                calls.append(args)
                return Out("web-app@netflix.service loaded active running x\nkodi.service" if args[0] == "list-units" else "")

            def popen(argv, **kw):
                procs.append(FakeProc(argv))
                return procs[-1]
            lit = []
            screen = miracast.Screen(systemctl=systemctl, light=lambda: (lit.append(1), (99, 1920, 1080))[1], popen=popen)
            self.assertFalse(screen.taken)
            screen.take()
            self.assertTrue(screen.taken)
            self.assertEqual(lit, [1])
            self.assertIn(("stop", "web-app@netflix.service"), calls)
            self.assertLess(calls.index(("stop", "web-app@netflix.service")), calls.index(("stop", "kodi.service")))
            screen.card = None   # the fake card number is not a real descriptor
            screen.start_drawer()
            screen.start_drawer()        # again: the first is stopped
            self.assertTrue(procs[0].stopped)
            self.assertIn("fdsrc", procs[1].argv)
            screen.give_back()
            self.assertTrue(procs[1].stopped)
            self.assertFalse(screen.taken)
            self.assertEqual(calls[-1], ("start", "--no-block", "kodi.service"))

    def test_drawer_output_goes_through_on_line_and_the_log_is_capped(self):
        with Rig():
            proc = FakeProc(["gst"])
            proc.stdout = [b"one\n", b"two\n"]
            screen = miracast.Screen(systemctl=lambda *a: Out(), light=lambda: (None, 1, 1), popen=lambda *a, **k: proc)
            got = []
            screen.on_line = got.append
            screen.start_drawer()
            self.wait_until(lambda: got == ["one", "two"])
            miracast.draw_log("kept")
            self.assertIn("kept", open(miracast.DRAW_LOG).read())
            saved, miracast.LOG_MAX = miracast.LOG_MAX, 10
            try:
                miracast.draw_log("x" * 20)
                miracast.draw_log("fresh")           # past the cap: starts over
            finally:
                miracast.LOG_MAX = saved
            self.assertEqual(open(miracast.DRAW_LOG).read(), "fresh\n")

    def test_write_goes_to_the_drawers_standard_input_and_not_to_a_dead_one(self):
        with Rig():
            r, w = os.pipe()

            class Stdin:
                def fileno(self):
                    return w

                def close(self):
                    pass
            proc = FakeProc(["gst"])
            proc.stdin = Stdin()
            screen = miracast.Screen(systemctl=lambda *a: Out(), light=None, popen=lambda *a, **k: proc)
            self.assertFalse(screen.write(b"nobody"))           # no drawer yet
            screen.start_drawer()
            self.assertTrue(screen.write(b"\x47abc"))
            self.assertEqual(os.read(r, 100), b"\x47abc")
            os.close(r)
            self.assertFalse(screen.write(b"x"))                # the reader is gone: EPIPE, not an exception
            os.close(w)
            screen.stop_drawer()
            self.assertFalse(screen.write(b"x"))

    @staticmethod
    def wait_until(cond, seconds=3):
        end = time.monotonic() + seconds
        while not cond() and time.monotonic() < end:
            time.sleep(0.02)
        assert cond(), "timed out"

    def test_light_failing_still_takes_the_screen(self):
        with Rig():
            def broken():
                raise OSError("no card")
            screen = miracast.Screen(systemctl=lambda *a: Out(), light=broken, popen=lambda *a, **k: FakeProc(a))
            screen.take()
            self.assertTrue(screen.taken)


class Exclusion(unittest.TestCase):
    def test_refusals(self):
        with Rig():
            self.assertIsNone(miracast.refusal(False))
            self.assertIn("session", miracast.refusal(True))
            open(miracast.AIRPLAY_FLAG, "w").close()
            self.assertIn("AirPlay", miracast.refusal(False))

    def test_airplay_ignores_a_phone_while_miracast_has_the_screen(self):
        saved = airplay.MIRACAST_FLAG
        with tempfile.TemporaryDirectory() as d:
            airplay.MIRACAST_FLAG = d + "/miracast"
            try:
                self.assertTrue(airplay.may_take())
                open(airplay.MIRACAST_FLAG, "w").close()
                self.assertFalse(airplay.may_take())
            finally:
                airplay.MIRACAST_FLAG = saved
        self.assertEqual(saved, miracast.FLAG)                  # the two programs name the same files
        self.assertEqual(airplay.FLAG, miracast.AIRPLAY_FLAG)


class FakeScreen:
    def __init__(self):
        self.events = []
        self.flag = False
        self.drawer = None
        self.dies = 0     # how many times a drawer is found dead after it started

    @property
    def taken(self):
        return self.flag

    def take(self):
        self.flag = True
        self.events.append("take")

    def start_drawer(self):
        self.events.append("drawer")
        self.drawer = FakeProc(["gst"])

    def write(self, data):
        return True

    def backlog(self):
        return 0

    def drawer_dead(self):
        if self.dies and self.drawer and self.drawer.code is None:
            self.dies -= 1
            self.drawer.code = 1
        return bool(self.drawer and self.drawer.code is not None)

    def give_back(self):
        self.flag = False
        self.events.append("give_back")


class FakeRelay:
    """RtpRelay's place in a session: no socket; due is set by a test to say "packets were lost"."""
    made = []

    def __init__(self, port, source_ip, write, backlog=None, dump=None):
        self.port, self.source_ip, self.write = port, source_ip, write
        self.due, self.started, self.stopped = False, False, False
        self.queued = 0     # bytes held for the drawer; a test sets it
        FakeRelay.made.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def idr_due(self):
        due, self.due = self.due, False
        return due

    def discard(self):
        self.queued = 0

    def summary(self, idrs, refreshes=0):
        return None


class SessionTest(unittest.TestCase):
    def run_session(self, pc, screen):
        a, b = socket.socketpair()
        FakeRelay.made = []
        session = miracast.Session(a, "127.0.0.1", screen, rtp_port=19000, relay=FakeRelay,
                                   connect=lambda ip, port: socket.create_connection(("127.0.0.1", pc.port), timeout=5))
        thread = threading.Thread(target=session.run, daemon=True)
        thread.start()
        return session, thread, b

    def test_screen_is_taken_before_play_and_given_back_at_stop(self):
        screen = FakeScreen()
        pc = FakePc(on_play=lambda: list(screen.events))
        session, thread, b = self.run_session(pc, screen)
        b.sendall(mice(9, tlv(7, b"zz")) + source_ready("TEST-PC", pc.port))   # an unknown command first
        pc.thread.join(8)
        self.assertIsNone(pc.error)
        self.assertEqual(pc.seen["at_play"], ["take", "drawer"])
        [relay] = FakeRelay.made
        self.assertEqual((relay.port, relay.source_ip, relay.write), (19000, "127.0.0.1", screen.write))
        self.assertTrue(relay.started)
        self.assertEqual(pc.seen["idr"].body.strip(), "wfd_idr_request")
        thread.join(5)   # the source's teardown trigger ends the RTSP side, and with it the session
        self.assertFalse(thread.is_alive())
        self.assertEqual(session.reason, "the source asked for a teardown")
        self.assertEqual(screen.events[-1], "give_back")
        b.close()

    def test_stop_projection_ends_it(self):
        screen = FakeScreen()
        pc = FakePc()
        pc.run = lambda: self.hold(pc)
        session, thread, b = self.run_session(pc, screen)
        b.sendall(source_ready("TEST-PC", pc.port))
        self.wait_for(lambda: session.sink is not None and session.sink.playing)
        b.sendall(mice(2))
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(session.reason, "the PC stopped projecting")
        self.assertEqual(screen.events[-1], "give_back")
        b.close()

    def test_closing_the_mice_connection_ends_it(self):
        screen = FakeScreen()
        pc = FakePc()
        pc.run = lambda: self.hold(pc)
        session, thread, b = self.run_session(pc, screen)
        b.sendall(source_ready("TEST-PC", pc.port))
        self.wait_for(lambda: session.sink is not None and session.sink.playing)
        b.close()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertIn("closed", session.reason)
        self.assertEqual(screen.events[-1], "give_back")

    def test_dead_drawer_is_restarted_with_an_idr_request(self):
        screen = FakeScreen()
        screen.dies = 1
        pc = FakePc()
        idrs = []

        def script():
            self.hold(pc, idrs)
        pc.run = script
        session, thread, b = self.run_session(pc, screen)
        b.sendall(source_ready("TEST-PC", pc.port))
        self.wait_for(lambda: len(idrs) >= 2)
        self.assertEqual(screen.events.count("drawer"), 2)
        b.sendall(mice(2))
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(FakeRelay.made[0].stopped)

    def test_lost_rtp_packets_ask_for_an_idr(self):
        screen = FakeScreen()
        pc = FakePc()
        idrs = []
        pc.run = lambda: self.hold(pc, idrs)
        self.addCleanup(setattr, miracast, "IDR_REFRESH_SECS", miracast.IDR_REFRESH_SECS)
        miracast.IDR_REFRESH_SECS = 0            # the refresh has its own tests
        session, thread, b = self.run_session(pc, screen)
        b.sendall(source_ready("TEST-PC", pc.port))
        self.wait_for(lambda: session.sink is not None and session.sink.playing)
        screen.on_line(PICTURE)                  # the decoder has a picture: the watchdog is quiet
        time.sleep(1.5)
        before = len(idrs)
        FakeRelay.made[0].due = True
        self.wait_for(lambda: len(idrs) == before + 1)
        time.sleep(1.2)
        self.assertEqual(len(idrs), before + 1)  # and only the one
        b.sendall(mice(2))
        thread.join(5)

    def test_no_source_ready_gives_up_quietly(self):
        saved = miracast.SETUP_LIMIT
        miracast.SETUP_LIMIT = 1.2
        try:
            screen = FakeScreen()
            session, thread, b = self.run_session(FakePc(), screen)
            thread.join(6)
            self.assertFalse(thread.is_alive())
            self.assertIn("no picture", session.reason)
            self.assertEqual(screen.events, [])
        finally:
            miracast.SETUP_LIMIT = saved
            b.close()

    @staticmethod
    def wait_for(cond, seconds=8):
        end = time.monotonic() + seconds
        while not cond() and time.monotonic() < end:
            time.sleep(0.05)
        assert cond(), "timed out"

    @staticmethod
    def hold(pc, idrs=None, teardown=None):
        """The PC's side up to PLAY, then it just stays (answering IDR requests) until the sink goes;
        it sends a TEARDOWN request when the event teardown is set."""
        c = pc.c
        c.sendall(request("OPTIONS", "*", 1, [("Require", "org.wfa.wfd1.0")]))
        pc.read(2)
        c.sendall(request("SET_PARAMETER", "rtsp://localhost/wfd1.0", 3, [], M4_BODY))
        pc.read(1)
        c.sendall(request("SET_PARAMETER", "rtsp://localhost/wfd1.0", 4, [], "wfd_trigger_method: SETUP\r\n"))
        setup = [m for m in pc.read(2) if not m.response][0]
        c.sendall(response(setup.cseq, [("Session", "AB12;timeout=30")]))
        play = pc.read(1)[0]
        c.sendall(response(play.cseq))
        c.settimeout(0.2)
        end = time.monotonic() + 20
        try:
            while time.monotonic() < end:
                if teardown is not None and teardown.is_set():
                    teardown.clear()
                    c.sendall(request("TEARDOWN", "rtsp://localhost/wfd1.0", 9, [("Session", "AB12")]))
                try:
                    msgs = pc.read(1)
                except socket.timeout:
                    continue
                for m in msgs:
                    if m.method == "SET_PARAMETER" and idrs is not None:
                        idrs.append(m)
                    if not m.response:
                        c.sendall(response(m.cseq))
        except (EOFError, OSError):
            pass


class StubbornProc(FakeProc):
    """A drawer that ignores SIGTERM (as a deadlocked gst-launch does) and dies of SIGKILL."""

    def __init__(self, argv):
        super().__init__(argv)
        self.events = []

    def terminate(self):
        self.events.append("terminate")

    def kill(self):
        self.events.append("kill")
        self.code = -9

    def wait(self, timeout=None):
        self.events.append("wait")
        if self.code is None:
            raise subprocess.TimeoutExpired("gst", timeout)
        return self.code


def pipe_screen(w):
    """A Screen whose drawer's standard input is the write end w of a pipe nobody reads."""
    proc = FakeProc(["gst"])
    proc.stdin = os.fdopen(w, "wb", buffering=0)
    screen = miracast.Screen(systemctl=lambda *a: Out(), light=lambda: (None, 1, 1), popen=lambda *a, **k: proc)
    screen.start_drawer()
    return screen, proc


class StuckDrawerRelayTest(unittest.TestCase):
    def test_a_drawer_that_never_reads_does_not_block_the_relay(self):
        with Rig():
            r, w = os.pipe()
            screen, proc = pipe_screen(w)
            dump_path = os.path.join(miracast.RUN, "dump.ts")
            payload = bytes([0x47]) + bytes(187)
            payload *= 7
            sent = 9000                                     # 11.8 MB: more than the pipe and the backlog hold
            relay = miracast.RtpRelay(19000, "10.0.0.2", screen.write, backlog=screen.backlog,
                                      dump=miracast.PayloadDump(dump_path, limit=1 << 30, log=lambda *a: None))
            done = threading.Event()

            def feed():
                for seq in range(sent):
                    relay.handle(rtp(seq, payload), "10.0.0.2")
                done.set()
            threading.Thread(target=feed, daemon=True).start()
            self.assertTrue(done.wait(10), "the relay blocked on the drawer's pipe")
            self.assertGreater(relay.dropped, 0)
            self.assertEqual(relay.lost, 0)
            self.assertTrue(relay.idr_due())                # a drop is a loss: a new keyframe is wanted
            self.assertFalse(relay.idr_due())               # at most once a second
            relay.clock = lambda: relay.summary_at + 6
            self.assertIn("%d dropped" % relay.dropped, relay.summary(1))
            os.set_blocking(r, False)
            got = b""
            while True:
                try:
                    chunk = os.read(r, 1 << 20)
                except BlockingIOError:
                    break
                if not chunk:
                    break
                got += chunk
            # whole payloads only, so the TS packets stay aligned: what was not dropped is in the
            # pipe, in the rest of a part-written payload, or in the backlog
            self.assertEqual(len(got) + len(screen.tail) + relay.queued, (sent - relay.dropped) * len(payload))
            self.assertGreater(relay.queued, miracast.BACKLOG_MAX)
            self.assertEqual(got[:188], payload[:188])
            relay.stop()
            with open(dump_path, "rb") as f:                # the dump has what was received, dropped or not
                self.assertEqual(len(f.read()), sent * len(payload))
            os.close(r)
            proc.stdin.close()

    @staticmethod
    def numbered(n, size=1316):
        """A payload of whole TS packets that says which it is."""
        return (bytes([0x47, n & 255, n >> 8]) + bytes(185)) * (size // 188)

    def test_a_drawer_that_reads_late_loses_nothing_and_gets_the_payloads_in_order(self):
        with Rig():
            r, w = os.pipe()
            os.set_blocking(r, False)
            screen, proc = pipe_screen(w)
            relay = miracast.RtpRelay(19000, "10.0.0.2", screen.write, backlog=screen.backlog)
            sent = 1800                                     # 2.4 MB: more than the 1 MB pipe holds
            for n in range(sent):
                relay.handle(rtp(n, self.numbered(n)), "10.0.0.2")
            self.assertEqual(relay.dropped, 0)
            self.assertGreater(relay.queued, 0)
            self.assertFalse(relay.idr_due())               # held, not lost: no keyframe wanted
            relay.clock = lambda: relay.summary_at + 6
            self.assertRegex(relay.summary(0), r"0 dropped.*backlog %d KB$" % (relay.queued // 1024))
            got = b""
            more = sent
            while relay.queued or screen.tail:              # the drawer starts reading
                try:
                    got += os.read(r, 1 << 16)
                except BlockingIOError:
                    pass
                relay.handle(rtp(more, self.numbered(more)), "10.0.0.2")
                more += 1
            while True:
                try:
                    chunk = os.read(r, 1 << 20)
                except BlockingIOError:
                    break
                got += chunk
            self.assertEqual(relay.dropped, 0)
            self.assertEqual(got, b"".join(self.numbered(n) for n in range(more)))
            os.close(r)
            proc.stdin.close()

    def test_a_full_backlog_drops_whole_payloads_and_wants_a_keyframe(self):
        saved = miracast.BACKLOG_MAX
        self.addCleanup(setattr, miracast, "BACKLOG_MAX", saved)
        miracast.BACKLOG_MAX = 10 * 1316
        open_, out = [False], []

        def write(payload):
            if not open_[0]:
                raise miracast.PipeFull()
            out.append(payload)
        relay = miracast.RtpRelay(19000, "10.0.0.2", write)
        for n in range(15):
            relay.handle(rtp(n, self.numbered(n)), "10.0.0.2")
        self.assertEqual((relay.queued, relay.dropped), (11 * 1316, 4))   # a payload still fits while the queue is not over the cap
        self.assertTrue(relay.idr_due())
        open_[0] = True
        relay.handle(rtp(15, self.numbered(15)), "10.0.0.2")
        self.assertEqual(out, [self.numbered(n) for n in list(range(11)) + [15]])   # in order, whole; 11 to 14 dropped
        self.assertEqual(relay.queued, 0)

    def test_a_payload_never_overtakes_the_queued_ones(self):
        open_, out = [False], []
        room = [0]

        def write(payload):
            if not open_[0] or room[0] == 0:
                raise miracast.PipeFull()
            room[0] -= 1
            out.append(payload)
        relay = miracast.RtpRelay(19000, "10.0.0.2", write)
        for n in range(4):
            relay.handle(rtp(n, self.numbered(n)), "10.0.0.2")
        open_[0], room[0] = True, 2                          # room for two payloads: the oldest two
        relay.handle(rtp(4, self.numbered(4)), "10.0.0.2")
        self.assertEqual(out, [self.numbered(0), self.numbered(1)])
        room[0] = 10
        relay.handle(rtp(5, self.numbered(5)), "10.0.0.2")
        self.assertEqual(out, [self.numbered(n) for n in range(6)])

    def test_a_part_of_a_payload_is_finished_before_the_next_one_goes_in(self):
        with Rig():
            r, w = os.pipe()
            screen, proc = pipe_screen(w)
            miracast.fcntl.fcntl(w, miracast.F_SETPIPE_SZ, 4096)     # after start_drawer, which made it roomy
            self.assertTrue(screen.write(b"a" * 6000))      # the pipe takes 4096 of it
            self.assertEqual(len(screen.tail), 6000 - miracast.pipe_pending(w))
            with self.assertRaises(miracast.PipeFull):
                screen.write(b"b" * 10)                     # behind: dropped whole
            got = os.read(r, 100000)
            self.assertTrue(screen.write(b"c" * 10))        # the rest of the first, then this one
            os.set_blocking(r, False)
            got += os.read(r, 100000)
            self.assertEqual(got, b"a" * 6000 + b"c" * 10)
            self.assertEqual(screen.tail, b"")
            os.close(r)
            proc.stdin.close()

    def test_no_drawer_is_not_a_drop(self):
        with Rig():
            screen = miracast.Screen(systemctl=lambda *a: Out(), light=None, popen=None)
            relay = miracast.RtpRelay(19000, "10.0.0.2", screen.write)
            relay.handle(rtp(1), "10.0.0.2")
            self.assertEqual(relay.dropped, 0)


class WatchdogTest(unittest.TestCase):
    """Session.check_drawer with a clock the test moves and a sink and a screen that are stubs."""

    class Sink:
        playing, ended = True, None

        def __init__(self):
            self.idr_count, self.asked, self.torn_down = 0, [], False

        def request_idr(self, why=""):
            self.idr_count += 1
            self.asked.append(why)

        def teardown(self):
            self.torn_down = True

    def setUp(self):
        self.now = 1000.0
        self.screen = FakeScreen()
        self.screen.flag = True
        a, self.b = socket.socketpair()
        self.session = miracast.Session(a, "127.0.0.1", self.screen, relay=FakeRelay, clock=lambda: self.now)
        self.session.sink = self.Sink()
        self.session.rtsp = None
        self.session.begin_watch()
        self.screen.start_drawer()
        self.screen.events.clear()

    def tearDown(self):
        self.b.close()

    def at(self, dt):
        self.now += dt
        self.session.check_drawer()

    def test_the_constants(self):
        self.assertEqual((miracast.STUCK_LIMIT, miracast.STUCK_RESTARTS), (8.0, 1))

    def test_no_picture_restarts_the_drawer_once_and_then_ends_the_session(self):
        sink = self.session.sink
        self.at(7)
        self.assertEqual(self.screen.events, [])
        self.assertIsNone(self.session.reason)
        before = sink.idr_count
        self.at(1.1)                                        # 8.1 s after the drawer started
        self.assertEqual(self.screen.events, ["drawer"])
        self.assertEqual(sink.asked[before:], [])           # the new drawer gets its first second
        self.at(1.1)
        self.assertEqual(sink.asked[before:][:1], ["no picture yet"])
        self.assertIsNone(self.session.reason)
        self.at(5.9)
        self.assertEqual(self.screen.events, ["drawer"])    # the second drawer has its own 8 s
        self.assertIsNone(self.session.reason)
        self.at(1.1)
        self.assertEqual(self.screen.events, ["drawer"])    # no third one
        self.assertEqual(self.session.reason, "the drawer showed no picture")

    def test_no_picture_is_not_asked_for_while_the_relay_holds_data(self):
        sink = self.session.sink
        self.session.relay = FakeRelay(0, "127.0.0.1", None)
        self.session.relay.queued = 1 << 20
        for _ in range(3):
            self.at(1.5)
        self.assertEqual(sink.asked, [])
        self.session.relay.queued = 0                       # drained: the second starts now
        self.at(0.5)
        self.assertEqual(sink.asked, [])
        self.at(0.6)
        self.assertEqual(sink.asked, ["no picture yet"])

    def test_a_new_drawer_drops_what_the_relay_held_for_the_old_one(self):
        self.session.relay = FakeRelay(0, "127.0.0.1", None)
        self.session.relay.queued = 1 << 20
        self.session.new_drawer()
        self.assertEqual(self.session.relay.queued, 0)

    def test_a_picture_in_time_means_no_restart(self):
        self.session.watch.feed(PICTURE)
        self.at(60)
        self.assertEqual(self.screen.events, [])
        self.assertIsNone(self.session.reason)

    def test_a_picture_from_the_second_drawer_keeps_the_session(self):
        self.at(8.1)
        self.session.watch.feed(PICTURE)
        self.at(60)
        self.assertEqual(self.screen.events, ["drawer"])
        self.assertIsNone(self.session.reason)

    def test_the_end_tears_down_closes_and_gives_the_screen_back(self):
        self.at(8.1)
        self.at(8.1)
        sock = self.session.rtsp = socket.socket()
        self.session.finish()
        self.assertTrue(self.session.sink.torn_down)
        self.assertEqual(self.screen.events[-1], "give_back")
        self.assertEqual(sock.fileno(), -1)
        self.assertEqual(self.session.conn.fileno(), -1)

    def test_a_failing_step_does_not_stop_the_next_ones(self):
        class Bad:
            def stop(self):
                raise RuntimeError("boom")
        self.session.relay = Bad()
        self.session.sink.teardown = lambda: 1 / 0
        self.session.rtsp = socket.socket()
        self.session.finish()
        self.assertEqual(self.screen.events[-1], "give_back")


class StopDrawerTest(unittest.TestCase):
    def setUp(self):
        self.saved = (miracast.TERM_WAIT, miracast.KILL_WAIT)

    def tearDown(self):
        miracast.TERM_WAIT, miracast.KILL_WAIT = self.saved

    def test_sigterm_then_wait_then_sigkill(self):
        with Rig():
            proc = StubbornProc(["gst"])
            screen = miracast.Screen(systemctl=lambda *a: Out(), light=None, popen=lambda *a, **k: proc)
            screen.start_drawer()
            screen.stop_drawer()
            self.assertEqual(proc.events, ["terminate", "wait", "kill", "wait"])
            self.assertIsNone(screen.drawer)

    def test_a_drawer_that_is_not_killed_either_is_left_behind_in_bounded_time(self):
        with Rig():
            miracast.TERM_WAIT = miracast.KILL_WAIT = 0.05

            class Unkillable(StubbornProc):
                def kill(self):
                    self.events.append("kill")
            proc = Unkillable(["gst"])
            screen = miracast.Screen(systemctl=lambda *a: Out(), light=None, popen=lambda *a, **k: proc)
            screen.start_drawer()
            begun = time.monotonic()
            screen.stop_drawer()
            self.assertLess(time.monotonic() - begun, 2)
            self.assertIsNone(screen.drawer)

    def test_systemctl_that_hangs_is_cut_off(self):
        saved, miracast.SYSTEMCTL_WAIT = miracast.SYSTEMCTL_WAIT, 0.2
        try:
            def hang(*a, **k):
                raise subprocess.TimeoutExpired("systemctl", 0.2)
            real, subprocess.run = subprocess.run, hang
            try:
                result = miracast.systemctl("stop", "kodi.service")
            finally:
                subprocess.run = real
            self.assertEqual((result.returncode, result.stdout), (124, ""))
        finally:
            miracast.SYSTEMCTL_WAIT = saved


STUCK_DRAWER = ("import signal, time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "print('stuck', flush=True)\n"
                "time.sleep(120)\n")


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class StuckDrawerSessionTest(unittest.TestCase):
    """A real process as the drawer that never reads its input and ignores SIGTERM; the real relay and the
    real Screen around it, a fake PC on the other side."""

    def setUp(self):
        self.saved = (miracast.TERM_WAIT, miracast.STUCK_LIMIT)
        miracast.TERM_WAIT, miracast.STUCK_LIMIT = 0.3, 100
        self.rig = Rig().__enter__()
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()
        self.rig.__exit__()
        miracast.TERM_WAIT, miracast.STUCK_LIMIT = self.saved

    def popen(self, argv, **kw):
        self.procs.append(subprocess.Popen([sys.executable, "-c", STUCK_DRAWER], **kw))
        return self.procs[-1]

    def start(self, teardown=None):
        screen = miracast.Screen(systemctl=lambda *a: Out(), light=lambda: (None, 1920, 1080), popen=self.popen)
        pc = FakePc()
        pc.run = lambda: SessionTest.hold(pc, teardown=teardown)
        a, b = socket.socketpair()
        port = free_udp_port()
        session = miracast.Session(a, "127.0.0.1", screen, rtp_port=port,
                                   connect=lambda ip, p: socket.create_connection(("127.0.0.1", pc.port), timeout=5))
        thread = threading.Thread(target=session.run, daemon=True)
        thread.start()
        b.sendall(source_ready("TEST-PC", pc.port))
        SessionTest.wait_for(lambda: session.relay is not None and session.sink.playing)
        SessionTest.wait_for(lambda: "stuck" in open(miracast.DRAW_LOG).read())
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        payload, seq = bytes([0x47]) + bytes(187), 0
        payload *= 7
        end = time.monotonic() + 10
        while session.relay.dropped == 0 and time.monotonic() < end:
            for _ in range(300):
                tx.sendto(rtp(seq % 65536, payload), ("127.0.0.1", port))
                seq += 1
            time.sleep(0.05)
        tx.close()
        self.assertGreater(session.relay.dropped, 0, "the pipe never filled")
        return session, thread, b, screen

    def test_stop_projection_is_handled_and_the_drawer_is_killed(self):
        session, thread, b, screen = self.start()
        begun = time.monotonic()
        b.sendall(mice(2))
        thread.join(8)
        self.assertFalse(thread.is_alive())
        self.assertLess(time.monotonic() - begun, 6)
        self.assertEqual(session.reason, "the PC stopped projecting")
        self.assertEqual(self.procs[0].wait(5), -9)         # SIGTERM was ignored: SIGKILL
        self.assertFalse(screen.taken)
        b.close()

    def test_a_teardown_from_the_pc_is_handled(self):
        teardown = threading.Event()
        session, thread, b, screen = self.start(teardown)
        teardown.set()
        thread.join(8)
        self.assertFalse(thread.is_alive())
        self.assertEqual(session.reason, "the source tore down")
        self.assertEqual(self.procs[0].wait(5), -9)
        self.assertFalse(screen.taken)
        b.close()

    def test_keep_alives_are_answered_and_the_idr_asked_for(self):
        session, thread, b, screen = self.start()
        self.assertGreater(session.relay.dropped, 0)
        SessionTest.wait_for(lambda: session.sink.idr_count >= 1)   # a drop is a loss: a keyframe is asked for
        b.sendall(mice(2))
        thread.join(8)
        self.assertFalse(thread.is_alive())
        b.close()


class SplashTest(unittest.TestCase):
    def test_the_paths_are_airplays(self):
        self.assertEqual((miracast.SPLASH, miracast.SPLASH_CACHE), (airplay.SPLASH, airplay.SPLASH_CACHE))

    def test_light_screen_paints_through_the_fallback(self):
        import inspect
        self.assertIn("paint_or_black(fd, dumb, mode.hdisplay, mode.vdisplay)", inspect.getsource(miracast.light_screen))

    def test_painting_that_fails_leaves_the_screen_black(self):
        with Rig():
            for error in (OSError("no map"), ValueError("bad"), MemoryError("big")):
                def boom(fd, dumb, w, h, error=error):
                    raise error
                miracast.paint_or_black(3, None, 1920, 1080, paint=boom)   # does not raise
            with open(miracast.LOG) as f:
                self.assertEqual(f.read().count("black instead"), 3)

    def test_without_a_picture_nothing_is_mapped(self):
        saved_pixels, saved_ioctl = miracast.splash_pixels, miracast.fcntl.ioctl
        miracast.splash_pixels = lambda w, h: None

        def no_ioctl(*a):
            raise AssertionError("the buffer must stay black")
        miracast.fcntl.ioctl = no_ioctl
        try:
            miracast.paint_splash(3, None, 8, 8)
        finally:
            miracast.splash_pixels, miracast.fcntl.ioctl = saved_pixels, saved_ioctl

    def test_pixels_come_from_the_cache_and_without_ffmpeg_or_picture_are_none(self):
        with tempfile.TemporaryDirectory() as d:
            splash = os.path.join(d, "splash.png")
            open(splash, "wb").close()
            raw = os.path.join(d, "splash-4x2.xrgb")
            with open(raw, "wb") as f:
                f.write(bytes(range(32)))
            os.utime(raw, (os.path.getmtime(splash) + 5,) * 2)
            real = subprocess.run

            def no_ffmpeg(*a, **k):
                raise FileNotFoundError("ffmpeg")
            subprocess.run = no_ffmpeg
            try:
                self.assertEqual(miracast.splash_pixels(4, 2, splash, d), bytes(range(32)))
                os.remove(raw)
                with Rig():
                    self.assertIsNone(miracast.splash_pixels(4, 2, splash, d))
            finally:
                subprocess.run = real

    def test_rows_are_copied_by_the_pitch(self):
        data = bytes(range(16))                  # 2 x 2 pixels
        tight, wide = bytearray(16), bytearray(24)
        miracast.put_rows(tight, data, 2, 2, 8)
        miracast.put_rows(wide, data, 2, 2, 12)
        self.assertEqual(bytes(tight), data)
        self.assertEqual(bytes(wide), data[:8] + bytes(4) + data[8:] + bytes(4))


class AudioDelayTest(unittest.TestCase):
    AUDIO = ("d. ! audio/mpeg,mpegversion=4,stream-format=adts ! queue leaky=downstream%s max-size-buffers=0"
             " max-size-bytes=0 max-size-time=%d ! aacparse ! avdec_aac ! audioconvert ! audioresample"
             " ! alsasink buffer-time=40000 latency-time=10000 sync=false async=false")

    @staticmethod
    def branches(args):
        launch = " ".join(args[args.index("gst-launch-1.0"):])
        video, _, audio = launch.partition(" d. ! audio")
        return video, "d. ! audio" + audio

    def test_the_default_audio_has_a_short_card_buffer_and_a_bounded_leaky_queue(self):
        self.assertEqual(miracast.AUDIO_DELAY_MS, 0)
        self.assertEqual(miracast.AUDIO_QUEUE_MS, 100)
        self.assertEqual(miracast.AUDIO_BUFFER_US, 40000)
        self.assertEqual(miracast.drawer(), miracast.drawer(0))
        self.assertEqual(self.branches(miracast.drawer())[1], self.AUDIO % ("", 100000000))

    def test_a_delay_holds_the_sound_in_its_leaky_queue_and_leaves_the_video_alone(self):
        video0, audio0 = self.branches(miracast.drawer())
        video, audio = self.branches(miracast.drawer(150))
        self.assertEqual(audio, self.AUDIO % (" min-threshold-time=150000000", 250000000))
        self.assertEqual(video, video0)
        self.assertIn("v4l2h264dec ! queue max-size-buffers=1 leaky=downstream ! kmssink sync=false async=false", video)
        self.assertEqual(miracast.drawer(150)[:miracast.drawer(150).index("gst-launch-1.0")], miracast.AS_MEDIA + ["GST_DEBUG=2,bufferpool:1"])

    def test_the_file_is_read_when_it_holds_a_number_from_0_to_1000(self):
        saved = miracast.AUDIO_DELAY_MS
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "delay")
            self.assertEqual(miracast.audio_delay_ms(path), 0)              # no file
            for text, want in (("150\n", 150), ("0", 0), (" 1000 ", 1000), ("1001", 0), ("-5", 0), ("abc", 0), ("", 0),
                               ("12.5", 0), ("150 ms", 0)):
                with open(path, "w") as f:
                    f.write(text)
                self.assertEqual(miracast.audio_delay_ms(path), want, text)
            miracast.AUDIO_DELAY_MS = 40                                    # what is used when the file is no good
            try:
                self.assertEqual(miracast.audio_delay_ms(path), 40)
            finally:
                miracast.AUDIO_DELAY_MS = saved

    def test_the_drawer_reads_the_file_at_its_start(self):
        with Rig():
            procs = []
            screen = miracast.Screen(systemctl=lambda *a: Out(), light=lambda: (None, 1, 1),
                                     popen=lambda argv, **k: procs.append(FakeProc(argv)) or procs[-1])
            screen.start_drawer()
            with open(miracast.AUDIO_DELAY_FLAG, "w") as f:
                f.write("150\n")
            screen.start_drawer()
            self.assertNotIn("min-threshold-time=150000000", procs[0].argv)
            self.assertIn("min-threshold-time=150000000", procs[1].argv)

    def test_nothing_in_the_drawer_waits_for_the_audio_pad(self):
        # a stream without sound (Windows may declare the AAC PID and send none) shows its picture:
        # the video branch is complete without the audio one, and neither is linked by pad name
        video, audio = self.branches(miracast.drawer(150))
        self.assertIn("kmssink", video)
        self.assertNotIn("alsasink", video)
        self.assertNotIn("audio_0", video + audio)


class IdrRefreshTest(unittest.TestCase):
    def test_the_file_overrides_the_default_within_0_to_60(self):
        self.assertEqual(miracast.IDR_REFRESH_SECS, 1)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "every")
            self.assertEqual(miracast.idr_refresh_secs(path), 1)
            for text, want in (("5\n", 5), ("0", 0), ("60", 60), ("61", 1), ("-1", 1), ("x", 1), ("", 1), ("2.5", 1)):
                with open(path, "w") as f:
                    f.write(text)
                self.assertEqual(miracast.idr_refresh_secs(path), want, text)

    def test_the_watch_says_so_every_interval_once_there_is_a_picture(self):
        now = [50.0]
        w = miracast.DrawWatch(lambda: now[0], lambda why: None, lambda line: None)
        self.assertFalse(w.refresh_due(3))          # not watching
        w.begin()
        now[0] += 100
        self.assertFalse(w.refresh_due(3))          # no picture yet
        w.feed(PICTURE)
        now[0] += 2.9
        self.assertFalse(w.refresh_due(3))
        now[0] += 0.2
        self.assertTrue(w.refresh_due(3))
        self.assertFalse(w.refresh_due(3))
        now[0] += 3
        self.assertTrue(w.refresh_due(3))
        now[0] += 1000
        self.assertFalse(w.refresh_due(0))          # off
        w.begin()                                   # a new drawer: no picture again
        now[0] += 100
        self.assertFalse(w.refresh_due(3))

    def test_the_session_asks_for_refreshes_and_counts_them_apart(self):
        now = [1000.0]
        screen = FakeScreen()
        a, b = socket.socketpair()
        session = miracast.Session(a, "127.0.0.1", screen, relay=FakeRelay, clock=lambda: now[0])
        session.sink = WatchdogTest.Sink()
        session.idr_refresh = 3
        session.begin_watch()
        asked = len(session.sink.asked)
        session.watch.feed(PICTURE)
        for _ in range(3):
            now[0] += 3.1
            session.check_drawer()
        self.assertEqual(session.sink.asked[asked:], ["refresh"] * 3)
        self.assertEqual(session.refreshes, 3)
        now[0] += 10
        session.idr_refresh = 0
        session.check_drawer()
        self.assertEqual(session.refreshes, 3)
        a.close()
        b.close()

    def test_the_summary_shows_the_refreshes(self):
        r = miracast.RtpRelay(19000, "10.0.0.2", lambda d: True, clock=lambda: 6.0)
        r.summary_at = 0.0
        self.assertIn("4 IDR requests so far (7 refresh)", r.summary(4, 7))


class BitrateTest(unittest.TestCase):
    def test_the_file_sets_the_answer_within_the_range(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bitrate")
            self.assertEqual(miracast.max_bitrate(path), miracast.MAX_BITRATE)
            for text, want in (("8000000\n", 8000000), ("1000000", 1000000), ("50000000", 50000000),
                               ("999999", miracast.MAX_BITRATE), ("50000001", miracast.MAX_BITRATE),
                               ("0", miracast.MAX_BITRATE), ("fast", miracast.MAX_BITRATE), ("", miracast.MAX_BITRATE)):
                with open(path, "w") as f:
                    f.write(text)
                self.assertEqual(miracast.max_bitrate(path), want, text)

    def test_m3_answers_with_it_when_the_file_is_there_at_that_time(self):
        with Rig():
            body = lambda: miracast.m3_body(["microsoft_max_bitrate"], 19000)
            self.assertEqual(body(), "microsoft_max_bitrate: %d\r\n" % miracast.MAX_BITRATE)
            with open(miracast.BITRATE_FLAG, "w") as f:
                f.write("12000000")
            self.assertEqual(body(), "microsoft_max_bitrate: 12000000\r\n")
            with open(miracast.BITRATE_FLAG, "w") as f:
                f.write("999")
            self.assertEqual(body(), "microsoft_max_bitrate: %d\r\n" % miracast.MAX_BITRATE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
