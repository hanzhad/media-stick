#!/bin/bash
# Smoke test of AirPlay screen mirroring's video path on the real device, run from the owner's computer.
#   smoke-airplay.sh
# Takes device/files/usr/local/bin/airplay from this tree (not the deployed one), builds the two pipelines it
# gives UxPlay and the drawer (UxPlay's appsrc replaced by the file, kmssink by fakevideosink: the screen is not
# touched), and runs 20 s of 1080p30 H.264 with motion at a Mac's 6 Mbit/s, made by the Pi's own encoder, through them.
# Acceptance (a Mac's 1080p mirror keeping up; the decoder copying each picture made it 27 at most, on a whole core):
#   every picture comes out, at >= 45 a second (1.5x the Mac's 30),
#   on <= 30% of one core for each second of video (both pipelines together).
# The parts that need no device: tools/test-airplay.py. Needs the device lease (MEDIASTICK_HOLDER, AGENTS.md):
# it takes the hardware decoder for a few seconds.
# Exit: 0 every check passed, 1 a check failed, 2 bad usage, 3 lease refused.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd); . "$here/common.sh"
root=$(cd "$here/.." && pwd)
[ $# -eq 0 ] || { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

require_lease
"${SSH[@]}" 'cat > "/run/user/$(id -u)/airplay-under-test"' < "$root/device/files/usr/local/bin/airplay" || exit 1
"${SSH[@]}" python3 - <<'EOF'
import importlib.machinery, importlib.util, os, resource, shlex, subprocess, sys, time

R = "/run/user/%d" % os.getuid()
SRC, CLIP = R + "/airplay-under-test", R + "/smoke-airplay.h264"
FRAMES, FPS_MIN, CPU_MAX = 600, 45, 0.30
loader = importlib.machinery.SourceFileLoader("airplay", SRC)
spec = importlib.util.spec_from_loader("airplay", loader)
airplay = importlib.util.module_from_spec(spec)
loader.exec_module(airplay)
fails = 0


def check(ok, what):
    global fails
    print(("PASS  " if ok else "FAIL  ") + what, flush=True)
    fails += not ok


def cpu():
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return ru.ru_utime + ru.ru_stime


try:
    enc = subprocess.run(
        ["gst-launch-1.0", "-q", "videotestsrc", "num-buffers=%d" % FRAMES, "pattern=smpte", "horizontal-speed=8",
         "!", "video/x-raw,width=1920,height=1080,framerate=30/1,format=I420", "!", "v4l2h264enc",
         "extra-controls=controls,video_bitrate=6000000",   # a Mac mirroring 1080p sent about 6 Mbit/s
         "!", "video/x-h264,level=(string)4", "!", "h264parse", "!", "filesink", "location=" + CLIP],
        capture_output=True, text=True)
    check(enc.returncode == 0 and os.path.getsize(CLIP) > 100000,
          "a 1080p30 clip made by the hardware encoder (%s bytes)" % (os.path.getsize(CLIP) if os.path.exists(CLIP) else 0))
    if enc.returncode:
        print(enc.stdout[-800:], enc.stderr[-800:])
        sys.exit(1)

    r, w = os.pipe()
    ux = airplay.uxplay(w)
    vd, vc, vs = (ux[ux.index(o) + 1] for o in ("-vd", "-vc", "-vs"))
    # UxPlay 1.71's fixed pipeline, its appsrc replaced by the clip
    side = "filesrc location=%s ! queue ! h264parse ! %s ! %s ! videoscale ! %s name=video_sink sync=false" % (
        CLIP, vd, vc, vs)
    dr = airplay.drawer()
    launch = dr[dr.index("gst-launch-1.0"):]
    k = launch.index("kmssink")
    launch[k:k + 1] = ["fakevideosink", "silent=false"]   # with -v: a line per picture

    before, t0 = cpu(), time.monotonic()
    draw = subprocess.Popen(launch, stdin=r, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    uxp = subprocess.Popen(["gst-launch-1.0", "-q"] + shlex.split(side), pass_fds=(w,),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    os.close(r)
    os.close(w)
    ux_out, _ = uxp.communicate(timeout=120)
    ux_used = cpu() - before
    draw_out, _ = draw.communicate(timeout=120)
    wall, used = time.monotonic() - t0, cpu() - before
    pictures = sum(1 for line in draw_out.splitlines() if "last-message = chain" in line)
    check(uxp.returncode == 0, "UxPlay's pipeline as airplay gives it runs (rc %d)" % uxp.returncode)
    check(draw.returncode == 0, "the drawer's pipeline runs (rc %d)" % draw.returncode)
    if uxp.returncode or draw.returncode:
        print(ux_out[-1500:], draw_out[-1500:])
    check(pictures >= FRAMES, "every picture comes out of the decoder (%d of %d)" % (pictures, FRAMES))
    fps = pictures / wall
    check(fps >= FPS_MIN, "%.1f pictures a second, at least %d" % (fps, FPS_MIN))
    share = used / (FRAMES / 30.0)
    check(share <= CPU_MAX, "%.0f%% of one core per second of video (%.2f s for %.0f s: UxPlay side %.2f, drawer %.2f),"
          " at most %.0f%%" % (share * 100, used, FRAMES / 30.0, ux_used, used - ux_used, CPU_MAX * 100))
finally:
    for f in (CLIP, SRC):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
sys.exit(1 if fails else 0)
EOF
