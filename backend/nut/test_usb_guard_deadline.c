/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Synthetic callback/deadline replay. No NUT driver or USB API is executed.
 */

#define _POSIX_C_SOURCE 200809L

#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

static struct timespec fake_now;
static int fake_clock_error;
static unsigned int decode_count;
static unsigned int submit_count;
static unsigned int submitted_timeout;
static int submit_result;

static int fake_clock_gettime(clockid_t clock_id, struct timespec *value)
{
	(void)clock_id;
	if (fake_clock_error) {
		return -1;
	}
	*value = fake_now;
	return 0;
}

struct libusb_transfer {
	void *user_data;
	int status;
	int actual_length;
	unsigned char *buffer;
	unsigned int timeout;
};

enum {
	LIBUSB_TRANSFER_COMPLETED = 0,
	LIBUSB_TRANSFER_ERROR = 1,
	LIBUSB_TRANSFER_TIMED_OUT = 2,
	LIBUSB_TRANSFER_STALL = 3,
	LIBUSB_TRANSFER_NO_DEVICE = 4,
	LIBUSB_TRANSFER_OVERFLOW = 5,
	LIBUSB_TRANSFER_CANCELLED = 6
};

#define LIBUSB_CALL

static int libusb_submit_transfer(struct libusb_transfer *transfer)
{
	submit_count++;
	submitted_timeout = transfer->timeout;
	return submit_result;
}

static void libusb_free_transfer(struct libusb_transfer *transfer)
{
	(void)transfer;
}

static void microlink_usb_try_decode_fallback(const unsigned char *data, size_t len)
{
	(void)data;
	(void)len;
	decode_count++;
}

static void upsdebugx(int level, const char *format, ...)
{
	(void)level;
	(void)format;
}

#include "usb_guard_deadline_generated.c"

static int callback_after_expiry(void)
{
	unsigned char bytes[2] = {0x23, 0x55};
	struct libusb_transfer transfer = {NULL, LIBUSB_TRANSFER_COMPLETED, 1, bytes, 0};

#ifdef EXPECT_CANDIDATE
	fake_now.tv_sec = 10;
	fake_now.tv_nsec = 0;
	if (!microlink_usb_guard_begin(1)) {
		return 2;
	}
	microlink_usb_async_xfer_active_set(1);
#else
	microlink_usb_async_xfer_active_set(1);
#endif
	fake_now.tv_sec = 11;
	microlink_usb_async_cb(&transfer);

#ifdef EXPECT_CANDIDATE
	if (submit_count != 0 || decode_count != 0 || async_queue_count != 0
		|| microlink_usb_async_xfer_active_get() != 0) {
		return 2;
	}
	puts("expired callback suppressed decode, queue, and resubmit");
	return 0;
#else
	if (submit_count != 1 || decode_count != 1 || async_queue_count != 1
		|| microlink_usb_async_xfer_active_get() != 1) {
		return 2;
	}
	puts("FAIL callback continued after observation deadline");
	return 1;
#endif
}

#ifdef EXPECT_CANDIDATE
static int valid_callback_and_budget(void)
{
	unsigned int remaining_ms = 0;
	unsigned char bytes[2] = {0x23, 0x55};
	struct libusb_transfer transfer = {NULL, LIBUSB_TRANSFER_COMPLETED, 1, bytes, 0};

	fake_now.tv_sec = 10;
	fake_now.tv_nsec = 0;
	if (!microlink_usb_guard_begin(2)) {
		return 2;
	}
	fake_now.tv_sec = 10;
	fake_now.tv_nsec = 1;
	pthread_mutex_lock(&async_lock);
	if (!microlink_usb_guard_remaining_ms_locked(&remaining_ms)) {
		pthread_mutex_unlock(&async_lock);
		return 2;
	}
	pthread_mutex_unlock(&async_lock);
	if (remaining_ms != 2000) {
		return 2;
	}
	if (!microlink_usb_guard_begin(300)) {
		return 2;
	}
	fake_now.tv_sec = 11;
	fake_now.tv_nsec = 500000000L;
	microlink_usb_async_xfer_active_set(1);
	microlink_usb_async_cb(&transfer);
	if (submit_count != 1 || decode_count != 1 || async_queue_count != 1
		|| submitted_timeout != 500) {
		return 2;
	}
	fake_now.tv_nsec = 999999999L;
	pthread_mutex_lock(&async_lock);
	if (!microlink_usb_guard_remaining_ms_locked(&remaining_ms)) {
		pthread_mutex_unlock(&async_lock);
		return 2;
	}
	pthread_mutex_unlock(&async_lock);
	if (remaining_ms != 1) {
		return 2;
	}
	puts("fixed budget rounded up and valid callback resubmitted within remainder");
	return 0;
}

