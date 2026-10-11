/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Source-exact owner retention replay with local libusb/NUT API doubles.
 * No USB device, NUT binary, libusb library, or IOKit framework is used.
 *
 * Pump/event scheduling uses real pthreads with explicit mock-libUSB barriers.
 * This is synthetic integration evidence only; it does not qualify platform
 * scheduling, a blocked kernel URB, real libusb cancellation, or process exit.
 */

#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <pthread.h>
#include <regex.h>
#include <signal.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define LIBUSB_CALL

typedef struct libusb_context { int marker; } libusb_context;
typedef struct usb_dev_handle { int marker; } usb_dev_handle;

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

typedef struct USBDeviceMatcher USBDeviceMatcher_t;
typedef int (*usb_device_match_fn)(USBDevice_t *, void *);
struct USBDeviceMatcher {
	usb_device_match_fn match_func;
	USBDeviceMatcher_t *next;
	void *privdata;
};

typedef int (*usb_report_callback_fn)(usb_dev_handle *, USBDevice_t *, char *, int);

typedef struct libusb_transfer libusb_transfer;
typedef void (LIBUSB_CALL *libusb_transfer_cb_fn)(libusb_transfer *);
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

typedef struct usb_communication_subdriver {
	int hid_ep_in;
	int (*open_dev)(usb_dev_handle **, USBDevice_t *, USBDeviceMatcher_t *,
		usb_report_callback_fn);
	void (*close_dev)(usb_dev_handle *);
	int (*get_interrupt)(usb_dev_handle *, char *, int, unsigned int);
} usb_communication_subdriver_t;

typedef char *usb_ctrl_charbuf;
typedef int usb_ctrl_charbufsize;
typedef unsigned int usb_ctrl_timeout_msec;

enum {
	LIBUSB_TRANSFER_COMPLETED = 0,
	LIBUSB_TRANSFER_ERROR = 1,
	LIBUSB_TRANSFER_TIMED_OUT = 2,
	LIBUSB_TRANSFER_STALL = 3,
	LIBUSB_TRANSFER_NO_DEVICE = 4,
	LIBUSB_TRANSFER_OVERFLOW = 5,
	LIBUSB_TRANSFER_CANCELLED = 6,
	LIBUSB_ERROR_NO_DEVICE = -4,
	LIBUSB_ERROR_NOT_FOUND = -5,
	LIBUSB_ERROR_BUSY = -6
};

#define USB_ENDPOINT_IN 0x80
#define NUT_UNUSED_VARIABLE(v) ((void)(v))

typedef enum {
	CASE_BLOCKED_INITIAL_SUBMIT,
	CASE_LATE_PUMP_START,
	CASE_CANCEL_SUCCESS,
	CASE_CANCEL_NOT_FOUND,
	CASE_BLOCKED_RESUBMIT,
	CASE_HEALTHY_REPORT,
	CASE_CREATE_FAILURE,
	CASE_ALLOC_FAILURE,
	CASE_SUBMIT_FAILURE,
	CASE_PENDING_REOPEN,
	CASE_GUARDED_REOPEN
} scenario_t;

#define MAX_GENERATIONS 8
typedef struct {
	void *owner;
	unsigned char *buffer;
	libusb_transfer *transfer;
	int owner_frees;
	int buffer_frees;
	int transfer_frees;
} generation_record_t;

typedef struct {
	pthread_mutex_t lock;
	pthread_cond_t cond;
	libusb_transfer *transfer;
	void *owner;
	unsigned char *buffer;
	int pending;
	int callback_delivered;
	int user_data_changed;
	int freed_while_pending;
	int duplicate_free;
	int fail_create;
	int fail_alloc;
	int fail_submit;
	int block_submit;
	int block_resubmit;
	int hold_pump_start;
	int release_pump_start;
	int pump_started;
	int submit_entered;
	int submit_returned;
	int release_submit;
	int resubmit_entered;
	int release_resubmit;
	int cancel_entered;
	int callback_permit;
	int callback_status;
	int event_waiting;
	int event_inflight;
	int hold_terminal_event;
	int release_event_return;
	int callback_returned;
	int cancel_result;
	int submit_count;
	int cancel_count;
	int callback_count;
	int event_count;
	int free_buffer_count;
	int free_owner_count;
	int free_transfer_count;
	int close_count;
	int decode_count;
	int log_count;
	int get_interrupt_count;
	int alarm_count;
	int sigaction_count;
	int libusb_exit_count;
	int alarm_handler_calls;
	int resubmit_after_stop;
	int initial_submit_failure;
	int open_dev_count;
	int open_dev_result;
	int matcher_new_count;
	int matcher_free_count;
	int reset_count;
	int sleep_count;
	int dstate_count;
	int testvar_guarded;
	int auto_callback_on_cancel;
	int active_gate_barrier;
	int active_gate_waiting;
	int release_active_gate;
	int active_gate_sample;
	unsigned int active_get_calls;
	unsigned int generation_count;
	generation_record_t generations[MAX_GENERATIONS];
} mock_ledger_t;

static mock_ledger_t ledger = {
	.lock = PTHREAD_MUTEX_INITIALIZER,
	.cond = PTHREAD_COND_INITIALIZER
};
typedef struct {
	void *(*routine)(void *);
	void *argument;
} pump_launch_t;
static pump_launch_t pump_launch;
static libusb_context fake_context;
static usb_dev_handle fake_device;
static char *device_path = (char *)"auto";
static int fake_sigaction(int, const struct sigaction *, struct sigaction *);
static unsigned int fake_alarm(unsigned int);
static void fake_libusb_exit(libusb_context *);
static void nut_libusb_cleanup_alarm(int);
static void microlink_usb_try_decode_fallback(const unsigned char *, size_t);
static void microlink_usb_handle_busy(const char *);
static void microlink_usb_device_gone_set(int);
static libusb_context *nut_libusb_get_context(void);
static void USBFreeRegexMatcher(USBDeviceMatcher_t *);
static int USBNewRegexMatcher(USBDeviceMatcher_t **, char **, int);
static int fake_open_dev(usb_dev_handle **, USBDevice_t *, USBDeviceMatcher_t *,
	usb_report_callback_fn);
