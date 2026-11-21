/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Synthetic fixture for source-exact guarded Microlink startup checks. */
#define _POSIX_C_SOURCE 200809L
#include <setjmp.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/types.h>
#include <time.h>

#define WITH_USB 1
#define WITH_LIBUSB_1_0 1
#define WITH_USB_0_1 0
#define B9600 9600
#define EXIT_FAILURE 1
#define MLINK_MAX_FRAME 64
#define MLINK_MAX_PAYLOAD 32
#define MLINK_STOP_BYTE 0xF7
#define MLINK_INIT_BYTE 0xFD
#define MLINK_NEXT_BYTE 0xFE
#define MLINK_OBJ_PROTOCOL 0
#define LOG_WARNING 4
#define LOG_ERR 3
#define ERROR_FD -1
#define VALID_FD(fd) ((fd) >= 0)

typedef int speed_t;
typedef struct { int seen; size_t len; unsigned char data[16]; } test_object_t;

static int guarded_monitor;
static int is_usb;
static int session_ready;
static int poll_primed;
static int authentication_sent;
static time_t authentication_sent_at;
static int authentication_accepted;
static unsigned int consecutive_timeouts;
static time_t last_poll_success;
static size_t rxbuf_len;
static int upsfd = -1;
static char *device_path = "auto";
static speed_t microlink_baudrate = B9600;
static long guarded_deadline_seconds;
static int test_guard_enabled;
static int test_guarded_option;
static int mock_open_result;
static int mock_open_pending;
static int mock_pending_owner;
static int mock_usb_close_count;
static int mock_initinfo_count;
static int mock_fatal_count;
static int mock_signal_setup_ok;
static int mock_usb_close_attempts;
static int mock_usb_handle_open;
static int mock_simple_send_count;
static int mock_write_send_count;
static unsigned char mock_bytes[32];
static size_t mock_byte_count;
static int inject_signal_on_stop;
static int inject_signal_on_stop_worker;
static int inject_signal_on_init;
static int mock_receive_result;
static int mock_receive_count;
static test_object_t protocol_object;
static jmp_buf fatal_jump;
static int fatal_armed;
static volatile sig_atomic_t test_guarded_signal_flag;

static void guarded_dump_signal_handler(int sig);
static int setup_guarded_dump_signals(void);
static int microlink_send_simple(unsigned char byte);
static int microlink_send_write(unsigned char id, unsigned char offset,
	unsigned char len, const unsigned char *data);
static int microlink_receive_once(void);
static int microlink_prime_poll(void);
static int microlink_start_session_impl(unsigned int max_attempts);
static void upsdrv_initups(void);
static void upsdrv_cleanup(void);

static void upsdebugx(int level, const char *format, ...)
{
	(void)level;
	(void)format;
}

static void upsdebug_hex(int level, const char *label,
	const unsigned char *data, size_t length)
{
	(void)level;
	(void)label;
	(void)data;
	(void)length;
}

static void upslogx(int level, const char *format, ...)
{
	(void)level;
	(void)format;
}

static void fatalx(int status, const char *format, ...)
{
	(void)status;
	(void)format;
	mock_fatal_count++;
	if (fatal_armed) {
		longjmp(fatal_jump, 1);
	}
	abort();
}

static void microlink_trace_frame(int level, const char *label,
	const unsigned char *buf, size_t len)
{
	upsdebug_hex(level, label, buf, len);
}

static void microlink_checksum(const unsigned char *buf, size_t len,
	unsigned char *cb0, unsigned char *cb1)
{
	(void)buf;
	(void)len;
	*cb0 = 0;
	*cb1 = 0;
}

static void *inject_signal_from_worker(void *arg)
{
	(void)arg;
	(void)raise(SIGTERM);
	return NULL;
}

static int ser_send_buf(int fd, const void *buf, size_t len)
{
	(void)fd;
	(void)buf;
	return (int)len;
}

static int microlink_usb_send_bytes(const unsigned char *buf, size_t len)
{
	size_t copy = len;
	if (mock_byte_count + copy > sizeof(mock_bytes)) {
		copy = sizeof(mock_bytes) - mock_byte_count;
	}
	memcpy(mock_bytes + mock_byte_count, buf, copy);
	mock_byte_count += copy;
	if (len == 1) {
		mock_simple_send_count++;
		if (buf[0] == MLINK_STOP_BYTE && inject_signal_on_stop) {
			pthread_t worker;
			inject_signal_on_stop = 0;
			if (inject_signal_on_stop_worker) {
				if (pthread_create(&worker, NULL, inject_signal_from_worker, NULL) != 0) {
					return 0;
				}
				if (pthread_join(worker, NULL) != 0) {
					return 0;
				}
			} else {
				(void)raise(SIGTERM);
			}
		}
		if (buf[0] == MLINK_INIT_BYTE && inject_signal_on_init) {
			inject_signal_on_init = 0;
			(void)raise(SIGTERM);
		}
	} else {
		mock_write_send_count++;
	}
	return 1;
}

