/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Synthetic-only test for three extracted Microlink scalar races.
 * The active reader models a raw read; get_char and lifecycle are not run.
 * No NUT driver or USB API is linked or executed.
 */

#define _POSIX_C_SOURCE 200809L

#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

static pthread_mutex_t start_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t start_cond = PTHREAD_COND_INITIALIZER;
static unsigned int ready_count = 0;
static unsigned int expected_threads = 2;
static int start_released = 0;
static volatile int observed_device_gone = 0;
static volatile int observed_transfer_active = 0;

static void await_start(void)
{
	pthread_mutex_lock(&start_lock);
	ready_count++;
	pthread_cond_broadcast(&start_cond);
	while (!start_released) {
		pthread_cond_wait(&start_cond, &start_lock);
	}
	pthread_mutex_unlock(&start_lock);
}

static void release_start(void)
{
	pthread_mutex_lock(&start_lock);
	while (ready_count != expected_threads) {
		pthread_cond_wait(&start_cond, &start_lock);
	}
	start_released = 1;
	pthread_cond_broadcast(&start_cond);
	pthread_mutex_unlock(&start_lock);
}

struct libusb_transfer {
	int status;
	int actual_length;
	unsigned char *buffer;
	void *user_data;
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

/* All libusb-shaped functions are file-local inert test stubs. */
static void *nut_libusb_get_context(void)
{
	return NULL;
}

static int libusb_handle_events_timeout_completed(void *context,
	struct timeval *timeout, int *completed)
{
	(void)context;
	(void)timeout;
	(void)completed;
	sched_yield();
	return 0;
}

static void libusb_free_transfer(struct libusb_transfer *transfer)
{
	(void)transfer;
}

static int libusb_submit_transfer(struct libusb_transfer *transfer)
{
	(void)transfer;
	return 0;
}

static void microlink_usb_try_decode_fallback(const unsigned char *data, size_t len)
{
	(void)data;
	(void)len;
}

static void upsdebugx(int level, const char *format, ...)
{
	(void)level;
	(void)format;
}

#include "usb_async_state_generated.c"

static void *pump_thread(void *unused)
{
	(void)unused;
	await_start();
	(void)microlink_usb_async_pump(NULL);
	return NULL;
}

static void *writer_thread(void *unused)
{
	unsigned int index;
	(void)unused;
	await_start();
	for (index = 0; index < 250000U; index++) {
#ifdef EXPECT_CANDIDATE
		microlink_usb_async_pump_stop_set(0);
#else
		async_pump_stop = 0;
#endif
	}
#ifdef EXPECT_CANDIDATE
	microlink_usb_async_pump_stop_set(1);
#else
	async_pump_stop = 1;
#endif
	return NULL;
}

static void *device_reader_thread(void *unused)
{
	unsigned int index;
	(void)unused;
	await_start();
	for (index = 0; index < 250000U; index++) {
		observed_device_gone = microlink_usb_device_gone();
	}
	return NULL;
}

static void *active_reader_thread(void *unused)
{
	unsigned int index;
	(void)unused;
	await_start();
	for (index = 0; index < 250000U; index++) {
#ifdef EXPECT_CANDIDATE
		observed_transfer_active = microlink_usb_async_xfer_active_get();
#else
		observed_transfer_active = async_xfer_active;
#endif
	}
	return NULL;
}

static void *callback_writer_thread(void *unused)
{
	unsigned int index;
	unsigned char report[MLINK_USB_REPORT_TOTAL_LEN] = {0};
	struct libusb_transfer transfer = {
		LIBUSB_TRANSFER_NO_DEVICE, 0, report, NULL
	};
	(void)unused;
	await_start();
	for (index = 0; index < 250000U; index++) {
		microlink_usb_async_cb(&transfer);
	}
	return NULL;
}

static int run_pump_race(void)
{
	pthread_t pump;
	pthread_t writer;
	if (pthread_create(&pump, NULL, pump_thread, NULL) != 0
		|| pthread_create(&writer, NULL, writer_thread, NULL) != 0) {
		fputs("could not create synthetic threads\n", stderr);
		return 2;
	}
	release_start();
	if (pthread_join(writer, NULL) != 0 || pthread_join(pump, NULL) != 0) {
		fputs("could not join synthetic threads\n", stderr);
		return 2;
	}
	puts("async pump shared-state check passed");
	return 0;
}

static int run_callback_race(int active_only)
{
	pthread_t reader;
	pthread_t callback_writer;
	expected_threads = 2;
#ifdef EXPECT_CANDIDATE
	microlink_usb_async_xfer_active_set(1);
#else
	async_xfer_active = 1;
#endif
	if (pthread_create(&reader, NULL,
		active_only ? active_reader_thread : device_reader_thread, NULL) != 0
		|| pthread_create(&callback_writer, NULL, callback_writer_thread, NULL) != 0) {
		fputs("could not create callback-state synthetic threads\n", stderr);
		return 2;
	}
	release_start();
	if (pthread_join(reader, NULL) != 0 || pthread_join(callback_writer, NULL) != 0) {
		fputs("could not join callback-state synthetic threads\n", stderr);
		return 2;
	}
	puts(active_only ? "active callback shared-state check passed"
		: "device-gone callback shared-state check passed");
	return 0;
}

int main(int argc, char **argv)
{
	(void)async_xfer;
	(void)async_pump_tid;
	if (argc != 2) {
		fputs("select exactly one synthetic case\n", stderr);
		return 2;
	}
	if (strcmp(argv[1], "pump") == 0) {
		return run_pump_race();
	}
	if (strcmp(argv[1], "device") == 0) {
		return run_callback_race(0);
	}
	if (strcmp(argv[1], "active") == 0) {
		return run_callback_race(1);
	}
	fputs("unknown synthetic case\n", stderr);
	return 2;
}
