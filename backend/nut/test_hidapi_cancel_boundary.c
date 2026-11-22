/* SPDX-License-Identifier: MIT
 * Offline native/shared boundary matrix. The included project fixture supplies
 * synthetic HIDAPI symbols; no real HIDAPI implementation is linked.
 * Build and execution are owned by the coordinator.
 */
#define main project_native_test_main
#include "test_hidapi_native.c"
#undef main

enum boundary_case {
	CASE_CANCEL_BEFORE_NATIVE,
	CASE_IO_ERROR_THEN_STOP,
	CASE_SHORT_WRITE_THEN_STOP,
	CASE_FULL_WRITE_THEN_STOP,
	CASE_HID_MINUS2_NO_STOP,
	CASE_HID_MINUS2_WITH_STOP,
	CASE_SENTINEL_NO_STOP,
	CASE_SENTINEL_AFTER_IO,
	CASE_IO_DURING_CONFIRMATION,
	CASE_CLEANUP_MINUS2_NO_RETRY
};

static enum boundary_case scenario;
static int ordinary_callbacks;
static int cleanup_callbacks;
static int confirmation_armed;
static int confirmation_calls;

static int boundary_stop(void *user)
{
	if (confirmation_armed) {
		confirmation_armed = 0;
		confirmation_calls++;
		mlink_shared_operational_fail();
		return 1;
	}
	return wrapped_real_ops->stop_requested(user);
}

static ssize_t boundary_write(void *user, const unsigned char *bytes, size_t length)
{
	if (mlink_shared_cleanup_stop_write_authorized(user)) {
		cleanup_callbacks++;
		if (scenario == CASE_CLEANUP_MINUS2_NO_RETRY) {
			fake.write_result = -2; /* Authentic fake hid_write result. */
			return wrapped_real_ops->write_report(user, bytes, length);
		}
		fake.write_result = 64;
		return wrapped_real_ops->write_report(user, bytes, length);
	}

	ordinary_callbacks++;
	switch (scenario) {
	case CASE_CANCEL_BEFORE_NATIVE:
		fake.stop = 1; /* Native adapter must reject before hid_write. */
		return wrapped_real_ops->write_report(user, bytes, length);
	case CASE_IO_ERROR_THEN_STOP:
		fake.write_result = -1;
		break;
	case CASE_SHORT_WRITE_THEN_STOP:
		fake.write_result = 63;
		break;
	case CASE_FULL_WRITE_THEN_STOP:
		fake.write_result = 64;
		break;
	case CASE_HID_MINUS2_NO_STOP:
	case CASE_HID_MINUS2_WITH_STOP:
		fake.write_result = -2; /* Return value comes from fake hid_write(). */
		break;
	case CASE_SENTINEL_NO_STOP:
		/* Host callback sentinel injection, deliberately without Stop. */
		return -2;
	case CASE_SENTINEL_AFTER_IO:
		/* Pre-latch IO before returning the injected sentinel. */
		mlink_shared_operational_fail();
		fake.stop = 1;
		return -2;
	case CASE_IO_DURING_CONFIRMATION:
		confirmation_armed = 1;
		return -2;
	case CASE_CLEANUP_MINUS2_NO_RETRY:
		return -1; /* No ordinary operation is expected in this case. */
	}

	ssize_t result = wrapped_real_ops->write_report(user, bytes, length);
	if (scenario == CASE_IO_ERROR_THEN_STOP
		|| scenario == CASE_SHORT_WRITE_THEN_STOP
		|| scenario == CASE_FULL_WRITE_THEN_STOP
		|| scenario == CASE_HID_MINUS2_WITH_STOP)
		fake.stop = 1; /* Stop arrives after authentic hid_write returned. */
	fake.write_result = 64; /* Allow the distinct cleanup write to succeed. */
	return result;
}

static const char *const case_names[] = {
	"cancel-before-native",
	"io-error-then-stop",
	"short-write-then-stop",
	"full-write-then-stop",
	"hid-minus2-no-stop",
	"hid-minus2-with-stop",
	"sentinel-no-stop",
	"sentinel-after-health-io",
	"io-during-confirmation",
	"cleanup-minus2-no-retry"
};

static mlink_health_reason_t expected_reason(enum boundary_case which)
{
	if (which == CASE_FULL_WRITE_THEN_STOP) return MLINK_HEALTH_STOP;
#ifdef EXPECT_DISTINCT_STOP
	if (which == CASE_CANCEL_BEFORE_NATIVE) return MLINK_HEALTH_STOP;
#endif
	return MLINK_HEALTH_IO;
}