static int ser_flush_io(int fd)
{
	(void)fd;
	return 0;
}

static void ser_comm_fail(const char *message)
{
	(void)message;
}

static int microlink_guard_deadline_expired(void)
{
	return 0;
}

static time_t microlink_now(void)
{
	return 100;
}

static int microlink_receive_once(void)
{
	mock_receive_count++;
	return mock_receive_result;
}

static int microlink_usb_guard_begin(long seconds)
{
	guarded_deadline_seconds = seconds;
	return test_guard_enabled;
}

static int microlink_usb_open(void)
{
	mock_usb_handle_open = 1;
	if (mock_open_pending) {
		mock_pending_owner = 1;
	}
	return mock_open_result;
}

static void microlink_usb_close(void)
{
	mock_usb_close_attempts++;
	if (mock_pending_owner) {
		return;
	}
	if (mock_usb_handle_open) {
		mock_usb_close_count++;
		mock_usb_handle_open = 0;
	}
}

static void microlink_read_config(void)
{
}

static const char *getval(const char *name)
{
	if (strcmp(name, "vendorid") == 0 || strcmp(name, "guard_vid") == 0
	 || strcmp(name, "guard_pid") == 0) {
		return "051d";
	}
	if (strcmp(name, "guard_deadline") == 0) {
		return "30";
	}
	return NULL;
}

static int testvar(const char *name)
{
	return strcmp(name, "guarded_monitor") == 0 ? test_guarded_option : 0;
}

static int nut_guard_hex_id(const char *value, uint16_t *result)
{
	(void)value;
	*result = 0x051d;
	return 1;
}

static int ser_open(const char *path)
{
	(void)path;
	return 3;
}

static void ser_set_speed(int fd, const char *path, speed_t baud)
{
	(void)fd;
	(void)path;
	(void)baud;
}

static void ser_set_dtr(int fd, int state)
{
	(void)fd;
	(void)state;
}

static void ser_close(int fd, const char *path)
{
	(void)fd;
	(void)path;
}

static test_object_t *microlink_get_object(int id)
{
	(void)id;
	return &protocol_object;
}

static void reset_fixture(void)
{
	guarded_monitor = 0;
	is_usb = 1;
	session_ready = 0;
	poll_primed = 0;
	authentication_sent = 0;
	authentication_sent_at = 0;
	authentication_accepted = 0;
	consecutive_timeouts = 0;
	last_poll_success = 0;
	rxbuf_len = 0;
	upsfd = -1;
	device_path = "auto";
	mock_open_result = 1;
	mock_open_pending = 0;
	mock_pending_owner = 0;
	mock_usb_close_count = 0;
	mock_usb_close_attempts = 0;
	mock_usb_handle_open = 0;
	mock_initinfo_count = 0;
	mock_fatal_count = 0;
	mock_signal_setup_ok = 0;
	mock_simple_send_count = 0;
	mock_write_send_count = 0;
	mock_byte_count = 0;
	inject_signal_on_stop = 0;
	inject_signal_on_stop_worker = 0;
	inject_signal_on_init = 0;
	mock_receive_result = 0;
	mock_receive_count = 0;
	test_guard_enabled = 1;
	test_guarded_option = 1;
	test_guarded_signal_flag = 0;
	memset(&protocol_object, 0, sizeof(protocol_object));
	mock_signal_setup_ok = setup_guarded_dump_signals() == 0;
}

#define guarded_dump_signal test_guarded_signal_flag
#include "guarded_startup_stop_generated.c"
#undef guarded_dump_signal

static int check(int condition, const char *name)
{
	if (!condition) {
		fprintf(stderr, "FAIL %s\n", name);
		return 0;
	}
	return 1;
}

static int test_main_thread_stop_signal_blocks_retry(void)
{
	reset_fixture();
	guarded_monitor = 1;
	inject_signal_on_stop = 1;
	(void)microlink_start_session_impl(3);
	return check(mock_signal_setup_ok && mock_simple_send_count == 1
		&& mock_bytes[0] == MLINK_STOP_BYTE,
		"main-thread signal during startup STOP permitted INIT or retry");
}