static int microlink_usb_report_callback(usb_dev_handle *, USBDevice_t *, char *, int);
static int testvar(const char *);
static char *getval(const char *);
static void warn_if_bad_usb_port_filename(const char *);
static void dstate_setinfo(const char *, const char *, ...);
void upsdebugx(int, const char *, ...);
void upslogx(int, const char *, ...);
static void fatalx(int, const char *, ...);
static void fatal_with_errno(int, const char *);
static void fake_sleep(unsigned int);
static void nut_guard_maybe_reset(int, void (*)(void *), void *);
static void usb_reset(usb_dev_handle *);
void nut_libusb_context_hold(void);
void nut_libusb_context_release(void);

static void ledger_free(void *pointer)
{
	unsigned int i;
	int matched = 0;
	if (pointer == NULL) {
		return;
	}
	pthread_mutex_lock(&ledger.lock);
	for (i = ledger.generation_count; i > 0; i--) {
		generation_record_t *generation = &ledger.generations[i - 1];
		if (pointer == generation->owner && generation->owner_frees == 0) {
			generation->owner_frees++;
			ledger.free_owner_count++;
			matched = 1;
			break;
		}
		if (pointer == generation->buffer && generation->buffer_frees == 0) {
			generation->buffer_frees++;
			ledger.free_buffer_count++;
			matched = 1;
			break;
		}
	}
	if (!matched) {
		ledger.duplicate_free = 1;
	}
	if (ledger.pending) {
		ledger.freed_while_pending = 1;
	}
	pthread_mutex_unlock(&ledger.lock);
	free(pointer);
}

static void *ledger_malloc(size_t size)
{
	void *pointer = malloc(size);
	pthread_mutex_lock(&ledger.lock);
	if (size == 64U && pointer != NULL) {
		ledger.buffer = (unsigned char *)pointer;
		if (ledger.generation_count > 0) {
			ledger.generations[ledger.generation_count - 1].buffer = pointer;
		}
	}
	pthread_mutex_unlock(&ledger.lock);
	return pointer;
}

static void *ledger_calloc(size_t count, size_t size)
{
	void *pointer = calloc(count, size);
	pthread_mutex_lock(&ledger.lock);
	if (pointer != NULL && ledger.generation_count < MAX_GENERATIONS) {
		generation_record_t *generation = &ledger.generations[ledger.generation_count++];
		memset(generation, 0, sizeof(*generation));
		generation->owner = pointer;
		ledger.owner = pointer;
	}
	pthread_mutex_unlock(&ledger.lock);
	return pointer;
}

static struct libusb_transfer *libusb_alloc_transfer(int iso_packets)
{
	libusb_transfer *transfer;
	(void)iso_packets;
	pthread_mutex_lock(&ledger.lock);
	if (ledger.fail_alloc) {
		pthread_mutex_unlock(&ledger.lock);
		return NULL;
	}
	pthread_mutex_unlock(&ledger.lock);
	transfer = (libusb_transfer *)calloc(1, sizeof(*transfer));
	if (transfer != NULL) {
		pthread_mutex_lock(&ledger.lock);
		ledger.transfer = transfer;
		if (ledger.generation_count > 0) {
			ledger.generations[ledger.generation_count - 1].transfer = transfer;
		}
		pthread_mutex_unlock(&ledger.lock);
	}
	return transfer;
}

static void libusb_free_transfer(libusb_transfer *transfer)
{
	unsigned int i;
	int matched = 0;
	pthread_mutex_lock(&ledger.lock);
	for (i = ledger.generation_count; i > 0; i--) {
		generation_record_t *generation = &ledger.generations[i - 1];
		if (transfer == generation->transfer && generation->transfer_frees == 0) {
			generation->transfer_frees++;
			matched = 1;
			break;
		}
	}
	if (!matched) {
		ledger.duplicate_free = 1;
	}
	ledger.free_transfer_count++;
	if (ledger.pending) {
		ledger.freed_while_pending = 1;
	}
	pthread_mutex_unlock(&ledger.lock);
	free(transfer);
}

static void libusb_fill_interrupt_transfer(libusb_transfer *transfer,
	usb_dev_handle *device, unsigned char endpoint, unsigned char *buffer,
	int length, libusb_transfer_cb_fn callback, void *user_data,
	unsigned int timeout)
{
	(void)endpoint;
	transfer->dev_handle = device;
	transfer->buffer = buffer;
	transfer->length = length;
	transfer->callback = callback;
	transfer->user_data = user_data;
	transfer->timeout = timeout;
	pthread_mutex_lock(&ledger.lock);
	ledger.buffer = buffer;
	ledger.owner = user_data;
	pthread_mutex_unlock(&ledger.lock);
}

static int libusb_submit_transfer(libusb_transfer *transfer)
{
	int fail;
	pthread_mutex_lock(&ledger.lock);
	ledger.submit_count++;
	if (transfer->user_data != ledger.owner) {
		ledger.user_data_changed = 1;
	}
	if (ledger.initial_submit_failure && ledger.submit_count == 1) {
		pthread_mutex_unlock(&ledger.lock);
		return -1;
	}
	ledger.pending = 1;
	ledger.submit_entered = 1;
	pthread_cond_broadcast(&ledger.cond);
	fail = ledger.fail_submit;
	if (ledger.block_submit && ledger.submit_count == 1) {
		while (!ledger.release_submit) {
			pthread_cond_wait(&ledger.cond, &ledger.lock);
		}
	}
	if (ledger.submit_count == 1) {
		ledger.submit_returned = 1;
		pthread_cond_broadcast(&ledger.cond);
	}
	if (ledger.block_resubmit && ledger.submit_count == 2) {
		ledger.resubmit_entered = 1;
		pthread_cond_broadcast(&ledger.cond);
		while (!ledger.release_resubmit) {
			pthread_cond_wait(&ledger.cond, &ledger.lock);
		}
	}
	pthread_mutex_unlock(&ledger.lock);
	return fail ? -1 : 0;
}

static int libusb_cancel_transfer(libusb_transfer *transfer)
{
	(void)transfer;
	pthread_mutex_lock(&ledger.lock);
	ledger.cancel_count++;
	ledger.cancel_entered = 1;
	if (ledger.auto_callback_on_cancel) {
		ledger.callback_status = LIBUSB_TRANSFER_CANCELLED;
		ledger.callback_permit = 1;
	}
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	return ledger.cancel_result;
}

