/* SPDX-License-Identifier: GPL-2.0-or-later
 * Synthetic HIDAPI symbols exercise the opt-in production session gate only.
 */
#include "apcmicrolink-hidapi-native.h"
#include "apcmicrolink-hidapi-session.h"
#include "apcmicrolink-hid-descriptor-checked.h"

#include <apcmicrolink-usb.h>
#include <hidapi.h>
#include <hidapi_darwin.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifndef MLINK_HIDAPI_NATIVE_CANDIDATE
int main(void)
{
	if (microlink_usb_guard_begin(1) != 0 || microlink_usb_open() != 0) return 1;
	puts("PASS candidate default OFF remains unbound and fails closed");
	return 0;
}
#else

#define CHECK(expr) do { if (!(expr)) { \
	fprintf(stderr, "FAIL line %d: %s (order=%s)\n", __LINE__, #expr, fake.order); return 1; \
} } while (0)

#define TEST_VID 0x1234U
#define TEST_PID 0x5678U
#define NO_REENTRY 0
#define REENTER_READ 1
#define REENTER_WRITE 2
#define REENTER_CLOSE 3

struct hid_device_ { int synthetic; };
static struct hid_device_ device = { 1 };
static const unsigned char valid_descriptor[] = {
	0x06,0x86,0xff,0x09,0x01,0xa1,0x01,
	0x85,0x07,0x09,0xfd,0x75,0x08,0x95,0x3f,0x81,0x02,
	0x85,0x08,0x09,0xfc,0x75,0x08,0x95,0x3f,0x91,0x02,0xc0
};

typedef struct fake {
	char order[128];
	size_t order_length;
	struct hid_device_info info;
	int initialized;
	int init_rc;
	int exit_rc;
	int exit_calls;
	int enumerate_calls;
	int free_calls;
	int open_calls;
	int open_fail;
	int descriptor_calls;
	int descriptor_fail;
	int stop_in_descriptor;
	int read_calls;
	int write_calls;
	int close_calls;
	int stop;
	int stop_calls;
	int clock_calls;
	int finish_on_stop_check;
	int finish_on_clock_check;
	int reentry;
	int nested_finish;
	int calls_after_finish_inside_api;
	int clock_fail;
	int exclusive;
	int device_exclusive;
	int write_result;
	unsigned char descriptor[sizeof(valid_descriptor)];
	size_t descriptor_length;
	struct timespec now;
} fake_t;

static fake_t fake;
static int setup_done;

static void mark(char event)
{
	if (fake.order_length + 1 < sizeof(fake.order)) {
		fake.order[fake.order_length++] = event;
		fake.order[fake.order_length] = '\0';
	}
}

static int stop_requested(void *user)
{
	fake_t *host = user;
	host->stop_calls++;
	if (host->finish_on_stop_check) {
		host->finish_on_stop_check = 0;
		host->nested_finish = mlink_shared_finish_native();
	}
	return host->stop;
}

int hid_init(void)
{
	mark('I');
	if (fake.init_rc == 0) fake.initialized = 1;
	return fake.init_rc;
}

int hid_exit(void)
{
	mark('Z');
	fake.exit_calls++;
	return fake.exit_rc;
}

void hid_darwin_set_open_exclusive(int exclusive)
{
	mark('N');
	fake.exclusive = exclusive;
}

int hid_darwin_get_open_exclusive(void)
{
	mark('G');
	return fake.exclusive;
}

int hid_darwin_is_device_open_exclusive(hid_device *handle)
{
	mark('X');
	return handle == &device ? fake.device_exclusive : 1;
}

struct hid_device_info *hid_enumerate(unsigned short vendor_id,
	unsigned short product_id)
{
	mark('E');
	fake.enumerate_calls++;
	if (vendor_id != TEST_VID || product_id != TEST_PID) return NULL;
	return &fake.info;
}

void hid_free_enumeration(struct hid_device_info *enumeration)
{
	mark('F');
	if (enumeration == &fake.info) fake.free_calls++;
}

hid_device *hid_open_path(const char *path)
{
	mark('O');
	fake.open_calls++;
	if (strcmp(path, "synthetic-session-path") != 0 || fake.open_fail) return NULL;
	return &device;
}

int hid_get_report_descriptor(hid_device *handle, unsigned char *dst, size_t capacity)
{
	size_t count;
	mark('D');
	fake.descriptor_calls++;
	if (handle != &device || fake.descriptor_fail) return -1;
	if (fake.stop_in_descriptor) fake.stop = 1;
	count = fake.descriptor_length < capacity ? fake.descriptor_length : capacity;
	memcpy(dst, fake.descriptor, count);
	return (int)count;
}

