/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Synthetic lifecycle observation over extracted candidate functions.
 * No NUT driver, libusb library, or USB device is linked or executed.
 * The fake join runs the captured pump synchronously after stop is set;
 * real pthread scheduling and potentially blocking join behavior are NOT_TESTED.
 */

#define _POSIX_C_SOURCE 200809L
#define WITH_LIBUSB_1_0 1
#define HAVE_PTHREAD 1
#define HAVE_CLOCK_GETTIME 1
#define HAVE_CLOCK_MONOTONIC 1

#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/time.h>

typedef struct usb_dev_handle {
	int marker;
} usb_dev_handle;

typedef struct {
	unsigned int VendorID;
	unsigned int ProductID;
	char *Vendor;
	char *Product;
	char *Serial;
	char *Bus;
	char *Device;
	char *BusPort;
} USBDevice_t;

typedef struct USBDeviceMatcher {
	int unused;
} USBDeviceMatcher_t;

typedef struct usb_communication_subdriver {
	int hid_ep_in;
	void (*close_dev)(usb_dev_handle *);
} usb_communication_subdriver_t;

#define LIBUSB_CALL

struct libusb_transfer;
typedef void (LIBUSB_CALL *libusb_transfer_cb_fn)(struct libusb_transfer *);

struct libusb_transfer {
	void *dev_handle;
	unsigned char *buffer;
	int length;
	int actual_length;
	int status;
	unsigned int timeout;
	void *user_data;
	libusb_transfer_cb_fn callback;
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

#define LIBUSB_ERROR_NOT_FOUND (-5)
#define USB_ENDPOINT_IN 0x80
#define NUT_UNUSED_VARIABLE(value) ((void)(value))

typedef enum {
	TRACE_ALLOC,
	TRACE_SUBMIT,
	TRACE_THREAD_CREATE,
	TRACE_JOIN,
	TRACE_PUMP,
	TRACE_CANCEL,
	TRACE_EVENT_CALLBACK,
	TRACE_CLOSE_DEVICE,
	TRACE_BUFFER_FREE,
	TRACE_TRANSFER_FREE
} trace_event;

typedef struct {
	struct libusb_transfer *transfer;
	unsigned char *buffer;
	void *submitted_user_data;
	int pending;
	int callback_delivered;
	int logical_buffer_frees;
	int logical_transfer_frees;
} transfer_ledger;

static transfer_ledger ledger;
static trace_event trace_events[64];
static size_t trace_count;
static unsigned int submit_count;
static unsigned int submitted_timeout;
static unsigned int event_call_count;
static unsigned int cancel_count;
static unsigned int close_count;
static unsigned int callback_count;
static unsigned int resubmit_after_abandon_count;
static int thread_create_fails;
static int cancel_result;
static int active_scenario_cancel_completed;
static int force_late_dispatch;
static int cancel_requested;
static int device_closed;
static int pending_at_close_owner_cleared;
static int user_data_changed_while_pending;
static int pending_buffer_freed;
static int pending_transfer_freed;
static int duplicate_buffer_free;
static int duplicate_transfer_free;
static int unknown_free_seen;
static int fake_clock_failure;
static struct timespec fake_now;
static void *(*captured_pump)(void *);
static void *captured_pump_argument;
static unsigned int pump_call_count;
static usb_dev_handle fake_device;
static USBDeviceMatcher_t fake_matcher;
static usb_communication_subdriver_t usb_subdriver;
static usb_communication_subdriver_t *comm_driver;
static usb_dev_handle *udev;
static USBDevice_t curDevice;
static USBDeviceMatcher_t *regex_matcher;
static size_t in_report_len;
static size_t in_report_pos;

static void trace_add(trace_event event)
{
	if (trace_count < sizeof(trace_events) / sizeof(trace_events[0])) {
		trace_events[trace_count++] = event;
	}
}

static transfer_ledger *ledger_for(struct libusb_transfer *transfer)
{
	return ledger.transfer == transfer ? &ledger : NULL;
}

static void lifecycle_test_free(void *pointer)
{
	if (pointer == NULL) {
		return;
	}
	if (pointer == (void *)ledger.buffer) {
		ledger.logical_buffer_frees++;
		trace_add(TRACE_BUFFER_FREE);
		if (ledger.logical_buffer_frees != 1) {
			duplicate_buffer_free = 1;
		}
		if (ledger.pending) {
			pending_buffer_freed = 1;
		}
		return;
	}
	unknown_free_seen = 1;
	free(pointer);
}

static void *xmalloc(size_t size)
{
	void *buffer = malloc(size);
	if (buffer != NULL) {
		ledger.buffer = (unsigned char *)buffer;
	}
	return buffer;
}

static void upsdebugx(int level, const char *format, ...)
{
	(void)level;
	(void)format;
}

static void USBFreeRegexMatcher(USBDeviceMatcher_t *matcher)
{
	(void)matcher;
}

static void *nut_libusb_get_context(void)
{
	return NULL;
}

static int fake_clock_gettime(clockid_t clock_id, struct timespec *value)
{
	(void)clock_id;
	if (fake_clock_failure) {
		return -1;
	}
	*value = fake_now;
	return 0;
}

#define clock_gettime fake_clock_gettime

static struct libusb_transfer *libusb_alloc_transfer(int iso_packets)
{
	struct libusb_transfer *transfer;
	(void)iso_packets;
	transfer = (struct libusb_transfer *)calloc(1, sizeof(*transfer));
	if (transfer != NULL) {
		ledger.transfer = transfer;
		trace_add(TRACE_ALLOC);
	}
	return transfer;
}

static void libusb_fill_interrupt_transfer(struct libusb_transfer *transfer,
	usb_dev_handle *handle, unsigned char endpoint, unsigned char *buffer,
	int length, libusb_transfer_cb_fn callback, void *user_data,
	unsigned int timeout)
{
	(void)endpoint;
	transfer->dev_handle = handle;
	transfer->buffer = buffer;
	transfer->length = length;
	transfer->callback = callback;
	transfer->user_data = user_data;
	transfer->timeout = timeout;
	ledger.buffer = buffer;
}

static int libusb_submit_transfer(struct libusb_transfer *transfer)
{
	transfer_ledger *entry = ledger_for(transfer);
	if (entry == NULL || entry->pending || entry->logical_transfer_frees != 0) {
		return -1;
	}
	if (entry->callback_delivered && transfer->user_data != NULL) {
		resubmit_after_abandon_count++;
	}
	entry->pending = 1;
	entry->submitted_user_data = transfer->user_data;
	submitted_timeout = transfer->timeout;
	submit_count++;
	trace_add(TRACE_SUBMIT);
	return 0;
}

static int libusb_cancel_transfer(struct libusb_transfer *transfer)
{
	transfer_ledger *entry = ledger_for(transfer);
	if (entry == NULL || !entry->pending) {
		return LIBUSB_ERROR_NOT_FOUND;
	}
	cancel_count++;
	cancel_requested = 1;
	trace_add(TRACE_CANCEL);
	return cancel_result;
}

static void libusb_free_transfer(struct libusb_transfer *transfer)
{
	transfer_ledger *entry = ledger_for(transfer);
	if (entry == NULL) {
		unknown_free_seen = 1;
		return;
	}
	entry->logical_transfer_frees++;
	trace_add(TRACE_TRANSFER_FREE);
	if (entry->logical_transfer_frees != 1) {
		duplicate_transfer_free = 1;
	}
	if (entry->pending) {
		pending_transfer_freed = 1;
	}
}

static void audit_pending_user_data(void)
{
	if (ledger.pending && ledger.transfer != NULL
	&& ledger.transfer->user_data != ledger.submitted_user_data) {
		user_data_changed_while_pending = 1;
	}
}

static void dispatch_cancelled_callback(void)
{
	if (ledger.transfer == NULL || !ledger.pending || ledger.callback_delivered) {
		return;
	}
	ledger.pending = 0;
	ledger.callback_delivered = 1;
	ledger.transfer->status = LIBUSB_TRANSFER_CANCELLED;
	ledger.transfer->actual_length = 0;
	callback_count++;
	trace_add(TRACE_EVENT_CALLBACK);
	ledger.transfer->callback(ledger.transfer);
}

static int libusb_handle_events_timeout_completed(void *context,
	struct timeval *timeout, int *completed)
{
	(void)context;
	(void)timeout;
	(void)completed;
	event_call_count++;
	audit_pending_user_data();
	if (cancel_requested && ((active_scenario_cancel_completed && !device_closed)
	|| (force_late_dispatch && device_closed))) {
		dispatch_cancelled_callback();
	}
	return 0;
}

static int fake_pthread_create(pthread_t *thread, const pthread_attr_t *attributes,
	void *(*start_routine)(void *), void *argument)
{
	(void)attributes;
	(void)thread;
	captured_pump = start_routine;
	captured_pump_argument = argument;
	trace_add(TRACE_THREAD_CREATE);
	return thread_create_fails ? EAGAIN : 0;
}

static int fake_pthread_join(pthread_t thread, void **return_value)
{
	(void)thread;
	(void)return_value;
	trace_add(TRACE_JOIN);
	if (captured_pump == NULL) {
		return EINVAL;
	}
	pump_call_count++;
	trace_add(TRACE_PUMP);
	(void)captured_pump(captured_pump_argument);
	return 0;
}

static void microlink_usb_try_decode_fallback(const unsigned char *data, size_t length)
{
	(void)data;
	(void)length;
}

#define pthread_create fake_pthread_create
#define pthread_join fake_pthread_join
#define free lifecycle_test_free
#include "usb_lifecycle_observation_generated.c"
#undef free
#undef pthread_join
#undef pthread_create
#undef clock_gettime

static void fake_close_dev(usb_dev_handle *handle)
{
	(void)handle;
	close_count++;
	device_closed = 1;
	trace_add(TRACE_CLOSE_DEVICE);
	audit_pending_user_data();
	if (ledger.pending && async_xfer == NULL && !microlink_usb_async_xfer_active_get()) {
		pending_at_close_owner_cleared = 1;
	}
}

static void release_mock_allocations(void)
{
	free(ledger.buffer);
	free(ledger.transfer);
	ledger.buffer = NULL;
	ledger.transfer = NULL;
}

static int trace_index(trace_event event)
{
	size_t index;
	for (index = 0; index < trace_count; index++) {
		if (trace_events[index] == event) {
			return (int)index;
		}
	}
	return -1;
}

static int setup_case(const char *profile, const char *scenario)
{
	udev = &fake_device;
	regex_matcher = &fake_matcher;
	usb_subdriver.hid_ep_in = 1;
	usb_subdriver.close_dev = fake_close_dev;
	comm_driver = &usb_subdriver;
	fake_now.tv_sec = 100;
	fake_now.tv_nsec = 0;
	if (strcmp(profile, "guarded") == 0 && !microlink_usb_guard_begin(300)) {
		return 0;
	}
	if (strcmp(profile, "ordinary") != 0 && strcmp(profile, "guarded") != 0) {
		return 0;
	}
	thread_create_fails = strcmp(scenario, "create-failure") == 0;
	cancel_result = strcmp(scenario, "cancel-not-found") == 0 ? LIBUSB_ERROR_NOT_FOUND : 0;
	active_scenario_cancel_completed = strcmp(scenario, "cancel-completed") == 0;
	return strcmp(scenario, "create-failure") == 0
		|| strcmp(scenario, "cancel-pending") == 0
		|| strcmp(scenario, "cancel-not-found") == 0
		|| active_scenario_cancel_completed;
}

static int record_expected_violation(void)
{
	int alloc_at = trace_index(TRACE_ALLOC);
	int submit_at = trace_index(TRACE_SUBMIT);
	int create_at = trace_index(TRACE_THREAD_CREATE);
	int join_at = trace_index(TRACE_JOIN);
	int pump_at = trace_index(TRACE_PUMP);
	int cancel_at = trace_index(TRACE_CANCEL);
	int close_at = trace_index(TRACE_CLOSE_DEVICE);
	int callback_at = trace_index(TRACE_EVENT_CALLBACK);
	int buffer_free_at = trace_index(TRACE_BUFFER_FREE);
	int transfer_free_at = trace_index(TRACE_TRANSFER_FREE);
	if (!pending_at_close_owner_cleared || !user_data_changed_while_pending
	|| cancel_count != 1 || event_call_count != (thread_create_fails ? 1U : 51U)
	|| pump_call_count != (thread_create_fails ? 0U : 1U)
	|| alloc_at < 0 || submit_at <= alloc_at || create_at <= submit_at
	|| cancel_at <= create_at || close_at <= cancel_at
	|| (!thread_create_fails && (join_at <= create_at || pump_at <= join_at
		|| cancel_at <= pump_at))
	|| (thread_create_fails && join_at >= 0)
	|| ledger.pending || !ledger.callback_delivered
	|| close_at < 0 || callback_at <= close_at || buffer_free_at <= callback_at
	|| transfer_free_at <= buffer_free_at || ledger.logical_buffer_frees != 1
	|| ledger.logical_transfer_frees != 1 || pending_buffer_freed
	|| pending_transfer_freed || duplicate_buffer_free || duplicate_transfer_free
	|| unknown_free_seen || resubmit_after_abandon_count != 0 || submit_count != 1
	|| close_count != 1 || callback_count != 1) {
		return 0;
	}
	puts("RED pending transfer observed at close with owner cleared");
	return 1;
}

static int record_control(void)
{
	int alloc_at = trace_index(TRACE_ALLOC);
	int submit_at = trace_index(TRACE_SUBMIT);
	int create_at = trace_index(TRACE_THREAD_CREATE);
	int join_at = trace_index(TRACE_JOIN);
	int pump_at = trace_index(TRACE_PUMP);
	int cancel_at = trace_index(TRACE_CANCEL);
	int callback_at = trace_index(TRACE_EVENT_CALLBACK);
	int buffer_free_at = trace_index(TRACE_BUFFER_FREE);
	int transfer_free_at = trace_index(TRACE_TRANSFER_FREE);
	int close_at = trace_index(TRACE_CLOSE_DEVICE);
	if (pending_at_close_owner_cleared || user_data_changed_while_pending
	|| ledger.pending || !ledger.callback_delivered || cancel_at < 0
	|| alloc_at < 0 || submit_at <= alloc_at || create_at <= submit_at
	|| join_at <= create_at || pump_at <= join_at || cancel_at <= pump_at
	|| callback_at <= cancel_at || buffer_free_at <= callback_at
	|| transfer_free_at <= buffer_free_at || close_at <= transfer_free_at
	|| ledger.logical_buffer_frees != 1 || ledger.logical_transfer_frees != 1
	|| pending_buffer_freed || pending_transfer_freed || duplicate_buffer_free
	|| duplicate_transfer_free || unknown_free_seen || resubmit_after_abandon_count != 0
	|| submit_count != 1 || cancel_count != 1 || event_call_count != 1
	|| close_count != 1 || callback_count != 1 || pump_call_count != 1) {
		return 0;
	}
	puts("CONTROL cancellation callback reaped before close");
	return 1;
}

int main(int argc, char **argv)
{
	char argument[64];
	char *separator;
	char *profile;
	char *scenario;
	int started;
	int expected_red;
	/* Keep source-exact static helpers referenced under -Wunused-function. */
	(void)microlink_usb_device_gone_get;
	(void)microlink_usb_guard_invalidate;
	if (argc != 2 || strlen(argv[1]) >= sizeof(argument)) {
		return 2;
	}
	memcpy(argument, argv[1], strlen(argv[1]) + 1);
	separator = strchr(argument, '-');
	if (separator == NULL) {
		return 2;
	}
	*separator++ = '\0';
	profile = argument;
	scenario = separator;
	if (!setup_case(profile, scenario)) {
		return 2;
	}
	expected_red = strcmp(scenario, "cancel-completed") != 0;
	started = microlink_usb_async_start();
	if (started != !thread_create_fails) {
		return 2;
	}
	if (submitted_timeout != (strcmp(profile, "guarded") == 0 ? 300000U : 0U)) {
		return 2;
	}
	if (expected_red) {
		microlink_usb_close();
		if (!device_closed || close_count != 1 || !ledger.pending) {
			return 2;
		}
		force_late_dispatch = 1;
		(void)libusb_handle_events_timeout_completed(nut_libusb_get_context(), NULL, NULL);
		if (!record_expected_violation()) {
			return 2;
		}
		release_mock_allocations();
		return 1;
	}
	microlink_usb_close();
	if (!record_control()) {
		return 2;
	}
	release_mock_allocations();
	return 0;
}