static int test_worker_thread_stop_signal_blocks_retry(void)
{
	reset_fixture();
	guarded_monitor = 1;
	inject_signal_on_stop = 1;
	inject_signal_on_stop_worker = 1;
	(void)microlink_start_session_impl(3);
	return check(mock_signal_setup_ok && mock_simple_send_count == 1
		&& mock_bytes[0] == MLINK_STOP_BYTE,
		"worker-thread signal during startup STOP permitted INIT or retry");
}

static int test_signal_after_init_blocks_receive_next_and_writes(void)
{
	static const unsigned char payload[] = {1, 2};
	int startup_ok;
	reset_fixture();
	guarded_monitor = 1;
	inject_signal_on_init = 1;
	mock_receive_result = 1;
	startup_ok = microlink_start_session_impl(1);
	if (!check(!startup_ok && mock_simple_send_count == 2 && mock_receive_count == 0
		&& mock_bytes[0] == MLINK_STOP_BYTE && mock_bytes[1] == MLINK_INIT_BYTE,
		"signal after INIT permitted receive or NEXT")) {
		return 0;
	}
	if (!check(!microlink_send_write(1, 2, sizeof(payload), payload)
		&& mock_write_send_count == 0,
		"guarded descriptor/auth writer sent after stop request")) {
		return 0;
	}
	return 1;
}

static int test_cleanup_stop_remains_separate(void)
{
	reset_fixture();
	guarded_monitor = 1;
	mock_usb_handle_open = 1;
	protocol_object.seen = 1;
	(void)raise(SIGTERM);
	upsdrv_cleanup();
	return check(mock_simple_send_count == 1 && mock_bytes[0] == MLINK_STOP_BYTE
		&& mock_usb_close_count == 1,
		"final cleanup STOP was not preserved as the separate best-effort path");
}

static int run_initups(int guarded, int open_result, int pending, int *continued)
{
	reset_fixture();
	test_guarded_option = guarded;
	mock_open_result = open_result;
	mock_open_pending = pending;
	fatal_armed = 1;
	if (setjmp(fatal_jump) == 0) {
		upsdrv_initups();
		*continued = 1;
		mock_initinfo_count++;
		fatal_armed = 0;
		return 0;
	}
	fatal_armed = 0;
	return 1;
}

static int test_guarded_open_pending_fails_before_continuation(void)
{
	int continued = 0;
	int failed = run_initups(1, 0, 1, &continued);
	return check(failed && mock_fatal_count == 1 && !continued
		&& mock_initinfo_count == 0 && mock_pending_owner == 1
		&& mock_usb_close_attempts == 1 && mock_usb_close_count == 0
		&& mock_usb_handle_open,
		"guarded pending open reached initinfo or released retained ownership");
}

static int test_open_success_and_ordinary_fallback_remain(void)
{
	int continued = 0;
	int failed = run_initups(1, 1, 0, &continued);
	if (!check(!failed && continued && mock_fatal_count == 0,
		"guarded successful open did not continue")) {
		return 0;
	}
	if (!check(guarded_deadline_seconds == 30 && mock_signal_setup_ok,
		"guarded open did not retain its validated configuration")) {
		return 0;
	}
	continued = 0;
	failed = run_initups(0, 0, 0, &continued);
	return check(!failed && continued && mock_fatal_count == 0
		&& mock_usb_close_attempts == 0 && mock_usb_handle_open,
		"ordinary open fallback behavior changed");
}

static int test_guarded_open_failure_closes_only_without_owner(void)
{
	int continued = 0;
	int failed = run_initups(1, 0, 0, &continued);
	if (!check(failed && mock_fatal_count == 1 && !continued
		&& mock_usb_close_attempts == 1 && mock_usb_close_count == 1
		&& !mock_usb_handle_open && !mock_pending_owner,
		"guarded failed open did not close an unowned USB handle before fatal")) {
		return 0;
	}
	continued = 0;
	failed = run_initups(1, -1, 0, &continued);
	return check(failed && mock_fatal_count == 1 && !continued
		&& mock_usb_close_attempts == 1 && mock_usb_close_count == 1
		&& !mock_usb_handle_open,
		"negative guarded open result did not close before fatal");
}

int main(void)
{
	int passed = 0;
	passed += test_main_thread_stop_signal_blocks_retry();
	passed += test_worker_thread_stop_signal_blocks_retry();
	passed += test_signal_after_init_blocks_receive_next_and_writes();
	passed += test_cleanup_stop_remains_separate();
	passed += test_guarded_open_pending_fails_before_continuation();
	passed += test_open_success_and_ordinary_fallback_remain();
	passed += test_guarded_open_failure_closes_only_without_owner();
	if (passed != 7) {
		fprintf(stderr, "%d synthetic startup/stop check(s) failed\n", 7 - passed);
		return 1;
	}
	puts("all guarded startup/stop synthetic checks passed");
	return 0;
}
