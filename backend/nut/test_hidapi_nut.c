/* SPDX-License-Identifier: GPL-2.0-or-later
 * Extracted NUT protocol -> production core/native/parser -> synthetic HIDAPI.
 * Not a NUT main or a complete protocol receive-decoder replay.
 */
#include "apcmicrolink-hidapi-native.h"
#include "apcmicrolink-hidapi-session.h"
#include <apcmicrolink.h>
#include <apcmicrolink-usb.h>
#include <nut-guarded-policy.h>
#include <hidapi.h>
#include <hidapi_darwin.h>
#include <limits.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#if !defined(MLINK_HIDAPI_NATIVE_CANDIDATE) || defined(MLINK_HIDAPI_SHARED_TEST)
#error "This replay requires production preparation, never test binding"
#endif
#if !defined(WITH_USB) || !WITH_LIBUSB_1_0 || WITH_LIBUSB_0_1
#error "Supply the pinned test-only or legacy-generated USB1 config; these defines are not hardware qualification"
#endif
_Static_assert(MLINK_MAX_FRAME == 256 && MLINK_MAX_PAYLOAD == 253, "NUT framing ABI");

#define LOG_ERR 3
#define LOG_WARNING 4
#define LOG_NOTICE 5
#define ERROR_FD (-1)
#define VALID_FD(fd) ((fd) >= 0)
#define REQUIRE(expr) do { if (!(expr)) { \
	fprintf(stderr, "FAIL line=%d scenario=%s: %s\n", __LINE__, scenario, #expr); \
	return 1; } } while (0)

struct hid_device_ { int synthetic; };
static struct hid_device_ device = { 1 };
static const unsigned char valid_descriptor[] = {
	0x06,0x86,0xff,0x09,0x01,0xa1,0x01,
	0x85,0x07,0x09,0xfd,0x75,0x08,0x95,0x3f,0x81,0x02,
	0x85,0x08,0x09,0xfc,0x75,0x08,0x95,0x3f,0x91,0x02,0xc0
};
typedef struct fake_state {
	struct hid_device_info info;
	struct timespec now;
	char order[128];
	size_t order_len;
	unsigned char reports[16][64];
	int init_calls, enum_calls, free_calls, open_calls, descriptor_calls;
	int read_calls, write_calls, close_calls, exit_calls, serial_calls;
	int config_calls, receive_calls, lookup_calls, fatal_calls;
	int init_fail, open_fail, descriptor_fail, invalid_descriptor, descriptor_stop;
	int exclusive, device_exclusive, write_result, receive_success;
	int stop_after_write, stop_in_read, deadline_in_read, reentrant_write;
	int nested_finish, premature_release, exit_fail;
	int expected_fatal, expected_close, expected_exit, expected_writes;
	int expected_open, expected_descriptor, expected_init, expected_config;
	int supervisor_mode, ready;
	int marker_count;
} fake_state_t;
static fake_state_t fake;
static volatile sig_atomic_t stop_flag;
static const char *scenario;
static int scenario_ok;
static FILE *lifecycle;

static void lifecycle_marker(const char *text)
{
	if (lifecycle == NULL || ++fake.marker_count > 4) _Exit(92);
	if (fprintf(lifecycle, "%s\n", text) < 0 || fflush(lifecycle) != 0) _Exit(92);
	puts(text);
	fflush(stdout);
}

/* The exact NUT structs are supplied by apcmicrolink.h, not copied here. */
static int guarded_monitor, is_usb, hidapi_auth_write_scope, hidapi_finish_called;
static unsigned int guard_probe_attempt_limit, guard_probe_attempts_used;
static long guarded_deadline_seconds;
static size_t rxbuf_len, descriptor_blob_len;
static int poll_primed, authentication_sent, authentication_accepted, session_ready;
static time_t authentication_sent_at, last_poll_success;
static unsigned int consecutive_timeouts;
static int upsfd = ERROR_FD;
static const char *device_path = "auto";
static microlink_page0_state_t page0;
static microlink_object_t objects[256];
static microlink_descriptor_usage_t usage;
static unsigned char descriptor_blob[MLINK_DESCRIPTOR_MAX_BLOB];
static struct { const char *name; const char *value; } options[] = {
	{"hidapi_shared", NULL}, {"guarded_monitor", NULL}, {"hid_fallback", "no"},
	{"guard_probe_attempts", "1"}, {"guard_vid", "1234"}, {"guard_pid", "5678"},
	{"guard_deadline", "20"}, {NULL, NULL}
};

