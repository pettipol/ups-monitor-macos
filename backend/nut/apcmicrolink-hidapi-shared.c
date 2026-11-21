/*
 * Guarded transport core, unbound unless a test or explicit candidate build
 * supplies a host. Native candidate preparation is disabled by default.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include <apcmicrolink-usb.h>
#include "apcmicrolink-hidapi-shared-host.h"

#if defined(MLINK_HIDAPI_NATIVE_CANDIDATE) && defined(MLINK_HIDAPI_SHARED_TEST)
#error "MLINK_HIDAPI_NATIVE_CANDIDATE and MLINK_HIDAPI_SHARED_TEST are mutually exclusive"
#endif

#ifdef MLINK_HIDAPI_NATIVE_CANDIDATE
#include "apcmicrolink-hidapi-native.h"
#include "apcmicrolink-hidapi-session.h"
#endif

#include <string.h>

#define REPORT_SIZE 64U
#define PAYLOAD_SIZE (REPORT_SIZE - 1U)
#define MAX_GUARD_SECONDS 300L
#define MAX_FOREIGN_REPORTS 32U
#define MAX_FLUSH_REPORTS 32U

typedef struct shared_state {
	const mlink_shared_host_ops_t *ops;
	void *user;
	mlink_shared_layout_t layout;
	int guard_started;
	int guard_invalid;
	int terminal;
	int attempted;
	int opened;
	int admitted;
	int admission_succeeded;
	int opening;
	int close_called;
	int close_pending;
	int in_api;
	int have_clock;
	int64_t last_clock_ms;
	int64_t deadline_ms;
	mlink_admission_diagnostic_t admission_diagnostic;
	unsigned char report[REPORT_SIZE];
	size_t report_pos;
	size_t report_end;
} shared_state_t;

static shared_state_t state;

static void record_diagnostic(mlink_admission_stage_t stage,
	mlink_admission_reason_t reason, mlink_admission_parser_status_t parser_status)
{
	if (state.admission_succeeded || state.admission_diagnostic.reason != MLINK_ADMISSION_REASON_NONE) {
		return;
	}
	state.admission_diagnostic.stage = stage;
	state.admission_diagnostic.reason = reason;
	state.admission_diagnostic.parser_status = parser_status;
}

static int valid_diagnostic(mlink_admission_diagnostic_t diagnostic,
	mlink_admission_stage_t expected_stage)
{
	if (diagnostic.stage <= MLINK_ADMISSION_STAGE_NONE
	 || diagnostic.stage > MLINK_ADMISSION_STAGE_LAYOUT
	 || diagnostic.stage != expected_stage
	 || diagnostic.reason <= MLINK_ADMISSION_REASON_NONE
	 || diagnostic.reason > MLINK_ADMISSION_REASON_CANCELLED
	 || diagnostic.parser_status < MLINK_ADMISSION_PARSER_NOT_RUN
	 || diagnostic.parser_status > MLINK_ADMISSION_PARSER_AMBIGUOUS) return 0;
	switch (diagnostic.stage) {
	case MLINK_ADMISSION_STAGE_INIT:
		if (diagnostic.reason != MLINK_ADMISSION_REASON_STATE
		 && diagnostic.reason != MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_HOST_FAILED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_CANCELLED) return 0;
		break;
	case MLINK_ADMISSION_STAGE_NONEXCLUSIVE:
		if (diagnostic.reason != MLINK_ADMISSION_REASON_STATE
		 && diagnostic.reason != MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_HOST_FAILED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_CANCELLED) return 0;
		break;
	case MLINK_ADMISSION_STAGE_SELECT:
		if (diagnostic.reason != MLINK_ADMISSION_REASON_STATE
		 && diagnostic.reason != MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_HOST_FAILED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_CANCELLED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_SELECTION_ZERO
		 && diagnostic.reason != MLINK_ADMISSION_REASON_SELECTION_AMBIGUOUS
		 && diagnostic.reason != MLINK_ADMISSION_REASON_PATH_INVALID
		 && diagnostic.reason != MLINK_ADMISSION_REASON_IDENTITY_INCONSISTENT
		 && diagnostic.reason != MLINK_ADMISSION_REASON_ENTRY_LIMIT
		 && diagnostic.reason != MLINK_ADMISSION_REASON_ALLOCATION_FAILED) return 0;
		break;
	case MLINK_ADMISSION_STAGE_OPEN:
		if (diagnostic.reason != MLINK_ADMISSION_REASON_STATE
		 && diagnostic.reason != MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_HOST_FAILED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_CANCELLED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_OPEN_NULL) return 0;
		break;
	case MLINK_ADMISSION_STAGE_LAYOUT:
		if (diagnostic.reason != MLINK_ADMISSION_REASON_STATE
		 && diagnostic.reason != MLINK_ADMISSION_REASON_HOST_FAILED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_CANCELLED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_OPEN_EXCLUSIVE
		 && diagnostic.reason != MLINK_ADMISSION_REASON_DESCRIPTOR_UNAVAILABLE
		 && diagnostic.reason != MLINK_ADMISSION_REASON_DESCRIPTOR_LIMIT
		 && diagnostic.reason != MLINK_ADMISSION_REASON_PARSER_REJECTED
		 && diagnostic.reason != MLINK_ADMISSION_REASON_LAYOUT_INVALID) return 0;
		break;
	default:
		return 0;
	}
	if (diagnostic.reason == MLINK_ADMISSION_REASON_PARSER_REJECTED) {
		return diagnostic.parser_status > MLINK_ADMISSION_PARSER_OK;
	}
	return diagnostic.parser_status == MLINK_ADMISSION_PARSER_NOT_RUN
		|| (diagnostic.stage == MLINK_ADMISSION_STAGE_LAYOUT
			&& diagnostic.reason == MLINK_ADMISSION_REASON_LAYOUT_INVALID
			&& diagnostic.parser_status == MLINK_ADMISSION_PARSER_OK);
}

static void record_host_diagnostic(mlink_admission_stage_t stage,
	mlink_admission_reason_t fallback_reason)
{
	mlink_admission_diagnostic_t diagnostic;
	if (state.admission_succeeded || state.admission_diagnostic.reason != MLINK_ADMISSION_REASON_NONE) return;
	if (state.ops != NULL && state.ops->get_admission_diagnostic != NULL) {
		diagnostic = state.ops->get_admission_diagnostic(state.user);
		if (valid_diagnostic(diagnostic, stage)) {
			state.admission_diagnostic = diagnostic;
			return;
		}
	}
	record_diagnostic(stage, fallback_reason, MLINK_ADMISSION_PARSER_NOT_RUN);
}

mlink_admission_diagnostic_t mlink_shared_admission_diagnostic(void)
{
	return state.admission_diagnostic;
}

#ifdef MLINK_HIDAPI_NATIVE_CANDIDATE
static mlink_hidapi_native_binding_t native_binding;
static int native_prepare_attempted;
static int native_dispose_attempted;
#endif

static int clock_now(int64_t *now)
{
	if (state.ops == NULL || state.ops->monotonic_ms == NULL
	 || state.ops->monotonic_ms(state.user, now) != 0 || *now < 0) {
		record_diagnostic(MLINK_ADMISSION_STAGE_GUARD,
			MLINK_ADMISSION_REASON_CLOCK_FAILED, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 0;
	}
	if (state.have_clock && *now < state.last_clock_ms) {
		record_diagnostic(MLINK_ADMISSION_STAGE_GUARD,
			MLINK_ADMISSION_REASON_CLOCK_REGRESSION, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 0;
	}
	state.have_clock = 1;
	state.last_clock_ms = *now;
	return 1;
}

static int stopped(void)
{
	if (state.ops == NULL || state.ops->stop_requested == NULL) {
		record_diagnostic(MLINK_ADMISSION_STAGE_GUARD,
			MLINK_ADMISSION_REASON_CALLBACK_MISSING, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 1;
	}
	if (state.ops->stop_requested(state.user) != 0) {
		record_diagnostic(MLINK_ADMISSION_STAGE_GUARD,
			MLINK_ADMISSION_REASON_STOP, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 1;
	}
	return 0;
}

static int usable(void)
{
	int64_t now;
	if (!state.guard_started) {
		record_diagnostic(MLINK_ADMISSION_STAGE_GUARD,
			MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 0;
	}
	if (state.guard_invalid) {
		record_diagnostic(MLINK_ADMISSION_STAGE_GUARD,
			MLINK_ADMISSION_REASON_INVALID_GUARD, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 0;
	}
	if (state.terminal) {
		record_diagnostic(MLINK_ADMISSION_STAGE_GUARD,
			MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		return 0;
	}
	if (stopped() || state.terminal) {
		if (state.admission_diagnostic.reason == MLINK_ADMISSION_REASON_NONE) {
			record_diagnostic(MLINK_ADMISSION_STAGE_GUARD,
				MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		}
		state.terminal = 1;
		return 0;
	}
	if (!clock_now(&now) || state.terminal) {
		if (state.admission_diagnostic.reason == MLINK_ADMISSION_REASON_NONE) {
			record_diagnostic(MLINK_ADMISSION_STAGE_GUARD,
				MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		}
		state.terminal = 1;
		return 0;
	}
	if (now >= state.deadline_ms) {
		record_diagnostic(MLINK_ADMISSION_STAGE_GUARD,
			MLINK_ADMISSION_REASON_DEADLINE, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 0;
	}
	return 1;
}

static unsigned int remaining_ms(void)
{
	int64_t now;
	int64_t remaining;
	if (!usable() || !clock_now(&now)) return 0;
	remaining = state.deadline_ms - now;
	if (remaining <= 0) { state.terminal = 1; return 0; }
	return remaining > 300000 ? 300000U : (unsigned int)remaining;
}

static void close_if_quiescent(void)
{
	int rc;
	if (!state.close_pending || state.in_api || !state.opened || state.close_called) {
		return;
	}
	state.close_called = 1;
	if (state.ops == NULL || state.ops->close == NULL) {
		state.terminal = 1;
		return;
	}
	rc = state.ops->close(state.user);
	if (rc != 0) {
		state.terminal = 1;
		return;
	}
	state.close_pending = 0;
	state.opened = 0;
}

static void api_enter(void)
{
	state.in_api++;
}

static void api_leave(void)
{
	if (state.in_api > 0) {
		state.in_api--;
	}
	close_if_quiescent();
}

static int call_status(int (*fn)(void *), mlink_admission_stage_t stage)
{
	int rc;
	if (!usable()) {
		state.terminal = 1;
		return 0;
	}
	if (fn == NULL) {
		record_diagnostic(stage, MLINK_ADMISSION_REASON_CALLBACK_MISSING,
			MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 0;
	}
	api_enter();
	rc = fn(state.user);
	if (rc != 0) {
		record_host_diagnostic(stage, MLINK_ADMISSION_REASON_HOST_FAILED);
	}
	api_leave();
	if (rc != 0) {
		state.terminal = 1;
		return 0;
	}
	if (!usable()) {
		state.terminal = 1;
		return 0;
	}
	return 1;
}

void microlink_usb_addvars(void)
{
}

int microlink_usb_guard_begin(long seconds)
{
	int64_t now;
	if (state.guard_started) {
		return usable();
	}
	state.guard_started = 1;
	if (seconds < 1 || seconds > MAX_GUARD_SECONDS) {
		record_diagnostic(MLINK_ADMISSION_STAGE_GUARD,
			MLINK_ADMISSION_REASON_INVALID_GUARD, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.guard_invalid = 1;
		state.terminal = 1;
		return 0;
	}
	if (!clock_now(&now)) {
		state.guard_invalid = 1;
		state.terminal = 1;
		return 0;
	}
	if (now > INT64_MAX - (int64_t)seconds * 1000) {
		record_diagnostic(MLINK_ADMISSION_STAGE_GUARD,
			MLINK_ADMISSION_REASON_DEADLINE, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.guard_invalid = 1;
		state.terminal = 1;
		return 0;
	}
	state.deadline_ms = now + (int64_t)seconds * 1000;
	return usable();
}

int microlink_usb_guard_expired(void)
{
	if (!state.guard_started) return 0;
	return !usable();
}

int microlink_usb_open(void)
{
	mlink_shared_layout_t layout;
	unsigned int selected_count = 0;
	int rc;
	if (state.attempted) {
		record_diagnostic(MLINK_ADMISSION_STAGE_PREPARE,
			MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 0;
	}
	if (!usable()) {
		state.terminal = 1;
		return 0;
	}
	if (state.ops == NULL) {
		record_diagnostic(MLINK_ADMISSION_STAGE_PREPARE,
			MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 0;
	}
	state.attempted = 1;
	if (!call_status(state.ops->init, MLINK_ADMISSION_STAGE_INIT)
	 || !call_status(state.ops->set_nonexclusive, MLINK_ADMISSION_STAGE_NONEXCLUSIVE)) {
		return 0;
	}
	if (!usable()) {
		state.terminal = 1;
		return 0;
	}
	if (state.ops->select_unique == NULL) {
		record_diagnostic(MLINK_ADMISSION_STAGE_SELECT,
			MLINK_ADMISSION_REASON_CALLBACK_MISSING, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 0;
	}
	api_enter();
	rc = state.ops->select_unique(state.user, &selected_count);
	if (rc != 0) record_host_diagnostic(MLINK_ADMISSION_STAGE_SELECT,
		MLINK_ADMISSION_REASON_HOST_FAILED);
	api_leave();
	if (rc != 0) {
		state.terminal = 1;
		return 0;
	}
	if (!usable()) {
		state.terminal = 1;
		return 0;
	}
	if (selected_count != 1) {
		record_diagnostic(MLINK_ADMISSION_STAGE_SELECT,
			selected_count > 1 ? MLINK_ADMISSION_REASON_SELECTION_AMBIGUOUS
				: MLINK_ADMISSION_REASON_SELECTION_ZERO,
			MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 0;
	}
	if (state.ops->open_selected == NULL) {
		record_diagnostic(MLINK_ADMISSION_STAGE_OPEN,
			MLINK_ADMISSION_REASON_CALLBACK_MISSING, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 0;
	}
	if (!usable()) {
		state.terminal = 1;
		return 0;
	}
	state.opening = 1;
	api_enter();
	rc = state.ops->open_selected(state.user);
	if (rc == 0) {
		state.opened = 1;
		state.close_called = 0;
	} else {
		record_host_diagnostic(MLINK_ADMISSION_STAGE_OPEN,
			MLINK_ADMISSION_REASON_HOST_FAILED);
	}
	api_leave();
	state.opening = 0;
	if (rc != 0) {
		state.terminal = 1;
		if (state.opened) {
			state.close_pending = 1;
			close_if_quiescent();
		}
		return 0;
	}
	if (!usable() || !state.opened) {
		if (!state.opened && state.admission_diagnostic.reason == MLINK_ADMISSION_REASON_NONE) {
			record_diagnostic(MLINK_ADMISSION_STAGE_OPEN,
				MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		}
		state.terminal = 1;
		if (state.opened) {
			state.close_pending = 1;
			close_if_quiescent();
		}
		return 0;
	}

	memset(&layout, 0, sizeof(layout));
	if (state.ops->read_layout == NULL) {
		record_diagnostic(MLINK_ADMISSION_STAGE_LAYOUT,
			MLINK_ADMISSION_REASON_CALLBACK_MISSING, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		microlink_usb_close();
		return 0;
	}
	if (!usable()) {
		state.terminal = 1;
		microlink_usb_close();
		return 0;
	}
	api_enter();
	rc = state.ops->read_layout(state.user, &layout);
	if (rc != 0) record_host_diagnostic(MLINK_ADMISSION_STAGE_LAYOUT,
		MLINK_ADMISSION_REASON_HOST_FAILED);
	api_leave();
	if (rc != 0) {
		state.terminal = 1;
		microlink_usb_close();
		return 0;
	}
	if (!usable()) {
		state.terminal = 1;
		microlink_usb_close();
		return 0;
	}
	if (!state.opened) {
		record_diagnostic(MLINK_ADMISSION_STAGE_LAYOUT,
			MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		microlink_usb_close();
		return 0;
	}
	if (layout.input_report_id == 0 || layout.input_report_id > 255
	 || layout.output_report_id == 0 || layout.output_report_id > 255
	 || layout.input_direction != MLINK_SHARED_INPUT
	 || layout.output_direction != MLINK_SHARED_OUTPUT
	 || layout.input_report_length != REPORT_SIZE
	 || layout.output_report_length != REPORT_SIZE) {
		record_diagnostic(MLINK_ADMISSION_STAGE_LAYOUT,
			MLINK_ADMISSION_REASON_LAYOUT_INVALID, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		microlink_usb_close();
		return 0;
	}
	state.layout = layout;
	if (!usable() || !state.opened) {
		if (!state.opened && state.admission_diagnostic.reason == MLINK_ADMISSION_REASON_NONE) {
			record_diagnostic(MLINK_ADMISSION_STAGE_LAYOUT,
				MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		}
		state.terminal = 1;
		microlink_usb_close();
		return 0;
	}
	state.admitted = 1;
	state.admission_succeeded = 1;
	state.admission_diagnostic = (mlink_admission_diagnostic_t){
		MLINK_ADMISSION_STAGE_NONE, MLINK_ADMISSION_REASON_NONE,
		MLINK_ADMISSION_PARSER_NOT_RUN
	};
	state.report_pos = state.report_end = 0;
	return 1;
}

void microlink_usb_close(void)
{
	state.terminal = 1;
	if ((!state.opened && !state.opening) || state.close_called) {
		return;
	}
	state.close_pending = 1;
	close_if_quiescent();
}

static int read_one_report(int64_t caller_deadline_ms, int allow_immediate)
{
	unsigned char incoming[REPORT_SIZE + 1U];
	ssize_t count;
	int64_t now;
	int64_t caller_remaining;
	unsigned int budget_ms;
	unsigned int timeout_ms;
	if (!usable() || !clock_now(&now)) {
		state.terminal = 1;
		return -1;
	}
	budget_ms = remaining_ms();
	caller_remaining = caller_deadline_ms - now;
	if (caller_remaining <= 0) {
		if (!allow_immediate) return 0;
		timeout_ms = 0;
	} else {
		timeout_ms = caller_remaining > 300000
			? 300000U : (unsigned int)caller_remaining;
		if (timeout_ms > budget_ms) timeout_ms = budget_ms;
	}
	if (!usable() || state.ops == NULL || state.ops->read_report == NULL) {
		state.terminal = 1;
		return -1;
	}
	api_enter();
	count = state.ops->read_report(state.user, incoming, sizeof(incoming), timeout_ms);
	api_leave();
	if (!usable() || !state.opened) {
		state.terminal = 1;
		return -1;
	}
	if (count == 0) return 0;
	if (count < 0 || (size_t)count > sizeof(incoming)) {
		state.terminal = 1;
		return -1;
	}
	if (incoming[0] != state.layout.input_report_id) return 2;
	if (count != REPORT_SIZE) {
		state.terminal = 1;
		return -1;
	}
	memcpy(state.report, incoming, REPORT_SIZE);
	state.report_pos = 1;
	state.report_end = REPORT_SIZE;
	return 1;
}

static int read_matching_report(int64_t caller_deadline_ms)
{
	unsigned int foreign;
	for (foreign = 0; foreign <= MAX_FOREIGN_REPORTS; foreign++) {
		int rc = read_one_report(caller_deadline_ms, foreign == 0);
		if (rc != 2) return rc;
	}
	state.terminal = 1;
	return -1;
}

int microlink_usb_send_bytes(const unsigned char *buf, size_t len)
{
	unsigned char outgoing[REPORT_SIZE];
	ssize_t count;
	if (buf == NULL || len == 0 || len > PAYLOAD_SIZE || !state.admitted
	 || !usable() || state.ops == NULL || state.ops->write_report == NULL) {
		state.terminal = 1;
		return 0;
	}
	outgoing[0] = (unsigned char)state.layout.output_report_id;
	memset(outgoing + 1, 0, PAYLOAD_SIZE);
	memcpy(outgoing + 1, buf, len);
	api_enter();
	count = state.ops->write_report(state.user, outgoing, sizeof(outgoing));
	api_leave();
	if (count != REPORT_SIZE || !usable() || !state.opened) {
		state.terminal = 1;
		return 0;
	}
	return 1;
}

int microlink_usb_get_char(unsigned char *ch, long d_usec)
{
	int rc;
	unsigned int timeout_ms;
	if (ch == NULL || !state.admitted || !usable()) {
		state.terminal = 1;
		return -1;
	}
	if (state.report_pos >= state.report_end) {
		int64_t now;
		int64_t call_deadline;
	int64_t guard_remaining;
		if (d_usec < 0) d_usec = 0;
		timeout_ms = d_usec / 1000L > 300000L ? 300000U
			: (unsigned int)(d_usec / 1000L + ((d_usec % 1000L) != 0));
		if (!usable() || !clock_now(&now)) return -1;
		guard_remaining = state.deadline_ms - now;
		if (guard_remaining <= 0) { state.terminal = 1; return -1; }
		if ((int64_t)timeout_ms > guard_remaining)
			timeout_ms = (unsigned int)guard_remaining;
		call_deadline = now + timeout_ms;
		rc = read_matching_report(call_deadline);
		if (rc <= 0) {
			return rc;
		}
	}
	if (!usable()) {
		return -1;
	}
	*ch = state.report[state.report_pos++];
	return 1;
}

size_t microlink_usb_drop_report_padding(void)
{
	size_t i;
	size_t remaining;
	if (!usable() || state.report_pos >= state.report_end) return 0;
	for (i = state.report_pos; i < state.report_end; i++) {
		if (state.report[i] != 0) return 0;
	}
	remaining = state.report_end - state.report_pos;
	state.report_pos = state.report_end;
	return remaining;
}

void microlink_usb_flush_io(void)
{
	unsigned int i;
	int rc;
	state.report_pos = state.report_end = 0;
	if (!state.admitted) {
		state.terminal = 1;
		return;
	}
	for (i = 0; i < MAX_FLUSH_REPORTS; i++) {
		int64_t now;
		if (!usable() || !clock_now(&now)) return;
		rc = read_one_report(now, 1);
		state.report_pos = state.report_end = 0;
		if (rc == 0 || rc < 0) {
			return;
		}
	}
	state.terminal = 1;
}

int microlink_usb_get_hid_fallback(int max_age_sec, int *ac_present,
	int *discharging, int *below_rcl, long *battery_charge, long *battery_runtime)
{
	(void)max_age_sec;
	(void)ac_present;
	(void)discharging;
	(void)below_rcl;
	(void)battery_charge;
	(void)battery_runtime;
	return 0;
}

int microlink_usb_hid_fallback_supported(void)
{
	return 0;
}

int microlink_usb_reset_and_reopen(void)
{
	return 0;
}

int microlink_usb_device_gone(void)
{
	return 0;
}

#ifdef MLINK_HIDAPI_NATIVE_CANDIDATE
int mlink_shared_prepare_native(
	const struct mlink_hidapi_native_config *config, long seconds)
{
	if (native_prepare_attempted) {
		record_diagnostic(MLINK_ADMISSION_STAGE_PREPARE,
			MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED, MLINK_ADMISSION_PARSER_NOT_RUN);
		return 0;
	}
	native_prepare_attempted = 1;
	if (config == NULL || seconds < 1 || seconds > MAX_GUARD_SECONDS) {
		record_diagnostic(MLINK_ADMISSION_STAGE_PREPARE,
			MLINK_ADMISSION_REASON_INVALID_CONFIG, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		state.guard_invalid = 1;
		return 0;
	}
	if (state.ops != NULL || state.guard_started || state.opened || state.opening
	 || state.in_api || state.terminal) {
		record_diagnostic(MLINK_ADMISSION_STAGE_PREPARE,
			MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		state.guard_invalid = 1;
		return 0;
	}
	if (mlink_hidapi_native_create(config, &native_binding) != 0) {
		record_diagnostic(MLINK_ADMISSION_STAGE_PREPARE,
			MLINK_ADMISSION_REASON_HOST_FAILED, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		return 0;
	}
	state.ops = native_binding.ops;
	state.user = native_binding.user;
	if (!microlink_usb_guard_begin(seconds)) {
		(void)mlink_shared_finish_native();
		return 0;
	}
	return 1;
}

mlink_hidapi_session_finish_t mlink_shared_finish_native(void)
{
	if (!native_prepare_attempted) {
		native_prepare_attempted = 1;
		record_diagnostic(MLINK_ADMISSION_STAGE_PREPARE,
			MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		state.terminal = 1;
		state.guard_invalid = 1;
		return MLINK_HIDAPI_SESSION_RELEASED;
	}
	state.terminal = 1;
	state.admitted = 0;
	state.report_pos = state.report_end = 0;
	if (state.ops == NULL) {
		return MLINK_HIDAPI_SESSION_RELEASED;
	}

	/* close() marks terminal immediately; close_if_quiescent defers ownership
	 * release until any active host call has returned. Finish may be called
	 * again after that point, but a failed dispose itself is never retried. */
	microlink_usb_close();
	if (state.opened || state.opening || state.in_api || state.close_pending) {
		return MLINK_HIDAPI_SESSION_RETAINED;
	}
	if (native_dispose_attempted) return MLINK_HIDAPI_SESSION_RETAINED;
	native_dispose_attempted = 1;
	if (mlink_hidapi_native_dispose(&native_binding) != 0) {
		return MLINK_HIDAPI_SESSION_RETAINED;
	}
	state.ops = NULL;
	state.user = NULL;
	memset(&state.layout, 0, sizeof(state.layout));
	state.admitted = 0;
	state.report_pos = state.report_end = 0;
	return MLINK_HIDAPI_SESSION_RELEASED;
}
#endif

#ifdef MLINK_HIDAPI_SHARED_TEST
int mlink_shared_test_bind(const mlink_shared_host_ops_t *ops, void *user)
{
	if (ops == NULL || ops->init == NULL || ops->set_nonexclusive == NULL
	 || ops->select_unique == NULL || ops->open_selected == NULL
	 || ops->read_layout == NULL
	 || ops->read_report == NULL || ops->write_report == NULL
	 || ops->close == NULL || ops->stop_requested == NULL
	 || ops->monotonic_ms == NULL) {
		return 0;
	}
	if (state.opened || state.opening || state.in_api || state.close_pending) return 0;
	memset(&state, 0, sizeof(state));
	state.ops = ops;
	state.user = user;
	return 1;
}

void mlink_shared_test_unbind(void)
{
	if (state.opened && !state.close_called) {
		microlink_usb_close();
	}
	if (state.opened || state.opening || state.in_api || state.close_pending) return;
	memset(&state, 0, sizeof(state));
}
#endif
