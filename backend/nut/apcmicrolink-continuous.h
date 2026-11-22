/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef APCMICROLINK_CONTINUOUS_H
#define APCMICROLINK_CONTINUOUS_H

#include <stddef.h>
#include <stdint.h>

#define MLINK_CONTINUOUS_FIELD_COUNT 17U
#define MLINK_CONTINUOUS_MAX_LINE 8192U
#define MLINK_CONTINUOUS_MAX_VALUE 32U

typedef enum {
	MLINK_CONTINUOUS_REPORTED,
	MLINK_CONTINUOUS_DRIVER_DERIVED,
	MLINK_CONTINUOUS_STATIC
} mlink_continuous_kind_t;

typedef enum {
	MLINK_CONTINUOUS_OBSERVED,
	MLINK_CONTINUOUS_UNAVAILABLE,
	MLINK_CONTINUOUS_INVALID
} mlink_continuous_state_t;

typedef struct {
	char value[129U];
	uint32_t observed_ms;
	mlink_continuous_kind_t kind;
	mlink_continuous_state_t state;
	int has_value;
	int has_time;
} mlink_continuous_field_t;

typedef struct {
	uint64_t received_ms;
	size_t copied_len;
	int received_valid;
	int copied_valid;
} mlink_continuous_page_t;

typedef enum {
	MLINK_CONTINUOUS_END_DURATION_COMPLETE,
	MLINK_CONTINUOUS_END_CANCELLED,
	MLINK_CONTINUOUS_END_DEVICE_LOST,
	MLINK_CONTINUOUS_END_SESSION_LOST,
	MLINK_CONTINUOUS_END_GUARD_ERROR,
	MLINK_CONTINUOUS_END_OUTPUT_ERROR
} mlink_continuous_end_reason_t;

void mlink_continuous_fields_clear(mlink_continuous_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT]);
int mlink_continuous_field_observed(mlink_continuous_field_t *field,
	mlink_continuous_kind_t kind, const char *value, uint32_t observed_ms);
void mlink_continuous_field_unavailable(mlink_continuous_field_t *field,
	mlink_continuous_kind_t kind);
void mlink_continuous_field_invalid(mlink_continuous_field_t *field,
	mlink_continuous_kind_t kind);
void mlink_continuous_field_mirror(mlink_continuous_field_t *destination,
	const mlink_continuous_field_t *source);
int mlink_continuous_number_valid(const char *value);
int mlink_continuous_status_valid(const char *value);
int mlink_continuous_page_dependency(const mlink_continuous_page_t *pages,
	size_t page_count, size_t width, size_t blob_len, size_t offset,
	size_t size, uint64_t *oldest_ms);
int mlink_continuous_definition_unchanged(const unsigned char *admitted,
	size_t admitted_len, const unsigned char *current, size_t current_len,
	size_t begin, size_t end);
int mlink_continuous_definition_range_valid(size_t data_ptr_offset,
	size_t parsed_end, size_t blob_len, size_t max_definition_len);
int mlink_continuous_sample_line(char *out, size_t out_size,
	uint32_t sequence, uint32_t slot, uint32_t elapsed_ms,
	uint32_t missed_slots,
	const mlink_continuous_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT]);
int mlink_continuous_end_line(char *out, size_t out_size,
	uint32_t elapsed_ms, mlink_continuous_end_reason_t reason);

#endif /* APCMICROLINK_CONTINUOUS_H */