static void mark(char event)
{
	if (fake.order_len + 1 < sizeof(fake.order)) {
		fake.order[fake.order_len++] = event;
		fake.order[fake.order_len] = '\0';
	}
}
static int testvar(const char *name)
{
	for (size_t i = 0; i < sizeof(options) / sizeof(options[0]); i++)
		if (options[i].name && !strcmp(name, options[i].name)) return 1;
	return 0;
}
static const char *getval(const char *name)
{
	for (size_t i = 0; i < sizeof(options) / sizeof(options[0]); i++)
		if (options[i].name && !strcmp(name, options[i].name)) return options[i].value;
	return NULL;
}
static void change_option(const char *name, const char *value, int remove)
{
	for (size_t i = 0; i < sizeof(options) / sizeof(options[0]); i++) {
		if (options[i].name && !strcmp(name, options[i].name)) {
			if (remove) options[i].name = NULL;
			else options[i].value = value;
			return;
		}
	}
	options[7].name = name;
	options[7].value = value;
}
static void upslogx(int level, const char *format, ...)
{
	(void)level; (void)format;
}
static void upsdebugx(int level, const char *format, ...)
{
	(void)level; (void)format;
}
static void fatalx(int status, const char *format, ...)
{
	va_list args;
	(void)status;
	fake.fatal_calls++;
	va_start(args, format);
	fputs("FATAL_STUB: ", stderr);
	vfprintf(stderr, format, args);
	fputc('\n', stderr);
	va_end(args);
	exit(73); /* Real exit deliberately exercises the extracted early atexit. */
}
static int nut_guarded_dump_signal_requested(void) { return stop_flag != 0; }
static void microlink_read_config(void) { fake.config_calls++; }
static void microlink_trace_frame(int level, const char *label, const unsigned char *data, size_t size)
{
	(void)level; (void)label; (void)data; (void)size;
}
static ssize_t ser_send_buf(int fd, const unsigned char *data, size_t size)
{
	(void)fd; (void)data; (void)size; fake.serial_calls++; return -1;
}
static void ser_flush_io(int fd) { (void)fd; fake.serial_calls++; }
static void ser_close(int fd, const char *path) { (void)fd; (void)path; fake.serial_calls++; }
static void ser_comm_fail(const char *text) { (void)text; }
static const microlink_descriptor_usage_t *microlink_find_descriptor_usage(const char *path)
{
	fake.lookup_calls++;
	return path && !strcmp(path, usage.path) ? &usage : NULL;
}
static const microlink_object_t *microlink_get_object(unsigned int id)
{
	if (id >= 256) abort();
	return &objects[id];
}
static microlink_object_t *microlink_get_object_mut(unsigned int id)
{
	if (id >= 256) abort();
	return &objects[id];
}
static int microlink_receive_once(void)
{
	unsigned char ch = 0;
	fake.receive_calls++;
	/* Only this NUT receive/parser boundary is stubbed. The byte is fetched
	 * through real core/native read and is NOT a validated Microlink frame. */
	if (microlink_usb_get_char(&ch, 100000L) != 1 || ch != 0x42 || !fake.receive_success) return 0;
	objects[MLINK_OBJ_PROTOCOL].seen = 1;
	return 1;
}
static int microlink_send_simple(unsigned char byte);
static int microlink_prime_poll(void);
#include "hidapi_nut_generated.c"

