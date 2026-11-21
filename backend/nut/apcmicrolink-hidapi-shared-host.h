/* SPDX-License-Identifier: GPL-2.0-or-later
 * Fake-only host operations for the guarded Microlink transport seam.
 * No HIDAPI implementation is provided by this tranche.
 */
#ifndef APCMICROLINK_HIDAPI_SHARED_HOST_H
#define APCMICROLINK_HIDAPI_SHARED_HOST_H

#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

enum mlink_shared_direction {
	MLINK_SHARED_INPUT = 1,
	MLINK_SHARED_OUTPUT = 2
};

typedef struct mlink_shared_layout {
	unsigned int selected_count;
	unsigned int input_report_id;
	unsigned int output_report_id;
	unsigned int input_direction;
	unsigned int output_direction;
	size_t input_report_length;
	size_t output_report_length;
} mlink_shared_layout_t;

/* Closed diagnostic vocabulary. Values cross the host seam by copy only;
 * they must never contain device, descriptor, path or platform strings. */
typedef enum mlink_admission_stage {
	MLINK_ADMISSION_STAGE_NONE = 0,
	MLINK_ADMISSION_STAGE_PREPARE,
	MLINK_ADMISSION_STAGE_GUARD,
	MLINK_ADMISSION_STAGE_INIT,
	MLINK_ADMISSION_STAGE_NONEXCLUSIVE,
	MLINK_ADMISSION_STAGE_SELECT,
	MLINK_ADMISSION_STAGE_OPEN,
	MLINK_ADMISSION_STAGE_LAYOUT
} mlink_admission_stage_t;

typedef enum mlink_admission_reason {
	MLINK_ADMISSION_REASON_NONE = 0,
	MLINK_ADMISSION_REASON_STATE,
	MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED,
	MLINK_ADMISSION_REASON_INVALID_CONFIG,
	MLINK_ADMISSION_REASON_CALLBACK_MISSING,
	MLINK_ADMISSION_REASON_HOST_FAILED,
	MLINK_ADMISSION_REASON_STOP,
	MLINK_ADMISSION_REASON_CLOCK_FAILED,
	MLINK_ADMISSION_REASON_CLOCK_REGRESSION,
	MLINK_ADMISSION_REASON_DEADLINE,
	MLINK_ADMISSION_REASON_INVALID_GUARD,
	MLINK_ADMISSION_REASON_SELECTION_ZERO,
	MLINK_ADMISSION_REASON_SELECTION_AMBIGUOUS,
	MLINK_ADMISSION_REASON_PATH_INVALID,
	MLINK_ADMISSION_REASON_IDENTITY_INCONSISTENT,
	MLINK_ADMISSION_REASON_ENTRY_LIMIT,
	MLINK_ADMISSION_REASON_ALLOCATION_FAILED,
	MLINK_ADMISSION_REASON_OPEN_NULL,
	MLINK_ADMISSION_REASON_OPEN_EXCLUSIVE,
	MLINK_ADMISSION_REASON_DESCRIPTOR_UNAVAILABLE,
	MLINK_ADMISSION_REASON_DESCRIPTOR_LIMIT,
	MLINK_ADMISSION_REASON_PARSER_REJECTED,
	MLINK_ADMISSION_REASON_LAYOUT_INVALID,
	MLINK_ADMISSION_REASON_CANCELLED
} mlink_admission_reason_t;

typedef enum mlink_admission_parser_status {
	MLINK_ADMISSION_PARSER_NOT_RUN = 0,
	MLINK_ADMISSION_PARSER_OK,
	MLINK_ADMISSION_PARSER_MALFORMED,
	MLINK_ADMISSION_PARSER_UNSUPPORTED,
	MLINK_ADMISSION_PARSER_LIMIT,
	MLINK_ADMISSION_PARSER_NO_TUNNEL,
	MLINK_ADMISSION_PARSER_AMBIGUOUS
} mlink_admission_parser_status_t;

typedef struct mlink_admission_diagnostic {
	mlink_admission_stage_t stage;
	mlink_admission_reason_t reason;
	mlink_admission_parser_status_t parser_status;
} mlink_admission_diagnostic_t;

static inline const char *mlink_admission_stage_token(mlink_admission_stage_t value)
{
	switch (value) {
	case MLINK_ADMISSION_STAGE_NONE: return "none";
	case MLINK_ADMISSION_STAGE_PREPARE: return "prepare";
	case MLINK_ADMISSION_STAGE_GUARD: return "guard";
	case MLINK_ADMISSION_STAGE_INIT: return "init";
	case MLINK_ADMISSION_STAGE_NONEXCLUSIVE: return "nonexclusive";
	case MLINK_ADMISSION_STAGE_SELECT: return "select";
	case MLINK_ADMISSION_STAGE_OPEN: return "open";
	case MLINK_ADMISSION_STAGE_LAYOUT: return "layout";
	default: return "unknown";
	}
}

