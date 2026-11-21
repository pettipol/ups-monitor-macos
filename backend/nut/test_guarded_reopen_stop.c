/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Synthetic guarded reopen/stop integration fixture; no hardware is accessed. */
#define _POSIX_C_SOURCE 200809L
#include <stdatomic.h>

static atomic_int guarded_stop_flag;
static atomic_int thread_create_calls;
static int inject_after_fill;
static int inject_after_submit;
static int inject_after_close;
static int inject_after_second_open;
static int pending_second_cancel;
static int rf04_cancel_policy;

#define main owner_retention_legacy_main
#define libusb_fill_interrupt_transfer owner_fixture_real_fill
#define libusb_submit_transfer owner_fixture_real_submit
#define libusb_cancel_transfer owner_fixture_real_cancel
#include "test_usb_owner_retention.c"
#undef main
#undef libusb_fill_interrupt_transfer
#undef libusb_submit_transfer
#undef libusb_cancel_transfer

int nut_guarded_dump_signal_requested(void)
{
	return atomic_load(&guarded_stop_flag);
}

static void inject_guarded_stop(void)
{
	atomic_store(&guarded_stop_flag, 1);
}

static void guarded_fill_interrupt_transfer(libusb_transfer *transfer,
	usb_dev_handle *device, unsigned char endpoint, unsigned char *buffer,
	int length, libusb_transfer_cb_fn callback, void *user_data,
	unsigned int timeout)
{
	owner_fixture_real_fill(transfer, device, endpoint, buffer, length,
		callback, user_data, timeout);
	if (inject_after_fill) {
		inject_after_fill = 0;
		inject_guarded_stop();
	}
}

static int guarded_submit_transfer(libusb_transfer *transfer)
{
	int result = owner_fixture_real_submit(transfer);
	if (inject_after_submit) {
		inject_after_submit = 0;
		inject_guarded_stop();
	}
	return result;
}

static int guarded_cancel_transfer(libusb_transfer *transfer)
{
	int result;
	if (rf04_cancel_policy) {
		pthread_mutex_lock(&ledger.lock);
		ledger.auto_callback_on_cancel = !pending_second_cancel || ledger.cancel_count == 0;
		pthread_mutex_unlock(&ledger.lock);
	}
	result = owner_fixture_real_cancel(transfer);
	return result;
}

static int guarded_pthread_create(pthread_t *thread, const pthread_attr_t *attr,
	void *(*routine)(void *), void *argument)
{
	atomic_fetch_add(&thread_create_calls, 1);
	return mock_pthread_create(thread, attr, routine, argument);
}

static int guarded_open_dev(usb_dev_handle **device, USBDevice_t *description,
	USBDeviceMatcher_t *matcher, usb_report_callback_fn callback)
{
	int result = fake_open_dev(device, description, matcher, callback);
	if (inject_after_second_open && ledger.open_dev_count == 2 && result > 0) {
		inject_after_second_open = 0;
		inject_guarded_stop();
	}
	return result;
}

static void guarded_close_dev(usb_dev_handle *device)
{
	fake_close_dev(device);
	if (inject_after_close) {
		inject_after_close = 0;
		inject_guarded_stop();
	}
}

static void install_interposed_transport(void)
{
	usb_subdriver.open_dev = guarded_open_dev;
	usb_subdriver.close_dev = guarded_close_dev;
}

static int start_guarded_listener(void)
{
	atomic_store(&guarded_stop_flag, 0);
	atomic_store(&thread_create_calls, 0);
	setup(CASE_GUARDED_REOPEN);
	install_interposed_transport();
	return microlink_usb_guard_begin(300) && microlink_usb_open() == 1
		&& async_owner != NULL && wait_for_flag(&ledger.event_waiting);
}

static int finish_clean_listener(void)
{
	atomic_store(&guarded_stop_flag, 0);
	microlink_usb_close();
	if (!wait_for_pump_ack()) {
		return 0;
	}
	microlink_usb_close();
	nut_libusb_cleanup_atexit();
	return async_owner == NULL && !nut_usb_ctx_held
		&& generations_freed_exactly(ledger.generation_count);
}