int hid_init(void) { mark('I'); fake.init_calls++; return fake.init_fail ? -1 : 0; }
int hid_exit(void)
{
	mark('Z'); fake.exit_calls++;
	if (fake.supervisor_mode) lifecycle_marker("EXIT");
	return fake.exit_fail ? -1 : 0;
}
void hid_darwin_set_open_exclusive(int value) { mark('N'); fake.exclusive = value; }
int hid_darwin_get_open_exclusive(void) { mark('G'); return fake.exclusive; }
int hid_darwin_is_device_open_exclusive(hid_device *handle)
{
	mark('X'); return handle == &device ? fake.device_exclusive : 1;
}
struct hid_device_info *hid_enumerate(unsigned short vid, unsigned short pid)
{
	mark('E'); fake.enum_calls++;
	if (vid != 0x1234 || pid != 0x5678) return NULL;
	return &fake.info;
}
void hid_free_enumeration(struct hid_device_info *list)
{
	mark('F'); if (list == &fake.info) fake.free_calls++;
}
hid_device *hid_open_path(const char *path)
{
	mark('O'); fake.open_calls++;
	if (fake.open_fail || strcmp(path, "synthetic-nut-path")) return NULL;
	return &device;
}
int hid_get_report_descriptor(hid_device *handle, unsigned char *dst, size_t capacity)
{
	size_t count = sizeof(valid_descriptor) - (fake.invalid_descriptor ? 1U : 0U);
	mark('D'); fake.descriptor_calls++;
	if (handle != &device || fake.descriptor_fail || capacity < count) return -1;
	memcpy(dst, valid_descriptor, count);
	if (fake.descriptor_stop) stop_flag = 1;
	return (int)count;
}
int hid_read_timeout(hid_device *handle, unsigned char *dst, size_t capacity, int timeout)
{
	mark('R'); fake.read_calls++;
	if (handle != &device || capacity != 65 || timeout < 0 || !fake.descriptor_calls) return -1;
	if (fake.supervisor_mode) {
		const struct timespec pause = {0, 10000000L};
		if (!fake.ready) { fake.ready = 1; lifecycle_marker("READY"); }
		while (fake.supervisor_mode == 2 || !stop_flag) nanosleep(&pause, NULL);
		return 0;
	}
	memset(dst, 0, 64);
	dst[0] = 7;
	dst[1] = 0x42;
	if (fake.stop_in_read) stop_flag = 1;
	if (fake.deadline_in_read) fake.now.tv_sec = 21;
	return 64;
}
int hid_write(hid_device *handle, const unsigned char *data, size_t size)
{
	int index = fake.write_calls++;
	mark('W');
	if (handle != &device || size != 64 || data[0] != 8 || index >= 16) return -1;
	memcpy(fake.reports[index], data, 64);
	if (fake.stop_after_write == fake.write_calls) stop_flag = 1;
	if (fake.reentrant_write) {
		fake.nested_finish = mlink_shared_finish_native();
		if (fake.close_calls || fake.exit_calls) fake.premature_release++;
	}
	return fake.write_result;
}
void hid_close(hid_device *handle)
{
	mark('C');
	if (handle == &device) fake.close_calls++;
	if (fake.supervisor_mode) lifecycle_marker("CLOSE");
}
int clock_gettime(clockid_t which, struct timespec *now)
{
	if (which != CLOCK_MONOTONIC) return -1;
	*now = fake.now;
	return 0;
}