int hid_read_timeout(hid_device *handle, unsigned char *dst, size_t capacity, int timeout)
{
	(void)timeout;
	mark('R');
	fake.read_calls++;
	if (handle != &device || capacity < 64U) return -1;
	memset(dst, 0x5a, 64U);
	dst[0] = 7U;
	if (fake.reentry == REENTER_READ) {
		fake.nested_finish = mlink_shared_finish_native();
		if (fake.close_calls != 0 || fake.exit_calls != 0) {
			fake.calls_after_finish_inside_api++;
		}
	}
	return 64;
}

int hid_write(hid_device *handle, const unsigned char *src, size_t length)
{
	mark('W');
	fake.write_calls++;
	if (handle != &device || src[0] != 8U || length != 64U) return -1;
	if (fake.reentry == REENTER_WRITE) {
		fake.nested_finish = mlink_shared_finish_native();
		if (fake.close_calls != 0 || fake.exit_calls != 0) {
			fake.calls_after_finish_inside_api++;
		}
	}
	return fake.write_result;
}

void hid_close(hid_device *handle)
{
	mark('C');
	if (handle == &device) fake.close_calls++;
	if (fake.reentry == REENTER_CLOSE) {
		fake.nested_finish = mlink_shared_finish_native();
		if (fake.exit_calls != 0) fake.calls_after_finish_inside_api++;
	}
}

int clock_gettime(clockid_t clock_id, struct timespec *now)
{
	fake.clock_calls++;
	if (clock_id != CLOCK_MONOTONIC || fake.clock_fail) return -1;
	if (fake.finish_on_clock_check) {
		fake.finish_on_clock_check = 0;
		fake.nested_finish = mlink_shared_finish_native();
	}
	*now = fake.now;
	return 0;
}

static mlink_hidapi_native_config_t config(void)
{
	mlink_hidapi_native_config_t result = {
		TEST_VID, TEST_PID, stop_requested, &fake
	};
	return result;
}

static void setup(void)
{
	if (setup_done) {
		fputs("FAIL: a one-shot scenario must not reset its fake host\n", stderr);
		exit(1);
	}
	setup_done = 1;
	memset(&fake, 0, sizeof(fake));
	fake.now.tv_sec = 1;
	fake.exclusive = 1;
	fake.write_result = 64;
	fake.descriptor_length = sizeof(valid_descriptor);
	memcpy(fake.descriptor, valid_descriptor, sizeof(valid_descriptor));
	fake.info.path = "synthetic-session-path";
	fake.info.vendor_id = TEST_VID;
	fake.info.product_id = TEST_PID;
	fake.info.bus_type = HID_API_BUS_USB;
	fake.info.interface_number = 0;
}

static mlink_admission_diagnostic_t get_diag(void)
{
	return mlink_shared_admission_diagnostic();
}

static int diag_is(mlink_admission_stage_t stage, mlink_admission_reason_t reason,
	mlink_admission_parser_status_t parser_status)
{
	char order[sizeof(fake.order)];
	int clocks = fake.clock_calls, stops = fake.stop_calls;
	mlink_admission_diagnostic_t diagnostic = get_diag();
	if (diagnostic.stage != stage || diagnostic.reason != reason
	 || diagnostic.parser_status != parser_status) return 0;
	memcpy(order, fake.order, sizeof(order));
	diagnostic = get_diag();
	return diagnostic.stage == stage && diagnostic.reason == reason
		&& diagnostic.parser_status == parser_status
		&& fake.clock_calls == clocks && fake.stop_calls == stops
		&& memcmp(order, fake.order, sizeof(order)) == 0;
}

static int prepare_and_open(void)
{
	mlink_hidapi_native_config_t cfg = config();
	CHECK(mlink_shared_prepare_native(&cfg, 20));
	CHECK(fake.order_length == 0);
	CHECK(microlink_usb_open());
	CHECK(strcmp(fake.order, "INGEFOXD") == 0);
	return 0;
}

static int test_no_prepare(void)
{
	mlink_hidapi_native_config_t cfg = config();
	setup();
	CHECK(!microlink_usb_guard_begin(20));
	CHECK(!microlink_usb_open());
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RELEASED);
	CHECK(!mlink_shared_prepare_native(&cfg, 20));
	CHECK(fake.order_length == 0);
	return 0;
}

