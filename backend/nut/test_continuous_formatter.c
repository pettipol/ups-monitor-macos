/* Test-only inclusion harness for the frozen APC diagnostic helpers.
 * Compile with APC_SOURCE set to the hash-pinned staged apcmicrolink.c.
 * This TU never calls the NUT entry point or any device/lifecycle routine.
 */
#include <assert.h>
#include <float.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

static ssize_t mlink_test_write(int fd, const void *bytes, size_t length);
#define write mlink_test_write
#include APC_SOURCE
#undef write
#undef main

enum { TEST_WRITE_FULL, TEST_WRITE_SHORT, TEST_WRITE_ERROR };
static int test_write_mode = TEST_WRITE_FULL;
static unsigned int test_write_calls;
static int test_write_fd;
static size_t test_write_length;
static unsigned char test_write_bytes[8192];

static int contains_bytes(const unsigned char *haystack, size_t haystack_length,
	const char *needle, size_t needle_length)
{
	size_t i;
	if (needle_length > haystack_length) return 0;
	for (i = 0U; i <= haystack_length - needle_length; i++) {
		if (memcmp(haystack + i, needle, needle_length) == 0) return 1;
	}
	return 0;
}

static ssize_t mlink_test_write(int fd, const void *bytes, size_t length)
{
	assert(test_write_calls < 4U);
	test_write_calls++;
	test_write_fd = fd;
	test_write_length = length;
	assert(length <= sizeof(test_write_bytes));
	memcpy(test_write_bytes, bytes, length);
	if (test_write_mode == TEST_WRITE_ERROR) return -1;
	if (test_write_mode == TEST_WRITE_SHORT) return length == 0U ? 0 : (ssize_t)(length - 1U);
	return (ssize_t)length;
}

static void reset_capture(void)
{
	test_write_calls = 0U;
	test_write_fd = -1;
	test_write_length = 0U;
	memset(test_write_bytes, 0, sizeof(test_write_bytes));
	continuous_diag_emitted = 0;
}

static void emit_and_check(int expected_mode)
{
	test_write_mode = expected_mode;
	microlink_diag_emit_summary();
	assert(test_write_calls == 1U);
	assert(test_write_fd == STDERR_FILENO);
	assert(test_write_length > 0U && test_write_length <= 4096U);
	assert(memchr(test_write_bytes, '\n', test_write_length) != NULL);
	assert(continuous_diag_emitted == 1);
	assert(continuous_end_reason == MLINK_CONTINUOUS_END_DURATION_COMPLETE);
	microlink_diag_emit_summary();
	assert(test_write_calls == 1U);
}