static void final_verify(void)
{
	if (fake.supervisor_mode == 2) return; /* No PASS marker for the blocked mode. */
	if ((fake.expected_fatal ? fake.fatal_calls != 1 : !scenario_ok)
	 || fake.close_calls != fake.expected_close || fake.exit_calls != fake.expected_exit
	 || fake.write_calls != fake.expected_writes || fake.open_calls != fake.expected_open
	 || fake.descriptor_calls != fake.expected_descriptor || fake.init_calls != fake.expected_init
	 || fake.config_calls != fake.expected_config || fake.serial_calls != 0
	 || fake.premature_release || (fake.expected_fatal && fake.read_calls)) {
		fprintf(stderr, "FAIL final scenario=%s fatal=%d init=%d open=%d descriptor=%d write=%d close=%d exit=%d config=%d serial=%d order=%s\n",
			scenario, fake.fatal_calls, fake.init_calls, fake.open_calls, fake.descriptor_calls,
			fake.write_calls, fake.close_calls, fake.exit_calls, fake.config_calls, fake.serial_calls, fake.order);
		fflush(stderr);
		_Exit(91);
	}
	if (fake.supervisor_mode) return;
	printf("PASS scenario=%s reached=1 init=%d open=%d layout=%d read=%d write=%d close=%d exit=%d probe=%u order=%s\n",
		scenario, fake.init_calls, fake.open_calls, fake.descriptor_calls, fake.read_calls,
		fake.write_calls, fake.close_calls, fake.exit_calls, guard_probe_attempts_used, fake.order);
}
static void setup(void)
{
	fake.now.tv_sec = 1;
	fake.exclusive = 1;
	fake.write_result = 64;
	fake.receive_success = 1;
	fake.expected_close = fake.expected_exit = fake.expected_open = 1;
	fake.expected_descriptor = fake.expected_init = fake.expected_config = 1;
	fake.info.path = "synthetic-nut-path";
	fake.info.vendor_id = 0x1234;
	fake.info.product_id = 0x5678;
	fake.info.bus_type = HID_API_BUS_USB;
	fake.info.interface_number = 0;
	page0.width = 16;
	descriptor_blob_len = 128;
	usage.valid = 1;
	usage.data_offset = 35;
	usage.size = 4;
	strcpy(usage.path, MLINK_DESC_SLAVE_PASSWORD);
	if (atexit(final_verify) != 0) abort();
}
static int admitted(void)
{
	microlink_hidapi_initups();
	REQUIRE(!strcmp(fake.order, "INGEFOXD"));
	REQUIRE(guarded_monitor && is_usb && guard_probe_attempt_limit == 1);
	REQUIRE(!microlink_usb_guard_expired());
	REQUIRE(fake.enum_calls == 1 && fake.free_calls == 1 && fake.write_calls == 0);
	return 0;
}
static int control_report(int index, unsigned char control)
{
	REQUIRE(index < fake.write_calls && fake.reports[index][0] == 8);
	REQUIRE(fake.reports[index][1] == control);
	for (size_t i = 2; i < 64; i++) REQUIRE(fake.reports[index][i] == 0);
	return 0;
}
static void signal_handler(int value) { (void)value; stop_flag = 1; }