static int test_invalid_config_is_one_shot(void)
{
	mlink_hidapi_native_config_t bad, good;
	setup();
	bad = config();
	bad.vendor_id = 0;
	good = config();
	CHECK(!mlink_shared_prepare_native(&bad, 20));
	CHECK(diag_is(MLINK_ADMISSION_STAGE_PREPARE,
		MLINK_ADMISSION_REASON_HOST_FAILED, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(!mlink_shared_prepare_native(&good, 20));
	CHECK(diag_is(MLINK_ADMISSION_STAGE_PREPARE,
		MLINK_ADMISSION_REASON_HOST_FAILED, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RELEASED);
	CHECK(fake.order_length == 0);
	return 0;
}

static int test_prepare_is_no_io_and_one_shot(void)
{
	mlink_hidapi_native_config_t cfg;
	setup();
	cfg = config();
	CHECK(mlink_shared_prepare_native(&cfg, 20));
	CHECK(diag_is(MLINK_ADMISSION_STAGE_NONE, MLINK_ADMISSION_REASON_NONE,
		MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(!mlink_shared_prepare_native(&cfg, 30));
	CHECK(diag_is(MLINK_ADMISSION_STAGE_PREPARE,
		MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(fake.order_length == 0 && fake.exit_calls == 0);
	CHECK(microlink_usb_guard_expired() == 0);
	fake.now.tv_sec = 21;
	CHECK(microlink_usb_guard_expired() == 1);
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RELEASED);
	CHECK(fake.order_length == 0 && fake.exit_calls == 0);
	CHECK(!mlink_shared_prepare_native(&cfg, 20));
	CHECK(diag_is(MLINK_ADMISSION_STAGE_PREPARE,
		MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED, MLINK_ADMISSION_PARSER_NOT_RUN));
	return 0;
}

static int test_prepare_guard_failure(int fail_clock)
{
	mlink_hidapi_native_config_t cfg;
	setup();
	cfg = config();
	fake.stop = !fail_clock;
	fake.clock_fail = fail_clock;
	CHECK(!mlink_shared_prepare_native(&cfg, 20));
	CHECK(diag_is(MLINK_ADMISSION_STAGE_GUARD,
		fail_clock ? MLINK_ADMISSION_REASON_CLOCK_FAILED : MLINK_ADMISSION_REASON_STOP,
		MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(fake.clock_calls == 1 && fake.stop_calls == !fail_clock);
	CHECK(!mlink_shared_prepare_native(&cfg, 20));
	CHECK(fake.clock_calls == 1 && fake.stop_calls == !fail_clock);
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RELEASED);
	CHECK(diag_is(MLINK_ADMISSION_STAGE_GUARD,
		fail_clock ? MLINK_ADMISSION_REASON_CLOCK_FAILED : MLINK_ADMISSION_REASON_STOP,
		MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(fake.order_length == 0 && fake.exit_calls == 0);
	return 0;
}

static int test_prepare_stop(void) { return test_prepare_guard_failure(0); }
static int test_prepare_clock(void) { return test_prepare_guard_failure(1); }

static int test_guarded_sequence_and_finish(void)
{
	mlink_hidapi_native_config_t cfg;
	unsigned char payload = 0xa5, ch = 0;
	setup();
	cfg = config();
	CHECK(mlink_shared_prepare_native(&cfg, 20));
	CHECK(diag_is(MLINK_ADMISSION_STAGE_NONE, MLINK_ADMISSION_REASON_NONE,
		MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(fake.order_length == 0);
	CHECK(!mlink_shared_prepare_native(&cfg, 30));
	CHECK(diag_is(MLINK_ADMISSION_STAGE_PREPARE,
		MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(microlink_usb_open());
	CHECK(diag_is(MLINK_ADMISSION_STAGE_NONE, MLINK_ADMISSION_REASON_NONE,
		MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(microlink_usb_send_bytes(&payload, 1));
	CHECK(fake.write_calls == 1);
	CHECK(microlink_usb_get_char(&ch, 1000000L) == 1);
	CHECK(ch == 0x5a && fake.read_calls == 1);
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RELEASED);
	CHECK(diag_is(MLINK_ADMISSION_STAGE_NONE, MLINK_ADMISSION_REASON_NONE,
		MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(fake.close_calls == 1 && fake.exit_calls == 1);
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RELEASED);
	CHECK(fake.close_calls == 1 && fake.exit_calls == 1);
	CHECK(!microlink_usb_open());
	CHECK(!mlink_shared_prepare_native(&cfg, 20));
	CHECK(diag_is(MLINK_ADMISSION_STAGE_NONE, MLINK_ADMISSION_REASON_NONE,
		MLINK_ADMISSION_PARSER_NOT_RUN));
	return 0;
}

static int test_open_failure_is_terminal(void)
{
	mlink_hidapi_native_config_t cfg;
	mlink_admission_diagnostic_t first, after;
	setup();
	cfg = config();
	fake.open_fail = 1;
	CHECK(mlink_shared_prepare_native(&cfg, 20));
	CHECK(!microlink_usb_open());
	CHECK(diag_is(MLINK_ADMISSION_STAGE_OPEN, MLINK_ADMISSION_REASON_OPEN_NULL,
		MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(fake.open_calls == 1 && fake.descriptor_calls == 0);
	first = get_diag();
	CHECK(!microlink_usb_open());
	after = get_diag();
	CHECK(first.stage == after.stage && first.reason == after.reason
		&& first.parser_status == after.parser_status);
	CHECK(fake.open_calls == 1);
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RELEASED);
	CHECK(diag_is(MLINK_ADMISSION_STAGE_OPEN, MLINK_ADMISSION_REASON_OPEN_NULL,
		MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(fake.close_calls == 0 && fake.exit_calls == 1);
	return 0;
}

static int test_layout_failure(int failure)
{
	mlink_hidapi_native_config_t cfg;
	setup();
	cfg = config();
	fake.descriptor_fail = failure == 0;
	fake.stop_in_descriptor = failure == 1;
	if (failure == 2) fake.descriptor_length--;
	CHECK(mlink_shared_prepare_native(&cfg, 20));
	CHECK(!microlink_usb_open());
	if (failure == 0) CHECK(diag_is(MLINK_ADMISSION_STAGE_LAYOUT,
		MLINK_ADMISSION_REASON_DESCRIPTOR_UNAVAILABLE, MLINK_ADMISSION_PARSER_NOT_RUN));
	if (failure == 1) CHECK(diag_is(MLINK_ADMISSION_STAGE_LAYOUT,
		MLINK_ADMISSION_REASON_CANCELLED, MLINK_ADMISSION_PARSER_NOT_RUN));
	if (failure == 2) CHECK(diag_is(MLINK_ADMISSION_STAGE_LAYOUT,
		MLINK_ADMISSION_REASON_PARSER_REJECTED, MLINK_ADMISSION_PARSER_MALFORMED));
	CHECK(fake.open_calls == 1 && fake.descriptor_calls == 1);
	CHECK(fake.stop == (failure == 1));
	CHECK(strcmp(fake.order, "INGEFOXDC") == 0);
	CHECK(fake.read_calls == 0 && fake.write_calls == 0);
	CHECK(fake.close_calls == 1);
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RELEASED);
	if (failure == 0) CHECK(diag_is(MLINK_ADMISSION_STAGE_LAYOUT,
		MLINK_ADMISSION_REASON_DESCRIPTOR_UNAVAILABLE, MLINK_ADMISSION_PARSER_NOT_RUN));
	if (failure == 1) CHECK(diag_is(MLINK_ADMISSION_STAGE_LAYOUT,
		MLINK_ADMISSION_REASON_CANCELLED, MLINK_ADMISSION_PARSER_NOT_RUN));
	if (failure == 2) CHECK(diag_is(MLINK_ADMISSION_STAGE_LAYOUT,
		MLINK_ADMISSION_REASON_PARSER_REJECTED, MLINK_ADMISSION_PARSER_MALFORMED));
	CHECK(fake.close_calls == 1 && fake.exit_calls == 1);
	return 0;
}

static int test_descriptor_error(void) { return test_layout_failure(0); }
static int test_descriptor_stop(void) { return test_layout_failure(1); }
static int test_descriptor_invalid(void) { return test_layout_failure(2); }

static int test_reentrant_finish_in_report_call(int reentry)
{
	unsigned char payload = 0x42, ch = 0;
	setup();
	CHECK(prepare_and_open() == 0);
	fake.reentry = reentry;
	if (reentry == REENTER_READ) {
		CHECK(microlink_usb_get_char(&ch, 1000000L) < 0);
		CHECK(fake.read_calls == 1 && fake.write_calls == 0);
	} else {
		CHECK(!microlink_usb_send_bytes(&payload, 1));
		CHECK(fake.write_calls == 1 && fake.read_calls == 0);
	}
	CHECK(fake.nested_finish == MLINK_HIDAPI_SESSION_RETAINED);
	CHECK(fake.close_calls == 1 && fake.exit_calls == 0);
	CHECK(fake.calls_after_finish_inside_api == 0);
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RELEASED);
	CHECK(fake.close_calls == 1 && fake.exit_calls == 1);
	return 0;
}

static int test_reentrant_read(void) { return test_reentrant_finish_in_report_call(REENTER_READ); }
static int test_reentrant_write(void) { return test_reentrant_finish_in_report_call(REENTER_WRITE); }

static int test_reentrant_finish_during_close(void)
{
	setup();
	CHECK(prepare_and_open() == 0);
	fake.reentry = REENTER_CLOSE;
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RELEASED);
	CHECK(fake.nested_finish == MLINK_HIDAPI_SESSION_RETAINED);
	CHECK(fake.close_calls == 1 && fake.exit_calls == 1);
	CHECK(fake.calls_after_finish_inside_api == 0);
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RELEASED);
	CHECK(fake.close_calls == 1 && fake.exit_calls == 1);
	return 0;
}

static int test_dispose_failure_retains_without_retry(void)
{
	mlink_hidapi_native_config_t cfg;
	setup();
	cfg = config();
	CHECK(prepare_and_open() == 0);
	fake.exit_rc = -1;
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RETAINED);
	CHECK(fake.close_calls == 1 && fake.exit_calls == 1);
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RETAINED);
	CHECK(!mlink_shared_prepare_native(&cfg, 20));
	CHECK(!microlink_usb_open());
	CHECK(fake.close_calls == 1 && fake.exit_calls == 1);
	return 0;
}

static int test_close_failure(int in_clock)
{
	mlink_hidapi_native_config_t cfg;
	unsigned char payload = 0x42;
	setup();
	cfg = config();
	CHECK(prepare_and_open() == 0);
	/* The callback is inside a native API call. A nested finish cannot
	 * close that still-active native context and must retain it permanently. */
	fake.finish_on_stop_check = !in_clock;
	fake.finish_on_clock_check = in_clock;
	CHECK(!microlink_usb_send_bytes(&payload, 1));
	CHECK(fake.nested_finish == MLINK_HIDAPI_SESSION_RETAINED);
	CHECK(fake.read_calls == 0 && fake.write_calls == 0);
	CHECK(fake.close_calls == 0 && fake.exit_calls == 0);
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RETAINED);
	CHECK(mlink_shared_finish_native() == MLINK_HIDAPI_SESSION_RETAINED);
	CHECK(!mlink_shared_prepare_native(&cfg, 20));
	CHECK(!microlink_usb_open());
	CHECK(fake.close_calls == 0 && fake.exit_calls == 0);
	return 0;
}

static int test_close_failure_in_stop(void) { return test_close_failure(0); }
static int test_close_failure_in_clock(void) { return test_close_failure(1); }

int main(int argc, char **argv)
{
	const struct { const char *name; int (*run)(void); } scenarios[] = {
		{"no-prepare", test_no_prepare},
		{"invalid-config", test_invalid_config_is_one_shot},
		{"prepare-one-shot", test_prepare_is_no_io_and_one_shot},
		{"guard-stop", test_prepare_stop},
		{"guard-clock", test_prepare_clock},
		{"sequence", test_guarded_sequence_and_finish},
		{"open-failure", test_open_failure_is_terminal},
		{"descriptor-error", test_descriptor_error},
		{"descriptor-stop", test_descriptor_stop},
		{"descriptor-invalid", test_descriptor_invalid},
		{"reentrant-read", test_reentrant_read},
		{"reentrant-write", test_reentrant_write},
		{"reentrant-close", test_reentrant_finish_during_close},
		{"close-failure-stop", test_close_failure_in_stop},
		{"close-failure-clock", test_close_failure_in_clock},
		{"dispose-failure", test_dispose_failure_retains_without_retry}
	};
	if (argc != 2) return 2;
	for (size_t i = 0; i < sizeof(scenarios) / sizeof(scenarios[0]); i++) {
		if (strcmp(argv[1], scenarios[i].name) != 0) continue;
		if (scenarios[i].run() != 0) return 1;
		CHECK(setup_done == 1);
		printf("PASS scenario=%s order=%s clock_reads=%d stop_checks=%d\n",
			scenarios[i].name, fake.order, fake.clock_calls, fake.stop_calls);
		return 0;
	}
	return 2;
}
#endif