static int libusb_handle_events_timeout_completed(libusb_context *context,
	struct timeval *timeout, int *completed)
{
	libusb_transfer *transfer;
	int status;
	(void)context;
	(void)timeout;
	(void)completed;
	pthread_mutex_lock(&ledger.lock);
	ledger.event_count++;
	ledger.event_waiting = 1;
	ledger.event_inflight = 1;
	pthread_cond_broadcast(&ledger.cond);
	if (!ledger.callback_permit) {
		struct timespec deadline;
		clock_gettime(CLOCK_REALTIME, &deadline);
		deadline.tv_nsec += 50000000L;
		if (deadline.tv_nsec >= 1000000000L) {
			deadline.tv_sec++;
			deadline.tv_nsec -= 1000000000L;
		}
		(void)pthread_cond_timedwait(&ledger.cond, &ledger.lock, &deadline);
	}
	if (!ledger.callback_permit) {
		ledger.event_waiting = 0;
		ledger.event_inflight = 0;
		pthread_cond_broadcast(&ledger.cond);
		pthread_mutex_unlock(&ledger.lock);
		return 0;
	}
	ledger.callback_permit = 0;
	ledger.event_waiting = 0;
	ledger.pending = 0;
	ledger.callback_delivered = 1;
	ledger.callback_count++;
	transfer = ledger.transfer;
	status = ledger.callback_status;
	transfer->status = status;
	transfer->actual_length = status == LIBUSB_TRANSFER_COMPLETED ? 4 : 0;
	pthread_mutex_unlock(&ledger.lock);
	transfer->callback(transfer);
	pthread_mutex_lock(&ledger.lock);
	ledger.callback_returned = 1;
	pthread_cond_broadcast(&ledger.cond);
	while (ledger.hold_terminal_event
	 && status == LIBUSB_TRANSFER_CANCELLED && !ledger.release_event_return) {
		pthread_cond_wait(&ledger.cond, &ledger.lock);
	}
	ledger.event_waiting = 0;
	ledger.event_inflight = 0;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	return 0;
}

void upsdebugx(int level, const char *format, ...)
{
	(void)level;
	(void)format;
	pthread_mutex_lock(&ledger.lock);
	ledger.log_count++;
	pthread_mutex_unlock(&ledger.lock);
}

void upslogx(int level, const char *format, ...)
{
	(void)level;
	(void)format;
	pthread_mutex_lock(&ledger.lock);
	ledger.log_count++;
	pthread_mutex_unlock(&ledger.lock);
}

static int fake_sigaction(int sig, const struct sigaction *act,
	struct sigaction *oldact)
{
	(void)sig;
	(void)act;
	(void)oldact;
	pthread_mutex_lock(&ledger.lock);
	ledger.sigaction_count++;
	pthread_mutex_unlock(&ledger.lock);
	return 0;
}

static unsigned int fake_alarm(unsigned int seconds)
{
	(void)seconds;
	pthread_mutex_lock(&ledger.lock);
	ledger.alarm_count++;
	pthread_mutex_unlock(&ledger.lock);
	return 0;
}

static void fake_libusb_exit(libusb_context *context)
{
	(void)context;
	pthread_mutex_lock(&ledger.lock);
	ledger.libusb_exit_count++;
	pthread_mutex_unlock(&ledger.lock);
}

static void nut_libusb_cleanup_alarm(int signal_number)
{
	(void)signal_number;
	pthread_mutex_lock(&ledger.lock);
	ledger.alarm_handler_calls++;
	pthread_mutex_unlock(&ledger.lock);
}

static void microlink_usb_try_decode_fallback(const unsigned char *data,
	size_t length)
{
	(void)data;
	(void)length;
	pthread_mutex_lock(&ledger.lock);
	ledger.decode_count++;
	pthread_mutex_unlock(&ledger.lock);
}

static int fake_get_interrupt(usb_dev_handle *device, char *buffer, int size,
	unsigned int timeout)
{
	(void)device;
	(void)buffer;
	(void)size;
	(void)timeout;
	pthread_mutex_lock(&ledger.lock);
	ledger.get_interrupt_count++;
	pthread_mutex_unlock(&ledger.lock);
	return 0;
}

static void microlink_usb_handle_busy(const char *where)
{
	(void)where;
}

static libusb_context *nut_libusb_get_context(void)
{
	return &fake_context;
}

static void USBFreeRegexMatcher(USBDeviceMatcher_t *matcher)
{
	if (!matcher) {
		return;
	}
	ledger.matcher_free_count++;
	free(matcher);
}

static void *pump_start_barrier(void *opaque)
{
	pump_launch_t *launch = (pump_launch_t *)opaque;
	pthread_mutex_lock(&ledger.lock);
	while (ledger.hold_pump_start && !ledger.release_pump_start) {
		pthread_cond_wait(&ledger.cond, &ledger.lock);
	}
	ledger.pump_started = 1;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	return launch->routine(launch->argument);
}

static int actual_pthread_create(pthread_t *thread, const pthread_attr_t *attr,
	void *(*routine)(void *), void *argument)
{
	return pthread_create(thread, attr, routine, argument);
}

static int mock_pthread_create(pthread_t *thread, const pthread_attr_t *attr,
	void *(*routine)(void *), void *argument)
{
	pthread_mutex_lock(&ledger.lock);
	if (ledger.fail_create) {
		pthread_mutex_unlock(&ledger.lock);
		return EAGAIN;
	}
	pump_launch.routine = routine;
	pump_launch.argument = argument;
	pthread_mutex_unlock(&ledger.lock);
	return actual_pthread_create(thread, attr, pump_start_barrier, &pump_launch);
}

#define free ledger_free
#define malloc ledger_malloc
#define calloc ledger_calloc
#define pthread_create mock_pthread_create
#define alarm(seconds) fake_alarm((seconds))
#define sigaction(sig, act, oldact) fake_sigaction((sig), (act), (oldact))
#define sleep(seconds) fake_sleep((seconds))
#define libusb_exit fake_libusb_exit
#include "usb_owner_retention_generated.c"

static int microlink_usb_async_pending(void)
{
	return integration_pending_source();
}