static int boundary_checks(void)
{
	unsigned int remaining_ms = 0;
	fake_now.tv_sec = 100;
	fake_now.tv_nsec = 900000000L;
	if (!microlink_usb_guard_begin(1)) {
		return 2;
	}
	fake_now.tv_nsec = 900000001L;
	pthread_mutex_lock(&async_lock);
	if (!microlink_usb_guard_remaining_ms_locked(&remaining_ms) || remaining_ms != 1000) {
		pthread_mutex_unlock(&async_lock);
		return 2;
	}
	pthread_mutex_unlock(&async_lock);
	fake_now.tv_sec = 101;
	fake_now.tv_nsec = 100000000L;
	pthread_mutex_lock(&async_lock);
	if (!microlink_usb_guard_remaining_ms_locked(&remaining_ms)) {
		pthread_mutex_unlock(&async_lock);
		return 2;
	}
	pthread_mutex_unlock(&async_lock);
	if (remaining_ms != 800) {
		return 2;
	}
	fake_now.tv_sec = 101;
	fake_now.tv_nsec = 899999999L;
	pthread_mutex_lock(&async_lock);
	if (!microlink_usb_guard_remaining_ms_locked(&remaining_ms)) {
		pthread_mutex_unlock(&async_lock);
		return 2;
	}
	pthread_mutex_unlock(&async_lock);
	if (remaining_ms != 1) {
		return 2;
	}
	fake_now.tv_sec = 101;
	fake_now.tv_nsec = 900000000L;
	if (!microlink_usb_guard_expired()) {
		return 2;
	}
	fake_now.tv_nsec = 900000001L;
	if (!microlink_usb_guard_expired() || microlink_usb_guard_begin(300)) {
		return 2;
	}
	puts("fractional boundary and exact expiry handled correctly");
	return 0;
}

static int clock_error_is_terminal(void)
{
	fake_now.tv_sec = 20;
	fake_now.tv_nsec = 0;
	if (!microlink_usb_guard_begin(2)) {
		return 2;
	}
	fake_clock_error = 1;
	if (!microlink_usb_guard_expired()) {
		return 2;
	}
	fake_clock_error = 0;
	fake_now.tv_sec = 20;
	if (microlink_usb_guard_begin(100)) {
		return 2;
	}
	puts("monotonic clock failure made guard terminal");
	return 0;
}

static int invalid_clock_input_is_terminal(void)
{
	fake_now.tv_sec = 20;
	fake_now.tv_nsec = 1000000000L;
	if (microlink_usb_guard_begin(1) || !microlink_usb_guard_expired()) {
		return 2;
	}
	puts("invalid monotonic timestamp rejected");
	return 0;
}

static int negative_elapsed_is_terminal(void)
{
	fake_now.tv_sec = 10;
	fake_now.tv_nsec = 500000000L;
	if (!microlink_usb_guard_begin(1)) return 2;
	fake_now.tv_nsec--;
	if (!microlink_usb_guard_expired()) return 2;
	fake_now.tv_sec = 11;
	if (microlink_usb_guard_begin(300) || !microlink_usb_guard_expired()) return 2;
	puts("negative elapsed time made guard terminal");
	return 0;
}

