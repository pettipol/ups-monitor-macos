/* SPDX-License-Identifier: GPL-2.0-or-later
 * Inactive native host operations: no constructor, registration or entrypoint.
 * HIDAPI may block internally; the guard is not a hard OS-call deadline.
 */
#include "apcmicrolink-hidapi-native.h"
#include "apcmicrolink-hid-descriptor-checked.h"

#include <hidapi.h>
#include <hidapi_darwin.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wchar.h>

#if HID_API_VERSION != HID_API_MAKE_VERSION(0, 15, 0)
#error "This binding requires the pinned HIDAPI 0.15.0 headers"
#endif

#define NATIVE_MAX_PATH_BYTES 4096U
#define NATIVE_MAX_ENUM_ENTRIES 1024U
#define NATIVE_REPORT_BYTES 64U

typedef struct native_state {
	mlink_hidapi_native_config_t config;
	hid_device *handle;
	char *path;
	int active;
	int init_attempted;
	int initialized;
	int nonexclusive_attempted;
	int nonexclusive;
	int select_attempted;
	int open_attempted;
	int layout_attempted;
	int layout_valid;
	mlink_admission_diagnostic_t admission_diagnostic;
} native_state_t;

/* HIDAPI init/exit and the Darwin opening option are process-global. */
static native_state_t *owner;
static int cancelled(native_state_t *state);

static void native_record(native_state_t *state, mlink_admission_stage_t stage,
	mlink_admission_reason_t reason, mlink_admission_parser_status_t parser_status)
{
	if (state == NULL || state->admission_diagnostic.reason != MLINK_ADMISSION_REASON_NONE) return;
	state->admission_diagnostic.stage = stage;
	state->admission_diagnostic.reason = reason;
	state->admission_diagnostic.parser_status = parser_status;
}

static int native_cancelled_at(native_state_t *state, mlink_admission_stage_t stage)
{
	if (cancelled(state)) {
		native_record(state, stage, MLINK_ADMISSION_REASON_CANCELLED,
			MLINK_ADMISSION_PARSER_NOT_RUN);
		return 1;
	}
	return 0;
}

static mlink_admission_diagnostic_t native_get_admission_diagnostic(void *user)
{
	native_state_t *state = user;
	mlink_admission_diagnostic_t empty = {
		MLINK_ADMISSION_STAGE_NONE, MLINK_ADMISSION_REASON_NONE,
		MLINK_ADMISSION_PARSER_NOT_RUN
	};
	return state == NULL ? empty : state->admission_diagnostic;
}

static int enter(native_state_t *state)
{
	if (state == NULL || state != owner || state->active) return 0;
	state->active = 1;
	return 1;
}

static int leave(native_state_t *state, int rc)
{
	state->active = 0;
	return rc;
}

static int cancelled(native_state_t *state)
{
	return state->config.stop_requested(state->config.stop_user) != 0;
}

static int native_init(void *user)
{
	native_state_t *state = user;
	int rc;
	if (!enter(state)) return -1;
	if (state->init_attempted) {
		native_record(state, MLINK_ADMISSION_STAGE_INIT,
			MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED, MLINK_ADMISSION_PARSER_NOT_RUN);
		return leave(state, -1);
	}
	if (native_cancelled_at(state, MLINK_ADMISSION_STAGE_INIT)) return leave(state, -1);
	state->init_attempted = 1;
	rc = hid_init();
	if (rc == 0) state->initialized = 1;
	else native_record(state, MLINK_ADMISSION_STAGE_INIT,
		MLINK_ADMISSION_REASON_HOST_FAILED, MLINK_ADMISSION_PARSER_NOT_RUN);
	return leave(state, rc == 0 ? 0 : -1);
}