/* The wrapper is fixture-only: it pauses after the real first active read. */
static int microlink_usb_async_xfer_active_get(void)
{
	int active = integration_active_source();
	pthread_mutex_lock(&ledger.lock);
	ledger.active_get_calls++;
	if (ledger.active_gate_barrier && !ledger.active_gate_waiting) {
		ledger.active_gate_sample = active;
		ledger.active_gate_waiting = 1;
		pthread_cond_broadcast(&ledger.cond);
		while (!ledger.release_active_gate) {
			pthread_cond_wait(&ledger.cond, &ledger.lock);
		}
	}
	pthread_mutex_unlock(&ledger.lock);
	return active;
}
#undef libusb_exit
#undef sigaction
#undef alarm
#undef sleep
#undef free
#undef malloc
#undef calloc
#undef pthread_create

static void microlink_usb_device_gone_set(int gone)
{
	usb_device_gone = gone;
}

static int USBNewRegexMatcher(USBDeviceMatcher_t **matcher, char **patterns, int flags)
{
	(void)patterns;
	(void)flags;
	*matcher = (USBDeviceMatcher_t *)malloc(sizeof(**matcher));
	if (!*matcher) {
		return -1;
	}
	memset(*matcher, 0, sizeof(**matcher));
	pthread_mutex_lock(&ledger.lock);
	ledger.matcher_new_count++;
	pthread_mutex_unlock(&ledger.lock);
	return 0;
}

static int fake_open_dev(usb_dev_handle **device, USBDevice_t *description,
	USBDeviceMatcher_t *matcher, usb_report_callback_fn callback)
{
	(void)matcher;
	(void)callback;
	pthread_mutex_lock(&ledger.lock);
	ledger.open_dev_count++;
	pthread_mutex_unlock(&ledger.lock);
	if (ledger.open_dev_result < 1) {
		return ledger.open_dev_result;
	}
	*device = &fake_device;
	description->VendorID = 0x051d;
	description->ProductID = 0x0003;
	return ledger.open_dev_result;
}

static int microlink_usb_report_callback(usb_dev_handle *device,
	USBDevice_t *description, char *buffer, int length)
{
	(void)device;
	(void)description;
	(void)buffer;
	(void)length;
	return 1;
}

static int testvar(const char *name)
{
	return strcmp(name, "guarded_monitor") == 0 && ledger.testvar_guarded;
}

static char *getval(const char *name)
{
	(void)name;
	return NULL;
}

static void warn_if_bad_usb_port_filename(const char *path)
{
	(void)path;
}

static void dstate_setinfo(const char *name, const char *format, ...)
{
	(void)name;
	(void)format;
	ledger.dstate_count++;
}

static void fatalx(int status, const char *format, ...)
{
	(void)status;
	(void)format;
	abort();
}

static void fatal_with_errno(int status, const char *format)
{
	(void)status;
	(void)format;
	abort();
}

static void fake_sleep(unsigned int seconds)
{
	(void)seconds;
	ledger.sleep_count++;
}

static void usb_reset(usb_dev_handle *device)
{
	(void)device;
	ledger.reset_count++;
}

static void nut_guard_maybe_reset(int guarded, void (*reset)(void *), void *context)
{
	if (!guarded && reset) {
		reset(context);
	}
}

static void fake_close_dev(usb_dev_handle *device)
{
	(void)device;
	ledger.close_count++;
}

static void reference_source_only_symbols(void)
{
	(void)microlink_usb_async_pending;
	(void)microlink_usb_guard_begin;
	(void)microlink_usb_guard_expired;
}

static void setup(scenario_t scenario)
{
	pthread_mutex_lock(&ledger.lock);
	memset((char *)&ledger + offsetof(mock_ledger_t, transfer), 0,
		sizeof(ledger) - offsetof(mock_ledger_t, transfer));
	ledger.cancel_result = scenario == CASE_CANCEL_NOT_FOUND
		? LIBUSB_ERROR_NOT_FOUND : 0;
	ledger.block_submit = scenario == CASE_BLOCKED_INITIAL_SUBMIT;
	ledger.block_resubmit = scenario == CASE_BLOCKED_RESUBMIT;
	ledger.hold_pump_start = scenario == CASE_LATE_PUMP_START;
	ledger.hold_terminal_event = 1;
	ledger.auto_callback_on_cancel = scenario == CASE_GUARDED_REOPEN;
	if (scenario == CASE_GUARDED_REOPEN) {
		ledger.hold_terminal_event = 0;
		ledger.testvar_guarded = 1;
	}
	ledger.fail_create = scenario == CASE_CREATE_FAILURE;
	ledger.fail_alloc = scenario == CASE_ALLOC_FAILURE;
	ledger.initial_submit_failure = scenario == CASE_SUBMIT_FAILURE;
	ledger.open_dev_result = 1;
	pthread_mutex_unlock(&ledger.lock);
	udev = &fake_device;
	regex_matcher = NULL;
	guarded_monitor = 0;
	in_report_len = 0;
	in_report_pos = 0;
	mlink_report_in = 1;
	usb_subdriver.hid_ep_in = 1;
	usb_subdriver.open_dev = fake_open_dev;
	usb_subdriver.close_dev = fake_close_dev;
	usb_subdriver.get_interrupt = fake_get_interrupt;
	comm_driver = &usb_subdriver;
	nut_usb_ctx = &fake_context;
	nut_usb_ctx_initialized = true;
	nut_usb_ctx_held = 0;
}

static int wait_for_flag(int *flag)
{
	struct timespec deadline;
	clock_gettime(CLOCK_REALTIME, &deadline);
	deadline.tv_sec += 5;
	pthread_mutex_lock(&ledger.lock);
	while (!*flag) {
		if (pthread_cond_timedwait(&ledger.cond, &ledger.lock, &deadline) != 0) {
			pthread_mutex_unlock(&ledger.lock);
			return 0;
		}
	}
	pthread_mutex_unlock(&ledger.lock);
	return 1;
}

static int wait_for_submit_count(int count)
{
	struct timespec deadline;
	clock_gettime(CLOCK_REALTIME, &deadline);
	deadline.tv_sec += 5;
	pthread_mutex_lock(&ledger.lock);
	while (ledger.submit_count < count) {
		if (pthread_cond_timedwait(&ledger.cond, &ledger.lock, &deadline) != 0) {
			pthread_mutex_unlock(&ledger.lock);
			return 0;
		}
	}
	pthread_mutex_unlock(&ledger.lock);
	return 1;
}

