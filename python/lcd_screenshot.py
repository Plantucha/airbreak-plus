#!/usr/bin/env python3

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


TCL_RPC_SEPARATOR = b"\x1a"


class OpenOcdError(RuntimeError):
    pass


class OpenOcdTclRpc:
    def __init__(self, host, port, timeout):
        self.sock = socket.create_connection((host, port), timeout)
        self.sock.settimeout(timeout)
        self.buffer = bytearray()

    def close(self):
        self.sock.close()

    def command(self, command):
        self.sock.sendall(command.encode("utf-8") + TCL_RPC_SEPARATOR)
        while TCL_RPC_SEPARATOR not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OpenOcdError("OpenOCD closed the Tcl RPC connection")
            self.buffer.extend(chunk)

        response, _, remainder = self.buffer.partition(TCL_RPC_SEPARATOR)
        self.buffer = bytearray(remainder)
        return response.decode("utf-8", errors="replace")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def tcl_quote(value):
    if any(char in value for char in "\x00\r\n"):
        raise ValueError("Tcl arguments cannot contain NUL or newlines")
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("$", "\\$")
    value = value.replace("[", "\\[")
    value = value.replace("]", "\\]")
    return f'"{value}"'


def openocd_call(rpc, *words):
    command = " ".join(tcl_quote(str(word)) for word in words)
    wrapped = (
        f"set __lcd_status [catch [list {command}] __lcd_result __lcd_options]; "
        "if {$__lcd_status && $__lcd_result eq \"\"} { "
        "set __lcd_result [dict get $__lcd_options -errorcode] }; "
        'if {$__lcd_status || $__lcd_result ne ""} { '
        'format "%d\\n%s" $__lcd_status $__lcd_result }'
    )
    response = rpc.command(wrapped)
    # OpenOCD also prints nonempty Tcl replies to its console.
    if response == "":
        return ""
    status, separator, result = response.partition("\n")
    if not separator or status not in ("0", "1"):
        raise OpenOcdError(f"invalid Tcl RPC response: {response!r}")
    if status == "1":
        raise OpenOcdError(f"{words[0]} failed: {result}")
    return result


def temporary_path(directory, stem, suffix):
    descriptor, name = tempfile.mkstemp(
        prefix=f".{stem}.", suffix=suffix, dir=directory
    )
    os.close(descriptor)
    return Path(name)


def detect_platform(rpc):
    cpuid = int(openocd_call(rpc, "read_memory", "0xe000ed00", 32, 1), 0)
    cores = {
        0xc24: ("air10", "0xe0042000", (0x413, 0x411)),
        0xc27: ("air11", "0x5c001000", (0x450,)),
    }
    core = (cpuid >> 4) & 0xfff
    if cpuid >> 24 != 0x41 or core not in cores:
        raise OpenOcdError(f"unsupported MCU CPUID 0x{cpuid:08x}")
    platform, address, device_ids = cores[core]
    device_id = int(openocd_call(rpc, "read_memory", address, 32, 1), 0) & 0xfff
    # Early STM32F405/407 silicon reports 0x411; the Cortex-M4 check distinguishes it from F2.
    if device_id not in device_ids:
        raise OpenOcdError(f"unsupported MCU device ID 0x{device_id:03x} (CPUID 0x{cpuid:08x})")
    return platform