static inline const char *mlink_admission_reason_token(mlink_admission_reason_t value)
{
	switch (value) {
	case MLINK_ADMISSION_REASON_NONE: return "none";
	case MLINK_ADMISSION_REASON_STATE: return "state";
	case MLINK_ADMISSION_REASON_ATTEMPT_CONSUMED: return "attempt-consumed";
	case MLINK_ADMISSION_REASON_INVALID_CONFIG: return "invalid-config";
	case MLINK_ADMISSION_REASON_CALLBACK_MISSING: return "callback-missing";
	case MLINK_ADMISSION_REASON_HOST_FAILED: return "host-failed";
	case MLINK_ADMISSION_REASON_STOP: return "stop";
	case MLINK_ADMISSION_REASON_CLOCK_FAILED: return "clock-failed";
	case MLINK_ADMISSION_REASON_CLOCK_REGRESSION: return "clock-regression";
	case MLINK_ADMISSION_REASON_DEADLINE: return "deadline";
	case MLINK_ADMISSION_REASON_INVALID_GUARD: return "invalid-guard";
	case MLINK_ADMISSION_REASON_SELECTION_ZERO: return "selection-zero";
	case MLINK_ADMISSION_REASON_SELECTION_AMBIGUOUS: return "selection-ambiguous";
	case MLINK_ADMISSION_REASON_PATH_INVALID: return "path-invalid";
	case MLINK_ADMISSION_REASON_IDENTITY_INCONSISTENT: return "identity-inconsistent";
	case MLINK_ADMISSION_REASON_ENTRY_LIMIT: return "entry-limit";
	case MLINK_ADMISSION_REASON_ALLOCATION_FAILED: return "allocation-failed";
	case MLINK_ADMISSION_REASON_OPEN_NULL: return "open-null";
	case MLINK_ADMISSION_REASON_OPEN_EXCLUSIVE: return "open-exclusive";
	case MLINK_ADMISSION_REASON_DESCRIPTOR_UNAVAILABLE: return "descriptor-unavailable";
	case MLINK_ADMISSION_REASON_DESCRIPTOR_LIMIT: return "descriptor-limit";
	case MLINK_ADMISSION_REASON_PARSER_REJECTED: return "parser-rejected";
	case MLINK_ADMISSION_REASON_LAYOUT_INVALID: return "layout-invalid";
	case MLINK_ADMISSION_REASON_CANCELLED: return "cancelled";
	default: return "unknown";
	}
}

static inline const char *mlink_admission_parser_token(mlink_admission_parser_status_t value)
{
	switch (value) {
	case MLINK_ADMISSION_PARSER_NOT_RUN: return "not-run";
	case MLINK_ADMISSION_PARSER_OK: return "ok";
	case MLINK_ADMISSION_PARSER_MALFORMED: return "malformed";
	case MLINK_ADMISSION_PARSER_UNSUPPORTED: return "unsupported";
	case MLINK_ADMISSION_PARSER_LIMIT: return "limit";
	case MLINK_ADMISSION_PARSER_NO_TUNNEL: return "no-tunnel";
	case MLINK_ADMISSION_PARSER_AMBIGUOUS: return "ambiguous";
	default: return "unknown";
	}
}

/* Pure value snapshot. Available before binding and after finish. */
mlink_admission_diagnostic_t mlink_shared_admission_diagnostic(void);

typedef struct mlink_shared_host_ops {
	/* select_unique resolves identity only; layout is read from the opened handle. */
	int (*init)(void *user);
	int (*set_nonexclusive)(void *user);
	int (*select_unique)(void *user, unsigned int *selected_count);
	int (*open_selected)(void *user);
	int (*read_layout)(void *user, mlink_shared_layout_t *layout);
	/* Reads are capped by a finite timeout; writes and close may still block at
	 * the OS API boundary and require an external process supervisor. */
	ssize_t (*read_report)(void *user, unsigned char *dst, size_t capacity,
		unsigned int timeout_ms);
	ssize_t (*write_report)(void *user, const unsigned char *src, size_t length);
	int (*close)(void *user);
	int (*stop_requested)(void *user);
	int (*monotonic_ms)(void *user, int64_t *now_ms);
	/* Optional, pure local-memory snapshot. Legacy fake hosts may leave NULL. */
	mlink_admission_diagnostic_t (*get_admission_diagnostic)(void *user);
} mlink_shared_host_ops_t;

#ifdef MLINK_HIDAPI_SHARED_TEST
int mlink_shared_test_bind(const mlink_shared_host_ops_t *ops, void *user);
void mlink_shared_test_unbind(void);
#endif

#endif