static int generations_freed_exactly(unsigned int expected)
{
	unsigned int i;
	int ok = 1;
	pthread_mutex_lock(&ledger.lock);
	if (ledger.generation_count != expected) {
		ok = 0;
	}
	for (i = 0; i < ledger.generation_count && i < MAX_GENERATIONS; i++) {
		generation_record_t *generation = &ledger.generations[i];
		if (!generation->owner || !generation->buffer || !generation->transfer
		 || generation->owner_frees != 1 || generation->buffer_frees != 1
		 || generation->transfer_frees != 1) {
			ok = 0;
		}
	}
	if (ledger.duplicate_free) {
		ok = 0;
	}
	pthread_mutex_unlock(&ledger.lock);
	return ok;
}

static int wait_for_pump_ack(void)
{
	struct timespec pause = {0, 1000000L};
	unsigned int i;
	for (i = 0; i < 5000U; i++) {
		int done;
		pthread_mutex_lock(&async_lock);
		done = async_owner == NULL
			|| (async_owner->callback_terminal && async_owner->pump_exited);
		pthread_mutex_unlock(&async_lock);
		if (done) {
			return 1;
		}
		nanosleep(&pause, NULL);
	}
	return 0;
}

static void permit_callback(int status)
{
	pthread_mutex_lock(&ledger.lock);
	if (status == LIBUSB_TRANSFER_CANCELLED) {
		ledger.callback_returned = 0;
	}
	ledger.callback_status = status;
	ledger.callback_permit = 1;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
}

static int pending_invariants(const char *case_name, int expected_closes)
{
	int ok = 1;
	int owner_exists;
	pthread_mutex_lock(&async_lock);
	owner_exists = async_owner != NULL;
	pthread_mutex_unlock(&async_lock);
	pthread_mutex_lock(&ledger.lock);
	if (!owner_exists || !nut_usb_ctx_held || !ledger.pending
	 || ledger.freed_while_pending || ledger.duplicate_free
	 || ledger.user_data_changed || ledger.close_count != expected_closes
	 || ledger.libusb_exit_count != 0 || ledger.alarm_count != 0
	 || ledger.get_interrupt_count != 0) {
		fprintf(stderr, "%s: pending ownership invariant failed\n", case_name);
		ok = 0;
	}
	if (ledger.transfer == NULL || ledger.transfer->user_data != ledger.owner) {
		fprintf(stderr, "%s: callback user_data identity changed\n", case_name);
		ok = 0;
	}
	pthread_mutex_unlock(&ledger.lock);
	return ok;
}

static int retained_without_submission(const char *case_name)
{
	int exists;
	int ok = 1;
	pthread_mutex_lock(&async_lock);
	exists = async_owner != NULL;
	pthread_mutex_unlock(&async_lock);
	pthread_mutex_lock(&ledger.lock);
	if (!exists || !nut_usb_ctx_held || ledger.pending || ledger.submit_count != 0
	 || ledger.close_count != 0 || ledger.free_buffer_count != 0
	 || ledger.free_transfer_count != 0 || ledger.free_owner_count != 0
	 || ledger.libusb_exit_count != 0 || ledger.get_interrupt_count != 0) {
		fprintf(stderr, "%s: undispatched owner was not retained exclusively\n", case_name);
		ok = 0;
	}
	pthread_mutex_unlock(&ledger.lock);
	return ok;
}

static int finish_pending(const char *name, int expected_submits,
	int expected_callbacks)
{
	int ok = 1;
	if (!wait_for_flag(&ledger.cancel_entered)) {
		fprintf(stderr, "%s: cancel API was not reached\n", name);
		return 0;
	}
	if (!pending_invariants(name, 0)) {
		ok = 0;
	}
	if (microlink_usb_get_char((unsigned char[1]){0}, 1000L) != -1
	 || microlink_usb_get_char_sync((unsigned char[1]){0}, 1000L) != -1
	 || ledger.get_interrupt_count != 0) {
		fprintf(stderr, "%s: pending listener entered synchronous read fallback\n", name);
		ok = 0;
	}
	nut_libusb_cleanup_atexit();
	if (ledger.alarm_count != 0 || ledger.libusb_exit_count != 0) {
		fprintf(stderr, "%s: atexit touched a held backend context\n", name);
		ok = 0;
	}
	permit_callback(LIBUSB_TRANSFER_CANCELLED);
	if (!wait_for_flag(&ledger.callback_returned)) {
		fprintf(stderr, "%s: terminal callback did not return\n", name);
		return 0;
	}
	pthread_mutex_lock(&async_lock);
	if (!async_owner || !async_owner->callback_terminal || async_owner->pump_exited) {
		fprintf(stderr, "%s: callback/pump acknowledgements were conflated\n", name);
		ok = 0;
	}
	pthread_mutex_unlock(&async_lock);
	microlink_usb_close();
	pthread_mutex_lock(&async_lock);
	if (!async_owner || !async_owner->callback_terminal || async_owner->pump_exited) {
		fprintf(stderr, "%s: close reaped before event dispatch returned\n", name);
		ok = 0;
	}
	pthread_mutex_unlock(&async_lock);
	pthread_mutex_lock(&ledger.lock);
	if (!ledger.event_inflight || ledger.freed_while_pending
	 || ledger.free_buffer_count != 0 || ledger.free_transfer_count != 0
	 || ledger.free_owner_count != 0 || !nut_usb_ctx_held) {
		fprintf(stderr, "%s: resources released before event pump returned\n", name);
		ok = 0;
	}
	ledger.release_event_return = 1;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	if (!wait_for_pump_ack()) {
		fprintf(stderr, "%s: pump exit acknowledgement timed out\n", name);
		return 0;
	}
	microlink_usb_close();
	if (async_owner != NULL || nut_usb_ctx_held || ledger.close_count != 1
	 || ledger.free_buffer_count != 1 || ledger.free_transfer_count != 1
	 || ledger.free_owner_count != 1 || ledger.freed_while_pending
	 || ledger.duplicate_free || ledger.submit_count != expected_submits
	 || ledger.callback_count != expected_callbacks || ledger.log_count != 0) {
		fprintf(stderr, "%s: quiescent cleanup contract failed\n", name);
		ok = 0;
	}
	nut_libusb_cleanup_atexit();
	if (ledger.libusb_exit_count != 1) {
		fprintf(stderr, "%s: backend context did not exit exactly once after release\n", name);
		ok = 0;
	}
	microlink_usb_close();
	if (ledger.close_count != 1 || ledger.free_buffer_count != 1
	 || ledger.free_transfer_count != 1 || ledger.free_owner_count != 1) {
		fprintf(stderr, "%s: repeated close duplicated cleanup\n", name);
		ok = 0;
	}
	return ok;
}