int main(void)
{
	struct guarded_buffer { unsigned char before; char data[8]; unsigned char after; } guarded;
	size_t used = 0U;
	uint32_t converted;
	unsigned int i;
	int saved_reason;
	int saved_guard;
	int saved_session_ready;
	int saved_cleanup_done;
	uint32_t saved_counter;
	uint32_t counters_before[DIAG_COUNTER_COUNT];

	/* Counter boundary, discarded increment, out-of-range and mode-off no-op. */
	continuous_mode = 1;
	continuous_diag_counters[DIAG_POLL_ATTEMPT] = UINT32_MAX - 1U;
	continuous_diag_saturated = 0;
	microlink_diag_increment(DIAG_POLL_ATTEMPT);
	assert(continuous_diag_counters[DIAG_POLL_ATTEMPT] == UINT32_MAX);
	assert(continuous_diag_saturated == 0);
	microlink_diag_increment(DIAG_POLL_ATTEMPT);
	assert(continuous_diag_counters[DIAG_POLL_ATTEMPT] == UINT32_MAX);
	assert(continuous_diag_saturated == 1);
	/* Invalid-index and mode-off cases start from nonmaximum values and a false
	 * saturation flag, then compare the entire state before and after. */
	for (i = 0U; i < DIAG_COUNTER_COUNT; i++) continuous_diag_counters[i] = i + 1U;
	continuous_diag_counters[DIAG_POLL_ATTEMPT] = 41U;
	continuous_diag_saturated = 0;
	memcpy(counters_before, continuous_diag_counters, sizeof(counters_before));
	microlink_diag_increment(DIAG_COUNTER_COUNT);
	assert(memcmp(counters_before, continuous_diag_counters, sizeof(counters_before)) == 0);
	assert(continuous_diag_saturated == 0);
	continuous_mode = 0;
	microlink_diag_increment(DIAG_POLL_ATTEMPT);
	assert(memcmp(counters_before, continuous_diag_counters, sizeof(counters_before)) == 0);
	assert(continuous_diag_saturated == 0);
	continuous_mode = 1;

	continuous_diag_time_saturated = 0;
	converted = microlink_diag_time((uint64_t)UINT32_MAX);
	assert(converted == UINT32_MAX && continuous_diag_time_saturated == 0);
	converted = microlink_diag_time((uint64_t)UINT32_MAX + 1U);
	assert(converted == UINT32_MAX && continuous_diag_time_saturated == 1);

	/* Explicitly small destination exercises the real bounded append helper. */
	memset(&guarded, 0xA5, sizeof(guarded));
	assert(microlink_diag_append(guarded.data, sizeof(guarded.data), &used,
		"%s", "012345678") == 0);
	assert(used == 0U && guarded.data[sizeof(guarded.data) - 1U] == '\0');
	assert(guarded.before == 0xA5 && guarded.after == 0xA5);

	/* Undefined optional metadata serializes as JSON null; emitted bytes are
	 * returned on stdout for the separately pinned strict-parser checker. */
	memset(continuous_diag_counters, 0, sizeof(continuous_diag_counters));
	continuous_diag_saturated = 0;
	continuous_diag_time_saturated = 0;
	continuous_diag_cache_time_defined = 0;
	continuous_diag_blob_rows_defined = 0;
	continuous_diag_publication_dynamic_defined = 0;
	continuous_diag_publication_dynamic_count = 0U;
	continuous_diag_terminal_time_defined = 0;
	continuous_diag_last_success_source = "none";
	continuous_diag_last_success_assigned = 0;
	continuous_diag_last_age_defined = 0;
	continuous_diag_last_age = 0.0;
	continuous_diag_first_site = "not_observed";
	continuous_diag_cleanup_invoked = 0;
	continuous_diag_stop_state = "not_reached";
	continuous_diag_finish_state = "not_called";
	continuous_cleanup_clock_ok = 0;
	continuous_cleanup_ok = 0;
	continuous_cleanup_done = 0;
	continuous_end_reason = MLINK_CONTINUOUS_END_DURATION_COMPLETE;
	reset_capture();
	emit_and_check(TEST_WRITE_FULL);
	assert(contains_bytes(test_write_bytes, test_write_length, "\"cache.first_ms\":null", sizeof("\"cache.first_ms\":null") - 1U));
	assert(contains_bytes(test_write_bytes, test_write_length, "\"terminal.elapsed_ms\":null", sizeof("\"terminal.elapsed_ms\":null") - 1U));
	assert(contains_bytes(test_write_bytes, test_write_length, "\"last_success.age_s_at_idle_check\":null", sizeof("\"last_success.age_s_at_idle_check\":null") - 1U));
	assert(fwrite(test_write_bytes, 1U, test_write_length, stdout) == test_write_length);

	/* Artificial serializer-only metadata probes maximum admitted token widths
	 * and representable uint32 values. No real protocol/lifecycle claim follows. */
	for (i = 0U; i < DIAG_COUNTER_COUNT; i++) continuous_diag_counters[i] = UINT32_MAX;
	continuous_diag_saturated = 1;
	continuous_diag_time_saturated = 1;
	continuous_diag_cache_time_defined = 1;
	continuous_diag_cache_first_ms = UINT32_MAX;
	continuous_diag_cache_last_ms = UINT32_MAX;
	continuous_diag_blob_rows_defined = 1;
	continuous_diag_blob_rows_min = 255U;
	continuous_diag_blob_rows_max = 255U;
	continuous_diag_publication_dynamic_defined = 1;
	continuous_diag_publication_dynamic_count = 15U;
	continuous_diag_publication_dynamic_min = UINT32_MAX;
	continuous_diag_publication_dynamic_max = UINT32_MAX;
	continuous_diag_terminal_time_defined = 1;
	continuous_last_elapsed_ms = UINT32_MAX;
	continuous_diag_last_success_source = "handshake";
	continuous_diag_last_success_assigned = 1;
	last_poll_success = 1;
	continuous_diag_last_age_defined = 1;
	continuous_diag_last_age = -DBL_MAX;
	continuous_diag_first_site = "update_post_session";
	consecutive_timeouts = UINT32_MAX;
	continuous_diag_stop_state = "not_required";
	reset_capture();
	emit_and_check(TEST_WRITE_FULL);
	assert(test_write_length <= 4096U);
	assert(contains_bytes(test_write_bytes, test_write_length, "-", 1U));
	assert(fwrite(test_write_bytes, 1U, test_write_length, stdout) == test_write_length);

	/* Failed/short writes do not retry or mutate existing terminal/driver state. */
	saved_reason = continuous_end_reason;
	saved_guard = continuous_guard_error;
	saved_session_ready = session_ready;
	saved_cleanup_done = continuous_cleanup_done;
	saved_counter = continuous_diag_counters[DIAG_POLL_ATTEMPT];
	reset_capture();
	emit_and_check(TEST_WRITE_ERROR);
	assert(test_write_calls == 1U && continuous_end_reason == saved_reason);
	assert(continuous_guard_error == saved_guard);
	assert(session_ready == saved_session_ready && continuous_cleanup_done == saved_cleanup_done);
	assert(continuous_diag_counters[DIAG_POLL_ATTEMPT] == saved_counter);
	reset_capture();
	emit_and_check(TEST_WRITE_SHORT);
	assert(test_write_calls == 1U && continuous_end_reason == saved_reason);
	assert(continuous_guard_error == saved_guard);
	assert(session_ready == saved_session_ready && continuous_cleanup_done == saved_cleanup_done);
	assert(continuous_diag_counters[DIAG_POLL_ATTEMPT] == saved_counter);

	puts("formatter_only=true cases=counter,time,nulls,max_width,append_bounds,write_faults status=PASS");
	return 0;
}