static int run_stop_at_entry(void)
{
	int opens;
	int closes;
	microlink_async_owner_t *owner;
	if (!start_guarded_listener()) {
		return 0;
	}
	owner = async_owner;
	opens = ledger.open_dev_count;
	closes = ledger.close_count;
	inject_guarded_stop();
	if (microlink_usb_reset_and_reopen() != 0 || async_owner != owner
	 || ledger.open_dev_count != opens || ledger.close_count != closes
	 || ledger.reset_count != 0 || atomic_load(&thread_create_calls) != 1) {
		return 0;
	}
	return finish_clean_listener();
}

static int run_stop_after_old_close(void)
{
	if (!start_guarded_listener()) {
		return 0;
	}
	inject_after_close = 1;
	if (microlink_usb_reset_and_reopen() != 0 || async_owner != NULL
	 || ledger.open_dev_count != 1 || ledger.close_count != 1
	 || ledger.reset_count != 0 || atomic_load(&thread_create_calls) != 1) {
		return 0;
	}
	return finish_clean_listener();
}

static int run_stop_after_new_open(void)
{
	if (!start_guarded_listener()) {
		return 0;
	}
	usb_device_gone = 1;
	inject_after_second_open = 1;
	if (microlink_usb_reset_and_reopen() != 0 || async_owner != NULL
	 || ledger.open_dev_count != 2 || ledger.close_count != 2
	 || ledger.submit_count != 1 || usb_device_gone != 1
	 || atomic_load(&thread_create_calls) != 1) {
		return 0;
	}
	return finish_clean_listener();
}

static int run_stop_before_owner_publish(void)
{
	if (!start_guarded_listener()) {
		return 0;
	}
	inject_after_fill = 1;
	if (microlink_usb_reset_and_reopen() != 0 || async_owner != NULL
	 || ledger.generation_count != 2 || !generations_freed_exactly(2)
	 || ledger.submit_count != 1 || ledger.open_dev_count != 2
	 || ledger.close_count != 2 || atomic_load(&thread_create_calls) != 1) {
		return 0;
	}
	return finish_clean_listener();
}

static int run_direct_start_with_active_owner(void)
{
	microlink_async_owner_t *owner;
	int submits;
	int creates;
	if (!start_guarded_listener()) {
		return 0;
	}
	owner = async_owner;
	submits = ledger.submit_count;
	creates = atomic_load(&thread_create_calls);
	inject_guarded_stop();
	if (microlink_usb_async_start() != -1 || async_owner != owner
	 || ledger.submit_count != submits || atomic_load(&thread_create_calls) != creates
	 || ledger.generation_count != 1 || ledger.free_owner_count != 0) {
		return 0;
	}
	return finish_clean_listener();
}

static int run_start_no_owner_with_stop(void)
{
	int generations;
	int allocations;
	int submissions;
	int threads;
	if (!start_guarded_listener() || !microlink_usb_async_stop() || async_owner) {
		return 0;
	}
	generations = ledger.generation_count;
	allocations = ledger.free_owner_count;
	submissions = ledger.submit_count;
	threads = atomic_load(&thread_create_calls);
	inject_guarded_stop();
	if (microlink_usb_async_start() != 0 || async_owner
	 || ledger.generation_count != generations
	 || ledger.free_owner_count != allocations
	 || ledger.submit_count != submissions
	 || atomic_load(&thread_create_calls) != threads) {
		return 0;
	}
	return finish_clean_listener();
}

static int run_ordinary_reopen_with_stop_flag(void)
{
	int result;
	atomic_store(&guarded_stop_flag, 0);
	atomic_store(&thread_create_calls, 0);
	setup(CASE_CANCEL_SUCCESS);
	ledger.auto_callback_on_cancel = 1;
	ledger.hold_terminal_event = 0;
	install_interposed_transport();
	if (microlink_usb_open() != 1 || !async_owner
	 || !wait_for_flag(&ledger.event_waiting)) {
		return 0;
	}
	inject_guarded_stop();
	result = microlink_usb_reset_and_reopen();
	if (result != 1 || guarded_monitor || !async_owner
	 || ledger.reset_count != 1 || ledger.sleep_count != 1
	 || ledger.open_dev_count != 2 || ledger.close_count != 1
	 || atomic_load(&thread_create_calls) != 2) {
		return 0;
	}
	atomic_store(&guarded_stop_flag, 0);
	return finish_clean_listener();
}