static int run_blocked_initial_submit(void)
{
	int start_result;
	setup(CASE_BLOCKED_INITIAL_SUBMIT);
	start_result = microlink_usb_async_start();
	if (!wait_for_flag(&ledger.submit_entered) || start_result != -1
	 || !pending_invariants("blocked-initial-submit", 0)) {
		fprintf(stderr, "blocked-initial-submit: startup did not return pending\n");
		return 0;
	}
	microlink_usb_close();
	if (microlink_usb_async_stop() != 0
	 || !pending_invariants("blocked-initial-submit-after-repeated-stop", 0)) {
		return 0;
	}
	pthread_mutex_lock(&ledger.lock);
	ledger.release_submit = 1;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	if (!wait_for_flag(&ledger.submit_returned)) {
		fprintf(stderr, "blocked-initial-submit: submit barrier did not release\n");
		return 0;
	}
	return finish_pending("blocked-initial-submit", 1, 1);
}

static int run_late_pump_start(void)
{
	setup(CASE_LATE_PUMP_START);
	if (microlink_usb_async_start() != -1
	 || !retained_without_submission("late-pump-start-before-dispatch")) {
		fprintf(stderr, "late-pump-start: startup did not retain the undispatched owner\n");
		return 0;
	}
	microlink_usb_close();
	if (!retained_without_submission("late-pump-start-after-close")) {
		return 0;
	}
	pthread_mutex_lock(&ledger.lock);
	ledger.release_pump_start = 1;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	if (!wait_for_pump_ack()) {
		fprintf(stderr, "late-pump-start: pump did not acknowledge stop-before-submit\n");
		return 0;
	}
	microlink_usb_close();
	nut_libusb_cleanup_atexit();
	if (ledger.submit_count != 0 || ledger.pending || ledger.close_count != 1
	 || ledger.free_buffer_count != 1 || ledger.free_transfer_count != 1
	 || ledger.free_owner_count != 1 || ledger.libusb_exit_count != 1) {
		fprintf(stderr, "late-pump-start: stop-before-submit teardown failed\n");
		return 0;
	}
	return 1;
}

static int run_healthy_report(void)
{
	int ok = 1;
	setup(CASE_HEALTHY_REPORT);
	if (microlink_usb_async_start() != 1 || !wait_for_flag(&ledger.event_waiting)) {
		fprintf(stderr, "healthy-report: pump did not start\n");
		return 0;
	}
	permit_callback(LIBUSB_TRANSFER_COMPLETED);
	if (!wait_for_submit_count(2)) {
		fprintf(stderr, "healthy-report: completed report was not resubmitted\n");
		return 0;
	}
	pthread_mutex_lock(&ledger.lock);
	ok = ledger.decode_count == 1;
	pthread_mutex_unlock(&ledger.lock);
	if (!ok) {
		fprintf(stderr, "healthy-report: completed report was not delivered\n");
		ok = 0;
	}
	microlink_usb_close();
	if (!wait_for_flag(&ledger.cancel_entered)) {
		fprintf(stderr, "healthy-report: cancel was not issued after stop\n");
		return 0;
	}
	return ok && finish_pending("healthy-report", 2, 2);
}

static int run_start_failure(scenario_t scenario, const char *name)
{
	setup(scenario);
	int result = microlink_usb_async_start();
	int owner_exists;
	pthread_mutex_lock(&async_lock);
	owner_exists = async_owner != NULL;
	pthread_mutex_unlock(&async_lock);
	if (result != 0 || owner_exists || nut_usb_ctx_held || ledger.pending
	 || ledger.submit_count != (scenario == CASE_SUBMIT_FAILURE ? 1 : 0)
	 || ledger.free_buffer_count != (scenario == CASE_ALLOC_FAILURE
		|| scenario == CASE_CREATE_FAILURE || scenario == CASE_SUBMIT_FAILURE)
	 || ledger.free_transfer_count != (scenario == CASE_CREATE_FAILURE
		|| scenario == CASE_SUBMIT_FAILURE)
	 || ledger.free_owner_count != (scenario == CASE_ALLOC_FAILURE
		|| scenario == CASE_CREATE_FAILURE || scenario == CASE_SUBMIT_FAILURE)
	 || ledger.freed_while_pending) {
		fprintf(stderr, "%s: safe pre-submit failure teardown failed\n", name);
		return 0;
	}
	microlink_usb_close();
	return ledger.close_count == 1;
}

static int run_noasync_fallback(void)
{
	unsigned char ch = 0;
	setup(CASE_HEALTHY_REPORT);
	if (microlink_usb_get_char(&ch, 1000L) != 0
	 || ledger.get_interrupt_count != 1 || ledger.close_count != 0) {
		fprintf(stderr, "noasync-fallback: sync read path was not used\n");
		return 0;
	}
	microlink_usb_close();
	return ledger.close_count == 1;
}

static int complete_pending_integration(const char *name, int expected_closes)
{
	if (!wait_for_flag(&ledger.cancel_entered)) {
		fprintf(stderr, "%s: cancellation was not reached\n", name);
		return 0;
	}
	permit_callback(LIBUSB_TRANSFER_CANCELLED);
	if (!wait_for_flag(&ledger.callback_returned)) {
		fprintf(stderr, "%s: terminal callback did not return\n", name);
		return 0;
	}
	if (!async_owner || !async_owner->callback_terminal || async_owner->pump_exited
	 || !nut_usb_ctx_held || ledger.get_interrupt_count != 0) {
		fprintf(stderr, "%s: terminal callback did not retain resources for pump ack\n", name);
		return 0;
	}
	microlink_usb_flush_io();
	if (ledger.get_interrupt_count != 0) {
		fprintf(stderr, "%s: flush used synchronous interrupt read\n", name);
		return 0;
	}
	pthread_mutex_lock(&ledger.lock);
	ledger.release_event_return = 1;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	if (!wait_for_pump_ack()) {
		fprintf(stderr, "%s: pump did not acknowledge exit\n", name);
		return 0;
	}
	microlink_usb_close();
	nut_libusb_cleanup_atexit();
	if (async_owner || nut_usb_ctx_held || ledger.pending
	 || ledger.free_buffer_count != 1 || ledger.free_transfer_count != 1
	 || ledger.free_owner_count != 1 || ledger.freed_while_pending
	 || ledger.duplicate_free || ledger.close_count != expected_closes
	 || ledger.libusb_exit_count != 1) {
		fprintf(stderr, "%s: terminal release did not occur exactly once\n", name);
		return 0;
	}
	return 1;
}