static int maximum_budget(void)
{
	unsigned int remaining_ms;
	fake_now.tv_sec = 42;
	if (!microlink_usb_guard_begin(300)) return 2;
	pthread_mutex_lock(&async_lock);
	if (!microlink_usb_guard_timeout_ms_locked(&remaining_ms) || remaining_ms != 300000) {
		pthread_mutex_unlock(&async_lock);
		return 2;
	}
	pthread_mutex_unlock(&async_lock);
	fake_now.tv_nsec = 1;
	if (!microlink_usb_guard_begin(1)) return 2;
	pthread_mutex_lock(&async_lock);
	if (!microlink_usb_guard_timeout_ms_locked(&remaining_ms) || remaining_ms != 300000) {
		pthread_mutex_unlock(&async_lock);
		return 2;
	}
	pthread_mutex_unlock(&async_lock);
	fake_now.tv_sec = 342;
	if (!microlink_usb_guard_expired() || microlink_usb_guard_begin(300)) return 2;
	puts("maximum budget remained finite and nonrenewable");
	return 0;
}

static int explicit_invalidation(void)
{
	fake_now.tv_sec = 10;
	if (!microlink_usb_guard_begin(2)) return 2;
	microlink_usb_async_xfer_active_set(1);
	microlink_usb_guard_invalidate();
	if (!microlink_usb_guard_expired() || microlink_usb_guard_begin(300)
		|| !microlink_usb_async_xfer_active_get()) return 2;
	puts("explicit invalidation remained terminal");
	return 0;
}

static int normal_callbacks(void)
{
	static const int statuses[] = {LIBUSB_TRANSFER_COMPLETED, LIBUSB_TRANSFER_ERROR,
		LIBUSB_TRANSFER_TIMED_OUT, LIBUSB_TRANSFER_STALL, LIBUSB_TRANSFER_OVERFLOW,
		LIBUSB_TRANSFER_CANCELLED, LIBUSB_TRANSFER_NO_DEVICE};
	unsigned char bytes[2] = {0x23, 0x55};
	size_t i;
	for (i = 0; i < sizeof(statuses) / sizeof(statuses[0]); i++) {
		int completed = statuses[i] == LIBUSB_TRANSFER_COMPLETED;
		int terminal = statuses[i] == LIBUSB_TRANSFER_CANCELLED || statuses[i] == LIBUSB_TRANSFER_NO_DEVICE;
		struct libusb_transfer transfer = {NULL, statuses[i], completed, bytes, 888};
		submit_count = decode_count = async_queue_count = async_queue_head = 0;
		usb_device_gone = 0;
		microlink_usb_async_xfer_active_set(1);
		microlink_usb_async_cb(&transfer);
		if (submit_count != (unsigned int)!terminal || decode_count != (unsigned int)completed
			|| async_queue_count != (unsigned int)completed
			|| microlink_usb_async_xfer_active_get() != !terminal
			|| usb_device_gone != (statuses[i] == LIBUSB_TRANSFER_NO_DEVICE)
			|| (!terminal && submitted_timeout != 0)) return 2;
	}
	{
		struct libusb_transfer transfer = {NULL, LIBUSB_TRANSFER_ERROR, 0, bytes, 888};
		submit_result = -1;
		submit_count = 0;
		microlink_usb_async_xfer_active_set(1);
		microlink_usb_async_cb(&transfer);
		if (submit_count != 1 || microlink_usb_async_xfer_active_get() != 0) return 2;
	}
	puts("normal callback and terminal statuses preserved");
	return 0;
}
#endif

int main(int argc, char **argv)
{
	(void)async_xfer;
	(void)async_pump_tid;
	(void)async_pump_stop;
	(void)fake_clock_gettime;
	if (argc != 2) {
		return 2;
	}
	if (strcmp(argv[1], "expired") == 0) {
		return callback_after_expiry();
	}
#ifdef EXPECT_CANDIDATE
	if (strcmp(argv[1], "valid") == 0) {
		return valid_callback_and_budget();
	}
	if (strcmp(argv[1], "clock-error") == 0) {
		return clock_error_is_terminal();
	}
	if (strcmp(argv[1], "invalid-clock") == 0) {
		return invalid_clock_input_is_terminal();
	}
	if (strcmp(argv[1], "boundary") == 0) {
		return boundary_checks();
	}
	if (strcmp(argv[1], "negative") == 0) return negative_elapsed_is_terminal();
	if (strcmp(argv[1], "maximum") == 0) return maximum_budget();
	if (strcmp(argv[1], "invalidate") == 0) return explicit_invalidation();
	if (strcmp(argv[1], "normal") == 0) return normal_callbacks();
#endif
	return 2;
}
