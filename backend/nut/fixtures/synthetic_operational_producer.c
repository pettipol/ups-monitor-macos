/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 UPS Monitor Mac contributors
 * Synthetic-only producer for exercising the continuous operational protocol.
 * It does not communicate with UPS hardware.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stopped;
static int64_t started_ms;
static size_t output_bytes;
static const char *const expected[] = {
    "-s", "ups-monitor-operational-v2", "-d1", "-x", "hidapi_shared",
    "-x", "guarded_monitor", "-x", "port=auto", "-x", "hid_fallback=no",
    "-x", "guard_probe_attempts=1", "-x", "guard_vid=051d", "-x",
    "guard_pid=0003", "-x", "guard_deadline=35", "-x", "monitor_stream_v2"
};
static const char *const fields[] = {
    "ups.status", "battery.charge", "battery.runtime", "battery.voltage",
    "battery.temperature", "ups.temperature", "input.voltage", "input.frequency",
    "output.voltage", "output.current", "output.frequency", "ups.load",
    "experimental.ups.load.apparent", "ups.realpower.nominal", "ups.power.nominal",
    "ups.realpower", "ups.power"
};

static void on_stop(int number) { (void)number; stopped = 1; }
static void on_timeout(int number) { (void)number; _exit(124); }
static int64_t clock_ms(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) _exit(70);
    return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}
static void append(char *buffer, size_t *used, const char *format, ...) {
    va_list args;
    va_start(args, format);
    int count = vsnprintf(buffer + *used, 8192 - *used, format, args);
    va_end(args);
    if (count < 0 || (size_t)count >= 8192 - *used) _exit(73);
    *used += (size_t)count;
}
static void emit(const char *buffer, size_t length) {
    if (length > 8192 || output_bytes + length > 8192) _exit(73);
    while (length) {
        ssize_t count = write(STDOUT_FILENO, buffer, length);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) _exit(74);
        buffer += count; length -= (size_t)count; output_bytes += (size_t)count;
    }
}
static void sample(int sequence) {
    int64_t elapsed = clock_ms() - started_ms;
    int64_t slot = elapsed / 5000;
    if (elapsed < 0 || slot + 1 < sequence) _exit(70);
    char buffer[8192]; size_t used = 0;
    append(buffer, &used, "{\"protocol\":\"ups-monitor.continuous.v2\",\"schema_version\":2,"
        "\"type\":\"sample\",\"sequence\":%d,\"slot\":%lld,\"elapsed_ms\":%lld,"
        "\"missed_slots\":%lld,\"fields\":{", sequence, (long long)slot,
        (long long)elapsed, (long long)(slot + 1 - sequence));
    for (size_t index = 0; index < sizeof(fields) / sizeof(fields[0]); ++index) {
        const char *kind = index >= 15 ? "driverDerived" : index >= 13 ? "static" : "reported";
        const char *value = index == 0 ? "OL" : index == 1 ? (sequence == 1 ? "90" : "91")
            : index == 2 ? (sequence == 1 ? "3000" : "2995") : NULL;
        append(buffer, &used, "%s\"%s\":{\"kind\":\"%s\",\"state\":\"%s\",\"value\":",
            index ? "," : "", fields[index], kind, value ? "observed" : "unavailable");
        if (value) append(buffer, &used, "\"%s\",\"observed_ms\":%lld}", value, (long long)elapsed);
        else append(buffer, &used, "null,\"observed_ms\":null}");
    }
    append(buffer, &used, "}}\n"); emit(buffer, used);
}
static void wait_until(int64_t target) {
    while (!stopped && clock_ms() - started_ms < target) {
        struct timespec delay = {.tv_sec = 0, .tv_nsec = 100000000};
        if (nanosleep(&delay, NULL) != 0 && errno != EINTR) _exit(70);
    }
}
int main(int argc, char **argv) {
    if (argc != 1 + (int)(sizeof(expected) / sizeof(expected[0])) || argv[0][0] != '/') return 64;
    const char *leaf = strrchr(argv[0], '/');
    if (!leaf || strcmp(leaf + 1, "apcmicrolink-hidapi-operational")) return 64;
    for (size_t index = 0; index < sizeof(expected) / sizeof(expected[0]); ++index)
        if (strcmp(argv[index + 1], expected[index])) return 64;
    struct sigaction action = {0}; sigemptyset(&action.sa_mask);
    action.sa_handler = on_stop;
    if (sigaction(SIGTERM, &action, NULL) || sigaction(SIGINT, &action, NULL)) return 70;
    action.sa_handler = on_timeout;
    if (sigaction(SIGALRM, &action, NULL)) return 70;
    action.sa_handler = SIG_IGN;
    if (sigaction(SIGPIPE, &action, NULL)) return 70;
    alarm(30);
    started_ms = clock_ms();
    if (!stopped) sample(1);
    wait_until(5000);
    if (!stopped) sample(2);
    while (!stopped) wait_until(30000);
    int64_t elapsed = clock_ms() - started_ms;
    if (elapsed < 0) return 70;
    char buffer[8192]; size_t used = 0;
    append(buffer, &used, "{\"protocol\":\"ups-monitor.continuous.v2\",\"schema_version\":2,"
        "\"type\":\"end\",\"elapsed_ms\":%lld,\"reason\":\"cancelled\"}\n", (long long)elapsed);
    emit(buffer, used);
    return 0;
}