static int run_pending_open_reopen_flush(void)
{
	int open_result, reopen_result;
	setup(CASE_PENDING_REOPEN);
	if (USBNewRegexMatcher(&regex_matcher, NULL, 0) != 0
	 || microlink_usb_async_start() != 1
	 || !wait_for_flag(&ledger.event_waiting)) {
		fprintf(stderr, "pending-open-reopen: listener setup failed\n");
		return 0;
	}
	open_result = microlink_usb_open();
	reopen_result = microlink_usb_reset_and_reopen();
	if (open_result != 0 || reopen_result != 0
	 || ledger.matcher_new_count != 1 || ledger.open_dev_count != 0
	 || ledger.close_count != 0 || ledger.reset_count != 0
	 || ledger.get_interrupt_count != 0 || !nut_usb_ctx_held
	 || !async_owner || !async_owner->stop_requested) {
		fprintf(stderr, "pending-open-reopen: owner did not block reuse before close/reset/open\n");
		return 0;
	}
	if (!wait_for_flag(&ledger.cancel_entered)) {
		fprintf(stderr, "pending-open-reopen: cancellation was not reached\n");
		return 0;
	}
	permit_callback(LIBUSB_TRANSFER_CANCELLED);
	if (!wait_for_flag(&ledger.callback_returned)) {
		fprintf(stderr, "pending-open-reopen: callback did not reach terminal state\n");
		return 0;
	}
	microlink_usb_flush_io();
	if (!async_owner || !async_owner->callback_terminal || async_owner->pump_exited
	 || ledger.get_interrupt_count != 0) {
		fprintf(stderr, "pending-open-reopen: terminal flush touched synchronous endpoint\n");
		return 0;
	}
	pthread_mutex_lock(&ledger.lock);
	ledger.release_event_return = 1;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	if (!wait_for_pump_ack()) {
		fprintf(stderr, "pending-open-reopen: pump did not exit\n");
		return 0;
	}
	microlink_usb_close();
	nut_libusb_cleanup_atexit();
	if (async_owner || nut_usb_ctx_held || ledger.close_count != 1
	 || ledger.matcher_free_count != 1 || ledger.get_interrupt_count != 0
	 || ledger.libusb_exit_count != 1) {
		fprintf(stderr, "pending-open-reopen: final cleanup counts failed\n");
		return 0;
	}
	return 1;
}

static int run_open_start_pending(void)
{
	int result;
	setup(CASE_BLOCKED_INITIAL_SUBMIT);
	result = microlink_usb_open();
	if (result != 0 || !wait_for_flag(&ledger.submit_entered)
	 || !pending_invariants("open-start-pending", 0)
	 || ledger.open_dev_count != 1 || ledger.close_count != 0
	 || ledger.get_interrupt_count != 0) {
		fprintf(stderr, "open-start-pending: open did not fail closed with retained submit\n");
		return 0;
	}
	pthread_mutex_lock(&ledger.lock);
	ledger.release_submit = 1;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	if (!wait_for_flag(&ledger.submit_returned)) {
		fprintf(stderr, "open-start-pending: submit barrier did not release\n");
		return 0;
	}
	return complete_pending_integration("open-start-pending", 1);
}

static int run_reopen_start_pending(void)
{
	int result;
	setup(CASE_BLOCKED_INITIAL_SUBMIT);
	if (USBNewRegexMatcher(&regex_matcher, NULL, 0) != 0) {
		return 0;
	}
	result = microlink_usb_reset_and_reopen();
	if (result != 0 || !wait_for_flag(&ledger.submit_entered)
	 || !pending_invariants("reopen-start-pending", 1)
	 || ledger.reset_count != 1 || ledger.close_count != 1
	 || ledger.sleep_count != 1 || ledger.open_dev_count != 1
	 || ledger.get_interrupt_count != 0) {
		fprintf(stderr, "reopen-start-pending: reopen did not fail closed without sync fallback\n");
		return 0;
	}
	pthread_mutex_lock(&ledger.lock);
	ledger.release_submit = 1;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	if (!wait_for_flag(&ledger.submit_returned)) {
		fprintf(stderr, "reopen-start-pending: submit barrier did not release\n");
		return 0;
	}
	return complete_pending_integration("reopen-start-pending", 2);
}

static int run_open_fallback(void)
{
	unsigned char ch = 0;
	int result;
	setup(CASE_CREATE_FAILURE);
	result = microlink_usb_open();
	if (result != 1 || async_owner || nut_usb_ctx_held
	 || ledger.open_dev_count != 1 || ledger.submit_count != 0
	 || microlink_usb_get_char(&ch, 1000L) != 0
	 || ledger.get_interrupt_count != 1) {
		fprintf(stderr, "open-fallback: ordinary no-owner fallback did not remain available\n");
		return 0;
	}
	microlink_usb_close();
	return ledger.close_count == 1 && ledger.matcher_free_count == 1;
}

static int run_guarded_reopen_no_reset(void)
{
	int result;
	setup(CASE_GUARDED_REOPEN);
	if (!microlink_usb_guard_begin(300) || microlink_usb_open() != 1
	 || !async_owner || !wait_for_flag(&ledger.event_waiting)) {
		fprintf(stderr, "guarded-reopen: initial guarded listener did not start\n");
		return 0;
	}
	result = microlink_usb_reset_and_reopen();
	if (result != 1 || ledger.reset_count != 0 || ledger.close_count != 1
	 || ledger.open_dev_count != 2 || ledger.sleep_count != 0
	 || !async_owner || !nut_usb_ctx_held) {
		fprintf(stderr, "guarded-reopen: quiescent reopen reset or failed to reopen\n");
		return 0;
	}
	microlink_usb_close();
	nut_libusb_cleanup_atexit();
	if (async_owner || nut_usb_ctx_held || ledger.reset_count != 0
	 || ledger.close_count != 2 || ledger.matcher_free_count != 1
	 || ledger.libusb_exit_count != 1 || !generations_freed_exactly(2)) {
		fprintf(stderr, "guarded-reopen: final quiescent cleanup failed\n");
		return 0;
	}
	return 1;
}