def convert_screenshot(convert, ppm_path, png_path, platform="air10"):
    correction = []
    if platform == "air10":
        correction = [
            "-channel", "R", "-evaluate", "multiply", "0.90",
            "-channel", "G", "-evaluate", "multiply", "1.20",
            "-channel", "B", "-evaluate", "multiply", "1.75",
            "+channel", "-gamma", "1.25",
        ]
    subprocess.run(
        [
            convert,
            f"{ppm_path}[0]",
            *correction,
            f"png:{png_path}",
        ],
        check=True,
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture the Air 10 or Air11 LCD through an existing OpenOCD server."
    )
    parser.add_argument("output", nargs="?", type=Path, default=Path("lcd.png"), help="PNG output path (default: lcd.png)")
    parser.add_argument("--host", default="127.0.0.1", help="OpenOCD Tcl RPC host")
    parser.add_argument("--port", type=int, default=6666, help="OpenOCD Tcl RPC port")
    parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="TCP timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--controller", choices=("auto", "ili9341", "ili932x"), default="auto",
        help="Air 10 LCD controller (default: auto)",
    )
    parser.add_argument(
        "--tcl",
        type=Path,
        help="LCD capture Tcl backend (default: selected automatically from the MCU)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.timeout <= 0:
        print("[!] --timeout must be greater than zero", file=sys.stderr)
        return 2

    output = args.output.resolve()
    convert = shutil.which("convert")

    if convert is None:
        print("[!] ImageMagick 'convert' not found", file=sys.stderr)
        return 1
    if output.suffix.lower() != ".png":
        print("[!] Output path must end in .png", file=sys.stderr)
        return 1
    if not output.parent.is_dir():
        print(f"[!] Output directory not found: {output.parent}", file=sys.stderr)
        return 1

    ppm_path = None
    png_path = None
    capture_pending = False

    try:
        ppm_path = temporary_path(output.parent, output.stem, ".ppm")
        png_path = temporary_path(output.parent, output.stem, ".png")
        print(
            f"[*] Connecting to OpenOCD Tcl RPC at {args.host}:{args.port}",
            flush=True,
        )
        with OpenOcdTclRpc(args.host, args.port, args.timeout) as rpc:
            platform = detect_platform(rpc)
            if platform == "air11" and args.controller != "auto":
                raise OpenOcdError("--controller is only supported on Air 10")
            backend_name = "as11-lcd-screenshot.tcl" if platform == "air11" else "lcd_screenshot.tcl"
            tcl_backend = (args.tcl or Path(__file__).resolve().parent.parent / "tcl" / backend_name).resolve()
            if not tcl_backend.is_file():
                raise OpenOcdError(f"Tcl backend not found: {tcl_backend}")
            openocd_call(rpc, "source", tcl_backend)
            if platform == "air11":
                print("[*] Capturing Air11 LCD", flush=True)
                height = int(openocd_call(rpc, "set", "as11_lcd::height"))
                progress = sys.stdout.isatty()
                if progress:
                    print(f"[*] LCD rows: 0/{height}", end="", flush=True)
                try:
                    for first_row in range(0, height, 8):
                        row_count = min(8, height - first_row)
                        capture_pending = True
                        openocd_call(rpc, "as11_lcd::capture", ppm_path, first_row, row_count)
                        capture_pending = False
                        if progress:
                            print(f"\r[*] LCD rows: {first_row + row_count}/{height}", end="", flush=True)
                finally:
                    if progress:
                        print(flush=True)
                openocd_call(rpc, "resume")
            else:
                print(f"[*] Capturing LCD through {args.controller}", flush=True)
                openocd_call(rpc, "lcd_screenshot", ppm_path, args.controller)

        if ppm_path.stat().st_size == 0:
            raise OpenOcdError("OpenOCD produced an empty PPM file")

        convert_screenshot(convert, ppm_path, png_path, platform)
        os.replace(png_path, output)
        print(f"[+] Wrote {output}", flush=True)
        return 0
    except TimeoutError:
        print(f"[!] OpenOCD did not reply within {args.timeout:g}s", file=sys.stderr)
        if capture_pending:
            print(f"[!] Capture may still be running in OpenOCD; partial PPM retained: {ppm_path}", file=sys.stderr)
            print("[!] Wait for OpenOCD to finish before issuing reset run or another capture", file=sys.stderr)
            ppm_path = None
        return 1
    except (OSError, OpenOcdError, ValueError, subprocess.CalledProcessError) as error:
        print(f"[!] {error}", file=sys.stderr)
        return 1
    finally:
        if ppm_path is not None:
            ppm_path.unlink(missing_ok=True)
        if png_path is not None:
            png_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
