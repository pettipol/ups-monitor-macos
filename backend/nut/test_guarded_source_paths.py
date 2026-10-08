#!/usr/bin/env python3
"""Static call-site checks for a separately patched, pinned NUT source tree."""

from pathlib import Path
import re
import sys


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def verify_sources(main_source: str, libusb_source: str, policy_source: str) -> None:
    entry = main_source.rfind("int main(int argc, char **argv)")
    require(entry >= 0, "could not locate the production main() entry point")
    main_body = main_source[entry:]
    gate = main_body.find('if (testvar("guarded_monitor"))')
    require(gate >= 0, "guarded mode is not gated in production main()")
    first_sibling_io = [
        pos
        for marker in ("upsdrvquery_oneshot(", "sendsignalfnaliases(", "sendsignalpidaliases(")
        if (pos := main_body.find(marker)) >= 0
    ]
    require(first_sibling_io and gate < min(first_sibling_io),
            "guard gate must precede every sibling socket/PID signaling call")

    gate_end = main_body.find("upsdrv_setproctag(upsname);", gate)
    require(gate_end > gate, "guard gate must complete before startup continues")
    gate_text = main_body[gate:gate_end]
    windows_rejection = (
        '# ifdef WIN32\n\t\tfatalx(EXIT_FAILURE,\n'
        '\t\t\t"guarded_monitor is unsupported on Windows because process signaling cannot be excluded");\n'
        '# else'
    )
    require(windows_rejection in gate_text,
            "Windows must fail before reaching process coordination")
    for required in (
        "# ifdef WIN32",
        "unsupported on Windows",
        "if (!nut_guard_allows_dump_mode(dump_data, foreground, cmd != 0,",
        "do_forceshutdown, oldpid_specified",
        "fatalx(EXIT_FAILURE,",
        "requires positive dump count in foreground",
    ):
        require(required in gate_text, f"guard gate is missing {required!r}")
    policy_check = gate_text.find("if (!nut_guard_allows_dump_mode(")
    require(
        gate_text.find("fatalx(EXIT_FAILURE,", policy_check) > policy_check,
        "guard gate must fail closed when the policy rejects startup",
    )

    require("oldpid_specified = 1;" in main_body,
            "explicit -P must be remembered even if PID parsing fails")
    for parser_behavior in (
        "if (nut_debug_level > 0 || dump_data)",
        "foreground = 1;",
        "foreground = 2;",
        "case 'B':\n\t\t\t\tforeground = 0;",
    ):
        require(parser_behavior in main_body,
                f"could not verify foreground parser behavior {parser_behavior!r}")
    require(
        'if (!testvar("guarded_monitor") && (!cmd || do_forceshutdown))'
        in main_body,
        "guarded mode must skip the normal competitor driver.exit block",
    )
    for required in (
        "dump_count > 0",
        "foreground == 1",
        "!command_requested",
        "!force_shutdown",
        "!oldpid_specified",
    ):
        require(required in policy_source,
                f"dump-mode policy helper is missing {required!r}")

    interrupt_match = re.search(
        r"(?m)^static int nut_libusb_get_interrupt\(", libusb_source
    )
    require(interrupt_match is not None, "could not locate interrupt read function")
    after_function = libusb_source[interrupt_match.start():]
    pipe_start = after_function.find("if (ret == LIBUSB_ERROR_PIPE)")
    success_comment = after_function.find("/* In case of success", pipe_start)
    require(pipe_start >= 0 and success_comment > pipe_start,
            "could not locate complete PIPE-error handling block")
    pipe_block = after_function[pipe_start:success_comment]
    guarded_check = pipe_block.find("nut_libusb_guarded_monitor()")
    guarded_return = pipe_block.find("return ret;", guarded_check)
    clear_halt = pipe_block.find("libusb_clear_halt(")
    require(guarded_check >= 0 and guarded_return > guarded_check,
            "PIPE error must return unchanged in guarded mode")
    require(clear_halt > guarded_return,
            "clear-halt fallback must occur only after the guarded return")


def verify_mutation_detection(main_source: str, libusb_source: str,
                              policy_source: str) -> None:
    mutations = (
        (
            main_source.replace('if (testvar("guarded_monitor")) {', "if (0) {", 1),
            libusb_source,
            "removed production main() guard",
        ),
        (
            main_source.replace(
                'fatalx(EXIT_FAILURE,\n\t\t\t\t"guarded_monitor requires positive dump count in foreground and no -c, -k, or -P options");',
                "/* policy rejection no longer fails closed */",
                1,
            ),
            libusb_source,
            "removed the startup rejection fatalx",
        ),
        (
            main_source.replace("oldpid_specified = 1;", "/* -P not recorded */", 1),
            libusb_source,
            "stopped recording explicit -P",
        ),
        (
            main_source.replace(
                'fatalx(EXIT_FAILURE,\n\t\t\t"guarded_monitor is unsupported on Windows because process signaling cannot be excluded");',
                '/* Windows rejection removed */',
                1,
            ),
            libusb_source,
            "removed the Windows fail-closed rejection",
        ),
        (
            main_source.replace("dump_data, foreground, cmd != 0,", "dump_data, foreground, 0,", 1),
            libusb_source,
            "stopped passing command-mode state to the policy",
        ),
        (
            main_source.replace(
                'if (!testvar("guarded_monitor") && (!cmd || do_forceshutdown))',
                "if (!cmd || do_forceshutdown)",
                1,
            ),
            libusb_source,
            "restored the competing driver.exit block",
        ),
        (
            main_source,
            libusb_source.replace(
                "if (nut_libusb_guarded_monitor()) {\n\t\t\treturn ret;\n\t\t}",
                "if (0) {\n\t\t\treturn ret;\n\t\t}",
                1,
            ),
            "removed the guarded PIPE early return",
        ),
    )
    for mutated_main, mutated_libusb, label in mutations:
        if mutated_main == main_source and mutated_libusb == libusb_source:
            raise SystemExit(f"FAIL: could not apply static-test mutation: {label}")
        try:
            verify_sources(mutated_main, mutated_libusb, policy_source)
        except SystemExit:
            continue
        raise SystemExit(f"FAIL: static checks did not catch mutation: {label}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: python3 test_guarded_source_paths.py <patched-nut-source-root>"
        )

    source_root = Path(sys.argv[1])
    main_source = (source_root / "drivers/main.c").read_text(encoding="utf-8")
    libusb_source = (source_root / "drivers/libusb1.c").read_text(encoding="utf-8")
    policy_source = (source_root / "drivers/nut-guarded-policy.h").read_text(
        encoding="utf-8"
    )
    verify_sources(main_source, libusb_source, policy_source)
    verify_mutation_detection(main_source, libusb_source, policy_source)
    print("guarded patched-source call-site checks: PASS")


if __name__ == "__main__":
    main()