static int run_scenario(void)
{
	unsigned char ch = 0xa5;
	const unsigned char auth[] = {0x11,0x22,0x33,0x44};
	const unsigned char auth_report[] = {8,2,3,4,0x11,0x22,0x33,0x44,194,137};
	if (!strncmp(scenario, "invalid-", 8)) {
		const char *which = scenario + 8;
		fake.expected_fatal = 1;
		fake.expected_close = fake.expected_exit = fake.expected_open = 0;
		fake.expected_descriptor = fake.expected_init = fake.expected_config = 0;
		if (!strcmp(which, "flag")) change_option("hidapi_shared", NULL, 1);
		else if (!strcmp(which, "guard")) change_option("guarded_monitor", NULL, 1);
		else if (!strcmp(which, "port")) device_path = "synthetic-serial";
		else if (!strcmp(which, "fallback")) change_option("hid_fallback", "yes", 0);
		else if (!strcmp(which, "attempts")) change_option("guard_probe_attempts", "2", 0);
		else if (!strcmp(which, "vid-zero")) change_option("guard_vid", "0000", 0);
		else if (!strcmp(which, "pid-zero")) change_option("guard_pid", "0000", 0);
		else if (!strcmp(which, "deadline-zero")) change_option("guard_deadline", "0", 0);
		else if (!strcmp(which, "deadline-large")) change_option("guard_deadline", "301", 0);
		else if (!strcmp(which, "deadline-overflow")) change_option("guard_deadline", "9999999999999999999999999999999999", 0);
		else if (!strcmp(which, "filter")) change_option("vendor", "synthetic", 0);
		else if (!strcmp(which, "baudrate")) change_option("baudrate", "9600", 0);
		else return 1;
		microlink_hidapi_initups();
		return 1; /* Must reach fatal, not merely a failed return. */
	}
	if (!strncmp(scenario, "fatal-", 6)) {
		const char *which = scenario + 6;
		fake.expected_fatal = 1;
		if (!strcmp(which, "init")) {
			fake.init_fail = 1;
			fake.expected_close = fake.expected_exit = fake.expected_open = fake.expected_descriptor = 0;
		} else if (!strcmp(which, "open")) {
			fake.open_fail = 1; fake.expected_close = fake.expected_descriptor = 0;
		} else if (!strcmp(which, "descriptor")) fake.invalid_descriptor = 1;
		else if (!strcmp(which, "descriptor-read")) fake.descriptor_fail = 1;
		else if (!strcmp(which, "descriptor-stop")) fake.descriptor_stop = 1;
		else if (!strcmp(which, "exclusive")) {
			fake.device_exclusive = 1; fake.expected_descriptor = 0;
		} else if (strcmp(which, "after-open")) return 1;
		microlink_hidapi_initups();
		if (!strcmp(which, "after-open")) fatalx(1, "synthetic fatal after admitted init, before normal cleanup registration");
		return 1;
	}
	REQUIRE(admitted() == 0);
	if (!strcmp(scenario, "positive-protocol")) {
		REQUIRE(microlink_start_session_impl(3) == 1);
		REQUIRE(fake.read_calls == 1 && fake.receive_calls == 1 && session_ready && poll_primed);
		REQUIRE(guard_probe_attempts_used == 1 && fake.write_calls == 3);
		REQUIRE(control_report(0, MLINK_STOP_BYTE) == 0);
		REQUIRE(control_report(1, MLINK_INIT_BYTE) == 0);
		REQUIRE(control_report(2, MLINK_NEXT_BYTE) == 0);
		REQUIRE(microlink_send_descriptor_write(MLINK_DESC_SLAVE_PASSWORD, auth, sizeof(auth)) == 1);
		REQUIRE(fake.write_calls == 4 && !memcmp(fake.reports[3], auth_report, sizeof(auth_report)));
		for (size_t i = sizeof(auth_report); i < 64; i++) REQUIRE(fake.reports[3][i] == 0);
		REQUIRE(!memcmp(descriptor_blob + 35, auth, 4) && hidapi_auth_write_scope == 0);
		REQUIRE(microlink_start_session_impl(3) == 0 && fake.write_calls == 4);
		fake.expected_writes = 5;
	} else if (!strcmp(scenario, "probe-exhaustion")) {
		fake.receive_success = 0;
		REQUIRE(microlink_start_session_impl(3) == 0);
		REQUIRE(guard_probe_attempts_used == 1 && fake.receive_calls == 1 && fake.write_calls == 2);
		REQUIRE(microlink_start_session_impl(3) == 0 && fake.write_calls == 2);
		fake.expected_writes = 2;
	} else if (!strcmp(scenario, "cleanup-stop") || !strcmp(scenario, "cleanup-signal") || !strcmp(scenario, "cleanup-deadline")) {
		objects[MLINK_OBJ_PROTOCOL].seen = 1;
		if (!strcmp(scenario, "cleanup-signal")) stop_flag = 1;
		if (!strcmp(scenario, "cleanup-deadline")) fake.now.tv_sec = 21;
		fake.expected_writes = !strcmp(scenario, "cleanup-stop");
	} else if (!strcmp(scenario, "partial-write") || !strcmp(scenario, "stop-after-stop")) {
		if (!strcmp(scenario, "partial-write")) fake.write_result = 63;
		else fake.stop_after_write = 1;
		REQUIRE(microlink_start_session_impl(3) == 0 && guard_probe_attempts_used == 1);
		REQUIRE(fake.write_calls == 1 && fake.read_calls == 0);
		REQUIRE(microlink_start_session_impl(3) == 0 && fake.write_calls == 1);
		fake.expected_writes = 1;
	} else if (!strcmp(scenario, "auth-denial")) {
		REQUIRE(!microlink_send_simple_raw(0x41));
		REQUIRE(!microlink_send_descriptor_write(MLINK_DESC_MASTER_PASSWORD, auth, 4));
		REQUIRE(!microlink_send_descriptor_write(MLINK_DESC_SLAVE_PASSWORD, auth, 3));
		REQUIRE(!microlink_send_write(2, 3, 4, auth));
		REQUIRE(fake.write_calls == 0 && fake.lookup_calls == 0);
		usage.size = 8;
		REQUIRE(!microlink_send_descriptor_write(MLINK_DESC_SLAVE_PASSWORD, auth, 4));
		REQUIRE(fake.lookup_calls == 1 && fake.write_calls == 0 && !hidapi_auth_write_scope);
	} else if (!strcmp(scenario, "reentrant-finish")) {
		fake.reentrant_write = 1;
		REQUIRE(!microlink_prime_poll());
		REQUIRE(fake.write_calls == 1 && fake.nested_finish == MLINK_HIDAPI_SESSION_RETAINED);
		REQUIRE(fake.close_calls == 1 && fake.exit_calls == 0 && fake.premature_release == 0);
		fake.expected_writes = 1;
	} else if (!strcmp(scenario, "read-stop") || !strcmp(scenario, "read-deadline")) {
		fake.stop_in_read = !strcmp(scenario, "read-stop");
		fake.deadline_in_read = !strcmp(scenario, "read-deadline");
		REQUIRE(microlink_usb_get_char(&ch, 100000L) < 0 && ch == 0xa5 && fake.read_calls == 1);
	} else if (!strcmp(scenario, "no-fallback")) {
		int a = -1, d = -1, b = -1; long c = -1, r = -1;
		REQUIRE(microlink_usb_hid_fallback_supported() == 0);
		REQUIRE(microlink_usb_get_hid_fallback(1, &a, &d, &b, &c, &r) == 0);
		REQUIRE(microlink_usb_reset_and_reopen() == 0 && microlink_usb_device_gone() == 0);
		REQUIRE(fake.open_calls == 1 && fake.read_calls == 0 && fake.write_calls == 0);
	} else if (!strcmp(scenario, "retained-exit")) {
		fake.exit_fail = 1;
	} else if (!strcmp(scenario, "supervisor-cooperative") || !strcmp(scenario, "supervisor-blocked")) {
		struct sigaction action;
		memset(&action, 0, sizeof(action));
		action.sa_handler = signal_handler;
		sigemptyset(&action.sa_mask);
		REQUIRE(sigaction(SIGINT, &action, NULL) == 0 && sigaction(SIGTERM, &action, NULL) == 0);
		fake.supervisor_mode = !strcmp(scenario, "supervisor-blocked") ? 2 : 1;
		REQUIRE(microlink_usb_get_char(&ch, 100000L) < 0 && stop_flag && fake.ready);
		upsdrv_cleanup();
		REQUIRE(fake.close_calls == 1 && fake.exit_calls == 1);
		lifecycle_marker("FINISH");
		scenario_ok = 1;
		return 0;
	} else return 1;
	upsdrv_cleanup();
	if (fake.expected_writes && objects[MLINK_OBJ_PROTOCOL].seen && !stop_flag && fake.now.tv_sec < 21)
		REQUIRE(control_report(fake.expected_writes - 1, MLINK_STOP_BYTE) == 0);
	upsdrv_cleanup();
	REQUIRE(!microlink_usb_open());
	REQUIRE(fake.open_calls == 1 && fake.close_calls == 1 && fake.exit_calls == 1);
	REQUIRE(hidapi_finish_called == 1);
	scenario_ok = 1;
	return 0;
}
int main(int argc, char **argv)
{
	int fd;
	if (argc < 2) return 2;
	scenario = argv[1];
	if (!strcmp(scenario, "supervisor-cooperative") || !strcmp(scenario, "supervisor-blocked")) {
		if (argc != 3) return 2;
		/* File creation is the sole OS open in this fake. O_EXCL refuses any
		 * existing path, including devices and symlinks; the caller owns the
		 * private output directory. No HIDAPI path reaches this syscall. */
		fd = open(argv[2], O_WRONLY | O_CREAT | O_EXCL, 0600);
		if (fd < 0) return 2;
		lifecycle = fdopen(fd, "w");
		if (lifecycle == NULL) { close(fd); return 2; }
	} else if (argc != 2) return 2;
	setup();
	return run_scenario();
}