static int run_stop_during_start(int pending)
{
	int result;
	if (!start_guarded_listener()) {
		return 0;
	}
	pending_second_cancel = pending;
	rf04_cancel_policy = 1;
	inject_after_submit = 1;
	result = microlink_usb_reset_and_reopen();
	if (result != 0 || ledger.open_dev_count != 2
	 || atomic_load(&thread_create_calls) != 2) {
		rf04_cancel_policy = 0;
		return 0;
	}
	if (!pending) {
		if (ledger.pending || async_owner || !wait_for_pump_ack()) {
			rf04_cancel_policy = 0;
			return 0;
		}
		microlink_usb_close();
		nut_libusb_cleanup_atexit();
		rf04_cancel_policy = 0;
		return async_owner == NULL && !nut_usb_ctx_held
			&& generations_freed_exactly(2) && ledger.close_count == 2;
	}
	if (!async_owner || !ledger.pending || ledger.free_owner_count != 1
	 || ledger.generation_count != 2 || !nut_usb_ctx_held
	 || ledger.close_count != 1) {
		rf04_cancel_policy = 0;
		return 0;
	}
	pthread_mutex_lock(&ledger.lock);
	ledger.callback_returned = 0;
	pthread_mutex_unlock(&ledger.lock);
	permit_callback(LIBUSB_TRANSFER_CANCELLED);
	if (!wait_for_flag(&ledger.callback_returned)) {
		rf04_cancel_policy = 0;
		return 0;
	}
	pthread_mutex_lock(&ledger.lock);
	ledger.release_event_return = 1;
	pthread_cond_broadcast(&ledger.cond);
	pthread_mutex_unlock(&ledger.lock);
	if (!wait_for_pump_ack()) {
		return 0;
	}
	atomic_store(&guarded_stop_flag, 0);
	microlink_usb_close();
	nut_libusb_cleanup_atexit();
	rf04_cancel_policy = 0;
	return async_owner == NULL && !nut_usb_ctx_held
		&& generations_freed_exactly(2) && ledger.close_count == 2;
}

int main(int argc, char **argv)
{
	int ok = 0;
	reference_source_only_symbols();
	if (argc != 2) {
		return 2;
	}
	if (strcmp(argv[1], "stop-entry") == 0) {
		ok = run_stop_at_entry();
	} else if (strcmp(argv[1], "stop-after-close") == 0) {
		ok = run_stop_after_old_close();
	} else if (strcmp(argv[1], "stop-after-open") == 0) {
		ok = run_stop_after_new_open();
	} else if (strcmp(argv[1], "stop-prepublish") == 0) {
		ok = run_stop_before_owner_publish();
	} else if (strcmp(argv[1], "start-active-owner-stop") == 0) {
		ok = run_direct_start_with_active_owner();
	} else if (strcmp(argv[1], "start-no-owner-stop") == 0) {
		ok = run_start_no_owner_with_stop();
	} else if (strcmp(argv[1], "start-stop-quiescent") == 0) {
		ok = run_stop_during_start(0);
	} else if (strcmp(argv[1], "start-stop-pending") == 0) {
		ok = run_stop_during_start(1);
	} else if (strcmp(argv[1], "ordinary-reopen-stop-flag") == 0) {
		ok = run_ordinary_reopen_with_stop_flag();
	} else if (strcmp(argv[1], "healthy-guarded-reopen") == 0) {
		ok = run_guarded_reopen_no_reset();
	} else if (strcmp(argv[1], "ordinary-fallback") == 0) {
		ok = run_open_fallback();
	} else {
		return owner_retention_legacy_main(argc, argv);
	}
	if (!ok) {
		fprintf(stderr, "FAIL %s\n", argv[1]);
		atomic_store(&guarded_stop_flag, 0);
		pthread_mutex_lock(&ledger.lock);
		ledger.release_submit = 1;
		ledger.release_resubmit = 1;
		ledger.release_pump_start = 1;
		ledger.release_event_return = 1;
		ledger.auto_callback_on_cancel = 1;
		ledger.callback_status = LIBUSB_TRANSFER_CANCELLED;
		if (ledger.pending) {
			ledger.callback_permit = 1;
		}
		pthread_cond_broadcast(&ledger.cond);
		pthread_mutex_unlock(&ledger.lock);
		if (async_owner) {
			microlink_usb_close();
		}
		(void)wait_for_pump_ack();
		microlink_usb_close();
		nut_libusb_cleanup_atexit();
		return 1;
	}
	printf("PASS %s\n", argv[1]);
	return 0;
}