static void *flush_thread(void *unused)
{
	(void)unused;
	microlink_usb_flush_io();
	return NULL;
}

static int run_flush_active_to_terminal_race(void)
{
	pthread_t thread;
	setup(CASE_PENDING_REOPEN);
	if (microlink_usb_async_start() != 1 || !wait_for_flag(&ledger.event_waiting)) {
		fprintf(stderr, "flush-active-race: listener setup failed\n");
		return 0;
	}
	pthread_mutex_lock(&ledger.lock);
	ledger.active_gate_barrier = 1;
	pthread_mutex_unlock(&ledger.lock);
	if (pthread_create(&thread, NULL, flush_thread, NULL) != 0
	 || !wait_for_flag(&ledger.active_gate_waiting)
	 || !ledger.active_gate_sample) {
		fprintf(stderr, "flush-active-race: first active read did not reach barrier\n");
		return 0;
	}
	permit_callback(LIBUSB_TRANSFER_NO_DEVICE);
	if (!wait_for_flag(&ledger.callback_returned)) {
		fprintf(stderr, "flush-active-race: terminal callback did not run\n");
		return 0;
	}
	if (integration_active_source() != 0 || !async_owner
	 || !async_owner->callback_terminal || async_owner->stop_requested) {
		fprintf(stderr, "flush-active-race: active state did not transition to zero\n");
		return 0;
	}
	pthread_mutex_lock(&ledger.lock);
	ledger.release_active_gate = 1;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	if (pthread_join(thread, NULL) != 0 || !async_owner
	 || !async_owner->callback_terminal || async_owner->stop_requested) {
		fprintf(stderr, "flush-active-race: terminal owner was not retained at flush return\n");
		return 0;
	}
	if (ledger.get_interrupt_count != 0) {
		fprintf(stderr, "flush-active-race: synchronous get_interrupt after active 1-to-0 transition\n");
		return 0;
	}
	pthread_mutex_lock(&ledger.lock);
	ledger.release_event_return = 1;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	if (!wait_for_pump_ack()) {
		fprintf(stderr, "flush-active-race: pump did not acknowledge terminal callback\n");
		return 0;
	}
	microlink_usb_close();
	nut_libusb_cleanup_atexit();
	if (async_owner || nut_usb_ctx_held || ledger.get_interrupt_count != 0
	 || !generations_freed_exactly(1) || ledger.close_count != 1
	 || ledger.libusb_exit_count != 1) {
		fprintf(stderr, "flush-active-race: final owner cleanup failed\n");
		return 0;
	}
	return 1;
}

int main(int argc, char **argv)
{
	int ok = 0;
	reference_source_only_symbols();
	if (argc != 2) {
		return 2;
	}
	if (strcmp(argv[1], "pending-open-reopen-flush") == 0) {
		ok = run_pending_open_reopen_flush();
	} else if (strcmp(argv[1], "open-start-pending") == 0) {
		ok = run_open_start_pending();
	} else if (strcmp(argv[1], "reopen-start-pending") == 0) {
		ok = run_reopen_start_pending();
	} else if (strcmp(argv[1], "open-fallback") == 0) {
		ok = run_open_fallback();
	} else if (strcmp(argv[1], "guarded-reopen-no-reset") == 0) {
		ok = run_guarded_reopen_no_reset();
	} else if (strcmp(argv[1], "flush-active-race") == 0) {
		ok = run_flush_active_to_terminal_race();
	} else if (strcmp(argv[1], "blocked-initial-submit") == 0) {
		ok = run_blocked_initial_submit();
	} else if (strcmp(argv[1], "late-pump-start") == 0) {
		ok = run_late_pump_start();
	} else if (strcmp(argv[1], "cancel-success") == 0) {
		setup(CASE_CANCEL_SUCCESS);
		ok = microlink_usb_async_start() == 1;
		if (ok) {
			microlink_usb_close();
			ok = finish_pending("cancel-success", 1, 1);
		}
	} else if (strcmp(argv[1], "cancel-not-found") == 0) {
		setup(CASE_CANCEL_NOT_FOUND);
		ok = microlink_usb_async_start() == 1;
		if (ok) {
			microlink_usb_close();
			ok = finish_pending("cancel-not-found", 1, 1);
		}
	} else if (strcmp(argv[1], "blocked-resubmit") == 0) {
		setup(CASE_BLOCKED_RESUBMIT);
		ok = microlink_usb_async_start() == 1
			&& wait_for_flag(&ledger.event_waiting);
		if (ok) {
			permit_callback(LIBUSB_TRANSFER_COMPLETED);
			ok = wait_for_flag(&ledger.resubmit_entered);
		}
		if (ok) {
			microlink_usb_close();
			ok = pending_invariants("blocked-resubmit", 0);
			pthread_mutex_lock(&ledger.lock);
			ledger.release_resubmit = 1;
			pthread_cond_broadcast(&ledger.cond);
			pthread_mutex_unlock(&ledger.lock);
			if (ok) {
				ok = finish_pending("blocked-resubmit", 2, 2);
			}
		}
	} else if (strcmp(argv[1], "healthy-report") == 0) {
		ok = run_healthy_report();
	} else if (strcmp(argv[1], "create-failure") == 0) {
		ok = run_start_failure(CASE_CREATE_FAILURE, argv[1]);
	} else if (strcmp(argv[1], "allocation-failure") == 0) {
		ok = run_start_failure(CASE_ALLOC_FAILURE, argv[1]);
	} else if (strcmp(argv[1], "submit-failure") == 0) {
		ok = run_start_failure(CASE_SUBMIT_FAILURE, argv[1]);
	} else if (strcmp(argv[1], "noasync-fallback") == 0) {
		ok = run_noasync_fallback();
	} else {
		return 2;
	}
	if (!ok) {
		return 1;
	}
	printf("PASS %s\n", argv[1]);
	return 0;
}