static int run_cleanup_minus2(void)
{
	mlink_hidapi_native_binding_t binding = {0};
	CHECK(open_operational_binding(&binding, 1) == 0);
	wrapped_ops.write_report = boundary_write;
	mlink_shared_operational_stop();
	CHECK(mlink_shared_operational_snapshot().reason == MLINK_HEALTH_STOP);
	CHECK(!microlink_usb_cleanup_stop());
	CHECK(!microlink_usb_cleanup_stop());
	CHECK(cleanup_callbacks == 1);
	CHECK(fake.write_calls == 1); /* One real fake hid_write; no retry. */
	CHECK(fake.written[1] == 0xF7 && fake.write_length == 64);
	microlink_usb_close();
	mlink_health_snapshot_t after = mlink_shared_operational_snapshot();
	CHECK(after.phase == MLINK_HEALTH_CLEANING);
	CHECK(after.reason == MLINK_HEALTH_STOP && after.cleanup_failed);
	CHECK(!mlink_shared_operational_cleanup_complete());
	mlink_shared_test_unbind();
	CHECK(finish(&binding) == 0);
	printf("%s ordinary_callbacks=0 cleanup_callbacks=%d hid_write=%d phase=%d reason=%d cleanup_failed=1\n",
		case_names[scenario], cleanup_callbacks, fake.write_calls,
		(int)after.phase, (int)after.reason);
	return 0;
}

static int run_write_case(void)
{
	mlink_hidapi_native_binding_t binding = {0};
	mlink_health_snapshot_t before, after;
	unsigned char payload = 0x55;
	int expected_hid_writes;
	CHECK(open_operational_binding(&binding, 1) == 0);
	wrapped_ops.write_report = boundary_write;
	CHECK(mlink_shared_operational_published(0));
	CHECK(mlink_shared_operational_snapshot().phase == MLINK_HEALTH_ACTIVE);
	if (scenario == CASE_IO_DURING_CONFIRMATION) wrapped_ops.stop_requested = boundary_stop;
	CHECK(!microlink_usb_send_bytes(&payload, 1));
	if (scenario == CASE_CANCEL_BEFORE_NATIVE) CHECK(fake.stop);
	if (scenario == CASE_IO_DURING_CONFIRMATION) {
#ifdef EXPECT_DISTINCT_STOP
		CHECK(confirmation_calls == 1);
#else
		CHECK(confirmation_calls == 0);
#endif
		confirmation_armed = 0;
	}
	CHECK(ordinary_callbacks == 1);
	expected_hid_writes = (scenario == CASE_CANCEL_BEFORE_NATIVE
		|| scenario == CASE_SENTINEL_NO_STOP || scenario == CASE_SENTINEL_AFTER_IO
		|| scenario == CASE_IO_DURING_CONFIRMATION) ? 0 : 1;
	CHECK(fake.write_calls == expected_hid_writes);
	if (expected_hid_writes) CHECK(fake.write_length == 64 && fake.written[1] == payload);
	if (scenario == CASE_HID_MINUS2_NO_STOP) CHECK(!fake.stop);
	if (scenario == CASE_HID_MINUS2_WITH_STOP) CHECK(fake.stop);
	if (scenario == CASE_SENTINEL_NO_STOP) CHECK(!fake.stop);
	if (scenario == CASE_SENTINEL_AFTER_IO) CHECK(fake.stop);

	/* The upper layer requests Stop after the ordinary operation has ended. */
	mlink_shared_operational_stop();
	before = mlink_shared_operational_snapshot();
	CHECK(microlink_usb_cleanup_stop()); /* Cleanup callback must succeed. */
	CHECK(cleanup_callbacks == 1);
	CHECK(fake.write_calls == expected_hid_writes + 1);
	CHECK(fake.written[1] == 0xF7 && fake.write_length == 64);
	microlink_usb_close();
	CHECK(fake.close_calls == 1 && mlink_shared_operational_cleanup_complete());
	after = mlink_shared_operational_snapshot();
	CHECK(after.phase == MLINK_HEALTH_FINISHED && !after.cleanup_failed);
	CHECK(before.reason == after.reason);
	CHECK(after.reason == expected_reason(scenario));
	mlink_shared_test_unbind();
	CHECK(finish(&binding) == 0);
	printf("%s ordinary_callbacks=%d cleanup_callbacks=%d ordinary_hid_write=%d cleanup_hid_write=1 phase=%d reason=%d cleanup_failed=0\n",
		case_names[scenario], ordinary_callbacks, cleanup_callbacks,
		expected_hid_writes, (int)after.phase, (int)after.reason);
	return 0;
}

int main(int argc, char **argv)
{
	int which;
	if (argc != 2) return 2;
	for (which = 0; which < (int)(sizeof(case_names) / sizeof(case_names[0])); which++)
		if (strcmp(argv[1], case_names[which]) == 0) break;
	if (which == (int)(sizeof(case_names) / sizeof(case_names[0]))) return 2;
	scenario = (enum boundary_case)which;
	ordinary_callbacks = cleanup_callbacks = 0;
	if (scenario == CASE_CLEANUP_MINUS2_NO_RETRY) return run_cleanup_minus2();
	return run_write_case();
}