static int native_set_nonexclusive(void *user)
{
	native_state_t *state = user;
	if (!enter(state)) return -1;
	if (!state->initialized) {
		native_record(state, MLINK_ADMISSION_STAGE_NONEXCLUSIVE,
			MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		return leave(state, -1);
	}
	if (state->nonexclusive_attempted) {
		native_record(state, MLINK_ADMISSION_STAGE_NONEXCLUSIVE,
			MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED, MLINK_ADMISSION_PARSER_NOT_RUN);
		return leave(state, -1);
	}
	if (native_cancelled_at(state, MLINK_ADMISSION_STAGE_NONEXCLUSIVE)) {
		return leave(state, -1);
	}
	state->nonexclusive_attempted = 1;
	hid_darwin_set_open_exclusive(0);
	state->nonexclusive = hid_darwin_get_open_exclusive() == 0;
	if (!state->nonexclusive) native_record(state, MLINK_ADMISSION_STAGE_NONEXCLUSIVE,
		MLINK_ADMISSION_REASON_HOST_FAILED, MLINK_ADMISSION_PARSER_NOT_RUN);
	return leave(state, state->nonexclusive ? 0 : -1);
}

static int path_valid(const char *path)
{
	size_t length;
	if (path == NULL || path[0] == '\0') return 0;
	for (length = 0; length < NATIVE_MAX_PATH_BYTES; length++) {
		if (path[length] == '\0') return 1;
	}
	return 0;
}

static int identity_matches(const native_state_t *state,
	const struct hid_device_info *info)
{
	return info->vendor_id == state->config.vendor_id
		&& info->product_id == state->config.product_id
		&& info->bus_type == HID_API_BUS_USB;
}

static int same_wide_string(const wchar_t *left, const wchar_t *right)
{
	if (left == NULL || right == NULL) return left == right;
	return wcscmp(left, right) == 0;
}

static int consistent_identity(const struct hid_device_info *left,
	const struct hid_device_info *right)
{
	/* Usage/page may differ for top-level collections on the same path. */
	return left->vendor_id == right->vendor_id
		&& left->product_id == right->product_id
		&& left->bus_type == right->bus_type
		&& left->release_number == right->release_number
		&& left->interface_number == right->interface_number
		&& same_wide_string(left->serial_number, right->serial_number)
		&& same_wide_string(left->manufacturer_string, right->manufacturer_string)
		&& same_wide_string(left->product_string, right->product_string);
}

static int native_select_unique(void *user, unsigned int *selected_count)
{
	native_state_t *state = user;
	struct hid_device_info *list, *info, *selected = NULL;
	unsigned int count = 0, entries = 0;
	int valid = 1;
	if (selected_count != NULL) *selected_count = 0;
	if (!enter(state)) return -1;
	if (selected_count == NULL || !state->initialized || !state->nonexclusive) {
		native_record(state, MLINK_ADMISSION_STAGE_SELECT,
			MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		return leave(state, -1);
	}
	if (state->select_attempted) {
		native_record(state, MLINK_ADMISSION_STAGE_SELECT,
			MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED, MLINK_ADMISSION_PARSER_NOT_RUN);
		return leave(state, -1);
	}
	if (native_cancelled_at(state, MLINK_ADMISSION_STAGE_SELECT)) return leave(state, -1);
	state->select_attempted = 1;
	list = hid_enumerate(state->config.vendor_id, state->config.product_id);
	for (info = list; info != NULL; info = info->next) {
		if (++entries > NATIVE_MAX_ENUM_ENTRIES) {
			valid = 0;
			native_record(state, MLINK_ADMISSION_STAGE_SELECT,
				MLINK_ADMISSION_REASON_ENTRY_LIMIT, MLINK_ADMISSION_PARSER_NOT_RUN);
			break;
		}
		if (!identity_matches(state, info)) continue;
		if (!path_valid(info->path)) {
			valid = 0;
			native_record(state, MLINK_ADMISSION_STAGE_SELECT,
				MLINK_ADMISSION_REASON_PATH_INVALID, MLINK_ADMISSION_PARSER_NOT_RUN);
			break;
		}
		if (selected == NULL) { selected = info; count = 1; }
		else if (strcmp(selected->path, info->path) != 0) {
			count = 2;
			native_record(state, MLINK_ADMISSION_STAGE_SELECT,
				MLINK_ADMISSION_REASON_SELECTION_AMBIGUOUS, MLINK_ADMISSION_PARSER_NOT_RUN);
			break;
		}
		else if (!consistent_identity(selected, info)) {
			valid = 0;
			native_record(state, MLINK_ADMISSION_STAGE_SELECT,
				MLINK_ADMISSION_REASON_IDENTITY_INCONSISTENT, MLINK_ADMISSION_PARSER_NOT_RUN);
			break;
		}
	}
	/* Detect a conflicting identity even if it appeared before the matching
	 * collection. Enumeration ownership is retained until both passes finish. */
	if (valid && count == 1) {
		entries = 0;
		for (info = list; info != NULL; info = info->next) {
			if (++entries > NATIVE_MAX_ENUM_ENTRIES) {
				valid = 0;
				native_record(state, MLINK_ADMISSION_STAGE_SELECT,
					MLINK_ADMISSION_REASON_ENTRY_LIMIT, MLINK_ADMISSION_PARSER_NOT_RUN);
				break;
			}
			if (path_valid(info->path) && strcmp(selected->path, info->path) == 0
			 && !consistent_identity(selected, info)) {
				valid = 0;
				native_record(state, MLINK_ADMISSION_STAGE_SELECT,
					MLINK_ADMISSION_REASON_IDENTITY_INCONSISTENT, MLINK_ADMISSION_PARSER_NOT_RUN);
				break;
			}
		}
	}
	if (valid && count == 1 && !native_cancelled_at(state, MLINK_ADMISSION_STAGE_SELECT)) {
		size_t length = strlen(selected->path) + 1;
		state->path = malloc(length);
		if (state->path == NULL) {
			valid = 0;
			native_record(state, MLINK_ADMISSION_STAGE_SELECT,
				MLINK_ADMISSION_REASON_ALLOCATION_FAILED, MLINK_ADMISSION_PARSER_NOT_RUN);
		}
		else memcpy(state->path, selected->path, length);
	} else {
		if (valid && count == 1) {
			/* Cancellation was recorded by native_cancelled_at above. */
			valid = 0;
		} else {
			valid = 0;
			if (state->admission_diagnostic.reason == MLINK_ADMISSION_REASON_NONE) {
				native_record(state, MLINK_ADMISSION_STAGE_SELECT,
					count > 1 ? MLINK_ADMISSION_REASON_SELECTION_AMBIGUOUS
						: MLINK_ADMISSION_REASON_SELECTION_ZERO,
					MLINK_ADMISSION_PARSER_NOT_RUN);
			}
		}
	}
	/* HIDAPI accepts NULL here too; no enumeration node escapes this scope. */
	hid_free_enumeration(list);
	*selected_count = valid ? count : (count > 1 ? count : 0);
	return leave(state, valid ? 0 : -1);
}

static int native_open_selected(void *user)
{
	native_state_t *state = user;
	if (!enter(state)) return -1;
	if (!state->initialized || !state->nonexclusive || state->path == NULL
	 || state->handle != NULL) {
		native_record(state, MLINK_ADMISSION_STAGE_OPEN,
			MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		return leave(state, -1);
	}
	if (state->open_attempted) {
		native_record(state, MLINK_ADMISSION_STAGE_OPEN,
			MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED, MLINK_ADMISSION_PARSER_NOT_RUN);
		return leave(state, -1);
	}
	if (native_cancelled_at(state, MLINK_ADMISSION_STAGE_OPEN)) {
		return leave(state, -1);
	}
	state->open_attempted = 1;
	state->handle = hid_open_path(state->path);
	if (state->handle == NULL) native_record(state, MLINK_ADMISSION_STAGE_OPEN,
		MLINK_ADMISSION_REASON_OPEN_NULL, MLINK_ADMISSION_PARSER_NOT_RUN);
	/* Once non-NULL, ownership must reach the core as success. Post-open
	 * checks belong to read_layout, where the core can close on failure. */
	return leave(state, state->handle != NULL ? 0 : -1);
}

static int native_read_layout(void *user, mlink_shared_layout_t *layout)
{
	native_state_t *state = user;
	unsigned char descriptor[MLINK_HID_DESC_MAX_BYTES + 1U];
	mlink_hid_desc_result_t parsed;
	int count;
	if (layout != NULL) memset(layout, 0, sizeof(*layout));
	if (!enter(state)) return -1;
	if (layout == NULL || state->handle == NULL || state->layout_attempted) {
		native_record(state, MLINK_ADMISSION_STAGE_LAYOUT,
			MLINK_ADMISSION_REASON_STATE, MLINK_ADMISSION_PARSER_NOT_RUN);
		return leave(state, -1);
	}
	if (native_cancelled_at(state, MLINK_ADMISSION_STAGE_LAYOUT)) return leave(state, -1);
	state->layout_attempted = 1;
	if (hid_darwin_is_device_open_exclusive(state->handle) != 0) {
		native_record(state, MLINK_ADMISSION_STAGE_LAYOUT,
			MLINK_ADMISSION_REASON_OPEN_EXCLUSIVE, MLINK_ADMISSION_PARSER_NOT_RUN);
		return leave(state, -1);
	}
	count = hid_get_report_descriptor(state->handle, descriptor, sizeof(descriptor));
	/* The mac backend silently clips to capacity. The extra byte distinguishes
	 * a full legal parser-domain descriptor from a clipped larger prefix. */
	if (count <= 0) {
		native_record(state, MLINK_ADMISSION_STAGE_LAYOUT,
			MLINK_ADMISSION_REASON_DESCRIPTOR_UNAVAILABLE, MLINK_ADMISSION_PARSER_NOT_RUN);
		return leave(state, -1);
	}
	if ((size_t)count > MLINK_HID_DESC_MAX_BYTES) {
		native_record(state, MLINK_ADMISSION_STAGE_LAYOUT,
			MLINK_ADMISSION_REASON_DESCRIPTOR_LIMIT, MLINK_ADMISSION_PARSER_NOT_RUN);
		return leave(state, -1);
	}
	if (native_cancelled_at(state, MLINK_ADMISSION_STAGE_LAYOUT)) return leave(state, -1);
	parsed.status = mlink_hid_desc_parse_checked(descriptor, (size_t)count, &parsed);
	if (parsed.status != MLINK_HID_DESC_OK) {
		mlink_admission_parser_status_t parser_status = MLINK_ADMISSION_PARSER_MALFORMED;
		switch (parsed.status) {
		case MLINK_HID_DESC_UNSUPPORTED: parser_status = MLINK_ADMISSION_PARSER_UNSUPPORTED; break;
		case MLINK_HID_DESC_LIMIT: parser_status = MLINK_ADMISSION_PARSER_LIMIT; break;
		case MLINK_HID_DESC_NO_TUNNEL: parser_status = MLINK_ADMISSION_PARSER_NO_TUNNEL; break;
		case MLINK_HID_DESC_AMBIGUOUS: parser_status = MLINK_ADMISSION_PARSER_AMBIGUOUS; break;
		case MLINK_HID_DESC_OK: parser_status = MLINK_ADMISSION_PARSER_OK; break;
		case MLINK_HID_DESC_MALFORMED:
		default: parser_status = MLINK_ADMISSION_PARSER_MALFORMED; break;
		}
		native_record(state, MLINK_ADMISSION_STAGE_LAYOUT,
			MLINK_ADMISSION_REASON_PARSER_REJECTED, parser_status);
		return leave(state, -1);
	}
	if (parsed.input_report_id == 0 || parsed.output_report_id == 0
	 || parsed.input_report_length != NATIVE_REPORT_BYTES
	 || parsed.output_report_length != NATIVE_REPORT_BYTES) {
		native_record(state, MLINK_ADMISSION_STAGE_LAYOUT,
			MLINK_ADMISSION_REASON_LAYOUT_INVALID, MLINK_ADMISSION_PARSER_OK);
		return leave(state, -1);
	}
	layout->selected_count = 1;
	layout->input_report_id = parsed.input_report_id;
	layout->output_report_id = parsed.output_report_id;
	layout->input_direction = MLINK_SHARED_INPUT;
	layout->output_direction = MLINK_SHARED_OUTPUT;
	layout->input_report_length = parsed.input_report_length;
	layout->output_report_length = parsed.output_report_length;
	state->layout_valid = 1;
	return leave(state, 0);
}

static ssize_t native_read_report(void *user, unsigned char *dst, size_t capacity,
	unsigned int timeout_ms)
{
	native_state_t *state = user;
	int count, timeout;
	if (!enter(state)) return -1;
	if (state->handle == NULL || !state->layout_valid || dst == NULL
	 || capacity == 0 || cancelled(state)) return leave(state, -1);
	if (capacity > INT_MAX) capacity = INT_MAX;
	timeout = timeout_ms > INT_MAX ? INT_MAX : (int)timeout_ms;
	count = hid_read_timeout(state->handle, dst, capacity, timeout);
	return leave(state, count > 0 && (size_t)count > capacity ? -1 : count);
}

static ssize_t native_write_report(void *user, const unsigned char *src, size_t length)
{
	native_state_t *state = user;
	int count;
	if (!enter(state)) return -1;
	if (state->handle == NULL || !state->layout_valid || src == NULL
	 || length == 0 || length > INT_MAX || cancelled(state)) return leave(state, -1);
	count = hid_write(state->handle, src, length);
	return leave(state, count > 0 && (size_t)count > length ? -1 : count);
}

static int native_close(void *user)
{
	native_state_t *state = user;
	if (!enter(state)) return -1;
	if (state->handle != NULL) {
		hid_close(state->handle);
		/* hid_close is void: normal return releases our ownership only; it
		 * does not provide an IOReturn status or a hard completion bound. */
		state->handle = NULL;
		state->layout_valid = 0;
	}
	return leave(state, 0);
}

static int native_stop(void *user)
{
	native_state_t *state = user;
	int rc;
	if (!enter(state)) return 1;
	rc = cancelled(state);
	return leave(state, rc);
}

static int native_clock(void *user, int64_t *now_ms)
{
	native_state_t *state = user;
	struct timespec now;
	if (!enter(state)) return -1;
	if (now_ms == NULL || clock_gettime(CLOCK_MONOTONIC, &now) != 0
	 || now.tv_sec < 0 || now.tv_nsec < 0 || now.tv_nsec >= 1000000000L
	 || (uintmax_t)now.tv_sec > (uintmax_t)INT64_MAX / 1000U
	 || (int64_t)now.tv_sec * 1000 > INT64_MAX - now.tv_nsec / 1000000L) {
		return leave(state, -1);
	}
	*now_ms = (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000L;
	return leave(state, 0);
}

static const mlink_shared_host_ops_t native_ops = {
	native_init, native_set_nonexclusive, native_select_unique, native_open_selected,
	native_read_layout, native_read_report, native_write_report, native_close,
	native_stop, native_clock, native_get_admission_diagnostic
};

int mlink_hidapi_native_create(const mlink_hidapi_native_config_t *config,
	mlink_hidapi_native_binding_t *binding)
{
	native_state_t *state;
	if (config == NULL || binding == NULL || binding->ops != NULL || binding->user != NULL
	 || owner != NULL || config->vendor_id == 0 || config->product_id == 0
	 || config->stop_requested == NULL) return -1;
	state = calloc(1, sizeof(*state));
	if (state == NULL) return -1;
	state->config = *config;
	owner = state;
	binding->ops = &native_ops;
	binding->user = state;
	return 0;
}

int mlink_hidapi_native_dispose(mlink_hidapi_native_binding_t *binding)
{
	native_state_t *state;
	if (binding == NULL || binding->ops != &native_ops || binding->user != owner
	 || owner == NULL) return -1;
	state = owner;
	if (state->handle != NULL || !enter(state)) return -1;
	if (state->initialized && hid_exit() != 0) return leave(state, -1);
	free(state->path);
	free(state);
	owner = NULL;
	binding->ops = NULL;
	binding->user = NULL;
	return 0;
}
